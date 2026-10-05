#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Crea una macchina virtuale VirtualBox con ZETA RAYS già installato, come file .ova.
#
#   ZETA_ARCH=amd64  (predefinito)  -> out/zetarays-1.7-amd64.ova  (PC Intel/AMD)
#   ZETA_ARCH=arm64                 -> out/zetarays-1.7-arm64.ova  (Mac Apple Silicon,
#                                       VirtualBox 7.2+ con supporto ARM)
#
# Parte dall'ISO corrispondente (./build.sh <arch>) e usa Docker + VBoxManage.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/out"
ARCH="${ZETA_ARCH:-amd64}"
ISO="${ZETA_ISO:-$OUT/zetarays-1.7-$ARCH.iso}"
DISK_GB="${ZETA_DISK_GB:-24}"
VM_NAME="ZETA RAYS 1.7 ($ARCH)"

# Parametri dipendenti dall'architettura
if [ "$ARCH" = "arm64" ]; then
  GRUB_TGT="arm64-efi"; EFI_NAME="BOOTAA64.EFI"
  GBIN="grub-efi-arm64-bin"; GPKG="grub-efi-arm64"
  VBOX_PLAT="arm"; VBOX_OSTYPE="Linux_arm64"      # «Other Linux»: nessun marchio di base nella VM
else
  GRUB_TGT="x86_64-efi"; EFI_NAME="BOOTX64.EFI"
  GBIN="grub-efi-amd64-bin"; GPKG="grub-efi-amd64"
  VBOX_PLAT="x86"; VBOX_OSTYPE="Linux26_64"        # «Linux generico»: nessun marchio di base nella VM
fi

[ -f "$ISO" ] || { echo "ISO non trovata: esegui prima ./build.sh $ARCH"; exit 1; }
command -v VBoxManage >/dev/null || { echo "VBoxManage non trovato: installa VirtualBox"; exit 1; }

# Su Mac Apple Silicon, per amd64 serve l'emulatore QEMU (il chroot non può usare
# Rosetta perché manca /proc). Per arm64 il container è nativo: nessuno scambio.
BINFMT=/proc/sys/fs/binfmt_misc
if [ "$ARCH" = "amd64" ] && [ "$(uname -m)" = "arm64" ] && command -v colima >/dev/null; then
  colima ssh -- sudo sh -c "echo 0 > $BINFMT/rosetta; echo 1 > $BINFMT/qemu-x86_64"
  trap 'colima ssh -- sudo sh -c "echo 1 > $BINFMT/rosetta; echo 0 > $BINFMT/qemu-x86_64"' EXIT
fi

VMDK="$OUT/zetarays-1.7-$ARCH.vmdk"
OVA="$OUT/zetarays-1.7-$ARCH.ova"

if [ "${ZETA_ONLY_OVA:-}" != 1 ]; then
rm -f "$VMDK"

