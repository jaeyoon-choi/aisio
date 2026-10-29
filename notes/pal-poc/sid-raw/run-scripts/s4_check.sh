echo "== device state now =="
D=/sys/bus/pci/devices/0000:4e:00.0
echo "driver=$(basename $(readlink -f $D/driver)) group=$(basename $(readlink $D/iommu_group)) type=$(cat /sys/kernel/iommu_groups/$(basename $(readlink $D/iommu_group))/type)"
echo "hugepages_free=$(awk '/HugePages_Free/{print $2}' /proc/meminfo)"
ls /dev/nvme2n1 2>&1
echo "== dmesg since test (nvme/DMAR/AER) =="
dmesg | grep -iE 'nvme|DMAR|AER|iommu|4e:00' | tail -25
echo "== nvme2 model/fw =="
ls /sys/class/nvme/nvme2/ 2>/dev/null | head
cat /sys/class/nvme/nvme2/model /sys/class/nvme/nvme2/firmware_rev 2>/dev/null
