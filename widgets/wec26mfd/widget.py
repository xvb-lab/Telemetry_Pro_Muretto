"""
widgets/wec26mfd/widget.py — WEC MFD Card: la card MULTIFUNZIONE.

Una sola card in stile SimHub/WEC col vestito del team del player:
  pagina 0  LAP TIMING  — posizione, giro live, best, settori colorati,
                          diff con chi sta davanti/dietro
  pagina 1  DATI AUTO   — cornice originale del pack: LAP/ABS/TC/OIL,
                          render 2026 dell'auto esatta, ERS
Si sfoglia con le DORSALI del joypad (LB/RB, via XInput) — gli stessi
tasti con cui giri l'MFD di LMU — o con un click sulla card.
Quando il MURETTO apre la radio, la card diventa la TEAM RADIO del
brand (arte originale) e a fine messaggio torna alla pagina attiva.
"""
import ctypes
import json
import os
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import (QPainter, QColor, QFont, QFontMetricsF,
                           QPixmap, QPainterPath, QLinearGradient,
                           QRadialGradient, QConicalGradient, QPen,
                           QBrush)

from widgets.weconboard.widget import WecOnboardOverlay
from core.paths import USER_DIR
from core import engineer_cfg          # flag auto_pit condiviso col muretto

_ROOT = Path(__file__).parent.parent.parent
_W, _H = 550, 300              # 260 + le due ROW (20+20): i moduli
                               # tengono lo spazio pieno di prima
_NAVY = QColor("#10123E")
_RADIO_SHOW_S = 9.0

# cornici del pack: (classe, brand) -> file
_GT3 = {"Aston Martin": "gt3aston", "Audi": "gt3audi", "BMW": "gt3bmw",
        "Corvette": "gt3corvette", "Lamborghini": "gt3lamborghini",
        "McLaren": "gt3mclaren", "Mercedes-AMG": "gt3mercedes",
        "Porsche": "gt3porsche"}
_HY = {"Alpine": "hypercaralpine", "Aston Martin": "hypercaraston",
       "BMW": "hypercarbmw", "Cadillac": "hypercarcadillac",
       "Lamborghini": "hypercarlamborghini",
       "Porsche": "hypercarporsche"}
_LMP2 = {"Ligier": "lmp2ligier", "Oreca": "lmp2oreca"}
_SLUG = {"Aston Martin": "aston", "BMW": "bmw", "Corvette": "corvette",
         "Lamborghini": "lamborghini", "McLaren": "mclaren",
         "Mercedes-AMG": "mercedes", "Porsche": "porsche",
         "Alpine": "alpine", "Cadillac": "cadillac", "Audi": "audi",
         "Ligier": "ligier", "Oreca": "oreca", "Ferrari": "ferrari",
         "Toyota": "toyota", "Peugeot": "peugeot", "Lexus": "lexus",
         "Ford": "ford", "Genesis": "genesis"}
_RADIO = {"Alpine": "radioalpine.png", "Aston Martin": "radioaston.png",
          "Audi": "radioaudi.png", "BMW": "radiobmw.png",
          "Cadillac": "radiocadillac.png",
          "Corvette": "radiocorvette.png",
          "Lamborghini": "radiolamborghini.png",
          "Ligier": "radioligier.png", "McLaren": "radiomclaren.png",
          "Mercedes-AMG": "radiomercedes.png",
          "Oreca": "radiooreca.png", "Porsche": "radioporsche.png"}

_XI_LB, _XI_RB = 0x0100, 0x0200
_XI_DL, _XI_DR = 0x0004, 0x0008    # croce SINISTRA/DESTRA
_XI_DU, _XI_DD = 0x0001, 0x0002    # croce SU/GIU (valore selezione)


class _XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class _XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong),
                ("Gamepad", _XINPUT_GAMEPAD)]


def _send_scancode(sc):
    """Preme e rilascia un tasto via SCANCODE DirectInput (SendInput):
    LMU legge DirectInput, il virtual-key normale non basta."""
    import ctypes
    from ctypes import wintypes

    class _KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]

    class _IN(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("ki", _KI),
                    ("pad", ctypes.c_ubyte * 8)]

    SCAN, UP = 0x0008, 0x0002
    d = _IN(type=1, ki=_KI(0, sc, SCAN, 0, None))
    u = _IN(type=1, ki=_KI(0, sc, SCAN | UP, 0, None))
    ctypes.windll.user32.SendInput(1, ctypes.byref(d),
                                   ctypes.sizeof(_IN))
    time.sleep(0.02)               # il gioco deve vedere il tasto giu'
    ctypes.windll.user32.SendInput(1, ctypes.byref(u),
                                   ctypes.sizeof(_IN))


def _xinput():
    for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return getattr(ctypes.windll, dll)
        except Exception:
            continue
    return None


