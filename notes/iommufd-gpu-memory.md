# iommufd의 GPU 메모리 DMA 매핑 지원 현황

- 작성일: 2026-10-13
- 기준 트리: Linux mainline v7.3-rc7 (2026-10-11), iommufd for-next (2026-09-24), linux-next 20261012
- 메일링리스트 인용 시점: 2026-10-12
- 본 팀 코드: upcie-experimental 0.9.0 (`iommu_map_pa`, `dmabuf_import`), NVIDIA 드라이버(측정 호스트 기준 580.178.04)

## 요약

**질문.** NVMe가 CUDA가 할당한 GPU VRAM으로 직접 DMA(P2P)하려면 그 VRAM을 NVMe의 IOMMU 페이지 테이블에 넣어야 한다. 지금은 upcie의 자체 커널모듈 `iommu_map_pa`가 이 일을 한다. 업스트림 iommufd가 같은 일을 하는 API를 갖추었는가, 그래서 자체 모듈을 제거할 수 있는가.

**답.** 아직 없다. iommufd는 v6.19부터 dma-buf를 받아 IOMMU 도메인에 매핑하지만, 받는 dma-buf는 vfio-pci 드라이버가 내보낸 단일 구간 MMIO dma-buf뿐이다. NVIDIA 드라이버가 내보낸 dma-buf는 거부된다. 이를 일반 exporter로 여는 설계는 둘이 제안되어 있다. PAL(Physical Address List)은 dma-buf 안에 물리주소 목록을 넘기는 새 매핑 타입을 추가하여 exporter가 그 목록을 주고 iommufd가 받는 방식이고, mm memory provider는 dma-buf를 거치지 않고 드라이버가 자기 메모리를 파일로 내면 iommufd가 `IOMMU_IOAS_MAP_FILE`로 그 파일을 매핑하는 방식이다. 두 설계 모두 미머지이고, 두 메인테이너(dma-buf, iommufd)의 의견이 아직 한 지점으로 모이지 않았다. 따라서 `iommu_map_pa`는 당분간 유지해야 한다.

**이유.** 거부는 코드 한 곳에서 일어난다. iommufd는 dma-buf의 물리주소를 vfio-pci의 전용 함수 `vfio_pci_dma_buf_iommufd_map()`을 `symbol_get()`으로 불러 얻는데, 이 함수는 exporter가 vfio-pci가 아니면 `-EOPNOTSUPP`를 돌려준다. dma-buf 프레임워크에 "물리주소 목록을 넘기는 범용 규약"이 없어서 iommufd가 이 사설 연결에 의존하는 것이고, 그 규약을 만드는 일이 바로 두 RFC다.

**성립 조건.** 이 결론은 다음 조건에서 성립한다. GPU가 CUDA로 상시 사용되어 vfio에 바인딩할 수 없고, NVMe는 vfio-pci에 바인딩되어 iommufd 또는 VFIO type1로 IOMMU 도메인을 받으며, 커널은 mainline v7.3-rc7 이하다. GPU를 vfio에 바인딩할 수 있는 환경(예: nvgrace-gpu variant 드라이버)이라면 결론이 달라진다.

**근거 표.**

| 질문 | 결론 | 근거 |
| --- | --- | --- |
| iommufd가 디바이스 메모리(dma-buf)를 IOAS에 매핑할 수 있는가 | **부분 지원** VFIO PCI dma-buf의 단일 MMIO 구간만 | UAPI 주석(v7.2 `298ab7e6f163`), `pages.c`의 `symbol_get` 경로 |
| CUDA/NVIDIA GPU dma-buf는 매핑되는가 | **미지원** `-EOPNOTSUPP` | `vfio_pci_dmabuf.c` 127행의 exporter ops 검사 |
| 일반 exporter를 여는 작업은 머지되었는가 | **미머지** 두 RFC 경합 | master, for-next, linux-next에 PAL 심볼 없음. mm provider는 2026-10-06 RFC |
| 사설 연결을 NVIDIA용으로 하나 더 두는 길은 있는가 | **없음** | iommufd 메인테이너의 2026-10-12 발언 |
| 워크어라운드 대체 시점 | **미정** 당분간 유지 | 위 네 줄의 결과 |

**의미.** `iommu_map_pa`는 VFIO/iommufd의 IOVA 회계, 수명주기, 락, dirty tracking 바깥에서 동작하므로 기술 부채이지만, 현재 용도는 실험과 검증 단계이고 프로덕션 의존은 없다. 업스트림이 어느 설계를 택하든 매핑의 의미(물리주소 목록을 `IOMMU_MMIO`로 등록)는 자체 모듈과 같으므로, 전환 자체의 비용은 크지 않다. 비용은 기다리는 시간이다.

**확인하지 못한 것.** NVIDIA dma-buf를 실제로 `IOMMU_IOAS_MAP_FILE`에 넣었을 때 어느 단계에서 어떤 오류로 실패하는지는 소스로 읽은 추론이며 실측하지 않았다(개발 PC 커널 6.8.12는 이 경로가 없다). CUDA 할당에 호스트 VMA가 없다는 서술은 일반론이다. "CUDA를 다룬 업스트림 시리즈가 없다"는 부재 주장은 patchwork 검색에 한정된다. 각 항목의 다음 단계는 부록 B에 적었다.

**반영한 변경.** 코드 변경은 없다. 본 팀 스택에서는 `iommu_map_pa`를 유지하고, §7의 감시 신호를 분기마다 점검한다.

## 1. 문제 정의

### 1.1 P2P DMA와 IOMMU 등록

LLM 추론의 KV 캐시 오프로딩, 모델 로딩, 체크포인팅처럼 GPU 메모리와 저장장치 사이에서 큰 데이터를 옮기는 작업에서는, 데이터를 GPU VRAM에서 호스트 RAM을 거쳐 NVMe로 복사하는 대신 NVMe가 GPU VRAM으로 직접 DMA하는 편이 대역폭과 CPU 부하에서 유리하다. 이 직접 경로를 P2P(peer-to-peer) DMA라고 한다.

