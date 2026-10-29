echo "== root bus 00.0 device IDs"
for b in 00 16 30 4a 64 80 97 b0 c9 e2; do printf "%s:00.0 " $b; lspci -nns $b:00.0 2>/dev/null; done
echo "== GPU numa_node"; cat /sys/bus/pci/devices/0000:31:00.0/numa_node
echo "== nvidia-smi topo -m"; nvidia-smi topo -m 2>&1
echo "== numa of candidate root ports"
for rp in 0000:4c:01.0 0000:66:00.0 0000:cb:00.0 0000:e4:00.0; do echo "$rp node=$(cat /sys/bus/pci/devices/$rp/numa_node 2>/dev/null)"; done
