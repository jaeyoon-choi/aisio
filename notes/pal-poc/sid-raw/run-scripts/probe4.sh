echo "== fstab =="; grep -vE '^\s*#|^\s*$' /etc/fstab
echo "== systemd mounts =="; systemctl list-units --type=mount --all --no-legend 2>/dev/null | grep -iE 'nvme|dataset|mnt|fail' || echo "(none)"
echo "== lsblk holders/mounts (nvme) =="; lsblk -o NAME,SIZE,TYPE,HOLDERS,FSTYPE,MOUNTPOINT | grep -E 'nvme|NAME'
echo "== fuser on sample candidates =="
for ns in /dev/nvme2n1 /dev/nvme4n1 /dev/nvme11n1 /dev/nvme1n1; do
  echo -n "$ns: "; fuser -v "$ns" 2>&1 | tr '\n' ' '; echo
done
echo "== lsof present? =="; command -v lsof && lsof /dev/nvme2n1 /dev/nvme11n1 2>/dev/null | head || echo "(no lsof)"
echo "== dataset nvme1 vs candidate serials =="
for ns in /dev/nvme1n1 /dev/nvme2n1 /dev/nvme11n1; do echo -n "$ns "; nvme id-ctrl "$ns" 2>/dev/null | grep -E '^sn |^mn '; done
echo "== candidates: any signature anywhere? (first 1MiB + last 1MiB) =="
for ns in /dev/nvme2n1 /dev/nvme11n1; do
  echo "--- $ns"; blkid -p "$ns" 2>&1
done
echo "== /mnt/datasets =="; findmnt /mnt/datasets 2>&1; ls -la /mnt/ 2>&1
echo "(done)"
