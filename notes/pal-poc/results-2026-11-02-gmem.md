# sid guest_memfd export PoC 결과 (2026-11-02)

`MANUAL-gmem.md` 3차 작업. 개발 PC 결과는 `results-2026-10-30-gmem.md`에 있다. 이 문서는 sid에서 같은 경로를 측정한 결과다.

방법: kvm.git `7e60162b16f9` 위에 Ackerley RFC v2와 Griffoul RFC를 쌓은 트리(`6766bffb9fc2`, tree `a6af7e15843c`)를 `7.3.0-rc7-gmem+`로 빌드해 설치하고 한 번 부팅했다. 장치는 기준 장치 `0000:4e:00.0` 하나, `SLBA=0`, `SPAN=1073741824`(1 GiB)를 썼다. `0000:4d:00.0`(데이터셋 장치)은 어떤 명령에도 넣지 않았다. 서버: Ice Lake-SP, NUMA 0, 경로 `4a:02.0/4b/4c:01.0/4e`, IOMMU 그룹 31 `DMA-FQ`, `intel_iommu=on`.

## 6절 단계 J — 정합성

`GPU=gmem ./followup-run.sh 0000:4e:00.0 0 c`. BAR1 구간은 1개, 첫 주소 `0x20a031e00000`이고, guest_memfd 1024 MiB를 IOVA `0xa00000`에 매핑했다.

| 시험 | 개발 PC 실측 | sid 예상 | sid 실측 |
| --- | --- | --- | --- |
| `--gmem` C1 (64K, 4K) | MATCH | MATCH (가정) | MATCH / MATCH |
| `--gmem` C2 (64K, 4K) | `sc=0x4` (플랫폼 제한) | MATCH (가정) | MATCH / MATCH |
| `--gmem` D | `sc=0x4`, DMAR fault | 같음 (가정) | `sc=0x4` + DMAR fault |
| `--gmem` D2 | OK | — | OK |
| `--map-pa` C1, C2 | C1 MATCH, C2 `sc=0x4` | MATCH | MATCH, MATCH |

세 실행 모두 `result: PASS (0 failure(s))`다. D의 DMAR fault는 의도한 미매핑 IOVA `0x80a00000`에 대한 3건뿐이다(Read `reason 0x06` 2건, Write `0x05` 1건). AER, NVRM, BUG, WARNING 줄은 없다.

## 7절 단계 K — 성능

`SECS=10 SPAN=1073741824 GPU=gmem ORDER="gmem pa host" ./followup-run.sh 0000:4e:00.0 0 "bench iova map pte"`. 25회 측정 모두 `0 err`, `result: PASS`.

### 처리량

| 시험 | guest_memfd | `iommu_map_pa` | host |
| --- | --- | --- | --- |
| rd 4K qd1 (MB/s, p50 µs) | 678.9, 5.8 | 635.5, 6.0 | 678.6, 5.8 |
| rd 128K qd32 (MB/s, p99 µs) | 6552.9, 901.0 | 6386.4, 928.0 | 6553.0, 901.5 |
| wr 4K qd1 (MB/s, p50 µs) | 714.4, 5.5 | 714.3, 5.5 | 745.6, 5.2 |
| wr 128K qd32 (MB/s, p50 µs) | 6424.8, 652.6 | 6424.7, 652.6 | 6424.8, 652.6 |
| map p50/p99 (µs) | 9040.4 / 9661.7 | 34.6 / 38.5 | 없음 |
| unmap p50/p99 (µs) | 7097.1 / 7937.9 | 2.4 / 2.8 | 없음 |

map/unmap은 1024 MiB 매핑을 1000회 반복한 값이다.

### IOVA 교차 (rd 128K qd32, MB/s)

기본 IOVA는 guest_memfd `0xa00000`, `iommu_map_pa` 256 GiB다.

| `iova` 조합 | 정방향 | 역방향 |
| --- | --- | --- |
| a guest_memfd, `0xa00000` | 6495.3 | 6495.6 |
| b guest_memfd, 256 GiB | 6330.7 | 6330.4 |
| c `iommu_map_pa`, 256 GiB | 6330.7 | 6331.4 |
| d `iommu_map_pa`, 1 GiB | 6495.6 | 6495.3 |
| host | 6495.5 | 6495.2 |

### PTE

