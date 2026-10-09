// ZETA RAYS — Firefox opens the ZETA RAYS start page from the very first launch
// (zetarays.org online, its local copy offline). Without these, the first launch
// showed Firefox's own welcome page and a privacy-notice tab that, offline,
// ended on a network error page. Default values: the user can still change them.
pref("browser.aboutwelcome.enabled", false);
pref("datareporting.policy.firstRunURL", "");

// Privacy and speed: no telemetry, studies, Pocket or sponsored content, and
// the open tabs saved every minute instead of every 15 seconds (fewer disk
// writes; nothing lost on a normal close).
pref("datareporting.healthreport.uploadEnabled", false);
pref("datareporting.policy.dataSubmissionEnabled", false);
pref("toolkit.telemetry.enabled", false);
pref("toolkit.telemetry.unified", false);
pref("toolkit.telemetry.archive.enabled", false);
pref("app.shield.optoutstudies.enabled", false);
pref("app.normandy.enabled", false);
pref("extensions.pocket.enabled", false);
pref("browser.newtabpage.activity-stream.feeds.telemetry", false);
pref("browser.newtabpage.activity-stream.telemetry", false);
pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);
pref("browser.newtabpage.activity-stream.showSponsored", false);
pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);
pref("browser.sessionstore.interval", 60000);
