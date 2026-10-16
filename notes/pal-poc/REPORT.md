# PAL 기반 iommufd GPU 메모리 매핑 PoC 종합 보고서

- 기간: 2026-10-13 ~ 2026-10-16
- 주 시험 호스트: sid (Xeon Ice Lake-SP 2소켓, NVIDIA L4)
- 보조 호스트: 개발 PC jaeyoon-pc (i9-14900K, RTX PRO 4000 Blackwell). 클라이언트 플랫폼 제약 확인에 썼다.
- 커널: PAL 브랜치 `jgunthorpe/linux dmabuf_map_type` c37cf2824740 (`7.0.0-rc1-pal+`)
- 드라이버: NVIDIA 580.178.04 오픈 커널 모듈 이식본, upcie-experimental 0.9.0 이식본
- 자료: 브랜치 `jaeyoon-choi/aisio poc/iommufd-pal`의 `notes/pal-poc/` (소스, 패치, 매뉴얼, 단계별 보고서 두 편, 원본 로그)
- 단계별 보고서: `results-2026-10-13.md`(개발 PC), `results-2026-10-15.md`(sid와 개발 PC 재측정). 이 문서는 두 편과 계획 검토(`2026-10-13-iommufd-poc-plan-review.md`), 2026-10-16 개발 PC 재측정을 하나로 묶는다.

이 보고서는 aisio와 xNVMe 팀의 엔지니어를 독자로 쓴다. NVMe 명령 구조(SQ, CQ, PRP)와 PCIe 기본(BAR, 루트 포트, 트랜잭션 종류)은 안다고 가정하고, iommufd와 dma-buf의 커널 내부는 모른다고 가정한다. `iommu_map_pa`를 대체할지 판단하려면 요약과 §9만 읽으면 된다. 본문은 그 판단의 근거를 sid 결과 중심으로 따라간다. PoC를 다시 빌드하거나 이어서 고칠 사람을 위한 커널 구성과 코드 수정 상세는 §4와 부록 A에 둔다.

## 요약

**질문.** 본 팀은 NVMe SSD가 GPU 메모리에 직접 읽고 쓰게 하려고(GPU P2P DMA), CUDA가 할당한 GPU 메모리의 주소를 자체 커널 모듈 `iommu_map_pa`로 NVMe의 IOMMU 페이지 테이블에 직접 넣고 있다. 이 모듈은 커널의 매핑 관리를 우회하므로 상용 경로로 쓸 수 없다. 업스트림에 제안된 PAL(Physical Address List) RFC 위에서 NVIDIA 드라이버를 고치면, 이 일을 커널 표준 인터페이스인 iommufd의 `IOMMU_IOAS_MAP_FILE`이 대신할 수 있는가.

**답.** 기능 면에서는 대신할 수 있다. NVIDIA 오픈 커널 모듈에 275행(`nv-dmabuf.c` 246행, conftest 28행, Kbuild 1행)을 더하자, PAL 커널의 iommufd가 CUDA 버퍼 1 GiB를 NVMe의 IOMMU에 2 MiB 엔트리 512개로 매핑했다. 서버 sid에서 그 매핑으로 NVMe가 GPU 메모리에 쓰는 방향(C1, NVMe 읽기 명령)과 GPU 메모리를 읽는 방향(C2, NVMe 쓰기 명령)이 모두 데이터 일치했다. 다만 클라이언트 플랫폼인 개발 PC(Raptor Lake)에서는 C2가 되지 않는다. 이것은 PAL과 무관한 플랫폼 제약이고, Intel 데이터시트에 적혀 있다.

**이유.** sid에서 매핑이 올바르다는 근거는 세 관측이다. 첫째, NVMe에게 준 주소(IOVA)가 GPU 메모리의 물리주소와 다른데도 데이터가 일치했다. IOMMU가 주소를 번역해 GPU에 전달했다는 뜻이다. 둘째, 매핑하지 않은 주소로 보낸 요청은 IOMMU가 막고 DMAR fault를 남겼다. 셋째, IOMMU 페이지 테이블 엔트리가 GPU 물리주소를 2 MiB 단위로 가리켰다. 또 같은 sid의 배포 커널은 CUDA dma-buf를 거부했으므로, 매핑 성공은 PAL 커널과 이식한 exporter가 만든 결과다. 개발 PC의 C2 실패는 IOMMU 번역을 끈 상태에서도 같았고, NVMe의 읽기 요청을 CPU의 루트 콤플렉스가 거부했다. Raptor Lake 데이터시트는 프로세서 루트 포트의 P2P 메모리 읽기를 지원하지 않는다고 적는다.

**성립 조건.**
- 커널: PAL 브랜치 c37cf2824740 그대로.
- IOMMU: Intel VT-d 번역 켬, vfio-pci cdev와 iommufd.
- 드라이버: NVIDIA 580.178.04 이식본(discrete GPU).
- 버퍼와 전송: 1 GiB 단일 구간 CUDA 버퍼, 4 KiB와 64 KiB 전송.
- 경로: sid에서 GPU와 NVMe가 같은 소켓의 서로 다른 호스트 브리지에 있는 경로.
- 확인한 것: 데이터 일치만 확인했다. 대역폭, 지연, 수명 시나리오는 측정하지 않았다.

**측정값.**

| 시험 | sid (Ice Lake-SP) | 개발 PC (Raptor Lake) |
|---|---|---|
| 배포 커널 iommufd가 NVIDIA dma-buf 거부 | 거부 (`errno=95`) | 미시험 |
| PAL 매핑 `IOMMU_IOAS_MAP_FILE` | OK, 2 MiB x 512 | OK, 2 MiB x 512 |
| C1 NVMe→GPU (번역) | MATCH | MATCH |
| C2 GPU→NVMe (번역) | MATCH | 실패 (`sc=0x4`) |
| C1 번역 없음 | MATCH | MATCH |
| C2 번역 없음 | MATCH | 실패 (`sc=0x4`) |
| CPU의 BAR1 읽기 | MATCH | MATCH |
| D 미매핑 주소 읽기 | 실패 + DMAR Read fault | 실패 + DMAR Read fault |
| D2 미매핑 주소 쓰기 | 명령 OK + DMAR Write fault | 명령 OK + DMAR Write fault |

MATCH는 DMA로 옮기거나 CPU로 읽은 데이터가 원본 패턴과 바이트 단위로 같았다는 뜻이다. 실패(`sc=0x4`)는 NVMe가 명령을 Data Transfer Error로 끝냈다는 뜻이다. 이 표는 매핑과 보호가 두 호스트에서 같게 동작하고, 두 호스트의 차이는 번역을 켜든 끄든 C2에서만 난다는 것을 보인다.

**의미.**
- NVMe→GPU와 GPU→NVMe 두 방향 모두 서버에서는 업스트림 iommufd 경로로 옮길 수 있다.
- 개발 PC 같은 Raptor Lake 클라이언트에서는 매핑 방식과 관계없이 GPU→NVMe가 되지 않는다. NVMe→GPU도 데이터시트가 보증하지 않는 동작이므로, 성능과 안정성은 서버에서 판단해야 한다.
- 이 경로를 실제로 쓰려면 PAL RFC가 업스트림에 머지되고, NVIDIA가 exporter를 제공해야 한다. 성능과 수명 관리는 아직 확인하지 않았다.

**바로잡은 이전 기록.**
- sid 실행 보고서의 서술 세 가지를 정정했다. 원인을 "대조로 확인"했다는 서술, 시험 NVMe를 루트 포트 아래로 본 서술, PTE 엔트리를 514개로 센 서술이다.
- 개발 PC의 C2 실패를 분석하며 남긴 기록 다섯 가지를 정정했다. SNP 비트 가설, "이전에 성공했다"는 기억, 쓰기만 전달하도록 설계되었다는 추정, 원래 커널로 되돌렸다는 서술, 시험 도구의 CC 버그다. 표와 경위는 §8에 있다.

**확인하지 못한 것.**
- 대역폭과 지연은 측정하지 않았다.
- 소켓 간 경로, fd close 뒤의 동작, 반복 map/unmap, 강제 종료는 시험하지 않았다.
- 각 항목의 다음 단계는 §10에 있다.

**반영한 변경.**
- NVIDIA 580.178.04용 PAL 이식 패치(275행 추가, 25행 삭제)와 upcie-experimental용 이식 패치(27행 추가, 4행 삭제)를 만들었다. 수정 개요는 §4에, 파일별, 함수별 상세는 부록 A에 있다.
- 시험 도구 `pal_probe`, `pal_nvme`, `bar1_cpu_read`를 작성했다. 시험 도구의 CC 버그를 고쳤다.
- sid 실행 매뉴얼을 만들었다.
- 커널 쪽 코드는 바꾸지 않았다.

## 1. 배경: GPU 메모리를 NVMe의 IOMMU에 넣는 문제

NVMe가 GPU 메모리에 직접 DMA하려면 NVMe가 GPU 메모리를 가리키는 주소를 써야 한다. NVIDIA GPU는 GPU 메모리(VRAM)의 일부를 BAR1이라는 PCIe 메모리 창으로 노출하고, 다른 장치는 BAR1의 물리주소로 GPU 메모리에 접근한다. 그런데 IOMMU가 켜진 호스트에서 장치가 내는 주소는 물리주소가 아니라 IOVA(I/O virtual address)다. IOMMU(Intel 플랫폼에서는 VT-d)는 장치마다 둔 페이지 테이블로 IOVA를 물리주소로 번역한다. 그래서 NVMe의 IOMMU 페이지 테이블에 "IOVA에서 BAR1 물리주소로" 가는 엔트리가 있어야 한다.

사용자 공간 NVMe 드라이버는 이 페이지 테이블을 커널의 iommufd로 다룬다. iommufd는 `/dev/iommu`로 노출되는 인터페이스이고, vfio-pci에 넘긴 장치의 IOMMU 매핑을 사용자 공간이 만들게 한다. 호스트 메모리는 `IOMMU_IOAS_MAP`으로, 파일 기반 메모리는 `IOMMU_IOAS_MAP_FILE`로 매핑한다. 한편 GPU 메모리를 다른 장치와 나누는 커널의 표준 수단은 dma-buf다. dma-buf는 한 드라이버(exporter)가 버퍼를 fd로 내보내고 다른 드라이버(importer)가 그 fd로 버퍼에 접근하게 하는 커널 프레임워크다. CUDA는 `cuMemGetHandleForAddressRange`로 GPU 메모리를 dma-buf fd로 내보낸다. 그런데 업스트림 iommufd는 `IOMMU_IOAS_MAP_FILE`에 들어온 dma-buf 가운데 vfio-pci가 내보낸 것만 받는다. 그래서 CUDA dma-buf fd를 넘기면 거부한다.

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

