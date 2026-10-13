// SPDX-License-Identifier: BSD-3-Clause
/*
 * pal_nvme: NVMe DMA into a CUDA allocation mapped through iommufd PAL.
 *
 * A minimal NVMe driver on a VFIO cdev device bound to iommufd. Host memory
 * for the queues and a staging buffer is mapped with IOMMU_IOAS_MAP, the
 * CUDA allocation with IOMMU_IOAS_MAP_FILE on its dma-buf (the PAL path).
 *
 *   C1  host pattern -> NVMe write (LBA 0) -> NVMe read into the GPU IOVA
 *       -> cuMemcpyDtoH -> compare
 *   C2  cuMemcpyHtoD pattern -> NVMe write from the GPU IOVA (LBA 0)
 *       -> NVMe read into host -> compare
 *   D   NVMe read into an IOVA that is not mapped -> expect a command error
 *       (and a DMAR fault in dmesg)
 *
 * The write goes to LBA 0 of the spare NVMe, as the team's earlier tests did.
 *
 * Build: gcc -O2 -Wall -I/data/linux-pal/usr/include -I/usr/local/cuda/include
 *            -o pal_nvme pal_nvme.c -lcuda
 */
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#include <linux/iommufd.h>
#include <linux/vfio.h>

#include <cuda.h>

#include "dmabuf_import.h"

#define PAGE 4096ULL
#define HOST_MEM (2ULL << 20)
#define AQ_DEPTH 32
#define IOQ_DEPTH 64
static uint64_t XFER = 64ULL << 10;
static uint64_t SLBA_BASE;   /* --slba: first LBA the test may overwrite */   /* bytes per I/O, --xfer; >8 KiB uses a PRP list */

/* host memory layout (offsets into the 2 MiB block) */
#define OFF_ASQ   0
#define OFF_ACQ   (4 * PAGE)
#define OFF_IOSQ  (8 * PAGE)
#define OFF_IOCQ  (12 * PAGE)
#define OFF_ID    (16 * PAGE)
#define OFF_PRPL  (17 * PAGE)
#define OFF_DATA  (32 * PAGE)   /* 64 KiB staging buffer */
#define OFF_DATA2 (64 * PAGE)   /* 64 KiB second staging buffer */

struct nvme_cmd {
	uint8_t opc, fuse;
	uint16_t cid;
	uint32_t nsid;
	uint64_t rsvd;
	uint64_t mptr;
	uint64_t prp1, prp2;
	uint32_t cdw10, cdw11, cdw12, cdw13, cdw14, cdw15;
};

struct nvme_cpl {
	uint32_t dw0, dw1;
	uint16_t sqhd, sqid;
	uint16_t cid;
	uint16_t status;
};

struct queue {
	struct nvme_cmd *sq;
	struct nvme_cpl *cq;
	volatile uint32_t *sq_db, *cq_db;
	uint16_t depth, sq_tail, cq_head, cid;
	uint8_t phase;
};

struct ctx {
	int iommufd, vfio_fd, dmabuf_fd;
	uint32_t ioas_id;
	volatile uint8_t *bar0;
	size_t bar0_len;
	uint32_t dstrd;
	uint8_t *hm;
	uint64_t hm_iova;
	CUdeviceptr gpu;
	size_t gpu_size;
	uint64_t gpu_iova;
	uint32_t lba_size;
	int identity;
	const char *uio_bdf;
	uint64_t gpu_pa;
	struct queue aq, ioq;
	int timeout_ms;
};

static const char *cu_err(CUresult r)
{
	const char *s = "?";
	cuGetErrorString(r, &s);
	return s;
}