NVMe가 IOMMU 뒤에 있으면 NVMe가 내보내는 주소(IOVA)는 IOMMU 페이지 테이블을 거쳐 물리주소로 번역된다. P2P가 성립하려면 그 테이블에 GPU VRAM의 물리주소(실제로는 GPU가 VRAM을 PCIe에 노출하는 BAR1 창의 주소)가 들어 있어야 한다. 규모를 숫자로 잡으면 다음과 같다. 본 팀의 측정에서 GPU의 BAR1은 물리주소 0x4800000000부터 32 GiB이고, CUDA가 할당한 1 GiB 버퍼는 그 안의 0x480f600000에 놓였으며, 이것을 NVMe의 IOMMU에 넣으면 2 MiB 엔트리 512개가 된다. 이 등록을 어느 주체가 어떤 API로 수행하는가가 이 보고서의 주제다.

### 1.2 현행 우회 경로 iommu_map_pa

VFIO와 iommufd가 사용자 공간에 주는 매핑 API는 모두 호스트 가상주소(VA)나 파일(fd)을 입력으로 받는다(§2.2). CUDA 할당은 호스트 주소 공간에 매핑되지 않아 VA가 없고(CUDA 일반론에 따른 추정이다), 파일 경로는 §3에서 보듯 NVIDIA dma-buf를 거부한다. 그래서 upcie는 `experimental/iommu_map_pa` 커널모듈로 이 API들을 건너뛴다.

이 모듈은 대상 vfio-pci 디바이스가 지금 쓰는 IOMMU 도메인을 `iommu_get_domain_for_dev()`로 얻은 뒤, 사용자 공간이 `dmabuf_import` 모듈로 알아낸 BAR1 물리주소 목록을 커널 내부 함수 `iommu_map()`으로 그 도메인에 직접 넣는다. 디바이스 메모리이므로 `IOMMU_MMIO` 속성으로 넣는다. 동작은 하지만, 모듈의 README가 열거하듯 VFIO/iommufd의 IOVA 회계, 수명주기 관리, 락, dirty tracking을 모두 우회한다. 도메인이 예고 없이 바뀌거나 IOVA가 겹치면 오매핑이나 use-after-free로 이어질 수 있고, README는 "production-safe VFIO extension이 아니다"라고 명시한다. README가 지목한 장기 방향은 "`IOMMU_IOAS_MAP_FILE`에 CUDA dma-buf 지원과 같은 owner-integrated dma-buf 매핑 API"다.

본 팀 스택에서 이 모듈은 DKMS 패키지 `upcie-experimental-dkms` 0.9.0(`dmabuf_import`와 함께 포장)으로 배포되고, upcie의 CUDA 경로 `dmamem_from_cuda_iommu_map_pa()`가 쓰며, `tests/test_dmamem_cuda_iommu_map_pa_nvme_readwrite.c`로 검증된다. aisio에서는 `tasks/setup_upcie_modules.yaml`이 적재한다. 즉 현재 용도는 실험과 검증이고 프로덕션 의존은 없다.

### 1.3 보고서의 범위와 구분

이 보고서는 README가 지목한 목표 API의 업스트림 진척을 머지된 패치와 진행 중인 RFC로 나누어 정리한다. 서술을 위해 지원 수준을 네 단계로 나눈다. 이 네 단계는 업스트림에 있는 분류가 아니라 이 보고서가 정리를 위해 정한 것이다.

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| ① 파일 매핑 도입 | `IOMMU_IOAS_MAP_FILE`로 memfd(호스트 페이지)를 매핑 | v6.13 (2025-01) |
| ② 디바이스 메모리 도입 | 같은 ioctl로 dma-buf(MMIO)를 매핑. 단 vfio-pci dma-buf 한정 | v6.19 (2026-02) |
| ③ 일반 exporter 개방 | 어느 드라이버의 dma-buf(또는 provider 파일)든 매핑 | 미머지, 방향 미정 |
| ④ CUDA/GPU exporter | NVIDIA 드라이버가 ③의 규약을 구현 | ③에 의존. 시리즈 없음 |

지금은 ②까지 머지되었고 ③은 미정이다. 이 그림을 읽으려면 등장 요소를 먼저 정리해야 한다.

## 2. 전체 그림과 용어

### 2.1 등장 요소

| 요소 | 역할 | 코드 위치 |
| --- | --- | --- |
| dma-buf | 한 드라이버의 버퍼를 다른 드라이버와 공유하는 커널 표준 틀. 버퍼 소유자가 exporter로서 fd로 내보내고, 받는 쪽이 importer로서 attach하여 매핑한다 | `drivers/dma-buf/dma-buf.c` |
| scatterlist | exporter와 importer가 전통적으로 주소를 주고받는 형식. `dma_addr_t` 목록이므로 DMA API를 쓰지 않는 importer에게는 맞지 않는다 | `include/linux/scatterlist.h` |
| `phys_vec` | 물리주소 한 구간(`paddr`, `len`). v6.19에 공용 타입으로 들어왔다 | `include/linux/types.h` |
| IOAS | iommufd의 IO 주소 공간 객체. 사용자 매핑을 담고 HWPT(하드웨어 페이지 테이블)를 통해 디바이스에 붙는다 | `drivers/iommu/iommufd/ioas.c` |
| `iommu_domain` | 커널 공통 IOMMU 계층의 페이지 테이블 객체. iommufd도 `iommu_map_pa`도 결국 여기에 `iommu_map()`을 부른다 | `drivers/iommu/iommu.c` |
| `IOMMU_MMIO` | 페이지 테이블 엔트리에 "캐시하지 말 것"을 전달하는 속성. 디바이스 메모리 매핑에 쓴다 | `include/linux/iommu.h` |
| revoke | exporter가 매핑을 회수하는 것. importer는 `invalidate_mappings` 콜백 안에서 매핑을 지워야 한다 | `dma_buf_invalidate_mappings()` |
| pin | importer가 버퍼를 움직이지 말라고 exporter에 요청하는 것. iommufd는 v7.1부터 일반 `dma_buf_pin()` 흐름을 탄다 | `dma_buf_pin()` |

### 2.2 사용자 매핑 API 비교

GPU 메모리를 IOMMU에 넣을 수 있는 후보 API는 네 가지다. 입력과 pin 방식이 다르고, 그 차이가 GPU 메모리를 받을 수 있는지를 정한다.