방식을 정했으니, 이제 주소와 데이터가 어떤 경로로 지나가는지 본다.

## 3. 전체 구조와 용어

PoC에서 데이터와 주소가 지나는 경로는 다음 순서다.

1. CUDA가 GPU 메모리 1 GiB를 할당하고 `cuMemGetHandleForAddressRange`로 dma-buf fd를 낸다.
2. 사용자 프로그램이 그 fd를 iommufd의 `IOMMU_IOAS_MAP_FILE`에 넘긴다.
3. iommufd가 dma-buf에 PAL 타입으로 attach하고, NVIDIA exporter의 `map_phys`가 BAR1 물리주소 구간 목록을 돌려준다.
4. iommufd가 그 구간을 IOAS의 IOVA에 `IOMMU_MMIO`로 매핑하고, NVMe가 붙은 HWPT의 VT-d 페이지 테이블에 엔트리가 생긴다.
5. 사용자 공간 NVMe 드라이버가 그 IOVA를 PRP에 넣어 명령을 낸다. VT-d가 IOVA를 BAR1 물리주소로 번역하고, 루트 콤플렉스가 요청을 GPU로 전달한다.

| 용어 | 뜻 |
|---|---|
| PAL | dma-buf exporter가 물리주소 구간 목록을 내는 mapping type. 브랜치에서는 iommufd만 사용 |
| IOAS, HWPT | iommufd의 주소 공간 객체와 그것을 하드웨어 페이지 테이블로 실현한 객체 |
| PTE | IOMMU 페이지 테이블 엔트리. IOVA 한 페이지가 가리키는 물리주소와 권한 비트를 담음 |
| C1 | NVMe 읽기 명령으로 GPU 메모리에 쓰기. PCIe에서는 장치의 posted write |
| C2 | NVMe 쓰기 명령으로 GPU 메모리를 읽기. PCIe에서는 장치의 non-posted read |
| D, D2 | 매핑하지 않은 IOVA로 보내는 읽기(D)와 쓰기(D2) |
| DMAR fault | VT-d가 매핑이나 권한이 없는 요청을 막고 커널 로그에 남기는 기록 |
| UR | Unsupported Request 완료. 요청을 받을 곳이 없을 때 돌아온다 |
| `sc=0x4` | NVMe 완료 상태 Data Transfer Error. 장치의 DMA가 오류 완료를 받았을 때 나온다 |
| SNP | VT-d PTE의 snoop 비트(bit 11) |

sid에서 관측한 실제 값을 이 경로에 대입하면 다음과 같다. CUDA 버퍼 1 GiB는 BAR1 물리주소 `0x20a031e00000`에서 시작하는 연속 구간 하나였다. `pal_probe`가 이 버퍼를 IOVA `0x200000`에 매핑했을 때, VT-d debugfs에는 다음 엔트리가 있었다.

| IOVA | PTE | 가리키는 물리주소 |
|---|---|---|
| 0x200000 | 0x000020a031e00883 | 0x20a031e00000 (BAR1 버퍼 시작) |
| 0x400000 | 0x000020a032000883 | 0x20a032000000 (+2 MiB) |
| 0x600000 | 0x000020a032200883 | 0x20a032200000 (+4 MiB) |
| ... | ... | 512번째 엔트리까지 2 MiB씩 증가 |

PTE의 하위 비트 `0x883`은 읽기(bit 0), 쓰기(bit 1), 2 MiB 페이지(bit 7), SNP(bit 11)다. IOVA와 물리주소가 다르므로 NVMe가 내는 주소는 VT-d를 거쳐야만 GPU에 닿는다. 구조를 보았으니, 이 경로를 만들기 위해 무엇을 고쳤는지 본다.

## 4. 구현 개요

이 절은 어떤 커널 위에서, 무엇을 고쳤는지와 왜 그만큼이면 되는지를 설명한다. 함수별 코드와 빌드 절차는 부록 A에 있다.

### 4.1 PAL 커널 구성

PoC 커널은 Jason Gunthorpe(NVIDIA)의 공개 브랜치 `jgunthorpe/linux dmabuf_map_type`의 커밋 c37cf2824740을 수정 없이 빌드한 것이다. 이 브랜치는 메인라인 v7.0-rc1(6de23f81a5e0) 위에 세 층의 커밋을 쌓았다.

| 층 | 범위 | 커밋 수 | 내용 |
|---|---|---|---|
| 1. base | v7.0-rc1..41dae5ac5e15 | 165 | drm-misc-next 개발 트리. PAL 시리즈의 전제가 되는 dma-buf 변경 포함 |
| 2. kunit 전환 시리즈 | 41dae5ac5e15..f1729d539631 | 6 (커버 레터 포함) | dma-buf 자체 시험을 kunit으로 옮김 |
| 3. mapping type 시리즈 | f1729d539631..c37cf2824740 | 28 (커버 레터 포함) | mapping type 체계와 PAL. 이 PoC가 쓰는 부분 |

1층 base에는 이미 다음 dma-buf 변경이 들어 있다. 이 변경들은 메인라인 v7.0-rc1에는 없으므로, 배포 커널과 비교할 때 차이의 일부는 PAL 시리즈가 아니라 base에서 온다.
- ef246da8e63c, 95308225e5ba: importer 콜백 `move_notify`와 `dma_buf_move_notify()`를 `invalidate_mappings`로 이름을 바꿨다. upcie `dmabuf_import`를 고쳐야 했던 이유 중 하나다.
- 8c5f9645c389: iommufd가 dma-buf를 받을 때 `dma_buf_pin()`을 부르게 했다. NVIDIA exporter에 `pin` 콜백이 없어도 되는 이유는 부록 A.2.8에 있다.
- be6d4c9e9d71, 575157b1b5fc: revoke 흐름(`dma_buf_attach_revocable()`)을 더하고 `invalidate_mappings` 콜백을 선택 사항으로 만들었다.

3층 mapping type 시리즈는 네 단계로 나뉜다. NVIDIA 드라이버를 고쳐야 했던 이유는 모두 이 시리즈에 있다.

| 단계 | 커밋 | 내용 | NVIDIA 드라이버에 미친 영향 |
|---|---|---|---|
| 코어 | 476e59f8dedd, 4f2a9799826e, 560b5ff80a0f, 5127679623ac, 8dc8b43eb82b | mapping type 개념, SGT type, `dma_buf_mapping_attach()`, SGT 동작을 `attach->map_type`으로 라우팅 | exporter가 `match_mapping`으로 type을 제시하는 구조가 생김 |
| exporter 변환 | c4c50f3e8000 외 11개 | 트리 안 exporter(simple exporter, amdgpu, xe, vfio-pci, RDMA, habanalabs 등)를 SGT type으로 옮기고, 83c52177f416에서 공통 구조체의 SGT 필드를 지움 | `dma_buf_ops.map_dma_buf`, `dma_buf_attachment.dev`, `dma_buf_attachment.peer2peer`가 사라져 out-of-tree인 NVIDIA가 빌드에 실패 |
| importer 이름 변경 | cd9f602bb99b, e3103a83aa3e, 6cdde449bcde, 169394c2e408 | `dma_buf_attach()` 등 importer 함수를 `dma_buf_sgt_*`로 바꿈 | NVIDIA의 importer 경로와 upcie `dmabuf_import`가 빌드에 실패 |
| PAL | a286ee763f15, 29ddc7d35bb9, f8983286b743, 12e7f38a26d8, 7815c190f793, 3256cae07d96 | PAL type 추가, vfio-pci PAL exporter, iommufd가 PAL만 요청, 여러 물리 구간 지원, selftest와 kunit | NVIDIA가 PAL exporter를 구현하면 iommufd가 받음 |

정리하면 트리 안 exporter는 시리즈가 직접 변환했고, NVIDIA 드라이버는 트리 밖에 있어 변환되지 않았다. 이 PoC의 NVIDIA 패치는 시리즈가 amdgpu와 simple exporter에 한 변환을 NVIDIA에 직접 적용하고, 그 위에 PAL exporter를 더한 것이다.

커널 소스는 고치지 않았다. 설정은 `/boot/config-6.8.12-dmabuf`에서 `localmodconfig`로 줄인 뒤 다음을 켰다. `LOCALVERSION=-pal`, `IOMMUFD=y`, `IOMMUFD_TEST=y`(브랜치에서는 `IOMMU_PT_AMDV1=y`와 `FAULT_INJECTION=y`가 함께 필요), `VFIO_PCI=m`, `VFIO_PCI_DMABUF=y`, `INTEL_IOMMU_DEBUGFS=y`(PTE 덤프용), `KUNIT=m`, `DMABUF_KUNIT_TEST=m`, NVMe와 ext4 내장(루트 파일시스템용), `DEBUG_INFO_NONE`이다. 개발 PC에서는 빌드한 커널을 `make modules_install install`로 설치하고, `grub-reboot`로 한 번만 부팅해 기본 부팅 항목은 바꾸지 않았다. sid는 같은 커밋을 자기 배포 커널의 설정에서 같은 방식으로 줄이고 같은 옵션을 켜서 빌드했다(`MANUAL.md`).

### 4.2 수정 범위

커널은 고치지 않았다. 새로 짠 코드는 NVIDIA exporter의 이식, upcie `dmabuf_import`의 이식, 시험 도구 세 개다. SNP 실험 커널 패치는 가설 검증에만 썼고, 최종 경로에는 들어가지 않는다.

| 대상 | 파일 | 추가 | 삭제 | 역할 |
|---|---|---|---|---|
| PAL 커널 | 없음 | 0 | 0 | 브랜치 c37cf2824740 그대로 |
| NVIDIA 580.178.04 | `nvidia/nv-dmabuf.c` | 246 | 25 | mapping type 이식과 PAL exporter |
| NVIDIA 580.178.04 | `conftest.sh` | 28 | 0 | `match_mapping` 존재 검사 |
| NVIDIA 580.178.04 | `nvidia/nvidia.Kbuild` | 1 | 0 | 위 검사를 빌드에 등록 |
| upcie-experimental 0.9.0 | `dmabuf_import/dmabuf_import.c` | 23 | 4 | importer 함수 이름 변경 대응 |
| upcie-experimental 0.9.0 | `dmabuf_import/Makefile` | 4 | 0 | PAL 커널 판별 |
| SNP 실험 커널 (최종 경로에서 제외) | `drivers/iommu/generic_pt/fmt/vtdss.h` | 6 | 1 | MMIO PTE에서 SNP 제거 |
| 시험 도구 | `pal_probe.c`, `pal_nvme.c`, `bar1_cpu_read.c`, `scripts/*.sh` | 새 파일 | | 매핑과 DMA 시험 |

