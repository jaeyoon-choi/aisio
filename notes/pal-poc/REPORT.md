# PAL 기반 iommufd GPU 메모리 매핑 PoC 종합 보고서

- 기간: 2026-10-13 ~ 2026-10-15
- 호스트: 개발 PC jaeyoon-pc (i9-14900K, RTX PRO 4000 Blackwell), sid (Xeon Ice Lake-SP 2소켓, NVIDIA L4)
- 커널: PAL 브랜치 `jgunthorpe/linux dmabuf_map_type` c37cf2824740 (`7.0.0-rc1-pal+`)
- 드라이버: NVIDIA 580.178.04 오픈 커널 모듈 이식본, upcie-experimental 0.9.0 이식본
- 자료: 브랜치 `jaeyoon-choi/aisio poc/iommufd-pal`의 `notes/pal-poc/` (소스, 패치, 매뉴얼, 단계별 보고서 두 편, 원본 로그)
- 단계별 보고서: `results-2026-10-13.md`(개발 PC), `results-2026-10-15.md`(sid와 개발 PC 재측정). 이 문서는 두 편과 계획 검토(`2026-10-13-iommufd-poc-plan-review.md`)를 하나로 묶는다.

## 요약

**질문.** 본 팀은 NVMe가 CUDA로 할당한 GPU 메모리에 직접 DMA하도록, 그 메모리를 자체 커널 모듈 `iommu_map_pa`로 NVMe의 IOMMU 페이지 테이블에 넣고 있다. 업스트림에 제안된 PAL(Physical Address List) RFC에 NVIDIA exporter를 붙이면, 이 일을 업스트림 iommufd의 `IOMMU_IOAS_MAP_FILE`이 대신할 수 있는가.

**답.** 대신할 수 있다. NVIDIA 오픈 커널 모듈에 275행(`nv-dmabuf.c` 246행, conftest 28행, Kbuild 1행)을 더하자, PAL 커널의 iommufd가 CUDA dma-buf를 받아 NVMe의 IOMMU 도메인에 2 MiB 엔트리 512개로 매핑했다. 그 매핑으로 NVMe가 GPU 메모리에 쓰는 방향(C1)은 두 호스트 모두에서 데이터가 일치했다. GPU 메모리를 읽는 방향(C2)은 sid에서 일치했고, 개발 PC에서는 PAL과 무관한 플랫폼 제약으로 실패했다.

**이유.** 매핑의 정확성은 세 관측이 함께 보인다. 첫째, IOVA(0x400000)가 BAR1 물리주소와 다른데도 데이터가 일치했다. 둘째, 매핑하지 않은 IOVA로 보낸 요청은 DMAR fault로 막혔다. 셋째, PTE가 BAR1 물리주소를 2 MiB 단위로 가리켰다. 개발 PC의 C2 실패는 번역을 끈 경로에서도 같았다. 오류 비트를 보면 NVMe의 읽기 요청이 GPU 쪽 루트 포트에 닿기 전에 루트 콤플렉스가 UR로 거부했다. 그래서 PAL, iommufd, NVIDIA exporter는 원인이 아니다.

**성립 조건.**
- 커널: PAL 브랜치 c37cf2824740 그대로.
- IOMMU: Intel VT-d 번역 켬, vfio-pci cdev와 iommufd.
- 드라이버: NVIDIA 580.178.04 이식본(discrete GPU).
- 버퍼와 전송: 1 GiB 단일 구간 CUDA 버퍼, 4 KiB와 64 KiB 전송.
- 확인한 것: 데이터 일치만 확인했다. 대역폭, 지연, 수명 시나리오는 측정하지 않았다.

**측정값.**

| 시험 | 개발 PC (Raptor Lake) | sid (Ice Lake-SP) |
|---|---|---|
| 배포 커널 iommufd가 NVIDIA dma-buf 거부 | 미시험 | `errno=95` |
| PAL 매핑 `IOMMU_IOAS_MAP_FILE` | OK, 2 MiB x 512 | OK, 2 MiB x 512 |
| C1 NVMe→GPU (번역) | MATCH | MATCH |
| C2 GPU→NVMe (번역) | `sc=0x4` | MATCH |
| C1 번역 없음 | MATCH | MATCH |
| C2 번역 없음 | `sc=0x4` | MATCH |
| CPU의 BAR1 읽기 | MATCH | MATCH |
| D 미매핑 IOVA 읽기 | `sc=0x4` + DMAR Read fault | `sc=0x4` + DMAR Read fault |
| D2 미매핑 IOVA 쓰기 (posted) | 명령 OK + DMAR Write fault | 명령 OK + DMAR Write fault |
| C2 뒤 UR 수신 비트 | NVMe와 NVMe 쪽 루트 포트만 | 해당 없음 |
| iommufd selftest | 236 pass, 0 fail, 5 skip | 미실행 |