def _fmt_t(s, dec=3):
    """secondi -> M:SS.mmm ('-' se non valido)."""
    if not s or s <= 0:
        return "-"
    m = int(s // 60)
    if not dec:
        return "%d:%02d" % (m, int(s - m * 60))
    return "%d:%0*.*f" % (m, dec + 3, dec, s - m * 60)


# MODULI: Mod 1..8, anonimi. Il config "mods" assegna a ogni mod il
# NUMERO di pagina (0 = spento). I painter si chiamano _paint_mod<N>
# e si costruiscono UNO alla volta.


class Wec26MfdOverlay(WecOnboardOverlay):
    KEY = "wec26mfd"
    TITLE = "WEC MFD Card"
    HDR = 46.0                 # altezza riga HEADER (logo|slash|P)
    ROW_T = 20.0               # riga (row) tra header e moduli
    ROW_B = 20.0               # riga (row) sotto i moduli

    def __init__(self):
        self._page = 0     # pagine MODULI: all'avvio sempre la prima
        self._pages = 8        # il ciclo VERO di LMU: 7 pagine + lo
                               # slot "MFD spento" (che qui useremo
                               # per altro) — cosi' restano in sync
        self._laps = 0
        self._run = 1              # RUN corrente (1 = primo stint dal garage)
        self._first_out = False    # prima uscita (garage) gia' avvenuta?
        self._run_out_lap = -1     # giro in cui e' iniziato il run (outlap)
        self._inpit_prev = None    # stato pit precedente, per lo scatto uscita
        self._run_sess = None      # sessione per cui vale il contatore run
        self._sector = 1           # settore corrente: 0=S3, 1=S1, 2=S2
        self._sess_bs = [None, None, None]   # best di settore di SESSIONE (fastest)
        self._in_garage = False    # dentro il box garage (simbolo WEC)
        self._in_pits = False      # in corsia box
        self._pit_state = 0        # 0=none 1=request 2=entering 3=stopped 4=exiting
        self._sess_remain = 0.0    # tempo sessione rimanente (s)
        self._track_temp = 0.0     # temp asfalto (garage)
        self._tt_ref = None        # campione per il trend temp
        self._tt_sample = 0.0
        self._tt_trend = 0         # -1 giu', 0 stabile, +1 su
        self._sess_best_lap = None # miglior giro di SESSIONE (tutti, per magenta)
        self._cls_best_lap = None  # miglior giro di CLASSE (per il delta)
        # ── motore DELTA live (traccia per distanza, stile TinyPedal) ──
        self._lapdist = 0.0
        self._dl_cur = []          # campioni (dist, tempo) del giro corrente
        self._dl_ref = None        # traccia di riferimento (mio best)
        self._dl_ref_time = None
        self._dl_lap = None
        self._prev_sector = None
        self._track = ""           # nome pista (chiave per la traccia delta)
        self._vclass = ""          # classe auto (chiave)
        self._dl_track = None      # pista/classe per cui e' caricata la traccia
        self._freeze_until = 0.0   # tempo settore/giro congelato 5s
        self._freeze_txt = ""
        self._freeze_col = None
        self._delta_txt = ""       # delta live corrente
        self._delta_col = None
        self._lap_aborted = False  # giro buttato (mollato): delta esploso
        self._lap_limits = False   # giro invalidato per track limits (Limits)
        self._sec_col = [None, None, None]   # colore CONGELATO tacca settore
        self._oil = None
        self._abs = None
        self._tc = None
        self._carnum = ""
        self._driver = ""
        self._vmodel = ""
        self._is_gt3 = False
        self._place = 0
        self._best = 0.0
        self._last = 0.0
        self._live = 0.0
        self._bs = (0.0, 0.0, 0.0)     # best S1, S2, S3 (split)
        self._ls = (0.0, 0.0, 0.0)     # last lap S1, S2, S3 (split)
        self._cs = (0.0, 0.0)          # settori del giro CORRENTE
        self._gap_ahead = None
        self._gap_behind = None
        # dati DDU (Mod 1) — None/0 = dato assente, la casella tace
        self._gear = None
        self._gear_old = 0
        self._gear_t0 = 0.0
        self._gear_ref = None
        self._speed = None
        self._water = None
        self._fuel_l = None
        self._fuel_max = 0.0
        self._ve_pct2 = 0.0
        self._bbias = None
        self._brake_in = None
        self._beam = False
        self._compound = ""
        self._press4 = [None] * 4
        self._carc4 = [None] * 4
        self._lap_use = None
        self._pens = 0
        self._pen_txt = "PEN"
        self._finish_t = None
        self._green_t = -99.0
        self._flags9 = {}
        self._rpm = None
        self._crpm = 0.0
        self._erpm = 0.0
        self._maxrpm = 0.0
        self._thr_in = 0.0
        self._tc_on = False
        self._abs_on = False
        self._lico = 0.0
        self._lico_open = False
        self._lico_snd = None
        self._wrot = [0.0] * 4
        self._wrad_f = 0.0
        self._wrad_r = 0.0
        self._wslip = 0.0
        self._shift_peak = 0.0
        self._ign = 1              # chiave: 0=off (schermo spento)
        self._pwr_prev = None      # transizione chiave (anim on/off)
        self._pwr_dir = None
        self._pwr_t0 = 0.0
        self._frame_px = None
        self._frame_name = None
        self._car_px = None
        self._car_name = None
        self._radio = {"t": 0.0, "text": "", "role": ""}
        self._radio_seen = 0.0
        # radio attiva nel menu overlay? (riga Engineer)
        self._radio_en = False
        try:
            self._radio_en = bool((json.loads(
                (USER_DIR / "config.json").read_text(encoding="utf-8"))
                .get("engineer") or {}).get("enabled", False))
        except Exception:
            pass
        self._xi = _xinput()
        self._xi_prev = 0
        # schermata interna PER MOD (croce dx/sx): PERSISTITA su file,
        # ogni mod riparte da dove l'hai lasciata anche dopo il riavvio
        try:
            self._mscreen = {int(k): int(v) for k, v in json.loads(
                (USER_DIR / "wec26mfd_screens.json")
                .read_text(encoding="utf-8")).items()}
        except Exception:
            self._mscreen = {}
        self._MSCREENS = 1         # dash: SOLO la schermata principale
                                   # (la seconda rimossa il 21/07)
        self._ctrl_sel = None      # casella regolazioni selezionata
        self._ctrl_sel_t = 0.0
        # preferenze della card (menu SETTINGS, persistite)
        try:
            self._prefs = json.loads(
                (USER_DIR / "wec26mfd_prefs.json")
                .read_text(encoding="utf-8-sig"))   # tollera il BOM
        except Exception:
            self._prefs = {}
        self._m3_sel = 0           # voce selezionata nel menu Mod 3
        # WEARABLES (sospensioni/aero) per la macchinina MOD 4: corsia
        # lenta dedicata (mai nel thread GUI), come faceva il dashboard v3
        self._wsusp = None
        self._waero = None

        def _wear_loop():
            import json as _js
            import urllib.request as _ur
            import time as _tt
            while True:
                try:
                    req = _ur.Request(
                        "http://localhost:6397/rest/garage/UIScreen"
                        "/RepairAndRefuel",
                        headers={"Accept": "application/json"})
                    with _ur.urlopen(req, timeout=0.4) as r:
                        _dt9 = _js.loads(r.read())
                    _w9 = (_dt9.get("wearables") or {})
                    _su9 = _w9.get("suspension") or []
                    self._wsusp = [float(x) for x in _su9[:4]] \
                        if len(_su9) >= 4 else None
                    _bd9 = _w9.get("body") or {}
                    self._waero = float(_bd9.get("aero", 0.0)) \
                        if "aero" in _bd9 else None
                except Exception:
                    pass
                # STIMA SOSTA (rotta scoperta 23/07 dai binari LMU):
                # tempo pit GIA' scomposto — fuel/ve, tires, brakes,
                # damage, penalties, total. Alimenta il pannello MOD 2.
                try:
                    with _ur.urlopen(_ur.Request(
                            "http://localhost:6397/rest/strategy"
                            "/pitstop-estimate",
                            headers={"Accept": "application/json"}),
                            timeout=0.4) as r:
                        self._pit_est = _js.loads(r.read())
                    self._pit_est_t = _tt.monotonic()
                except Exception:
                    pass
                # durante la sosta il rimanente cala in fretta: poll fitto
                _tt.sleep(1.0 if getattr(self, "_pit_t0", None) is not None
                          else 2.0)
        import threading as _th9
        _th9.Thread(target=_wear_loop, daemon=True).start()
        self._pit_est = None       # stima sosta (dalla corsia lenta sopra)
        self._pit_t0 = None        # inizio sosta (fermo ai box)
        self._pit_run = 0.0        # ultimo tempo sosta corso (per il FATTO)
        self._m2_sel = 0           # voce selezionata nella pagina PIT
        self._auto_pit = False     # AUTO PIT (engineer_cfg): mostrato nel Mod 3
        self._ap_ts = 0.0          # throttle rilettura flag auto_pit/engineer_on
        self._radio_en = False     # RADIO on/off (engineer_on): come riga Radio Options
        try:
            _ec0 = engineer_cfg.load()
            self._auto_pit = bool(_ec0.get("auto_pit", False))
            self._radio_en = bool(_ec0.get("engineer_on", False))
        except Exception:
            pass
        self._pm_items = []
        self._pm_pending = {}      # {nome voce: indice scelto} — protetti finche' LMU conferma
        self._pm_pending_ts = {}   # {nome voce: monotonic dell'ultimo cambio}
        # scancode dei comandi elettronica: letti dal keyboard.json di
        # LMU (bind fantasma scritti dall'app + eventuali bind utente)
        _NAMES = {
            0: ("Increment Motor Map", "Decrement Motor Map"),
            1: ("Traction Control Up", "Traction Control Down"),
            2: ("Traction Control Slip Angle Up",
                "Traction Control Slip Angle Down"),
            3: ("Traction Control 2 Up", "Traction Control 2 Down"),
            4: ("Antilock Brake System Up",
                "Antilock Brake System Down"),
            5: ("Bias Forward", "Bias Rearward"),
            6: ("Inc Front ARB", "Dec Front ARB"),
            7: ("Inc Rear ARB", "Dec Rear ARB"),
            8: ("Brake Migration Forward", "Brake Migration Rearward"),
        }
        self._BIND_NAMES = _NAMES
        self._bind_codes = {}
        try:
            _kb = json.loads(Path(
                r"C:\program files (x86)\steam\steamapps\common"
                r"\Le Mans Ultimate\UserData\player\keyboard.json")
                .read_text(encoding="utf-8")).get("Input") or {}
            for i, (nu, nd) in _NAMES.items():
                if nu in _kb and nd in _kb:
                    self._bind_codes[i] = (int(_kb[nu]), int(_kb[nd]))
        except Exception:
            pass
        super().__init__()
        # pad: poll fitto (le dorsali sono pressioni brevi)
        self._pad_t = QTimer(self)
        self._pad_t.timeout.connect(self._poll_pad)
        self._pad_t.start(30)
        # config LIVE: la card si aggiorna da sola quando il pannello
        # salva (niente sparisci/riappari da riavvio processo)
        self._cfg_mtime = 0.0
        self._cfg_t = QTimer(self)
        self._cfg_t.timeout.connect(self._watch_cfg)
        self._cfg_t.start(700)
        # animazione accensione/spegnimento schermo (solo in transizione)
        self._anim_t = QTimer(self)
        self._anim_t.timeout.connect(self.update)
        self._anim_t.setInterval(16)
        # animazione CAMBIATA (33ms come il WEC 2024 Revs, solo ~1s)
        self._gear_t = QTimer(self)
        self._gear_t.timeout.connect(self.update)
        self._gear_t.setInterval(33)
        # dash FLUIDA: repaint costante a 33ms (come il Revs), sempre
        self._fluid_t = QTimer(self)
        self._fluid_t.timeout.connect(self._fast_tick)
        self._fluid_t.start(33)
        # tabella VE del pit menu su THREAD: MAI REST nel filo grafico
        # (era il singhiozzo ogni 5s). Aggiorna self._pl_menu da solo.
        import threading

        def _plm_loop():
            import urllib.request as _ur
            while True:
                try:
                    req = _ur.Request(
                        "http://localhost:6397/rest/garage"
                        "/PitMenu/receivePitMenu",
                        headers={"Accept": "application/json"})
                    dd = json.loads(_ur.urlopen(req,
                                                timeout=1.5).read())
                    best = None
                    for it in (dd if isinstance(dd, list) else []):
                        if str((it or {}).get("name") or "").startswith(
                                "VIRTUAL ENERGY"):
                            for op in (it.get("settings") or []):
                                m = re.match(
                                    r"(\d+)%\s+(\d+)\s+laps",
                                    str((op or {}).get("text") or ""))
                                if m and int(m.group(2)) > 0:
                                    c = (int(m.group(1)),
                                         int(m.group(2)))
                                    if best is None or c[0] > best[0]:
                                        best = c
                    if best:
                        self._pl_menu = best[0] / float(best[1])
                    # ANTI-RIMBALZO: finche' LMU non CONFERMA la mia
                    # scelta, tengo il mio valore (mai il vecchio del
                    # gioco nel frattempo). Confermato -> mollo.
                    pend = getattr(self, "_pm_pending", None) or {}
                    pts = getattr(self, "_pm_pending_ts", None)
                    if pts is None:
                        pts = self._pm_pending_ts = {}
                    if pend:
                        _now2 = time.monotonic()
                        for it2 in (dd if isinstance(dd, list)
                                    else []):
                            n2 = str((it2 or {}).get("name") or "")
                            if n2 in pend:
                                if int(it2.get("currentSetting")
                                       or 0) == pend[n2]:
                                    pend.pop(n2, None)   # LMU conferma
                                    pts.pop(n2, None)
                                elif (_now2 - pts.get(n2, 0.0)) > 5.0:
                                    pend.pop(n2, None)   # scaduto: cedo
                                    pts.pop(n2, None)
                                else:
                                    it2["currentSetting"] = pend[n2]  # tengo il mio
                    self._pm_items = dd
                except Exception:
                    pass
                # inventario SLICK ogni ~3s (max / nuove rimaste)
                self._tinv_n = getattr(self, "_tinv_n", 0) + 1
                if self._tinv_n % 15 == 1:
                    try:
                        req2 = _ur.Request(
                            "http://localhost:6397/rest/garage"
                            "/UIScreen/TireManagement",
                            headers={"Accept": "application/json"})
                        tm = json.loads(_ur.urlopen(
                            req2, timeout=1.5).read())
                        inv = (tm.get("tireInventory") or {})
                        self._tyre_max = int(inv.get(
                            "maxAvailableTires") or 0)
                        self._tyre_new_left = int(inv.get(
                            "newTires") or 0)
                    except Exception:
                        pass
                time.sleep(0.2)

        threading.Thread(target=_plm_loop, daemon=True).start()

    def _fast_tick(self):
        """Poll RAPIDO (33ms) dei soli canali vivi del player —
        pedali, giri, velocita' — per la fluidita' da HUD; il resto
        continua ad arrivare dal _read normale."""
        try:
            i = getattr(self, "_pidx", None)
            if i is not None:
                t = self._mem._get_sim().telemetry.telemInfo[i]
                self._thr_in = float(t.mUnfilteredThrottle)
                self._brake_in = float(t.mUnfilteredBrake) * 100.0
                self._rpm = float(t.mEngineRPM)
                lv = t.mLocalVel
                self._speed = (lv.x * lv.x + lv.y * lv.y
                               + lv.z * lv.z) ** 0.5 * 3.6
        except Exception:
            pass
        self.update()

    def _watch_cfg(self):
        try:
            import os
            f = USER_DIR / "config.json"
            mt = os.path.getmtime(f)
            if mt == self._cfg_mtime:
                return
            first = self._cfg_mtime == 0.0
            self._cfg_mtime = mt
            if first:
                return
            _full = json.loads(f.read_text(encoding="utf-8"))
            # NB: RADIO (engineer_on) vive in engineer_cfg.json e viene
            # riletto ogni 1s nel paint. NON sovrascriverlo qui col vecchio
            # config.json/engineer.enabled (flag legacy) -> corrompeva il toggle.
            d = _full.get("wec26mfd") or {}
            tgt = self._config._data.setdefault("wec26mfd", {})
            tgt.update(d)
            self.cfg = self._config.widget("wec26mfd")
            self._apply_scale()
            self.update()
        except Exception:
            pass

    def _apply_scale(self):
        s = float(self.cfg.scale)
        self.setFixedSize(int(_W * s), int(_H * s))
        self.setWindowOpacity(
            max(0.15, float(self.cfg.get("bg_opacity", 100)) / 100.0))

    # ── pad: LB/RB sfogliano le pagine ────────────────────────────────
    def _poll_pad(self):
        if self._xi is None:
            return
        st = _XINPUT_STATE()
        try:
            if self._xi.XInputGetState(0, ctypes.byref(st)) != 0:
                return
        except Exception:
            return
        b = st.Gamepad.wButtons
        prev = self._xi_prev
        self._xi_prev = b
        if self._ign == 0:
            return      # niente corrente: nessun comando, nessun suono
        if (b & _XI_RB) and not (prev & _XI_RB):
            self._page = (self._page + 1) % self._pages
            self._page_beep()
            self.update()
        elif (b & _XI_LB) and not (prev & _XI_LB):
            self._page = (self._page - 1) % self._pages
            self._page_beep()
            self.update()
        # croce dx/sx sulla DASH: selezione delle caselle regolazioni
        # (destra parte da sinistra, sinistra parte da destra)
        elif (b & (_XI_DR | _XI_DL)) and not (prev & (_XI_DR | _XI_DL)):
            act = self._active_mods()
            mod = act[self._page % len(act)] if act else None
            if mod == 1:
                if self._ctrl_sel is None:
                    self._ctrl_sel = 0 if (b & _XI_DR) else 8
                else:
                    self._ctrl_sel = (self._ctrl_sel
                                      + (1 if (b & _XI_DR) else -1)) % 9
                self._ctrl_sel_t = time.monotonic()
                self._page_beep()
                self.update()
            elif mod == 2:
                # dx/sx sulla pagina PIT: cambia il valore della voce
                self._m2_change(1 if (b & _XI_DR) else -1)
                # arma l'auto-repeat da TENUTA (benzina/VE: corsa veloce)
                self._m2h_t0 = time.monotonic()
                self._m2h_last = self._m2h_t0
                self._page_beep()
                self.update()
            elif mod == 3:
                # dx/sx sul menu SETTINGS: cambia il valore della voce
                if self._m3_sel == 0:      # SPEED UNIT
                    cur = self._prefs.get("speed_unit", "KPH")
                    self._prefs["speed_unit"] = \
                        "MPH" if cur == "KPH" else "KPH"
                    self._save_prefs()
                    self._page_beep()
                    self.update()
                elif self._m3_sel == 1:    # ELECTRIC CONTROL
                    if self._prefs.get("electric_control"):
                        self._prefs["electric_control"] = False
                        self._save_prefs()
                    else:
                        # BIND GIA' NEL FILE? Allora il gioco li ha
                        # caricati all'avvio: riattiva il flag SUBITO,
                        # niente scrittura, niente riavvio LMU (23/07)
                        _have = False
                        try:
                            _kb9 = json.loads(Path(
                                r"C:\program files (x86)\steam"
                                r"\steamapps\common\Le Mans Ultimate"
                                r"\UserData\player\keyboard.json")
                                .read_text(encoding="utf-8")) \
                                .get("Input") or {}
                            _have = all(n9 in _kb9 for n9 in (
                                "Increment Motor Map",
                                "Traction Control Up",
                                "Antilock Brake System Up",
                                "Bias Forward", "Inc Front ARB",
                                "Brake Migration Forward"))
                        except Exception:
                            _have = False
                        # LMU acceso? il file bind si scrive SOLO a
                        # gioco chiuso (senno' li butta alla chiusura)
                        _run = False
                        try:
                            import urllib.request as _ur
                            _ur.urlopen("http://localhost:6397"
                                        "/rest/watch/sessionInfo",
                                        timeout=0.3)
                            _run = True
                        except Exception:
                            _run = False
                        if _have:
                            self._prefs["electric_control"] = True
                            self._save_prefs()
                            self._m3_msg = ("ELECTRIC ON (BINDS OK)",
                                            time.monotonic())
                        elif _run:
                            self._m3_msg = ("CLOSE LMU FIRST, "
                                            "THEN ENABLE",
                                            time.monotonic())
                        elif self._write_ghost_binds():
                            self._prefs["electric_control"] = True
                            self._save_prefs()
                            self._m3_msg = ("BINDS WRITTEN - "
                                            "START LMU",
                                            time.monotonic())
                        else:
                            self._m3_msg = ("LMU FILE NOT FOUND",
                                            time.monotonic())
                    self._page_beep()
                    self.update()
                elif self._m3_sel == 2:    # AUTO PIT (auto-fuel del muretto)
                    self._auto_pit = not self._auto_pit
                    self._ap_ts = time.monotonic()
                    try:
                        engineer_cfg.save(auto_pit=self._auto_pit)
                    except Exception:
                        pass
                    self._m3_msg = (("AUTO PIT ON - ENGINEER SETS VE"
                                     if self._auto_pit else "AUTO PIT OFF"),
                                    time.monotonic())
                    self._page_beep()
                    self.update()
                elif self._m3_sel == 3:    # RADIO (engineer_on): come Options
                    self._radio_en = not self._radio_en
                    self._ap_ts = time.monotonic()
                    try:
                        engineer_cfg.save(engineer_on=self._radio_en)
                    except Exception:
                        pass
                    self._m3_msg = (("RADIO ON" if self._radio_en
                                     else "RADIO OFF"), time.monotonic())
                    self._page_beep()
                    self.update()
                elif self._m3_sel == 4:    # TEST MODE (ciclo unico coi minuti)
                    _seq = [(None, 0), ("longrun", 0), ("racesim", 30),
                            ("racesim", 60), ("racesim", 90),
                            ("racesim", 120), ("hotlap", 0)]
                    _cur4 = (getattr(self, "_test_mode", None),
                             getattr(self, "_test_min", 60)
                             if getattr(self, "_test_mode", None)
                             == "racesim" else 0)
                    _i4 = _seq.index(_cur4) if _cur4 in _seq else 0
                    _i4 = (_i4 + (1 if (b & _XI_DR) else -1)) % len(_seq)
                    self._test_mode, _mn4 = _seq[_i4]
                    if self._test_mode == "racesim":
                        self._test_min = _mn4
                        engineer_cfg.save(test_mode=self._test_mode,
                                          test_race_min=_mn4)
                        _lbl4 = "RACE SIM %d MIN" % _mn4
                    else:
                        engineer_cfg.save(test_mode=self._test_mode)
                        _lbl4 = {None: "TEST OFF",
                                 "longrun": "LONG RUN - USES LICO",
                                 "hotlap": "HOTLAP - PUSH!"}[self._test_mode]
                    self._ap_ts = time.monotonic()
                    self._m3_msg = (_lbl4, time.monotonic())
                    self._page_beep()
                    self.update()
                elif self._m3_sel == 6:    # LIGHTS: toggle fari (bind invisibile)
                    if getattr(self, "_prefs", {}).get("electric_control"):
                        _send_scancode(39)     # "Headlights" (DIK ;)
                        self._m3_msg = ("LIGHTS TOGGLE", time.monotonic())
                    else:
                        self._m3_msg = ("ENABLE ELECTRIC CONTROL FIRST",
                                        time.monotonic())
                    self._page_beep()
                    self.update()
                elif self._m3_sel == 7:    # WIPER: velocita' tergi
                    if getattr(self, "_prefs", {}).get("electric_control"):
                        _send_scancode(51 if (b & _XI_DR) else 52)
                        self._m3_msg = ("WIPER %s" %
                                        ("+" if (b & _XI_DR) else "-"),
                                        time.monotonic())
                    else:
                        self._m3_msg = ("ENABLE ELECTRIC CONTROL FIRST",
                                        time.monotonic())
                    self._page_beep()
                    self.update()
                elif self._m3_sel == 8:    # LINGUA dash: EN <-> IT
                    _cl9 = self._prefs.get("dash_lang", "EN")
                    self._prefs["dash_lang"] = \
                        "IT" if _cl9 == "EN" else "EN"
                    self._save_prefs()
                    self._m3_msg = ("LINGUA ITALIANA"
                                    if self._prefs["dash_lang"] == "IT"
                                    else "ENGLISH", time.monotonic())
                    self._page_beep()
                    self.update()
                elif self._m3_sel == 5:    # LICO: risparmio libero (anche gara)
                    _opts6 = [0, 1, 2, 3, 4]
                    _c6 = getattr(self, "_eco_free", 0)
                    _j6 = _opts6.index(_c6) if _c6 in _opts6 else 0
                    _j6 = (_j6 + (1 if (b & _XI_DR) else -1)) % len(_opts6)
                    self._eco_free = _opts6[_j6]
                    engineer_cfg.save(eco_free=self._eco_free)
                    self._ap_ts = time.monotonic()
                    self._m3_msg = (("LICO OFF" if not self._eco_free
                                     else "LICO +%d LAPS" % self._eco_free),
                                    time.monotonic())
                    self._page_beep()
                    self.update()
        # TENUTA dx/sx sulla pagina PIT: auto-repeat che ACCELERA
        # (0.35s di attesa, poi 8/s -> 20/s -> 50/s): i numeri LMU di
        # benzina/energia si impostano senza mitragliare il pad
        elif (b & (_XI_DR | _XI_DL)):
            act = self._active_mods()
            mod = act[self._page % len(act)] if act else None
            if mod == 2 and getattr(self, "_m2h_t0", None) is not None:
                _nowh = time.monotonic()
                _held = _nowh - self._m2h_t0
                if _held > 0.35:
                    _iv = 0.12 if _held < 1.5 else \
                        (0.05 if _held < 3.0 else 0.02)
                    if _nowh - getattr(self, "_m2h_last", 0.0) >= _iv:
                        self._m2h_last = _nowh
                        self._m2_change(1 if (b & _XI_DR) else -1)
                        self.update()
        # croce su/giu: cambio valore della casella selezionata
        elif (b & (_XI_DU | _XI_DD)) and not (prev & (_XI_DU | _XI_DD)):
            act = self._active_mods()
            mod = act[self._page % len(act)] if act else None
            if mod == 2:
                # nella pagina PIT: sposta la voce selezionata
                _nr2 = max(1, len(self._m2_rows()))
                self._m2_sel = (self._m2_sel
                                + (1 if (b & _XI_DD) else -1)) % _nr2
                self._page_beep()
                self.update()
            elif mod == 3:
                # nel menu SETTINGS: sposta la voce selezionata
                self._m3_sel = (self._m3_sel
                                + (1 if (b & _XI_DD) else -1)) % 9
                self._page_beep()
                self.update()
            elif self._ctrl_sel is not None:
                self._ctrl_sel_t = time.monotonic()
                # comando VERO al gioco SOLO con ELECTRIC CONTROL on
                _bc = self._bind_codes.get(self._ctrl_sel)
                if _bc and self._prefs.get("electric_control"):
                    try:
                        _send_scancode(_bc[0] if (b & _XI_DU)
                                       else _bc[1])
                    except Exception:
                        pass
                self.update()

    def _page_beep(self):
        """Beep corto al cambio pagina (assets/pagebeep.wav)."""
        try:
            if getattr(self, "_beep_fx", None) is None:
                from PySide6.QtMultimedia import QSoundEffect
                from PySide6.QtCore import QUrl
                fx = QSoundEffect(self)
                fx.setSource(QUrl.fromLocalFile(
                    str(_ROOT / "assets" / "pagebeep.wav")))
                fx.setVolume(0.55)
                self._beep_fx = fx
            self._beep_fx.play()
        except Exception:
            pass

    def mousePressEvent(self, e):
        from core.utils import overlays_locked
        if not overlays_locked() and e.button() == Qt.RightButton:
            self._page = (self._page + 1) % self._pages
            self._page_beep()
            self.update()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        # click (non-drag) sul box header -> apre/chiude come la onboard
        moved = self._drag_pos is not None and \
            (e.globalPosition().toPoint()
             - (self._drag_pos + self.frameGeometry().topLeft())
             ).manhattanLength() > 4
        super().mouseReleaseEvent(e)
        if not moved and e.button() == Qt.LeftButton and self.width() > 0:
            sx = self.width() / float(_W)
            sy = self.height() / float(_H)
            px = e.position().x() / sx if sx else 0.0
            py = e.position().y() / sy if sy else 0.0
            if 0 <= py <= self.HDR and px >= getattr(self, "_hdr_bx0", 1e9):
                self._hdr_forced = not getattr(self, "_hdr_open_now", True)
                self.update()

    # ── dati ──────────────────────────────────────────────────────────
    def _read(self):
        ok = super()._read()
        if not ok:
            return ok
        try:
            sim = self._mem._get_sim()
            from pyLMUSharedMemory.lmu_data import \
                MAX_MAPPED_VEHICLES as _MX
            num = int(sim.scoring.scoringInfo.mNumVehicles)
            cur_et = float(sim.scoring.scoringInfo.mCurrentET)
            try:
                self._track = bytes(sim.scoring.scoringInfo.mTrackName) \
                    .split(b"\x00")[0].decode("utf-8", "ignore").strip()
            except Exception:
                self._track = ""
            try:
                self._track_len = float(sim.scoring.scoringInfo.mLapDist)
            except Exception:
                self._track_len = 0.0
            try:
                self._sess_id = int(sim.scoring.scoringInfo.mSession)
            except Exception:
                self._sess_id = 0
            try:
                _end = float(sim.scoring.scoringInfo.mEndET)
                self._sess_remain = max(0.0, _end - cur_et) \
                    if _end > 0 else 0.0
            except Exception:
                self._sess_remain = 0.0
            # MILESTONE tempo sessione (long run): al passaggio di
            # 60/30/15/10/5/1 minuti la casella tempo mostra il residuo 5s
            try:
                _prev_rem = getattr(self, "_rem_prev", None)
                self._rem_prev = self._sess_remain
                if _prev_rem and self._sess_remain > 0 \
                        and _prev_rem > self._sess_remain:
                    for _ms in (3600.0, 1800.0, 900.0, 600.0,
                                300.0, 60.0):
                        if _prev_rem > _ms >= self._sess_remain:
                            self._sess_flash_t = time.monotonic()
                            self._sess_flash_v = _ms
                            break
            except Exception:
                pass
            try:
                self._track_temp = float(sim.scoring.scoringInfo.mTrackTemp)
            except Exception:
                self._track_temp = 0.0
            _tn = time.monotonic()          # trend temp asfalto (campione 6s)
            if _tn - self._tt_sample > 6.0:
                if self._tt_ref is not None:
                    _dd = self._track_temp - self._tt_ref
                    # STICKY: su/giu' appena si muove (0.05°), se stabile
                    # tiene l'ULTIMA direzione (triangolo sempre visibile)
                    self._tt_trend = 1 if _dd > 0.05 else \
                        (-1 if _dd < -0.05 else self._tt_trend)
                self._tt_ref = self._track_temp
                self._tt_sample = _tn
            try:
                self._sess_type = int(sim.scoring.scoringInfo.mSession)
            except Exception:
                self._sess_type = 0
            # SESSIONE NUOVA = cambia il tipo OPPURE il tempo di sessione
            # (mCurrentET) TORNA INDIETRO (pratica->pratica ha lo stesso tipo:
            # il tempo che riparte da ~0 e' l'unico segnale affidabile).
            _sess_new = (self._sess_type != self._run_sess
                         or cur_et < getattr(self, "_prev_cur_et", 0.0) - 5.0)
            self._prev_cur_et = cur_et
            if _sess_new:
                self._run_sess = self._sess_type      # nuova sessione: azzera run
                self._run = 1
                self._first_out = False
                self._inpit_prev = None
                self._run_out_lap = -1
                self._dl_ref = None                   # delta: riparte da questa sessione
                self._dl_ref_time = None
                self._dl_cur = []
                self._dl_ref_time = None
                self._dl_lap = None
            pid = None
            _ovr = 0
            _pcc = b""
            for i in range(min(num, _MX)):
                v = sim.scoring.vehScoringInfo[i]
                if v.mIsPlayer:
                    pid = int(v.mID)
                    self._laps = int(v.mTotalLaps)
                    # RUN: scatto uscita box (in pit -> in pista) = nuovo run
                    _inpit = bool(int(getattr(v, "mInPits", 0)))
                    _ingar = bool(int(getattr(v, "mInGarageStall", 0)))
                    _off = _inpit or _ingar          # fermo: garage o corsia box
                    if self._inpit_prev is None:
                        self._inpit_prev = _off
                    elif self._inpit_prev and not _off:   # garage/pit -> IN PISTA
                        if self._first_out:               # non la 1a (garage)
                            self._run += 1                # box successivo = nuovo run
                        self._first_out = True
                        self._run_out_lap = self._laps    # inizia l'outlap
                    self._inpit_prev = _off
                    self._in_pits = _inpit
                    self._in_garage = _ingar
                    _ps_prev = self._pit_state
                    self._pit_state = int(getattr(v, "mPitState", 0))
                    # RICHIESTA BOX (tasto pit o chiamata gioco): mPitState
                    # passa a 1 -> apri da solo la pagina PIT (MOD 2). Solo sul
                    # FRONTE, cosi' dopo puoi navigare altrove liberamente.
                    if self._pit_state == 1 and _ps_prev != 1:
                        try:
                            _am = self._active_mods()
                            if 2 in _am:
                                self._page = _am.index(2)
                        except Exception:
                            pass
                    _ovr = int(v.mPlace)
                    try:
                        _pcc = bytes(v.mVehicleClass).split(b"\x00")[0]
                    except Exception:
                        _pcc = b""
                    self._vclass = _pcc.decode("utf-8", "ignore")
                    self._best = float(v.mBestLapTime)
                    self._last = float(v.mLastLapTime)
                    _ls1 = float(v.mLastSector1)
                    _ls2 = float(v.mLastSector2)
                    self._ls = (_ls1,
                                _ls2 - _ls1 if _ls2 > 0 and _ls1 > 0
                                else 0.0,
                                self._last - _ls2 if self._last > 0
                                and _ls2 > 0 else 0.0)
                    _bs1 = float(v.mBestSector1)
                    _bs2 = float(v.mBestSector2)
                    self._bs = (_bs1,
                                _bs2 - _bs1 if _bs2 > 0 and _bs1 > 0
                                else 0.0,
                                self._best - _bs2 if self._best > 0
                                and _bs2 > 0 else 0.0)
                    _cs1 = float(v.mCurSector1)
                    _cs2 = float(v.mCurSector2)
                    self._cs = (_cs1, _cs2 - _cs1 if _cs2 > 0
                                and _cs1 > 0 else 0.0)
                    self._sector = int(getattr(v, "mSector", 1))
                    _lst = float(v.mLapStartET)
                    self._live = max(0.0, cur_et - _lst) \
                        if _lst > 0 else 0.0
                    dn = bytes(v.mDriverName).split(b"\x00")[0] \
                        .decode("utf-8", "ignore").strip()
                    if dn:
                        _pp = dn.split()
                        self._driver = (_pp[0][0] + ". "
                                        + " ".join(_pp[1:])) \
                            if len(_pp) >= 2 else dn
                    vn = bytes(v.mVehicleName).split(b"\x00")[0] \
                        .decode("utf-8", "ignore")
                    m = re.search(r"#\s*(\d+)", vn)
                    if m:
                        self._carnum = m.group(1)
                    _vm0 = re.sub(r"#\s*\d+", "", vn)
                    _vm0 = re.sub(r"\s*:\s*\w+\s*$", "", _vm0)   # toglie ":WEC" finale
                    self._vmodel = _vm0.strip()
                    self._is_gt3 = "GT3" in vn.upper()
                    try:
                        self._cls_name = bytes(v.mVehicleClass) \
                            .split(b"\x00")[0].decode("utf-8", "ignore")
                    except Exception:
                        self._cls_name = ""
                    try:
                        self._pits9 = int(getattr(v, "mNumPitstops", 0)
                                          or 0)
                    except Exception:
                        self._pits9 = 0
                    break
            # posizione DI CLASSE: quanti della mia classe davanti +1
            if pid is not None and _ovr > 0:
                if _pcc:
                    _cnt = 0
                    for i in range(min(num, _MX)):
                        v2 = sim.scoring.vehScoringInfo[i]
                        try:
                            _cc2 = bytes(v2.mVehicleClass) \
                                .split(b"\x00")[0]
                        except Exception:
                            continue
                        if _cc2 == _pcc and int(v2.mPlace) < _ovr:
                            _cnt += 1
                    self._place = _cnt + 1
                else:
                    self._place = _ovr
            # BEST DI SETTORE + BEST GIRO DI SESSIONE della MIA CLASSE:
            # magenta e delta si riferiscono a questi (multiclass: una classe
            # piu' veloce NON deve rubare il fuxia alla tua pole di classe)
            _sbs = [None, None, None]
            _sbl = None
            _cbl = None
            for i in range(min(num, _MX)):
                v3 = sim.scoring.vehScoringInfo[i]
                try:
                    _b1 = float(v3.mBestSector1)
                    _b2 = float(v3.mBestSector2)
                    _bl = float(v3.mBestLapTime)
                except Exception:
                    continue
                try:
                    _cc3 = bytes(v3.mVehicleClass).split(b"\x00")[0]
                except Exception:
                    _cc3 = b""
                _same3 = (not _pcc) or (_cc3 == _pcc)   # solo la MIA classe
                if _bl and _bl > 0:
                    if _same3 and (_sbl is None or _bl < _sbl):
                        _sbl = _bl
                    if _pcc and _cc3 == _pcc and (_cbl is None or _bl < _cbl):
                        _cbl = _bl        # best giro della MIA classe
                if not _same3:
                    continue              # settori: solo la mia classe
                _sp = (_b1 if _b1 > 0 else None,
                       (_b2 - _b1) if _b2 > 0 and _b1 > 0 else None,
                       (_bl - _b2) if _bl > 0 and _b2 > 0 else None)
                for _si in range(3):
                    _tt = _sp[_si]
                    if _tt and _tt > 0 and (_sbs[_si] is None
                                            or _tt < _sbs[_si]):
                        _sbs[_si] = _tt
            self._sess_bs = _sbs
            self._sess_best_lap = _sbl
            self._cls_best_lap = _cbl
            if pid is not None:
                try:
                    self._update_delta(v)      # delta live + freeze settori
                except Exception:
                    pass
            for i in range(min(num, _MX)):
                t = sim.telemetry.telemInfo[i]
                if pid is not None and int(t.mID) == pid:
                    try:
                        self._oil = float(t.mEngineOilTemp)
                    except Exception:
                        self._oil = None
                    try:                       # danno serio (dent >= 2)
                        self._dmg_sev = any(
                            int(t.mDentSeverity[_di]) >= 2
                            for _di in range(8))
                    except Exception:
                        self._dmg_sev = False
                    # DAMAGE = COMBO RITIRO (come il muretto): danno serio
                    # + motore MORTO per 10s in pista. Riarma se riparte.
                    _dead9 = (self._dmg_sev and (self._rpm or 0.0) < 100.0
                              and not self._in_garage)
                    if _dead9:
                        if getattr(self, "_dmg_t0", None) is None:
                            self._dmg_t0 = time.monotonic()
                        elif time.monotonic() - self._dmg_t0 >= 10.0:
                            self._dmg_dead = True
                    else:
                        self._dmg_t0 = None
                        if (self._rpm or 0.0) > 300.0:
                            self._dmg_dead = False   # e' ripartita
                    try:
                        self._abs = int(t.mABS) \
                            if int(t.mABSMax) > 0 else None
                    except Exception:
                        self._abs = None
                    try:
                        self._tc = int(t.mTC) \
                            if int(t.mTCMax) > 0 else None
                    except Exception:
                        self._tc = None
                    try:
                        ga = float(t.mTimeGapCarAhead)
                        gb = float(t.mTimeGapCarBehind)
                        self._gap_ahead = ga if 0 < ga < 900 else None
                        self._gap_behind = gb if 0 < gb < 900 else None
                    except Exception:
                        self._gap_ahead = self._gap_behind = None
                    self._pidx = i        # indice per il poll rapido
                    self._pens = int(v.mNumPenalties)
                    try:
                        if int(getattr(v, "mFinishStatus", 0)) == 1 \
                                and not self._finish_t:
                            self._finish_t = time.monotonic()
                    except Exception:
                        pass
                    # ── dati DDU (Mod 1) ──
                    try:
                        self._gear = int(t.mGear)
                        lv = t.mLocalVel
                        self._speed = (lv.x * lv.x + lv.y * lv.y
                                       + lv.z * lv.z) ** 0.5 * 3.6
                        self._water = float(t.mEngineWaterTemp)
                        self._overheat = bool(t.mOverheating)
                        self._fuel_l = float(t.mFuel)
                        self._fuel_max = float(t.mFuelCapacity)
                        # NB: _ve_pct, NON _ve — la classe base usa
                        # gia' self._ve in FRAZIONE e ce lo
                        # sovrascriveva (flash FUEL del 21/07)
                        self._ve_pct2 = float(t.mVirtualEnergy) * 100.0
                        self._bbias = (1.0 - float(t.mRearBrakeBias)) \
                            * 100.0
                        # regolazioni (MapBar del vecchio HUD)
                        self._mmap = int(t.mMotorMap)
                        self._tcslip = int(t.mTCSlip)
                        self._tccut = int(t.mTCCut)
                        self._arbf = int(t.mFrontAntiSway)
                        self._arbr = int(t.mRearAntiSway)
                        self._mig = int(t.mMigration)
                        self._brake_in = float(t.mUnfilteredBrake) * 100.0
                        self._beam = bool(t.mHeadlights)
                        self._compound = bytes(t.mFrontTireCompoundName) \
                            .split(b"\x00")[0].decode("utf-8",
                                                      "ignore").strip()
                        self._press4 = [float(t.mWheels[k].mPressure)
                                        for k in range(4)]
                        # carcassa in KELVIN nella shm: -> gradi C
                        self._carc4 = [float(
                            t.mWheels[k].mTireCarcassTemperature)
                            - 273.15 for k in range(4)]
                        self._brk4 = [float(t.mWheels[k].mBrakeTemp)
                                      - 273.15 for k in range(4)]
                        # INNER layer (media 3 zone): lo strato di
                        # riferimento per la temperatura di lavoro gomma
                        self._inn4 = [sum(
                            float(t.mWheels[k].mTireInnerLayerTemperature[j])
                            - 273.15 for j in range(3)) / 3.0
                            for k in range(4)]
                        self._wear4 = [float(t.mWheels[k].mWear)
                                       for k in range(4)]
                        # DANNI diretti (letture proprie: mai dipendere
                        # dal blocco car_d per gomme/danni della MOD 4)
                        self._dent8 = [int(x) for x in t.mDentSeverity]
                        self._det_part = bool(t.mDetached)
                        self._flat4 = [bool(t.mWheels[k].mFlat)
                                       for k in range(4)]
                        self._det4 = [bool(t.mWheels[k].mDetached)
                                      for k in range(4)]
                        self._comp4 = [int(t.mWheels[k].mCompoundType)
                                       for k in range(4)]
                        self._comp_rr = bytes(t.mRearTireCompoundName) \
                            .split(b"\x00")[0].decode("utf-8",
                                                      "ignore").strip()
                        self._wiper9 = int(getattr(t, "mWiperState", 0) or 0)
                        # HAZARD: fermo in pista >5s — ANCHE a motore
                        # spento (in panne le frecce servono); mai in garage
                        try:
                            _spd0 = (self._speed or 0.0)
                            if _spd0 < 0.5                                     and not getattr(self, "_in_garage",
                                                    False):
                                if getattr(self, "_stop_t0", None) is None:
                                    self._stop_t0 = time.monotonic()
                            else:
                                self._stop_t0 = None
                            self._hazard9 = (
                                getattr(self, "_stop_t0", None) is not None
                                and time.monotonic() - self._stop_t0 > 5.0)
                        except Exception:
                            self._hazard9 = False
                        # CRONO SOSTA (MOD 2): parte quando sei FERMO in
                        # corsia box (non in garage), si azzera quando
                        # riparti. Il pannello mostra stima - trascorso.
                        try:
                            if getattr(self, "_in_pits", False) \
                                    and not getattr(self, "_in_garage",
                                                    False) \
                                    and (self._speed or 0.0) < 0.5:
                                if self._pit_t0 is None:
                                    self._pit_t0 = time.monotonic()
                                    # ANCORA: stima fotografata all'arrivo
                                    # (certificata al decimo, test 23/07).
                                    # Da qui scala il NOSTRO orologio:
                                    # un solo countdown fluido, niente
                                    # gradini delle fasi ne' il preventivo
                                    # prossima-sosta che LMU riarma prima
                                    # del via ("manca 13" fantasma).
                                    self._pit_est0 = dict(
                                        self._pit_est or {})
                                    try:
                                        self._pit_total0 = float(
                                            self._pit_est0.get("total")
                                            or 0.0)
                                    except (TypeError, ValueError):
                                        self._pit_total0 = 0.0
                                self._pit_run = (time.monotonic()
                                                 - self._pit_t0)
                                self._pit_mov_t0 = None
                            elif (self._speed or 0.0) > 1.5:
                                # fine sosta SOLO se ti muovi per 2s VERI:
                                # il rilascio dai cric fa un blip di
                                # velocita' che resettava il countdown
                                # (visto nel video test 23/07, t~107)
                                if self._pit_t0 is not None:
                                    if getattr(self, "_pit_mov_t0",
                                               None) is None:
                                        self._pit_mov_t0 = time.monotonic()
                                    elif time.monotonic() \
                                            - self._pit_mov_t0 > 2.0:
                                        self._pit_t0 = None
                                        self._pit_mov_t0 = None
                            else:
                                self._pit_mov_t0 = None
                        except Exception:
                            pass
                        self._batt9 = float(getattr(
                            t, "mBatteryChargeFraction", 0.0) or 0.0)
                        self._emo9 = int(getattr(
                            t, "mElectricBoostMotorState", 0) or 0)
                        self._rpm = float(t.mEngineRPM)
                        self._crpm = float(t.mClutchRPM)
                        self._erpm = float(t.mElectricBoostMotorRPM)
                        self._ign = int(t.mIgnitionStarter)
                        self._limiter = bool(t.mSpeedLimiter)
                        # FARI: lampeggio = 2+ commutazioni in 1.2s
                        try:
                            _bm9 = bool(t.mHeadlights)
                            _bp9 = getattr(self, "_beam_prev", None)
                            if _bp9 is not None and _bm9 != _bp9:
                                _hq = getattr(self, "_beam_tg", None)
                                if _hq is None:
                                    from collections import deque as _dq9
                                    _hq = self._beam_tg = _dq9(maxlen=6)
                                _nwtg = time.monotonic()
                                # inizio di una SEQUENZA di lampeggi:
                                # congela lo stato pre-lampeggio (la spia
                                # verde non deve ballare col toggling)
                                if not _hq or _nwtg - _hq[-1] > 1.2:
                                    self._beam_pre = _bp9
                                _hq.append(_nwtg)
                            self._beam_prev = _bm9
                            _hq = getattr(self, "_beam_tg", None) or []
                            _nw9 = time.monotonic()
                            self._light_flash = len(
                                [x for x in _hq if _nw9 - x < 1.2]) >= 2
                            # stato FISSO (debounce 1.2s): comanda spia
                            # verde e retroilluminazione — i lampeggi,
                            # primo tocco compreso, non lo toccano MAI
                            if _bm9 != getattr(self, "_beam_raw_prev",
                                               None):
                                self._beam_chg_t = _nw9
                            self._beam_raw_prev = _bm9
                            if _nw9 - getattr(self, "_beam_chg_t",
                                              0.0) >= 1.2:
                                self._beam_steady = _bm9
                        except Exception:
                            self._light_flash = False
                        # dati MACCHININA (MOD 4)
                        try:
                            self._car_d = {
                                "tires": self._carc4,
                                "tyre_surf": [[float(t.mWheels[i2]
                                               .mTemperature[j2]) - 273.15
                                               for j2 in range(3)]
                                              for i2 in range(4)],
                                "tyre_flat": [bool(t.mWheels[i2].mFlat)
                                              for i2 in range(4)],
                                "tyre_detached": [bool(t.mWheels[i2].mDetached)
                                                  for i2 in range(4)],
                                "body_dent": [int(x2) for x2
                                              in t.mDentSeverity],
                                "detached": bool(t.mDetached),
                                "water_temp": self._water,
                                "oil_temp": self._oil,
                                "headlights": bool(t.mHeadlights),
                                "light_flash": getattr(self, "_light_flash",
                                                       False),
                                "pit_limiter": self._limiter,
                                "brake": float(t.mUnfilteredBrake),
                                "car_class": getattr(self, "_cls_name", "")
                                or ("GT3" if getattr(self, "_is_gt3", False)
                                    else ""),
                                "comp4": [int(t.mWheels[i2].mCompoundType)
                                          for i2 in range(4)],
                            }
                        except Exception:
                            pass
                        # effetto cambiata (dal WEC 2024 Revs) —
                        # memoria PROPRIA: self._gear e' gia'
                        # aggiornato in questa stessa lettura
                        _g9 = int(t.mGear)
                        _gp = getattr(self, "_gear_prev", None)
                        if _gp is None or _g9 != _gp:
                            if _g9 != 0 and self._gear_ref is not None \
                                    and _g9 != self._gear_ref:
                                self._gear_old = self._gear_ref
                                self._gear_t0 = time.monotonic()
                                self._gear_t.start()
                            if _g9 != 0:
                                self._gear_ref = _g9
                        self._gear_prev = _g9
                        # fila RPM/LED (dalla vecchia dashboard)
                        self._maxrpm = float(t.mEngineMaxRPM)
                        self._thr_in = float(t.mUnfilteredThrottle)
                        self._tc_on = bool(getattr(t, "mTCActive", 0))
                        self._abs_on = bool(getattr(t, "mABSActive", 0))
                        try:
                            self._lico = float(
                                t.mLiftAndCoastProgress) / 255.0
                        except Exception:
                            self._lico = 0.0
                        self._wrot = [abs(float(t.mWheels[k].mRotation))
                                      for k in range(4)]
                        # slittamento alla TINYPEDAL: raggio APPRESO
                        # (EMA in rilascio) e slip = rot*r/v - 1
                        try:
                            v_ms = (self._speed or 0.0) / 3.6
                            raf = (self._wrot[0] + self._wrot[1]) / 2.0
                            rar = (self._wrot[2] + self._wrot[3]) / 2.0
                            if v_ms > 3.0 and self._thr_in < 0.2 \
                                    and (self._brake_in or 0.0) < 8.0:
                                if raf > 1.0:
                                    self._wrad_f += \
                                        (v_ms / raf - self._wrad_f) \
                                        * 0.05
                                if rar > 1.0:
                                    self._wrad_r += \
                                        (v_ms / rar - self._wrad_r) \
                                        * 0.05
                            _sl = 0.0
                            if v_ms > 1.0:
                                if self._wrad_f > 0:
                                    _sl = max(
                                        _sl,
                                        self._wrot[0] * self._wrad_f
                                        / v_ms - 1.0,
                                        self._wrot[1] * self._wrad_f
                                        / v_ms - 1.0)
                                if self._wrad_r > 0:
                                    _sl = max(
                                        _sl,
                                        self._wrot[2] * self._wrad_r
                                        / v_ms - 1.0,
                                        self._wrot[3] * self._wrad_r
                                        / v_ms - 1.0)
                            self._wslip = _sl
                        except Exception:
                            self._wslip = 0.0
                    except Exception:
                        pass
                    break
            # consumo ULTIMO GIRO (DDU): delta del carico al cambio giro
            try:
                _cur = self._ve_pct2 if self._ve_pct2 > 0 \
                    else self._fuel_l
                if self._laps != getattr(self, "_lu_lap", None):
                    _v0 = getattr(self, "_lu_start", None)
                    if _v0 is not None and _cur is not None \
                            and _v0 > _cur:
                        self._lap_use = _v0 - _cur
                    self._lu_lap = self._laps
                    self._lu_start = _cur
            except Exception:
                pass
        except Exception:
            pass
        # beep LIFT & COAST (assets/lift.wav) all'apertura della zona
        # — vale per il lico NATIVO e per il NOSTRO (stesso suono,
        # stessa soglia: mai due comportamenti diversi)
        try:
            _leff = self._lico
            if _leff < 0.015:
                try:
                    _own9 = self._eco_lift_frac()
                    if _own9 is not None:
                        _leff = _own9
                except Exception:
                    pass
            self._lico_eff = _leff
            if _leff < 0.015:
                self._lico_open = False
            elif _leff >= 0.03 and not self._lico_open:
                self._lico_open = True
                if self._lico_snd is None:
                    from PySide6.QtMultimedia import QSoundEffect
                    from PySide6.QtCore import QUrl
                    _pw = _ROOT / "assets" / "lift.wav"
                    if _pw.is_file():
                        fx = QSoundEffect(self)
                        fx.setSource(QUrl.fromLocalFile(str(_pw)))
                        fx.setVolume(0.9)
                        self._lico_snd = fx
                    else:
                        self._lico_snd = False
                if self._lico_snd:
                    self._lico_snd.play()
        except Exception:
            pass
        # bandiere: il FlagReader COLLAUDATO del widget Flag
        # (gialla coi metri, blu con la classe, penalita', scacchi)
        try:
            if not hasattr(self, "_flagr"):
                from widgets.flag.reader import FlagReader
                self._flagr = FlagReader()
            self._flags9 = self._flagr.read() or {}
        except Exception:
            self._flags9 = {}
        try:
            _si9 = self._mem._get_sim().scoring.scoringInfo
            _gp = int(_si9.mGamePhase)
            self._game_phase = _gp        # per PIT CLOSED (quali/prova)
            # GOMMATURA pista 0-4 (mTrackGripLevel) + trend STICKY
            _tg9 = int(getattr(_si9, "mTrackGripLevel", 0) or 0)
            _pg9 = getattr(self, "_track_grip", None)
            if _pg9 is not None and _tg9 != _pg9:
                self._tg_trend = 1 if _tg9 > _pg9 else -1
            self._track_grip = _tg9
            if _gp == 5 and getattr(self, "_gp_prev", None) != 5:
                self._green_t = time.monotonic()
            self._gp_prev = _gp
        except Exception:
            pass
        # WET del meteo (come il widget Flag): allo scatto parte
        # la finestra dei 10 secondi
        try:
            _wn = bool((self._mem.get_weather() or {}).get("wet"))
            if _wn and not getattr(self, "_wet_prev", False):
                self._wet_t = time.monotonic()
            self._wet_prev = _wn
        except Exception:
            pass
        # testo penalita' (SG/DT/+s) dal race control, throttle 2s
        try:
            if (self._flags9.get("num_penalties") or 0) > 0:
                _nowp9 = time.monotonic()
                if _nowp9 - getattr(self, "_pen_ts", 0.0) > 2.0:
                    self._pen_ts = _nowp9
                    from core.race_control import latest_penalty_parts
                    _pt, _pk, _pr, _pl = latest_penalty_parts()
                    k = (_pk or "").upper()
                    _dig = "".join(c for c in k if c.isdigit())
                    if "DRIVE" in k:
                        self._pen_txt = "DT"
                    elif "STOP" in k:
                        self._pen_txt = "SG"
                    elif k.startswith("+"):
                        self._pen_txt = "%s+" % _dig if _dig else "PEN"
                    else:
                        self._pen_txt = "PEN"
        except Exception:
            pass
        # stato TELEMETRIA (file del recorder, letto max 1 volta/s)
        try:
            _nowt = time.monotonic()
            if _nowt - getattr(self, "_trec_ts", 0.0) >= 1.0:
                self._trec_ts = _nowt
                self._tele_rec = bool(json.loads(
                    (USER_DIR / "telemetry_state.json")
                    .read_text(encoding="utf-8")).get("rec", False))
        except Exception:
            pass
        # radio del muretto: takeover per _RADIO_SHOW_S
        try:
            d = json.loads((USER_DIR / "team_radio.json")
                           .read_text(encoding="utf-8"))
            t = float(d.get("t") or 0.0)
            if t and t != self._radio_seen and (d.get("text") or "").strip():
                self._radio_seen = t
                self._radio = {"t": t, "text": d["text"].strip(),
                               "role": d.get("role") or ""}
                self._radio_on_t = time.monotonic()
                self._radio_end_t = None      # parlato in corso
            _e = float(d.get("end") or 0.0)
            if _e and _e != getattr(self, "_radio_end_seen", None):
                self._radio_end_seen = _e
                self._radio_end_t = time.monotonic()
        except Exception:
            pass
        return ok

    # ── asset ─────────────────────────────────────────────────────────
    def _frame(self):
        table = _GT3 if self._is_gt3 else _HY
        fn = table.get(self._brand) or _LMP2.get(self._brand)
        if fn != self._frame_name:
            self._frame_name = fn
            self._frame_px = None
            if fn:
                pth = _ROOT / "assets" / "mfd" / (fn + ".png")
                if pth.exists():
                    px = QPixmap(str(pth))
                    self._frame_px = px if not px.isNull() else None
        return self._frame_px

    def _car(self):
        key = (self._carnum, self._brand, self._is_gt3)
        if key == self._car_name:
            return self._car_px
        self._car_name = key
        self._car_px = None
        try:
            files = []
            for sub in ("car-th", "car-th/2025", "car-th/elms"):
                files += sorted((_ROOT / "assets" / sub).glob("*.png"))
            pick = None
            slug = _SLUG.get(self._brand, "")
            want = self._carnum          # ESATTO: "7" != "007"
            for f in files:
                m = re.match(r"20\d\d-\w+-(\d+)-", f.name)
                if not (m and want and m.group(1) == want):
                    continue
                # il numero DEVE stare sulla marca giusta (se nota)
                if slug and slug not in f.name.lower():
                    continue
                pick = f
                break
            if pick is None:
                for f in files:
                    if slug and slug in f.name.lower():
                        if self._is_gt3 and "gt3" not in f.name.lower():
                            continue
                        pick = f
                        break
            if pick is not None:
                px = QPixmap(str(pick))
                self._car_px = px if not px.isNull() else None
        except Exception:
            pass
        return self._car_px

    def _chip(self):
        fn = "lmgt3" if self._is_gt3 else "hypercar"
        pth = _ROOT / "assets" / "mfd" / (fn + ".png")
        if not hasattr(self, "_chip_cache"):
            self._chip_cache = {}
        if fn not in self._chip_cache:
            px = QPixmap(str(pth)) if pth.exists() else QPixmap()
            self._chip_cache[fn] = None if px.isNull() else px
        return self._chip_cache[fn]

    def _radio_art(self):
        fn = _RADIO.get(self._brand)
        if not fn:
            return None
        if fn != getattr(self, "_ra_name", None):
            pth = _ROOT / "assets" / "teamradio" / fn
            px = QPixmap(str(pth)) if pth.exists() else QPixmap()
            self._ra_px = None if px.isNull() else px
            self._ra_name = fn
        return getattr(self, "_ra_px", None)

    def _header_style(self):
        """(bg, fg) testata dal brand (stile card classifiche)."""
        try:
            from core.wec_style import row_color, text_on
            c = row_color(self._brand)
            if c:
                return QColor(c), QColor(text_on(self._brand))
        except Exception:
            pass
        # riserva NEUTRA (navy pannello): niente flash gialli quando
        # il brand non e' ancora noto durante i reload
        return QColor("#312C54"), QColor(255, 255, 255)

    def _sector_states(self):
        """3 stati settore (logica relative): fastest / improved / normal /
        current. Acceso appena il settore chiude nel giro corrente."""
        st = ["", "", ""]
        # giro ABORTITO: tacche neutralizzate finche' non si richiude
        if getattr(self, "_lap_aborted", False):
            return st
        ins = getattr(self, "_sector", 1)          # 0=S3, 1=S1, 2=S2
        if ins != 1:
            self._abort_prev = False   # via dal primo settore: reset flag
        cs = self._cs or (0.0, 0.0)                 # (S1, split S2)
        last = self._ls or (0.0, 0.0, 0.0)
        best = self._bs or (0.0, 0.0, 0.0)
        sbs = getattr(self, "_sess_bs", [None, None, None])

        def _state(t, pb, idx):
            if not t or t <= 0.0:
                return ""
            if sbs[idx] is not None and t <= sbs[idx] + 1e-3:
                return "fastest"       # magenta: best di sessione
            if pb and pb > 0.0 and t <= pb + 1e-3:
                return "improved"      # verde: mio best
            return "normal"            # giallo: piu' lento

        if ins != 1 and len(cs) > 0 and cs[0] > 0:
            st[0] = _state(cs[0], best[0] if len(best) > 0 else -1, 0)
        if ins == 0 and len(cs) > 1 and cs[1] > 0:
            st[1] = _state(cs[1], best[1] if len(best) > 1 else -1, 1)
        if ins == 1 and getattr(self, "_abort_prev", False):
            pass        # il giro prima era buttato: riparti pulito da S1
        elif ins == 1:                  # giro appena chiuso: tutti e 3 dal last
            for si in range(3):
                lt = last[si] if si < len(last) else -1
                if lt and lt > 0:
                    st[si] = _state(lt, best[si] if si < len(best) else -1, si)
        cur_idx = {0: 2, 1: 0, 2: 1}.get(ins, None)
        if cur_idx is not None and not st[cur_idx]:
            st[cur_idx] = "current"
        return st

    @staticmethod
    def _fmt_t(s):
        """Tempo in secondi -> 'sss.mmm' o 'm:ss.mmm'."""
        if not s or s <= 0:
            return "--"
        _m = int(s // 60)
        return "%d:%06.3f" % (_m, s - _m * 60) if _m else "%.3f" % s

    @staticmethod
    def _interp(arr, x):
        """Interpola il tempo alla distanza x nella traccia (dist, tempo)."""
        if not arr:
            return None
        if x <= arr[0][0]:
            return arr[0][1]
        if x >= arr[-1][0]:
            return arr[-1][1]
        for i in range(1, len(arr)):
            if arr[i][0] >= x:
                x0, t0 = arr[i - 1]
                x1, t1 = arr[i]
                if x1 == x0:
                    return t1
                return t0 + (t1 - t0) * (x - x0) / (x1 - x0)
        return arr[-1][1]

    def _dl_path(self):
        """File della traccia delta per pista+classe (persistente tra riavvii)."""
        _t = re.sub(r"[^A-Za-z0-9]+", "_", self._track or "track").strip("_")
        _c = re.sub(r"[^A-Za-z0-9]+", "_", self._vclass or "cls").strip("_")
        _d = USER_DIR / "delta"
        try:
            _d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return _d / ("%s__%s.json" % (_t or "track", _c or "cls"))

    def _dl_load(self):
        """Carica la traccia di riferimento salvata (o azzera se non c'e')."""
        self._dl_ref = None
        self._dl_ref_time = None
        self._dl_cur = []
        try:
            p = self._dl_path()
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                tr = d.get("trace")
                tm = d.get("time")
                if tr and tm and float(tm) > 0:
                    self._dl_ref = [(float(a), float(b)) for a, b in tr]
                    self._dl_ref_time = float(tm)
        except Exception:
            pass

    def _dl_save(self):
        """Salva la traccia di riferimento corrente su file."""
        try:
            if not self._dl_ref or not self._dl_ref_time:
                return
            self._dl_path().write_text(json.dumps({
                "time": self._dl_ref_time,
                "trace": [[round(a, 1), round(b, 3)]
                          for a, b in self._dl_ref],
            }), encoding="utf-8")
        except Exception:
            pass

    _DASH_LOGO = {
        "Cadillac": "cardlogo/Cadillac_white.svg",
        "Peugeot": "brandlogo/Peugeot_white_backup.svg",
        "McLaren": "cardlogo/McLaren.svg",
        "Toyota": "cardlogo/Toyota.svg",
    }
    # ritocchi dimensione SOLO dash (per-brand), non tocca onboard
    _DASH_SCALE = {
        "ginetta": 0.90,
        "Peugeot": 1.10,
    }

    def _car_logo(self):
        """Logo per il dash NERO: 1) mappa esplicita per-brand (_DASH_LOGO),
        2) cardlogo/<brand>_white.svg, 3) brandlogo/ naturali. Cachato."""
        import os
        lp = None
        try:
            from core.wec_style import _ROOT as _WR
            _root = str(_WR)
            _rel = self._DASH_LOGO.get(self._brand)
            if _rel:
                _c = os.path.join(_root, _rel.replace("/", os.sep))
                if os.path.exists(_c):
                    lp = _c
            if lp is None and self._brand:
                _cw = os.path.join(_root, "cardlogo",
                                   "%s_white.svg" % self._brand)
                if os.path.exists(_cw):
                    lp = _cw
        except Exception:
            lp = None
        if lp is None:
            try:
                from core.utils import find_logo_path
                lp = find_logo_path(self._brand)
            except Exception:
                lp = None
        if not lp:
            return None
        lp = str(lp)
        if getattr(self, "_clogo_lp", None) != lp:
            try:
                from PySide6.QtSvg import QSvgRenderer
                self._clogo = QSvgRenderer(lp)
                self._clogo_lp = lp
            except Exception:
                self._clogo = None
        return getattr(self, "_clogo", None)

    def _draw_car_logo(self, p, cx, cy, unit=72.0, opacity=1.0):
        """Logo auto centrato con le PROPORZIONI per-brand ESATTE dell'onboard
        (logo_box unit 72, rect_w 100 -> come wec26board.draw_card_base): stessa
        grandezza e allineamento. Le bianche hanno l'aspect delle sorelle card.
        Ritorna l'altezza."""
        lg = self._car_logo()
        if lg is None:
            return 0.0
        ds = lg.defaultSize()
        vb = lg.viewBoxF()
        if vb.width() > 0:
            ar = vb.height() / vb.width()
        elif ds.width() > 0:
            ar = ds.height() / float(ds.width())
        else:
            return 0.0
        try:
            from core.wec_style import logo_box
            ww, hh, _dy, _adv, _dx = logo_box(self._brand, ar, unit,
                                              rect_w=100.0, surface="onboard")
        except Exception:
            hh = unit
            ww = (unit / ar) if ar else unit
        _sc = self._DASH_SCALE.get(self._brand, 1.0)   # ritocco solo dash
        ww *= _sc
        hh *= _sc
        p.save()
        p.setOpacity(max(0.0, min(1.0, opacity)))
        lg.render(p, QRectF(cx - ww / 2.0, cy - hh / 2.0, ww, hh))
        p.restore()
        return hh

    def _dl_persist(self):
        """Salva il riferimento delta su disco: sopravvive al riavvio
        dell'app nella STESSA sessione LMU (ripristino in _update_delta)."""
        try:
            _fd9 = USER_DIR / "delta"
            _fd9.mkdir(parents=True, exist_ok=True)
            (_fd9 / "session_ref.json").write_text(json.dumps({
                "track": self._track, "vclass": self._vclass,
                "sess_type": getattr(self, "_sess_type", None),
                "remain": float(getattr(self, "_sess_remain", 0.0) or 0.0),
                "wall": time.time(),
                "ref_time": self._dl_ref_time,
                "ref_inv": bool(getattr(self, "_dl_ref_inv", False)),
                "trace": [[round(a, 1), round(b, 3)]
                          for a, b in (self._dl_ref or [])]}))
        except Exception:
            pass

    def _ref_from_db(self, best):
        """RIPESCA dal recorder (.lmtel) la traccia del BEST di sessione
        LMU perso dai riavvii (bug 23/07 secondo atto: LMU migliore
        1:53.203, noi rif. 1:54.0 post-riavvio). Cerca nei log recenti
        un giro con tempo IDENTICO (<6ms) su stessa pista/classe e ne
        ricostruisce (lapdist, t) dai samples. Thread: il risultato va
        in _refdb_out, consumato dal tick GUI."""
        try:
            import sqlite3
            import glob as _gl
            base = os.path.join(os.environ.get("APPDATA", ""),
                                "LMU_TelemetryPro", "logs")
            files = sorted(_gl.glob(os.path.join(base, "*.lmtel")),
                           key=os.path.getmtime, reverse=True)[:14]
            now = time.time()
            for f in files:
                if now - os.path.getmtime(f) > 12 * 3600.0:
                    break                      # troppo vecchio: altra sessione
                try:
                    con = sqlite3.connect(
                        "file:%s?mode=ro" % f.replace("\\", "/"), uri=True)
                except Exception:
                    continue
                try:
                    meta = con.execute("SELECT track, car_class FROM "
                                       "session_meta LIMIT 1").fetchone()
                    if not meta or meta[0] != self._track \
                            or meta[1] != self._vclass:
                        continue
                    row = con.execute(
                        "SELECT lap, lap_time FROM laps WHERE "
                        "ABS(lap_time - ?) < 0.006 LIMIT 1",
                        (best,)).fetchone()
                    if not row:
                        continue
                    smp = con.execute(
                        "SELECT t, lapdist FROM samples WHERE lap=? "
                        "ORDER BY t", (int(row[0]),)).fetchall()
                finally:
                    con.close()
                if len(smp) < 100:
                    continue
                # trace (lapdist, t): salta i campioni pre-traguardo
                # (lapdist ancora alta), poi solo avanzamenti >= 3m
                tr, last, started = [], -1e9, False
                for t9, ld9 in smp:
                    if not started:
                        if ld9 < 200.0:
                            started = True
                        else:
                            continue
                    if ld9 >= last + 3.0:
                        tr.append((float(ld9), float(t9)))
                        last = ld9
                # sanita': copre il giro e finisce vicino al tempo giro
                if len(tr) > 80 and abs(tr[-1][1] - row[1]) < 4.0:
                    self._refdb_out = (tr, float(row[1]))
                    return
        except Exception:
            pass

    def _update_delta(self, v):
        """DELTA live (vs mio best trace, ancorato al best di CLASSE) +
        freeze 5s del tempo di settore/giro alla chiusura."""
        now = time.monotonic()
        self._lapdist = float(getattr(v, "mLapDist", 0.0))
        # TRANSITORIO al traguardo: lapdist gia' a ~0 (nuovo giro) ma _live e'
        # ancora il tempo del giro precedente per un paio di frame. NON va
        # campionato (avvelena il riferimento) ne' usato per il delta.
        _transient = self._lapdist < 150.0 and self._live > 10.0
        # track limits: mCountLapFlag==1 -> giro conta ma NON il tempo
        try:
            _ll_prev = self._lap_limits
            self._lap_limits = (int(getattr(v, "mCountLapFlag", 2)) == 1)
            if self._lap_limits:
                self._lap_was_inv = True          # questo giro NON fara' da ref
                if not _ll_prev:
                    self._inv_t = now             # INVALID: mostrato 5s
        except Exception:
            self._lap_limits = False
        # cambio pista/classe -> AZZERA il riferimento (delta vs best di
        # SESSIONE, come LMU e come le tacche; niente traccia all-time da disco)
        _key = (self._track, self._vclass)
        if _key != self._dl_track:
            self._dl_track = _key
            self._dl_ref = None
            self._dl_ref_time = None
            self._dl_cur = []
            self._dl_restored = False
        # RIPRISTINO rif. dopo RIAVVIO APP a meta' sessione (bug 23/07:
        # LMU ricordava il best 1:53, noi ripartivamo dal primo giro
        # post-riavvio 1:56 -> delta verde bugiardo). Il best salvato su
        # disco torna valido SOLO se e' ancora la stessa sessione LMU:
        # stessa pista/classe/tipo + continuita' del tempo rimanente.
        if self._dl_ref is None and not getattr(self, "_dl_restored", False):
            _rem9 = float(getattr(self, "_sess_remain", 0.0) or 0.0)
            if _rem9 > 0.0:
                self._dl_restored = True          # un tentativo solo, armato
                try:
                    _d9 = json.loads((USER_DIR / "delta"
                                      / "session_ref.json")
                                     .read_text(encoding="utf-8"))
                    _age = time.time() - float(_d9.get("wall") or 0.0)
                    _exp = float(_d9.get("remain") or -1.0) - _age
                    _tr9 = _d9.get("trace") or []
                    if (_d9.get("track") == self._track
                            and _d9.get("vclass") == self._vclass
                            and _d9.get("sess_type")
                            == getattr(self, "_sess_type", None)
                            and 0.0 <= _age < 6.0 * 3600.0
                            and abs(_exp - _rem9) < 180.0
                            and len(_tr9) > 50
                            and float(_d9.get("ref_time") or 0.0) > 10.0):
                        self._dl_ref = [(float(q[0]), float(q[1]))
                                        for q in _tr9]
                        self._dl_ref_time = float(_d9["ref_time"])
                        self._dl_ref_inv = bool(_d9.get("ref_inv"))
                except Exception:
                    pass
        # RIPESCAGGIO dal recorder: se LMU ha un best di sessione
        # migliore del nostro riferimento (riavvii multipli), il giro
        # vero sta nei log — cercalo in un thread (una volta per best)
        try:
            _bst9 = float(self._best or 0.0)
        except (TypeError, ValueError):
            _bst9 = 0.0
        if _bst9 > 10.0 \
                and (self._dl_ref_time is None
                     or self._dl_ref_time > _bst9 + 0.15) \
                and getattr(self, "_refdb_for", None) != _bst9:
            self._refdb_for = _bst9
            import threading as _th9d
            _th9d.Thread(target=self._ref_from_db, args=(_bst9,),
                         daemon=True).start()
        # consumo del risultato (solo se migliora il rif. attuale)
        _cand9 = getattr(self, "_refdb_out", None)
        if _cand9 and (self._dl_ref_time is None
                       or _cand9[1] < self._dl_ref_time - 0.01):
            self._refdb_out = None
            self._dl_ref = _cand9[0]
            self._dl_ref_time = _cand9[1]
            self._dl_ref_inv = False
            self._dl_persist()
        elif _cand9:
            self._refdb_out = None
        _MAG, _GRN, _YEL = (QColor("#ff2bd6"), QColor("#00e676"),
                            QColor("#ffe24d"))          # rosa/verde/giallo WEC

        def _col(t, pb, sb):
            if t and t > 0:
                if sb is not None and t <= sb + 1e-3:
                    return _MAG
                if pb and pb > 0 and t <= pb + 1e-3:
                    return _GRN
            return _YEL

        best = self._bs or (0.0, 0.0, 0.0)
        sbs = self._sess_bs or [None, None, None]
        # ── NUOVO GIRO: valuta il giro chiuso come reference + freeze tempo giro
        if self._laps != self._dl_lap:
            # PROVA DELTA (verifica 23/07, da togliere a collaudo ok): al
            # traguardo il delta mostrato deve convergere a (giro - best).
            try:
                if self._last and self._last > 0:
                    _rt9 = self._dl_ref_time
                    with open(USER_DIR / "delta_check.log", "a",
                              encoding="utf-8") as _fh:
                        if _rt9:
                            _fh.write("lap %d: giro %.3f ref %.3f -> "
                                      "atteso %+.3f | mostrato %s\n" % (
                                          self._laps, self._last, _rt9,
                                          self._last - _rt9,
                                          getattr(self, "_d_final",
                                                  "n/d")))
                        else:
                            _fh.write("lap %d: giro %.3f ref N/D "
                                      "(nessun riferimento!)\n"
                                      % (self._laps, self._last))
            except Exception:
                pass
            if self._lap_aborted:            # giro CHIUSO era buttato -> nuovo RUN
                self._abort_prev = True      # tacche: riparti pulito da S1
                self._run += 1
            self._lap_aborted = False
            # COOL-DOWN: se il giro appena chiuso era veloce (hai segnato un
            # tempo), il prossimo e' raffreddamento -> niente delta/ABORTED
            self._cool_lap = (self._last > 0 and self._best > 0
                              and self._last <= self._best + 1.0)
            if len(self._dl_cur) > 5 and self._last and self._last > 0:
                # REGOLE riferimento: un giro PULITO scalza sempre un ref
                # invalido; un giro INVALIDO puo' solo fare da ref
                # PROVVISORIO (bootstrap) o migliorare tra invalidi — mai
                # scalzare un pulito. Cosi' il delta c'e' SEMPRE, e appena
                # fai un giro vero il riferimento diventa quello sano.
                _cur_inv = getattr(self, "_lap_was_inv", False)
                _ref_inv = getattr(self, "_dl_ref_inv", False)
                if self._dl_ref_time is None \
                        or (not _cur_inv and _ref_inv) \
                        or (self._last < self._dl_ref_time
                            and (_cur_inv == _ref_inv or not _cur_inv)):
                    self._dl_ref = self._dl_cur      # nuovo trace di rif.
                    self._dl_ref_time = self._last
                    self._dl_ref_inv = _cur_inv
                    self._dl_persist()   # sopravvive al riavvio app
            self._lap_was_inv = False
            self._dl_cur = [(0.0, 0.0)]      # ANCHOR all'origine (stile TinyPedal)
            self._dl_pos_last = 0.0
            self._dl_lap = self._laps
            self._sec_col = [None, None, None]   # nuovo giro: tacche da rifare
            if self._last and self._last > 0 \
                    and self._laps > self._run_out_lap:
                self._freeze_until = now + 5.0
                self._freeze_txt = self._fmt_t(self._last)
                self._freeze_col = _col(self._last, self._best,
                                        self._sess_best_lap)
        # ── ARMA: solo quando l'inizio giro e' coerente (mLapStartET aggiornato,
        #    _live piccolo). Cosi' NON registro il transitorio del traguardo
        #    dove _live e' ancora ~il tempo del giro precedente. ──
        if not getattr(self, "_dl_armed", False) and self._live < 5.0:
            self._dl_armed = True
        # ── campione traccia (stile TinyPedal): avanzi in distanza + tempo
        #    crescente e ragionevole ──
        if getattr(self, "_dl_armed", False) and 0.0 < self._live < 600.0:
            _pl = getattr(self, "_dl_pos_last", 0.0)
            _lt = self._dl_cur[-1][1] if self._dl_cur else 0.0
            if self._lapdist > _pl + 4.0 and self._live >= _lt:
                self._dl_cur.append((self._lapdist, self._live))
                self._dl_pos_last = self._lapdist
        # ── CAMBIO SETTORE: freeze 5s del tempo di settore chiuso
        if self._prev_sector is not None and self._prev_sector != self._sector:
            if self._prev_sector == 1:            # chiuso S1
                _st = self._cs[0] if len(self._cs) > 0 else 0.0
                if _st > 0:
                    _cc = _col(_st, best[0], sbs[0])
                    self._freeze_until = now + 5.0
                    self._freeze_txt = "S1 " + self._fmt_t(_st)
                    self._freeze_col = _cc
                    self._sec_col[0] = _cc        # tacca = stesso colore del tempo
            elif self._prev_sector == 2:          # chiuso S2
                _st = self._cs[1] if len(self._cs) > 1 else 0.0
                if _st > 0:
                    _cc = _col(_st, best[1], sbs[1])
                    self._freeze_until = now + 5.0
                    self._freeze_txt = "S2 " + self._fmt_t(_st)
                    self._freeze_col = _cc
                    self._sec_col[1] = _cc
        self._prev_sector = self._sector
        # ── DELTA LIVE rolling (vs mio best trace), ancorato al best di CLASSE
        # SBLOCCO abort incastrato: ai box/garage o a inizio giro pulito
        # (transitorio nuovo giro) il flag si azzera SEMPRE — senno' un
        # abort seguito dal rientro lasciava delta nascosto e tacche
        # neutre per tutta la sessione
        if self._in_garage or self._in_pits:
            self._lap_aborted = False
        self._delta_txt, self._delta_col = "", None
        ref = self._dl_ref
        # delta se: riferimento valido, campionamento ARMATO (fuori dal
        # transitorio) e giro in corso. (Niente piu' blocco cool-down: nascondeva
        # il delta a chi e' costante col proprio best.)
        if ref and len(ref) >= 2 and getattr(self, "_dl_armed", False) \
                and self._live > 0.5:
            rt = self._interp(ref, self._lapdist)
            if rt is not None:
                d = self._live - rt              # delta vs il MIO best
                _valid = (self._laps > self._run_out_lap
                          and not self._in_pits and not self._in_garage)
                _LIM = 3.0                        # limite delta = soglia abort
                if _valid and d > _LIM:
                    if not self._lap_aborted:     # FRONTE: segnala al muretto
                        try:                      # (voce sincronizzata al dash)
                            (USER_DIR / "dash_abort.json").write_text(
                                json.dumps({"t": time.time(),
                                            "lap": self._laps}))
                        except Exception:
                            pass
                    self._lap_aborted = True      # molto piu' lento -> giro buttato
                _dd = max(-_LIM, min(_LIM, d))    # cappato: aborted non esplode
                self._d_final = "%+.3f" % d       # ultimo delta VERO (prova)
                # ABORTED: nascondo il numero pinnato (+3.000) -> solo la scritta
                self._delta_txt = "" if self._lap_aborted else ("%+.3f" % _dd)
                # COLORE DINAMICO (su proiezione = mio best + delta attuale):
                # magenta = batti il fast di P1 (classe), verde = batti il tuo
                # best, bianco = non stai migliorando niente
                _col = QColor(255, 255, 255, 235)   # bianco: NON stai migliorando
                _mb = self._dl_ref_time or 0.0
                _p1 = self._cls_best_lap or 0.0
                # coloro SOLO se stai migliorando (delta <= 0) e fuori dal
                # transitorio di inizio giro (~2s). Delta positivo -> bianco.
                if _mb > 0 and self._live > 2.0 and d <= 1e-3:
                    _proj = _mb + d
                    if _p1 > 0 and _proj <= _p1 + 1e-3:
                        _col = _MAG        # proiezione batte il fast di P1
                    else:
                        _col = _GRN        # batti il tuo best
                self._delta_col = _col

    # ── paint ─────────────────────────────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self.width() / float(_W)
        p.scale(s, s)
        # ── DASH LAYOUT (Options app): 0 completa, 1 solo cambio,
        # 2 solo header, 3 senza header ──
        try:
            _dl9 = int(self.cfg.get("dash_layout", 0) or 0)
        except Exception:
            _dl9 = 0
        _mc9 = getattr(self, "_minicar", None)
        if _dl9 == 1:
            # SOLO CAMBIO: tachimetro neon grande su fondo pulito
            if _mc9 is not None and _mc9.isVisible():
                _mc9.hide()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(10, 14, 22, 235))
            p.drawRoundedRect(QRectF(0, 0, _W, _H), 14, 14)
            self._gauge_with_fade(p, _W / 2.0, _H / 2.0, 105.0,
                                  show_gear=True)
            p.end()
            return
        if _dl9 == 2:
            # SOLO HEADER: resta la barra alta, il resto trasparente
            if _mc9 is not None and _mc9.isVisible():
                _mc9.hide()
            p.setClipRect(QRectF(0, 0, _W, self.HDR))
            self._paint_frame(p)
            p.end()
            return
        if _dl9 == 3:
            # SENZA HEADER: tutto il corpo, barra alta trasparente
            p.setClipRect(QRectF(0, self.HDR, _W, _H - self.HDR))
        # (radio SEPARATA: vive nell'overlay "Team Radio", non qui)
        self._paint_frame(p)
        self._paint_page(p)
        p.end()

    def _active_mods(self):
        """MODULI FISSI: 1 = dashboard, 2 = pit, 3 = impostazioni,
        4 = macchinina danni/gomme (dal dashboard V2)."""
        return [1, 2, 3, 4]

    # ── MOD 4: MACCHININA del dashboard v3 (TyreBrakeGrid) ──
    def _paint_mod4(self, p):
        y0 = self.HDR + self.ROW_T
        bodyh = _H - self.HDR - self.ROW_T - self.ROW_B
        s = self.width() / float(_W)
        # child in PIXEL DEVICE (come nel vecchio dashboard): riempie
        # ~65% del corpo pagina, ricreato se cambia la scala della card
        _msc = (bodyh * s * 0.65) / 72.0
        mc = getattr(self, "_minicar", None)
        if mc is None or abs(mc._scale - _msc) > 0.06:
            if mc is not None:
                mc.deleteLater()
            from .minicar import TyreBrakeGrid
            mc = self._minicar = TyreBrakeGrid(scale=_msc, rear_ext=0.3)
            mc.setParent(self)
        mc.move(int(_W / 2.0 * s - mc.width() / 2.0),
                int((y0 + bodyh / 2.0) * s - mc.height() / 2.0))
        if not mc.isVisible():
            mc.show()
        mc.raise_()
        _cd = getattr(self, "_car_d", None) or {}
        try:
            from core.classes import class_tag as _ct
            _tag = _ct(getattr(self, "_cls_name", "") or "") or ""
        except Exception:
            _tag = ""
        try:
            # colori gomma dall'INNER layer (strato di lavoro), non carcassa;
            # danni/foratura/staccate da letture DIRETTE; sospensioni e aero
            # dai wearables REST (thread dedicato), come nel dashboard v3
            _t4m = getattr(self, "_inn4", None) or self._carc4
            mc.set_data(_t4m, getattr(self, "_brk4", None), _tag,
                        getattr(self, "_dent8", None),
                        getattr(self, "_wsusp", None),
                        getattr(self, "_waero", None),
                        getattr(self, "_flat4", None),
                        getattr(self, "_det4", None),
                        getattr(self, "_det_part", False))
        except Exception:
            pass
        # ── VERBATIM dashboard v3 (_draw_minicar_labels): temp °C + usura %
        # per ruota, ACQUA davanti / OLIO dietro, fulmine energia al centro.
        try:
            from widgets.list.colors import col_tyre_temp as _ctt
            from ui.icons import (WATER_SVG as _WSVG, OIL_SVG as _OSVG,
                                  energy_bolt_svg as _ebolt)
            from PySide6.QtSvg import QSvgRenderer as _QSR
            from PySide6.QtCore import QByteArray as _QBA
            if not hasattr(self, "_svg_cache9"):
                self._svg_cache9 = {}

            def _prnd(svg):
                r9 = self._svg_cache9.get(svg)
                if r9 is None:
                    r9 = self._svg_cache9[svg] = _QSR(_QBA(svg.encode()))
                return r9

            gx = mc.x() / s
            gy = mc.y() / s
            gw = mc.width() / s
            gh = mc.height() / s
            tv = getattr(self, "_inn4", None) or [None] * 4
            wear = getattr(self, "_wear4", None) or [None] * 4
            # centri ruota dalla geometria vera di TyreBrakeGrid (row_y),
            # riportati in unita' painter (la v3 usava _WY=20.6 perche' la
            # scala della minicar coincideva con quella del pannello)
            sc9 = mc._scale
            _h0d = 72.0 * sc9
            _wy_f = (_h0d * 0.30 - sc9) / s
            _wy_r = (mc.height() - _h0d * 0.30 + sc9) / s
            corners = [(0, -1, 0), (1, +1, 0), (2, -1, 1), (3, +1, 1)]
            p.setFont(QFont("Arial", 11, QFont.Bold))
            _CW = 46.0
            # chip COMPOUND (simboli nostri) sul lato esterno del blocco:
            # SOLO i simboli compound, sempre. Sigla dal NOME mescola
            # (regola collaudata: l'indice intero inganna sulle Hypercar),
            # indice come fallback.
            from ui.icons import tyre_chip_svg as _tcs
            _sig4 = {0: "S", 1: "M", 2: "H", 3: "W"}
            _co4 = getattr(self, "_comp4", None) or [None] * 4

            def _signm(nm):
                n9 = (nm or "").strip().lower()
                if not n9:
                    return ""
                if any(k9 in n9 for k9 in ("wet", "rain", "inter", "full")):
                    return "W"
                if "hard" in n9:
                    return "H"
                if "med" in n9:
                    return "M"
                if "soft" in n9:
                    return "S"
                if "slick" in n9:
                    return "M"
                return ""
            _sgf = _signm(getattr(self, "_compound", ""))
            _sgr = _signm(getattr(self, "_comp_rr", ""))
            for wi, side, row in corners:
                cx = gx - 20.0 if side < 0 else gx + gw + 20.0
                cy = gy + (_wy_f if row == 0 else _wy_r)
                _lx = cx - _CW / 2.0
                if tv[wi] is not None:
                    p.setPen(_ctt(tv[wi], _tag))
                    p.drawText(QRectF(_lx, cy - 16.0, _CW, 15),
                               Qt.AlignHCenter | Qt.AlignVCenter,
                               "%d°C" % int(round(tv[wi])))
                if wear[wi] is not None:
                    p.setPen(QColor("#f2f4f7"))
                    p.drawText(QRectF(_lx, cy + 1.0, _CW, 15),
                               Qt.AlignHCenter | Qt.AlignVCenter,
                               "%d%%" % int(round(wear[wi] * 100)))
                # PRESSIONE (kPa) e TEMP FRENO per ruota (rich. 23/07):
                # pressione bianca tenue, freno col gradiente collaudato
                # della minicar (carbon/acciaio per classe)
                _pr9 = (self._press4[wi]
                        if isinstance(self._press4, list)
                        and self._press4[wi] else None)
                if _pr9:
                    p.setPen(QColor(255, 255, 255, 150))
                    p.drawText(QRectF(_lx, cy + 16.0, _CW, 15),
                               Qt.AlignHCenter | Qt.AlignVCenter,
                               "%d" % int(round(_pr9)))
                _bk9 = getattr(self, "_brk4", None)
                if _bk9 and _bk9[wi] is not None and _bk9[wi] > -100:
                    p.setPen(mc._brake_grad_color(
                        int(round(_bk9[wi])), _tag))
                    p.drawText(QRectF(_lx, cy + 31.0, _CW, 15),
                               Qt.AlignHCenter | Qt.AlignVCenter,
                               "%d°" % int(round(_bk9[wi])))
                _ccx = _lx - 30.0 if side < 0 else _lx + _CW + 4.0
                _sg9 = (_sgf if wi < 2 else _sgr) or _sig4.get(_co4[wi])
                if _sg9:
                    _prnd(_tcs(_sg9, True)).render(
                        p, QRectF(_ccx, cy - 13.0, 26, 26))

            # (acqua/olio TOLTI dal MOD 4 su richiesta: vivono in MOD 1)
            _bt9 = getattr(self, "_batt9", None)
            if getattr(self, "_emo9", 0) and _bt9 is not None:
                _st9x = self._emo9
                if _st9x == 3:
                    _ec9 = "#00e676"
                elif _st9x == 2:
                    _ec9 = "#ff3cdc"
                elif _bt9 < 0.20:
                    _ec9 = "#ff9a30"
                else:
                    _ec9 = "#50a0eb"
                _ex9 = gx + gw / 2.0
                _ey9 = gy + gh / 2.0
                _prnd(_ebolt(_ec9)).render(
                    p, QRectF(_ex9 - 7.5, _ey9 - 12.5, 15, 15))
                p.setFont(QFont("Arial", 7, QFont.Bold))
                p.setPen(QColor(_ec9))
                p.drawText(QRectF(_ex9 - 16, _ey9 + 3.5, 32, 9),
                           Qt.AlignHCenter | Qt.AlignVCenter,
                           "%d" % int(round(_bt9 * 100)))
        except Exception:
            pass

    def _paint_page(self, p):
        """Disegna il MOD della pagina corrente. PRIMA la CORRENTE:
        chiave off = TUTTE le pagine spente (nessun comando altrove);
        al riarmo boot spinner e si riparte dalla PRIMA pagina."""
        act = self._active_mods()
        self._pages = max(1, len(act))
        ion = self._ign != 0
        if self._pwr_prev is None:
            self._pwr_prev = ion
        if ion != self._pwr_prev:
            self._pwr_prev = ion
            if ion:
                self._page = 0           # riarmo: pagina iniziale
                self._pwr_t0 = time.monotonic()
                self._anim_t.start()
        scr = QRectF(0, self.HDR, _W, _H - self.HDR)
        _mc0 = getattr(self, "_minicar", None)
        if not ion:
            self._lamp_t0 = None       # prossima accensione: nuovo lamp test
            if _mc0 is not None and _mc0.isVisible():
                _mc0.hide()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(6, 7, 9))
            p.drawRect(scr)
            return
        boot = (time.monotonic() - self._pwr_t0) if self._pwr_t0 else 99
        if boot < 3.0:
            if _mc0 is not None and _mc0.isVisible():
                _mc0.hide()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(6, 7, 9))
            p.drawRect(scr)
            # LOGO AUTO in fade (sopra), poi lo spinner PIU' IN BASSO
            _cy0 = scr.center().y()
            self._draw_car_logo(p, _W / 2.0, _cy0 - 26.0, 72.0,
                                 opacity=max(0.0, min(1.0, boot / 0.6)))
            side, gap = 4.5, 2.0
            step = side + gap
            cx = _W / 2.0 - step
            cy = _cy0 + 44.0                    # spinner abbassato
            POS = ((0, 0), (1, 0), (1, 1),
                   (1, 2), (0, 2), (0, 1))
            head = int(boot * 10) % 6
            for i, (gx, gy) in enumerate(POS):
                k = (head - i) % 6
                p.setBrush(QColor(255, 255, 255,
                                  max(30, 217 - k * 45)))
                p.drawRect(QRectF(cx + gx * step, cy + gy * step,
                                  side, side))
            return
        if self._anim_t.isActive():
            self._anim_t.stop()
        # LAMP TEST da auto vera: alla prima schermata dopo il boot (o
        # all'avvio app) TUTTE le spie accese per 2.5s, poi ognuna torna
        # alla sua condizione
        if getattr(self, "_lamp_t0", None) is None:
            self._lamp_t0 = time.monotonic()
        if not act:
            return
        # RETROILLUMINAZIONE notte = SOLO fari verdi FISSI (debounce):
        # i lampeggi, primo tocco compreso, non la toccano mai
        if getattr(self, "_beam_steady", False):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(64, 130, 255, 14))
            p.drawRect(scr)
        mod = act[self._page % len(act)]
        if mod != 4 and _mc0 is not None and _mc0.isVisible():
            _mc0.hide()          # la macchinina vive SOLO nel MOD 4
        fn = getattr(self, "_paint_mod%d" % mod, None)
        if fn is not None:
            fn(p)

    # ── MOD 2: pagina PIT — riparazioni, gomme, benzina/VE MANUALE
    # (voci VERE del pit menu di LMU, scrittura via loadPitMenu) ──
    def _m2_rows(self):
        """Ordine voluto: DAMAGE, VE (sotto i danni), 4 TYRES,
        poi (staccate) FL FR RL RR."""
        items = getattr(self, "_pm_items", None) or []

        def find(pfx):
            for it in items:
                if str((it or {}).get("name") or "").upper() \
                        .startswith(pfx):
                    return it
            return None

        rows = []
        it = find("DAMAGE")                    # SOLO se c'è danno (val != "-")
        if it:
            _o = it.get("settings") or []
            _c = int(it.get("currentSetting") or 0)
            _v = str((_o[_c] or {}).get("text") or "") \
                if 0 <= _c < len(_o) else ""
            if self._tr_pit(_v) != "-":
                rows.append(it)
        it = find("VIRTUAL ENERGY")
        if it:
            rows.append(it)
        it = find("FUEL RATIO")               # ratio carburante
        if it:
            rows.append(it)
        for pfx in ("TIRES", "FL TIRE", "FR TIRE",
                    "RL TIRE", "RR TIRE"):
            it = find(pfx)
            if it:
                rows.append(it)
        # STOP/GO (serve penalità sì/no): SEMPRE in cima quando LMU lo espone,
        # switchabile — NON sparisce se metti "No"
        it = find("STOP/GO") or find("STOP AND GO") or find("STOP")
        if it:
            rows.insert(0, it)
        return rows

    @staticmethod
    def _tyre_opt_parse(txt):
        """(lettera, nuova) dal testo opzione LMU ('Nuove Media',
        'Usata Media 0%', 'New Soft'...). None se non e' una gomma."""
        t = (txt or "").upper()
        letter = None
        for k, L in (("MEDI", "M"), ("MORBID", "S"), ("SOFT", "S"),
                     ("DURA", "H"), ("HARD", "H"), ("BAGNAT", "W"),
                     ("WET", "W"), ("RAIN", "W")):
            if k in t:
                letter = L
                break
        if letter is None:
            return None
        _used = ("USAT" in t) or ("USED" in t)
        # "Usata ... 0%" e' FINTA: 0 di usura = non hai gomme usate
        # in inventario -> trattala come NUOVA (chip pieno)
        m = re.search(r"(\d+)\s*%", t)
        if _used and m and int(m.group(1)) == 0:
            _used = False
        return letter, (not _used)

    def _m2_icon_svg(self, it, rows):
        """SVG del simbolo per la riga: chip mescola (tratteggiato se
        usata) o i 4 DOT per 'Mixed Tires'."""
        try:
            from ui.icons import tyre_chip_svg, tyre_mix_svg
            opts = it.get("settings") or []
            cur = int(it.get("currentSetting") or 0)
            vt = str((opts[cur] or {}).get("text") or "") \
                if 0 <= cur < len(opts) else ""
            nm = str(it.get("name") or "").upper()
            if nm.startswith("TIRES") and "MIX" in vt.upper():
                four, new4 = [], []
                for r2 in rows:
                    n2 = str(r2.get("name") or "").upper()
                    if n2[:2] in ("FL", "FR", "RL", "RR"):
                        o2 = r2.get("settings") or []
                        c2 = int(r2.get("currentSetting") or 0)
                        t2 = str((o2[c2] or {}).get("text") or "") \
                            if 0 <= c2 < len(o2) else ""
                        pr = self._tyre_opt_parse(t2)
                        four.append(pr[0] if pr else "")
                        new4.append(pr[1] if pr else False)
                if len(four) == 4:
                    return tyre_mix_svg(four, new4)
                return None
            pr = self._tyre_opt_parse(vt)
            if pr:
                return tyre_chip_svg(pr[0], pr[1])
        except Exception:
            pass
        return None

    def _m2_change(self, step):
        rows = self._m2_rows()
        if not rows:
            return
        it = rows[self._m2_sel % len(rows)]
        opts = it.get("settings") or []
        if not opts:
            return
        try:
            cur = int(it.get("currentSetting") or 0)
        except (TypeError, ValueError):
            cur = 0
        _new = (cur + step) % len(opts)
        # salta le opzioni NON valide (master E singole ruote):
        # "Mixed" (appare da sola) e "Usata ... 0%" (0% = non hai
        # gomme usate -> LMU la rifiuta e finisce in mixed)
        _nmu = str(it.get("name") or "").upper()
        if _nmu.startswith("TIRES") or _nmu[:2] in ("FL", "FR",
                                                    "RL", "RR"):
            def _skip(txt):
                u = (txt or "").upper()
                if "MIX" in u:
                    return True
                if "USAT" in u or "USED" in u:
                    m = re.search(r"(\d+)\s*%", u)
                    return bool(m and int(m.group(1)) == 0)
                return False
            _g = 0
            while _g < len(opts) and _skip(
                    (opts[_new] or {}).get("text") or ""):
                _new = (_new + step) % len(opts)
                _g += 1
        it["currentSetting"] = _new
        _pend = {str(it.get("name") or ""): it["currentSetting"]}
        # MASTER "4 TYRES": switcha SUBITO tutte e 4 le ruote sotto
        # (come LMU). Il testo scelto (Nuove Media / Usata / Nessuna
        # modifica) viene ricopiato su FL/FR/RL/RR per l'indice che
        # combacia; "Mixed" invece le lascia com'e' (indipendenti).
        nm0 = str(it.get("name") or "").upper()
        if nm0.startswith("TIRES"):
            sel_txt = str((opts[it["currentSetting"]] or {})
                          .get("text") or "")
            # propaga per INDICE (come LMU): le opzioni ruota sono
            # nello stesso ordine del master, solo senza "Mixed" ->
            # il match per testo falliva con usure diverse -> mixed
            _mi = it["currentSetting"]
            if "MIX" not in sel_txt.upper():
                for r2 in (self._pm_items or []):
                    n2o = str((r2 or {}).get("name") or "")
                    if n2o.upper()[:2] in ("FL", "FR", "RL", "RR"):
                        if _mi < len(r2.get("settings") or []):
                            r2["currentSetting"] = _mi
                            _pend[n2o] = _mi
        elif nm0[:2] in ("FL", "FR", "RL", "RR"):
            # cambiata una SINGOLA ruota: allinea il MASTER come LMU —
            # 4 uguali -> quell'indice, 4 diverse -> "Mixed" (senno' il
            # master riapplica e sovrascrive la ruota che ho toccato)
            mst = None
            wset = []
            for r2 in (self._pm_items or []):
                nn = str((r2 or {}).get("name") or "").upper()
                if nn.startswith("TIRES"):
                    mst = r2
                elif nn[:2] in ("FL", "FR", "RL", "RR"):
                    wset.append(int(r2.get("currentSetting") or 0))
            if mst is not None:
                mo = mst.get("settings") or []
                if wset and all(w == wset[0] for w in wset) \
                        and wset[0] < len(mo):
                    mst["currentSetting"] = wset[0]
                else:
                    for j3, op3 in enumerate(mo):
                        if "MIX" in str((op3 or {}).get("text")
                                        or "").upper():
                            mst["currentSetting"] = j3
                            break
                _pend[str(mst.get("name") or "")] = \
                    mst["currentSetting"]
        _now = time.monotonic()
        self._pm_pending = {**(getattr(self, "_pm_pending", None) or {}),
                            **_pend}
        if not hasattr(self, "_pm_pending_ts"):
            self._pm_pending_ts = {}
        for _k in _pend:
            self._pm_pending_ts[_k] = _now       # ogni voce difesa dal SUO istante
        import threading

        def _post(menu):
            try:
                import urllib.request as _ur
                req = _ur.Request(
                    "http://localhost:6397/rest/garage/PitMenu"
                    "/loadPitMenu",
                    data=json.dumps(menu).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST")
                _ur.urlopen(req, timeout=1.5)
            except Exception:
                pass

        threading.Thread(target=_post, args=(self._pm_items,),
                         daemon=True).start()

    # LINGUA DASH (rich. 23/07): IT traduce le PAROLE (danno/energia/
    # benzina/gomme/ripara...); i termini classici (STINT, RUN, BOX,
    # GARAGE, LAP, LICO, MDF, MOD/SC, ON/OFF, elettronica) restano
    # in inglese SEMPRE. L'app principale non c'entra: solo la card.
    _IT9 = {"DAMAGE": "DANNO", "ENERGY": "ENERGIA", "FUEL": "BENZINA",
            "4 TYRES": "4 GOMME", "TYRES": "GOMME", "ALL": "TUTTE",
            "REPAIR ALL": "RIPARA TUTTO",
            "REPAIR BODY": "RIPARA CARROZZERIA",
            "REPAIR SUSP": "RIPARA SOSPENSIONI",
            "REPAIR AERO": "RIPARA AERO",
            "NO REPAIR": "NON RIPARARE",
            "NO DAMAGE": "NESSUN DANNO",
            "NO CHANGE": "NESSUNA MODIFICA",
            "MIXED": "MISTE",
            "FL": "AS", "FR": "AD", "RL": "PS", "RR": "PD",
            "PENALTY": "PENALITA'", "BRAKES": "FRENI",
            "DRIVER": "PILOTA", "DUCTS": "PRESE",
            "SPEED UNIT": "UNITA' VELOCITA'",
            "ELECTRIC CONTROL": "CONTROLLI ELETTRONICI",
            "TEST MODE": "MODALITA' TEST",
            "LIGHTS": "LUCI", "WIPER": "TERGICRISTALLI",
            "LANGUAGE": "LINGUA",
            "TELEMETRY ON": "TELEMETRIA ON",
            "TELEMETRY OFF": "TELEMETRIA OFF"}

    def _it9(self, s):
        """Traduzione display EN->IT se la lingua dash e' IT."""
        if self._prefs.get("dash_lang", "EN") != "IT":
            return s
        return self._IT9.get(s, s)

    @staticmethod
    def _tr_pit(txt):
        """Testo opzione LMU (spesso in italiano) -> INGLESE, UPPER."""
        t = (txt or "").strip()
        FIX = {"nessuna modifica": "NO CHANGE",
               "non riparare": "NO REPAIR",
               "ripara tutto": "REPAIR ALL",
               "ripara carrozzeria": "REPAIR BODY",
               "ripara sospensioni": "REPAIR SUSP",
               "ripara aerodinamica": "REPAIR AERO",
               "mixed tires": "MIXED", "n/d": "-", "": "-"}
        if t.lower() in FIX:
            return FIX[t.lower()]
        o = t
        for a, b in ((r"nuov[ei]", "NEW"), (r"usat[ae]", "USED"),
                     (r"medi[ae]", "MEDIUM"), (r"morbid[aei]", "SOFT"),
                     (r"dur[ae]", "HARD"), (r"bagnato", "WET"),
                     (r"asciutto", "DRY"),
                     (r"\bgiri\b", "LAPS"), (r"\bgiro\b", "LAP")):
            o = re.sub(a, b, o, flags=re.I)
        return o.upper().strip()

    def _paint_mod2(self, p):
        FAM = "Archivo SemiExpanded"
        bx = _W / 1334.0
        by = (_H - self.HDR - self.ROW_T - self.ROW_B) / 750.0
        y0 = self.HDR + self.ROW_T
        # blocco GEAR/tachimetro come in MOD 1, STESSA posizione (dietro la lista)
        _gy = self.HDR + self.ROW_T \
            + (_H - self.HDR - self.ROW_T - self.ROW_B) / 2.0 - 44.0
        # gauge RIMOSSO dal MOD 2 (richiesta 23/07: pagina PIT pulita,
        # in attesa di destinazione per questo spazio)
        rows = self._m2_rows()
        f = QFont(FAM)
        if not rows:
            f.setPixelSize(max(6, int(64 * by)))
            p.setFont(f)
            p.setPen(QPen(QColor(255, 255, 255, 120)))
            p.drawText(QRectF(0, self.HDR, _W, _H - self.HDR),
                       Qt.AlignCenter, "NO PIT DATA")
            return
        _DISP = {"DAMAGE": "DAMAGE", "VIRTUAL ENERGY": "ENERGY",
                 "FUEL": "FUEL", "TIRES": "4 TYRES",
                 "FL TIRE": "FL", "FR TIRE": "FR",
                 "RL TIRE": "RL", "RR TIRE": "RR"}
        if not hasattr(self, "_m2_ico_cache"):
            self._m2_ico_cache = {}
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QByteArray
        f.setPixelSize(18)
        f.setWeight(QFont.Medium)
        p.setFont(f)
        _fm = QFontMetricsF(f)
        lh = 66.0 * by

        def _ico(svg, x, cy, sz=22.0):
            if not svg:
                return
            rnd = self._m2_ico_cache.get(svg)
            if rnd is None:
                rnd = QSvgRenderer(QByteArray(svg.encode()))
                self._m2_ico_cache[svg] = rnd
                if len(self._m2_ico_cache) > 40:
                    self._m2_ico_cache.clear()
            rnd.render(p, QRectF(x, cy - sz / 2.0, sz, sz))

        def _pct_txt(it2):
            o2 = it2.get("settings") or []
            c2 = int(it2.get("currentSetting") or 0)
            t2 = str((o2[c2] or {}).get("text") or "") \
                if 0 <= c2 < len(o2) else ""
            m2 = re.search(r"(\d+)\s*%", t2)
            return m2.group(1) if m2 else None

        wheels = [r for r in rows
                  if str(r.get("name") or "").upper()[:2]
                  in ("FL", "FR", "RL", "RR")]
        # % PEGGIORE tra le 4 (None = tutte nuove)
        worst = None
        for r2 in wheels:
            pv = _pct_txt(r2)
            if pv and int(pv) > 0:
                worst = int(pv) if worst is None else min(worst,
                                                          int(pv))
        # ── LISTA VERTICALE, colonna sinistra: STOP/GO(pen), DAMAGE, ENERGY,
        #    RATIO, 4 TYRES, FL, FR, RL, RR. Righe/font AUTO-FIT sul numero
        #    di voci (max 25 alto): con la penalità o piu' voci si stringono. ──
        COLW = 220.0          # larghezza colonna testo
        SELW = 175.0          # larghezza banda SELEZIONE (piu' stretta)
        ROWH = 25.0           # altezza riga FISSA (il menu SCROLLA)
        XC = 20.0             # margine sinistro colonna
        TX = XC + 14.0        # rientro testo
        PITCH = 31.0          # passo verticale
        Y0C = y0 + 4.0
        _isz = 22.0
        f.setPixelSize(18)
        f.setWeight(QFont.Medium)
        p.setFont(f)
        _fm = QFontMetricsF(f)
        # ── SCROLL: finestra di righe attorno alla selezione ──
        _n = len(rows)
        _bot = y0 + 690.0 * by
        _maxvis = max(1, int((_bot - Y0C) / PITCH))
        _sel = (self._m2_sel % _n) if _n else 0
        _sc = getattr(self, "_m2_scroll", 0)
        if _sel < _sc:
            _sc = _sel
        elif _sel >= _sc + _maxvis:
            _sc = _sel - _maxvis + 1
        _sc = max(0, min(_sc, max(0, _n - _maxvis)))
        self._m2_scroll = _sc
        for i in range(_sc, min(_n, _sc + _maxvis)):
            it = rows[i]
            nm = str(it.get("name") or "").rstrip(":")
            opts = it.get("settings") or []
            cur = int(it.get("currentSetting") or 0)
            vt = str((opts[cur] or {}).get("text") or "") \
                if 0 <= cur < len(opts) else ""
            up = nm.upper()
            sel = (i == _sel)
            ry = Y0C + (i - _sc) * PITCH
            cy = ry + ROWH / 2.0
            if sel:                              # selezione = bg grigio tenue
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(160, 164, 174, 70))
                p.drawRect(QRectF(XC, ry, SELW, ROWH))
            p.setPen(QPen(QColor(255, 255, 255, 235)))
            if up.startswith("STOP"):            # PENALITÀ stop&go
                # SG = badge bg ROSSO testo bianco; 3 LAPS bianco (giri che
                # restano, INFO); poi lo switch SÌ(verde)/NO(giallo).
                _low = vt.strip().lower()
                _on = _low.startswith("s") or _low.startswith("y")  # Sì/Yes
                _mg = re.search(r"(\d+)", vt)
                _cx = TX
                _sgw = _fm.horizontalAdvance("SG") + 12.0
                _bh = ROWH - 6.0
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#ff2b2b"))
                p.drawRect(QRectF(_cx, ry + (ROWH - _bh) / 2.0, _sgw, _bh))
                p.setPen(QPen(QColor(255, 255, 255)))
                p.drawText(QRectF(_cx, ry, _sgw, ROWH), Qt.AlignCenter, "SG")
                _cx += _sgw + 8.0
                if _mg:                          # giri rimasti (bianco)
                    _t = "%s LAPS " % _mg.group(1)
                    p.setPen(QPen(QColor("#ffffff")))
                    _w = _fm.horizontalAdvance(_t)
                    p.drawText(QRectF(_cx, ry, _w + 6, ROWH),
                               Qt.AlignLeft | Qt.AlignVCenter, _t)
                    _cx += _w
                p.setPen(QPen(QColor("#ffffff")))   # separatore
                _w = _fm.horizontalAdvance("- ")
                p.drawText(QRectF(_cx, ry, _w + 6, ROWH),
                           Qt.AlignLeft | Qt.AlignVCenter, "- ")
                _cx += _w
                _yn, _col = ("SI", "#00e676") if _on else ("NO", "#ffee00")
                p.setPen(QPen(QColor(_col)))        # switch (verde/giallo)
                p.drawText(QRectF(_cx, ry, 60.0, ROWH),
                           Qt.AlignLeft | Qt.AlignVCenter, _yn)
            elif up.startswith("FUEL RATIO"):    # ratio carburante
                p.drawText(QRectF(TX, ry, COLW - 24.0, ROWH),
                           Qt.AlignLeft | Qt.AlignVCenter,
                           "RATIO %s" % vt.strip())
            elif up.startswith("VIRTUAL ENERGY"):
                # NUMERO % su badge VIOLA bold; poi i GIRI + bandierina a
                # scacchi (FLAG_SVG) al posto di "LAPS".
                _ln = self._tr_pit(vt)
                _mp = re.match(r"\s*(\d+)\s*(?:%|L)?\s*(.*)", _ln)
                if _mp:
                    _num, _rest = _mp.group(1), _mp.group(2)
                    _fb = QFont(FAM)
                    _fb.setPixelSize(18)
                    _fb.setWeight(QFont.Bold)
                    _pw = QFontMetricsF(_fb).horizontalAdvance(_num) + 14.0
                    _bh = ROWH - 6.0
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor("#8a3ffb"))          # viola
                    p.drawRect(QRectF(TX, ry + (ROWH - _bh) / 2.0,
                                      _pw, _bh))
                    p.setFont(_fb)
                    p.setPen(QPen(QColor(255, 255, 255)))
                    p.drawText(QRectF(TX, ry, _pw, ROWH),
                               Qt.AlignCenter, _num)
                    _cx = TX + _pw + 8.0
                    p.setFont(f)
                    # % che SERVE per finire (STESSA logica dell'auto-pit:
                    # auto_fuel_target = min VE% che copre i giri rimanenti).
                    # Solo in GARA. Arancio.
                    _need = None
                    if self._sess_type >= 10:
                        try:
                            _lt9 = self._best or self._last or 0.0
                            if self._sess_remain > 0 and _lt9 > 20.0 \
                                    and self._pm_items:
                                from core.strategy import auto_fuel_target
                                _lneed = int(self._sess_remain / _lt9) + 1
                                _r9 = auto_fuel_target(self._pm_items, _lneed)
                                if _r9:
                                    _need = _r9[1]
                        except Exception:
                            _need = None
                    if _need is not None:
                        p.setPen(QPen(QColor(255, 255, 255, 150)))
                        p.drawText(QRectF(_cx, ry, 18.0, ROWH),
                                   Qt.AlignLeft | Qt.AlignVCenter, ">")
                        _cx += _fm.horizontalAdvance("> ")
                        _nt = "%d" % _need
                        p.setPen(QPen(QColor("#ff7a00")))     # arancio
                        p.drawText(QRectF(_cx, ry, 40.0, ROWH),
                                   Qt.AlignLeft | Qt.AlignVCenter, _nt)
                        _cx += _fm.horizontalAdvance(_nt) + 10.0
                    _lm2 = re.search(r"(\d+)", _rest)
                    _lp = _lm2.group(1) if _lm2 else _rest
                    p.setPen(QPen(QColor(255, 255, 255, 235)))
                    p.drawText(QRectF(_cx, ry, 60.0, ROWH),
                               Qt.AlignLeft | Qt.AlignVCenter, _lp)
                    _cx += _fm.horizontalAdvance(_lp) + 5.0
                    if _lm2:                               # bandierina a scacchi
                        if not hasattr(self, "_flag_rnd"):
                            from ui.icons import FLAG_SVG
                            self._flag_rnd = QSvgRenderer(
                                QByteArray(FLAG_SVG.encode()))
                        _fsz = ROWH - 4.0
                        self._flag_rnd.render(
                            p, QRectF(_cx, ry + (ROWH - _fsz) / 2.0,
                                      _fsz, _fsz))
                else:
                    p.drawText(QRectF(TX, ry, COLW - 24.0, ROWH),
                               Qt.AlignLeft | Qt.AlignVCenter, _ln)
            elif up.startswith("TIRES"):
                _all9 = self._it9("ALL")
                p.drawText(QRectF(TX, ry, 200.0, ROWH),
                           Qt.AlignLeft | Qt.AlignVCenter, _all9)
                _ix = TX + _fm.horizontalAdvance(_all9) + 16
                _mix = "MIX" in vt.upper()
                if self._tyre_opt_parse(vt) or _mix:
                    _ico(self._m2_icon_svg(it, rows), _ix, cy, _isz)
                    if not _mix:
                        _pt = ("%d%%" % worst) if worst is not None \
                            else "100"
                        p.setPen(QPen(QColor(255, 255, 255, 235)))
                        p.drawText(QRectF(_ix + 28, ry, 120.0, ROWH),
                                   Qt.AlignLeft | Qt.AlignVCenter, _pt)
                else:
                    # gomme NON selezionate: dillo (prima riga vuota)
                    f.setPixelSize(14)
                    p.setFont(f)
                    p.setPen(QPen(QColor(255, 255, 255, 120)))
                    p.drawText(QRectF(_ix, ry, 170.0, ROWH),
                               Qt.AlignLeft | Qt.AlignVCenter,
                               self._it9("NO CHANGE"))
                    f.setPixelSize(18)
                    p.setFont(f)
            elif up[:2] in ("FL", "FR", "RL", "RR"):
                sig = self._it9(up[:2])      # IT: AS/AD/PS/PD
                p.drawText(QRectF(TX, ry, 60.0, ROWH),
                           Qt.AlignLeft | Qt.AlignVCenter, sig)
                _ix = TX + 32.0        # colonna icona FISSA (non spinta dal testo)
                if self._tyre_opt_parse(vt):
                    _ico(self._m2_icon_svg(it, rows), _ix, cy, _isz)
                    pv = _pct_txt(it)
                    _pt = ("%s%%" % pv) if (pv and int(pv) > 0) else "100"
                    p.setPen(QPen(QColor(255, 255, 255, 235)))
                    p.drawText(QRectF(_ix + 28, ry, 120.0, ROWH),
                               Qt.AlignLeft | Qt.AlignVCenter, _pt)
                else:
                    # ruota senza cambio selezionato: dillo, non vuoto
                    f.setPixelSize(14)
                    p.setFont(f)
                    p.setPen(QPen(QColor(255, 255, 255, 120)))
                    p.drawText(QRectF(_ix, ry, 170.0, ROWH),
                               Qt.AlignLeft | Qt.AlignVCenter,
                               self._it9("NO CHANGE"))
                    f.setPixelSize(18)
                    p.setFont(f)
            else:
                _ln = self._tr_pit(vt)
                if up.startswith("DAMAGE"):
                    if _ln in ("-", "N/D"):
                        _ln = "NO DAMAGE"
                        p.setPen(QPen(QColor("#00e676")))   # verde
                    elif _ln == "REPAIR ALL":
                        p.setPen(QPen(QColor("#ff7a00")))   # arancione acceso
                    elif _ln == "REPAIR BODY":
                        p.setPen(QPen(QColor("#ffee00")))   # giallo acceso
                p.drawText(QRectF(TX, ry, COLW - 24.0, ROWH),
                           Qt.AlignLeft | Qt.AlignVCenter,
                           self._it9(_ln))
        # ── frecce SCROLL: se ci sono voci sopra/sotto la finestra ──
        from PySide6.QtGui import QPolygonF as _QPF
        _ax = XC + COLW - 14.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 160))
        if _sc > 0:                              # su
            _ay = Y0C - 1.0
            p.drawPolygon(_QPF([QPointF(_ax, _ay + 6.0),
                                QPointF(_ax + 9.0, _ay + 6.0),
                                QPointF(_ax + 4.5, _ay)]))
        if _sc + _maxvis < _n:                    # giu'
            _ay = Y0C + _maxvis * PITCH - 6.0
            p.drawPolygon(_QPF([QPointF(_ax, _ay),
                                QPointF(_ax + 9.0, _ay),
                                QPointF(_ax + 4.5, _ay + 6.0)]))
        # SLICK montate / totale — SOLO in qualifica (5-8) o gara
        # (>=10): in pratica le gomme sono illimitate, non ha senso
        _tmax = getattr(self, "_tyre_max", 0)
        _st9 = getattr(self, "_sess_type", 0)
        if _tmax > 0 and (5 <= _st9 <= 8 or _st9 >= 10):
            _mounted = _tmax - getattr(self, "_tyre_new_left", _tmax)
            f.setPixelSize(18)
            f.setWeight(QFont.Medium)
            p.setFont(f)
            p.setPen(QPen(QColor(255, 255, 255, 210)))
            p.drawText(QRectF(700 * bx, y0 + 12 * by, 594 * bx,
                              60 * by),
                       Qt.AlignRight | Qt.AlignVCenter,
                       "NEW SLICKS %d/%d" % (_mounted, _tmax))
        # ── PANNELLO TEMPO SOSTA (spazio ex-gauge): stima LMU scomposta
        # (rotta pitstop-estimate, 23/07) e CRONO che scorre da fermi ai
        # box: grande = stima − trascorso (ambra), oltre stima = +X rosso ──
        _stopping = getattr(self, "_pit_t0", None) is not None
        # da FERMI: stima e scomposizione CONGELATE all'ancora (un solo
        # countdown fluido); in marcia: preventivo live
        _est9 = (getattr(self, "_pit_est0", None) if _stopping
                 else getattr(self, "_pit_est", None)) or {}
        try:
            _tot9 = float(_est9.get("total") or 0.0)
        except (TypeError, ValueError):
            _tot9 = 0.0
        if _tot9 > 0.05 or _stopping:
            _px0, _px1 = 300.0, 530.0
            _pxc = (_px0 + _px1) / 2.0
            f.setPixelSize(12)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            p.setPen(QPen(QColor(255, 255, 255, 150)))
            p.drawText(QRectF(_px0, 96.0, _px1 - _px0, 16.0),
                       Qt.AlignCenter,
                       "PIT STOP" if _stopping else "PIT STOP EST")
            _big = QFont(FAM)
            _big.setPixelSize(34)
            _big.setWeight(QFont.Bold)
            p.setFont(_big)
            if _stopping:
                # UN SOLO countdown fluido: ancora fotografata all'arrivo
                # meno il NOSTRO orologio (stima d'ingresso esatta al
                # decimo: test 45.99 vs 45.9). NESSUN ri-ancoraggio: verso
                # fine sosta LMU riarma il preventivo della sosta DOPO
                # (~12-14s) e riagganciarlo impallava il conto li' (video
                # + dettato 23/07). L'ancora vive dallo stop al via.
                _rem = max(0.0, getattr(self, "_pit_total0", 0.0)
                           - self._pit_run)
                if _rem > 0.05:
                    p.setPen(QPen(QColor("#ffb020")))       # ambra: lavori
                    _bt = "%.1f" % _rem
                    self._pit_zero_t = None
                else:
                    # lavori finiti e ancora fermo: overtime (semaforo,
                    # penalita' in scomputo, coda in corsia)
                    if getattr(self, "_pit_zero_t", None) is None:
                        self._pit_zero_t = time.monotonic()
                    _ovr = time.monotonic() - self._pit_zero_t
                    if _ovr < 2.0:
                        p.setPen(QPen(QColor("#00e676")))   # verde: via!
                        _bt = "0.0"
                    else:
                        p.setPen(QPen(QColor("#ff2b2b")))
                        _bt = "+%.1f" % _ovr
            else:
                self._pit_zero_t = None
                p.setPen(QPen(QColor(255, 255, 255, 235)))
                _bt = "%.1f" % _tot9
            p.drawText(QRectF(_px0, 112.0, _px1 - _px0, 42.0),
                       Qt.AlignCenter, _bt + "s")
            if _stopping and self._pit_run > 0.2:
                f.setPixelSize(11)
                f.setWeight(QFont.Medium)
                p.setFont(f)
                p.setPen(QPen(QColor(255, 255, 255, 150)))
                p.drawText(QRectF(_px0, 152.0, _px1 - _px0, 14.0),
                           Qt.AlignCenter,
                           "ELAPSED %.1fs" % self._pit_run)
            # scomposizione: solo le voci > 0, dalla piu' pesante
            _LBL = (("ve", "ENERGY"), ("fuel", "FUEL"),
                    ("tires", "TYRES"), ("damage", "DAMAGE"),
                    ("penalties", "PENALTY"), ("brakes", "BRAKES"),
                    ("driverSwap", "DRIVER"), ("brakeDucts", "DUCTS"))
            _parts9 = []
            for _k9, _l9 in _LBL:
                try:
                    _v9 = float(_est9.get(_k9) or 0.0)
                except (TypeError, ValueError):
                    _v9 = 0.0
                if _v9 > 0.05:
                    _parts9.append((_v9, _l9))
            _parts9.sort(reverse=True)
            f.setPixelSize(12)
            f.setWeight(QFont.Medium)
            p.setFont(f)
            _fme = QFontMetricsF(f)
            # sotto l'ELAPSED, staccata (prima pestava su ENERGY)
            _yy9 = 186.0
            for _v9, _l9 in _parts9[:4]:
                p.setPen(QPen(QColor(255, 255, 255, 140)))
                p.drawText(QPointF(_pxc - 62.0, _yy9), self._it9(_l9))
                p.setPen(QPen(QColor(255, 255, 255, 220)))
                _vt9 = "%.1fs" % _v9
                p.drawText(QPointF(_pxc + 62.0
                                   - _fme.horizontalAdvance(_vt9), _yy9),
                           _vt9)
                _yy9 += 17.0
        f.setPixelSize(max(6, int(26 * by)))
        f.setWeight(QFont.Normal)                # hint torna Regular
        p.setFont(f)
        p.setPen(QPen(QColor(255, 255, 255, 180)))
        p.drawText(QRectF(0, y0 + 706 * by, _W, 34 * by),
                   Qt.AlignCenter, "LEFT/RIGHT/UP/DOWN = Move")

    # ── MOD 3: SCHERMATA IMPOSTAZIONI del dash (menu stile DDU) ──
    def _paint_beam_spia(self, p, gy):
        """SPIA FARI: SVG fari_on (verde, dall'utente) / fari_off (grigia
        spenta). Sempre visibile; blink sul lampeggio. Vive anche a
        MOTORE SPENTO (i fari si usano da fermi)."""
        if not hasattr(self, "_svg_fari_on"):
            from PySide6.QtSvg import QSvgRenderer as _QSRf
            _ip9 = _ROOT / "assets" / "icons"
            self._svg_fari_on = _QSRf(str(_ip9 / "fari_on.svg"))
            self._svg_fari_off = _QSRf(str(_ip9 / "fari_off.svg"))
            self._svg_fari_hi = _QSRf(str(_ip9 / "abbaglianti.svg"))
        _bm = getattr(self, "_beam", False)
        _lf = getattr(self, "_light_flash", False)
        # spia FARI = stato FISSO (debounce): mai mossa dai lampeggi
        _bshow = getattr(self, "_beam_steady", _bm)
        _lt9 = (getattr(self, "_lamp_t0", None) is not None
                and time.monotonic() - self._lamp_t0 < 2.5)
        sv = self._svg_fari_on if (_bshow or _lt9) else self._svg_fari_off
        if sv.isValid():
            sv.render(p, QRectF(_W / 2.0 - 156.0, gy - 48.0, 22, 22))
        # spia ABBAGLIANTI: A SE', ACCANTO — durante il lampeggio segue
        # LO STATO REALE dei fari di LMU (accesa quando il gioco li
        # accende), non un timer nostro
        if _lf or _lt9:
            if (_bm or _lt9) and self._svg_fari_hi.isValid():
                self._svg_fari_hi.render(
                    p, QRectF(_W / 2.0 - 184.0, gy - 48.0, 22, 22))
            self.update()          # segue il toggling del gioco

    def _cfg_pull(self):
        """engineer_cfg riletta throttled 1s: serve a MOD 3 (valori menu)
        e a MOD 1 (spia ECO verde quando il risparmio e' attivo)."""
        _now = time.monotonic()
        if _now - self._ap_ts <= 1.0:
            return
        self._ap_ts = _now
        try:
            _ec = engineer_cfg.load()
            self._auto_pit = bool(_ec.get("auto_pit", False))
            self._radio_en = bool(_ec.get("engineer_on", False))
            self._test_mode = _ec.get("test_mode") or None
            self._test_extra = int(_ec.get("test_extra_laps") or 2)
            self._test_min = int(_ec.get("test_race_min") or 60)
            self._eco_free = int(_ec.get("eco_free") or 0)
        except Exception:
            pass

    def _eco_active_laps(self):
        """+N del risparmio attivo (test long run o ECO FREE), 0 se spento."""
        tm = getattr(self, "_test_mode", None)
        if tm == "longrun":
            return getattr(self, "_eco_free", 0) or 2
        if tm == "racesim":
            return -1                    # gestione attiva senza +N
        return getattr(self, "_eco_free", 0)

    def _paint_mod3(self, p):
        FAM = "Archivo SemiExpanded"
        bx = _W / 1334.0
        by = (_H - self.HDR - self.ROW_T - self.ROW_B) / 750.0
        y0 = self.HDR + self.ROW_T
        self._cfg_pull()
        # MENU VERO: voci reali con valore
        _tmv = getattr(self, "_test_mode", None)
        if _tmv == "racesim":
            _tm_lbl = "RACE SIM %d" % getattr(self, "_test_min", 60)
        else:
            _tm_lbl = {None: "OFF", "longrun": "LONG RUN",
                       "hotlap": "HOTLAP"}.get(_tmv, "OFF")
        ITEMS = (("SPEED UNIT",
                  self._prefs.get("speed_unit", "KPH")),
                 ("ELECTRIC CONTROL",
                  "ON" if self._prefs.get("electric_control")
                  else "OFF"),
                 ("AUTO PIT",
                  "ON" if self._auto_pit else "OFF"),
                 ("RADIO",
                  "ON" if self._radio_en else "OFF"),
                 ("TEST MODE", _tm_lbl),
                 ("LICO",
                  ("+%d LAPS" % getattr(self, "_eco_free", 0))
                  if getattr(self, "_eco_free", 0) else "OFF"),
                 ("LIGHTS",
                  "ON" if getattr(self, "_beam_steady", False) else "OFF"),
                 ("WIPER", str(getattr(self, "_wiper9", 0))),
                 ("LANGUAGE",
                  self._prefs.get("dash_lang", "EN")))
        f = QFont(FAM)
        f.setPixelSize(max(6, int(52 * by)))     # piu' GRANDE (rich. 23/07)
        f.setWeight(QFont.Medium)
        p.setFont(f)
        _pitch = 68.0     # 9 righe (LINGUA inclusa) senza sbordare
        lh = _pitch * by
        for i, (it, vv) in enumerate(ITEMS):
            sel = (i == self._m3_sel)
            ry = y0 + (60 + i * _pitch) * by
            if sel:                      # selezione = bg pieno come MOD 2
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(160, 164, 174, 70))
                p.drawRect(QRectF(28 * bx, ry + 4 * by,
                                  1278 * bx, lh - 8 * by))
            p.setPen(QPen(QColor(255, 255, 255, 235)))
            p.drawText(QRectF(48 * bx, ry, 900 * bx, lh),
                       Qt.AlignLeft | Qt.AlignVCenter, self._it9(it))
            _vc3 = QColor(255, 255, 255, 235)
            if i == 4 and vv != "OFF":
                _vc3 = QColor("#2fa8e0")        # TEST: blu
            elif i == 5 and vv != "OFF":
                _vc3 = QColor("#00e676")        # LICO: verde
            # valore + TRIANGOLINI stile LMU sulla voce selezionata
            # (rich. 23/07: come il menu pit del gioco, niente "<>")
            from PySide6.QtGui import QPolygonF as _QPF3
            _vtxt = str(vv)
            _vx1 = 1270.0 * bx                  # bordo destro valori
            _vw3 = QFontMetricsF(f).horizontalAdvance(_vtxt)
            p.setPen(QPen(_vc3))
            p.drawText(QRectF(700 * bx, ry, _vx1 - 700 * bx - 16.0, lh),
                       Qt.AlignRight | Qt.AlignVCenter, _vtxt)
            if sel:
                _cyv = ry + lh / 2.0
                p.setPen(Qt.NoPen)
                p.setBrush(_vc3)
                p.drawPolygon(_QPF3([                 # destra >
                    QPointF(_vx1 - 8.0, _cyv - 5.5),
                    QPointF(_vx1 - 8.0, _cyv + 5.5),
                    QPointF(_vx1, _cyv)]))
                _lx3 = _vx1 - 16.0 - _vw3 - 12.0
                p.drawPolygon(_QPF3([                 # sinistra <
                    QPointF(_lx3 + 8.0, _cyv - 5.5),
                    QPointF(_lx3 + 8.0, _cyv + 5.5),
                    QPointF(_lx3, _cyv)]))
        # TRIANGOLINO GIU' centrato sotto il menu (il giro delle voci
        # continua: stesso segnale del menu pit, rich. 23/07)
        from PySide6.QtGui import QPolygonF as _QPF4
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 150))
        _dx4 = _W / 2.0
        _dy4 = y0 + 680.0 * by
        p.drawPolygon(_QPF4([QPointF(_dx4 - 7.0, _dy4),
                             QPointF(_dx4 + 7.0, _dy4),
                             QPointF(_dx4, _dy4 + 7.0)]))
        f.setPixelSize(max(6, int(26 * by)))
        p.setFont(f)
        p.setPen(QPen(QColor(255, 255, 255, 180)))
        yb = y0 + 706 * by
        # avviso del menu (es. "chiudi LMU prima"), giallo, 5s
        _msg = getattr(self, "_m3_msg", None)
        if _msg and time.monotonic() - _msg[1] < 5.0:
            fm3 = QFont(FAM)
            fm3.setPixelSize(max(6, int(34 * by)))
            p.setFont(fm3)
            p.setPen(QPen(QColor("#ffed00")))
            p.drawText(QRectF(0, y0 + 14 * by, _W, 46 * by),
                       Qt.AlignCenter, _msg[0])
            p.setFont(f)                      # ripristina la legenda
            p.setPen(QPen(QColor(255, 255, 255, 180)))
        # comandi NOSTRI: croce del pad
        p.drawText(QRectF(0, yb, _W, 34 * by), Qt.AlignCenter,
                   "LEFT/RIGHT/UP/DOWN = Move")

    def _paint_spie(self, p, gy):
        """TUTTE le spie del cruscotto (acqua/olio con
        temperature, fari/abbaglianti, tergi, ESP, LIM, benzina,
        motore, gomma, triangolo, freni, MOD/ECO): visibili sia a
        motore acceso che a QUADRO inserito con motore spento —
        come un'auto vera. Solo la marcia resta nascosta da spenti.
        LAMP TEST: nei primi 2.5s dopo il boot tutte accese."""
        _lt = (getattr(self, "_lamp_t0", None) is not None
               and time.monotonic() - self._lamp_t0 < 2.5)
        if _lt:
            self.update()
        # ACQUA e OLIO impilati a SINISTRA in basso: le ICONE PNG di
        # assets/icons (ok normale, warn quando il motore surriscalda)
        try:
            if not hasattr(self, "_px_wat_ok"):
                _ip = _ROOT / "assets" / "icons"
                # ACQUA: SVG nuove dell'utente (warn rossa / ok neutra)
                from PySide6.QtSvg import QSvgRenderer as _QSRw
                self._svg_wat_ok = _QSRw(str(_ip / "acqua_ok.svg"))
                self._svg_wat_wn = _QSRw(str(_ip / "acqua_warn.svg"))
                self._svg_oil_ok = _QSRw(str(_ip / "olio_ok.svg"))
                self._svg_oil_wn = _QSRw(str(_ip / "olio_warn.svg"))
                self._px_wat_ok = True    # sentinella: init fatto
            # spie come il vecchio HUD: acqua >=110, olio >=125
            # (pulsano), warn fisso a motore spento
            _eoff9 = (self._rpm or 0.0) < 50.0
            _wt9 = self._water or 0.0
            _ot9 = self._oil or 0.0
            _pw9 = _wt9 >= 110.0
            _po9 = _ot9 >= 125.0
            wsvg = self._svg_wat_wn if (_pw9 or _eoff9) \
                else self._svg_wat_ok
            osvg = self._svg_oil_wn if (_po9 or _eoff9) \
                else self._svg_oil_ok
            # blocco COMPATTO e ordinato, appoggiato al cerchio:
            # icona 18px + valore 11px, due righe allineate a destra
            f_t = QFont("Archivo SemiExpanded")
            f_t.setPixelSize(11)
            f_t.setWeight(QFont.Bold)     # numeri temperature/fuel BOLD
            p.setFont(f_t)
            p.setPen(QColor(255, 255, 255, 240))
            _xr = _W / 2.0 - 72.0        # bordo destro del blocco
            if wsvg.isValid():
                wsvg.render(p, QRectF(_xr - 44, gy + 18, 18, 18))
            if self._water is not None:
                p.drawText(QRectF(_xr - 40, gy + 18, 44, 18),
                           Qt.AlignRight | Qt.AlignVCenter,
                           "%.0f°C" % self._water)
            if osvg.isValid():
                osvg.render(p, QRectF(_xr - 35, gy + 34, 18, 18))
            if self._oil is not None:
                p.drawText(QRectF(_xr - 29, gy + 34, 44, 18),
                           Qt.AlignRight | Qt.AlignVCenter,
                           "%.0f°C" % self._oil)
            # NUMERO energia/benzina sotto l'olio: BIANCO con l'icona
            # carburante BIANCA a sinistra (rich. 23/07), come acqua/olio
            _bp9 = getattr(self, "_bar_pct9", None)
            if _bp9:
                if not hasattr(self, "_svg_fuel_w9"):
                    try:
                        from PySide6.QtSvg import QSvgRenderer as _QSRf2
                        from PySide6.QtCore import QByteArray as _QBAf2
                        import re as _re2
                        _tf2 = (_ROOT / "assets" / "icons"
                                / "fuel_spia.svg").read_text(
                                    encoding="utf-8")
                        _tf2 = _re2.sub(r"#[0-9a-fA-F]{6}",
                                        "#ffffff", _tf2)
                        self._svg_fuel_w9 = _QSRf2(_QBAf2(_tf2.encode()))
                    except Exception:
                        self._svg_fuel_w9 = None
                if getattr(self, "_svg_fuel_w9", None) is not None:
                    self._svg_fuel_w9.render(
                        p, QRectF(_xr - 27, gy + 51, 16, 16))
                p.setPen(QColor(255, 255, 255, 240))
                p.drawText(QRectF(_xr - 21, gy + 50, 44, 18),
                           Qt.AlignRight | Qt.AlignVCenter,
                           "%d" % _bp9[0])
        except Exception:
            pass
        # SPIE a destra del cerchio (speculari ad acqua/olio):
        # - MOD gialla: test attivo (1=long run, 2=race sim, 3=hotlap),
        #   OFF in giallo tenue quando nessun test gira
        # - ECO verde: risparmio attivo (long run / race sim / ECO FREE)
        try:
            self._cfg_pull()
            # STRATO BASE: tutte le icone della fila SEMPRE visibili in
            # grigio spento; le accese si disegnano sopra a colore (i
            # lampeggi alternano colore/grigio, da cruscotto vero)
            if not hasattr(self, "_svg_offmap"):
                from PySide6.QtSvg import QSvgRenderer as _QSRo
                _ipo = _ROOT / "assets" / "icons"
                self._svg_offmap = {
                    nm0: _QSRo(str(_ipo / (nm0 + "_off.svg")))
                    for nm0 in ("fuel_spia", "pit_limiter", "abbaglianti",
                                "esp_tc", "engine_warn", "tyre_warn",
                                "warning_light", "freni_warn", "batteria",
                                "eco_spia", "abs_spia",
                                "freccia_sx", "freccia_dx")}
            for _nm0, _dx0 in (("fuel_spia", -100.0),
                               ("pit_limiter", -128.0),
                               ("abbaglianti", -184.0),
                               ("esp_tc", -212.0),
                               ("engine_warn", 78.0),
                               ("tyre_warn", 106.0),
                               ("warning_light", 134.0),
                               ("freni_warn", 162.0),
                               ("batteria", 190.0),
                               ("abs_spia", 218.0),
                               ("freccia_sx", -268.0),
                               ("freccia_dx", 246.0)):
                _r0 = self._svg_offmap.get(_nm0)
                if _r0 is not None and _r0.isValid():
                    _r0.render(p, QRectF(_W / 2.0 + _dx0, gy - 48.0,
                                         22, 22))
            f_e = QFont("Archivo SemiExpanded")
            f_e.setPixelSize(12)
            f_e.setBold(True)
            p.setFont(f_e)
            _xl = _W / 2.0 + 66.0
            _tmv = getattr(self, "_test_mode", None)
            _mn = {"longrun": "MOD 1", "racesim": "MOD 2",
                   "hotlap": "MOD 3"}.get(_tmv)
            _rm = QRectF(_xl, gy + 20, 62, 19)
            if _mn:
                _yc = QColor("#b06bff")            # test = VIOLA
                p.setPen(QPen(_yc, 1.4))
                p.setBrush(QColor(46, 26, 74, 150))
                p.drawRoundedRect(_rm, 4, 4)
                p.setPen(QPen(_yc))
                p.drawText(_rm, Qt.AlignCenter, _mn)
            else:
                # spia SPENTA: grigia tenue, testo piccolo (rich. 23/07)
                _gd = QColor(150, 156, 168, 110)
                p.setPen(QPen(_gd, 1.0))
                p.setBrush(QColor(30, 34, 40, 80))
                p.drawRoundedRect(_rm, 4, 4)
                p.setFont(f_e)          # STESSO font da acceso e spento
                p.setPen(QPen(_gd))
                p.drawText(_rm, Qt.AlignCenter, "MOD 0")
            # SPIA "SC" (mappa motore 0 = safety car map) nello slot
            # che era dell'ECO: ambra fissa quando sei in mappa 0
            _map0 = (getattr(self, "_mmap", None) == 0)
            _rsc = QRectF(_xl + 66, gy + 20, 34, 19)
            if _map0 or _lt:
                p.setPen(QPen(QColor("#ffb020"), 1.4))
                p.setBrush(QColor(70, 48, 8, 150))
                p.drawRoundedRect(_rsc, 4, 4)
                p.setFont(f_e)                     # stesso font del MOD
                p.setPen(QPen(QColor("#ffb020")))
                p.drawText(_rsc, Qt.AlignCenter, "SC")
            else:
                # SC SPENTA: grigia, stesso font (come MOD 0 / LICO)
                _gds = QColor(150, 156, 168, 110)
                p.setPen(QPen(_gds, 1.0))
                p.setBrush(QColor(30, 34, 40, 80))
                p.drawRoundedRect(_rsc, 4, 4)
                p.setFont(f_e)
                p.setPen(QPen(_gds))
                p.drawText(_rsc, Qt.AlignCenter, "SC")
            _en = self._eco_active_laps()
            if _lt and not _en:
                _en = -1                    # lamp test: icona accesa
            _rl0 = QRectF(_W / 2.0 - 134.0, gy - 12.0, 64, 19)
            if not _en:
                # chip LICO SPENTO: grigio tenue come MOD OFF
                _gd0 = QColor(150, 156, 168, 110)
                p.setPen(QPen(_gd0, 1.0))
                p.setBrush(QColor(30, 34, 40, 80))
                p.drawRoundedRect(_rl0, 4, 4)
                p.setFont(f_e)          # STESSO font da acceso e spento
                p.setPen(QPen(_gd0))
                p.drawText(_rl0, Qt.AlignCenter, "LICO")
            if _en:
                # chip LICO ACCESO: come SC ma VERDE
                _gc0 = QColor("#00e676")
                p.setPen(QPen(_gc0, 1.4))
                p.setBrush(QColor(10, 58, 32, 150))
                p.drawRoundedRect(_rl0, 4, 4)
                p.setFont(f_e)                     # stesso font del MOD
                p.setPen(QPen(_gc0))
                p.drawText(_rl0, Qt.AlignCenter,
                           "LICO +%d" % _en if _en > 0 else "LICO")
            self._paint_beam_spia(p, gy)
            # SPIA PIT LIMITER (icona utente LIM): FISSA col
            # limitatore inserito, accanto ai fari
            if getattr(self, "_limiter", False) or _lt:
                if not hasattr(self, "_svg_lim9"):
                    from PySide6.QtSvg import QSvgRenderer as _QSRl
                    self._svg_lim9 = _QSRl(
                        str(_ROOT / "assets" / "icons" / "pit_limiter.svg"))
                if self._svg_lim9.isValid():
                    self._svg_lim9.render(
                        p, QRectF(_W / 2.0 - 128.0, gy - 48.0, 22, 22))
            # SPIA BENZINA (icona utente): autonomia sotto i 2 giri
            # (stessa soglia/isteresi del cerchio), fissa gialla
            if getattr(self, "_fuel_low", False) or _lt:
                if not hasattr(self, "_svg_fuel9"):
                    from PySide6.QtSvg import QSvgRenderer as _QSRu
                    self._svg_fuel9 = _QSRu(
                        str(_ROOT / "assets" / "icons" / "fuel_spia.svg"))
                if self._svg_fuel9.isValid():
                    self._svg_fuel9.render(
                        p, QRectF(_W / 2.0 - 100.0, gy - 48.0, 22, 22))
            # SPIA TERGI (PNG originali): logica V2 dell'IconBar —
            # motore spento wiper_0, >=3 fast, >=1 slow, 0 off
            if not hasattr(self, "_px_wip9"):
                _ipt = _ROOT / "assets" / "icons"
                self._px_wip9 = {k9: QPixmap(str(_ipt / ("wiper_%s.png" % k9)))
                                 for k9 in ("0", "slow", "fast", "off")}
            _wp9 = getattr(self, "_wiper9", 0)
            if _lt:
                _wk9 = "fast"
            elif (self._rpm or 0.0) < 50.0:
                _wk9 = "0"
            elif _wp9 >= 3:
                _wk9 = "fast"
            elif _wp9 >= 1:
                _wk9 = "slow"
            else:
                _wk9 = "off"
            p.drawPixmap(QRectF(_W / 2.0 - 240.0, gy - 48.0,
                                22, 22).toRect(), self._px_wip9[_wk9])
            # SPIA ESP/TC (icona utente): sfarfalla quando il controllo
            # trazione sta intervenendo, come su una stradale
            if getattr(self, "_tc_on", False) or _lt:
                if not hasattr(self, "_svg_esp9"):
                    from PySide6.QtSvg import QSvgRenderer as _QSRz
                    self._svg_esp9 = _QSRz(
                        str(_ROOT / "assets" / "icons" / "esp_tc.svg"))
                if (time.monotonic() % 0.3) < 0.18 \
                        and self._svg_esp9.isValid():
                    self._svg_esp9.render(
                        p, QRectF(_W / 2.0 - 212.0, gy - 48.0, 22, 22))
                self.update()          # sfarfallio fluido
            # ── gruppo spie DESTRO (icone utente), da dentro a fuori:
            # MOTORE rossa (surriscaldo/danno), GOMMA TPMS (forata/persa),
            # TRIANGOLO (sospensione GRAVE >=50%)
            if not hasattr(self, "_svg_warn9"):
                from PySide6.QtSvg import QSvgRenderer as _QSRt
                _ipw = _ROOT / "assets" / "icons"
                self._svg_warn9 = _QSRt(str(_ipw / "warning_light.svg"))
                self._svg_tyre9 = _QSRt(str(_ipw / "tyre_warn.svg"))
                self._svg_eng9 = _QSRt(str(_ipw / "engine_warn.svg"))
            _blk9 = _lt or (time.monotonic() % 0.8) < 0.5
            if getattr(self, "_overheat", False) or _lt:
                if _blk9 and self._svg_eng9.isValid():
                    self._svg_eng9.render(
                        p, QRectF(_W / 2.0 + 78.0, gy - 48.0, 22, 22))
                self.update()
            if (_lt or any(getattr(self, "_flat4", None) or [])
                    or any(getattr(self, "_det4", None) or [])):
                if _blk9 and self._svg_tyre9.isValid():
                    self._svg_tyre9.render(
                        p, QRectF(_W / 2.0 + 106.0, gy - 48.0, 22, 22))
                self.update()
            _ws9 = getattr(self, "_wsusp", None) or []
            if _lt or any(v is not None and v >= 0.5 for v in _ws9):
                if _blk9 and self._svg_warn9.isValid():
                    self._svg_warn9.render(
                        p, QRectF(_W / 2.0 + 134.0, gy - 48.0, 22, 22))
                self.update()          # lampeggio fluido
            # SPIA FRENI (icona utente): oltre il limite di classe
            # (650 acciaio GT / 750 carbonio HY-P2-P3, soglie del doc)
            _bk4s = getattr(self, "_brk4", None) or []
            _carb9 = (getattr(self, "_cls_name", "") or "").upper()
            _blim9 = 750.0 if any(k9 in _carb9 for k9 in
                                  ("HYPER", "LMH", "LMDH", "LMP", "P2",
                                   "P3")) else 650.0
            if _lt or (_bk4s and max(_bk4s) >= _blim9):
                if not hasattr(self, "_svg_brk9"):
                    from PySide6.QtSvg import QSvgRenderer as _QSRb
                    self._svg_brk9 = _QSRb(
                        str(_ROOT / "assets" / "icons" / "freni_warn.svg"))
                if _blk9 and self._svg_brk9.isValid():
                    self._svg_brk9.render(
                        p, QRectF(_W / 2.0 + 162.0, gy - 48.0, 22, 22))
                self.update()
            # SPIA ABS (icona utente): sfarfalla con l'intervento
            if getattr(self, "_abs_on", False) or _lt:
                if not hasattr(self, "_svg_abs9"):
                    from PySide6.QtSvg import QSvgRenderer as _QSRa
                    self._svg_abs9 = _QSRa(
                        str(_ROOT / "assets" / "icons" / "abs_spia.svg"))
                if (_lt or (time.monotonic() % 0.3) < 0.18)                         and self._svg_abs9.isValid():
                    self._svg_abs9.render(
                        p, QRectF(_W / 2.0 + 218.0, gy - 48.0, 22, 22))
                self.update()
            # FRECCE HAZARD agli estremi: pit limiter O fermo >5s in pista
            if (getattr(self, "_limiter", False)
                    or getattr(self, "_hazard9", False) or _lt):
                if not hasattr(self, "_svg_fsx9"):
                    from PySide6.QtSvg import QSvgRenderer as _QSRf9
                    _ipf = _ROOT / "assets" / "icons"
                    self._svg_fsx9 = _QSRf9(str(_ipf / "freccia_sx.svg"))
                    self._svg_fdx9 = _QSRf9(str(_ipf / "freccia_dx.svg"))
                # IN FASE con la fila RPM arancione del limiter
                if (_lt or int(time.monotonic() * 2) % 2 == 0):
                    if self._svg_fsx9.isValid():
                        self._svg_fsx9.render(
                            p, QRectF(_W / 2.0 - 268.0, gy - 48.0, 22, 22))
                    if self._svg_fdx9.isValid():
                        self._svg_fdx9.render(
                            p, QRectF(_W / 2.0 + 246.0, gy - 48.0, 22, 22))
                self.update()
            # batteria nel LAMP TEST (di norma vive nel check da spenti)
            if _lt:
                if not hasattr(self, "_svg_batt9"):
                    from PySide6.QtSvg import QSvgRenderer as _QSRbt
                    self._svg_batt9 = _QSRbt(
                        str(_ROOT / "assets" / "icons" / "batteria.svg"))
                if self._svg_batt9.isValid():
                    self._svg_batt9.render(
                        p, QRectF(_W / 2.0 + 190.0, gy - 48.0, 22, 22))
        except Exception:
            pass

    # ── MOD 1: DASHBOARD DDU (dal pack "BMW M4 GT3 Borsh DDU10") ──
    # Geometria TRASPOSTA dal .djson originale (tela 1334x750 -> corpo
    # card), font CP Mono del pack. Colori nostri: nero -> trasparente
    # (resta il navy della card), arancione -> bianco 90%; le celle
    # piene hanno i numeri "in negativo" col navy. Dato assente = tace.
    def _paint_mod1(self, p):
        # (corrente/boot gestiti a monte in _paint_page)
        # DASH: SOLO il tachimetro NEON al centro (il gear 2024 e'
        # stato rimosso il 21/07).
        # Il codice sotto il return resta come riferimento, non gira.
        gy = self.HDR + self.ROW_T \
            + (_H - self.HDR - self.ROW_T - self.ROW_B) / 2.0 - 44.0
        # fila regolazioni (MapBar del vecchio HUD) sopra l'ultima riga
        self._paint_ctrl_row(p)
        # MOTORE SPENTO (rpm a zero): LOGO AUTO che resta + scritte sotto
        if self._rpm is not None and self._rpm < 1.0:
            # il gauge qui NON viene disegnato: azzera il flag motore,
            # senno' alla riaccensione la transizione non scatta e il
            # fade in MOD 1 non parte MAI (bug segnalato 23/07)
            self._eng_on_prev = False
            _lcy = (self.HDR + _H) / 2.0 - 26.0        # STESSA posizione del boot
            _lh = self._draw_car_logo(p, _W / 2.0, _lcy, 72.0)
            _oy = _lcy + (_lh or 40.0) / 2.0 + 12.0    # sotto il logo
            f_off = QFont("Archivo SemiExpanded")
            f_off.setPixelSize(20)
            p.setFont(f_off)
            p.setPen(QPen(QColor(255, 45, 45)))
            p.drawText(QRectF(0, _oy, _W, 28), Qt.AlignCenter,
                       "ENGINE OFF")
            if not self._is_gt3 and self._erpm > 10.0:
                f_off.setPixelSize(15)
                p.setFont(f_off)
                p.setPen(QPen(QColor(0, 220, 90)))
                p.drawText(QRectF(0, _oy + 28.0, _W, 24),
                           Qt.AlignCenter, "E-MOTOR ON")
            # QUADRO inserito, motore spento: TUTTE le spie visibili
            # (auto vera); in piu' BATTERIA e MOTORE fisse accese
            self._paint_spie(p, gy)
            try:
                # QUADRO inserito, motore spento: spie BATTERIA e MOTORE
                # accese fisse come su un'auto vera; si spengono
                # all'avviamento (il ramo live non le disegna)
                from PySide6.QtSvg import QSvgRenderer as _QSRbt
                _ipb = _ROOT / "assets" / "icons"
                if not hasattr(self, "_svg_batt9"):
                    self._svg_batt9 = _QSRbt(str(_ipb / "batteria.svg"))
                if not hasattr(self, "_svg_engoff9"):
                    self._svg_engoff9 = _QSRbt(
                        str(_ipb / "engine_warn.svg"))
                if self._svg_engoff9.isValid():
                    self._svg_engoff9.render(
                        p, QRectF(_W / 2.0 + 78.0, gy - 48.0, 22, 22))
                # FRENI accesi fissi nel check (auto vera: batteria +
                # motore + olio + freni a quadro inserito)
                if not hasattr(self, "_svg_brk9"):
                    from PySide6.QtSvg import QSvgRenderer as _QSRb
                    self._svg_brk9 = _QSRb(
                        str(_ROOT / "assets" / "icons" / "freni_warn.svg"))
                if self._svg_brk9.isValid():
                    self._svg_brk9.render(
                        p, QRectF(_W / 2.0 + 162.0, gy - 48.0, 22, 22))
                if self._svg_batt9.isValid():
                    # slot TUTTO SUO (+162, dopo i freni): mai sovrapposta
                    self._svg_batt9.render(
                        p, QRectF(_W / 2.0 + 190.0, gy - 48.0, 22, 22))
            except Exception:
                pass
            return
        self._gauge_with_fade(p, _W / 2.0, gy, 56.0, show_gear=True)
        self._paint_spie(p, gy)
        return
        gx = 110.0
        gr = 30.0
        now = time.monotonic()
        t = (now - self._gear_t0) / 0.55 if self._gear_t0 else 2.0
        g = self._gear or 0
        up = g > self._gear_old
        GAP_C, GAP_W = 90.0, 55.0
        p.setPen(QPen(QColor(255, 255, 255, 235), 2))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(gx - gr, gy - gr, gr * 2, gr * 2),
                  int((GAP_C + GAP_W / 2.0) * 16),
                  int((360.0 - GAP_W) * 16))
        if t < 1.0:
            ang = GAP_C - 360.0 * t if up else GAP_C + 360.0 * t
            col = QColor("#3FE05A") if up else QColor("#FF3B30")
            span, seg_r, seg_w = 32.0, gr + 5.0, 4.0
            if t > 0.8:
                k = (t - 0.8) / 0.2
                col = QColor(int(col.red() + (255 - col.red()) * k),
                             int(col.green() + (255 - col.green()) * k),
                             int(col.blue() + (255 - col.blue()) * k))
                seg_r = gr + 5.0 * (1.0 - k)
                seg_w = 4.0 - 1.0 * k
                span = 32.0 + 8.0 * k
        else:
            ang, col = GAP_C, QColor(255, 255, 255, 245)
            span, seg_r, seg_w = 40.0, gr, 3.0
        p.setPen(QPen(col, seg_w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(gx - seg_r, gy - seg_r, seg_r * 2, seg_r * 2),
                  int((ang - span / 2.0) * 16), int(span * 16))

        def _gsym(gv):
            return "R" if gv < 0 else ("N" if gv == 0 else str(gv))

        f_gear = QFont("Archivo SemiExpanded", 34)
        f_gear.setWeight(QFont.Black)     # marcia principale EXTRA bold
        p.setFont(f_gear)
        fg = QFontMetricsF(f_gear)
        ts = (now - self._gear_t0) / 0.25 if self._gear_t0 else 2.0
        p.setPen(QColor(255, 255, 255, 245))
        if ts < 1.0:
            shown = _gsym(self._gear_old if ts < 0.5 else g)
            sy = max(0.08, abs(1.0 - 2.0 * ts))
            p.save()
            p.translate(gx, gy)
            p.scale(1.0, sy)
            p.drawText(QPointF(-fg.horizontalAdvance(shown) / 2.0,
                               fg.ascent() / 2.0 - 4), shown)
            p.restore()
        else:
            gear = _gsym(g)
            p.drawText(QPointF(gx - fg.horizontalAdvance(gear) / 2.0,
                               gy + fg.ascent() / 2.0 - 4), gear)
        f_gl = QFont("Archivo SemiExpanded", 13)
        f_gl.setWeight(QFont.DemiBold)
        f_gl.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f_gl)
        fl = QFontMetricsF(f_gl)
        p.setPen(QColor(219, 216, 214, 235))
        p.drawText(QPointF(gx - fl.horizontalAdvance("GEAR") / 2.0,
                           gy + gr + 22), "GEAR")
        if t >= 1.0 and ts >= 1.0 and self._gear_t.isActive():
            self._gear_t.stop()      # animazione finita: timer a riposo
        return

    def _save_prefs(self):
        try:
            (USER_DIR / "wec26mfd_prefs.json").write_text(
                json.dumps(self._prefs), encoding="utf-8")
        except Exception:
            pass

    def _write_ghost_binds(self):
        """Scrive i 18 bind elettronica nel keyboard.json di LMU
        (SOLO a gioco chiuso; backup se manca). Ritorna True se ok."""
        BINDS = {
            "Increment Motor Map": 71, "Decrement Motor Map": 72,
            "Traction Control Up": 73, "Traction Control Down": 74,
            "Traction Control Slip Angle Up": 75,
            "Traction Control Slip Angle Down": 76,
            "Traction Control 2 Up": 77,
            "Traction Control 2 Down": 78,
            "Antilock Brake System Up": 79,
            "Antilock Brake System Down": 80,
            "Bias Forward": 81, "Bias Rearward": 82,
            "Inc Front ARB": 83, "Dec Front ARB": 55,
            "Inc Rear ARB": 70, "Dec Rear ARB": 41,
            "Brake Migration Forward": 43,
            "Brake Migration Rearward": 86,
            "Headlights": 39,
            "Increment Wipers": 51, "Decrement Wipers": 52,
            "Increment Windscreen Wipers": 51,
            "Decrement Windscreen Wipers": 52,
        }
        try:
            import shutil
            f = Path(r"C:\program files (x86)\steam\steamapps\common"
                     r"\Le Mans Ultimate\UserData\player"
                     r"\keyboard.json")
            if not f.exists():
                return False
            bak = f.with_suffix(".json.bak_telemetrypro")
            if not bak.exists():
                shutil.copy2(f, bak)
            d = json.loads(f.read_text(encoding="utf-8"))
            d.setdefault("Input", {}).update(BINDS)
            f.write_text(json.dumps(d, indent=2, ensure_ascii=False),
                         encoding="utf-8")
            self._bind_codes = {i: (BINDS[nu], BINDS[nd])
                                for i, (nu, nd)
                                in self._BIND_NAMES.items()}
            return True
        except Exception:
            return False

    def _paint_ctrl_row(self, p):
        """Caselle regolazioni del vecchio HUD (MapBar): MAP TC SLIP
        CUT ABS BIAS ARB-F ARB-R MIG — flash BLU quando cambiano."""
        def _s(v):
            return "-" if v is None else str(v)

        items = (("MAP", _s(getattr(self, "_mmap", None))),
                 ("TC", _s(self._tc)),
                 ("SLIP", _s(getattr(self, "_tcslip", None))),
                 ("CUT", _s(getattr(self, "_tccut", None))),
                 ("ABS", _s(self._abs)),
                 ("BIAS", ("%.1f" % self._bbias)
                  if self._bbias is not None else "-"),
                 ("ARB-F", _s(getattr(self, "_arbf", None))),
                 ("ARB-R", _s(getattr(self, "_arbr", None))),
                 ("MIG", _s(getattr(self, "_mig", None))))
        now = time.monotonic()
        if not hasattr(self, "_ctrl_prev"):
            self._ctrl_prev = {}
            self._ctrl_flash = {}
        # selezione: sparisce da sola dopo 6s di inattivita'
        if self._ctrl_sel is not None \
                and now - self._ctrl_sel_t > 6.0:
            self._ctrl_sel = None
        n = len(items)
        gap = 6.0
        x0 = 14.0
        bw = (_W - 28.0 - gap * (n - 1)) / n
        y = _H - self.ROW_B - 42.0
        bh = 36.0
        # celle pulite: niente bordi ne' bg (solo flash e selezione)
        f_l = QFont("Archivo SemiExpanded")
        for i, (lbl, val) in enumerate(items):
            # BIAS: la migration lo muove DA SOLA a ogni frenata —
            # confronto a passi di 0.5 e MAI popup centrale (era il
            # flash continuo che copriva il FUEL)
            _cmp = val
            if lbl == "BIAS":
                try:
                    _cmp = "%d" % round(float(val) * 2.0)
                except (TypeError, ValueError):
                    pass
            pv = self._ctrl_prev.get(lbl)
            # NIENTE flash al primo popolamento ("-" -> valore vero
            # all'avvio: era il lampo blu su tutte le celle, rich. 23/07)
            if pv is not None and pv != _cmp and pv != "-":
                self._ctrl_flash[lbl] = now
                if lbl != "BIAS":
                    self._ctrl_popup = (lbl, val, now)
            self._ctrl_prev[lbl] = _cmp
            hot = now - self._ctrl_flash.get(lbl, -9.0) < 1.0
            rx = x0 + i * (bw + gap)
            rr = QRectF(rx, y, bw, bh)
            if hot:
                # flash: lo STESSO blu del cerchio cambio-dato
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(18, 64, 200))
                p.drawRect(rr)
            # SELEZIONE: quadratino grigio pieno come MOD 2/3
            _sel9 = (i == self._ctrl_sel)
            if _sel9:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(160, 164, 174, 70))
                p.drawRect(rr)
            # BOLD nomi e numeri: il font fino sgranava (rich. 23/07)
            f_l.setPixelSize(8)
            f_l.setWeight(QFont.Bold)
            p.setFont(f_l)
            p.setPen(QColor(255, 255, 255, 200))
            p.drawText(QRectF(rx, y + 3, bw, 10), Qt.AlignCenter, lbl)
            f_l.setPixelSize(15)
            p.setFont(f_l)
            p.setPen(QColor(255, 255, 255, 245))
            p.drawText(QRectF(rx, y + 13, bw, 21), Qt.AlignCenter, val)

    def _gauge_with_fade(self, p, cx, cy, r, show_gear=True):
        """Regola MOTORE per il gauge (mod 1 e 2): spento = non appare;
        all'accensione riappare subito ma con fade morbido (~0.35s)."""
        _eon = (self._rpm or 0.0) >= 50.0
        _nowf = time.monotonic()
        if _eon and not getattr(self, "_eng_on_prev", False):
            self._ign_fade_t0 = _nowf
        self._eng_on_prev = _eon
        if not _eon:
            return
        _ft = (_nowf - getattr(self, "_ign_fade_t0", 0.0)) / 0.5
        if _ft < 1.0:
            p.save()
            p.setOpacity(max(0.05, min(1.0, _ft)))
            self._paint_neon_gauge(p, cx, cy, r, show_gear=show_gear)
            p.restore()
            self.update()          # frame successivo del fade
        else:
            self._paint_neon_gauge(p, cx, cy, r, show_gear=show_gear)

    def _paint_neon_gauge(self, p, cx, cy, r, show_gear=True):
        """Tachimetro NEON: disco di fondo, tacche, arco RPM fluido
        (valori AMMORBIDITI frame per frame: il dato arriva a scatti,
        il video no), punta luminosa e velocita' grande al centro."""
        import math
        # smoothing: insegue il dato vero ad ogni frame (33ms)
        _tr = self._rpm or 0.0
        _dr = getattr(self, "_rpm_disp", 0.0)
        self._rpm_disp = _dr + (_tr - _dr) * 0.25
        _tv = self._speed or 0.0
        _dv = getattr(self, "_spd_disp", 0.0)
        self._spd_disp = _dv + (_tv - _dv) * 0.30
        rpm = self._rpm_disp
        top = self._maxrpm or 0.0
        peak = self._shift_peak
        limit = peak if (top and peak >= top * 0.85) else (top or 1.0)
        frac = max(0.0, min(1.0, rpm / limit)) if limit > 0 else 0.0
        a0, sweep = 45.0, 270.0     # ruotato 180: varco in ALTO
        # disco di fondo (dissolve ai bordi)
        g0 = QRadialGradient(QPointF(cx, cy), r * 1.35)
        g0.setColorAt(0.0, QColor(14, 20, 27, 235))
        g0.setColorAt(0.75, QColor(14, 20, 27, 160))
        g0.setColorAt(1.0, QColor(14, 20, 27, 0))
        p.setBrush(g0)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), r * 1.35, r * 1.35)
        # binario scuro: CERCHIO PERFETTO chiuso (niente varco)
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(26, 34, 44), 3.0))
        p.drawEllipse(rect)
        # DOPPIO cerchio: anello esterno a 4 SPICCHI STACCATI
        # (le tre parti + quella che mancava sopra)
        r2 = r + 7.0
        rect2 = QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2)
        p.setPen(QPen(QColor(26, 34, 44), 3.0,
                      Qt.SolidLine, Qt.RoundCap))
        for _a2 in (49, -41, 139, 229):
            p.drawArc(rect2, int(_a2 * 16), int(82 * 16))
        # PEDALI sugli spicchi laterali (fluidi): DX = acceleratore
        # verde, SX = freno rosso — si riempiono dal basso
        _tt = self._thr_in or 0.0
        _bb = (self._brake_in or 0.0) / 100.0
        _td = getattr(self, "_thr_disp", 0.0)
        self._thr_disp = _td + (_tt - _td) * 0.55
        _bd = getattr(self, "_brk_disp", 0.0)
        self._brk_disp = _bd + (_bb - _bd) * 0.55
        if self._thr_disp > 0.01:
            p.setPen(QPen(QColor("#00e676"), 3.0,
                          Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect2, int(-41 * 16),
                      int(82 * min(1.0, self._thr_disp) * 16))
        if self._brk_disp > 0.01:
            p.setPen(QPen(QColor("#ff3b30"), 3.0,
                          Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect2, int(221 * 16),
                      int(-82 * min(1.0, self._brk_disp) * 16))
        # spicchio in BASSO: energia virtuale BLU; se l'auto e' solo
        # benzina (P2/P3/GTE: niente VE) barra ROSA sul carburante.
        # Si esaurisce verso sinistra.
        # VE con TENUTA anti-glitch: se la shm sputa uno 0 per un
        # frame, tieni l'ultimo valore buono per 2s (era il flash)
        _ve9 = self._ve_pct2 or 0.0
        _nw9 = time.monotonic()
        if _ve9 > 0.0:
            self._ve_ok = _ve9
            self._ve_ok_t = _nw9
        elif _nw9 - getattr(self, "_ve_ok_t", -9.0) < 2.0:
            _ve9 = getattr(self, "_ve_ok", 0.0)
        if _ve9 > 0.0:
            _vef = max(0.0, min(1.0, _ve9 / 100.0))
            _cbar = QColor("#2979ff")
        elif self._fuel_l is not None and self._fuel_max > 0:
            _vef = max(0.0, min(1.0, self._fuel_l / self._fuel_max))
            _cbar = QColor("#ff6ec7")
        else:
            _vef = 0.0
            _cbar = None
        # ROSSA sotto 2 GIRI di autonomia (soglia alla TinyPedal),
        # con ISTERESI: entra sotto 2.0, esce sopra 2.2
        _laps9 = None
        _plm9 = getattr(self, "_pl_menu", None)
        if _ve9 > 0.0 and _plm9:
            _laps9 = _ve9 / _plm9
        elif self._fuel_l is not None and self._lap_use:
            _laps9 = self._fuel_l / self._lap_use
        _thr9 = 2.2 if getattr(self, "_fuel_low", False) else 2.0
        self._fuel_low = (_laps9 is not None and _laps9 < _thr9)
        self._dbg_laps = _laps9
        self._dbg_ve = _ve9
        if self._fuel_low:
            _cbar = QColor("#ff2a1f")
        if _vef > 0.005 and _cbar is not None:
            p.setPen(QPen(_cbar, 3.0, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect2, int(229 * 16), int(82 * _vef * 16))
        # NUMERO energia/benzina (senza %) sotto la temperatura OLIO
        # nel blocco a sinistra (rich. 23/07): qui salvo valore+colore,
        # lo disegna il blocco acqua/olio che conosce le sue coordinate
        self._bar_pct9 = (round(_vef * 100), _cbar) \
            if (_cbar is not None and _vef > 0.0) else None
        # SOC nel SEMICERCHIO ALTO (il varco vuoto del gauge, rich.
        # 23/07): carica batteria ibrida — VERDE quando rigenera,
        # AMBRA quando scarica (boost), BIANCO neutro. Solo se l'auto
        # ha la batteria (HY); sulle altre resta vuoto com'era.
        _soc9 = float(getattr(self, "_batt9", 0.0) or 0.0)
        _emo = int(getattr(self, "_emo9", 0) or 0)
        if _soc9 > 0.001 or _emo >= 2:
            # varco: 55 gradi centrati in alto (90) — sfondo tenue
            p.setPen(QPen(QColor(255, 255, 255, 45), 3.0,
                          Qt.SolidLine, Qt.FlatCap))
            p.drawArc(rect2, int(117.5 * 16), int(-55 * 16))
            _csoc = QColor(255, 255, 255, 235)      # neutro
            if _emo == 3:
                _csoc = QColor("#00e676")           # rigenera
            elif _emo == 2:
                _csoc = QColor("#ffb020")           # scarica (boost)
            p.setPen(QPen(_csoc, 3.0, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect2, int(117.5 * 16),
                      int(-55 * max(0.0, min(1.0, _soc9)) * 16))
        # RPM: arco sul lato SINISTRO in basso (meno di mezzo cerchio),
        # parte dal fondo e sale a sinistra — BLU che sfuma al BIANCO
        # (arco RPM RIMOSSO il 21/07: resta solo l'effetto cambiata)
        # CAMBIATA: la luce fa il GIRO COMPLETO del cerchio —
        # ORARIO a salire, ANTIORARIO a scalare
        tsh = (time.monotonic() - self._gear_t0) / 0.35 \
            if self._gear_t0 else 2.0
        if tsh < 1.0:
            up9 = (self._gear or 0) > self._gear_old
            ang9 = -90.0 - 360.0 * tsh if up9 else -90.0 + 360.0 * tsh
            span9 = 42.0
            _cb = (63, 224, 90) if up9 else (255, 59, 48)
            for _w9, _a9 in ((12.0, 30), (7.0, 80), (3.0, 230)):
                p.setPen(QPen(QColor(*_cb, _a9), _w9,
                              Qt.SolidLine, Qt.RoundCap))
                p.drawArc(rect, int((ang9 - span9 / 2.0) * 16),
                          int(span9 * 16))
        elif self._gear_t.isActive():
            self._gear_t.stop()
        # SLITTAMENTO (metodo TinyPedal: slip ratio >= 0.10):
        # l'anello lampeggia BLU veloce
        _slip = ((self._wslip or 0.0) >= 0.10
                 and (self._speed or 0.0) > 18.0)
        if _slip and int(time.monotonic() * 8) % 2 == 0:
            for _w9, _a9 in ((6.0, 70), (3.0, 220)):
                p.setPen(QPen(QColor(255, 45, 45, _a9), _w9))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(rect)
        # (arco RPM neon RIMOSSO il 21/07: resta il binario pulito)
        # ── MARCIA dentro il cerchio (Bebas, con roll di cambiata) ──
        def _gsym(gv):
            return "R" if gv < 0 else ("N" if gv == 0 else str(gv))

        g = self._gear or 0
        now = time.monotonic()
        # popup CAMBIO REGOLAZIONE: la marcia si fa piccola e sale
        # (fade), la meta' BASSA del cerchio mostra il dato cambiato
        _pu = getattr(self, "_ctrl_popup", None)
        _pua = (now - _pu[2]) if _pu else 99.0
        # stato AMMORBIDITO: si rimpicciolisce UNA volta e resta giu'
        # finche' continui a cambiare (ogni cambio rinfresca il blu);
        # torna su solo quando il blu muore
        _lim9 = getattr(self, "_limiter", False)
        _fl9 = bool(getattr(self, "_fuel_low", False))
        # ── SCALA PRIORITA' (dal piu' DEBOLE al piu' FORTE):
        # PIT < GREEN < FINISH < elettronica < FUEL < BLU classe
        # < PENALITA' < GIALLA coi metri ──
        fl9d = self._flags9 or {}
        _state9 = None                 # (bg, testo, colore testo)
        if _lim9:
            _state9 = (QColor(255, 122, 0), "PIT",
                       QColor(255, 255, 255))
        if now - getattr(self, "_green_t", -99.0) < 5.0:
            _state9 = (QColor(0, 168, 80), "GREEN",
                       QColor(255, 255, 255))
        if fl9d.get("checkered"):
            _state9 = (QColor(240, 240, 240), "FINISH",
                       QColor(12, 12, 12))
        if _pua < 3.0 and _pu:
            _state9 = "POPUP"
        if _fl9:
            _state9 = (QColor(255, 42, 31), "FUEL",
                       QColor(255, 255, 255))
        _bc9 = fl9d.get("blue_class")
        if _bc9:
            from core.classes import class_tag as _ct9
            _tag9 = _ct9(str(_bc9))
            _btx = {"HY": "HY", "P2": "LMP", "P3": "LMP",
                    "GT3": "GT", "GTE": "GT"}.get(_tag9, "BLU")
            _state9 = (QColor(18, 64, 200), _btx,
                       QColor(255, 255, 255))
        if (fl9d.get("num_penalties") or 0) > 0:
            _state9 = (QColor(200, 16, 16),
                       getattr(self, "_pen_txt", "PEN"),
                       QColor(255, 255, 255))
        # WET: appena sotto la gialla, dura 10 secondi dallo scatto
        if now - getattr(self, "_wet_t", -99.0) < 10.0:
            _state9 = (QColor(12, 74, 110), "WET",
                       QColor(255, 255, 255))
        _yd9 = fl9d.get("yellow_dist")
        if _yd9 is not None:
            _state9 = (QColor(255, 204, 0), "%dm" % int(_yd9),
                       QColor(12, 12, 12))
        _tgt9 = 1.0 if _state9 is not None else 0.0
        # SONDA (debug flash): logga ogni cambio di stato coi numeri
        try:
            _sk = _state9 if isinstance(_state9, str) else \
                (_state9[1] if _state9 else "none")
            if _sk != getattr(self, "_dbg_sk", "init"):
                self._dbg_sk = _sk
                with open(str(USER_DIR / "mfd_state.log"), "a",
                          encoding="utf-8") as fh:
                    fh.write("%.2f st=%s ve=%r laps=%r pens=%r "
                             "yd=%r bc=%r pua=%.1f lim=%r\n"
                             % (time.monotonic(), _sk,
                                getattr(self, "_dbg_ve", None),
                                getattr(self, "_dbg_laps", None),
                                getattr(self, "_pens", 0),
                                fl9d.get("yellow_dist"),
                                fl9d.get("blue_class"),
                                _pua, _lim9))
        except Exception:
            pass
        k9 = getattr(self, "_pu_k", 0.0)
        k9 += (_tgt9 - k9) * 0.28
        if k9 < 0.01:
            k9 = 0.0
        self._pu_k = k9
        _gsz = int(60 - 32 * k9)          # 60 -> 28
        _gcy9 = cy - (r * 0.48) * k9      # centro -> meta' alta
        f_g = QFont("Archivo SemiExpanded", max(12, _gsz))
        p.setFont(f_g)
        fg = QFontMetricsF(f_g)
        p.setPen(QColor(255, 255, 255, 245))
        gear = _gsym(g)
        if show_gear:      # in MOD 2 la marcia NON si disegna (una sola, in MOD 1)
            p.drawText(QPointF(cx - fg.horizontalAdvance(gear) / 2.0,
                               _gcy9 + fg.capHeight() / 2.0), gear)
        if show_gear and k9 > 0.0 and _state9 is not None \
                and _state9 != "POPUP":
            # meta' bassa col COLORE dello stato attivo + testo grande
            _bg9, _tx9, _tc9 = _state9
            p.setPen(Qt.NoPen)
            _bg9 = QColor(_bg9)
            _bg9.setAlpha(int(235 * k9))
            p.setBrush(_bg9)
            _ri = r - 2.5
            p.drawPie(QRectF(cx - _ri, cy - _ri, _ri * 2, _ri * 2),
                      180 * 16, 180 * 16)
            fL = QFont("Archivo SemiExpanded")
            fL.setPixelSize(20 if _tx9 == "GREEN" else 22)
            fL.setBold(True)
            p.setFont(fL)
            _tc9 = QColor(_tc9)
            _tc9.setAlpha(int(255 * k9))
            p.setPen(_tc9)
            p.drawText(QRectF(cx - 60, cy + 1, 120, 34),
                       Qt.AlignCenter, _tx9)
        if k9 > 0.0 and _state9 == "POPUP":
            # meta' cerchio in basso: BLU col dato cambiato
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(18, 64, 200, int(235 * k9)))
            _ri = r - 2.5
            p.drawPie(QRectF(cx - _ri, cy - _ri, _ri * 2, _ri * 2),
                      180 * 16, 180 * 16)
            f9 = QFont("Archivo SemiExpanded")
            f9.setPixelSize(10)
            p.setFont(f9)
            p.setPen(QColor(255, 255, 255, int(215 * k9)))
            p.drawText(QRectF(cx - 60, cy + 1, 120, 13),
                       Qt.AlignCenter, _pu[0])
            _vt = _pu[1]
            _px9 = 24
            f9.setPixelSize(_px9)
            _fmv = QFontMetricsF(f9)
            while _px9 > 10 and _fmv.horizontalAdvance(_vt) > 84:
                _px9 -= 2
                f9.setPixelSize(_px9)
                _fmv = QFontMetricsF(f9)
            p.setFont(f9)
            p.setPen(QColor(255, 255, 255, int(255 * k9)))
            p.drawText(QRectF(cx - 60, cy + 13, 120, 30),
                       Qt.AlignCenter, _vt)
        # ── velocita' SOTTO il cerchio, fuori (unita' dal menu) ──
        _mph = self._prefs.get("speed_unit", "KPH") == "MPH"
        f_s = QFont("Archivo SemiExpanded", 19)
        p.setFont(f_s)
        fm = QFontMetricsF(f_s)
        s = "%.0f" % (self._spd_disp / 1.609344 if _mph
                      else self._spd_disp)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(QPointF(cx - fm.horizontalAdvance(s) / 2.0,
                           cy + r + 34.0), s)
        # (dicitura unita' rimossa il 21/07: resta solo il numero)

    @staticmethod
    def _gauge_col(f):
        STOPS = ((0.0, (0, 229, 255)), (0.45, (0, 255, 200)),
                 (0.70, (168, 255, 0)), (0.85, (255, 212, 0)),
                 (1.0, (255, 59, 48)))
        for k in range(len(STOPS) - 1):
            p0, c0 = STOPS[k]
            p1, c1 = STOPS[k + 1]
            if f <= p1:
                tt = (f - p0) / (p1 - p0) if p1 > p0 else 0.0
                return QColor(int(c0[0] + (c1[0] - c0[0]) * tt),
                              int(c0[1] + (c1[1] - c0[1]) * tt),
                              int(c0[2] + (c1[2] - c0[2]) * tt))
        return QColor(255, 59, 48)
        W90 = QColor(255, 255, 255, 230)
        NAVY = QColor(16, 17, 20)  # "negativo" delle celle piene = bg
        FAM = "Archivo SemiExpanded"
        bx = _W / 1334.0
        by = (_H - self.HDR - self.ROW_T - self.ROW_B) / 750.0
        y0 = self.HDR + self.ROW_T

        def R(x, y, w, h):
            return QRectF(x * bx, y0 + y * by, w * bx, h * by)

        BORD = QColor(255, 255, 255, 130)   # cornici opacizzate

        def box(r, px=1.2):
            p.setPen(QPen(BORD, px))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)

        def txt(r, s, size, col=W90, align=Qt.AlignCenter):
            if not s:
                return
            f = QFont(FAM)
            f.setPixelSize(max(6, int(size * by)))
            p.setFont(f)
            p.setPen(QPen(col))
            p.drawText(r, align, s)

        def num(v, fmt="%d"):
            return (fmt % v) if v is not None else ""

        ve_mode = self._ve and self._ve > 0
        # ── TYRE TEMP: carcassa, celle coi colori standard dell'app ──
        from widgets.list.colors import col_tyre_temp
        _ccls = "GT3" if self._is_gt3 else "HY"
        # blocco RIDOTTO (fattore 0.78, ancorato in alto a sinistra)
        _s = 0.78

        def RS(x, y, w, h):
            return R(13 + (x - 13) * _s, 17 + (y - 17) * _s,
                     w * _s, h * _s)

        box(RS(13, 17, 406, 306))
        txt(RS(13, 22, 406, 46), "TYRE TEMP", 32 * _s)
        p.setBrush(W90)
        p.setPen(Qt.NoPen)
        p.drawRect(RS(14, 68, 404, 3))
        cells = ((25, 80), (221, 80), (25, 200), (221, 200))
        for k, (cx, cy) in enumerate(cells):
            r = RS(cx, cy, 185, 111)
            v = self._carc4[k] if k < len(self._carc4) else None
            p.setBrush(col_tyre_temp(v, _ccls))
            p.setPen(Qt.NoPen)
            p.drawRect(r)
            txt(r, num(v, "%.1f"), 70 * _s, NAVY)
        # ── LAP FUEL / FUEL REMAIN (unita' dal vincolo: % o litri) ──
        unit = "%" if ve_mode else "L"
        box(R(13, 332, 314, 125))
        txt(R(13, 340, 314, 40), "LAP FUEL [%s]" % unit, 32)
        txt(R(13, 372, 314, 80),
            num(self._lap_use, "%.1f"), 75)
        box(R(13, 466, 314, 125))
        _rm = self._ve if ve_mode else self._fuel_l
        # alterna ogni 5s PIENI (toggle a stato, non orologio assoluto):
        # carico rimanente <-> GIRI di autonomia (senza consumo tace)
        _nowp = time.monotonic()
        if _nowp - getattr(self, "_fr_t0", 0.0) >= 5.0:
            self._fr_t0 = _nowp
            self._fr_laps = not getattr(self, "_fr_laps", False)
        _plm = getattr(self, "_pl_menu", None)   # %/giro DI LMU
        _laps_ph = getattr(self, "_fr_laps", False) \
            and ve_mode and _plm and _rm is not None
        if _laps_ph:
            _VIO = QColor("#b678ff")
            txt(R(13, 474, 314, 40), "FUEL REMAIN [LAPS]", 32, _VIO)
            txt(R(13, 506, 314, 80), "%.1f" % (_rm / _plm), 75, _VIO)
        else:
            txt(R(13, 474, 314, 40), "FUEL REMAIN [%s]" % unit, 32)
            txt(R(13, 506, 314, 80), num(_rm, "%.1f"), 75)
        # ── GEAR + SPEED al centro (MOTORE SPENTO: rpm a zero) ──
        eng_off = (self._rpm is not None and self._rpm < 1.0)
        if eng_off:
            txt(R(0, 280, 1334, 100), "ENGINE OFF", 70,
                QColor(255, 45, 45))
            if not self._is_gt3 and self._erpm > 10.0:
                txt(R(0, 390, 1334, 90), "E-MOTOR ON", 55,
                    QColor(0, 220, 90))
        else:
            txt(R(610, 20, 114, 55), "GEAR", 35)
            g = self._gear
            gs = "" if g is None else ("R" if g < 0 else
                                       ("N" if g == 0 else str(g)))
            txt(R(584, 57, 166, 253), gs, 250)
            _lim = getattr(self, "_limiter", False)
            txt(R(378, 273, 576, 130), num(self._speed, "%.0f"), 110,
                QColor("#ff7a00") if _lim else W90)
            # PIT LIMITER armato: INVERTITO in riquadro arancione
            # pieno (spigoli vivi), scritta grande bold in negativo
            if _lim:
                _lr = R(490, 418, 352, 68)
                p.setBrush(QColor("#ff7a00"))
                p.setPen(Qt.NoPen)
                p.drawRect(_lr)
                _fl = QFont(FAM)
                _fl.setPixelSize(max(6, int(52 * by)))
                _fl.setBold(True)
                p.setFont(_fl)
                p.setPen(QPen(NAVY))
                p.drawText(_lr, Qt.AlignCenter, "PIT LIMITER")
        def tfmt(v):
            if not v or v <= 0:
                return ""
            m = int(v // 60)
            s = v - m * 60
            return "%d.%02d.%02d" % (m, int(s), int((s % 1) * 100))

        # ── LAST / GAIN-LOSS / BEST a destra ──
        dlt = None
        cs1, cs2 = self._cs
        if cs2 > 0 and self._bs[0] > 0 and self._bs[1] > 0:
            dlt = (cs1 + cs2) - (self._bs[0] + self._bs[1])
        elif cs1 > 0 and self._bs[0] > 0:
            dlt = cs1 - self._bs[0]
        for lbl, val, y in (("LAST LAP", tfmt(self._last), 164),
                            ("GAIN/LOSS",
                             ("%+.2f" % dlt) if dlt is not None else "",
                             307),
                            ("BEST LAP", tfmt(self._best), 450)):
            box(R(938, y, 381, 135))
            txt(R(938, y + 6, 381, 40), lbl, 32)
            txt(R(938, y + 50, 381, 80), val, 65)
        # ── BEAM (solo coi fari accesi: dato vero, il resto tace) ──
        if self._beam:
            r = R(373, 490, 141, 49)
            p.setBrush(W90)
            p.setPen(Qt.NoPen)
            p.drawRect(r)
            txt(r, "BEAM", 40, NAVY)
        # ── fila in basso ──
        for lbl, val, x, w in (
                ("TMOT", num(self._water, "%.0f"), 14, 130),
                ("TOIL", num(self._oil, "%.0f"), 152, 130),
                ("RADIO", "", 290, 130)):
            box(R(x, 601, w, 135))
            txt(R(x, 607, w, 40), lbl, 32)
            txt(R(x, 645, w, 80), val, 71)
        # casella RADIO: ON/OFF dal menu overlay; quando il muretto
        # chiama -> CH 1/2/3 per TUTTO il parlato + 3s dopo la fine
        rr = R(290, 645, 130, 80)
        _rot = getattr(self, "_radio_on_t", 0.0)
        _ret = getattr(self, "_radio_end_t", None)
        if _rot and _ret is None:
            _ch_vis = time.monotonic() - _rot < 30.0   # rete anti-stallo
        elif _ret is not None:
            _ch_vis = time.monotonic() - _ret < 3.0
        else:
            _ch_vis = False
        if _ch_vis:
            _RCH = {"engineer": ("CH 1", "#e8802a"),
                    "strategist": ("CH 2", "#45b4ef"),
                    "spotter": ("CH 3", "#37d67a")}
            ch, cc = _RCH.get(self._radio.get("role") or "engineer",
                              ("CH 1", "#e8802a"))
            txt(rr, ch, 60, QColor(cc))
        else:
            on = getattr(self, "_radio_en", False)
            txt(rr, "ON" if on else "OFF", 60,
                W90 if on else QColor(255, 255, 255, 90))

    # ── CARD A ZERO: solo BG squadra. Si costruisce passo passo. ──────
    def _paint_frame(self, p):
        # team VERO del player (test 23 pagine concluso)
        hb, hf = self._header_style()
        try:
            from core.wec_style import row_gradient
            tri = row_gradient(self._brand)
        except Exception:
            tri = None
        g = QLinearGradient(0, 0, _W, 0)
        if tri:
            g.setColorAt(0.0, QColor(tri[0]))
            g.setColorAt(0.5, QColor(tri[1]))
            g.setColorAt(1.0, QColor(tri[2]))
        else:
            g.setColorAt(0.0, hb.lighter(115))
            g.setColorAt(1.0, hb.darker(122))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        # la riga alta e' l'HEADER (gradiente brand)...
        p.drawRect(QRectF(0, 0, _W, self.HDR))
        # ...e sotto il corpo nel BLU della zona tempi delle card
        # classifica (#0D1B2A)
        p.setBrush(QColor(16, 17, 20))     # nero "display spento"
        p.drawRect(QRectF(0, self.HDR, _W, _H - self.HDR))
        # ROW sopra e sotto i moduli (vuote per ora): come il bg
        p.setBrush(QColor(16, 17, 20))
        p.drawRect(QRectF(0, self.HDR, _W, self.ROW_T))
        p.drawRect(QRectF(0, _H - self.ROW_B, _W, self.ROW_B))
        # ── alto a SINISTRA, bilanciato: logo | slash piccolo | P14 ──
        x = 14.0
        try:
            from core.wec_style import card_logo_path
            from PySide6.QtSvg import QSvgRenderer
            lp = card_logo_path(self._brand)
            if lp:
                if getattr(self, "_hdr_lp", None) != lp:
                    self._hdr_rnd = QSvgRenderer(lp)
                    self._hdr_lp = lp
                r = self._hdr_rnd
                ds = r.defaultSize()
                if ds.height() > 0:
                    ar = ds.height() / float(ds.width())   # h/w
                    from core.wec_style import logo_box
                    # blocco alto-sx ridotto allo 0.8 (unit 40->32)
                    ww, hh, _dy, _adv, _dx = logo_box(self._brand, ar,
                                                      32.0)
                    r.render(p, QRectF(x + _dx,
                                       8 + (32.0 - hh) / 2.0 + _dy,
                                       ww, hh))
                    x += _adv + _dx
        except Exception:
            pass
        # slash piccolo (scala 0.8)
        p.setPen(QPen(QColor(hf), 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x + 13.0, 11.0), QPointF(x + 8.0, 32.0))
        x += 21.0
        # posizione, in linea con lo slash e attaccata (scala 0.8)
        f_ps = QFont("Archivo SemiExpanded", 22)
        f_ps.setWeight(QFont.Black)
        f_ps.setItalic(True)
        p.setFont(f_ps)
        p.setPen(QColor(hf))
        _ptxt = "P%d" % (self._place or 14)
        p.drawText(QPointF(x + 2.0, 32.0), _ptxt)
        # ── nome pilota (grande) + modello auto (piccolo): STATICI nell'header
        #    a DESTRA. Il box navy dinamico ci scorre SOPRA (poi -> i dati).
        _nm = (self._driver or "").upper()
        _vm = (getattr(self, "_vmodel", "") or "").upper()
        _rx = float(_W) - 14.0
        if _nm:
            f_dr = QFont("Archivo SemiExpanded", 15)
            f_dr.setWeight(QFont.Black)
            f_dr.setItalic(True)
            p.setFont(f_dr)
            p.setPen(QColor(hf))                 # colore testo della card (brand)
            p.drawText(QPointF(
                _rx - QFontMetricsF(f_dr).horizontalAdvance(_nm),
                21.0), _nm)
        if _vm:
            f_vm = QFont("Archivo SemiExpanded", 10)
            f_vm.setWeight(QFont.DemiBold)
            f_vm.setItalic(True)
            p.setFont(f_vm)
            _mc = QColor(hf)
            _mc.setAlpha(215)
            p.setPen(_mc)
            p.drawText(QPointF(
                _rx - QFontMetricsF(f_vm).horizontalAdvance(_vm),
                37.0), _vm)
        # ── box navy DINAMICO che scorre da DESTRA SOPRA il nome (come onboard):
        #    si apre da solo dopo open_delay_s, click apre/chiude.
        _od = float(self.cfg.get("open_delay_s", 10.0))
        _t0 = getattr(self, "_hdr_shown_t0", None)
        if _t0 is None:
            _t0 = self._hdr_shown_t0 = time.monotonic()
        _fc = getattr(self, "_hdr_forced", None)
        _open = _fc if _fc is not None else \
            (time.monotonic() - _t0) >= _od   # dopo 10s copre il nome
        self._hdr_open_now = _open                      # per il click
        _tgt = 1.0 if _open else 0.0
        _hf = getattr(self, "_hdr_k", 0.0)
        _hf += (_tgt - _hf) * 0.22                      # scorrimento fluido
        if abs(_tgt - _hf) < 0.01:
            _hf = _tgt
        self._hdr_k = _hf
        _pend = x + 2.0 + QFontMetricsF(f_ps).horizontalAdvance(_ptxt)
        _bx0 = _pend + 16.0
        _bx1 = float(_W)
        self._hdr_bx0 = _bx0                            # per il click
        if _bx1 > _bx0 and _hf > 0.001:
            _bw = _bx1 - _bx0
            _dx = _bw * (1.0 - _hf)                     # scorre right->left
            _rect = QRectF(_bx0 + _dx, 0.0, _bw - _dx, self.HDR)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(85, 74, 146, 255))       # #554A92, copre il nome
            p.drawRect(_rect)
            # ── DATO DINAMICO: prova/quali (RUN) e GARA (STINT) — stesso
            # header identico, cambia solo il contatore (rich. 23/07) ──
            if True:
                p.save()
                p.setClipRect(_rect)
                f_big = QFont("Archivo SemiExpanded", 15)
                f_big.setWeight(QFont.Black)
                f_big.setItalic(True)
                f_sup = QFont("Archivo SemiExpanded", 9)
                f_sup.setWeight(QFont.Black)
                f_sup.setItalic(True)
                _tx = _bx0 + 14.0
                _yb = 30.0

                def _fmt(s):
                    if not s or s <= 0:
                        return "--"
                    _m = int(s // 60)
                    return "%d:%06.3f" % (_m, s - _m * 60) if _m \
                        else "%.3f" % s

                # giro VALIDO = fuori garage/pit e outlap gia' chiuso
                _valid = (not self._in_pits and not self._in_garage
                          and self._laps > self._run_out_lap)
                # ── etichetta: GARAGE / PIT / BOX / OUTLAP / Nˢᵗ RUN (come relative) ──
                p.setFont(f_big)
                p.setPen(QColor(255, 255, 255, 250))
                _phq = int(getattr(self, "_game_phase", 5) or 0)
                if _phq <= 0:
                    _lbl = "PIT CLOSED"   # quali/prova: corsia box chiusa
                elif self._in_garage:
                    _lbl = "GARAGE"       # (poi simbolo WEC da creare)
                elif self._in_pits:
                    _lbl = "PIT"
                elif self._pit_state == 1:
                    _lbl = "BOX"          # box chiamato (pit request)
                elif getattr(self, "_dmg_dead", False):
                    _lbl = "DAMAGE"       # combo ritiro: macchina morta
                elif not _valid:
                    _lbl = "OUT LAP"
                elif self._lap_aborted:
                    _lbl = "ABORTED"      # hai mollato: giro buttato
                else:
                    _lbl = None
                if _lbl is not None:
                    p.drawText(QPointF(_tx, _yb), _lbl)
                    _tx += QFontMetricsF(f_big).horizontalAdvance(_lbl) + 16.0
                elif int(getattr(self, "_sess_type", 0) or 0) >= 10:
                    # GARA: contatore STINT (soste + 1), stesso stile run
                    _stn = int(getattr(self, "_pits9", 0) or 0) + 1
                    _d3 = _stn % 100
                    _sfx3 = "TH" if 11 <= _d3 <= 13 else                         {1: "ST", 2: "ND", 3: "RD"}.get(_stn % 10, "TH")
                    _ns3 = str(_stn)
                    p.drawText(QPointF(_tx, _yb), _ns3)
                    _tx += QFontMetricsF(f_big).horizontalAdvance(_ns3) + 1.0
                    f_sup3 = QFont("Archivo SemiExpanded", 8)
                    f_sup3.setWeight(QFont.Black)
                    f_sup3.setItalic(True)
                    p.setFont(f_sup3)
                    p.drawText(QPointF(_tx, _yb - 6.0), _sfx3)
                    _tx += QFontMetricsF(f_sup3).horizontalAdvance(_sfx3) + 7.0
                    p.setFont(f_big)
                    p.drawText(QPointF(_tx, _yb), "STINT")
                    _tx += QFontMetricsF(f_big).horizontalAdvance("STINT")                         + 14.0
                else:
                    _run = max(1, int(self._run))    # 1 = primo stint
                    _d2 = _run % 100
                    _sfx = "TH" if 11 <= _d2 <= 13 else \
                        {1: "ST", 2: "ND", 3: "RD"}.get(_run % 10, "TH")
                    _ns = str(_run)
                    p.drawText(QPointF(_tx, _yb), _ns)
                    _tx += QFontMetricsF(f_big).horizontalAdvance(_ns) + 1.0
                    # suffisso ST/ND/RD come l'originale WEC: PICCOLO,
                    # apice allineato in alto al numero
                    f_sup2 = QFont("Archivo SemiExpanded", 8)
                    f_sup2.setWeight(QFont.Black)
                    f_sup2.setItalic(True)
                    p.setFont(f_sup2)
                    p.drawText(QPointF(_tx, _yb - 6.0), _sfx)
                    _tx += QFontMetricsF(f_sup2).horizontalAdvance(_sfx) + 7.0
                    p.setFont(f_big)
                    p.drawText(QPointF(_tx, _yb), "RUN")
                    _tx += QFontMetricsF(f_big).horizontalAdvance("RUN") + 14.0

                if not _valid:
                    # GARAGE / PIT / OUT LAP: colonne colorate come il RUN.
                    # TEMPO SESSIONE nella colonna #0a0031, TRACK TEMP /34°\
                    # nella colonna #181246 a destra (niente LAP qui).
                    _srt = int(max(0.0, self._sess_remain))
                    _h = _srt // 3600
                    _m = (_srt % 3600) // 60
                    _s = _srt % 60
                    _stxt = "%d:%02d:%02d" % (_h, _m, _s) if _h > 0 \
                        else "%d:%02d" % (_m, _s)
                    # colonna TEMP/GRIP: pagina condivisa GARAGE/OUT LAP/PIT
                    # (cosi' deciso: il pit mostra lo stesso del garage)
                    _has_tt = self._track_temp > 0
                    _gl = getattr(self, "_track_grip", None)
                    # stile "controlli elettronici" del dash: VALORE sopra
                    # (+ triangolo attaccato), label piccola sotto.
                    # TEMP e GRIP (0-4) affiancati, niente alternanza.
                    f_tt = QFont("Archivo SemiExpanded", 13)
                    f_tt.setWeight(QFont.Normal)
                    f_tt.setItalic(True)
                    f_lb = QFont("Archivo SemiExpanded", 7)
                    f_lb.setWeight(QFont.Medium)
                    f_lb.setItalic(True)
                    _fv2 = QFontMetricsF(f_tt)
                    _fl2 = QFontMetricsF(f_lb)
                    _txt_t = "%d°" % int(round(self._track_temp))
                    _txt_g = ("%d" % _gl) if _gl is not None else "-"
                    _wt2 = max(_fv2.horizontalAdvance(_txt_t) + 12.0,
                               _fl2.horizontalAdvance("TEMP"))
                    _wg2 = max(_fv2.horizontalAdvance(_txt_g) + 12.0,
                               _fl2.horizontalAdvance("GRIP"))
                    # ALTERNA ogni 10s: blocco TEMP <-> blocco GRIP
                    _show_g = (_gl is not None
                               and int(time.monotonic() / 10.0) % 2 == 1)
                    _wb2 = max(_wt2, _wg2)          # larghezza fissa
                    # colonna a destra: icona STRADA + [temp|grip]
                    _ttw = 12.0 + 22.0 + 9.0 + _wb2 + 12.0
                    _tt_x0 = _bx1 - (_ttw if _has_tt else 0.0)
                    p.setPen(Qt.NoPen)
                    if _has_tt:
                        p.setBrush(QColor("#181246"))
                        p.drawRect(QRectF(_tt_x0, 0.0, _ttw, self.HDR))
                    # colonna TEMPO SESSIONE: dal label fino alla colonna temp
                    p.setBrush(QColor("#0a0031"))
                    p.drawRect(QRectF(_tx, 0.0, _tt_x0 - _tx, self.HDR))
                    _twt = QFontMetricsF(f_big).horizontalAdvance(_stxt)
                    _cx2 = _tx + max(10.0, (_tt_x0 - _tx - _twt) / 2.0)
                    p.setFont(f_big)
                    p.setPen(QColor(255, 255, 255, 235))
                    p.drawText(QPointF(_cx2, _yb), _stxt)
                    # ── TEMP ASFALTO: icona STRADA + numero + triangolo ──
                    if _has_tt:
                        _cx2 = _tt_x0 + 12.0
                        # icona strada BIANCA (bordi obliqui + tratteggio)
                        _ry1 = _yb + 2.0            # base (larga)
                        _ry0 = _yb - 15.0           # cima (stretta)
                        _rw = 22.0
                        _pen = QPen(QColor(255, 255, 255, 240), 2.4,
                                    Qt.SolidLine, Qt.FlatCap)
                        p.setPen(_pen)              # bordo sinistro /
                        p.drawLine(QPointF(_cx2 + 1.0, _ry1),
                                   QPointF(_cx2 + 6.5, _ry0))
                        # bordo destro \
                        p.drawLine(QPointF(_cx2 + _rw - 1.0, _ry1),
                                   QPointF(_cx2 + _rw - 6.5, _ry0))
                        # mezzeria tratteggiata (3 tacche)
                        _mx = _cx2 + _rw / 2.0
                        p.setPen(QPen(QColor(255, 255, 255, 240), 2.2,
                                      Qt.SolidLine, Qt.FlatCap))
                        p.drawLine(QPointF(_mx, _ry1),
                                   QPointF(_mx, _ry1 - 4.5))
                        p.drawLine(QPointF(_mx, _ry1 - 7.5),
                                   QPointF(_mx, _ry1 - 11.0))
                        p.drawLine(QPointF(_mx, _ry1 - 14.0),
                                   QPointF(_mx, _ry1 - 17.0))
                        _cx2 += _rw + 9.0
                        from PySide6.QtGui import QPolygonF

                        def _blk(x, val, lab, tr, w):
                            """valore sopra + triangolo, label sotto."""
                            p.setFont(f_tt)
                            p.setPen(QColor(255, 255, 255, 245))
                            p.drawText(QPointF(x, 25.0), val)
                            _txr = x + _fv2.horizontalAdvance(val) + 4.0
                            p.setPen(Qt.NoPen)
                            p.setBrush(QColor(255, 255, 255,
                                              245 if tr != 0 else 110))
                            _cyT = 24.0
                            if tr >= 0:
                                p.drawPolygon(QPolygonF([
                                    QPointF(_txr, _cyT),
                                    QPointF(_txr + 8.0, _cyT),
                                    QPointF(_txr + 4.0, _cyT - 9.0)]))
                            else:
                                p.drawPolygon(QPolygonF([
                                    QPointF(_txr, _cyT - 9.0),
                                    QPointF(_txr + 8.0, _cyT - 9.0),
                                    QPointF(_txr + 4.0, _cyT)]))
                            p.setFont(f_lb)
                            p.setPen(QColor(255, 255, 255, 190))
                            p.drawText(QPointF(x, 38.0), lab)
                            return x + w + 10.0

                        if _show_g:
                            _blk(_cx2, _txt_g, "GRIP",
                                 getattr(self, "_tg_trend", 0), _wb2)
                        else:
                            _blk(_cx2, _txt_t, "TEMP",
                                 self._tt_trend, _wb2)
                else:
                    # ── colori 3 barrette settore: magenta/verde/giallo + pulse ──
                    _SC = {"fastest": QColor("#ff2bd6"),
                           "improved": QColor("#00e676"),
                           "normal": QColor("#ffe24d")}    # colori WEC
                    _states = self._sector_states()
                    _pul = 0.35 + 0.65 * abs(
                        (time.monotonic() % 1.0) - 0.5) * 2.0
                    # ── 3 barrette settore ATTACCATE alla label, sul navy ──
                    p.setPen(Qt.NoPen)
                    for _i2 in range(3):
                        _frz = self._sec_col[_i2]
                        if _frz is not None:
                            _c2 = _frz               # congelato: come il tempo
                        else:
                            _stt = _states[_i2]
                            if _stt == "current":
                                _c2 = QColor(255, 255, 255, int(255 * _pul))
                            elif _stt in _SC:
                                _c2 = _SC[_stt]
                            else:
                                _c2 = QColor(255, 255, 255, 45)
                        p.setBrush(_c2)
                        p.drawRect(QRectF(_tx + _i2 * 9.0, 12.0, 5.0, 20.0))
                    _tx += 3 * 9.0 + 16.0
                    # ── COLONNA LAP (a destra): bg #181246, larghezza fissa 3 cifre ──
                    f_lap = QFont("Archivo SemiExpanded", 12)
                    f_lap.setWeight(QFont.DemiBold)
                    f_lap.setItalic(True)
                    _lm = QFontMetricsF(f_lap)
                    _laptxt = "LAP %d" % (self._laps + 1)
                    # larga sul DATO REALE (pagina RUN: spazio ai tempi)
                    _lapw = _lm.horizontalAdvance(_laptxt) + 24.0
                    _lap_x0 = _bx1 - _lapw
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor("#181246"))
                    p.drawRect(QRectF(_lap_x0, 0.0, _lapw, self.HDR))
                    # ── testo EVENTI: freeze (5s) / INVALID / milestone ──
                    if time.monotonic() < self._freeze_until                             and self._freeze_txt:
                        _vt, _vc, _lim = self._freeze_txt, self._freeze_col, False
                    elif self._lap_limits and                             time.monotonic() - getattr(self, "_inv_t",
                                                       -99.0) < 5.0:
                        _vt, _vc, _lim = "INVALID",                             QColor(255, 255, 255, 150), True
                    elif time.monotonic() - getattr(self, "_sess_flash_t",
                                                    -99.0) < 5.0:
                        _rm = int(round(getattr(self, "_sess_flash_v", 0.0)))
                        _vt = ("LAST MINUTE" if _rm <= 60
                               else "LEFT %d MIN" % (_rm // 60))
                        _vc, _lim = QColor(255, 255, 255, 200), False
                    else:
                        _vt, _vc, _lim = None, None, False
                    # ── CELLA DELTA (ardesia, STRETTA sul testo): stessa
                    # animazione LATERALE WEC, ancorata alla colonna LAP ──
                    _dtx = self._delta_txt or ""
                    if _dtx:
                        self._d_last = _dtx
                        self._d_lastc = self._delta_col
                    _tgtd = 0.0 if _dtx else 1.0
                    _kd = getattr(self, "_dcell_k", _tgtd)
                    _kd += (_tgtd - _kd) * 0.12
                    if abs(_tgtd - _kd) > 0.005:
                        self.update()
                    else:
                        _kd = _tgtd
                    self._dcell_k = _kd
                    f_d9 = QFont("Archivo SemiExpanded", 14)
                    f_d9.setWeight(QFont.DemiBold)
                    f_d9.setItalic(True)
                    _dtx_show = _dtx or getattr(self, "_d_last", "")
                    _dwf = QFontMetricsF(f_d9).horizontalAdvance(
                        _dtx_show or "+0.000") + 14.0
                    _dx1 = _lap_x0
                    _dx0 = _dx1 - _dwf * (1.0 - _kd)
                    if _kd < 0.999 and _dtx_show:
                        _bgd9 = QColor("#262c38")
                        _bgd9.setAlpha(int(255 * (1.0 - _kd)))
                        p.setPen(Qt.NoPen)
                        p.setBrush(_bgd9)
                        p.drawRect(QRectF(_dx0, 0.0, _dx1 - _dx0, self.HDR))
                        if _kd < 0.5:
                            p.setFont(f_d9)
                            _pcd = QColor(self._d_lastc)                                 if _dtx and self._d_lastc                                 else QColor(255, 255, 255, 235)
                            p.setPen(_pcd)
                            _twd = QFontMetricsF(f_d9)                                 .horizontalAdvance(_dtx_show)
                            p.drawText(QPointF(
                                _dx0 + (_dwf - _twd) / 2.0, _yb), _dtx_show)
                    # ── CELLA EVENTI (blu): l'ORIGINALE con l'animazione
                    # laterale. Z-INDEX SOPRA la cella delta: stesso
                    # ancoraggio a LAP, aprendosi la COPRE e chiudendosi
                    # la scopre (rich. 23/07: "i tempi stanno un zindex
                    # sopra, non nello stesso livello") ──
                    _tgt9 = 0.0 if _vt else 1.0
                    _k9 = getattr(self, "_dl_coll", _tgt9)
                    _k9 += (_tgt9 - _k9) * 0.12
                    if abs(_tgt9 - _k9) > 0.005:
                        self.update()
                    else:
                        _k9 = _tgt9
                    self._dl_coll = _k9
                    _ex1 = _lap_x0
                    _dl_x0 = _tx + (_ex1 - _tx) * _k9
                    _dl_x1 = _ex1
                    _bgc9 = QColor("#0a0031")
                    _bgc9.setAlpha(int(255 * (1.0 - _k9 * 0.9)))
                    p.setPen(Qt.NoPen)
                    p.setBrush(_bgc9)
                    p.drawRect(QRectF(_dl_x0, 0.0, _dl_x1 - _dl_x0,
                                      self.HDR))
                    if _lim:
                        f_v = QFont("Archivo SemiExpanded", 12)
                        f_v.setWeight(QFont.Bold)
                        f_v.setItalic(False)
                    else:
                        f_v = QFont("Archivo SemiExpanded", 14)
                        f_v.setWeight(QFont.DemiBold)
                        f_v.setItalic(True)
                    if _vt:
                        _txt_w = QFontMetricsF(f_v).horizontalAdvance(_vt)
                        _gx = _dl_x0 + max(6.0, (_dl_x1 - _dl_x0 - _txt_w) / 2.0)
                        p.setFont(f_v)
                        p.setPen(_vc or QColor(255, 255, 255, 235))
                        p.drawText(QPointF(_gx, _yb), _vt)
                    # ── LAP N / CARBURANTE alternati ogni 10s (rich.
                    # 23/07, come TEMP/GRIP): icona benzina BIANCA
                    # (dal tuo SVG, ricolorato) + numero secco — senza
                    # % ne' litri, vale per VE (GT3/HY) e benzina (P2/GTE)
                    _bp10 = getattr(self, "_bar_pct9", None)
                    _alt10 = (_bp10 is not None
                              and int(time.monotonic() / 10.0) % 2 == 1)
                    p.setFont(f_lap)
                    if _alt10:
                        if not hasattr(self, "_svg_fuel_w9"):
                            try:
                                from PySide6.QtSvg import QSvgRenderer \
                                    as _QSRf
                                from PySide6.QtCore import QByteArray
                                _tf9 = (_ROOT / "assets" / "icons"
                                        / "fuel_spia.svg").read_text(
                                            encoding="utf-8")
                                _tf9 = re.sub(r"#[0-9a-fA-F]{6}",
                                              "#ffffff", _tf9)
                                self._svg_fuel_w9 = _QSRf(
                                    QByteArray(_tf9.encode()))
                            except Exception:
                                self._svg_fuel_w9 = None
                        _ftx = "%d" % _bp10[0]
                        _fw10 = _lm.horizontalAdvance(_ftx)
                        _fx10 = _bx1 - 12.0 - _fw10
                        p.setPen(QColor(255, 255, 255, 235))
                        p.drawText(QPointF(_fx10, _yb), _ftx)
                        if getattr(self, "_svg_fuel_w9", None) is not None:
                            self._svg_fuel_w9.render(
                                p, QRectF(_fx10 - 24.0, 8.0, 20.0, 20.0))
                    else:
                        p.setPen(QColor(255, 255, 255, 220))
                        p.drawText(QPointF(
                            _bx1 - 12.0 - _lm.horizontalAdvance(_laptxt),
                            _yb), _laptxt)
                # ── MOD 2/3/4: il gauge col cambio non c'e' -> la cella
                # DESTRA dell'header diventa MARCIA + VELOCITA' (rich.
                # 23/07). Z-sopra qualunque cosa ci fosse (LAP o TEMP);
                # al MOD 1 non si disegna e la cella torna com'era. ──
                try:
                    _mods9 = self._active_mods()
                    _mcur9 = _mods9[self._page % max(1, len(_mods9))]
                except Exception:
                    _mcur9 = 1
                # entrata/uscita a SCORRIMENTO laterale da destra (stile
                # WEC, come le celle delta/eventi); sfondo viola chiaro
                # del box PIT/GARAGE (rich. 23/07)
                _tgtg = 1.0 if _mcur9 != 1 else 0.0
                _kg = getattr(self, "_gcell_k", 0.0)
                _kg += (_tgtg - _kg) * 0.18
                if abs(_tgtg - _kg) > 0.005:
                    self.update()
                else:
                    _kg = _tgtg
                self._gcell_k = _kg
                if _kg > 0.001:
                    _g9v = self._gear if self._gear is not None else 0
                    _g9 = "R" if _g9v < 0 else \
                        ("N" if _g9v == 0 else str(_g9v))
                    _mph9 = self._prefs.get("speed_unit", "KPH") == "MPH"
                    # _speed e' GIA' in km/h: niente x3.6 doppio
                    _sp9 = (self._speed or 0.0) / (1.609344 if _mph9
                                                   else 1.0)
                    # larghezza PIENA fino al bordo (il trattino residuo
                    # a sinistra era la colonna sotto che spuntava) e
                    # velocita' allineata a destra con margine
                    _gw9 = 104.0
                    _gx0 = _bx1 - _gw9 * _kg
                    p.save()
                    p.setClipRect(QRectF(_gx0, 0.0, _bx1 - _gx0,
                                         self.HDR))
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor("#554A92"))   # viola chiaro PIT
                    p.drawRect(QRectF(_gx0, 0.0, _bx1 - _gx0, self.HDR))
                    f_gg = QFont("Archivo SemiExpanded", 24)
                    f_gg.setWeight(QFont.Black)
                    p.setFont(f_gg)
                    p.setPen(QColor("#ffb020") if _g9 in ("R", "N")
                             else QColor(255, 255, 255, 245))
                    p.drawText(QPointF(_bx1 - _gw9 + 12.0, _yb + 2.0),
                               _g9)
                    f_sp = QFont("Archivo SemiExpanded", 15)
                    f_sp.setWeight(QFont.DemiBold)
                    f_sp.setItalic(True)
                    p.setFont(f_sp)
                    p.setPen(QColor(255, 255, 255, 235))
                    _spt9 = "%d" % round(_sp9)
                    p.drawText(QPointF(
                        _bx1 - 12.0
                        - QFontMetricsF(f_sp).horizontalAdvance(_spt9),
                        _yb), _spt9)
                    p.restore()
                p.restore()
        # ── ROW ALTA: <MDF> celeste a sinistra, pagina 1/3 a destra
        #    (font del dash; i numeri header sono stati spostati qui)
        f_row = QFont("Archivo SemiExpanded")
        f_row.setPixelSize(11)
        p.setFont(f_row)
        # in basso a DESTRA: <MDF> celeste + numero moduli
        rr = QRectF(14, _H - self.ROW_B, _W - 28, self.ROW_B)
        n_pg = max(1, len(self._active_mods()))
        _num = "%d/%d" % ((self._page % n_pg) + 1, n_pg)
        # in basso a SINISTRA: titolo del modulo in giallo VR46
        _TIT = {1: "DASHBOARD", 2: "PIT", 3: "SETTINGS", 4: "CAR STATUS"}
        _mcur = self._active_mods()[self._page % n_pg]
        p.setPen(QColor("#ffed00"))
        p.drawText(rr, Qt.AlignLeft | Qt.AlignVCenter,
                   _TIT.get(_mcur, ""))
        # al CENTRO: RADIO ON/OFF (dal menu overlay) e poi TELEMETRY
        _fm2 = QFontMetricsF(f_row)
        _r_on = getattr(self, "_radio_en", False)
        _t_on = getattr(self, "_tele_rec", False)
        _rtxt = "RADIO ON" if _r_on else "RADIO OFF"
        _ttxt = self._it9("TELEMETRY ON" if _t_on else "TELEMETRY OFF")
        _gap2 = 24.0
        _tot2 = _fm2.horizontalAdvance(_rtxt) + _gap2 \
            + _fm2.horizontalAdvance(_ttxt)
        _xc = (_W - _tot2) / 2.0
        p.setPen(QColor(255, 255, 255, 230) if _r_on
                 else QColor(255, 255, 255, 120))
        p.drawText(QRectF(_xc, _H - self.ROW_B, 200, self.ROW_B),
                   Qt.AlignLeft | Qt.AlignVCenter, _rtxt)
        p.setPen(QColor("#00e676") if _t_on
                 else QColor(255, 255, 255, 120))
        p.drawText(QRectF(_xc + _fm2.horizontalAdvance(_rtxt) + _gap2,
                          _H - self.ROW_B, 220, self.ROW_B),
                   Qt.AlignLeft | Qt.AlignVCenter, _ttxt)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(rr, Qt.AlignRight | Qt.AlignVCenter, _num)
        _wnum = QFontMetricsF(f_row).horizontalAdvance(_num)
        p.setPen(QColor("#2fa8e0"))
        p.drawText(QRectF(14, _H - self.ROW_B,
                          _W - 28 - _wnum - 8, self.ROW_B),
                   Qt.AlignRight | Qt.AlignVCenter, "<MDF>")
        # ROW ALTA: fila RPM + LED laterali (dalla vecchia dashboard)
        self._paint_rpm_row(p)

    # ── fila RPM/LED nella ROW alta (porting dashboard_overlay) ──
    def _led_mini(self, p, rect, color, lit=True):
        """LED con alone + corpo a gradiente radiale (come la dash)."""
        cx = rect.x() + rect.width() / 2.0
        cy = rect.y() + rect.height() / 2.0
        if not lit or color is None:
            g = QRadialGradient(QPointF(cx, cy), rect.width())
            g.setColorAt(0.0, QColor(26, 31, 40))
            g.setColorAt(1.0, QColor(10, 12, 17))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(rect, 2, 2)
            return
        base = QColor(color)
        halo_r = max(rect.width(), rect.height()) * 1.15
        hg = QRadialGradient(QPointF(cx, cy), halo_r)
        h0 = QColor(base)
        h0.setAlpha(45)
        h1 = QColor(base)
        h1.setAlpha(0)
        hg.setColorAt(0.0, h0)
        hg.setColorAt(1.0, h1)
        p.setBrush(hg)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), halo_r, halo_r)
        bg = QRadialGradient(QPointF(cx, cy - rect.height() * 0.15),
                             rect.width() * 0.9)
        hot = QColor(min(255, base.red() + 90),
                     min(255, base.green() + 90),
                     min(255, base.blue() + 90))
        edge = QColor(int(base.red() * 0.55),
                      int(base.green() * 0.55),
                      int(base.blue() * 0.55))
        bg.setColorAt(0.0, hot)
        bg.setColorAt(0.5, base)
        bg.setColorAt(1.0, edge)
        p.setBrush(bg)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, 2, 2)

    def _grip_signal(self):
        """Giallo=lock/ABS anteriore, viola=posteriore, blu=TC
        (stessa logica della vecchia dashboard)."""
        C_F, C_R, C_TC = "#ffcc00", "#c04bff", "#00a8ff"
        out = {"L": None, "R": None}
        rot = self._wrot
        thr = self._thr_in
        brk = (self._brake_in or 0.0) / 100.0
        spd = self._speed or 0.0
        tc = self._tc_on
        if len(rot) == 4 and spd > 30.0:
            fl, fr, rl, rr = rot
            mx = max(rot)
            if brk > 0.10 and mx > 0.5:
                thr_lock = 0.55 * mx
                if fl < thr_lock:
                    out["L"] = C_F
                if rl < thr_lock:
                    out["L"] = C_R
                if fr < thr_lock:
                    out["R"] = C_F
                if rr < thr_lock:
                    out["R"] = C_R
                if self._abs_on:
                    if out["L"] != C_R:
                        out["L"] = C_F
                    if out["R"] != C_R:
                        out["R"] = C_F
            elif thr > 0.25:
                f = (fl + fr) / 2.0
                if tc or (f > 1.0 and rl > f * 1.10):
                    out["L"] = C_TC
                if tc or (f > 1.0 and rr > f * 1.10):
                    out["R"] = C_TC
        if tc and out["L"] is None and out["R"] is None:
            out["L"] = out["R"] = C_TC
        return out

    def _eco_lift_frac(self):
        """LIFT&COAST NOSTRO (0..1 come mLiftAndCoastProgress): con l'eco
        del muretto attivo, avvicinandosi a ogni curva frenata appresa i
        LED si riempiono fino al punto di rilascio. Il punto = inizio
        frenata appreso - margine ADATTIVO: piu' sei sopra il target di
        consumo, prima ti fa alzare (si autocalibra giro dopo giro).
        None = eco spento o dati non pronti (si torna al grip signal)."""
        if not self._eco_active_laps():
            return None
        spd = self._speed or 0.0
        if spd < 80.0:
            return None                    # niente coach nel lento/pit
        ld = getattr(self, "_lapdist", 0.0) or 0.0
        tl = getattr(self, "_track_len", 0.0) or 0.0
        if ld <= 0.0 or tl < 500.0:
            return None
        # curve apprese: cache per pista+classe (ricarica ogni 30s)
        _now = time.monotonic()
        _key = (getattr(self, "_track", ""), getattr(self, "_cls_name", ""))
        if (getattr(self, "_eco_ck", None) != _key
                or _now - getattr(self, "_eco_ct", 0.0) > 30.0):
            self._eco_ck = _key
            self._eco_ct = _now
            self._eco_corners = []
            try:
                from core import engineer_learn as _el
                from core.classes import class_tag as _ct
                prof = _el.load(_key[0], _ct(_key[1]) or _key[1])
                cs = ((prof.get("cond") or {}).get("dry") or {}) \
                    .get("corners") or []
                self._eco_corners = [
                    (float(c["d"]),
                     min(max(float(c.get("brake_d") or 60.0), 25.0), 300.0))
                    for c in cs
                    if c.get("d") is not None
                    and float(c.get("drop") or 0.0) >= 12.0]
            except Exception:
                self._eco_corners = []
        if not self._eco_corners:
            return None
        # margine adattivo dal muretto (eco_state.json: used vs target)
        if _now - getattr(self, "_eco_rt", 0.0) > 1.0:
            self._eco_rt = _now
            try:
                import json as _js
                _st9 = _js.loads((USER_DIR / "eco_state.json")
                                 .read_text(encoding="utf-8"))
                _tg9 = float(_st9.get("target") or 0.0)
                _us9 = float(_st9.get("used") or 0.0)
                self._eco_ratio = (_us9 / _tg9) if _tg9 > 0 else 1.0
            except Exception:
                self._eco_ratio = 1.0
        _ratio = min(max(getattr(self, "_eco_ratio", 1.0), 0.8), 1.4)
        margin = min(max(60.0 + (_ratio - 1.0) * 450.0, 40.0), 180.0)
        # prossima curva frenata (wrap sul giro); se ho APPENA superato un
        # punto di rilascio e sono ancora in zona frenata: pieno (LIFT!)
        best = None
        for d, bd in self._eco_corners:
            lift = d - bd - margin
            past = (ld - lift) % tl
            if past < margin + 20.0:
                return 1.0
            dl = (lift - ld) % tl
            if best is None or dl < best:
                best = dl
        window = 220.0
        if best is not None and best <= window:
            return min(1.0, 1.0 - best / window + 0.001)
        return None

    def _paint_rpm_row(self, p):
        """12 LED RPM al centro (verde->rosso, blu al limite, arancione
        col limitatore) + 4 LED per lato: lift&coast prioritario
        (viola fisso / rosa lampeggiante sul gas), senno' grip."""
        y = self.HDR + 7.5
        lh = 5.0
        n, lw, gap = 12, 15.0, 3.0
        row_w = n * lw + (n - 1) * gap
        x0 = (_W - row_w) / 2.0
        off = None
        cols = [off] * n
        top = self._maxrpm
        rpm = self._rpm or 0.0
        if getattr(self, "_limiter", False):
            on = int(time.monotonic() * 2) % 2 == 0
            cols = ["#ff8a1e" if on else off] * n
        elif top and top > 0 and rpm > 0:
            peak = self._shift_peak
            if rpm > peak:
                peak = self._shift_peak = rpm
            limit = peak if peak >= top * 0.85 else top
            frac = rpm / limit
            if peak >= top * 0.85 and frac >= 0.99:
                on = int(time.monotonic() * 5) % 2 == 0
                cols = ["#00b0ff" if on else off] * n
            else:
                start = 0.80
                pos = 0.0 if frac <= start else \
                    (frac - start) / (0.99 - start) * n
                pos = min(pos, float(n))
                cols = [("#00e676" if i < 7 else "#ff2a1f")
                        if pos >= i + 1 else off for i in range(n)]
        for i in range(n):
            c = cols[i]
            self._led_mini(p, QRectF(x0 + i * (lw + gap), y, lw, lh),
                           c, lit=bool(c))
        ns, lws = 6, 12.0
        blk = ns * lws + (ns - 1) * gap
        lx, rx = 10.0, _W - 10.0 - blk
        # lico EFFETTIVO (nativo o NOSTRO): stessi LED viola, stesso
        # blink rosa sul gas, stesso beep — nessuna differenza
        frac = getattr(self, "_lico_eff", None)
        if frac is None:
            frac = self._lico
        if frac >= 0.015:
            if self._thr_in > 0.15:
                on = int(time.monotonic() * 3) % 2 == 0
                side = [("#ff2ad9" if on and (frac * ns - i) > 0.1
                         else None) for i in range(ns)]
            else:
                side = ["#b678ff" if (frac * ns - i) > 0.1 else None
                        for i in range(ns)]
            colsL = side
            colsR = side[::-1]      # SPECULARE: a destra si riempie verso il centro
        else:
            sig = self._grip_signal()
            colsL = [sig["L"]] * ns
            colsR = [sig["R"]] * ns
        for i in range(ns):
            self._led_mini(p, QRectF(lx + i * (lws + gap), y, lws, lh),
                           colsL[i], lit=bool(colsL[i]))
            self._led_mini(p, QRectF(rx + i * (lws + gap), y, lws, lh),
                           colsR[i], lit=bool(colsR[i]))