| API | 입력 | 일반 RAM | PFNMAP VMA(장치 BAR mmap) | dma-buf | 매핑 수명 보장 |
| --- | --- | --- | --- | --- | --- |
| `VFIO_IOMMU_MAP_DMA` (type1) | 호스트 VA | pin | pin 없이 `follow_fault_pfn()`으로 따라감 | 받지 않음 | PFNMAP은 없음 |
| `IOMMU_IOAS_MAP` (iommufd) | 호스트 VA | pin | 받지 않음 | 받지 않음 | pin |
| `IOMMU_IOAS_MAP_FILE` + memfd | fd | `memfd_pin_folios()` | 해당 없음 | 해당 없음 | pin |
| `IOMMU_IOAS_MAP_FILE` + dma-buf | fd | 해당 없음 | 해당 없음 | vfio-pci 단일 구간만 | revoke 콜백 |

VFIO type1은 PFNMAP VMA를 받는다. `vaddr_get_pfns()`는 VMA에 `VM_PFNMAP`이 있으면 `follow_fault_pfn()`으로 물리주소를 얻고 pin하지 않는다. QEMU가 패스스루 장치의 BAR mmap을 다른 장치의 IOMMU에 넣는 P2P가 이 경로다. 다만 매핑의 수명을 보장할 수단이 없어서, iommufd는 이 경로를 받지 않고 dma-buf 경로를 만들었다. CUDA 할당은 어느 VA 경로에도 해당하지 않는다. 호스트 VMA가 없기 때문이다. 남는 것은 dma-buf 경로 하나이고, 그 경로가 NVIDIA dma-buf를 받는지가 핵심 질문이 된다.

### 2.3 매핑 결과

어느 경로로 넣든 페이지 테이블에 들어가는 내용은 같다. 본 팀 측정값으로 적으면 다음과 같다.

| 항목 | 값 |
| --- | --- |
| 버퍼 | CUDA 1 GiB, BAR1 안의 물리주소 0x480f600000 (2 MiB 정렬) |
| IOVA | 0x3f80000000 (1 GiB 정렬) |
| 엔트리 | 2 MiB x 512 (물리주소가 1 GiB 정렬이 아니어서 1 GiB 엔트리는 쓰이지 않음) |
| 속성 | `IOMMU_MMIO`, 읽기와 쓰기 |

iommufd의 dma-buf 경로도 `BATCH_MMIO`로 모은 뒤 `IOMMU_MMIO`를 붙여 `iommu_map()`을 부르고(`pages.c` 520행), PAL RFC와 mm provider RFC도 MMIO 페이지를 `IOMMU_MMIO`로 넣는다. 자체 모듈과 업스트림 설계의 차이는 결과가 아니라 누가 물리주소를 확인하고 수명을 책임지는가에 있다. 이제 실제로 무슨 일이 일어나는지 본다.

## 3. 구체적 예시: 두 dma-buf의 경로

같은 ioctl에 두 종류의 dma-buf fd를 넣었을 때 코드가 어디까지 가는지 단계별로 적는다. 입력은 모두 `IOMMU_IOAS_MAP_FILE`에 fd, `start = 0`, `length = 1 GiB`, `flags = READABLE | WRITEABLE`이다.

### 3.1 vfio-pci dma-buf (성공)

| 단계 | 코드 | 결과 |
| --- | --- | --- |
| 1 | `iommufd_ioas_map_file()`이 플래그와 길이를 검사하고 `iopt_map_file_pages()`를 부른다 | 통과 |
| 2 | `dma_buf_get(fd)`가 성공하므로 dma-buf 경로로 간다. memfd라면 실패하여 `iopt_alloc_file_pages()`로 간다 | dma-buf 경로 |
| 3 | `iopt_alloc_dmabuf_pages()`가 크기와 `MAX_NPFNS`를 검사하고 `iopt_map_dmabuf()`를 부른다 | 통과 |
| 4 | `dma_buf_dynamic_attach()`가 iommufd의 misc 장치 명의로 attach한다. importer ops는 `allow_peer2peer = true`, `invalidate_mappings = iopt_revoke_notify` | 통과 |
| 5 | `dma_buf_pin()`이 exporter의 `pin` 콜백을 부른다. vfio-pci의 `pin` 콜백은 `dma_buf_attach_revocable()`로 importer가 `invalidate_mappings`를 구현했는지 보고, 아니면 `-EOPNOTSUPP`를 돌려준다 (v7.1) | 통과 |
| 6 | `sym_vfio_pci_dma_buf_iommufd_map()`이 selftest 훅을 시도하고(`-EOPNOTSUPP`), `CONFIG_VFIO_PCI_DMABUF`를 확인한 뒤 `symbol_get(vfio_pci_dma_buf_iommufd_map)`을 부른다 | 심볼 획득 |
| 7 | `vfio_pci_dma_buf_iommufd_map()`이 exporter ops가 vfio-pci인지, revoke되지 않았는지, 구간이 하나인지 검사하고 `phys_vec` 하나를 돌려준다 | `phys_vec` 획득 |
| 8 | 이후 도메인에 붙을 때 `BATCH_MMIO`로 `IOMMU_MMIO` 매핑을 만든다. 매핑이 IOAS에 남아 있는 동안 attach가 유지되고, exporter가 revoke하면 `iopt_revoke_notify()`가 모든 도메인에서 그 구간을 지운다 | 매핑 완료 |

### 3.2 NVIDIA dma-buf (거부)