패치 파일은 `notes/pal-poc/patches/`에 있다. NVIDIA 패치와 upcie 패치는 조건부 컴파일로 짰다. 그래서 같은 소스가 PAL 커널(7.0.0-rc1-pal+)과 기존 커널(6.8.12)에서 모두 빌드된다. 두 커널 모두 실제로 빌드해 확인했다.

### 4.3 exporter에게 필요한 두 가지

PAL 브랜치의 iommufd는 `IOMMU_IOAS_MAP_FILE`로 dma-buf fd를 받으면 PAL 타입으로만 attach를 요청한다. 그래서 exporter는 두 가지를 해야 한다. 첫째, attach 때 dma-buf 코어가 부르는 `match_mapping` 콜백에서 PAL을 지원한다고 제시해야 한다. 둘째, `map_phys`와 `unmap_phys` 콜백으로 버퍼의 물리주소 구간 목록을 내주고 거둬야 한다. iommufd는 받은 구간을 MMIO 속성(`IOMMU_MMIO`)으로 NVMe의 IOMMU 도메인에 넣는다. 나머지 일(IOVA 할당, 페이지 테이블 기록, unmap)은 iommufd가 한다. iommufd 쪽 호출 경로는 부록 A.1에 있다.

### 4.4 NVIDIA exporter 수정

580.178.04는 PAL 커널에서 `nv-dmabuf.c`만 빌드에 실패한다. PAL 브랜치가 dma-buf의 SGT(scatter-gather table) 매핑 콜백을 별도 ops로 옮기고, attachment의 `dev` 멤버를 없애고, importer 함수 이름을 바꿨기 때문이다. 수정은 다음 여덟 항목이다.

| 번호 | 대상 | 내용 | 상세 |
|---|---|---|---|
| 1 | conftest `dma_buf_ops_has_match_mapping` | 커널에 mapping type 체계가 있는지 검사. 이후 수정은 모두 이 매크로로 감싸 기존 커널에서는 원래 코드로 빌드 | A.2.1 |
| 2 | `nv_dma_buf_ops` | SGT 콜백을 새 SGT ops로 옮기고 `match_mapping` 등록 | A.2.2 |
| 3 | `nv_dma_buf_match_mapping()` | discrete GPU에서 PAL을 먼저, SGT를 다음에 제시 | A.2.3 |
| 4 | `nv_dma_buf_pal_map_phys()`, `nv_dma_buf_pal_unmap_phys()` | RM이 보고하는 BAR1 구간을 `dma_buf_phys_list`로 복사하고, 해제 때 참조를 돌려줌 | A.2.4 |
| 5 | `nv_dma_buf_check_peer_device()` | attach의 PCI 토폴로지 검사를 SGT가 선택된 뒤로 옮김 | A.2.5 |
| 6 | `nv_dma_buf_attachment_dev()` | 사라진 `attachment->dev` 대체 | A.2.6 |
| 7 | importer 함수 세 개 | `dma_buf_sgt_*` 이름으로 변경 | A.2.7 |
| 8 | 고치지 않은 것 | pin, revoke, 심볼 네임스페이스, RM, CUDA 사용자 라이브러리 | A.2.8 |

이 가운데 PoC 결과를 좌우하는 것은 3번과 4번이다. 3번이 iommufd에게 PAL을 내주고, 4번이 BAR1 구간을 넘긴다. 나머지는 빌드를 통과시키고 기존 SGT importer(`dmabuf_import`, RDMA)의 동작을 유지하기 위한 수정이다. 수정 전후의 호출 흐름은 다음과 같다.

| importer | PAL 이전 커널 | PAL 커널과 이식 패치 |
|---|---|---|
| iommufd (`IOMMU_IOAS_MAP_FILE`) | 배포 7.0 커널은 vfio-pci가 낸 dma-buf만 받으므로 거부한다(sid A0, `errno=95`) | `dma_buf_mapping_attach(PAL)` → `nv_dma_buf_match_mapping()`이 PAL을 고르고 장치 검사를 건너뜀 → `nv_dma_buf_attach()` → `dma_buf_pin()`(콜백 없음, 0) → `nv_dma_buf_pal_map_phys()`가 BAR1 구간 목록을 돌려줌 → iommufd가 `IOMMU_MMIO`로 매핑 |
| SGT importer (`dmabuf_import`, RDMA 등) | `dma_buf_dynamic_attach()` → `nv_dma_buf_attach()`가 토폴로지와 peer2peer를 검사 → `dma_buf_map_attachment()` → `nv_dma_buf_map()`이 `attachment->dev`로 매핑 | `dma_buf_sgt_dynamic_attach()` → `nv_dma_buf_match_mapping()`이 SGT를 고르고 토폴로지를 검사 → `nv_dma_buf_attach()` → `dma_buf_sgt_map_attachment()` → `nv_dma_buf_map()`이 `dma_buf_sgt_dma_device()`로 매핑 |

dma-buf 코어는 `match_mapping`을 `attach`보다 먼저 부른다(`drivers/dma-buf/dma-buf.c` 1033~1052행). 그래서 장치 검사는 type이 정해지는 `match_mapping` 안으로 옮겼다. 표의 SGT 행에서 peer2peer 검사가 빠진 것은 의도한 변경이 아니라 이식의 한계다. 이유는 부록 A.2.8에 있다. RM과 CUDA 사용자 라이브러리는 고치지 않았으므로, CUDA 응용 쪽은 기존 `cuMemGetHandleForAddressRange()` 호출을 그대로 쓴다. 8번의 revoke는 운영에서 따져야 할 항목이다. NVIDIA exporter는 importer에게 매핑 무효화를 알리지 않으므로, GPU 메모리를 먼저 해제했을 때 iommufd 매핑이 어떻게 되는지는 확인하지 않았다(§10).

### 4.5 upcie `dmabuf_import` 수정

`dmabuf_import`는 CUDA dma-buf를 import해 BAR1 물리주소 목록을 사용자 공간에 주는 upcie 모듈이다. 시험 도구는 identity IOVA 모드, 번역 없는 uio 모드, `bar1_cpu_read`에서 BAR1 물리주소를 얻을 때 이 모듈을 쓴다. PAL 브랜치에서 importer 함수 이름과 콜백 이름이 바뀌어 빌드되지 않았고, 이를 조건부 매크로로 고쳤다. `iommu_map_pa`는 수정 없이 빌드되었다. 상세는 부록 A.3에 있다.

### 4.6 시험 도구

`pal_nvme`는 vfio cdev와 iommufd 위에서 동작하는 최소 NVMe 드라이버다. 커널 nvme 드라이버나 xNVMe를 쓰지 않고 새로 짠 이유는 두 가지다. 매핑 경로를 `IOMMU_IOAS_MAP_FILE` 하나로 고정해야 했고, 명령 하나하나의 완료 상태(`sct`, `sc`)를 그대로 봐야 했다. 시험은 다음 넷이다. 전송 크기를 `XFER`(기본 64 KiB), 시작 LBA를 `--slba`(기본 0), LBA 크기를 512 B로 놓았다.

| 시험 | NVMe 명령 | 데이터 버퍼 IOVA | LBA | 판정 |
|---|---|---|---|---|
| C1 | Write → Read | 호스트 버퍼 1 → GPU IOVA | slba | `cuMemcpyDtoH`로 읽은 GPU 내용이 호스트 패턴과 같음 |
| C2 | Write → Read | GPU IOVA + XFER → 호스트 버퍼 1 | slba + XFER/512 | `cuMemcpyHtoD`로 쓴 패턴이 다시 읽은 내용과 같음 |
| D | Write | GPU IOVA + 1 GiB + 1 GiB (매핑 없음) | slba + 2·XFER/512 | 오류 상태여야 함 |
| D2 | Read | 같은 미매핑 IOVA | slba | 결과만 기록 (posted이므로 OK가 예상) |

64 KiB 전송이면 LBA 0~383을 덮어쓴다. 출력 줄의 "LBA0", "LBA16"은 고정 문자열이고, 실제 범위는 `test LBAs:` 줄에 찍힌다.

C1과 C2는 데이터가 실제로 옮겨졌는지를 CUDA 복사(`cuMemcpyDtoH`, `cuMemcpyHtoD`)로 대조한다. D와 D2는 매핑하지 않은 주소로의 DMA를 IOMMU가 막는지 본다. `pal_nvme` 하나로는 실패가 어디서 났는지 가를 수 없으므로, 경로의 요소를 하나씩 빼는 도구와 모드를 함께 썼다.

| 도구 | 보여주는 것 | 필요한 이유 |
|---|---|---|
| `pal_probe` | CUDA dma-buf가 `IOMMU_IOAS_MAP_FILE`로 매핑되는가. `--hold`로 매핑을 유지 | 매핑 자체의 성공과 PTE 관찰. 데이터 경로는 보지 못한다 |
| `pal_nvme --vfio` | C1, C2, D, D2를 실행하고 `cuMemcpy`로 대조 | 매핑이 실제 DMA에 쓰이는지와 보호가 적용되는지를 본다 |
| `pal_nvme --identity` | GPU를 BAR1 물리주소와 같은 IOVA에 매핑 | 실패가 주소 값 때문인지 가른다 |
| `pal_nvme --uio` | 번역 없이 물리주소로 실행 | 실패가 번역과 무관한지 가른다. 앞의 두 모드로는 IOMMU를 경로에서 뺄 수 없다 |
| `bar1_cpu_read` | CPU가 BAR1 mmap으로 같은 버퍼를 읽음 | BAR1 주소와 내용이 올바른지 확인한다. 장치 간 읽기만의 문제인지 가른다 |
| `pte-dump.sh` | VT-d debugfs의 PTE | 페이지 크기, 물리주소, SNP 비트를 직접 본다 |
| `lspci` Status, DevSta | C2 뒤 어느 장치가 UR을 받았는지 | 오류 완료가 루트 콤플렉스에서 나왔는지 GPU에서 나왔는지 가른다. NVMe의 `sc=0x4`만으로는 알 수 없다 |

도구는 위에서 아래로 갈수록 경로에서 요소를 하나씩 뺀다. 각 도구의 설정 단계, 메모리 배치, 선택 모드는 부록 A.5에 있다. 다음 절은 이 도구들이 어떤 결과를 내야 하는지를 원리로 먼저 정한다.

## 5. 원리와 예상 결과

NVMe 명령의 방향과 PCIe 트랜잭션은 반대로 대응한다. NVMe 읽기 명령(C1)에서는 장치가 GPU 메모리에 posted write를 낸다. posted write는 완료가 없으므로, 라우팅이나 IOMMU에서 막혀도 장치는 알 수 없고 명령은 성공으로 끝난다. NVMe 쓰기 명령(C2)에서는 장치가 GPU 메모리에 non-posted read를 낸다. 읽기는 완료가 돌아와야 하므로, 막히면 UR이나 CA 완료가 돌아오고 NVMe는 이를 Data Transfer Error(`sc=0x4`)로 보고한다. 따라서 플랫폼이 장치 간 전달을 지원하는지는 C2가 가르고, IOMMU 보호가 적용되는지는 D가 가른다.

