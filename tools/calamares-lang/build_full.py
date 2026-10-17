import json, xml.etree.ElementTree as ET
# Italian translations and corrections (localization data): data/it_fill.json
# (the translations of the missing messages) and data/build_full.json
T = json.load(open('data/it_fill.json', encoding='utf-8'))['translations']
DATA = json.load(open('data/build_full.json', encoding='utf-8'))
T.update(DATA['extra'])
FIX = DATA['fix']
PLUR = DATA['plural']
t = ET.parse('it.ts'); n = 0
for ctx in t.getroot().findall('context'):
    for m in ctx.findall('message'):
        s = m.find('source').text or ''; tr = m.find('translation')
        if tr is None or tr.get('type') in ('vanished', 'obsolete'): continue
        if m.get('numerus') == 'yes':
            if s in PLUR:
                for f in list(tr): tr.remove(f)
                tr.text = None
                for x in PLUR[s]: ET.SubElement(tr, 'numerusform').text = x
                tr.attrib.pop('type', None); n += 1
            continue
        empty = tr.get('type') == 'unfinished' or not (tr.text or '').strip()
        if s in FIX or (empty and s in T):
            tr.text = FIX.get(s, T.get(s)); tr.attrib.pop('type', None); n += 1
t.write('calamares_it_IT.ts', encoding='utf-8', xml_declaration=True)
print("changed", n)
