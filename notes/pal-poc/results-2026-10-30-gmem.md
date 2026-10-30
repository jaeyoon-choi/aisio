# guest_memfd export PoC 개발 PC 결과 (2026-10-30)

- 측정 호스트: 개발 PC(i9-14900K, RTX PRO 4000 Blackwell, NVIDIA 580.178.04)
- 커널: `7.3.0-rc7-gmem+`. kvm.git `7e60162b16f9`(2026-10-22, "Merge tag 'kvm-riscv-7.4-1'")에 Ackerley Tng의 [guest_memfd alternative providers RFC v2](https://lore.kernel.org/all/20261022-gmem-alternative-providers-v2-0-5dd1dc6c660a@google.com/) 50편과 Fred Griffoul의 [guest_memfd export RFC](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/) 14편을 적용했다. 트리 해시는 `a6af7e15843c`다.
- 시험 장치: 예비 NVMe `0000:02:00.0`. LBA 2097152부터 384섹터를 덮어썼고, 쓰기 측정은 하지 않았다.
- 원본 로그: `devpc-raw/gmem-2026-10-30/`
- 빌드: `src/pal_nvme.c`를 `-DPAL_NVME_GMEM`과 이 커널의 uapi 헤더로 빌드했다.

## 요약

이 시험은 CUDA로 할당한 GPU 메모리를 VM 게스트 없이 guest_memfd export 경로로 NVMe의 IOMMU에 매핑할 수 있는지 개발 PC에서 확인한다. PAL RFC에서는 iommufd가 dma-buf를 받지만, 이 경로에서는 iommufd가 guest_memfd 파일을 받는다. NVIDIA 드라이버는 guest_memfd provider를 제공하지 않으므로, NVIDIA dma-buf의 BAR1 구간을 PFN mode provider로 내보내는 브리지 모듈 `gpu_gmem_provider`를 새로 작성했다.

매핑은 동작했다. NVMe가 GPU 메모리에 쓰는 방향(C1)은 64 KiB와 4 KiB 전송에서 데이터가 일치했고, 매핑하지 않은 IOVA로 보낸 명령은 DMAR fault와 함께 실패했다. 사용자 fd를 모두 닫거나 `cuMemFree`를 불러도 매핑이 GPU 메모리를 잡고 있었고, 매핑을 풀자 메모리가 돌아왔다. NVMe가 GPU 메모리를 읽는 방향(C2)은 실패했다. 같은 커널의 `iommu_map_pa` 경로도 같은 상태 코드로 실패하므로, 이 실패는 이 PC 루트 콤플렉스의 P2P 읽기 제한(`REPORT.md` §7.3) 때문으로 본다.

처리량은 `iommu_map_pa` 경로와 0.05% 안에서 같았고, 두 경로의 차이는 매핑 비용에서 났다. 1 GiB 매핑에 44 ms가 들어 `iommu_map_pa`(89 µs)보다 약 500배 느렸다. RFC의 iommufd 코드가 4 KiB 페이지마다 `iommu_map()`을 한 번씩 부르기 때문이다. 호출 한 번의 비용은 두 경로가 168 ns와 174 ns로 비슷했고, 호출 횟수가 262,144회와 512회로 달랐다.

이 결과로 보면 guest_memfd export 경로는 PAL 없이도 기능 면에서 `iommu_map_pa`를 대체할 수 있다. 다만 지금 RFC의 매핑 비용은 매핑을 자주 다시 만드는 사용 방식에 맞지 않는다. Griffoul은 표지 메일에서 이 iommufd 코드가 "not meant to be merged"이고, 실제 지원은 큰 IOPTE를 다루는 generic_pt 작업과 함께 별도 iommufd 시리즈로 나온다고 밝혔다. 따라서 업스트림에 들어갈 매핑 방식은 이번에 측정한 것과 다를 수 있다. C2와 쓰기 방향 처리량은 sid에서 확인한다(`MANUAL-gmem.md`).

| 항목 | guest_memfd 경로 | `iommu_map_pa` 경로 (같은 커널) |
| --- | --- | --- |
| GPU 매핑 | 성공. BAR1 구간 1개, 1 GiB | 성공. 2 MiB x 512 |
| C1 (NVMe → GPU) | MATCH | MATCH |
| C2 (GPU → NVMe) | `sc=0x4` (플랫폼 제한) | `sc=0x4` |
| D (미매핑 IOVA) | `sc=0x4`, DMAR fault | `sc=0x4`, DMAR fault |
| 1 GiB 매핑 p50 / 해제 p50 | 44,170 µs / 4,742 µs | 89.3 µs / 4.1 µs |
| VT-d 리프 | 4 KiB x 262,144, 하위 비트 `0x803` | 2 MiB x 512, 하위 비트 `0x883` |
| rd 128K qd32 | 6789.6 MB/s | 6792.1 MB/s |
| 수명 (fd 닫기, `cuMemFree`, kill -9) | 모두 정상 정리 | fd 닫기, `cuMemFree` 정상 (kill -9는 시험하지 않음) |

## 1. 시험 구성

CUDA 메모리는 다음 순서로 NVMe의 IOAS에 들어간다.

1. `pal_nvme`가 CUDA로 1 GiB를 할당하고 dma-buf fd로 내보낸다.
2. `pal_nvme`가 `/dev/gpu_gmem_provider`에 `GGP_NEW_FILE` ioctl로 dma-buf fd를 넘긴다. 브리지 모듈은 NVIDIA 패치가 더한 `nv_dma_buf_get_bar1_ranges()`로 BAR1 물리 구간을 읽고, 그 구간의 PFN을 돌려주는 provider 연산을 단 파일(provider 파일)을 만든다.
3. `pal_nvme`가 빈 KVM VM을 만들고(`KVM_CREATE_VM`), 그 VM fd에 `KVM_CREATE_GUEST_MEMFD`를 부른다. 플래그는 `INIT_SHARED | USE_RESOURCE | PFN_MODE`이고 `resource_fd`는 provider 파일이다.
4. `pal_nvme`가 guest_memfd fd를 `IOMMU_IOAS_MAP_FILE`에 넘긴다.

VM에는 vCPU도 메모리 슬롯도 없다. guest_memfd를 만드는 ioctl이 VM fd에 걸려 있으므로 VM 객체만 만든다. 이 커널의 iommufd는 NVIDIA dma-buf를 직접 받지 않는다. `--gmem` 없이 dma-buf를 매핑하면 `IOMMU_IOAS_MAP_FILE`이 `EOPNOTSUPP`로 실패했다(`followup-trial-gmem-20261030.log`의 host 대상 측정). 이 커널에서 CUDA 메모리를 iommufd로 매핑하는 방법은 guest_memfd 경로뿐이다.

| 구성 요소 | 위치 | 내용 |
| --- | --- | --- |
| 커널 | `patches/linux-gmem-on-v7.3-rc7.bundle` | 위 두 RFC를 적용한 트리. v7.3-rc7 위에 kvm.git `7e60162b16f9`의 트리를 커밋 하나로 얹고 RFC 64편을 쌓았다. 최종 트리 해시는 개발 PC 커널과 같다 |
| NVIDIA 580.178.04 | `patches/nvidia-580.178.04-bar1-ranges.patch` | `nvidia/nv-dmabuf.c`에 129행을 더한다. 이 드라이버가 내보낸 dma-buf의 BAR1 구간을 얻고 돌려주는 함수 두 개다 |
| 브리지 모듈 | `src/gpu_gmem_provider/` | PFN mode provider. `get_pfn`은 BAR1 구간 안에서 정렬된 가장 큰 블록의 차수를 돌려준다 |
| `pal_nvme` | `src/pal_nvme.c` | `--gmem` 옵션 추가 |
| upcie-experimental 0.9.0 | `patches/upcie-experimental-0.9.0-gmem-kernel.patch` | 이 커널에서 `dma_buf_attach_ops.move_notify`가 `invalidate_mappings`로 바뀌어 한 줄을 고쳤다. `--map-pa` 비교 경로와 물리주소 조회에 쓴다 |

## 2. 예상 결과

매핑 방식은 `drivers/iommu/iommufd/pages.c`의 `iopt_gmem_map()`이 정한다. 이 함수는 provider에게 정렬된 블록 단위로 PFN을 묻지만, 실제 매핑은 `batch_iommu_map_small()`로 4 KiB마다 `iommu_map()`을 한 번씩 부른다. 함수 주석은 큰 블록의 일부를 갱신할 때 큰 IOMMU 페이지를 쪼개지 않으려고 이렇게 했다고 적는다. 1 GiB 버퍼는 리프 262,144개와 `iommu_map()` 262,144회가 된다. 해제를 맡는 `iopt_gmem_unmap()`은 구멍이 있을 수 있으므로 4 KiB마다 `iommu_iova_to_phys()`로 매핑 여부를 확인한 뒤 연속 구간을 한 번에 푼다.

PTE 비트는 두 경로가 PS 비트만 다를 것으로 예상했다. `iopt_gmem_prot()`는 `area->iommu_prot`를 그대로 쓰고 `IOMMU_MMIO`를 더하지 않는다. `iommu_map_pa`와 dma-buf 경로는 BAR 구간에 `IOMMU_MMIO`를 더한다. 그러나 VT-d 페이지 테이블 형식(`drivers/iommu/generic_pt/fmt/vtdss.h`)은 이 플래그를 읽지 않고, SNP 비트를 도메인 기능 `FORCE_COHERENCE`로 정한다. AMD와 x86_64 형식은 `IOMMU_MMIO`를 읽으므로 이 예상은 Intel에만 해당한다.

매핑이 끝난 뒤의 DMA 경로는 두 방식이 같고 리프 크기만 다르다. 4 KiB 리프는 IOTLB 항목 하나가 덮는 범위가 2 MiB 리프의 512분의 1이므로 IOTLB miss가 늘 수 있다. 개발 PC의 rd 128K qd32는 SSD 한계(약 6.8 GB/s)에서 측정되므로, 그 영향은 보이지 않을 것으로 예상했다.

수명은 참조 관계로 예상했다. `kvm_gmem_export_attach()`는 guest_memfd 파일의 참조를 잡고, guest_memfd는 브리지의 `attach` 연산이 돌려준 provider 파일의 참조를 잡으며, provider 파일은 dma-buf 참조와 BAR1 구간을 잡는다. 따라서 사용자 fd를 모두 닫거나 `cuMemFree`를 불러도 매핑을 풀기 전에는 NVIDIA가 메모리를 해제하지 않아야 한다.

| 항목 | guest_memfd 경로 | `iommu_map_pa` 경로 | 근거 |
| --- | --- | --- | --- |
| 리프 (1 GiB) | 4 KiB x 262,144 | 2 MiB x 512 | `iopt_gmem_map()`, `iommu_map_pa`의 2 MiB 매핑 |
| `iommu_map()` 호출 | 262,144회 | 512회 | 같은 이유 |
| 매핑 시간 | 약 45.6 ms (가정) | 89.3 µs (실측) | 호출당 비용이 같다고 가정하면 89.3 µs / 512 x 262,144 |
| 리프 하위 비트 | `0x803` | `0x883` | `vtdss.h`: R, W, SNP. 2 MiB 리프는 PS(`0x80`)가 더해진다 |
| rd 128K qd32 | `iommu_map_pa`와 같음 (가정) | | SSD 한계에서 측정 |
| C2 | `sc=0x4` | `sc=0x4` | 이 PC의 P2P 읽기 제한 |

## 3. 측정 방법

`devpc-run.sh`로 C1, C2, D를 64 KiB와 4 KiB 전송에서 시험하고, 두 경로의 매핑 반복 100회와 수명 시나리오인 fd 닫기와 `cuMemFree`를 실행했다. C1, C2, D의 정의는 `MANUAL.md`와 같다.

VT-d debugfs의 `domain_translation_struct`는 지금 있는 매핑만 보여주므로, 두 경로에서 각각 8초 읽기 측정을 실행하는 동안 이 파일을 읽었고, `pte-sum.py`로 IOVA 구간별 리프 크기와 하위 비트를 셌다.

측정 중 kill -9 시험은 계획에 없던 시험이다. 브리지 모듈의 해제 경로가 프로세스의 비정상 종료에서도 동작하는지 보려고 추가했다.

마지막으로 sid 매뉴얼에 쓸 `followup-run.sh`의 `GPU=gmem` 모드를 개발 PC에서 미리 실행했다(`c bench map life pte`, 그리고 `iova`). 개발 PC는 C2 방향이 실패하므로 `WR=0`으로 쓰기 측정을 빼고, `SECS=3`으로 실행했다. 첫 실행에서 host 대상 측정이 위의 `EOPNOTSUPP`로 실패했다. `--target host`도 GPU 버퍼를 매핑하므로 host 대상에도 `--gmem`을 붙이도록 스크립트를 고친 뒤 그 부분을 다시 실행했다.

## 4. 결과

### 4.1 정합성과 보호

| 실행 | C1 | C2 | D (장치 읽기) | D2 (장치 쓰기) |
| --- | --- | --- | --- | --- |
| guest_memfd, 64 KiB | MATCH | `sc=0x4`, MISMATCH | `sc=0x4` | 명령 OK |
| guest_memfd, 4 KiB | MATCH | `sc=0x4`, MISMATCH | `sc=0x4` | 명령 OK |
| `iommu_map_pa`, 64 KiB | MATCH | `sc=0x4`, MISMATCH | `sc=0x4` | 명령 OK |

D의 dmesg에는 IOVA `0x80a00000`에 대해 "PTE Read access is not set"(fault reason 0x06)과 "PTE Write access is not set"(0x05)이 남았다. guest_memfd 매핑이 1 GiB 범위에만 번역을 만들고, 그 밖의 IOVA는 IOMMU가 막는다는 것을 보여준다. C2는 두 경로가 같은 상태 코드로 실패했고 DMAR fault는 없었다. 번역 단계가 아니라 플랫폼에서 실패한 것으로 본다.

### 4.2 매핑 비용

| 실행 | guest_memfd map p50 / p99 (µs) | unmap p50 / p99 (µs) | `iommu_map_pa` map p50 / p99 (µs) | unmap p50 / p99 (µs) |
| --- | --- | --- | --- | --- |
| 100회 (`devpc-run-20261030.log`) | 43,307.3 / 44,654.7 | 4,649.8 / 5,445.0 | 91.0 / 98.7 | 4.3 / 4.6 |
| 1000회 (`followup-trial-gmem-20261030.log`) | 44,170.2 / 45,346.4 | 4,742.4 / 4,898.9 | 89.3 / 98.0 | 4.1 / 4.8 |

1000회 실행의 p50을 호출 횟수로 나누면 guest_memfd 경로는 `iommu_map()` 한 번에 168 ns, `iommu_map_pa`는 174 ns다. 예상한 45.6 ms와 측정한 44.2 ms가 3% 안에서 맞으므로, 매핑 비용은 `iommu_map()` 호출 횟수로 설명된다. 해제는 페이지 하나를 확인하는 데 18 ns가 들었다. 참고로 2026-10-26에 PAL 커널에서 잰 PAL 경로의 1 GiB 매핑은 4.9 µs였다(`results-2026-10-26.md` §3). 커널이 달라 직접 비교할 수는 없다.

### 4.3 VT-d 리프 엔트리

| 경로 | GPU 리프 | 하위 비트 | 첫 리프 | 마지막 리프 |
| --- | --- | --- | --- | --- |
| guest_memfd (IOVA `0xa00000`) | 4 KiB x 262,144 | `0x803` x262,144 | `0x000000480f600803` | `0x000000484f5ff803` |
| `iommu_map_pa` (IOVA 256 GiB) | 2 MiB x 512 | `0x883` x512 | `0x000000480f600883` | `0x000000484f400883` |

두 경로 모두 호스트 버퍼는 4 KiB x 2048, `0x803`이었다(`pte-summary-20261030.txt`). guest_memfd 경로의 리프는 BAR1 `0x480f600000`부터 1 GiB를 빈틈없이 덮었다. 하위 비트는 R, W, SNP로 같고 2 MiB 리프의 PS 비트만 달랐다. guest_memfd 경로에 `IOMMU_MMIO`가 없어도 Intel에서는 PTE가 달라지지 않는다는 2절의 예상과 맞는다.

### 4.4 처리량

| 측정 | guest_memfd | `iommu_map_pa` | host 대상 |
| --- | --- | --- | --- |
| rd 4K qd1 (MB/s, p50 µs) | 641.5, 6.1 | 635.1, 6.1 | 642.2, 6.1 |
| rd 128K qd32 (MB/s, p99 µs) | 6789.6, 749.4 | 6792.1, 737.2 | 7235.6, 650.4 |
| rd 128K qd32, `pte` 부분 8초 | 6790.7 | 6792.8 | |

`iova` 부분은 두 경로를 서로의 기본 IOVA에 두고 rd 128K qd32를 정방향과 역방향으로 한 번씩 쟀다.

| 조합 | 정방향 (MB/s) | 역방향 (MB/s) |
| --- | --- | --- |
| guest_memfd, `0xa00000` | 6789.4 | 6789.0 |
| guest_memfd, 256 GiB | 6789.6 | 6790.0 |
| `iommu_map_pa`, 256 GiB | 6793.0 | 6792.5 |
| `iommu_map_pa`, 1 GiB | 6792.9 | 6792.9 |
| host 대상 | 7235.4 | 7235.7 |

guest_memfd 경로는 모든 실행에서 `iommu_map_pa`보다 2~4 MB/s(0.05%) 낮았고, IOVA 위치는 영향이 없었다. 차이가 실행마다 같은 방향으로 나왔으므로 4 KiB 리프의 IOTLB miss 비용이 조금 보였을 수 있지만, 처리량에 의미 있는 차이로 보기는 어렵다. 이것은 추정이다. 같은 날 따로 실행한 8초 측정에서 guest_memfd 경로가 6777.2 MB/s로 0.2% 낮게 나온 적이 한 번 있었다(`pte-bench-gmem-20261030.log`). 그 뒤 실행에서는 다시 6789~6791 MB/s였다. GPU 대상이 host 대상보다 6% 낮은 것은 2026-10-26 PAL 측정(6788 대 7204 MB/s)과 같은 경향이다.

### 4.5 수명

| 시험 | 확인하는 것 | guest_memfd 결과 |
| --- | --- | --- |
| fd 닫기 | dma-buf, provider, guest_memfd, VM fd를 모두 닫은 뒤에도 매핑이 동작하는가 | C1 MATCH. 해제 뒤 CUDA 여유 메모리 23740 MiB로 복귀 |
| `cuMemFree` 직후 여유 메모리 | 매핑이 있는 동안 NVIDIA가 메모리를 해제하는가 | 22716 MiB로 해제 전과 같음. 해제하지 않음 |
| F1 새 버퍼 | 옛 IOVA로 쓴 데이터가 새 버퍼를 덮어쓰는가 | intact. 새 버퍼 물리주소는 `0x484f600000`으로 옛 버퍼(`0x480f600000`)와 다름 |
| F2 | 옛 IOVA가 아직 옛 메모리를 가리키는가 | 측정 불가(C2 방향) |
| 측정 중 kill -9 | 강제 종료 뒤 GPU 메모리와 모듈 참조가 정리되는가 | CUDA 사용량 1269 MiB에서 15 MiB로 복귀. `gpu_gmem_provider` 참조 수 0. 다음 실행 C1 MATCH |

`iommu_map_pa` 경로의 fd 닫기와 `cuMemFree` 결과는 guest_memfd 경로와 숫자까지 같았다. 시험 중 커널 경고(`BUG`, `WARNING`)는 없었다. 이 결과는 2절에서 예상한 참조 관계가 실제로 메모리를 붙잡고 있음을 보여준다.

## 5. 해석

| 항목 | 예상 | 측정 | 판정 |
| --- | --- | --- | --- |
| 1 GiB 매핑 시간 | 약 45.6 ms (가정) | 44.2 ms | 맞음. 비용은 `iommu_map()` 호출 횟수로 정해진다 |
| 리프 크기와 비트 | 4 KiB, `0x803` | 4 KiB x 262,144, `0x803` | 맞음 |
| rd 128K qd32 | `iommu_map_pa`와 같음 (가정) | 0.05% 낮음 | 맞음. SSD 한계에서는 차이가 드러나지 않는다 |
| C2 | `sc=0x4` | `sc=0x4` | 맞음. 판정은 sid에서 한다 |
| 수명 | 매핑이 메모리를 붙잡음 | 붙잡고, 해제 뒤 반환 | 맞음 |

매핑 비용의 원인은 RFC의 데모 코드에 있다. 표지 메일은 실제 지원에 큰 IOPTE를 제자리에서 자르고 합치는 generic_pt 작업이 필요하다고 적었다. 그 작업이 들어오면 guest_memfd 경로도 2 MiB 이상의 리프로 매핑하고, 매핑 비용이 PAL 경로 수준으로 내려갈 것으로 추정한다. 브리지 모듈의 `get_pfn`은 이미 BAR1 구간 안에서 가장 큰 정렬 블록의 차수를 돌려주므로 provider 쪽은 바꿀 필요가 없다.

## 6. 확인하지 못한 것

- C2와 쓰기 방향 처리량을 확인하지 못했다. 이 PC는 P2P 읽기를 처리하지 못한다. sid에서 `MANUAL-gmem.md`대로 측정해 확인한다.
- 4 KiB 리프가 IOTLB에 주는 영향을 SSD 한계 아래에서만 봤다. sid에서도 차이가 없으면, 여러 NVMe가 같은 GPU 버퍼를 동시에 읽는 부하로 IOMMU 쪽 한계를 측정한다.
- PFN mode의 revoke 경로(`kvm_gmem_revoke()`)와 구멍 처리를 시험하지 않았다. 브리지 모듈은 revoke를 부르지 않고, NVIDIA는 매핑이 있는 동안 메모리를 해제하지 않는다. NVIDIA가 dma-buf의 `invalidate_mappings`를 보낼 때 이를 revoke로 잇는 코드를 브리지에 더하면 시험할 수 있다.
- 업스트림의 큰 IOPTE 지원이 들어온 뒤의 매핑 비용은 측정할 수 없다. generic_pt 시리즈와 iommufd 시리즈가 나오면 같은 `--map-loop`로 다시 잰다.
- AMD IOMMU에서 `IOMMU_MMIO`가 없을 때의 영향은 시험하지 않았다. AMD 장비가 없다. 소스로는 AMD와 x86_64 형식이 이 플래그를 읽는다는 것까지만 확인했다.