| 조건 | C1 | C2 | D | D2 |
|---|---|---|---|---|
| 매핑 정상, 플랫폼이 장치 간 읽기와 쓰기 전달 (가정) | MATCH | MATCH | 해당 없음 | 해당 없음 |
| 매핑 정상, 플랫폼이 장치 간 쓰기만 전달 (가정) | MATCH | `sc=0x4`, DMAR fault 없음 | 해당 없음 | 해당 없음 |
| 매핑이 틀린 경우 (가정) | MISMATCH 또는 DMAR fault | DMAR fault | 해당 없음 | 해당 없음 |
| 매핑하지 않은 IOVA | 해당 없음 | 해당 없음 | `sc=0x4` + DMAR Read fault | 명령 OK + DMAR Write fault |

이 표에 따르면 C1 MATCH와 D fault가 함께 나오면 매핑과 보호가 모두 정상이다. 그 상태에서 C2만 fault 없이 `sc=0x4`이면 원인은 IOMMU 뒤쪽, 즉 플랫폼에 있다. 이 표를 기준으로 주 시험 호스트인 sid의 결과를 먼저 보고, 이어서 개발 PC를 본다.

## 6. sid 결과

sid는 Ice Lake-SP 2소켓이다. 호스트 브리지 8086:09a2는 커널 p2pdma 허용 목록에 있다. 주 시험 호스트로 sid를 고른 이유는 두 가지다. 서버 플랫폼이고, 본 팀이 실제 벤치마크를 돌리는 호스트다. 실행은 sia의 Claude Code 세션이 매뉴얼을 따라 했고, 운영자가 단계마다 승인했다.

### 6.1 경로 구조

```text
sid 소켓 0 (Ice Lake-SP)

     IIO 스택 30 ─────── 메시 ─────── IIO 스택 4a
          │                                │
   30:02.0 루트 포트                 4a:02.0 루트 포트
          │                                │
   31:00.0 NVIDIA L4                 4b:00.0 Microchip 스위치 상위 포트
                                           │
                                     4c:01.0 스위치 하위 포트 (ACS ReqRedir+)
                                           │
                                     4e:00.0 시험 NVMe

C1, C2  NVMe → 4c:01.0 → 4b:00.0 → 4a:02.0 → 메시 → 30:02.0 → GPU    둘 다 전달됨
```

GPU(31:00.0)는 호스트 브리지 30의 루트 포트 30:02.0 바로 아래에 있다. 시험 NVMe 0000:4e:00.0은 호스트 브리지 4a에 있고, 루트 포트 4a:02.0 아래 Microchip PCIe 스위치의 하위 포트 4c:01.0에 붙어 있다. 두 호스트 브리지는 모두 소켓 0의 IIO 스택이다. 스위치 하위 포트는 ACS `ReqRedir+`이므로 장치 간 요청은 스위치 안에서 처리되지 않고 위로 올라간다. 따라서 C2의 읽기 요청은 루트 포트 4a:02.0에서 소켓 0의 메시를 거쳐 루트 포트 30:02.0으로 간다. sid에는 GPU와 같은 호스트 브리지 아래에 NVMe가 없으므로, 같은 호스트 브리지 안의 경로는 시험할 수 없었다.

### 6.2 단계별 결과

| 단계 | 커널 | 결과 |
|---|---|---|
| A0 | 배포 7.0.0-34-generic | `IOMMU_IOAS_MAP_FILE: FAILED errno=95` |
| A1 번역 없음 | 같음 | C1, C2 모두 MATCH (64K, 4K) |
| A2 | 같음 | CPU의 BAR1 읽기 MATCH |
| C0 | PAL | `IOMMU_IOAS_MAP_FILE: OK iova=0x200000 length=0x40000000` |
| C1, C2 번역 | PAL | 모두 MATCH (64K, 4K, identity IOVA) |
| D, D2 | PAL | `sc=0x4` + Read fault, 명령 OK + Write fault |
| PTE | PAL | `0x000020a031e00883`부터 2 MiB 간격, 512개 |

단계 A를 먼저 한 이유는 커널을 바꾸기 전에 플랫폼이 장치 간 읽기를 전달하는지부터 가리기 위해서다. A1에서 C2가 성공했으므로 sid는 §5 표의 "읽기와 쓰기 전달" 행이다. 단계 C에서는 PAL 경로로도 같은 결과가 나왔다. A0는 배포 커널이 NVIDIA dma-buf를 받지 않는다는 것을 보인다. 따라서 단계 C의 매핑 성공은 PAL 커널과 이식한 exporter가 만든 결과다. sid는 PAL 경로로 양방향이 된다. 다음 절은 같은 시험이 클라이언트 플랫폼에서는 어떻게 되는지 본다.

## 7. 개발 PC: 클라이언트 플랫폼 제약

같은 시험을 개발 PC에서도 실행했다. 개발 PC는 팀 엔지니어가 평소 쓰는 데스크톱 클라이언트 플랫폼이므로, 여기서 무엇이 되고 무엇이 안 되는지가 팀의 개발 방식에 직접 영향을 준다.

### 7.1 경로 구조

개발 PC는 i9-14900K(Raptor Lake-S Refresh, 호스트 브리지 8086:a700)다. CPU는 x16 PCIe 링크 하나를 x8 두 개로 나눠 쓸 수 있고, Intel은 이 두 루트 포트를 PEG10(0:1:0)과 PEG11(0:1:1)이라고 부른다. GPU는 PEG10에, 예비 NVMe는 PEG11에 붙어 있다. 그래서 두 장치 사이의 요청은 반드시 CPU의 루트 콤플렉스를 지난다.

```text
개발 PC (i9-14900K)

                 CPU 루트 콤플렉스 (VT-d)
                 │                     │
   00:01.0 PEG10 (8086:a70d)    00:01.1 PEG11 (8086:a72d)
                 │                     │
   01:00.0 GPU (10de:2c34)      02:00.0 예비 NVMe (PM9A1)

C1  NVMe → 00:01.1 → 루트 콤플렉스 → 00:01.0 → GPU    posted write, 전달됨
C2  NVMe → 00:01.1 → 루트 콤플렉스에서 UR 완료        non-posted read, 거부됨
```

### 7.2 결과

아래 표는 2026-10-16에 수정하지 않은 PAL 커널과 고친 시험 도구로 측정한 값이다. 번역 없는 C2는 2026-10-15에 identity 도메인과 uio로 측정했다. UR 비트는 2026-10-15에 네 장치의 오류 비트를 지운 뒤 C2를 한 번 실행하고 읽었다.

| 시험 | 결과 |
|---|---|
| PAL 매핑 | OK, PTE `0x000000480f600883`부터 2 MiB 간격, 512개 |
| C1 64 KiB, 4 KiB (번역 IOVA, identity IOVA) | MATCH |
| C2 64 KiB, 4 KiB (번역 IOVA, identity IOVA) | `sc=0x4`, DMAR fault 없음 |
| C2 번역 없음 (identity 도메인, uio) | `sc=0x4` |
| D / D2 | `sc=0x4` + DMAR Read fault / 명령 OK + DMAR Write fault |
| C2 뒤 UR 수신 비트 | NVMe와 00:01.1에만 `<MAbort+`, GPU와 00:01.0에는 없음 |

C1과 D는 §5 표의 "매핑 정상" 행과 일치하므로, PAL 매핑은 개발 PC에서도 sid와 같게 동작한다. C2는 "장치 간 쓰기만 전달" 행과 같은 모양이다. UR 비트는 NVMe의 읽기 요청이 GPU 쪽에 닿기 전에 루트 콤플렉스가 UR로 끝냈다는 것을 보인다. 여기까지는 측정이다.

### 7.3 Intel 데이터시트의 P2P 지원 표

Intel 데이터시트가 이 동작을 설명한다. 13세대 Core 프로세서 데이터시트 1권(문서 번호 743844, 개정 006)의 PCI Express Support 절에는 포트별 기능 표가 있다. 그 표는 S, S Refresh, HX 라인의 포트별 P2P 지원을 다음과 같이 적는다. 14900K는 S Refresh 라인이다.

| 포트 | 개발 PC에 붙은 장치 | P2P Mem Write | P2P Mem Read |
|---|---|---|---|
| PEG10 (0:1:0) | GPU 01:00.0 | No | No |
| PEG11 (0:1:1) | 예비 NVMe 02:00.0 | No | No |
| PEG60 (0:6:0) | 시스템 NVMe 03:00.0 | Yes | No |

같은 표에서 H, PX, P, U 라인의 포트도 P2P 읽기는 모두 No다. 데이터시트와 측정을 나란히 놓으면 다음과 같다.

| 트랜잭션 | 데이터시트 | 측정 |
|---|---|---|
| C2 peer 읽기 (PEG11에서 PEG10으로) | 지원하지 않음 | UR 완료, `sc=0x4` |
| C1 peer 쓰기 (PEG11에서 PEG10으로) | 지원하지 않음 | 전달됨, MATCH |

읽기는 데이터시트와 측정이 일치한다. 따라서 개발 PC의 C2 실패는 Raptor Lake 프로세서 루트 포트의 문서화된 제약이다. 데이터시트가 프로세서 루트 포트 전부에서 P2P 읽기를 No로 적으므로, 장치를 다른 프로세서 루트 포트로 옮겨도 해결되지 않는다. 쓰기는 다르다. 데이터시트는 PEG10과 PEG11의 P2P 쓰기도 지원하지 않는다고 적지만 C1은 데이터가 일치했다. 데이터시트는 "No"가 하드웨어 차단인지 검증하지 않은 동작인지를 정의하지 않는다. 측정으로 보면 적어도 쓰기는 차단되지 않는다. 그래서 개발 PC의 C1 성공은 Intel이 보증하지 않는 동작이라고 판단한다. 8086:a700이 커널 p2pdma 허용 목록에 없는 것도 이 문서 내용과 맞는다.

이 결론에 이르기 전에 SNP 비트, IOMMU 번역, 시험 도구 버그 같은 다른 원인을 의심했고, 그 과정에서 남긴 기록 몇 가지가 틀렸다. 다음 절에서 정정한다. 원본 로그는 §11의 위치에 있다.

## 8. 바로잡은 이전 기록

