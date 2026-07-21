"""core/world_records.py — Record reali di pista (P/Q/Race) per la card azzurra.

Dati in settings/world_records.json, chiave: track corto -> classe -> sessione
(practice/qualifying/race) -> {time, driver, car, where, date, series}.

record(car_class, track_short, session_type) ritorna il record della sessione
giusta (P/Q/Race in base a session_type 0/1/2) con sigla WRP/WRQ/WRR.
"""
import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_FILE = _ROOT / "settings" / "world_records.json"
_cache = None

_CLASS_MAP = {
    "HY": "HYPERCAR", "HYP": "HYPERCAR", "HYPERCAR": "HYPERCAR", "LMH": "HYPERCAR",
    "GT3": "GT3", "LMGT3": "GT3", "GTE": "GT3",
    "P2": "LMP2", "LMP2": "LMP2",
    "P3": "LMP3", "LMP3": "LMP3",
}
_SIGLA = {"practice": "WRP", "qualifying": "WRQ", "race": "WRR"}
_LABEL = {"practice": "world record practice",
          "qualifying": "world record qualifying",
          "race": "world record race"}


def _session_key(st):
    """session_type grezzo LMU/rF2 -> practice/qualifying/race.
    0 Test day / 1-4 Practice / 9 Warmup  -> practice (running libero).
    5-8 Qualify. 10+ Race. Accetta anche stringhe ('Practice'/'Q'/'Race')."""
    try:
        st = int(st)
        if 0 <= st <= 4 or st == 9:
            return "practice"
        if 5 <= st <= 8:
            return "qualifying"
        if st >= 10:
            return "race"
        return None
    except Exception:
        pass
    s = str(st or "").strip().lower()
    if not s:
        return None
    if "pract" in s or "warm" in s or "test" in s or s in ("p", "fp", "fp1", "fp2", "fp3"):
        return "practice"
    if "qual" in s or "hotlap" in s or s in ("q", "q1", "q2", "q3"):
        return "qualifying"
    if "race" in s or s in ("r", "r1", "r2"):
        return "race"
    return None


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _norm_class(c):
    try:
        from core.classes import class_tag
        tag = class_tag(c or "")
    except Exception:
        tag = "".join(ch for ch in (c or "") if ch.isalnum()).upper()
    return {"HY": "HYPERCAR", "P2": "LMP2", "P3": "LMP3",
            "GT3": "GT3", "GTE": "GT3"}.get(tag)


# Layout alternativi/corti presenti in LMU ma NON corsi da WEC/ELMS:
# su questi il record reale non si applica -> card nascosta.
_ALT_LAYOUTS = {
    "Bahrain Outer Circuit",
    "Bahrain Paddock Circuit",
    "Lusail Short Circuit",
    "Sebring School Circuit",
    "Fuji Speedway Classic",
    "Monza Curva Grande Circuit",
}


def _short(track):
    """Nome pista corto riusando la mappa dell'app (settings/tracks.json)."""
    try:
        from telemetry.db import _short_track
        return _short_track(track or "")
    except Exception:
        t = (track or "").strip()
        return t.split()[0] if t else ""


def all_records():
    """Tutti i record reali in lista piatta, per la tab Records.
    [{track, cls, session, car, brand, driver, date, time, secs, where, series}]"""
    data = _load()
    rows = []
    for trk, classes in data.items():
        for cls, sessions in classes.items():
            for sess in ("practice", "qualifying", "race"):
                rec = sessions.get(sess)
                if not rec:
                    continue
                rows.append({
                    "track": trk, "cls": cls, "session": sess,
                    "car": rec.get("car", ""), "driver": rec.get("driver", ""),
                    "brand": rec.get("brand", ""),
                    "date": rec.get("date", ""), "time": rec.get("time", ""),
                    "secs": rec.get("secs"), "where": rec.get("where", ""),
                    "series": rec.get("series", "")})
    return rows


def record(car_class, track, session_type):
    """track = nome pista COMPLETO (es. 'Bahrain International Circuit').
    Le varianti corte/alternative (Outer, Short, ...) ritornano None."""
    data = _load()
    if (track or "").strip() in _ALT_LAYOUTS:
        return None
    cls = _norm_class(car_class)
    track_short = _short(track)
    if not cls or not track_short:
        return None
    trk = data.get(track_short)
    if not trk:
        return None
    cd = trk.get(cls)
    if not cd:
        return None
    try:
        sess = _session_key(session_type)
    except Exception:
        sess = None
    if sess is None:
        return None
    rec = cd.get(sess)
    if not rec:
        return None
    out = dict(rec)
    out["sigla"] = _SIGLA[sess]
    out["label"] = _LABEL[sess]
    return out
