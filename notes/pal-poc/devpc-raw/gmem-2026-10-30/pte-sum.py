import collections
import sys

# Summarize the VT-d leaves in a domain_translation_struct dump by IOVA
# region. The last field of a line is the leaf: a PDE with the PS bit (0x80)
# maps 2 MiB, a PTE maps 4 KiB. pal_nvme puts the host buffer at IOVA
# 0x200000 (8 MiB), the guest_memfd or PAL mapping at 0xa00000 and the
# iommu_map_pa mapping at 256 GiB.
for path in sys.argv[1:]:
    regions = collections.OrderedDict()
    for line in open(path):
        f = line.replace("|", " ").split()
        if not f or not f[0].startswith("0x"):
            continue
        pfn = int(f[0], 16)
        leaf = int(f[-1], 16)
        if pfn < 0xA00:
            region = "host"
        elif pfn < 0xA00 + 0x40000:
            region = "gpu at 0xa00000"
        elif pfn >= 0x4000000:
            region = "gpu at 256 GiB"
        else:
            region = "other"
        r = regions.setdefault(region, dict(n=0, size=collections.Counter(), low=collections.Counter(), first=None, last=None))
        r["n"] += 1
        r["size"]["2M" if leaf & 0x80 else "4K"] += 1
        r["low"][hex(leaf & 0xFFF)] += 1
        if r["first"] is None:
            r["first"] = (pfn, leaf)
        r["last"] = (pfn, leaf)
    print("##", path.split("/")[-1])
    for k, r in regions.items():
        print(
            f"  {k}: leaves {r['n']}, sizes {dict(r['size'])}, low bits {dict(r['low'])}, "
            f"first pfn {r['first'][0]:#x} -> {r['first'][1]:#018x}, last pfn {r['last'][0]:#x} -> {r['last'][1]:#018x}"
        )
