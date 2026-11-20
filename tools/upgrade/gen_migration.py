#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes the user migration of a release:
usr/share/zeta/migration/update-TO-0-defaults.json and the earlier release's
hyprland.lua it compares against ("-0-defaults" sorts it before the other
update-TO-*.json files, which patch only what a user changed).

    tools/upgrade/gen_migration.py 3.0 [--from 2.5]

Input: the released configuration of FROM (.cache/src-FROM-release-config,
read-only) and the migration files already shipped. It only depends on
FROM, so it is generated once per release; zeta-migrate-user reads /etc/skel
of the running system for the new content.
"""
import argparse
import hashlib
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INCLUDES = os.path.join(ROOT, "live-build", "config", "includes.chroot")
MIGRATION = os.path.join(INCLUDES, "usr", "share", "zeta", "migration")
# files Debian puts in /etc/skel (bash): never re-created
DEBIAN_SKEL = [".bashrc", ".profile", ".bash_logout"]
LUA_APPEND_EXCLUDE = ["zeta-snap "]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("to")
    ap.add_argument("--from", dest="from_", default="2.5")
    a = ap.parse_args()
    skel = os.path.join(ROOT, ".cache", "src-%s-release-config" % a.from_, "includes.chroot", "etc", "skel")
    known_hashes, known_paths = {}, list(DEBIAN_SKEL)
    for base, dirs, files in os.walk(skel):
        for name in sorted(files) + sorted(d for d in dirs if os.path.islink(os.path.join(base, d))):
            p = os.path.join(base, name)
            rel = os.path.relpath(p, skel)
            if name == ".DS_Store":
                continue
            known_paths.append(rel)
            if os.path.isfile(p) and not os.path.islink(p):
                known_hashes[rel] = [hashlib.sha256(open(p, "rb").read()).hexdigest()]
    # versions shipped by earlier releases (an untouched old copy is replaced too)
    for fn in sorted(os.listdir(MIGRATION)):
        if not fn.endswith(".json") or fn == "update-%s-0-defaults.json" % a.to:
            continue
        for step in json.load(open(os.path.join(MIGRATION, fn), encoding="utf-8"))["steps"]:
            if step["kind"] != "skel":
                continue
            for rel, hashes in step["files"].items():
                rel = step.get("renamed", {}).get(rel, rel)
                if rel in known_hashes:
                    known_hashes[rel] += [h for h in hashes if h not in known_hashes[rel]]
    base_dir = os.path.join(MIGRATION, "base-%s" % a.from_)
    os.makedirs(base_dir, exist_ok=True)
    shutil.copyfile(os.path.join(skel, ".config", "hypr", "hyprland.lua"), os.path.join(base_dir, "hyprland.lua"))
    data = {
        "description": "ZETA RAYS %s to %s: default settings files the user never changed are "
                       "replaced with the new ones; changed ones stay (new version kept for comparison); "
                       "new shortcuts are added to a changed hyprland.lua; new files are added." % (a.from_, a.to),
        "steps": [
            {"kind": "skel", "keep_new": True, "files": dict(sorted(known_hashes.items()))},
            {"kind": "lua-append", "file": ".config/hypr/hyprland.lua",
             "base": "/usr/share/zeta/migration/base-%s/hyprland.lua" % a.from_,
             "marker": "ZETA RAYS %s" % a.to,
             # shortcuts whose command needs functions of the new hyprland.lua
             # (zeta-snap -> zeta_snap() via hyprctl eval): not added to an old file
             "exclude": LUA_APPEND_EXCLUDE},
            {"kind": "skel-new", "known": sorted(set(known_paths))},
        ],
    }
    out = os.path.join(MIGRATION, "update-%s-0-defaults.json" % a.to)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("written", out, "and", os.path.join(base_dir, "hyprland.lua"))


if __name__ == "__main__":
    main()
