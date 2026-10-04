#!/usr/bin/env python3
"""Aggiunge a kb_it_IT.ts le voci di xkb-data (Debian 13) assenti dal catalogo di
Calamares, tradotte con il catalogo italiano di xkeyboard-config. Gira nel container."""
import gettext
import xml.etree.ElementTree as ET

it = gettext.translation("xkeyboard-config", "/usr/share/locale", languages=["it"])
rules = ET.parse("/usr/share/X11/xkb/rules/evdev.xml").getroot()
want = {"kb_layouts": set(), "kb_variants": set(), "kb_models": set()}
for m in rules.iter("model"):
    d = m.find("configItem/description")
    if d is not None: want["kb_models"].add(d.text)
for l in rules.iter("layout"):
    d = l.find("configItem/description")
    if d is not None: want["kb_layouts"].add(d.text)
    for v in l.iter("variant"):
        d = v.find("configItem/description")
        if d is not None: want["kb_variants"].add(d.text)

t = ET.parse("/w/kb_it_IT.ts"); root = t.getroot()
added = 0
for ctx in root.findall("context"):
    name = ctx.find("name").text
    have = {m.find("source").text for m in ctx.findall("message")}
    for src in sorted(want.get(name, ())):
        if src in have: continue
        tr = it.gettext(src)
        if tr == src: continue
        msg = ET.SubElement(ctx, "message")
        ET.SubElement(msg, "source").text = src
        ET.SubElement(msg, "comment").text = name
        ET.SubElement(msg, "translation").text = tr
        added += 1
t.write("/w/kb_it_IT.ts", encoding="utf-8", xml_declaration=True)
print("aggiunte", added, "| Indonesian (Latin) ->", it.gettext("Indonesian (Latin)"))
