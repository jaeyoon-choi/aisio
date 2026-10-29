# sid PAL PoC 후속 측정 매뉴얼

이 문서는 sia에서 일하는 Claude에게 넘기는 2차 작업 지시서다. 1차 작업(`MANUAL.md`)은 2026-10-14~15에 끝났고, 그 결과는 `results-2026-10-15.md`와 `REPORT.md`에 있다. 이번 작업은 1차 결과가 남긴 질문 세 가지를 측정한다. 아래 "작업 지시" 절 전체를 붙여 넣는다.

## 작업 지시

너는 sid에서 PAL PoC의 후속 측정을 한다. 이 문서의 순서를 따르고, "멈춤"이라고 적힌 곳에서는 결과를 보고한 뒤 사용자의 답을 기다린다. 문서에 없는 판단이 필요하면 멈추고 묻는다.

### 0. 배경과 질문

1차 작업에서 sid는 PAL 커널(`7.0.0-rc1-pal+`)과 NVIDIA exporter 이식본으로 CUDA 메모리를 `IOMMU_IOAS_MAP_FILE`로 NVMe의 IOMMU에 매핑했다. 그 매핑으로 NVMe → GPU(C1)와 GPU → NVMe(C2)가 모두 데이터 일치했다. 시험 NVMe는 `0000:4e:00.0` 한 대였고, 그 경로는 같은 소켓 0 안에서 IIO 스택 4a에서 스택 30으로 가는 한 가지였다. 이번에 답할 질문은 셋이다.

1. 성능: PAL 경로가 지금 쓰는 `iommu_map_pa` 경로보다 느린가. 처리량, 지연, 매핑과 해제 비용을 같은 드라이버 코드로 비교한다(단계 E, F).
2. 경로: 다른 IIO 스택과 다른 소켓의 NVMe에서도 C1, C2가 되는가(단계 G).
3. 수명: dma-buf fd를 닫거나 CUDA 메모리를 해제하거나 프로세스가 강제 종료될 때, 매핑과 GPU 메모리가 안전하게 정리되는가(단계 H).

이를 위해 `src/pal_nvme.c`에 모드 네 가지를 더했다. 같은 NVMe 드라이버 코드에서 GPU 매핑 방식만 바꿔 비교하려는 것이다.

| 옵션 | 동작 |
| --- | --- |
| `--map-pa <BDF>` | GPU를 `IOMMU_IOAS_MAP_FILE` 대신 `iommu_map_pa` 모듈로 매핑한다. xNVMe와 같은 조건(2 MiB 페이지, IOVA 256 GiB)이다 |
| `--bench rd\|wr` | 큐 깊이 `--qd`(1~63)로 `--secs`초 동안 순차 I/O를 낸다. `rd`는 NVMe 읽기(장치가 GPU에 씀), `wr`는 NVMe 쓰기(장치가 GPU를 읽음)다. `--target host`면 GPU 대신 호스트 메모리 6 MiB를 대상으로 한다 |
| `--map-loop N` | GPU 매핑을 N번 해제하고 다시 매핑하며 지연을 잰다. 끝나면 C1, C2로 마지막 매핑을 확인한다 |
| `--lifecycle close\|free` | `close`는 매핑 뒤 dma-buf fd를 닫고 C 시험을 한다. `free`는 매핑을 쥔 채 fd를 닫고 `cuMemFree`한 뒤, 새 버퍼를 0x5a로 채우고 옛 IOVA로 DMA한다 |

`scripts/followup-run.sh <BDF> <SLBA> [parts]`가 한 장치에 대해 이 시험들을 차례로 실행한다. `parts`는 `c bench map life` 중에서 고른다. 개발 PC에서 이 스크립트를 미리 돌렸고 로그는 `devpc-raw/followup-trial-2026-10-26.log`에 있다. 개발 PC는 C2 방향이 플랫폼 제약으로 실패하므로(`REPORT.md` §7.3) 쓰기 측정은 빼고 돌렸다.

