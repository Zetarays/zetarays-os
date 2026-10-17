#!/usr/bin/env python3
"""Italian translations for the xkb-data 2.x entries missing from both the Calamares
and the xkeyboard-config catalogs (listed in kb_missing.txt). Adds them to kb_it_IT.ts."""
import json
import xml.etree.ElementTree as ET

# Italian keyboard names (localization data): data/kb_manual.json
T = json.load(open("data/kb_manual.json", encoding="utf-8"))["translations"]

rows = [l.rstrip("\n").split("\t") for l in open("kb_missing.txt", encoding="utf-8").readlines()[1:] if "\t" in l]
t = ET.parse("kb_it_IT.ts"); root = t.getroot()
ctxs = {c.find("name").text: c for c in root.findall("context")}
added, missing = 0, []
for ctx, src in rows:
    tr = T.get(src)
    if tr is None:
        missing.append(src); continue
    msg = ET.SubElement(ctxs[ctx], "message")
    ET.SubElement(msg, "source").text = src
    ET.SubElement(msg, "comment").text = ctx
    ET.SubElement(msg, "translation").text = tr
    added += 1
t.write("kb_it_IT.ts", encoding="utf-8", xml_declaration=True)
print("added", added, "without translation:", missing)
