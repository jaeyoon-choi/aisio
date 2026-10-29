# 리뷰: iommufd GPU 메모리 DMA 매핑 지원 현황 보고서 (2026-10-29)

- 리뷰 대상: `notes/iommufd-gpu-memory.md`(한글), `notes/iommufd-gpu-memory.en.md`(영문). 아래 줄 번호는 두 파일 공통.
- 리뷰 기준일: 2026-10-29
- 리뷰 방법: 6축 병렬 검증 — 머지 커밋 / 미머지 시리즈·lore / 커널 소스 코드 / 누락 패치 스윕 / 내부 정합성·한영 대조 / 외부 참조·PoC 대조.
- 1차 출처: git.kernel.org cgit, lore `lei`(mbox), raw.githubusercontent v7.3/v7.4, cdn.kernel.org ChangeLog, GitHub, 로컬 torvalds 트리.
- 표기: **A(실오류) > S(최신성) > B(정밀도) > C(누락) > D(검증 불가)**.
**핵심 결론은 2026-10-29 현재 유효**하다(upstream iommufd는 여전히 NVIDIA dma-buf 거부, mapping types 정식 시리즈에 PAL/iommufd importer type 없음, v7.4 창에 exporter 개방 커밋 없음). 아래는 고칠 오류·stale·누락이다.

## 0. 한눈에
| 구분 | 건수 |
|---|---|
| A. 실오류/오귀속 | 9 |
| S. Stale(최신성) | 3 |
| B. 정밀도·표현 | 22 |
| C. 놓친 커밋/시리즈 | 머지 9개 + 시리즈·신호 10건 |
| D. 검증 불가 | 7 |

## A. 실오류/오귀속 (반드시 수정)

| # | 위치 | 문제 | 근거 | 수정 |
|---|---|---|---|---|
| A1 | L95 | §3 표 헤더 기준 `65ba8f34ec88`은 **xtensa 머지**(2026-10-27). L6이 선언한 기준 `c339f4010dea`(2026-10-28)와 불일치 | cgit: 65ba8f34ec88 = Merge tag 'xtensa-20261027' | 헤더를 `c339f4010dea`로 통일 |
| A2 | L128 | guest_memfd export "Not yet reviewed" — **2026-10-28 Sashiko AI 리뷰 존재**(09/14, Medium: missing iova page-alignment check). 사람 리뷰는 없음 | `sashiko-outbox-188091@kernel.org` | "사람 리뷰 없음, Sashiko AI 리뷰 1건(10-28)" |
| A3 | L130 | "mm provider v2가 이 중 patch 1만 기반" — Woodhouse patch 1은 KVM selftest. gmem ops는 **3/11** | Woodhouse `20260720111259`, Griffoul v2 cover | "gmem ops 패치(3/11)를 v2가 자기 patch 1로 가져옴" |
| A4 | L213 | König "exporter 전용 사설 인터페이스 허용"을 `a04f17cc`에 귀속 — 실제로는 다른 메일 | `f0077cec-10fe-400a-b229-f7434e297364@amd.com` (2026-10-05 16:53 +0200) | 링크 교체 |
| A5 | L215, L243 | "mm provider thread"(2026-10-12) — 실제 스레드는 **dma-buf `get_phys()` RFC(0/6)** | `20261012144616.GF14213` (Subject/In-Reply-To) | "dma-buf get_phys 스레드" |
| A6 | L148 | 절충안 "인용"이 문자 그대로가 아님 | 원문: "The exporter provides the address data, the importer provides the iommu_domain. The core code, and only the core code, has both and does the required operation?" | 따옴표 제거/원문 |
| A7 | L146 | "DPDK/SPDK connecting GPU memory to VFIO/iommufd" 인용이 문자 그대로가 아님 | 원문: "there are use cases in DPDK/SPDK to connect GPU memory into VFIO/iommufd" | 원문으로 |
| A8 | L103 | "dma-buf 하나는 4 GiB 이하" — 실제 `if (size > UINT_MAX) return -EINVAL;` → 정확히 4 GiB도 거부 | master `block/fops.c` | "4 GiB 미만(최대 4 GiB−1바이트)" |
| A9 | L40 | DKMS 패키지명 `upcie-experimental-dkms` — upcie v0.9.0 README 실제 이름은 **`iommu-map-pa-dkms`** | v0.9.0 README `apt install ../iommu-map-pa-dkms_*_all.deb` | `iommu-map-pa-dkms`로 |

## S. Stale (최신성 — 기준일 이후 바뀐 사실)