### 1. 규칙

1차 매뉴얼의 규칙을 그대로 따른다. 특히 다음을 지킨다.

1. `0000:4d:00.0`은 데이터셋 장치다. 어떤 명령에도 이 주소를 넣지 않는다. 스크립트도 이 주소를 거부한다.
2. 시험 장치와 덮어쓸 LBA 구간은 사용자가 정한다. `wr` 측정은 `SLBA`부터 `SPAN` 바이트(기본 1 GiB)를 덮어쓴다. 그 밖의 시험은 `SLBA`부터 384섹터(512 B 섹터 기준)만 쓴다.
3. 다음은 사용자 승인 없이 하지 않는다: sid 재부팅, `grub-reboot`, `grub-editenv`, `/boot`나 `/etc/default/grub` 변경, 패키지 설치.
4. 측정 중에는 GPU에 다른 프로세스가 없어야 한다. 스크립트가 `nvidia-smi`로 확인하고, 다른 프로세스가 있으면 멈춘다. `--lifecycle free`는 해제된 GPU 메모리를 다른 프로세스가 받으면 그 메모리를 덮어쓸 수 있다.
5. 명령이 실패하면 출력 전체를 보고한다. 실패를 고치려고 시험 프로그램이나 판정 기준을 바꾸지 않는다.
6. 측정한 것과 추정한 것을 보고에서 구분한다.

접속은 1차와 같다(`sid-raw/params.env`). `ssh jaeyoon@sid`로 비밀번호 인증을 한 뒤 sudo로 root 명령을 실행한다. 아래 명령은 `ssh jaeyoon@sid 'sudo ...'` 형태로 적었다. 1차 작업에서 비밀번호와 sudo를 처리한 방식(스크립트를 복사해 sudo로 실행하는 방식 등)이 따로 있으면 그 방식으로 바꿔 실행한다. 명령의 내용은 바꾸지 않는다.

### 2. sid의 현재 상태

1차 작업이 끝난 뒤 sid는 다음 상태로 남아 있다. 시작 전에 읽기만 해서 확인한다.

| 항목 | 상태 |
| --- | --- |
| 부팅 커널 | 기본 커널 `7.0.0-38-generic` |
| PAL 커널 | `/boot/*-7.0.0-rc1-pal+`, `/lib/modules/7.0.0-rc1-pal+`(NVIDIA, `dmabuf_import`, `iommu_map_pa` 포함)가 남아 있다 |
| GRUB | `/etc/default/grub`의 `GRUB_DEFAULT`를 `7.0.0-38-generic` 항목으로 고정했다(원래 값 0은 `sid-raw/sid-logs/grub.default.orig`). grubenv가 LVM 위에 있어 GRUB이 쓰지 못하므로 `grub-reboot`가 한 번만 적용되지 않는다 |
| 작업 폴더 | `/root/pal-poc/`(1차 묶음 `sid-bundle`, `linux-pal`, `nvidia-pal`, `upcie-pal`, CUDA 13 호환 헤더 `sid-cuda13-compat.h`) |

```sh
ssh jaeyoon@sid 'sudo bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/f-precheck.txt
uname -r
ls /boot | grep pal; ls /lib/modules/7.0.0-rc1-pal+/extra
grep -E '^GRUB_DEFAULT' /etc/default/grub; grub-editenv /boot/grub/grubenv list
ls /root/pal-poc /root/pal-poc/upcie-pal/iommu_map_pa/iommu_map_pa.h /root/pal-poc/sid-cuda13-compat.h
nvidia-smi --query-compute-apps=pid,name --format=csv
findmnt /mnt/datasets
EOS
```

### 3. 시험 장치 선택

1차 시험 장치 `4e:00.0`은 스위치를 거쳐 IIO 스택 4a에 있다. GPU(`31:00.0`)는 스택 30에 있다. 경로 질문에 답하려면 장치가 둘 더 필요하다. 1차 사전 점검에서 본 후보는 다음과 같다(`sid-raw/logs/precheck.txt`).

