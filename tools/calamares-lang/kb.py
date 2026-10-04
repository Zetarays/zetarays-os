import re, xml.etree.ElementTree as ET
# msgid -> msgstr dal .po di xkeyboard-config
po=open('/w/xkb-it.po',encoding='utf-8').read()
tr={}
for m in re.finditer(r'(?:msgctxt ".*"\n)?msgid ((?:".*"\n)+)msgstr ((?:".*"\n)+)', po):
    j=lambda x: ''.join(re.findall(r'"(.*)"',x)).replace('\\"','"').replace('\\\\','\\')
    a,b=j(m.group(1)),j(m.group(2))
    if a and b: tr[a]=b
t=ET.parse('/w/kb_en.ts'); root=t.getroot(); root.set('language','it_IT')
n=tot=0
for ctx in root.findall('context'):
    for msg in ctx.findall('message'):
        tot+=1
        s=msg.find('source').text or ''
        x=msg.find('translation')
        if s in tr:
            x.text=tr[s]; x.attrib.pop('type',None); n+=1
        else:
            x.set('type','unfinished'); x.text=None
t.write('/w/kb_it_IT.ts',encoding='utf-8',xml_declaration=True)
print('tradotte',n,'su',tot); print('Italian ->',tr.get('Italian'),'| Default ->',tr.get('Default'),'| Generic 105-key PC ->',tr.get('Generic 105-key PC'))
