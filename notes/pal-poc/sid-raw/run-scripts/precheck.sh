echo "== kernel"; uname -r; cat /proc/cmdline
echo "== secure boot"; mokutil --sb-state 2>&1
echo "== root fs"; findmnt -no SOURCE,FSTYPE /; lsblk -no NAME,TYPE,FSTYPE,MOUNTPOINT | head -30
echo "== host bridges"; lspci -nn | grep -i 'host bridge' | head
echo "== gpu"; nvidia-smi --query-gpu=name,pci.bus_id,driver_version --format=csv,noheader
echo "== nvidia dkms"; dkms status 2>&1 | grep -i -E 'nvidia|upcie'
echo "== nvidia src"; ls -d /usr/src/nvidia-* 2>&1
echo "== upcie"; ls -l /dev/dmabuf_import /usr/include/linux/dmabuf_import.h 2>&1
echo "== cuda"; ls -d /usr/local/cuda* 2>&1; ls /usr/local/cuda/include/cuda.h 2>&1
echo "== nvme"; for d in /sys/bus/pci/devices/*; do [ "$(cat $d/class)" = 0x010802 ] && echo "$(basename $d) node=$(cat $d/numa_node) driver=$(basename $(readlink -f $d/driver)) group=$(basename $(readlink $d/iommu_group)) groupsize=$(ls $d/iommu_group/devices | wc -l)"; done
echo "== nvme namespaces"; for n in /sys/class/nvme/nvme*; do echo "$(basename $n) $(basename $(readlink -f $n/device)) $(cat $n/model)"; done
echo "== mounts of nvme"; grep nvme /proc/mounts
echo "== gpu path"; readlink -f /sys/bus/pci/devices/0000:31:00.0
echo "== tools"; for c in gcc make bc flex bison pahole setpci git zstd; do command -v $c >/dev/null || echo "MISSING $c"; done
dpkg -l libcap-dev libelf-dev libssl-dev 2>/dev/null | awk '/^ii/{print $2}'
echo "== disk"; df -h /root /boot
echo "== iommu debugfs"; ls /sys/kernel/debug/iommu/intel 2>&1 | head -2
