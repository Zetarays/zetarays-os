# SPDX-License-Identifier: GPL-3.0-or-later
"""Understand the request locally: sentence -> [(capability, arguments)].

Fast (milliseconds), offline, deterministic. It recognizes the verb, then the
object; names (apps, folders, files) are checked against the real system in
the capabilities. Compound sentences («open firefox and close the terminal»)
become several actions in sequence. If it does not understand, it returns
None: the model is then asked to choose among the same capabilities.
"""
from __future__ import annotations

import os
import re
import shutil

from i18n_data import load

from . import state as S

# Both Italian and English are understood, whatever the system language. The
# patterns that hold Italian words (what the user says or types) are language
# data: they live in i18n-data/understanding.json, keyed by the capability they
# recognize (or by the name of the constant they define). Pure English
# patterns stay here in the code.
_W = load("understanding")

# polite words at the beginning and at the end: they are stripped
_PREAMBLE = re.compile(_W["preamble"])
# (the final word must be a word on its own: «open snow» does not lose «now»)
_TRAILING = re.compile(_W["trailing"])

# verbs (after norm: lowercase, no accents)
V_OPEN = _W["v_open"]
V_CLOSE = _W["v_close"]
V_RESTART = _W["v_restart"]
V_SWITCH = _W["v_switch"]
V_CREATE = _W["v_create"]
V_SEARCH = _W["v_search"]
V_DELETE = _W["v_delete"]
V_TURN_ON = _W["v_turn_on"]
V_TURN_OFF = _W["v_turn_off"]

_ART = _W["art"]
_COMPUTER = _W["computer"]

# places (well-known folders), in Italian and in English
_PLACES = _W["places"]
_PLACE_PREP = _W["place_prep"]


def _clean(text):
    t = S.norm(text)
    t = t.replace("’", "'")
    t = _PREAMBLE.sub("", t)
    t = _TRAILING.sub("", t)
    return t.strip()


def _number(t):
    m = re.search(_W["number"], t)
    return int(m.group(1)) if m else None


def _place(t):
    """«on the desktop», «in my documents folder», «in downloads» (and the
    Italian prepositions and folder names) -> name of the place."""
    m = re.search(r"\b" + _PLACE_PREP + _W["place"] + _PLACES + r")\b", t)
    return m.group(1) if m else None


def _strip_place(t):
    return re.sub(r"\s+" + _PLACE_PREP + _W["strip_place"] + _PLACES +
                  r")(?:\s+folder)?\b", "", t).strip()


# A name containing a connective («and then», «then», «and open…», or their
# Italian equivalents) is not a name: it is the rest of a compound sentence
# that was not understood. The request «create a folder trips and then open
# it», said in Italian, created a folder named «trips and then open it»
# (actually seen). Better not to understand at all.
_CONNECTIVE = re.compile(_W["connective"])


def _valid_name(n):
    return bool(n) and not _CONNECTIVE.search(n)


def _object_name(t):
    """strips «the file», «the folder», articles and quotes (in both languages)"""
    t = re.sub(_W["object_name"], "", t.strip())
    t = re.sub(r"^(?:the |a |an |my |this )?(?:(?:file|folder|document|image|photo|picture) )?"
               r"(?:(?:called|named) )?", "", t)
    return t.strip().strip("«»\"'“”")


def _system(t):
    """Power: only if the computer is named (or the verb stands alone)."""
    if re.fullmatch(_W["restart_system.1"] + _COMPUTER + r")?", t) or \
            re.fullmatch(_W["restart_system.2"] + _COMPUTER, t):
        return "restart_system", {}
    if re.fullmatch(_W["shutdown_system"] + _COMPUTER + r")?", t) or \
            re.fullmatch(r"(?:turn off|switch off|shut down|power down) " + _COMPUTER, t) or \
            re.fullmatch(r"(?:turn|switch|shut) " + _COMPUTER + r" (?:off|down)", t):
        return "shutdown_system", {}
    if re.fullmatch(_W["suspend_system"] + _COMPUTER + r")?", t) or \
            re.fullmatch(r"put " + _COMPUTER + r" to sleep|put " + _COMPUTER + r" in standby", t):
        return "suspend_system", {}
    if re.fullmatch(_W["lock_screen.1"] + _COMPUTER + _W["lock_screen.2"], t):
        return "lock_screen", {}
    if re.fullmatch(_W["logout"], t):
        return "logout", {}
    return None