| 이전 서술 | 바로잡은 내용 | 경위 |
|---|---|---|
| 개발 PC C2 실패는 PTE의 SNP 비트 때문으로 추정 (10-13 §5) | SNP를 끄고도, 번역을 끄고도 실패했다. 원인은 루트 콤플렉스의 peer 읽기 거부다 | PTE에서 SNP를 발견하고, DMA-FQ 경로에서 이전에 성공했다는 사용자 기억과 맞춰 본 정황 추론이었다. 그 기억은 아래 행에서 따로 정정한다 |
| sid 결과로 개발 PC 실패 원인을 "대조로 확인" (sid 실행 보고서) | sid 결과는 PAL과 IOMMU를 배제할 뿐이다. 루트 콤플렉스 위치는 오류 비트 측정(§7.2)으로, 문서화된 제약이라는 것은 Intel 데이터시트로 확인했다 | 두 장비는 GPU, NVMe, 경로 구조도 다른데 한 변수의 대조로 보았다 |
| 시험 NVMe가 루트 포트 4c:01.0 아래 (sid 실행 보고서) | 4c:01.0은 Microchip 스위치의 하위 포트이고, 루트 포트는 4a:02.0이다 | 사전 점검 스크립트가 NVMe의 바로 위 브리지를 "rootport"로 출력했다 |
| 개발 PC 루트 콤플렉스는 peer 쓰기는 전달하고 peer 읽기는 전달하지 않도록 설계되었다고 추정 (이 보고서의 이전 판 §8, 현재 §7.3) | 데이터시트는 PEG10, PEG11에서 P2P 쓰기와 읽기를 모두 지원하지 않는다고 적는다. 쓰기가 전달된 것은 보증되지 않은 동작이다 | C1이 성공한 측정 결과를 설계 의도로 일반화했다. 데이터시트를 찾기 전이었다 |
| SNP 가설을 기각한 뒤 원래 PAL 커널로 되돌렸다 (이 보고서의 이전 판 부록 A.4) | `/boot`의 PAL 커널 이미지는 SNP 실험 커널로 남아 있었다. 그 커널로 한 시험은 SNP 가설 시험과 번역 없는 uio 시험뿐이라 결과는 바뀌지 않는다 | 되돌리는 작업을 기록에만 적고 실행 여부를 이미지 해시로 확인하지 않았다. 재측정을 준비하며 해시를 비교해 드러났다 |
| PTE 엔트리 514개 (sid 실행 보고서) | 512개다 | `pte-dump.sh`가 `wc -l`로 세어 머리글 2줄이 들어갔다 |
| 이 PC에서 GPU→NVMe가 이전에 성공했다 (10-13 보고서가 인용한 사용자 기억) | 이 PC에서 GPU→NVMe를 측정한 기록은 없다. GDS 기록은 읽기와 바운스 버퍼 경로뿐이다. 루트 콤플렉스가 peer 읽기를 UR로 거부하므로, 이전에 성공한 실행이 있었다면 직접 P2P 읽기가 아니라 호스트 메모리를 거친 경로였다고 추정한다 | 기억을 기록으로 확인하지 않은 채 SNP 가설의 근거로 썼다 |
| 시험 도구가 CC에 IOSQES=6, IOCQES=4를 씀 | 실제로는 두 값을 바꿔 썼다(0x00640001). 개발 PC 결과에는 영향이 없음을 번역 없는 경로(10-15)와 PAL 경로(10-16) 재측정으로 확인했다 | 시프트 16과 20을 바꿔 적었다. 개발 PC 드라이브는 이 값을 검사하지 않았고, sid 드라이브가 I/O CQ 생성을 `0x102`로 거부해 드러났다 |

## 9. 의미와 제언

**`iommu_map_pa` 대체 가능성.** 기능 면에서는 대체할 수 있다. PAL 경로는 `iommu_map_pa`와 같은 2 MiB 엔트리를 만든다. 또 iommufd IOAS 안에서 매핑하므로, 매핑하지 않은 IOVA에 대한 보호(D, D2)가 그대로 적용된다. 처리량은 측정하지 않았다. 다만 페이지 테이블 모양이 같으므로 `iommu_map_pa` 경로와 같은 처리량이 나올 것으로 추정한다.

**남은 장벽은 업스트림 상태다.** PAL은 RFC 단계다. PAL 헤더는 이 타입을 쓰기 전에 dma-buf 메인테이너와 상의하라고 적는다. NVIDIA exporter는 이 PoC가 out-of-tree로 만든 것이고, NVIDIA 오픈 모듈에 들어간 것이 아니다. 따라서 이 PoC 결과를 지금 바로 생산 경로에 쓸 수는 없다. 쓸 수 있는 곳은 두 가지다. 하나는 PAL 또는 mm provider 스레드에 "GPU 메모리를 NVMe 사용자 공간 드라이버에 매핑하는 실사용 사례"로 내는 실증 자료다. 다른 하나는 NVIDIA에 exporter 지원을 요청할 근거다.

**플랫폼 제약은 매핑 방식과 별개다.** Raptor Lake 데이터시트는 프로세서 루트 포트의 P2P 메모리 읽기를 지원하지 않는다고 적는다. 그래서 개발 PC에서 GPU→NVMe 방향은 어떤 매핑 방식으로도 되지 않는다. 본 팀이 쓰기 워크로드를 개발 PC에서 시험하려면, PAL 경로를 쓰든 쓰지 않든 GPU 메모리를 호스트 메모리로 복사하는 경로가 필요하다. 개발 PC의 NVMe→GPU 방향도 데이터시트가 보증하지 않는 동작이므로, 성능과 안정성은 sid 같은 서버에서 판단해야 한다. sid에서는 양방향이 된다.

**D2가 보여 주는 수명 문제.** 매핑되지 않은 IOVA로 NVMe 읽기 명령을 보내면 데이터는 버려지고 명령은 성공으로 끝난다. 그래서 unmap은 그 IOVA를 쓰는 명령이 모두 끝난 뒤에만 해야 한다. 이 순서는 iommufd가 보장하지 않으므로 사용자 공간 드라이버(xNVMe upcie 백엔드)가 지켜야 한다.

## 10. 확인하지 못한 것과 다음 단계

| 항목 | 다음 단계 |
|---|---|
| 데이터시트가 지원하지 않는다고 적는 PEG10, PEG11 사이의 P2P 쓰기가 전달되는 이유 | 데이터시트 2권의 루트 포트 레지스터에서 P2P 관련 설정을 찾고, 필요하면 Intel에 문의한다. C1을 장시간 반복해 데이터 손상이 없는지 본다 |
| C1, C2의 대역폭과 지연 | 큰 전송과 깊은 큐로 처리량을 측정하고 `iommu_map_pa` 경로와 비교한다 |
| 매핑과 해제 비용 | gpu-iommu-map-size 브랜치의 kprobe 도구로 `IOMMU_IOAS_MAP_FILE`과 unmap 지연을 잰다 |
| 소켓 간 경로 | sid에서 GPU(소켓 0)와 소켓 1의 NVMe(호스트 브리지 c9, e2)로 C1, C2를 반복한다 |
| 같은 호스트 브리지 안의 경로 | GPU와 NVMe가 같은 호스트 브리지 아래 있는 서버를 찾는다 |
| 수명 시나리오 | fd close 뒤 I/O, 반복 map과 unmap, 명령 진행 중 강제 종료를 KASAN 빌드로 시험한다 |
| NVIDIA exporter의 revoke | NVIDIA는 `dma_buf_invalidate_mappings()`를 부르지 않는다. GPU 메모리 해제 시 매핑이 어떻게 되는지 확인한다 |
| NVIDIA exporter의 peer2peer 검사 공백 (부록 A.2.8) | P2P SGT type을 제시하거나 `match_mapping`에 같은 검사를 넣고, peer2peer를 지원하지 않는 importer가 거부되는지 시험한다 |
| mm memory provider와의 비교 | mm RFC의 다음 버전이 나오면 같은 도구로 매핑 엔트리 수와 지연을 비교한다 |

## 11. 자료 위치

| 자료 | 위치 |
|---|---|
| 이식 패치 (NVIDIA, upcie, SNP 실험 커널) | `notes/pal-poc/patches/` |
| 시험 도구 소스 | `notes/pal-poc/src/` |
| 실행 스크립트 | `notes/pal-poc/scripts/` |
| sid 실행 매뉴얼 | `notes/pal-poc/MANUAL.md` |
| 개발 PC 결과 보고서 | `notes/pal-poc/results-2026-10-13.md` |
| sid 결과와 개발 PC 재측정 보고서 | `notes/pal-poc/results-2026-10-15.md` |
| sid 원본 로그, 커널 config, 토폴로지 | `notes/pal-poc/sid-raw/` |
| 개발 PC 재측정 로그 | `notes/pal-poc/devpc-raw/run-2026-10-15-ccfix-ab.log`(번역 없음), `run-2026-10-16-pal.log`(PAL 커널), `run-2026-10-16-pal.sh`(실행 스크립트) |
| 개발 PC 1차 원본 로그 | `/data/aisio/pal-poc/run-2026-10-13.log`, `dmesg-2026-10-13.log`, `run-2026-10-14-*.log` |
| PoC 계획 검토 | `~/Documents/Claude/aisio/2026-10-13-iommufd-poc-plan-review.md` (작성자 로컬) |
| Raptor Lake 데이터시트 P2P 기능 표 | Intel 13th Generation Core Processors Datasheet Vol. 1 (743844, rev. 006), PCI Express Support: https://edc.intel.com/content/www/us/en/design/products/platforms/details/raptor-lake-s/13th-generation-core-processors-datasheet-volume-1-of-2/006/pci-express-support/ |
| 업스트림 현황 보고서 | `notes/iommufd-gpu-memory.md` (브랜치 `docs/iommufd-gpu-memory`) |

## 부록 A. 구현 상세

이 부록은 PoC를 다시 빌드하거나 이어서 고칠 사람을 위한 것이다. 코드 인용은 `notes/pal-poc/patches/`의 패치와 PAL 브랜치 소스에서 그대로 옮겼다. 본문 §4.4 표의 번호는 A.2.1~A.2.8과 같다.

### A.1 iommufd가 dma-buf를 받는 경로 (PAL 브랜치, 수정 없음)

exporter가 무엇을 내놓아야 하는지는 iommufd 쪽 코드가 정한다. 사용자가 `IOMMU_IOAS_MAP_FILE`을 부르면 `iommufd_ioas_map_file()`이 `iopt_map_file_pages()`를 부른다. 이 함수는 먼저 `dma_buf_get(fd)`로 fd가 dma-buf인지 본다. dma-buf이면 `iopt_alloc_dmabuf_pages()`를 거쳐 `iopt_map_dmabuf()`(`drivers/iommu/iommufd/pages.c` 1489행)로 간다.

```c
struct dma_buf_mapping_match pal_match[] = { DMA_BUF_IMAPPING_PAL() };
...
attach = dma_buf_mapping_attach(dmabuf, pal_match,
                                ARRAY_SIZE(pal_match),
                                &iopt_dmabuf_attach_revoke_ops, pages);
...
rc = dma_buf_pin(attach);
...
pages->dmabuf.exp_phys = dma_buf_pal_map_phys(attach);
```

