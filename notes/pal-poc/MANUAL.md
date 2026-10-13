# sid PAL PoC 실행 매뉴얼

이 문서는 sia에서 일하는 Claude에게 그대로 넘기는 작업 지시서다. 아래 "작업 지시" 절 전체를 붙여 넣고, 같은 폴더(`sid-bundle`)를 sia로 복사해 둔다.

## 작업 지시

너는 sid에서 PAL PoC의 남은 질문 하나를 확인한다. 개발 PC에서는 그 질문에 답할 수 없었다. 이 문서의 순서를 따르고, "멈춤"이라고 적힌 곳에서는 결과를 보고한 뒤 사용자의 답을 기다린다. 문서에 없는 판단이 필요하면 멈추고 묻는다.

### 0. 배경과 질문

본 팀은 NVMe가 CUDA로 할당한 GPU 메모리에 직접 DMA하도록 그 메모리를 NVMe의 IOMMU 페이지 테이블에 넣어야 한다. 지금은 자체 커널모듈 `iommu_map_pa`가 이 일을 하는데, 업스트림 iommufd의 `IOMMU_IOAS_MAP_FILE`이 CUDA dma-buf를 받으면 그 모듈을 걷어낼 수 있다. 업스트림에는 아직 그 기능이 없고, Jason Gunthorpe의 PAL(Physical Address List) RFC가 iommufd 쪽을 구현한다. 개발 PC에서 PAL 브랜치 커널과 PAL exporter를 더한 NVIDIA 드라이버로 다음을 확인했다. 자세한 결과는 같은 폴더의 `results-2026-10-13.md`에 있다.

| 확인한 것 | 결과 |
| --- | --- |
| CUDA dma-buf를 `IOMMU_IOAS_MAP_FILE`로 매핑 | 성공. 2 MiB 엔트리 512개 |
| NVMe → GPU (NVMe 읽기 명령, 장치가 GPU에 씀) | 데이터 일치 |
| 매핑하지 않은 IOVA | DMAR fault, 명령 오류 |
| GPU → NVMe (NVMe 쓰기 명령, 장치가 GPU BAR1을 읽음) | 실패(`sc=0x4`). 번역을 끈 identity 도메인에서도 실패, CPU는 같은 BAR1을 정상으로 읽음 |

마지막 줄은 개발 PC(i9-14900K, 호스트 브리지 8086:a700)의 루트 콤플렉스가 루트 포트 사이의 P2P 읽기를 처리하지 못하기 때문으로 추정한다. 이 호스트 브리지는 커널 `drivers/pci/p2pdma.c`의 P2P 허용 목록에 없고, sid의 Ice Lake-SP 호스트 브리지(8086:09a2)는 목록에 있다. 그래서 sid에서 답할 질문은 둘이다.

1. sid에서 NVMe가 GPU 메모리를 읽는 P2P가 번역 없이 되는가(단계 A).
2. 된다면, PAL 경로(iommufd 번역)로도 GPU → NVMe와 NVMe → GPU가 모두 되는가(단계 B, C).

### 1. 규칙

1. sid의 `0000:4d:00.0`은 데이터셋 장치(`/mnt/datasets`)다. 어떤 명령에도 이 주소를 넣지 않는다. 묶음의 스크립트도 이 주소를 거부한다.
2. 시험은 고른 NVMe 한 개의 연속된 LBA 구간 하나를 덮어쓴다(`pal_nvme --slba N`부터 64 KiB 전송 기준 384 섹터). 어떤 장치의 어느 LBA를 쓸지는 사용자가 정한다(2절에서 멈춤). 파티션 표나 파일시스템 앞부분이 있는 위치를 쓰지 않는다.
3. 다음은 사용자 승인 없이 하지 않는다: sid 재부팅, `grub-reboot`, `/boot`에 파일 설치, 패키지 설치, DKMS 조작, 기본 GRUB 항목 변경. 기본 GRUB 항목은 끝까지 바꾸지 않는다. 새 커널은 `grub-reboot`로 한 번만 부팅한다.
4. sid의 작업 파일은 모두 `/root/pal-poc` 아래에 둔다. 커널 트리는 `/root/pal-poc/linux-pal`이다(공간이 모자라면 멈추고 묻는다). 로그는 `/root/pal-poc/logs`에 남기고 단계가 끝날 때마다 sia의 `~/pal-poc-sid/logs`로 복사한다.
5. 명령이 실패하면 출력 전체를 보고한다. 이유 없이 같은 명령을 반복하지 않는다. 실패를 고치려고 시험 프로그램이나 판정 기준을 바꾸지 않는다.
6. 측정한 것과 추정한 것을 보고에서 구분한다.

