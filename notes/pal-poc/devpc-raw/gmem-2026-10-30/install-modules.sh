#!/bin/sh
# Install the out-of-tree modules for the guest_memfd export kernel.
# Run as root. Booting that kernel is not needed.
set -e
KVER=7.3.0-rc7-gmem+
EXTRA=/lib/modules/$KVER/extra
mkdir -p $EXTRA/nvidia $EXTRA/upcie $EXTRA/gmem-poc
for m in nvidia nvidia-uvm nvidia-modeset nvidia-drm; do
    install -m 644 /data/nvidia-580-gmem/$m.ko $EXTRA/nvidia/
done
install -m 644 /data/upcie-exp-gmem/dmabuf_import/dmabuf_import.ko $EXTRA/upcie/
install -m 644 /data/upcie-exp-gmem/iommu_map_pa/iommu_map_pa.ko $EXTRA/upcie/
install -m 644 /data/gmem-poc/gpu_gmem_provider/gpu_gmem_provider.ko $EXTRA/gmem-poc/
depmod -a $KVER
