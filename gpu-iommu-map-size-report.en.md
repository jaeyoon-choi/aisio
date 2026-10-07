# IOMMU Mapping Granularity of GPU Memory dma-bufs

Written 2026-09-18, updated 2026-09-29. Measured on the dev PC with the tools on branch `gpu-iommu-map-size` (`c46577e`). Section 7.5 carries over results measured on the same PC for a different purpose, as a cross-check.

## 1. Summary

**Question.** In the IOMMU overhead benchmark, GPU-memory buffers showed almost no performance difference whether the IOMMU was on or off. To explain why, we needed to know what page size the IOMMU uses to map the GPU window when an NVMe reads GPU memory over P2P DMA.

**Answer.** 2 MiB. One GiB of GPU memory goes into the IOMMU page table as 512 entries of 2 MiB. This was confirmed by reading the page size the kernel actually chose with kprobes. The earlier record only relied on a constant in the upcie-cuda source.

**Why not 1 GiB.** The mapping is a single 1 GiB call, and the hardware (VT-d) supports 1 GiB pages. But the kernel can only use the largest page to which both the IOVA and the physical address are aligned. The physical address of this GPU's BAR memory (0x480f600000) is only 2 MiB-aligned, so 2 MiB is the ceiling.

**Two conditions are needed for 2 MiB.**

- The mapping call must be at least 2 MiB. Paths that map in 64 KiB calls (GDS, BaM default mode, the older uPCIe test) all ended up with 4 KiB entries. For the same 1 GiB that is 262,144 entries instead of 512.
- The physical address must be 2 MiB-aligned. This PC's GPU met this condition in every run.

upcie-cuda, which the benchmark uses, maps in 2 MiB calls and so meets both conditions.

**Measurements.**

| Observation | Result |
|---|---|
| `iommu:map` tracepoint | One 1 GiB call, physical address 0x480f600000 |
| Pages the driver received (kprobe) | 2 MiB x 512 |
| Page-table level (kprobe) | Only level 2 (2 MiB) used, no level 3 (1 GiB) |
| Cross-check on another path (BaM, `dma_map_resource`) | 1 GiB as 2 MiB x 512, 4 GiB as 2 MiB x 2048 |
| Paths that map in 64 KiB calls | All 4 KiB entries |

**What it means for the benchmark.** The GPU window is mapped once at startup as 512 entries of 2 MiB, and the mapping does not change during I/O. So the benchmark result that the IOMMU costs almost nothing for GPU memory is consistent with the mapping structure. However, IOTLB misses were not measured directly. This measurement also cannot rule out that the PCIe link saturates first and hides the difference.

**Corrected earlier record.** The earlier record said "a dma-buf imported on behalf of the NVMe goes through NVIDIA's private path and is invisible to the kernel tracepoint". In fact, with the IOMMU on, it shows up as a single `iommu_map` call. It was most likely invisible before because sid was running with the IOMMU off or in passthrough at the time. The earlier record also took the 64 KiB pieces on the misc path to be the page size at which NVIDIA exports GPU memory. In fact the NVIDIA driver cuts the buffer by the receiving device's DMA max segment size, and the misc device sets none, so the kernel's 64 KiB default applies. This was confirmed in the kernel and NVIDIA driver sources.

**Not verified.** Three items were not verified.

- The same result was not re-run on the sid server.
- The benchmark's actual upcie-cuda mapping path was not traced directly with kprobes.
- IOTLB counters were not read.

**Branch changes.** Branch `gpu-iommu-map-size` was reduced to two commits: probe and trace. A single run of the trace task prints the page-size summary to the console. On a machine where the trace could not show the mapping, it stops with a reason before tracing. It records in a tracefs instance of its own, so the global tracing settings and anyone else's trace are left alone.

The sections below describe how the measurements were made and the evidence in detail.

## 2. Background and Question

The sister branch `iommu-overhead-gpu` has an IOMMU overhead benchmark. It prepares a buffer that NVMe SSDs move data into over DMA, then runs the same I/O with the IOMMU on and off and compares throughput. When the buffer was in GPU memory, the difference between the two conditions was close to zero.

