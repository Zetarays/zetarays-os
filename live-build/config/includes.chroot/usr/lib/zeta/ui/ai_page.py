# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › AI: the local model, memory, current information,
language, behavior, voice.

ZETA uses only models that run on this computer (Ollama): there is no online
AI service to choose and no key to enter. Anything that may take more than a
moment (Ollama, downloads, the memory store) runs in a thread: the window
never stops to wait.
"""
import os
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from intelligence import models, ollama_manager as og  # noqa: E402
from intelligence import resources, store, websearch  # noqa: E402
from intelligence.memory import Memory  # noqa: E402
from intelligence.registry import (DEFAULT_SYSTEM, LOCAL, Registry,  # noqa: E402
                                   load_settings, save_settings)


def _in_thread(job, done):
    """job() in a thread; done(result) back on the window's thread."""
    def run_worker():
        try:
            r = job()
        except Exception as e:  # noqa: BLE001 - no error may bring Settings down
            r = e
        GLib.idle_add(lambda: (done(r), False)[1])
    threading.Thread(target=run_worker, daemon=True).start()


def _gb(x):
    return ("%.1f GB" % x) if x >= 0.1 else ("%.0f MB" % (x * 1000))


def _size(n_bytes):
    """A file size: KB below a megabyte (a new memory store is ~70 KB)."""
    return "%.0f KB" % (n_bytes / 1e3) if n_bytes < 1e6 else _gb(n_bytes / 1e9)


