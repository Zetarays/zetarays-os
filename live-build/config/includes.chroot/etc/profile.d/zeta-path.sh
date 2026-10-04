# SPDX-License-Identifier: GPL-3.0-or-later
# ZETA RAYS — anche l'utente normale trova i comandi in /usr/sbin e /sbin.
#
# Debian li lascia fuori dal PATH di chi non e' root: «ifconfig», «route»,
# «arp», «iw», «ethtool» rispondevano «comando non trovato» pur essendo
# installati. Molti funzionano anche senza privilegi (mostrare interfacce,
# rotte, stato del Wi-Fi); per gli altri basta sudo. Come fanno Kali e
# Ubuntu, le cartelle si aggiungono in fondo, senza togliere nulla.
for d in /usr/local/sbin /usr/sbin /sbin; do
    case ":$PATH:" in
        *":$d:"*) ;;
        *) PATH="$PATH:$d" ;;
    esac
done
export PATH