| 구분 | 후보 | 위치 |
| --- | --- | --- |
| 기준 | `0000:4e:00.0` | 소켓 0, 호스트 브리지 4a (1차와 같다) |
| 같은 소켓, 다른 스택 | `0000:67:00.0` ~ `0000:6e:00.0` | 소켓 0, 호스트 브리지 64 |
| 다른 소켓 | `0000:cc:00.0` ~ `0000:d3:00.0`, `0000:e5:00.0` ~ `0000:ec:00.0` | 소켓 1 |

각 후보의 경로와 마운트 여부를 읽는다.

```sh
ssh jaeyoon@sid 'sudo bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/f-candidates.txt
for b in 0000:4e:00.0 0000:67:00.0 0000:cc:00.0 0000:e5:00.0; do
  d=/sys/bus/pci/devices/$b
  echo "$b node=$(cat $d/numa_node) group=$(ls $d/iommu_group/devices | wc -l) path=$(readlink -f $d)"
done
grep nvme /proc/mounts
lsblk -no NAME,FSTYPE,MOUNTPOINT /dev/nvme*n1 2>/dev/null | grep -v '^$' | head -40
EOS
```

멈춤: 후보의 경로, 파일시스템, 마운트 여부를 보고한다. 사용자에게 다음을 받는다. 같은 소켓 다른 스택 장치 하나(`NVME_S0`), 다른 소켓 장치 하나(`NVME_S1`), 각 장치의 `SLBA`, 그리고 `wr` 측정이 덮어써도 되는 `SPAN`. 기준 장치는 `4e:00.0`, `SLBA` 0을 다시 쓸지 확인한다. 받은 값은 sia 셸에서 `export SLBA=... SPAN=... NVME_S0=... SLBA_S0=... NVME_S1=... SLBA_S1=...`로 두고 이후 명령에 쓴다. `SLBA`는 기준 장치의 값이다.

### 4. PAL 커널 부팅

PAL 커널은 이미 설치되어 있다. 1차와 같은 방법으로 한 번만 부팅한다. 사용자 승인을 받은 뒤 한다. GRUB 항목 이름은 `grub.cfg`에서 확인해 맞춘다.

```sh
ssh jaeyoon@sid 'sudo bash -c "grub-reboot \"Advanced options for Ubuntu>Ubuntu, with Linux 7.0.0-rc1-pal+\" && grub-editenv /boot/grub/grubenv list && systemctl reboot"'
```

부팅 뒤 `uname -r`이 `7.0.0-rc1-pal+`인지 보고, 곧바로 `next_entry`를 지운다. 지우지 않으면 다음 재부팅도 PAL 커널로 간다.

```sh
ssh jaeyoon@sid 'sudo bash -c "uname -r; grub-editenv /boot/grub/grubenv unset next_entry; grub-editenv /boot/grub/grubenv list; modprobe nvidia; modprobe nvidia-uvm; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader"'
```

### 5. 도구 갱신과 빌드

sia에서 브랜치를 받아 새 소스와 스크립트를 sid로 복사한다. `<clone>`은 1차 때 받은 `jaeyoon-choi/aisio` 클론이다.

```sh
git -C <clone> fetch origin poc/iommufd-pal && git -C <clone> checkout poc/iommufd-pal && git -C <clone> pull --ff-only
cd <clone>/notes/pal-poc
ssh jaeyoon@sid 'mkdir -p ~/pal-poc-f'
scp src/pal_nvme.c scripts/followup-run.sh scripts/bind-vfio.sh scripts/restore-nvme.sh jaeyoon@sid:~/pal-poc-f/
ssh jaeyoon@sid 'sudo bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/f-build.txt
set -e
mkdir -p /root/pal-poc/followup && cp ~jaeyoon/pal-poc-f/* /root/pal-poc/followup/
cd /root/pal-poc/followup
cp /root/pal-poc/upcie-pal/dmabuf_import/dmabuf_import.h .
cp /root/pal-poc/upcie-pal/iommu_map_pa/iommu_map_pa.h .
gcc -O2 -Wall -I. -I/usr/local/cuda/include -include /root/pal-poc/sid-cuda13-compat.h -o pal_nvme pal_nvme.c -lcuda
chmod +x followup-run.sh bind-vfio.sh restore-nvme.sh
md5sum pal_nvme.c; ls -l pal_nvme
EOS
```