def _network(t):
    wifi = _W["wifi"]
    if re.fullmatch(V_TURN_ON + " " + wifi, t) or re.fullmatch(r"(?:turn|switch) " + wifi + r" on", t):
        return "wifi_on", {}
    if re.fullmatch(V_TURN_OFF + " " + wifi, t) or re.fullmatch(r"(?:turn|switch) " + wifi + r" off", t):
        return "wifi_off", {}
    if re.fullmatch(_W["wifi_disconnect"], t) or \
            re.fullmatch(r"disconnect(?: me)?(?: from)?(?: the)? (?:wi[ -]?fi|(?:wi[ -]?fi )?network|internet)", t):
        return "wifi_disconnect", {}
    # Bluetooth devices: «connect the headphones» is not a network
    devices = _W["devices"]
    m = re.fullmatch(_W["wifi_connect"], t) or \
        re.fullmatch(r"(?:connect|join)(?: me)?(?: to)?(?: the)? (?:(?:wi[ -]?fi )?network |wi[ -]?fi )?"
                     r"(.+?)(?: (?:with|using)(?: the)? password (.+))?", t)
    if m and not re.match(devices, m.group(1)) and \
            not re.search(r"\b(?:headphones|earbuds|headset|mouse|keyboard|speakers?)$", m.group(1)):
        return "wifi_connect", {"network": m.group(1).strip("«»\"'“” "), "password": m.group(2)}
    if re.search(_W["wifi_list"], t) or \
            re.search(r"\b(?:available|nearby) (?:wi[ -]?fi )?networks\b|\b(?:which|what) (?:wi[ -]?fi )?networks\b|"
                      r"\b(?:networks|wi[ -]?fi networks?) (?:available|nearby|around)\b|"
                      r"\b(?:list|show)(?: me)?(?: the)? (?:wi[ -]?fi )?networks\b", t):
        return "wifi_list", {}
    if re.search(_W["network_status"], t) or \
            re.search(r"\b(?:network status|am i (?:connected|online)|is (?:the )?internet working|"
                      r"do i have internet|ip address|my ip\b|which network|what network|current network)", t):
        return "network_status", {}
    bt = _W["bt"]
    if re.fullmatch(V_TURN_ON + " " + bt, t) or re.fullmatch(r"(?:turn|switch) " + bt + r" on", t):
        return "bluetooth_on", {}
    if re.fullmatch(V_TURN_OFF + " " + bt, t) or re.fullmatch(r"(?:turn|switch) " + bt + r" off", t):
        return "bluetooth_off", {}
    if re.search(_W["bluetooth_devices"], t) or \
            re.search(r"bluetooth devices|bluetooth (?:connected|nearby|paired)|paired devices", t):
        return "bluetooth_devices", {}
    bt_types = _W["bt_types"]
    m = re.fullmatch(_W["bluetooth_connect.1"], t)
    if m and re.search(bt_types, t):
        return "bluetooth_connect", {"device": re.sub(_W["bluetooth_connect.2"], "", m.group(1))
                                     if len(m.group(1).split()) > 1 else m.group(1)}
    m = re.fullmatch(r"(?:connect|pair)(?: my| the)? (.+?)(?: (?:via|over|with|using) bluetooth)?", t)
    if m and re.search(bt_types, t):
        name = m.group(1)
        if len(name.split()) > 1:      # «sony headphones» -> «sony»
            name = re.sub(r"^(?:headphones|earbuds|headset|mouse|keyboard|speakers?) | "
                          r"(?:headphones|earbuds|headset|mouse|keyboard|speakers?)$", "", name)
        return "bluetooth_connect", {"device": name}
    m = re.fullmatch(_W["bluetooth_disconnect"], t) or \
        re.fullmatch(r"(?:disconnect|unpair)(?: my| the)? (.+?)(?: bluetooth)?", t)
    if m and re.search(bt_types, t):
        return "bluetooth_disconnect", {"device": m.group(1)}
    return None


