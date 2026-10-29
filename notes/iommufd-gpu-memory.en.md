# iommufd Support for GPU Memory DMA Mapping

This report will be refreshed regularly as new upstream patches appear. The Korean original is [iommufd-gpu-memory.md](iommufd-gpu-memory.md).

- Written: 2026-10-13, revised: 2026-10-29
- Base trees: Linux mainline v7.3 (2026-10-18) and the v7.4 merge window so far (c339f4010dea, 2026-10-28), iommufd for-next (04bcf8461334), linux-next 20261028
- Mailing lists: dri-devel, linux-mm, iommu, kvm, io-uring, linux-nvme, linux-block and linux-pci archives up to 2026-10-28 23:00 UTC
- Related code: upcie-experimental 0.9.0 (`iommu_map_pa`, `dmabuf_import`; latest release 0.10.4), NVIDIA driver 580.178.04 (version on the test server; latest release 615.78.08)

## Summary

For an NVMe device to DMA directly into GPU VRAM allocated by CUDA, the physical address of that VRAM (the GPU BAR1 address) must be mapped in the NVMe device's IOMMU page table. Today the upcie kernel module `iommu_map_pa` creates this mapping directly, without going through iommufd. This report examines whether upstream iommufd can accept a CUDA dma-buf through `IOMMU_IOAS_MAP_FILE` and create the same mapping, which would let us remove `iommu_map_pa`. The report reflects the state as of 2026-10-29.

Upstream iommufd cannot map an NVIDIA dma-buf today, so `iommu_map_pa` has to stay for now. iommufd has accepted dma-bufs through `IOMMU_IOAS_MAP_FILE` since v6.19, but it gets the physical addresses only from the vfio-pci private function `vfio_pci_dma_buf_iommufd_map()`, so it maps only single-range dma-bufs exported by vfio-pci. On our test server (a two-socket Xeon Ice Lake-SP system with an NVIDIA L4), an unmodified distribution kernel (7.0.0-34-generic) rejected an NVIDIA dma-buf with `errno=95` (`EOPNOTSUPP`).

Work to accept dma-bufs from other exporters such as NVIDIA is under way as patch series on the Linux kernel mailing lists, and none of it has been merged. The dma-buf mapping types series, which Jason Gunthorpe of NVIDIA (the iommufd maintainer) posted as an RFC on 2026-02-18, adds a scheme for negotiating the address exchange format (mapping type) of a dma-buf. Alistair Popple, also of NVIDIA, reposted the series as a formal patch set for the first time on 2026-10-26. However, this version drops the physical address list type (PAL) and the iommufd connection, and the iommufd connection is planned as a separate "iommufd importer type" later.

Fred Griffoul of Amazon posted the mm memory provider series as an RFC on 2026-10-06. It placed the same kind of protocol in mm instead of going through dma-buf. In a follow-up RFC on 2026-10-27, however, he dropped the mm interface and narrowed the work to mapping VM memory (guest_memfd) into iommufd. As a result, the mapping types series is the only posted path that applies to drivers outside a VM, such as NVIDIA (inferred). Adding one more private connection just for NVIDIA is unlikely to be accepted, because the iommufd maintainer has rejected that approach (inferred). The full list of series and their history is in §5.

