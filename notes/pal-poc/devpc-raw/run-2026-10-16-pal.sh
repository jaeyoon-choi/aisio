#!/bin/sh
# Dev PC re-measurement on the unmodified PAL kernel with the fixed pal_nvme.
# Run as root after booting 7.0.0-rc1-pal+ (original image, not the SNP one).
# Uses only LBA 0..383 of the spare NVMe 0000:02:00.0.
set -x
cd /data/aisio/pal-poc
S=/data/aisio/aisio/.claude/worktrees/iommufd-gpu-memory/notes/pal-poc/scripts
echo "== $(date) $(uname -a)"
cat /proc/cmdline
md5sum /boot/vmlinuz-7.0.0-rc1-pal+ /boot/vmlinuz-7.0.0-rc1-pal+.snp-orig
cat /sys/kernel/iommu_groups/*/type 2> /dev/null | sort | uniq -c
dmesg -C
modprobe dmabuf_import
modprobe iommu_map_pa
lsmod | grep -E "^(nvidia|dmabuf_import|iommu_map_pa) "
./bind-nvme-vfio.sh jaeyoon || exit 1
cat /sys/bus/pci/devices/0000:02:00.0/iommu_group/type
echo "#### pal_probe + PTE"
./pal_probe --vfio /dev/vfio/devices/vfio0 --hold 15 &
sleep 8
sh $S/pte-dump.sh 0000:02:00.0
wait
for X in 65536 4096; do
  echo "#### fixed CC, vfio, xfer $X"
  ./pal_nvme --xfer $X
  echo "#### fixed CC, identity IOVA, xfer $X"
  ./pal_nvme --identity --xfer $X
done
echo "#### buggy CC, vfio, xfer 65536"
./pal_nvme.ccbug --xfer 65536
echo "#### dmesg"
dmesg | grep -i -E 'dmar|iommu|vfio|nvme|AER' | tail -40
for d in 00:01.0 00:01.1 01:00.0 02:00.0; do echo "$d: $(lspci -vv -s $d | grep -E 'Status:|DevSta:' | tr -s ' ' | tr '\n' ' ')"; done
echo "== done $(date)"
