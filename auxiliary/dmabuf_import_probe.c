// SPDX-FileCopyrightText: Samsung Electronics Co., Ltd
//
// SPDX-License-Identifier: BSD-3-Clause
/*
 * Dump the export-side view of a CUDA dma-buf and where the buffer ends up.
 * The (dma_addr, dma_len) tuples DMABUF_IMPORT_GET_MAP returns are not the
 * IOMMU mapping unit: the benchmark maps the GPU heap through iommu_map_pa_add
 * at 2 MiB (DMAMEM_CUDA_REGISTRY_GRANULARITY), while GET_MAP shows 64 KiB
 * export pages on a misc import or NVIDIA's private map path merged into one
 * segment on a real-device (--bdf) import.
 */

#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <cuda.h>
#include <linux/dmabuf_import.h>

/* cuCtxCreate takes the CUctxCreateParams argument from CUDA 13.0 on, where
 * the alias moved from cuCtxCreate_v2 to cuCtxCreate_v4. 12.5 introduced the v4
 * entry point but kept the alias on v2, so the arity follows the major. */
#if CUDA_VERSION >= 13000
#define CU_CTX_CREATE(pctx, flags, dev) cuCtxCreate((pctx), NULL, (flags), (dev))
#else
#define CU_CTX_CREATE(pctx, flags, dev) cuCtxCreate((pctx), (flags), (dev))
#endif

static const char *
cuda_err_name(CUresult res)
{
	const char *name = "unknown";

	cuGetErrorString(res, &name);
	return name;
}

#define CHECK_CU(expr)                                                         \
	do {                                                                       \
		CUresult _r = (expr);                                                  \
		if (_r != CUDA_SUCCESS) {                                              \
			fprintf(stderr, "FAILED: %s: %s (%d)\n", #expr,                   \
				cuda_err_name(_r), (int)_r);                                   \
			goto out;                                                          \
		}                                                                      \
	} while (0)

static void
fmt_bytes(uint64_t v, char *buf, size_t cap)
{
	static const char *units[] = {"B", "KiB", "MiB", "GiB", "TiB"};
	int u = 0;
	double d = (double)v;

	while (d >= 1024.0 && u < 4) {
		d /= 1024.0;
		u++;
	}

	if (u == 0)
		snprintf(buf, cap, "%" PRIu64 " B", v);
	else
		snprintf(buf, cap, "%.2f %s", d, units[u]);
}

static int
run_variant(const char *label, int dmabuf_fd, const char *bdf, size_t nbytes)
{
	struct dmabuf_import_attach_bdf attach_bdf;
	struct dmabuf_import_get_map *map = NULL;
	struct dmabuf_import_describe describe;
	uint32_t count;
	uint64_t total = 0, prev_end = 0;
	uint64_t smallest = UINT64_MAX, largest = 0;
	char len[32], smallest_s[32], largest_s[32], total_s[32];
	int import_fd = -1;
	int contiguous = 1;
	int ret = 1;

	printf("\n== %s ==\n", label);

	import_fd = open(DMABUF_IMPORT_DEVPATH, O_RDWR);
	if (import_fd < 0) {
		fprintf(stderr, "FAILED: open(%s): %s; is the module loaded?\n",
			DMABUF_IMPORT_DEVPATH, strerror(errno));
		goto out;
	}

	memset(&attach_bdf, 0, sizeof(attach_bdf));
	attach_bdf.fd = dmabuf_fd;
	if (bdf)
		snprintf(attach_bdf.bdf, sizeof(attach_bdf.bdf), "%s", bdf);
	/* An empty bdf attaches as the misc device, which is what the upcie-cuda
	 * backend does. ATTACH_BDF owns the import per descriptor, so even a
	 * process killed mid-run cannot leak it into the module's fd table. */
	if (ioctl(import_fd, DMABUF_IMPORT_ATTACH_BDF, &attach_bdf)) {
		fprintf(stderr, "FAILED: DMABUF_IMPORT_ATTACH_BDF(%s): %s\n",
			bdf ? bdf : "", strerror(errno));
		goto out;
	}
	count = attach_bdf.count;
	printf("attach: %u dma segment%s\n", count, count == 1 ? "" : "s");

	map = malloc(sizeof(*map) + (size_t)count * sizeof(map->dma_arr[0]));
	if (!map) {
		fprintf(stderr, "FAILED: malloc(%u segments): %s\n", count,
			strerror(errno));
		goto out;
	}
	memset(map, 0, sizeof(*map));
	map->fd = dmabuf_fd;
	map->count = count;

	if (ioctl(import_fd, DMABUF_IMPORT_GET_MAP, map)) {
		fprintf(stderr, "FAILED: DMABUF_IMPORT_GET_MAP: %s\n", strerror(errno));
		goto out;
	}

	/* GET_MAP reports how many segments it filled in; anything above what
	 * ATTACH_BDF asked for would be read past the end of the allocation. */
	if (map->count > count) {
		fprintf(stderr, "FAILED: GET_MAP returned %u of %u segments\n",
			map->count, count);
		goto out;
	}
	if (!map->count) {
		fprintf(stderr, "FAILED: GET_MAP returned no segments\n");
		goto out;
	}

	count = map->count;
	for (uint32_t i = 0; i < count; i++) {
		struct dmabuf_import_dma_map *m = &map->dma_arr[i];

		fmt_bytes(m->dma_len, len, sizeof(len));
		printf("  [%2u] dma_addr 0x%016" PRIx64 " len %" PRIu64 " (%s)\n",
			i, (uint64_t)m->dma_addr, (uint64_t)m->dma_len, len);

		total += m->dma_len;
		if (m->dma_len < smallest)
			smallest = m->dma_len;
		if (m->dma_len > largest)
			largest = m->dma_len;
		if (i > 0 && prev_end != m->dma_addr)
			contiguous = 0;
		prev_end = m->dma_addr + m->dma_len;
	}

	fmt_bytes(total, total_s, sizeof(total_s));
	fmt_bytes(smallest, smallest_s, sizeof(smallest_s));
	fmt_bytes(largest, largest_s, sizeof(largest_s));
	printf("map: %u segment%s, %s total (smallest %s, largest %s)\n",
		count, count == 1 ? "" : "s", total_s, smallest_s, largest_s);
	printf("contiguity: %s\n", contiguous ? "every segment abuts the previous"
					       : "segments are disjoint");
	printf("as 4 KiB pages: %zu entries\n", nbytes / 4096);

	memset(&describe, 0, sizeof(describe));
	describe.fd = dmabuf_fd;
	if (ioctl(import_fd, DMABUF_IMPORT_DESCRIBE, &describe) == 0) {
		printf("describe: exporter=%-16s importer=%-16s segments=%u nbus=%u "
		       "nopage=%u npages=%u pinned=%u nbytes=%" PRIu64 "\n",
			describe.exporter, describe.importer, describe.count,
			describe.nbus, describe.nopage, describe.npages,
			describe.pinned, (uint64_t)describe.nbytes);
	} else {
		fprintf(stderr, "FAILED: DMABUF_IMPORT_DESCRIBE: %s\n",
			strerror(errno));
	}

	ret = 0;

out:
	free(map);
	if (import_fd >= 0) {
		ioctl(import_fd, DMABUF_IMPORT_DETACH, &dmabuf_fd);
		close(import_fd);
	}
	return ret;
}

