# iommufd GPU 메모리 매핑 PoC 자료

CUDA 메모리를 `iommu_map_pa` 대신 iommufd의 `IOMMU_IOAS_MAP_FILE`로 NVMe의 IOMMU에 매핑하는 PoC의 보고서, 매뉴얼, 결과, 원본 로그를 모은 폴더다. PAL RFC 경로는 `REPORT.md`에, guest_memfd export 경로는 `results-2026-10-30-gmem.md`(개발 PC)와 `results-2026-11-02-gmem.md`(sid)에 정리되어 있다.

## 코드 위치

수정한 코드는 원래 속한 저장소의 fork에 브랜치로 두었다. 이 폴더의 `src/`, `scripts/`, `patches/`는 측정 당시의 사본이고, 매뉴얼이 이 경로를 가리키므로 그대로 둔다. 이후 코드를 고칠 때는 아래 브랜치를 쓴다.

| 대상 | 위치 | 내용 |
| --- | --- | --- |
| NVIDIA 드라이버 (PAL) | [`jaeyoon-choi/open-gpu-kernel-modules` `poc/iommufd-pal-exporter`](https://github.com/jaeyoon-choi/open-gpu-kernel-modules/tree/poc/iommufd-pal-exporter) | 태그 `580.178.04` 위 커밋 하나. `patches/nvidia-580.178.04-pal-port.patch`와 같다 |
| NVIDIA 드라이버 (guest_memfd export) | [`jaeyoon-choi/open-gpu-kernel-modules` `poc/gmem-bar1-ranges`](https://github.com/jaeyoon-choi/open-gpu-kernel-modules/tree/poc/gmem-bar1-ranges) | 태그 `580.178.04` 위 커밋 하나. `patches/nvidia-580.178.04-bar1-ranges.patch`와 같다 |
| 브리지 모듈, 시험 도구, `dmabuf_import` 대응 | [`jaeyoon-choi/upcie` `poc/iommufd-gpu`](https://github.com/jaeyoon-choi/upcie/tree/poc/iommufd-gpu) | v0.10.4 위 커밋 세 개. `experimental/gpu_gmem_provider/`, `experimental/iommufd_gpu_poc/` |

Linux 커널은 직접 고친 코드가 없어 fork하지 않았다. 빌드한 트리는 다음과 같다.

| PoC | 커널 트리 |
| --- | --- |
| PAL | `jgunthorpe/linux` 브랜치 `dmabuf_map_type` 커밋 `c37cf2824740` (v7.0-rc1 `6de23f81a5e0` 기반). 고치지 않고 빌드했다 |
| guest_memfd export | kvm.git `7e60162b16f9`(지금은 v7.4-rc1에 포함)에 Ackerley Tng의 [alternative providers RFC v2](https://lore.kernel.org/all/20261022-gmem-alternative-providers-v2-0-5dd1dc6c660a@google.com/) 50편과 Fred Griffoul의 [guest_memfd export RFC](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/) 14편을 적용한 트리. 트리 해시 `a6af7e15843c`. `patches/linux-gmem-on-v7.3-rc7.bundle`이 같은 트리를 v7.3-rc7 위에 다시 쌓은 것이다(끝 커밋 `6766bffb9fc2`) |

## 파일

| 파일 | 내용 |
| --- | --- |
| `REPORT.md` | PAL PoC 종합 보고서 (구현 상세, 바로잡은 기록 포함) |
| `results-*.md` | 단계별 결과 |
| `MANUAL.md`, `MANUAL-followup.md`, `MANUAL-gmem.md` | sid 실행 매뉴얼 |
| `sid-raw/`, `devpc-raw/` | 원본 로그 |
| `src/`, `scripts/`, `patches/` | 측정 당시의 시험 도구, 스크립트, 패치 |
