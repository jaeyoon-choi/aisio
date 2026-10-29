cd /root/pal-poc/sid-bundle/src || exit 1
echo "== copy dmabuf_import.h =="
cp /usr/include/linux/dmabuf_import.h ./dmabuf_import.h && echo "header copied: $(wc -l < dmabuf_import.h) lines"
CU=-I/usr/local/cuda/include
echo "== build pal_probe ==";   gcc -O2 -Wall $CU -o pal_probe   pal_probe.c   -lcuda 2>&1
echo "== build pal_nvme ==";    gcc -O2 -Wall $CU -o pal_nvme    pal_nvme.c    -lcuda 2>&1
echo "== build bar1_cpu_read =="; gcc -O2 -Wall -Wno-unused-result $CU -o bar1_cpu_read bar1_cpu_read.c -lcuda 2>&1
echo "== result =="; ls -l pal_probe pal_nvme bar1_cpu_read 2>&1
