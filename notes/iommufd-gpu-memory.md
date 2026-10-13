## 요약

본 보고서는 NVMe가 GPU VRAM으로 직접 DMA(P2P)하는 경로를 본 팀 스택에서 사용하기 위하여, 업스트림 Linux **iommufd**가 GPU 메모리를 IOMMU 도메인에 매핑하는 기능을 어디까지 지원하는지 조사한 결과를 정리한 것이다. 현재는 upcie의 자체 커널모듈 `iommu_map_pa`가 해당 기능을 우회 구현하고 있으나, 이 모듈은 VFIO/iommufd의 IOVA 회계, 수명주기, 락을 우회하는 임시 수단이므로, 장기적으로는 업스트림 API로 대체되어야 한다.

조사 결과, iommufd는 **v6.19(2025년 12월)에서 디바이스 메모리(dma-buf) 매핑을 도입**하였으나, 지원 범위가 **VFIO PCI dma-buf가 가리키는 단일 MMIO 구간**으로 한정되어 있다. 즉 iommufd는 "디바이스 메모리를 IOMMU 도메인에 등록하고 수명주기를 관리한다"는 본 팀과 동일한 기능을 수행하게 되었으나, **GPU 벤더(NVIDIA/CUDA)가 내보내는 dma-buf는 여전히 수용하지 않는다**(`-EOPNOTSUPP`). 이를 일반화하려는 두 설계 — dma-buf "mapping types/PAL"과 mm "memory provider" — 는 모두 **RFC 단계로 미머지** 상태이며, 방향 또한 확정되지 않았다.

따라서 **2026년 10월(mainline 7.3-rc) 기준으로 `iommu_map_pa`는 대체 불가**이며, 대체 시점은 커뮤니티 합의에 의존하여 예측이 어렵다. 본 보고서는 이 판단의 근거를 릴리스 및 커밋 단위로 제시하고, 향후 감시 항목과 마이그레이션 착수 조건을 제언한다.

**경합 중인 두 RFC.** 일반 exporter를 열려는 두 시도가 있으며, 모두 미머지다.

| RFC | 제안자 | 요지 | 상태 |
| --- | --- | --- | --- |
| DMA-buf mapping types (PAL) | J. Gunthorpe (NVIDIA) | dma-buf에 주소 교환 형식을 협상하는 틀을 도입하고, 물리주소 목록(**PAL**) 타입으로 iommufd가 다중 range 메모리를 매핑한다. | 미머지 (2026년 3월 이후 정체) |
| mm memory provider | F. Griffoul, D. Woodhouse (Amazon) | mm 계층에 메모리 대여 인터페이스를 두고, iommufd가 provider 파일을 매핑한다(pin 없이, revoke 방식). dma-buf 경로는 폐기. | 미머지 (2026년 10월 최신) |

쟁점은 "누가 물리주소를 확인하는가"이다. dma-buf 메인테이너는 체계 자체에는 찬성하나 importer의 물리주소 직접 수신에는 반대하여, 2026년 5월 이후 합의가 정체되어 있다.

| 질문 | 결론 |
| --- | --- |
| iommufd가 디바이스 메모리(dma-buf)를 IOAS에 매핑할 수 있는가 | **부분 지원** VFIO PCI dma-buf의 단일 MMIO 구간만 |
| CUDA/NVIDIA GPU dma-buf는 매핑되는가 | **미지원** 거부됨(`-EOPNOTSUPP`) |
| 일반 exporter를 여는 작업은 머지되었는가 | **미머지** 상반된 두 RFC가 경합 중 |
| 워크어라운드 대체 시점 | **미정** 당분간 유지가 합리적 |

## 1. 서론

### 1.1 배경

LLM 추론의 KV 캐시 오프로딩, 모델 로딩, 체크포인팅과 같이 GPU 메모리와 저장장치 사이에서 대용량 데이터를 주고받는 작업에서는, 데이터를 GPU VRAM에서 호스트 RAM을 거쳐 NVMe로 복사하는 대신 NVMe가 **GPU VRAM으로 직접 DMA**하는 편이 대역폭과 CPU 부하 측면에서 유리하다. 이 직접 경로를 P2P(Peer-to-Peer) DMA라고 한다.

