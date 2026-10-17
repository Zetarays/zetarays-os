# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — local command recognition (no AI model).

Turns natural-language sentences (Italian and English) into actions of the
`actions.py` engine, without contacting any service. It is fast, works
offline and is deterministic: well suited to system commands ("open
documents", "how much RAM am I using", "close this window").

If no rule matches, `parse()` returns None and ZETA can hand the question
over to the language model (if configured).
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus as _url_quote
import unicodedata
from dataclasses import dataclass

from i18n import tr, language
from i18n_data import load
from ui import accent as _accent

# The patterns that hold Italian words (what the user says or types) are
# language data: they live in i18n-data/intents.json, keyed by the action they
# recognize (or by the name of the table they define). Pure English patterns
# stay here in the code.
_W = load("intents")


@dataclass
class Intent:
    action: str | None    # None: a question with a known answer, nothing to run
    args: dict
    reply: str            # what ZETA RAYS says while acting (or the answer)


def _norm(text: str) -> str:
    text = text.lower().strip()
    text = "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")   # strips accents
    text = text.replace("’", "'")                   # typographic apostrophe
    return re.sub(r"\s+", " ", text)


# folders recognized in the text -> name for the open_folder action
_FOLDERS = _W["folders"]

# recognized apps -> name for open_application
_APPS = _W["apps"]

# settings pages
_SETTINGS = _W["settings"]


def _find(mapping: dict, text: str):
    for pattern, value in mapping.items():
        if re.search(pattern, text):
            return value
    return None


# verbs meaning "open/show/go to"
_OPEN = _W["open"]


# "How do I open…", "where do I find…" (in both languages): questions about
# how to do something, not commands.
# The small model answered at random (it sent people to Settings to open the
# terminal, mentioned browsers that are not installed). Here the answer is a
# fact about the system, always correct, and it teaches the command that
# gets ZETA to do it.
# Icons are described by shape, not by position: the dock can be reordered.
# The suggested commands are all routed by this very file.
# The color shades are the ones the system offers in Settings › Appearance:
# whoever says "set red" expects that red, not just any red.
_COLORS = dict(_W["colors"])
# the system's own colors come from its palette (ui/accent.py):
# "set red" gives exactly the red of Settings › Appearance
for _it, _en, _key in _W["accent_colors"]:
    _COLORS[_it] = _COLORS[_en] = _accent.color_of(_key)

