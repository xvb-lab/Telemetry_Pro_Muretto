# -*- coding: utf-8 -*-
"""MAPPA AUTO-REGISTRATA (24/07, idea dell'utente): al primo giro
completo e pulito (niente pit) la pista viene scritta in
settings/trackmap_auto/ nello STESSO formato degli SVG TinyPedal, ma
con le coordinate VERE del gioco: versione pista attuale, partenza =
traguardo, lapdist del gioco. I lettori (mappa review, mappa live,
curve del muretto) la preferiscono alla TinyPedal: niente piu' scarti
pista/traiettoria ne' cartelli fuori posto."""
import math
import re
from pathlib import Path

# le mappe si SCRIVONO nella cartella di configurazione dell'UTENTE
# (rich. 24/07: ogni pilota si registra le sue col primo giro, e
# sopravvivono agli aggiornamenti dell'app); quelle in
# settings/trackmap_auto dentro l'app restano come dotazione/esempio
try:
    from core.paths import USER_DIR as _UD
    _DIR = _UD / "trackmap_auto"
except Exception:
    _DIR = Path(__file__).resolve().parent.parent \
        / "settings" / "trackmap_auto"


# payload GREZZO del REST watch/trackmap: si salva TUTTO (pista,
# corsia, piazzole/griglia) — piu' roba abbiamo e meglio e' (rich. 24/07)
_RAWDIR = _DIR.parent / "trackmap_official"


def _safe_name(track):
    s = (track or "").strip()
    return re.sub(r'[<>:"/\\|?*]', "_", s) or None


# suffisso nel NOME file (rich. 24/07): "_2026" = mappa NOSTRA, unica,
# aggiornata da noi — i lettori lo ignorano nel match della pista
_SUF = "_2026"


def has_map(track):
    n = _safe_name(track)
    return bool(n and (_DIR / (n + _SUF + ".svg")).exists())


