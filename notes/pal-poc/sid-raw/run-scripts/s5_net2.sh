echo "== git info/refs via proxy =="
curl -sS -o /dev/null -w "proxy info/refs -> %{http_code}\n" -x http://12.26.204.100:8080 'https://github.com/jgunthorpe/linux.git/info/refs?service=git-upload-pack'
echo "== git info/refs direct =="
timeout 15 curl -sS -o /dev/null -w "direct info/refs -> %{http_code}\n" 'https://github.com/jgunthorpe/linux.git/info/refs?service=git-upload-pack' 2>&1
echo "== github root direct =="
timeout 15 curl -sS -o /dev/null -w "direct github -> %{http_code}\n" https://github.com 2>&1
echo "== proxy HEAD on repo page =="
curl -sS -o /dev/null -w "proxy repo page -> %{http_code}\n" -x http://12.26.204.100:8080 https://github.com/jgunthorpe/linux
