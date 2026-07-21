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
_W, _H = 500, 300              # 260 + le due ROW (20+20): i moduli
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
        self._oil = None
        self._abs = None
        self._tc = None
        self._carnum = ""
        self._driver = ""
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
        self._m2_sel = 0           # voce selezionata nella pagina PIT
        self._auto_pit = False     # AUTO PIT (engineer_cfg): mostrato nel Mod 3
        self._ap_ts = 0.0          # throttle rilettura flag auto_pit
        try:
            self._auto_pit = bool(engineer_cfg.load().get("auto_pit", False))
        except Exception:
            pass
        self._pm_items = []
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
                    pend = getattr(self, "_pm_pending", None)
                    if pend and (time.monotonic()
                                 - getattr(self, "_pm_pending_t",
                                           0.0)) < 4.0:
                        allok = True
                        for it2 in (dd if isinstance(dd, list)
                                    else []):
                            n2 = str((it2 or {}).get("name") or "")
                            if n2 in pend:
                                if int(it2.get("currentSetting")
                                       or 0) != pend[n2]:
                                    it2["currentSetting"] = pend[n2]
                                    allok = False
                        if allok:
                            self._pm_pending = None
                    else:
                        self._pm_pending = None
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
            self._radio_en = bool((_full.get("engineer") or {})
                                  .get("enabled", False))
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
                        if _run:
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
                    self._m3_msg = (("AUTO PIT ON - MURETTO SCRIVE LA VE"
                                     if self._auto_pit else "AUTO PIT OFF"),
                                    time.monotonic())
                    self._page_beep()
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
                                + (1 if (b & _XI_DD) else -1)) % 3
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
                self._sess_type = int(sim.scoring.scoringInfo.mSession)
            except Exception:
                self._sess_type = 0
            pid = None
            _ovr = 0
            _pcc = b""
            for i in range(min(num, _MX)):
                v = sim.scoring.vehScoringInfo[i]
                if v.mIsPlayer:
                    pid = int(v.mID)
                    self._laps = int(v.mTotalLaps)
                    _ovr = int(v.mPlace)
                    try:
                        _pcc = bytes(v.mVehicleClass).split(b"\x00")[0]
                    except Exception:
                        _pcc = b""
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
                    self._is_gt3 = "GT3" in vn.upper()
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
            for i in range(min(num, _MX)):
                t = sim.telemetry.telemInfo[i]
                if pid is not None and int(t.mID) == pid:
                    try:
                        self._oil = float(t.mEngineOilTemp)
                    except Exception:
                        self._oil = None
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
                        self._rpm = float(t.mEngineRPM)
                        self._crpm = float(t.mClutchRPM)
                        self._erpm = float(t.mElectricBoostMotorRPM)
                        self._ign = int(t.mIgnitionStarter)
                        self._limiter = bool(t.mSpeedLimiter)
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
        try:
            if self._lico < 0.015:
                self._lico_open = False
            elif self._lico >= 0.03 and not self._lico_open:
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
            _gp = int(self._mem._get_sim().scoring
                      .scoringInfo.mGamePhase)
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

    # ── paint ─────────────────────────────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self.width() / float(_W)
        p.scale(s, s)
        # (radio SEPARATA: vive nell'overlay "Team Radio", non qui)
        self._paint_frame(p)
        self._paint_page(p)
        p.end()

    def _active_mods(self):
        """MODULI FISSI: 1 = dashboard, 2 = vuota, 3 = impostazioni."""
        return [1, 2, 3]

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
        if not ion:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(6, 7, 9))
            p.drawRect(scr)
            return
        boot = (time.monotonic() - self._pwr_t0) if self._pwr_t0 else 99
        if boot < 3.0:
            # boot: spinner a quadratini 2x3 al centro
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(6, 7, 9))
            p.drawRect(scr)
            side, gap = 4.5, 2.0
            step = side + gap
            cx = _W / 2.0 - step
            cy = scr.center().y() - 1.5 * step
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
        if not act:
            return
        mod = act[self._page % len(act)]
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
        for pfx in ("DAMAGE",):
            it = find(pfx)
            if it:
                rows.append(it)
        it = find("VIRTUAL ENERGY") or find("FUEL")
        if it:
            rows.append(it)
        for pfx in ("TIRES", "FL TIRE", "FR TIRE",
                    "RL TIRE", "RR TIRE"):
            it = find(pfx)
            if it:
                rows.append(it)
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
        self._pm_pending = _pend
        self._pm_pending_t = time.monotonic()
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

    @staticmethod
    def _tr_pit(txt):
        """Testo opzione LMU (spesso in italiano) -> INGLESE, UPPER."""
        t = (txt or "").strip()
        FIX = {"nessuna modifica": "NO CHANGE",
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
                     (r"asciutto", "DRY")):
            o = re.sub(a, b, o, flags=re.I)
        return o.upper().strip()

    def _paint_mod2(self, p):
        FAM = "Heebo"
        bx = _W / 1334.0
        by = (_H - self.HDR - self.ROW_T - self.ROW_B) / 750.0
        y0 = self.HDR + self.ROW_T
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
        f.setPixelSize(20)
        p.setFont(f)
        _fm = QFontMetricsF(f)
        lh = 66.0 * by

        def _ico(svg, x, cy):
            if not svg:
                return
            rnd = self._m2_ico_cache.get(svg)
            if rnd is None:
                rnd = QSvgRenderer(QByteArray(svg.encode()))
                self._m2_ico_cache[svg] = rnd
                if len(self._m2_ico_cache) > 40:
                    self._m2_ico_cache.clear()
            rnd.render(p, QRectF(x, cy - 11.0, 22.0, 22.0))

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
        # ── HEAD: DAMAGE, ENERGY, 4 TYRES ──
        for i in range(min(3, len(rows))):
            it = rows[i]
            nm = str(it.get("name") or "").rstrip(":")
            opts = it.get("settings") or []
            cur = int(it.get("currentSetting") or 0)
            vt = str((opts[cur] or {}).get("text") or "") \
                if 0 <= cur < len(opts) else ""
            sel = (i == self._m2_sel % len(rows))
            ry = (14 + i * 76) * by
            cy = y0 + ry + lh / 2.0
            p.setPen(QPen(QColor("#2fa8e0") if sel
                          else QColor(255, 255, 255, 235)))
            if nm.upper().startswith("TIRES"):
                p.drawText(QRectF(40 * bx, y0 + ry, 400 * bx, lh),
                           Qt.AlignLeft | Qt.AlignVCenter, "4 TYRES")
                _ix = 40 * bx + _fm.horizontalAdvance("4 TYRES") + 16
                # solo se monti gomme (No Change = niente simbolo/%)
                _mix = "MIX" in vt.upper()
                if self._tyre_opt_parse(vt) or _mix:
                    _ico(self._m2_icon_svg(it, rows), _ix, cy)
                    if not _mix:
                        _pt = ("%d%%" % worst) if worst is not None \
                            else "100"
                        p.setPen(QPen(QColor(255, 255, 255, 235)))
                        p.drawText(QRectF(_ix + 28, y0 + ry,
                                          200 * bx, lh),
                                   Qt.AlignLeft | Qt.AlignVCenter, _pt)
            else:
                _ln = self._tr_pit(vt)
                # DAMAGE senza danno (N/D / -): riga VUOTA, niente "-"
                if nm.upper().startswith("DAMAGE") and _ln in ("-",
                                                               "N/D"):
                    _ln = ""
                p.drawText(QRectF(40 * bx, y0 + ry, 900 * bx, lh),
                           Qt.AlignLeft | Qt.AlignVCenter, _ln)
        # ── 4 RUOTE in formazione MACCHININA (2 avanti / 2 dietro) ──
        _cells = {"FL": (330, 452), "FR": (830, 452),
                  "RL": (330, 600), "RR": (830, 600)}
        for r2 in wheels:
            sig = str(r2.get("name") or "").upper()[:2]
            gx, gy2 = _cells.get(sig, (330, 452))
            idx = rows.index(r2)
            sel = (idx == self._m2_sel % len(rows))
            cx2 = gx * bx
            cy2 = y0 + gy2 * by
            p.setPen(QPen(QColor("#2fa8e0") if sel
                          else QColor(255, 255, 255, 235)))
            p.drawText(QRectF(cx2, cy2 - lh / 2.0, 60 * bx, lh),
                       Qt.AlignLeft | Qt.AlignVCenter, sig)
            _ix = cx2 + _fm.horizontalAdvance(sig) + 12
            # solo se monti gomme su questa ruota (No Change = niente)
            o2 = r2.get("settings") or []
            c2 = int(r2.get("currentSetting") or 0)
            vt2 = str((o2[c2] or {}).get("text") or "") \
                if 0 <= c2 < len(o2) else ""
            if self._tyre_opt_parse(vt2):
                _ico(self._m2_icon_svg(r2, rows), _ix, cy2)
                pv = _pct_txt(r2)
                _pt = ("%s%%" % pv) if (pv and int(pv) > 0) else "100"
                p.setPen(QPen(QColor(255, 255, 255, 235)))
                p.drawText(QRectF(_ix + 28, cy2 - lh / 2.0,
                                  120 * bx, lh),
                           Qt.AlignLeft | Qt.AlignVCenter, _pt)
        # SLICK montate / totale — SOLO in qualifica (5-8) o gara
        # (>=10): in pratica le gomme sono illimitate, non ha senso
        _tmax = getattr(self, "_tyre_max", 0)
        _st9 = getattr(self, "_sess_type", 0)
        if _tmax > 0 and (5 <= _st9 <= 8 or _st9 >= 10):
            _mounted = _tmax - getattr(self, "_tyre_new_left", _tmax)
            f.setPixelSize(20)
            p.setFont(f)
            p.setPen(QPen(QColor(255, 255, 255, 210)))
            p.drawText(QRectF(700 * bx, y0 + 12 * by, 594 * bx,
                              60 * by),
                       Qt.AlignRight | Qt.AlignVCenter,
                       "NEW SLICKS %d/%d" % (_mounted, _tmax))
        f.setPixelSize(max(6, int(26 * by)))
        p.setFont(f)
        p.setPen(QPen(QColor(255, 255, 255, 180)))
        p.drawText(QRectF(0, y0 + 706 * by, _W, 34 * by),
                   Qt.AlignCenter, "LEFT/RIGHT/UP/DOWN = Move")

    # ── MOD 3: SCHERMATA IMPOSTAZIONI del dash (menu stile DDU) ──
    def _paint_mod3(self, p):
        FAM = "CPMono_v07 Plain"
        bx = _W / 1334.0
        by = (_H - self.HDR - self.ROW_T - self.ROW_B) / 750.0
        y0 = self.HDR + self.ROW_T
        # AUTO PIT vive in engineer_cfg (lo scrive anche la config overlay):
        # rilettura throttled 1s cosi' il valore mostrato resta allineato
        _now = time.monotonic()
        if _now - self._ap_ts > 1.0:
            self._ap_ts = _now
            try:
                self._auto_pit = bool(engineer_cfg.load().get("auto_pit", False))
            except Exception:
                pass
        # MENU VERO: voci reali con valore
        ITEMS = (("SPEED UNIT",
                  self._prefs.get("speed_unit", "KPH")),
                 ("ELECTRIC CONTROL",
                  "ON" if self._prefs.get("electric_control")
                  else "OFF"),
                 ("AUTO PIT",
                  "ON" if self._auto_pit else "OFF"))
        f = QFont(FAM)
        f.setPixelSize(max(6, int(44 * by)))
        p.setFont(f)
        lh = 58.0 * by
        for i, (it, vv) in enumerate(ITEMS):
            sel = (i == self._m3_sel)
            p.setPen(QPen(QColor("#2fa8e0") if sel
                          else QColor(255, 255, 255, 230)))
            p.drawText(QRectF(40 * bx, y0 + (18 + i * 58) * by,
                              900 * bx, lh),
                       Qt.AlignLeft | Qt.AlignVCenter, it)
            p.setPen(QPen(QColor(255, 255, 255, 235)))
            p.drawText(QRectF(700 * bx, y0 + (18 + i * 58) * by,
                              580 * bx, lh),
                       Qt.AlignRight | Qt.AlignVCenter,
                       "<%s>" % vv)
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
            p.drawText(QRectF(40 * bx, y0 + 560 * by,
                              1254 * bx, 60 * by),
                       Qt.AlignLeft | Qt.AlignVCenter, _msg[0])
            p.setFont(f)                      # ripristina la legenda
            p.setPen(QPen(QColor(255, 255, 255, 180)))
        # comandi NOSTRI: croce del pad
        p.drawText(QRectF(0, yb, _W, 34 * by), Qt.AlignCenter,
                   "LEFT/RIGHT/UP/DOWN = Move")

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
        # MOTORE SPENTO (rpm a zero): niente gauge, scritte di stato
        if self._rpm is not None and self._rpm < 1.0:
            f_off = QFont("CPMono_v07 Plain")
            f_off.setPixelSize(20)
            p.setFont(f_off)
            p.setPen(QPen(QColor(255, 45, 45)))
            p.drawText(QRectF(0, gy - 34, _W, 34), Qt.AlignCenter,
                       "ENGINE OFF")
            if not self._is_gt3 and self._erpm > 10.0:
                f_off.setPixelSize(15)
                p.setFont(f_off)
                p.setPen(QPen(QColor(0, 220, 90)))
                p.drawText(QRectF(0, gy + 6, _W, 26), Qt.AlignCenter,
                           "E-MOTOR ON")
            return
        self._paint_neon_gauge(p, _W / 2.0, gy, 56.0)
        # ACQUA e OLIO impilati a SINISTRA in basso: le ICONE PNG di
        # assets/icons (ok normale, warn quando il motore surriscalda)
        try:
            if not hasattr(self, "_px_wat_ok"):
                _ip = _ROOT / "assets" / "icons"
                self._px_wat_ok = QPixmap(str(_ip / "water_ok.png"))
                self._px_wat_wn = QPixmap(str(_ip / "water_warn.png"))
                self._px_oil_ok = QPixmap(str(_ip / "oil_ok.png"))
                self._px_oil_wn = QPixmap(str(_ip / "oil_warn.png"))
            # spie come il vecchio HUD: acqua >=110, olio >=125
            # (pulsano), warn fisso a motore spento
            _eoff9 = (self._rpm or 0.0) < 50.0
            _wt9 = self._water or 0.0
            _ot9 = self._oil or 0.0
            _pw9 = _wt9 >= 110.0
            _po9 = _ot9 >= 125.0
            wpx = self._px_wat_wn if (_pw9 or _eoff9) \
                else self._px_wat_ok
            opx = self._px_oil_wn if (_po9 or _eoff9) \
                else self._px_oil_ok
            # blocco COMPATTO e ordinato, appoggiato al cerchio:
            # icona 18px + valore 11px, due righe allineate a destra
            f_t = QFont("CPMono_v07 Plain")
            f_t.setPixelSize(11)
            p.setFont(f_t)
            p.setPen(QColor(255, 255, 255, 240))
            _xr = _W / 2.0 - 72.0        # bordo destro del blocco
            p.drawPixmap(QRectF(_xr - 44, gy + 18, 18, 18).toRect(),
                         wpx)
            if self._water is not None:
                p.drawText(QRectF(_xr - 40, gy + 18, 44, 18),
                           Qt.AlignRight | Qt.AlignVCenter,
                           "%.0f°C" % self._water)
            p.drawPixmap(QRectF(_xr - 35, gy + 34, 18, 18).toRect(),
                         opx)
            if self._oil is not None:
                p.drawText(QRectF(_xr - 29, gy + 34, 44, 18),
                           Qt.AlignRight | Qt.AlignVCenter,
                           "%.0f°C" % self._oil)
        except Exception:
            pass
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

        f_gear = QFont("Bebas Neue", 34)
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
        f_gl = QFont("Heebo", 13)
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
        f_l = QFont("CPMono_v07 Plain")
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
            if pv is not None and pv != _cmp:
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
            f_l.setPixelSize(8)
            p.setFont(f_l)
            p.setPen(QColor(255, 255, 255, 200))
            p.drawText(QRectF(rx, y + 3, bw, 10), Qt.AlignCenter, lbl)
            # SELEZIONE: lo STESSO numero diventa giallo e un po'
            # piu' grande
            _sel9 = (i == self._ctrl_sel)
            f_l.setPixelSize(19 if _sel9 else 15)
            p.setFont(f_l)
            p.setPen(QColor("#ffed00") if _sel9
                     else QColor(255, 255, 255, 245))
            p.drawText(QRectF(rx, y + 11 if _sel9 else y + 13,
                              bw, 23 if _sel9 else 21),
                       Qt.AlignCenter, val)

    def _paint_neon_gauge(self, p, cx, cy, r):
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
        _gsz = int(60 - 36 * k9)          # 60 -> 24
        _gcy9 = cy - (r * 0.48) * k9      # centro -> meta' alta
        f_g = QFont("CPMono_v07 Plain", max(12, _gsz))
        p.setFont(f_g)
        fg = QFontMetricsF(f_g)
        p.setPen(QColor(255, 255, 255, 245))
        gear = _gsym(g)
        p.drawText(QPointF(cx - fg.horizontalAdvance(gear) / 2.0,
                           _gcy9 + fg.capHeight() / 2.0), gear)
        if k9 > 0.0 and _state9 is not None and _state9 != "POPUP":
            # meta' bassa col COLORE dello stato attivo + testo grande
            _bg9, _tx9, _tc9 = _state9
            p.setPen(Qt.NoPen)
            _bg9 = QColor(_bg9)
            _bg9.setAlpha(int(235 * k9))
            p.setBrush(_bg9)
            _ri = r - 2.5
            p.drawPie(QRectF(cx - _ri, cy - _ri, _ri * 2, _ri * 2),
                      180 * 16, 180 * 16)
            fL = QFont("CPMono_v07 Plain")
            fL.setPixelSize(26)
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
            f9 = QFont("CPMono_v07 Plain")
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
        f_s = QFont("CPMono_v07 Plain", 19)
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
        FAM = "CPMono_v07 Plain"
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
        f_ps = QFont("Druk Wide Cy TT", 22)
        f_ps.setWeight(QFont.Black)
        f_ps.setItalic(True)
        p.setFont(f_ps)
        p.setPen(QColor(hf))
        p.drawText(QPointF(x + 2.0, 32.0),
                   "P%d" % (self._place or 14))
        # ── ROW ALTA: <MDF> celeste a sinistra, pagina 1/3 a destra
        #    (font del dash; i numeri header sono stati spostati qui)
        f_row = QFont("CPMono_v07 Plain")
        f_row.setPixelSize(11)
        p.setFont(f_row)
        # in basso a DESTRA: <MDF> celeste + numero moduli
        rr = QRectF(14, _H - self.ROW_B, _W - 28, self.ROW_B)
        n_pg = max(1, len(self._active_mods()))
        _num = "%d/%d" % ((self._page % n_pg) + 1, n_pg)
        # in basso a SINISTRA: titolo del modulo in giallo VR46
        _TIT = {1: "DASHBOARD", 2: "PIT", 3: "SETTINGS"}
        _mcur = self._active_mods()[self._page % n_pg]
        p.setPen(QColor("#ffed00"))
        p.drawText(rr, Qt.AlignLeft | Qt.AlignVCenter,
                   _TIT.get(_mcur, ""))
        # al CENTRO: RADIO ON/OFF (dal menu overlay) e poi TELEMETRY
        _fm2 = QFontMetricsF(f_row)
        _r_on = getattr(self, "_radio_en", False)
        _t_on = getattr(self, "_tele_rec", False)
        _rtxt = "RADIO ON" if _r_on else "RADIO OFF"
        _ttxt = "TELEMETRY ON" if _t_on else "TELEMETRY OFF"
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
        frac = self._lico
        if frac >= 0.015:
            if self._thr_in > 0.15:
                on = int(time.monotonic() * 3) % 2 == 0
                side = [("#ff2ad9" if on and (frac * ns - i) > 0.1
                         else None) for i in range(ns)]
            else:
                side = ["#b678ff" if (frac * ns - i) > 0.1 else None
                        for i in range(ns)]
            colsL = colsR = side
        else:
            sig = self._grip_signal()
            colsL = [sig["L"]] * ns
            colsR = [sig["R"]] * ns
        for i in range(ns):
            self._led_mini(p, QRectF(lx + i * (lws + gap), y, lws, lh),
                           colsL[i], lit=bool(colsL[i]))
            self._led_mini(p, QRectF(rx + i * (lws + gap), y, lws, lh),
                           colsR[i], lit=bool(colsR[i]))
