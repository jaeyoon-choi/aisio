echo "== git proxy config =="
git config --global --get http.proxy; git config --global --get https.proxy
echo "== proxy env =="; env | grep -i proxy || echo "(no proxy env)"
echo "== CA certs (samsung) =="
ls /usr/local/share/ca-certificates/ 2>/dev/null; ls /etc/ssl/certs/ 2>/dev/null | grep -iE 'samsung|prx' || echo "(no samsung CA in ssl/certs)"
echo "== apt proxy (worked earlier) =="
grep -rhi proxy /etc/apt/apt.conf.d/ 2>/dev/null || echo "(none)"
echo "== connectivity: direct github (5s) =="
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/github.com/443' 2>&1 && echo "direct:443 OK" || echo "direct:443 blocked"
echo "== connectivity: via proxy =="
timeout 8 curl -sS -o /dev/null -w "proxy https github %{http_code}\n" -x http://12.26.204.100:8080 https://github.com 2>&1 | tail -2
echo "== disk =="; df -h /root | tail -1
