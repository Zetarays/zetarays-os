# ZETA RAYS Security

The security center of ZETA RAYS OS (the Security app, `zeta-sicurezza`) and
its collection of tools. ZETA RAYS is built for information security work
**with authorization**: authorized penetration testing, defense, research,
CTF, forensics, administration.

## System status

The center shows the real state of the system and never declares it "secure"
by default. Each item is classified honestly:

| State | Meaning |
|---|---|
| ACTIVE | the protection is active |
| CONFIGURED | present and configured |
| NOT CONFIGURED | available but not active |
| ATTENTION | needs action |

Items checked: firewall, disk encryption, Secure Boot, updates, application
confinement (AppArmor), audit log (auditd), network.
Debian's AppArmor profiles are installed and loaded at boot (the
`apparmor` package), as on a standard Debian system.

## Tools

Preinstalled in the image:

| Category | Tools |
|---|---|
| Reconnaissance | nmap, masscan, whois, dig (bind9-dnsutils) |
| Network | tcpdump, tshark |
| Web | sqlmap, ffuf, gobuster |
| Forensics | Sleuth Kit, foremost, binwalk, ExifTool |
| Cryptography and passwords | OpenSSL, GnuPG, John the Ripper, hashcat |
| Defense | nftables, Lynis, AIDE, rkhunter, chkrootkit, ClamAV, auditd, firejail |

The Security app lists its catalog by category (reconnaissance, network
analysis, web security, passwords and authentication, wireless, sniffing and
spoofing, forensics, reverse engineering, defense). Every tool can really be
started: graphical tools open in their own window, command-line tools open in
the terminal with their help in view. Tools that are not installed (Wireshark,
Nikto, Hydra, Aircrack-ng, bettercap and others) are installed with one click,
with authentication, but only if APT really knows them; otherwise the app
explains why they are missing.

All tools come from the official Debian repositories and are legitimate and
maintained. Not every security package in existence is installed: the
selection is curated.

## Ethical use

- Nothing is ever run against a target unless the user asks: ZETA RAYS opens
  the tool, and its use is the responsibility of whoever launches it.
- firejail is included to run untrusted programs in a sandbox instead of
  directly on the host.
- ZETA, the assistant, has no action that attacks other systems, never
  bypasses security controls, and asks for consent before anything
  destructive.