An IOMMU is hardware that translates the DMA addresses a device sends into real physical addresses. Just as the CPU's MMU translates a process's virtual addresses, the IOMMU translates the addresses a device uses. These device-side addresses are called IOVAs (I/O virtual addresses). The kernel builds a page table per device that maps IOVAs to physical addresses, and the IOMMU walks this table for each incoming DMA. Translation results stay in a cache called the IOTLB, so a repeated DMA to the same page does not walk the table again. IOMMU overhead comes mostly from two places. One is the table walk on an IOTLB miss, and the other is the cost of creating and removing mappings.

Two explanations for the near-zero difference were possible.

- **Translation is cheap.** GPU memory is mapped with large pages, so a few IOTLB entries cover the whole buffer and misses are rare.
- **The link saturates first.** The GPU's PCIe link is the throughput ceiling, so both conditions saturate at the same point whether the IOMMU is on or off.

Whether the first explanation holds depends on the page size used for the mapping. The same 1 GiB buffer needs 262,144 translation entries with 4 KiB pages, 512 with 2 MiB pages, and just one with a 1 GiB page. The IOTLB is a cache of limited capacity, so a difference of hundreds of times in entry count greatly changes the miss rate.

The earlier session found the mapping-unit constant `DMAMEM_CUDA_REGISTRY_GRANULARITY` (2 MiB) in the upcie-cuda source and concluded "2 MiB". But upcie-cuda requesting mappings in 2 MiB units does not guarantee that the kernel uses 2 MiB pages, because the kernel can split a request into smaller pages. This report measures the page size the kernel actually used. To read the measurements, we first need to know how the kernel picks a page size.

## 3. IOMMU Page-Size Selection Rules

VT-d, Intel's IOMMU implementation, uses a multi-level page table like the CPU does. An entry at the lowest level (level 1) points to 4 KiB. An entry one level up (level 2) normally points to a lower table, but it can instead point directly to a 2 MiB region. An entry at the next level (level 3) can point directly to a 1 GiB region. The 2 MiB and 1 GiB pages are called superpages. Which superpages the hardware supports is recorded in the VT-d capability register, and this PC's VT-d reports support for both 2 MiB and 1 GiB.

When kernel code calls `iommu_map(iova, paddr, size)`, `iommu_pgsize()` in the kernel's common layer picks the page size first. It picks the largest size that meets all of three conditions.

1. The hardware must support the size. On this PC that is 4 KiB, 2 MiB, and 1 GiB.
2. It must not exceed the remaining size to map. A 2 MiB page cannot be used to map 64 KiB.
3. Both the IOVA and the physical address must be aligned to that size. If either one is not, the next smaller size is used.

The common layer then calls the Intel driver's `intel_iommu_map_pages()` in the form "this many pages of this size", and the driver writes the entries into the page table.

With real numbers it looks like this. This PC's GPU exposes its memory to other devices through an address window called PCIe BAR1. BAR1 is a 32 GiB window starting at physical address 0x4800000000. In this measurement, the 1 GiB buffer CUDA allocated landed at 0x480f600000, 246 MiB from the start of that window. 246 MiB is 123 times 2 MiB, so it is 2 MiB-aligned but not a multiple of 1 GiB.

| Case | IOVA | Physical address | Call size | Page the kernel picks |
|---|---|---|---|---|
| GPU buffer in this measurement | 0x3f80000000 (1 GiB-aligned) | 0x480f600000 (2 MiB-aligned) | 1 GiB | 2 MiB x 512 |
| If the physical address were the BAR1 start (hypothetical) | 0x3f80000000 (1 GiB-aligned) | 0x4800000000 (1 GiB-aligned) | 1 GiB | 1 GiB x 1 |
| Paths that map in 64 KiB calls | 64 KiB-aligned | 64 KiB-aligned | 64 KiB | 4 KiB x 16 |

In the first row the IOVA is 1 GiB-aligned but the physical address is only 2 MiB-aligned, so condition 3 caps it at 2 MiB. The second row is only what the rules predict and was not observed this time. The third row becomes 4 KiB because of condition 2, regardless of address alignment. 64 KiB is not a size VT-d supports, so it falls back to the smaller 4 KiB.

In short, GPU memory is mapped with 2 MiB pages only if two things hold. The mapping call must be at least 2 MiB, and the physical address of the GPU buffer must be 2 MiB-aligned. By these rules, this PC should produce 2 MiB. The following sections describe how we measured whether it does.

## 4. Measurement Method

