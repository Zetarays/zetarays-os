#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate the website source (site-zetarays/index.html).

    tools/check-site.py [PATH_TO_INDEX_HTML]

Checks:
- HTML nesting: every element is closed in the right order;
- every element with Italian text has a non-empty English version
  (data-en), and so do accessibility labels and image descriptions that
  have an English attribute (data-en-aria, data-en-alt);
- terminology (docs/GLOSSARY.md): "click" also in the Italian text (no
  Italian form of the word), no "Donate" (nor its Italian forms) anywhere:
  the project uses "Support" (the patterns are in data/check-site.json);
- the support link points to the PayPal pool and every in-page link (#id)
  has a target;
- the downloads table lists four images with 64-character SHA-256 codes.

Exit code 1 when a check fails.
"""
import html
import json
import os
import re
import sys
from html.parser import HTMLParser

VOID = {"meta", "link", "img", "br", "hr", "input", "source", "area", "col", "base", "wbr",
        "path", "circle", "rect", "polyline", "line", "polygon", "stop", "use", "ellipse"}
PAYPAL = "https://www.paypal.com/pool/9sSHdLylmE"
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "check-site.json"),
          encoding="utf-8") as _f:
    TERMS = json.load(_f)


class Nesting(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.ids, self.links = [], [], set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        else:
            self.errors.append("line %d: </%s> closes <%s>" % (
                self.getpos()[0], tag, self.stack[-1][0] if self.stack else "nothing"))


def main(argv):
    path = argv[1] if len(argv) > 1 else "site-zetarays/index.html"
    text = open(path, encoding="utf-8").read()
    body = text[text.index("<header"):]
    problems = []

    p = Nesting()
    p.feed(text)
    problems += p.errors[:10]
    if p.stack:
        problems.append("unclosed elements: %s" % ", ".join(t for t, _ in p.stack[:5]))

    for m in re.finditer(r'<([a-zA-Z0-9]+)[^>]*\sdata-en="([^"]*)"[^>]*>(.*?)</\1>', body, re.S):
        it = re.sub(r"<[^>]+>|\s+", " ", m.group(3)).strip()
        if it and not html.unescape(m.group(2)).strip():
            problems.append("empty English text for: %s" % it[:60])
    for attr in ("data-en-aria", "data-en-alt"):
        for m in re.finditer(r'%s="([^"]*)"' % attr, body):
            if not m.group(1).strip():
                problems.append("empty %s" % attr)

    visible_it = re.sub(r'data-en(-[a-z]+)?="[^"]*"', "", body)
    visible_it = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", visible_it, flags=re.S)
    for word in re.findall(TERMS["italian_click"], visible_it, re.I):
        problems.append('terminology: "%s" (write "click", see docs/GLOSSARY.md)' % word)
    for word in re.findall(TERMS["donate"], body):
        problems.append('terminology: "%s" (the project uses "Support")' % word)

    if not any(h.startswith(PAYPAL) for h in p.links):
        problems.append("the support link to the PayPal pool is missing")
    for h in p.links:
        if h.startswith("#") and len(h) > 1 and h[1:] not in p.ids:
            problems.append("in-page link without a target: %s" % h)

    sums = re.findall(r'<td class="h">([0-9a-f]+)</td>', body)
    if len(sums) != 4 or any(len(s) != 64 for s in sums):
        problems.append("downloads: expected four SHA-256 codes, found %d" % len(sums))

    for line in problems:
        print("site: %s" % line)
    print("site: %s (%d problem(s))" % ("OK" if not problems else "FAILED", len(problems)),
          file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
