#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Makes the OVA exported by VirtualBox importable in VMware too.

    tools/ova-vmware-compat.py OVA arm64|amd64

make-ova.sh exports OVF 1.0 (VMware's ovftool rejects the OVF 2.0
elements StorageItem and EthernetPortItem). VirtualBox reads its own
<vbox:Machine> section and ignores what is added here; VMware reads only the
standard part, which says too little for it to start the machine. Added, all
with ovf:required="false" (VirtualBox, and any other importer, skips them):

  - VirtualSystemType "vmx-NN": without it VMware writes no hardware version
    and refuses to power on ("hardware version not supported");
  - the guest type (Debian 12 64-bit; see OS_TYPE for Apple silicon);
  - firmware EFI (the image boots only with UEFI);
  - a video card with 3D acceleration on (the desktop needs it);
  - on arm64 a VMXNET3 network card (VMware's Arm machines have no E1000;
    Debian's kernel has the driver).

The OVA is rewritten in a single pass (the disk is copied, not unpacked),
with a new SHA-256 manifest for both files, the descriptor first as the OVF
standard requires.
"""
import hashlib
import io
import os
import re
import sys
import tarfile

VMW_NS = "http://www.vmware.com/schema/ovf"
HW = {"arm64": "vmx-20", "amd64": "vmx-19"}       # Fusion 13 / Workstation 16.2 and later
# vSphere guest ids (VMware's importer ignores the .vmx names here): Debian 12
# 64-bit, CIM operating system 96. ovftool knows no Arm guest types, so on a
# Mac with Apple silicon the imported machine says "Debian 12.x 64-bit" and
# must be switched to "Debian 12.x 64-bit Arm" (Settings › General) before
# its first start; VMware documents OVF import as Intel-only there. The ISO
# works in Fusion on Apple silicon as it is.
OS_TYPE = {"arm64": "debian12_64Guest", "amd64": "debian12_64Guest"}
CIM_DEBIAN_64 = "96"


def patch_ovf(text, arch):
    if 'xmlns:vmw=' not in text:
        text = text.replace('xmlns:vbox="http://www.virtualbox.org/ovf/machine"',
                            'xmlns:vbox="http://www.virtualbox.org/ovf/machine" xmlns:vmw="%s"' % VMW_NS, 1)
    text = re.sub(r"<vssd:VirtualSystemType>(?:vmx-\d+ )?virtualbox-2\.2</vssd:VirtualSystemType>",
                  "<vssd:VirtualSystemType>%s virtualbox-2.2</vssd:VirtualSystemType>" % HW[arch], text, count=1)
    if "vmw:osType" not in text:
        text = re.sub(r'<OperatingSystemSection ovf:id="\d+"',
                      '<OperatingSystemSection ovf:id="%s" vmw:osType="%s"' % (CIM_DEBIAN_64, OS_TYPE[arch]),
                      text, count=1)
    # a video card with 3D on, as VMware writes it in its own OVF files: the
    # desktop needs 3D acceleration and an imported machine had it off
    if "enable3DSupport" not in text:
        ids = [int(i) for i in re.findall(r"<rasd:InstanceID>(\d+)</rasd:InstanceID>", text)]
        video = ('<Item ovf:required="false">\n'
                 "        <rasd:Caption>video</rasd:Caption>\n"
                 "        <rasd:Description>Video card with 3D acceleration (VMware)</rasd:Description>\n"
                 "        <rasd:ElementName>video</rasd:ElementName>\n"
                 "        <rasd:InstanceID>%d</rasd:InstanceID>\n"
                 "        <rasd:ResourceType>24</rasd:ResourceType>\n"
                 '        <vmw:Config ovf:required="false" vmw:key="enable3DSupport" vmw:value="true"/>\n'
                 '        <vmw:Config ovf:required="false" vmw:key="use3dRenderer" vmw:value="automatic"/>\n'
                 "      </Item>\n      " % (max(ids or [0]) + 1))
        text = text.replace("</VirtualHardwareSection>", video + "</VirtualHardwareSection>", 1)
    if 'vmw:key="firmware"' not in text:
        text = text.replace("</VirtualHardwareSection>",
                            '  <vmw:Config ovf:required="false" vmw:key="firmware" vmw:value="efi"/>\n'
                            "    </VirtualHardwareSection>", 1)
    # the sound card (ResourceType 35, VirtualBox's ensoniq1371) does not
    # exist in VMware: optional, so its importer skips it instead of refusing
    # the whole package (VirtualBox takes the card from its own section)
    text = re.sub(r"<Item>(\s*(?:<[^>]+>[^<]*</[^>]+>\s*)*?<rasd:ResourceType>35</rasd:ResourceType>)",
                  r'<Item ovf:required="false">\1', text)
    if arch == "arm64":
        text = text.replace("<rasd:ResourceSubType>E1000</rasd:ResourceSubType>",
                            "<rasd:ResourceSubType>VmxNet3</rasd:ResourceSubType>")
    for needed in (HW[arch], OS_TYPE[arch], 'vmw:key="firmware"'):
        if needed not in text:
            raise SystemExit("ova-vmware-compat: could not add %s to the descriptor" % needed)
    return text


def main(argv):
    if len(argv) != 2 or argv[1] not in HW:
        raise SystemExit(__doc__)
    ova, arch = argv
    tmp = ova + ".compat"
    with tarfile.open(ova) as src:
        members = src.getmembers()
        ovf_m = next(m for m in members if m.name.endswith(".ovf"))
        disks = [m for m in members if not m.name.endswith((".ovf", ".mf"))]
        ovf = patch_ovf(src.extractfile(ovf_m).read().decode("utf-8"), arch).encode("utf-8")
        sums = {ovf_m.name: hashlib.sha256(ovf).hexdigest()}
        for m in disks:
            h = hashlib.sha256()
            f = src.extractfile(m)
            for block in iter(lambda: f.read(1 << 22), b""):
                h.update(block)
            sums[m.name] = h.hexdigest()
        mf_name = os.path.splitext(ovf_m.name)[0] + ".mf"
        mf = "".join("SHA256(%s)= %s\n" % (n, s) for n, s in sums.items()).encode()
        with tarfile.open(tmp, "w", format=tarfile.USTAR_FORMAT) as out:
            for name, data in ((ovf_m.name, ovf), (mf_name, mf)):
                ti = tarfile.TarInfo(name)
                ti.size, ti.mode, ti.mtime = len(data), 0o644, ovf_m.mtime
                out.addfile(ti, io.BytesIO(data))
            for m in disks:
                m.mode = 0o644
                out.addfile(m, src.extractfile(m))
    os.replace(tmp, ova)
    print("OVA made importable in VMware too: %s (%s, %s)" % (ova, HW[arch], OS_TYPE[arch]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