### 4.1 Path That Maps the GPU Buffer for the NVMe

P2P (peer-to-peer) DMA is when an NVMe reads and writes GPU memory directly without going through CPU memory. For that, the GPU memory's BAR1 address has to be mapped into the NVMe's IOMMU page table.

This measurement creates that mapping with a dma-buf. A dma-buf is the Linux kernel's standard way for one driver to hand a buffer to another. The side that hands out the buffer is the exporter, and the side that receives it is the importer. Here the exporter is the NVIDIA driver and the importer is uPCIe's `dmabuf_import` kernel module. When importing, this module can choose which device the buffer is imported on behalf of.

The addresses are made in the kernel function `dma_buf_map_attachment()`. When the module calls it, the kernel passes the request to a callback in the exporter, the NVIDIA driver, which builds the address list in two steps (`nv_dma_buf_map_pfns()` in `nv-dmabuf.c`).

1. It cuts the physical range of the buffer by the receiving device's DMA max segment size. The device's driver sets this value, and a device that sets none uses the kernel's 64 KiB default.
2. For each piece it calls `dma_map_resource(receiving device, physical address, length)` to get the DMA address that device will use. If the receiving device sits behind an IOMMU, the kernel creates a mapping in that device's IOMMU page table and returns an IOVA. Without an IOMMU it returns the physical address as is.

The measurement program `dmabuf_import_probe` (the probe) allocates 1 GiB of GPU memory with CUDA, exports it as a dma-buf, and imports it back on behalf of two devices.

- **misc path**: imports on behalf of the module's own virtual device, not a real PCI device. This device is not behind an IOMMU and sets no max segment size, so it gets a list of physical addresses cut into 64 KiB. upcie-cuda imports on behalf of the misc device in the same way when it looks up the physical addresses of a GPU buffer.
- **`--bdf` path**: imports on behalf of the given NVMe (here 0000:02:00.0). The nvme driver sets the max segment size to about 4 GiB, so the buffer is not cut. With the IOMMU on, the kernel creates a real mapping in that NVMe's IOMMU page table. This path is what we measure.

upcie-cuda, which the benchmark uses, gets the physical address list through the misc path and then arranges it into a table of 2 MiB units. With the IOMMU on, it binds the NVMe to the vfio driver and maps those physical addresses in 2 MiB units through uPCIe's `iommu_map_pa` module. With the IOMMU off, it binds the NVMe to the uio driver and uses the GPU memory's physical addresses as is. Both paths end up calling the kernel's `iommu_map()`, so the rules of section 3 apply the same way. The benchmark path itself was not traced, and this is listed as a limitation in section 11.

### 4.2 Three Observation Layers

The mapping is observed at three layers. Higher layers are closer to user space, and lower layers are closer to the actual page table.

| Layer | Tool | What it shows |
|---|---|---|
| User space | Probe | `(address, length)` list returned by `dmabuf_import` |
| Kernel common layer | Tracepoints `iommu:map`, `iommu:unmap` | IOVA, physical address, and size of one `iommu_map()` call |
| Intel driver | kprobes `intel_iommu_map_pages`, `pfn_to_dma_pte` | Page size and count the kernel chose, page-table level |

A tracepoint is an observation point built into kernel code in advance. `iommu:map` logs one line each time `iommu_map()` is called. But the size in that line is the call size, not the page size. A single line for a 1 GiB call does not tell whether it is one 1 GiB page or 512 pages of 2 MiB.

So kprobes are added. A kprobe is an observation point attached dynamically to the entry of a kernel function, and it can read the function's arguments. They are attached to two functions.

- `intel_iommu_map_pages(domain, iova, paddr, pgsize, pgcount, ...)`: receives the page size (`pgsize`) and count (`pgcount`) the common layer picked. It shows the outcome of the section 3 rules directly.
- `pfn_to_dma_pte(domain, iov_pfn, &level, ...)`: the function the driver calls to find where to write an entry in the page table. It receives the level to write at as an argument. Level 1 is 4 KiB, 2 is 2 MiB, and 3 is 1 GiB. This function is not called per entry, only when a new table range starts, so the level value matters more than the call count.

The first kprobe shows what the kernel requested, and the second shows which level the driver actually wrote to. If they agree, the conclusion holds.

## 5. Test Environment