| 단계 | 코드 | 결과 | 확신 |
| --- | --- | --- | --- |
| 1-3 | 위와 같다. dma-buf이므로 dma-buf 경로로 간다 | 통과 | 확실 |
| 4 | `dma_buf_dynamic_attach()`가 NVIDIA의 `nv_dma_buf_attach()`를 부른다. 이 콜백은 importer가 PCI 장치가 아니면(`!dev_is_pci(attachment->dev)`) 권한만 확보하고 rc=0으로 조기 반환하며, `to_pci_dev()`와 PCI 토폴로지 검사는 PCI importer에만 적용된다. iommufd의 importer 장치는 PCI 장치가 아닌 misc 장치이므로 이 조기 반환 경로를 탄다 | 통과로 추정 | 추정. 본 팀의 `dmabuf_import` misc 경로가 같은 종류의 misc 장치로 attach에 성공했다 |
| 5 | `dma_buf_pin()`. NVIDIA exporter에는 `pin` 콜백이 없으므로 0을 돌려준다 | 통과 | 확실 |
| 6 | `symbol_get(vfio_pci_dma_buf_iommufd_map)` | 심볼 획득 | 확실 |
| 7 | `vfio_pci_dma_buf_iommufd_map()` 127행: `attachment->dmabuf->ops != &vfio_pci_dmabuf_ops` | **`-EOPNOTSUPP`** | 확실 |
| 8 | `iopt_map_dmabuf()`가 unpin, detach하고 오류를 돌려준다. ioctl은 `-EOPNOTSUPP`로 끝난다 | 거부 | 확실 |

구간 개수 검사(135행)는 7단계의 exporter 검사 뒤에 있으므로, NVIDIA dma-buf는 구간이 하나여도 거부된다. 4단계의 추정은 실측으로 확인해야 하며(부록 B), 4단계에서 먼저 실패하더라도 결론(거부)은 같다. 인용한 `nv-dmabuf.c`의 거동은 최신 open-gpu-kernel-modules 소스 기준이며, 개발 PC에 설치된 DKMS NVIDIA 570.211.01의 `nv_dma_buf_ops`에는 `.attach`가 없다(측정 호스트는 580.178.04 기준).

### 3.3 iommu_map_pa 경로와의 대비

`iommu_map_pa`는 위 표의 모든 단계를 건너뛴다. 사용자 공간이 `dmabuf_import`로 얻은 물리주소 목록을 ioctl로 넘기면, 모듈이 `iommu_get_domain_for_dev()`로 얻은 도메인에 `iommu_map(iova, phys, size, IOMMU_READ | IOMMU_WRITE | IOMMU_MMIO)`를 반복한다. exporter가 누구인지, 구간이 몇 개인지, 물리주소가 유효한지를 커널이 확인하지 않는다. 그래서 지금 동작하는 유일한 경로이면서 동시에 안전하지 않은 경로다. 업스트림이 ③을 완성하면 이 모듈이 하던 일은 3.1 표의 7단계와 8단계가 대신하게 된다.

## 4. 업스트림 연혁 (머지된 패치)

| 릴리스 | 머지 윈도 | 릴리스 날짜 | 내용 | 커밋 |
| --- | --- | --- | --- | --- |
| v6.13 | 2024-11 | 2025-01-19 | `IOMMU_IOAS_MAP_FILE` (memfd) | `f4986a72d6e4` |
| v6.19 | 2025-12 | 2026-02-08 | dma-buf(MMIO) 매핑, `phys_vec`, vfio-pci dma-buf export와 P2P 기본 활성화 | `44ebaa1744fd`, `71db84a092c3`, `96ce2aeb15bd`, `3114c674401e`, `3aa31a8bb11e`, `35c3503908d3` |
| v7.1 | 2026-04 | 2026-06-14 | dma-buf revoke/pin 정비 | `8c5f9645c389`, `be6d4c9e9d71`, `6ffe939bf94f`, `95308225e5ba` |
| v7.2 | 2026-06 | 2026-08-16 | UAPI 주석 정정, access 경로에서 dma-buf 거부 | `298ab7e6f163`, `5f3fc0ad9a41` |
| v7.3-rc1 | 2026-08 | (rc7 2026-10-11) | noiommu용 `IOMMU_IOAS_NOIOMMU_GET_PA` (호스트 메모리 전용, 본 주제와 무관) | `60decab325a4` |

### 4.1 v6.13: IOMMU_IOAS_MAP_FILE (memfd)

Oracle의 Steve Sistare가 라이브 마이그레이션을 위해 추가하였다. 커밋 메시지대로 "memfd와 offset, length를 넘겨 메모리를 등록"하며 `memfd_pin_folios()`로 구현되었다. 대상은 호스트 페이지였고 디바이스 메모리는 아니었다. 중요한 것은 "VA가 아니라 파일로 매핑한다"는 확장 지점이 생긴 것이다.

### 4.2 v6.19: 디바이스 메모리(dma-buf/MMIO) 도입

NVIDIA의 Jason Gunthorpe가 주도한 묶음이 같은 ioctl로 dma-buf를 받게 하였다. `71db84a092c3`의 메시지가 범위를 정확히 적는다. "DMABUF pages are not supported for accesses, and for now can only be used with the VFIO DMABUF exporter. ... There is no pinned page accounting done for DMABUF maps. The DMABUF attachment exists so long as the dmabuf is mapped into an IOAS." 같은 묶음에서 vfio-pci가 BAR 구간을 dma-buf로 내보내는 기능(`VFIO_DEVICE_FEATURE_DMA_BUF`)과 iommufd용 전용 함수 `vfio_pci_dma_buf_iommufd_map()`, 그리고 `phys_vec` 공용 타입이 들어왔다.

iommufd와 vfio 사이의 이 전용 함수가 사설 연결(private interconnect)이다. `pages.c`의 주석은 "iommufd and vfio have a circular dependency. Future work for a phys based private interconnect will remove this."라고 적는다. v6.19는 출발점이지 완성점이 아니다.

### 4.3 v7.1: revoke/pin 정비

NVIDIA의 Leon Romanovsky가 `dma_buf_move_notify()`를 `dma_buf_invalidate_mappings()`로 개명하고, `dma_buf_attach_revocable()`을 추가하여 vfio exporter가 revoke를 따르는 pinned importer를 받게 하였으며, iommufd가 사설 경로 대신 일반 `dma_buf_pin()` 흐름을 타게 하였다. `6ffe939bf94f`는 이것이 "IOMMUFD가 VFIO dma-buf에 대한 사설 인터페이스를 없애는 데 필요한 두 항목 중 하나"라고 적고, `8c5f9645c389`는 나머지 하나를 명시한다. "This isn't enough to allow IOMMUFD to work with other exporters, it still needs a way to get the physical address list which is another series." 그 "another series"가 §6.1의 PAL RFC다.

### 4.4 v7.2에서 v7.3-rc: 현재 상태