빌드 경고나 오류가 있으면 보고한다. `md5sum`은 sia 클론의 `src/pal_nvme.c`와 같아야 한다.

### 6. 단계 E와 F: 기준 장치에서 성능 비교

기준 장치에서 정합성(c), 처리량(bench), 매핑 비용(map)을 잰다. `SECS=10`이면 처리량 측정 12회에 약 3분이 걸린다.

```sh
ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/followup && SECS=10 SPAN=$SPAN ./followup-run.sh 0000:4e:00.0 $SLBA \"c bench map\"; ./restore-nvme.sh 0000:4e:00.0'" 2>&1 | tee ~/pal-poc-sid/logs/f-E-4e.txt
```

스크립트는 시작할 때 `nvidia-smi`로 GPU가 비었는지 확인하고, 장치를 vfio-pci에 묶은 뒤 시험을 차례로 실행한다. 끝나면 `restore-nvme.sh`로 장치를 nvme 드라이버에 되돌린다. 각 시험의 출력 끝 줄 `rc=`가 0이면 통과다. 처리량 줄은 `bench result:`로, 매핑 비용 줄은 `map-loop`로 시작한다. 출력의 `nvme: mdts=` 줄이 128 KiB보다 작은 값을 보이고 `--xfer 131072 exceeds MDTS`가 나오면, `XFER_BIG=65536`을 붙여 다시 실행하고 그 사실을 보고한다.

예상값은 다음과 같다. 개발 PC 열은 `devpc-raw/followup-trial-2026-10-26.log`의 실측이다. sid 열은 원리에서 끌어낸 예상이며 "가정"이라고 표시한다.

| 항목 | 개발 PC 실측 | sid 예상 | 근거 |
| --- | --- | --- | --- |
| c: C1, C2, `--map-pa` C1, C2 | C1 MATCH, C2 `sc=0x4` | 모두 MATCH | 1차 결과 |
| rd 128K qd32: PAL 대 map-pa | 6788.6 대 6788.2 MB/s | 차이 3% 이내 (가정) | 두 경로 모두 2 MiB PTE이고, 매핑 뒤의 DMA 경로는 같다 |
| rd 4K qd1 지연 p50: PAL 대 map-pa | 6.1 대 6.1 µs | 차이 없음 (가정) | 같은 이유다 |
| wr 128K qd32: PAL 대 map-pa | 측정 불가 | 차이 3% 이내 (가정) | 같은 이유다. 절댓값은 sid에서 처음 잰다 |
| GPU 대 host 대상 | rd 6788 대 7204 MB/s | GPU가 같거나 낮음 (가정) | P2P는 메시를 한 번 더 지난다 |
| map-loop 1 GiB map p50: PAL 대 map-pa | 4.9 대 82.8 µs | PAL이 더 빠름 (가정) | `iommu_map_pa`는 2 MiB마다 `iommu_map()`을 따로 부른다 |
| map-loop unmap p50: PAL 대 map-pa | 4.7 대 3.0 µs | 비슷함 (가정) | 개발 PC 실측 |

멈춤: 아래 표를 채워 보고한다. PAL과 map-pa의 처리량 차이가 5%를 넘으면, 같은 명령을 한 번 더 실행해 재현되는지 함께 보고한다.

| 시험 | PAL | map-pa | host |
| --- | --- | --- | --- |
| rd 4K qd1 (MB/s, p50 µs) | | | |
| rd 128K qd32 (MB/s, p99 µs) | | | |
| wr 4K qd1 | | | |
| wr 128K qd32 | | | |
| map p50/p99 (µs) | | | 없음 |
| unmap p50/p99 (µs) | | | 없음 |