iommufd는 PAL 하나만 요청하므로, exporter가 PAL을 제시하지 않으면 attach가 실패한다. 배포 커널에서 나온 `errno=95`는 이 경로가 아니다. 배포 커널의 iommufd는 vfio-pci가 낸 dma-buf만 받도록 되어 있어서 거부한 것이다. attach가 성공하면 `dma_buf_pin()`을 부르고, `dma_buf_pal_map_phys()`로 exporter의 `map_phys`를 불러 물리주소 구간 목록을 받는다. 그 목록은 MMIO 배치(`BATCH_MMIO`)가 된다. `batch_to_domain()`(같은 파일 521~522행)이 이 배치를 IOMMU 도메인에 넣을 때 `IOMMU_CACHE`를 빼고 `IOMMU_MMIO`를 붙인다. importer ops `iopt_dmabuf_attach_revoke_ops`는 `allow_peer2peer = true`이고, revoke 콜백 `iopt_revoke_notify`를 가진다.

정리하면 exporter가 할 일은 둘이다. `match_mapping`에서 PAL을 제시하는 것, 그리고 `map_phys`와 `unmap_phys`를 구현하는 것이다.

### A.2 NVIDIA exporter 수정

**빌드 실패 원인.** 580.178.04를 PAL 커널에서 빌드하면 `nv-dmabuf.c`에서만 실패한다. 원인은 셋이다.
- PAL 브랜치는 `struct dma_buf_ops`에서 `map_dma_buf`와 `unmap_dma_buf`를 없애고 `struct dma_buf_mapping_sgt_exp_ops`로 옮겼다.
- `struct dma_buf_attachment`에서 `dev` 멤버가 사라졌다. SGT 매핑의 대상 장치는 `dma_buf_sgt_dma_device(attach)`로 얻는다.
- importer 함수가 `dma_buf_sgt_attach()`, `dma_buf_sgt_map_attachment()`, `dma_buf_sgt_unmap_attachment()`로 이름이 바뀌었다.

**변경 위치.** 패치는 배포 패키지가 설치한 DKMS 소스 `/usr/src/nvidia-580.178.04`에 `patch -p1`로 그대로 적용된다(2026-10-16에 `--dry-run`으로 확인). `nv-dmabuf.c`는 1926행에서 2147행이 된다. hunk별 위치는 다음과 같다. 행 범위는 패치의 hunk 머리글(앞뒤 문맥 3행 포함)을 따랐다.

| 파일 | hunk (원본 → 수정본) | 함수 | 변경 | 상세 |
|---|---|---|---|---|
| `conftest.sh` | 2454~2459 → 2454~2487 | 검사 case 문 | `dma_buf_ops_has_match_mapping` 검사 추가 | A.2.1 |
| `nvidia/nvidia.Kbuild` | 149~154 → 149~155 | `NV_CONFTEST_FUNCTION_COMPILE_TESTS` | 위 검사 등록 | A.2.1 |
| `nvidia/nv-dmabuf.c` | 22~27 → 22~30 | include | `<linux/dma-buf-mapping.h>`를 조건부로 포함 | |
| `nvidia/nv-dmabuf.c` | 1004~1054 → 1007~1097 | `nv_dma_buf_attach()` | 검사 본문을 `nv_dma_buf_check_peer_device()`(1016행)로 분리, `nv_dma_buf_attachment_dev()`(1058행) 추가, `nv_dma_buf_attach()`(1070행)의 검사 호출을 조건부로 | A.2.5, A.2.6 |
| `nvidia/nv-dmabuf.c` | 1062~1068 → 1105~1111 | `nv_dma_buf_attach()` 끝 | `unlock_priv` 레이블에 `unused` 속성 | A.2.5 |
| `nvidia/nv-dmabuf.c` | 1078~1083 → 1121~1132 | `nv_dma_buf_map()` | 대상 장치를 `nv_dma_buf_attachment_dev()`로 얻고 NULL이면 실패 | A.2.6 |
| `nvidia/nv-dmabuf.c` | 1108~1118 → 1157~1167 | `nv_dma_buf_map()` | `nv_dma_buf_map_pages()`, `nv_dma_buf_map_pfns()`에 그 장치를 넘김 | A.2.6 |
| `nvidia/nv-dmabuf.c` | 1144~1160 → 1193~1210 | `nv_dma_buf_unmap()` | 같은 방식으로 장치를 바꿈 | A.2.6 |
| `nvidia/nv-dmabuf.c` | 1457~1466 → 1507~1674 | `nv_dma_buf_ops` 앞 | SGT ops(1511행), `nv_dma_buf_pal_map_phys()`(1525행), `nv_dma_buf_pal_unmap_phys()`(1594행), PAL ops(1613행), `nv_dma_buf_match_mapping()`(1626행) 추가, ops 테이블(1664행)을 조건부로 교체 | A.2.2~A.2.4 |
| `nvidia/nv-dmabuf.c` | 1818~1824 → 2026~2036 | `nv_dma_import_dma_buf()` | `dma_buf_sgt_attach()` | A.2.7 |
| `nvidia/nv-dmabuf.c` | 1839~1845 → 2051~2061 | `nv_dma_import_dma_buf()` | `dma_buf_sgt_map_attachment()` | A.2.7 |
| `nvidia/nv-dmabuf.c` | 1915~1922 → 2131~2143 | `nv_dma_release_dma_buf()` | `dma_buf_sgt_unmap_attachment()` | A.2.7 |

아래 여덟 항목이 수정 전체다.

#### A.2.1 conftest 항목 `dma_buf_ops_has_match_mapping`

NVIDIA 모듈은 커널 API의 존재를 conftest로 검사하고 그 결과를 `#define`으로 쓴다. `conftest.sh`에 다음 검사를 더했다. 이 검사는 `struct dma_buf_ops`에 `match_mapping` 멤버가 있는 코드가 컴파일되는지 본다.

```c
#include <linux/dma-buf.h>
int conftest_dma_buf_ops_has_match_mapping(void) {
    return offsetof(struct dma_buf_ops, match_mapping);
}
```

컴파일이 되면 `NV_DMA_BUF_OPS_HAS_MATCH_MAPPING`을 정의하고, 안 되면 `#undef`한다. `nvidia.Kbuild`의 `NV_CONFTEST_FUNCTION_COMPILE_TESTS`에 이 항목을 한 줄 더해 빌드 때 실행되게 했다. 이후의 모든 변경은 이 매크로로 감쌌다. 그래서 매크로가 정의되지 않은 기존 커널에서는 원래 코드가 그대로 컴파일된다. 6.8.12에서 빌드했을 때 conftest 결과는 `#undef NV_DMA_BUF_OPS_HAS_MATCH_MAPPING`이었고 `nvidia.ko`가 만들어졌다.

#### A.2.2 `nv_dma_buf_ops` 교체

exporter ops 테이블에서 SGT 함수를 빼고 `match_mapping`을 넣었다. 기존 SGT 함수 `nv_dma_buf_map()`과 `nv_dma_buf_unmap()`은 지우지 않고 새 SGT ops 테이블로 옮겼다.

```c
static const struct dma_buf_mapping_sgt_exp_ops nv_dma_buf_sgt_ops = {
    .map_dma_buf   = nv_dma_buf_map,
    .unmap_dma_buf = nv_dma_buf_unmap,
};
...
static const struct dma_buf_ops nv_dma_buf_ops = {
    .attach        = nv_dma_buf_attach,
#if defined(NV_DMA_BUF_OPS_HAS_MATCH_MAPPING)
    .match_mapping = nv_dma_buf_match_mapping,
#else
    .map_dma_buf   = nv_dma_buf_map,
    .unmap_dma_buf = nv_dma_buf_unmap,
#endif
    .release       = nv_dma_buf_release,
```

이 변경은 PAL 브랜치가 simple exporter들과 amdgpu를 변환한 커밋과 같은 방식이다.

#### A.2.3 `nv_dma_buf_match_mapping()` 추가

importer가 attach할 때 dma-buf 코어가 이 함수를 부르고, exporter는 자기가 줄 수 있는 mapping type을 선호 순서대로 제시한다.

```c
if (!priv->nv->coherent ||
    (priv->mapping_type == NV_DMABUF_EXPORT_MAPPING_TYPE_FORCE_PCIE))
{
    matches[num_match++] = DMA_BUF_EMAPPING_PAL(&nv_dma_buf_pal_ops);
}
matches[num_match++] = DMA_BUF_EMAPPING_SGT(&nv_dma_buf_sgt_ops);

rc = dma_buf_match_mapping(args, matches, num_match);
...
// PAL has no importing device and nothing to check.
dev = dma_buf_sgt_dma_device(args->attach);
if (dev == NULL)
{
    return 0;
}

mutex_lock(&priv->lock);
rc = nv_dma_buf_check_peer_device(priv, dev);
mutex_unlock(&priv->lock);
```

- **PAL 제시 조건.** discrete GPU(`coherent`가 거짓)이거나 FORCE_PCIE 매핑일 때만 PAL을 제시한다. 이 경우 RM이 주는 구간은 호스트 관점에서 MMIO인 BAR1 주소다. Grace 같은 coherent 플랫폼의 DEFAULT 매핑은 시스템 메모리 페이지이므로 PAL로 내보내지 않는다.
- **순서.** PAL을 먼저, SGT를 다음에 둔다. iommufd는 PAL만 요청하므로 PAL이 선택되고, `dmabuf_import`나 RDMA 같은 SGT importer는 SGT가 선택된다.
- **SGT 종류.** P2P 전용 SGT가 아니라 plain SGT를 제시했다. P2P SGT는 importer가 PCI 장치여야 하는데, 본 팀의 `dmabuf_import`는 misc 장치로 attach하는 경로가 있어서 그 경로가 깨지지 않게 했다.
- **장치 검사.** 선택된 type이 SGT이면 `dma_buf_sgt_dma_device()`가 importer 장치를 돌려주고, 그 장치로 토폴로지를 검사한다. PAL이면 NULL을 돌려준다. PAL에는 검사할 importer 장치가 없으므로 검사 없이 통과한다.

#### A.2.4 PAL exporter `nv_dma_buf_pal_map_phys()`와 `nv_dma_buf_pal_unmap_phys()` 추가

`map_phys`는 RM이 이 dma-buf의 핸들들에 대해 보고하는 메모리 구간을 `struct dma_buf_phys_list`로 옮긴다. discrete GPU에서는 그 구간이 BAR1의 PCIe 주소다.