**의미.**
- 본 팀의 주 사용 경로인 NVMe→GPU 읽기는 업스트림 iommufd 경로로 옮길 수 있다. 쓰기 방향(GPU→NVMe)은 서버 플랫폼에서는 되고 Intel 클라이언트 플랫폼에서는 되지 않는다. 이 성질은 `iommu_map_pa`를 쓰든 PAL을 쓰든 같다.
- 이 경로를 실제로 쓰려면 두 가지가 해결되어야 한다. PAL RFC가 업스트림에 머지되어야 하고, NVIDIA가 exporter를 제공해야 한다. PoC는 두 조건이 갖춰지면 기능 요구(양방향 데이터 경로와 미매핑 IOVA 보호)가 충족된다는 것을 보였다. 성능과 수명 관리는 아직 확인하지 않았다.

**바로잡은 이전 기록.**
- 개발 PC C2 실패의 원인으로 세웠던 SNP 비트 가설은 기각했다. 그 가설의 근거였던 "이 PC에서 GPU→NVMe가 이전에 성공했다"는 기억은 기록으로 확인되지 않았다.
- sid 실행 보고서의 서술 세 가지를 정정했다. 원인을 "대조로 확인"했다는 서술, 시험 NVMe를 루트 포트 아래로 본 서술, PTE 엔트리를 514개로 센 서술이다.
- 시험 도구의 CC 레지스터 버그가 결과에 영향을 주지 않았음을 재측정으로 확인했다. 경위는 §9에 있다.

**확인하지 못한 것.**
- 개발 PC 루트 콤플렉스의 거부가 설계상 제약인지는 Intel 문서로 확인하지 못했다.
- C2의 대역폭과 지연은 측정하지 않았다.
- 소켓 간 경로, fd close 뒤의 동작, 반복 map/unmap, 강제 종료는 시험하지 않았다.
- 개발 PC에서 고친 도구로 PAL 커널 경로를 다시 측정하지 않았다.
- 각 항목의 다음 단계는 §11에 있다.

**반영한 변경.**
- NVIDIA 580.178.04용 PAL 이식 패치와 upcie-experimental용 이식 패치를 만들었다.
- 시험 도구 `pal_probe`, `pal_nvme`, `bar1_cpu_read`를 작성했다. 시험 도구의 CC 버그를 고쳤다.
- sid 실행 매뉴얼을 만들었다.
- 커널 쪽 코드는 바꾸지 않았다.

## 1. 배경: GPU 메모리를 NVMe의 IOMMU에 넣는 문제

NVMe가 GPU 메모리에 직접 DMA하려면 NVMe에게 GPU 메모리의 주소가 보여야 한다. IOMMU가 켜진 호스트에서 장치가 내는 주소는 IOVA다. 그 IOVA가 GPU BAR1의 물리주소로 번역되도록 NVMe의 IOMMU 페이지 테이블에 엔트리를 넣어야 한다. 사용자 공간 드라이버(vfio-pci와 iommufd)는 호스트 메모리를 `IOMMU_IOAS_MAP`으로, 파일 기반 메모리를 `IOMMU_IOAS_MAP_FILE`로 매핑한다. 그런데 업스트림 iommufd는 GPU 드라이버가 내보낸 dma-buf를 받지 않는다. 현재 업스트림이 받는 dma-buf exporter는 vfio-pci 하나뿐이다.

그래서 본 팀은 upcie의 실험용 모듈 `iommu_map_pa`로 이 일을 한다. 사용자 공간은 `dmabuf_import` 모듈로 CUDA dma-buf의 BAR1 물리주소 목록을 얻는다. `iommu_map_pa`는 그 목록을 받아 NVMe가 쓰는 IOMMU 도메인에 `iommu_map(..., IOMMU_MMIO)`로 직접 넣는다. 이 방식은 동작하지만, 모듈의 README가 적듯 iommufd의 IOVA 회계, 수명 관리, 락, dirty tracking을 모두 우회한다. 또 커널은 exporter가 누구인지, 물리주소가 유효한지를 확인하지 않는다. README는 이 모듈이 production-safe가 아니라고 명시하고, 장기 방향으로 "`IOMMU_IOAS_MAP_FILE`에 CUDA dma-buf 지원"을 지목한다. 이 PoC는 그 장기 방향이 실제로 동작하는지를 확인한다.

