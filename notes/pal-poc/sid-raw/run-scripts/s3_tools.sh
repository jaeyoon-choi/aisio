echo "== apt proxy config =="
grep -rhi 'proxy' /etc/apt/apt.conf.d/ 2>/dev/null || echo "(none)"
echo "== apt-get update =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq 2>&1 | tail -4
echo "== install =="
apt-get install -y flex bison dwarves libcap-dev 2>&1 | tail -15
echo "== verify tools =="
for c in flex bison pahole; do printf "%s: " "$c"; command -v "$c" || echo MISSING; done
dpkg -l libcap-dev 2>/dev/null | awk '/^ii/{print $2, $3}'
