# sid guest_memfd export PoC 매뉴얼

이 문서는 sia에서 일하는 Claude에게 넘기는 3차 작업 지시서다. 1차(`MANUAL.md`)와 2차(`MANUAL-followup.md`) 작업은 PAL 경로를 측정했다. 이번 작업은 다른 업스트림 경로인 guest_memfd export를 같은 도구로 측정한다. 아래 "작업 지시" 절 전체를 붙여 넣는다.

## 작업 지시

너는 sid에서 guest_memfd export PoC를 측정한다. 이 문서의 순서를 따르고, "멈춤"이라고 적힌 곳에서는 결과를 보고한 뒤 사용자의 답을 기다린다. 문서에 없는 판단이 필요하면 멈추고 묻는다.

### 0. 배경과 질문

1차와 2차 작업에서 sid는 PAL 커널로 CUDA 메모리를 `IOMMU_IOAS_MAP_FILE`에 매핑했다. C1(NVMe → GPU)과 C2(GPU → NVMe)가 모두 데이터 일치했고, 처리량은 host 대상과 같았으며, 1 GiB 매핑은 4.1 µs로 `iommu_map_pa`(33.5 µs)보다 빨랐다(`results-2026-10-26.md`, `results-2026-10-27-iova.md`).

이번에 측정하는 경로는 Fred Griffoul의 [guest_memfd export RFC](https://lore.kernel.org/all/20261027154649.91571-1-griffoul@gmail.com/)(2026-10-27)다. 이 RFC에서는 iommufd가 dma-buf가 아니라 guest_memfd 파일을 `IOMMU_IOAS_MAP_FILE`로 받는다. guest_memfd는 KVM이 VM 메모리를 담는 파일인데, Ackerley Tng의 [alternative providers RFC v2](https://lore.kernel.org/all/20261022-gmem-alternative-providers-v2-0-5dd1dc6c660a@google.com/)가 페이지 할당자 밖의 메모리(PFN mode provider)로 guest_memfd를 채울 수 있게 했다. NVIDIA에는 provider가 없으므로 브리지 모듈 `gpu_gmem_provider`가 NVIDIA dma-buf의 BAR1 구간을 provider로 내보낸다. guest_memfd는 VM fd로만 만들 수 있으므로 `pal_nvme --gmem`은 vCPU도 메모리 슬롯도 없는 빈 VM을 하나 만든다.

개발 PC에서 이 경로를 먼저 시험했다(`results-2026-10-30-gmem.md`). 매핑, C1, D(미매핑 IOVA 보호), 수명 시나리오는 통과했고, 처리량은 `iommu_map_pa`와 0.05% 안에서 같았다. 다만 RFC의 iommufd 코드가 4 KiB마다 `iommu_map()`을 부르므로 1 GiB 매핑에 44 ms가 들었다. 개발 PC는 C2 방향을 시험할 수 없다. 이번 작업은 다음 질문에 답한다.

1. 정합성: guest_memfd 경로로 C1과 C2가 모두 되는가(단계 J).
2. 성능: 4 KiB 리프가 읽기와 쓰기 처리량을 낮추는가. 매핑 비용은 얼마인가(단계 K).
3. 수명: fd 닫기, `cuMemFree`, 강제 종료에서 매핑과 GPU 메모리가 안전하게 정리되는가. 개발 PC에서 측정하지 못한 F2(옛 IOVA가 옛 메모리를 가리키는가)를 포함한다(단계 L).

### 1. 규칙

1차와 2차 매뉴얼의 규칙을 그대로 따른다. 특히 다음을 지킨다.

1. `0000:4d:00.0`은 데이터셋 장치다. 어떤 명령에도 이 주소를 넣지 않는다. 스크립트도 이 주소를 거부한다.
2. 시험 장치와 덮어쓸 LBA 구간은 사용자가 정한다. `wr` 측정은 `SLBA`부터 `SPAN` 바이트를 덮어쓴다. 그 밖의 시험은 `SLBA`부터 384섹터만 쓴다.
3. 다음은 사용자 승인 없이 하지 않는다: sid 재부팅, `grub-reboot`, `grub-editenv`, `/boot`나 `/lib/modules`나 `/etc/default/grub` 변경, 패키지 설치.
4. 측정 중에는 GPU에 다른 프로세스가 없어야 한다. 스크립트가 `nvidia-smi`로 확인한다.
5. 명령이 실패하면 출력 전체를 보고한다. 실패를 고치려고 시험 프로그램, 패치, 판정 기준을 바꾸지 않는다.
6. 측정한 것과 추정한 것을 보고에서 구분한다.
7. 기존 PAL 커널 파일(`*-7.0.0-rc1-pal+`)과 `/root/pal-poc`의 1차, 2차 파일은 지우지 않는다. 이번 작업의 파일은 `/root/pal-poc/gmem` 아래에 둔다.

접속은 2차와 같다. `ssh jaeyoon@sid`로 들어가 sudo로 root 명령을 실행한다. 아래 명령은 `ssh jaeyoon@sid 'sudo ...'` 형태로 적었다. 2차 작업에서 비밀번호와 sudo를 처리한 방식이 따로 있으면 그 방식으로 실행하고, 명령의 내용은 바꾸지 않는다.

### 2. 사전 점검

읽기만 한다.

```sh
ssh jaeyoon@sid 'sudo bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/g-precheck.txt
uname -r
ls /boot | grep -E 'pal|gmem'
grep -E '^GRUB_DEFAULT' /etc/default/grub; grub-editenv /boot/grub/grubenv list
ls /root/pal-poc /root/pal-poc/sid-cuda13-compat.h
ls -d /usr/src/nvidia-580.178.04 /usr/src/upcie-experimental-0.9.0
echo "vmx $(grep -c -w vmx /proc/cpuinfo)"; ls -l /dev/kvm; lsmod | grep -E '^kvm'
git --version; dpkg -l libdw-dev flex bison libelf-dev libssl-dev 2>/dev/null | awk '/^ii/{print $2}'
df -h /root /boot
nvidia-smi --query-compute-apps=pid,name --format=csv
findmnt /mnt/datasets
EOS
```

| 항목 | 기대값 | 다를 때 |
| --- | --- | --- |
| 부팅 커널 | `7.0.0-38-generic` | 보고한다 |
| GRUB | `GRUB_DEFAULT`가 `7.0.0-38-generic` 항목, `next_entry` 없음 | 보고한다 |
| 소스 | `/usr/src/nvidia-580.178.04`, `/usr/src/upcie-experimental-0.9.0` | 멈춤. 패치가 이 두 버전을 기준으로 한다 |
| VT-x | `vmx`가 0보다 크고 `/dev/kvm`이 있음 | 멈춤. BIOS에서 VT-x가 꺼져 있으면 guest_memfd를 만들 수 없다 |
| 도구 | 다섯 패키지 모두 설치됨 | 빠진 것을 보고하고 설치 승인을 받는다 |
| 공간 | `/root`에 30 GiB 이상, `/boot`에 500 MiB 이상 여유 | 멈춤 |
| GPU | 다른 프로세스 없음 | 보고한다 |

### 3. 시험 장치

2차 작업의 기준 장치 `0000:4e:00.0`(소켓 0, 호스트 브리지 4a)을 다시 쓴다. 경로 질문은 2차 작업에서 답했으므로 이번에는 장치 하나만 쓴다.

멈춤: 사전 점검 결과를 보고하고, 사용자에게 기준 장치의 `SLBA`와 `SPAN`을 받는다. 2차 작업은 `SLBA=0`, `SPAN=1073741824`(1 GiB)를 썼다. 받은 값은 sia 셸에서 `export SLBA=... SPAN=...`로 둔다.

### 4. 커널 소스

커널은 kvm.git의 `7e60162b16f9` 위에 두 RFC 64편을 적용한 트리다. sid의 프록시는 git smart-HTTP의 큰 ref 광고를 넘기지 못해서, 1차 작업은 GitHub 토큰 인증으로 우회했다(`sid-raw/REPORT.md`). kvm.git(git.kernel.org)은 이 방법으로 받을 수 없고 프록시를 넘는지도 확인하지 않았으므로, 개발 PC에서 이 트리를 465 KiB짜리 git bundle로 만들었다. bundle은 v7.3-rc7 위에 kvm.git 트리를 커밋 하나로 얹고 RFC 64편을 쌓은 것이고, v7.3-rc7 커밋 하나만 전제로 한다. sid는 GitHub에서 v7.3-rc7을 깊이 1로 받은 뒤 bundle을 가져온다.

sia에서 브랜치를 갱신하고 이번 묶음을 sid로 복사한다. `<clone>`은 2차 때 쓴 `jaeyoon-choi/aisio` 클론이다.

```sh
git -C <clone> fetch origin poc/iommufd-pal && git -C <clone> checkout poc/iommufd-pal && git -C <clone> pull --ff-only
cd <clone>/notes/pal-poc
ssh jaeyoon@sid 'mkdir -p ~/pal-poc-g'
scp -r patches/linux-gmem-on-v7.3-rc7.bundle patches/nvidia-580.178.04-bar1-ranges.patch \
  patches/upcie-experimental-0.9.0-gmem-kernel.patch src/gpu_gmem_provider src/pal_nvme.c \
  scripts/followup-run.sh scripts/bind-vfio.sh scripts/restore-nvme.sh jaeyoon@sid:~/pal-poc-g/
md5sum patches/linux-gmem-on-v7.3-rc7.bundle src/pal_nvme.c
```

sid에서 트리를 만든다. GitHub 접근에는 1차 작업에서 프록시를 넘으려고 쓴 인증 방식을 그대로 쓴다. 토큰은 로그나 파일에 남기지 않는다.

```sh
ssh jaeyoon@sid 'sudo bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/g-source.txt
set -e
mkdir -p /root/pal-poc/gmem && cp -r ~jaeyoon/pal-poc-g/* /root/pal-poc/gmem/
cd /root/pal-poc/gmem
md5sum linux-gmem-on-v7.3-rc7.bundle pal_nvme.c
git init -q linux-gmem && cd linux-gmem
git fetch --depth 1 https://github.com/torvalds/linux.git refs/tags/v7.3-rc7:refs/tags/v7.3-rc7
git bundle verify ../linux-gmem-on-v7.3-rc7.bundle
git fetch ../linux-gmem-on-v7.3-rc7.bundle gmem-export-poc-v7.3-rc7:gmem
git checkout -q gmem
git rev-parse HEAD HEAD^{tree}
EOS
```

| 항목 | 기대값 |
| --- | --- |
| `md5sum` | sia 클론의 값과 같다 |
| `git bundle verify` | `is okay` |
| `HEAD` | `6766bffb9fc2acbd8d4f0eb177562accb3a752dc` |
| `HEAD^{tree}` | `a6af7e15843c6a6c29d07c408b034f1b5d119a68` (개발 PC 커널과 같은 트리) |

트리 해시가 다르면 멈춘다.

### 5. 빌드와 설치

**커널 설정.** sid에서 부팅이 확인된 PAL 커널 설정(`/boot/config-7.0.0-rc1-pal+`)에서 시작한다. 이 설정은 1차 작업에서 sid의 모듈 목록으로 줄였고, 루트 LVM에 필요한 dm을 커널에 넣었다. 여기에 KVM을 더한다. `KVM_GUEST_MEMFD`는 x86_64에서 KVM이 자동으로 선택한다.

```sh
ssh jaeyoon@sid 'sudo bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/g-kernel-config.txt
set -e
cd /root/pal-poc/gmem/linux-gmem
cp /boot/config-7.0.0-rc1-pal+ .config
./scripts/config --set-str LOCALVERSION "-gmem" \
  -e VIRTUALIZATION -m KVM -m KVM_INTEL \
  -e IOMMUFD -e INTEL_IOMMU -e INTEL_IOMMU_DEBUGFS -e IOMMU_DEBUGFS \
  -m VFIO -m VFIO_PCI -e VFIO_DEVICE_CDEV -e PCI_P2PDMA -e DMA_SHARED_BUFFER \
  -e DEBUG_INFO_NONE -d DEBUG_INFO_BTF -d KASAN
make olddefconfig >/dev/null
grep -E '^CONFIG_(KVM|KVM_INTEL|KVM_GUEST_MEMFD|IOMMUFD|VFIO_PCI|VFIO_DEVICE_CDEV|PCI_P2PDMA|INTEL_IOMMU_DEBUGFS|BLK_DEV_DM)=' .config
make -s kernelrelease
EOS
```

`KVM=m`, `KVM_INTEL=m`, `KVM_GUEST_MEMFD=y`, `IOMMUFD=y`, `VFIO_DEVICE_CDEV=y`, `BLK_DEV_DM=y`가 있어야 하고, 릴리스는 `7.3.0-rc7-gmem+`이어야 한다. 다르면 멈춘다. 빌드는 1차처럼 백그라운드로 실행한다. 끝나면 `pal_nvme`가 쓸 uapi 헤더를 `usr/include`에 설치한다.

```sh
ssh jaeyoon@sid 'sudo bash -c "cd /root/pal-poc/gmem/linux-gmem && nohup sh -c \"make -j\$(nproc) && make headers_install\" > build.log 2>&1; echo exit=\$? >> build.log"' &
```

**NVIDIA, upcie, 브리지 모듈, pal_nvme.** 커널 빌드가 `exit=0`으로 끝난 뒤 실행한다.

```sh
ssh jaeyoon@sid 'sudo bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/g-build.txt
set -e
G=/root/pal-poc/gmem; K=$G/linux-gmem
grep -q '^exit=0' $K/build.log || { tail -20 $K/build.log; exit 1; }
rm -rf $G/nvidia-gmem && cp -r /usr/src/nvidia-580.178.04 $G/nvidia-gmem && cd $G/nvidia-gmem
patch -p1 --dry-run < $G/nvidia-580.178.04-bar1-ranges.patch && patch -p1 < $G/nvidia-580.178.04-bar1-ranges.patch
make -j16 SYSSRC=$K NV_EXCLUDE_KERNEL_MODULES=nvidia-peermem modules > build.log 2>&1 || { grep -E 'error' build.log | head; exit 1; }
ls -l nvidia.ko nvidia-uvm.ko nvidia-modeset.ko nvidia-drm.ko; modinfo -F vermagic nvidia.ko
grep -E 'nv_dma_buf_(get|put)_bar1_ranges' Module.symvers
rm -rf $G/upcie-gmem && cp -r /usr/src/upcie-experimental-0.9.0 $G/upcie-gmem && cd $G/upcie-gmem
patch -p1 < $G/upcie-experimental-0.9.0-gmem-kernel.patch
make KDIR=$K > build.log 2>&1 || { tail -20 build.log; exit 1; }
ls -l dmabuf_import/dmabuf_import.ko iommu_map_pa/iommu_map_pa.ko
cd $G/gpu_gmem_provider && make KDIR=$K NVSYMVERS=$G/nvidia-gmem/Module.symvers > build.log 2>&1 || { tail -20 build.log; exit 1; }
ls -l gpu_gmem_provider.ko
mkdir -p $G/run && cd $G/run
cp $G/pal_nvme.c $G/followup-run.sh $G/bind-vfio.sh $G/restore-nvme.sh .
cp $G/gpu_gmem_provider/gpu_gmem_provider.h $G/upcie-gmem/dmabuf_import/dmabuf_import.h $G/upcie-gmem/iommu_map_pa/iommu_map_pa.h .
gcc -O2 -Wall -DPAL_NVME_GMEM -I$K/usr/include -I. -I/usr/local/cuda/include \
  -include /root/pal-poc/sid-cuda13-compat.h -o pal_nvme pal_nvme.c -lcuda
chmod +x followup-run.sh bind-vfio.sh restore-nvme.sh
md5sum pal_nvme.c; ls -l pal_nvme
EOS
```

`patch --dry-run`이 실패하거나 빌드 경고, 오류가 있으면 보고한다. NVIDIA 패치는 `nvidia/nv-dmabuf.c` 한 파일에 BAR1 구간을 얻고 돌려주는 함수 두 개를 더한다. upcie 패치는 이 커널에서 `move_notify`가 `invalidate_mappings`로 이름이 바뀐 것을 반영하는 한 줄이다. `-include sid-cuda13-compat.h`는 2차와 같이 CUDA 13의 `cuCtxCreate` 인자 차이를 메운다.

**설치.** 승인을 받은 뒤 한다. 1차와 같이 `make install`을 쓰지 않고 단계를 나눈다.

```sh
ssh jaeyoon@sid 'sudo bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/g-install.txt
set -e
G=/root/pal-poc/gmem; cd $G/linux-gmem
K=$(make -s kernelrelease)
make modules_install >/dev/null
mkdir -p /lib/modules/$K/extra
cp $G/nvidia-gmem/nvidia.ko $G/nvidia-gmem/nvidia-uvm.ko $G/nvidia-gmem/nvidia-modeset.ko $G/nvidia-gmem/nvidia-drm.ko /lib/modules/$K/extra/
cp $G/upcie-gmem/dmabuf_import/dmabuf_import.ko $G/upcie-gmem/iommu_map_pa/iommu_map_pa.ko $G/gpu_gmem_provider/gpu_gmem_provider.ko /lib/modules/$K/extra/
depmod -a $K
cp arch/x86/boot/bzImage /boot/vmlinuz-$K; cp System.map /boot/System.map-$K; cp .config /boot/config-$K
update-initramfs -c -k $K
update-grub
grep -c "$K" /boot/grub/grub.cfg
grep -E '^GRUB_DEFAULT' /etc/default/grub
lsinitramfs /boot/initrd.img-$K | grep -c lvm
EOS
```

`grub.cfg`에 새 항목이 있어야 하고, `GRUB_DEFAULT`는 `7.0.0-38-generic` 그대로여야 하며, initramfs에 lvm이 있어야 한다(마지막 줄이 0이 아니어야 한다). 하나라도 다르면 멈춘다.

**부팅.** 사용자 승인을 받은 뒤 2차 4절과 같은 방법으로 한 번만 부팅한다. GRUB 항목 이름은 `grub.cfg`에서 확인해 맞춘다.

```sh
ssh jaeyoon@sid 'sudo bash -c "grub-reboot \"Advanced options for Ubuntu>Ubuntu, with Linux 7.3.0-rc7-gmem+\" && grub-editenv /boot/grub/grubenv list && systemctl reboot"'
```

부팅 뒤 곧바로 `next_entry`를 지운다. grubenv가 LVM 위에 있어 GRUB이 이 값을 지우지 못하므로, 지우지 않으면 다음 재부팅도 이 커널로 간다.

```sh
ssh jaeyoon@sid 'sudo bash -c "uname -r; grub-editenv /boot/grub/grubenv unset next_entry; grub-editenv /boot/grub/grubenv list; modprobe nvidia; modprobe nvidia-uvm; modprobe kvm_intel; modprobe gpu_gmem_provider; ls -l /dev/kvm /dev/gpu_gmem_provider; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader"'
```

`uname -r`이 `7.3.0-rc7-gmem+`이고 두 장치 파일이 있어야 한다. 새 커널이 부팅하지 못하면 원격 콘솔로 전원을 다시 넣는다. 이때 `next_entry`가 남아 있어 GRUB이 다시 새 커널을 고르므로, GRUB 메뉴에서 기본 커널을 직접 골라 부팅한 뒤 `next_entry`를 지운다.

### 6. 단계 J: 정합성

`followup-run.sh`는 `GPU=gmem`이면 PAL 경로 대신 guest_memfd 경로를 쓴다. `iommu_map_pa` 경로(`--map-pa`)는 비교 기준으로 그대로 실행한다.

```sh
ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/gmem/run && GPU=gmem ./followup-run.sh 0000:4e:00.0 $SLBA c; ./restore-nvme.sh 0000:4e:00.0'" 2>&1 | tee ~/pal-poc-sid/logs/g-J-4e.txt
```

| 시험 | 개발 PC 실측 | sid 예상 | 근거 |
| --- | --- | --- | --- |
| `--gmem` C1 (64K, 4K) | MATCH | MATCH (가정) | 개발 PC |
| `--gmem` C2 (64K, 4K) | `sc=0x4` (플랫폼 제한) | MATCH (가정) | sid는 PAL과 `iommu_map_pa`로 C2가 됐다. 리프 비트는 개발 PC에서 두 경로가 PS 비트만 달랐다 |
| `--gmem` D | `sc=0x4`, DMAR fault | 같음 (가정) | 개발 PC |
| `--map-pa` C1, C2 | C1 MATCH, C2 `sc=0x4` | MATCH | 2차 결과 |

출력 첫 줄의 `gmem:` 줄에 BAR1 구간 수와 첫 물리주소가 찍힌다. 기록한다.

멈춤: 표를 채워 보고하고 dmesg의 DMAR, AER 줄을 함께 보고한다. `--gmem`의 C2만 실패하고 `--map-pa`의 C2가 MATCH면 guest_memfd 경로 고유의 문제다. 그 경우 단계 K의 `pte` 부분만 먼저 실행해 두 경로의 리프 비트를 보고하고 지시를 기다린다.

### 7. 단계 K: 성능

처리량, IOVA 교차, 매핑 비용, PTE를 한 번에 잰다.

```sh
ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/gmem/run && SECS=10 SPAN=$SPAN GPU=gmem ORDER=\"gmem pa host\" ./followup-run.sh 0000:4e:00.0 $SLBA \"bench iova map pte\"; ./restore-nvme.sh 0000:4e:00.0'" 2>&1 | tee ~/pal-poc-sid/logs/g-K-4e.txt
```

약 10분이 걸린다. `bench`는 host 대상 쓰기로 구간을 채우고 30초 쉰 뒤, 세 경로의 읽기를 모두 재고 나서 쓰기를 잰다. `iova`는 두 경로를 서로의 IOVA에도 두고 읽기만 잰다. 2차 작업에서 GPU IOVA를 256 GiB에 두면 읽기가 2.6% 낮아졌으므로(`results-2026-10-27-iova.md`), 리프 크기의 영향은 같은 IOVA에 둔 조합끼리 비교해야 한다. guest_memfd 경로의 기본 IOVA는 `0xa00000`이고 `iommu_map_pa`의 기본 IOVA는 256 GiB다. `map`은 guest_memfd 경로의 매핑과 해제를 1000번 반복하므로 이 부분에만 1분 안팎이 걸린다.

예상값은 다음과 같다. sid 예상은 1차, 2차 실측과 원리에서 끌어낸 값이며 "가정"이라고 표시한다.

| 항목 | 개발 PC 실측 | sid 예상 | 근거 |
| --- | --- | --- | --- |
| rd 128K qd32, guest_memfd (`0xa00000`) | 6789.6 MB/s | 약 6588 MB/s (가정) | sid의 PAL과 host 대상이 6588 MB/s였다. 4 KiB 리프의 영향이 없으면 같다 |
| rd 128K qd32, `iommu_map_pa` (1 GiB) | 6792.9 MB/s | 약 6588 MB/s | 2차 12절 실측 |
| rd 128K qd32, 256 GiB의 두 경로 | 6789.6, 6793.0 MB/s | 약 6419 MB/s (가정) | 2차 12절 실측. IOVA 위치 효과 |
| rd 4K qd1, guest_memfd | 641.5 MB/s | 약 639 MB/s (가정) | 2차의 읽기만 한 측정에서 세 경로가 637~640 MB/s였다 |
| wr 128K qd32, guest_memfd | 측정 불가 | 약 6424 MB/s (가정) | 2차에서 모든 경로와 대상이 6424 MB/s였고, NVMe의 쓰기 한계로 추정했다 |
| map p50, guest_memfd | 44,170 µs | 약 17 ms (가정) | 비용은 `iommu_map()` 호출 횟수에 비례했다. sid의 `iommu_map_pa`는 512회에 33.5 µs였으므로 262,144회면 약 17 ms다 |
| map p50, `iommu_map_pa` | 89.3 µs | 약 33.5 µs | 2차 실측 |
| PTE, guest_memfd | 4 KiB x 262,144, `0x803` | 같음, SNP 여부 기록 | VT-d 형식은 `IOMMU_MMIO`를 읽지 않는다 |
| PTE, `iommu_map_pa` | 2 MiB x 512, `0x883` | 같음 | 2차 실측 |

guest_memfd 경로의 읽기나 쓰기가 같은 IOVA의 `iommu_map_pa`보다 1% 넘게 낮으면 4 KiB 리프의 영향으로 볼 수 있다. 이 경우 같은 명령을 한 번 더 실행해 재현되는지 함께 보고한다.

멈춤: 아래 표와 PTE 요약 두 줄(`gpu leaves:`)을 보고한다.

| 시험 | guest_memfd | `iommu_map_pa` | host |
| --- | --- | --- | --- |
| rd 4K qd1 (MB/s, p50 µs) | | | |
| rd 128K qd32 (MB/s, p99 µs) | | | |
| wr 4K qd1 | | | |
| wr 128K qd32 | | | |
| map p50/p99 (µs) | | | 없음 |
| unmap p50/p99 (µs) | | | 없음 |

| `iova` 조합 | 정방향 (MB/s) | 역방향 (MB/s) |
| --- | --- | --- |
| a guest_memfd, `0xa00000` | | |
| b guest_memfd, 256 GiB | | |
| c `iommu_map_pa`, 256 GiB | | |
| d `iommu_map_pa`, 1 GiB | | |
| host | | |

### 8. 단계 L: 수명

```sh
ssh jaeyoon@sid "sudo bash -c 'cd /root/pal-poc/gmem/run && GPU=gmem ./followup-run.sh 0000:4e:00.0 $SLBA life; ./restore-nvme.sh 0000:4e:00.0; lsmod | grep -E \"^gpu_gmem_provider|^kvm_intel\"'" 2>&1 | tee ~/pal-poc-sid/logs/g-L-4e.txt
```

| 시험 | 확인하는 것 | 개발 PC 실측 | sid 예상 |
| --- | --- | --- | --- |
| close (guest_memfd, `iommu_map_pa`) | dma-buf, provider, guest_memfd, VM fd를 닫아도 매핑이 유지되는가 | C1 MATCH, unmap 뒤 GPU 메모리 반환 | C1, C2 MATCH (가정) |
| free: `cuMemFree` 직후 여유 메모리 | 매핑이 있는 동안 NVIDIA가 메모리를 해제하는가 | 해제 전과 같음. 해제하지 않음 | 같음 (가정) |
| free: F1 새 버퍼 | 옛 IOVA로 쓴 데이터가 새 버퍼를 덮어쓰는가 | intact, 새 버퍼 물리주소가 다름 | intact (가정) |
| free: F2 | 옛 IOVA가 아직 옛 메모리를 가리키는가 | 측정 불가(C2 방향) | yes (가정) |
| kill -9 | I/O 중 강제 종료 뒤 장치, GPU 메모리, 모듈 참조가 정리되는가 | 다음 실행 C1 MATCH, 메모리 15 MiB로 복귀, `gpu_gmem_provider` 참조 수 0 | 같음 (가정) |

F1이 `CHANGED`로 나오면 해제된 메모리를 살아 있는 매핑이 가리킨다는 뜻이다. 곧바로 멈추고, 그 출력과 dmesg 전체를 보고한다.

멈춤: 표를 채우고, dmesg의 `BUG`, `WARNING`, `DMAR`, `AER`, `NVRM` 줄과 마지막 `lsmod` 줄(참조 수)을 보고한다.

### 9. 원상 복구

1. `0000:4e:00.0`이 nvme 드라이버로 돌아왔는지 본다.
2. 사용자 승인 뒤 sid를 재부팅한다. `next_entry`를 지웠으므로 기본 커널로 부팅된다.
3. 부팅 뒤 `uname -r`, `nvidia-smi`, `findmnt /mnt/datasets`를 확인한다.
4. 사용자에게 gmem 커널 파일(`/boot/*-7.3.0-rc7-gmem+`, `/lib/modules/7.3.0-rc7-gmem+`)과 `/root/pal-poc/gmem`을 지울지 묻는다. 묻기만 하고, 답을 받기 전에는 실행하지 않는다.

```sh
ssh jaeyoon@sid "echo \$(basename \$(readlink -f /sys/bus/pci/devices/0000:4e:00.0/driver)); sudo grub-editenv /boot/grub/grubenv list"
```

### 10. 보고

sid의 로그와 sia의 `~/pal-poc-sid/logs/g-*.txt`를 한 폴더에 모은다. 보고서는 `results-<날짜>-gmem.md` 하나로 쓰고, 6~8절의 표를 채운 뒤 짧은 해석을 붙인다. 해석에는 다음을 적는다.

- guest_memfd 경로의 C2 결과와, 실패했다면 상태 코드와 DMAR, AER 근거.
- 같은 IOVA에서 guest_memfd 경로와 `iommu_map_pa`의 처리량 차이가 측정 오차 안에 드는지. 4 KiB 리프의 영향이 보였는지.
- 매핑 비용이 `iommu_map()` 호출 횟수로 설명되는지(예상 약 17 ms).
- F2 결과와, `cuMemFree` 뒤 메모리가 매핑 해제까지 유지되는지.
- 측정한 것과 추정한 것의 구분.

## 묶음 구성 (이번에 더한 것)

| 경로 | 내용 |
| --- | --- |
| `patches/linux-gmem-on-v7.3-rc7.bundle` | 커널 트리. v7.3-rc7 위에 kvm.git `7e60162b16f9`의 트리를 커밋 하나로 얹고 Ackerley RFC v2 50편과 Griffoul RFC 14편을 쌓았다. 끝 커밋 `6766bffb9fc2`, 트리 `a6af7e15843c` |
| `patches/nvidia-580.178.04-bar1-ranges.patch` | NVIDIA dma-buf의 BAR1 구간을 얻고 돌려주는 `nv_dma_buf_get_bar1_ranges()`, `nv_dma_buf_put_bar1_ranges()` |
| `patches/upcie-experimental-0.9.0-gmem-kernel.patch` | `move_notify`를 `invalidate_mappings`로 바꾸는 한 줄 |
| `src/gpu_gmem_provider/` | 브리지 모듈. `GGP_NEW_FILE` ioctl이 NVIDIA dma-buf fd를 PFN mode provider 파일로 바꾼다 |
| `src/pal_nvme.c` | `--gmem` 추가. 빈 VM과 guest_memfd를 만들고 그 guest_memfd를 매핑한다. `-DPAL_NVME_GMEM`으로 빌드한다 |
| `scripts/followup-run.sh` | `GPU=gmem`이면 PAL 경로 대신 guest_memfd 경로를 쓴다. `pte` 부분이 4 KiB 리프도 센다 |
| `devpc-raw/gmem-2026-10-30/` | 개발 PC 로그. `followup-trial-gmem-*.log`는 이 매뉴얼의 명령을 `WR=0 SECS=3`으로 미리 실행한 로그다 |
| `results-2026-10-30-gmem.md` | 개발 PC 결과 보고서 |