v7.2의 `298ab7e6f163`은 UAPI 주석을 현실에 맞게 고쳤다. 현재 문구는 다음과 같다.

> Set an IOVA mapping from a memfd file. On kernels with dma-buf support, supported dma-buf files may also be accepted. This is not a generic dma-buf import path; currently supported dma-bufs include single-range VFIO PCI dma-bufs exported through VFIO_DEVICE_FEATURE_DMA_BUF, and other dma-bufs may be rejected.

코드도 같다. `pages.c`는 selftest 전용 mock exporter(`CONFIG_IOMMUFD_TEST`)를 제외하면 vfio 심볼로만 물리주소를 얻고, `vfio_pci_dmabuf.c`의 주석은 성공 조건을 "There is one physical range and it is pointing to MMIO"로 적는다. 인트리에서 GPU 메모리를 이 경로로 넣는 유일한 예는 v6.19의 nvgrace-gpu vfio variant 드라이버(`5415d887db0e`)인데, GPU를 vfio에 바인딩해야 하므로 CUDA와 공존하지 못한다. 지금까지가 머지된 것이다. 이제 무엇이 막고 있는지 본다.

## 5. 제약 요인

현행 제약은 직접 요인 하나와, 그것이 풀린 뒤에 드러나는 조건 둘로 나뉜다.

### 5.1 exporter 고정 (직접 요인)

iommufd가 물리주소를 얻는 방법이 "vfio-pci의 특정 심볼을 `symbol_get()`으로 호출"로 고정되어 있다. 다른 exporter의 dma-buf는 §3.2의 7단계에서 거부된다. 이 요인을 풀려면 iommufd가 exporter를 이름으로 알지 않고도 물리주소 목록을 받을 수 있는 규약이 있어야 한다.

### 5.2 단일 구간 조건 (후속 조건)

현행 함수는 구간이 하나일 때만 성공한다(`vfio_pci_dmabuf.c` 134행 주석 "More than one range to iommufd will require proper DMABUF support"). 이 조건은 5.1이 풀린 뒤에야 의미가 있다. 본 팀 측정에서 1 GiB CUDA 버퍼는 구간 하나였지만, NVIDIA exporter(`nv-dmabuf.c`의 `nv_dma_buf_map_pfns()`)는 핸들마다 `memArea.numRanges`개의 구간을 돌려줄 수 있으므로 일반 경로는 다중 구간을 받아야 한다. PAL RFC의 patch 24와 mm provider RFC가 각각 이를 다룬다.

### 5.3 물리주소 목록 규약 부재 (근본 조건)

iommufd는 DMA API를 쓰지 않고 `iommu_map()`에 물리주소를 직접 넣으므로, importer에게 필요한 것은 `dma_addr_t` scatterlist가 아니라 `phys_addr_t` 목록이다. dma-buf의 표준 교환 형식은 여전히 scatterlist이고, 물리주소 목록을 교환하는 범용 규약은 없다. §4.3의 커밋이 "another series"로 미룬 항목이 이것이며, §6의 두 RFC가 서로 다른 자리(dma-buf, mm)에 이 규약을 두려 한다.

## 6. 진행 중 RFC와 논쟁

### 6.1 dma-buf mapping types와 PAL (Jason Gunthorpe, NVIDIA)

2026년 2월 18일 `[RFC 00/26] Add DMA-buf mapping types and convert vfio/iommufd to use them`이 올라왔다. dma-buf에 "mapping type" 개념을 넣어 importer와 exporter가 주소 교환 형식을 협상하게 하고, 기존 scatterlist를 SGT 타입으로 옮긴 뒤, 새 타입 PAL(Physical Address List)을 추가한다. PAL은 `phys_vec` 배열을 직접 넘긴다.

본 팀 관점에서 중요한 사실 세 가지가 RFC에 명시되어 있다. 첫째, PAL importer는 모듈 로더(`EXPORT_SYMBOL_FOR_MODULES(dma_buf_pal_map_phys, "iommufd")`)로 iommufd만 허용되고, KVM은 같은 타입이 필요하다고 적혔으나 이 RFC에서는 허용되지 않았다. exporter는 누구나 구현할 수 있으며, 그 사유로 "DPDK/SPDK가 GPU 메모리를 VFIO/iommufd에 연결하는 용도"를 든다. 둘째, PAL 엔트리는 모두 MMIO로 간주되어 `IOMMU_MMIO`로 매핑된다. 셋째, patch 23이 iommufd의 vfio 함수 호출을 PAL로 바꾸고 patch 24가 다중 구간을 지원한다. 즉 §5의 요인과 두 조건을 모두 푼다.

그러나 브랜치 `jgunthorpe/linux dmabuf_map_type`의 마지막 커밋은 2026년 3월 1일이고, master, iommufd for-next, linux-next 어디에도 PAL 심볼이 없다.

### 6.2 mm memory provider (Fred Griffoul, Amazon)

기반은 David Woodhouse의 `[RFC v2 00/11] KVM: Allow alternative providers of guest_memfd backed by PFNMAP memory`(2026년 7월 20일)다. guest_memfd의 백엔드를 교체 가능하게 하는 KVM 쪽 시리즈이며, iommufd 연결은 guest_memfd를 뒷받침하는 dma-buf를 RAM으로 매핑하는 방식이었다. 저자 자신이 "장기적으로 더 깨끗한 선택인지 확신하지 못한다"고 적었다.

Griffoul은 2026년 10월 5일 `[RFC 0/6] KVM: guest_memfd: back guest_memfd with an imported dma-buf`로 dma-buf에 `get_phys()`를 추가하는 안을 냈다. dma-buf 메인테이너 Christian König이 같은 날 "importer가 페이지 테이블을 채우는 것은 absolutely clear NO-GO"라며 NAK했고, Griffoul은 당일 철회하였다. 다음 날 10월 6일 `[RFC 0/9] mm: Memory providers for guest_memfd and iommufd`가 올라왔다. 페이지 할당자 밖의 메모리를 가진 드라이버가 provider가 되어 파일을 내고, guest_memfd와 iommufd의 `IOMMU_IOAS_MAP_FILE`이 consumer로서 그 파일을 매핑한다. pin이 없고, provider가 revoke하면 모든 consumer가 매핑을 먼저 지운다. iommufd 패치(5/9)는 프레임마다 `PAGE_SIZE` 엔트리를 만들고, hole은 비워 두며, 읽기 전용 페이지는 `IOMMU_WRITE` 없이, MMIO 페이지는 `IOMMU_MMIO`로 넣는다.

