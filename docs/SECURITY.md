# ZETA RAYS Security

Il centro di sicurezza di ZETA RAYS OS (`zeta-sicurezza`) e la sua raccolta di
strumenti. ZETA RAYS è orientato alla sicurezza informatica **per uso autorizzato**:
penetration testing autorizzato, difesa, ricerca, CTF, forense, amministrazione.

## Stato del sistema

Il centro mostra lo stato reale, senza mai dichiarare il sistema "sicuro" a
priori. Ogni voce è classificata onestamente:

| Stato | Significato |
|---|---|
| ATTIVO | la protezione è attiva |
| CONFIGURATO | presente e configurato |
| NON CONFIGURATO | disponibile ma non attivo |
| ATTENZIONE | richiede intervento |

Voci controllate: firewall, cifratura del disco, avvio sicuro, aggiornamenti,
isolamento applicazioni (AppArmor), registro di controllo (auditd), rete.

## Strumenti per categoria

| Categoria | Strumenti |
|---|---|
| Ricognizione | nmap, whois, bind9-dnsutils, masscan |
| Rete | wireshark, tcpdump, tshark, nftables |
| Web | sqlmap, ffuf, gobuster |
| Forense | Sleuth Kit, foremost, binwalk, ExifTool |
| Crittografia | OpenSSL, GnuPG, John the Ripper, hashcat |
| Difesa | Lynis, AIDE, rkhunter, chkrootkit, ClamAV, auditd, firejail |

Tutti gli strumenti provengono dai repository ufficiali e sono legittimi e
mantenuti. Non viene installato ogni pacchetto di sicurezza esistente: la
selezione è curata.

## Uso etico

- L'analisi malware avviene in ambiente isolato (firejail); il sistema non
  esegue malware sconosciuto direttamente sull'host.
- Le operazioni intrusive richiedono autorizzazione e conferma esplicita.
- L'assistente non compie attacchi autonomi né aggira controlli di sicurezza.