### 7. 단계 G: 다른 스택과 다른 소켓의 경로

먼저 정합성만 본다. 다른 소켓 경로는 UPI를 지나는 P2P다. Intel이 이 경로를 지원하는지는 확인하지 못했다. 읽기 요청이 완료 시간 초과로 끝나면 AER 로그가 남을 수 있다.

```sh
sid_c() {
  ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/followup && ./followup-run.sh $1 $2 c; ./restore-nvme.sh $1; lspci -vvv -s ${1#0000:} | grep -E \"DevSta|UESta\"'" 2>&1 | tee ~/pal-poc-sid/logs/f-G-c-${1#0000:}.txt
}
sid_c $NVME_S0 $SLBA_S0
sid_c $NVME_S1 $SLBA_S1
```

멈춤: 장치마다 C1, C2, `--map-pa` C1, C2와 dmesg의 DMAR, AER 줄을 보고한다. C2가 실패하면 NVMe의 상태 코드와 AER 줄을 그대로 옮긴다. 사용자가 승인하면 정합성을 통과한 장치에서 처리량을 잰다. C1이 실패한 장치는 처리량을 재지 않고, C2만 실패한 장치는 wr 측정을 뺀다. 아래 예시의 두 번째 줄은 C2가 실패했을 때의 형태다.

```sh
sid_bench() {
  ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/followup && SECS=10 SPAN=$SPAN WR=${3:-1} ./followup-run.sh $1 $2 bench; ./restore-nvme.sh $1'" 2>&1 | tee ~/pal-poc-sid/logs/f-G-bench-${1#0000:}.txt
}
sid_bench $NVME_S0 $SLBA_S0      # C1, C2를 모두 통과한 장치
sid_bench $NVME_S1 $SLBA_S1 0    # 세 번째 인자 0은 wr 측정을 뺀다. C2가 실패한 장치에 쓴다
```

| 경로 | C1 | C2 | rd 128K qd32 PAL (MB/s) | wr 128K qd32 PAL (MB/s) |
| --- | --- | --- | --- | --- |
| 소켓 0, 스택 4a → 30 (`4e:00.0`) | | | | |
| 소켓 0, 스택 64 → 30 | | | | |
| 소켓 1 → 소켓 0 스택 30 | | | | |

### 8. 단계 H: 수명 시나리오

기준 장치에서 수명 시험을 실행한다.

```sh
ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/followup && ./followup-run.sh 0000:4e:00.0 $SLBA life; ./restore-nvme.sh 0000:4e:00.0'" 2>&1 | tee ~/pal-poc-sid/logs/f-H-4e.txt
```

시험은 다섯 가지다. 개발 PC 실측 열은 C2 방향이 실패하는 플랫폼에서 얻은 값이다.

| 시험 | 확인하는 것 | 개발 PC 실측 | sid 예상 |
| --- | --- | --- | --- |
| close (PAL, map-pa) | fd를 닫아도 iommufd와 `iommu_map_pa`가 dma-buf 참조를 쥐어 매핑이 유지되는가 | C1 MATCH, unmap 뒤 GPU 메모리 반환 | C1, C2 MATCH (가정) |
| free: `cuMemFree` 직후 CUDA 여유 메모리 | 매핑이 남아 있는 동안 NVIDIA가 메모리를 실제로 해제하는가 | 해제 전과 같음(22717 MiB). 해제하지 않음 | 같음 (가정) |
| free: F1 새 버퍼 | 옛 IOVA로 쓴 데이터가 새 버퍼를 덮어쓰는가 | intact, 새 버퍼 물리주소가 다름 | intact (가정) |
| free: F2 | 옛 IOVA가 아직 옛 메모리를 가리키는가 | 측정 불가(C2 방향) | yes (가정) |
| free: unmap 뒤 여유 메모리 | 매핑을 풀면 메모리가 돌아오는가 | 1 GiB 반환(23741 MiB) | 반환 (가정) |
| kill -9 | I/O 중 강제 종료 뒤 장치와 GPU 메모리가 정리되는가 | 다음 실행 C1 MATCH, 메모리 15 MiB로 복귀, 커널 경고 없음 | 같음 (가정) |

