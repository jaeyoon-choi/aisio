cd /root/pal-poc/linux-pal || exit 1
K=$(make -s kernelrelease); echo "K=$K"
make modules_install >/dev/null 2>&1; echo "modules_install=$?"
mkdir -p /lib/modules/$K/extra
cp /root/pal-poc/nvidia-pal/nvidia.ko /root/pal-poc/nvidia-pal/nvidia-uvm.ko /root/pal-poc/nvidia-pal/nvidia-modeset.ko /root/pal-poc/nvidia-pal/nvidia-drm.ko /lib/modules/$K/extra/
cp /root/pal-poc/upcie-pal/dmabuf_import/dmabuf_import.ko /root/pal-poc/upcie-pal/iommu_map_pa/iommu_map_pa.ko /lib/modules/$K/extra/
depmod -a $K; echo "depmod=$?"
cp arch/x86/boot/bzImage /boot/vmlinuz-$K
cp System.map /boot/System.map-$K
cp .config /boot/config-$K
update-initramfs -c -k $K 2>&1 | tail -2
echo "== /boot files =="; ls -l /boot/vmlinuz-$K /boot/initrd.img-$K /boot/config-$K
echo "== initramfs dm modules count =="; lsinitramfs /boot/initrd.img-$K | grep -cE 'dm-mod|dm_mod|dm-crypt'
echo "== extra modules =="; ls /lib/modules/$K/extra/
echo "== DRY RUN grub-mkconfig -> /tmp/grub.new (real grub.cfg untouched) =="
grub-mkconfig -o /tmp/grub.new 2>/dev/null
echo "--- menu order (top 14) ---"; grep -nE "^\s*(menuentry|submenu) " /tmp/grub.new | head -14
echo "--- real grub.cfg mtime (should be unchanged) ---"; ls -l --time-style=+%H:%M:%S /boot/grub/grub.cfg
