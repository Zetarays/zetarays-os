# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › AI: which intelligence ZETA uses, keys, models.

Anything that may take more than a moment (network, Ollama, key encryption)
runs in a thread: the window never stops to wait.
"""
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from intelligence import ollama_manager as og  # noqa: E402
from intelligence import resources, websearch  # noqa: E402
from intelligence.registry import (CATALOG, DEFAULT_SYSTEM, Registry,  # noqa: E402
                                   capabilities, keyring_set, keyring_where, default_model,
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


class AIPage:
    def __init__(self, window):
        self.w = window
        self.reg = Registry()
        self.page = Adw.PreferencesPage()
        self._choice_group()
        self._ollama_group()
        self._cloud_group()
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
            title=tr("Active Intelligence"),
            description=tr("Automatic uses Ollama, the model on this computer, which works even "
                           "without internet. Questions go to an online service only if you choose "
                           "it here, or accept it in the chat for one question."))
        self.ids = ["auto"] + list(CATALOG)
        names = [tr("Automatic")] + [
            (tr("{name} (on this computer)") if CATALOG[p][2] == "local"
             else tr("{name} (online)")).format(name=CATALOG[p][1])
            for p in CATALOG]
        line = Adw.ComboRow(title=tr("ZETA uses"), model=Gtk.StringList.new(names))
        current = self.reg.settings.get("default", "auto") or "auto"
        line.set_selected(self.ids.index(current) if current in self.ids else 0)
        self.effective_row = Adw.ActionRow(title=tr("In use now"), subtitle="…")

        def choose(c, _p):
            pid = self.ids[c.get_selected()]
            try:
                self.reg.choose(pid)
            except (ValueError, OSError) as e:
                self.toast(tr("Choice not saved: {error}").format(error=e))
                return
            if pid == "auto":
                self.toast(tr("ZETA will choose automatically"))
            else:
                self.toast(tr("ZETA will use {name}").format(name=CATALOG[pid][1]))
            self._update_effective()
        line.connect("notify::selected", choose)
        g.add(line)
        g.add(self.effective_row)
        self.page.add(g)
        self._update_effective()

    def _update_effective(self):
        def job():
            p = Registry().resolve_default()
            if p.config.kind == "local" and hasattr(p, "_model"):
                model = p._model()          # Ollama: the default one, or the first installed
            else:
                model = p.config.model or default_model(p.config.name)
            return tr("{name} · model {model}").format(name=p.config.label,
                                                       model=model or tr("default"))
        _in_thread(job, lambda r: self.effective_row.set_subtitle(
            r if isinstance(r, str) else tr("can't be determined")))

    # --- Ollama -------------------------------------------------------------
    def _ollama_group(self):
        g = Adw.PreferencesGroup(title=tr("Ollama · On This Computer"),
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

        self.o_download = Adw.EntryRow(title=tr("Download a model (e.g. qwen3:1.7b, qwen3:4b-instruct, gemma3:4b)"),
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

        g.add(self._options("ollama", locale=True))
        test = Adw.ActionRow(title=tr("Test Connection"), subtitle=tr("A short question to the model"))
        self._test_button(test, "ollama")
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
                self.o_state.set_subtitle(tr("Stopped: start it, or choose an online service above"))
            self.o_free_memory.set_sensitive(bool(d["loaded"]))
            self._o_models(d["models"])
        _in_thread(job, done)

    def _o_models(self, models):
        for r in self._model_rows:
            self.ollama_models.remove(r)
        self._model_rows = []
        names = [m["name"] for m in models]
        in_use = self._option("ollama", "model", "") or (
            default_model("ollama") if default_model("ollama") in names or not names else names[0])
        self.ollama_models.set_subtitle(tr("{n} · in use: {model}").format(n=len(models), model=in_use)
                                    if models else tr("none: download one below"))
        for m in models:
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
        self._save_option("ollama", "model", name)
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
                if ok and self._option("ollama", "model", "") == name:
                    self._save_option("ollama", "model", "")
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
    def _options(self, pid, locale=False, inside=None):
        """Option rows. With «inside» (a service's card) they go directly in
        there: libadwaita doesn't show the content of an expander row nested
        inside another one (tested: it stayed empty)."""
        e = inside or Adw.ExpanderRow(title=tr("Advanced Options"),
                                      subtitle=tr("Temperature, length, timeout, streaming"))

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
             "max_tokens", 220 if locale else 4096, 16, 32768, 16)
        spin(tr("Maximum Wait Time"), tr("seconds for the whole reply; 0 = default (5 minutes "
                                         "on this computer, 3 online)"),
             "timeout", 0, 0, 900, 5)
        if locale:
            spin(tr("Context"), tr("conversation tokens the model remembers; 0 = the model's "
                 "default. Larger = more memory used"), "context", 0, 0, 131072, 512)
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

    # --- online services ----------------------------------------------------
    def _cloud_group(self):
        g = Adw.PreferencesGroup(
            title=tr("Online Services"),
            description=tr("Keys are encrypted: only your user can read them, only on this "
                           "computer. Questions go only to the chosen service."))
        self._expanders = {}
        for pid, (_cls, name, kind) in CATALOG.items():
            if kind != "cloud":
                continue
            e = Adw.ExpanderRow(title=name, subtitle="…")
            self._expanders[pid] = e
            e.add_row(self._about_row(pid))

            key = Adw.PasswordEntryRow(title=tr("API Key") if pid != "custom"
                                          else tr("API Key (optional for services on this computer)"),
                                          show_apply_button=True)
            key.connect("apply", lambda r, p=pid: self._save_key(p, r))
            e.add_row(key)
            remove = Adw.ActionRow(title=tr("Remove the saved key"))
            bt = Gtk.Button(label=tr("Remove"), valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
            bt.connect("clicked", lambda _b, p=pid: self._remove_key(p))
            remove.add_suffix(bt)
            e.add_row(remove)

            default = default_model(pid)
            fields = [("model", tr("Model (default: {model})").format(model=default) if default
                      else tr("Model"))]
            fields.append(("endpoint",
                          tr("Service address, e.g. http://localhost:1234/v1/chat/completions")
                          if pid == "custom"
                          else tr("Service address (empty = the official one)")))
            for k, title in fields:
                r = Adw.EntryRow(title=title, show_apply_button=True)
                r.set_text(str(self._option(pid, k, "") or ""))
                r.connect("apply", lambda w, p=pid, k=k: (
                    self._save_option(p, k, w.get_text().strip()),
                    self.toast(tr("Saved: press “Test” to check")), self._cloud_state(p)))
                e.add_row(r)
            self._options(pid, inside=e)
            test = Adw.ActionRow(title=tr("Test Connection"),
                                  subtitle=tr("A real, very small request"))
            self._test_button(test, pid)
            e.add_row(test)
            g.add(e)
            self._cloud_state(pid)
        self.page.add(g)

    @staticmethod
    def _about_row(pid):
        """What this service costs (where verified) and what ZETA really does
        with it: only the capabilities the code supports are listed."""
        notes = {
            # checked at api-docs.deepseek.com on 17 October 2026
            "deepseek": tr("Pay as you go: the API has no permanent free tier. The DeepSeek web "
                           "chat is free, but ZETA can't use it. Default model: deepseek-flash "
                           "(DeepSeek V4.1 Flash)."),
            # checked at ai.google.dev/gemini-api/docs/pricing on 17 October 2026
            "gemini": tr("Has a free tier with rate limits; on the free tier Google may use what "
                         "you send to improve its products (not on the paid tier)."),
            "perplexity": tr("Searches the web by itself and cites its sources."),
            "custom": tr("Any OpenAI-compatible service. At a localhost address nothing leaves "
                         "this computer."),
        }
        caps = capabilities(pid)
        parts = [tr("Can run ZETA's actions (with your confirmation)") if caps["tools"] else
                 tr("Replies appear as they are written")]
        text = " · ".join(parts)
        if pid in notes:
            text = notes[pid] + "\n" + text
        row = Adw.ActionRow(title=tr("About This Service"), subtitle=text)
        row.set_subtitle_lines(0)
        return row

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
            use_markup=False,          # "Language & Region": a plain ampersand
            title=tr("Reply language"),
            subtitle=tr("The language set in Language & Region: {language}").format(language=system_name),
            model=Gtk.StringList.new([tr("Same as my message"),
                                      tr("Always {language}").format(language=system_name)]))
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

    def _cloud_state(self, pid):
        def job():
            p = Registry().get(pid)
            return bool(p.config.api_key), p.config.model or default_model(pid)

        def done(r):
            if isinstance(r, Exception):
                return
            has_key, model = r
            self._expanders[pid].set_subtitle(
                tr("key saved · {model}").format(model=model) if has_key else
                (tr("no key") if pid == "custom" else tr("key missing")))
        _in_thread(job, done)

    def _save_key(self, pid, line):
        val = line.get_text().strip()
        if not val:
            self.toast(tr("Enter the key before saving it"))
            return
        line.set_sensitive(False)

        def done(ok):
            line.set_sensitive(True)
            if ok is True:
                line.set_text("")
                self.toast(tr("Key saved ({where})").format(where=keyring_where().split(" (")[0]))
            else:
                self.toast(tr("Key NOT saved: try again, or see “zeta diagnose”"))
            self._cloud_state(pid)
        _in_thread(lambda: keyring_set(pid, val), done)

    def _remove_key(self, pid):
        _in_thread(lambda: keyring_set(pid, ""),
                   lambda ok: (self.toast(tr("Key removed") if ok is True else tr("Not removed")),
                               self._cloud_state(pid), self._update_effective()))

    # --- behavior -----------------------------------------------------------
    def _behavior_group(self):
        g = Adw.PreferencesGroup(title=tr("ZETA Behavior"))
        e = Adw.ExpanderRow(title=tr("System Instructions"),
                            subtitle=tr("How ZETA introduces itself and behaves, with every service"))
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
        g.add(Adw.ActionRow(title=tr("Conversation Memory"),
                            subtitle=tr("Stays on this computer (clear it with “zeta --forget”)")))
        self.behavior_group = g
        self.page.add(g)


def build(window):
    """The AI page and the "Behavior" group (so more rows can be added to it)."""
    p = AIPage(window)
    return p.page, p.behavior_group
