mv /tmp/sid-cuda13-compat.h /root/pal-poc/sid-cuda13-compat.h
cd /root/pal-poc/sid-bundle/src
CU="-I/usr/local/cuda/include -include /root/pal-poc/sid-cuda13-compat.h"
echo "== source md5 (must match dev bundle) =="; md5sum pal_probe.c pal_nvme.c bar1_cpu_read.c
echo "== build pal_probe ==";     gcc -O2 -Wall $CU -o pal_probe     pal_probe.c     -lcuda && echo "OK pal_probe"
echo "== build pal_nvme ==";      gcc -O2 -Wall $CU -o pal_nvme      pal_nvme.c      -lcuda && echo "OK pal_nvme"
echo "== build bar1_cpu_read =="; gcc -O2 -Wall -Wno-unused-result $CU -o bar1_cpu_read bar1_cpu_read.c -lcuda && echo "OK bar1_cpu_read"
echo "== result =="; ls -l pal_probe pal_nvme bar1_cpu_read
