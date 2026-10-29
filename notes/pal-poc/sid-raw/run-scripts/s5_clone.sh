mkdir -p /root/pal-poc/logs
cd /root/pal-poc
rm -f /root/pal-poc/logs/clone.log
rm -rf /root/pal-poc/linux-pal
nohup setsid bash -c '
  cd /root/pal-poc
  git clone --no-checkout --filter=blob:none https://github.com/jgunthorpe/linux linux-pal
  r1=$?
  cd linux-pal && git fetch origin dmabuf_map_type
  r2=$?
  git checkout --detach c37cf2824740
  r3=$?
  echo "CLONE_EXIT git=$r1 fetch=$r2 checkout=$r3"
' > /root/pal-poc/logs/clone.log 2>&1 < /dev/null &
echo "started pid $!"
for i in $(seq 1 90); do
  grep -q CLONE_EXIT /root/pal-poc/logs/clone.log && break
  sleep 6
done
echo "== clone.log tail =="; tail -8 /root/pal-poc/logs/clone.log
echo "== tree check =="
cd /root/pal-poc/linux-pal 2>/dev/null && { git rev-parse HEAD; git log --oneline -1; du -sh /root/pal-poc/linux-pal; } || echo "linux-pal not ready"
