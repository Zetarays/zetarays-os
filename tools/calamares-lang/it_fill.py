import json, xml.etree.ElementTree as ET
miss = json.load(open('missing.json'))
T = {
 "Crashes Calamares, so that Dr. Konqi can look at it.": "Arresta l'installer per consentire l'analisi dell'errore.",
 "Main script file %1 for python job %2 raised an exception.": "Lo script principale %1 del passaggio %2 ha generato un'eccezione.",
 "Main script file %1 for python job %2 returned invalid results.": "Lo script principale %1 del passaggio %2 ha restituito risultati non validi.",
 "Main script file %1 for python job %2 does not contain a run() function.": "Lo script principale %1 del passaggio %2 non contiene una funzione run().",
 "Running %1 operation…": "Esecuzione dell'operazione %1…",
 'Boost.Python error in job "%1"': "Errore Python nel passaggio «%1»",
 "QML step <i>%1</i>.": "Passaggio QML <i>%1</i>.",
 "Unparseable Python error": "Errore Python non interpretabile",
 "Unparseable Python traceback": "Traccia Python non interpretabile",
 "Unfetchable Python error": "Errore Python non recuperabile",
 "Set filesystem label <strong>%1</strong> to partition <strong>%2</strong>": "Imposta l'etichetta <strong>%1</strong> sulla partizione <strong>%2</strong>",
 "Setting filesystem label <strong>%1</strong> to partition <strong>%2</strong>…": "Impostazione dell'etichetta <strong>%1</strong> sulla partizione <strong>%2</strong>…",
 "Keyboard model has been set to %1.": "Il modello della tastiera è stato impostato su %1.",
 "Set timezone to %1.": "Il fuso orario sarà impostato su %1.",
 "Create new <strong>%1MiB</strong> partition on <strong>%3</strong> (%2)": "Crea una nuova partizione da <strong>%1 MiB</strong> su <strong>%3</strong> (%2)",
 "Create new <strong>%2MiB</strong> partition on <strong>%4</strong> (%3) with file system <strong>%1</strong>": "Crea una nuova partizione da <strong>%2 MiB</strong> su <strong>%4</strong> (%3) con file system <strong>%1</strong>",
 "Creating new <strong>%1</strong> partition table on <strong>%2</strong> (%3)…": "Crea una nuova tabella delle partizioni <strong>%1</strong> su <strong>%2</strong> (%3)",
 "Creating new volume group named %1…": "Creazione del gruppo di volumi %1…",
 "Creating new volume group named <strong>%1</strong>…": "Creazione del gruppo di volumi <strong>%1</strong>…",
 "Deactivating volume group named %1…": "Disattivazione del gruppo di volumi %1…",
 "Deactivating volume group named <strong>%1</strong>…": "Disattivazione del gruppo di volumi <strong>%1</strong>…",
 "Performing dummy C++ job…": "Esecuzione del passaggio di prova…",
 "Missing tools": "Strumenti mancanti",
 "The <i>%1</i> tool is not installed on the system.": "Lo strumento <i>%1</i> non è installato nel sistema.",
 "Invalid fsarchiver configuration": "Configurazione di fsarchiver non valida",
 "The source archive <i>%1</i> does not exist.": "L'archivio di origine <i>%1</i> non esiste.",
 "No destination could be found for <i>%1</i>.": "Nessuna destinazione trovata per <i>%1</i>.",
 "Install %1 on <strong>new</strong> %2 system partition": "Installa %1 sulla <strong>nuova</strong> partizione di sistema %2",
 "Set up <strong>new</strong> %2 partition with mount point <strong>%1</strong> and features <em>%3</em>": "Configura la <strong>nuova</strong> partizione %2 con punto di montaggio <strong>%1</strong> e opzioni <em>%3</em>",
 "Set up <strong>new</strong> %2 partition with mount point <strong>%1</strong>%3": "Configura la <strong>nuova</strong> partizione %2 con punto di montaggio <strong>%1</strong>%3",
 "Install %2 on %3 system partition <strong>%1</strong> with features <em>%4</em>": "Installa %2 sulla partizione di sistema %3 <strong>%1</strong> con opzioni <em>%4</em>",
 "Install %2 on %3 system partition <strong>%1</strong>": "Installa %2 sulla partizione di sistema %3 <strong>%1</strong>",
 "Set up %3 partition <strong>%1</strong> with mount point <strong>%2</strong> and features <em>%4</em>": "Configura la partizione %3 <strong>%1</strong> con punto di montaggio <strong>%2</strong> e opzioni <em>%4</em>",
 "Set up %3 partition <strong>%1</strong> with mount point <strong>%2</strong>%4…": "Configura la partizione %3 <strong>%1</strong> con punto di montaggio <strong>%2</strong>%4…",
 "Format partition %1 (file system: %2, size: %3 MiB) on %4": "Formatta la partizione %1 (file system: %2, dimensione: %3 MiB) su %4",
 "Format <strong>%3MiB</strong> partition <strong>%1</strong> with file system <strong>%2</strong>": "Formatta la partizione <strong>%1</strong> da <strong>%3 MiB</strong> con file system <strong>%2</strong>",
 "Select your preferred region, or use the default settings": "Scegli la tua area geografica o usa le impostazioni predefinite",
 "Select your preferred zone within your region": "Scegli il fuso orario della tua area",
 "You can fine-tune language and locale settings below": "Qui sotto puoi regolare lingua e formati locali",
 "<strong>Erase</strong> disk <strong>%2</strong> (%3) and install %1": "<strong>Cancella</strong> il disco <strong>%2</strong> (%3) e installa %1",
 "<strong>Replace</strong> a partition on disk <strong>%2</strong> (%3) with %1": "<strong>Sostituisci</strong> una partizione del disco <strong>%2</strong> (%3) con %1",
 "<strong>Manual</strong> partitioning on disk <strong>%1</strong> (%2)": "Partizionamento <strong>manuale</strong> del disco <strong>%1</strong> (%2)",
 "Create a swap file.": "Crea un file di swap.",
 "Applying Plasma Look-and-Feel…": "Applicazione dell'aspetto…",
 "Look-and-Feel": "Aspetto",
 "Removing Volume Group named %1…": "Rimozione del gruppo di volumi %1…",
 "Removing Volume Group named <strong>%1</strong>…": "Rimozione del gruppo di volumi <strong>%1</strong>…",
 "Resize <strong>%2MiB</strong> partition <strong>%1</strong> to <strong>%3MiB</strong>": "Ridimensiona la partizione <strong>%1</strong> da <strong>%2 MiB</strong> a <strong>%3 MiB</strong>",
 "Resize volume group named <strong>%1</strong> from <strong>%2</strong> to <strong>%3</strong>": "Ridimensiona il gruppo di volumi <strong>%1</strong> da <strong>%2</strong> a <strong>%3</strong>",
 "Resizing volume group named %1 from %2 to %3…": "Ridimensionamento del gruppo di volumi %1 da %2 a %3…",
 "Set flags on partition %1": "Imposta gli attributi della partizione %1",
 "Set flags on %1MiB %2 partition": "Imposta gli attributi della partizione %2 da %1 MiB",
 "Set flags on new partition": "Imposta gli attributi della nuova partizione",
 "Clear flags on partition <strong>%1</strong>": "Rimuovi gli attributi della partizione <strong>%1</strong>",
 "Clear flags on %1MiB <strong>%2</strong> partition": "Rimuovi gli attributi della partizione <strong>%2</strong> da %1 MiB",
 "Clear flags on new partition": "Rimuovi gli attributi della nuova partizione",
 "Set flags on partition <strong>%1</strong> to <strong>%2</strong>": "Imposta l'attributo <strong>%2</strong> sulla partizione <strong>%1</strong>",
 "Set flags on %1MiB <strong>%2</strong> partition to <strong>%3</strong>": "Imposta l'attributo <strong>%3</strong> sulla partizione <strong>%2</strong> da %1 MiB",
 "Set flags on new partition to <strong>%1</strong>": "Imposta l'attributo <strong>%1</strong> sulla nuova partizione",
 "Clearing flags on partition <strong>%1</strong>…": "Rimozione degli attributi della partizione <strong>%1</strong>…",
 "Clearing flags on %1MiB <strong>%2</strong> partition…": "Rimozione degli attributi della partizione <strong>%2</strong> da %1 MiB…",
 "Clearing flags on new partition…": "Rimozione degli attributi della nuova partizione…",
 "Setting flags <strong>%2</strong> on partition <strong>%1</strong>…": "Impostazione dell'attributo <strong>%2</strong> sulla partizione <strong>%1</strong>…",
 "Setting flags <strong>%3</strong> on %1MiB <strong>%2</strong> partition…": "Impostazione dell'attributo <strong>%3</strong> sulla partizione <strong>%2</strong> da %1 MiB…",
 "Setting flags <strong>%1</strong> on new partition…": "Impostazione dell'attributo <strong>%1</strong> sulla nuova partizione…",
 "Configuring <pre>sudo</pre> users…": "Configurazione degli amministratori…",
 "Invalid tarball configuration": "Configurazione dell'archivio non valida",
 "Tarball extract file %1": "Estrazione dell'archivio %1",
 "Unpack filesystems": "Copia del sistema",
 "Invalid unsquash configuration": "Configurazione dell'estrazione non valida",
 "Unsquash file %1": "Estrazione del file %1",
 "Master Boot Record (MBR)": "Master Boot Record (MBR)",
 "Fi&le System:": "&File system:",
}
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
# plurale
c = ctxs.setdefault('Calamares::RequirementsChecker', ET.SubElement(root, 'context'))
if c.find('name') is None: ET.SubElement(c, 'name').text = 'Calamares::RequirementsChecker'
msg = ET.SubElement(c, 'message', numerus="yes")
ET.SubElement(msg, 'source').text = 'Waiting for %n module(s)…'
ET.SubElement(msg, 'comment').text = '@status'
tr = ET.SubElement(msg, 'translation')
ET.SubElement(tr, 'numerusform').text = 'In attesa di %n modulo…'
ET.SubElement(tr, 'numerusform').text = 'In attesa di %n moduli…'
ET.ElementTree(root).write('calamares-zetarays_it.ts', encoding='utf-8', xml_declaration=True)
print("tradotte", done+1, "su", len(miss))
print("non coperte:", [m['src'][:50] for m in miss if not m['num'] and m['src'] not in T])
