echo "== /data_03 =="; ls -ld /data_03 2>&1; df -h /data_03 2>/dev/null | tail -1
echo "== /data_03/jaeyoon/kernel =="; ls -la /data_03/jaeyoon/kernel/ 2>&1
echo "== linux tree =="
L=/data_03/jaeyoon/kernel/linux
ls -ld $L 2>&1
if [ -d $L/.git ]; then
  cd $L
  echo "-- HEAD:"; git log --oneline -1 2>&1
  echo "-- branches:"; git branch -a 2>&1 | head -20
  echo "-- remotes:"; git remote -v 2>&1
  echo "-- has c37cf2824740?"; git cat-file -e c37cf2824740 2>&1 && echo "YES has commit" || echo "no"
  echo "-- has dmabuf_map_type ref?"; git rev-parse --verify refs/heads/dmabuf_map_type 2>&1 || git rev-parse --verify origin/dmabuf_map_type 2>&1 || echo "no such ref"
  echo "-- Makefile version:"; head -4 Makefile 2>&1
  echo "-- dirty?"; git status --porcelain 2>&1 | head
fi