```c
mutex_lock(&priv->lock);

if (priv->num_objects != priv->total_objects)
{
    phys = ERR_PTR(-EINVAL);
    goto unlock_priv;
}

if (!priv->static_phys_addrs)
{
    status = nv_dma_buf_get_phys_addresses(priv, 0, priv->num_objects);
    ...
}

for (i = 0; i < priv->num_objects; i++)
{
    nranges += priv->handles[i].memArea.numRanges;
}

phys = kvmalloc(struct_size(phys, phys, nranges), GFP_KERNEL);
...
phys->length = nranges;
for (i = 0; i < priv->num_objects; i++)
{
    for (index = 0; index < priv->handles[i].memArea.numRanges; index++)
    {
        phys->phys[n].paddr = priv->handles[i].memArea.pRanges[index].start;
        phys->phys[n].len   = priv->handles[i].memArea.pRanges[index].size;
        n++;
    }
}
```

- **완성 검사.** dma-buf는 CUDA가 핸들을 여러 번에 걸쳐 채울 수 있다. 모든 핸들이 채워지기 전(`num_objects != total_objects`)에는 `-EINVAL`로 거부한다. 기존 SGT 경로의 `nv_dma_buf_map()`과 같은 조건이다.
- **물리주소 획득.** 기존 함수 `nv_dma_buf_get_phys_addresses()`를 그대로 쓴다. 이 함수는 RM에서 `memArea.pRanges[]`를 채우고 `phys_refcount`를 올린다. `static_phys_addrs`인 버퍼는 export 때 이미 주소를 받아 두었으므로 다시 부르지 않는다.
- **구간 복사.** 핸들마다, 구간마다 `paddr`과 `len`을 옮긴다. DMA 매핑을 만들지 않으므로 SGT 경로처럼 DMA 세그먼트 한도로 구간을 쪼개지 않는다. 측정한 1 GiB 버퍼는 구간 하나였다. 구간이 여러 개여도 PAL 브랜치의 iommufd는 받는다.
- **수명.** `unmap_phys`가 불릴 때까지 `phys_refcount`가 RM 구간을 붙잡는다. SGT 매핑이 `unmap_dma_buf`까지 붙잡는 것과 같다.

`unmap_phys`는 같은 락 안에서 목록을 `kvfree()`하고, `static_phys_addrs`가 아니면 `nv_dma_buf_put_phys_addresses()`로 참조를 돌려준다. 두 함수는 `struct dma_buf_mapping_pal_exp_ops nv_dma_buf_pal_ops`로 묶어 A.2.3의 `DMA_BUF_EMAPPING_PAL()`에 넘긴다.

#### A.2.5 attach 검사의 분리: `nv_dma_buf_check_peer_device()`

원래 `nv_dma_buf_attach()`는 `to_pci_dev(attachment->dev)`로 importer의 PCI 토폴로지를 검사했다. PAL 커널에서는 `attachment->dev`가 없다(83c52177f416). importer 장치는 SGT type이 정해진 뒤 `dma_buf_sgt_dma_device()`로 얻는다. dma-buf 코어의 `dma_buf_mapping_attach()`(`drivers/dma-buf/dma-buf.c` 1033~1052행)는 `match_mapping`을 먼저 부르고 `attach`를 나중에 부르므로, 검사는 type을 정하는 `nv_dma_buf_match_mapping()` 안에서 SGT가 선택된 직후에 한다. 검사에 실패하면 attach 콜백까지 가지 않고 attach 전체가 실패한다. 두 커널에서 같은 검사를 쓰도록 검사 본문을 새 함수 `nv_dma_buf_check_peer_device(priv, dev)`로 떼어 냈다.

```c
if (priv->mapping_type == NV_DMABUF_EXPORT_MAPPING_TYPE_FORCE_PCIE)
{
    if (dev_is_pci(dev) &&
        !nv_pci_is_valid_topology_for_direct_pci(priv->nv, to_pci_dev(dev)))
    {
        ...
        return -ENOTSUPP;
    }

    priv->skip_iommu = NV_TRUE;
}
else if (dev_is_pci(dev))
{
    nv_dma_device_t peer_dma_dev = {{ 0 }};

    peer_dma_dev.dev = &to_pci_dev(dev)->dev;
    peer_dma_dev.addressable_range.limit = to_pci_dev(dev)->dma_mask;

    if (!nv_grdma_pci_topology_supported(priv->nv, &peer_dma_dev))
    {
        ...
        return -ENOTSUPP;
    }
}
```

- 기존 커널에서는 `nv_dma_buf_attach()`가 이 함수를 `attachment->dev`로 부른다. 동작은 원래와 같다.
- PAL 커널에서는 `nv_dma_buf_match_mapping()`이 SGT가 선택된 뒤에 이 함수를 부른다. 그래서 `nv_dma_buf_attach()` 안의 호출은 `#if !defined(NV_DMA_BUF_OPS_HAS_MATCH_MAPPING)`로 감쌌다.
- `dev_is_pci()` 검사를 새로 넣었다. 원래 코드는 importer가 PCI 장치라고 가정하고 `to_pci_dev()`를 조건 없이 적용했다. 580에서 misc 장치 importer가 통과한 것은 `nv_grdma_pci_topology_supported()`의 기본값이 참이었기 때문이다. 이제는 PCI가 아닌 importer를 명시적으로 검사에서 뺀다. 615.78.08(main)에 들어간 `dev_is_pci()` 분기와 같은 방향이다.
- PAL 커널 빌드에서는 `nv_dma_buf_attach()`의 `unlock_priv` 레이블을 쓰는 `goto`가 사라진다. 그래서 컴파일러 경고를 막으려고 레이블에 `__attribute__((unused))`를 붙였다.

#### A.2.6 SGT 경로의 대상 장치: `nv_dma_buf_attachment_dev()`

`nv_dma_buf_map()`과 `nv_dma_buf_unmap()`은 `attachment->dev`로 DMA 매핑을 만들었다. 이 필드 대신 쓸 함수를 더했다.

```c
static struct device*
nv_dma_buf_attachment_dev(
    struct dma_buf_attachment *attachment
)
{
#if defined(NV_DMA_BUF_OPS_HAS_MATCH_MAPPING)
    return dma_buf_sgt_dma_device(attachment);
#else
    return attachment->dev;
#endif
}
```

두 함수 안의 `attachment->dev` 네 곳(`nv_dma_buf_map_pages()`, `nv_dma_buf_map_pfns()`와 각각의 unmap)을 이 함수의 반환값 `dev`로 바꿨다. `nv_dma_buf_map()`은 `dev`가 NULL이면 NULL을 돌려준다.

#### A.2.7 NVIDIA가 importer일 때의 함수 이름

NVIDIA 드라이버는 다른 드라이버의 dma-buf를 가져오는 importer 역할도 한다(`nv_dma_import_dma_buf()`, `nv_dma_release_dma_buf()`). 이 경로의 세 호출을 PAL 커널에서는 새 이름으로 바꿨다.

| 원래 호출 | PAL 커널에서의 호출 |
|---|---|
| `dma_buf_attach(dma_buf, dma_dev->dev)` | `dma_buf_sgt_attach(dma_buf, dma_dev->dev)` |
| `dma_buf_map_attachment(dma_attach, direction)` | `dma_buf_sgt_map_attachment(dma_attach, direction)` |
| `dma_buf_unmap_attachment(attach, sgt, direction)` | `dma_buf_sgt_unmap_attachment(attach, sgt, direction)` |

이 경로는 PoC 시험에 쓰이지 않는다. 그러나 고치지 않으면 모듈이 빌드되지 않는다.

#### A.2.8 고치지 않은 것

- **pin.** NVIDIA exporter에는 `pin` 콜백이 없다. 그래서 iommufd가 부르는 `dma_buf_pin()`은 아무 일도 하지 않고 0을 돌려준다. BAR1 구간은 A.2.4의 `phys_refcount`가 붙잡는다.
- **revoke.** NVIDIA exporter는 `dma_buf_invalidate_mappings()`를 부르지 않는다. 그래서 iommufd의 `iopt_revoke_notify`가 불릴 일이 없다. GPU 메모리를 먼저 해제하는 경우의 동작은 §10의 확인 항목으로 남겼다.
- **peer2peer 검사.** 원래 `nv_dma_buf_attach()`는 importer가 peer2peer를 지원하지 않고 GPU 메모리에 struct page가 없으면 attach를 거부한다(`NV_DMA_BUF_ATTACHMENT_HAS_PEER2PEER` 블록). PAL 브랜치는 83c52177f416에서 `dma_buf_attachment.peer2peer`를 지웠으므로, PAL 커널 빌드에서는 conftest가 이 매크로를 `#undef`로 정하고 블록이 컴파일되지 않는다(`conftest/functions.h`로 확인). 이식 패치는 SGT를 P2P 전용 type이 아니라 일반 SGT type으로 제시하므로, 이 검사를 대신하는 곳이 없다. 코드로 보면 PAL 커널에서는 MMIO를 다루지 못하는 SGT importer도 NVIDIA dma-buf에 attach할 수 있다. 이 PoC의 시험(iommufd, `dmabuf_import`)에는 영향이 없다. 업스트림에 낼 exporter라면 importer가 PCI 장치일 때는 P2P SGT type을 제시하거나, 같은 검사를 `match_mapping`에 넣어야 한다고 판단한다.
- **심볼 네임스페이스.** `nv.c`에는 이미 conftest 결과에 따라 `MODULE_IMPORT_NS(DMA_BUF)` 또는 `MODULE_IMPORT_NS("DMA_BUF")`를 쓰는 처리가 있다. PAL 심볼 `dma_buf_mapping_pal_type`도 같은 `DMA_BUF` 네임스페이스(`dma-buf-mapping.c` 414행)라서 추가 작업이 필요 없었다.
- **RM과 CUDA 사용자 라이브러리.** 고치지 않았다. CUDA 쪽은 기존 `cuMemGetHandleForAddressRange()`를 플래그 없이 그대로 쓴다.

**빌드.** NVIDIA DKMS는 7.0 커널에서 소스 컴파일 전에 `Makefile:18: /Kbuild: No such file or directory`로 실패한다. 그래서 소스를 복사하고 패치를 적용한 뒤 다음 명령으로 빌드했다.

```sh
make -j16 SYSSRC=/data/linux-pal NV_EXCLUDE_KERNEL_MODULES=nvidia-peermem modules
```

`nvidia-peermem`은 OFED의 `Module.symvers`를 요구하므로 제외했다. 만든 `.ko`는 PAL 커널의 `/lib/modules/7.0.0-rc1-pal+/extra/`에 넣고 `depmod -a`를 실행했다(`install-modules.sh`). 배포 커널의 DKMS 모듈은 건드리지 않는다.

### A.3 upcie `dmabuf_import` 수정

