#!/usr/bin/python3
"""Unit tests of usr/lib/zeta/system/open_with.py ("Open With" and dropping
files onto an app icon on the Desktop).

They need GIO and the shared MIME database, not a display: run them in a
Debian 13 container, from the repository root:

    docker run --rm -v "$PWD":/src debian:trixie sh -c \
      'apt-get update -qq && apt-get install -y -qq python3-gi gir1.2-glib-2.0 shared-mime-info >/dev/null &&
       python3 /src/tools/tests/test-open-with.py'

Everything happens in a temporary XDG tree (apps, mimeapps.list, files): the
system and the user's configuration are never touched. The launch tests
start a tiny program that writes its arguments to a file, and check that
GIO handed over every name exactly (spaces, quotes, "$", backquotes,
non-Latin letters), for each Exec field code: %f %F %u %U and none.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.parse

ROOT = tempfile.mkdtemp(prefix="zeta-open-with-")
DATA = os.path.join(ROOT, "data")
CONF = os.path.join(ROOT, "config")
OUT = os.path.join(ROOT, "out")
FILES = os.path.join(ROOT, "files")
for d in (os.path.join(DATA, "applications"), CONF, OUT, FILES):
    os.makedirs(d)
# GIO reads these once, at the first use: they must be set before importing it
os.environ.update({
    "XDG_DATA_HOME": DATA,
    "XDG_DATA_DIRS": "/usr/share",          # the MIME database, no system apps
    "XDG_CONFIG_HOME": CONF,
    "XDG_CONFIG_DIRS": os.path.join(ROOT, "etc-xdg"),
    "XDG_CURRENT_DESKTOP": "Hyprland",
    "HOME": ROOT,
})
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "live-build", "config", "includes.chroot",
                                "usr", "lib", "zeta"))

import gi  # noqa: E402
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from system import open_with  # noqa: E402

# the program the test apps start: it writes its arguments as JSON
DUMP_DIR = os.path.join(ROOT, "program dir with space")
os.makedirs(DUMP_DIR)
DUMP = os.path.join(DUMP_DIR, "dump args.py")
with open(DUMP, "w") as f:
    f.write("#!/usr/bin/python3\nimport json, os, sys, uuid\n"
            "out = os.path.join(%r, sys.argv[1] + '-' + uuid.uuid4().hex + '.json')\n"
            "json.dump(sys.argv[2:], open(out, 'w'))\n" % OUT)
os.chmod(DUMP, 0o755)
# an Exec= with the program path in double quotes, as the spec wants it
QUOTED_DUMP = '"%s"' % DUMP

APPS = {
    # id: (Exec, MimeType, extra lines)
    "z-f": (QUOTED_DUMP + " f %f", "text/plain;", ""),
    "z-bigf": (QUOTED_DUMP + " F %F", "image/png;text/plain;", ""),
    "z-u": (QUOTED_DUMP + " u %u", "text/plain;", ""),
    "z-bigu": (QUOTED_DUMP + " U %U", "application/pdf;text/plain;", ""),
    "z-none": (QUOTED_DUMP + " none", "text/plain;", ""),
    "z-nomime": (QUOTED_DUMP + " nomime %F", None, ""),
    "z-any": (QUOTED_DUMP + " any %F", "all/all;", ""),
    "z-allfiles": (QUOTED_DUMP + " allfiles %F", "all/allfiles;", ""),
    "z-octet": (QUOTED_DUMP + " octet %F", "application/octet-stream;", ""),
    "z-wild": (QUOTED_DUMP + " wild %F", "image/*;", ""),
    "z-folder": (QUOTED_DUMP + " folder %U", "inode/directory;", ""),
    "z-hidden": (QUOTED_DUMP + " hidden %f", "text/plain;", "NoDisplay=true\n"),
    "z-kde": (QUOTED_DUMP + " kde %f", "text/plain;", "OnlyShowIn=KDE;\n"),
}
for ident, (exe, mime, extra) in APPS.items():
    with open(os.path.join(DATA, "applications", ident + ".desktop"), "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=%s\n%s%s" % (
            ident, exe, ("MimeType=%s\n" % mime) if mime else "", extra))

# GLib lists the apps of a type only through mimeinfo.cache (see
# open_with.refresh_mime_cache): built here as the registry does it
CACHE_BUILT = open_with.refresh_mime_cache(os.path.join(DATA, "applications"))

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
       b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
       b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
NAMES = {
    "space": "my file.txt",
    "quotes": "it's \"quoted\".txt",
    "shell": "$HOME `id` ;&|.txt",
    "unicode": "ünïcödé € 東京 🙂.txt",
    "percent": "100% done %f.txt",
    "python": "script with space.py",
    "png": "photo one.png",
    "pdf": "paper (final).pdf",
}


def make_files():
    paths = {}
    for key, name in NAMES.items():
        p = os.path.join(FILES, name)
        with open(p, "wb") as f:
            if key == "png":
                f.write(PNG)
            elif key == "pdf":
                f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
            elif key == "python":
                f.write(b"#!/usr/bin/python3\nprint('hello')\n")
            else:
                f.write(b"plain text\n")
        paths[key] = p
    folder = os.path.join(FILES, "a folder")
    os.makedirs(folder)
    paths["folder"] = folder
    return paths


P = make_files()


def app(ident):
    a = Gio.DesktopAppInfo.new(ident + ".desktop")
    assert a is not None, "test app %s not loaded" % ident
    return a


def collect(prefix, expected, timeout=10.0):
    """The argument lists written by the launched program for that prefix."""
    end = time.time() + timeout
    while time.time() < end:
        found = [n for n in os.listdir(OUT) if n.startswith(prefix + "-")]
        if len(found) >= expected:
            time.sleep(0.2)
            found = [n for n in os.listdir(OUT) if n.startswith(prefix + "-")]
            out = []
            for n in found:
                with open(os.path.join(OUT, n)) as f:
                    out.append(json.load(f))
                os.unlink(os.path.join(OUT, n))
            return out
        time.sleep(0.05)
    raise AssertionError("program %s did not run %d time(s)" % (prefix, expected))


def uri_to_path(u):
    """%u/%U: GLib hands a local file over as its path (tested with GLib
    2.84), other programs may get a file:// URI: both are accepted."""
    if u.startswith("file://"):
        return urllib.parse.unquote(u[len("file://"):])
    return u


