cd /root/pal-poc/sid-bundle || exit 1
NVME=0000:4e:00.0
SLBA=0
echo "== A0 stock iommufd refuses the NVIDIA dma-buf"
./src/pal_probe; echo "A0 rc=$?"
echo "== A1 untranslated (identity IOMMU + uio)"
./scripts/identity-uio.sh $NVME; echo "identity-uio rc=$?"
echo "-- A1 64K"; ./src/pal_nvme --uio $NVME --slba $SLBA; echo "rc=$?"
echo "-- A1 4K";  ./src/pal_nvme --uio $NVME --slba $SLBA --xfer 4096; echo "rc=$?"
echo "== A2 cpu read through BAR1"
./src/bar1_cpu_read; echo "A2 rc=$?"
echo "== restore"
./scripts/restore-nvme.sh $NVME; echo "restore rc=$?"
echo "== dmesg"
dmesg | grep -E 'DMAR|AER|pcieport' | tail -20
