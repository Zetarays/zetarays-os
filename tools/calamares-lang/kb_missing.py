import xml.etree.ElementTree as ET
rules = ET.parse("/usr/share/X11/xkb/rules/evdev.xml").getroot()
t = ET.parse("/w/kb_it_IT.ts").getroot()
have = {}
for ctx in t.findall("context"):
    have[ctx.find("name").text] = {m.find("source").text for m in ctx.findall("message")}
out = []
for l in rules.iter("layout"):
    d = l.find("configItem/description").text
    if d not in have["kb_layouts"]: out.append(("kb_layouts", d))
for m in rules.iter("model"):
    d = m.find("configItem/description").text
    if d not in have["kb_models"]: out.append(("kb_models", d))
for v in rules.iter("variant"):
    d = v.find("configItem/description").text
    if d not in have["kb_variants"]: out.append(("kb_variants", d))
print(len(out))
for c, d in out: print(c + "\t" + d)