규모를 먼저 숫자로 보면 다음과 같다. CUDA 버퍼 1 GiB는 BAR1에서 연속 구간 하나이고, VT-d가 2 MiB 페이지를 쓰면 엔트리 512개로 매핑된다. 이 숫자에서 방식 선택의 기준 하나가 나온다. 구간 목록을 그대로 IOMMU에 넣는 방식이면 엔트리가 512개다. 페이지 단위로 넣는 방식이면 같은 버퍼에 4 KiB 엔트리가 262,144개 생긴다.

업스트림에는 이 문제를 겨냥한 제안이 둘 있다. 어느 쪽을 PoC에 쓸지가 첫 결정이었다.

## 2. 방식 선택: PAL과 mm memory provider

두 RFC 모두 머지되지 않았다.

| 항목 | PAL (Jason Gunthorpe, NVIDIA) | mm memory provider (Fred Griffoul, Amazon) |
|---|---|---|
| exporter 인터페이스 | dma-buf에 mapping type 체계를 넣고, exporter가 물리주소 구간 목록(`dma_buf_phys_list`)을 내는 PAL 타입을 제공 | 메모리 소유 드라이버가 provider 파일을 내고, consumer가 페이지마다 `get_page()`로 PFN을 받음 |
| iommufd 쪽 | 브랜치에 구현됨. 구간 목록을 큰 페이지로 매핑 | PAGE_SIZE 엔트리로 매핑 |
| CUDA와의 접점 | 기존 CUDA dma-buf fd를 그대로 사용 | NVIDIA가 새 종류의 fd를 내야 함 |
| 검증 상태 | 브랜치에 selftest 포함 | 커버 레터가 mock 도메인 외 미검증이라고 밝힘 |
| 1 GiB 버퍼의 엔트리 수 | 512 (2 MiB) | 262,144 (4 KiB) |

PoC에는 PAL을 골랐다. 이유는 셋이다. 기존 CUDA dma-buf fd를 그대로 쓸 수 있다. iommufd 쪽 코드가 이미 브랜치에 있어 새로 짤 코드가 NVIDIA exporter뿐이다. 매핑 단위가 현재 `iommu_map_pa`와 같은 2 MiB다. mm 방식은 코드가 더 나오면 같은 시험 도구로 비교하기로 했다.

ChatGPT가 세운 원래 계획에서는 두 가지를 고쳤다. 첫째, 계획은 "번역된 P2P가 되는지"를 최대 불확실성으로 놓았다. 하지만 본 팀은 이미 두 호스트에서 번역된 P2P를 관측했으므로 이 항목은 회귀 확인으로 내렸다. 둘째, 계획은 PAL 브랜치가 `dma_buf_ops.map_dma_buf`를 없앤다는 것을 놓쳤다. 이 때문에 NVIDIA exporter 전체를 mapping type 체계로 옮기는 이식이 필요했다. 실제로 PoC 코드 작업의 대부분이 이 이식이었다.

방식을 정했으니, 이제 주소와 데이터가 어떤 경로로 지나가는지 본다.

## 3. 전체 구조와 용어

PoC에서 데이터와 주소가 지나는 경로는 다음 순서다.

1. CUDA가 GPU 메모리 1 GiB를 할당하고 `cuMemGetHandleForAddressRange`로 dma-buf fd를 낸다.
2. 사용자 프로그램이 그 fd를 iommufd의 `IOMMU_IOAS_MAP_FILE`에 넘긴다.
3. iommufd가 dma-buf에 PAL 타입으로 attach하고, NVIDIA exporter의 `map_phys`가 BAR1 물리주소 구간 목록을 돌려준다.
4. iommufd가 그 구간을 IOAS의 IOVA에 `IOMMU_MMIO`로 매핑하고, NVMe가 붙은 HWPT의 VT-d 페이지 테이블에 엔트리가 생긴다.
5. 사용자 공간 NVMe 드라이버가 그 IOVA를 PRP에 넣어 명령을 낸다. VT-d가 IOVA를 BAR1 물리주소로 번역하고, 루트 콤플렉스가 요청을 GPU로 전달한다.

이 문서를 읽는 데 필요한 용어는 다음과 같다.

| 용어 | 뜻 |
|---|---|
| PAL | dma-buf exporter가 물리주소 구간 목록을 내는 mapping type. 브랜치에서는 iommufd만 사용 |
| IOAS, HWPT | iommufd의 주소 공간 객체와 그것을 하드웨어 페이지 테이블로 실현한 객체 |
| C1 | NVMe 읽기 명령으로 GPU 메모리에 쓰기. PCIe에서는 장치의 posted write |
| C2 | NVMe 쓰기 명령으로 GPU 메모리를 읽기. PCIe에서는 장치의 non-posted read |
| D, D2 | 매핑하지 않은 IOVA로 보내는 읽기(D)와 쓰기(D2) |
| UR | Unsupported Request 완료. 요청을 받을 곳이 없을 때 돌아온다 |
| SNP | VT-d PTE의 snoop 비트(bit 11) |

