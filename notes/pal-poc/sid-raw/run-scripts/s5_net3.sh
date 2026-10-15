PX=http://12.26.204.100:8080
echo "== info/refs via proxy HTTP/1.1 =="
curl -sS --max-time 20 --http1.1 -o /dev/null -w "h1.1 -> %{http_code}\n" -x $PX 'https://github.com/jgunthorpe/linux.git/info/refs?service=git-upload-pack'
echo "== codeload tarball via proxy =="
curl -sS --max-time 40 -o /dev/null -w "codeload -> %{http_code} bytes=%{size_download}\n" -x $PX -L 'https://codeload.github.com/jgunthorpe/linux/tar.gz/c37cf2824740'
echo "== github archive via proxy =="
curl -sS --max-time 40 -o /dev/null -w "archive -> %{http_code}\n" -x $PX -L 'https://github.com/jgunthorpe/linux/archive/c37cf2824740.tar.gz'