def _adjustments(t):
    if re.search(_W["adjustments"], t):
        return None                    # «sound settings» is a page, not the volume
    n = _number(t)
    # «make the music a bit louder», «quieter», «make it louder»: the volume, in words
    if not re.search(_W["set_volume.1"], t):
        if re.search(_W["set_volume.2"], t) or \
                re.search(r"\b(?:louder|turn (?:it|the music|the sound|the audio) up|"
                          r"turn up the (?:music|sound|audio))\b", t):
            return "set_volume", {"change": 10}
        if re.search(_W["set_volume.3"], t) or \
                re.search(r"\b(?:quieter|softer|turn (?:it|the music|the sound|the audio) down|"
                          r"turn down the (?:music|sound|audio))\b", t):
            return "set_volume", {"change": -10}
    # questions about slowness: «is something slowing down the computer?»,
    # «why is it so slow?», «why is my computer so slow?»
    if (re.search(_W["list_processes.1"], t) or
            re.search(r"\bslow(?:ing|s)? (?:down|it down|me down)\b|\bslowing\b|"
                      r"\b(?:is|so|very|too|running|really|being|got) (?:so |very |too |really )?slow\b|"
                      r"\b(?:frozen|sluggish|laggy|lagging)\b", t)) and \
            not re.search(_W["list_processes.2"], t):
        return "list_processes", {"by": "cpu"}
    if re.search(_W["set_volume.4"], t):
        if re.search(_W["set_volume.5"], t) or t in _W["set_volume.6"]:
            return "set_volume", {"mute": True}
        if re.search(_W["set_volume.7"], t):
            return "set_volume", {"mute": False}
        if n is not None and re.search(_W["set_volume.8"], t):
            return "set_volume", {"level": n}          # «raise the volume to 60%»: 60, not +60
        if re.search(_W["set_volume.9"], t):
            return "set_volume", {"change": n if n is not None else 10}
        if re.search(_W["set_volume.10"], t):
            return "set_volume", {"change": -(n if n is not None else 10)}
        if n is not None:
            return "set_volume", {"level": n}
        return "set_volume", {}
    if t in _W["set_volume.11"]:
        return "set_volume", {"mute": True}
    if t in ("unmute",):
        return "set_volume", {"mute": False}
    if re.search(_W["set_brightness.1"], t):
        if n is not None and re.search(_W["set_brightness.2"], t):
            return "set_brightness", {"level": n}
        if re.search(_W["set_brightness.3"], t):
            return "set_brightness", {"change": n if n is not None else 10}
        if re.search(_W["set_brightness.4"], t):
            return "set_brightness", {"change": -(n if n is not None else 10)}
        return "set_brightness", ({"level": n} if n is not None else {})
    m = re.search(_W["set_theme"], t)
    if m:
        return "set_theme", {"theme": m.group(1) or m.group(2)}
    m = re.search(r"\b(light|dark) (?:theme|mode)\b|\b(?:theme|mode) (?:to )?(light|dark)\b", t)
    if m:
        return "set_theme", {"theme": m.group(1) or m.group(2)}
    m = re.fullmatch(_W["set_wallpaper.1"], t) or \
        re.fullmatch(r"(?:change|set|switch)(?: the| my)? (?:wallpaper|background|desktop background)"
                     r"(?: to| with)? (.+)", t) or \
        re.fullmatch(r"(?:use|set|make) (.+?) as (?:the |my )?(?:wallpaper|background|desktop background)", t) or \
        re.fullmatch(r"(?:use|set|put|choose|apply)(?: the| a)? (.+?) (?:wallpaper|background)", t) or \
        re.fullmatch(_W["set_wallpaper.2"], t)
    if m:
        return "set_wallpaper", {"image": _object_name(m.group(1))}
    if re.search(_W["screenshot"], t):
        return "screenshot", {}
    if re.search(_W["current_time"], t) or \
            re.search(r"\bwhat time is it\b|\bwhat(?:'s| is) the (?:time|date)\b|\bwhat day is (?:it|today)\b|"
                      r"\bwhat(?:'s| is) today(?:'s date)?\b|\bwhat date is it\b|\bthe time\b$", t):
        return "current_time", {}
    if re.search(_W["system_status.1"], t) or \
            re.search(r"\bhow much (?:ram|memory)\b|\b(?:ram|memory) usage\b|\bfree (?:ram|memory)\b", t):
        return "system_status", {"what": "ram"}
    if re.search(_W["system_status.2"], t) or \
            re.search(r"\b(?:free (?:disk )?space|disk space|how much space|disk (?:is )?full|disk usage|"
                      r"storage space)\b", t):
        return "system_status", {"what": "disk"}
    if re.search(_W["system_status.3"], t):
        return "system_status", {"what": "battery"}
    if re.search(_W["system_status.4"], t) and \
            not re.search(r"\bprocess", t):
        return "system_status", {"what": "cpu"}
    if re.search(_W["system_status.5"], t) or \
            re.search(r"\b(?:system|computer) status\b|\bhow is (?:the|my) (?:computer|system)(?: doing)?\b|"
                      r"\bstatus of the (?:system|computer)\b", t):
        return "system_status", {}
    if re.search(_W["list_processes.3"], t) or \
            re.search(r"\bwho(?:'s| is) (?:using|eating|hogging)\b|\bwhat(?:'s| is) (?:using|eating|hogging)\b|"
                      r"\bwhich (?:apps|programs) (?:are )?using\b", t):
        return "list_processes", {"by": "memory" if re.search(_W["list_processes.4"], t) else "cpu"}
    return None


