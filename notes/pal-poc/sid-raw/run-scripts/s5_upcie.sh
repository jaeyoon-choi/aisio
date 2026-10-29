V=$(ls -d /usr/src/upcie-experimental-* | head -1)
echo "== upcie src: $V =="
rm -rf /root/pal-poc/upcie-pal && cp -r "$V" /root/pal-poc/upcie-pal && cd /root/pal-poc/upcie-pal
P=/root/pal-poc/sid-bundle/patches/upcie-experimental-0.9.0-pal-port.patch
echo "== patch dry-run =="
patch -p1 --dry-run < "$P" && echo DRYRUN_OK || { echo DRYRUN_FAILED; exit 3; }
patch -p1 < "$P"
echo "== build =="
make KDIR=/root/pal-poc/linux-pal > build.log 2>&1; echo "make_exit=$?"
grep -iE 'error:|Error [0-9]+' build.log | head -8
echo "== .ko files =="; find . -name '*.ko' -exec ls -l {} \;
