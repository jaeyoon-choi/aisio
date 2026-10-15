mkdir -p /root/pal-poc
ls -ld /tmp/sid-bundle && echo "SRC_OK=$(find /tmp/sid-bundle -type f | wc -l) files"
rm -rf /root/pal-poc/sid-bundle
mv /tmp/sid-bundle /root/pal-poc/sid-bundle
chown -R root:root /root/pal-poc/sid-bundle
echo MOVED_OK
find /root/pal-poc/sid-bundle -maxdepth 2 | sort