### 2. 사전 점검 (읽기만)

sia에서 sid에 root로 비밀번호 없이 들어가는지 본다. `SID`는 이전 실험에서 쓴 이름이다. 모르면 사용자에게 묻는다.

```sh
export SID=<sid 이름이나 주소>
mkdir -p ~/pal-poc-sid/logs
ssh -o BatchMode=yes root@$SID hostname
```

다음을 sid에서 읽기만 한다.

```sh
ssh root@$SID 'bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/precheck.txt
echo "== kernel"; uname -r; cat /proc/cmdline
echo "== secure boot"; mokutil --sb-state 2>&1
echo "== root fs"; findmnt -no SOURCE,FSTYPE /; lsblk -no NAME,TYPE,FSTYPE,MOUNTPOINT | head -30
echo "== host bridges"; lspci -nn | grep -i 'host bridge' | head
echo "== gpu"; nvidia-smi --query-gpu=name,pci.bus_id,driver_version --format=csv,noheader
echo "== nvidia dkms"; dkms status 2>&1 | grep -i -E 'nvidia|upcie'
echo "== nvidia src"; ls -d /usr/src/nvidia-* 2>&1
echo "== upcie"; ls -l /dev/dmabuf_import /usr/include/linux/dmabuf_import.h 2>&1
echo "== cuda"; ls -d /usr/local/cuda* 2>&1; ls /usr/local/cuda/include/cuda.h 2>&1
echo "== nvme"; for d in /sys/bus/pci/devices/*; do [ "$(cat $d/class)" = 0x010802 ] && echo "$(basename $d) node=$(cat $d/numa_node) driver=$(basename $(readlink -f $d/driver)) group=$(basename $(readlink $d/iommu_group)) groupsize=$(ls $d/iommu_group/devices | wc -l)"; done
echo "== nvme namespaces"; for n in /sys/class/nvme/nvme*; do echo "$(basename $n) $(basename $(readlink -f $n/device)) $(cat $n/model)"; done
echo "== mounts of nvme"; grep nvme /proc/mounts
echo "== gpu path"; readlink -f /sys/bus/pci/devices/0000:31:00.0
echo "== tools"; for c in gcc make bc flex bison pahole setpci git zstd; do command -v $c >/dev/null || echo "MISSING $c"; done
dpkg -l libcap-dev libelf-dev libssl-dev 2>/dev/null | awk '/^ii/{print $2}'
echo "== disk"; df -h /root /boot
echo "== iommu debugfs"; ls /sys/kernel/debug/iommu/intel 2>&1 | head -2
EOS
```

대조할 기대값은 다음과 같다.

| 항목 | 기대값 | 다를 때 |
| --- | --- | --- |
| kernel | `7.0.0-34-generic` 계열, `intel_iommu=on`, `iommu=pt` 없음 | 보고한다. passthrough면 단계 B의 번역 시험은 의미가 없다 |
| secure boot | disabled | 멈춤. 직접 빌드한 커널은 서명 없이 부팅되지 않는다 |
| host bridges | 8086:09a2가 있음 | 보고한다. 허용 목록 근거가 약해진다 |
| gpu | L4, `00000000:31:00.0` | 멈춤 |
| nvidia src | `/usr/src/nvidia-<버전>` 하나. 버전을 기록한다 | 멈춤 |
| upcie | `/dev/dmabuf_import`와 헤더가 있음 | 멈춤. 단계 A의 물리주소 획득에 필요하다 |
| nvme | 시험 후보마다 `groupsize=1` | 그 장치는 후보에서 뺀다 |
| tools | MISSING 없음, libcap-dev 등 세 패키지 | 빠진 것을 보고하고 설치 승인을 받는다 |
| disk | `/root`에 40 GiB 이상 여유 | 멈춤 |