_DEST = (_W["dest"])


_URL = r"((?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:[/?#]\S*)?)"


def _file(t):
    place = _place(t)
    # «open the website www.debian.org», «go to wikipedia.org», «open https://…»
    m = re.fullmatch(r"(?:" + V_OPEN + _W["open_url.1"] + _URL, t)
    if m:
        return "open_url", {"url": m.group(1)}
    # after a plain «open», «notes.txt» is a file: it is a website only if the user says so
    m = re.fullmatch(V_OPEN + r"\s+" + _URL, t)
    if m and re.match(r"(?:https?://|www\.)|.*\.(?:com|org|net|it|eu|io|dev|info|gov|edu|co|uk|de|fr|es|ch|"
                      r"app|ai|me|tv|news|blog|wiki)(?:[/?#]|$)", m.group(1)):
        return "open_url", {"url": m.group(1)}
    m = re.fullmatch(V_OPEN + _W["open_url.2"], t)
    if m:
        return "open_url", {"url": m.group(1)}
    # programs: where they are, which command starts them, which package
    m = re.fullmatch(_W["where_is_program.1"], t) or \
        re.fullmatch(r"(?:which|what) command (?:launches|starts|opens|runs)\s+(.+)", t) or \
        re.fullmatch(_W["where_is_program.2"], t) or \
        re.fullmatch(r"(?:which|what) package (?:provides|contains|installs|has|owns)\s+(.+)", t) or \
        re.fullmatch(_W["where_is_program.3"], t) or \
        re.fullmatch(r"(?:where is|where's|show me|show|what is|what's)\s+(?:the )?"
                     r"(?:executable|binary|program file|desktop file|\.desktop file|desktop entry|launcher|"
                     r"launch command)\s+(?:of|for)\s+(.+)", t) or \
        re.fullmatch(r"(?:where is|where's|where are)\s+(.+?)\s+installed", t) or \
        re.fullmatch(_W["where_is_program.4"], t) or \
        re.fullmatch(_W["where_is_program.5"], t)
    if m:
        return "where_is_program", {"app": _object_name(m.group(1))}
    if re.fullmatch(_W["list_appimages"], t) or \
            re.fullmatch(r"(?:find|show|list|search for)\s+(?:me )?(?:my |the |all |all my )?appimages?", t):
        return "list_appimages", {}
    # "where is firefox" / "where's nmap": a program, not a file
    m = re.fullmatch(_W["where_is_program.6"], t)
    if m and _is_program(m.group(1)):
        return "where_is_program", {"app": _object_name(m.group(1))}
    # «can you show me the photos I downloaded», «let me see the documents»,
    # «show me my photos», «let me see the downloads»
    m = re.match(_W["open_folder.1"], t)
    if m:
        rest = m.group(1)
        if re.search(_W["open_folder.2"], rest):
            return "open_folder", {"folder": "downloads"}
        for word, folder in _W["folder_words"]:
            if re.search(r"\b%s\b" % word, rest):
                return "open_folder", {"folder": folder}
    m = re.fullmatch(V_CREATE + _W["create_folder"], t)
    if m and _valid_name(_object_name(_strip_place(m.group(1)))):
        return "create_folder", {"name": _object_name(_strip_place(m.group(1))), "location": place or "home"}
    m = re.fullmatch(V_CREATE + _W["create_file"], t) or \
        re.fullmatch(V_CREATE + r" (?:a |the )?(?:new )?(?:text )?file(?: called| named)? (.+?)"
                     r"(?: (?:with the text|with text|containing|that says|saying) (.+))?", t)
    if m and _valid_name(_object_name(_strip_place(m.group(1)))):
        return "create_file", {"name": _object_name(_strip_place(m.group(1))), "location": place or "documents",
                               "text": m.group(2) or ""}
    m = re.fullmatch(_W["rename_item"], t) or \
        re.fullmatch(r"(?:rename|change the name of)\s+(.+?)\s+(?:to|as|into)\s+(.+)", t)
    if m and _valid_name(m.group(2)):
        return "rename_item", {"item": _object_name(_strip_place(m.group(1))),
                               "new_name": _object_name(m.group(2)), "location": place}
    m = re.fullmatch(_W["copy_item"] + _DEST + r"(.+)", t)
    if m and _valid_name(m.group(2)):
        return "copy_item", {"item": _object_name(m.group(1)), "destination": m.group(2)}
    m = re.fullmatch(_W["move_item.1"] + _DEST + r"(.+)", t)
    if m and not re.search(_W["move_item.2"], m.group(2)) and _valid_name(m.group(2)) and \
            not re.search(r"\bdock\b|full ?screen", m.group(2)):
        return "move_item", {"item": _object_name(m.group(1)), "destination": m.group(2)}
    m = re.fullmatch(V_DELETE + _W["delete_item.1"], t) or \
        re.fullmatch(_W["delete_item.2"], t) or \
        re.fullmatch(r"(?:move|put|throw|send)\s+(.+?)\s+(?:in|into|to)(?: the)? (?:trash|recycle bin)(?: can)?", t)
    if m:
        location = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        return "delete_item", {"item": _object_name(_strip_place(m.group(1))), "location": location or place}
    m = re.fullmatch(_W["show_location"], t) or \
        re.fullmatch(r"(?:where is|where's|wheres|show (?:me )?the location of|"
                     r"open the (?:containing )?folder (?:of|containing|that contains|for)|"
                     r"which folder (?:is|contains))\s+(.+?)(?:\s+in)?", t) or \
        re.fullmatch(r"(?:show me|tell me) where\s+(.+?)\s+(?:is|are)", t)
    if m:
        return "show_location", {"item": _object_name(m.group(1))}
    m = re.fullmatch(V_SEARCH + _W["search_files"], t)
    if m and m.group(1) not in ("", "file", "files"):
        return "search_files", {"text": _object_name(_strip_place(m.group(1))), "location": place}
    m = re.fullmatch(_W["download_file"], t)
    if m:
        return "download_file", {"url": m.group(1), "location": place or "downloads"}
    return None