_QUESTION = _W["question"]   # also the truncated Italian "where" before an apostrophe
_KNOWLEDGE = [
    (_W["knowledge.1"],
     tr("Deleted files go to the Trash. To get one back: double-click the Trash icon on the desktop, "
        "then right-click the file and choose Restore. It goes back where it was.")),
    (_W["knowledge.2"],
     tr("Right-click the Trash icon on the desktop, then Empty Trash. "
        "Or tell me “empty the trash”: I'll ask you to confirm and empty it for you.")),
    (_W["knowledge.3"],
     tr("The Trash is on the desktop, at the top left: double-click to open it. "
        "Or tell me “open the trash”.")),
    (_W["knowledge.4"],
     tr("Settings › Appearance › Wallpaper: click one of the ZETA RAYS wallpapers, or Choose… "
        "for your own image. Or tell me “set the red waves wallpaper”.")),
    (_W["knowledge.5"],
     tr("Settings › Appearance › Accent Color: blue, red, white, green, or + to pick your own. "
        "It changes the whole interface at once. Or tell me “open appearance settings”.")),
    (_W["knowledge.6"],
     tr("Settings › Appearance › Theme: Dark or Light. Or tell me “open appearance settings”.")),
    (_W["knowledge.7"],
     tr("The bar is at the bottom: on the left the ZETA RAYS symbol (the app list) and the "
        "workspaces 1 2 3, in the middle the dock with your apps, on the right search, network, "
        "volume, clock and power. Position and apps can be changed in Settings › Dock.")),
    (_W["knowledge.8"],
     tr("The terminal is in the dock at the bottom: the icon with the >_ symbol. "
        "Or tell me “open the terminal” and I'll open it.")),
    (_W["knowledge.9"],
     tr("The browser is Firefox: in the dock at the bottom, the globe icon. "
        "Or tell me “open the browser” and I'll open it.")),
    (_W["knowledge.10"],
     tr("The file manager is in the dock at the bottom: the folder icon. You can also open it by "
        "double-clicking Home on the desktop. Or tell me “open the file manager”.")),
    (_W["knowledge.11"],
     tr("Settings is in the dock at the bottom: the icon with the sliders. Or right-click the "
        "desktop › Customize, or tell me “open settings”.")),
    (_W["knowledge.12"],
     tr("The text editor is in the dock at the bottom: the pencil icon. Or tell me “open the editor”.")),
    (_W["knowledge.13"],
     tr("The Calculator is in the app list: click the ZETA RAYS symbol at the bottom left, "
        "then Calculator. Or tell me “open the calculator”.")),
    (_W["knowledge.14"],
     tr("The system monitor is in the dock at the bottom: the speedometer icon. "
        "Or tell me “open the monitor”.")),
    (_W["knowledge.15"],
     tr("Settings › Printers: network printers are found automatically, USB printers as soon "
        "as you plug them in.")),
    (_W["knowledge.16"],
     tr("Double-click the file, in the file manager or on the desktop: it opens with the right app. "
        "PDFs and documents in the viewer, photos and images in the image viewer, video and music in "
        "the player, zip, rar and 7z in the archive manager. Or tell me “open the file” followed by "
        "its name and I'll find it and open it.")),
    (_W["knowledge.17"],
     tr("The Documents folder is inside Home: double-click Home on the desktop, then Documents. "
        "Or tell me “open documents”.")),
    (_W["knowledge.18"],
     tr("Downloaded files are in the Downloads folder, inside Home. Or tell me “open downloads”.")),
    (_W["knowledge.19"],
     tr("The Pictures folder is inside Home. Or tell me “open pictures”.")),
    (_W["knowledge.20"],
     tr("The Music folder is inside Home. Or tell me “open music”.")),
    (r"\bvideos?\b",
     tr("The Videos folder is inside Home. Or tell me “open videos”.")),
    (_W["knowledge.21"],
     tr("Home is your personal folder: you'll find it on the desktop, at the top left. Inside are "
        "Documents, Pictures, Music, Downloads and Videos. Or tell me “open home”.")),
]


def _knowledge_intent(t: str) -> Intent | None:
    if not re.search(_QUESTION, t):
        return None
    for schema, answer in _KNOWLEDGE:
        if re.search(schema, t):
            return Intent(None, {}, answer)
    return None


_EXTENSIONS = (r"pdf|png|jpe?g|gif|webp|heic|svg|txt|md|docx?|odt|rtf|xlsx?|ods|csv|pptx?|odp|"
               r"mp3|wav|flac|ogg|m4a|mp4|mov|avi|mkv|webm|zip|rar|7z|tar|gz|iso")


# "the photos", "the videos"...: a file type, i.e. several extensions together
_FILE_TYPES = [
    (_W["file_types.1"],
     "*.jpg,*.jpeg,*.png,*.heic,*.webp,*.gif", tr("Searching for photos.")),
    (_W["file_types.2"],
     "*.mp4,*.mov,*.mkv,*.avi,*.webm", tr("Searching for videos.")),
    (_W["file_types.3"],
     "*.mp3,*.flac,*.wav,*.ogg,*.m4a", tr("Searching for music.")),
    (_W["file_types.4"],
     "*.pdf,*.doc,*.docx,*.odt,*.txt,*.rtf,*.md", tr("Searching for documents.")),
]


