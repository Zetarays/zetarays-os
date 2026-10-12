# SPDX-License-Identifier: GPL-3.0-or-later
# ZETA RAYS — regular users also find the commands in /usr/sbin and /sbin.
#
# Debian leaves them out of non-root users' PATH: "ifconfig", "route", "arp",
# "iw", "ethtool" answered "command not found" even though they were
# installed. Many of them work without privileges (showing interfaces, routes,
# Wi-Fi status); for the rest, sudo is enough. As Kali and Ubuntu do, the
# folders are appended at the end, without removing anything.
for d in /usr/local/sbin /usr/sbin /sbin; do
    case ":$PATH:" in
        *":$d:"*) ;;
        *) PATH="$PATH:$d" ;;
    esac
done
export PATH
