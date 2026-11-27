# ZETA RAYS Security

The security center of ZETA RAYS OS (the Security app, `zeta-security`) and
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

## ZETA WATCH (3.5)

Real-time monitoring by a system service, `/usr/libexec/zeta-watch`
(`zeta-watch.service`: 120 MB and 15% of a CPU at most, read-only except its
log, its baseline and the firewall set of blocked addresses).

| Source | What it reports |
|---|---|
| journal | SSH logins (failed, accepted, root), wrong passwords at login, lock screen, su, sudo and administrator prompts, root sessions, refused sudo, new or removed users, administrator rights given, passwords changed, SSH connections refused by the firewall |
| auditd (`/etc/audit/rules.d/50-zeta-watch.rules`) | writes to passwd/shadow/group, sudoers, polkit rules, PAM, sshd configuration, root's SSH keys, systemd units in /etc, cron, rc.local, profile.d, `/etc/ld.so.preload`, kernel modules loaded by hand; not the writes of apt/dpkg and of the account tools |
| every minute | new listening ports, firewall rules changed, services newly enabled, programs running from /tmp, /var/tmp, /dev/shm or from deleted files, outgoing connections to unusual ports |
| weekly (`zeta-watch-scan.timer`) | rkhunter warnings, and what the daily chkrootkit found that its reference run did not |
| optional | Suricata alerts of severity 1-2 (`/var/log/suricata/eve.json`), installed from Settings |

The same event within ten minutes becomes one entry with a count
(`/var/log/zeta-watch/events.jsonl`, group `sudo`). An address that fails
the SSH password 5 times in 10 minutes goes into the nftables sets
`watch_block4/6` for an hour; never 127.0.0.1, never an address with an SSH
session open, never the local network unless "Also on the local network"
is on. `zeta-watch-notify` shows the alerts to every administrator logged
in (and reads them aloud if chosen). Settings › ZETA WATCH turns each part
on or off (system settings in `/etc/zeta/watch.json`, changed through
pkexec), shows the blocked addresses and the history, and sends a test
alert. Commands: `zeta-watch status`, `sudo zeta-watch unblock ADDRESS|all`,
`sudo zeta-watch scan`, `sudo zeta-watch test`.

Limits, said plainly: it reports what the system records and what changes.
It is not an antivirus, cannot see inside encrypted traffic, and can miss an
attack that leaves no trace in these sources; rkhunter, chkrootkit and
Suricata also report harmless things. The rules are tested with real log
lines in `tools/tests/test_watch_rules.py`.

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
