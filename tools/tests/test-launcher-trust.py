#!/usr/bin/python3
"""Unit tests of usr/lib/zeta/system/launcher_trust.py: which launchers
(.desktop files) on the Desktop may run with a double-click, or with files
dropped on them, without asking first.

The trust mark is GIO metadata (gvfsd-metadata), so the tests need a D-Bus
session and gvfs; run them as an ordinary user (root can write anything,
which hides the "file of the system" rule). In a Debian 13 container, from
the repository root:

    docker run --rm -v "$PWD":/src debian:trixie sh -c '
      apt-get update -qq && apt-get install -y -qq python3-gi gir1.2-glib-2.0 gvfs dbus >/dev/null &&
      useradd -m tester && mkdir -p /opt/sysapp &&
      printf "[Desktop Entry]\\nType=Application\\nName=Sys\\nExec=true\\n" > /opt/sysapp/sys.desktop &&
      chmod 644 /opt/sysapp/sys.desktop &&
      su tester -c "ZT_ROOT_ENTRY=/opt/sysapp/sys.desktop dbus-run-session python3 /src/tools/tests/test-launcher-trust.py"'
"""
import os
import shutil
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "live-build", "config", "includes.chroot",
                                "usr", "lib", "zeta"))

import gi  # noqa: E402
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from system import launcher_trust as T  # noqa: E402

ENTRY = "[Desktop Entry]\nType=Application\nName=%s\nExec=%s\n%s"


def write(path, name="App", command="true", extra="", mode=0o644):
    with open(path, "w") as f:
        f.write(ENTRY % (name, command, extra))
    os.chmod(path, mode)
    return path


def metadata_works(folder):
    p = write(os.path.join(folder, "probe.desktop"))
    try:
        Gio.File.new_for_path(p).set_attribute_string("metadata::zeta-probe", "1",
                                                      Gio.FileQueryInfoFlags.NONE, None)
        return True
    except GLib.Error:
        return False
    finally:
        os.unlink(p)


class Trust(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="zeta-trust-")
        if not metadata_works(self.d):
            self.skipTest("GIO metadata not available (needs a D-Bus session and gvfs)")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_downloaded_launcher_is_not_trusted(self):
        self.assertFalse(T.is_trusted(write(os.path.join(self.d, "evil.desktop"),
                                            command="sh -c 'rm -rf ~'")))

    def test_executable_bit_alone_is_not_enough(self):
        # archives keep the executable bit
        self.assertFalse(T.is_trusted(write(os.path.join(self.d, "x.desktop"), mode=0o755)))

    def test_mark_alone_is_not_enough(self):
        p = write(os.path.join(self.d, "m.desktop"))
        Gio.File.new_for_path(p).set_attribute_string(T.TRUSTED, "true",
                                                      Gio.FileQueryInfoFlags.NONE, None)
        self.assertTrue(T.has_trust_mark(p))
        self.assertFalse(T.is_trusted(p))

    def test_mark_trusted(self):
        p = write(os.path.join(self.d, "ok.desktop"))
        T.mark_trusted(p)
        self.assertTrue(os.stat(p).st_mode & stat.S_IXUSR)
        self.assertTrue(T.is_trusted(p))

    def test_link_to_a_users_entry(self):
        target = write(os.path.join(self.d, "real.desktop"))
        link = os.path.join(self.d, "link.desktop")
        os.symlink(target, link)
        self.assertFalse(T.is_trusted(link))
        T.mark_trusted(link)
        self.assertTrue(os.stat(target).st_mode & stat.S_IXUSR)
        self.assertTrue(T.is_trusted(link))

    def test_link_to_a_system_entry(self):
        root_entry = os.environ.get("ZT_ROOT_ENTRY")
        if not root_entry or os.getuid() == 0:
            self.skipTest("needs ZT_ROOT_ENTRY (a root-owned .desktop) and a normal user")
        link = os.path.join(self.d, "sys.desktop")
        os.symlink(root_entry, link)
        self.assertTrue(T.is_trusted(link))

    def test_missing_target(self):
        link = os.path.join(self.d, "gone.desktop")
        os.symlink(os.path.join(self.d, "nothing.desktop"), link)
        self.assertFalse(T.is_trusted(link))

    def test_created_by_zeta(self):
        own = write(os.path.join(self.d, "own.desktop"), extra="X-ZETA-App=firefox-esr.desktop\n")
        origin = write(os.path.join(self.d, "origin.desktop"), extra="X-ZETA-Origin=/opt/b/b.desktop\n")
        other = write(os.path.join(self.d, "other.desktop"))
        link = os.path.join(self.d, "l.desktop")
        os.symlink(own, link)
        self.assertTrue(T.created_by_zeta(own))
        self.assertTrue(T.created_by_zeta(origin))
        self.assertFalse(T.created_by_zeta(other))
        self.assertFalse(T.created_by_zeta(link))

    def test_migration_trusts_only_own_shortcuts(self):
        own = write(os.path.join(self.d, "own.desktop"), extra="X-ZETA-App=a.desktop\n")
        foreign = write(os.path.join(self.d, "foreign.desktop"))
        self.assertTrue(T.trust_own_shortcuts(self.d))
        self.assertTrue(T.is_trusted(own))
        self.assertFalse(T.is_trusted(foreign))

    def test_exec_line(self):
        p = write(os.path.join(self.d, "e.desktop"), command='"/opt/my app/run" --x %F')
        self.assertEqual(T.exec_line(p), '"/opt/my app/run" --x %F')
        self.assertEqual(T.exec_line(os.path.join(self.d, "none.desktop")), "")


class RegistryKeepsMode(unittest.TestCase):
    def test_write_kf_keeps_executable_bit(self):
        from system import applications
        d = tempfile.mkdtemp(prefix="zeta-kf-")
        try:
            p = write(os.path.join(d, "s.desktop"), mode=0o755)
            kf = GLib.KeyFile()
            kf.load_from_file(p, GLib.KeyFileFlags.NONE)
            kf.set_string("Desktop Entry", "X-ZETA-App", "b.desktop")
            applications._write_kf(kf, p)
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o755)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