docker run --rm --privileged --platform "linux/$ARCH" \
  -e DISK_GB="$DISK_GB" -e ARCH="$ARCH" -e GRUB_TGT="$GRUB_TGT" \
  -e EFI_NAME="$EFI_NAME" -e GBIN="$GBIN" -e GPKG="$GPKG" \
  -v "$OUT:/out" \
  -v "$ISO:/iso/zeta.iso:ro" \
  -v "$ROOT/live-build/config/includes.chroot:/zeta:ro" \
  -v "zeta-ova-work-$ARCH:/work" \
  debian:trixie bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends xorriso squashfs-tools e2fsprogs dosfstools mtools fdisk \
      $GBIN grub-common qemu-utils uuid-runtime ca-certificates >/dev/null

    W=/work; rm -rf $W/*; mkdir -p $W/iso $W/target
    echo "== Estraggo il sistema dall ISO ($ARCH)"
    xorriso -osirrox on -indev /iso/zeta.iso -extract /live/filesystem.squashfs $W/iso/filesystem.squashfs >/dev/null 2>&1
    unsquashfs -q -f -d $W/target $W/iso/filesystem.squashfs
    rm -f $W/iso/filesystem.squashfs

    cp -a /zeta/. $W/target/
    # Artefatti che servono solo alla costruzione dell ISO: non devono finire
    # nel disco. L archivio del runtime Ollama (1,3 GB) vi era entrato una
    # volta, gonfiando la OVA amd64 da 3,3 a 4,7 GB.
    rm -f $W/target/usr/share/zeta/ollama-runtime.tar.zst
    rm -rf $W/target/usr/share/zeta/hyprland-corretto
    rm -rf $W/target/usr/share/zeta/localsend
    find $W/target/usr/lib/zeta $W/target/usr/local/bin -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
    chmod 755 $W/target/usr/local/bin/zeta-*

    ROOT_UUID=$(uuidgen); ESP_ID=$(printf "%08X" $((RANDOM * RANDOM)))
    ESP_UUID="${ESP_ID:0:4}-${ESP_ID:4:4}"

    echo "== Configuro il sistema installato"
    T=$W/target
    mount -t proc proc $T/proc; mount -t sysfs sys $T/sys; mount --bind /dev $T/dev; mount --bind /dev/pts $T/dev/pts
    rm -f $T/etc/resolv.conf; cp /etc/resolv.conf $T/etc/resolv.conf

    mkdir -p $T/boot/efi
    cat > $T/etc/fstab <<EOF
UUID=$ROOT_UUID  /          ext4  errors=remount-ro  0 1
UUID=$ESP_UUID   /boot/efi  vfat  umask=0077         0 1
EOF
    echo zetarays > $T/etc/hostname
    printf "127.0.0.1\tlocalhost\n127.0.1.1\tzetarays\n" > $T/etc/hosts

    mkdir -p $T/usr/local/sbin
    cat > $T/usr/local/sbin/zeta-firstboot <<EOF
#!/bin/sh
set -e
grub-install --target=$GRUB_TGT --efi-directory=/boot/efi --removable --no-nvram
sed -i "s/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=1/" /etc/default/grub
update-grub
mkdir -p /var/lib/zeta && touch /var/lib/zeta/firstboot-done
EOF
    chmod 755 $T/usr/local/sbin/zeta-firstboot
    cat > $T/etc/systemd/system/zeta-firstboot.service <<"EOF"
[Unit]
Description=ZETA RAYS - configurazione del primo avvio
ConditionPathExists=!/var/lib/zeta/firstboot-done
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/zeta-firstboot

[Install]
WantedBy=multi-user.target
EOF

    rm -f $T/etc/apt/sources.list
    grep -rl "/run/live/medium" $T/etc/apt/sources.list.d/ 2>/dev/null | xargs -r rm -f || true
    cat > $T/etc/apt/sources.list.d/debian.sources <<EOF
Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
    rm -f $T/etc/apt/sources.list.d/backports.list
    ln -sf /usr/share/zoneinfo/Europe/Rome $T/etc/localtime; echo "Europe/Rome" > $T/etc/timezone
    [ -f $T/etc/default/keyboard ] && sed -i "s/^XKBLAYOUT=.*/XKBLAYOUT=\"it\"/" $T/etc/default/keyboard
    # live-build riporta la lingua a C.UTF-8 (in live la imposta live-config al
    # boot): nel sistema installato va fissata, altrimenti le app sono in inglese.
    echo "LANG=it_IT.UTF-8" > $T/etc/default/locale; echo "LANGUAGE=it_IT:it" >> $T/etc/default/locale
    GPKG_ENV="$GPKG"
    chroot $T /bin/bash -euo pipefail -c "
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get purge -y -qq live-boot live-boot-initramfs-tools live-config live-config-systemd user-setup || true
      for b in /usr/sbin/grub-install /usr/sbin/update-grub; do dpkg-divert --local --rename --add \$b >/dev/null; ln -sf /bin/true \$b; done
      apt-get install -y -qq --no-install-recommends $GPKG_ENV efibootmgr
      for b in /usr/sbin/grub-install /usr/sbin/update-grub; do rm -f \$b; dpkg-divert --local --rename --remove \$b >/dev/null; done
      apt-get autoremove -y -qq >/dev/null || true
      rm -f /etc/sddm.conf
      for g in sudo audio video netdev plugdev bluetooth lpadmin scanner; do getent group \$g >/dev/null || groupadd -r \$g; done
      id zeta >/dev/null 2>&1 || useradd -m -s /bin/bash -G adm,sudo,audio,video,netdev,plugdev,bluetooth,lpadmin,scanner zeta
      usermod -aG lpadmin,scanner zeta
      echo zeta:zeta | chpasswd
      mkdir -p /etc/sddm.conf.d
      printf \"[Autologin]\nUser=zeta\nSession=zeta.desktop\n\" > /etc/sddm.conf.d/20-zeta-autologin.conf
      systemctl enable zeta-firstboot.service >/dev/null 2>&1
      update-initramfs -c -k all >/dev/null 2>&1 || update-initramfs -u -k all
      apt-get clean
      : > /etc/machine-id; rm -f /var/lib/dbus/machine-id
    "
    KVER=$(ls $T/boot | sed -n "s/^vmlinuz-//p" | sort -V | tail -1)
    echo "== Kernel $KVER"

    mkdir -p $T/boot/grub
    cp -r $T/usr/lib/grub/$GRUB_TGT $T/boot/grub/ 2>/dev/null || cp -r /usr/lib/grub/$GRUB_TGT $T/boot/grub/
    cat > $T/boot/grub/grub.cfg <<EOF