```
gpu leaves: 2 MiB 0, 4 KiB 262144, low bits: 803 x262144, host 4 KiB leaves: 2048
gpu leaves: 2 MiB 512, 4 KiB 0, low bits: 883 x512, host 4 KiB leaves: 2048
```

guest_memfd 경로는 4 KiB 리프 262,144개(`0x803`, P+W+SNP), `iommu_map_pa`는 2 MiB 리프 512개(`0x883`)다. 차이는 PS 비트 하나이며 개발 PC와 같다.

## 8절 단계 L — 수명

| 시험 | 확인하는 것 | 개발 PC 실측 | sid 예상 | sid 실측 |
| --- | --- | --- | --- | --- |
| close (guest_memfd, `iommu_map_pa`) | dma-buf, provider, guest_memfd, VM fd를 닫아도 매핑이 유지되는가 | C1 MATCH, unmap 뒤 GPU 메모리 반환 | C1, C2 MATCH (가정) | fd 4종을 닫은 뒤에도 매핑 유지, C1·C2 MATCH, unmap+close 뒤 22,369 MiB 반환 |
| free: `cuMemFree` 직후 여유 | 매핑이 있는 동안 NVIDIA가 메모리를 해제하는가 | 해제하지 않음 | 같음 (가정) | 해제하지 않음 (21,345 MiB 유지), 두 경로 동일 |
| free: F1 새 버퍼 | 옛 IOVA로 쓴 데이터가 새 버퍼를 덮어쓰는가 | intact, 새 버퍼 물리주소가 다름 | intact (가정) | intact, 옛 `0x20a031e00000` → 새 `0x20a071e00000` |
| free: F2 | 옛 IOVA가 아직 옛 메모리를 가리키는가 | 측정 불가(C2 방향) | yes (가정) | yes |
| kill -9 | I/O 중 강제 종료 뒤 장치, GPU 메모리, 모듈 참조가 정리되는가 | 다음 실행 C1 MATCH, 메모리 15 MiB로 복귀, 참조 수 0 | 같음 (가정) | killed rc=137, 다음 실행 PASS, `cuda used after: 0 MiB`, 참조 수 0 |

마지막 `lsmod`는 `gpu_gmem_provider 0`, `kvm_intel 0`이다. dmesg에 BUG, WARNING, DMAR, AER, NVRM 줄이 없다.

## 해석

- **측정**: 4 KiB 리프는 처리량에 영향을 주지 않는다. 같은 IOVA끼리 비교하면 a(6495.3) ≈ d(6495.6) ≈ host(6495.5), b(6330.7) = c(6330.7)이고 정·역방향 차이는 0.1% 이내다. 2.54% 차이는 리프가 아니라 IOVA 위치가 만든다. 2차 PAL 측정의 2.6%와 같은 방향·크기다.
- **측정**: 처리량 표의 `--gmem`(6552.9)과 `--map-pa`(6386.4) 차이도 두 경로의 기본 IOVA가 달라서다. rd 4K qd1의 678.9 대 635.5도 같은 이유다(host가 678.6으로 guest_memfd와 같다). 표의 IOVA 교차는 128K만 쟀으므로 4K에 대해서는 이 분리가 간접 근거다.
- **측정**: 매핑 비용은 `iommu_map()` 호출 횟수에 비례한다. 262,144회에 9.04 ms, `iommu_map_pa`는 512회에 34.6 µs로 약 260배다. unmap도 7.10 ms 대 2.4 µs다.
- **측정**: 128K 쓰기는 세 경로가 6424.8 MB/s로 같다.
- **측정**: `cuMemFree`는 매핑이 살아 있는 동안 메모리를 반환하지 않는다. 매핑이 해제되면 22,369 MiB로 돌아온다.
- **측정**: F1이 intact이므로 해제된 버퍼의 페이지를 새 할당이 재사용해도 살아 있는 매핑이 새 버퍼를 오염시키지 않는다(새 버퍼가 다른 물리주소를 받았다).
- **측정**: F2는 yes다. 매핑이 여전히 해제된 버퍼의 물리 페이지를 가리킨다. 개발 PC에서 C2 방향이 안 돼 확인하지 못한 항목이다.
- **측정**: `kill -9` 뒤에도 장치 복귀, 메모리 회계, 모듈 참조가 정상이다. 개발 PC는 15 MiB로 복귀했지만 sid는 디스플레이가 없어 기준선이 0 MiB다.
- **추정**: F2가 yes라는 것은 그 페이지가 나중에 다른 용도로 재할당되면 살아 있는 매핑이 그 메모리를 계속 DMA할 수 있다는 뜻이다. 이번 시험에서는 새 버퍼가 다른 물리주소를 받아 실제 오염이 관측되지 않았고, 매뉴얼도 yes를 예상값으로 둔다. 이 상태를 "안전"으로 일반화할 수는 없다.
- **추정**: 매뉴얼 예상 "약 17 ms"보다 매핑 비용 실측이 1.9배 빠르다(9.04 ms). `iommu_map()` 호출당 비용이 개발 PC보다 낮은 것으로 보이나 원인은 확인하지 않았다.
- **추정**: 낮은 IOVA 기대값 6588 대비 6495(-1.4%), 256 GiB 기대 6419 대비 6330(-1.4%)으로 전 항목이 같은 비율로 낮다. 2차 측정과 날짜·상태가 달라 생긴 차이로 보며 경로 간 상대 비교에는 영향이 없다.
- **추정**: wr 4K qd1만 host가 745.6으로 gmem/map-pa(714.4)보다 4.4% 높다. 원인은 분리하지 않았다.

