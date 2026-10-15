/* sid build shim (2026-10-14).
   sid CUDA is 13.3: cuda.h maps cuCtxCreate -> cuCtxCreate_v4(pctx,
   ctxCreateParams, flags, dev).  The test sources call the legacy 3-arg
   form cuCtxCreate(&ctx, 0, dev), written for an older CUDA (dev PC).
   This header re-exposes the 3-arg form with ctxCreateParams = NULL
   ("create a regular CUDA context"), which is semantically identical.
   Injected with gcc -include so src/*.c stay byte-for-byte unmodified. */
#ifndef SID_CUDA13_COMPAT_H
#define SID_CUDA13_COMPAT_H
#include <cuda.h>
#if defined(CUDA_VERSION) && (CUDA_VERSION >= 13000)
#undef cuCtxCreate
static inline CUresult cuCtxCreate(CUcontext *pctx, unsigned int flags, CUdevice dev)
{
	return cuCtxCreate_v4(pctx, 0, flags, dev);
}
#endif
#endif