멈춤: 대조 결과와 함께 시험 장치 후보를 보고한다. 후보는 node 0의 NVMe 중 `0000:4d:00.0`이 아니고, 마운트되지 않았고, `groupsize=1`인 것이다. 가능하면 GPU(00:31)와 다른 루트 포트에 있는 장치를 고른다. 사용자에게 장치 주소 하나(`NVME`)와 덮어써도 되는 시작 LBA(`SLBA`)를 받는다. 받은 값은 이후 모든 명령에 쓴다.

### 3. 묶음 복사와 빌드

```sh
scp -r sid-bundle root@$SID:/root/pal-poc/
ssh root@$SID 'bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/build-tools.txt
cd /root/pal-poc/sid-bundle/src
cp /usr/include/linux/dmabuf_import.h ./dmabuf_import.h
CU=-I/usr/local/cuda/include
gcc -O2 -Wall $CU -o pal_probe pal_probe.c -lcuda
gcc -O2 -Wall $CU -o pal_nvme pal_nvme.c -lcuda
gcc -O2 -Wall -Wno-unused-result $CU -o bar1_cpu_read bar1_cpu_read.c -lcuda
ls -l pal_probe pal_nvme bar1_cpu_read
EOS
```

`dmabuf_import.h`는 묶음에 없으므로 sid에 설치된 모듈의 헤더를 복사해 쓴다. 개발 PC에서 옛 바이너리가 헤더 불일치로 `-25`(ENOTTY)를 낸 일이 있다. 빌드 오류는 보고한다.

### 4. 단계 A: 기본 커널에서 번역 없이 P2P 읽기 확인

이 단계는 재부팅이 필요 없다. 장치의 IOMMU 그룹을 identity로 바꿔 번역을 빼고 uio로 직접 명령을 보낸다. 개발 PC에서 같은 시험의 C2가 실패했다.

```sh
ssh root@$SID "bash -s" <<EOS 2>&1 | tee ~/pal-poc-sid/logs/stageA.txt
cd /root/pal-poc/sid-bundle
echo "== A0 stock iommufd refuses the NVIDIA dma-buf"
./src/pal_probe
echo "== A1 untranslated"
./scripts/identity-uio.sh $NVME
./src/pal_nvme --uio $NVME --slba $SLBA
./src/pal_nvme --uio $NVME --slba $SLBA --xfer 4096
echo "== A2 cpu read through BAR1"
./src/bar1_cpu_read
./scripts/restore-nvme.sh $NVME
dmesg | grep -E 'DMAR|AER|pcieport' | tail -20
EOS
```

| 시험 | 기대값 |
| --- | --- |
| A0 | `IOMMU_IOAS_MAP_FILE: FAILED errno=95`. 기본 커널의 iommufd가 NVIDIA dma-buf를 거부한다는 분석 보고서의 결론을 실기로 확인한다 |
| A1 C1 | MATCH |
| A1 C2 | 핵심 질문이다. MATCH면 sid는 P2P 읽기가 된다 |
| A2 | MATCH |

`pal_nvme`의 출력 줄 이름(`LBA0`, `LBA16`)은 고정 문자열이고 실제 위치는 `test LBAs:` 줄에 찍힌다.

멈춤: 결과를 보고한다. A1의 C2가 실패하면 sid도 P2P 읽기가 안 되는 것이므로 단계 B로 가지 않는다. 그 경우 `lspci -vvv -s <GPU 쪽 루트 포트>`와 `-s <NVMe 쪽 루트 포트>`의 ACS 줄, 그리고 두 장치의 경로(`readlink -f`)를 함께 보고한다.

### 5. 단계 B: PAL 커널, NVIDIA 드라이버, upcie 모듈 빌드

A1의 C2가 MATCH이고 사용자가 승인했을 때만 한다.

**커널.** 브랜치는 `https://github.com/jgunthorpe/linux`의 `dmabuf_map_type`이고 커밋은 `c37cf2824740`(v7.0-rc1 이후 dma-buf 토픽 트리 기반, 34커밋)이다. 개발 PC 설정을 따르되 sid의 루트 파일시스템이 LVM이므로 dm 관련 모듈이 initramfs에 들어가야 한다.