F1이 `CHANGED`로 나오면 해제된 메모리를 살아 있는 매핑이 가리킨다는 뜻이다. 이 경우 곧바로 멈추고, 그 출력과 dmesg 전체를 보고한다.

멈춤: 표를 채우고 dmesg에서 `BUG`, `WARNING`, `DMAR`, `AER`, `NVRM` 줄을 함께 보고한다. 개발 PC에서는 호스트 메모리가 부족할 때 CUDA 컨텍스트 생성 중 `NVRM: ... Out of memory`가 찍혔고, 드라이버는 기본 페이지 크기로 다시 시도해 계속 진행했다. 같은 줄이 보이면 `free -g` 출력과 함께 보고한다.

### 9. 원상 복구

1. 각 시험 장치가 nvme 드라이버로 돌아왔는지 본다.
2. 사용자 승인 뒤 sid를 재부팅한다. `next_entry`를 지웠으므로 기본 커널로 부팅된다.
3. 부팅 뒤 `uname -r`, `nvidia-smi`, `findmnt /mnt/datasets`를 확인한다.
4. 사용자에게 다음 두 가지를 묻는다. 묻기만 하고, 답을 받기 전에는 실행하지 않는다.
   - `/etc/default/grub`의 `GRUB_DEFAULT`를 원래 값 0으로 되돌릴지. 되돌리면 `update-grub` 뒤 버전 정렬상 PAL 커널이 기본이 될 수 있으므로, PAL 커널 파일을 먼저 지울지와 함께 정해야 한다.
   - PAL 커널 파일(`/boot/*-pal+`, `/lib/modules/*-pal+`)과 `/root/pal-poc`를 지울지.

```sh
ssh jaeyoon@sid "for b in 0000:4e:00.0 $NVME_S0 $NVME_S1; do echo \$b \$(basename \$(readlink -f /sys/bus/pci/devices/\$b/driver)); done; sudo grub-editenv /boot/grub/grubenv list"
```

### 10. 보고

sid의 로그와 sia의 `~/pal-poc-sid/logs/f-*.txt`를 한 폴더에 모은다. 보고서는 `results-<날짜>.md` 하나로 쓰고, 6~8절의 표를 채운 뒤 짧은 해석을 붙인다. 해석에는 다음을 적는다.

- PAL과 `iommu_map_pa`의 처리량, 지연, 매핑 비용 차이와 그 차이가 측정 오차 안에 드는지.
- 경로별 C2 결과. 다른 소켓에서 실패했다면 상태 코드와 AER 근거.
- `cuMemFree` 뒤 메모리가 매핑 해제까지 유지되는지와 그것이 `iommu_map_pa` 대체에 주는 의미.
- 측정한 것과 추정한 것의 구분.

### 11. 추가 측정: 읽기 처리량의 측정 순서 효과

2026-10-26 측정(`results-2026-10-26.md`)에서 rd 128K qd32는 PAL이 `iommu_map_pa`보다 3~4.5% 높게 나왔다. 그런데 그때의 `followup-run.sh`는 PAL rd → PAL wr → map-pa rd → map-pa wr → host rd 순서로 측정했다. 그래서 PAL 읽기만 쓰기 부하 없이 측정됐고, map-pa와 host 읽기는 1 GiB 쓰기 직후에 측정됐다. 쓰기 직후 읽기의 p99는 879~930 µs로, PAL의 636 µs보다 높다. 4K qd1에서도 쓰기가 낀 실행에서만 PAL이 6% 높았고, 읽기만 한 추가 3회에서는 세 경로가 0.3% 안에서 같았다. 이 절은 128K qd32의 차이가 측정 순서에서 생겼는지를 확인한다.