이 시리즈는 dma-buf를 건드리지 않는다. 다만 KVM 쪽에서 같은 기능을 제안하는 시리즈가 둘 더 있어(Aneesh Kumar의 confidential computing용 시리즈 2026-10-10, Ackerley Tng의 resource fd RFC) 10월 12일 현재 인터페이스를 맞추는 중이고, iommufd 패치는 저자도 "주로 인터페이스를 보이기 위한 것이며 더 손봐야 한다"고 적었다.

### 6.3 쟁점 타임라인

| 날짜 | 누가 | 내용 | 출처 |
| --- | --- | --- | --- |
| 2026-02-18 | Gunthorpe | PAL RFC 26편 게시 | `0-v1-b5cab63049c0+191af-dmabuf_map_type_jgg@nvidia.com` |
| 2026-03-01 | Gunthorpe | 브랜치 마지막 커밋 | `jgunthorpe/linux dmabuf_map_type` |
| 2026-04-13 | König | patch 21(PAL)에 "pretty big NO-GO". importer의 물리주소 직접 접근 반대. "iommufd가 왜 물리주소가 필요한가" | `c413710b-4c28-4ed8-88ec-aeb8c4482011@amd.com` |
| 2026-04-13 | Gunthorpe | "CPU iommu hw only works in physical address." 목표 경로 둘: VFIO에서 KVM, 그리고 GPU/RDMA 드라이버에서 iommufd("SPDK and DPDK type userspace drivers to work with GPU memory. This is becoming a popular topic") | `20260413121628.GE2588311@nvidia.com` |
| 2026-04-22 | König | dma-buf 안에 그런 인터페이스를 두는 것 자체를 반대. 대안: exporter가 iommufd의 `iommu_domain`에 직접 매핑하는 `dma_buf_map_attachment_iommu()` | `fd8065ce-fd0e-4df5-9c80-8e9603657cfe@amd.com`, `f6d38a08-009c-4efe-9dc3-6bcf00ac35f7@amd.com` |
| 2026-04-22 | Gunthorpe | 절충안: exporter는 PAL, importer는 `iommu_domain`, 둘을 잇는 converter는 dma-buf core만 가진다. König은 mapping type 체계 자체에는 "Yes, absolutely" | `20260422150000.GK3199414@nvidia.com`, `e67426b9-4ded-4f6c-8309-7f847adb4540@amd.com` |
| 2026-05-09 | Xu Yilun | 이 방식은 KVM에 맞지 않는다(KVM은 주소 공간 관리자이자 매퍼) | `af7GzASJiASopYiN@yilunxu-OptiPlex-7050` |
| 2026-05-11 | Gunthorpe | 동의. PAL 스레드의 마지막 메시지 | `20260511224841.GA1197107@nvidia.com` |
| 2026-07-20 | Woodhouse | guest_memfd provider RFC v2. iommufd 연결은 dma-buf | `20260720111259.122911-1-dwmw2@infradead.org` |
| 2026-10-05 | Griffoul, König | dma-buf `get_phys()` RFC와 당일 NAK. König: exporter 전용 사설 인터페이스는 괜찮고 `symbol_get()`이 "아마 옳은 방법" | `20261005095552.52748-1-griffoul@gmail.com`, `a04f17cc-f59a-4240-81c8-29776eee3a2e@amd.com`, `f0077cec-10fe-400a-b229-f7434e297364@amd.com` |
| 2026-10-06 | Griffoul | mm memory provider RFC 9편 | `20261006183235.16576-1-griffoul@gmail.com` |
| 2026-10-12 | Gunthorpe | "I don't want to keep expanding this hack in iommufd. ... I don't want to hardwire every exporter into iommufd." 현행 vfio 사설 연결은 범용 해법을 끌어내기 위한 것이지 확장할 대상이 아니다 | `20261012144616.GF14213@ziepe.ca` |
| 2026-10-12 | Griffoul | iommufd 쪽 exporter registry 안은 포기. mm 경로가 Gunthorpe가 생각하는 범용 인터페이스인지 질문. 답 없음 | `20261012152946.63489-1-griffoul@gmail.com` |

표에서 읽을 수 있는 것은 두 가지다. PAL 스레드는 절충안이 나온 채 5월에 멈췄고, 10월에 쟁점이 "누가 물리주소를 확인하는가"에서 "범용 훅을 dma-buf, iommufd 사설 연결, mm 중 어디에 두는가"로 옮겨 갔다. 두 메인테이너는 서로 상대 쪽 서브시스템에 훅을 두자고 한다. König은 dma-buf 밖(iommufd 사설 또는 mm)을, Gunthorpe는 dma-buf 안(pluggable한 `iommu_domain` 채우기)을 말한다.

### 6.4 설계 비교

| 항목 | `iommu_map_pa` (본 팀) | 현행 vfio 경로 (v6.19+) | PAL RFC | mm provider RFC |
| --- | --- | --- | --- | --- |
| exporter 범위 | 제한 없음 (사용자 공간이 물리주소를 줌) | vfio-pci만 | PAL을 구현한 모든 드라이버 | provider 파일을 내는 모든 드라이버 |
| 물리주소를 확인하는 쪽 | 아무도 (사용자 공간을 믿음) | vfio-pci | exporter가 주고 importer(iommufd)가 받음 | provider가 주고 consumer가 받음 |
| 구간 수 | 제한 없음 | 1 | 다중 (patch 24) | 다중, 페이지 단위 |
| pin / revoke | 없음 | pin + revoke 콜백 | pin + revoke 콜백 | pin 없음, revoke만 |
| IOVA 회계와 락 | 우회 | iommufd | iommufd | iommufd |
| MMIO 속성 | `IOMMU_MMIO` | `IOMMU_MMIO` | `IOMMU_MMIO` | 페이지 타입에 따라 `IOMMU_MMIO` |
| NVIDIA 드라이버가 할 일 | 없음 | 불가 (vfio-pci가 아님) | PAL exporter 구현 | provider 파일 구현 |
| 상태 | 동작, 안전하지 않음 | 머지됨 | 미머지, 2026-03 이후 정체 | 미머지, 2026-10-06 RFC, 논의 중 |