```sh
ssh root@$SID 'bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/kernel-config.txt
set -e
cd /root/pal-poc
git clone --no-checkout --filter=blob:none https://github.com/jgunthorpe/linux linux-pal
cd linux-pal && git fetch origin dmabuf_map_type && git checkout --detach c37cf2824740
cp /boot/config-$(uname -r) .config
modprobe vfio-pci; modprobe uio_pci_generic; modprobe dm_mod
make olddefconfig >/dev/null
yes '' | make localmodconfig >/dev/null
./scripts/config --set-str LOCALVERSION "-pal" \
  --set-str SYSTEM_TRUSTED_KEYS "" --set-str SYSTEM_REVOCATION_KEYS "" \
  -e IOMMUFD -e IOMMU_PT_AMDV1 -e FAULT_INJECTION -e IOMMUFD_TEST \
  -m VFIO -m VFIO_PCI -m VFIO_PCI_CORE -m VFIO_IOMMU_TYPE1 -e VFIO_DEVICE_CDEV \
  -e PCI_P2PDMA -e DMA_SHARED_BUFFER -m UIO -m UIO_PCI_GENERIC \
  -e INTEL_IOMMU -e INTEL_IOMMU_DEBUGFS -e IOMMU_DEBUGFS -e KPROBE_EVENTS \
  -e DEBUG_INFO_NONE -d DEBUG_INFO_BTF -d KASAN
make olddefconfig >/dev/null
grep -E '^CONFIG_(IOMMUFD|IOMMUFD_TEST|VFIO_PCI_DMABUF|VFIO_DEVICE_CDEV|BLK_DEV_DM|DM_|MD|INTEL_IOMMU_DEBUGFS)=' .config
make -s kernelrelease
EOS
```

`VFIO_PCI_DMABUF=y`, `IOMMUFD=y`, `BLK_DEV_DM`이 있어야 한다. 없으면 멈춘다. 빌드는 오래 걸리므로 백그라운드로 돌리고 로그를 본다.

```sh
ssh root@$SID 'cd /root/pal-poc/linux-pal && nohup make -j$(nproc) > build.log 2>&1; echo exit=$? >> build.log' &
```

**NVIDIA 드라이버.** DKMS는 이 커널에서 쓰지 않는다. 개발 PC에서 NVIDIA 580의 최상위 Makefile이 7.0-rc1 커널의 외부 모듈 빌드에서 `$(src)/Kbuild`를 찾지 못해 DKMS 빌드가 실패했다. 소스를 복사해 직접 빌드한다. sid의 드라이버가 580.178.04면 `patches/nvidia-580.178.04-pal-port.patch`를 그대로 적용한다. 버전이 다르면 패치를 참고해 같은 변경을 손으로 옮긴다. 변경은 `nvidia/nv-dmabuf.c`, `conftest.sh`, `nvidia/nvidia.Kbuild` 세 파일뿐이다.

```sh
ssh root@$SID 'bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/nvidia-build.txt
V=$(ls -d /usr/src/nvidia-* | head -1)
rm -rf /root/pal-poc/nvidia-pal && cp -r $V /root/pal-poc/nvidia-pal && cd /root/pal-poc/nvidia-pal
patch -p1 --dry-run < /root/pal-poc/sid-bundle/patches/nvidia-580.178.04-pal-port.patch && patch -p1 < /root/pal-poc/sid-bundle/patches/nvidia-580.178.04-pal-port.patch
make -j16 SYSSRC=/root/pal-poc/linux-pal NV_EXCLUDE_KERNEL_MODULES=nvidia-peermem modules > build.log 2>&1; echo exit=$?
grep -E 'error:' build.log | head; ls -l *.ko; modinfo -F vermagic nvidia.ko
EOS
```

`--dry-run`이 실패하면 버전 차이다. 그 출력을 보고하고 손으로 옮길지 승인을 받는다. `nvidia-peermem`은 OFED의 심볼 파일을 요구하므로 뺀다. 변수 이름은 `NV_EXCLUDE_KERNEL_MODULES`다(DKMS가 쓰는 `NV_EXCLUDE_BUILD_MODULES`는 Makefile이 읽지 않는다).

**upcie-experimental.** 같은 방식으로 `/usr/src/upcie-experimental-*`를 `/root/pal-poc/upcie-pal`로 복사하고 `patches/upcie-experimental-0.9.0-pal-port.patch`를 `patch -p1`로 적용한 뒤 `make KDIR=/root/pal-poc/linux-pal`로 빌드한다. `dmabuf_import.ko`와 `iommu_map_pa.ko`가 나와야 한다.

