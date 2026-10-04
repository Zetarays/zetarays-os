# ZETA RAYS OS — condizioni d'uso

## Che cos'è

ZETA RAYS OS è un sistema operativo costruito sulla base di Debian GNU/Linux e
composto in larga parte da software libero di terze parti, con in più una
scrivania, applicazioni di sistema, un tema e dei testi scritti per ZETA RAYS.

L'elenco completo dei componenti e delle loro licenze è in `LICENZE.md`,
accanto a questo file. Che cosa esce dal computer è scritto in `PRIVACY.md`.

## Licenze

Ogni componente di terze parti resta dei suoi autori e si usa secondo la
**propria** licenza: GPL, LGPL, MIT, BSD, Apache e le altre elencate in
`LICENZE.md`. Niente in questo documento restringe i diritti che quelle
licenze ti danno — e dove ci fosse contrasto, **vale la licenza del
componente**.

**Le parti scritte per ZETA RAYS sono software libero**, distribuito con la
**GNU General Public License versione 3 o successive** (GPL-3.0-or-later):
ZETA e ZETA Core, il Monitor, le Impostazioni, la scrivania, la barra, il
launcher, la ricerca, gli script di sistema, i temi e le configurazioni. Puoi
usarle per qualsiasi scopo, studiarle, modificarle e ridistribuirle, anche
modificate, a condizione che chi le riceve abbia gli stessi diritti: il
codice resta aperto. Ogni file porta l'indicazione
`SPDX-License-Identifier: GPL-3.0-or-later`; il testo integrale della licenza
è in `/usr/share/common-licenses/GPL-3`. Il codice è già tutto nel sistema,
in forma leggibile: in `/usr/lib/zeta` e `/usr/local/bin`.

**Il marchio è un'altra cosa.** Il nome «ZETA RAYS», il simbolo e il logotipo
non sono coperti dalle licenze del software: restano del titolare del
progetto. Puoi usare, modificare e ridistribuire il sistema; se lo modifichi e
lo ridistribuisci, **toglici il marchio** e dagli un altro nome. È la stessa
regola che Debian e Firefox applicano ai propri, ed è espressamente prevista
dalle licenze libere (GPL-3 §7e, Apache-2.0 §6).

## Nessuna garanzia

Questo è il punto che conta di più, ed è quello standard del software libero.

**Il sistema è fornito "così com'è", senza garanzia di alcun tipo**, esplicita
o implicita, comprese — a titolo di esempio — le garanzie di commerciabilità,
di idoneità a uno scopo particolare e di assenza di violazioni.

**Il rischio dell'uso è tuo.** Chi ha realizzato o distribuito ZETA RAYS OS non
risponde di danni diretti, indiretti, incidentali o consequenziali — fra cui
perdita di dati, perdita di profitti, interruzione dell'attività — derivanti
dall'uso o dall'impossibilità di usare il sistema, anche se informato della
possibilità di tali danni.

Questa clausola non esclude le responsabilità che la legge applicabile non
consente di escludere.

## Installazione: attenzione ai dati

L'installatore **scrive sul disco e può cancellare quello che c'è**. Prima di
installare, fai una copia di sicurezza dei tuoi dati e assicurati di aver
capito quale disco stai per usare. Una partizione riscritta non si recupera.

## Credenziali predefinite

Le immagini pronte all'uso hanno l'utente `zeta` con password `zeta`, e nelle
macchine virtuali l'accesso è automatico. **Sono credenziali pubbliche, scritte
in questo documento: vanno bene per provare, non per un computer vero.** Se
installi il sistema per usarlo davvero, cambia la password e disattiva
l'accesso automatico.

## Sicurezza

Il sistema include un firewall attivo, strumenti di verifica e aggiornamenti
dagli archivi Debian. Nessuno di questi rende un computer inviolabile. Tieni
il sistema aggiornato: è la cosa che conta di più.

## Uso degli strumenti di rete e sicurezza

ZETA RAYS include strumenti che analizzano reti e sistemi. Usali **solo su
sistemi tuoi o per cui hai un'autorizzazione esplicita**. Usarli contro
sistemi altrui senza permesso è illegale in Italia e nella maggior parte dei
paesi, e la responsabilità è interamente di chi lo fa.

## Assistente e modelli linguistici

ZETA può sbagliare: i modelli linguistici inventano, anche quando
sembrano sicuri. **Non fidarti di una risposta per decisioni che contano**
senza verificarla — a maggior ragione per questioni mediche, legali o
finanziarie.

Il modello locale Llama 3.2 è distribuito da Meta con la *Llama 3.2 Community
License*, che ha condizioni proprie: il testo, la policy d'uso e l'avviso di
attribuzione sono in `llama-3.2/`, accanto a questo file. Built with Llama.

Se colleghi un provider cloud, valgono anche le condizioni di quel provider.

## Marchi di terzi

Debian è un marchio di SPI Inc. Firefox è un marchio di Mozilla Foundation.
Llama è un marchio di Meta Platforms. GNOME, Linux e gli altri nomi citati
appartengono ai rispettivi titolari. ZETA RAYS OS **non è prodotto, sostenuto
né approvato** da nessuno di loro.

## Legge applicabile

Si applica la legge italiana. Le licenze dei singoli componenti restano
regolate dai propri termini.

---

*ZETA RAYS OS 1.7*