def maybe_save(track, con, lap, track_len=None, sec_lds=None):
    """Scrive la mappa se manca e il giro e' COMPLETO (copre tutta la
    lapdist). Ritorna True se scritta. Per rifarla: cancellare il file."""
    n = _safe_name(track)
    if not n or con is None or lap is None:
        return False
    dest = _DIR / (n + _SUF + ".svg")
    if dest.exists():
        # senza indici settore (scritta da sessione vecchia): rifalla
        # appena i confini sono noti; altrimenti la prima resta.
        # Le mappe UFFICIALI (REST LMU) non si toccano MAI da qui:
        # i settori li inietta add_sectors_official.
        try:
            _txt9 = dest.read_text(encoding="utf-8")
            if "UFFICIALE LMU" in _txt9[:200]:
                return False
            if sec_lds and any(b is not None for b in sec_lds) \
                    and re.search(r"<desc>\s*</desc>", _txt9):
                dest.unlink()
            else:
                return False
        except Exception:
            return False
    rows = con.execute(
        "SELECT pos_x, pos_z, lapdist FROM samples WHERE lap=? "
        "ORDER BY lapdist", (lap,)).fetchall()
    pts = [(r[0], r[1], r[2]) for r in rows
           if r[0] is not None and r[1] is not None and r[2] is not None]
    if len(pts) < 600:
        return False
    if pts[0][2] > 50.0:
        return False                        # non parte dal traguardo
    if track_len and track_len > 0 and pts[-1][2] < 0.97 * float(track_len):
        return False                        # giro non completo
    step = max(1, len(pts) // 1500)         # ~1500 punti bastano
    pts = pts[::step]
    # indici dei confini settore nella polyline (da lapdist)
    secs = []
    for b in (sec_lds or []):
        if b is None:
            continue
        lo, hi = 0, len(pts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if pts[mid][2] < b:
                lo = mid + 1
            else:
                hi = mid
        secs.append(lo)
    xs = [p[0] for p in pts]
    ys = [-p[1] for p in pts]               # convenzione TinyPedal: y = -z
    return _write_svg(dest, track, xs, ys, secs)


def add_pitlane(track, pts):
    """Aggiunge la CORSIA BOX alla mappa auto (seconda polyline
    id='pitlane') quando il pilota la percorre. Una volta scritta
    resta; per rifarla si cancella il file mappa."""
    n = _safe_name(track)
    if not n or not pts or len(pts) < 40:
        return False
    dest = _DIR / (n + _SUF + ".svg")
    if not dest.exists():
        return False                        # prima serve la mappa
    try:
        txt = dest.read_text(encoding="utf-8")
    except Exception:
        return False
    if 'id="pitlane"' in txt:
        return False
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    _diag = ((max(xs) - min(xs)) ** 2
             + (max(zs) - min(zs)) ** 2) ** 0.5
    if _diag < 150.0:
        return False                        # solo manovre nel box
    step = max(1, len(pts) // 400)
    pts = pts[::step]
    body = " ".join("%.1f,%.1f" % (x, -z) for x, z in pts)
    txt = txt.replace(
        "</svg>",
        chr(9) + '<polyline id="pitlane" fill="none" stroke="gray" '
        'stroke-width="6" points="%s"/>' % body + chr(10) + "</svg>")
    dest.write_text(txt, encoding="utf-8")
    return True


def _write_svg(dest, track, xs, ys, secs):
    """Scrive il file SVG formato TinyPedal (viewBox + polyline)."""
    mx, my = min(xs), min(ys)
    pad = 20.0
    vb = "%.4f %.4f %.4f %.4f" % (mx - pad, my - pad,
                                  (max(xs) - mx) + 2 * pad,
                                  (max(ys) - my) + 2 * pad)
    body = " ".join("%.1f,%.1f" % (x, y) for x, y in zip(xs, ys))
    _DIR.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        '<?xml version="1.0" encoding="utf-8"?>' + chr(10)
        + '<!-- Mappa registrata da LMU Telemetry Pro '
          '(coordinate vere di gioco) -->' + chr(10)
        + '<svg viewBox="%s" version="1.1" '
          'xmlns="http://www.w3.org/2000/svg">' % vb + chr(10)
        + chr(9) + '<title>%s</title>' % track + chr(10)
        + chr(9) + '<desc>%s</desc>' % ",".join(str(i) for i in secs)
        + chr(10)
        + chr(9) + '<polyline id="map" fill="none" stroke="black" '
          'stroke-width="10" points="%s"/>' % body + chr(10)
        + '</svg>' + chr(10),
        encoding="utf-8")
    return True


def save_official(track, payload, track_len=None, sf_xy=None,
                  dir_xy=None):
    """MAPPA UFFICIALE dal REST di LMU (watch/trackmap, 24/07):
    type 0 = tracciato, type 1 = corsia box. Salva SEMPRE il payload
    GREZZO completo (piazzole comprese) in trackmap_official/, poi
    scrive la _2026 ufficiale — ruotata cosi' che l'indice 0 sia il
    TRAGUARDO (sf_xy = posizione vera a lapdist~0) e nel verso di
    marcia (dir_xy = posizione a ~100 m). L'ufficiale VINCE sulla
    registrata dai giri. Ritorna True se la mappa e' stata scritta."""
    n = _safe_name(track)
    if not n or not payload:
        return False
    try:
        _RAWDIR.mkdir(parents=True, exist_ok=True)
        import json as _js
        (_RAWDIR / (n + "_lmu_raw.json")).write_text(
            _js.dumps(payload), encoding="utf-8")
    except Exception:
        pass
    try:
        t0 = [(float(q["x"]), float(q["z"])) for q in payload
              if q.get("type") == 0]
        t1 = [(float(q["x"]), float(q["z"])) for q in payload
              if q.get("type") == 1]
    except Exception:
        return False
    if len(t0) < 50:
        return False
    # SANITA' LUNGHEZZA (24/07 sera, caso Monza Curva Grande): su
    # alcuni LAYOUT CORTI il REST serve la mezzeria del circuito
    # INTERO (5732 m sul layout da ~3 km). Giudice = il righello del
    # GIOCO (track_len del giro): se la mezzeria non torna (+-15%),
    # si RIFIUTA e resta la mappa registrata dai giri, fedele al
    # layout per costruzione. Il grezzo e' comunque salvato sopra.
    try:
        if track_len:
            _La = sum(math.hypot(t0[i][0] - t0[i - 1][0],
                                 t0[i][1] - t0[i - 1][1])
                      for i in range(1, len(t0)))
            if abs(_La - float(track_len)) / float(track_len) > 0.15:
                return False
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    dest = _DIR / (n + _SUF + ".svg")
    try:
        if dest.exists() and "UFFICIALE LMU" in dest.read_text(
                encoding="utf-8")[:200]:
            return False                  # gia' ufficiale: non rifare
    except Exception:
        pass
    # rotazione: indice 0 = traguardo, avanti nel verso di marcia
    if sf_xy:
        _i0 = min(range(len(t0)),
                  key=lambda i: (t0[i][0] - sf_xy[0]) ** 2
                  + (t0[i][1] - sf_xy[1]) ** 2)
        t0 = t0[_i0:] + t0[:_i0]
        if dir_xy and len(t0) > 40:
            _fw = min((t0[i][0] - dir_xy[0]) ** 2
                      + (t0[i][1] - dir_xy[1]) ** 2
                      for i in range(1, 30))
            _bw = min((t0[-i][0] - dir_xy[0]) ** 2
                      + (t0[-i][1] - dir_xy[1]) ** 2
                      for i in range(1, 30))
            if _bw < _fw:
                t0 = [t0[0]] + t0[1:][::-1]
    xs = [p[0] for p in t0]
    ys = [-p[1] for p in t0]              # convenzione TinyPedal: y=-z
    mx, my = min(xs), min(ys)
    pad = 20.0
    vb = "%.4f %.4f %.4f %.4f" % (mx - pad, my - pad,
                                  (max(xs) - mx) + 2 * pad,
                                  (max(ys) - my) + 2 * pad)
    body = " ".join("%.1f,%.1f" % (x, y) for x, y in zip(xs, ys))
    pit_el = ""
    if len(t1) >= 10:
        pbody = " ".join("%.1f,%.1f" % (q[0], -q[1]) for q in t1)
        pit_el = (chr(9) + '<polyline id="pitlane" fill="none" '
                  'stroke="gray" stroke-width="6" points="%s"/>' % pbody
                  + chr(10))
    _DIR.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        '<?xml version="1.0" encoding="utf-8"?>' + chr(10)
        + '<!-- Mappa UFFICIALE LMU (REST watch/trackmap) -->' + chr(10)
        + '<svg viewBox="%s" version="1.1" '
          'xmlns="http://www.w3.org/2000/svg">' % vb + chr(10)
        + chr(9) + '<title>%s</title>' % track + chr(10)
        + chr(9) + '<desc></desc>' + chr(10)
        + chr(9) + '<polyline id="map" fill="none" stroke="black" '
          'stroke-width="10" points="%s"/>' % body + chr(10)
        + pit_el
        + '</svg>' + chr(10),
        encoding="utf-8")
    return True


def add_sectors_official(track, sec_lds, track_len=None):
    """Inietta gli indici settore nella mappa UFFICIALE (desc vuota):
    lapdist del gioco -> indice sulla polyline via arco riscalato."""
    n = _safe_name(track)
    _lds = [b for b in (sec_lds or []) if b]
    if not n or len(_lds) < 2:
        return False
    dest = _DIR / (n + _SUF + ".svg")
    if not dest.exists():
        return False
    try:
        txt = dest.read_text(encoding="utf-8")
    except Exception:
        return False
    if "UFFICIALE LMU" not in txt[:200] or "<desc></desc>" not in txt:
        return False
    m = re.search(r'id="map"[^>]*points="([^"]+)"', txt)
    if not m:
        return False
    import math as _m
    import bisect as _bs
    pts = []
    for tok in m.group(1).split():
        if "," in tok:
            a, b = tok.split(",")[:2]
            pts.append((float(a), float(b)))
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + _m.hypot(pts[i][0] - pts[i - 1][0],
                                      pts[i][1] - pts[i - 1][1]))
    if cum[-1] <= 0:
        return False
    try:
        _tl = float(track_len) if track_len else cum[-1]
    except (TypeError, ValueError):
        _tl = cum[-1]
    idxs = []
    for ld in sorted(_lds)[:2]:
        target = float(ld) / _tl * cum[-1]
        idxs.append(min(_bs.bisect_left(cum, target), len(pts) - 1))
    txt = txt.replace("<desc></desc>",
                      "<desc>%d,%d</desc>" % (idxs[0], idxs[1]), 1)
    dest.write_text(txt, encoding="utf-8")
    return True