### 6.5 본 팀에 미치는 함의

첫째, NVIDIA 드라이버가 vfio-pci처럼 사설 심볼을 하나 더 제공하여 현행 경로에 추가되는 방법은 없다. dma-buf 메인테이너는 그 방법을 허용했지만 iommufd 메인테이너는 거부했다. 둘째, CUDA/NVIDIA를 명시적으로 다룬 시리즈는 이번 조사에서 찾지 못했지만, 용도 자체는 Gunthorpe가 2026-04-13에 두 번째 목표 경로로 언급했다. 셋째, 어느 설계가 채택되든 NVIDIA 쪽은 그 범용 규약(PAL exporter 또는 provider 파일)을 구현하는 형태가 될 것으로 전망된다. 이것은 추정이다.

## 7. 결론과 제언

**결론.** iommufd는 v6.19에서 "회계와 수명주기를 갖춘 owner-integrated 매핑"이라는 개념을 확보했지만, 지원 대상이 vfio-pci dma-buf 한 구간에 고정되어 있어 본 팀의 CUDA dma-buf는 매핑되지 않는다. 일반화 설계 둘은 미머지이고 방향이 미정이며, iommufd 메인테이너는 exporter별 사설 연결을 더 늘리지 않겠다고 밝혔다(2026-10-12). 따라서 범용 설계가 머지되기 전에는 `iommu_map_pa`를 대체할 수 없고, 그 시점은 예측하기 어렵다.

**리스크.** `iommu_map_pa`는 VFIO/iommufd의 회계, 수명주기, 락, dirty tracking 밖에서 동작하므로 도메인 교체나 IOVA 충돌 시 오매핑과 use-after-free 위험이 있다. 현재 용도가 실험과 검증에 한정되므로 이 위험의 영향 범위도 그 안에 한정된다.

**제언.**

- **유지.** `iommu_map_pa`를 유지하되 README의 안전 제약(도메인 변경 금지, IOVA 창 예약, 매핑 제거 순서)을 운영 절차에 적는다.
- **감시.** 아래 신호를 분기마다 점검한다.
- **선제 대응(선택).** PAL 또는 mm provider 중 하나가 for-next에 들어가면, upcie에 해당 규약의 exporter 프로토타입을 만들어 전환을 사전 검증한다. 매핑의 의미가 자체 모듈과 같으므로 전환 비용은 크지 않을 것으로 판단된다.

**감시 신호.**

| 신호 | 확인 방법 | 의미 |
| --- | --- | --- |
| PAL 심볼이 iommufd for-next에 등장 | `git grep dma_buf_pal_map_phys` on `jgg/iommufd.git for-next` | PAL 채택. upcie PAL exporter 착수 |
| `FOP_MEM_PROVIDER` 또는 `mm/memory_provider`가 linux-next에 등장 | `git grep -l FOP_MEM_PROVIDER` on linux-next | mm provider 채택. provider 파일 설계 검토 |
| Griffoul의 2026-10-12 질문에 Gunthorpe가 답함 | patchwork patch 14867538(dma-buf RFC 2/6)의 comments | 방향 수렴의 첫 신호 |
| NVIDIA open-gpu-kernel-modules의 `nv-dmabuf.c`에 PAL 또는 provider 코드 | 릴리스 노트, 소스 grep | ④ 단계 착수 |
| `IOMMU_IOAS_MAP_FILE` UAPI 주석에서 "not a generic dma-buf import path" 삭제 | `include/uapi/linux/iommufd.h` | ③ 완성 |

**전환 착수 조건.** 위 첫째 또는 둘째 신호가 나타나고, NVIDIA 드라이버가 해당 규약을 구현한 릴리스를 내며, 본 팀 커널이 그 릴리스 이상일 때 전환을 시작한다. 세 조건이 모두 갖춰지기 전에는 전환 작업이 업스트림 변경에 따라 다시 바뀔 수 있다.

## 부록 A. 근거 자료

### 머지된 커밋

| 릴리스 | 커밋 | 제목 |
| --- | --- | --- |
| v6.13 | `f4986a72d6e4` | iommufd: Add IOMMU_IOAS_MAP_FILE |
| v6.19 | `44ebaa1744fd` | iommufd: Accept a DMABUF through IOMMU_IOAS_MAP_FILE |
| v6.19 | `71db84a092c3` | iommufd: Add DMABUF to iopt_pages |
| v6.19 | `96ce2aeb15bd` | vfio/pci: Add vfio_pci_dma_buf_iommufd_map() |
| v6.19 | `3114c674401e` | iommufd: Allow MMIO pages in a batch |
| v6.19 | `3aa31a8bb11e` | dma-buf: provide phys_vec to scatter-gather mapping routine |
| v6.19 | `35c3503908d3` | vfio/pci: Enable peer-to-peer DMA transactions by default |
| v6.19 | `5415d887db0e` | vfio/nvgrace: Support get_dmabuf_phys |
| v7.1 | `8c5f9645c389` | iommufd: Add dma_buf_pin() |
| v7.1 | `be6d4c9e9d71` | dma-buf: Add dma_buf_attach_revocable() |
| v7.1 | `6ffe939bf94f` | vfio: Permit VFIO to work with pinned importers |
| v7.1 | `95308225e5ba` | dma-buf: Rename dma_buf_move_notify() to dma_buf_invalidate_mappings() |
| v7.2 | `298ab7e6f163` | iommufd: Clarify IOAS_MAP_FILE dma-buf support |
| v7.2 | `5f3fc0ad9a41` | iommufd: Reject DMABUF pages from the access pin path |
| v7.3-rc1 | `60decab325a4` | iommufd: Add an ioctl to query PA from IOVA for noiommu mode |

### 미머지 시리즈와 스레드

