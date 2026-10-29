echo "== sid CUDA_VERSION =="
grep -m2 -E '#define CUDA_VERSION' /usr/local/cuda/include/cuda.h
echo "== cuCtxCreate mapping in sid cuda.h =="
grep -n -E 'define cuCtxCreate|cuCtxCreate_v4|CUctxCreateParams' /usr/local/cuda/include/cuda.h | head
echo "== is cuCtxCreate_v4 / v3 exported? =="
nm -D --defined-only /usr/local/cuda/lib64/libcuda.so* 2>/dev/null | grep -iE 'cuCtxCreate' | head
