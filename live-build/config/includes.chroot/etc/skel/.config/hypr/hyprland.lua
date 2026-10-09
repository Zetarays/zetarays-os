-- SPDX-License-Identifier: GPL-3.0-or-later
-- ZETA RAYS — configurazione di Hyprland (0.55, formato Lua)

-- Colore d'accento: il file zeta_colors.lua è scritto da zeta-accent
local ok, colors = pcall(require, "zeta_colors")
if not ok or type(colors) ~= "table" then
    colors = { accent = "rgb(3A8DFF)" }
end

-- Macchina virtuale (VirtualBox, QEMU...): zeta-desktop-session scrive zeta_vm.lua.
-- Nelle VM il cursore hardware spesso non si vede, quindi usiamo quello software.
-- pcall restituisce il messaggio d'errore al posto del valore quando fallisce:
-- va ridotto a un booleano vero, altrimenti una stringa d'errore conterebbe
-- come «sono in una VM» e sballerebbe gli effetti qui sotto.
local vm_ok, vm_val = pcall(require, "zeta_vm")
local is_vm = (vm_ok and vm_val == true)
if is_vm then
    -- nelle VM il cursore hardware spesso non si vede
    hl.config({ cursor = { no_hardware_cursors = true } })
end

-------------------
---- SCHERMI ----
-------------------

-- Scala calcolata all'avvio da zeta-display-scale (DPI reali dall'EDID).
-- La scala "auto" di Hyprland sbaglia senza EDID (nelle VM mette 2x).
local mon_ok, mon = pcall(require, "zeta_monitor")
local monitor_scale = (mon_ok and type(mon) == "table" and mon.scale) or 1

hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = monitor_scale,
})

-- Impostazioni › Schermi: risoluzione, frequenza, scala, rotazione, posizione,
-- specchio e schermo principale, ricordati per ogni schermo (marca, modello,
-- numero di serie). Le regole per uno schermo preciso valgono piu' di quella
-- generale qui sopra, che resta per gli schermi mai configurati.
-- Il file c'e' solo dopo il primo «Mantieni» nelle Impostazioni: un require
-- di un modulo che non esiste Hyprland lo segnala come errore della
-- configurazione (riquadro rosso) anche dentro pcall, quindi prima si guarda.
local sch_file = io.open(os.getenv("HOME") .. "/.config/hypr/zeta_schermi.lua", "r")
local sch_ok, schermi = false, nil
if sch_file then
    sch_file:close()
    sch_ok, schermi = pcall(require, "zeta_schermi")
end
if sch_ok and type(schermi) == "function" then
    local ok_s, err_s = pcall(schermi)
    if not ok_s then hl.notification.create({ text = "zeta_schermi: " .. tostring(err_s), timeout = 5000 }) end
    -- all'avvio gli schermi si collegano dopo la lettura della configurazione:
    -- lo specchio, che vuole il nome della presa, si rimette quando compaiono
    hl.on("monitor.added", function() pcall(schermi) end)
end

-------------------
---- AVVIO ----
-------------------

hl.on("hyprland.start", function()
    hl.exec_cmd("zeta-session")
end)

-- Dimensione del puntatore scelta in Impostazioni > Aspetto (zeta-aspetto)
-- Keyboard layout of the system (installer, Settings > Language & Region):
-- zeta-desktop-session writes zeta_tastiera.lua from /etc/default/keyboard.
local kb_ok, kb = pcall(require, "zeta_tastiera")
if not kb_ok or type(kb) ~= "table" then kb = {} end
local asp_ok, asp = pcall(require, "zeta_aspetto")
local cursor_size = (asp_ok and type(asp) == "table" and asp.cursor) or 24
local tema_chiaro = asp_ok and type(asp) == "table" and asp.tema == "chiaro"
-- Effetti scelti in Impostazioni › Aspetto. Spegnerli rende il desktop più
-- reattivo sulle macchine lente; i valori predefiniti restano quelli di ZETA RAYS.
local asp_t = (asp_ok and type(asp) == "table") and asp or {}
local animazioni  = asp_t.animazioni ~= false
local trasparenza = asp_t.trasparenza ~= false
local angoli      = tonumber(asp_t.angoli) or 14