**설치.** 승인을 받은 뒤 한다. `make install`은 `/etc/kernel/postinst.d/dkms`가 실패하면 그 뒤의 initramfs와 GRUB 갱신을 건너뛴다. 그래서 단계를 나눠 실행하고 DKMS 실패 출력은 무시한다.

```sh
ssh root@$SID 'bash -s' <<'EOS' 2>&1 | tee ~/pal-poc-sid/logs/install.txt
cd /root/pal-poc/linux-pal
K=$(make -s kernelrelease)
make modules_install >/dev/null
mkdir -p /lib/modules/$K/extra
cp /root/pal-poc/nvidia-pal/{nvidia,nvidia-uvm,nvidia-modeset,nvidia-drm}.ko /lib/modules/$K/extra/
cp /root/pal-poc/upcie-pal/dmabuf_import/dmabuf_import.ko /root/pal-poc/upcie-pal/iommu_map_pa/iommu_map_pa.ko /lib/modules/$K/extra/
depmod -a $K
cp arch/x86/boot/bzImage /boot/vmlinuz-$K; cp System.map /boot/System.map-$K; cp .config /boot/config-$K
update-initramfs -c -k $K
update-grub
grep -c "$K" /boot/grub/grub.cfg
lsinitramfs /boot/initrd.img-$K | grep -c -E 'dm-mod|dm_mod'
EOS
```

initramfs에 dm 모듈이 없으면(마지막 줄이 0) 멈춘다. 루트가 LVM이라 부팅하지 못한다.

멈춤: 빌드와 설치 결과를 보고하고 재부팅 승인을 받는다. sid에 원격 콘솔(BMC, IPMI)이 있는지 사용자에게 확인한다. 새 커널이 부팅에 실패해도 `grub-reboot`는 한 번만 적용되므로 전원을 다시 넣으면 기본 커널로 돌아온다. 다만 그 전원 조작에는 원격 콘솔이 필요하다.

```sh
ssh root@$SID 'grub-reboot "Advanced options for Ubuntu>Ubuntu, with Linux 7.0.0-rc1-pal+" && grep next_entry /boot/grub/grubenv && systemctl reboot'
```

GRUB 항목 이름은 sid의 `grub.cfg`에서 확인해 맞춘다.

### 6. 단계 C: PAL 커널에서 번역된 P2P 확인

부팅 후 `uname -v`가 새 빌드인지 확인한다.

```sh
ssh root@$SID "bash -s" <<EOS 2>&1 | tee ~/pal-poc-sid/logs/stageC.txt
uname -a
modprobe nvidia; modprobe nvidia-uvm; modprobe dmabuf_import; modprobe vfio-pci
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
cd /root/pal-poc/sid-bundle
./scripts/bind-vfio.sh $NVME
VF=/dev/vfio/devices/\$(ls /sys/bus/pci/devices/$NVME/vfio-dev)
echo "== C0 map"; ./src/pal_probe --vfio \$VF
echo "== C1/C2/D 64K"; ./src/pal_nvme --vfio \$VF --slba $SLBA
echo "== 4K"; ./src/pal_nvme --vfio \$VF --slba $SLBA --xfer 4096
echo "== identity iova"; ./src/pal_nvme --vfio \$VF --slba $SLBA --identity --no-negative
echo "== PTE"; (./src/pal_probe --vfio \$VF --hold 15 &) ; sleep 8; ./scripts/pte-dump.sh $NVME
sleep 10
dmesg | grep -E 'DMAR|AER' | tail -20
EOS
```

| 시험 | 기대값 | 의미 |
| --- | --- | --- |
| C0 | `IOMMU_IOAS_MAP_FILE: OK` | PAL exporter와 iommufd 연결 |
| C1 | MATCH | NVMe → GPU, 번역된 IOVA |
| C2 | MATCH | GPU → NVMe, 번역된 IOVA. 이 시험이 sid에 온 이유다 |
| D | `sc=0x4` 그리고 dmesg에 "PTE Read access is not set" | 번역과 보호가 적용됨 |
| D2 | 명령은 OK, dmesg에 "PTE Write access is not set" | posted write는 장치에 오류가 돌아오지 않음 |
| PTE | 첫 줄들이 `0x...883` 또는 `0x...083`, 엔트리 약 512개 | 2 MiB 매핑. 비트 11(SNP) 여부를 기록한다 |

