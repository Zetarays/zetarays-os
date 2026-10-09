# ZETA RAYS OS — terms of use

*(Versione italiana: `CONDIZIONI.it.md`, in this same folder.)*

## What it is

ZETA RAYS OS is an operating system built on Debian GNU/Linux and made up
largely of third-party free software, plus a desktop, system applications,
a theme and texts written for ZETA RAYS.

The complete list of components and their licenses is in `LICENZE.md`, next
to this file. What leaves the computer is described in `PRIVACY.md`.

## Licenses

Every third-party component remains the property of its authors and is used
under **its own** license: GPL, LGPL, MIT, BSD, Apache and the others listed
in `LICENZE.md`. Nothing in this document restricts the rights those
licenses give you — and in case of conflict, **the component's license
prevails**.

**The parts written for ZETA RAYS are free software**, distributed under the
**GNU General Public License version 3 or later** (GPL-3.0-or-later): ZETA and
ZETA Core, the Monitor, Settings, the desktop, the bar, the launcher, search,
the system scripts, the themes and the configuration. You may use them for
any purpose, study them, modify them and redistribute them, modified or not,
provided that whoever receives them gets the same rights: the code stays
open. Every file carries the notice `SPDX-License-Identifier: GPL-3.0-or-later`;
the full text of the license is in `/usr/share/common-licenses/GPL-3`. All the
code is already on the system, in readable form: in `/usr/lib/zeta` and
`/usr/local/bin`.

**The trademark is a different matter.** The name «ZETA RAYS», the symbol and
the logotype are not covered by the software licenses: they remain the
property of the project owner. You may use, modify and redistribute the
system; if you modify and redistribute it, **remove the trademark** and give
it another name. It is the same rule Debian and Firefox apply to their own
marks, and the free licenses expressly allow it (GPL-3 §7e, Apache-2.0 §6).

## No warranty

This is the most important point, and it is the standard one for free
software.

**The system is provided "as is", without warranty of any kind**, express or
implied, including — by way of example — the warranties of merchantability,
fitness for a particular purpose and non-infringement.

**You use it at your own risk.** Those who created or distributed ZETA RAYS OS
are not liable for any direct, indirect, incidental or consequential
damages — including loss of data, loss of profits or business
interruption — arising from the use of, or the inability to use, the system,
even if advised of the possibility of such damages.

This clause does not exclude any liability that the applicable law does not
allow to be excluded.

## Installation: mind your data

The installer **writes to the disk and can erase what is on it**. Before
installing, back up your data and make sure you understand which disk you
are about to use. An overwritten partition cannot be recovered.

## Default credentials

The ready-to-use images have the user `zeta` with password `zeta`, and in
virtual machines sign-in is automatic. **These are public credentials,
written in this document: they are fine for trying the system, not for a
real computer.** If you install the system to actually use it, change the
password and turn off automatic sign-in.

## Security

The system includes an active firewall, auditing tools and updates from the
Debian archives. None of these makes a computer invulnerable. Keep the system
up to date: that is what matters most.

## Use of the network and security tools

ZETA RAYS includes tools that analyze networks and systems. Use them **only on
systems you own or are explicitly authorized to test**. Using them against
other people's systems without permission is illegal in Italy and in most
countries, and the responsibility lies entirely with whoever does it.

## Assistant and language models

ZETA can be wrong: language models make things up, even when they sound
confident. **Do not rely on an answer for decisions that matter** without
checking it — all the more so for medical, legal or financial matters.

The local Llama 3.2 model is distributed by Meta under the *Llama 3.2
Community License*, which has its own conditions: the license text, the
acceptable use policy and the attribution notice are in `llama-3.2/`, next to
this file. Built with Llama.

If you connect a cloud provider, that provider's terms also apply.

## Third-party trademarks

Debian is a trademark of SPI Inc. Firefox is a trademark of the Mozilla
Foundation. Llama is a trademark of Meta Platforms. GNOME, Linux and the other
names mentioned belong to their respective owners. ZETA RAYS OS **is not
produced, endorsed or approved** by any of them.

## Governing law

Italian law applies. The licenses of the individual components remain
governed by their own terms.

---

*ZETA RAYS OS 2.0*