hl.env("XCURSOR_SIZE", tostring(cursor_size))
hl.env("HYPRCURSOR_SIZE", tostring(cursor_size))
hl.env("QT_QPA_PLATFORM", "wayland;xcb")

-------------------
---- ASPETTO ----
-------------------

hl.config({
    general = {
        gaps_in     = 6,
        gaps_out    = 12,
        border_size = 1,
        col = {
            active_border   = colors.accent,
            inactive_border = tema_chiaro and "rgba(00000018)" or "rgba(ffffff14)",
        },
        resize_on_border = true,
        layout = "dwindle",
    },

    decoration = {
        rounding       = angoli,
        rounding_power = 2,
        active_opacity   = 1.0,
        inactive_opacity = 1.0,

        -- Il costo degli effetti si adatta alla macchina. Sfocatura e ombre
        -- sono l'operazione piu pesante del compositore: «passes = 3» rifa il
        -- calcolo tre volte su tutta l'area sfocata. Su un computer vero con
        -- GPU non si sente; dentro una macchina virtuale, dove tutto viene
        -- disegnato dalla CPU, e la ragione principale per cui il desktop
        -- sembrava lento. In VM si tiene lo stesso aspetto vetro, ma con un
        -- solo passaggio e un raggio piccolo: costa circa un ottavo.
        shadow = {
            enabled      = trasparenza and not is_vm,
            range        = 40,
            render_power = 3,
            color        = 0xaa000000,
        },

        blur = {
            enabled  = trasparenza,
            size     = is_vm and 4 or 10,
            -- due passaggi: a vista quasi uguale a tre, un terzo di lavoro in meno
            passes   = is_vm and 1 or 2,
            vibrancy = 0.17,
            -- non risfocare cio che sta gia dietro una finestra opaca
            new_optimizations = true,
            xray              = true,
        },
    },

    animations = {
        enabled = animazioni,
    },

    dwindle = {
        preserve_split = true,
    },

    misc = {
        force_default_wallpaper = 0,
        disable_hyprland_logo   = true,
        disable_splash_rendering = true,
        background_color        = tema_chiaro and 0xfff6f6f8 or 0xff000000,
        -- se la schermata di blocco si chiude, una nuova può riprendere la sessione
        allow_session_lock_restore = true,
        -- standby dello schermo: tastiera o mouse lo riaccendono
        key_press_enables_dpms   = true,
        mouse_move_enables_dpms  = true,
    },

    input = {
        kb_layout    = kb.layout or "us",
        kb_variant   = kb.variant or "",
        kb_options   = kb.options or "",
        follow_mouse = 1,
        touchpad = {
            natural_scroll = true,
        },
    },
})

-- Animazioni: morbide e rapide
hl.curve("zeta",   { type = "bezier", points = { {0.2, 0.9}, {0.1, 1} } })
hl.curve("linear", { type = "bezier", points = { {0, 0},     {1, 1}   } })
hl.curve("soft",   { type = "spring", mass = 1, stiffness = 80, dampening = 16 })