P2P가 성립하려면 NVMe가 내보내는 주소(IOVA)가 GPU VRAM의 물리주소로 번역되도록, NVMe가 사용하는 **IOMMU 페이지 테이블에 GPU 메모리를 등록**하여야 한다. 문제는 이 등록을 담당하는 사용자 공간 API가 GPU 메모리를 수용하지 못한다는 점이다.

### 1.2 현행 우회 경로

VFIO와 iommufd가 제공하는 사용자 매핑 API(`VFIO_IOMMU_MAP_DMA`, iommufd의 `IOMMU_IOAS_MAP`)는 사용자 가상주소(VA)를 입력으로 받아 해당 페이지를 pin한 뒤 페이지 테이블을 구성한다. 그러나 GPU VRAM은 커널이 관리하는 일반 RAM 페이지가 아니라 디바이스 메모리(PFNMAP 영역)이므로 pin이 불가능하다. 즉 "pin 가능한 호스트 VA만 수용한다"는 API의 전제가 GPU 메모리와 맞지 않는다.

이를 우회하기 위해 upcie는 `experimental/iommu_map_pa` 커널모듈을 제공한다. 이 모듈은 대상 vfio-pci 디바이스가 현재 사용하는 IOMMU 도메인을 `iommu_get_domain_for_dev()`로 조회한 뒤, 커널 내부 함수 `iommu_map()`에 물리주소를 직접 등록한다(디바이스 메모리이므로 `IOMMU_MMIO` 속성으로 매핑). 동작은 하나, VFIO/iommufd의 **IOVA 회계, 수명주기 관리, 락, dirty tracking을 모두 우회**한다. 도메인이 예고 없이 교체되거나 IOVA가 충돌할 경우 오매핑, use-after-free로 이어질 수 있으며, 모듈 자체가 "production-safe가 아님"을 명시하고 있다.

### 1.3 본 팀 스택에서의 현황

`iommu_map_pa`는 **실험적(experimental) 모듈**로 DKMS 패키지 형태로 배포되며, upcie의 CUDA dma-buf 경로(`dmamem_from_cuda_iommu_map_pa`)에서 사용된다. 정식 uPCIe API가 아니며, 동작 검증은 NVMe 읽기/쓰기 테스트(`tests/test_dmamem_cuda_iommu_map_pa_nvme_readwrite.c`)로 수행된다. 본 팀 벤치마크 스택(aisio)에서는 `tasks/setup_upcie_modules.yaml`을 통해 적재된다. 즉 현재 용도는 실험 및 검증 단계이며, 프로덕션 의존은 확인되지 않는다. 모듈 버전은 0.9.0이다.

### 1.4 보고서 범위

`iommu_map_pa`가 지목한 목표 API는 "owner-integrated dma-buf 매핑 API, 곧 `IOMMU_IOAS_MAP_FILE`에 CUDA dma-buf 지원"이다. 본 보고서는 해당 API의 업스트림 진척을 머지된 패치와 진행 중 RFC를 함께 놓고 정리한다. §2에서 배경 기술을, §3에서 지원 현황을, §4에서 현재의 제약 요인을, §5에서 진행 중 논쟁을, §6에서 결론과 제언을 서술한다.

## 2. 배경 기술

### 2.1 IOMMU와 IOVA→PA 번역

IOMMU는 디바이스가 내보내는 주소(IOVA)를 시스템 물리주소(PA)로 번역하는 하드웨어이다. 디바이스가 IOMMU 뒤에 위치하면, 디바이스가 DMA에 사용하는 주소는 실제 메모리 주소가 아니라 IOMMU 페이지 테이블이 정한 IOVA이며, 이 테이블을 누가 어떻게 구성하는지가 격리와 안전성의 핵심이다. VFIO/iommufd 환경에서 이 테이블은 커널이 소유하며, 사용자 공간은 API를 통해서만 간접적으로 접근한다.

### 2.2 dma-buf와 exporter/importer

**dma-buf**는 서로 다른 디바이스와 드라이버가 하나의 버퍼를 공유하기 위한 커널 표준 프레임워크이다. 버퍼를 소유한 쪽이 **exporter**(예: GPU 드라이버)로서 파일 디스크립터로 내보내고, 다른 쪽이 **importer**로서 해당 fd를 받아 자신의 디바이스가 접근할 수 있도록 매핑한다. 전통적으로 양측은 `scatterlist`(`dma_addr_t`의 목록)로 주소를 교환한다. `dma_addr_t`는 DMA API에 특화된 타입이므로, DMA API를 사용하지 않는 소비자에게는 적합하지 않다는 한계가 있다.