set default=0
set timeout=0
insmod all_video
insmod gzio
insmod part_gpt
insmod ext2
menuentry "ZETA RAYS" {
  search --no-floppy --fs-uuid --set=root $ROOT_UUID
  linux /boot/vmlinuz-$KVER root=UUID=$ROOT_UUID ro quiet splash loglevel=3 rd.udev.log_level=3 udev.log_level=3 vt.global_cursor_default=0
  initrd /boot/initrd.img-$KVER
}
EOF
    umount $T/dev/pts $T/dev $T/sys $T/proc
    rm -f $T/etc/resolv.conf; ln -s ../run/NetworkManager/resolv.conf $T/etc/resolv.conf 2>/dev/null || true

    echo "== Creo il disco da ${DISK_GB} GB"
    SECTORS=$(( DISK_GB * 1024 * 1024 * 1024 / 512 ))
    ESP_START=2048; ESP_SIZE=524288
    ROOT_START=$(( ESP_START + ESP_SIZE ))
    ROOT_SIZE=$(( (SECTORS - ROOT_START - 34) / 8 * 8 ))
    truncate -s $(( SECTORS * 512 )) $W/disk.raw
    sfdisk -q $W/disk.raw <<EOF
label: gpt
start=$ESP_START, size=$ESP_SIZE, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name="EFI"
start=$ROOT_START, size=$ROOT_SIZE, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="ZETA RAYS"
EOF

    printf "search --no-floppy --fs-uuid --set=root %s\nset prefix=(\$root)/boot/grub\nconfigfile \$prefix/grub.cfg\n" "$ROOT_UUID" > $W/early.cfg
    grub-mkimage -O $GRUB_TGT -o $W/$EFI_NAME -p /boot/grub -c $W/early.cfg \
      part_gpt fat ext2 normal linux search search_fs_uuid configfile gzio all_video efi_gop echo test
    mkfs.fat -C -F 32 -n EFI -i "$ESP_ID" $W/esp.img $(( ESP_SIZE / 2 )) >/dev/null
    mmd -i $W/esp.img ::/EFI ::/EFI/BOOT
    mcopy -i $W/esp.img $W/$EFI_NAME ::/EFI/BOOT/$EFI_NAME
    dd if=$W/esp.img of=$W/disk.raw bs=512 seek=$ESP_START conv=notrunc status=none

    truncate -s $(( ROOT_SIZE * 512 )) $W/root.img
    mkfs.ext4 -q -F -L zeta -U $ROOT_UUID -d $T $W/root.img
    dd if=$W/root.img of=$W/disk.raw bs=4M oflag=seek_bytes seek=$(( ROOT_START * 512 )) conv=notrunc,sparse status=none
    rm -f $W/root.img $W/esp.img

    echo "== Converto in VMDK"
    qemu-img convert -O vmdk -o subformat=streamOptimized $W/disk.raw /out/zetarays-1.7-'"$ARCH"'.vmdk
    rm -rf $W/*
  '
fi

echo "== Creo la macchina virtuale e l'OVA ($ARCH)"
# VM temporanea con nome univoco: non deve MAI coincidere con le VM dell'utente
# (es. una "ZETA RAYS 1.7 (arm64)" già importata). Il nome finale lo dà --vmname.
BUILD_VM="zeta-build-$ARCH-$$"
for u in $(VBoxManage list hdds | awk -v f="zetarays-1.7-$ARCH.vmdk" '/^UUID:/{u=$2} $0 ~ f {print u}'); do
  VBoxManage closemedium disk "$u" >/dev/null 2>&1 || true
done
TMPVM="$(mktemp -d)"
VBoxManage createvm --name "$BUILD_VM" --platform-architecture="$VBOX_PLAT" --ostype "$VBOX_OSTYPE" --basefolder "$TMPVM" --register

# Accelerazione 3D sempre attiva: il desktop ZETA RAYS (Hyprland) la richiede.
# 8 GB e 4 processori: con 8 GB la macchina e nella fascia in cui ZETA tiene il
# modello AI gia pronto all'accesso (risposte immediate invece di attendere il
# caricamento) e il desktop non va mai in scambio su disco. Sono i valori
# proposti all'importazione: su un computer ospite con meno memoria si
# abbassano nella finestra di VirtualBox prima di avviare.
VBoxManage modifyvm "$BUILD_VM" --memory 8192 --cpus 4 --firmware efi \
  --graphicscontroller vmsvga --vram 128 --accelerate-3d on \
  --nic1 nat --mouse usbtablet --usb-xhci on --rtc-use-utc on \
  --audio-enabled on --audio-controller hda --audio-out on --audio-in on \
  --ioapic on --paravirtprovider kvm
# --paravirtprovider kvm: il sistema ospite riconosce di girare dentro una
#   macchina virtuale e usa le scorciatoie previste per l orologio e per
#   l attesa fra processori. Senza, con quattro processori virtuali il kernel
#   perde tempo in attese che nessuno gli dice essere inutili.
# --ioapic on: necessario con piu di un processore. VirtualBox lo accende da
#   se, ma scriverlo evita che una modifica a mano nella finestra lo spenga e
#   lasci la macchina con un processore solo senza dirlo.
# Audio HDA: il kernel arm64 non ha il driver dell'AC'97 (predefinito su ARM).
VBoxManage storagectl "$BUILD_VM" --name SATA --add sata --controller IntelAhci --portcount 1
# --nonrotational on: il disco si presenta come un SSD. Il kernel allora non
# applica le astuzie pensate per i dischi a piatti (letture in anticipo,
# riordino delle richieste per ridurre gli spostamenti della testina), che su
# un file dell ospite sono solo lavoro sprecato e attese in piu.
VBoxManage storageattach "$BUILD_VM" --storagectl SATA --port 0 --device 0 --type hdd --nonrotational=on --medium "$VMDK"
# La cache del disco sull ospitante resta SPENTA, com e di serie: accendendola
# la macchina andrebbe piu veloce, ma un blocco del computer ospitante
# perderebbe le ultime scritture. Fra velocita e non perdere dati si sceglie
# di non perdere dati.
rm -f "$OVA"
VBoxManage export "$BUILD_VM" --output "$OVA" --ovf20 --manifest \
  --vsys 0 --vmname "$VM_NAME" --product "ZETA RAYS OS" --version "1.7" --description "ZETA RAYS OS 1.7 ($ARCH)"
VBoxManage unregistervm "$BUILD_VM" >/dev/null 2>&1 || true
VBoxManage closemedium disk "$VMDK" >/dev/null 2>&1 || true
rm -rf "$TMPVM" "$VMDK"
chmod 644 "$OVA"

echo "OVA pronta: $OVA"