def _search_intent(t: str) -> Intent | None:
    m = re.search(_W["search_intent.1"], t)
    if not m:
        m = re.search(r"^(?:search(?: for)?|find(?: me)?|look for|locate"
                      r"|where (?:is|are|did i (?:put|save))|where'?s)\s+"
                      r"(?:all )?(?:the |my |a |an |some )?"
                      r"(?:files? (?:called |named )?)?(.+?)\s*\??$", t)
    if not m:
        return None
    rest = m.group(1)
    # "search the internet for…" and the Italian "try to…" (same verb as
    # "search") are not file searches
    if re.search(_W["search_intent.2"], t) or \
            re.match(_W["search_intent.3"], t) or \
            re.match(r"(search|find) (out|a way)\b", t):
        return None
    args = {}
    if re.search(_W["search_intent.4"], rest):
        args["today"] = True
    g = re.search(_W["search_intent.5"], rest)
    if g:
        args["days"] = int(g.group(1) or g.group(2))
    elif re.search(_W["search_intent.6"], rest):
        args["days"] = 7
    rest = re.sub(_W["search_intent.7"], " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" .?!")
    rest = re.sub(_W["search_intent.8"], "", rest)   # "the photos from [this week]"
    rest = re.sub(_W["search_intent.9"],
                   "", rest)   # "the document invoice"
    if not rest:
        return None
    for schema, extensions, answer in _FILE_TYPES:
        if re.fullmatch(schema, rest):
            args["pattern"] = extensions
            return Intent("find_files", args, answer)
    if re.fullmatch(_EXTENSIONS, rest):
        args["pattern"] = "*." + rest
        spoken = tr("Searching for {ext} files.").format(ext=rest.upper())
    else:
        args["pattern"] = "*%s*" % rest
        spoken = tr("Searching for “{name}”.").format(name=rest)
    return Intent("find_files", args, spoken)


def _folder_name(key: str) -> str:
    names = {"documents": tr("Documents"), "downloads": tr("Downloads"), "pictures": tr("Pictures"),
             "music": tr("Music"), "videos": tr("Videos"), "desktop": tr("Desktop"),
             "home": tr("Home")}
    return names.get(key, key)


def parse(text: str) -> Intent | None:
    t = _norm(text)
    if not t:
        return None

    # --- "how's the network": real status, not an explanation ---
    # Must come before _knowledge_intent(), otherwise "do I have internet?" ends up in the
    # answer about the browser and "how's the network" reaches the model, which
    # cannot inspect the interfaces. Sentences asking for the panel or how to
    # browse are excluded: those are not questions about the status.
    if not re.search(_W["network_status.1"], t) and \
       re.search(_W["network_status.2"], t):
        return Intent("network_status", {}, tr("Checking the network."))

    question = _knowledge_intent(t)
    if question:
        return question

    # --- deleting a file by name ------------------------------------------
    # "delete the folder X" was already understood, "erase the file X" was
    # not: two ways of saying the same thing cannot behave differently.
    # The noun ("file", "photo"...) is consumed only when it is a word on its
    # own: otherwise "trash photo.jpg" lost "photo".
    m = re.search(_W["trash_file.1"], t)
    english = False
    if not m and not re.search(_QUESTION, t):
        # in English "trash" is also a noun ("open the trash"): it counts as a
        # verb only at the start of the sentence
        english = True
        m = re.search(r"(?:^(?:please )?trash|\b(?:delete|erase))\s+"
                      r"(?:the |my |this |that )?"
                      r"(?:(?:file|document|folder|photo|picture|image)\s+)?"
                      r"[\"«“]?([^\"»”]{2,60}?)[\"»”]?[.!]?$", t)
    if m and not re.search(_W["trash_file.2"], m.group(1)) \
            and not (english and re.search(r"\b(everything|all|trash|bin|system|disk|program|history)\b",
                                           m.group(1))):
        name = m.group(1).strip()
        return Intent("trash_file", {"name": name},
                      tr("Moving “{name}” to the Trash.").format(name=name))

    # --- open windows ------------------------------------------------------
    if re.search(_W["list_windows.1"], t):
        return Intent("list_windows", {}, tr("Here are the open windows."))

    # --- accent color in words -------------------------------------------
    # The action wants an #RRGGBB: nobody says that out loud. Here the colors
    # people actually name become the shades used by the system.
    colors = "|".join(sorted(_COLORS, key=len, reverse=True))
    m = re.search(_W["set_accent.1"] % colors, t)
    if not m:
        m = re.search(_W["set_accent.2"] % colors, t)
    if not m:
        m = re.search(r"\b(%s)\s+accent\b" % colors, t)
    if m:
        name = m.group(1)
        return Intent("set_accent", {"color": _COLORS[name]},
                      tr("Setting the accent color to {color}.").format(color=name))

    # --- turning off the screen (not the computer) ------------------------
    if re.search(_W["screen_off"], t):
        return Intent("screen_off", {}, tr("Turning off the screen."))

    # --- brightness -------------------------------------------------------
    m = re.search(_W["set_brightness.1"], t)
    if not m:
        m = re.search(r"\b(?:set|put|make|turn)\b[^.?!]{0,20}brightness\s*(?:to|at)?\s*(\d{1,3})", t)
    if m:
        return Intent("set_brightness", {"level": max(0, min(100, int(m.group(1))))},
                      tr("Setting the brightness."))
    if re.search(_W["set_brightness.2"], t):
        return Intent("set_brightness", {"level": 100}, tr("Turning up the brightness."))
    if re.search(_W["set_brightness.3"], t):
        return Intent("set_brightness", {"level": 30}, tr("Turning down the brightness."))

    # --- web search ------------------------------------------------------
    # These sentences used to be excluded from the file search and ended up
    # at the model: that meant waiting for the model to load just to open a
    # page. Now the page simply opens. The default engine is DuckDuckGo, which
    # does not track searchers; if the user names an engine, that one is used.
    _ENGINES = r"(google|internet|web|duckduckgo|youtube|wikipedia)"
    what = engine = None
    m = re.search(_W["open_url.1"] + _ENGINES + r"\b[.?!]?$", t) or \
        re.search(r"\b(?:search(?: for)?|look up|look for|find)\b\s+(.{2,80}?)"
                  r"\s+(?:on|in)\s+(?:the\s+)?" + _ENGINES + r"\b[.?!]?$", t)
    if m:
        what, engine = m.group(1), m.group(2)
    else:
        m2 = re.search(_W["open_url.2"]
                       + _ENGINES + r"\b\s+(.{2,80})$", t) or \
            re.search(r"\b(?:search|look up)\b\s+(?:on\s+)?(?:the\s+)?" + _ENGINES
                      + r"\b\s+(?:for\s+)?(.{2,80})$", t)
        if m2:
            engine, what = m2.group(1), m2.group(2)
    if what:
        what = what.strip(" .?!")
        q = _url_quote(what)
        engines = {
            "google": "https://www.google.com/search?q=%s",
            "youtube": "https://www.youtube.com/results?search_query=%s",
            # Wikipedia in the system language
            "wikipedia": "https://" + language() + ".wikipedia.org/w/index.php?search=%s",
        }
        url = engines.get(engine, "https://duckduckgo.com/?q=%s") % q
        return Intent("open_url", {"url": url},
                      tr("Searching the web for “{query}”.").format(query=what))

    # --- closing the window ---
    if re.search(_W["close_active_window"], t):
        return Intent("close_active_window", {}, tr("Closing the active window."))

    # --- closing a program by name: "close firefox" ---
    # Must come after the active window, otherwise "close the window" would
    # be read as "close the program called the window".
    # "turn off" is left out on purpose: "turn off the wifi" and "turn off
    # the screen" do not close a program, yet with that verb in here they
    # ended up here.
    m = re.search(_W["close_application.1"], t) or \
        re.search(r"\b(close|quit|exit)\s+(?:the )?(?:program |app |application )?([a-z0-9 .+-]{2,30})$", t)
    if m and not re.search(_W["close_application.2"], m.group(2)):
        name = m.group(2).strip()
        return Intent("close_application", {"app": name}, tr("Closing {name}.").format(name=name))

    # --- screenshot ---
    if re.search(_W["screenshot"], t):
        return Intent("screenshot", {}, tr("Saving a screenshot."))

    # --- searching INSIDE files, not in their names ---
    # Filler words ("in the files", "the word") must be consumed by the pattern
    # one by one: counting them as characters, "search inside the files for
    # the word invoice" (in Italian) searched for the last letters of "word"
    # followed by "invoice".
    m = re.search(_W["search_content.1"], t)
    if not m:
        m = re.search(_W["search_content.2"], t)
    if not m:
        m = re.search(r"(?:search|find|look)\b[^.?!]{0,20}?\b(?:inside|within|in the contents? of|in the text of)\b"
                      r"(?:\s+(?:the|my|all))?"
                      r"(?:\s+(?:files|documents|document|pdfs?))?"
                      r"(?:\s+for)?"
                      r"(?:\s+the\s+(?:word|phrase|text|term))?"
                      r"\s+[\"«“]?([^\"»”]{2,60})[\"»”]?$", t)
    if not m:
        m = re.search(r"(?:which|what) (?:files?|documents?)[^.?!]{0,20}"
                      r"(?:talks? about|contains?|mentions?|says?)\s+(.{2,60})$", t)
    if m:
        query = m.group(1).strip(" .")
        return Intent("search_content", {"text": query},
                      tr("Searching inside files for “{text}”.").format(text=query))

    # --- renaming ---
    m = re.search(_W["rename_file"], t) or \
        re.search(r"\brename\s+[\"«“]?([^\"»”]{1,60}?)[\"»”]?\s+(?:to|as|into)\s+[\"«“]?([^\"»”]{1,60})[\"»”]?$", t)
    if m:
        old, new = m.group(1).strip(), m.group(2).strip(" .")
        return Intent("rename_file", {"name": old, "new_name": new},
                      tr("Renaming “{old}” to “{new}”.").format(old=old, new=new))

    # --- moving ---
    m = re.search(_W["move_file.1"], t) or \
        re.search(r"\bmove\s+[\"«“]?([^\"»”]{1,60}?)[\"»”]?\s+(?:to|into|in)\s+(?:the\s+)?"
                  r"[\"«“]?([^\"»”]{1,40})[\"»”]?$", t)
    if m and not re.search(_W["move_file.2"], m.group(2)) \
            and not re.search(r"\b(window|workspace)\b", m.group(1)):
        item, folder = m.group(1).strip(), m.group(2).strip(" .")
        return Intent("move_file", {"name": item, "folder": folder},
                      tr("Moving “{name}” to {folder}.").format(name=item, folder=folder))

    # --- window management ---
    if re.search(_W["minimize_window"], t):
        return Intent("minimize_window", {}, tr("Minimizing the active window."))
    if re.search(_W["maximize_window"], t):
        return Intent("maximize_window", {}, tr("Maximizing the active window."))
    # "how many windows do I have open", "tell me the windows", "what windows are there":
    # people do not use the verb we expected, and the sentence ended up at the
    # model, which answers that it cannot know which windows are open.
    if re.search(_W["list_windows.2"], t):
        return Intent("list_windows", {}, tr("Here are the windows."))

    # --- opening a website ---
    if re.search(_W["open_url.3"], t):
        m = re.search(r"(https?://\S+|www\.\S+|\b[a-z0-9-]+\.(?:it|com|org|net|eu|io|dev)\b\S*)", t)
        if m:
            return Intent("open_url", {"url": m.group(1)}, tr("Opening the website."))

    # --- opening a file by name ---
    if re.search(_W["open_file.1"], t):
        m = re.search(_W["open_file.2"], t)
        if m and m.group(1).strip() and m.group(1).strip() not in ("folder", "folders"):
            return Intent("open_file", {"name": m.group(1).strip()},
                          tr("Finding and opening the file."))

    # --- desktop wallpaper ---
    if re.search(_W["set_wallpaper.1"], t):
        if re.search(_W["set_wallpaper.2"], t):
            return Intent("set_wallpaper", {"name": "default"},
                          tr("Restoring the ZETA RAYS wallpaper."))
        # one of the ZETA RAYS wallpapers by name ("set the red waves wallpaper")
        m = re.search(_W["set_wallpaper.3"], t)
        if m:
            from system import wallpapers
            if wallpapers.search(m.group(1)):
                return Intent("set_wallpaper", {"name": m.group(1).strip()}, tr("Changing the wallpaper."))
        m = re.search(_W["set_wallpaper.4"], t)
        if m and m.group(1).strip():
            return Intent("set_wallpaper", {"name": m.group(1).strip()}, tr("Changing the wallpaper."))
        return Intent("open_settings", {"page": "appearance"},
                      tr("Opening Settings so you can pick a wallpaper."))

    # --- light / dark theme ---
    if re.search(_W["set_theme.1"], t):
        return Intent("set_theme", {"theme": "light"}, tr("Switching to the light theme."))
    if re.search(_W["set_theme.2"], t):
        return Intent("set_theme", {"theme": "dark"}, tr("Switching to the dark theme."))

    # --- trivial questions: instant answers, no need to bother the model ---
    if re.search(_W["current_time"], t):
        return Intent("current_time", {}, tr("It's…"))
    if re.search(_W["current_date"], t):
        return Intent("current_date", {}, tr("Today is…"))
    if re.search(_W["battery_status"], t):
        return Intent("battery_status", {}, tr("Checking the battery."))
    if re.search(_W["volume_status"], t):
        return Intent("volume_status", {}, tr("Checking the volume."))
    if re.search(_W["system_info.1"], t):
        return Intent("system_info", {}, tr("Here's the system information."))

    # --- system status ---
    if re.search(_W["cpu_usage"], t):
        return Intent("cpu_usage", {}, tr("Checking CPU usage."))
    if re.search(_W["memory_usage"], t):
        return Intent("memory_usage", {}, tr("Checking memory."))
    if re.search(_W["disk_usage"], t):
        return Intent("disk_usage", {}, tr("Checking disk space."))
    # "ip" without word boundaries matched inside "zip" and inside Italian
    # words: asking how to open a zip file got the IP address as answer.
    if re.search(_W["ip_address"], t):
        return Intent("ip_address", {}, tr("Here are your IP addresses."))
    if re.search(_W["uptime"], t):
        return Intent("uptime", {}, tr("How long the system has been on."))
    if re.search(_W["system_info.2"], t):
        return Intent("system_info", {}, tr("Here's the system information."))
    if re.search(_W["open_system_monitor.1"], t):
        return Intent("open_system_monitor", {"section": "processes"}, tr("Opening processes in the Monitor."))

    # --- system monitor / security ---
    if re.search(_OPEN + _W["open_system_monitor.2"], t):
        return Intent("open_system_monitor", {}, tr("Opening the System Monitor."))
    if re.search(_OPEN + _W["open_security"], t):
        return Intent("open_security", {}, tr("Opening ZETA RAYS Security."))

    # --- terminal ---
    if re.search(_OPEN + _W["open_terminal.1"], t) or t in _W["open_terminal.2"]:
        return Intent("open_terminal", {}, tr("Opening the terminal."))

    # --- settings (with an optional page) ---
    if re.search(_OPEN + _W["open_settings.1"], t):
        page = _find(_SETTINGS, t)
        if page:
            from .actions import page_name
            return Intent("open_settings", {"page": page},
                          tr("Opening Settings › {page}.").format(page=page_name(page)))
        return Intent("open_settings", {}, tr("Opening Settings."))
    if re.search(_W["open_settings.2"], t):
        page = _find(_SETTINGS, t)
        return Intent("open_settings", {"page": page} if page else {}, tr("Opening Settings."))

    # --- Wi-Fi (before power: "turn off the wifi" must not shut everything down) ---
    if re.search(_W["wifi_toggle.1"], t):
        return Intent("wifi_toggle", {"on": True}, tr("Turning Wi-Fi on."))
    if re.search(_W["wifi_toggle.2"], t):
        return Intent("wifi_toggle", {"on": False}, tr("Turning Wi-Fi off."))

    # --- power ---
    # "turn off" on its own, or referring to the computer. NOT "turn off the
    # screen", "turn off the wifi", "turn off the bluetooth": the Italian verb
    # anywhere used to be enough, so asking to turn off the screen offered to
    # shut down the computer. The confirmation prevented disaster, but the
    # question was wrong.
    if re.search(_W["power_off"], t):
        return Intent("power_off", {}, tr("Shutting down the computer."))
    if re.search(_W["reboot"], t):
        return Intent("reboot", {}, tr("Restarting the computer."))
    if re.search(_W["suspend"], t):
        return Intent("suspend", {}, tr("Suspending the computer."))
    if re.search(_W["lock_screen"], t):
        return Intent("lock_screen", {}, tr("Locking the screen."))
    if re.search(_W["log_out"], t):
        return Intent("log_out", {}, tr("Logging out."))

    # --- volume ---
    m = re.search(r"(?:volume|audio|sound)[^.?!]{0,12}?\b(\d{1,3})\s*%?", t)
    if m and re.search(_W["set_volume.1"], t):
        return Intent("set_volume", {"level": int(m.group(1))}, tr("Setting the volume."))
    # relative to the current volume: before, "raise" always went to
    # 80% (lowering it from 95) and "lower" always to 30%
    if re.search(_W["set_volume.2"], t):
        return Intent("set_volume", {"step": "up", "amount": 10}, tr("Turning up the volume."))
    if re.search(_W["set_volume.3"], t):
        return Intent("set_volume", {"step": "down", "amount": 10}, tr("Turning down the volume."))
    if re.search(_W["set_volume.4"], t):
        return Intent("set_volume", {"mute": True}, tr("Muting the audio."))

    # --- brightness ---
    m = re.search(_W["set_brightness.4"], t)
    if m:
        return Intent("set_brightness", {"level": int(m.group(1) or m.group(2))},
                      tr("Adjusting the brightness."))

    # --- programs ---
    m = re.search(_W["install_package"], t) or \
        re.search(r"^(?:please |can you |could you )?install\s+(?:the )?(?:program |app |package )?"
                  r"([a-z0-9.+-]{2,40})[.!?]?$", t)
    if m:
        name = m.group(1).strip()
        return Intent("install_package", {"name": name}, tr("Installing {name}.").format(name=name))
    m = re.search(_W["remove_package.1"], t) or \
        re.search(_W["remove_package.2"], t)
    if m:
        name = m.group(1).strip()
        return Intent("remove_package", {"name": name}, tr("Removing {name}.").format(name=name))

    # --- new folder ---
    m = re.search(_W["create_folder"], t) or \
        re.search(r"(?:create|make|new)[^.?!]{0,12}folder\s+(?:called\s+|named\s+)?([\w .-]{1,40})", t)
    if m and m.group(1).strip():
        return Intent("create_folder", {"name": m.group(1).strip()}, tr("Creating the folder."))

    # --- moving to the Trash ---
    m = re.search(_W["trash_file.3"], t) or \
        re.search(r"\bmove\s+(?:the |my )?(?:file\s+)?([\w .-]{1,40}?)\s+to (?:the )?(?:trash|bin|recycle bin)$", t)
    if m and m.group(1).strip() not in _W["trash_file.4"]:
        return Intent("trash_file", {"name": m.group(1).strip()}, tr("Moving it to the Trash."))
    if re.search(_W["empty_trash"], t):
        return Intent("empty_trash", {}, tr("Emptying the Trash."))

    # --- finding files: "search invoice", "find today's pdf files",
    #     "where is the file test.txt" ---
    file_search = _search_intent(t)
    if file_search:
        return file_search

    # --- folders ---
    folder = _find(_FOLDERS, t)
    if folder and re.search(_OPEN + _W["open_folder"], t):
        if folder == "trash":
            return Intent("open_folder", {"name": folder}, tr("Opening the Trash."))
        return Intent("open_folder", {"name": folder},
                      tr("Opening the {name} folder.").format(name=_folder_name(folder)))

    # --- specific apps ---
    app = _find(_APPS, t)
    if app and re.search(_OPEN, t):
        return Intent("open_application", {"app": app}, tr("Opening {name}.").format(name=app))

    # --- generic "open <something>": passes the name to open_application ---
    m = re.search(_OPEN + _W["open_application.1"], t)
    if m:
        target = m.group(1).strip()
        # avoid catching sentences already handled above
        if target and target not in _W["open_application.2"]:
            return Intent("open_application", {"app": target},
                          tr("Trying to open {name}.").format(name=target))

    return None