### 2.3 iommufd의 매핑 경로

iommufd는 IOAS(IO Address Space) 객체에 IOVA 매핑을 담고, HWPT(하드웨어 페이지 테이블)를 통해 디바이스에 연결한다. 사용자 매핑 경로는 두 가지이다.

- `IOMMU_IOAS_MAP` — 사용자 VA를 받아 pin한 뒤 매핑한다. 호스트 RAM 전용이며, pin이 불가능한 GPU 메모리는 등록할 수 없다.
- `IOMMU_IOAS_MAP_FILE` — v6.13에 추가된 경로로, VA 대신 파일(fd)을 받아 매핑한다. 도입 당시에는 memfd만 수용하였다.

GPU 메모리를 다루기 위해서는 `IOMMU_IOAS_MAP_FILE` 경로가 열려야 하며, 그 대상이 memfd에서 dma-buf(디바이스 메모리)로 확장되는지가 핵심 질문이 된다.

### 2.4 IOMMU_MMIO 속성

일반 RAM과 달리 GPU VRAM 및 BAR 영역은 캐시되어서는 안 되는 MMIO/디바이스 메모리이다. IOMMU 페이지 테이블에 이 사실을 전달하는 플래그가 `IOMMU_MMIO`이며, `iommu_map_pa`도 이 플래그로 매핑한다. 후술하듯 업스트림의 신규 경로 역시 GPU 메모리를 `IOMMU_MMIO`로 매핑하므로, 이 점에서 자체 우회 모듈과 업스트림 설계의 의미는 동일하다.

## 3. 업스트림 지원 현황 (머지된 패치)

iommufd의 디바이스 메모리 지원은 아래 4단계로 진화하였으며, 현재는 ② 단계에서 멈춰 ③을 대기하는 상태이다.

| 단계 | 릴리스 | 내용 |
| --- | --- | --- |
| ① 파일 매핑 도입 | v6.13 | `IOMMU_IOAS_MAP_FILE` — memfd(호스트 페이지) 매핑 |
| ② 디바이스 메모리 도입 | v6.19 | dma-buf(**MMIO = 디바이스 메모리**) 매핑 — **단 VFIO PCI dma-buf 한정** |
| ③ 일반 exporter 개방 | — | dma-buf mapping types(**PAL**) 또는 mm memory provider — **미머지, 방향 미정** |
| ④ CUDA/GPU exporter | — | ③에 의존. 명시적으로 다룬 시리즈 없음 |

### 3.1 v6.13 — IOMMU_IOAS_MAP_FILE (memfd)

2024년 11월, Oracle의 Steve Sistare가 `IOMMU_IOAS_MAP_FILE`을 추가하였다(`f4986a72d6e4`). 목적은 라이브 마이그레이션이며, 게스트 메모리를 `memfd` 형태로 전달하여 IOAS에 매핑하는 것이었다. 당시 대상은 memfd, 즉 호스트 페이지였고 디바이스 메모리는 아니었다. 다만 "VA가 아니라 파일로 매핑한다"는 확장 지점이 마련된 것이 중요하다.

### 3.2 v6.19 — 디바이스 메모리(dma-buf/MMIO) 도입

전환점은 2025년 12월이다. NVIDIA의 Jason Gunthorpe가 주도한 패치 묶음이 v6.19에 반영되어, iommufd가 dma-buf를 받아 IOAS에 매핑하게 되었다(`44ebaa1744fd`, `71db84a092c3` 등). 매핑 대상은 MMIO, 즉 디바이스 메모리이며 `IOMMU_MMIO`로 등록된다. 함께 `phys_vec`(물리주소 벡터) 공용 타입과 VFIO PCI의 P2P 기본 활성화가 정비되었다.

그러나 이 기능은 **VFIO PCI가 내보내는 dma-buf 전용**이다. iommufd는 `vfio_pci_dma_buf_iommufd_map()` 함수를 `symbol_get()`으로 호출하는데, 이는 VFIO exporter와 iommufd importer 사이의 사설 연결(private interconnect)이다. 코드 주석에도 "iommufd와 vfio는 순환 의존이 있으며, 물리주소 기반 사설 연결이 도입되면 본 연결은 제거될 것"이라고 기술되어 있다. 즉 v6.19는 출발점이며 완성점이 아니다.

