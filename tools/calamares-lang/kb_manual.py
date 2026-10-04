#!/usr/bin/env python3
"""Traduzioni italiane per le voci di xkb-data 2.x assenti dal catalogo di Calamares
e da quello di xkeyboard-config (elenco in kb_missing.txt). Aggiunge a kb_it_IT.ts."""
import xml.etree.ElementTree as ET

T = {
 "Arabic (Egypt)": "Araba (Egitto)", "Arabic (Iraq)": "Araba (Iraq)",
 "Berber (Algeria, Latin)": "Berbera (Algeria, latina)", "Dari": "Dari",
 "English (Australia)": "Inglese (Australia)", "English (New Zealand)": "Inglese (Nuova Zelanda)",
 "Indonesian (Latin)": "Indonesiana (latina)", "N'Ko (AZERTY)": "N'Ko (AZERTY)",
 "A user-defined custom Layout": "Disposizione personalizzata dall'utente",
 "Azona RF2300 Wireless Internet": "Azona RF2300 Wireless Internet", "Compal FL90": "Compal FL90",
 "Hewlett-Packard SK-2501 Multimedia": "Hewlett-Packard SK-2501 Multimedia",
 "PinePhone Keyboard": "Tastiera PinePhone",
 "Arabic (Macintosh, phonetic)": "Araba (Macintosh, fonetica)", "Tarifit": "Tarifit",
 "Belarusian (phonetic)": "Bielorussa (fonetica)", "Berber (Algeria, Tifinagh)": "Berbera (Algeria, tifinagh)",
 "Kabyle (AZERTY, with dead keys)": "Cabila (AZERTY, con tasti muti)",
 "Kabyle (QWERTY, UK, with dead keys)": "Cabila (QWERTY, Regno Unito, con tasti muti)",
 "Kabyle (QWERTY, US, with dead keys)": "Cabila (QWERTY, USA, con tasti muti)",
 "Burmese (Zawgyi)": "Birmana (Zawgyi)", "Mon": "Mon", "Mon (A1)": "Mon (A1)", "Shan": "Shan",
 "Shan (Zawgyi)": "Shan (Zawgyi)",
 "Hanyu Pinyin Letters (with AltGr dead keys)": "Lettere Hanyu Pinyin (con tasti muti AltGr)",
 "Czech (extra backslash)": "Ceca (barra rovesciata aggiuntiva)",
 "Czech (QWERTY, extra backslash)": "Ceca (QWERTY, barra rovesciata aggiuntiva)",
 "Czech (QWERTZ, Windows)": "Ceca (QWERTZ, Windows)", "Czech (QWERTY, Windows)": "Ceca (QWERTY, Windows)",
 "Russian (Czechia, phonetic)": "Russa (Cechia, fonetica)", "Dari (Afghanistan, OLPC)": "Dari (Afghanistan, OLPC)",
 "Dutch (US)": "Olandese (USA)", "Maori": "Maori", "English (UK, Colemak-DH)": "Inglese (Regno Unito, Colemak-DH)",
 "Scottish Gaelic": "Gaelico scozzese", "English (Colemak-DH)": "Inglese (Colemak-DH)",
 "English (Colemak-DH Wide)": "Inglese (Colemak-DH largo)",
 "English (Colemak-DH Ortholinear)": "Inglese (Colemak-DH ortolineare)",
 "English (Colemak-DH ISO)": "Inglese (Colemak-DH ISO)",
 "English (Colemak-DH Wide ISO)": "Inglese (Colemak-DH largo ISO)",
 "English (Dvorak, Macintosh)": "Inglese (Dvorak, Macintosh)",
 "French (Ergo‑L)": "Francese (Ergo‑L)", "French (Ergo‑L, ISO variant)": "Francese (Ergo‑L, variante ISO)",
 "Breton (France)": "Bretone (Francia)", "Canadian (CSA)": "Canadese (CSA)",
 "Hebrew (SI-1452-2)": "Ebraica (SI-1452-2)", "Assamese (KaGaPa, phonetic)": "Assamese (KaGaPa, fonetica)",
 "Bangla (India, KaGaPa, phonetic)": "Bengalese (India, KaGaPa, fonetica)",
 "Bangla (India, Baishakhi InScript)": "Bengalese (India, Baishakhi InScript)",
 "Gujarati (KaGaPa, phonetic)": "Gujarati (KaGaPa, fonetica)",
 "Malayalam (enhanced InScript, with rupee)": "Malayalam (InScript avanzata, con rupia)",
 "Malayalam (Poorna, extended InScript)": "Malayalam (Poorna, InScript estesa)",
 "Manipuri (Meitei)": "Manipuri (meitei)", "Marathi (enhanced InScript)": "Marathi (InScript avanzata)",
 "Oriya (Bolnagri)": "Oriya (Bolnagri)", "Oriya (Wx)": "Oriya (Wx)", "Santali (Ol Chiki)": "Santali (Ol Chiki)",
 "Tamil (InScript, with Arabic numerals)": "Tamil (InScript, con numeri arabi)",
 "Tamil (InScript, with Tamil numerals)": "Tamil (InScript, con numeri tamil)",
 "Indic IPA": "IPA indiano", "Indonesian (Arab Pegon, phonetic)": "Indonesiana (Arab Pegon, fonetica)",
 "Javanese": "Giavanese", "Latvian (Modern Latin)": "Lettone (latino moderno)",
 "Latvian (Modern Cyrillic)": "Lettone (cirillico moderno)", "Lithuanian (IBM)": "Lituana (IBM)",
 "Lithuanian (Ratise)": "Lituana (Ratise)", "Maltese (US, with AltGr overrides)": "Maltese (USA, con AltGr)",
 "Gagauz (Moldova)": "Gagauza (Moldavia)", "Norwegian (Colemak-DH)": "Norvegese (Colemak-DH)",
 "Norwegian (Colemak-DH Wide)": "Norvegese (Colemak-DH largo)", "Persian (Windows)": "Persiana (Windows)",
 "Azerbaijani (Iran)": "Azera (Iran)", "Russian (Brazil, phonetic)": "Russa (Brasile, fonetica)",
 "Russian (engineering, RU)": "Russa (ingegneristica, RU)", "Russian (engineering, EN)": "Russa (ingegneristica, EN)",
 "Abkhazian (Russia)": "Abcasa (Russia)", "Slovak (extra backslash)": "Slovacca (barra rovesciata aggiuntiva)",
 "Slovak (QWERTY, extra backslash)": "Slovacca (QWERTY, barra rovesciata aggiuntiva)",
 "Turkish (E)": "Turca (E)", "Ukrainian (macOS)": "Ucraina (macOS)", "Vietnamese (France)": "Vietnamita (Francia)",
}

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
print("aggiunte", added, "senza traduzione:", missing)
