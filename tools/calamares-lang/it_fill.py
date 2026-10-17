import json, xml.etree.ElementTree as ET
miss = json.load(open('missing.json'))
# Italian translations (localization data): data/it_fill.json
DATA = json.load(open('data/it_fill.json', encoding='utf-8'))
T = DATA['translations']
root = ET.Element('TS', version="2.1", language="it_IT")
ctxs = {}
done = 0
for m in miss:
    src = m['src']
    if m['num']:
        continue
    if src not in T:
        continue
    c = ctxs.get(m['ctx'])
    if c is None:
        c = ET.SubElement(root, 'context'); ET.SubElement(c, 'name').text = m['ctx']; ctxs[m['ctx']] = c
    msg = ET.SubElement(c, 'message')
    ET.SubElement(msg, 'source').text = src
    if m['comment']:
        ET.SubElement(msg, 'comment').text = m['comment']
    ET.SubElement(msg, 'translation').text = T[src]
    done += 1
# plural
c = ctxs.setdefault('Calamares::RequirementsChecker', ET.SubElement(root, 'context'))
if c.find('name') is None: ET.SubElement(c, 'name').text = 'Calamares::RequirementsChecker'
msg = ET.SubElement(c, 'message', numerus="yes")
ET.SubElement(msg, 'source').text = 'Waiting for %n module(s)…'
ET.SubElement(msg, 'comment').text = '@status'
tr = ET.SubElement(msg, 'translation')
for form in DATA['waiting_plural']:
    ET.SubElement(tr, 'numerusform').text = form
ET.ElementTree(root).write('calamares-zetarays_it.ts', encoding='utf-8', xml_declaration=True)
print("translated", done+1, "of", len(miss))
print("not covered:", [m['src'][:50] for m in miss if not m['num'] and m['src'] not in T])