### 3.3 v7.1 — revoke/pin 정비

2026년 4월(v7.1)에는 NVIDIA의 Leon Romanovsky가 dma-buf의 revoke/pin 흐름을 정리하였다(`8c5f9645c389`, `be6d4c9e9d71`, `6ffe939bf94f`, `95308225e5ba`). `move_notify`를 `invalidate_mappings`로 개명하고 `dma_buf_pin()`과 pinned importer 지원을 추가하여, iommufd의 VFIO 의존을 일부 제거하였다. 다만 해당 시리즈의 커밋 메시지에는 **"다른 exporter를 지원하기 위해서는 물리주소 목록을 얻는 수단이 아직 필요하다"**고 명시되어 있다. 본 팀에 필요한 조각이 업스트림에서도 미구현 항목으로 인정된 것이다.

### 3.4 현재 상태 (mainline 7.3-rc)

2026년 10월 mainline(7.3-rc)에서 사실 관계는 UAPI 주석과 코드에 그대로 드러난다.

- **UAPI 문구**(`include/uapi/linux/iommufd.h`): "This is **not a generic dma-buf import path**; currently supported dma-bufs include **single-range VFIO PCI dma-bufs** ... and other dma-bufs may be rejected."
- **코드 경로**(`drivers/iommu/iommufd/pages.c`): dma-buf는 `vfio_pci_dma_buf_iommufd_map()` 심볼로만 매핑된다(`CONFIG_VFIO_PCI_DMABUF`로 제어되며, 부재 시 `-EOPNOTSUPP`). 계약은 "one physical range ... pointing to MMIO"이다.

정리하면 현재 매핑 가능한 대상은 vfio-pci 디바이스 자신의 BAR 한 구간에 국한된다. GPU가 CUDA로 상시 사용되며 NVIDIA 드라이버가 VRAM을 dma-buf로 내보내는 본 팀 시나리오는, exporter가 vfio-pci가 아니므로 이 경로에 해당하지 않는다.

## 4. 현재 제약 요인 분석

현행 제약은 세 가지 요인으로 구분할 수 있다.

### 4.1 exporter 고정 (hardwired)

iommufd의 dma-buf importer는 vfio-pci exporter에 고정되어 있다. importer가 exporter로부터 물리주소를 얻는 방식이 "vfio-pci의 특정 심볼을 `symbol_get`으로 호출"로 고정되어 있으므로, NVIDIA 드라이버와 같이 다른 exporter가 dma-buf를 내보내면 해당 심볼이 부재하여 `-EOPNOTSUPP`로 거부된다. 일반 exporter를 수용하려면 "물리주소 목록을 교환하는 범용 규약"이 먼저 마련되어야 한다.

### 4.2 단일 MMIO range 조건

현행 경로는 dma-buf가 MMIO 한 구간을 가리킬 때만 동작한다. GPU VRAM은 일반적으로 여러 물리 구간에 분포하므로, 이 조건만으로도 GPU dma-buf는 배제된다.

### 4.3 물리주소 목록 API 부재

가장 근본적인 요인이다. iommufd는 DMA API를 사용하지 않고 `iommu_map()`으로 물리주소를 직접 페이지 테이블에 등록하므로, importer에게 필요한 것은 `dma_addr_t`의 scatterlist가 아니라 **`phys_addr_t` 목록**이다. 그러나 dma-buf의 표준 교환 형식은 여전히 scatterlist이며, 물리주소 목록을 교환하는 범용 규약은 존재하지 않는다. §3.3의 커밋이 이 항목을 명시적으로 미구현으로 남긴 이유이다.

자체 모듈과의 대비는 다음과 같다. `iommu_map_pa`는 이 세 요인을 정면으로 우회한다 — exporter, range 개수, 물리주소 규약을 따지지 않고 `iommu_map()`에 직접 등록한다. 이로써 현재 유일하게 동작하는 경로이지만, 회계, 수명주기, 락이 없어 안전하지 않다. 업스트림이 ③ 단계에서 이 요인들을 해소하면 본 모듈은 역할을 다하게 된다.

