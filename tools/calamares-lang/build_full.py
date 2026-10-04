import re, xml.etree.ElementTree as ET
exec(open('it_fill.py').read().split("root = ET.Element")[0].split("miss = json.load")[0])  # imports
src_py = open('it_fill.py').read()
T = eval(src_py[src_py.index("T = {")+4: src_py.index("\n}\n")+2])
T["Creating new <strong>%1</strong> partition table on <strong>%2</strong> (%3)…"] = "Creazione della nuova tabella delle partizioni <strong>%1</strong> su <strong>%2</strong> (%3)…"
FIX = {
 "Create new %1MiB partition on %3 (%2) with entries %4": "Crea una nuova partizione %4 da %1 MiB su %3 (%2)",
 "Create new <strong>%1MiB</strong> partition on <strong>%3</strong> (%2) with entries <em>%4</em>": "Crea una nuova partizione <em>%4</em> da <strong>%1 MiB</strong> su <strong>%3</strong> (%2)",
 "Create user <strong>%1</strong>": "Crea l'utente <strong>%1</strong>",
 "Install %1 on <strong>new</strong> %2 system partition with features <em>%3</em>": "Installa %1 sulla <strong>nuova</strong> partizione di sistema %2 con opzioni <em>%3</em>",
 "The <strong>boot environment</strong> of this system.<br><br>Older x86 systems only support <strong>BIOS</strong>.<br>Modern systems usually use <strong>EFI</strong>, but may also show up as BIOS if started in compatibility mode.": "L'<strong>ambiente di avvio</strong> di questo sistema.<br><br>I sistemi x86 più vecchi supportano solo il <strong>BIOS</strong>.<br>I sistemi moderni usano di solito <strong>EFI</strong>, ma possono apparire come BIOS se avviati in modalità compatibile.",
 "The %1 setup program is about to make changes to your disk in order to set up %2.<br/><strong>You will not be able to undo these changes.</strong>": "Il programma d'installazione %1 sta per modificare il disco per installare %2.<br/><strong>Non sarà possibile annullare queste modifiche.</strong>",
 "The %1 installer is about to make changes to your disk in order to install %2.<br/><strong>You will not be able to undo these changes.</strong>": "Il programma d'installazione %1 sta per modificare il disco per installare %2.<br/><strong>Non sarà possibile annullare queste modifiche.</strong>",
 "<h1>All done.</h1><br/>%1 has been installed on your computer.<br/>You may now restart into your new system, or continue using the %2 Live environment.": "<h1>Tutto fatto.</h1><br/>%1 è stato installato sul computer.<br/>Ora puoi riavviare e usare il nuovo sistema, oppure continuare a usare %2 in modalità Live.",
 "<h1>Installation Failed</h1><br/>%1 has not been installed on your computer.<br/>The error message was: %2.": "<h1>Installazione non riuscita</h1><br/>%1 non è stato installato sul computer.<br/>Il messaggio di errore è: %2.",
 "<p>This computer does not satisfy some of the recommended requirements for setting up %1.<br/>\n        Setup can continue, but some features might be disabled.</p>": "<p>Questo computer non soddisfa alcuni requisiti consigliati per installare %1.<br/>\nL'installazione può continuare, ma alcune funzioni potrebbero essere disattivate.</p>",
 "<p>This computer does not satisfy the minimum requirements for installing %1.<br/>\n        Installation cannot continue.</p>": "<p>Questo computer non soddisfa i requisiti minimi per installare %1.<br/>\nL'installazione non può continuare.</p>",
}
PLUR = {
 "Waiting for %n module(s)…": ["In attesa di %n modulo…", "In attesa di %n moduli…"],
 "(%n second(s))": ["(%n secondo)", "(%n secondi)"],
}
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
print("modificate", n)