def load(kf, text):
    data = text.encode("utf-8")
    kf.load_from_data(data.decode("utf-8"), len(data), GLib.KeyFileFlags.NONE)


class ContentTypes(unittest.TestCase):
    def test_types(self):
        self.assertEqual(open_with.content_type(P["png"]), "image/png")
        self.assertEqual(open_with.content_type(P["pdf"]), "application/pdf")
        self.assertEqual(open_with.content_type(P["space"]), "text/plain")
        self.assertEqual(open_with.content_type(P["folder"]), "inode/directory")
        self.assertTrue(Gio.content_type_is_a(open_with.content_type(P["python"]), "text/plain"))

    def test_missing_file_is_guessed(self):
        self.assertEqual(open_with.content_type(os.path.join(FILES, "nope.png")), "image/png")


class Matching(unittest.TestCase):
    def test_exact_and_parent_types(self):
        self.assertTrue(open_with.can_open(app("z-f"), "text/plain"))
        # text/x-python derives from text/plain
        self.assertTrue(open_with.can_open(app("z-f"), open_with.content_type(P["python"])))
        self.assertFalse(open_with.can_open(app("z-f"), "image/png"))
        self.assertFalse(open_with.can_open(app("z-f"), "inode/directory"))

    def test_no_mimetype_opens_nothing(self):
        for t in ("text/plain", "image/png", "inode/directory"):
            self.assertFalse(open_with.can_open(app("z-nomime"), t))

    def test_any_file(self):
        self.assertTrue(open_with.can_open(app("z-any"), "image/png"))
        self.assertTrue(open_with.can_open(app("z-any"), "inode/directory"))
        self.assertTrue(open_with.can_open(app("z-allfiles"), "image/png"))
        self.assertFalse(open_with.can_open(app("z-allfiles"), "inode/directory"))
        # octet-stream is the parent of every file, never of a folder
        self.assertTrue(open_with.can_open(app("z-octet"), "application/pdf"))
        self.assertFalse(open_with.can_open(app("z-octet"), "inode/directory"))

    def test_wildcard(self):
        self.assertTrue(open_with.can_open(app("z-wild"), "image/png"))
        self.assertFalse(open_with.can_open(app("z-wild"), "text/plain"))

    def test_split(self):
        good, bad = open_with.split(app("z-bigu"), [P["pdf"], P["png"], P["space"]])
        self.assertEqual(good, [P["pdf"], P["space"]])
        self.assertEqual(bad, [P["png"]])


class MimeCache(unittest.TestCase):
    def test_cache_built_and_up_to_date(self):
        self.assertTrue(CACHE_BUILT)
        folder = os.path.join(DATA, "applications")
        with open(os.path.join(folder, "mimeinfo.cache")) as f:
            text = f.read()
        self.assertIn("z-f.desktop", text)
        # nothing changed: not rebuilt again
        self.assertFalse(open_with.refresh_mime_cache(folder))
        # a newer entry: rebuilt
        later = time.time() + 5
        os.utime(os.path.join(folder, "z-f.desktop"), (later, later))
        self.assertTrue(open_with.refresh_mime_cache(folder))

    def test_missing_folder(self):
        self.assertFalse(open_with.refresh_mime_cache(os.path.join(ROOT, "nowhere")))