sid에서 관측한 실제 값을 이 경로에 대입하면 다음과 같다. CUDA 버퍼 1 GiB는 BAR1 물리주소 `0x20a031e00000`에서 시작하는 연속 구간 하나였다. `pal_probe`가 이 버퍼를 IOVA `0x200000`에 매핑했을 때, VT-d debugfs에는 다음 엔트리가 있었다.

| IOVA | PTE | 가리키는 물리주소 |
|---|---|---|
| 0x200000 | 0x000020a031e00883 | 0x20a031e00000 (BAR1 버퍼 시작) |
| 0x400000 | 0x000020a032000883 | 0x20a032000000 (+2 MiB) |
| 0x600000 | 0x000020a032200883 | 0x20a032200000 (+4 MiB) |
| ... | ... | 512번째 엔트리까지 2 MiB씩 증가 |

PTE의 하위 비트 `0x883`은 읽기(bit 0), 쓰기(bit 1), 2 MiB 페이지(bit 7), SNP(bit 11)다. IOVA와 물리주소가 다르므로 NVMe가 내는 주소는 VT-d를 거쳐야만 GPU에 닿는다. 구조를 보았으니, 이 경로를 만들기 위해 무엇을 고쳤는지 본다.

## 4. 구현

### 4.1 커널

PAL 브랜치 c37cf2824740(v7.0-rc1 기반, 34커밋)을 수정 없이 빌드했다. `CONFIG_IOMMUFD`, `CONFIG_IOMMUFD_TEST`, `CONFIG_VFIO_PCI_DMABUF`, `CONFIG_PCI_P2PDMA`, `CONFIG_INTEL_IOMMU_DEBUGFS`를 켰다. 개발 PC에서는 iommufd selftest가 hugepage 64개를 예약한 뒤 236 pass, 0 fail, 5 skip이었다. 처음 실패한 22건은 모두 `MAP_HUGETLB` mmap 실패였다. dma-buf 관련 테스트(`dmabuf_simple`, `dmabuf_multi_page`, `dmabuf_revoke`)는 두 번 모두 통과했다.

### 4.2 NVIDIA exporter 이식

NVIDIA 580.178.04는 PAL 커널에서 `nv-dmabuf.c`만 빌드에 실패한다. 원인은 셋이다. `dma_buf_ops`에 `map_dma_buf`가 없고, `dma_buf_attachment`에 `dev`가 없고, importer 함수 이름이 `dma_buf_sgt_*`로 바뀌었다. 이식 패치는 `nv-dmabuf.c`에 246행을 더하고 25행을 지운다. 그 밖에 conftest 28행과 Kbuild 1행을 더한다.

- `nv_dma_buf_match_mapping()`이 importer에 제시할 mapping type을 정한다. discrete GPU이거나 FORCE_PCIE이면 PAL을 먼저 제시하고, 그다음 plain SGT를 제시한다. iommufd는 PAL만 요청하므로 PAL이 선택된다. `dmabuf_import` 같은 SGT importer는 SGT로 선택된다.
- `nv_dma_buf_pal_map_phys()`는 기존 `nv_dma_buf_get_phys_addresses()`로 RM에서 `memArea.pRanges[]`를 받아 `dma_buf_phys_list`로 옮긴다. `unmap_phys`는 목록을 해제하고 참조를 돌려준다.
- 토폴로지 검사는 `dev_is_pci()`로 감쌌다. 그래서 PCI 장치가 아닌 importer(misc 장치)는 검사를 건너뛰어 기존 동작을 유지한다.
- conftest에 `dma_buf_ops_has_match_mapping` 항목을 더했다. 같은 소스가 PAL 커널과 기존 커널 양쪽에서 빌드된다.

NVIDIA DKMS는 7.0 커널에서 소스 컴파일 전에 실패한다. 그래서 `make SYSSRC=<kernel> NV_EXCLUDE_KERNEL_MODULES=nvidia-peermem modules`로 직접 빌드했다.

### 4.3 upcie-experimental 이식

`dmabuf_import`는 같은 API 변경 때문에 다섯 곳을 고쳤다(31행 추가, 4행 삭제). Makefile이 `include/linux/dma-buf-mapping.h`의 존재로 PAL 커널을 판별하므로, 같은 소스가 두 커널에서 빌드된다. `iommu_map_pa`는 수정 없이 빌드되었다.

### 4.4 시험 도구