`dmabuf_import`는 CUDA dma-buf를 misc 장치나 지정한 PCI 장치 명의로 import해 물리주소 목록을 사용자 공간에 주는 모듈이다. 시험 도구는 이 모듈을 두 곳에 쓴다. identity IOVA 모드와 uio 모드에서 BAR1 물리주소를 얻을 때다. 이 모듈도 importer 함수 이름 변경 때문에 PAL 커널에서 빌드되지 않아 다음을 고쳤다.

- **Makefile.** `include/linux/dma-buf-mapping.h`가 커널 트리에 있으면 `-DDMABUF_IMPORT_MAPPING_TYPES`를 붙인다. 이 헤더는 PAL 브랜치가 새로 만든 파일이다.

  ```make
  ccflags-y += $(if $(wildcard $(srctree)/include/linux/dma-buf-mapping.h),-DDMABUF_IMPORT_MAPPING_TYPES)
  ```

- **함수 이름 매크로.** 세 importer 함수를 매크로로 바꿔 부르게 했다. PAL 커널에서는 `dma_buf_sgt_*`로, 기존 커널에서는 원래 이름으로 풀린다. 본문 세 곳(`dma_buf_dynamic_attach`, `dma_buf_map_attachment`, `dma_buf_unmap_attachment`)이 이 매크로를 쓴다.
- **move_notify 콜백 이름.** PAL 브랜치의 base에 들어 있는 ef246da8e63c에서 `struct dma_buf_attach_ops.move_notify`가 `invalidate_mappings`로 바뀌었다(§4.1). 같은 함수 `dmabuf_import_move_notify`를 조건부로 그 이름에 연결했다.
- **경고 메시지.** `dev_warn_once(attach->dev, ...)`는 `attach->dev`가 없어져 컴파일되지 않는다. `pr_warn_once("dmabuf_import: ...")`로 바꿨다.

`iommu_map_pa`는 수정 없이 빌드되었다. 이 PoC는 `iommu_map_pa`를 쓰지 않지만, 비교 경로를 남기기 위해 같은 커널에 함께 설치했다.

처음 만든 패치에는 `MODULE_IMPORT_NS` 블록을 한 번 더 감싸는 군더더기 hunk가 있었다. 그 hunk는 6.13 미만 커널의 `#else` 분기 안에서만 의미가 있고, 그 분기에서도 원래와 같은 `MODULE_IMPORT_NS(DMA_BUF)`로 풀린다. 그래서 어느 커널에서도 컴파일 결과를 바꾸지 않는다. 2026-10-15에 이 hunk를 패치에서 지웠다. 지운 패치가 upcie-experimental 0.9.0 원본에 적용되는 것과, PAL 커널과 6.8.12에서 모두 빌드되는 것을 확인했다. sid는 지우기 전 패치로 빌드했다.

### A.4 SNP 실험 커널 패치 (최종 경로에서 제외)

개발 PC C2 실패의 원인으로 SNP 비트를 의심했을 때 쓴 패치다. generic_pt의 VT-d second-stage 형식은 도메인에 `PT_FEAT_VTDSS_FORCE_COHERENCE`가 켜져 있으면 `iommu_prot`와 관계없이 SNP를 세운다. 이 패치는 MMIO 매핑에서만 SNP를 빼도록 고쳤다.

```c
-	if (pt_feature(common, PT_FEAT_VTDSS_FORCE_COHERENCE))
+	if (pt_feature(common, PT_FEAT_VTDSS_FORCE_COHERENCE) &&
+	    !(iommu_prot & IOMMU_MMIO))
 		pte |= VTDSS_FMT_SNP;
```

이 커널로 PTE가 `0x...083`(SNP 없음)이 된 것을 확인했지만 C2는 같은 실패였다. 가설을 기각한 뒤에도 개발 PC의 `/boot/vmlinuz-7.0.0-rc1-pal+`는 이 실험 커널로 남아 있었고, 원본은 `.snp-orig`로 보관되어 있었다. 2026-10-16에 이미지 해시로 확인했다. 이 커널로 부팅한 것은 2026-10-13 18:44부터 10-14 08:51까지 한 번뿐이다. 그 부팅에서 실행한 시험은 SNP 가설 시험과 identity 도메인, uio 시험이다. uio 시험은 IOMMU 번역을 거치지 않으므로 SNP 패치와 무관하다. 그 뒤 개발 PC 측정은 6.8.12 커널에서 했다. 따라서 보고서의 결과는 이 서술 오류의 영향을 받지 않는다. sid에서는 이 패치를 쓰지 않았다.

### A.5 시험 도구 구현

#### A.5.1 `pal_probe`

매핑만 확인하는 도구다. 순서는 다음과 같다.
1. `cuMemAlloc()`으로 1 GiB를 할당하고 `cuMemGetHandleForAddressRange(..., CU_MEM_RANGE_HANDLE_TYPE_DMA_BUF_FD, 0)`로 dma-buf fd를 얻는다.
2. `/dev/iommu`를 열고 `IOMMU_IOAS_ALLOC`으로 IOAS를 만든다.
3. `--vfio`를 주면 vfio cdev 장치를 `VFIO_DEVICE_BIND_IOMMUFD`로 묶는다. 이어서 `IOMMU_HWPT_ALLOC`, `VFIO_DEVICE_ATTACH_IOMMUFD_PT`로 하드웨어 도메인에 붙인다. 이렇게 해야 매핑이 실제 VT-d 페이지 테이블에 들어간다.
4. `IOMMU_IOAS_MAP_FILE`에 dma-buf fd를 넣고 IOVA나 errno를 출력한다.
5. `--hold N`이면 N초 동안 매핑을 유지한다. 그동안 `pte-dump.sh`로 PTE를 읽는다.

#### A.5.2 `pal_nvme`

`pal_nvme`를 새로 짠 이유와 시험 정의는 §4.6에 있다. 이 절은 설정과 명령 처리를 설명한다.

**설정 순서.**

| 단계 | 호출 | 결과 |
|---|---|---|
| 1 | `cuMemAlloc`, `cuMemGetHandleForAddressRange`, `cuMemsetD8` | 1 GiB GPU 버퍼와 dma-buf fd |
| 2 | `open("/dev/iommu")`, `IOMMU_IOAS_ALLOC` | IOAS |
| 3 | `VFIO_DEVICE_BIND_IOMMUFD`, `IOMMU_HWPT_ALLOC`, `VFIO_DEVICE_ATTACH_IOMMUFD_PT` | NVMe가 IOAS의 하드웨어 도메인에 붙음 |
| 4 | `VFIO_DEVICE_GET_REGION_INFO`(BAR0), `mmap` | 컨트롤러 레지스터 |
| 5 | config 공간 Command 레지스터에 `0x6` OR | 메모리 공간과 버스 마스터 켬 |
| 6 | `mmap` 2 MiB 익명 메모리, `IOMMU_IOAS_MAP` | 큐와 버퍼용 호스트 메모리와 그 IOVA |
| 7 | `IOMMU_IOAS_MAP_FILE`(dma-buf fd) | GPU 버퍼의 IOVA (PAL 경로) |

**호스트 메모리 배치.** 2 MiB 블록 하나를 다음과 같이 나눠 쓴다.

| 오프셋 | 용도 |
|---|---|
| 0 | admin SQ (깊이 32) |
| 16 KiB | admin CQ |
| 32 KiB | I/O SQ (깊이 64) |
| 48 KiB | I/O CQ |
| 64 KiB | Identify 결과 |
| 68 KiB | PRP 리스트 |
| 128 KiB | 호스트 버퍼 1 (64 KiB) |
| 256 KiB | 호스트 버퍼 2 (64 KiB) |

**컨트롤러 초기화.** CAP에서 MQES, DSTRD, 타임아웃을 읽는다. CC.EN=0으로 끄고, AQA, ASQ, ACQ를 쓴 뒤 CC를 `(6 << 16) | (4 << 20) | 1`로 켠다. 이 값은 IOSQES=6(64 B), IOCQES=4(16 B), MPS=0(4 KiB), EN=1이다. Identify Namespace로 LBA 크기를 읽고, Create I/O CQ와 Create I/O SQ로 큐 쌍 하나를 만든다. 명령은 하나씩 제출하고 완료 큐를 폴링해 기다린다.

**PRP.** 전송이 4 KiB이면 PRP1만 쓴다. 8 KiB이면 PRP2에 둘째 페이지를 넣는다. 그보다 크면 PRP2가 호스트 메모리의 PRP 리스트를 가리키게 한다. GPU 버퍼로 가는 64 KiB 전송에서는 PRP 엔트리 16개가 모두 GPU IOVA다.

**시험 정의.** 시험 C1, C2, D, D2의 명령, IOVA, LBA, 판정 기준은 §4.6의 표에 있다.

**선택 모드.**
- `--identity`: `dmabuf_import`를 misc 장치 명의로 붙여 BAR1 물리주소를 얻는다. 그 주소를 `IOMMU_IOAS_MAP_FIXED_IOVA`로 IOVA에 지정한다. 그래서 IOVA와 물리주소가 같아진다.
- `--uio <BDF>`: iommufd를 쓰지 않는다. sysfs `resource0`으로 BAR0를 mmap하고, 호스트 메모리는 2 MiB hugepage로 잡아 `/proc/self/pagemap`에서 물리주소를 읽는다. GPU 주소는 `dmabuf_import`로 얻은 BAR1 물리주소를 그대로 쓴다. NVMe는 identity 도메인(또는 IOMMU off)에서 uio_pci_generic에 묶여 있어야 한다.
- `--xfer`, `--slba`, `--no-negative`: 전송 크기, 시작 LBA, D와 D2 생략.

**종료.** CC.EN=0으로 컨트롤러를 끄고, GPU와 호스트 매핑을 `IOMMU_IOAS_UNMAP`으로 지운 뒤 fd를 닫는다.

#### A.5.3 `bar1_cpu_read`와 스크립트

`bar1_cpu_read`는 CUDA 버퍼에 패턴을 쓰고 `dmabuf_import`로 그 버퍼의 BAR1 물리주소를 얻는다. 그다음 GPU의 sysfs `resource1`을 mmap해 같은 오프셋 64 KiB를 CPU로 읽어 대조한다.

스크립트는 넷이다.
- `bind-vfio.sh`: NVMe를 DMA-FQ 그룹의 vfio-pci에 묶는다. 데이터셋 장치, 그룹 크기, 마운트 여부를 먼저 검사한다.
- `identity-uio.sh`: 그룹을 identity로 바꾸고 uio_pci_generic에 묶는다. 버스 마스터를 켜고 hugepage 64개를 예약한다.
- `restore-nvme.sh`: 커널 nvme 드라이버와 DMA-FQ로 되돌리고 hugepage를 해제한다.
- `pte-dump.sh`: VT-d debugfs의 `domain_translation_struct`를 읽는다.
