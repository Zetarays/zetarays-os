# ZETA RAYS OS: Debranding

The places where the identity of the base distribution is replaced with
ZETA RAYS OS. The work is done by the hook `0100-zeta-branding.hook.chroot`
(inside the system) and by `9000-zeta-disk.hook.binary` (on the boot media).

## Rewritten

| Place | Before | After |
|---|---|---|
| `/etc/os-release`, `/usr/lib/os-release` | Debian GNU/Linux 13 | ZETA RAYS OS 2.0 (ID=zeta) |
| `/etc/issue`, `/etc/issue.net` | Debian GNU/Linux | ZETA RAYS OS 2.0 |
| `/etc/motd` | Debian text | ZETA RAYS OS 2.0 · AI · Security · Control |
| Shell prompt | generic prompt | `user@zetarays` (the default computer name) in the ZETA RAYS colors |
| `/usr/share/pixmaps/debian-logo.png` | Debian logo | ZETA RAYS symbol |
| GRUB `GRUB_DISTRIBUTOR` | Debian | ZETA RAYS OS |
| Boot menu (GRUB/syslinux) | Debian artwork | ZETA RAYS logo, English entries |
| Boot theme (Plymouth) | Debian theme | animated ZETA RAYS logo |
| Login screen (SDDM) | generic theme | ZETA RAYS theme, with the version from `os-release` |
| Installer (Calamares) | generic branding | ZETA RAYS branding and logo |
| `.disk/info` on the media | Debian GNU/Linux ... | ZETA RAYS OS 2.0 ... |
| Settings > About | "Debian" line | ZETA RAYS information only |

`/usr/lib/os-release` is diverted with `dpkg-divert`, so system updates do not
put the original back.

## Internal references left in place (not visible to the user)

Some package names and file types contain "debian" for technical reasons (for
example the `application/x-debian-package` type used to install packages).
They do NOT appear in the interface and must not be removed: removing them
would break dependencies.