hl.animation({ leaf = "global",     enabled = true, speed = 8,   bezier = "zeta" })
hl.animation({ leaf = "border",     enabled = true, speed = 5,   bezier = "zeta" })
hl.animation({ leaf = "windowsIn",  enabled = true, speed = 4,   spring = "soft",   style = "popin 90%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 1.5, bezier = "linear", style = "popin 90%" })
hl.animation({ leaf = "fade",       enabled = true, speed = 3,   bezier = "zeta" })
hl.animation({ leaf = "layersIn",   enabled = true, speed = 3,   bezier = "zeta",   style = "fade" })
hl.animation({ leaf = "layersOut",  enabled = true, speed = 1.5, bezier = "linear", style = "fade" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 3,   bezier = "zeta",   style = "slide" })

hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

-------------------
---- BARRE DEL TITOLO ----
-------------------

-- Hyprland non disegna decorazioni: senza questo plugin nessuna finestra
-- avrebbe chiudi / riduci / ingrandisci. Il plugin è compilato in fase di
-- build contro questa stessa versione di Hyprland (hook 0400).
-- Al primo avvio il plugin non è ancora caricato quando la configurazione
-- viene letta: zeta-session esegue un «hyprctl reload» che completa il giro.
local BARS = "/usr/lib/zeta/hypr/hyprbars.so"
local bars_file = io.open(BARS, "r")
if bars_file then
    bars_file:close()
    hl.plugin.load(BARS)
end

if hl.plugin.hyprbars then
    hl.config({
        plugin = {
            hyprbars = {
                enabled                    = true,
                bar_height                 = 32,
                -- la barra del titolo segue il tema scelto in Impostazioni
                bar_color                  = tema_chiaro and "rgba(F2F2F4F2)" or "rgba(1C1C1EF2)",
                col                        = { text = tema_chiaro and "rgb(1C1C1E)" or "rgb(EDEDEA)" },
                bar_text_size              = 11,
                bar_text_font              = "Roboto",
                bar_text_align             = "center",
                bar_buttons_alignment      = "left",
                bar_padding                = 12,
                bar_button_padding         = 8,
                bar_part_of_window         = true,
                bar_precedence_over_border = true,
                -- la barra e' opaca al 95%: la sfocatura dietro non si vedeva,
                -- ma si calcolava per ogni finestra a ogni fotogramma
                bar_blur                   = false,
                icon_on_hover              = true,
                on_double_click            = [[hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = "maximized" })']],
            },
        },
    })

    -- Ordine da sinistra: chiudi, riduci, ingrandisci.
    hl.plugin.hyprbars.add_button({
        bg_color = "rgb(FF5F57)", fg_color = "rgba(00000099)", size = 13, icon = "×",
        action = [[hyprctl dispatch 'hl.dsp.window.close()']],
    })
    hl.plugin.hyprbars.add_button({
        bg_color = "rgb(FEBC2E)", fg_color = "rgba(00000099)", size = 13, icon = "–",
        action = "zeta-finestre minimizza",
    })
    hl.plugin.hyprbars.add_button({
        bg_color = "rgb(28C840)", fg_color = "rgba(00000099)", size = 13, icon = "+",
        action = [[hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = "maximized" })']],
    })
end

-------------------
---- REGOLE ----
-------------------

-- Barra, launcher e notifiche con effetto vetro
hl.layer_rule({ name = "zeta-bar-blur",      match = { namespace = "^waybar$" },        blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-launcher-blur", match = { namespace = "^zeta-launcher$" }, blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-cerca-blur",    match = { namespace = "^zeta-cerca$" },    blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-notify-blur",   match = { namespace = "^notifications$" }, blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-control-blur",  match = { namespace = "^zeta-control$" },  blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-energia-blur",  match = { namespace = "^zeta-energia$" },  blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-selettore-blur", match = { namespace = "^zeta-selettore$" }, blur = true, ignore_alpha = 0.1 })
-- la foto della finestra che si riduce deve comparire di colpo, sopra la
-- finestra vera: con la dissolvenza si vedrebbe un salto (zeta-riduci)
hl.layer_rule({ name = "zeta-riduci-subito", match = { namespace = "^zeta-riduci$" }, no_anim = true })

-- Finestre mobili e centrate, come su macOS (Super + V per affiancarle),
-- mai più grandi dello schermo: su schermi piccoli nulla finisce sotto la barra.
hl.window_rule({ name = "zeta-float-all", match = { class = ".*" }, float = true, center = true,
                 max_size = "(monitor_w*0.92) (monitor_h*0.84)" })
-- Posta: al primo avvio Thunderbird non chiede una dimensione e la finestra
-- principale nasceva minuscola (250x300). Solo le finestre principali (titolo
-- «... - Mozilla Thunderbird»), non i dialoghi; poi ricorda da se' la misura.
hl.window_rule({ name = "zeta-posta-misura",
                 match = { class = "^thunderbird$", title = ".*Mozilla Thunderbird$" },
                 size = "(monitor_w*0.8) (monitor_h*0.78)" })
-- Firefox: stessa cosa al primo avvio (finestra piccola, la pagina iniziale
-- di ZETA RAYS si vedeva a meta'). Solo le finestre principali.
hl.window_rule({ name = "zeta-browser-misura",
                 match = { class = "^firefox-esr$", title = ".*Mozilla Firefox$" },
                 size = "(monitor_w*0.8) (monitor_h*0.78)" })
-- Blender: la finestra principale sempre grande, come quella del pacchetto
-- del sistema. Le versioni scaricate da blender.org (5.x) si aprono su
-- Wayland con un altro nome (org.blender.Blender) e una misura di fabbrica
-- piccola; quella del sistema passa da X11 come «Blender». Solo la finestra
-- principale («Blender», «Blender [file]», «file - Blender 5.2», e anche
-- «(Unsaved) - Blender 5.2.2 LTS»: senza il suffisso «LTS» la regola non
-- scattava e il 5.2.2 avviato su Wayland nasceva a 320x240): Preferenze,
-- Render e i dialoghi dei file restano della loro misura.
hl.window_rule({ name = "zeta-blender-misura",
                 match = { class = "^([Bb]lender|org\\.blender\\.Blender)$",
                           title = "^(Blender|Blender\\*?( \\[.*\\])?|.* - Blender( [0-9.]+)?( [A-Za-z][A-Za-z ]*)?)$" },
                 size = "(monitor_w*0.92) (monitor_h*0.84)" })
hl.window_rule({ name = "zeta-posta-scrivi",
                 match = { class = "^thunderbird$", title = "^(Componi|Scrivi|Compose|Write): .*" },
                 size = "(monitor_w*0.62) (monitor_h*0.72)" })

-- Finestre principali che nascono piccole. Qui tutte le finestre sono
-- fluttuanti, e un programma senza una misura salvata si apre con la sua
-- misura minima di fabbrica (Thunar 640x480, l'editor di testo 700x520): su
-- uno schermo grande sembrava una finestra «chiusa» da allargare a mano.
-- Si allargano solo le finestre principali: la prima finestra di un
-- programma, o una nuova con lo stesso finale del titolo («... - Thunar»).
-- I dialoghi (Preferenze, Copia file, Autentica, Proprieta') restano come
-- sono, e cosi' un programma che si ricorda gia' una misura grande.
local ZETA_NON_ALLARGARE = { "^zenity$", "^yad$", "^kdialog$", "^polkit", "^pinentry",
    "portal", "^gcr%-prompter$", "^zeta%-", "^org%.zetarays%.", "^nm%-", "^blueman" }

local function zeta_finale_titolo(t)
    return (t or ""):match(" [-—] ([^-—]+)$")
end

local function zeta_finestra_principale(w)
    local finale = zeta_finale_titolo(w.title)
    local altre = 0
    for _, a in ipairs(hl.get_windows()) do
        if a.address ~= w.address and a.class == w.class and a.mapped then
            altre = altre + 1
            if finale and zeta_finale_titolo(a.title) == finale then return true end
        end
    end
    return altre == 0
end

-------------------
---- FINESTRE SEMPRE RAGGIUNGIBILI ----
-------------------

-- Nessuna finestra deve finire dove non la si puo' prendere. Un programma
-- X11 puo' spostarsi da solo dopo l'apertura (anche a coordinate negative)
-- o chiedere una misura piu' grande dello schermo; staccando un monitor o
-- cambiando risoluzione o scala una finestra puo' restare fuori. Qui, nello
-- stesso compositore (nessun secondo gestore di finestre), ogni finestra
-- mobile resta con la barra del titolo e i pulsanti (a sinistra) dentro
-- l'area utile: lo schermo meno la barra di ZETA RAYS.
-- La barra del titolo (hyprbars) sta SOPRA la posizione della finestra.
local ZG_BARRA   = hl.plugin.hyprbars and 32 or 0
local ZG_MARGINE = 8
local ZG_VISIBILE = 160       -- quanta finestra resta almeno visibile a destra
local zg_ultimo, zg_conti = {}, {}
-- misura chiesta all'ultima correzione e misura minima di un programma che
-- l'ha rifiutata (una finestra che non puo' diventare piu' piccola di cosi')
local zg_chiesto, zg_minimo = {}, {}

-- Area utile di un monitor, in coordinate logiche (come le finestre).
-- Hyprland non da' l'area riservata al Lua: la si ricava dalla barra.
local function zeta_area(m)
    local sc = (m.scale and m.scale > 0) and m.scale or 1
    local mw, mh = m.width / sc, m.height / sc
    if m.transform % 2 == 1 then mw, mh = mh, mw end
    local a = { x0 = m.x, y0 = m.y, x1 = m.x + mw, y1 = m.y + mh }
    local ok, livelli = pcall(hl.get_layers, { monitor = m })
    if ok and type(livelli) == "table" then
        for _, l in ipairs(livelli) do
            if l.mapped and l.namespace == "waybar" and l.w >= mw * 0.5 and l.h < mh * 0.3 then
                if l.y + l.h >= a.y1 - 40 then
                    a.y1 = math.min(a.y1, l.y)                   -- barra in basso
                elseif l.y <= a.y0 + 40 then
                    a.y0 = math.max(a.y0, l.y + l.h)             -- barra in alto
                end
            end
        end
    end
    return a
end

-- Le finestre di cui occuparsi: mobili, visibili sullo schermo (non ridotte
-- a icona, che stanno in un workspace speciale), non a tutto schermo. I menu
-- e i suggerimenti X11 (senza titolo) si posizionano da se'.
local function zeta_da_guardare(w)
    if not w.mapped or not w.floating or w.fullscreen ~= 0 then return false end
    if w.xwayland and (w.title or "") == "" then return false end
    local ws = w.workspace
    if not ws or ws.special then return false end
    return w.monitor ~= nil
end

-- Dove dovrebbe stare la finestra: nil se va bene cosi'.
-- «stretto»: tutta dentro (apertura, cambio di schermo, recupero a mano);
-- altrimenti basta che la barra del titolo e i pulsanti siano raggiungibili.
local function zeta_correzione(w, stretto)
    local a = zeta_area(w.monitor)
    local aw, ah = a.x1 - a.x0, a.y1 - a.y0
    local x, y, W, H = w.at.x, w.at.y, w.size.x, w.size.y
    local addr = w.address
    -- il programma ha tenuto una misura piu' grande di quella chiesta: e' la
    -- sua minima. Non la si chiede piu' (sarebbe un ciclo): la finestra resta
    -- di quella misura, con la barra del titolo in alto dentro lo schermo.
    local chiesto = zg_chiesto[addr]
    if chiesto and (W > chiesto.w or H > chiesto.h) then
        zg_minimo[addr] = { w = W, h = H }
    end
    zg_chiesto[addr] = nil
    local nW, nH = W, H
    if W > aw then nW = math.floor(aw - 2 * ZG_MARGINE) end
    if H + ZG_BARRA > ah then nH = math.floor(ah - ZG_BARRA - 2 * ZG_MARGINE) end
    local minimo = zg_minimo[addr]
    if minimo then
        nW, nH = math.max(nW, math.min(W, minimo.w)), math.max(nH, math.min(H, minimo.h))
    end
    local ymin = a.y0 + ZG_BARRA
    local nx, ny
    if nW ~= W or nH ~= H then
        -- troppo grande: ridotta all'area utile e centrata
        nx = a.x0 + (aw - nW) / 2
        ny = ymin + (a.y1 - ymin - nH) / 2
    elseif stretto then
        nx = math.max(a.x0, math.min(x, a.x1 - nW))
        ny = math.max(ymin, math.min(y, a.y1 - nH))
    else
        nx = math.max(a.x0, math.min(x, a.x1 - ZG_VISIBILE))
        ny = math.max(ymin, math.min(y, a.y1 - 48))
    end
    nx, ny = math.floor(nx), math.floor(ny)
    if nx == x and ny == y and nW == W and nH == H then return nil end
    return { x = nx, y = ny, w = nW, h = nH, area = a }
end

local function zeta_sistema(w, stretto)
    local c = zeta_correzione(w, stretto)
    local addr = w.address
    if not c then zg_conti[addr] = nil; return false end
    -- un programma che si rimette fuori di continuo non va inseguito:
    -- dopo 4 correzioni lo si lascia stare (il recupero a mano resta)
    local n = (zg_conti[addr] or 0) + 1
    if n > 4 then return false end
    zg_conti[addr] = n
    -- Hyprland calcola spostamento e misura come differenza dalla misura
    -- della finestra, ma la applica al riquadro del layout: se un programma
    -- X11 si e' ridimensionato o spostato da solo i due non coincidono, e il
    -- primo comando arriva altrove (anche a misure negative, ridotte alla
    -- minima). Dal secondo coincidono: si ripete finche' il risultato e'
    -- quello chiesto.
    if c.w ~= w.size.x or c.h ~= w.size.y then
        for _ = 1, 3 do
            hl.dispatch(hl.dsp.window.resize({ x = c.w, y = c.h, window = w }))
            if w.size.x == c.w and w.size.y == c.h then break end
        end
        -- al prossimo controllo si vede se il programma l'ha accettata
        zg_chiesto[addr] = { w = c.w, h = c.h }
    end
    for _ = 1, 3 do
        hl.dispatch(hl.dsp.window.move({ x = c.x, y = c.y, window = w }))
        if w.at.x == c.x and w.at.y == c.y then break end
    end
    return true
end

-- Controllo di tutte le finestre. Senza «stretto» si tocca solo una finestra
-- ferma dall'ultimo giro: una finestra trascinata in quel momento si muove,
-- e non le si fa la guerra mentre la si sposta.
local function zeta_guarda_tutte(stretto)
    local viste = {}
    for _, w in ipairs(hl.get_windows()) do
        if zeta_da_guardare(w) then
            local addr = w.address
            viste[addr] = true
            local firma = string.format("%d,%d,%d,%d", w.at.x, w.at.y, w.size.x, w.size.y)
            if stretto or zg_ultimo[addr] == firma then
                zeta_sistema(w, stretto)
            end
            zg_ultimo[addr] = firma
        end
    end
    for addr in pairs(zg_ultimo) do
        if not viste[addr] then
            zg_ultimo[addr] = nil; zg_conti[addr] = nil
            zg_chiesto[addr] = nil; zg_minimo[addr] = nil
        end
    end
end

-- Recupero a mano (Super + Maiusc + W, «zeta-finestre recupera», Impostazioni
-- › Schermi): tutte le finestre dentro lo schermo, anche quelle lasciate stare.
function zeta_recupera()
    zg_conti = {}
    zeta_guarda_tutte(true)
end

hl.timer(function() zeta_guarda_tutte(false) end, { timeout = 1500, type = "repeat" })
for _, ev in ipairs({ "monitor.added", "monitor.removed", "monitor.layout_changed" }) do
    hl.on(ev, function()
        hl.timer(function() zg_conti = {}; zeta_guarda_tutte(true) end, { timeout = 600, type = "oneshot" })
    end)
end

hl.on("window.open", function(w)
    -- un programma X11 si sposta spesso subito dopo essersi aperto
    local addr = w.address
    for _, t in ipairs({ 300, 1200 }) do
        hl.timer(function()
            for _, a in ipairs(hl.get_windows()) do
                if a.address == addr and zeta_da_guardare(a) then zeta_sistema(a, true) end
            end
        end, { timeout = t, type = "oneshot" })
    end

    if not w.floating or w.fullscreen ~= 0 or w.class == "" then return end
    for _, p in ipairs(ZETA_NON_ALLARGARE) do
        if w.class:find(p) then return end
    end
    local m = w.monitor
    if not m then return end
    local a = zeta_area(m)
    local mw, mh = a.x1 - a.x0, a.y1 - a.y0
    local W, H = w.size.x, w.size.y
    if W * H >= mw * mh * 0.42 then return end           -- gia' grande
    if W < 560 or H < 380 then return end                -- misura da dialogo
    if not zeta_finestra_principale(w) then return end
    local nw, nh = math.floor(mw * 0.72), math.floor(mh * 0.76)
    -- stesso centro di prima (la regola «center» l'aveva gia' centrata),
    -- dentro l'area utile, con la barra del titolo sotto il bordo
    local nx = math.max(a.x0, math.min(w.at.x - (nw - W) // 2, a.x1 - nw))
    local ny = math.max(a.y0 + ZG_BARRA, math.min(w.at.y - (nh - H) // 2, a.y1 - nh))
    hl.dispatch(hl.dsp.window.resize({ x = nw, y = nh, window = w }))
    hl.dispatch(hl.dsp.window.move({ x = nx, y = ny, window = w }))
end)

hl.window_rule({
    name  = "fix-xwayland-drags",
    match = { class = "^$", title = "^$", xwayland = true, float = true, fullscreen = false, pin = false },
    no_focus = true,
})

-------------------
---- SCORCIATOIE ----
-------------------

local mod = "SUPER"

hl.bind(mod .. " + SUPER_L",     hl.dsp.exec_cmd("zeta-pannello launcher"), { release = true })
hl.bind(mod .. " + SPACE",       hl.dsp.exec_cmd("zeta-pannello launcher"))
hl.bind(mod .. " + S",           hl.dsp.exec_cmd("zeta-pannello cerca"))
-- le app scelte in Impostazioni › App predefinite
hl.bind(mod .. " + RETURN",      hl.dsp.exec_cmd("zeta-predefinita terminale"))
hl.bind(mod .. " + E",           hl.dsp.exec_cmd("zeta-predefinita file"))
hl.bind(mod .. " + B",           hl.dsp.exec_cmd("zeta-predefinita browser"))
hl.bind(mod .. " + I",           hl.dsp.exec_cmd("zeta-impostazioni"))
hl.bind(mod .. " + T",           hl.dsp.exec_cmd("zeta-aspetto cambia-tema"))
hl.bind(mod .. " + Q",           hl.dsp.window.close())
hl.bind(mod .. " + F",           hl.dsp.window.fullscreen())
hl.bind(mod .. " + V",           hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + SHIFT + S",   hl.dsp.exec_cmd("sh -c 'grim -g \"$(slurp)\" - | wl-copy'"))
-- Testo da una zona dello schermo (OCR, in locale), come l'Estrattore di testo
-- di Windows: si seleziona, il testo finisce negli appunti.
hl.bind(mod .. " + SHIFT + T",   hl.dsp.exec_cmd("zeta-testo"))
hl.bind(mod .. " + SHIFT + E",   hl.dsp.exec_cmd("zeta-pannello energia"))
hl.bind(mod .. " + ESCAPE",      hl.dsp.exec_cmd("zeta-pannello energia"))
hl.bind(mod .. " + L",           hl.dsp.exec_cmd("hyprlock"))
hl.bind(mod .. " + A",           hl.dsp.exec_cmd("zeta-pannello controllo"))
hl.bind(mod .. " + W",           hl.dsp.exec_cmd("zeta-finestre"))
-- tutte le finestre di nuovo dentro lo schermo, con i pulsanti a portata
hl.bind(mod .. " + SHIFT + W",   function() zeta_recupera() end)
-- Uscita forzata, come Cmd+Alt+Esc su macOS e Ctrl+Shift+Esc su Windows:
-- serve quando un programma non risponde piu', quindi non passa per il
-- programma bloccato ne' per il suo menu.
-- Ctrl+Alt+Esc: mirino, si clicca la finestra bloccata (sfondo = elenco completo).
-- Ctrl+Maiusc+Esc: emergenza, chiude subito la finestra attiva, senza
-- interfaccia: funziona anche quando un pannello fatica ad aprirsi.
-- NON Ctrl+Alt+Maiusc+Esc: con systemd 257 e' la «Secure Attention Key» di
-- logind, che apre una nuova schermata di accesso (provato: ci si ritrova
-- davanti al login con la sessione ancora aperta dietro).
hl.bind("CTRL + ALT + ESCAPE", hl.dsp.exec_cmd("zeta-finestre scegli"))
hl.bind("CTRL + SHIFT + ESCAPE", hl.dsp.exec_cmd("zeta-finestre attiva"))
-- Ctrl+Alt+Canc: pannello di emergenza (gestione attivita', programma
-- bloccato, terminale, ripristino del desktop, blocco, uscita, riavvio,
-- spegnimento). Lo gestisce Hyprland: un'app bloccata non lo ferma. NON con lo
-- schermo bloccato: dal pannello si apre un terminale, e il blocco va rispettato.
hl.bind("CTRL + ALT + Delete", hl.dsp.exec_cmd("zeta-emergenza"))
hl.bind(mod .. " + H",           hl.dsp.exec_cmd("zeta-finestre minimizza"))

-- Selettore delle app, come Cmd+Tab su macOS ma con Ctrl (va bene su ogni
-- tastiera). Ctrl+Tab apre il selettore ed entra nella submap «zeta-selettore»:
-- li' Tab e Maiusc+Tab scorrono, il rilascio di Ctrl porta in primo piano
-- l'app scelta, Esc annulla, Ctrl+Q chiude l'app scelta. Fuori dalla submap
-- nessun altro tasto cambia. Per cambiare scheda dentro le app (Firefox,
-- terminale, editor) resta Ctrl+PagGiu' / Ctrl+PagSu'.
hl.bind("CTRL + TAB", function()
    hl.dispatch(hl.dsp.exec_cmd("zeta-selettore apri"))
    hl.dispatch(hl.dsp.submap("zeta-selettore"))
end)
hl.bind("CTRL + SHIFT + TAB", function()
    hl.dispatch(hl.dsp.exec_cmd("zeta-selettore apri_indietro"))
    hl.dispatch(hl.dsp.submap("zeta-selettore"))
end)
hl.define_submap("zeta-selettore", function()
    hl.bind("CTRL + TAB",         hl.dsp.exec_cmd("zeta-selettore avanti"),   { repeating = true })
    hl.bind("CTRL + SHIFT + TAB", hl.dsp.exec_cmd("zeta-selettore indietro"), { repeating = true })
    hl.bind("CTRL + Q",           hl.dsp.exec_cmd("zeta-selettore chiudi"))
    for _, tasto in ipairs({ "ESCAPE", "CTRL + ESCAPE", "CTRL + SHIFT + ESCAPE" }) do
        hl.bind(tasto, function()
            hl.dispatch(hl.dsp.exec_cmd("zeta-selettore annulla"))
            hl.dispatch(hl.dsp.submap("reset"))
        end)
    end
    -- rilascio di Ctrl (sinistro o destro): si va all'app scelta
    for _, tasto in ipairs({ "Control_L", "Control_R" }) do
        hl.bind(tasto, function()
            hl.dispatch(hl.dsp.exec_cmd("zeta-selettore attiva"))
            hl.dispatch(hl.dsp.submap("reset"))
        end, { release = true, ignore_mods = true, transparent = true })
    end
end)
hl.bind(mod .. " + M",           hl.dsp.window.fullscreen({ mode = "maximized" }))

hl.bind(mod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mod .. " + down",  hl.dsp.focus({ direction = "down" }))

for i = 1, 3 do
    hl.bind(mod .. " + " .. i,         hl.dsp.focus({ workspace = i }))
    hl.bind(mod .. " + SHIFT + " .. i, hl.dsp.window.move({ workspace = i }))
end

hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd("zeta-volume su"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd("zeta-volume giu"),      { locked = true, repeating = true })
hl.bind("XF86AudioMute",         hl.dsp.exec_cmd("zeta-volume muto"),     { locked = true })
hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd("brightnessctl set 5%+"),                          { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl set 5%-"),                          { locked = true, repeating = true })