`followup-run.sh`의 bench 부분은 이제 다음 순서로 실행한다. `WR=1`이면 먼저 host 대상 쓰기로 구간을 3초 동안 채우고 `SETTLE`초(기본 30초) 쉰다. 그다음 `ORDER`(기본 `pal pa host`) 순서로 모든 경로의 읽기를 잰 뒤, 쓰기를 잰다. 이번 추가 측정은 `WR=0`으로 읽기만 한다. `4e:00.0`의 LBA 0부터 1 GiB는 10-26 측정에서 이미 여러 번 썼으므로 채우기는 필요 없다. 이 측정은 장치에 쓰지 않는다.

PAL 커널 부팅은 4절과 같다(승인 뒤 `grub-reboot`, 부팅 직후 `next_entry` 해제). 도구는 5절처럼 브랜치에서 `scripts/followup-run.sh`를 다시 받아 `/root/pal-poc/followup/`에 덮어쓴다. `pal_nvme.c`는 바뀌지 않았으므로 다시 빌드하지 않는다.

```sh
for order in "pal pa host" "host pa pal" "pa pal host" "pal pa host"; do
  ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/followup && SECS=10 WR=0 ORDER=\"$order\" ./followup-run.sh 0000:4e:00.0 0 bench'" 2>&1 | tee -a ~/pal-poc-sid/logs/f-order-4e.txt
done
ssh jaeyoon@sid "sudo /root/pal-poc/followup/restore-nvme.sh 0000:4e:00.0"
```

네 번 실행에 약 5분이 걸린다. 경로 순서를 바꿔 가며 반복하므로, 순서 효과가 있으면 같은 경로라도 앞에 올 때와 뒤에 올 때의 값이 달라진다. 개발 PC에서 같은 순서 변경을 시험했다(`devpc-raw/order-test-2026-10-26.log`). 읽기만 한 실행에서 rd 128K qd32는 PAL 6786.1, map-pa 6783.8 MB/s로 같았다.

| 예상 | 근거 |
| --- | --- |
| rd 128K qd32에서 PAL과 map-pa의 차이가 1% 이내 (가정) | 매핑 뒤 DMA 경로가 같고, 읽기만 한 4K qd1에서 차이가 0.3% 이내였다 |
| 같은 경로의 값이 순서와 관계없이 1% 이내 (가정) | 쓰기가 없으면 장치 상태가 실행 사이에 바뀌지 않는다 |

멈춤: 아래 표를 채워 보고한다. 칸마다 rd 128K qd32 MB/s와 p99 µs를 적고, 4K qd1 MB/s도 따로 적는다. 9절의 원상 복구(재부팅)는 이 측정 뒤에 한다.

| 실행 | 순서 | PAL | map-pa | host |
| --- | --- | --- | --- | --- |
| 1 | pal pa host | | | |
| 2 | host pa pal | | | |
| 3 | pa pal host | | | |
| 4 | pal pa host | | | |

### 12. 추가 측정: `iommu_map_pa` 처리량 차이의 원인 분리

11절 측정(`results-2026-10-27.md`)에서 rd 128K qd32는 PAL과 host 대상이 6588 MB/s로 같았고, `iommu_map_pa`만 6419 MB/s로 2.6% 낮았다. 두 경로는 매핑 방식(iommufd의 `IOMMU_IOAS_MAP_FILE`과 `iommu_map()` 반복)과 GPU IOVA 위치(`0xa00000`과 256 GiB)가 다르다. 이 절은 두 요인을 분리하고, sid에서 두 경로의 PTE를 비교한다.

`pal_nvme`에 `--gpu-iova`를 더했다. 이 옵션은 어느 경로든 GPU 매핑을 지정한 IOVA에 둔다. `followup-run.sh`의 `iova` 부분은 다음 네 조합과 host 대상을 정방향과 역방향으로 한 번씩, 모두 읽기만 측정한다.

