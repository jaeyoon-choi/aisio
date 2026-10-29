echo "== lines mentioning 09a2"
lspci -nn | grep -i 09a2
echo "== GPU numa + root complex"
readlink -f /sys/bus/pci/devices/0000:31:00.0/..
cat /sys/bus/pci/devices/0000:31:00.0/numa_node
cat /sys/bus/pci/devices/0000:31:00.0/iommu_group/type 2>/dev/null
echo "== GPU current driver"
basename "$(readlink -f /sys/bus/pci/devices/0000:31:00.0/driver)"
echo "== GPU root port ACS"
lspci -vvv -s 0000:30:02.0 2>/dev/null | grep -iE 'ACSCtl|ACSCap|LnkCap:|DevCap' | head
echo "== candidate root ports ACS (4c:01, 66:00)"
for rp in 0000:4c:01.0 0000:66:00.0; do
  echo "--- $rp"
  lspci -vvv -s $rp 2>/dev/null | grep -iE 'ACSCtl|ACSCap' | head -3
done
echo "== p2pdma allowlist in running kernel source? =="
for f in /usr/src/linux-*/drivers/pci/p2pdma.c /lib/modules/$(uname -r)/build/drivers/pci/p2pdma.c; do
  [ -f "$f" ] && { echo "found $f"; grep -nE '0x09a2|0x0998|ICE|Ice Lake' "$f" | head; }
done
echo "(done)"