| Item | Value |
|---|---|
| Machine | Dev PC `jaeyoon-pc`, Intel Core i9-14900K |
| GPU | NVIDIA RTX PRO 4000 Blackwell, 0000:01:00.0, open kernel module 580.178.04, BAR1 32 GiB |
| Kernel | 6.8.12-dmabuf, `CONFIG_INTEL_IOMMU=y`, scalable mode on by default, `CONFIG_KPROBE_EVENTS=y` |
| IOMMU | Two VT-d units, 2 MiB and 1 GiB superpage support |
| NVMe | 0000:02:00.0, Samsung 980 PRO, spare disk, `nvme` driver |
| uPCIe modules | `upcie-experimental-dkms` 0.9.0 (`dmabuf_import`, `iommu_map_pa`) |
| CUDA | 12.8 (nvcc), driver reports CUDA 13.0 |
| Execution | cijoe 0.9.58, run locally as root without ssh |

The measurement tools were originally built to run on the server `sid`. To run them on this PC, we used a cijoe config without ssh settings and a copy of the task with the target NVMe changed to 0000:02:00.0. These copies were not added to the repo. A spare disk rather than the root disk was chosen as the target NVMe so that mappings created and removed during measurement would not affect the system disk.

## 6. Test Procedure

1. **IOMMU off baseline**: boot with `intel_iommu=off` and run the probe on the misc and `--bdf` paths. Run the trace task too. This step shows what the probe returns without translation and how the trace ends.
2. **Switch to IOMMU on**: change `/etc/default/grub` to `intel_iommu=on` and reboot. Do not add the passthrough option (`iommu=pt`), because in passthrough mode the IOVA is fixed to equal the physical address and no real translation mapping is created. After the reboot, confirm through sysfs that NVMe 0000:02:00.0 is in a translating domain (DMA-FQ).
3. **Tracepoint measurement**: run the probe on the `--bdf` path with `iommu:map` and `iommu:unmap` enabled, and save the full trace to a file.
4. **kprobe measurement**: run the same probe again with the two kprobes from section 4.2 attached.

The buffer size is 1 GiB in every step. Step 4 was first done with a hand-written script, then the kprobes were merged into the branch's trace task and rerun to confirm the same values.

## 7. Results

### 7.1 Address Lists Returned by the Probe

| Path | IOMMU off | IOMMU on |
|---|---|---|
| misc | 64 KiB x 16384, all contiguous, from 0x480f600000 (physical) | Same |
| `--bdf` | One 1 GiB segment, 0x480f600000 (physical) | One 1 GiB segment, 0x3fc0000000 (IOVA) |

The misc path returns physical addresses in 64 KiB units regardless of IOMMU state. 64 KiB is not a property of GPU memory. It is the kernel default that applies because the misc device sets no DMA max segment size. The misc device is not behind an IOMMU, so this list has nothing to do with the IOMMU mapping.

The `--bdf` path returns physical addresses with the IOMMU off and IOVAs with it on. The address changing to 0x3fc0000000 with the IOMMU on is itself proof that a new mapping was created in the NVMe's IOMMU page table. It comes back as one segment not because pieces were merged later. The nvme driver sets the max segment size to about 4 GiB, so the NVIDIA driver handed over the whole 1 GiB as one piece from the start. Appearing as one segment does not mean it is a single 1 GiB page, though. The next two layers check that.

### 7.2 Tracepoint

With the IOMMU off there were no map or unmap events at all. With the IOMMU on, 5327 events were recorded while the probe ran, with no buffer loss. Of these, the two lines for the GPU buffer are below.

```
map:   iova=0x3fc0000000 - 0x4000000000 paddr=0x480f600000 size=1073741824
unmap: iova=0x3fc0000000 - 0x4000000000 size=1073741824   (6 us later)
```

The `--bdf` import showed up as a single `iommu_map()` call of 1 GiB. The unmap follows right away because the probe releases the buffer as soon as it reads the addresses.

The remaining events are unrelated to the GPU buffer. Most of them are host memory that CUDA mapped for the GPU during initialization. 4 KiB was the most common with 4324 events, followed by 4 events of 2 MiB and a few between several MiB and 40 MiB. This mix differed from run to run. Mappings created at the same time by other devices (wireless LAN, the file system journal, and so on) are also mixed in.

### 7.3 kprobes

