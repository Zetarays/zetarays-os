# ZETA RAYS OS — software di terze parti e licenze

*Generato automaticamente dall'immagine di ZETA RAYS OS {version} il {today}.*

ZETA RAYS OS è composto in larghissima parte da **software libero e open
source** scritto da altri. Questo documento elenca che cosa c'è dentro, con
quali licenze, e dove trovarne il testo completo.

## In breve

L'immagine contiene **{n} pacchetti** installati. Per ognuno, il testo
integrale della licenza e l'elenco degli autori sono nel sistema stesso, in
`/usr/share/doc/<nome-del-pacchetto>/copyright`.

L'elenco completo, pacchetto per pacchetto con versione e licenza, è nel file
`COMPONENTS.csv` accanto a questo documento.

## Famiglie di licenza presenti

Un pacchetto può comparire in più famiglie: molti progetti usano licenze
diverse per parti diverse del codice.

{families}

I testi delle licenze più diffuse sono in `/usr/share/common-licenses/`.

## Componenti principali

Questi sono i programmi che danno forma a ZETA RAYS. Ognuno resta dei suoi
autori e mantiene la propria licenza.

{main_components}

## Base del sistema

ZETA RAYS OS è costruito sulla distribuzione **Debian GNU/Linux 13 (trixie)**
e ne usa gli archivi dei pacchetti (`deb.debian.org`, sezioni `main`,
`contrib`, `non-free`, `non-free-firmware` e `trixie-backports`).

Debian è un marchio di SPI Inc. ZETA RAYS OS non è prodotto, sostenuto né
approvato da Debian o da SPI Inc.: è un sistema indipendente che ne usa la
base tecnica, come le licenze del software libero consentono.

## Componenti scritti per ZETA RAYS

Sono di ZETA RAYS la scrivania e le applicazioni di sistema (i comandi
`zeta-*`), i temi, le icone, il marchio e i testi dell'interfaccia con le
loro traduzioni.

**Il marchio ZETA RAYS, il nome, il simbolo e il logotipo non sono software
libero**: restano di proprietà del titolare del progetto. Le licenze del
software libero riguardano il codice, non i marchi (GPL-3 §7e, Apache-2.0 §6).

## Modello linguistico incluso

L'immagine include **Qwen3 4B Instruct (2507)** del team Qwen (Alibaba
Cloud), distribuito con la *Apache License 2.0*. Il testo della licenza
viaggia con il modello ed è copiato in `qwen3/LICENSE.txt` accanto a questo
documento.

La voce italiana di ZETA, **Sara**, viene da **Kokoro-82M** di hexgrad, anche
questo con la *Apache License 2.0*: licenza e attribuzione in `kokoro/`.

## Firmware non libero

L'immagine include i pacchetti `firmware-*` della sezione `non-free-firmware`
di Debian, necessari perché schede di rete, schede video e adattatori senza
fili funzionino su hardware reale. Sono distribuiti dai rispettivi produttori
con licenze di sola redistribuzione, il cui testo è nei relativi file
`copyright`.

## Come ottenere il codice sorgente

Per ogni pacchetto incluso, il codice sorgente corrispondente si ottiene dagli
archivi Debian con:

    apt-get source <nome-del-pacchetto>

Questo soddisfa l'obbligo di messa a disposizione del sorgente previsto dalla
GPL e dalle licenze analoghe.