**그림 1. 지원 진화와 현재 위치.** ③ 단계에서 정체 상태이다.

## 5. 진행 중 작업 및 논쟁

③ 단계(일반 exporter 개방)를 향한 시도는 두 진영으로 나뉘어 있으며, 모두 미머지 상태이다. 어느 쪽도 "곧 머지"라기보다 방향을 다투는 중이다.

### 5.1 dma-buf mapping types와 PAL (Jason Gunthorpe)

2026년 2월 제안된 RFC("Add DMA-buf mapping types", 26개 패치)는 dma-buf 자체에 "mapping types" 개념을 도입한다. 기존의 scatterlist 단일 형식 대신, importer와 exporter가 주소 교환 형식을 협상하도록 하는 틀이다. 여기에 iommufd를 위해 추가된 것이 **PAL(Physical Address List)** 타입이며, `phys_vec` 배열, 즉 물리주소 목록을 직접 교환한다.

본 팀 관점에서 중요한 사항이 세 가지 이 RFC에 명시되어 있다. 첫째, PAL importer는 모듈 로더에 의해 iommufd/KVM만 구현하도록 제한되나, exporter는 누구나 구현할 수 있으며 그 사유로 "DPDK/SPDK가 GPU 메모리를 VFIO/iommufd로 연결하기 위함"이라고 GPU 메모리를 직접 언급한다. 둘째, 매핑은 `IOMMU_MMIO`로 수행되어 자체 워크어라운드와 동일하다. 셋째, patch 23에서 iommufd가 vfio 함수 대신 PAL을 사용하고, patch 24에서 다중 range를 지원한다. 즉 본 RFC는 §4의 세 요인을 모두 해소한다.

다만 브랜치(`jgunthorpe/linux dmabuf_map_type`)의 최종 커밋은 2026년 3월 1일이며, 이후 진척이 없고 master, iommufd for-next, linux-next 어디에도 반영되지 않았다.

### 5.2 mm memory provider (Fred Griffoul / David Woodhouse, Amazon)

다른 진영은 dma-buf를 확장하는 대신 mm 계층에 "memory provider" 인터페이스를 신설한다. 페이지 할당자 밖에서 메모리를 소유한 드라이버(provider)가 그 메모리를 대여하고, 소비자(consumer)인 guest_memfd와 iommufd의 `IOMMU_IOAS_MAP_FILE`이 이를 매핑한다. 특징은 pin을 수행하지 않는다는 점이다 — provider가 언제든 프레임을 회수(revoke)할 수 있고, 회수 시 모든 consumer가 매핑을 먼저 제거한다. 2026년 10월 최신 RFC(Griffoul, 9개 패치)의 iommufd 관련 패치는 provider 파일을 수용하되, MMIO 페이지는 `IOMMU_MMIO`로, hole은 미매핑으로, 읽기 전용 페이지는 `IOMMU_WRITE` 없이 매핑한다.

주목할 점은 이 진영이 dma-buf 경로를 명시적으로 폐기하였다는 것이다. 동일 저자가 2026년 10월 초 dma-buf를 이용한 접근(`get_phys()` 등)을 제안하였다가, dma-buf 메인테이너의 반대로 이를 접고 mm 계층으로 방향을 전환하였다.

### 5.3 논쟁의 실체

양 진영을 가른 쟁점은 "누가 물리주소를 확인하는가"이다. dma-buf 메인테이너 Christian König은 일반 mapping type 체계 자체에는 찬성("Yes, absolutely")하되, importer가 dma-buf로부터 물리주소를 직접 수신하는 PAL importer에는 반대한다 — importer가 dma-buf로 자체 페이지 테이블을 구성하는 것을 차단하려는 것이다. 이에 Jason은 2026년 4월 22일 "exporter=PAL, core=converter, importer=iommu_domain"의 3단계 절충안을 제시하였으나, 2026년 5월 11일 이후 논의가 정체되어 있다.

결과적으로 ③ 단계는 "설계가 반대로 폐기된" 것이 아니라 절충안이 도출된 채 합의에 이르지 못하고 정체된 상태이다. 또한 CUDA/NVIDIA를 명시적으로 다룬 시리즈는 존재하지 않는다. 현재의 기반 기술들은 guest_memfd/vGPU(PFNMAP) 시나리오를 겨냥하며, CUDA exporter는 어느 설계가 채택되든 그 범용 메커니즘 위에 구현되는 형태가 될 것으로 전망된다.