| 도구 | 보여주는 것 | 필요한 이유 |
|---|---|---|
| `pal_probe` | CUDA dma-buf가 `IOMMU_IOAS_MAP_FILE`로 매핑되는가. `--hold`로 매핑을 유지 | 매핑 자체의 성공과 PTE 관찰. 데이터 경로는 보지 못한다 |
| `pal_nvme --vfio` | vfio cdev와 iommufd로 묶은 NVMe에 C1, C2, D, D2를 실행하고 `cuMemcpy`로 대조 | 매핑이 실제 DMA에 쓰이는지와 보호가 적용되는지를 본다 |
| `pal_nvme --identity` | GPU를 BAR1 물리주소와 같은 IOVA에 매핑 | 실패가 주소 값 때문인지 가른다 |
| `pal_nvme --uio` | identity 도메인과 uio_pci_generic으로 번역 없이 물리주소로 실행 | 실패가 번역과 무관한지 가른다. 앞의 두 도구로는 IOMMU를 경로에서 뺄 수 없다 |
| `bar1_cpu_read` | CPU가 BAR1 mmap으로 같은 버퍼를 읽음 | BAR1 주소와 내용이 올바른지 확인한다. 장치 간 읽기만의 문제인지 가른다 |
| `pte-dump.sh` | VT-d debugfs의 PTE | 페이지 크기, 물리주소, SNP 비트를 직접 본다 |
| `lspci` Status, DevSta | C2 뒤 어느 장치가 UR을 받았는지 | 오류 완료가 루트 콤플렉스에서 나왔는지 GPU에서 나왔는지 가른다. NVMe의 `sc=0x4`만으로는 알 수 없다 |

도구는 위에서 아래로 갈수록 경로에서 요소를 하나씩 뺀다. 다음 절은 이 도구들이 어떤 결과를 내야 하는지를 원리로 먼저 정한다.

## 5. 원리와 예상 결과

NVMe 명령의 방향과 PCIe 트랜잭션은 반대로 대응한다. NVMe 읽기 명령(C1)에서는 장치가 GPU 메모리에 posted write를 낸다. posted write는 완료가 없으므로, 라우팅이나 IOMMU에서 막혀도 장치는 알 수 없고 명령은 성공으로 끝난다. NVMe 쓰기 명령(C2)에서는 장치가 GPU 메모리에 non-posted read를 낸다. 읽기는 완료가 돌아와야 하므로, 막히면 UR이나 CA 완료가 돌아오고 NVMe는 이를 Data Transfer Error(`sc=0x4`)로 보고한다. 따라서 플랫폼이 장치 간 전달을 지원하는지는 C2가 가르고, IOMMU 보호가 적용되는지는 D가 가른다.

| 조건 | C1 | C2 | D | D2 |
|---|---|---|---|---|
| 매핑 정상, 플랫폼이 장치 간 읽기와 쓰기 전달 (가정) | MATCH | MATCH | 해당 없음 | 해당 없음 |
| 매핑 정상, 플랫폼이 장치 간 쓰기만 전달 (가정) | MATCH | `sc=0x4`, DMAR fault 없음 | 해당 없음 | 해당 없음 |
| 매핑이 틀린 경우 (가정) | MISMATCH 또는 DMAR fault | DMAR fault | 해당 없음 | 해당 없음 |
| 매핑하지 않은 IOVA | 해당 없음 | 해당 없음 | `sc=0x4` + DMAR Read fault | 명령 OK + DMAR Write fault |

이 표에 따르면 C1 MATCH와 D fault가 함께 나오면 매핑과 보호가 모두 정상이다. 그 상태에서 C2만 fault 없이 `sc=0x4`이면 원인은 IOMMU 뒤쪽, 즉 플랫폼에 있다. 이 표를 기준으로 두 호스트의 결과를 차례로 본다.

## 6. 개발 PC 결과

개발 PC는 i9-14900K(호스트 브리지 8086:a700)다. GPU는 CPU 루트 포트 00:01.0 아래, 예비 NVMe는 00:01.1 아래에 있다.

| 시험 | 결과 |
|---|---|
| `pal_probe` (장치 없이, NVMe 부착 후) | `IOMMU_IOAS_MAP_FILE` OK, IOVA 0x200000 |
| C1 4 KiB, 64 KiB | MATCH |
| C2 4 KiB, 64 KiB, identity IOVA | `sct=0 sc=0x4`, DMAR fault 없음 |
| D | `sc=0x4` + "PTE Read access is not set" |
| D2 | 명령 OK + "PTE Write access is not set" |
| PTE | 2 MiB x 512, 하위 비트 0x883 (R, W, PS, SNP) |
| `dmabuf_import` 회귀 | 64 KiB x 16384, 연속 1 GiB |

