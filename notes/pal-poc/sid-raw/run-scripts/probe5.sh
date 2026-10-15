echo "== GPU RC domain and root port =="
readlink -f /sys/bus/pci/devices/0000:31:00.0
echo "== devices under GPU RC (pci0000:30) =="
ls -d /sys/devices/pci0000:30/*/ 2>/dev/null
echo "== devices on buses 30-3f (GPU stack) =="
lspci -nn | grep -E '^3[0-9a-f]:'
echo "== each NVMe: root complex + root port =="
for n in $(ls -d /sys/class/nvme/nvme* 2>/dev/null | sort -V); do
  name=$(basename "$n"); dev=$(basename "$(readlink -f "$n/device")")
  path=$(readlink -f /sys/bus/pci/devices/$dev)
  rc=$(echo "$path" | grep -oE 'pci0000:[0-9a-f]{2}' | head -1)
  rp=$(basename "$(readlink -f /sys/bus/pci/devices/$dev/..)")
  echo "$name $dev $rc rootport=$rp"
done | sort -k1.5 -V
echo "== all RC domains =="
ls -d /sys/devices/pci0000:* 2>/dev/null | xargs -n1 basename | tr '\n' ' '; echo
echo "== NUMA per RC (from GPU/candidate root ports) =="
for bdf in 0000:30:02.0 0000:4c:01.0 0000:66:00.0; do
  echo "$bdf node=$(cat /sys/bus/pci/devices/$bdf/numa_node 2>/dev/null)"
done