class AIPage:
    def __init__(self, window):
        self.w = window
        self.reg = Registry()
        self.page = Adw.PreferencesPage()
        self._choice_group()
        self._ollama_group()
        self._memory_group()
        self._web_group()
        self._language_group()
        self._behavior_group()
        self._voice_group()

    def _voice_group(self):
        """Settings › AI › Voice (ui/voice_settings.py, owned by the voice)."""
        try:
            from ui import voice_settings
            self.page.add(voice_settings.build_group(self.toast))
        except Exception as e:  # noqa: BLE001 - the voice section must not bring the page down
            print("ai_page: voice section: %s" % e)

    def toast(self, t):
        self.w.toast(t)

    # --- options saved in intelligence.json ---------------------------------
    def _option(self, pid, key, default):
        return self.reg.settings.get("providers", {}).get(pid, {}).get(key, default)

    def _save_option(self, pid, key, value):
        self.reg.set_option(pid, key, value)

    # --- which intelligence -------------------------------------------------
    def _choice_group(self):
        g = Adw.PreferencesGroup(
            title=tr("Intelligence"),
            description=tr("ZETA answers only with models that run on this computer. Your questions, "
                           "memories and voice never go to an online AI service."))
        self.effective_row = Adw.ActionRow(title=tr("In use now"), subtitle="…")
        g.add(self.effective_row)
        m = models.machine()
        profile = (tr("low-power processor ({cpu})").format(cpu=m.cpu or "?") if m.profile == "low-power"
                   else tr("{gb} GB of RAM").format(gb="%.0f" % m.ram_gb))
        row = Adw.ActionRow(title=tr("Chosen for this computer"),
                            subtitle=tr("{profile}: {models}").format(
                                profile=profile, models=", ".join(models.preferred())))
        row.set_subtitle_lines(0)
        g.add(row)
        # the first choice for this computer, when it is not installed yet:
        # downloaded only if the user asks (size, disk and memory are checked)
        self.recommend_row = Adw.ActionRow(title=tr("Recommended for this computer"), visible=False)
        self.recommend_row.set_subtitle_lines(0)
        get = Gtk.Button(label=tr("Download"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        get.connect("clicked", lambda _b: self._download_recommended())
        self.recommend_row.add_suffix(get)
        g.add(self.recommend_row)
        self.page.add(g)
        self._update_effective()
        _in_thread(og.models, self._show_recommendation)

    def _show_recommendation(self, installed):
        if isinstance(installed, Exception):
            return
        best = models.preferred()[0]
        names = [m["name"] for m in installed]
        if not og.installed() or any(n == best or n.startswith(best + "-") for n in names):
            return
        self._recommended = best
        self.recommend_row.set_subtitle(tr("{model}: {why}").format(
            model=best, why=models.reason(models.machine().profile)))
        self.recommend_row.set_visible(True)

    def _download_recommended(self):
        name = getattr(self, "_recommended", "")
        if name:
            self.o_download.set_text(name)
            self._o_download(self.o_download)

    def _update_effective(self):
        def job():
            p = Registry().resolve_default()
            return tr("{name} · model {model}").format(name=p.config.label,
                                                       model=p._model() or tr("default"))
        _in_thread(job, lambda r: self.effective_row.set_subtitle(
            r if isinstance(r, str) else tr("can't be determined")))

    # --- Ollama -------------------------------------------------------------
    def _ollama_group(self):
        g = Adw.PreferencesGroup(title=tr("Local Model · Ollama"),
                                 description=tr("Free and private: your questions stay on this "
                                                "computer, and it works without internet."))
        self.o_ram = Adw.ActionRow(title=tr("Memory"), subtitle="…")
        g.add(self.o_ram)
        self._o_ram_refresh()
        self.o_state = Adw.ActionRow(title=tr("Status"), subtitle=tr("checking…"))
        self.o_start = Gtk.Button(valign=Gtk.Align.CENTER, sensitive=False)
        self._o_active = False
        self.o_start.connect("clicked", self._o_start_stop)
        self.o_free_memory = Gtk.Button(label=tr("Free Memory"), valign=Gtk.Align.CENTER,
                                   tooltip_text=tr("Unloads the model from memory: it stays installed "
                                                   "and reloads with the next question"))
        self.o_free_memory.connect("clicked", self._o_free_memory)
        self.o_state.add_suffix(self.o_free_memory)
        self.o_state.add_suffix(self.o_start)
        g.add(self.o_state)

        self.ollama_models = Adw.ExpanderRow(title=tr("Installed Models"), subtitle="…")
        g.add(self.ollama_models)
        self._model_rows = []

        self.o_download = Adw.EntryRow(title=tr("Download a model (e.g. {models})").format(
                                          models=", ".join(models.preferred())),
                                      show_apply_button=True)
        self.o_download.connect("apply", self._o_download)
        g.add(self.o_download)
        self.o_progress_row = Adw.ActionRow(title=tr("Download"), visible=False)
        self.o_prog = Gtk.ProgressBar(valign=Gtk.Align.CENTER, hexpand=True, show_text=True)
        self.o_stop_dl = Gtk.Button(label=tr("Cancel"), valign=Gtk.Align.CENTER)
        self.o_stop_dl.connect("clicked", lambda *_: setattr(self, "_dl_stopped", True))
        self.o_progress_row.add_suffix(self.o_prog)
        self.o_progress_row.add_suffix(self.o_stop_dl)
        g.add(self.o_progress_row)

        g.add(self._options(LOCAL))
        test = Adw.ActionRow(title=tr("Test"), subtitle=tr("Checks the service, the model and the memory"))
        self._test_button(test, LOCAL)
        g.add(test)
        self.page.add(g)
        self._o_refresh()

    def _o_refresh(self):
        def job():
            return {"inst": og.installed(), "active": og.service_active(), "ver": og.version(),
                    "models": og.models(), "loaded": og.loaded_models(), "res": og.process_resources()}

        def done(d):
            if isinstance(d, Exception):
                self.o_state.set_subtitle(tr("Error: {error}").format(error=d))
                return
            if not d["inst"]:
                self.o_state.set_subtitle(tr("Ollama isn't installed"))
                self.o_start.set_visible(False)
                self.o_free_memory.set_visible(False)
                return
            self.o_start.set_sensitive(True)
            self._o_active = bool(d["active"])
            self.o_start.set_label(tr("Stop") if d["active"] else tr("Start"))
            if d["active"]:
                loaded = ", ".join("%s (%s)" % (m["name"], _gb(m["gb"])) for m in d["loaded"])
                self.o_state.set_subtitle(
                    tr("Running · version {version} · {loaded} · processes: {ram} of RAM").format(
                        version=d["ver"] or "?",
                        loaded=(tr("in memory: {models}").format(models=loaded) if loaded
                                else tr("no model in memory")),
                        ram=_gb(d["res"]["ram_gb"])))
            else:
                self.o_state.set_subtitle(tr("Stopped: start it to use ZETA"))
            self.o_free_memory.set_sensitive(bool(d["loaded"]))
            self._o_models(d["models"])
        _in_thread(job, done)

    def _o_models(self, models_):
        for r in self._model_rows:
            self.ollama_models.remove(r)
        self._model_rows = []
        in_use = self._option(LOCAL, "model", "") or models.choose({m["name"]: m["gb"] for m in models_})
        self.ollama_models.set_subtitle(tr("{n} · in use: {model}").format(n=len(models_), model=in_use)
                                        if models_ else tr("none: download one below"))
        for m in models_:
            r = Adw.ActionRow(title=m["name"], subtitle="%s · %s %s" % (
                _gb(m["gb"]), m["parameters"] or "", m["quantization"] or ""))
            if m["name"] == in_use:
                r.add_suffix(Gtk.Label(label=tr("In Use"), css_classes=["dim-label"], valign=Gtk.Align.CENTER))
            else:
                use = Gtk.Button(label=tr("Use"), valign=Gtk.Align.CENTER)
                use.connect("clicked", lambda _b, n=m["name"]: self._o_use(n))
                r.add_suffix(use)
            remove_btn = Gtk.Button(icon_name="edit-delete-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text=tr("Remove the model"), css_classes=["flat"])
            remove_btn.connect("clicked", lambda _b, n=m["name"]: self._ollama_remove(n))
            r.add_suffix(remove_btn)
            self.ollama_models.add_row(r)
            self._model_rows.append(r)

    def _o_use(self, name):
        self._save_option(LOCAL, "model", name)
        self.toast(tr("ZETA will use the model {name}").format(name=name))
        self._o_refresh()
        self._update_effective()

    def _ollama_remove(self, name):
        d = Adw.AlertDialog(heading=tr("Remove {name}?").format(name=name),
                            body=tr("The model will be deleted from disk. You can download it again."))
        d.add_response("no", tr("Cancel"))
        d.add_response("yes", tr("Remove"))
        d.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)

        def answer(_d, r):
            if r != "yes":
                return
            def done(res):
                ok, msg = res if isinstance(res, tuple) else (False, str(res))
                self.toast(msg)
                if ok and self._option(LOCAL, "model", "") == name:
                    self._save_option(LOCAL, "model", "")
                self._o_refresh()
            _in_thread(lambda: og.remove(name), done)
        d.connect("response", answer)
        d.present(self.w)

    def _o_download(self, line):
        name = line.get_text().strip()
        if not name:
            return
        self._dl_stopped = False
        line.set_sensitive(False)
        self.o_progress_row.set_visible(True)
        self.o_progress_row.set_title(tr("Downloading {name}").format(name=name))
        self.o_prog.set_fraction(0)
        self.o_prog.set_text(tr("starting…"))

        def progress(text, fraction):
            def ui():
                self.o_prog.set_text(text[:60])
                if fraction is not None:
                    self.o_prog.set_fraction(fraction)
                else:
                    self.o_prog.pulse()
                return False
            GLib.idle_add(ui)

        def done(res):
            ok, msg = res if isinstance(res, tuple) else (False, str(res))
            line.set_sensitive(True)
            self.o_progress_row.set_visible(False)
            if ok:
                line.set_text("")
            self.toast(msg)
            self._o_refresh()
        _in_thread(lambda: og.download(name, progress, lambda: self._dl_stopped), done)

    def _o_start_stop(self, b):
        operation = "stop" if self._o_active else "start"
        b.set_sensitive(False)

        def done(res):
            ok, msg = res if isinstance(res, tuple) else (False, str(res))
            self.toast(msg)
            GLib.timeout_add(1500, lambda: (self._o_refresh(), self._update_effective(), False)[2])
        _in_thread(lambda: og.service(operation), done)

    def _o_free_memory(self, b):
        b.set_sensitive(False)
        _in_thread(og.free_memory, lambda n: (self.toast(tr("Memory freed") if n else
                                                           tr("No model in memory")),
                                                 self._o_refresh()))

    # --- common options (temperature, length, timeout, streaming) -----------
    def _options(self, pid):
        """Option rows of the local model."""
        e = Adw.ExpanderRow(title=tr("Advanced Options"),
                            subtitle=tr("Temperature, length, timeout, context, streaming"))

        def spin(title, below, key, default, minimum, maximum, step, digits=0):
            r = Adw.SpinRow.new_with_range(minimum, maximum, step)
            r.set_title(title)
            r.set_subtitle(below)
            r.set_digits(digits)
            r.set_value(float(self._option(pid, key, default) or default))
            r.connect("notify::value", lambda s, _p: self._save_option(
                pid, key, round(s.get_value(), digits) if digits else int(s.get_value())))
            e.add_row(r)

        spin(tr("Temperature"), tr("0 = precise, repeatable answers; 1 and above = more creative"),
             "temperature", 0.7, 0.0, 2.0, 0.1, 1)
        spin(tr("Maximum Reply Length"), tr("in tokens (about 3/4 of a word each)"),
             "max_tokens", 220, 16, 32768, 16)
        spin(tr("Maximum Wait Time"), tr("seconds for the whole reply; 0 = default (5 minutes)"),
             "timeout", 0, 0, 900, 5)
        spin(tr("Context"), tr("conversation tokens the model remembers; 0 = chosen for this "
             "computer ({n}). Larger = more memory used").format(n=models.context_size()),
             "context", 0, 0, 131072, 512)
        s = Adw.SwitchRow(title=tr("Streaming"), subtitle=tr("The reply appears as it's written"))
        s.set_active(bool(self._option(pid, "stream", True)))
        s.connect("notify::active", lambda w, _p: self._save_option(pid, "stream", w.get_active()))
        e.add_row(s)
        return e

    def _test_button(self, line, pid):
        b = Gtk.Button(label=tr("Test"), valign=Gtk.Align.CENTER)

        def test(btn):
            btn.set_sensitive(False)
            line.set_subtitle(tr("testing…"))

            def done(res):
                ok, msg = res if isinstance(res, tuple) else (False, str(res))
                btn.set_sensitive(True)
                line.set_subtitle(("✓ " if ok else "✗ ") + msg)
            _in_thread(lambda: Registry().test(pid), done)
        b.connect("clicked", test)
        line.add_suffix(b)

    def _o_ram_refresh(self):
        def job():
            from intelligence.providers.ollama import OllamaProvider
            prov = Registry().get("ollama")
            need = prov._model_gb() if isinstance(prov, OllamaProvider) else 0.0
            return resources.plan(need), need

        def done(r):
            if isinstance(r, Exception):
                self.o_ram.set_subtitle(tr("can't be determined"))
                return
            p, need = r
            text = tr("{total} GB of RAM, {free} GB free; the model needs about {need} GB. "
                      "Kept in memory {keep} after the last question.").format(
                total="%.0f" % p["nominal_gb"], free="%.1f" % p["available_gb"],
                need="%.1f" % (need or resources.MODEL_GB), keep=p["keep_alive"])
            if p["advice"]:
                text += "\n" + p["advice"]
            elif not p["can_load"]:
                text += "\n" + resources.memory_reason(need)
            self.o_ram.set_subtitle(text)
            self.o_ram.set_subtitle_lines(0)
        _in_thread(job, done)

    # --- memory -------------------------------------------------------------
    def _memory_group(self):
        """What ZETA remembers: the conversation (for how long), the long-term
        memories the user asked for (listed, deletable), export and clear."""
        mem = Memory()
        g = Adw.PreferencesGroup(
            title=tr("Memory"),
            description=tr("What ZETA remembers stays on this computer, in a file only you can read. "
                           "Nothing is remembered for the long term unless you ask: “remember that…”."))
        conv = Adw.SwitchRow(title=tr("Remember the conversation"),
                             subtitle=tr("The latest messages help ZETA follow what you are saying"))
        conv.set_active(mem.enabled)
        conv.connect("notify::active", lambda w, _p: Memory().set_enabled(w.get_active()))
        g.add(conv)

        days = list(store.RETENTION_CHOICES)
        labels = [tr("1 day"), tr("7 days"), tr("30 days"), tr("90 days"), tr("1 year")]
        keep = Adw.ComboRow(title=tr("Keep the conversation for"), model=Gtk.StringList.new(labels))
        keep.set_selected(days.index(mem.retention_days))

        def set_days(r, _p):
            i = r.get_selected()
            if 0 <= i < len(days):
                _in_thread(lambda: Memory().set_retention(days[i]),
                           lambda res: (self.toast(tr("Saved")), self._memory_refresh()))
        keep.connect("notify::selected", set_days)
        g.add(keep)

        lt = Adw.SwitchRow(title=tr("Long-term memory"),
                           subtitle=tr("Each question gets only the memories that match it"))
        lt.set_active(mem.long_term)
        lt.connect("notify::active", lambda w, _p: Memory().set_long_term(w.get_active()))
        g.add(lt)

        self.facts_row = Adw.ExpanderRow(title=tr("Memories"), subtitle="…")
        self._fact_rows = []
        g.add(self.facts_row)
        add = Adw.EntryRow(title=tr("Add a memory (e.g. I prefer short answers)"), show_apply_button=True)

        def add_fact(line):
            text = line.get_text().strip()
            if not text:
                return

            def done(res):
                outcome = res[1] if isinstance(res, tuple) else "error"
                if outcome in ("added", "updated"):
                    line.set_text("")
                    self.toast(tr("Memory saved"))
                elif outcome == "duplicate":
                    self.toast(tr("Already remembered"))
                elif outcome == "full":
                    self.toast(tr("The memory is full: remove something first"))
                else:
                    self.toast(tr("Not saved"))
                self._memory_refresh()
            _in_thread(lambda: store.add_fact(text), done)
        add.connect("apply", add_fact)
        g.add(add)

        self.memory_size = Adw.ActionRow(title=tr("Stored"), subtitle="…")
        export = Gtk.Button(label=tr("Export"), valign=Gtk.Align.CENTER,
                            tooltip_text=tr("Saves everything ZETA remembers in Documents, as a JSON file"))
        export.connect("clicked", self._memory_export)
        clear = Gtk.Button(label=tr("Clear…"), valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
        clear.connect("clicked", self._memory_clear)
        self.memory_size.add_suffix(export)
        self.memory_size.add_suffix(clear)
        g.add(self.memory_size)
        self.page.add(g)
        self._memory_refresh()

    def _memory_refresh(self):
        def job():
            return store.list_facts(), store.stats()

        def done(r):
            if isinstance(r, Exception):
                self.memory_size.set_subtitle(tr("Error: {error}").format(error=r))
                return
            facts, st = r
            for row in self._fact_rows:
                self.facts_row.remove(row)
            self._fact_rows = []
            self.facts_row.set_subtitle(tr("{n} saved").format(n=len(facts)) if facts
                                        else tr("none yet"))
            for f in facts:
                row = Adw.ActionRow(title=GLib.markup_escape_text(f.text),
                                    subtitle=time.strftime("%Y-%m-%d", time.localtime(f.created)))
                row.set_title_lines(0)
                rm = Gtk.Button(icon_name="edit-delete-symbolic", valign=Gtk.Align.CENTER,
                                css_classes=["flat"], tooltip_text=tr("Forget this"))
                rm.connect("clicked", lambda _b, fid=f.id: _in_thread(
                    lambda: store.delete_fact(fid), lambda _r: self._memory_refresh()))
                row.add_suffix(rm)
                self.facts_row.add_row(row)
                self._fact_rows.append(row)
            self.memory_size.set_subtitle(
                tr("{turns} messages, {facts} memories, {sources} saved sources · {size}").format(
                    turns=st["turns"], facts=st["facts"], sources=st["knowledge"],
                    size=_size(st["bytes"])))
        _in_thread(job, done)

    def _memory_export(self, _b):
        folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS) or os.path.expanduser("~")
        dest = os.path.join(folder, "zeta-memory-%s.json" % time.strftime("%Y-%m-%d-%H%M"))
        _in_thread(lambda: store.export(dest), lambda ok: self.toast(
            tr("Saved in {path}").format(path=dest) if ok is True else tr("Not saved")))

    def _memory_clear(self, _b):
        d = Adw.AlertDialog(heading=tr("Clear ZETA's memory?"),
                            body=tr("The conversation is always cleared. “Everything” also removes "
                                    "the memories you asked ZETA to keep and the saved web sources."))
        d.add_response("no", tr("Cancel"))
        d.add_response("conversation", tr("Conversation"))
        d.add_response("everything", tr("Everything"))
        d.set_response_appearance("everything", Adw.ResponseAppearance.DESTRUCTIVE)

        def answer(_d, r):
            if r in ("conversation", "everything"):
                _in_thread(lambda: store.clear(r), lambda _x: (self.toast(tr("Memory cleared")),
                                                                self._memory_refresh()))
        d.connect("response", answer)
        d.present(self.w)

    # --- current information from the web ----------------------------------
    def _web_group(self):
        s = load_settings()
        g = Adw.PreferencesGroup(
            title=tr("Current Information"),
            description=tr("A model only knows the world up to its training date. For questions "
                           "about current facts (office holders, news, prices, versions, weather, "
                           "results) ZETA can look up public sources first, and shows them under "
                           "the answer."))
        on = Adw.SwitchRow(title=tr("Search the web for current information"),
                           subtitle=tr("Only for questions about current facts. Only the question, "
                                       "shortened, is sent to Wikipedia: never the chat, never "
                                       "your files."))
        on.set_active(websearch.enabled(s))
        ddg = Adw.SwitchRow(title=tr("Also ask DuckDuckGo"),
                            subtitle=tr("Instant answers (api.duckduckgo.com): the shortened "
                                        "question is sent there too."))
        ddg.set_active(bool(s.get(websearch.SETTING_DDG)))
        ddg.set_sensitive(on.get_active())

        def save(key, value):
            st = load_settings()
            st[key] = value
            if key == websearch.SETTING_ENABLED and value:
                st.pop(websearch.SETTING_DECLINED, None)
            try:
                save_settings(st)
            except OSError as e:
                self.toast(tr("Choice not saved: {error}").format(error=e))
                return
            self.reg.settings = st

        def toggled(w, _p):
            save(websearch.SETTING_ENABLED, w.get_active())
            ddg.set_sensitive(w.get_active())
        on.connect("notify::active", toggled)
        ddg.connect("notify::active", lambda w, _p: save(websearch.SETTING_DDG, w.get_active()))
        g.add(on)
        g.add(ddg)
        self.page.add(g)

    # --- language of the replies --------------------------------------------
    def _language_group(self):
        """ZETA answers in the language the user writes or speaks in (the
        system language when that is unclear), or always in the system
        language chosen in Language & Region."""
        from i18n import language
        from intelligence.registry import REPLY_LANGUAGE, language_label
        g = Adw.PreferencesGroup(title=tr("Language"))
        system_name = language_label(language())
        modes = ["auto", "system"]
        row = Adw.ComboRow(
            title=tr("Reply language"),
            model=Gtk.StringList.new([tr("Same as my message"),
                                      tr("Always {language}").format(language=system_name)]))
        # "Language & Region" has a plain ampersand: markup off before the
        # text is set (as a constructor argument it was parsed as markup first)
        row.set_use_markup(False)
        row.set_subtitle(tr("The language set in Language & Region: {language}").format(language=system_name))
        current = load_settings().get(REPLY_LANGUAGE, "auto")
        row.set_selected(modes.index(current) if current in modes else 0)

        def changed(r, _p):
            st = load_settings()
            st[REPLY_LANGUAGE] = modes[r.get_selected()]
            try:
                save_settings(st)
            except OSError as e:
                self.toast(tr("Choice not saved: {error}").format(error=e))
                return
            self.reg.settings = st
        row.connect("notify::selected", changed)
        g.add(row)
        self.page.add(g)

    # --- behavior -----------------------------------------------------------
    def _behavior_group(self):
        g = Adw.PreferencesGroup(title=tr("ZETA Behavior"))
        e = Adw.ExpanderRow(title=tr("System Instructions"),
                            subtitle=tr("How ZETA introduces itself and behaves"))
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                          left_margin=8, right_margin=8)
        tv.get_buffer().set_text(self.reg.settings.get("system", DEFAULT_SYSTEM))
        sc = Gtk.ScrolledWindow(child=tv, min_content_height=130, margin_top=6, margin_bottom=6,
                                margin_start=6, margin_end=6)
        e.add_row(sc)
        buttons = Adw.ActionRow(title="")
        save_btn = Gtk.Button(label=tr("Save"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        restore = Gtk.Button(label=tr("Restore ZETA RAYS Defaults"), valign=Gtk.Align.CENTER)

        def _save(_b):
            b = tv.get_buffer()
            text = b.get_text(b.get_start_iter(), b.get_end_iter(), False).strip()
            s = dict(self.reg.settings)
            if text and text != DEFAULT_SYSTEM:
                s["system"] = text
            else:
                s.pop("system", None)
            save_settings(s)
            self.reg.settings = s
            self.toast(tr("Instructions saved: they apply from the next question"))

        def _restore(_b):
            tv.get_buffer().set_text(DEFAULT_SYSTEM)
            _save(None)
        save_btn.connect("clicked", _save)
        restore.connect("clicked", _restore)
        buttons.add_suffix(restore)
        buttons.add_suffix(save_btn)
        e.add_row(buttons)
        g.add(e)
        self.behavior_group = g
        self.page.add(g)


def build(window):
    """The AI page and the "Behavior" group (so more rows can be added to it)."""
    p = AIPage(window)
    return p.page, p.behavior_group