#define CU_CHECK(call)                                                       \
	do {                                                                 \
		CUresult _r = (call);                                        \
		if (_r != CUDA_SUCCESS) {                                    \
			fprintf(stderr, "%s failed: %s\n", #call, cu_err(_r)); \
			return -1;                                           \
		}                                                            \
	} while (0)

#define IOCTL(fd, req, arg)                                                   \
	({                                                                    \
		int _rc = ioctl(fd, req, arg);                                \
		if (_rc < 0)                                                  \
			fprintf(stderr, "%s failed: %s\n", #req, strerror(errno)); \
		_rc;                                                          \
	})

static uint32_t rd32(struct ctx *c, size_t off)
{
	return *(volatile uint32_t *)(c->bar0 + off);
}

static void wr32(struct ctx *c, size_t off, uint32_t v)
{
	*(volatile uint32_t *)(c->bar0 + off) = v;
}

static void wr64(struct ctx *c, size_t off, uint64_t v)
{
	wr32(c, off, (uint32_t)v);
	wr32(c, off + 4, (uint32_t)(v >> 32));
}

static int64_t now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1000LL + ts.tv_nsec / 1000000;
}

static int wait_csts_rdy(struct ctx *c, int want)
{
	int64_t t0 = now_ms();

	while ((rd32(c, 0x1c) & 1) != (uint32_t)want) {
		if (rd32(c, 0x1c) & 2) {
			fprintf(stderr, "CSTS.CFS set\n");
			return -1;
		}
		if (now_ms() - t0 > c->timeout_ms) {
			fprintf(stderr, "timeout waiting CSTS.RDY=%d\n", want);
			return -1;
		}
		usleep(1000);
	}
	return 0;
}

static void queue_init(struct ctx *c, struct queue *q, int qid, uint8_t *sq,
		       uint8_t *cq, uint16_t depth)
{
	memset(q, 0, sizeof(*q));
	q->sq = (struct nvme_cmd *)sq;
	q->cq = (struct nvme_cpl *)cq;
	memset(sq, 0, depth * sizeof(struct nvme_cmd));
	memset(cq, 0, depth * sizeof(struct nvme_cpl));
	q->depth = depth;
	q->phase = 1;
	q->sq_db = (volatile uint32_t *)(c->bar0 + 0x1000 + (2 * qid) * (4 << c->dstrd));
	q->cq_db = (volatile uint32_t *)(c->bar0 + 0x1000 + (2 * qid + 1) * (4 << c->dstrd));
}

/* Submit one command and wait for its completion. Returns the status field
 * (0 on success, >0 NVMe status, <0 on timeout). */
static int submit_sync(struct ctx *c, struct queue *q, struct nvme_cmd *cmd,
		       struct nvme_cpl *out)
{
	int64_t t0 = now_ms();

	cmd->cid = q->cid++;
	q->sq[q->sq_tail] = *cmd;
	__sync_synchronize();
	q->sq_tail = (q->sq_tail + 1) % q->depth;
	*q->sq_db = q->sq_tail;

	for (;;) {
		volatile struct nvme_cpl *cpl = &q->cq[q->cq_head];

		if ((cpl->status & 1) == q->phase) {
			struct nvme_cpl got = *(struct nvme_cpl *)cpl;

			q->cq_head = (q->cq_head + 1) % q->depth;
			if (q->cq_head == 0)
				q->phase ^= 1;
			*q->cq_db = q->cq_head;
			if (out)
				*out = got;
			if (got.cid != cmd->cid)
				fprintf(stderr, "cid mismatch %u != %u\n", got.cid, cmd->cid);
			return got.status >> 1;
		}
		if (now_ms() - t0 > c->timeout_ms)
			return -ETIMEDOUT;
	}
}

static int map_host(struct ctx *c)
{
	c->hm = mmap(NULL, HOST_MEM, PROT_READ | PROT_WRITE,
		     MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);
	if (c->hm == MAP_FAILED) {
		perror("mmap host");
		return -1;
	}
	memset(c->hm, 0, HOST_MEM);

	struct iommu_ioas_map m = {
		.size = sizeof(m),
		.flags = IOMMU_IOAS_MAP_READABLE | IOMMU_IOAS_MAP_WRITEABLE,
		.ioas_id = c->ioas_id,
		.user_va = (uintptr_t)c->hm,
		.length = HOST_MEM,
	};
	if (IOCTL(c->iommufd, IOMMU_IOAS_MAP, &m))
		return -1;
	c->hm_iova = m.iova;
	printf("host: %llu KiB mapped at iova 0x%llx\n", HOST_MEM >> 10,
	       (unsigned long long)c->hm_iova);
	return 0;
}

/* BAR1 physical address of the start of the CUDA buffer, through the team's
 * dmabuf_import misc importer (no IOMMU domain, so dma_addr == phys). */
static int gpu_phys_addr(struct ctx *c)
{
	int fd = open(DMABUF_IMPORT_DEVPATH, O_RDWR);
	if (fd < 0) {
		perror("open " DMABUF_IMPORT_DEVPATH);
		return -1;
	}
	struct dmabuf_import_attach_bdf at = { .fd = c->dmabuf_fd, .bdf = "" };
	if (IOCTL(fd, DMABUF_IMPORT_ATTACH_BDF, &at))
		return -1;
	struct dmabuf_import_info info = { .fd = c->dmabuf_fd };
	if (IOCTL(fd, DMABUF_IMPORT_GET_INFO, &info))
		return -1;
	size_t sz = sizeof(struct dmabuf_import_get_map) + info.count * sizeof(struct dmabuf_import_dma_map);
	struct dmabuf_import_get_map *gm = calloc(1, sz);
	gm->fd = c->dmabuf_fd;
	gm->count = info.count;
	if (IOCTL(fd, DMABUF_IMPORT_GET_MAP, gm))
		return -1;
	uint64_t pa = gm->dma_arr[0].dma_addr;
	uint64_t contig = 0;
	for (uint32_t i = 0; i < gm->count; i++) {
		if (gm->dma_arr[i].dma_addr != pa + contig)
			break;
		contig += gm->dma_arr[i].dma_len;
	}
	printf("dmabuf_import: %u entries, first pa 0x%llx, contiguous %llu MiB\n", gm->count,
	       (unsigned long long)pa, (unsigned long long)(contig >> 20));
	int dfd = c->dmabuf_fd;
	IOCTL(fd, DMABUF_IMPORT_DETACH, &dfd);
	close(fd);
	free(gm);
	c->gpu_pa = pa;
	return contig >= c->gpu_size ? 0 : -1;
}

static int map_gpu(struct ctx *c)
{
	if (c->identity && gpu_phys_addr(c))
		return -1;
	struct iommu_ioas_map_file m = {
		.size = sizeof(m),
		.flags = IOMMU_IOAS_MAP_READABLE | IOMMU_IOAS_MAP_WRITEABLE,
		.ioas_id = c->ioas_id,
		.fd = c->dmabuf_fd,
		.start = 0,
		.length = c->gpu_size,
	};
	if (c->identity) {
		m.flags |= IOMMU_IOAS_MAP_FIXED_IOVA;
		m.iova = c->gpu_pa;
	}
	if (IOCTL(c->iommufd, IOMMU_IOAS_MAP_FILE, &m))
		return -1;
	c->gpu_iova = m.iova;
	printf("gpu: dma-buf fd %d (%zu MiB) mapped at iova 0x%llx\n", c->dmabuf_fd,
	       c->gpu_size >> 20, (unsigned long long)c->gpu_iova);
	return 0;
}

static int vfio_setup(struct ctx *c, const char *path)
{
	c->vfio_fd = open(path, O_RDWR);
	if (c->vfio_fd < 0) {
		fprintf(stderr, "open %s: %s\n", path, strerror(errno));
		return -1;
	}
	struct vfio_device_bind_iommufd bind = { .argsz = sizeof(bind), .iommufd = c->iommufd };
	if (IOCTL(c->vfio_fd, VFIO_DEVICE_BIND_IOMMUFD, &bind))
		return -1;
	struct iommu_hwpt_alloc hwpt = { .size = sizeof(hwpt), .dev_id = bind.out_devid,
					 .pt_id = c->ioas_id };
	if (IOCTL(c->iommufd, IOMMU_HWPT_ALLOC, &hwpt))
		return -1;
	struct vfio_device_attach_iommufd_pt at = { .argsz = sizeof(at), .pt_id = hwpt.out_hwpt_id };
	if (IOCTL(c->vfio_fd, VFIO_DEVICE_ATTACH_IOMMUFD_PT, &at))
		return -1;

	/* BAR0 */
	struct vfio_region_info ri = { .argsz = sizeof(ri), .index = VFIO_PCI_BAR0_REGION_INDEX };
	if (IOCTL(c->vfio_fd, VFIO_DEVICE_GET_REGION_INFO, &ri))
		return -1;
	c->bar0_len = ri.size;
	c->bar0 = mmap(NULL, ri.size, PROT_READ | PROT_WRITE, MAP_SHARED, c->vfio_fd, ri.offset);
	if (c->bar0 == MAP_FAILED) {
		perror("mmap bar0");
		return -1;
	}

	/* bus master + memory space in the config header */
	struct vfio_region_info ci = { .argsz = sizeof(ci), .index = VFIO_PCI_CONFIG_REGION_INDEX };
	if (IOCTL(c->vfio_fd, VFIO_DEVICE_GET_REGION_INFO, &ci))
		return -1;
	uint16_t command;
	if (pread(c->vfio_fd, &command, 2, ci.offset + 4) != 2) {
		perror("pread command");
		return -1;
	}
	command |= 0x6;
	if (pwrite(c->vfio_fd, &command, 2, ci.offset + 4) != 2) {
		perror("pwrite command");
		return -1;
	}
	printf("vfio: %s devid=%u hwpt=%u bar0=%zu KiB\n", path, bind.out_devid,
	       hwpt.out_hwpt_id, c->bar0_len >> 10);
	return 0;
}

/* Untranslated mode: BAR0 from sysfs, host memory on a 2 MiB hugepage with
 * its physical address from pagemap, GPU at its BAR1 physical address. The
 * NVMe must be in an identity IOMMU domain (or the IOMMU off). Needs root. */
static int uio_setup(struct ctx *c)
{
	char path[128];

	snprintf(path, sizeof(path), "/sys/bus/pci/devices/%s/resource0", c->uio_bdf);
	int fd = open(path, O_RDWR | O_SYNC);
	if (fd < 0) {
		perror(path);
		return -1;
	}
	c->bar0_len = 16384;
	c->bar0 = mmap(NULL, c->bar0_len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (c->bar0 == MAP_FAILED) {
		perror("mmap resource0");
		return -1;
	}
	c->hm = mmap(NULL, HOST_MEM, PROT_READ | PROT_WRITE,
		     MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB | MAP_POPULATE, -1, 0);
	if (c->hm == MAP_FAILED) {
		perror("mmap hugepage");
		return -1;
	}
	memset(c->hm, 0, HOST_MEM);
	int pm = open("/proc/self/pagemap", O_RDONLY);
	uint64_t ent;
	if (pm < 0 || pread(pm, &ent, 8, ((uintptr_t)c->hm / PAGE) * 8) != 8 || !(ent >> 63)) {
		perror("pagemap");
		return -1;
	}
	close(pm);
	c->hm_iova = (ent & ((1ULL << 55) - 1)) * PAGE;
	if (gpu_phys_addr(c))
		return -1;
	c->gpu_iova = c->gpu_pa;
	printf("uio: %s bar0 via sysfs, host pa 0x%llx, gpu pa 0x%llx (no translation)\n",
	       c->uio_bdf, (unsigned long long)c->hm_iova, (unsigned long long)c->gpu_iova);
	return 0;
}

static int ctrl_init(struct ctx *c)
{
	uint64_t cap = rd32(c, 0x0) | ((uint64_t)rd32(c, 0x4) << 32);
	uint32_t mqes = (cap & 0xffff) + 1;
	uint32_t to = ((cap >> 24) & 0xff) * 500;

	c->dstrd = (cap >> 32) & 0xf;
	c->timeout_ms = to > 5000 ? to : 5000;
	printf("nvme: CAP mqes=%u dstrd=%u timeout=%u ms VS=0x%x\n", mqes, c->dstrd,
	       c->timeout_ms, rd32(c, 0x8));

	wr32(c, 0x14, rd32(c, 0x14) & ~1u);     /* CC.EN = 0 */
	if (wait_csts_rdy(c, 0))
		return -1;

	queue_init(c, &c->aq, 0, c->hm + OFF_ASQ, c->hm + OFF_ACQ, AQ_DEPTH);
	wr32(c, 0x24, ((AQ_DEPTH - 1) << 16) | (AQ_DEPTH - 1));
	wr64(c, 0x28, c->hm_iova + OFF_ASQ);
	wr64(c, 0x30, c->hm_iova + OFF_ACQ);
	/* IOSQES=6 IOCQES=4 MPS=0 (4 KiB) CSS=0 EN=1 */
	wr32(c, 0x14, (6 << 20) | (4 << 16) | 1);
	if (wait_csts_rdy(c, 1))
		return -1;
	printf("nvme: controller enabled\n");

	/* Identify Namespace 1 -> LBA size */
	struct nvme_cmd cmd = { .opc = 0x06, .nsid = 1, .prp1 = c->hm_iova + OFF_ID, .cdw10 = 0 };
	int st = submit_sync(c, &c->aq, &cmd, NULL);
	if (st) {
		fprintf(stderr, "identify ns failed: status 0x%x\n", st);
		return -1;
	}
	uint8_t *id = c->hm + OFF_ID;
	uint8_t flbas = id[26] & 0xf;
	uint8_t lbads = id[128 + 4 * flbas + 2];
	uint64_t nsze = *(uint64_t *)&id[0];
	c->lba_size = 1u << lbads;
	printf("nvme: ns1 lba_size=%u nsze=%llu\n", c->lba_size, (unsigned long long)nsze);
	if (c->lba_size > PAGE || XFER % c->lba_size) {
		fprintf(stderr, "unsupported LBA size\n");
		return -1;
	}

	/* IO CQ 1 then IO SQ 1 */
	queue_init(c, &c->ioq, 1, c->hm + OFF_IOSQ, c->hm + OFF_IOCQ, IOQ_DEPTH);
	struct nvme_cmd ccq = { .opc = 0x05, .prp1 = c->hm_iova + OFF_IOCQ,
				.cdw10 = ((IOQ_DEPTH - 1) << 16) | 1, .cdw11 = 1 };
	st = submit_sync(c, &c->aq, &ccq, NULL);
	if (st) {
		fprintf(stderr, "create io cq failed: 0x%x\n", st);
		return -1;
	}
	struct nvme_cmd csq = { .opc = 0x01, .prp1 = c->hm_iova + OFF_IOSQ,
				.cdw10 = ((IOQ_DEPTH - 1) << 16) | 1, .cdw11 = (1 << 16) | 1 };
	st = submit_sync(c, &c->aq, &csq, NULL);
	if (st) {
		fprintf(stderr, "create io sq failed: 0x%x\n", st);
		return -1;
	}
	printf("nvme: io queue pair 1 created (depth %d)\n", IOQ_DEPTH);
	return 0;
}

/* Build PRP1/PRP2 for a contiguous IOVA range of XFER bytes. */
static void set_prps(struct ctx *c, struct nvme_cmd *cmd, uint64_t iova)
{
	uint64_t *list = (uint64_t *)(c->hm + OFF_PRPL);
	unsigned int npages = XFER / PAGE;

	cmd->prp1 = iova;
	if (npages == 1) {
		cmd->prp2 = 0;
	} else if (npages == 2) {
		cmd->prp2 = iova + PAGE;
	} else {
		for (unsigned int i = 1; i < npages; i++)
			list[i - 1] = iova + i * PAGE;
		cmd->prp2 = c->hm_iova + OFF_PRPL;
	}
}

static int nvme_rw(struct ctx *c, uint8_t opc, uint64_t slba, uint64_t iova, const char *what)
{
	slba += SLBA_BASE;
	struct nvme_cmd cmd = { .opc = opc, .nsid = 1, .cdw10 = (uint32_t)slba,
				.cdw11 = (uint32_t)(slba >> 32),
				.cdw12 = XFER / c->lba_size - 1 };
	struct nvme_cpl cpl;

	set_prps(c, &cmd, iova);
	int st = submit_sync(c, &c->ioq, &cmd, &cpl);
	if (st < 0)
		printf("%s: TIMEOUT\n", what);
	else if (st)
		printf("%s: status sct=0x%x sc=0x%x\n", what, (st >> 8) & 7, st & 0xff);
	else
		printf("%s: OK\n", what);
	return st;
}

static void fill(uint8_t *p, size_t n, uint32_t seed)
{
	uint32_t x = seed ? seed : 1;

	for (size_t i = 0; i < n; i++) {
		x ^= x << 13; x ^= x >> 17; x ^= x << 5;
		p[i] = (uint8_t)x;
	}
}

int main(int argc, char **argv)
{
	struct ctx c = { .gpu_size = 1ULL << 30, .timeout_ms = 5000 };
	const char *vfio_path = "/dev/vfio/devices/vfio0";
	int do_negative = 1;
	int c_opt;
	static const struct option opts[] = {
		{ "size", required_argument, NULL, 's' },
		{ "vfio", required_argument, NULL, 'v' },
		{ "no-negative", no_argument, NULL, 'n' },
		{ "xfer", required_argument, NULL, 'x' },
		{ "identity", no_argument, NULL, 'i' },
		{ "uio", required_argument, NULL, 'u' },
		{ "slba", required_argument, NULL, 'l' },
		{ 0 }
	};

	while ((c_opt = getopt_long(argc, argv, "s:v:nx:iu:l:", opts, NULL)) != -1) {
		switch (c_opt) {
		case 'i': c.identity = 1; break;
		case 'u': c.uio_bdf = optarg; break;
		case 'l': SLBA_BASE = strtoull(optarg, NULL, 0); break;
		case 's': c.gpu_size = strtoull(optarg, NULL, 0); break;
		case 'x': XFER = strtoull(optarg, NULL, 0); break;
		case 'v': vfio_path = optarg; break;
		case 'n': do_negative = 0; break;
		default: return 2;
		}
	}

	/* CUDA allocation and its dma-buf */
	CUdevice dev;
	CUcontext cuctx;

	CU_CHECK(cuInit(0));
	CU_CHECK(cuDeviceGet(&dev, 0));
	CU_CHECK(cuCtxCreate(&cuctx, 0, dev));
	CU_CHECK(cuMemAlloc(&c.gpu, c.gpu_size));
	CU_CHECK(cuMemGetHandleForAddressRange(&c.dmabuf_fd, c.gpu, c.gpu_size,
					       CU_MEM_RANGE_HANDLE_TYPE_DMA_BUF_FD, 0));
	CU_CHECK(cuMemsetD8(c.gpu, 0, c.gpu_size));

	if (c.uio_bdf) {
		if (uio_setup(&c))
			return 1;
		goto ctrl;
	}

	/* iommufd, IOAS, device, mappings */
	c.iommufd = open("/dev/iommu", O_RDWR);
	if (c.iommufd < 0) {
		perror("open /dev/iommu");
		return 1;
	}
	struct iommu_ioas_alloc ia = { .size = sizeof(ia) };
	if (IOCTL(c.iommufd, IOMMU_IOAS_ALLOC, &ia))
		return 1;
	c.ioas_id = ia.out_ioas_id;
	if (vfio_setup(&c, vfio_path) || map_host(&c) || map_gpu(&c))
		return 1;
ctrl:
	if (ctrl_init(&c))
		return 1;

	printf("test LBAs: %llu .. %llu (overwritten)\n", (unsigned long long)SLBA_BASE,
	       (unsigned long long)(SLBA_BASE + 3 * XFER / c.lba_size - 1));
	int failures = 0;
	uint8_t *host = c.hm + OFF_DATA;
	uint8_t *host2 = c.hm + OFF_DATA2;
	uint8_t *cmp = malloc(XFER);

	/* C1: host -> NVMe -> GPU -> host, compare */
	fill(host, XFER, 0xC1);
	if (nvme_rw(&c, 0x01, 0, c.hm_iova + OFF_DATA, "C1 write LBA0 from host"))
		failures++;
	if (nvme_rw(&c, 0x02, 0, c.gpu_iova, "C1 read LBA0 into GPU iova"))
		failures++;
	CU_CHECK(cuMemcpyDtoH(cmp, c.gpu, XFER));
	if (memcmp(cmp, host, XFER) == 0)
		printf("C1 compare: MATCH (%llu bytes)\n", (unsigned long long)XFER);
	else {
		size_t i;
		for (i = 0; i < XFER && cmp[i] == host[i]; i++)
			;
		printf("C1 compare: MISMATCH at byte %zu (got 0x%02x want 0x%02x)\n", i, cmp[i], host[i]);
		failures++;
	}

	/* C2: host pattern -> GPU (cuMemcpy) -> NVMe write from GPU -> NVMe read into host2 */
	fill(host2, XFER, 0xC2);
	CU_CHECK(cuMemcpyHtoD(c.gpu + XFER, host2, XFER));
	if (nvme_rw(&c, 0x01, XFER / c.lba_size, c.gpu_iova + XFER, "C2 write LBA16 from GPU iova"))
		failures++;
	memset(host, 0, XFER);
	if (nvme_rw(&c, 0x02, XFER / c.lba_size, c.hm_iova + OFF_DATA, "C2 read LBA16 into host"))
		failures++;
	if (memcmp(host, host2, XFER) == 0)
		printf("C2 compare: MATCH (%llu bytes)\n", (unsigned long long)XFER);
	else {
		printf("C2 compare: MISMATCH\n");
		failures++;
	}

	/* D: read into an IOVA with no mapping (just past the GPU range + 1 GiB) */
	if (do_negative && !c.uio_bdf) {
		uint64_t bad = c.gpu_iova + c.gpu_size + (1ULL << 30);
		int st = nvme_rw(&c, 0x01, 2 * XFER / c.lba_size, bad,
				 "D write LBA from unmapped iova (device read)");

		printf("D expectation: an error status or timeout, not OK (iova 0x%llx)\n",
		       (unsigned long long)bad);
		if (st == 0)
			failures++;
		/* device write to an unmapped IOVA is posted: no error, only a DMAR fault in dmesg */
		nvme_rw(&c, 0x02, 0, bad, "D2 read LBA0 into unmapped iova (device write, posted)");
	}

	/* teardown */
	wr32(&c, 0x14, rd32(&c, 0x14) & ~1u);
	wait_csts_rdy(&c, 0);
	if (c.uio_bdf)
		goto done;
	struct iommu_ioas_unmap u = { .size = sizeof(u), .ioas_id = c.ioas_id,
				      .iova = c.gpu_iova, .length = c.gpu_size };
	IOCTL(c.iommufd, IOMMU_IOAS_UNMAP, &u);
	u.iova = c.hm_iova; u.length = HOST_MEM;
	IOCTL(c.iommufd, IOMMU_IOAS_UNMAP, &u);
	close(c.vfio_fd);
	close(c.iommufd);
done:
	close(c.dmabuf_fd);
	cuMemFree(c.gpu);
	cuCtxDestroy(cuctx);
	printf("result: %s (%d failure(s))\n", failures ? "FAIL" : "PASS", failures);
	return failures ? 1 : 0;
}
