Catalogo italiano completo di Calamares 3.3.14 per ZETA RAYS.
Upstream lascia ~85 frasi non tradotte (compaiono in inglese) e alcune tradotte male.
Calamares carica /usr/share/calamares/lang/calamares_it_IT.qm prima di quello interno.

Rigenerare: python3 build_full.py (serve it.ts di upstream, tag v3.3.14),
poi lrelease calamares_it_IT.ts -qm calamares_it_IT.qm (pacchetto qt6-l10n-tools)
e copiare il .qm in live-build/config/includes.chroot/usr/share/calamares/lang/.