def _apps_and_windows(t):
    if re.fullmatch(_W["close_all_windows"], t) or \
            re.fullmatch(r"close(?: all(?: the| my)? (?:windows|apps|applications|programs)| everything)", t):
        return "close_all_windows", {}
    if re.fullmatch(_W["close_window"], t) or \
            re.fullmatch(r"close(?: this| the| the current| the active)? window", t):
        return "close_window", {}
    m = re.fullmatch(_W["force_close_application"], t) or \
        re.fullmatch(r"(?:force[ -]quit|force[ -]close|kill)\s+(.+)", t)
    if m:
        return "force_close_application", {"app": m.group(1)}
    m = re.fullmatch(_W["minimize_window.1"], t) or \
        re.fullmatch(_W["minimize_window.2"], t)
    if m:
        return "minimize_window", {"app": m.group(1) or ""}
    m = re.fullmatch(_W["maximize_window"], t) or \
        re.fullmatch(r"(?:maximi[sz]e|enlarge)(?: the window(?: of)?)?(?: (.+))?", t)
    if m:
        return "maximize_window", {"app": m.group(1) or ""}
    m = re.fullmatch(_W["fullscreen_window"], t) or \
        re.fullmatch(r"(?:go |make it |toggle )?full ?screen(?: (?:for|on) (.+))?|"
                     r"(?:make|put|set|switch) (.+?) (?:to |in |into )?full ?screen", t)
    if m:
        return "fullscreen_window", {"app": m.group(1) or m.group(2) or ""}
    roles = (_W["roles"])
    roles_en = (r"(web browser|browser|email client|mail client|email|mail|file manager|files|terminal|"
                r"text editor|editor|video player|media player|music player|pdf viewer|pdf reader|pdf|"
                r"image viewer|photo viewer|images)")
    m = re.fullmatch(_W["set_default_app.1"] + roles +
                     _W["set_default_app.2"], t) or \
        re.fullmatch(r"(?:set|use|make|choose)\s+(.+?)\s+(?:as\s+)?(?:the |my )?(?:default |system )" + roles_en, t) or \
        re.fullmatch(r"(?:set|use|make|choose)\s+(.+?)\s+as\s+(?:the |my )?" + roles_en +
                     r"(?: by default)?", t)
    if m:
        return "set_default_app", {"app": m.group(1), "role": m.group(2)}
    m = re.fullmatch(_W["set_default_app.3"] + roles +
                     _W["set_default_app.4"], t) or \
        re.fullmatch(r"(?:set|change|switch)\s+(?:the |my )?default\s+" + roles_en + r"\s+(?:to|as)\s+(.+)", t)
    if m:
        return "set_default_app", {"role": m.group(1), "app": m.group(2)}
    if (re.search(_W["list_default_apps.1"], t) or
            re.search(r"\bdefault (?:apps|applications|programs)\b|"
                      r"\bwhat(?:'s| is) (?:the |my )?default (?:browser|terminal|file manager|email|mail)\b|"
                      r"\bwhich (?:browser|terminal|file manager) is (?:the )?default\b", t)) and \
            not re.search(_W["list_default_apps.2"], t):
        return "list_default_apps", {}
    m = re.fullmatch(V_SWITCH + r"\s+(.+)", t)
    if m and S.find_app(m.group(1)):
        return "focus_application", {"app": m.group(1)}
    if re.search(_W["list_running_applications"], t) or \
            re.search(r"\b(?:what|which) (?:apps|applications|programs|windows) (?:are |do i have |i have )?(?:open|running)\b|"
                      r"\b(?:apps|applications|programs|windows) (?:are )?(?:open|running)\b|"
                      r"\b(?:list|show)(?: me)?(?: the| all)? (?:open|running) (?:apps|applications|programs|windows)\b|"
                      r"^running (?:apps|applications|programs)$", t):
        return "list_running_applications", {}
    if re.search(_W["list_installed_applications"], t) or \
            re.search(r"\b(?:what|which) (?:apps|applications|programs) (?:are |do i have |i have )?installed\b|"
                      r"\b(?:list|show)(?: me)?(?: the| all)? installed (?:apps|applications|programs)\b|"
                      r"^installed (?:apps|applications|programs)$", t):
        return "list_installed_applications", {}
    m = re.fullmatch(_W["is_installed.1"], t)
    if m and re.search(_W["is_installed.2"], t):
        return "is_installed", {"app": m.group(1)}
    m = re.fullmatch(r"(?:is|do i have|have i got|have i) (.+?) installed\??", t)
    if m:
        return "is_installed", {"app": m.group(1)}
    m = re.fullmatch(_W["install_package"], t) or \
        re.fullmatch(r"install\s+(?:the )?(?:program |package |app )?(.+)", t)
    if m:
        return "install_package", {"package": m.group(1)}
    m = re.fullmatch(_W["remove_package"], t)
    if m:
        return "remove_package", {"package": m.group(1)}
    m = re.fullmatch(_W["dock_add"], t) or \
        re.fullmatch(r"(?:add|put|pin)\s+(.+?)\s+(?:to|on|in)(?: the)? dock", t)
    if m:
        return "dock_add", {"app": m.group(1)}
    m = re.fullmatch(_W["dock_remove"], t) or \
        re.fullmatch(r"(?:remove|take|unpin)\s+(.+?)\s+(?:from|off)(?: the)? dock", t)
    if m:
        return "dock_remove", {"app": m.group(1)}
    # settings (also «wifi settings», «open the sound settings»,
    # «open sound settings»)
    m = re.fullmatch(r"(?:" + V_OPEN + _W["open_settings"], t) or \
        re.fullmatch(r"(?:" + V_OPEN + r"\s+)?(?:the |my )?(?:system )?(?:settings|preferences)"
                     r"(?:\s+(?:for |of |on |about )?(?:the )?(.+))?", t) or \
        re.fullmatch(r"(?:" + V_OPEN + r"\s+)?(?:the |my )?(.+?)\s+(?:settings|preferences)", t)
    if m:
        return "open_settings", {"page": m.group(1) or ""}
    # restart an app (the computer is handled by _system, which runs first)
    m = re.fullmatch(V_RESTART + r"\s+(.+)", t)
    if m:
        return "restart_application", {"app": m.group(1)}
    m = re.fullmatch(V_CLOSE + r"\s+(.+)", t)
    if m:
        return "close_application", {"app": m.group(1)}
    m = re.fullmatch(V_OPEN + r"\s+(.+)", t)
    if m:
        obj = m.group(1).strip()
        if re.match(r"https?://|www\.", obj):
            return "open_url", {"url": obj}
        cleaned = re.sub(_W["open_folder.4"], "", obj)
        folder_en = re.match(r"(?:the |my )?(?:folder |directory )|(?:the |my )?.+ folder$", obj)
        if folder_en:               # «open the documents folder», «open the folder projects»
            cleaned = re.sub(r"^(?:the |my )?(?:folder |directory )?(?:called |named )?|\s+folder$", "", obj)
        elif re.match(r"(?:the |my )", obj):
            cleaned = re.sub(r"^(?:the |my )", "", obj)
        if S.norm(cleaned) in _W["open_folder.5"] or _place("in " + cleaned) == cleaned or \
                re.match(_W["open_folder.6"], obj) or folder_en:
            return "open_folder", {"folder": cleaned}
        if re.search(r"\.[a-z0-9]{2,5}$", obj) or re.match(_W["open_file"], obj) or \
                re.match(r"(?:the |my |a )?(?:file|document|image|photo|picture) ", obj):
            return "open_file", {"item": _object_name(_strip_place(obj)), "location": _place(t)}
        return "open_application", {"app": obj}
    return None


