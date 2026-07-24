"""
widgets/map/widget.py — Overlay Mappa (stile TinyPedal).

- Registra il tracciato dal giro pulito del player (mPos x,z) e i confini dei
  settori, salvando in settings/maps/<pista>.json (una volta sola per circuito).
- Disegna il layout e ci piazza TUTTE le auto come pallini colorati per
  categoria (HY/P2/P3/GT3/GTE), col player evidenziato.
- Bandiere: i settori in giallo vengono evidenziati sul tracciato; le auto in
  fase gialla hanno un anello giallo; le auto ai box sono in cavo.
- Segno del traguardo. Ridimensionabile. Auto-hide fuori pista, drag-save, ⚙.
"""
import json
import re
import time
import math
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath, QPixmap, QPolygonF

from core.config import get_config
from core.shared_memory import SharedMemory
from .reader import MapReader
from .style import load_qss

_ROOT = Path(__file__).parent.parent.parent
from core.paths import POSITIONS_FILE  # dati utente, fuori dall'app
MAPS_DIR = _ROOT / "settings" / "maps"
TRACKMAP_DIR = _ROOT / "settings" / "trackmap"   # SVG pronti (stile TinyPedal)
AUTOMAP_DIR = _ROOT / "settings" / "trackmap_auto"  # dotazione app
try:
    from core.paths import USER_DIR as _UDM
    USERMAP_DIR = _UDM / "trackmap_auto"   # registrate dall'UTENTE (vince)
except Exception:
    USERMAP_DIR = AUTOMAP_DIR

_CLASS_COL = {
    "HY":  QColor("#bd1016"),
    "P2":  QColor("#1e3163"),
    "P3":  QColor("#411c52"),
    "GT3": QColor("#01824d"),
    "GTE": QColor("#ff9100"),
}
_YELLOW = QColor("#ffd400")


def _safe(track):
    s = "".join(c for c in (track or "") if c.isalnum() or c in "-_ ").strip()
    return s.replace(" ", "_") or "track"


# indice {nome_pista: file.svg} costruito una volta (decodifica #Uxxxx -> unicode)
_svg_index_cache = None

def _svg_index():
    global _svg_index_cache
    if _svg_index_cache is None:
        idx = {}
        try:
            # priorita' crescente (l'ultima sovrascrive): vecchie ->
            # dotazione app -> registrate dall'UTENTE
            for _dir9 in (TRACKMAP_DIR, AUTOMAP_DIR, USERMAP_DIR):
                if not _dir9.exists():
                    continue
                for f in _dir9.glob("*.svg"):
                    name = re.sub(r"#U([0-9a-fA-F]{4})",
                                  lambda m: chr(int(m.group(1), 16)), f.stem)
                    if name.endswith("_2026"):
                        name = name[:-5]      # suffisso delle mappe NOSTRE
                    idx[name] = f
        except Exception:
            idx = {}
        _svg_index_cache = idx
    return _svg_index_cache


def _load_svg_map(track):
    """Carica un SVG pronto (coordinate globali reali + indici settore in <desc>).
    -> (path[(x,z)], secs[indici]) oppure (None, [])."""
    f = _svg_index().get(track)
    if f is None:
        return None, [], []
    try:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'points="([^"]+)"', txt)
        if not m:
            return None, []
        path = []
        for tok in m.group(1).split():
            if "," in tok:
                a, b = tok.split(",")[:2]
                path.append((float(a), -float(b)))   # nega z: SVG TinyPedal ha z invertita vs mPos
        secs = []
        dm = re.search(r"<desc>([\d,\s]+)</desc>", txt)
        if dm:
            secs = [int(x) for x in re.findall(r"\d+", dm.group(1))][:2]
        # CORSIA BOX (solo mappe auto-registrate): seconda polyline
        pit = []
        pm = re.search(r'id="pitlane"[^>]*points="([^"]+)"', txt)
        if pm:
            for tok in pm.group(1).split():
                if "," in tok:
                    a, b = tok.split(",")[:2]
                    pit.append((float(a), -float(b)))
        return (path if len(path) > 10 else None), secs, pit
    except Exception:
        return None, [], []


def _load_map(track):
    """-> (path[(x,z)], secs, pit). Prima lo SVG pronto, poi la mappa
    registrata. (None, [], []) se nessuna delle due c'è (si registra)."""
    # 1) SVG pronto (auto-registrato o TinyPedal): coordinate reali
    path, secs, pit = _load_svg_map(track)
    if path:
        return path, secs, pit
    # 2) mappa registrata in precedenza
    try:
        f = MAPS_DIR / f"{_safe(track)}.json"
        if f.exists():
            raw = json.loads(f.read_text())
            if isinstance(raw, dict):
                path = [tuple(p) for p in raw.get("path", [])]
                secs = list(raw.get("secs", []))
            else:
                path = [tuple(p) for p in raw]
                secs = []
            return path, secs, []
    except Exception:
        pass
    return None, [], []


def _save_map(track, path, secs):
    try:
        MAPS_DIR.mkdir(parents=True, exist_ok=True)
        f = MAPS_DIR / f"{_safe(track)}.json"
        data = {"path": [[round(x, 2), round(z, 2)] for (x, z) in path], "secs": list(secs)}
        f.write_text(json.dumps(data))
    except Exception:
        pass


