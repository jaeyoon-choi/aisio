set -e
V=$(ls -d /usr/src/nvidia-* | head -1)
echo "== nvidia src: $V =="
rm -rf /root/pal-poc/nvidia-pal && cp -r "$V" /root/pal-poc/nvidia-pal && cd /root/pal-poc/nvidia-pal
P=/root/pal-poc/sid-bundle/patches/nvidia-580.178.04-pal-port.patch
echo "== patch dry-run =="
patch -p1 --dry-run < "$P" && echo "DRYRUN_OK" || { echo "DRYRUN_FAILED"; exit 3; }
patch -p1 < "$P"
echo "== build =="
make -j16 SYSSRC=/root/pal-poc/linux-pal NV_EXCLUDE_KERNEL_MODULES=nvidia-peermem modules > build.log 2>&1; echo "make_exit=$?"
grep -E 'error:' build.log | head -5
echo "== ko files =="; ls -l *.ko 2>&1
echo "== vermagic =="; modinfo -F vermagic nvidia.ko 2>&1
