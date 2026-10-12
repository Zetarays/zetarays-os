Complete Italian catalog of Calamares 3.3.14 for ZETA RAYS.
Upstream leaves ~85 sentences untranslated (they show up in English) and a few badly translated.
Calamares loads /usr/share/calamares/lang/calamares_it_IT.qm before its built-in one.

To regenerate: python3 build_full.py (needs upstream's it.ts, tag v3.3.14),
then lrelease calamares_it_IT.ts -qm calamares_it_IT.qm (package qt6-l10n-tools)
and copy the .qm into live-build/config/includes.chroot/usr/share/calamares/lang/.