| 기호 | 매핑 방식 | GPU IOVA |
| --- | --- | --- |
| a | PAL | `0xa00000` (기본) |
| b | PAL | 256 GiB (`0x4000000000`) |
| c | `iommu_map_pa` | 256 GiB (기본) |
| d | `iommu_map_pa` | 1 GiB (`0x40000000`) |

`pte` 부분은 두 경로 각각에서 읽기 측정을 하는 동안 VT-d debugfs의 2 MiB 리프 엔트리를 센다. 하위 비트별 개수도 함께 출력한다.

PAL 커널 부팅은 4절과 같다. 이번에는 `pal_nvme.c`도 바뀌었으므로 5절처럼 `src/pal_nvme.c`와 `scripts/followup-run.sh`를 다시 복사하고 다시 빌드한다. 빌드 뒤 `md5sum pal_nvme.c`를 sia 클론의 값과 대조한다.

```sh
ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/followup && SECS=10 ./followup-run.sh 0000:4e:00.0 0 \"iova pte\"; ./restore-nvme.sh 0000:4e:00.0'" 2>&1 | tee ~/pal-poc-sid/logs/f12-iova-4e.txt
```

장치에는 쓰지 않는다. 약 2분이 걸린다. 개발 PC에서 같은 명령을 시험했고 네 조합 모두 6785~6787 MB/s였다(`devpc-raw/iova-test-2026-10-27.log`). 개발 PC에서는 두 경로의 PTE도 같았다(`devpc-raw/pte-compare-2026-10-27.log`).

결과는 다음 셋 중 하나로 읽는다.

| 결과 | 뜻 |
| --- | --- |
| a와 b가 6588, c와 d가 6419 | 매핑 방식이 원인이다. IOVA 위치는 관계없다 |
| a와 d가 6588, b와 c가 6419 | IOVA 위치(256 GiB)가 원인이다. 매핑 방식은 관계없다 |
| 그 밖의 형태 | 두 요인이 섞였거나 다른 요인이 있다. 그대로 보고한다 |

PTE 출력에서 두 경로의 2 MiB 리프 개수(512)와 하위 비트가 다르면, 그 차이를 함께 보고한다.

멈춤: 아래 표와 PTE 요약을 보고한다. 그 뒤 9절대로 원상 복구한다.

| 조합 | 정방향 (MB/s, p50 µs) | 역방향 (MB/s, p50 µs) |
| --- | --- | --- |
| a PAL, `0xa00000` | | |
| b PAL, 256 GiB | | |
| c map-pa, 256 GiB | | |
| d map-pa, 1 GiB | | |
| host | | |

## 묶음 구성 (이번에 바뀐 것)

| 경로 | 내용 |
| --- | --- |
| `src/pal_nvme.c` | `--map-pa`, `--bench`, `--map-loop`, `--lifecycle`, `--gpu-iova`(12절) 추가. Identify Controller로 MDTS를 읽어 `--xfer`가 넘으면 거부한다. vfio 모드의 호스트 메모리를 8 MiB로 늘렸다 |
| `scripts/followup-run.sh` | 한 장치에 대해 c, bench, map, life를 차례로 실행한다. GPU에 다른 프로세스가 있으면 멈춘다. bench는 구간 채우기, 모든 경로의 읽기, 모든 경로의 쓰기 순서로 실행한다(11절). `iova`와 `pte` 부분은 12절에서 쓴다 |
| `devpc-raw/followup-trial-2026-10-26.log` | 개발 PC에서 `SECS=3 WR=0`으로 미리 돌린 로그 |
| `devpc-raw/order-test-2026-10-26.log` | 개발 PC에서 바뀐 bench 순서를 시험한 로그 |
| `devpc-raw/iova-test-2026-10-27.log`, `devpc-raw/pte-compare-2026-10-27.log` | 개발 PC에서 12절 시험과 PTE 비교를 미리 한 로그 |