C1과 D는 §5 표의 "매핑 정상" 행과 일치한다. IOVA 0x400000이 BAR1 물리주소 0x480e800000과 다른데도 데이터가 일치했으므로, NVMe의 쓰기는 VT-d 번역을 거쳐 GPU 메모리에 도달했다. C2는 "장치 간 쓰기만 전달" 행과 같은 모양이다. 원인을 가리기 위해 §8의 순서로 가설을 하나씩 확인했다.

## 7. sid 결과

sid는 Ice Lake-SP 2소켓이다. 호스트 브리지 8086:09a2는 커널 p2pdma 허용 목록에 있다. 비교 호스트로 sid를 고른 이유는 두 가지다. 개발 PC와 달리 서버 플랫폼이고, 본 팀이 실제 벤치마크를 돌리는 호스트다. 실행은 sia의 Claude Code 세션이 매뉴얼을 따라 했고, 운영자가 단계마다 승인했다.

### 7.1 경로 구조

GPU는 호스트 브리지 30의 루트 포트 30:02.0 바로 아래에 있다. 시험 NVMe 0000:4e:00.0은 호스트 브리지 4a에 있고, 루트 포트 4a:02.0 아래 Microchip PCIe 스위치의 하위 포트 4c:01.0에 붙어 있다. 두 호스트 브리지는 모두 소켓 0의 IIO 스택이다. 스위치 하위 포트는 ACS `ReqRedir+`이므로 장치 간 요청은 스위치 안에서 처리되지 않고 위로 올라간다. 따라서 C2의 읽기 요청은 루트 포트 4a:02.0에서 소켓 0의 메시를 거쳐 루트 포트 30:02.0으로 간다. sid에는 GPU와 같은 호스트 브리지 아래에 NVMe가 없으므로, 같은 호스트 브리지 안의 경로는 시험할 수 없었다.

### 7.2 단계별 결과

| 단계 | 커널 | 결과 |
|---|---|---|
| A0 | 배포 7.0.0-34-generic | `IOMMU_IOAS_MAP_FILE: FAILED errno=95` |
| A1 번역 없음 | 같음 | C1, C2 모두 MATCH (64K, 4K) |
| A2 | 같음 | CPU의 BAR1 읽기 MATCH |
| C0 | PAL | `IOMMU_IOAS_MAP_FILE: OK iova=0x200000 length=0x40000000` |
| C1, C2 번역 | PAL | 모두 MATCH (64K, 4K, identity IOVA) |
| D, D2 | PAL | `sc=0x4` + Read fault, 명령 OK + Write fault |
| PTE | PAL | `0x000020a031e00883`부터 2 MiB 간격, 512개 |

단계 A를 먼저 한 이유는 커널을 바꾸기 전에 플랫폼이 장치 간 읽기를 전달하는지부터 가리기 위해서다. A1에서 C2가 성공했으므로 sid는 §5 표의 "읽기와 쓰기 전달" 행이다. 단계 C에서는 PAL 경로로도 같은 결과가 나왔다. A0는 배포 커널이 NVIDIA dma-buf를 받지 않는다는 것을 보인다. 따라서 단계 C의 매핑 성공은 PAL 커널과 이식한 exporter가 만든 결과다. sid에서 C2가 성공했으므로, 이제 개발 PC의 C2 실패 원인을 좁힐 수 있다.

## 8. 원인 분석 경과

개발 PC의 C2 실패에 대해 세운 가설과 그것을 확인한 실험은 다음 순서다.

| 순서 | 가설 | 실험 | 결과 | 판단 |
|---|---|---|---|---|
| 1 | 주소 값 문제 | identity IOVA로 C2 | 같은 실패 | 기각 |
| 2 | 번역된 peer 읽기에 SNP 비트가 붙어 루트 콤플렉스가 거부 | MMIO PTE에서 SNP를 빼는 커널로 C2. PTE `0x...083` 확인 | 같은 실패 | 기각 |
| 3 | IOMMU 번역 자체가 원인 | identity 도메인과 uio로 물리주소 C2 | 같은 실패 | 기각 |
| 4 | BAR1 주소나 내용 문제 | CPU로 BAR1 읽기 | MATCH | 기각 |
| 5 | PAL 경로나 NVIDIA 이식본 문제 | 같은 커널, 모듈, 도구로 sid에서 C2 | MATCH | 기각 |
| 6 | 시험 도구의 CC 버그 | 고친 도구와 버그 도구로 번역 없는 C2 | 둘 다 같은 실패 | 기각 |
| 7 | GPU가 읽기를 거부 | 오류 비트를 지운 뒤 C2 한 번, 네 장치의 Status와 DevSta 확인 | NVMe와 00:01.1에만 `<MAbort+`, GPU와 00:01.0은 비트 없음 | 기각 |

