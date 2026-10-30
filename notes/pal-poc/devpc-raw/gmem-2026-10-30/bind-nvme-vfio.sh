#!/bin/sh
# Bind the spare NVMe (0000:02:00.0) to vfio-pci and hand the device nodes
# and a tracefs instance to the given user so the PoC runs without sudo.
# Run as root on the 7.3.0-rc7-gmem+ kernel: sudo ./bind-nvme-vfio.sh jaeyoon
set -e
USER_NAME=${1:-jaeyoon}
BDF=0000:02:00.0
DEV=/sys/bus/pci/devices/$BDF
[ "$(uname -r)" = "7.3.0-rc7-gmem+" ] || { echo "not the gmem kernel"; exit 1; }
# refuse if this NVMe holds a mounted filesystem
if [ -d $DEV/nvme ]; then
    for n in $DEV/nvme/*/; do
        for ns in $n/nvme*n*; do
            [ -e "$ns" ] && grep -q "^/dev/$(basename $ns)" /proc/mounts && { echo "$(basename $ns) is mounted"; exit 1; }
        done
    done
fi
modprobe vfio-pci
if [ -e $DEV/driver ] && [ "$(basename $(readlink $DEV/driver))" != "vfio-pci" ]; then
    echo $BDF > $DEV/driver/unbind
fi
echo vfio-pci > $DEV/driver_override
echo $BDF > /sys/bus/pci/drivers_probe
echo "driver: $(basename $(readlink $DEV/driver))"
GROUP=$(basename $(readlink $DEV/iommu_group))
modprobe nvidia
modprobe nvidia-uvm
modprobe dmabuf_import
modprobe iommu_map_pa
modprobe kvm_intel
modprobe gpu_gmem_provider
chown $USER_NAME /dev/iommu /dev/dmabuf_import /dev/iommu_map_pa /dev/kvm /dev/gpu_gmem_provider
chmod 600 /dev/iommu /dev/dmabuf_import /dev/iommu_map_pa /dev/gpu_gmem_provider
[ -e /dev/vfio/$GROUP ] && chown $USER_NAME /dev/vfio/$GROUP
ls /dev/vfio/devices/ 2>/dev/null | while read d; do chown $USER_NAME /dev/vfio/devices/$d; done
# tracefs instance for iommu:map / kprobes
mkdir -p /sys/kernel/tracing/instances/gmem
chown -R $USER_NAME /sys/kernel/tracing/instances/gmem
chown $USER_NAME /sys/kernel/tracing/kprobe_events /sys/kernel/tracing/uprobe_events 2>/dev/null || true
ls -la /dev/iommu /dev/vfio/$GROUP /dev/vfio/devices/* /dev/dmabuf_import /dev/iommu_map_pa /dev/kvm /dev/gpu_gmem_provider 2>/dev/null
echo "group $GROUP, vfio cdev: $(ls $DEV/vfio-dev 2>/dev/null)"
