#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write the sizes and SHA-256 checksums of the release files into the website.

    tools/site-downloads.py INDEX_HTML DELIVERY_DIR VERSION

Run by tools/sync-site.sh at release time. For the four images
(zetarays-VERSION-ARCH.{iso,ova}) and the two upgrade files
(zetarays-VERSION-upgrade-ARCH.run) in DELIVERY_DIR it reads the size of the
file and the checksum in FILE.sha256, then rewrites in the page:
  - the text of each download link, "LABEL · SIZE" in both languages
    (data-en with a decimal point, the Italian with a decimal comma):
    images in GB with one decimal, upgrade files in whole MB;
  - the row of the file in the checksum table (<td class="f">NAME</td>).
Whatever the link text or the table cell held before (a placeholder or the
values of an earlier build) is replaced, so running it again is harmless.
It stops, changing nothing, if a file, a checksum, a link or a table row is
missing or ambiguous.
"""
import os
import re
import sys

ARCHES = ("amd64", "arm64")


def release_files(version):
    """(file name, short name in the checksum table) in page order."""
    files = [("zetarays-%s-%s.%s" % (version, a, k), "%s.%s" % (a, k))
             for a in ARCHES for k in ("iso", "ova")]
    files += [("zetarays-%s-upgrade-%s.run" % (version, a), "upgrade-%s.run" % a) for a in ARCHES]
    return files


def human_size(name, size):
    """English and Italian size text, the way the page writes them."""
    if name.endswith(".run"):
        en = "%d MB" % max(1, round(size / 1e6))
        return en, en
    en = "%.1f GB" % (size / 1e9)
    return en, en.replace(".", ",")


def read_checksum(path, name):
    try:
        fields = open(path + ".sha256", encoding="ascii").read().split()
    except (OSError, UnicodeDecodeError) as e:
        sys.exit("checksum not readable: %s.sha256 (%s)" % (path, e))
    if len(fields) < 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
        sys.exit("not a SHA-256 checksum in %s.sha256" % path)
    if os.path.basename(fields[1].lstrip("*")) != name:
        sys.exit("%s.sha256 names another file: %s" % (path, fields[1]))
    return fields[0]


def fill(page, name, short, size_en, size_it, digest):
    # the download link: <a class="..." href=".../NAME" ... data-en="LABEL · X">LABEL · X</a>
    link = re.compile(r'(<a class="(?:iso|ova|run)" href="[^"]*/%s"[^>]*\sdata-en=")([^"]*)("[^>]*>)([^<]*)(</a>)'
                      % re.escape(name))
    found = link.findall(page)
    if len(found) != 1:
        sys.exit("index.html: expected one download link for %s, found %d" % (name, len(found)))

    def new_link(m):
        label_en, label_it = m.group(2).split(" · ")[0], m.group(4).split(" · ")[0]
        return "%s%s · %s%s%s · %s%s" % (m.group(1), label_en, size_en, m.group(3),
                                          label_it, size_it, m.group(5))
    page = link.sub(new_link, page)
    row = re.compile(r'(<td class="f">%s</td><td class="h">)[^<]*(</td>)' % re.escape(short))
    if len(row.findall(page)) != 1:
        sys.exit("index.html: expected one checksum row for %s" % short)
    return row.sub(lambda m: m.group(1) + digest + m.group(2), page)


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__)
    index, delivery, version = argv[1:]
    page = original = open(index, encoding="utf-8").read()
    for name, short in release_files(version):
        path = os.path.join(delivery, name)
        if not os.path.isfile(path):
            sys.exit("missing in the delivery folder: %s" % path)
        size_en, size_it = human_size(name, os.path.getsize(path))
        digest = read_checksum(path, name)
        page = fill(page, name, short, size_en, size_it, digest)
        print("site: %-34s %8s  %s" % (name, size_en, digest))
    if page != original:
        with open(index + ".partial", "w", encoding="utf-8") as f:
            f.write(page)
        os.replace(index + ".partial", index)
        print("site: index.html updated")
    else:
        print("site: index.html already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