_RULES = (_system, _network, _adjustments, _file, _apps_and_windows)


def _two_versions(text):
    """(lowercase, original case) of the same length: positions found in the
    first one are also valid in the second."""
    import unicodedata
    lower, orig, spacing = [], [], False
    for ch in unicodedata.normalize("NFC", (text or "").replace("’", "'")):
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn") or ch
        if base.isspace():
            if spacing or not lower:
                continue
            spacing, base = True, " "
        else:
            spacing = False
        for b in base:
            lb = b.lower()
            if len(lb) != 1:
                lb = b
            lower.append(lb)
            orig.append(b)
    return "".join(lower).rstrip(), "".join(orig).rstrip()


def _one(lower, orig):
    i = 0
    m = _PREAMBLE.match(lower)
    if m:
        i = m.end()
    m = _TRAILING.search(lower, i)
    j = m.start() if m else len(lower)
    t, c = lower[i:j].strip(), orig[i:j].strip()
    for rule in _RULES:
        r = rule(t)
        if r:
            name, args = r
            # names (files, folders, networks, passwords, addresses) as the user wrote them
            for k, v in list(args.items()):
                if isinstance(v, str) and v:
                    pos = t.find(v)
                    if pos >= 0:
                        args[k] = c[pos:pos + len(v)]
            return name, args
    return None


