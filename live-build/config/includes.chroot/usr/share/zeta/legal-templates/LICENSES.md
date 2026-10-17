# ZETA RAYS OS — third-party software and licenses

*Generated automatically from the ZETA RAYS OS {version} image on {today}.*

{it_pointer}

ZETA RAYS OS is made up overwhelmingly of **free and open source software**
written by others. This document lists what is inside, under which licenses,
and where to find their full text.

## In short

The image contains **{n} installed packages**. For each one, the full license
text and the list of authors are on the system itself, in
`/usr/share/doc/<package-name>/copyright`.

The complete list, package by package with version and license, is in the
file `COMPONENTS.csv` next to this document.

## License families present

A package can appear in more than one family: many projects use different
licenses for different parts of their code.

{families}

The texts of the most common licenses are in `/usr/share/common-licenses/`.

## Main components

These are the programs that shape ZETA RAYS. Each one remains the property of
its authors and keeps its own license.

{main_components}

## System base

ZETA RAYS OS is built on the **Debian GNU/Linux 13 (trixie)** distribution and
uses its package archives (`deb.debian.org`, sections `main`, `contrib`,
`non-free`, `non-free-firmware` and `trixie-backports`).

Debian is a trademark of SPI Inc. ZETA RAYS OS is not produced, endorsed or
approved by Debian or by SPI Inc.: it is an independent system that uses its
technical base, as the free software licenses allow.

## Components written for ZETA RAYS

The desktop and the system applications (the `zeta-*` commands), the themes,
the icons, the brand and the interface texts and their translations belong to
ZETA RAYS.

**The ZETA RAYS trademark, name, symbol and logotype are not free
software**: they remain the property of the project owner. Free software
licenses cover the code, not trademarks (GPL-3 §7e, Apache-2.0 §6).

## Included language model

The image includes **Qwen3 4B Instruct (2507)** by the Qwen team (Alibaba
Cloud), released under the *Apache License 2.0*. The license text travels
with the model and is copied to `qwen3/LICENSE.txt` next to this document.

ZETA's Italian voice, **Sara**, comes from **Kokoro-82M** by hexgrad, also
under the *Apache License 2.0*: license and attribution in `kokoro/`.

## Non-free firmware

The image includes the `firmware-*` packages from Debian's `non-free-firmware`
section, needed for network cards, graphics cards and wireless adapters to
work on real hardware. They are distributed by their manufacturers under
redistribution-only licenses, whose text is in the corresponding `copyright`
files.

## How to get the source code

For every included package, the corresponding source code can be obtained
from the Debian archives with:

    apt-get source <package-name>

This meets the obligation to make the source available under the GPL and
similar licenses.