## 관측: sda ATA 오류

이번 커널 부팅에서 루트 LVM(vg0)의 PV인 `sda`(Intel SSDSCKKB240G8)에 NCQ 타임아웃과 읽기 오류가 났다.

| 부팅 | 커널 | `ata1.00` 로그 | `sda` I/O 오류 | failed command |
| --- | --- | --- | --- | --- |
| -2 (10-27 02:42) | `7.0.0-rc1-pal+` | 100 | 23 | 31 |
| -1 (10-27 02:58 ~ 11-02 04:55) | `7.0.0-38-generic` | 6 | 0 | 0 |
| 0 (11-02 05:23) | `7.3.0-rc7-gmem+` | 118 | 18 | 37 |
| 복구 후 (11-02 07:5x) | `7.0.0-38-generic` | 6 | 0 | 0 |

**측정**: 같은 패턴이 1차 PAL 커널 부팅에서도 났다. 두 커널은 같은 최소화 설정에서 파생됐고, 스톡 커널 두 번의 부팅은 모두 0건이다. 오류는 부팅 초기에 몰려 있고 파일시스템 오류는 없었다. **추정**: 이 커널 설정의 기존 특성이지 이번에 새로 생긴 문제는 아니다. 디스크 건강 상태는 확인하지 못했다(`smartctl` 미설치).

## 원상 복구

- 복구 재부팅 후: 커널 `7.0.0-38-generic`, NVIDIA L4 580.178.04, GPU compute app 0, grubenv 비어 있음(`next_entry` 없음).
- 시험 장치 `4e`/`67`/`cc`/`4d` 모두 `nvme` 드라이버, `/mnt/datasets` 미마운트(전과 동일), `gpu_gmem_provider` 미적재.
- gmem 커널 파일(`/boot/*-7.3.0-rc7-gmem+` 4개)과 `/root/pal-poc/gmem`은 사용자 결정 대기 중으로 남겨 두었다.

## 문서와 다르게 한 점

prerequisite `v7.3-rc7`을 GitHub이 아니라 git.kernel.org에서 받았다. 프록시가 GitHub의 linux 규모 ref 광고를 넘기지 못해(인증·protocol v2 헤더 무관, curl 30초·git 45~300초 전부 타임아웃) 같은 torvalds 태그를 git.kernel.org에서 받았다(127 KB, 0.68초). 4절 검증표의 번들 prerequisite 커밋 `24a19b953e2a`, `HEAD` `6766bffb9fc2`, tree `a6af7e15843c`가 모두 매뉴얼 기대값과 일치해 같은 트리임을 확인했다.

## 로그

`~/pal-poc-sid/logs/` — `g-precheck.txt`, `g-source.txt`, `g-kernel-config.txt`, `g-build.txt`, `g-install.txt`, `g-boot.txt`, `g-postboot.txt`, `g-J-4e.txt`, `g-K-4e.txt`, `g-L-4e.txt`, `g-recover.txt`, `g-verify.txt`.