7번 실험의 표는 다음과 같다.

| 장치 | 지운 뒤 | C2 한 번 뒤 |
|---|---|---|
| 00:01.0 (GPU 쪽 루트 포트) | 비트 없음 | 비트 없음 |
| 00:01.1 (NVMe 쪽 루트 포트) | 비트 없음 | `<MAbort+` |
| 01:00.0 (GPU) | 비트 없음 | 비트 없음 |
| 02:00.0 (NVMe) | 비트 없음 | `<MAbort+` |

`<MAbort+`는 Received Master Abort이고, UR 완료를 받았다는 뜻이다. GPU와 GPU 쪽 루트 포트에는 아무 기록이 없으므로 요청은 GPU 쪽에 도달하지 않았다. 루트 콤플렉스가 NVMe 쪽 루트 포트에서 들어온 peer 읽기를 UR로 끝냈다. 여기까지는 측정이다. 이것이 Raptor Lake 루트 콤플렉스의 설계상 제약(루트 포트 사이의 peer 쓰기는 전달하고 peer 읽기는 전달하지 않음)이라는 해석은 Intel 문서로 확인하지 않은 추정이다. 이 해석은 두 가지 정황과 맞는다. 8086:a700은 커널 p2pdma 허용 목록에 없다. 같은 PC에서 peer 쓰기(C1)는 전달된다.

## 9. 바로잡은 이전 기록

| 이전 서술 | 바로잡은 내용 | 경위 |
|---|---|---|
| 개발 PC C2 실패는 PTE의 SNP 비트 때문으로 추정 (10-13 §5) | SNP를 끄고도, 번역을 끄고도 실패했다. 원인은 루트 콤플렉스의 peer 읽기 거부다 | PTE에서 SNP를 발견하고, DMA-FQ 경로에서 이전에 성공했다는 사용자 기억과 맞춰 본 정황 추론이었다. 그 기억은 아래 행에서 따로 정정한다 |
| sid 결과로 개발 PC 실패 원인을 "대조로 확인" (sid 실행 보고서) | sid 결과는 PAL과 IOMMU를 배제할 뿐이다. 루트 콤플렉스 위치는 §8의 7번 실험으로 확인했고, 설계상 제약이라는 것은 추정이다 | 두 장비는 GPU, NVMe, 경로 구조도 다른데 한 변수의 대조로 보았다 |
| 시험 NVMe가 루트 포트 4c:01.0 아래 (sid 실행 보고서) | 4c:01.0은 Microchip 스위치의 하위 포트이고, 루트 포트는 4a:02.0이다 | 사전 점검 스크립트가 NVMe의 바로 위 브리지를 "rootport"로 출력했다 |
| PTE 엔트리 514개 (sid 실행 보고서) | 512개다 | `pte-dump.sh`가 `wc -l`로 세어 머리글 2줄이 들어갔다 |
| 이 PC에서 GPU→NVMe가 이전에 성공했다 (10-13 보고서가 인용한 사용자 기억) | 이 PC에서 GPU→NVMe를 측정한 기록은 없다. GDS 기록은 읽기와 바운스 버퍼 경로뿐이다. 루트 콤플렉스가 peer 읽기를 UR로 거부하므로, 이전에 성공한 실행이 있었다면 직접 P2P 읽기가 아니라 호스트 메모리를 거친 경로였다고 추정한다 | 기억을 기록으로 확인하지 않은 채 SNP 가설의 근거로 썼다 |
| 시험 도구가 CC에 IOSQES=6, IOCQES=4를 씀 | 실제로는 두 값을 바꿔 썼다(0x00640001). 개발 PC 결과에는 영향이 없음을 재측정으로 확인했다 | 시프트 16과 20을 바꿔 적었다. 개발 PC 드라이브는 이 값을 검사하지 않았고, sid 드라이브가 I/O CQ 생성을 `0x102`로 거부해 드러났다 |

## 10. 의미와 제언

**`iommu_map_pa` 대체 가능성.** 기능 면에서는 대체할 수 있다. PAL 경로는 `iommu_map_pa`와 같은 2 MiB 엔트리를 만든다. 또 iommufd IOAS 안에서 매핑하므로, 매핑하지 않은 IOVA에 대한 보호(D, D2)가 그대로 적용된다. 처리량은 측정하지 않았다. 다만 페이지 테이블 모양이 같으므로 `iommu_map_pa` 경로와 같은 처리량이 나올 것으로 추정한다.