| Observation | Value |
|---|---|
| `intel_iommu_map_pages` | iova=0x3f80000000 paddr=0x480f600000 pgsize=2097152 pgcount=512 |
| `pfn_to_dma_pte`, inside the GPU buffer's IOVA range | 2 calls at level 2, 0 calls at level 3 |

The 1 GiB call reached the driver as "512 pages of 2 MiB", and the driver wrote entries at level 2. No call wrote at level 3 (1 GiB). This is exactly what the first row of the section 3 table predicted.

The IOVA differs from section 7.2 (0x3fc0000000) because the IOVA allocator hands out a different spot each run. Both values are 1 GiB-aligned and the physical address is the same, so the result is unaffected.

### 7.4 kprobe Record Checks and Findings

The kprobe values are function arguments read by argument slot (`$arg2` to `$arg5`). The argument order can change between kernels, so values that merely look plausible cannot be trusted. The trace task therefore checks the kprobe records against independent observers before it reports any findings, and the task fails if any check disagrees.

| Check | Compared against | Result on this PC |
|---|---|---|
| Page sizes are VT-d sizes | 4 KiB, 2 MiB, 1 GiB | 2 MiB, pass |
| Pages cover the whole call | pgsize x pgcount, tracepoint size, probe length | 1 GiB each, pass |
| Calls follow each other | IOVA and physical address of consecutive `map_pages` calls | one call, pass |
| Physical address agrees | kprobe paddr, tracepoint paddr, first physical address on the probe's misc path | 0x480f600000 each, pass |
| Level matches page size | `pfn_to_dma_pte` level and the level for pgsize | level 2, pass |

Wrong argument slots cannot pass these checks. For example, a record with pgsize and pgcount swapped fails the first and the fifth check. The findings logic was tested with several doctored records, including that one.

When every check passes, the task reports its findings. This is the output of a real run on this PC.

```
mapping: 1 GiB as 512 x 2 MiB
page size: 2 MiB, capped because IOVA 0x3f80000000 (2 GiB-aligned) and physical 0x480f600000 (2 MiB-aligned) line up only on 2 MiB boundaries
translations to cover the buffer: 512
```

The findings compute the rules of section 3 directly. A page of size P needs the IOVA and physical address to differ by a multiple of P, and needs a P-aligned block of size P to fit in the range. If the page used is smaller than those two conditions allow, the findings say the IOMMU or this domain offers no larger page. If it is the same, it names what set that size.

### 7.5 Cross-Check on Other Mapping Paths

There are results measured on 2026-09-22 and 09-23 on the same PC, same kernel, and same NVMe for a different purpose (collecting evidence for a patent). The method was the same `intel_iommu_map_pages` kprobe and `iommu:map` tracepoint. Only the two results relevant to this report's conclusion are carried over.

The first checks whether a path that bypasses dma-buf gives the same result. The kernel module (`libnvm.ko`) of BaM, a GPU-based storage framework, was modified to map the whole GPU memory pool with a single `dma_map_resource()` call.

| Pool size | Physical address | IOVA | Pages the driver received |
|---|---|---|---|
| 1 GiB | 0x480f600000 | 0x3f40000000 (1 GiB-aligned) | 2 MiB x 512 |
| 4 GiB | 0x480f600000 | 0x3d00000000 (1 GiB-aligned) | 2 MiB x 2048 |
| 1 GiB, allocated after fragmenting GPU memory | 0x490f600000 | 0x3f40000000 (1 GiB-aligned) | 2 MiB x 512 |

In all three cases the IOVA was 1 GiB-aligned and the physical address was only 2 MiB-aligned. The result was 2 MiB every time, and no 1 GiB page ever appeared. Even after deliberately fragmenting GPU memory, the physical address still ended in 0x...0f600000. On this GPU, the buffer start repeatedly sits 246 MiB past a 1 GiB boundary.

The second covers paths that map in 64 KiB calls. GPU Direct Storage (GDS), BaM default mode, and the older uPCIe GPU test fall into this group. These paths called `iommu_map()` only with a size of 64 KiB for GPU memory. The uPCIe test and GDS mapped 128 MiB in 2048 calls, and BaM default mode mapped about 4 MiB in 66 calls. As in the third row of the section 3 table, each of these calls became 16 entries of 4 KiB.

## 8. Interpretation

### 8.1 Measurements Against the Rules