class MapCanvas(QWidget):
    def __init__(self, scale=1.0):
        super().__init__()
        self._scale = scale
        self._size = round(380 * scale)
        try:
            _layout = get_config().widget("map").get("map_layout", 1)
        except Exception:
            _layout = 1
        _hpct = 50 if _layout == 2 else 100   # GPS = 50% fisso, mappa intera = 100%
        self._h = max(60, round(self._size * _hpct / 100))
        self.setFixedSize(self._size, self._h)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._path = None
        self._secs = []              # 2 indici: fine S1, fine S2
        self._pit9 = []              # corsia box (dalle mappe auto)
        self._cars = []
        self._track = ""
        self._sector_flags = [0, 0, 0]
        self._yellow_active = False
        self._my_dist = 0.0
        self._track_len = 0.0
        self._yellow_bands = []
        self._cum = None             # lunghezze cumulate lungo il path (m)
        self._cum_total = 0.0
        # interpolazione posizioni (fluidità): target dai dati, render = lerp
        self._targets = {}           # {id: (x,z)} ultima posizione dai dati
        self._rendered = {}          # {id: (x,z)} posizione interpolata a schermo
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick)
        self._anim.start(16)         # ~60fps
        self._last_tick = None       # per interpolazione a tempo reale (anti-scatto)
        # registrazione
        self._record = []
        self._rec_secs = []
        self._last_ld = None
        self._cur_sec = None
        self._started = False
        self._recording = False

    def _tick(self):
        """Avvicina le posizioni renderizzate ai target con smoothing a TEMPO REALE:
        anche se il timer parte irregolare (altri widget occupano il thread) la
        velocità a schermo resta costante e fluida."""
        if not self._targets:
            self._last_tick = None
            return
        now = time.monotonic()
        dt = 0.016 if self._last_tick is None else (now - self._last_tick)
        self._last_tick = now
        dt = min(max(dt, 0.001), 0.1)        # clamp (evita salti enormi dopo uno stallo)
        a = 1.0 - math.exp(-dt / 0.05)       # costante di smoothing ~50ms
        moved = False
        for cid, (tx, tz) in self._targets.items():
            rx, rz = self._rendered.get(cid, (tx, tz))
            nx = rx + (tx - rx) * a
            nz = rz + (tz - rz) * a
            self._rendered[cid] = (nx, nz)
            if abs(nx - tx) > 0.05 or abs(nz - tz) > 0.05:
                moved = True
        if moved:
            self.update()
        elif getattr(self, "_blink_active", False):
            self.update()                        # auto in pit ferma: ridisegna per il lampeggio

    def _build_cum(self):
        """Lunghezze cumulate lungo il tracciato, per mappare lapdist -> punto."""
        self._cum = None; self._cum_total = 0.0
        if not self._path or len(self._path) < 2:
            return
        cum = [0.0]
        for i in range(1, len(self._path)):
            x0, z0 = self._path[i - 1]; x1, z1 = self._path[i]
            cum.append(cum[-1] + ((x1 - x0) ** 2 + (z1 - z0) ** 2) ** 0.5)
        self._cum = cum
        self._cum_total = cum[-1]

    def _turns_map(self):
        """[(indice path, 'Tn')] — curve dalla CURVATURA del tracciato,
        numerate dalla partenza; soglia calibrata sul numero di curve
        UFFICIALE (stessa logica della mappa telemetria). Cache."""
        key = (id(self._path), len(self._path or []))
        if getattr(self, "_tm_key", None) == key:
            return self._tm_cache
        out = []
        ol = self._path or []
        n = len(ol)
        _step9 = 1
        if n > 20:
            # NORMALIZZAZIONE DENSITA' (24/07): le mappe auto-registrate
            # hanno un punto ogni ~3 m (le vecchie ~10) — l'analisi
            # curvatura lavora SEMPRE a passo ~8 m, poi riporta gli
            # indici sull'originale. Senza, le curve strette si
            # spezzavano (T1/T2/T3 attaccate) e i curvoni sparivano.
            _L9 = 0.0
            for i in range(1, n):
                _L9 += math.hypot(ol[i][0] - ol[i - 1][0],
                                  ol[i][1] - ol[i - 1][1])
            _sp9 = _L9 / max(1, n - 1)
            if _sp9 > 0:
                _step9 = max(1, int(round(8.0 / _sp9)))
            if _step9 > 1:
                ol = ol[::_step9]
                n = len(ol)
        if n > 20:
            hd = []
            for i in range(n):
                a = ol[i]; b = ol[(i + 1) % n]
                hd.append(math.atan2(b[1] - a[1], b[0] - a[0]))
            dh = []
            for i in range(n):
                d = hd[(i + 1) % n] - hd[i]
                while d > math.pi:
                    d -= 2 * math.pi
                while d < -math.pi:
                    d += 2 * math.pi
                dh.append(d)
            sm = [(dh[i - 1] + dh[i] + dh[(i + 1) % n]) / 3.0
                  for i in range(n)]
            TH = math.radians(2.5)

            def _detect(minang):
                i = 0; turns = []
                while i < n:
                    if abs(sm[i]) > TH:
                        j = i; tot = 0.0; apex = i; mx = 0.0
                        sgn0 = 1.0 if sm[i] > 0 else -1.0
                        while (j < n and abs(sm[j]) > TH * 0.6
                               and (sm[j] * sgn0) > 0):
                            tot += sm[j]
                            if abs(sm[j]) > mx:
                                mx = abs(sm[j]); apex = j
                            j += 1
                        # (24/07) tratto MINIMO 3 punti: lo zigzag della
                        # linea di guida registrata non e' una curva.
                        # Estensione (i..j) tenuta per i cordoli
                        if abs(tot) > minang and (j - i) >= 3:
                            turns.append((apex, i, j))
                        i = j if j > i else i + 1
                    else:
                        i += 1
                # dedupe: apici quasi coincidenti = stessa curva
                out2 = []
                for t in turns:
                    if out2 and t[0] - out2[-1][0] < 5:
                        continue
                    out2.append(t)
                return out2

            official = None
            try:
                from data.tracks import _track_logo_stem
                from data.track_info import track_info as _ti
                _info = _ti((_track_logo_stem(self._track) or "").lower())
                if _info:
                    official = int(_info[1])
            except Exception:
                official = None
            best = None
            if official:
                for deg in range(40, 5, -1):
                    t = _detect(math.radians(deg))
                    d = abs(len(t) - official)
                    if best is None or d < best[0]:
                        best = (d, t)
                    if d == 0:
                        break
            turns = best[1] if best else _detect(math.radians(28.0))
            out = [(idx * _step9, "T%d" % (k + 1),
                    i0 * _step9, j0 * _step9)
                   for k, (idx, i0, j0) in enumerate(turns)]
        self._tm_key = key
        self._tm_cache = out
        return out

    def _draw_decor9(self, p, tf, lw, vis=None):
        """CORDOLI + tacche/etichette SETTORE + numeri CURVA esterni,
        come la mappa della telemetria (rich. 24/07). vis(i) = filtro
        del focus GPS: fuori finestra non si disegna."""
        ol = self._path or []
        n = len(ol)
        if n < 20:
            return
        w = self.width(); h = self.height()
        sc = self._scale

        def _scr(i):
            x, z = ol[i % n]
            X, Y = tf(x, z)
            return QPointF(X, Y)

        def _norm(i):
            a = _scr(i - 2); b = _scr(i + 2)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            L = math.hypot(dx, dy) or 1.0
            return (-dy / L, dx / L)

        f9 = QFont("Archivo SemiExpanded")
        f9.setPixelSize(max(7, int(9 * sc)))
        f9.setBold(True)
        p.setFont(f9)
        _used9 = []                 # rettangoli etichette gia' disegnate
        _kw = max(2.5, lw * 0.5)
        # CORDOLO LUNGO (24/07): copre il tratto VERO della curva
        # rilevato dalla detection (i..j), non una finestrella fissa
        for _ti_idx, _lab, _i0k, _j0k in self._turns_map():
            if vis is not None and not vis(_ti_idx % n):
                continue          # fuori dal focus GPS
            c0 = _scr(_ti_idx)
            if not (-60 <= c0.x() <= w + 60 and -60 <= c0.y() <= h + 60):
                continue
            a = _scr(_ti_idx - 2); b = _scr(_ti_idx + 2)
            ux, uy = c0.x() - a.x(), c0.y() - a.y()
            vx, vy = b.x() - c0.x(), b.y() - c0.y()
            _ins = 1.0 if (ux * vy - uy * vx) > 0 else -1.0   # lato interno
            _off = lw / 2.0 + _kw / 2.0 + 1.0
            kpath = QPainterPath(); started = False
            for i in range(_i0k - 1, _j0k + 2):
                cc = _scr(i)
                nx, ny = _norm(i)
                pt = QPointF(cc.x() + nx * _ins * _off,
                             cc.y() + ny * _ins * _off)
                if not started:
                    kpath.moveTo(pt); started = True
                else:
                    kpath.lineTo(pt)
            p.setBrush(Qt.NoBrush)
            _kp = QPen(QColor(240, 240, 240, 235), _kw)
            _kp.setCapStyle(Qt.FlatCap)
            p.setPen(_kp); p.drawPath(kpath)          # base bianca
            _kr = QPen(QColor(224, 40, 60, 235), _kw)
            _kr.setCapStyle(Qt.FlatCap)
            _kr.setDashPattern([2.0, 2.0])            # strisce rosse
            p.setPen(_kr); p.drawPath(kpath)
            # numero curva sul lato ESTERNO — con ANTI-COLLISIONE:
            # se il posto e' occupato da un'altra etichetta, si sposta
            # piu' fuori (T9/T11 uscivano una sopra l'altra, 24/07)
            nx, ny = _norm(_ti_idx)
            _tw = p.fontMetrics().horizontalAdvance(_lab)
            _r9 = None
            for _try9 in range(4):
                _d9 = lw / 2.0 + (10.0 + 11.0 * _try9) * sc
                _lx = c0.x() - nx * _ins * _d9
                _ly = c0.y() - ny * _ins * _d9
                _r9 = QRectF(_lx - _tw / 2.0 - 2, _ly - 7,
                             _tw + 4, 13)
                if not any(_r9.intersects(u) for u in _used9):
                    break
            _used9.append(_r9)
            p.setPen(QColor(0, 0, 0, 210))
            p.drawText(QPointF(_lx - _tw / 2.0 + 1, _ly + 4), _lab)
            p.setPen(QColor(230, 235, 245, 235))
            p.drawText(QPointF(_lx - _tw / 2.0, _ly + 3), _lab)
        # tacche bianche ai confini settore + etichette S1/S2/S3
        secs = [s for s in (self._secs or []) if 0 <= s < n]
        for si in secs:
            if vis is not None and not vis(si):
                continue
            nx, ny = _norm(si)
            c = _scr(si)
            hw = lw / 2.0 + 3.0
            p.setPen(QPen(QColor(255, 255, 255, 200),
                          max(1.4, lw * 0.22)))
            p.drawLine(QPointF(c.x() - nx * hw, c.y() - ny * hw),
                       QPointF(c.x() + nx * hw, c.y() + ny * hw))
        if secs:
            _sb = [0] + secs + [n - 1]
            for si in range(min(3, len(_sb) - 1)):
                mid = (_sb[si] + _sb[si + 1]) // 2
                if vis is not None and not vis(mid):
                    continue
                c = _scr(mid)
                if not (-40 <= c.x() <= w + 40 and -40 <= c.y() <= h + 40):
                    continue
                nx, ny = _norm(mid)
                lab = "S%d" % (si + 1)
                _tw = p.fontMetrics().horizontalAdvance(lab)
                _rs9 = None
                for _try9 in range(4):
                    off = lw / 2.0 + (15.0 + 11.0 * _try9) * sc
                    lx, ly = c.x() + nx * off, c.y() + ny * off
                    _rs9 = QRectF(lx - _tw / 2.0 - 2, ly - 7,
                                  _tw + 4, 13)
                    if not any(_rs9.intersects(u) for u in _used9):
                        break
                _used9.append(_rs9)
                p.setPen(QColor(0, 0, 0, 210))
                p.drawText(QPointF(lx - _tw / 2.0 + 1, ly + 4), lab)
                p.setPen(QColor(255, 255, 255, 235))
                p.drawText(QPointF(lx - _tw / 2.0, ly + 3), lab)

    def set_data(self, track, cars, player, sector_flags, player_sector,
                 yellow_active=False, my_dist=0.0, track_len=0.0, yellow_bands=None):
        if track and track != self._track:
            self._track = track
            # indice SVG RIFRESCATO a ogni cambio pista: la mappa
            # auto-registrata puo' essere nata dopo l'avvio del widget
            global _svg_index_cache
            _svg_index_cache = None
            self._path, self._secs, self._pit9 = _load_map(track)
            self._record = []; self._rec_secs = []
            self._last_ld = None; self._cur_sec = None
            self._started = False
            self._recording = self._path is None
            self._build_cum()
        self._cars = cars or []
        self._blink_active = any(c.get("in_pits") and not c.get("garage") for c in self._cars)
        self._sector_flags = sector_flags or [0, 0, 0]
        self._yellow_active = bool(yellow_active)
        self._my_dist = float(my_dist)
        self._track_len = float(track_len)
        self._yellow_bands = yellow_bands or []
        # aggiorna i target di posizione (il _tick interpola verso questi)
        live = set()
        for c in self._cars:
            cid = c["id"]; live.add(cid)
            self._targets[cid] = (c["x"], c["z"])
            if cid not in self._rendered:
                self._rendered[cid] = (c["x"], c["z"])
        # rimuovi auto sparite
        for cid in list(self._targets.keys()):
            if cid not in live:
                self._targets.pop(cid, None); self._rendered.pop(cid, None)
        if self._recording and player and not player.get("in_pits"):
            self._record_point(player, player_sector)
        self.update()

    def _record_point(self, player, player_sector):
        x, z, ld = player["x"], player["z"], player["lapdist"]
        wrapped = self._last_ld is not None and ld < self._last_ld - 50
        self._last_ld = ld
        if wrapped:
            if self._started and len(self._record) > 80:
                self._path = self._record[:]
                self._secs = self._rec_secs[:2]
                _save_map(self._track, self._path, self._secs)
                self._build_cum()
                self._recording = False
                return
            # primo traguardo: comincia a registrare un giro intero
            self._started = True
            self._record = []
            self._rec_secs = []
            self._cur_sec = player_sector
        if self._started:
            if not self._record or (abs(x - self._record[-1][0]) + abs(z - self._record[-1][1])) > 4:
                self._record.append((x, z))
            # confine settore (1=S1 -> 2=S2 -> 0=S3)
            if player_sector is not None and player_sector != self._cur_sec:
                if len(self._rec_secs) < 2:
                    self._rec_secs.append(len(self._record))
                self._cur_sec = player_sector

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width(); h = self.height()
        sc = self._scale
        pad = 14 * sc

        if not self._path:
            p.setPen(QPen(QColor("#8a8a90")))
            f = QFont("Archivo SemiExpanded"); f.setPixelSize(int(11 * sc)); f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Recording lap…" if self._recording else "No track data")
            p.end(); return

        xs = [pt[0] for pt in self._path]; zs = [pt[1] for pt in self._path]
        minx, maxx = min(xs), max(xs); minz, maxz = min(zs), max(zs)
        spanx = max(1e-3, maxx - minx); spanz = max(1e-3, maxz - minz)
        avail = min(w, h) - 2 * pad
        scl = min(avail / spanx, avail / spanz)
        offx = (w - spanx * scl) / 2
        offz = (h - spanz * scl) / 2

        # ── layout 2: vista GPS, player al centro, pista ruotata e zoomata ──
        _cfg = get_config().widget("map")
        layout = _cfg.get("map_layout", 1)
        # MAPPA ADATTIVA (rich. 24/07): intera di norma, ma quando
        # qualcuno ti arriva VICINO (~80 m lungo il nastro) passa da
        # sola alla vista GPS zoomata per vedere la battaglia; torna
        # intera quando il vicino sparisce da >130 m per 3 secondi
        if layout == 1 and _cfg.get("map_adaptive") \
                and self._track_len > 0:
            _md9 = None
            for c in self._cars:
                if c.get("is_player") or c.get("garage") \
                        or c.get("in_pits"):
                    continue
                _ld9 = c.get("lapdist")
                if _ld9 is None:
                    continue
                d9 = abs((_ld9 - self._my_dist) % self._track_len)
                d9 = min(d9, self._track_len - d9)
                if _md9 is None or d9 < _md9:
                    _md9 = d9
            _now9 = time.monotonic()
            st9 = getattr(self, "_adapt9", None) or {"on": False,
                                                     "t": 0.0}
            if _md9 is not None and _md9 < 80.0:
                st9["on"] = True
                st9["t"] = _now9
            elif st9["on"]:
                if _md9 is not None and _md9 <= 130.0:
                    st9["t"] = _now9
                elif _now9 - st9["t"] > 3.0:
                    st9["on"] = False
            self._adapt9 = st9
            if st9["on"]:
                layout = 2
        dot_mult = 1.0
        track_w_mult = 1.0
        ply = None
        for c in self._cars:
            if c.get("is_player"):
                ply = self._rendered.get(c["id"], (c["x"], c["z"])); break

        if layout == 2 and ply is not None:
            px, pz = ply
            zoom = 5.5                                          # zoom unico (ex livello 3)
            gcal = 0.7                                          # 0.7 diventa lo standard 1.0
            z2 = scl * zoom * gcal
            track_w_mult = 2.6 * gcal                           # pista (come a 0.7)
            dot_mult = 1.75 * gcal                              # piloti (come a 0.7)
            hm = getattr(self, "_l2_hm", -math.pi / 2.0)        # heading map-space (smussato)
            prev = getattr(self, "_l2_prev", None)
            _now = time.monotonic()
            _hdt = 0.016 if not hasattr(self, "_l2_t") else (_now - self._l2_t)
            self._l2_t = _now
            _hdt = min(max(_hdt, 0.001), 0.05)                  # clamp: assorbe i freeze (standings)
            pu, pv = px, -pz
            if prev is not None:
                du = pu - prev[0]; dv = pv - prev[1]
                if du * du + dv * dv > 0.03:                    # soglia bassa: aggiorna anche piano
                    target = math.atan2(dv, du)
                    diff = (target - hm + math.pi) % (2 * math.pi) - math.pi
                    a = 1.0 - math.exp(-_hdt / 0.12)            # low-pass a tempo reale
                    hm += diff * a
                    self._l2_hm = hm
            self._l2_prev = (pu, pv)
            self._gps_active = True                             # repaint continuo per rotazione fluida
            a = -math.pi / 2.0 - hm                             # ruota così l'heading punta in alto
            ca = math.cos(a); sa = math.sin(a)
            cx2 = w / 2.0; cy2 = h / 2.0

            def tf(x, z):
                u = x - px; v = pz - z
                return (cx2 + (u * ca - v * sa) * z2,
                        cy2 + (u * sa + v * ca) * z2)
        else:
            self._gps_active = False
            def tf(x, z):
                return (offx + (x - minx) * scl, offz + (maxz - z) * scl)

        # ── FOCUS GPS (rich. 24/07): in vista GPS si disegna SOLO il
        # tratto di pista ATTORNO al player (±550 m lungo il nastro) —
        # le strade parallele lontane sparivano nel nulla e "si
        # vedevano tre strade senza capirci niente" ──
        _vis9 = None
        _arcvis9 = None
        if layout == 2 and ply is not None and self._cum \
                and self._cum_total > 0 and self._track_len > 0:
            _tgt9 = ((self._my_dist or 0.0) % self._track_len) \
                / self._track_len * self._cum_total
            # finestra LISCIATA (rich. 24/07: "scatta"): insegue la
            # posizione con un low-pass, con wrap sul giro
            _prev9 = getattr(self, "_pd_s9", None)
            if _prev9 is None:
                _pd9 = _tgt9
            else:
                _dd9 = (_tgt9 - _prev9 + self._cum_total / 2.0) \
                    % self._cum_total - self._cum_total / 2.0
                _pd9 = (_prev9 + _dd9 * 0.25) % self._cum_total
            self._pd_s9 = _pd9
            _vw9 = 550.0

            def _vis9(i, _pd=_pd9, _vw=_vw9):
                d = abs(self._cum[min(i, len(self._cum) - 1)] - _pd)
                d = min(d, self._cum_total - d)
                return d <= _vw

            def _arcvis9(ld, _pd=_pd9, _vw=_vw9):
                # stessa finestra, ma per la LAPDIST delle auto
                if ld is None:
                    return True
                d = abs((ld % self._track_len) / self._track_len
                        * self._cum_total - _pd)
                d = min(d, self._cum_total - d)
                return d <= _vw + 60.0

        def arc(p0, p1, color, width):
            if p1 <= p0:
                return
            sub = QPainterPath()
            _op = False
            for i in range(p0, p1):
                if _vis9 is not None and not _vis9(i):
                    _op = False
                    continue
                X, Y = tf(*self._path[i])
                if not _op:
                    sub.moveTo(X, Y); _op = True
                else:
                    sub.lineTo(X, Y)
            p.setPen(QPen(color, width)); p.setBrush(Qt.NoBrush)
            p.drawPath(sub)

        # ── CORSIA BOX (dalla mappa auto-registrata): sotto la pista,
        # cosi' si vede DOVE vanno le macchine quando sono nel pit ──
        _plw = max(2.5, 3.0 * sc) * track_w_mult
        if getattr(self, "_pit9", None) and len(self._pit9) >= 4:
            if _vis9 is None or ply is None:
                pl9 = QPainterPath()
                _px9, _py9 = tf(*self._pit9[0]); pl9.moveTo(_px9, _py9)
                for (x, z) in self._pit9[1:]:
                    X, Y = tf(x, z); pl9.lineTo(X, Y)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(0, 0, 0, 80), _plw + 2.0))
                p.drawPath(pl9)
                # stile LMU: tinta pista OPACIZZATA/trasparente
                p.setPen(QPen(QColor(243, 244, 248, 105), _plw))
                p.drawPath(pl9)
            else:
                # in GPS la corsia SFUMA con la distanza dal player:
                # niente pezzi che restano in giro (rich. 24/07)
                def _wp9(q):
                    d = math.hypot(q[0] - ply[0], q[1] - ply[1])
                    if d <= 330.0:
                        return 1.0
                    if d >= 500.0:
                        return 0.0
                    return 1.0 - (d - 330.0) / 170.0
                p.setBrush(Qt.NoBrush)
                for _alp9, _colp9, _wwp9 in (
                        (80, QColor(0, 0, 0), _plw + 2.0),
                        (105, QColor(243, 244, 248), _plw)):
                    for i in range(1, len(self._pit9)):
                        _wa9 = min(_wp9(self._pit9[i - 1]),
                                   _wp9(self._pit9[i]))
                        if _wa9 <= 0.03:
                            continue
                        _c9 = QColor(_colp9)
                        _c9.setAlpha(int(_alp9 * _wa9))
                        p.setPen(QPen(_c9, _wwp9, Qt.SolidLine,
                                      Qt.RoundCap))
                        p.drawLine(
                            QPointF(*tf(*self._pit9[i - 1])),
                            QPointF(*tf(*self._pit9[i])))

        # ── tracciato: bordo nero opacizzato sotto + linea chiara sopra ──
        lw = max(4.0, 5.0 * sc) * track_w_mult
        _hw9 = lw + max(3.0, 3.5 * sc) * track_w_mult
        if _vis9 is None:
            base = QPainterPath()
            fx, fy = tf(*self._path[0]); base.moveTo(fx, fy)
            for (x, z) in self._path[1:]:
                X, Y = tf(x, z); base.lineTo(X, Y)
            base.closeSubpath()
            p.setPen(QPen(QColor(0, 0, 0, 150), _hw9))
            p.setBrush(Qt.NoBrush)
            p.drawPath(base)
            p.setPen(QPen(QColor("#f3f4f8"), lw))
            p.drawPath(base)
        else:
            # FOCUS GPS SFUMATO (rich. 24/07): nucleo pieno attorno al
            # player + estremita' che EVAPORANO in trasparenza, niente
            # taglio netto che scatta mentre la finestra avanza
            _CORE9, _EDGE9 = 430.0, 550.0

            def _wf9(i):
                d = abs(self._cum[min(i, len(self._cum) - 1)] - _pd_l9)
                d = min(d, self._cum_total - d)
                if d <= _CORE9:
                    return 1.0
                if d >= _EDGE9:
                    return 0.0
                return 1.0 - (d - _CORE9) / (_EDGE9 - _CORE9)

            _pd_l9 = self._pd_s9
            _n9 = len(self._path)
            _ws9 = [_wf9(i) for i in range(_n9)]
            base = QPainterPath()
            _opb9 = False
            for i, (x, z) in enumerate(self._path):
                if _ws9[i] < 1.0:
                    _opb9 = False
                    continue
                X, Y = tf(x, z)
                if not _opb9:
                    base.moveTo(X, Y); _opb9 = True
                else:
                    base.lineTo(X, Y)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 150), _hw9))
            p.drawPath(base)
            for _al9, _hex9, _ww9 in ((150, None, _hw9),
                                      (255, "#f3f4f8", lw)):
                for i in range(1, _n9):
                    _wa9 = min(_ws9[i - 1], _ws9[i])
                    if _wa9 <= 0.03 or _wa9 >= 1.0:
                        continue
                    _c9 = QColor(_hex9) if _hex9 else QColor(0, 0, 0)
                    _c9.setAlpha(int(_al9 * _wa9))
                    p.setPen(QPen(_c9, _ww9, Qt.SolidLine, Qt.RoundCap))
                    p.drawLine(QPointF(*tf(*self._path[i - 1])),
                               QPointF(*tf(*self._path[i])))
            p.setPen(QPen(QColor("#f3f4f8"), lw))
            p.drawPath(base)
        # cordoli + settori + numeri curva (come la mappa telemetria)
        try:
            self._draw_decor9(p, tf, lw, _vis9)
        except Exception:
            pass

        # ── giallo: una banda da OGNI colpevole verso 500m DIETRO di lui (tutte le gialle) ──
        if (self._yellow_bands and self._cum and self._cum_total > 0
                and self._track_len > 0):
            tl = self._track_len
            ratio = tl / self._cum_total
            yw = max(4.0, 5.0 * sc) * track_w_mult
            p.setPen(QPen(_YELLOW, yw)); p.setBrush(Qt.NoBrush)

            def draw_band(d0, d1):
                a = d0 % tl
                b = d1 % tl
                wrapped = b < a
                seg = None
                for i, (x, z) in enumerate(self._path):
                    ld = self._cum[i] * ratio
                    inb = (ld >= a or ld <= b) if wrapped else (a <= ld <= b)
                    if inb:
                        X, Y = tf(x, z)
                        if seg is None:
                            seg = QPainterPath(); seg.moveTo(X, Y)
                        else:
                            seg.lineTo(X, Y)
                    elif seg is not None:
                        p.drawPath(seg); seg = None
                if seg is not None:
                    p.drawPath(seg)

            for d0, d1 in self._yellow_bands:
                draw_band(d0, d1)

        # ── divisori settori sulla pista (tacche trasversali) ──
        def sector_tick(idx, color, length, width):
            n = len(self._path)
            if n < 3:
                return
            i = max(1, min(idx, n - 2))
            x0, z0 = self._path[i - 1]; x1, z1 = self._path[i + 1]
            X0, Y0 = tf(x0, z0); X1, Y1 = tf(x1, z1)
            dx, dy = X1 - X0, Y1 - Y0
            ln = (dx * dx + dy * dy) ** 0.5 or 1.0
            px, py = -dy / ln, dx / ln               # perpendicolare
            Xc, Yc = tf(*self._path[i])
            half = length / 2
            p.setPen(QPen(color, width))
            p.drawLine(QPointF(Xc - px * half, Yc - py * half),
                       QPointF(Xc + px * half, Yc + py * half))

        if len(self._secs) >= 2:
            tick_len = max(10.0, 12.0 * sc); tick_w = max(2.0, 2.4 * sc)
            sector_tick(self._secs[0], QColor("#00aaff"), tick_len, tick_w)  # S1|S2
            sector_tick(self._secs[1], QColor("#00aaff"), tick_len, tick_w)  # S2|S3

        # ── traguardo (tacca al punto 0) ──
        sfx, sfy = tf(*self._path[0])
        p.setPen(QPen(QColor("#ff3b30"), max(2.4, 2.8 * sc)))
        sector_tick(0, QColor("#ff3b30"), max(12.0, 14.0 * sc), max(2.4, 2.8 * sc))

        # ── auto ── (posizione interpolata per fluidità)
        r = 7.8 * sc * dot_mult
        garage_cars = []
        def _shadow(X, Y, rad):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 80))
            p.drawEllipse(QPointF(X + 1.3 * sc, Y + 1.3 * sc), rad + 0.8 * sc, rad + 0.8 * sc)

        def draw_dot(cx, cy, c, base_r):
            col = _CLASS_COL.get(c.get("cls", ""), QColor("#9aa0a8"))
            in_pit = c.get("in_pits")
            in_garage = c.get("garage")
            is_yellow = bool(c.get("yellow"))
            is_player = c.get("is_player")
            rr = base_r
            _shadow(cx, cy, base_r)
            if is_player:
                if in_garage:
                    fillc = QColor("#f3f4f8"); numc = col                 # garage: colorato come normale
                elif is_yellow:
                    fillc = QColor("#000000"); numc = _YELLOW              # gialla
                elif in_pit:
                    _bon = int(time.monotonic() * 2.5) % 2 == 0
                    fillc = QColor("#cc5500") if _bon else QColor("#000000")  # pit lampeggiante
                    numc = QColor("#ffffff")
                else:
                    fillc = QColor("#f3f4f8"); numc = col                  # normale: bg bianco, numero classe
                p.setPen(QPen(col, max(1.6, 1.8 * sc)))                    # anello colore classe
                p.setBrush(QBrush(fillc))
            else:
                if in_garage:
                    fillc = QColor("#000000"); numc = QColor("#ffffff")    # garage: nero fisso
                    p.setPen(QPen(col, max(1.6, 1.8 * sc)))                # anello classe
                elif is_yellow:
                    rr = base_r + 1.4 * sc
                    fillc = QColor("#000000"); numc = _YELLOW
                    p.setPen(QPen(col, max(2.0, 2.2 * sc)))                # anello classe
                elif in_pit:
                    numc = QColor("#ffffff")
                    p.setPen(QPen(col, max(1.6, 1.8 * sc)))                # pit: anello classe
                    _bon = int(time.monotonic() * 2.5) % 2 == 0
                    fillc = QColor("#cc5500") if _bon else QColor("#000000")  # pit lampeggiante
                else:
                    fillc = col; numc = QColor("#ffffff")
                    p.setPen(Qt.NoPen)
                p.setBrush(QBrush(fillc))
            p.drawEllipse(QPointF(cx, cy), rr, rr)
            numtxt = c.get("num", "")
            if numtxt:
                f = QFont("Archivo SemiExpanded"); f.setBold(True)
                ratio = 1.3 if len(numtxt) <= 2 else 0.78
                f.setPixelSize(max(7, int(rr * ratio)))
                p.setFont(f)
                p.setPen(QPen(numc))
                p.drawText(QRectF(cx - rr, cy - rr, rr * 2, rr * 2), Qt.AlignCenter, numtxt)

        pcls = next((c.get("cls") for c in self._cars if c.get("is_player")), None)
        _names9 = bool(_cfg.get("map_names", True))
        for c in self._cars:
            rx, rz = self._rendered.get(c["id"], (c["x"], c["z"]))
            X, Y = tf(rx, rz)
            if c.get("garage"):
                if pcls is None or c.get("cls") == pcls or c.get("is_player"):
                    garage_cars.append(c)                           # solo classe del pilota (+ pilota)
                continue                                            # garage: fuori dalla pista
            if _arcvis9 is not None and not c.get("is_player") \
                    and not _arcvis9(c.get("lapdist")):
                continue          # fuori dal focus GPS: pista nascosta
            draw_dot(X, Y, c, r)
            # TAG PILOTA stile F1 (rich. 24/07): 3 lettere del cognome
            # in bold bianco bordato nero — in TUTTE le viste (toggle)
            if _names9:
                _nm3 = (c.get("name", "").split() or [""])[-1][:3] \
                    .upper()
                if _nm3:
                    _ft9 = QFont("Archivo SemiExpanded")
                    _ft9.setBold(True)
                    _ft9.setPixelSize(max(8, int(9 * sc * dot_mult)))
                    p.setFont(_ft9)
                    _tx9 = X + r + 4.0
                    _ty9 = Y + 4.0
                    p.setPen(QPen(QColor(0, 0, 0, 230)))
                    for _dx9, _dy9 in ((1, 1), (-1, 1), (1, -1),
                                       (-1, -1)):
                        p.drawText(QPointF(_tx9 + _dx9, _ty9 + _dy9),
                                   _nm3)
                    p.setPen(QPen(QColor(255, 255, 255, 240)))
                    p.drawText(QPointF(_tx9, _ty9), _nm3)

        # ── auto in GARAGE: colonna stretta in basso a sinistra + label "GAR" ──
        if garage_cars:
            garage_cars.sort(key=lambda c: (c.get("cls", ""), c.get("num", "")))
            gr = max(6.0, 6.2 * sc)
            gx = gr + 6 * sc
            lbl_h = max(10, int(gr * 1.5))                 # spazio per "GAR"
            gy = self.height() - lbl_h - gr - 6 * sc       # primo dot (in basso) sopra la label
            step = gr * 2 + 4 * sc
            first_gy = gy
            for c in garage_cars:
                draw_dot(gx, gy, c, gr)                     # stesso stile della pista
                gy -= step
            # label "GAR" sotto la prima icona dal basso
            f = QFont("Archivo SemiExpanded"); f.setBold(True)
            f.setPixelSize(max(8, int(gr * 1.0)))
            p.setFont(f)
            rect = QRectF(gx - gr * 1.8, first_gy + gr + 5 * sc, gr * 3.6, lbl_h)
            p.setPen(QPen(QColor(0, 0, 0, 160)))           # ombra per leggibilità
            p.drawText(rect.translated(1, 1), Qt.AlignCenter, "GAR")
            p.setPen(QPen(QColor("#e6e8ec")))
            p.drawText(rect, Qt.AlignCenter, "GAR")
        p.end()


class MapOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU Map")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("overlay")
        self._drag_pos = None
        self._user_enabled = True

        self._mem = SharedMemory.instance()
        self._reader = MapReader()
        self._config = get_config()
        self.cfg = self._config.widget("map")

        self._build_ui()
        pos = self._load_position("map")
        self.move(pos[0], pos[1]) if pos else self.move(820, 200)
        self._apply_qss()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(self.cfg.get("update_ms", 100))

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._container = QWidget()
        self._container.setObjectName("container")
        self._container.setAttribute(Qt.WA_StyledBackground, True)
        cl = QVBoxLayout(self._container)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(0)
        self._canvas = MapCanvas(scale=self.cfg.scale)
        cl.addWidget(self._canvas, 0, Qt.AlignCenter)
        outer.addWidget(self._container)
        self.adjustSize()

    def _apply_qss(self):
        self.setStyleSheet(load_qss(self.cfg))

    def reload_config(self):
        pos = self.pos()
        self.cfg = self._config.widget("map")
        old = self.layout()
        QWidget().setLayout(old)
        self._build_ui()
        self._apply_qss()
        self.move(pos)
        self._timer.start(self.cfg.get("update_ms", 100))

    def set_enabled(self, enabled):
        self._user_enabled = enabled
        if enabled:
            self._timer.start(self.cfg.get("update_ms", 100))
            if self._mem.is_on_track():
                super().show()
                self.raise_()
        else:
            self._timer.stop()
            super().hide()

    def open_config(self):
        from gui.config_window import ConfigWindow
        from PySide6.QtGui import QGuiApplication
        if getattr(self, "_cfg_win", None) is None:
            self._cfg_win = ConfigWindow(self._config, self, widget_key="map", title="Map")
        self._cfg_win.show()
        self._cfg_win.adjustSize()
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w = self._cfg_win.width(); h = self._cfg_win.height()
        x = self.x() + self.width() + 12; y = self.y()
        if x + w > geo.right():
            x = self.x() - w - 12
        if x < geo.left() or x + w > geo.right():
            x = geo.left() + (geo.width() - w) // 2
        if y + h > geo.bottom():
            y = geo.bottom() - h
        if y < geo.top():
            y = geo.top()
        self._cfg_win.move(x, y)
        self._cfg_win.raise_()
        self._cfg_win.activateWindow()

    def mousePressEvent(self, e):
        from core.utils import overlays_locked
        if overlays_locked():
            return          # overlay BLOCCATI: niente drag
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if self._drag_pos is not None:
            self._save_position("map")
        self._drag_pos = None

    def _update(self):
        if self._user_enabled:
            on_track = self._mem.is_on_track()
            if on_track and not self.isVisible():
                super().show()
            elif not on_track and self.isVisible():
                super().hide()
                return
            if not on_track:
                return
        d = self._reader.read()
        if not d:
            return
        self._canvas.set_data(d.get("track", ""), d.get("cars"), d.get("player"),
                              d.get("sector_flags"), d.get("player_sector"),
                              d.get("yellow_active", False), d.get("my_dist", 0.0),
                              d.get("track_len", 0.0), d.get("yellow_bands"))

    def _save_position(self, key):
        try:
            data = {}
            if POSITIONS_FILE.exists():
                data = json.loads(POSITIONS_FILE.read_text())
            data[key] = [self.x(), self.y()]
            POSITIONS_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _load_position(self, key):
        try:
            if POSITIONS_FILE.exists():
                return json.loads(POSITIONS_FILE.read_text()).get(key)
        except Exception:
            pass
        return None

    def closeEvent(self, e):
        self._save_position("map")
        super().closeEvent(e)
