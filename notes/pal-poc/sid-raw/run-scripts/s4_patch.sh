cd /root/pal-poc/sid-bundle/src || exit 1
[ -f pal_nvme.c.orig ] || cp pal_nvme.c pal_nvme.c.orig
echo "== before =="; grep -n 'wr32(c, 0x14, (' pal_nvme.c
sed -i 's/(6 << 20) | (4 << 16) | 1/(6 << 16) | (4 << 20) | 1/' pal_nvme.c
echo "== after =="; grep -n 'wr32(c, 0x14, (' pal_nvme.c
CU="-I/usr/local/cuda/include -include /root/pal-poc/sid-cuda13-compat.h"
gcc -O2 -Wall $CU -o pal_nvme pal_nvme.c -lcuda && echo "OK pal_nvme rebuilt"
ls -l pal_nvme; md5sum pal_nvme.c
