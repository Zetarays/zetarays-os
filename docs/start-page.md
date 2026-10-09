# The Firefox start page in ZETA RAYS OS

## How it works

Firefox ESR opens a **local** file, installed with the system, as its start
page:

    file:///usr/share/zetarays/start/index.html

- **With internet**: the page checks that `https://zetarays.org/` really
  answers (a `HEAD` request with a 2.5-second timeout) and then switches to
  the online site by itself. Having a cable or Wi-Fi connected is not enough:
  the check is on the site's answer.
- **Without internet** (or if the site does not answer): it stays on the
  local copy of the site, with the same look and text but **with every link
  disabled** (they cannot be clicked), and a small note "Offline copy of
  zetarays.org · links are disabled" (in Italian when the page is shown in
  Italian). Firefox's error page never appears.

The local copy loads nothing from the internet: no Google Fonts (JetBrains
Mono and Roboto are installed in the system), and the Syne font (SIL OFL) and
the wallpaper thumbnails are copied next to the page. The online site uses
Clash Display, whose license does not allow redistribution, so it is never
included in the images.

## Where it comes from

The page is **never edited by hand**: at every image build,
`build.sh` generates it from `sito-zetarays/`, first with
`tools/sito-font-libero.py` (which swaps Clash Display for Syne) and then with
`tools/genera-pagina-firefox.py`. It is therefore always the same as the
published site:

    python3 tools/sito-font-libero.py sito-zetarays .cache/sito-font-libero
    python3 tools/genera-pagina-firefox.py .cache/sito-font-libero \
        live-build/config/includes.chroot/usr/share/zetarays/start

The script removes the Google Fonts links and the `canonical` link, removes
`href`/`target` from every link (including those in the English texts), adds
the "online -> zetarays.org" check, and stops with an error if any external
resource is left in the page.

## Firefox policy

`live-build/config/includes.chroot/usr/share/firefox-esr/distribution/policies.json`

In Debian, `/usr/lib/firefox-esr/distribution` is a link to
`/usr/share/firefox-esr/distribution`: the file lives in the real folder, so
the package's link stays intact and Firefox reads it from the usual path.

```json
{
  "policies": {
    "Homepage": {
      "URL": "file:///usr/share/zetarays/start/index.html",
      "StartPage": "homepage",
      "Locked": false
    },
    "OverrideFirstRunPage": "",
    "OverridePostUpdatePage": ""
  }
}
```

`Locked: false`: users can change the start page in Firefox's settings.
`OverrideFirstRunPage` and `OverridePostUpdatePage` are empty: on first start
and after an update, Firefox opens the ZETA RAYS page instead of its own
welcome pages. `/etc/firefox-esr/zeta-rays.js` (default values, which can be
changed) turns off the "about:welcome" page and the privacy-notice tab, which
ended on an error page without a network. Hyprland opens Firefox's main
window at 80% of the screen (rule `zeta-browser-misura`), so the whole page is
visible from the first start.

## Automatic checks

- the hook `0100-zeta-branding.hook.chroot` stops the build if `index.html`
  or `policies.json` is missing, or if the policy does not point to the page;
- the ISO inspection (`ispeziona-iso.sh`, a local script kept outside the
  repository in `.cache/ispeziona/`) checks the page, the fonts (and that no
  Clash Display file is present), the absence of external resources, the
  policy and the Debian link.

## Server side

Nothing special is needed: the check uses a `no-cors` request, so **no** CORS
headers are required. The site only has to be published.

**TODO**: as of 3 October 2026, `https://zetarays.org/` redirects to
`https://www.zetarays.org/`, which still shows Aruba's placeholder page. Until
the site files (`sito-zetarays/`) are uploaded, Firefox shows that page when
online.

## How to test it

1. **With a network**: start Firefox; the local page opens and, a moment
   later, `www.zetarays.org`.
2. **Without a network** (Wi-Fi off or cable unplugged): start Firefox; the
   local copy of the site appears with the "Offline copy" note, and links do
   not react to clicks.
3. **Policy active**: type `about:policies` in the address bar: "Homepage"
   must appear with the URL above.
4. **Manual change**: Firefox Settings > Home > choose another page: it is
   accepted (the policy is not locked).

Tested with a new profile (a real first start) and without a network: a
single tab, the copy of the site, a large window, no error page.
