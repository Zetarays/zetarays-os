// ZETA RAYS — Firefox opens the ZETA RAYS start page from the very first launch
// (zetarays.org online, its local copy offline). Without these, the first launch
// showed Firefox's own welcome page and a privacy-notice tab that, offline,
// ended on a network error page. Default values: the user can still change them.
pref("browser.aboutwelcome.enabled", false);
pref("datareporting.policy.firstRunURL", "");
