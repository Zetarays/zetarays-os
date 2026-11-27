#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the in-place upgrade file zetarays-TO-upgrade-ARCH.run.

Called by tools/make-upgrade.sh (read it first); standard library only, runs
on the Mac or on Linux. Everything that differs between the released FROM
configuration (.cache/src-FROM-release-config, read-only) and the current
tree is computed here, at bundle time: files, new packages, services,
reviewed build hooks.

    make_bundle.py --arch arm64 --to X.Y --out out/zetarays-X.Y-upgrade-arm64.run
                   [--ollama cache/ollama-linux-arm64.tar.zst] [--release-deb DEB]
                   [--accept-hooks]
"""
import argparse
import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zeta_files as zf  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CONFIG = os.path.join(ROOT, "live-build", "config")
INCLUDES = os.path.join(CONFIG, "includes.chroot")
REVIEWED = os.path.join(HERE, "hooks-reviewed.json")
I18N_IT = os.path.join(HERE, "data", "it.json")
# Data folders every computer gets recorded and checked around the upgrade.
# None by default: each computer lists its own in /etc/zeta/protected-paths
# (private paths never go into a public file). The upgrade never writes
# under PROTECTED_ROOTS at all.
PROTECTED_DATA = []
PROTECTED_ROOTS = ("/home", "/root", "/srv", "/mnt", "/media", "/run/media")


def under_protected(path):
    p = os.path.normpath("/" + path.lstrip("/"))
    return any(p == r or p.startswith(r + "/") for r in PROTECTED_ROOTS)

# The patched Hyprland that each release installed (hook 0350, «+zeta2»).
HYPRLAND_RELEASED = {"2.5": "0.55.2+ds-1~bpo13+1+zeta2", "3.0": "0.55.2+ds-1~bpo13+1+zeta2"}
# GPU libraries the Ollama hook removes (0300): never bundled
OLLAMA_GPU = re.compile(r"^lib/ollama/(cuda_|rocm|.*jetpack)")


def die(msg):
    print("make_bundle: ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------ hooks

def check_hooks(accept):
    hooks_dir = os.path.join(CONFIG, "hooks", "normal")
    data = json.load(open(REVIEWED, encoding="utf-8"))
    reviewed = data["hooks"]
    changed = []
    for fn in sorted(os.listdir(hooks_dir)):
        cur = file_sha(os.path.join(hooks_dir, fn))
        entry = reviewed.get(fn)
        if entry is None or entry.get("sha256") != cur:
            changed.append(fn)
            if accept:
                if entry is None:
                    entry = reviewed[fn] = {"upgrade": "skip", "how": "added by --accept-hooks: review"}
                entry["sha256"] = cur
    for fn in list(reviewed):
        if not os.path.exists(os.path.join(hooks_dir, fn)):
            changed.append(fn + " (removed)")
            if accept:
                del reviewed[fn]
    if changed and not accept:
        die("build hooks changed since they were reviewed for the upgrade: %s\n"
            "  Read each change and decide whether the upgrade must repeat it\n"
            "  (tools/upgrade/hooks-reviewed.json, zeta_upgrade.py), then run\n"
            "  tools/make-upgrade.sh --accept-hooks" % ", ".join(changed))
    if changed:
        with open(REVIEWED, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        print("hooks accepted: " + ", ".join(changed))
    return reviewed


# ------------------------------------------------------------ files

def generated(config, version):
    """Files the build writes outside includes.chroot that the upgrade owns:
    the Ollama service (hook 0300) and the extra package sources."""
    out = {}
    unit = zf.heredoc(os.path.join(config, "hooks", "normal", "0300-zeta-ollama.hook.chroot"),
                      "/etc/systemd/system/ollama.service")
    if unit:
        out["/etc/systemd/system/ollama.service"] = unit.encode()
    arch_dir = os.path.join(config, "archives")
    if os.path.isdir(arch_dir):
        for fn in sorted(os.listdir(arch_dir)):
            p = os.path.join(arch_dir, fn)
            if fn.endswith(".list.chroot"):
                out["/etc/apt/sources.list.d/" + fn[:-len(".chroot")]] = open(p, "rb").read()
            elif fn.endswith(".pref.chroot"):
                out["/etc/apt/preferences.d/" + fn[:-len(".pref.chroot")]] = open(p, "rb").read()
    entries = {}
    for path, data in out.items():
        entries[path] = {"policy": "conffile", "type": "file", "mode": 0o644, "size": len(data),
                         "sha256": sha(data), "data": data}
    return entries


def all_files(config, version):
    files = zf.collect(os.path.join(config, "includes.chroot"), version)
    files.update(generated(config, version))
    return files


# ------------------------------------------------------------ Ollama

def slim_ollama(src, dest):
    """The Ollama runtime without the GPU libraries, as .tar.xz (the hook
    removes them from the image too). Returns (sha256 of bin/ollama, size)."""
    if src.endswith(".zst"):
        if not shutil.which("zstd"):
            die("zstd is needed to read %s" % src)
        proc = subprocess.Popen(["zstd", "-dc", src], stdout=subprocess.PIPE)
        stream = proc.stdout
    else:
        proc, stream = None, open(src, "rb")
    bin_sha, size = None, 0
    with tarfile.open(fileobj=stream, mode="r|*") as tin, \
            tarfile.open(dest, "w:xz", format=tarfile.PAX_FORMAT, preset=6) as tout:
        for m in tin:
            name = m.name.lstrip("./")
            if not (name.startswith(("bin/", "lib/ollama/")) or name in ("bin", "lib", "lib/ollama")):
                continue
            if OLLAMA_GPU.match(name):
                continue
            m.name = name
            m.uid = m.gid = 0
            m.uname = m.gname = "root"
            if m.isfile():
                data = tin.extractfile(m).read()
                if name == "bin/ollama":
                    bin_sha = sha(data)
                size += len(data)
                tout.addfile(m, io.BytesIO(data))
            elif m.isdir() or m.issym():
                tout.addfile(m)
    if proc:
        if proc.wait() != 0:
            die("could not decompress %s" % src)
    if not bin_sha:
        die("bin/ollama is missing from %s" % src)
    return bin_sha, size


# ------------------------------------------------------------ texts

def strings_used():
    """English texts of zeta_upgrade.py (_("...")) and stub.sh (t "...")."""
    found = set()
    tree = ast.parse(open(os.path.join(HERE, "zeta_upgrade.py"), encoding="utf-8").read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    stub = open(os.path.join(HERE, "stub.sh"), encoding="utf-8").read()
    stub_found = set(re.findall(r'\bt "((?:[^"\\$`]|\\.)*)"', stub))
    return found, stub_found


def translations():
    py, stub = strings_used()
    table = {}
    for item in json.load(open(I18N_IT, encoding="utf-8")):
        table[item["en"]] = item["it"]
    missing = sorted((py | stub) - set(table))
    if missing:
        die("upgrade texts without an Italian translation in %s:\n  %s" % (I18N_IT, "\n  ".join(missing)))
    unused = sorted(set(table) - py - stub)
    if unused:
        print("note: translations no longer used: %s" % "; ".join(unused))
    return {k: table[k] for k in py}, {k: table[k] for k in stub}


def bash_quote(s):
    return "$'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


# ------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True, choices=("amd64", "arm64"))
    ap.add_argument("--to", required=True)
    ap.add_argument("--from", dest="from_", default="3.0")
    ap.add_argument("--old-config", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ollama", default="")
    ap.add_argument("--hypr-cache", default=os.path.join(ROOT, "cache", "hyprland-zeta"))
    ap.add_argument("--release-deb", default="")
    ap.add_argument("--accept-hooks", action="store_true")
    a = ap.parse_args()
    old_config = a.old_config or os.path.join(ROOT, ".cache", "src-%s-release-config" % a.from_)
    if not os.path.isdir(os.path.join(old_config, "includes.chroot")):
        die("the released %s configuration is missing: %s" % (a.from_, old_config))
    if a.to == a.from_:
        die("VERSION is still %s: nothing to upgrade to" % a.to)

    reviewed = check_hooks(a.accept_hooks)

    new = all_files(CONFIG, a.to)
    old = all_files(old_config, a.from_)
    if "/etc/systemd/system/ollama.service" not in new:
        die("the ollama.service text was not found in hook 0300 (cat > ... <<'UNIT')")
    files_manifest, removed = {}, {}
    for path, e in new.items():
        m = {k: e[k] for k in ("type", "policy", "mode", "sha256", "size")}
        if e["type"] == "link":
            m["target"] = e["target"]
        if path in old:
            m["shipped_before"] = True
            m["old"] = [old[path]["sha256"]]
        files_manifest[path] = m
    for path, e in old.items():
        if path not in new:
            removed[path] = {"policy": e["policy"], "old": [e["sha256"]]}

    new_pk = zf.packages(os.path.join(CONFIG, "package-lists"), a.arch)
    old_pk = zf.packages(os.path.join(old_config, "package-lists"), a.arch)
    units_new = zf.hook_units(os.path.join(CONFIG, "hooks", "normal"))
    units_old = zf.hook_units(os.path.join(old_config, "hooks", "normal"))
    units = {}
    # Image-only defaults the upgrade must not repeat on an installed system:
    # the unattended-upgrades power-off guard is off in the image and turned
    # on by zeta-auto-updates together with automatic updates (installer,
    # Settings), so an installed system already has the state its owner chose.
    image_only = {("disable", "unattended-upgrades.service")}
    for verb, unit in sorted(units_new - units_old - image_only):
        units.setdefault(verb, []).append(unit)

    work = tempfile.mkdtemp(prefix="zeta-bundle-")
    try:
        pay = os.path.join(work, "payload")
        os.makedirs(os.path.join(pay, "hooks"))
        # files.tar.gz: every file of the release, as the image has it
        with tarfile.open(os.path.join(pay, "files.tar.gz"), "w:gz", format=tarfile.PAX_FORMAT,
                          compresslevel=9) as tar:
            for path in sorted(new):
                e = new[path]
                ti = tarfile.TarInfo(path.lstrip("/"))
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = "root"
                ti.mtime = int(time.time())
                if e["type"] == "link":
                    ti.type = tarfile.SYMTYPE
                    ti.linkname = e["target"]
                    tar.addfile(ti)
                else:
                    ti.mode = e["mode"]
                    ti.size = len(e["data"])
                    tar.addfile(ti, io.BytesIO(e["data"]))

        ollama = None
        unpacked = 0
        if a.ollama:
            print("Ollama runtime: %s (GPU libraries left out)" % a.ollama)
            bin_sha, unpacked = slim_ollama(a.ollama, os.path.join(pay, "ollama-runtime.tar.xz"))
            ollama = {"archive": "ollama-runtime.tar.xz", "binary_sha256": bin_sha, "size": unpacked}

        # Hyprland: only when the patched build is not the one FROM installed
        if a.from_ not in HYPRLAND_RELEASED:
            die("unknown Hyprland of release %s: add it to HYPRLAND_RELEASED" % a.from_)
        HYPRLAND_FROM = HYPRLAND_RELEASED[a.from_]
        hypr = None
        hooks_dir = os.path.join(CONFIG, "hooks", "normal")
        hdir = os.path.join(a.hypr_cache, a.arch)
        debs = sorted(os.listdir(hdir)) if os.path.isdir(hdir) else []
        hdeb = [d for d in debs if re.match(r"hyprland_.*_%s\.deb$" % a.arch, d)]
        hver = hdeb[0].split("_")[1] if hdeb else HYPRLAND_FROM
        hooks_same = all(
            os.path.exists(os.path.join(old_config, "hooks", "normal", h)) and
            file_sha(os.path.join(old_config, "hooks", "normal", h)) == file_sha(os.path.join(hooks_dir, h))
            for h in ("0350-zeta-hyprland-patched.hook.chroot", "0400-zeta-hyprbars.hook.chroot"))
        if hver != HYPRLAND_FROM or not hooks_same:
            want = [d for d in debs if re.match(
                r"(hyprland|hyprland-dev|libaquamarine10|libaquamarine-dev|libhyprutils-dev)_.*_%s\.deb$" % a.arch, d)]
            if len(want) < 5:
                die("Hyprland changed (%s) but its packages are missing from %s" % (hver, hdir))
            os.makedirs(os.path.join(pay, "hyprland"))
            for d in want:
                shutil.copy2(os.path.join(hdir, d), os.path.join(pay, "hyprland", d))
            for h in ("0350-zeta-hyprland-patched.hook.chroot", "0400-zeta-hyprbars.hook.chroot"):
                shutil.copy2(os.path.join(hooks_dir, h), os.path.join(pay, "hooks", h))
            hypr = {"version": hver, "debs": want}
            print("Hyprland: %s -> %s (packages bundled, title bars rebuilt on the computer)" % (HYPRLAND_FROM, hver))
        else:
            print("Hyprland: unchanged (%s)" % hver)

        replay = sorted(h for h, e in reviewed.items() if e.get("upgrade") == "replay"
                        and os.path.exists(os.path.join(hooks_dir, h)))
        for h in replay:
            shutil.copy2(os.path.join(hooks_dir, h), os.path.join(pay, "hooks", h))

        release_deb = None
        if a.release_deb:
            release_deb = os.path.basename(a.release_deb)
            shutil.copy2(a.release_deb, os.path.join(pay, release_deb))

        models = []
        dl = open(os.path.join(ROOT, "tools", "download-ai-model.sh"), encoding="utf-8").read()
        mm = re.search(r'^MODELS="([^"]*)"', dl, re.M)
        if mm:
            models = mm.group(1).split()

        it_py, it_stub = translations()
        files_size = sum(e["size"] for e in new.values())
        manifest = {
            "format": 1, "from": a.from_, "to": a.to, "arch": a.arch,
            "bundle_id": "%s-%s-%s" % (a.to, a.arch, file_sha(os.path.join(pay, "files.tar.gz"))[:16]),
            "built": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": files_manifest, "remove": removed,
            "packages": {"new": sorted(new_pk - old_pk), "dropped": sorted(old_pk - new_pk)},
            "units": units, "ollama": ollama, "hyprland": hypr, "replay": replay,
            "release_deb": release_deb, "models": models,
            # the files and their backup twice, Ollama and its backup, room for apt
            "space_needed": 2 * files_size + 2 * unpacked + 1536 * 1024 * 1024,
            "i18n": {"it": it_py},
            # data folders recorded before the upgrade and checked after it
            # (zeta_upgrade.py, "protected data"); a computer adds its own in
            # /etc/zeta/protected-paths
            "protected_data": PROTECTED_DATA,
        }
        touching = sorted(p for p in list(files_manifest) + list(removed) if under_protected(p))
        if touching:
            die("the bundle would write under a protected folder: %s" % ", ".join(touching[:5]))
        shutil.copy2(os.path.join(HERE, "zeta_upgrade.py"), os.path.join(pay, "zeta_upgrade.py"))
        with open(os.path.join(pay, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1, ensure_ascii=False, sort_keys=True)
        sums = []
        for base, _dirs, fns in os.walk(pay):
            for fn in sorted(fns):
                p = os.path.join(base, fn)
                sums.append("%s  %s\n" % (file_sha(p), os.path.relpath(p, pay)))
        with open(os.path.join(pay, "SHA256SUMS"), "w") as f:
            f.write("".join(sorted(sums, key=lambda l: l.split("  ", 1)[1])))

        payload = os.path.join(work, "payload.tar")
        with tarfile.open(payload, "w", format=tarfile.PAX_FORMAT) as tar:
            for fn in sorted(os.listdir(pay)):
                tar.add(os.path.join(pay, fn), arcname=fn, filter=_root_owned)
        size = os.path.getsize(payload)
        payload_sha = file_sha(payload)

        name = os.path.basename(a.out)
        stub = open(os.path.join(HERE, "stub.sh"), encoding="utf-8").read()
        i18n = "\n".join("            %s) printf '%%s' %s; return ;;" % (bash_quote(k), bash_quote(v))
                         for k, v in sorted(it_stub.items()))
        stub = (stub.replace("@TO@", a.to).replace("@FROM@", a.from_).replace("@ARCH@", a.arch)
                .replace("@NAME@", name).replace("@SIZE@", str(size)).replace("@SHA256@", payload_sha)
                .replace('            "@I18N@") ;;', i18n))
        # fixed width: the offset does not change the length of the script
        offset = len(stub.replace("@OFFSET@", " " * 12).encode("utf-8"))
        stub = stub.replace("@OFFSET@", str(offset).ljust(12))
        assert len(stub.encode("utf-8")) == offset, "stub length changed"
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        tmp = a.out + ".partial"
        with open(tmp, "wb") as out, open(payload, "rb") as src:
            out.write(stub.encode("utf-8"))
            shutil.copyfileobj(src, out)
        os.chmod(tmp, 0o755)
        os.replace(tmp, a.out)
        with open(a.out + ".sha256", "w") as f:
            f.write("%s  %s\n" % (file_sha(a.out), name))

        counts = {}
        for e in files_manifest.values():
            counts[e["policy"]] = counts.get(e["policy"], 0) + 1
        print("files: %d (%s); no longer shipped: %d" % (
            len(files_manifest), ", ".join("%s %d" % kv for kv in sorted(counts.items())), len(removed)))
        for p in sorted(removed):
            print("  removed since %s: %s" % (a.from_, p))
        print("new packages (%s): %s" % (a.arch, " ".join(manifest["packages"]["new"]) or "none"))
        if manifest["packages"]["dropped"]:
            print("packages no longer in the lists (left installed): %s" % " ".join(manifest["packages"]["dropped"]))
        print("services: %s" % (json.dumps(units) if units else "no new enable/disable"))
        print("replayed hooks: %s" % (", ".join(replay) or "none"))
        print("package source package: %s" % (release_deb or "NOT INCLUDED (no repository key)"))
        print("%s: %.1f MB" % (a.out, os.path.getsize(a.out) / 1048576.0))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _root_owned(ti):
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = "root"
    return ti


if __name__ == "__main__":
    main()
