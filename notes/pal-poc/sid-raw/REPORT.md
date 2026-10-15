# sid PAL PoC 결과 (2026-10-14~15)

시험 장치 `0000:4e:00.0` (nvme2, socket0/RC 4a), SLBA 0. `4d:00.0` 미접촉.

## 결과 표

| 단계 | 시험 | 개발 PC 결과 | sid 결과 |
| --- | --- | --- | --- |
| A0 | 기본 커널 iommufd가 NVIDIA dma-buf 거부 | 미시험 | `IOMMU_IOAS_MAP_FILE: FAILED errno=95` |
| A1 | 번역 없이 C1 (NVMe→GPU) | MATCH | MATCH |
| A1 | 번역 없이 C2 (GPU→NVMe) | 실패 `sc=0x4` | **MATCH** |
| A2 | CPU의 BAR1 읽기 | MATCH | MATCH |
| C0 | PAL 매핑 | OK | `IOMMU_IOAS_MAP_FILE: OK iova=0x200000` |
| C1 | 번역된 NVMe→GPU | MATCH | MATCH (64K/4K/identity) |
| C2 | 번역된 GPU→NVMe | 실패 `sc=0x4` | **MATCH (64K/4K/identity)** |
| D | 미매핑 IOVA | 오류 + DMAR fault | `sct=0x0 sc=0x4` + `PTE Read/Write access is not set` |
| PTE | 페이지 크기, SNP | 2 MiB × 512, SNP 켜짐 | 2 MiB, entries 514, SNP 켜짐(bit 11=1) |

## 해석

- **C2가 sid에서 MATCH.** dev PC에서 `sc=0x4`로 실패했던 방향(GPU BAR1을 장치가 읽는 non-posted P2P read)이 sid(Ice Lake-SP)에서는 번역(identity/translated) 모두 성공. → dev PC의 C2 실패는 **클라이언트 루트 콤플렉스(8086:a700)의 cross-root-port P2P read 제약**이었고, PAL/iommufd 번역 문제가 아님을 실기로 확인.
- **단계 A와 C의 차이 없음.** sid에서는 번역 없이(단계 A)도, PAL 번역(단계 C)으로도 C1/C2 모두 MATCH. 즉 이 플랫폼에서는 P2P 방향 제약이 없고, PAL 경로가 그대로 동작.
- **SNP(PTE bit 11)가 켜진 상태에서도 C2 성공** → SNP는 원인 아님(dev PC 결론과 일치). `patches/kernel-vtdss-mmio-nosnp.patch` 불필요.
- **측정**: A0/A1/A2/C0/C1/C2/D/PTE 전부 실측. **추정**: 없음.
- **결론**: 자체 모듈 `iommu_map_pa`의 workaround를 업스트림 PAL(`IOMMU_IOAS_MAP_FILE` + dma-buf mapping types)로 대체할 근거를 sid에서 확보.

## 기록해 둘 환경·수정

- **CUDA 13.3** (dev PC와 다름): `cuCtxCreate`가 4인자 `cuCtxCreate_v4`. 시험 소스는 3인자 → `gcc -include sid-cuda13-compat.h` shim으로 소스 무수정 빌드.
- **하네스 버그 수정(승인)**: `pal_nvme.c:411` CC의 IOSQES/IOCQES 스왑(`0x00640001`→`0x00460001`). 수정 전에는 이 엔터프라이즈 드라이브가 Create I/O CQ를 `0x102`로 거부.
- **빌드 도구 추가 설치(승인)**: `libdw-dev`(gendwarfksyms의 `dwarf.h`).
- **커널 소스**: sid 프록시는 git smart-HTTP의 대형 ref 광고를 못 넘김 → github PAT의 Basic 인증(`x-access-token`)으로 clone(공개 github.com은 IP 레이트리밋).
- **GRUB**: `7.0.0-rc1-pal+`가 버전정렬상 최신이라 update-grub 시 기본이 바뀔 수 있어 `GRUB_DEFAULT`를 `7.0.0-38-generic`으로 고정(기본 커널 불변). 또한 grubenv가 LVM 위라 GRUB이 쓸 수 없어 `grub-reboot`가 1회성이 아님 → PAL 부팅 후 `grub-editenv /boot/grub/grubenv unset next_entry`로 해제함.

## 원상 복구

- `4e:00.0` → nvme 드라이버/DMA-FQ 복귀, hugepage 해제.
- 기본 커널 `7.0.0-38-generic`으로 재부팅, `nvidia-smi` 정상, `/dev/nvme2n1` 복귀.
- `/mnt/datasets`는 미마운트(테스트 전과 동일).
- PAL 커널 파일(`/boot/*-pal+`, `/lib/modules/*-pal+`)은 사용자 결정에 따라 남겨 둠.

## 로그

- sia: `~/pal-poc-sid/logs/` (각 단계 tee 로그)
- sid: `~/pal-poc-sid/sid-logs/`