## 6. 결론 및 제언

**결론.** iommufd는 v6.19에서 디바이스 메모리 dma-buf 매핑을 도입하여 "회계와 수명주기를 갖춘 owner-integrated 매핑"이라는 개념을 확보하였으나, 지원 대상이 VFIO PCI dma-buf 한 구간으로 고정되어 있어 본 팀이 사용하는 CUDA/GPU dma-buf는 아직 매핑되지 않는다. 이를 일반화할 두 설계(PAL, mm memory provider)는 모두 미머지이며 방향 또한 미정이다. 따라서 현재 `iommu_map_pa` 워크어라운드는 대체가 불가하며, 대체 시점은 커뮤니티 합의에 의존하여 예측이 어렵다.

**리스크.** 워크어라운드는 VFIO/iommufd의 회계, 수명주기, 락, dirty tracking을 우회하므로, 도메인 교체, IOVA 충돌 시 오매핑, use-after-free 위험이 상존한다. 업스트림 API가 등장하면 제거해야 할 기술 부채이다. 다만 §1.3에서 확인하였듯 현재 용도는 실험 및 검증 단계로, 프로덕션 의존은 없다.

**제언.**

- **당분간 유지.** 대체 API가 근시일 내 등장한다고 보기 어려우므로, 워크어라운드를 유지하되 README의 안전 제약 목록을 운영 절차에 명시한다.
- **동향 재점검.** ③ 단계의 두 진영(PAL vs mm memory provider) 중 채택 방향을 분기마다 재점검한다. PAL은 master, for-next, next 어디에도 없으므로, 먼저 for-next 진입 여부가 유의미한 신호이다.
- **(선택) 선제 대응.** PAL 경로가 유력해지면 upcie에 PAL exporter 프로토타입을 구현하여 마이그레이션을 사전 검증한다. 매핑이 `IOMMU_MMIO`로 수행되는 등 의미가 자체 모듈과 동일하므로 전환 비용은 크지 않을 것으로 판단된다.

## 부록 A. 근거 자료

| 구분 | 커밋 / msgid |
| --- | --- |
| v6.13 | `f4986a72d6e4` |
| v6.19 | `44ebaa1744fd`, `71db84a092c3`, `96ce2aeb15bd`, `3114c674401e`, `3aa31a8bb11e` |
| v7.1 | `8c5f9645c389`, `be6d4c9e9d71`, `6ffe939bf94f`, `95308225e5ba` |
| v7.1–7.3 | `298ab7e6f163`, `5f3fc0ad9a41`, `60decab325a4` |
| 미머지 (jgg) | RFC 00/26 `0-v1-b5cab63049c0+191af-dmabuf_map_type_jgg@nvidia.com` |
| 미머지 (Griffoul) | RFC 0/9 `20261006183235.16576-1-griffoul@gmail.com` |
| 미머지 (Woodhouse) | RFC v2 00/11 `20260720111259.122911-1-dwmw2@infradead.org` |
| 본 팀 코드 | `upcie/experimental/iommu_map_pa/{README.md, module/iommu_map_pa.c}`, `upcie/tests/test_dmamem_cuda_iommu_map_pa_nvme_readwrite.c` |

## 부록 B. 방법과 한계

- 릴리스, 커밋, UAPI 문구 등 사실 관계는 1차 소스로 확인하였다. 머지된 패치는 `torvalds/linux` 커밋과 태그별 소스 검사로, 미머지 패치는 `lore.kernel.org` linux-iommu 메일링리스트(public-inbox 검색 API / `lei`)로 확인하였다(lore 웹 검색은 봇 차단으로 API를 경유).
- 릴리스 귀속은 태그별 소스 검사로 재확인하였다(dmabuf-revoke/pin = v7.1, `phys_vec` = v6.19, `NOIOMMU_GET_PA` = v7.3 신규).
- 본문에서 릴리스, 커밋, UAPI 문구는 사실로, 장래 방향(예: CUDA exporter가 특정 설계 위에 구현될 것이라는 판단)은 "전망된다"로 표기한 추정으로 구분하였다.
- 미머지 시리즈는 이후 리비전이 진행될 수 있으며, 인용 내용은 2026년 10월 시점 기준이다.