**남은 장벽은 업스트림 상태다.** PAL은 RFC 단계다. PAL 헤더는 이 타입을 쓰기 전에 dma-buf 메인테이너와 상의하라고 적는다. NVIDIA exporter는 이 PoC가 out-of-tree로 만든 것이고, NVIDIA 오픈 모듈에 들어간 것이 아니다. 따라서 이 PoC 결과를 지금 바로 생산 경로에 쓸 수는 없다. 쓸 수 있는 곳은 두 가지다. 하나는 PAL 또는 mm provider 스레드에 "GPU 메모리를 NVMe 사용자 공간 드라이버에 매핑하는 실사용 사례"로 내는 실증 자료다. 다른 하나는 NVIDIA에 exporter 지원을 요청할 근거다.

**플랫폼 제약은 매핑 방식과 별개다.** GPU→NVMe 방향은 Intel 클라이언트 플랫폼에서 어떤 매핑 방식으로도 되지 않는다. 본 팀이 쓰기 워크로드를 개발 PC에서 시험하려면, PAL 경로를 쓰든 쓰지 않든 GPU 메모리를 호스트 메모리로 복사하는 경로가 필요하다. 반대로 sid 같은 서버에서는 양방향이 된다.

**D2가 보여 주는 수명 문제.** 매핑되지 않은 IOVA로 NVMe 읽기 명령을 보내면 데이터는 버려지고 명령은 성공으로 끝난다. 그래서 unmap은 그 IOVA를 쓰는 명령이 모두 끝난 뒤에만 해야 한다. 이 순서는 iommufd가 보장하지 않으므로 사용자 공간 드라이버(xNVMe upcie 백엔드)가 지켜야 한다.

## 11. 확인하지 못한 것과 다음 단계

| 항목 | 다음 단계 |
|---|---|
| 개발 PC 루트 콤플렉스의 peer 읽기 거부가 설계상 제약인지 | Raptor Lake 데이터시트와 BIOS 설정에서 루트 포트 간 peer read 지원 여부를 확인한다 |
| 고친 도구로 PAL 커널 경로 재측정 (개발 PC) | PAL 커널로 부팅해 고친 `pal_nvme`로 C1, C2, D를 다시 실행한다 |
| C1, C2의 대역폭과 지연 | 큰 전송과 깊은 큐로 처리량을 측정하고 `iommu_map_pa` 경로와 비교한다 |
| 매핑과 해제 비용 | gpu-iommu-map-size 브랜치의 kprobe 도구로 `IOMMU_IOAS_MAP_FILE`과 unmap 지연을 잰다 |
| 소켓 간 경로 | sid에서 GPU(소켓 0)와 소켓 1의 NVMe(호스트 브리지 c9, e2)로 C1, C2를 반복한다 |
| 같은 호스트 브리지 안의 경로 | GPU와 NVMe가 같은 호스트 브리지 아래 있는 서버를 찾는다 |
| 수명 시나리오 | fd close 뒤 I/O, 반복 map과 unmap, 명령 진행 중 강제 종료를 KASAN 빌드로 시험한다 |
| NVIDIA exporter의 revoke | NVIDIA는 `dma_buf_invalidate_mappings()`를 부르지 않는다. GPU 메모리 해제 시 매핑이 어떻게 되는지 확인한다 |
| mm memory provider와의 비교 | mm RFC의 다음 버전이 나오면 같은 도구로 매핑 엔트리 수와 지연을 비교한다 |

## 12. 자료 위치

| 자료 | 위치 |
|---|---|
| 이식 패치 (NVIDIA, upcie, SNP 실험 커널) | `notes/pal-poc/patches/` |
| 시험 도구 소스 | `notes/pal-poc/src/` |
| 실행 스크립트 | `notes/pal-poc/scripts/` |
| sid 실행 매뉴얼 | `notes/pal-poc/MANUAL.md` |
| 개발 PC 결과 보고서 | `notes/pal-poc/results-2026-10-13.md` |
| sid 결과와 개발 PC 재측정 보고서 | `notes/pal-poc/results-2026-10-15.md` |
| sid 원본 로그, 커널 config, 토폴로지 | `notes/pal-poc/sid-raw/` |
| 개발 PC 재측정 로그 | `notes/pal-poc/devpc-raw/run-2026-10-15-ccfix-ab.log` |
| 개발 PC 1차 원본 로그 | `/data/aisio/pal-poc/run-2026-10-13.log`, `dmesg-2026-10-13.log`, `run-2026-10-14-*.log` |
| PoC 계획 검토 | `~/Documents/Claude/aisio/2026-10-13-iommufd-poc-plan-review.md` (작성자 로컬) |
| 업스트림 현황 보고서 | `notes/iommufd-gpu-memory.md` (브랜치 `docs/iommufd-gpu-memory`) |