| 구분 | msgid 또는 위치 |
| --- | --- |
| PAL RFC 00/26 | `0-v1-b5cab63049c0+191af-dmabuf_map_type_jgg@nvidia.com` (patchwork 시리즈 1055041) |
| PAL 브랜치 | `https://github.com/jgunthorpe/linux` `dmabuf_map_type`, 끝 c37cf2824740 |
| Woodhouse RFC v2 00/11 | `20260720111259.122911-1-dwmw2@infradead.org` |
| Griffoul dma-buf RFC 0/6 | `20261005095552.52748-1-griffoul@gmail.com` |
| Griffoul mm provider RFC 0/9 | `20261006183235.16576-1-griffoul@gmail.com` (patchwork 시리즈 1180470) |
| 인용한 답글 | §6.3 표의 출처 열 |

### 소스 파일

| 파일 | 쓰임 |
| --- | --- |
| `drivers/iommu/iommufd/pages.c` (v7.3-rc7) | `iopt_map_dmabuf()`, `sym_vfio_pci_dma_buf_iommufd_map()`, `BATCH_MMIO` |
| `drivers/iommu/iommufd/io_pagetable.c` | `iopt_map_file_pages()`의 dma-buf/memfd 분기 |
| `drivers/vfio/pci/vfio_pci_dmabuf.c` | `vfio_pci_dma_buf_iommufd_map()`의 exporter와 구간 검사 |
| `drivers/vfio/vfio_iommu_type1.c` | `vaddr_get_pfns()`의 `VM_PFNMAP` 처리 |
| `include/uapi/linux/iommufd.h` | `IOMMU_IOAS_MAP_FILE` 주석 |
| `upcie-experimental-0.9.0/iommu_map_pa/{README.md, iommu_map_pa.c}`, `dkms.conf` | 자체 모듈의 동작과 제약 |
| `upcie-experimental-0.9.0/dmabuf_import/dmabuf_import.c` | misc 장치 명의 attach |
| NVIDIA 드라이버(측정 호스트 기준 580.178.04) `nvidia/nv-dmabuf.c` | `nv_dma_buf_ops`, `nv_dma_buf_attach()`, `nv_dma_buf_map_pfns()` |
| 본 팀 GPU IOMMU 매핑 크기 측정 보고서 (2026-09) | §1.1과 §2.3의 주소와 엔트리 수 |

## 부록 B. 방법과 한계

### 방법

- 머지 여부와 릴리스 귀속은 torvalds/linux의 `git tag --contains`로 확인하였다. iommufd for-next와 linux-next, PAL 브랜치는 직접 fetch하여 심볼을 grep하였다.
- 메일링리스트 인용은 patchwork.kernel.org REST API(`/api/covers/`, `/api/series/<id>/`, `/api/patches/<id>/comments/`)로 원문을 읽었다. lore.kernel.org 웹은 봇 차단으로 읽지 못하였다.
- 본 팀 코드와 NVIDIA 드라이버는 개발 PC의 설치 소스를 읽었다.
- 측정한 것과 추론한 것은 문장 단위로 구분하였다. "추정"이라고 적은 것은 소스나 로그로 확인하지 못한 것이다.

### 바로잡은 이전 기록

초안(커밋 a132b05)과 이 판의 차이다.

| 초안의 서술 | 이 판 | 경위 |
| --- | --- | --- |
| VFIO type1과 iommufd 모두 GPU 메모리를 pin할 수 없어 거부한다 | type1은 PFNMAP VMA를 pin 없이 매핑한다. iommufd만 받지 않는다. CUDA 메모리는 VMA 자체가 없다 | `vfio_iommu_type1.c`를 읽지 않고 두 API를 묶었다 |
| GPU VRAM은 일반적으로 여러 물리 구간에 분포한다 | 팀 측정에서 1 GiB 버퍼는 구간 하나였다. 구간 수는 exporter 검사 뒤의 2차 조건이다 | 일반론을 근거 없이 썼고 검사 순서를 보지 않았다 |
| PAL importer는 iommufd/KVM만 허용 | iommufd만 허용. KVM은 필요하다고만 적힘 | 커밋 메시지의 "required by iommufd and kvm"을 허용으로 읽었다 |
| PAL 논의는 2026-05-11 이후 정체 | PAL 스레드는 그렇다. 쟁점은 2026-10-05와 10-12에 다른 스레드에서 이어졌다 | 10월 스레드의 답글을 읽지 않았다 |
| mm memory provider 제안자는 Griffoul과 Woodhouse | Griffoul. Woodhouse 시리즈는 기반이며 그 iommufd 연결은 dma-buf였다 | 두 시리즈를 하나로 묶었다 |
| "one physical range" 계약은 `pages.c`에 있다 | `vfio_pci_dmabuf.c`에 있다 | 인용 위치 오기 |

### 확인하지 못한 것과 다음 단계

| 항목 | 확신 | 다음 단계 |
| --- | --- | --- |
| NVIDIA dma-buf가 §3.2의 4단계(attach)를 통과하는지, 최종 오류가 `-EOPNOTSUPP`인지 | 추정 | v6.19 이상 커널에서 `dmabuf_import`가 내보낸 fd를 `IOMMU_IOAS_MAP_FILE`에 넣는 프로브를 실행하고 errno와 dmesg를 기록한다 |
| CUDA 할당에 호스트 VMA가 없다 | 추정 (일반론) | `test_dmamem_cuda_iommu_map_pa_nvme_readwrite` 실행 중 `/proc/<pid>/maps`에 BAR1 범위(0x4800000000 이후)가 있는지 본다 |
| CUDA/NVIDIA를 다룬 업스트림 시리즈가 없다 | 추정 (patchwork 검색 한정) | lore의 `lei` 또는 public-inbox 미러로 "nvidia dmabuf iommufd"를 재검색한다 |
| 1 GiB 버퍼가 구간 하나였다 | 간접 확인 (측정 보고서 인용) | 원본 로그 `/tmp/claude-doc/aisio/gpu-iommu-map-size-report.md`와 `/tmp/claude-doc/upcie/patent/experiments/bam-probe-single-range-2026-09-22.txt`(`phys_segs=1`)를 다시 연다 |
| NVIDIA가 어느 규약을 구현할지 | 추정 | 감시 신호 표의 넷째 항목 |

미머지 시리즈는 이후 리비전이 나올 수 있으며, 인용은 2026년 10월 12일 시점이다.