int
main(int argc, char *argv[])
{
	const char *bdf = NULL;
	size_t size_mib = 1024;
	int gpu_id = 0;
	CUdevice cu_dev;
	CUcontext ctx = NULL;
	CUdeviceptr vaddr = 0;
	char name[64], bytes_s[32];
	size_t gran_min = 0, gran_rec = 0;
	CUmemAllocationProp prop;
	int dmabuf_fd = -1;
	int ret = 1;

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--size_mib") && i + 1 < argc)
			size_mib = (size_t)atoll(argv[++i]);
		else if (!strcmp(argv[i], "--gpu_id") && i + 1 < argc)
			gpu_id = atoi(argv[++i]);
		else if (!strcmp(argv[i], "--bdf") && i + 1 < argc)
			bdf = argv[++i];
	}

	CHECK_CU(cuInit(0));
	CHECK_CU(cuDeviceGet(&cu_dev, gpu_id));
	CHECK_CU(cuDeviceGetName(name, sizeof(name), cu_dev));
	CHECK_CU(CU_CTX_CREATE(&ctx, 0, cu_dev));

	printf("gpu: %s (device %d)\n", name, gpu_id);

	memset(&prop, 0, sizeof(prop));
	prop.type = CU_MEM_ALLOCATION_TYPE_PINNED;
	prop.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
	prop.location.id = cu_dev;
	if (cuMemGetAllocationGranularity(&gran_min, &prop,
					  CU_MEM_ALLOC_GRANULARITY_MINIMUM) == CUDA_SUCCESS)
		printf("allocation granularity (minimum):    %zu bytes\n", gran_min);
	if (cuMemGetAllocationGranularity(&gran_rec, &prop,
					  CU_MEM_ALLOC_GRANULARITY_RECOMMENDED) == CUDA_SUCCESS)
		printf("allocation granularity (recommended): %zu bytes\n", gran_rec);

	fmt_bytes((uint64_t)size_mib << 20, bytes_s, sizeof(bytes_s));
	printf("allocating %s (%zu MiB)\n", bytes_s, size_mib);

	CHECK_CU(cuMemAlloc(&vaddr, (size_t)size_mib << 20));

	{
		CUmemGenericAllocationHandle handle;

		CHECK_CU(cuMemGetHandleForAddressRange(
			&handle, vaddr, (size_t)size_mib << 20,
			CU_MEM_RANGE_HANDLE_TYPE_DMA_BUF_FD, 0));
		dmabuf_fd = (int)handle;
	}

	/* Both variants run even when the first one fails, since each is a
	 * separate observation; a failure in either is reported as one. */
	ret = run_variant("misc device (upcie-cuda default)", dmabuf_fd, NULL,
			  (size_t)size_mib << 20);
	if (bdf && run_variant("PCI device (peer-to-peer path)", dmabuf_fd, bdf,
			       (size_t)size_mib << 20))
		ret = 1;

out:
	if (dmabuf_fd >= 0)
		close(dmabuf_fd);
	if (vaddr)
		cuMemFree(vaddr);
	if (ctx)
		cuCtxDestroy(ctx);

	return ret;
}