C2가 실패하고 단계 A의 C2가 성공했다면 번역 경로 고유의 문제다. 이때 PTE의 SNP 비트를 기록하고, 사용자 승인 후 `patches/kernel-vtdss-mmio-nosnp.patch`를 커널 트리에서 `git apply`로 적용해 다시 빌드하고 같은 시험을 반복한다. 이 패치는 MMIO 매핑에서 SNP 비트를 빼는 6행짜리 변경이다. 개발 PC에서는 C2 실패의 원인이 아니었지만 sid에서는 따로 확인할 가치가 있다.

### 7. 원상 복구

```sh
ssh root@$SID "/root/pal-poc/sid-bundle/scripts/restore-nvme.sh $NVME; grep -E 'saved_entry|next_entry' /boot/grub/grubenv"
```

멈춤: 사용자 승인 후 sid를 재부팅해 기본 커널로 돌아간다. 부팅 후 `uname -r`과 `nvidia-smi`, 데이터셋 마운트(`findmnt /mnt/datasets`)를 확인한다. PAL 커널 파일(`/boot/*-pal+`, `/lib/modules/*-pal+`)은 지우지 않는다. 지울지는 사용자가 정한다.

### 8. 보고

sid의 `/root/pal-poc/logs`와 각 단계의 tee 로그를 sia의 `~/pal-poc-sid/logs`에 모은다. 보고는 아래 표 하나와 짧은 해석으로 한다.

| 단계 | 시험 | 개발 PC 결과 | sid 결과 |
| --- | --- | --- | --- |
| A0 | 기본 커널 iommufd가 NVIDIA dma-buf 거부 | 미시험 | |
| A1 | 번역 없이 C1 | MATCH | |
| A1 | 번역 없이 C2 | 실패 `sc=0x4` | |
| A2 | CPU의 BAR1 읽기 | MATCH | |
| C0 | PAL 매핑 | OK | |
| C1 | 번역된 NVMe → GPU | MATCH | |
| C2 | 번역된 GPU → NVMe | 실패 `sc=0x4` | |
| D | 미매핑 IOVA | 오류 + DMAR fault | |
| PTE | 페이지 크기, SNP | 2 MiB x 512, SNP 켜짐 | |

해석에는 C2의 결과가 무엇을 뜻하는지, 단계 A와 C의 차이가 있었는지, 측정과 추정을 나눠 적는다.

## 묶음 구성

| 경로 | 내용 |
| --- | --- |
| `src/pal_probe.c` | CUDA 1 GiB를 dma-buf로 내보내 `IOMMU_IOAS_MAP_FILE`로 매핑. `--vfio`로 장치를 붙이고 `--hold`로 유지 |
| `src/pal_nvme.c` | vfio cdev와 iommufd 위의 최소 NVMe 드라이버. C1, C2, D 시험. `--uio <BDF>`는 번역 없는 모드, `--identity`는 IOVA를 BAR1 물리주소로 고정, `--slba`는 덮어쓸 시작 LBA |
| `src/bar1_cpu_read.c` | CPU가 GPU BAR1(`resource1`)로 CUDA 버퍼를 읽어 대조. 기본 GPU 주소는 `0000:31:00.0` |
| `scripts/bind-vfio.sh` | NVMe를 vfio-pci와 DMA-FQ 그룹으로 |
| `scripts/identity-uio.sh` | NVMe를 identity 그룹과 uio_pci_generic으로, hugepage 64개 |
| `scripts/restore-nvme.sh` | NVMe를 nvme 드라이버와 DMA-FQ로, hugepage 해제 |
| `scripts/pte-dump.sh` | VT-d debugfs로 NVMe의 페이지 테이블 첫 줄 출력 |
| `patches/nvidia-580.178.04-pal-port.patch` | NVIDIA exporter의 mapping type 이식과 PAL exporter |
| `patches/upcie-experimental-0.9.0-pal-port.patch` | `dmabuf_import`의 importer API 이식 |
| `patches/kernel-vtdss-mmio-nosnp.patch` | 선택. MMIO PTE에서 SNP 제거 |
| `results-2026-10-13.md` | 개발 PC 결과 보고서 |
