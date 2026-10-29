echo "== host bridges (full)"
lspci -nn | grep -iE 'host bridge'
echo "== 09a2 count"
lspci -nn | grep -ci 09a2
echo "== root complexes"
ls -d /sys/devices/pci*  2>/dev/null
echo "== debugfs"
mount | grep -i debug || echo "(no debugfs mount)"
ls -ld /sys/kernel/debug 2>&1
echo "== dataset device check (0000:4d:00.0) — read only"
ls -l /sys/bus/pci/devices/0000:4d:00.0/
echo "== nvme table"
for n in $(ls -d /sys/class/nvme/nvme* 2>/dev/null | sort -V); do
  name=$(basename "$n"); dev=$(basename "$(readlink -f "$n/device")")
  base=/sys/bus/pci/devices/$dev
  node=$(cat "$base/numa_node")
  grp=$(basename "$(readlink "$base/iommu_group")")
  gs=$(ls "$base/iommu_group/devices" | wc -l)
  ns=/dev/${name}n1
  size=$(blockdev --getsize64 "$ns" 2>/dev/null)
  mnt=$(grep -c "$ns" /proc/mounts)
  echo "$name $dev node=$node group=$grp groupsize=$gs ns=$ns bytes=$size mounted=$mnt"
done
echo "== candidates partition layout (node0, groupsize=1, not 4d)"
for n in $(ls -d /sys/class/nvme/nvme* 2>/dev/null | sort -V); do
  name=$(basename "$n"); dev=$(basename "$(readlink -f "$n/device")")
  [ "$dev" = "0000:4d:00.0" ] && continue
  [ "$(cat /sys/bus/pci/devices/$dev/numa_node)" = "0" ] || continue
  [ "$(ls /sys/bus/pci/devices/$dev/iommu_group/devices | wc -l)" = "1" ] || continue
  echo "--- $name ($dev) rootport=$(basename $(readlink -f /sys/bus/pci/devices/$dev/..))"
  lsblk -o NAME,SIZE,TYPE,FSTYPE,PARTTYPENAME,MOUNTPOINT /dev/${name}n1 2>/dev/null
  nvme id-ns /dev/${name}n1 2>/dev/null | grep -E '^nsze|^ncap|^lbaf' | head -3
  blkid /dev/${name}n1 2>/dev/null || echo "(no blkid signature)"
done
