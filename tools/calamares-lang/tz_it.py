#!/usr/bin/env python3
"""Generate tz_it_IT.ts (Italian time zone names for Calamares) from tz_en_upstream.ts.
Upstream has no Italian translation: regions and cities that have an Italian name."""
import json
import re
from xml.sax.saxutils import escape

# Italian names of regions and cities (localization data): data/tz_it.json
with open("data/tz_it.json", encoding="utf-8") as _f:
    _DATA = json.load(_f)
REGIONS, NAMES = _DATA["regions"], _DATA["names"]

def main():
    s = open("tz_en_upstream.ts", encoding="utf-8").read()
    s = s.replace('language="en_US"', 'language="it_IT"')

    def repl(m):
        src, com = m.group(2), m.group(4)
        tr = (REGIONS if com == "tz_regions" else NAMES).get(src)
        if tr is None or tr == src:
            return m.group(0)
        return m.group(1) + m.group(3) + '<translation>%s</translation>' % escape(tr)

    s = re.sub(r'(<source>(.*?)</source>\s*)(<comment>(.*?)</comment>\s*)<translation type="unfinished"></translation>',
               repl, s)
    open("tz_it_IT.ts", "w", encoding="utf-8").write(s)
    print("translated:", s.count("<translation>"))

main()