| # | 위치 | 현재 문서 | 실제(2026-10-29) | 영향 |
|---|---|---|---|---|
| S1 | L8, L40 링크 | upcie-experimental **0.9.0** | **0.10.4** (v0.10.0 2026-10-21). v0.10.0에서 `dmamem_iommu_map_pa_reserve_window()`(IOMMU_IOAS_IOVA_RANGES/ALLOW_IOVAS로 IOVA carve-out), 최대 **16 target device**, `include/upcie/iommufd.h` userspace helper 추가 | §5.4/§6의 "user space가 IOVA 겹침을 직접 관리"·"운영 절차에 예약 window" 서술 일부가 라이브러리 helper로 대체됨. 단 "production-safe 아님" 결론은 유지 |
| S2 | L8, L14 | NVIDIA 드라이버 **580.178.04** | 최신 branch **580.196.07 / 595.112.07 / 615.71.10** (2026-10-21~22). 최신 `nv-dmabuf.c`에 mapping type/phys_vec/PAL 코드 **0건** → signal 4 부정은 유지. Issue #1324는 580.178.04가 아니라 **595.84**에 대한 보고 | 버전 참조 갱신. 결론 불변 |
| S3 | L126 | Mehltretter release-path 수정을 "Popple이 fold **검토**" | Popple이 2026-10-21 "**v2에 fold하겠다**"고 확정(`athLCINDCSUbRHiC@nvdebian.thelocal`), v2는 10-29까지 미게시 | "fold 확정, v2 미게시" |

## B. 정밀도·표현 (사실 오류 아님)
B1 L71 "CUDA VA 경로 매핑 불가" 사실 단정 → "(추정)"(§1 L40·§7 L270은 추정/미확인)
B2 L245 "NVIDIA/CUDA 시리즈 없음" 단정 → 완화(§7 L271은 검색범위 한정 미확인)
B3 L162 König "importer ops" — 원문에 없는 표현 → "기존 `dma_buf_dynamic_attach()`를 쓰라"
B4 L71 "pages.c 522행에서 `iommu_map()` 호출" — 522행은 플래그 설정, 호출은 540(대형)/491(소형)
B5 L113 "`symbol_get()`으로만" — 테스트 훅(`iommufd_test_dma_buf_iommufd_map`)·`CONFIG_VFIO_PCI_DMABUF` 가드 존재
B6 L84 인용문("for now can only be used with the VFIO DMABUF exporter")은 소스 주석이 아니라 **커밋 메시지**(71db84a092c3)
B7 L79 f4986a72d6e4 "라이브 마이그레이션용"은 커밋 메시지에 없음(시리즈 맥락)
B8 L82 "iommufd misc 장치로 우회"는 커밋 메시지가 아닌 코드 사실(`iommufd_global_device()`→misc)
B9 L88 "계약을 확인" → "bounded revoke 가능 importer만 수용"이 원문에 가까움
B10 L169 링크 순서가 시간순 아님: `fd8065ce`(12:39)→`e67426b9`(14:04)→Gunthorpe(15:00)
B11 L217 행 날짜 10-15 vs 인용 msgid 날짜 10-16(UTC)
B12 L125/L167 RFC v1 Date = 2026-02-17 20:11 −0400 (= 02-18 UTC)
B13 L130 "David Woodhouse, Amazon" — 인용 메일로 미검증(`dwmw2@infradead.org`, Cc에만 amazon)
B14 L138 "나머지 시리즈는 이 규약을 만들지 않으며" 총칭에 `get_phys()`(L129) 불릿 누락
B15 L89–90 "두 항목"(pin/revoke, 물리주소 목록) 지시 대상 모호
B16 L269 "A0" 미정의
B17 L3 상호 언어 링크 파일명(`iommufd-gpu-memory.en.md`/`.md`)이 실제(`ko.md`/`en.md`)와 다름
B18 L1 영문 제목에서 "현황(status)" 탈락(선택)
B19 L30 "NVIDIA 전용 연결" 앵커 `#4-제약-요인`(§4) → 실제 내용은 §5.5
B20 L82 "revoke는 v7.1에서 해결"로 읽히나 iommufd 측 revoke는 v6.19(`fc7063abd98e`)
B21 L75 "소속은 저자 이메일 도메인으로 추정" — Gunthorpe `jgg@ziepe.ca`, Romanovsky `leon@kernel.org`라 도메인으로 NVIDIA 추론 불가(근거는 Signed-off-by)
B22 L239 262,144개 4 KiB는 mm provider 설계/산술(실측 아님) → "by design"

## C. 놓친 커밋/시리즈

### C1. 머지된 커밋 (§3 표 누락)
| 커밋 | 릴리스 | 제목 | 왜 |
|---|---|---|---|
| 74014a4b55f5 | v6.19 | `iommufd: Have pfn_reader process DMABUF iopt_pages` | 같은 시리즈 핵심, 769f2cd9226c의 Fixes 대상 |
| fc7063abd98e | v6.19 | `iommufd: Allow a DMABUF to be revoked` | 실제 revoke 구현 |
| 71e2409a0c85 | v6.19 | `iommufd: Do not map/unmap revoked DMABUFs` | 같은 시리즈 |
| 5d74781ebc86 | v6.19 | `vfio/pci: Add dma-buf export support for MMIO regions` | vfio-pci exporter 본체 |
| 61ceaf236115 | v6.19 | `vfio: Prevent pinned DMABUF importers from attaching to VFIO DMABUF` | 6ffe939bf94f의 직전 상태 |
| 575157b1b5fc | v7.1 | `dma-buf: Make .invalidate_mapping() truly optional` | revoke 시리즈 |
| 1a8a5227f229 | v7.1 | `vfio: Wait for dma-buf invalidation to complete` | revoke 시리즈 |
| b344ca94e8cc | v7.3 | `dma-buf: Fix silent overflow for phys vec to sgt` | **CVE-2026-98242** |
| 06dd5e1ae8ce | v7.3/v7.4 | `dma-buf: Split sgl by largest page-aligned chunk` | 위 수정의 후속 |

