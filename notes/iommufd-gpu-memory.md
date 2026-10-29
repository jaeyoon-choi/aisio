# iommufd의 GPU 메모리 DMA 매핑 지원 현황

이 문서는 업스트림의 최신 패치를 주기적으로 확인해 갱신할 예정이다. 영문판은 [iommufd-gpu-memory.en.md](iommufd-gpu-memory.en.md)다.

- 작성일: 2026-10-13, 개정일: 2026-10-29
- 기준 트리: Linux mainline v7.3 (2026-10-18)과 v7.4 머지 윈도 진행분(c339f4010dea, 2026-10-28), iommufd for-next (04bcf8461334), linux-next 20261028
- 메일링리스트: dri-devel, linux-mm, iommu, kvm, io-uring, linux-nvme, linux-block, linux-pci 아카이브의 2026-10-28 23시(UTC)까지 메일
- 관련 코드: upcie-experimental 0.9.0 (`iommu_map_pa`, `dmabuf_import`, 최신 릴리스는 0.10.4), NVIDIA 드라이버 580.178.04 (측정 서버 버전, 최신 릴리스는 615.78.08)

## 요약

NVMe가 CUDA로 할당한 GPU VRAM에 직접 DMA하려면, 그 VRAM의 물리주소(GPU BAR1 주소)를 NVMe의 IOMMU 페이지 테이블에 매핑해야 한다. 지금은 upcie의 커널 모듈 `iommu_map_pa`가 iommufd를 거치지 않고 이 매핑을 직접 만든다. 이 보고서는 업스트림 iommufd의 `IOMMU_IOAS_MAP_FILE`이 CUDA dma-buf를 받아 이 매핑을 만들 수 있는지, 즉 `iommu_map_pa`를 없앨 수 있는지를 2026-10-29 기준으로 정리한다.

현재 업스트림 iommufd는 NVIDIA dma-buf를 매핑하지 못하므로 `iommu_map_pa`를 당분간 유지해야 한다. iommufd는 v6.19부터 `IOMMU_IOAS_MAP_FILE`로 dma-buf를 받지만, 물리주소를 vfio-pci의 전용 함수 `vfio_pci_dma_buf_iommufd_map()`에서만 얻기 때문에 vfio-pci가 내보낸 단일 구간 dma-buf만 매핑한다. Xeon Ice Lake-SP 2소켓과 NVIDIA L4를 갖춘 측정 서버에서, 수정하지 않은 배포판 커널(7.0.0-34-generic)에 NVIDIA dma-buf를 넣으면 `errno=95`(`EOPNOTSUPP`)로 거부되었다.

NVIDIA 같은 다른 exporter의 dma-buf도 받게 하려는 작업은 Linux 커널 메일링리스트에 올라온 패치 시리즈로 진행 중이며, 아직 머지된 것은 없다. NVIDIA의 Jason Gunthorpe(iommufd 메인테이너)가 2026-02-18에 RFC로 올린 dma-buf mapping types 시리즈는 dma-buf에 주소 교환 형식(mapping type)을 협상하는 체계를 넣는다. 같은 NVIDIA의 Alistair Popple이 2026-10-26에 이 시리즈를 처음 정식 패치로 다시 올렸다. 다만 이 패치에서는 물리주소 목록 type(PAL)과 iommufd 연결이 빠졌고, iommufd 연결은 이후 "iommufd importer type"으로 따로 올라올 예정이다.

Amazon의 Fred Griffoul은 2026-10-06에 dma-buf를 거치지 않고 mm에 같은 규약을 두는 mm memory provider 시리즈를 RFC로 올렸다. 그러나 2026-10-27에 올린 후속 RFC에서는 mm 인터페이스를 빼고 VM 메모리(guest_memfd)만 iommufd로 매핑하는 방향으로 바꿨다. 따라서 NVIDIA 같은 VM 밖의 드라이버에 해당하는 경로로 게시된 것은 mapping types 시리즈만 남았다(추정). NVIDIA용 전용 연결을 하나 더 두는 방법은 iommufd 메인테이너가 거부했으므로 채택될 가능성이 낮다(추정). 시리즈의 목록과 경과는 §5에 있다.