The measurements matched the section 3 rules in every case.

| Case | Page predicted by the rules | Page measured |
|---|---|---|
| dma-buf `--bdf`, one 1 GiB call | 2 MiB | 2 MiB x 512 |
| BaM `dma_map_resource`, one 1 GiB or 4 GiB call | 2 MiB | 2 MiB x 512, 2 MiB x 2048 |
| GDS, BaM default, older uPCIe test, 64 KiB each | 4 KiB | 4 KiB |

So the 2 MiB result does not come from the constant upcie-cuda chose. It is set by the physical address where this GPU places the buffer. Had upcie-cuda requested mappings in 1 GiB units, they would still have been split into 2 MiB at this address, and the BaM experiment shows exactly that case. Conversely, had upcie-cuda requested 64 KiB units, it would have ended up with 262,144 entries of 4 KiB. upcie-cuda's 2 MiB unit is a choice that does not miss the largest page this GPU can get.

### 8.2 What It Means for the Benchmark

upcie-cuda maps the whole GPU buffer at once when the benchmark starts and does not change the mapping during I/O. This behavior was confirmed by reading the upcie-cuda code. So the only IOMMU cost during I/O is translation, and there is no cost for creating and removing mappings.

Translation is also likely cheap. The whole 1 GiB buffer is covered by 512 entries of 2 MiB, so as long as I/O repeatedly hits part of the buffer, IOTLB misses become rare after the first few. With the IOMMU off (uio) there is no translation at all. The difference between the two conditions is about the initial period while the IOTLB fills, which is unlikely to show up in the steady-state throughput the benchmark measures.

That is, the first explanation in section 2 (translation is cheap) is consistent with the mapping structure. But this is inferred from the mapping structure, not a measurement of IOTLB misses. This measurement also cannot rule out that the second explanation (the link saturates first) is true at the same time. Ways to separate the two are listed in section 11.

## 9. Differences From the Earlier Record

| Earlier record | This measurement |
|---|---|
| The `--bdf` path goes through NVIDIA's private dma-buf path and is invisible to `iommu:map` | With the IOMMU on, it shows up as a single `iommu_map()` call |
| The `--bdf` address list is a 1 GiB BAR physical address | With the IOMMU on it is an IOVA. A physical address means the IOMMU was off or in passthrough |
| The 64 KiB on the misc path is NVIDIA's export page size, and on the `--bdf` path the kernel merges these pieces into 1 GiB | 64 KiB is the misc device's DMA max segment size, the kernel default. The NVMe's value is large, so the NVIDIA driver hands over one piece from the start |
| CUDA initialization maps in 2 MiB-aligned units | Sizes vary per run and 4 KiB dominates. Not reproduced |
| The basis for the 2 MiB mapping unit is the upcie-cuda constant | The page size the kernel chose was observed directly with kprobes |

The first row matters most. The earlier record observed that the `--bdf` import did not show up in the tracepoint on sid and interpreted this as "NVIDIA bypasses the kernel". But in this measurement it showed up once the IOMMU was on and disappeared once it was off. It was most likely invisible on sid because sid was running with the IOMMU off or in passthrough at the time. The record that sid's `--bdf` result was a physical address supports this.

The wrong reading in the third row came from treating the piece size on each path as a property of GPU memory. The NVIDIA driver source shows that the receiving device decides the piece size. The same buffer went to the misc device in 64 KiB pieces and to the NVMe in one piece because the two devices are set up differently.

## 10. Changes Made on the Branch

The branch was reduced to two commits on top of main. Every problem found during measurement is fixed in these two commits. A survey task that lists a target's tracepoints and IOMMU groups was also written but left out of the PR, because the trace task checks the conditions a trace needs more precisely, for the device it traces.