### C2. 놓친 시리즈·신호
1. **[중요] CVE-2026-98242** (2026-10-06 공지, 7.2.8 백포트): `3aa31a8bb11e`가 만든 `dma_buf_phys_vec_to_sgt()`에서 **MMIO 크기 >4 GiB + host bridge 경유 P2P**일 때 `mapped_len` 32비트 절단. 문서가 다루는 GPU BAR1(>4 GiB) + NVMe P2P 시나리오에 정확히 해당. §3 "v7.3/v7.4는 범위를 넓히지 않았다"는 사실이나 이 수정을 가림. PoC PAL 브랜치가 이 수정을 포함하는지 확인 필요.
2. `dma-buf: Fix IOVA offset when linking phys vecs to sgt` (Yili Zhang, Baidu, 2026-09-24) — 미머지, 같은 헬퍼의 offset 버그.
3. `[PATCH v8 0/9] vfio/pci: Add mmap() for DMABUFs` (Matt Evans, 2026-10-06) — 미머지. vfio-pci BAR dma-buf 표면을 바꾸는 향후 변화 신호.
4. `[PATCH v11 00/19] PCI/P2PDMA: Route peer-to-peer DMA by TLP class` (Leon Romanovsky, 2026-10-13) — 미머지. ACS/switch P2P 라우팅에 더 직접적(문서는 Guanghui Feng 시리즈만 언급).
5. **fgds** v1(2026-09-08)/v2(2026-10-27, KylinOS, Li Wang/Mengmeng Zhao) — 문서는 König NAK 한 줄만; §5.1에 시리즈(목적·테스트) 누락.
6. **mlx5 GH200 보고** (Dezhen Lu, 2026-10-28): NVIDIA dma-buf를 DMA-API importer(`ibv_reg_dmabuf_mr`)로 등록해 GH200에서 정상 동작(2^k 정렬 시 wrap 버그). §7의 "IOMMU 켜면 동작 안 할 수 있다" 추론에 대한 반대 신호 → §7에 인용 권장.
7. **mapping types의 PCIe P2P/SGT_P2P 방향**: Popple cover "separate out PCIe P2P as its own mapping type", 시리즈에 `SGT_P2P` type 존재. §5.4/§5.5의 선택지가 PAL/importer type 2개뿐이라 불완전(단 SGT_P2P는 `dma_addr_t`라 핵심 결론 불변).
8. Aneesh Kumar V `[RFC PATCH v1 0/6] KVM/VFIO: guest_memfd support for device MMIO resources` (2026-10-10)
9. Ackerley Tng `[PATCH RFC 00/17] Allow guest_memfd to be created using a resource (pool) fd` (2026-09-25)
10. Aneesh `[PATCH v7 00/16] iommufd: vIOMMUs and TSM guest requests...` (2026-10-08)
11. (경미) 같은 io_uring merge의 `839231d19393`, `d88e44f43e93`, `45b716456dd9`, `f57b957778a3`, `fd13f31ac62a`; v7.4 `1319b085869e`(P2PDMA DMABUF lifecycle docs).

## D. 검증 불가
- linux-next `next-20261028` tree 직접 확인(중반 이후 git.kernel.org 502) — 보고서의 "linux-next에 심볼 없음"은 정황상 사실일 가능성 높음.
- v6.19/v7.1 tag containment(44ebaa1744fd, 8c5f9645c389) — 동일 장애.
- NVIDIA GitHub issue 전수 목록(rate limit).
- P2PDMA v11 / Matt Evans v8 패치의 실제 코드(빌드·적용 미수행).
- PoC PAL 브랜치가 CVE-2026-98242 수정을 포함하는지(코드 미확인).
- NVIDIA 580.178.04 동작(-ENOTSUPP/BAR1 주소), PoC 내부 수치(errno=95, 처리량 등).

## E. 확인된 정확성
- §3 머지 커밋 23개: 존재·제목·저자·릴리스 귀속 전건 일치. 릴리스 날짜(v6.13 2025-01-19, v6.19 2026-02-08, v7.1 2026-06-14, v7.2 2026-08-16, v7.3 2026-10-18) 일치.
- 코드레벨 주장: 함수명·에러코드·검사 순서·버전 귀속 전건 일치(vfio_pci_dmabuf.c, pages.c, UAPI 주석, io_uring 경로).
- lore 인용 37건 실재; 날짜·저자·버전 대체로 정확.
- Issue #1324 실재(2026-08-27, OPEN, 댓글 0, 내용 일치).
- 한/영 실질 불일치 0건; 표 13개 무결; "추정" 마커 1:1.
- 핵심 결론(upstream이 NVIDIA dma-buf를 거부, iommu_map_pa 유지 필요)은 최신 트리에서도 유효.