iommufd 밖에서는 2026-10-27에 io_uring의 dma-buf 지원이 v7.4 머지 윈도에 들어가, NVMe를 커널 드라이버로 구동하면 dma-buf로 GPU 메모리에 직접 DMA할 수 있게 되었다. 이 경로는 vfio 기반 사용자 공간 드라이버에는 해당하지 않으며, NVIDIA dma-buf로 동작하는지는 확인하지 못했다. 같은 dma-buf를 NVMe passthrough 명령(`io_uring_cmd`)에도 쓰게 하는 Anuj Gupta(Samsung)의 [시리즈](https://lore.kernel.org/all/20261022144501.2478417-1-anuj1072538@gmail.com/)가 리뷰 중이다. 이 시리즈가 머지되고 xNVMe가 dma-buf 고정 버퍼 등록을 지원하면, aisio의 커널 경로에서 xNVMe가 NVMe 명령 단위로 GPU 메모리에 P2P DMA할 수 있을 것으로 추정한다(§3).

| 항목 | 상태 | 근거 |
| --- | --- | --- |
| [iommufd의 dma-buf 매핑](#4-제약-요인) | VFIO PCI dma-buf의 단일 MMIO 구간만 | UAPI 주석([298ab7e6f163](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=298ab7e6f163)), [`pages.c`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/iommu/iommufd/pages.c?h=v7.3) |
| [NVIDIA dma-buf](#4-제약-요인) | 거부(`-EOPNOTSUPP`) | [`vfio_pci_dmabuf.c`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/vfio/pci/vfio_pci_dmabuf.c?h=v7.3)의 exporter 검사, 측정 서버 실측 `errno=95`([PoC 보고서 §6.2](https://github.com/jaeyoon-choi/aisio/blob/poc/iommufd-pal/notes/pal-poc/REPORT.md#62-단계별-결과)) |
| [일반 exporter 개방](#51-시리즈-목록) | 머지되지 않음 | [v7.4 머지 윈도](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/log/?id=c339f4010dea), [iommufd for-next](https://git.kernel.org/pub/scm/linux/kernel/git/jgg/iommufd.git/log/?id=04bcf8461334), [linux-next 20261028](https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tag/?h=next-20261028)에 관련 심볼(`dma_buf_mapping_match`, PAL, provider) 없음 |
| [PAL type](#52-dma-buf-mapping-types와-pal) | [정식 시리즈](https://lore.kernel.org/all/20261026053623.202642-1-apopple@nvidia.com/)(2026-10-26)에서 제외 | iommufd 연결은 [4월 절충안](https://lore.kernel.org/all/20260422150000.GK3199414@nvidia.com/)을 따르는 importer type으로 미룸(§5.2) |
| [mm provider](#53-mm-memory-provider와-guest_memfd-export) | 중단. guest_memfd export로 대체 | [후속 RFC](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/) 표지 메일 "this series drops the mm interface" |
| [io_uring dma-buf (iommufd 밖)](#3-머지된-패치) | v7.4 머지 윈도에 머지 | [ed02f4f7ad9b](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=ed02f4f7ad9b). passthrough 확장은 [리뷰 중](https://lore.kernel.org/all/20261022144501.2478417-1-anuj1072538@gmail.com/) |
| [NVIDIA 전용 연결](#55-nvidia-드라이버에-미치는-영향) | 가능성 낮음(추정) | iommufd 메인테이너의 [2026-10-01](https://lore.kernel.org/all/20261001171501.GD3019323@ziepe.ca/), [2026-10-12](https://lore.kernel.org/all/20261012144616.GF14213@ziepe.ca/) 메일 |

어느 설계가 채택되든 iommufd는 `iommu_map_pa`와 마찬가지로 BAR1 물리주소를 `IOMMU_MMIO`로 등록한다. PoC에서 PAL 경로는 측정 서버의 NVMe 한 대, 큐 하나, 순차 I/O 조건에서 호스트 메모리 대상과 같은 처리량을 냈다.

업스트림이 정해질 때까지는 `iommu_map_pa`를 계속 쓰고, §6의 지켜볼 신호를 분기마다 확인한다. 확인하지 못한 항목(CUDA 할당에 BAR1을 가리키는 CPU 매핑이 없는지, CUDA를 다룬 업스트림 시리즈가 정말 없는지 등)과 그 다음 단계는 §7에 있다.

## 1. 문제와 현행 우회 경로

LLM 추론의 KV 캐시 오프로딩, 모델 로딩, 체크포인팅처럼 GPU 메모리와 저장장치 사이에서 큰 데이터를 옮길 때는, 호스트 RAM을 거치지 않고 NVMe가 GPU VRAM으로 직접 DMA(P2P)하는 편이 대역폭과 CPU 부하에서 유리하다. vfio로 NVMe를 사용자 공간에서 구동하면, IOMMU가 NVMe의 DMA 주소를 번역한다. 이때 NVMe가 DMA에 쓰는 주소는 물리주소가 아니라 IOVA(I/O 가상주소)이고, IOMMU는 NVMe에 할당된 페이지 테이블에서 이 IOVA에 대응하는 물리주소를 찾는다. 따라서 NVMe가 GPU VRAM에 DMA하려면, GPU가 VRAM을 노출하는 BAR1 창의 물리주소가 이 페이지 테이블에 매핑되어 있어야 한다.

VFIO와 iommufd의 매핑 API는 호스트 가상주소(VA)나 파일(fd)만 받는다. CUDA 할당에는 BAR1을 가리키는 CPU 매핑(VMA)이 없으므로(일반론에 따른 추정) VA 경로를 쓸 수 없고, fd 경로는 NVIDIA dma-buf를 거부한다(§4). 두 경로를 모두 쓸 수 없으므로 upcie의 [iommu_map_pa](https://github.com/safl/upcie/tree/v0.9.0/experimental/iommu_map_pa) 모듈이 이 일을 직접 한다. 이 모듈은 vfio-pci 장치의 현재 도메인을 `iommu_get_domain_for_dev()`로 얻고, `dmabuf_import`로 얻은 BAR1 물리주소를 `iommu_map(..., IOMMU_MMIO)`로 그 도메인에 넣는다. 이 모듈은 DKMS 패키지 `upcie-experimental-dkms`로 배포되고, upcie의 `dmamem_from_cuda_iommu_map_pa()`가 이 모듈을 부른다. 이 모듈은 iommufd의 IOVA 회계, 수명주기, 락, dirty tracking을 우회하므로 상용 환경에서 안전하게 쓸 수 없다. 장기적으로는 `IOMMU_IOAS_MAP_FILE`이 CUDA dma-buf를 직접 받아 이 모듈을 대체하는 것이 목표다.

이 보고서는 지원 수준을 다음 네 단계로 나누어 업스트림 진척을 정리한다.

| 단계 | 상태 | 내용 |
| --- | --- | --- |
| ① 파일 매핑 | 머지됨 (v6.13) | `IOMMU_IOAS_MAP_FILE`로 memfd 매핑 |
| ② 디바이스 메모리 | 머지됨 (v6.19) | 같은 ioctl로 dma-buf(MMIO) 매핑. vfio-pci dma-buf 한정 |
| ③ 일반 exporter 개방 | 머지되지 않음 | 어느 드라이버의 dma-buf(또는 provider 파일)든 매핑 |
| ④ NVIDIA exporter | 시리즈 없음 | NVIDIA 드라이버가 ③의 규약을 구현 |

## 2. 매핑 API와 용어

이후의 절을 읽으려면 dma-buf의 용어와, GPU 메모리를 IOMMU에 넣을 수 있는 매핑 API의 차이를 알아야 한다.

| 용어 | 뜻 |
| --- | --- |
| dma-buf | 버퍼를 소유한 드라이버(exporter)가 fd로 내보내고 다른 드라이버(importer)가 attach해 매핑하는 커널의 버퍼 공유 프레임워크 |
| scatterlist | dma-buf의 전통적 주소 형식. `dma_addr_t` 목록이라 DMA API를 쓰지 않는 importer(iommufd)에는 맞지 않는다 |
| `phys_vec` | 물리주소 한 구간(`paddr`, `len`)을 나타내는 커널 구조체 |
| `IOMMU_MMIO` | IOMMU 페이지 테이블 엔트리에 장치 메모리(캐시하지 않음) 속성을 주는 플래그. iommufd는 MMIO PFN을 `BATCH_MMIO` 묶음으로 모아 이 플래그로 매핑한다 |
| IOAS, `iommu_domain` | iommufd의 IO 주소 공간 객체와, 실제 페이지 테이블을 가진 IOMMU 계층 객체 |
| revoke, pin | exporter가 매핑을 회수하는 것(`dma_buf_invalidate_mappings()`), importer가 버퍼 이동을 막는 것(`dma_buf_pin()`) |

| API | 입력 | 일반 RAM | 장치 BAR mmap (PFNMAP) | dma-buf |
| --- | --- | --- | --- | --- |
| `VFIO_IOMMU_MAP_DMA` (type1) | 호스트 VA | pin | pin 없이 매핑(수명 보장 없음) | 받지 않음 |
| `IOMMU_IOAS_MAP` | 호스트 VA | pin | 받지 않음 | 받지 않음 |
| `IOMMU_IOAS_MAP_FILE` + memfd | fd | pin | 해당 없음 | 해당 없음 |
| `IOMMU_IOAS_MAP_FILE` + dma-buf | fd | 해당 없음 | 해당 없음 | vfio-pci 단일 구간만, revoke 콜백 |

type1은 PFNMAP VMA를 `follow_fault_pfn()`으로 pin 없이 매핑하지만 수명을 보장하지 못하므로, iommufd는 이 경로 대신 dma-buf 경로를 만들었다. CUDA 할당은 어느 VA 경로로도 매핑할 수 없다고 추정하므로 dma-buf 경로만 남고, 이 경로가 NVIDIA dma-buf를 받는지는 §4에서 다룬다. 어느 경로든 BAR1 물리주소를 `IOMMU_MMIO`로 넣는다는 점은 같다. iommufd도 `BATCH_MMIO`로 모은 뒤 `IOMMU_MMIO`를 붙여 `iommu_map()`을 부르며(`pages.c`, v7.3), PAL RFC와 mm provider RFC v2도 패치 기준으로 MMIO 페이지를 `IOMMU_MMIO`로 넣는다. 차이는 누가 물리주소를 확인하고 수명을 책임지는가에 있다.

## 3. 머지된 패치

iommufd의 dma-buf 지원은 v6.13부터 v7.4 머지 윈도까지 이어진 변경으로 지금 모양이 되었다. v6.19의 dma-buf 지원은 Gunthorpe와 Romanovsky(NVIDIA)의 시리즈([v1](https://lore.kernel.org/all/0-v1-64bed2430cdb+31b-iommufd_dmabuf_jgg@nvidia.com/) 2025-10-27, [v2](https://lore.kernel.org/all/0-v2-b2c110338e3f+5c2-iommufd_dmabuf_jgg@nvidia.com/) 2025-11-21)로 들어왔다. 표의 저자는 각 커밋의 Author이고, 괄호 안의 소속은 저자 이메일이나 Signed-off-by 주소의 도메인으로 추정했다.

| 릴리스 | 커밋 | 저자 | 내용 |
| --- | --- | --- | --- |
| v6.13 (2025-01-19) | [f4986a72d6e4](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f4986a72d6e4) | Steve Sistare (Oracle) | `IOMMU_IOAS_MAP_FILE` 추가. memfd를 `memfd_pin_folios()`로 pin해 매핑한다. 매핑 입력이 파일이 되면서 이후 dma-buf를 같은 ioctl로 받을 자리가 생겼다 |
| v6.19 (2026-02-08) | [3aa31a8bb11e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=3aa31a8bb11e) | Leon Romanovsky (NVIDIA) | BAR의 MMIO 구간 배열을 scatterlist로 바꾸는 dma-buf 공용 함수 |
|  | [5d74781ebc86](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=5d74781ebc86) | Leon Romanovsky (NVIDIA) | vfio-pci가 BAR의 MMIO 구간을 dma-buf로 내보내는 exporter 본체 |
|  | [35c3503908d3](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=35c3503908d3) | Leon Romanovsky (NVIDIA) | 모든 vfio-pci 장치의 P2P를 기본으로 켜서 BAR를 dma-buf로 내보낼 수 있게 함 |
|  | [96ce2aeb15bd](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=96ce2aeb15bd) | Jason Gunthorpe (NVIDIA) | vfio-pci exporter와 iommufd 사이의 전용 함수 `vfio_pci_dma_buf_iommufd_map()`. 커밋 메시지는 이를 임시 API로 부르고, 일반 exporter 지원에 필요한 것으로 revoke 의미(iommufd 쪽은 v6.19의 fc7063abd98e, vfio 쪽은 v7.1), 물리주소 협상(§5.2에서 진행 중), DMA 장치가 없는 importer의 attach를 든다. attach는 지금 iommufd misc 장치로 우회한다 |
|  | [3114c674401e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=3114c674401e) | Jason Gunthorpe (NVIDIA) | iommufd가 MMIO PFN 묶음을 `IOMMU_MMIO`로 매핑 |
|  | [74014a4b55f5](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=74014a4b55f5) | Jason Gunthorpe (NVIDIA) | iommufd의 pfn_reader가 dma-buf `iopt_pages`를 처리 |
|  | [fc7063abd98e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=fc7063abd98e) | Jason Gunthorpe (NVIDIA) | iommufd가 dma-buf revoke를 받아 매핑을 지움 |
|  | [71db84a092c3](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=71db84a092c3) | Jason Gunthorpe (NVIDIA) | `iopt_pages`에 dma-buf 종류 추가. 커밋 메시지는 "for now can only be used with the VFIO DMABUF exporter"라고 적는다. pin 회계와 커널 CPU 접근은 지원하지 않음 |
|  | [44ebaa1744fd](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=44ebaa1744fd) | Jason Gunthorpe (NVIDIA) | `IOMMU_IOAS_MAP_FILE`이 dma-buf fd를 받아 사용자 공간에 기능을 공개 |
|  | [5415d887db0e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=5415d887db0e) | Jason Gunthorpe (NVIDIA) | nvgrace-gpu vfio variant 드라이버의 GPU 메모리 export. GPU를 vfio에 바인딩해야 하므로 CUDA와 함께 쓸 수 없음 |
| v7.1 (2026-06-14) | [ef246da8e63c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=ef246da8e63c), [95308225e5ba](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=95308225e5ba) | Leon Romanovsky (NVIDIA) | `move_notify`를 `invalidate_mappings`로 이름 변경 |
|  | [575157b1b5fc](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=575157b1b5fc), [1a8a5227f229](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=1a8a5227f229) | Leon Romanovsky (NVIDIA) | `invalidate_mappings`를 선택 사항으로 만들고, vfio가 dma-buf invalidation 완료를 기다림 |
|  | [be6d4c9e9d71](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=be6d4c9e9d71) | Leon Romanovsky (NVIDIA) | `dma_buf_attach_revocable()`. exporter가 동기적으로 접근을 회수하고 importer는 회수 뒤 메모리를 건드리지 않는다는 계약을 확인 |
|  | [6ffe939bf94f](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=6ffe939bf94f) | Leon Romanovsky (NVIDIA) | 이 계약을 지키는 pinned importer를 vfio가 받음. iommufd 전용 인터페이스 제거에 필요한 두 항목(revoke 계약, 물리주소 목록) 중 하나 |
|  | [8c5f9645c389](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=8c5f9645c389) | Leon Romanovsky (NVIDIA) | iommufd가 일반 `dma_buf_pin()`을 부름. 나머지 한 항목(물리주소 목록)은 "another series"로 미룸(§5.2) |
| v7.2 (2026-08-16) | [298ab7e6f163](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=298ab7e6f163) | Alex Mastro (Meta) | UAPI 주석 정정. "This is not a generic dma-buf import path; currently supported dma-bufs include single-range VFIO PCI dma-bufs" |
|  | [5f3fc0ad9a41](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=5f3fc0ad9a41) | Peiyang He (난징대) | dma-buf `iopt_pages`가 커널 access pin 경로에 들어가 사용자 주소로 잘못 해석되던 문제 차단 |
|  | [e745cd2c749e](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=e745cd2c749e) | Ankit Soni (AMD) | 해제 경로에서 `dma_buf_unpin()`을 `dma_resv` 락 안에서 부름(selftest 경고로 발견). PoC 커널에는 없음 |
|  | [f2d70dbd3dce](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=f2d70dbd3dce) | Jason Gunthorpe (NVIDIA) | dma-buf detach가 끝난 뒤에 pages 내용을 정리(커널 메일링리스트의 AI 리뷰 봇 Sashiko의 지적). PoC 커널에는 없음 |
| v7.3 (2026-10-18) | [b344ca94e8cc](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=b344ca94e8cc), [06dd5e1ae8ce](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=06dd5e1ae8ce) | David Hu (Google) | `dma_buf_phys_vec_to_sgt()`의 길이 overflow 수정과 sgl 분할 변경. vfio-pci와 RDMA exporter가 SGT를 만들 때 쓰는 헬퍼이며 iommufd 경로는 쓰지 않음 |
| v7.4 머지 윈도 (c339f4010dea 기준) | [769f2cd9226c](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=769f2cd9226c) | Andrea Parri | 도메인을 나중에 붙이거나 영역을 복사할 때도 dma-buf PFN을 `IOMMU_MMIO`로 매핑. 도메인 하나에 한 번 매핑하는 `iommu_map_pa`와 PoC의 사용 방식은 해당하지 않음 |
|  | [0d3120db2cbe](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=0d3120db2cbe) | Pavel Begunkov | dma-buf 파일 I/O 기반(`dma_buf_io_ctx`, `dma_buf_io_map`). iommufd와 무관한 io_uring 경로 |
|  | [ce5e386c1108](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=ce5e386c1108) | Pavel Begunkov | 커널 nvme-pci 드라이버가 dma-buf를 dynamic importer(`allow_peer2peer`)로 받아 그 DMA 주소로 명령을 만듦 |
|  | [839231d19393](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=839231d19393) | Pavel Begunkov | raw 블록 장치에서 dma-buf I/O 지원. O_DIRECT만 허용 |
|  | [d5c8cfd41d25](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=d5c8cfd41d25) | Anuj Gupta (Samsung) | nvme-pci의 dma-buf 경로에 SGL 지원 |
|  | [62e4bf5b25d4](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=62e4bf5b25d4) | Pavel Begunkov | io_uring이 dma-buf fd를 블록 장치용 고정 버퍼로 등록. `IORING_OP_READ_FIXED`, `WRITE_FIXED`로 사용 |
|  | [bcbd808652e1](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=bcbd808652e1) | Keith Busch | 4 GiB 이상인 dma-buf 거부 (bvec 오프셋이 32비트) |

v6.19에서 iommufd는 회계와 수명주기를 갖춘 dma-buf 매핑을 갖게 되었고, v7.1에서 revoke와 pin 흐름이 일반 dma-buf 방식으로 정리되었다. 남은 전용 부분은 물리주소 목록을 얻는 vfio-pci 함수 하나이고, `pages.c`의 주석도 이 연결을 "Future work for a phys based private interconnect will remove this"라고 적는다. v7.3과 v7.4 머지 윈도는 iommufd가 받는 dma-buf의 범위를 넓히지 않았다. v7.3의 dma-buf 수정 두 건은 vfio-pci와 RDMA exporter가 쓰는 SGT 헬퍼를 고친 것이다. PoC가 쓴 PAL 브랜치는 v7.1의 변경까지 포함하고, v7.2의 해제 경로 수정 두 건은 포함하지 않는다.

iommufd 밖에서는 2026-10-27에 io_uring의 dma-buf 지원(머지 커밋 [ed02f4f7ad9b](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=ed02f4f7ad9b))이 v7.4 머지 윈도에 들어갔다. 사용자 공간이 dma-buf fd와 NVMe 블록 장치를 io_uring에 등록하면, 커널 nvme-pci 드라이버가 그 dma-buf에 attach하고 exporter가 돌려준 DMA 주소로 직접 읽고 쓴다. NVMe의 IOMMU 매핑은 exporter가 NVMe 장치를 대상으로 DMA API를 불러 만들므로, 이 경로에는 vfio, iommufd, `iommu_map_pa`가 모두 필요 없다. 대신 NVMe를 커널 드라이버로 구동해야 하므로 vfio 기반 사용자 공간 드라이버에는 해당하지 않는다. dma-buf 하나는 4 GiB 미만이어야 하고, raw 블록 장치에 O_DIRECT로만 쓸 수 있으며, integrity checksum(PI)을 쓰는 장치에서는 거부된다(`block/fops.c`). PI 제한을 완화하는 [패치](https://lore.kernel.org/all/20261028181412.1919506-1-kbader@redhat.com/)(2026-10-28)와 파일 시스템(xfs, iomap)으로 넓히는 [RFC](https://lore.kernel.org/all/20261016091919.971295-1-anuj1072538@gmail.com/)(2026-10-16)가 올라와 있다. NVIDIA dma-buf가 이 경로에서 동작하는지는 확인하지 못했다. NVIDIA 드라이버에는 IOMMU가 켜진 환경에서 importer에 DMA 주소 대신 BAR1 물리주소를 돌려준다는 보고([Issue #1324](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1324), 2026-08-27, 드라이버 595.84, 답 없음)가 있으므로, IOMMU를 켠 환경에서는 동작하지 않을 수 있다(추정). 같은 날 KylinOS의 Li Wang이 올린 fgds RFC v2(커널 misc 드라이버로 GPU dma-buf와 파일 사이의 direct I/O를 하는 시리즈)에 König은 이 io_uring 작업을 들어 NAK했고([메일](https://lore.kernel.org/all/fa64ae97-72a0-4c0f-9988-18500936a8a8@amd.com/)), 저자는 Pavel Begunkov에게 자기 방식의 이유를 설명하고 커뮤니티의 진행을 지켜보겠다고 답했다.

Anuj Gupta(Samsung)의 [dma-buf backed NVMe passthrough 시리즈](https://lore.kernel.org/all/20261022144501.2478417-1-anuj1072538@gmail.com/)(v2 5편, 2026-10-22)는 같은 dma-buf 고정 버퍼를 NVMe 문자 장치(`/dev/ngXnY`)의 `io_uring_cmd` passthrough 명령에도 쓰게 한다. 머지된 경로가 블록 계층의 읽기와 쓰기만 다루는 것과 달리, passthrough에서는 사용자 공간이 만든 NVMe 명령이 그대로 장치로 간다. Christoph Hellwig가 2026-10-28에 block과 nvme 패치(4/5, 5/5)에 Reviewed-by를 주었고, 머지되지는 않았다.

이 두 작업은 aisio에 영향이 크다고 판단한다(추정). aisio의 구조 문서(`docs/src/architecture.md`)는 커널 nvme 드라이버와 io_uring, dma-buf를 쓰는 CPU 주도 P2P 경로를 세 구조 가운데 하나로 둔다. v7.4의 머지로 이 경로의 블록 읽기와 쓰기는 패치 없는 업스트림 커널에서 가능해진다. passthrough 시리즈까지 머지되면 xNVMe의 `io_uring_cmd` 백엔드가 uPCIe 백엔드와 같은 NVMe 명령 단위로 GPU 메모리에 P2P DMA할 수 있으므로, aisio가 강조하는 구성(같은 xNVMe API로 커널 경로와 사용자 공간 경로를 바꿔 쓰는 구성)을 업스트림 커널만으로 갖출 수 있다. 그러려면 xNVMe 쪽에도 작업이 필요하다. 로컬 xNVMe(2026-09-22)의 io_uring 백엔드는 io_uring 고정 버퍼를 등록하지 않으며(`register_buffers` 옵션은 있지만 백엔드가 쓰지 않음), passthrough 시리즈는 고정 버퍼를 dma-buf로 쓰겠다고 명시한 호출만 받는다. 다만 vfio와 iommufd를 쓰지 않는 경로이므로 이 문서의 주제인 `iommu_map_pa` 대체와는 별개이고, 4 GiB 미만 제한, PI 장치 거부, NVIDIA dma-buf 동작 여부라는 조건이 남는다.

## 4. 제약 요인

지금 NVIDIA dma-buf가 거부되는 곳은 iommufd가 물리주소를 얻으려고 부르는 vfio-pci 전용 함수다. `IOMMU_IOAS_MAP_FILE`에 NVIDIA dma-buf fd를 넣으면 iommufd는 dma-buf로 인식해 attach까지 진행하지만, `vfio_pci_dma_buf_iommufd_map()`이 exporter가 vfio-pci가 아니라는 이유로 `-EOPNOTSUPP`를 반환한다(v7.3 코드 기준). 구간 수 검사는 이 검사 뒤에 있으므로 구간이 하나여도 거부된다. 측정 서버의 배포판 커널(7.0.0-34-generic)에서 실측한 오류는 `errno=95`(`EOPNOTSUPP`)였다. NVIDIA 드라이버(580.178.04)의 attach가 실패했다면 `-ENOTSUPP`(524)가 나왔어야 하므로 attach 단계는 배제된다. 다만 vfio-pci 모듈이 적재되지 않아 심볼 조회가 실패해도 같은 값이 나오고, 실측은 장치를 vfio에 바인딩하기 전에 했으므로 두 경우는 실측으로 구분하지 못했다. `iommu_map_pa`는 이 검사를 모두 건너뛰므로 커널은 exporter, 구간 수, 물리주소의 유효성을 확인하지 않는다. 따라서 `iommu_map_pa`는 지금 동작하는 유일한 경로이지만 안전하지 않다.

거부 원인을 요인별로 정리하면 다음과 같다. exporter 고정이 지금 NVIDIA dma-buf를 막는 직접 요인이고, 단일 구간 조건과 규약 부재는 그 요인이 풀린 뒤에 드러나는 조건이다.

| 요인 | 내용 |
| --- | --- |
| exporter 고정 (직접 요인) | iommufd가 물리주소를 얻는 방법이 vfio-pci 심볼의 `symbol_get()` 호출로 고정되어 다른 exporter는 그 함수에서 거부된다. selftest용 훅을 빼면 다른 경로가 없고, `CONFIG_VFIO_PCI_DMABUF`가 꺼지면 이 경로도 없다 |
| 단일 구간 (후속 조건) | 현행 함수는 구간이 하나일 때만 성공한다. 실험의 1 GiB 버퍼는 구간 하나였지만, NVIDIA exporter는 핸들마다 여러 구간을 반환할 수 있다 |
| 물리주소 목록 규약 부재 (근본 조건) | iommufd에 필요한 것은 `dma_addr_t` scatterlist가 아니라 `phys_addr_t` 목록인데, dma-buf에는 그것을 교환하는 범용 규약이 없다 |

## 5. 리뷰 중인 패치

§4의 요인을 풀려는 작업은 아직 머지되지 않았고 메일링리스트에서 리뷰 중이다. 이 절에서는 그 시리즈와 관련 시리즈를 2026-10-29 기준으로 정리한다.

### 5.1 시리즈 목록

iommufd가 NVIDIA dma-buf를 받으려면, vfio-pci가 아닌 exporter의 물리주소를 iommufd에 넘기는 범용 규약이 필요하다. 이 절에서는 그 규약을 만들거나 만들려 했던 시리즈와, 규약을 만들지는 않지만 이 문서의 판단에 영향을 주는 관련 시리즈를 나누어 정리한다.

#### 범용 규약 시리즈

| 시리즈 | 제안자 | 최신 버전 (날짜) | 상태 |
| --- | --- | --- | --- |
| DMA-buf mapping types | Gunthorpe, Popple (NVIDIA) | [PATCH 00/26](https://lore.kernel.org/all/20261026053623.202642-1-apopple@nvidia.com/) (2026-10-26) | 리뷰 중, v2 예고. 기존 scatterlist를 SGT type으로 옮김. [RFC v1](https://lore.kernel.org/all/0-v1-b5cab63049c0+191af-dmabuf_map_type_jgg@nvidia.com/)(2026-02-18)의 PAL type과 iommufd 연결은 빠짐 |
| mm memory provider | Fred Griffoul (Amazon) | [RFC v2 00/11](https://lore.kernel.org/all/20261014093733.90312-1-griffoul@gmail.com/) (2026-10-14) | 중단. guest_memfd export로 대체 |
| guest_memfd export | Fred Griffoul (Amazon) | [RFC 00/14](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/) (2026-10-27) | 사람의 리뷰 없음(Sashiko AI 리뷰만 있음). VM 메모리만 다룸 |
| guest_memfd를 dma-buf로 받치기 (`get_phys()`) | Fred Griffoul | [RFC 0/6](https://lore.kernel.org/all/20261005095552.52748-1-griffoul@gmail.com/) (2026-10-05) | König NAK, 당일 철회 |
| iommufd PAL 해제 경로 수정 | Karl Mehltretter | [RFC 0/6](https://lore.kernel.org/all/cover.1792477872.git.kmehltretter@gmail.com/) (2026-10-20) | PAL 제외로 patch 1~3의 대상 코드가 없어짐, patch 4~5는 v7.2와 중복 |

mapping types 시리즈는 이 규약을 dma-buf에 만들고 있다. 2026-02의 RFC v1은 물리주소 목록 type(PAL)으로 iommufd 연결까지 넣었지만, 4월에 dma-buf 메인테이너 König이 importer가 물리주소를 받는 데 반대하자 Gunthorpe가 절충안을 냈다. 2026-10-26의 정식 패치는 PAL과 iommufd 연결을 빼고 type 협상 체계만 담았다. 10-27에는 König이 새 attach 함수에 반대했고, Popple은 리뷰에서 나온 버그를 고친 v2를 예고했다. 자세한 경과는 §5.2에 있다.

Griffoul은 같은 규약을 mm에 만들려 했다. guest_memfd를 dma-buf로 받치는 `get_phys()` RFC가 2026-10-05에 거부된 다음 날 mm memory provider RFC v1을 올렸고, 10-14에 RFC v2가 나왔으며 Gunthorpe가 iommufd 쪽 구현 조건을 제시했다. 그러나 Griffoul은 10-27의 후속 RFC에서 mm 인터페이스를 빼고 guest_memfd만 매핑하는 방향으로 바꿨다. 자세한 경과는 §5.3에 있다.

Mehltretter의 수정은 PoC 커널과 같은 PAL 브랜치에서 iommufd 해제 경로의 double-free를 고치고 fault injection selftest를 더한다. Popple은 10-21에 이 수정을 [v2에 합치겠다고](https://lore.kernel.org/all/athLCINDCSUbRHiC@nvdebian.thelocal/) 답했지만, 10-26에 올린 정식 패치(PATCH 00/26)에서 PAL이 빠져 patch 1~3이 고치던 코드가 없어졌다. Popple의 10-21 답에서 말한 "v2"가 이 10-26 게시물이다. patch 4와 5는 v7.2의 f2d70dbd3dce, e745cd2c749e와 중복이라고 [저자](https://lore.kernel.org/all/atgWXLYKOFj5cZ0F@gmail.com/)가 밝혔다.

#### 관련 시리즈

| 시리즈 | 제안자 | 최신 버전 (날짜) | 이 문서와의 관계 |
| --- | --- | --- | --- |
| guest_memfd PFNMAP provider | David Woodhouse (Amazon) | [RFC v2 00/11](https://lore.kernel.org/all/20260720111259.122911-1-dwmw2@infradead.org/) (2026-07-20) | guest_memfd 백엔드를 교체 가능하게 함. mm provider v2의 patch 1이 이 시리즈의 `kvm_gmem_ops` 패치를 기반으로 씀 |
| guest_memfd alternative providers | Ackerley Tng (Google) | [RFC v2 00/50](https://lore.kernel.org/all/20261022-gmem-alternative-providers-v2-0-5dd1dc6c660a@google.com/) (2026-10-22) | 리뷰 중. guest_memfd export RFC의 기반. RFC v1은 [2026-09-26](https://lore.kernel.org/all/20260925-gmem-tmpfs-backend-v1-0-d36159822d18@google.com/) |
| guest_memfd 장치 MMIO | Aneesh Kumar K.V (Arm) | [RFC v2 00/13](https://lore.kernel.org/all/20261017073149.1303738-1-aneesh.kumar@kernel.org/) (2026-10-17) | vfio-pci BAR를 guest_memfd provider로 VM에 연결하고, provider가 붙은 동안 dma-buf export를 막음. RFC v1은 [2026-10-10](https://lore.kernel.org/all/20261010072504.536230-1-aneesh.kumar@kernel.org/) |
| iommufd의 guest_memfd 매핑 | Alexey Kardashevskiy (AMD) | [RFC](https://lore.kernel.org/all/20260225075211.3353194-1-aik@amd.com/) (2026-02-25) | guest_memfd를 `IOMMU_IOAS_MAP_FILE`로 매핑하려던 앞선 시도. 후속 버전 없음 |
| 호스트 브리지 MMIO 창 조회 | Guanghui Feng (Alibaba) | [v6 0/3](https://lore.kernel.org/all/20261028090453.2392991-1-guanghuifeng@linux.alibaba.com/) (2026-10-28) | xNVMe가 GPU IOVA 창을 고를 때 피할 범위를 조회하고 예약 |
| P2PDMA TLP 종류별 라우팅 | Leon Romanovsky (NVIDIA) | [v11 00/19](https://lore.kernel.org/all/20261013-fix-p2p-acs-v4-0-v11-0-72cf8c96e617@nvidia.com/) (2026-10-13) | ACS와 스위치 아래의 P2P 경로 판단. Helgaas가 [rc1 이후](https://lore.kernel.org/all/20261019191845.GA2219127@bhelgaas/)로 미룸 |
| vfio-pci dma-buf mmap | Matt Evans | [v8 0/9](https://lore.kernel.org/all/20261006193643.76330-1-matt@ozlabs.org/) (2026-10-06) | vfio-pci dma-buf의 mmap과 사용자 요청 revoke. Williamson이 [리뷰](https://lore.kernel.org/all/20261013171347.54e856c7@shazbot.org/)했고 v7.4에 없음 |
| dma-buf backed NVMe passthrough | Anuj Gupta (Samsung) | [v2 0/5](https://lore.kernel.org/all/20261022144501.2478417-1-anuj1072538@gmail.com/) (2026-10-22) | aisio의 커널 경로에 영향(§3). Hellwig가 2026-10-28에 Reviewed-by |

guest_memfd 시리즈들은 VM 메모리를 iommufd로 매핑하는 기반이며, iommufd가 받는 dma-buf의 범위는 바꾸지 않는다. vfio-pci dma-buf mmap과 NVMe passthrough 시리즈도 dma-buf를 쓰는 범위를 넓히지만 iommufd의 제약은 바꾸지 않는다.

호스트 브리지 MMIO 창 조회와 P2PDMA 시리즈는 PCIe 스위치 아래의 P2P 경로를 다룬다. 스위치의 ACS Upstream Forwarding이 꺼져 있으면, 스위치 아래 장치가 호스트 브리지 MMIO 창과 겹치는 IOVA로 DMA할 때 스위치가 그 요청을 IOMMU로 올려 보내지 않고 다른 장치로 보낼 수 있다. Guanghui의 시리즈는 사용자 공간이 그런 IOVA 범위를 조회하고(`IOMMU_GET_RECOMMENDED_RESERVATIONS`) IOAS 할당기에서 제외하게(`IOMMU_IOAS_RESERVE_IOVAS`) 한다. v5에서 Gunthorpe의 v4 리뷰(2026-10-27)를 반영해 ioctl 이름을 바꾸고 예약 ioctl을 더했고, 같은 날 v6에서 Sashiko 지적 두 건을 고쳤다. Romanovsky의 P2PDMA 시리즈는 같은 문제를 커널의 P2P 경로 판단에서 다룬다.

### 5.2 dma-buf mapping types와 PAL

iommufd 메인테이너 Jason Gunthorpe(NVIDIA)의 RFC v1은 dma-buf에 mapping type을 넣어 importer와 exporter가 주소 형식을 협상하게 하고, `phys_vec` 배열을 넘기는 PAL(Physical Address List) type을 추가했다. PAL importer로는 iommufd만 허용되고 exporter는 어느 드라이버든 구현할 수 있으며, Gunthorpe는 그 이유로 "there are use cases in DPDK/SPDK to connect GPU memory into VFIO/iommufd"라고 적었다. 이 RFC는 §4의 세 요인을 모두 해소한다. PAL type이 물리주소 목록을 교환하는 범용 규약이 되어 규약 부재를 풀고, patch 23과 24가 iommufd의 vfio-pci 전용 호출을 PAL로 바꿔 exporter 고정을 없애며, 같은 patch가 다중 구간을 지원해 단일 구간 조건을 없앤다. PoC는 이 RFC의 브랜치(c37cf2824740) 위에서 NVIDIA exporter를 이식해 측정 서버에서 양방향 P2P DMA를 확인했다.

dma-buf 메인테이너 Christian König(AMD)은 importer가 물리주소를 직접 받는 데 반대했고, Gunthorpe는 exporter가 물리주소를 내고 importer가 `iommu_domain`을 내면 둘을 모두 가진 dma-buf core만 매핑을 수행하는 절충안을 냈다(원문: "The exporter provides the address data, the importer provides the iommu_domain. The core code, and only the core code, has both and does the required operation?"). 10월에는 type을 정하는 시점이 쟁점이 되었고, 정식 패치는 Intel의 Thomas Hellström이 제안한 계약(attach 때 후보를 합의하고, 첫 pin 또는 map 때 고르고, invalidate까지 유지)을 따랐다. 정식 패치는 PAL type을 빼고 iommufd 연결을 절충안에 따른 "iommufd importer type"으로 미뤘다. AI 리뷰 봇 Sashiko는 정식 패치의 vfio-pci 변환이 iommufd의 현행 vfio dma-buf 매핑을 attach 단계에서 깨뜨릴 수 있다고 지적했고([메일](https://lore.kernel.org/all/sashiko-outbox-184718@kernel.org/)), 이 지적에는 10월 29일 현재 답이 없다. Sashiko가 지적한 다른 문제(map이 실패하면 앞선 pin이 고른 type까지 지워지는 문제)는 Mehltretter가 KUnit 시험으로 재현했고, Popple은 이를 v2에서 고치겠다고 답했다. 같은 날 König은 정식 시리즈가 새로 둔 attach 함수(`dma_buf_mapping_attach()`, `dma_buf_sgt_attach()`)를 NO-GO라고 하고, type 협상을 기존 `dma_buf_dynamic_attach()`의 importer ops 안에서 하라고 요구했다([메일](https://lore.kernel.org/all/43a20d60-89a9-48fc-af73-5907b35a54d7@amd.com/)). Gunthorpe는 SGT만 쓰는 호출처를 드러내는 도우미 함수가 낫다고 반박했으므로, v2에서는 API 이름과 형태가 바뀔 수 있다.

#### PAL과 iommufd importer type의 차이

두 방식의 차이는 exporter가 낸 물리주소를 받아 IOMMU에 넣는 주체에 있다.

| 항목 | PAL (RFC v1, 2026-02) | iommufd importer type (4월 절충안, 게시되지 않음) |
| --- | --- | --- |
| exporter(NVIDIA)가 내는 것 | BAR1 물리주소 목록(`phys_vec`) | BAR1 물리주소 목록 (PAL과 같음) |
| 물리주소를 받는 쪽 | importer인 iommufd | dma-buf core |
| IOMMU 매핑을 하는 쪽 | iommufd가 받은 주소로 직접 `iommu_map()`을 부름 | iommufd는 `iommu_domain`만 넘기고, dma-buf core가 그 도메인에 매핑 |
| importer가 물리주소를 보는가 | 봄 | 보지 않음 |

König은 importer가 물리주소를 직접 받는 구조에 반대했다. 2026-10-27에도 König은 "Sharing page/physical to be used with the IOMMU functions through DMA-buf is an absolutely hard NAK"라고 쓰면서, KVM, IOMMUFD, virtio 세 곳에만 허용하는 방법은 아직 정해야 한다고 덧붙였다([메일](https://lore.kernel.org/all/2be3338a-5657-4312-869d-3bb1d386f9fc@amd.com/)). 이 메일은 Tegra DRM이 dma-buf의 SGT를 자기 `iommu_domain`에 매핑해 fault가 난다는 Mehltretter의 보고에 대한 답이었고, 같은 스레드에서 Gunthorpe도 "you cannot connect dmabuf to an iommu_domain"이라고 썼다([메일](https://lore.kernel.org/all/20261027123308.GC1671235@nvidia.com/)). 이 발언은 드라이버가 SGT를 직접 IOMMU에 넣는 사용을 가리키며, core가 매핑하는 importer type 구상과는 다른 이야기다(추정). 따라서 iommufd는 예외로 허용될 대상에 들어 있지만, 그 방법은 정해지지 않았다. Gunthorpe는 이 반대에 대응해 변환을 dma-buf core에만 두는 절충안을 냈고, 이 절충안을 따르는 것이 iommufd importer type이다.

NVIDIA exporter가 BAR1 구간 목록을 만들어 내는 일은 두 방식에서 같고, 달라지는 것은 iommufd 쪽이다. iommufd는 받은 주소로 매핑하던 구조에서 도메인을 넘기고 매핑을 core에 맡기는 구조로 바뀐다. revoke 때 IOMMU에서 매핑을 지우는 주체도 core 쪽으로 옮겨질 것으로 추정하며, importer type 시리즈가 게시되지 않아 확인하지 못했다. 5월에 Xu Yilun은 KVM의 페이지 테이블이 `iommu_domain`이 아니므로 이 절충안이 KVM에 맞지 않는다고 지적했다. Gunthorpe는 "it doesn't work well for kvm, and yes it is really weird and worse that phys in every way"라고 답했고, 그 뒤 이 스레드에는 답이 없다. 그런데도 Popple의 10-26 표지 메일은 iommufd 연결을 이 절충안으로 할 계획이라고 적고 있으므로, importer type의 형태는 아직 바뀔 수 있다(추정).

경과 표의 날짜는 UTC 기준이다.

| 날짜 | 경과 | 출처 |
| --- | --- | --- |
| 2026-02-18 | Gunthorpe, RFC v1 26편 (PAL type 포함) | [메일](https://lore.kernel.org/all/0-v1-b5cab63049c0+191af-dmabuf_map_type_jgg@nvidia.com/) |
| 2026-04-13 | König, PAL에 "pretty big NO-GO". Gunthorpe, "CPU iommu hw only works in physical address"라며 사용자 공간 드라이버의 GPU 메모리 용도를 언급 | [König](https://lore.kernel.org/all/c413710b-4c28-4ed8-88ec-aeb8c4482011@amd.com/), [Gunthorpe](https://lore.kernel.org/all/20260413121628.GE2588311@nvidia.com/) |
| 2026-04-22 | König, exporter가 `iommu_domain`에 직접 매핑하는 대안 제시. Gunthorpe 절충안. König은 mapping type 체계 자체에 찬성 | [König](https://lore.kernel.org/all/fd8065ce-fd0e-4df5-9c80-8e9603657cfe@amd.com/), [Gunthorpe](https://lore.kernel.org/all/20260422150000.GK3199414@nvidia.com/), [König](https://lore.kernel.org/all/e67426b9-4ded-4f6c-8309-7f847adb4540@amd.com/) |
| 2026-05-09, 05-11 | Xu Yilun, 절충안은 KVM에 맞지 않음. Gunthorpe, "worse that phys in every way"라며 동의. 이후 스레드 정지 | [Xu](https://lore.kernel.org/all/af7GzASJiASopYiN@yilunxu-OptiPlex-7050/), [Gunthorpe](https://lore.kernel.org/all/20260511224841.GA1197107@nvidia.com/) |
| 2026-10-16 | Mehltretter, iommufd PAL 해제 경로 double-free(KASAN 재현)와 `match_mapping()` 호출 시점 문제 보고 | [메일](https://lore.kernel.org/all/20261016194022.62065-1-kmehltretter@gmail.com/), [메일](https://lore.kernel.org/all/20261016202653.97339-1-kmehltretter@gmail.com/) |
| 2026-10-19 | König, type 결정은 매핑 직전 `dma_resv` 락 안에서. Hellström, attach-map-invalidate 계약 제안 | [König](https://lore.kernel.org/all/d08a26ed-ded7-4447-bf7b-88597ee7df0e@amd.com/), [Hellström](https://lore.kernel.org/all/8d4cb20b70ac4c3f36d8d631769757158af2ac8e.camel@linux.intel.com/) |
| 2026-10-20 | Mehltretter, 해제 경로 수정 RFC. Popple, "PAL 방식의 수용 여부가 아직 정리되지 않았고 다른 방식을 보기 시작했다" | [RFC](https://lore.kernel.org/all/cover.1792477872.git.kmehltretter@gmail.com/), [Popple](https://lore.kernel.org/all/atdKZpEJVZY0enR2@nvdebian.thelocal/) |
| 2026-10-21 | Popple, Mehltretter의 수정을 v2에 합치겠다고 답함 | [Popple](https://lore.kernel.org/all/athLCINDCSUbRHiC@nvdebian.thelocal/) |
| 2026-10-26 | Popple, 정식 패치 `[PATCH 00/26]`. PAL과 vfio/iommufd 사용처 제외, type 선택을 pin 또는 map 시점으로. Mehltretter, map 실패 시 선택이 지워지는 문제를 KUnit으로 재현 | [메일](https://lore.kernel.org/all/20261026053623.202642-1-apopple@nvidia.com/), [Mehltretter](https://lore.kernel.org/all/at8IQZ34wkHQ_5PL@gmail.com/) |
| 2026-10-27 | Popple, Mehltretter의 보고와 Xe 관련 지적 두 건을 v2에서 고치겠다고 답함. König, 새 attach 함수에 NO-GO, dma-buf로 물리주소를 IOMMU 함수에 넘기는 것은 KVM, IOMMUFD, virtio 외에는 hard NAK | [Popple](https://lore.kernel.org/all/auA0XzHv9lgImZLP@nvdebian.thelocal/), [Popple](https://lore.kernel.org/all/auAk6hXyZbvBIrVO@nvdebian.thelocal/), [König](https://lore.kernel.org/all/43a20d60-89a9-48fc-af73-5907b35a54d7@amd.com/), [König](https://lore.kernel.org/all/2be3338a-5657-4312-869d-3bb1d386f9fc@amd.com/) |

### 5.3 mm memory provider와 guest_memfd export

이 절의 시리즈는 dma-buf를 거치지 않고 드라이버의 메모리를 iommufd에 매핑하려는 시도다. 처음에는 mm에 범용 인터페이스를 두려 했으나, 2026-10-27에 VM 메모리(guest_memfd)만 다루는 방향으로 범위가 줄었다.

#### mm memory provider (RFC v1, v2)

Amazon의 Griffoul이 2026-10-06에 올린 mm memory provider의 구조는 다음과 같다.

- 페이지 할당자 밖의 메모리를 가진 드라이버(예: GPU 드라이버)가 그 메모리를 provider 파일로 내놓는다.
- iommufd는 `IOMMU_IOAS_MAP_FILE`로 이 파일을 받아 IOMMU에 매핑한다. dma-buf와 달리 메모리를 pin하지 않는다.
- 드라이버가 메모리를 회수(revoke)하려면 먼저 그 파일을 매핑한 모든 사용자(iommufd, KVM)에게 알리고, 사용자는 매핑을 지운다.

이 설계는 guest_memfd를 dma-buf로 받치려던 RFC(dma-buf importer가 물리주소를 받는 `get_phys()` 포함)를 König이 거부한 다음 날 나왔다. guest_memfd를 iommufd로 매핑하려는 시도는 이보다 앞서 2026-02에 AMD의 Kardashevskiy가 RFC로 올린 적이 있다. Griffoul은 VFIO도 BAR를 provider 파일로 내면 iommufd의 현행 vfio-pci 전용 경로(`symbol_get()`)를 대체할 수 있다고 적었다([메일](https://lore.kernel.org/all/20261016105752.68015-1-griffoul@gmail.com/)).

iommufd 메인테이너 Gunthorpe는 "if we are going to do this"라고 전제한 뒤, provider 파일 매핑이 IOMMU 공통 페이지 테이블 코드인 iommupt(generic_pt)에서만 동작해야 하고 hole(드라이버가 아직 메모리를 주지 않은 페이지)을 처리하는 unmap을 갖춰야 한다고 요구했다. 채택 여부는 밝히지 않았다. RFC v2의 큰 IOMMU 페이지 매핑 patch도 Gunthorpe의 지적을 받아 Griffoul이 빼겠다고 답했다.

#### guest_memfd export로의 전환 (2026-10-27)

Griffoul은 RFC v3 대신 guest_memfd export RFC를 올리고, 표지 메일에서 "this series drops the mm interface"라고 밝혔다. guest_memfd는 KVM이 VM의 메모리를 담는 파일이다. 2026-10-22에 올라온 Ackerley Tng(Google)의 guest_memfd RFC v2가 페이지 할당자 밖의 메모리를 guest_memfd에 공급하는 기능(PFN mode provider)을 guest_memfd 안에 직접 넣었으므로, Griffoul은 mm에 별도 인터페이스를 둘 필요가 없어졌다고 설명했다.

| 항목 | mm memory provider RFC v2 (2026-10-14) | guest_memfd export RFC (2026-10-27) |
| --- | --- | --- |
| 인터페이스 위치 | mm | guest_memfd (KVM) |
| iommufd가 매핑하는 파일 | 드라이버가 낸 provider 파일 | guest_memfd 파일 |
| 대상 메모리 | 페이지 할당자 밖의 드라이버 메모리 (VM 밖 포함) | VM 메모리 |
| 매핑 갱신 방법 | 드라이버가 revoke를 알림 | guest_memfd가 페이지 변경(private 전환, punch hole, revoke)을 콜백으로 알리면 iommufd가 해당 구간을 다시 매핑 |

새 시리즈의 iommufd 부분은 인터페이스를 시험하는 시연용이다. 실제 지원은 Gunthorpe가 v2에 요구한 generic_pt 작업(큰 IOPTE의 분할과 병합)을 갖춘 별도 iommufd 시리즈로 올릴 예정이다.

같은 시기에 Arm의 Aneesh Kumar는 vfio-pci BAR를 guest_memfd provider로 쓰는 RFC(v1 10-10, v2 10-17)를 올렸다. 이 시리즈는 장치 MMIO를 VM에 연결하는 용도이고, provider가 붙어 있는 동안 vfio-pci의 dma-buf export를 막는다.

이 전환으로 VM 밖의 드라이버가 자기 메모리를 iommufd에 매핑하게 하는 경로는 게시된 시리즈에서 사라졌다. CUDA 할당은 guest_memfd가 아니므로, 이 시리즈는 NVMe가 CUDA 메모리에 DMA하는 용도에는 해당하지 않는다고 추정한다.

#### 경과

경과 표의 날짜는 UTC 기준이다.

| 날짜 | 경과 | 출처 |
| --- | --- | --- |
| 2026-02-25 | Kardashevskiy, iommufd의 guest_memfd 매핑 RFC | [메일](https://lore.kernel.org/all/20260225075211.3353194-1-aik@amd.com/) |
| 2026-07-16, 07-20 | Woodhouse, guest_memfd PFNMAP provider RFC v1, v2 (iommufd 연결은 dma-buf) | [v1](https://lore.kernel.org/all/20260716151706.244987-1-dwmw2@infradead.org/), [v2](https://lore.kernel.org/all/20260720111259.122911-1-dwmw2@infradead.org/) |
| 2026-09-26 | Ackerley Tng, guest_memfd resource fd RFC v1 17편 | [메일](https://lore.kernel.org/all/20260925-gmem-tmpfs-backend-v1-0-d36159822d18@google.com/) |
| 2026-10-01 | Gunthorpe, Ackerley RFC v1 스레드에서 "not add more of the hack mess I made for vfio/iommufd" | [메일](https://lore.kernel.org/all/20261001171501.GD3019323@ziepe.ca/) |
| 2026-10-05 | Griffoul, guest_memfd를 dma-buf로 받치는 RFC(`get_phys()` 포함). König이 당일 NAK했고, 다른 메일에서 exporter 전용 사설 인터페이스는 괜찮다고 답함 | [RFC](https://lore.kernel.org/all/20261005095552.52748-1-griffoul@gmail.com/), [König NAK](https://lore.kernel.org/all/a04f17cc-f59a-4240-81c8-29776eee3a2e@amd.com/), [König](https://lore.kernel.org/all/f0077cec-10fe-400a-b229-f7434e297364@amd.com/) |
| 2026-10-06 | Griffoul, mm memory provider RFC v1 9편 | [메일](https://lore.kernel.org/all/20261006183235.16576-1-griffoul@gmail.com/) |
| 2026-10-10, 10-17 | Aneesh Kumar, guest_memfd 장치 MMIO RFC v1, v2 | [v1](https://lore.kernel.org/all/20261010072504.536230-1-aneesh.kumar@kernel.org/), [v2](https://lore.kernel.org/all/20261017073149.1303738-1-aneesh.kumar@kernel.org/) |
| 2026-10-12 | Gunthorpe, `get_phys()` RFC 스레드에서 "I don't want to hardwire every exporter into iommufd". Griffoul, iommufd 쪽 exporter registry 방안을 포기 | [Gunthorpe](https://lore.kernel.org/all/20261012144616.GF14213@ziepe.ca/), [Griffoul](https://lore.kernel.org/all/20261012152946.63489-1-griffoul@gmail.com/) |
| 2026-10-14 | Griffoul, RFC v2 11편. provider 파일을 `resource_fd`로 받고 큰 IOMMU 페이지 매핑 patch 추가 | [메일](https://lore.kernel.org/all/20261014093733.90312-1-griffoul@gmail.com/) |
| 2026-10-16 | Gunthorpe, 큰 페이지 patch에 "generic_pt에 cut과 알맞은 unmap을 구현해야 한다". Griffoul, v3에서 제외하겠다고 답함 | [Gunthorpe](https://lore.kernel.org/all/20261016001448.GC14213@ziepe.ca/), [Griffoul](https://lore.kernel.org/all/20261016094610.57849-1-griffoul@gmail.com/) |
| 2026-10-21 | Samiullah Khawaja(Google)의 hole 추적 질문에 Gunthorpe가 iommupt와 hole 대응 unmap을 조건으로 제시 | [메일](https://lore.kernel.org/all/20261021234647.GA3381610@ziepe.ca/) |
| 2026-10-22 | Ackerley Tng, guest_memfd alternative providers RFC v2 50편. guest_memfd 안에 provider 연산을 둠 | [메일](https://lore.kernel.org/all/20261022-gmem-alternative-providers-v2-0-5dd1dc6c660a@google.com/) |
| 2026-10-27 | Griffoul, guest_memfd export RFC 14편. mm 인터페이스를 빼고 iommufd가 guest_memfd 파일을 매핑 | [메일](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/) |

### 5.4 설계 비교

| 항목 | 현행 vfio 경로 | `iommu_map_pa` | mapping types (PAL RFC, 이후 importer type) | mm provider (RFC v2, 중단) |
| --- | --- | --- | --- | --- |
| exporter 범위 | vfio-pci만 | 제한 없음 (사용자 공간이 물리주소를 줌) | 규약을 구현한 모든 드라이버 | provider 파일을 내는 모든 드라이버 |
| 물리주소 확인 | vfio-pci | 없음 | exporter | provider |
| pin / revoke | pin + revoke | 없음 | pin + revoke | revoke만 |
| IOVA 회계와 락 | iommufd | 우회 | iommufd | iommufd |
| NVIDIA가 할 일 | 불가 | 없음 | 새 type의 exporter 구현 | provider 파일 구현 |
| 상태 (2026-10-29) | 머지됨 | 동작, 안전하지 않음 | 체계는 정식 시리즈, iommufd 연결은 게시되지 않음 | 중단(2026-10-27, guest_memfd export로 대체) |

네 방식 모두 GPU BAR1의 물리주소를 `IOMMU_MMIO` 속성으로 NVMe의 IOMMU 도메인에 넣는다. 다만 엔트리 크기는 설계에 따라 다르고(아래 마지막 문단), 그 밖의 차이는 물리주소를 누가 보증하고 매핑의 수명을 누가 관리하는가에 있다.

`iommu_map_pa`를 쓰면 커널은 사용자 공간이 `dmabuf_import`로 알아낸 물리주소를 확인하지 않고 도메인에 넣는다. 주소가 틀렸거나 그 사이에 버퍼의 쓰임이 바뀌어도 커널은 알 수 없다. 또 iommufd 밖에서 도메인에 직접 쓰므로, IOVA가 iommufd의 다른 매핑과 겹치지 않게 하는 일과 장치가 도메인을 떠나기 전에 매핑을 지우는 일을 사용자 공간이 맡는다. upcie 0.9.0에도 있는 `dmamem_iommu_map_pa_reserve_window()`는 IOAS에서 이 창을 예약해 겹침을 막는다. 나머지 세 방식은 메모리를 소유한 드라이버(vfio-pci, exporter, provider)가 물리주소를 내므로 주소의 유효성은 소유자가 책임지고, IOVA 할당과 매핑 추적은 iommufd가 한다.

pin과 revoke 중 무엇을 쓰는지에 따라 매핑 도중 메모리 소유자가 할 수 있는 일이 달라진다. importer는 pin으로 버퍼 이동을 막고, 소유자는 revoke로 접근을 회수하며 그때 importer가 매핑을 지운다. 현행 vfio 경로와 mapping types는 둘 다 쓰므로, 버퍼는 매핑 동안 고정되지만 장치 리셋 같은 상황에서는 소유자가 회수할 수 있다. mm provider는 pin 없이 revoke만 쓰므로 소유자가 언제든 프레임을 회수할 수 있고, iommufd는 회수 알림을 받는 즉시 해당 구간을 IOMMU에서 지운다. `iommu_map_pa`는 매핑할 때 dma-buf 참조를 잡아 두므로 `cuMemFree` 뒤에도 메모리가 남으며, PoC에서 이를 확인했다. 그러나 `iommu_map_pa`에는 회수 알림을 받을 방법이 없다.

NVIDIA 쪽에서 보면 현행 vfio 경로는 vfio-pci가 내보낸 dma-buf만 받으므로 NVIDIA 드라이버가 할 수 있는 일이 없다. mapping types가 채택되면 NVIDIA는 BAR1 구간 목록을 내는 exporter를 구현하면 되고, 이는 PoC에서 PAL exporter로 한 일과 같다. CUDA 응용은 지금처럼 `cuMemGetHandleForAddressRange()`로 받은 dma-buf fd를 그대로 쓴다. mm provider RFC v2대로라면 NVIDIA는 프레임을 돌려주고 회수하는 provider 파일을 새로 구현해야 했고, CUDA 응용도 dma-buf가 아닌 그 파일을 받아야 했을 것이다(추정). 그러나 이 방향은 2026-10-27에 mm 인터페이스가 빠지면서 중단되었다(§5.3). 매핑 단위도 다르다. PoC의 PAL 경로는 1 GiB 버퍼를 2 MiB 엔트리 512개로 매핑했지만, mm provider v2에서 큰 페이지 patch를 빼면 `PAGE_SIZE` 단위가 되어 같은 버퍼에 4 KiB 엔트리 262,144개를 만들게 된다(설계상 계산).

### 5.5 NVIDIA 드라이버에 미치는 영향

**NVIDIA 전용 사설 연결.** NVIDIA dma-buf만을 위한 별도 경로가 생길 가능성은 낮다(추정). 지금 vfio-pci는 iommufd와 전용 함수로 연결되어 있고, NVIDIA 드라이버에도 같은 전용 함수를 두는 방법을 생각할 수 있다. 그러나 iommufd 메인테이너 Gunthorpe는 2026-10-01에 "I want us to resolve this in the dmabuf code cleanly not add more of the hack mess I made for vfio/iommufd"라고 썼고([메일](https://lore.kernel.org/all/20261001171501.GD3019323@ziepe.ca/)), 2026-10-12에는 `get_phys()` RFC 스레드에서 "I don't want to hardwire every exporter into iommufd"라고 썼다([메일](https://lore.kernel.org/all/20261012144616.GF14213@ziepe.ca/)). 따라서 NVIDIA dma-buf는 범용 규약이 머지된 뒤에야 iommufd로 매핑할 수 있을 것으로 추정한다. 이 추정의 근거는 Gunthorpe의 두 메일이며, 다른 메인테이너의 의견은 찾지 못했다.

**NVIDIA 드라이버가 구현할 규약.** NVIDIA가 할 일은 어느 설계가 채택되는지에 따라 달라지며, 설계별 내용은 §5.4의 표와 설명에 있다. 확인한 범위(§7)에서는 NVIDIA나 CUDA를 다룬 업스트림 시리즈가 없지만, Gunthorpe는 2026-04-13에 사용자 공간 드라이버가 GPU 메모리를 쓰는 용도를 목표 가운데 하나로 언급했다. mapping types 쪽이 채택되면 NVIDIA exporter는 PoC의 PAL exporter와 같은 일을 하게 된다고 추정하는데, 이 추정은 4월 절충안과 10월 26일 표지 메일에 근거한다.

## 6. 앞으로의 작업

**위험.** `iommu_map_pa`는 도메인이 바뀌거나 IOVA가 겹치면 잘못된 매핑이나 use-after-free를 일으킬 수 있다. 지금은 실험과 검증에만 쓰므로 그 영향도 실험 환경 안에 머문다.

**할 일.** 업스트림이 정해질 때까지는 `iommu_map_pa`를 계속 쓴다. 그동안 이 모듈을 안전하게 쓰기 위한 제약(도메인 변경 금지, IOVA 창 예약, 매핑 제거 순서)을 운영 절차에 옮겨 적어, 실험 중에 도메인을 바꾸거나 IOVA 창을 겹쳐 쓰는 일을 막는다. IOVA 창 예약은 upcie의 `dmamem_iommu_map_pa_reserve_window()`로 할 수 있다. iommufd importer type 시리즈가 게시되면 PoC의 NVIDIA 패치를 그 규약으로 옮길 수 있는지 검토하고, 그 시리즈가 iommufd for-next에 들어가면 실제로 다시 이식해 PoC의 정합성, 처리량, 수명 시험을 다시 실행한다. `iommu_map_pa`를 실제로 바꾸는 전환은 아래 "전환 시점"의 조건이 갖춰진 뒤에 한다. Guanghui Feng의 `IOMMU_GET_RECOMMENDED_RESERVATIONS`와 `IOMMU_IOAS_RESERVE_IOVAS`가 머지되면, xNVMe가 그 범위를 조회해 예약한 뒤 GPU IOVA 창을 고르게 한다. io_uring dma-buf 경로(§3)는 NVMe를 커널 드라이버로 구동하는 대안이므로, v7.4-rc1이 나오면 xNVMe의 io_uring 백엔드에서 CUDA dma-buf를 등록해 IOMMU를 켠 환경에서 동작하는지 시험할지 검토한다. passthrough 시리즈가 머지되면 xNVMe의 io_uring 백엔드에 dma-buf 고정 버퍼 등록을 더한 뒤 `io_uring_cmd` 백엔드로도 같은 시험을 한다.

**지켜볼 신호.** 분기마다 아래 항목을 확인한다. 1과 2는 dma-buf 쪽, 3은 mm과 guest_memfd 쪽, 4는 NVIDIA, 5는 iommufd 자체, 6은 iommufd 밖 커널 경로의 변화다.

1. **mapping type 체계의 linux-next 진입.** linux-next에서 `dma_buf_mapping_match`나 `match_mapping`을 찾는다. König이 새 attach 함수에 반대했으므로 `dma_buf_mapping_attach`는 v2에서 이름이 바뀔 수 있다. 들어갔다면 iommufd importer type이 기반으로 삼을 체계가 갖춰졌다.
2. **iommufd importer type 시리즈 게시.** lore에서 Popple이나 Gunthorpe의 dma-buf, iommufd 시리즈를 찾는다. 게시되면 dma-buf 경로의 iommufd 연결 방식이 정해지는 단계이므로 PoC 패치의 재이식을 검토한다.
3. **guest_memfd 쪽 iommufd 시리즈의 범위.** Griffoul이 예고한 별도 iommufd 시리즈가 guest_memfd 파일만 받는지, 드라이버가 내는 다른 파일도 받는지 본다. guest_memfd만 받으면 NVIDIA에 해당하는 경로는 dma-buf 쪽만 남는다.
4. **NVIDIA 드라이버의 대응.** open-gpu-kernel-modules 릴리스의 `nv-dmabuf.c`에 새 mapping type의 exporter 코드가 들어가는지 본다.
5. **iommufd UAPI 주석의 변경.** `include/uapi/linux/iommufd.h`의 `IOMMU_IOAS_MAP_FILE` 주석에서 "not a generic dma-buf import path"가 사라지면 iommufd가 일반 dma-buf를 받게 되었다고 판단한다.
6. **dma-buf backed NVMe passthrough 머지.** Anuj Gupta 시리즈가 block 또는 nvme 트리에 들어가는지 본다. 들어가면 xNVMe에 dma-buf 고정 버퍼 등록을 더해, aisio의 커널 경로에서 xNVMe `io_uring_cmd` 백엔드로 GPU 메모리 P2P를 시험할 수 있다.

**전환 시점.** `iommu_map_pa`를 업스트림 경로로 바꾸는 작업은 iommufd 연결 규약(지금으로서는 importer type)이 linux-next에 들어가고, NVIDIA가 그 규약을 구현한 드라이버를 내고, 사용하는 커널이 그 버전 이상이 된 뒤에 시작한다. 그 전에 시작하면 업스트림 변경에 따라 작업을 다시 해야 할 수 있다.

## 7. 확인하지 못한 것

이 문서에서 "추정"으로 표시한 것은 소스나 로그로 확인하지 못한 판단이다. 그중 다음 단계가 정해진 항목은 다음과 같다.

| 확인하지 못한 것 | 다음 단계 |
| --- | --- |
| NVIDIA dma-buf가 심볼 조회와 exporter 검사 중 어디서 거부되는지 | 측정 서버 배포판 커널의 `/boot/config-7.0.0-34-generic`에서 `CONFIG_VFIO_PCI_DMABUF`를 확인하고, vfio-pci(vfio-pci-core) 모듈을 적재한 상태에서 PoC의 A0 시험(배포판 커널에서 `IOMMU_IOAS_MAP_FILE` 호출)을 다시 실행하며 kprobe로 `vfio_pci_dma_buf_iommufd_map`의 반환값을 기록한다 |
| CUDA 할당에 BAR1을 가리키는 CPU 매핑(VMA)이 없다 | `test_dmamem_cuda_iommu_map_pa_nvme_readwrite` 실행 중 `/proc/<pid>/maps`에 BAR1 범위가 있는지 본다 |
| CUDA/NVIDIA를 다룬 업스트림 시리즈가 없다 (linux-iommu와 io-uring은 2026-01 이후, dri-devel과 kvm은 2026-09 중순 이후, linux-nvme는 2026-01 이후, linux-block은 2026-06 이후. linux-mm, linux-pci의 과거분과 linux-rdma, linaro-mm-sig는 미확인) | 나머지 리스트와 기간을 받아 다시 검색한다 |
| Sashiko가 지적한 "정식 시리즈 patch 15가 iommufd의 vfio dma-buf 매핑을 깨뜨린다"는 문제 (AI 리뷰의 주장) | 스레드의 답을 확인하고, 필요하면 그 시리즈를 적용한 커널에서 iommufd selftest의 dma-buf 시험을 실행한다 |
| NVIDIA dma-buf가 io_uring dma-buf 경로(커널 nvme-pci importer)에서 동작하는지, IOMMU를 켠 환경에서 DMA 주소를 제대로 돌려주는지 | v7.4-rc1 커널에서 CUDA dma-buf를 io_uring에 등록해 raw NVMe 블록 장치로 읽고 쓰고, 데이터와 IOMMU fault 로그를 확인한다 |
| iommufd importer type이 out-of-tree exporter를 받는 형태가 될지, revoke 때 IOMMU 매핑을 지우는 주체가 dma-buf core인지 | 시리즈가 게시되면 exporter 쪽 계약과 invalidate 경로를 읽는다 |

머지되지 않은 시리즈는 이후 버전에서 내용이 바뀔 수 있다. 인용은 2026년 10월 29일 시점이다.
