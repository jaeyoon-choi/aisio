cd /root/pal-poc/sid-bundle || exit 1
NVME=0000:4e:00.0
SLBA=0
modprobe nvidia; modprobe nvidia-uvm; modprobe dmabuf_import; modprobe vfio-pci
echo "== bind-vfio =="; ./scripts/bind-vfio.sh $NVME; echo "bind rc=$?"
VF=/dev/vfio/devices/$(ls /sys/bus/pci/devices/$NVME/vfio-dev)
echo "VF=$VF"
echo "== C0 map (stock-style probe on PAL kernel) =="; ./src/pal_probe --vfio $VF; echo "rc=$?"
echo "== C1/C2/D 64K =="; ./src/pal_nvme --vfio $VF --slba $SLBA; echo "rc=$?"
echo "== 4K =="; ./src/pal_nvme --vfio $VF --slba $SLBA --xfer 4096; echo "rc=$?"
echo "== identity iova =="; ./src/pal_nvme --vfio $VF --slba $SLBA --identity --no-negative; echo "rc=$?"
echo "== PTE =="; ( ./src/pal_probe --vfio $VF --hold 15 & ) ; sleep 8; ./scripts/pte-dump.sh $NVME
sleep 10
echo "== dmesg DMAR/AER =="; dmesg | grep -E 'DMAR|AER' | tail -20