Outside iommufd, io_uring dma-buf support entered the v7.4 merge window on 2026-10-27. With it, an NVMe device driven by the kernel driver can DMA directly into GPU memory through a dma-buf. This path does not apply to vfio-based user space drivers, and we have not verified that it works with NVIDIA dma-bufs. A [series](https://lore.kernel.org/all/20261022144501.2478417-1-anuj1072538@gmail.com/) by Anuj Gupta (Samsung) that lets the same dma-buf be used for NVMe passthrough commands (`io_uring_cmd`) is under review. If it is merged and xNVMe gains support for registering dma-buf fixed buffers, we infer that xNVMe on aisio's kernel path can do P2P DMA into GPU memory at the level of individual NVMe commands (§3).

| Item | Status | Evidence |
| --- | --- | --- |
| [dma-buf mapping in iommufd](#4-blocking-factors) | Single MMIO range of a VFIO PCI dma-buf only | UAPI comment ([298ab7e6f163](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=298ab7e6f163)), [`pages.c`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/iommu/iommufd/pages.c?h=v7.3) |
| [NVIDIA dma-buf](#4-blocking-factors) | Rejected (`-EOPNOTSUPP`) | Exporter check in [`vfio_pci_dmabuf.c`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/vfio/pci/vfio_pci_dmabuf.c?h=v7.3), `errno=95` measured on the test server ([PoC report §6.2](https://github.com/jaeyoon-choi/aisio/blob/poc/iommufd-pal/notes/pal-poc/REPORT.md#62-단계별-결과)) |
| [Support for any exporter](#51-series-list) | Not merged | No related symbols (`dma_buf_mapping_match`, PAL, provider) in [v7.4 merge window](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/log/?id=c339f4010dea), [iommufd for-next](https://git.kernel.org/pub/scm/linux/kernel/git/jgg/iommufd.git/log/?id=04bcf8461334), [linux-next 20261028](https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tag/?h=next-20261028) |
| [PAL type](#52-dma-buf-mapping-types-and-pal) | Dropped from the [formal series](https://lore.kernel.org/all/20261026053623.202642-1-apopple@nvidia.com/) (2026-10-26) | The iommufd connection is deferred to an importer type that follows the [April compromise](https://lore.kernel.org/all/20260422150000.GK3199414@nvidia.com/) (§5.2) |
| [mm provider](#53-mm-memory-provider-and-guest_memfd-export) | Stopped. Replaced by guest_memfd export | Cover letter of the [follow-up RFC](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/): "this series drops the mm interface" |
| [io_uring dma-buf (outside iommufd)](#3-merged-patches) | Merged in the v7.4 merge window | [ed02f4f7ad9b](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=ed02f4f7ad9b). A passthrough extension is [under review](https://lore.kernel.org/all/20261022144501.2478417-1-anuj1072538@gmail.com/) |
| [Private connection for NVIDIA](#55-impact-on-the-nvidia-driver) | Unlikely (inferred) | Mails from the iommufd maintainer on [2026-10-01](https://lore.kernel.org/all/20261001171501.GD3019323@ziepe.ca/), [2026-10-12](https://lore.kernel.org/all/20261012144616.GF14213@ziepe.ca/) |

Whichever design is adopted, iommufd will register the BAR1 physical addresses with `IOMMU_MMIO`, just as `iommu_map_pa` does. In the PoC, the PAL path reached the same throughput as a host memory target with one NVMe device, one queue and sequential I/O on the test server.

Until upstream settles, we keep using `iommu_map_pa` and check the signals in §6 every quarter. Items we could not verify (for example, whether a CUDA allocation has no CPU mapping that points to BAR1, and whether there really is no upstream series that covers CUDA) and their next steps are in §7.

## 1. Problem and Current Workaround

When large amounts of data move between GPU memory and storage, as in KV cache offloading for LLM inference, model loading and checkpointing, it is better for bandwidth and CPU load if the NVMe device DMAs directly into GPU VRAM (P2P) instead of going through host RAM. When the NVMe device is driven from user space through vfio, the IOMMU translates the NVMe device's DMA addresses. The addresses that the NVMe device uses for DMA are then IOVAs (I/O virtual addresses), not physical addresses, and the IOMMU looks up the physical address for each IOVA in the page table assigned to the NVMe device. For the NVMe device to DMA into GPU VRAM, the physical addresses of the BAR1 window, through which the GPU exposes its VRAM, must therefore be mapped in this page table.

The mapping APIs of VFIO and iommufd accept only a host virtual address (VA) or a file (fd). A CUDA allocation has no CPU mapping (VMA) that points to BAR1 (inferred from general behavior), so the VA path cannot be used, and the fd path rejects NVIDIA dma-bufs (§4). Because neither path works, the upcie [iommu_map_pa](https://github.com/safl/upcie/tree/v0.9.0/experimental/iommu_map_pa) module does the job directly. The module gets the current domain of the vfio-pci device with `iommu_get_domain_for_dev()` and inserts the BAR1 physical addresses that `dmabuf_import` found into that domain with `iommu_map(..., IOMMU_MMIO)`. The module ships as the DKMS package `upcie-experimental-dkms`, and upcie's `dmamem_from_cuda_iommu_map_pa()` calls it. The module bypasses the IOVA accounting, lifetime management, locking and dirty tracking of iommufd, so it is not safe for production use. The long-term goal is for `IOMMU_IOAS_MAP_FILE` to accept CUDA dma-bufs directly and replace this module.

This report tracks upstream progress in the following four levels of support.

| Level | Status | Description |
| --- | --- | --- |
| ① File mapping | Merged (v6.13) | Map a memfd with `IOMMU_IOAS_MAP_FILE` |
| ② Device memory | Merged (v6.19) | Map a dma-buf (MMIO) with the same ioctl. vfio-pci dma-bufs only |
| ③ Support for any exporter | Not merged | Map a dma-buf (or provider file) from any driver |
| ④ NVIDIA exporter | No series | The NVIDIA driver implements the protocol of ③ |

## 2. Mapping APIs and Terms

The later sections assume familiarity with the dma-buf terms and with how the mapping APIs that could put GPU memory into the IOMMU differ.

| Term | Meaning |
| --- | --- |
| dma-buf | The kernel buffer sharing framework. The driver that owns a buffer (exporter) exports it as an fd, and another driver (importer) attaches to it and maps it |
| scatterlist | The traditional address format of dma-buf. It is a list of `dma_addr_t`, so it does not fit an importer that does not use the DMA API (iommufd) |
| `phys_vec` | A kernel structure that describes one physical address range (`paddr`, `len`) |
| `IOMMU_MMIO` | A flag that gives an IOMMU page table entry the device memory (uncached) attribute. iommufd collects MMIO PFNs into `BATCH_MMIO` batches and maps them with this flag |
| IOAS, `iommu_domain` | The iommufd IO address space object, and the IOMMU layer object that holds the actual page table |
| revoke, pin | The exporter taking back a mapping (`dma_buf_invalidate_mappings()`), and the importer preventing the buffer from moving (`dma_buf_pin()`) |

| API | Input | Regular RAM | Device BAR mmap (PFNMAP) | dma-buf |
| --- | --- | --- | --- | --- |
| `VFIO_IOMMU_MAP_DMA` (type1) | Host VA | Pinned | Mapped without pin (no lifetime guarantee) | Not accepted |
| `IOMMU_IOAS_MAP` | Host VA | Pinned | Not accepted | Not accepted |
| `IOMMU_IOAS_MAP_FILE` + memfd | fd | Pinned | N/A | N/A |
| `IOMMU_IOAS_MAP_FILE` + dma-buf | fd | N/A | N/A | Single-range vfio-pci only, revoke callback |

type1 maps a PFNMAP VMA without pinning through `follow_fault_pfn()`, but it cannot guarantee the lifetime of the mapping, so iommufd added the dma-buf path instead. We infer that a CUDA allocation cannot be mapped through any VA path, which leaves the dma-buf path, and §4 covers whether that path accepts NVIDIA dma-bufs. Every path inserts the BAR1 physical addresses with `IOMMU_MMIO`. iommufd also collects them into `BATCH_MMIO` and calls `iommu_map()` with `IOMMU_MMIO` (`pages.c`, v7.3), and the PAL RFC and mm provider RFC v2 patches also map MMIO pages with `IOMMU_MMIO`. The difference lies in who checks the physical addresses and who is responsible for the lifetime.

## 3. Merged Patches

The dma-buf support in iommufd reached its current form through changes from v6.13 to the v7.4 merge window. The v6.19 dma-buf support came from a series by Gunthorpe and Romanovsky (NVIDIA) ([v1](https://lore.kernel.org/all/0-v1-64bed2430cdb+31b-iommufd_dmabuf_jgg@nvidia.com/) 2025-10-27, [v2](https://lore.kernel.org/all/0-v2-b2c110338e3f+5c2-iommufd_dmabuf_jgg@nvidia.com/) 2025-11-21). The author column shows each commit's Author, and the affiliation in parentheses is inferred from the domain of the author's email or Signed-off-by address.

| Release | Commit | Author | Description |
| --- | --- | --- | --- |
| v6.13 (2025-01-19) | [f4986a72d6e4](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f4986a72d6e4) | Steve Sistare (Oracle) | Adds `IOMMU_IOAS_MAP_FILE`, which pins a memfd with `memfd_pin_folios()` and maps it. Because the mapping input became a file, the same ioctl could later accept dma-bufs |
| v6.19 (2026-02-08) | [3aa31a8bb11e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=3aa31a8bb11e) | Leon Romanovsky (NVIDIA) | A common dma-buf helper that turns an array of BAR MMIO ranges into a scatterlist |
|  | [5d74781ebc86](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=5d74781ebc86) | Leon Romanovsky (NVIDIA) | The vfio-pci exporter itself, which exports BAR MMIO ranges as a dma-buf |
|  | [35c3503908d3](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=35c3503908d3) | Leon Romanovsky (NVIDIA) | Enables P2P on every vfio-pci device by default so that a BAR can be exported as a dma-buf |
|  | [96ce2aeb15bd](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=96ce2aeb15bd) | Jason Gunthorpe (NVIDIA) | The private function `vfio_pci_dma_buf_iommufd_map()` between the vfio-pci exporter and iommufd. The commit message calls it a temporary API and lists what support for any exporter needs: revoke semantics (fc7063abd98e in v6.19 on the iommufd side, v7.1 on the vfio side), physical address negotiation (in progress, §5.2) and attach for an importer without a DMA device. Attach is currently worked around with the iommufd misc device |
|  | [3114c674401e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=3114c674401e) | Jason Gunthorpe (NVIDIA) | iommufd maps batches of MMIO PFNs with `IOMMU_MMIO` |
|  | [74014a4b55f5](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=74014a4b55f5) | Jason Gunthorpe (NVIDIA) | The iommufd pfn_reader handles dma-buf `iopt_pages` |
|  | [fc7063abd98e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=fc7063abd98e) | Jason Gunthorpe (NVIDIA) | iommufd accepts a dma-buf revoke and removes the mapping |
|  | [71db84a092c3](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=71db84a092c3) | Jason Gunthorpe (NVIDIA) | Adds a dma-buf type to `iopt_pages`. The commit message says "for now can only be used with the VFIO DMABUF exporter". Pin accounting and kernel CPU access are not supported |
|  | [44ebaa1744fd](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=44ebaa1744fd) | Jason Gunthorpe (NVIDIA) | `IOMMU_IOAS_MAP_FILE` accepts a dma-buf fd, which exposes the feature to user space |
|  | [5415d887db0e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=5415d887db0e) | Jason Gunthorpe (NVIDIA) | GPU memory export from the nvgrace-gpu vfio variant driver. The GPU must be bound to vfio, so it cannot be used together with CUDA |
| v7.1 (2026-06-14) | [ef246da8e63c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=ef246da8e63c), [95308225e5ba](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=95308225e5ba) | Leon Romanovsky (NVIDIA) | Renames `move_notify` to `invalidate_mappings` |
|  | [575157b1b5fc](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=575157b1b5fc), [1a8a5227f229](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=1a8a5227f229) | Leon Romanovsky (NVIDIA) | Makes `invalidate_mappings` optional, and vfio waits for dma-buf invalidation to complete |
|  | [be6d4c9e9d71](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=be6d4c9e9d71) | Leon Romanovsky (NVIDIA) | `dma_buf_attach_revocable()`, which checks the contract that the exporter revokes access synchronously and the importer does not touch the memory after the revoke |
|  | [6ffe939bf94f](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=6ffe939bf94f) | Leon Romanovsky (NVIDIA) | vfio accepts pinned importers that follow this contract. One of the two items (the revoke contract and the physical address list) needed to remove the iommufd private interface |
|  | [8c5f9645c389](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=8c5f9645c389) | Leon Romanovsky (NVIDIA) | iommufd calls the generic `dma_buf_pin()`. The remaining item (the physical address list) is deferred to "another series" (§5.2) |
| v7.2 (2026-08-16) | [298ab7e6f163](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=298ab7e6f163) | Alex Mastro (Meta) | Corrects the UAPI comment: "This is not a generic dma-buf import path; currently supported dma-bufs include single-range VFIO PCI dma-bufs" |
|  | [5f3fc0ad9a41](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=5f3fc0ad9a41) | Peiyang He (Nanjing University) | Blocks dma-buf `iopt_pages` from entering the kernel access pin path, where they were misread as user addresses |
|  | [e745cd2c749e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=e745cd2c749e) | Ankit Soni (AMD) | Calls `dma_buf_unpin()` under the `dma_resv` lock in the release path (found by a selftest warning). Not in the PoC kernel |
|  | [f2d70dbd3dce](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f2d70dbd3dce) | Jason Gunthorpe (NVIDIA) | Cleans up the pages contents only after the dma-buf detach finishes (reported by Sashiko, the AI review bot on the kernel mailing lists). Not in the PoC kernel |
| v7.3 (2026-10-18) | [b344ca94e8cc](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=b344ca94e8cc), [06dd5e1ae8ce](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=06dd5e1ae8ce) | David Hu (Google) | Fixes a length overflow in `dma_buf_phys_vec_to_sgt()` and changes how the sgl is split. The vfio-pci and RDMA exporters use this helper to build their SGTs; the iommufd path does not |
| v7.4 merge window (as of c339f4010dea) | [769f2cd9226c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=769f2cd9226c) | Andrea Parri | Maps dma-buf PFNs with `IOMMU_MMIO` also when a domain is attached later or an area is copied. Does not affect `iommu_map_pa` or the PoC, which map once into a single domain |
|  | [0d3120db2cbe](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=0d3120db2cbe) | Pavel Begunkov | dma-buf file I/O infrastructure (`dma_buf_io_ctx`, `dma_buf_io_map`). An io_uring path unrelated to iommufd |
|  | [ce5e386c1108](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=ce5e386c1108) | Pavel Begunkov | The kernel nvme-pci driver imports a dma-buf as a dynamic importer (`allow_peer2peer`) and builds commands from its DMA addresses |
|  | [839231d19393](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=839231d19393) | Pavel Begunkov | dma-buf I/O on raw block devices, O_DIRECT only |
|  | [d5c8cfd41d25](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=d5c8cfd41d25) | Anuj Gupta (Samsung) | SGL support in the nvme-pci dma-buf path |
|  | [62e4bf5b25d4](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=62e4bf5b25d4) | Pavel Begunkov | io_uring registers a dma-buf fd as a fixed buffer for a block device, used with `IORING_OP_READ_FIXED` and `WRITE_FIXED` |
|  | [bcbd808652e1](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=bcbd808652e1) | Keith Busch | Rejects dma-bufs of 4 GiB or more (the bvec offset is 32 bits) |

With v6.19, iommufd gained dma-buf mapping with accounting and lifetime management, and v7.1 aligned the revoke and pin flow with the generic dma-buf model. The only private part left is the vfio-pci function that provides the physical address list, and the comment in `pages.c` describes this link as "Future work for a phys based private interconnect will remove this". v7.3 and the v7.4 merge window did not widen the range of dma-bufs that iommufd accepts. The two v7.3 dma-buf fixes repair an SGT helper used by the vfio-pci and RDMA exporters. The PAL branch used by the PoC includes the v7.1 changes but not the two v7.2 release path fixes.

Outside iommufd, io_uring dma-buf support (merge commit [ed02f4f7ad9b](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=ed02f4f7ad9b)) entered the v7.4 merge window on 2026-10-27. When user space registers a dma-buf fd and an NVMe block device with io_uring, the kernel nvme-pci driver attaches to that dma-buf and reads and writes directly with the DMA addresses that the exporter returns. The exporter creates the NVMe device's IOMMU mapping by calling the DMA API for the NVMe device, so this path needs none of vfio, iommufd or `iommu_map_pa`. In exchange, the NVMe device must be driven by the kernel driver, so the path does not apply to vfio-based user space drivers. Each dma-buf must be smaller than 4 GiB, it can be used only with O_DIRECT on a raw block device, and devices that use an integrity checksum (PI) are rejected (`block/fops.c`). A [patch](https://lore.kernel.org/all/20261028181412.1919506-1-kbader@redhat.com/) that relaxes the PI restriction (2026-10-28) and an [RFC](https://lore.kernel.org/all/20261016091919.971295-1-anuj1072538@gmail.com/) that extends the path to file systems (xfs, iomap; 2026-10-16) have been posted. We have not verified that NVIDIA dma-bufs work on this path. There is a report that the NVIDIA driver returns BAR1 physical addresses instead of DMA addresses to an importer when the IOMMU is enabled ([Issue #1324](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1324), 2026-08-27, driver 595.84, no reply), so the path may not work with the IOMMU enabled (inferred). On the same day, König NAKed fgds RFC v2 from Li Wang of KylinOS (a kernel misc driver for direct I/O between a GPU dma-buf and a file) and cited this io_uring work as the reason ([mail](https://lore.kernel.org/all/fa64ae97-72a0-4c0f-9988-18500936a8a8@amd.com/)), and the author explained the design choice to Pavel Begunkov and said they would track the community's progress.

Anuj Gupta's (Samsung) [dma-buf backed NVMe passthrough series](https://lore.kernel.org/all/20261022144501.2478417-1-anuj1072538@gmail.com/) (v2, 5 patches, 2026-10-22) lets the same dma-buf fixed buffer be used for `io_uring_cmd` passthrough commands on the NVMe character device (`/dev/ngXnY`). The merged path covers only block layer reads and writes, while with passthrough the NVMe commands built in user space go to the device as they are. Christoph Hellwig gave Reviewed-by to the block and nvme patches (4/5, 5/5) on 2026-10-28, and the series has not been merged.

We judge that these two pieces of work matter a lot for aisio (inferred). aisio's architecture document (`docs/src/architecture.md`) lists a CPU-initiated P2P path that uses the kernel nvme driver, io_uring and dma-buf as one of its three architectures. With the v7.4 merge, block reads and writes on this path work on an unpatched upstream kernel. Once the passthrough series is also merged, xNVMe's `io_uring_cmd` backend can do P2P DMA into GPU memory with the same NVMe command interface as the uPCIe backend, so the setup that aisio emphasizes, switching between kernel and user space paths behind the same xNVMe API, becomes possible with upstream kernels alone. This also needs work on the xNVMe side. The io_uring backends of our local xNVMe (2026-09-22) do not register io_uring fixed buffers (a `register_buffers` option exists but the backends do not use it), and the passthrough series accepts only calls that explicitly opt in to using a fixed buffer as a dma-buf. This path does not use vfio or iommufd, so it is separate from replacing `iommu_map_pa`, which is the subject of this report, and the 4 GiB limit, the PI rejection and NVIDIA dma-buf support remain open conditions.

## 4. Blocking Factors

NVIDIA dma-bufs are rejected today in the vfio-pci private function that iommufd calls to get the physical addresses. When an NVIDIA dma-buf fd is passed to `IOMMU_IOAS_MAP_FILE`, iommufd recognizes it as a dma-buf and proceeds through attach, but `vfio_pci_dma_buf_iommufd_map()` returns `-EOPNOTSUPP` because the exporter is not vfio-pci (based on the v7.3 code). The range count check comes after this check, so the dma-buf is rejected even if it has only one range. The error measured on the test server's distribution kernel (7.0.0-34-generic) was `errno=95` (`EOPNOTSUPP`). If the attach in the NVIDIA driver (580.178.04) had failed, the result would have been `-ENOTSUPP` (524), so the attach step is ruled out. However, a failed symbol lookup, which happens when the vfio-pci module is not loaded, returns the same value, and the measurement was taken before the device was bound to vfio, so the measurement cannot tell the two cases apart. `iommu_map_pa` skips all of these checks, so the kernel does not validate the exporter, the range count or the physical addresses. `iommu_map_pa` is therefore the only path that works today, but it is not safe.

The causes of the rejection break down as follows. The fixed exporter is the direct factor that blocks NVIDIA dma-bufs today, and the single range limit and the missing protocol are conditions that surface once the direct factor is removed.

| Factor | Description |
| --- | --- |
| Fixed exporter (direct factor) | iommufd gets the physical addresses only through a `symbol_get()` call to a vfio-pci symbol, so other exporters are rejected in that function. Apart from a selftest hook there is no other path, and with `CONFIG_VFIO_PCI_DMABUF` off this path does not exist either |
| Single range (follow-on condition) | The current function succeeds only when there is a single range. The 1 GiB buffer in our tests was a single range, but the NVIDIA exporter can return several ranges per handle |
| No physical address list protocol (root condition) | iommufd needs a list of `phys_addr_t`, not a scatterlist of `dma_addr_t`, and dma-buf has no generic protocol to exchange such a list |

## 5. Patches Under Review

The work to remove the factors in §4 has not been merged and is under review on the mailing lists. This section summarizes those series and related ones as of 2026-10-29.

### 5.1 Series List

For iommufd to accept NVIDIA dma-bufs, it needs a generic protocol that passes the physical addresses of an exporter other than vfio-pci to iommufd. This section separates the series that build or tried to build that protocol from related series that do not build it but affect the judgments in this report.

#### Generic Protocol Series

| Series | Proposer | Latest version (date) | Status |
| --- | --- | --- | --- |
| DMA-buf mapping types | Gunthorpe, Popple (NVIDIA) | [PATCH 00/26](https://lore.kernel.org/all/20261026053623.202642-1-apopple@nvidia.com/) (2026-10-26) | Under review, v2 announced. Moves the existing scatterlist to an SGT type. The PAL type and the iommufd connection from [RFC v1](https://lore.kernel.org/all/0-v1-b5cab63049c0+191af-dmabuf_map_type_jgg@nvidia.com/) (2026-02-18) are left out |
| mm memory provider | Fred Griffoul (Amazon) | [RFC v2 00/11](https://lore.kernel.org/all/20261014093733.90312-1-griffoul@gmail.com/) (2026-10-14) | Stopped. Replaced by guest_memfd export |
| guest_memfd export | Fred Griffoul (Amazon) | [RFC 00/14](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/) (2026-10-27) | No human review yet (only a Sashiko AI review). Covers VM memory only |
| guest_memfd backed by dma-buf (`get_phys()`) | Fred Griffoul | [RFC 0/6](https://lore.kernel.org/all/20261005095552.52748-1-griffoul@gmail.com/) (2026-10-05) | NAKed by König, withdrawn the same day |
| iommufd PAL release path fix | Karl Mehltretter | [RFC 0/6](https://lore.kernel.org/all/cover.1792477872.git.kmehltretter@gmail.com/) (2026-10-20) | The PAL code that patches 1-3 fixed was dropped, and patches 4-5 duplicate v7.2 |

The mapping types series is building this protocol in dma-buf. RFC v1 in 2026-02 included the iommufd connection through the physical address list type (PAL), but in April the dma-buf maintainer König objected to an importer receiving physical addresses, and Gunthorpe proposed a compromise. The formal patch set of 2026-10-26 dropped PAL and the iommufd connection and kept only the type negotiation scheme. On 10-27, König objected to the new attach functions, and Popple announced a v2 that fixes the bugs found in review. The detailed history is in §5.2.

Griffoul tried to build the same protocol in mm. The day after König rejected his `get_phys()` RFC, which backed guest_memfd with a dma-buf, on 2026-10-05, he posted mm memory provider RFC v1. RFC v2 followed on 10-14, and Gunthorpe set implementation conditions on the iommufd side. In the follow-up RFC on 10-27, however, Griffoul dropped the mm interface and narrowed the work to mapping guest_memfd only. The detailed history is in §5.3.

Mehltretter's fix repairs a double free in the iommufd release path on the PAL branch that the PoC kernel is based on, and adds a fault injection selftest. Popple [agreed to fold it into v2](https://lore.kernel.org/all/athLCINDCSUbRHiC@nvdebian.thelocal/) on 10-21, but the formal PATCH 00/26 posted on 10-26 dropped PAL, so the code that patches 1-3 fixed is gone. The "v2" in Popple's 10-21 reply is this 10-26 posting. The [author](https://lore.kernel.org/all/atgWXLYKOFj5cZ0F@gmail.com/) noted that patches 4 and 5 duplicate f2d70dbd3dce and e745cd2c749e in v7.2.

#### Related Series

| Series | Proposer | Latest version (date) | Relation to this report |
| --- | --- | --- | --- |
| guest_memfd PFNMAP provider | David Woodhouse (Amazon) | [RFC v2 00/11](https://lore.kernel.org/all/20260720111259.122911-1-dwmw2@infradead.org/) (2026-07-20) | Makes the guest_memfd backend replaceable. Patch 1 of mm provider v2 builds on this series' `kvm_gmem_ops` patch |
| guest_memfd alternative providers | Ackerley Tng (Google) | [RFC v2 00/50](https://lore.kernel.org/all/20261022-gmem-alternative-providers-v2-0-5dd1dc6c660a@google.com/) (2026-10-22) | Under review. Base of the guest_memfd export RFC. RFC v1 was posted on [2026-09-26](https://lore.kernel.org/all/20260925-gmem-tmpfs-backend-v1-0-d36159822d18@google.com/) |
| guest_memfd for device MMIO | Aneesh Kumar K.V (Arm) | [RFC v2 00/13](https://lore.kernel.org/all/20261017073149.1303738-1-aneesh.kumar@kernel.org/) (2026-10-17) | Connects a vfio-pci BAR to a VM as a guest_memfd provider and blocks dma-buf exports while the provider is attached. RFC v1 was posted on [2026-10-10](https://lore.kernel.org/all/20261010072504.536230-1-aneesh.kumar@kernel.org/) |
| guest_memfd mapping in iommufd | Alexey Kardashevskiy (AMD) | [RFC](https://lore.kernel.org/all/20260225075211.3353194-1-aik@amd.com/) (2026-02-25) | An earlier attempt to map guest_memfd through `IOMMU_IOAS_MAP_FILE`. No later version |
| Host bridge MMIO window query | Guanghui Feng (Alibaba) | [v6 0/3](https://lore.kernel.org/all/20261028090453.2392991-1-guanghuifeng@linux.alibaba.com/) (2026-10-28) | Lets xNVMe query and reserve the ranges to avoid when it chooses the GPU IOVA window |
| P2PDMA routing by TLP class | Leon Romanovsky (NVIDIA) | [v11 00/19](https://lore.kernel.org/all/20261013-fix-p2p-acs-v4-0-v11-0-72cf8c96e617@nvidia.com/) (2026-10-13) | Decides P2P routes below ACS-enabled switches. Helgaas deferred it to [after rc1](https://lore.kernel.org/all/20261019191845.GA2219127@bhelgaas/) |
| mmap of vfio-pci dma-bufs | Matt Evans | [v8 0/9](https://lore.kernel.org/all/20261006193643.76330-1-matt@ozlabs.org/) (2026-10-06) | mmap of vfio-pci dma-bufs and revoke on user request. [Reviewed](https://lore.kernel.org/all/20261013171347.54e856c7@shazbot.org/) by Williamson, not in v7.4 |
| dma-buf backed NVMe passthrough | Anuj Gupta (Samsung) | [v2 0/5](https://lore.kernel.org/all/20261022144501.2478417-1-anuj1072538@gmail.com/) (2026-10-22) | Affects aisio's kernel path (§3). Reviewed-by from Hellwig on 2026-10-28 |

The guest_memfd series are the base for mapping VM memory into iommufd, and they do not change the range of dma-bufs that iommufd accepts. The vfio-pci dma-buf mmap and NVMe passthrough series also widen where dma-bufs can be used, but they do not change the iommufd constraints.

The host bridge MMIO window query and the P2PDMA series deal with P2P routes below PCIe switches. When ACS Upstream Forwarding is disabled on a switch and a device below the switch DMAs to an IOVA that overlaps a host bridge MMIO window, the switch can send the request to another device instead of forwarding it up to the IOMMU. Guanghui's series lets user space query such IOVA ranges (`IOMMU_GET_RECOMMENDED_RESERVATIONS`) and exclude them from the IOAS allocator (`IOMMU_IOAS_RESERVE_IOVAS`). v5 renamed the ioctl and added the reservation ioctl after Gunthorpe's v4 review (2026-10-27), and v6 on the same day fixed two Sashiko findings. Romanovsky's P2PDMA series addresses the same problem in the kernel's P2P route decision.

### 5.2 dma-buf Mapping Types and PAL

RFC v1 by the iommufd maintainer Jason Gunthorpe (NVIDIA) adds mapping types to dma-buf so that importers and exporters can negotiate the address format, and it adds a PAL (Physical Address List) type that passes an array of `phys_vec`. Only iommufd is allowed as a PAL importer, while any driver can implement a PAL exporter, and Gunthorpe gave the reason as "there are use cases in DPDK/SPDK to connect GPU memory into VFIO/iommufd". This RFC removes all three factors of §4. The PAL type becomes the generic protocol for exchanging physical address lists, which removes the missing protocol. Patches 23 and 24 replace the vfio-pci private call in iommufd with PAL, which removes the fixed exporter, and the same patches add multi-range support, which removes the single range limit. The PoC ported an NVIDIA exporter on top of this RFC's branch (c37cf2824740) and confirmed P2P DMA in both directions on the test server.

The dma-buf maintainer Christian König (AMD) objected to importers receiving physical addresses directly, and Gunthorpe proposed a compromise in which the exporter provides the physical addresses, the importer provides an `iommu_domain`, and only the dma-buf core, which has both, performs the mapping (original: "The exporter provides the address data, the importer provides the iommu_domain. The core code, and only the core code, has both and does the required operation?"). In October, the point at which the type is chosen became the main issue, and the formal patch set followed the contract that Thomas Hellström of Intel proposed (agree on candidates at attach, choose at the first pin or map, keep the choice until invalidate). The formal patch set dropped the PAL type and deferred the iommufd connection to an "iommufd importer type" that follows the compromise. The AI review bot Sashiko reported that the formal set's vfio-pci conversion could break the current vfio dma-buf mapping in iommufd at the attach step ([mail](https://lore.kernel.org/all/sashiko-outbox-184718@kernel.org/)), and this report has no reply as of October 29. Mehltretter reproduced another problem that Sashiko reported (a failed map also clears the type chosen by an earlier pin) with a KUnit test, and Popple replied that v2 will fix it. On the same day, König called the new attach functions of the formal set (`dma_buf_mapping_attach()`, `dma_buf_sgt_attach()`) a NO-GO and asked for the type negotiation to happen inside the importer ops of the existing `dma_buf_dynamic_attach()` ([mail](https://lore.kernel.org/all/43a20d60-89a9-48fc-af73-5907b35a54d7@amd.com/)). Gunthorpe argued that a helper that marks SGT-only callers is better, so the API names and shape may change in v2.

#### Difference Between PAL and the iommufd Importer Type

The two approaches differ in which component receives the physical addresses from the exporter and puts them into the IOMMU.

| Item | PAL (RFC v1, 2026-02) | iommufd importer type (April compromise, not posted) |
| --- | --- | --- |
| What the exporter (NVIDIA) provides | BAR1 physical address list (`phys_vec`) | BAR1 physical address list (same as PAL) |
| Who receives the physical addresses | iommufd, the importer | The dma-buf core |
| Who creates the IOMMU mapping | iommufd calls `iommu_map()` directly with the addresses it received | iommufd passes only an `iommu_domain`, and the dma-buf core maps into that domain |
| Does the importer see physical addresses | Yes | No |

König objected to a design in which the importer receives physical addresses directly. On 2026-10-27 König again wrote "Sharing page/physical to be used with the IOMMU functions through DMA-buf is an absolutely hard NAK", and added that a way to allow it only for KVM, IOMMUFD and virtio still has to be worked out ([mail](https://lore.kernel.org/all/2be3338a-5657-4312-869d-3bb1d386f9fc@amd.com/)). That mail answered Mehltretter's report that Tegra DRM faults because it maps a dma-buf SGT into its own `iommu_domain`, and in the same thread Gunthorpe wrote "you cannot connect dmabuf to an iommu_domain" ([mail](https://lore.kernel.org/all/20261027123308.GC1671235@nvidia.com/)). That remark is about drivers putting an SGT into the IOMMU themselves, which is different from the importer type idea in which the core does the mapping (inferred). iommufd is therefore among the candidates for an exception, but the mechanism has not been decided. Gunthorpe responded to this objection with the compromise that keeps the translation inside the dma-buf core only, and the iommufd importer type follows that compromise.

The NVIDIA exporter's job of producing the BAR1 range list is the same in both approaches, and what changes is the iommufd side. iommufd moves from mapping the addresses it receives to passing a domain and leaving the mapping to the core. We infer that the component that removes the IOMMU mapping on revoke also moves to the core side, but we could not verify this because the importer type series has not been posted. In May, Xu Yilun pointed out that the compromise does not fit KVM because KVM's page tables are not an `iommu_domain`. Gunthorpe replied "it doesn't work well for kvm, and yes it is really weird and worse that phys in every way", and the thread has had no reply since. Popple's 10-26 cover letter still names this compromise as the plan for the iommufd connection, so the shape of the importer type may still change (inferred).

Dates in the history tables are in UTC.

| Date | Event | Source |
| --- | --- | --- |
| 2026-02-18 | Gunthorpe, RFC v1 with 26 patches (includes the PAL type) | [mail](https://lore.kernel.org/all/0-v1-b5cab63049c0+191af-dmabuf_map_type_jgg@nvidia.com/) |
| 2026-04-13 | König called PAL a "pretty big NO-GO". Gunthorpe replied "CPU iommu hw only works in physical address" and mentioned the use of GPU memory by user space drivers | [König](https://lore.kernel.org/all/c413710b-4c28-4ed8-88ec-aeb8c4482011@amd.com/), [Gunthorpe](https://lore.kernel.org/all/20260413121628.GE2588311@nvidia.com/) |
| 2026-04-22 | König proposed an alternative in which the exporter maps directly into an `iommu_domain`. Gunthorpe's compromise. König supported the mapping type scheme itself | [König](https://lore.kernel.org/all/fd8065ce-fd0e-4df5-9c80-8e9603657cfe@amd.com/), [Gunthorpe](https://lore.kernel.org/all/20260422150000.GK3199414@nvidia.com/), [König](https://lore.kernel.org/all/e67426b9-4ded-4f6c-8309-7f847adb4540@amd.com/) |
| 2026-05-09, 05-11 | Xu Yilun: the compromise does not fit KVM. Gunthorpe agreed, calling it "worse that phys in every way", and the thread stopped | [Xu](https://lore.kernel.org/all/af7GzASJiASopYiN@yilunxu-OptiPlex-7050/), [Gunthorpe](https://lore.kernel.org/all/20260511224841.GA1197107@nvidia.com/) |
| 2026-10-16 | Mehltretter reported a double free in the iommufd PAL release path (reproduced with KASAN) and a problem with when `match_mapping()` is called | [mail](https://lore.kernel.org/all/20261016194022.62065-1-kmehltretter@gmail.com/), [mail](https://lore.kernel.org/all/20261016202653.97339-1-kmehltretter@gmail.com/) |
| 2026-10-19 | König: decide the type right before mapping, under the `dma_resv` lock. Hellström proposed the attach, map and invalidate contract | [König](https://lore.kernel.org/all/d08a26ed-ded7-4447-bf7b-88597ee7df0e@amd.com/), [Hellström](https://lore.kernel.org/all/8d4cb20b70ac4c3f36d8d631769757158af2ac8e.camel@linux.intel.com/) |
| 2026-10-20 | Mehltretter posted the release path fix RFC. Popple wrote that whether the PAL approach is acceptable is still open and that he has started to look at other approaches | [RFC](https://lore.kernel.org/all/cover.1792477872.git.kmehltretter@gmail.com/), [Popple](https://lore.kernel.org/all/atdKZpEJVZY0enR2@nvdebian.thelocal/) |
| 2026-10-21 | Popple agreed to fold Mehltretter's fixes into v2 | [Popple](https://lore.kernel.org/all/athLCINDCSUbRHiC@nvdebian.thelocal/) |
| 2026-10-26 | Popple posted the formal `[PATCH 00/26]`, without PAL and the vfio and iommufd users, and with type selection moved to pin or map time. Mehltretter reproduced with KUnit the problem that a failed map clears the selection | [mail](https://lore.kernel.org/all/20261026053623.202642-1-apopple@nvidia.com/), [Mehltretter](https://lore.kernel.org/all/at8IQZ34wkHQ_5PL@gmail.com/) |
| 2026-10-27 | Popple replied that v2 will fix Mehltretter's report and two Xe findings. König called the new attach functions a NO-GO, and said that passing physical addresses to IOMMU functions through dma-buf is a hard NAK except for KVM, IOMMUFD and virtio | [Popple](https://lore.kernel.org/all/auA0XzHv9lgImZLP@nvdebian.thelocal/), [Popple](https://lore.kernel.org/all/auAk6hXyZbvBIrVO@nvdebian.thelocal/), [König](https://lore.kernel.org/all/43a20d60-89a9-48fc-af73-5907b35a54d7@amd.com/), [König](https://lore.kernel.org/all/2be3338a-5657-4312-869d-3bb1d386f9fc@amd.com/) |

### 5.3 mm Memory Provider and guest_memfd Export

The series in this section try to map a driver's memory into iommufd without going through dma-buf. The first attempt put a generic interface in mm, but on 2026-10-27 the scope narrowed to VM memory (guest_memfd) only.

#### mm Memory Provider (RFC v1, v2)

The mm memory provider that Griffoul of Amazon posted on 2026-10-06 works as follows.

- A driver that owns memory outside the page allocator (for example, a GPU driver) exposes that memory as a provider file.
- iommufd accepts this file through `IOMMU_IOAS_MAP_FILE` and maps it into the IOMMU. Unlike dma-buf, it does not pin the memory.
- To take memory back (revoke), the driver first notifies every user that mapped the file (iommufd, KVM), and the users remove their mappings.

This design appeared the day after König rejected the RFC that would have backed guest_memfd with a dma-buf (including `get_phys()`, which lets a dma-buf importer receive physical addresses). An earlier attempt to map guest_memfd into iommufd had been posted as an RFC by Kardashevskiy of AMD in 2026-02. Griffoul wrote that if VFIO also exposed a BAR as a provider file, it could replace the current vfio-pci private path in iommufd (`symbol_get()`) ([mail](https://lore.kernel.org/all/20261016105752.68015-1-griffoul@gmail.com/)).

The iommufd maintainer Gunthorpe started with "if we are going to do this" and then required that provider file mapping work only with iommupt (generic_pt), the common IOMMU page table code, and that it come with an unmap that handles holes (pages for which the driver has not yet provided memory). He did not say whether the design would be accepted. Griffoul also agreed to drop the RFC v2 patch that maps large IOMMU pages after Gunthorpe's review.

#### Switch to guest_memfd Export (2026-10-27)

Instead of an RFC v3, Griffoul posted the guest_memfd export RFC and stated in the cover letter that "this series drops the mm interface". guest_memfd is the file in which KVM holds a VM's memory. Ackerley Tng's (Google) guest_memfd RFC v2, posted on 2026-10-22, put the ability to supply memory from outside the page allocator to guest_memfd (PFN mode providers) directly inside guest_memfd, so Griffoul explained that a separate interface in mm was no longer needed.

| Item | mm memory provider RFC v2 (2026-10-14) | guest_memfd export RFC (2026-10-27) |
| --- | --- | --- |
| Where the interface lives | mm | guest_memfd (KVM) |
| File that iommufd maps | Provider file exposed by a driver | guest_memfd file |
| Target memory | Driver memory outside the page allocator (including outside VMs) | VM memory |
| How mappings are updated | The driver signals a revoke | guest_memfd reports page changes (private conversion, punch hole, revoke) through a callback, and iommufd remaps the affected range |

The iommufd part of the new series is a demonstration that tests the interface. Real support will come as a separate iommufd series once the generic_pt work that Gunthorpe asked for on v2 (splitting and merging large IOPTEs) is in place.

Around the same time, Aneesh Kumar of Arm posted an RFC that uses a vfio-pci BAR as a guest_memfd provider (v1 on 10-10, v2 on 10-17). It connects device MMIO to a VM, and it blocks vfio-pci dma-buf exports while a provider is attached.

With this switch, no posted series lets a driver outside a VM map its own memory into iommufd anymore. A CUDA allocation is not guest_memfd, so we infer that this series does not apply to NVMe DMA into CUDA memory.

#### History

Dates in the history table are in UTC.

| Date | Event | Source |
| --- | --- | --- |
| 2026-02-25 | Kardashevskiy, RFC for guest_memfd mapping in iommufd | [mail](https://lore.kernel.org/all/20260225075211.3353194-1-aik@amd.com/) |
| 2026-07-16, 07-20 | Woodhouse, guest_memfd PFNMAP provider RFC v1 and v2 (iommufd connection through dma-buf) | [v1](https://lore.kernel.org/all/20260716151706.244987-1-dwmw2@infradead.org/), [v2](https://lore.kernel.org/all/20260720111259.122911-1-dwmw2@infradead.org/) |
| 2026-09-26 | Ackerley Tng, guest_memfd resource fd RFC v1 with 17 patches | [mail](https://lore.kernel.org/all/20260925-gmem-tmpfs-backend-v1-0-d36159822d18@google.com/) |
| 2026-10-01 | Gunthorpe in the Ackerley RFC v1 thread: "not add more of the hack mess I made for vfio/iommufd" | [mail](https://lore.kernel.org/all/20261001171501.GD3019323@ziepe.ca/) |
| 2026-10-05 | Griffoul, RFC that backs guest_memfd with a dma-buf (includes `get_phys()`). König NAKed it the same day, and in another mail said an exporter-specific private interface is fine | [RFC](https://lore.kernel.org/all/20261005095552.52748-1-griffoul@gmail.com/), [König NAK](https://lore.kernel.org/all/a04f17cc-f59a-4240-81c8-29776eee3a2e@amd.com/), [König](https://lore.kernel.org/all/f0077cec-10fe-400a-b229-f7434e297364@amd.com/) |
| 2026-10-06 | Griffoul, mm memory provider RFC v1 with 9 patches | [mail](https://lore.kernel.org/all/20261006183235.16576-1-griffoul@gmail.com/) |
| 2026-10-10, 10-17 | Aneesh Kumar, guest_memfd device MMIO RFC v1 and v2 | [v1](https://lore.kernel.org/all/20261010072504.536230-1-aneesh.kumar@kernel.org/), [v2](https://lore.kernel.org/all/20261017073149.1303738-1-aneesh.kumar@kernel.org/) |
| 2026-10-12 | Gunthorpe in the `get_phys()` RFC thread: "I don't want to hardwire every exporter into iommufd". Griffoul dropped the idea of an exporter registry in iommufd | [Gunthorpe](https://lore.kernel.org/all/20261012144616.GF14213@ziepe.ca/), [Griffoul](https://lore.kernel.org/all/20261012152946.63489-1-griffoul@gmail.com/) |
| 2026-10-14 | Griffoul, RFC v2 with 11 patches. Accepts provider files as `resource_fd` and adds a patch that maps large IOMMU pages | [mail](https://lore.kernel.org/all/20261014093733.90312-1-griffoul@gmail.com/) |
| 2026-10-16 | Gunthorpe on the large page patch: generic_pt needs a cut operation and a matching unmap. Griffoul replied that v3 will drop it | [Gunthorpe](https://lore.kernel.org/all/20261016001448.GC14213@ziepe.ca/), [Griffoul](https://lore.kernel.org/all/20261016094610.57849-1-griffoul@gmail.com/) |
| 2026-10-21 | In reply to a question about hole tracking from Samiullah Khawaja (Google), Gunthorpe set iommupt and a hole-aware unmap as conditions | [mail](https://lore.kernel.org/all/20261021234647.GA3381610@ziepe.ca/) |
| 2026-10-22 | Ackerley Tng, guest_memfd alternative providers RFC v2 with 50 patches. Puts provider operations inside guest_memfd | [mail](https://lore.kernel.org/all/20261022-gmem-alternative-providers-v2-0-5dd1dc6c660a@google.com/) |
| 2026-10-27 | Griffoul, guest_memfd export RFC with 14 patches. Drops the mm interface, and iommufd maps guest_memfd files | [mail](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/) |

### 5.4 Design Comparison

| Item | Current vfio path | `iommu_map_pa` | mapping types (PAL RFC, later importer type) | mm provider (RFC v2, stopped) |
| --- | --- | --- | --- | --- |
| Exporters covered | vfio-pci only | No limit (user space supplies the physical addresses) | Any driver that implements the protocol | Any driver that exposes a provider file |
| Who checks the physical addresses | vfio-pci | Nobody | Exporter | Provider |
| pin / revoke | pin + revoke | Neither | pin + revoke | revoke only |
| IOVA accounting and locking | iommufd | Bypassed | iommufd | iommufd |
| What NVIDIA must do | Not possible | Nothing | Implement an exporter for the new type | Implement a provider file |
| Status (2026-10-29) | Merged | Works, not safe | Scheme in a formal series, iommufd connection not posted | Stopped (2026-10-27, replaced by guest_memfd export) |

All four approaches insert the GPU BAR1 physical addresses into the NVMe device's IOMMU domain with the `IOMMU_MMIO` attribute. The entry size differs by design (see the last paragraph below), and the other differences lie in who vouches for the physical addresses and who manages the lifetime of the mapping.

With `iommu_map_pa`, the kernel inserts the physical addresses that user space found through `dmabuf_import` into the domain without checking them. If an address is wrong, or the buffer is repurposed in the meantime, the kernel cannot tell. Because the module writes to the domain directly outside iommufd, user space is also responsible for keeping the IOVA from overlapping other iommufd mappings and for removing the mapping before the device leaves the domain. upcie 0.9.0 already provides `dmamem_iommu_map_pa_reserve_window()`, which reserves this window in the IOAS to prevent overlaps. In the other three approaches, the driver that owns the memory (vfio-pci, the exporter or the provider) supplies the physical addresses, so the owner is responsible for their validity, and iommufd handles IOVA allocation and mapping tracking.

Whether an approach uses pin, revoke or both decides what the memory owner can do while the mapping exists. The importer prevents the buffer from moving with pin, and the owner takes back access with revoke, at which point the importer removes its mapping. The current vfio path and mapping types use both, so the buffer stays fixed while it is mapped, but the owner can still take it back in cases such as a device reset. The mm provider uses only revoke without pin, so the owner can take frames back at any time, and iommufd removes the affected range from the IOMMU as soon as it receives the notification. `iommu_map_pa` holds a dma-buf reference while the mapping exists, so the memory remains even after `cuMemFree`, which the PoC confirmed. However, `iommu_map_pa` has no way to receive a revoke notification.

From the NVIDIA side, the current vfio path accepts only dma-bufs exported by vfio-pci, so there is nothing the NVIDIA driver can do. If mapping types are adopted, NVIDIA needs to implement an exporter that provides the BAR1 range list, which is what the PoC did with its PAL exporter. CUDA applications keep using the dma-buf fd from `cuMemGetHandleForAddressRange()` as they do today. Under mm provider RFC v2, NVIDIA would have had to implement a new provider file that hands out and takes back frames, and CUDA applications would have had to use that file instead of a dma-buf (inferred). That direction stopped on 2026-10-27, when the mm interface was dropped (§5.3). The mapping granularity also differs. The PoC's PAL path mapped a 1 GiB buffer with 512 entries of 2 MiB, but mm provider v2 without its large page patch maps at `PAGE_SIZE` granularity and would create 262,144 entries of 4 KiB for the same buffer (by design, not measured).

### 5.5 Impact on the NVIDIA Driver

**Private connection for NVIDIA.** A separate path just for NVIDIA dma-bufs is unlikely (inferred). vfio-pci is connected to iommufd through a private function today, and one could imagine giving the NVIDIA driver the same kind of private function. However, the iommufd maintainer Gunthorpe wrote on 2026-10-01 "I want us to resolve this in the dmabuf code cleanly not add more of the hack mess I made for vfio/iommufd" ([mail](https://lore.kernel.org/all/20261001171501.GD3019323@ziepe.ca/)), and on 2026-10-12, in the `get_phys()` RFC thread, "I don't want to hardwire every exporter into iommufd" ([mail](https://lore.kernel.org/all/20261012144616.GF14213@ziepe.ca/)). We therefore infer that iommufd will be able to map NVIDIA dma-bufs only after a generic protocol is merged. This inference rests on these two mails from Gunthorpe, and we found no opinion from other maintainers.

**Protocol for the NVIDIA driver to implement.** What NVIDIA has to do depends on which design is adopted, and the table and explanation in §5.4 cover each design. Within the range we checked (§7), no upstream series covers NVIDIA or CUDA, but Gunthorpe mentioned on 2026-04-13 that user space drivers using GPU memory are one of the goals. We infer that if mapping types are adopted, the NVIDIA exporter will do the same job as the PoC's PAL exporter, based on the April compromise and the 2026-10-26 cover letter.

## 6. Next Steps

**Risk.** `iommu_map_pa` can cause wrong mappings or use-after-free if the domain changes or IOVAs overlap. It is used only for experiments and validation today, so the impact stays inside the test environment.

**Work items.** Until upstream settles, we keep using `iommu_map_pa`. In the meantime, we write the constraints for using this module safely (no domain changes, a reserved IOVA window, the order of mapping removal) into the operating procedure so that experiments do not change the domain or reuse an overlapping IOVA window. The IOVA window can be reserved with upcie's `dmamem_iommu_map_pa_reserve_window()`. When the iommufd importer type series is posted, we review whether the PoC's NVIDIA patch can move to that protocol, and when the series lands in iommufd for-next, we port it and rerun the PoC's correctness, throughput and lifetime tests. The actual switch away from `iommu_map_pa` happens only after the conditions under "Switch point" below are met. When Guanghui Feng's `IOMMU_GET_RECOMMENDED_RESERVATIONS` and `IOMMU_IOAS_RESERVE_IOVAS` are merged, xNVMe will query and reserve those ranges before choosing the GPU IOVA window. The io_uring dma-buf path (§3) is an alternative that drives the NVMe device with the kernel driver, so when v7.4-rc1 is out we will consider testing it by registering a CUDA dma-buf with xNVMe's io_uring backend on a system with the IOMMU enabled. If the passthrough series is merged, we add dma-buf fixed buffer registration to xNVMe's io_uring backends and then run the same test with the `io_uring_cmd` backend.

**Signals to watch.** We check the following every quarter. Items 1 and 2 are on the dma-buf side, 3 is on the mm and guest_memfd side, 4 is NVIDIA, 5 is iommufd itself, and 6 is the kernel path outside iommufd.

1. **Mapping type scheme in linux-next.** Look for `dma_buf_mapping_match` or `match_mapping` in linux-next. König objected to the new attach function, so `dma_buf_mapping_attach` may be renamed in v2. If the scheme is in, the base that the iommufd importer type needs is in place.
2. **iommufd importer type series posted.** Look on lore for dma-buf or iommufd series from Popple or Gunthorpe. Once it is posted, the way the dma-buf path connects to iommufd is being decided, so we review porting the PoC patch.
3. **Scope of the iommufd series on the guest_memfd side.** Check whether the separate iommufd series that Griffoul announced accepts only guest_memfd files or also other files exposed by drivers. If it accepts only guest_memfd, the dma-buf side is the only path left that applies to NVIDIA.
4. **NVIDIA driver response.** Check whether `nv-dmabuf.c` in open-gpu-kernel-modules releases gains exporter code for the new mapping type.
5. **iommufd UAPI comment change.** If "not a generic dma-buf import path" disappears from the `IOMMU_IOAS_MAP_FILE` comment in `include/uapi/linux/iommufd.h`, we conclude that iommufd accepts generic dma-bufs.
6. **dma-buf backed NVMe passthrough merged.** Check whether the Anuj Gupta series lands in the block or nvme tree. If it does, after adding dma-buf fixed buffer registration to xNVMe, GPU memory P2P can be tested with xNVMe's `io_uring_cmd` backend on aisio's kernel path.

**Switch point.** Work to replace `iommu_map_pa` with an upstream path starts after the iommufd connection protocol (the importer type, as things stand) is in linux-next, NVIDIA ships a driver that implements the protocol, and the kernel we use is at or above that version. Starting earlier risks redoing the work as upstream changes.

## 7. Unverified Items

Items marked "inferred" in this report are judgments that we could not confirm with source code or logs. The items with a defined next step are listed below.

| Unverified item | Next step |
| --- | --- |
| Whether NVIDIA dma-bufs are rejected at the symbol lookup or at the exporter check | Check `CONFIG_VFIO_PCI_DMABUF` in `/boot/config-7.0.0-34-generic` of the test server's distribution kernel, rerun the PoC's A0 test (calling `IOMMU_IOAS_MAP_FILE` on the distribution kernel) with the vfio-pci (vfio-pci-core) module loaded, and record the return value of `vfio_pci_dma_buf_iommufd_map` with a kprobe |
| A CUDA allocation has no CPU mapping (VMA) that points to BAR1 | Check `/proc/<pid>/maps` for the BAR1 range while `test_dmamem_cuda_iommu_map_pa_nvme_readwrite` runs |
| No upstream series covers CUDA or NVIDIA (linux-iommu and io-uring since 2026-01, dri-devel and kvm since mid 2026-09, linux-nvme since 2026-01, linux-block since 2026-06. Older linux-mm and linux-pci mail, linux-rdma and linaro-mm-sig not checked) | Fetch the remaining lists and periods and search again |
| Sashiko's claim that patch 15 of the formal series breaks the vfio dma-buf mapping in iommufd (a claim by an AI review) | Check the thread for replies, and if needed run the dma-buf tests of the iommufd selftests on a kernel with the series applied |
| Whether NVIDIA dma-bufs work on the io_uring dma-buf path (kernel nvme-pci importer), and whether the driver returns correct DMA addresses with the IOMMU enabled | On a v7.4-rc1 kernel, register a CUDA dma-buf with io_uring, read and write through a raw NVMe block device, and check the data and the IOMMU fault log |
| Whether the iommufd importer type will accept out-of-tree exporters, and whether the dma-buf core removes the IOMMU mapping on revoke | Read the exporter contract and the invalidate path when the series is posted |

Unmerged series may change in later versions. Quotes reflect the state as of October 29, 2026.
