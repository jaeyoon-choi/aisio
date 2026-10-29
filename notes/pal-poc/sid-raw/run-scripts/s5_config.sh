cd /root/pal-poc/linux-pal || exit 1
set -e
cp /boot/config-$(uname -r) .config
modprobe vfio-pci; modprobe uio_pci_generic; modprobe dm_mod
make olddefconfig >/dev/null 2>&1
yes '' | make localmodconfig >/dev/null 2>&1
./scripts/config --set-str LOCALVERSION "-pal" \
  --set-str SYSTEM_TRUSTED_KEYS "" --set-str SYSTEM_REVOCATION_KEYS "" \
  -e IOMMUFD -e IOMMU_PT_AMDV1 -e FAULT_INJECTION -e IOMMUFD_TEST \
  -m VFIO -m VFIO_PCI -m VFIO_PCI_CORE -m VFIO_IOMMU_TYPE1 -e VFIO_DEVICE_CDEV \
  -e PCI_P2PDMA -e DMA_SHARED_BUFFER -m UIO -m UIO_PCI_GENERIC \
  -e INTEL_IOMMU -e INTEL_IOMMU_DEBUGFS -e IOMMU_DEBUGFS -e KPROBE_EVENTS \
  -e DEBUG_INFO_NONE -d DEBUG_INFO_BTF -d KASAN
make olddefconfig >/dev/null 2>&1
echo "== CONFIG checks =="
grep -E '^CONFIG_(IOMMUFD|IOMMUFD_TEST|VFIO_PCI_DMABUF|VFIO_DEVICE_CDEV|BLK_DEV_DM|INTEL_IOMMU_DEBUGFS|DMA_SHARED_BUFFER|PCI_P2PDMA)=' .config
echo "== kernelrelease =="
make -s kernelrelease