_UNITS = _W["units"]
_TENS = _W["tens"]
# in English: «sixty», «sixty-five» (also «sixty five», joined beforehand)
_UNITS_EN = {"zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
             "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_DIGITS_EN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TENS_EN = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
              "eighty": 80, "ninety": 90}


def _value(word):
    """A number written in words -> its value: «sixty-five» -> 65, «hundred» ->
    100, and the same for the Italian number words; None if not a number."""
    p = word.lower()
    if p in _W["hundred_words"]:
        return 100
    if p in _UNITS_EN:
        return _UNITS_EN[p]
    if p in _TENS_EN:
        return _TENS_EN[p]
    d, _t, u = p.partition("-")
    if d in _TENS_EN and u in _DIGITS_EN:
        return _TENS_EN[d] + _DIGITS_EN[u]
    if p in _UNITS and p not in _W["one_words"]:          # «one» alone is an article, not a number
        return _UNITS[p]
    for name, v in _TENS.items():
        root = name[:-1]                       # the tens without their last vowel, joined to a unit
        if p == name:
            return v
        for r in (name, root):
            if p.startswith(r) and p[len(r):] in _UNITS and p[len(r):] not in _W["one_feminine"]:
                return v + _UNITS[p[len(r):]]
    return None


def _numbers_to_digits(text):
    """Voice input writes numbers as words: «at sixty percent» -> «at 60 percent».
    Only after a trigger word («to», «at», «volume»… and the Italian ones) or
    before «percent»: «open two windows» stays as it is."""
    # «sixty five» -> «sixty-five»: a single word
    text = re.sub(r"(?i)\b(%s)\s+(%s)\b" % ("|".join(_TENS_EN), "|".join(_DIGITS_EN)), r"\1-\2", text)
    text = re.sub(r"(?i)\b(?:a|one) hundred\b", "hundred", text)
    words = re.split(r"(\s+)", text)
    triggers = set(_W["triggers"])
    for k in range(0, len(words), 2):
        v = _value(words[k])
        if v is None:
            continue
        preceding = words[k - 2].lower() if k >= 2 else ""
        after = words[k + 2].lower() if k + 2 < len(words) else ""
        if preceding in triggers or after == _W["percent_word"] or after.startswith("percent"):
            words[k] = str(v)
    return "".join(words)


