# Security policy

ZETA RAYS OS ships a firewall that is closed by default, SSH that never lets
root in, and an AI that never gets unrestricted root access. If you find a
weakness, please tell us privately first.

## How to report

- Use **GitHub › Security › Report a vulnerability** on this repository
  (private advisory), or
- write to **info@zetarays.org** with "SECURITY" in the subject.

Please include: the image you used (`zetarays-1.7-amd64.iso`, …), what you did,
what happened, and if possible the output of `sudo zeta-diagnosi`. Do not open
a public issue for security problems.

We will confirm receipt, fix confirmed issues in a new image, and credit you in
the release notes if you wish.

## Supported versions

| Version | Supported |
|---|---|
| 1.7 | ✓ |
| older | ✗ (please update) |

Security updates of the underlying Debian packages are installed with the
normal system updates (`sudo apt update && sudo apt upgrade`).