| Commit | Content | Problems fixed during measurement |
|---|---|---|
| `1938442` feat(bench): probe how a CUDA dma-buf is mapped for an NVMe | Probe C source, runner script, task | Marked the allocation granularity output as unrelated to `cuMemAlloc`. Replaced the `GET_MAP` count check with a cross-check against the `DESCRIBE` segment count. Made the target's temporary path a fresh directory per run. Corrected the explanation of the 64 KiB pieces. Check each import for full coverage, device memory, and the segment count, and fail on disagreement. Report whether the `--bdf` import is translated by the IOMMU by comparing it with the misc path's physical address |
| `c46577e` feat(bench): trace the IOMMU page size behind a GPU dma-buf mapping | Trace script and task | Corrected the docs that said "invisible to the tracepoint". Raised the console filter from 64 KiB to 2 MiB. Two kprobes record the page size, which is checked against the other observers before the task reports the mapping unit and its cause as findings. Fail on disagreement. The summary counts only the probe process's lines. Stop before tracing on a malformed bdf, no IOMMU, a passthrough domain, or a driver other than nvme. Use a tracefs instance of its own and per-run kprobe names, and remove both afterward. Run the probe under a timeout. Drop the measurement narrative from the code docs. Take the NVMe from the dataset device in `configs/datasets.toml` instead of hardcoding it |

A single run of `tasks/trace_iommu_gpu.yaml` now produces the results of sections 7.2 and 7.3 together. The function names the kprobes attach to are those of Linux 6.8. If registration fails on another kernel, only the summary is dropped and the rest still runs.

## 11. Not Verified and Next Steps

- **Re-check on sid**: the same trace was not run on sid with the IOMMU on. The explanation in section 9 is an inference from circumstantial evidence. Booting sid with `intel_iommu=on` (no passthrough) and running the trace task once would confirm it.
- **1 GiB superpages**: no 1 GiB page appeared in any run. This is because the physical address of this GPU's buffer was 246 MiB past a 1 GiB boundary every time. The hardware supports 1 GiB, so a GPU whose buffer lands at a 1 GiB-aligned address could give a different result. This was not checked on such a GPU.
- **Benchmark path**: the path upcie-cuda actually uses (`iommu_map_pa_add`, `/dev/iommu_map_pa`) was not traced directly. The uPCIe path traced in section 7.5 is the older 64 KiB test, not the benchmark path. It calls the same `iommu_map()`, so the same rules should apply, but attaching the same kprobes while running the benchmark would confirm it directly.
- **IOTLB misses**: the IOTLB discussion in section 8.2 is inference. IOTLB miss counters were not read. The kernel has VT-d performance counter support (`CONFIG_INTEL_IOMMU_PERF_EVENTS`) enabled, but no perf event device (`dmar*`) appears on this PC. This PC's VT-d appears not to report counters. The next step is to check whether counters show up on sid.
- **Link saturation**: the second explanation in section 2 was not tested. Comparing IOMMU on and off at small I/O sizes or low queue depths, where the PCIe link does not saturate, would show whether the link was hiding a difference.

## 12. Data Locations

- The raw output of this measurement (probe, trace, kprobe trace), the local run configs, and the kprobe prototype script are in `/data/aisio/results-jaeyoon-pc/gpu-iommu-map-size/`.
- The raw logs and scripts for section 7.5 are in `/data/aisio/upcie-doc/patent/exp/`. The BaM single mapping is in `bam-probe-single-range-2026-09-22.txt`, and the per-path mapping call counts are in `iommu-map-count-2026-09-23.txt`. The BaM module change that adds the `single_range` option sits uncommitted in `/data/aisio/bam`.
- The kernel source basis for the section 3 rules is `iommu_pgsize()` in `/usr/src/linux-source-6.8.0/drivers/iommu/iommu.c`, and `hardware_largepage_caps()` and `__domain_mapping()` in `drivers/iommu/intel/iommu.c`.
- The piece sizes in section 4.1 rest on three places. The NVIDIA driver cuts the buffer in `nv_dma_buf_map_pfns()` in `/usr/src/nvidia-580.178.04/nvidia/nv-dmabuf.c` and calls `dma_map_resource()` from `nv_dma_map_peer()` in `nv-dma.c`. The kernel's 64 KiB default is in `dma_get_max_seg_size()` in `include/linux/dma-mapping.h`. The nvme driver's setting is `dma_set_max_seg_size(&pdev->dev, 0xffffffff)` in `drivers/nvme/host/pci.c`.
- The code where upcie-cuda gets physical addresses through the misc device is the `dmabuf_import_attach()` call in `/data/aisio/xnvme/toolbox/third-party/linux/upcie/dmamem_cuda.h`.
- The branch is `jaeyoon/gpu-iommu-map-size`, and the worktree is `/data/aisio/aisio/.claude/worktrees/gpu-iommu-map-size`.