def _is_program(name):
    """An installed app or a command called so (and no file with that name
    in the usual folders is meant: files have extensions or several words)."""
    name = _object_name(name).strip()
    if not name or "." in name.rstrip(".") and not name.endswith((".app",)):
        return False
    return bool(S.find_app(name) or shutil.which(name) or shutil.which(name.lower()))


def understanding(text: str):
    """[(capability, arguments), ...] or None if the sentence is not a known command."""
    lower, orig = _two_versions(_numbers_to_digits(text or ""))
    if not lower:
        return None
    compound = _compound(lower, orig)
    if compound:
        return compound
    whole = _one(lower, orig)
    return [whole] if whole else None


def _compound(lower, orig):
    """«open firefox and then close the terminal» -> two actions (only if every
    piece is a recognized command)."""
    pieces_b = re.split(_W["compound"],
                       lower)
    if len(pieces_b) < 2:
        return None
    actions, pos = [], 0
    for p in pieces_b:
        k = lower.find(p, pos)
        pos = k + len(p)
        # the pronoun first: «open it» would be taken for an app called «it»
        r = _pronoun(p, actions) or _one(p, orig[k:k + len(p)])
        if not r:
            return None                  # a piece was not understood: try the whole sentence
        actions.append(r)
    return actions


def _pronoun(chunk, previous):
    """«...and then open it»: open exactly what was just created, copied or
    moved (with the exact path, not by searching for it by name)."""
    if not previous or not re.fullmatch(_W["pronoun"], chunk.strip()):
        return None
    name, args = previous[-1]
    from . import capabilities as C
    if name in ("create_folder", "create_file"):
        base = C.folder_of(args.get("location") or "home") or S.HOME
        path = os.path.join(base, args.get("name", ""))
    elif name in ("copy_item", "move_item"):
        base = C.folder_of(args.get("destination", ""))
        if not base:
            return None
        path = os.path.join(base, os.path.basename(args.get("item", "")))
    else:
        return None
    return ("open_folder", {"folder": path}) if name == "create_folder" else \
        ("open_file", {"item": path})
