# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › AI › Voice: which voice reads ZETA's replies, how fast.

The choice is saved by intelligence.speech in ~/.config/zeta/speech.json and
applies from the next reply. "Listen" plays a sample sentence with the
current choice, so the user can decide by ear.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from i18n_data import load  # noqa: E402
from intelligence import speech  # noqa: E402

# language names in their own language
LANGUAGES = tuple(tuple(x) for x in load("voice_settings")["languages"])
SPEED_KEYS = ("slow", "normal", "fast")


def _listen_button(lang):
    b = Gtk.Button(icon_name="audio-volume-high-symbolic", valign=Gtk.Align.CENTER,
                   tooltip_text=tr("Listen"), css_classes=["flat"])

    def play(_b):
        if speech.speaking():
            speech.stop()
            return
        speech.say(speech.sample_sentence(lang), lang=lang)
    b.connect("clicked", play)
    return b


def build_group(toast):
    """The "Voice" group; toast(text) shows a confirmation."""
    g = Adw.PreferencesGroup(
        title=tr("Voice"),
        description=tr("How ZETA reads its replies aloud. Everything stays on this computer."))
    for lang, name in LANGUAGES:
        voices = speech.installed_voices(lang)
        if not voices:
            continue
        current = speech.chosen_voice(lang)
        if len(voices) == 1:
            # nothing to choose, but the voice can still be heard
            row = Adw.ActionRow(title=tr("Voice ({language})").format(language=name))
            row.add_suffix(Gtk.Label(label=speech.voice_label(voices[0]), css_classes=["dim-label"]))
            row.add_suffix(_listen_button(lang))
            g.add(row)
            continue
        row = Adw.ComboRow(title=tr("Voice ({language})").format(language=name),
                           model=Gtk.StringList.new([speech.voice_label(v) for v in voices]))
        row.set_selected(voices.index(current) if current in voices else 0)

        def choose(r, _p, lang=lang, voices=voices):
            i = r.get_selected()
            if 0 <= i < len(voices):
                try:
                    speech.set_voice(lang, voices[i])
                except OSError as e:
                    toast(tr("Choice not saved: {error}").format(error=e))
                    return
                speech.stop()
                toast(tr("Voice saved"))
        row.connect("notify::selected", choose)
        row.add_suffix(_listen_button(lang))
        g.add(row)

    labels = [tr("Slow"), tr("Normal"), tr("Fast")]
    speed_row = Adw.ComboRow(title=tr("Speaking Speed"), model=Gtk.StringList.new(labels))
    speed_row.set_selected(SPEED_KEYS.index(speech.speed()))

    def set_speed(r, _p):
        i = r.get_selected()
        if 0 <= i < len(SPEED_KEYS):
            try:
                speech.set_speed(SPEED_KEYS[i])
            except (OSError, ValueError) as e:
                toast(tr("Choice not saved: {error}").format(error=e))
                return
            toast(tr("Speed saved"))
    speed_row.connect("notify::selected", set_speed)
    g.add(speed_row)
    return g