class Lists(unittest.TestCase):
    def ids(self, types):
        return [a.get_id() for a, _d in open_with.apps_for(types)]

    def test_apps_for_one_type(self):
        ids = self.ids(["text/plain"])
        for ident in ("z-f", "z-u", "z-none", "z-bigf", "z-bigu", "z-hidden"):
            self.assertIn(ident + ".desktop", ids)
        self.assertNotIn("z-kde.desktop", ids)       # OnlyShowIn=KDE
        self.assertNotIn("z-nomime.desktop", ids)
        self.assertNotIn("z-wild.desktop", ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_apps_for_several_types(self):
        ids = self.ids(["text/plain", "image/png"])
        self.assertIn("z-bigf.desktop", ids)
        self.assertNotIn("z-f.desktop", ids)
        self.assertNotIn("z-bigu.desktop", ids)

    def test_set_default_goes_first(self):
        ok, err = open_with.set_default(app("z-u"), "text/plain")
        self.assertTrue(ok, err)
        listing = open_with.apps_for(["text/plain"])
        self.assertEqual(listing[0][0].get_id(), "z-u.desktop")
        self.assertTrue(listing[0][1])
        self.assertFalse(any(d for _a, d in listing[1:]))
        with open(os.path.join(CONF, "mimeapps.list")) as f:
            self.assertIn("text/plain=z-u.desktop", f.read())

    def test_all_apps_hides_nodisplay(self):
        ids = [a.get_id() for a in open_with.all_apps()]
        self.assertIn("z-f.desktop", ids)
        self.assertNotIn("z-hidden.desktop", ids)


class Launch(unittest.TestCase):
    TRICKY = ["space", "quotes", "shell", "unicode", "percent"]

    def setUp(self):
        for n in os.listdir(OUT):
            os.unlink(os.path.join(OUT, n))

    def test_f_one_instance_per_file(self):
        files = [P[k] for k in self.TRICKY]
        ok, err = open_with.launch(app("z-f"), files)
        self.assertTrue(ok, err)
        got = sorted(args[0] for args in collect("f", len(files)))
        self.assertEqual(got, sorted(files))

    def test_big_f_all_files_at_once(self):
        files = [P[k] for k in self.TRICKY]
        ok, err = open_with.launch(app("z-bigf"), files)
        self.assertTrue(ok, err)
        runs = collect("F", 1)
        self.assertEqual(runs, [files])

    def test_u_uris(self):
        files = [P[k] for k in self.TRICKY]
        ok, err = open_with.launch(app("z-u"), files)
        self.assertTrue(ok, err)
        got = sorted(uri_to_path(args[0]) for args in collect("u", len(files)))
        self.assertEqual(got, sorted(files))

    def test_big_u_uris(self):
        files = [P[k] for k in self.TRICKY]
        ok, err = open_with.launch(app("z-bigu"), files)
        self.assertTrue(ok, err)
        runs = collect("U", 1)
        self.assertEqual([uri_to_path(u) for u in runs[0]], files)

    def test_no_field_code_appends_the_file(self):
        ok, err = open_with.launch(app("z-none"), [P["quotes"]])
        self.assertTrue(ok, err)
        self.assertEqual(collect("none", 1), [[P["quotes"]]])

    def test_folder(self):
        ok, err = open_with.launch(app("z-folder"), [P["folder"]])
        self.assertTrue(ok, err)
        self.assertEqual(uri_to_path(collect("folder", 1)[0][0]).rstrip("/"), P["folder"])

    def test_keyfile_launcher_with_env_prefix(self):
        # what zeta-desktop builds for a program unpacked in /opt (resolved
        # absolute program, Blender's "env -u WAYLAND_DISPLAY" prefix)
        kf = GLib.KeyFile()
        load(kf, "[Desktop Entry]\nType=Application\nName=Opt app\n"
                 "Exec=env -u WAYLAND_DISPLAY %s kf %%f\nMimeType=text/plain;\n"
                 "Path=%s\n" % (QUOTED_DUMP, DUMP_DIR))
        a = open_with.app_from_keyfile(kf)
        self.assertIsNotNone(a)
        self.assertTrue(open_with.can_open(a, "text/plain"))
        ok, err = open_with.launch(a, [P["unicode"]])
        self.assertTrue(ok, err)
        self.assertEqual(collect("kf", 1), [[P["unicode"]]])

    def test_keyfile_refused(self):
        kf = GLib.KeyFile()
        load(kf, "[Desktop Entry]\nType=Application\nName=Gone\n"
                 "Exec=/nonexistent/program %f\n")
        self.assertIsNone(open_with.app_from_keyfile(kf))
        self.assertIsNone(open_with.app_from_keyfile(None))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
