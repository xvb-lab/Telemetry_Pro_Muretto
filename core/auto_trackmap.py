# -*- coding: utf-8 -*-
"""MAPPA AUTO-REGISTRATA (24/07, idea dell'utente): al primo giro
completo e pulito (niente pit) la pista viene scritta in
settings/trackmap_auto/ nello STESSO formato degli SVG TinyPedal, ma
con le coordinate VERE del gioco: versione pista attuale, partenza =
traguardo, lapdist del gioco. I lettori (mappa review, mappa live,
curve del muretto) la preferiscono alla TinyPedal: niente piu' scarti
pista/traiettoria ne' cartelli fuori posto."""
import re
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "settings" / "trackmap_auto"


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
        # appena i confini sono noti; altrimenti la prima resta
        try:
            if sec_lds and any(b is not None for b in sec_lds) \
                    and re.search(r"<desc>\s*</desc>",
                                  dest.read_text(encoding="utf-8")):
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
