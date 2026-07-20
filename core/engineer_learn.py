"""
core/engineer_learn.py — apprendimento sessione dopo sessione.

Mantiene un profilo per (pista + classe) con i valori "appresi":
consumo/giro, degrado gomme/giro, miglior tempo e settori, e per ogni
curva T1..Tn il punto di frenata e la Vmin di riferimento.

Aggiornamento a fine sessione con MEDIA MOBILE PESATA (i dati recenti
contano di piu). I profili sono semplici JSON in settings/learn/.

Non dipende dalla UI. Usato dall'Engineer all'avvio (load) e da un passaggio
post-sessione (update_from_session).
"""
import json
import re
import time
from pathlib import Path

try:
    from core import paths as _paths
    _LEARN_DIR = _paths.USER_DIR / "learn"
except Exception:
    _LEARN_DIR = Path(__file__).resolve().parent.parent / "settings" / "learn"

# versione della logica di apprendimento: se la alzo, i file gia' marcati con
# una versione inferiore verranno ri-analizzati una volta sola.
LEARN_VER = 4


def _ensure_marker_cols(con):
    for col, typ in (("learned", "INTEGER"), ("learned_ver", "INTEGER"),
                     ("learned_at", "TEXT")):
        try:
            con.execute("ALTER TABLE session_meta ADD COLUMN %s %s" % (col, typ))
        except Exception:
            pass


def is_learned(con):
    """True se questo file di telemetria e' gia' stato analizzato (versione corrente)."""
    try:
        r = con.execute(
            "SELECT learned, learned_ver FROM session_meta WHERE id=1").fetchone()
        if not r:
            return False
        learned = r["learned"] if hasattr(r, "keys") else r[0]
        ver = r["learned_ver"] if hasattr(r, "keys") else r[1]
        return bool(learned) and int(ver or 0) >= LEARN_VER
    except Exception:
        return False


def mark_learned(con):
    """Scrive il marcatore di 'analizzata' dentro il file (persistente)."""
    import time as _t
    _ensure_marker_cols(con)
    try:
        con.execute(
            "UPDATE session_meta SET learned=1, learned_ver=?, learned_at=? WHERE id=1",
            (LEARN_VER, _t.strftime("%Y-%m-%d %H:%M")))
        con.commit()
    except Exception:
        pass

# peso del dato NUOVO nella media mobile (0..1). 0.30 = il nuovo pesa 30%,
# lo storico 70%. Piu alto = si adatta piu in fretta, meno stabile.
_ALPHA = 0.30


def _slug(s):
    s = (s or "").strip()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s or "Unknown"


def profile_path(track, car_class):
    # il learning dell'ingegnere e' SEMPRE privato (per pilota), mai condiviso
    # con la squadra: ognuno guida diverso, i riferimenti non vanno mischiati.
    _LEARN_DIR.mkdir(parents=True, exist_ok=True)
    return _LEARN_DIR / ("%s_%s.json" % (_slug(track), _slug(car_class)))


def _empty_cond():
    return {"fuel_per_lap": None, "energy_per_lap": None,
            "deg_front": None, "deg_rear": None,
            "deg_wheel": [None, None, None, None],
            "corners": [],
            "best_lap": None, "sectors": [None, None, None], "samples": 0}


def load(track, car_class):
    """Profilo appreso (dict) con condizioni dry/wet. Valido anche se assente."""
    p = profile_path(track, car_class)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if "cond" not in d:
            d = {"track": track, "car_class": car_class,
                 "cond": {"dry": _empty_cond(), "wet": _empty_cond()},
                 "updated": d.get("updated")}
        d["cond"].setdefault("dry", _empty_cond())
        d["cond"].setdefault("wet", _empty_cond())
        return d
    except Exception:
        return {"track": track, "car_class": car_class,
                "cond": {"dry": _empty_cond(), "wet": _empty_cond()},
                "updated": None}


def save(prof):
    p = profile_path(prof.get("track"), prof.get("car_class"))
    try:
        p.write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _blend(old, new, alpha=_ALPHA):
    """Media mobile pesata: se non c'e' storico prende il nuovo."""
    if new is None:
        return old
    if old is None:
        return new
    return old * (1.0 - alpha) + new * alpha


# ──────────────────────────────────────────────────────────────────────────
#  Aggiornamento a fine sessione
# ──────────────────────────────────────────────────────────────────────────
def update_from_session(con, track, car_class, energy_car=False, wet=False):
    """Legge i giri PULITI dal DB e aggiorna il profilo pista+classe per
    condizione (dry/wet). Scarta gli outlier (giri molto piu' lenti della
    mediana: SC, traffico, errori). Ritorna il profilo aggiornato o None."""
    try:
        rows = con.execute(
            "SELECT lap,stint,lap_time,invalid,fuel_used,ve_used,"
            "w_fl,w_fr,w_rl,w_rr,s1,s2,s3 FROM laps "
            "WHERE lap_time>0 AND invalid=0 ORDER BY lap").fetchall()
    except Exception:
        return None
    if not rows:
        return None

    prof = load(track, car_class)
    cond = "wet" if wet else "dry"
    c = prof["cond"][cond]

    # out-lap = primo giro di ogni stint (escluso dai consumi)
    first_of_stint = {}
    for r in rows:
        st = r["stint"]
        if st not in first_of_stint:
            first_of_stint[st] = r["lap"]

    # reiezione outlier: mediana dei tempi puliti (no out-lap), soglia +7%
    body = [r["lap_time"] for r in rows
            if r["lap"] != first_of_stint.get(r["stint"]) and r["lap_time"] > 0]
    cutoff = None
    if body:
        sb = sorted(body)
        med = sb[len(sb) // 2]
        cutoff = med * 1.07            # piu' lento del 7% = giro non rappresentativo

    def _rep(r):
        """giro rappresentativo per consumi/degrado/settori?"""
        if r["lap"] == first_of_stint.get(r["stint"]):
            return False
        if cutoff is not None and r["lap_time"] and r["lap_time"] > cutoff:
            return False
        return True

    fuels, energies, laptimes = [], [], []
    s1s, s2s, s3s = [], [], []
    for r in rows:
        if not _rep(r):
            continue
        if r["fuel_used"] and r["fuel_used"] > 0:
            fuels.append(r["fuel_used"])
        if r["ve_used"] and r["ve_used"] > 0:
            energies.append(r["ve_used"])
        if r["lap_time"] and r["lap_time"] > 0:
            laptimes.append(r["lap_time"])
        if r["s1"]:
            s1s.append(r["s1"])
        if r["s2"]:
            s2s.append(r["s2"])
        if r["s3"]:
            s3s.append(r["s3"])

    def _avg(a):
        return (sum(a) / len(a)) if a else None

    # degrado/giro = cali tra giri consecutivi (solo coppie rappresentative)
    by = {}
    for r in rows:
        by.setdefault(r["stint"], []).append(r)
    df, dr = [], []
    dw = [[], [], [], []]                     # per gomma: FL, FR, RL, RR
    _WK = ("w_fl", "w_fr", "w_rl", "w_rr")
    for st, lst in by.items():
        lst = sorted(lst, key=lambda r: r["lap"])
        for i in range(1, len(lst)):
            a, b = lst[i - 1], lst[i]
            if not (_rep(a) and _rep(b)):
                continue
            for wi, k in enumerate(_WK):
                if a[k] is not None and b[k] is not None:
                    ddw = a[k] - b[k]
                    if ddw >= 0:
                        dw[wi].append(ddw)
            fa = [a[k] for k in ("w_fl", "w_fr") if a[k] is not None]
            fb = [b[k] for k in ("w_fl", "w_fr") if b[k] is not None]
            ra = [a[k] for k in ("w_rl", "w_rr") if a[k] is not None]
            rb = [b[k] for k in ("w_rl", "w_rr") if b[k] is not None]
            if len(fa) == 2 and len(fb) == 2:
                dd = sum(fa) / 2 - sum(fb) / 2
                if dd >= 0:
                    df.append(dd)
            if len(ra) == 2 and len(rb) == 2:
                dd = sum(ra) / 2 - sum(rb) / 2
                if dd >= 0:
                    dr.append(dd)

    if energy_car:
        c["energy_per_lap"] = _blend(c.get("energy_per_lap"), _avg(energies))
    else:
        c["fuel_per_lap"] = _blend(c.get("fuel_per_lap"), _avg(fuels))
    c["deg_front"] = _blend(c.get("deg_front"), _avg(df))
    c["deg_rear"] = _blend(c.get("deg_rear"), _avg(dr))
    oldw = c.get("deg_wheel") or [None, None, None, None]
    c["deg_wheel"] = [_blend(oldw[i], _avg(dw[i])) for i in range(4)]
    # PASSO-PER-USURA (s/giro per punto % di gomma): Theil-Sen sui giri
    # rappresentativi, per stint. E' il SEED del modello di passo live:
    # copre i primi giri della gara successiva, poi comanda il misurato.
    pw = []
    for st, lst in by.items():
        pts = []
        for r in sorted(lst, key=lambda r: r["lap"]):
            if not _rep(r):
                continue
            ws = [r[k] for k in _WK if r[k] is not None]
            if len(ws) == 4 and r["lap_time"] and r["lap_time"] > 0:
                pts.append((min(ws), r["lap_time"]))
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                dwv = pts[i][0] - pts[j][0]    # usura consumata (positiva)
                if abs(dwv) < 0.5:
                    continue
                pw.append((pts[j][1] - pts[i][1]) / dwv)
    if len(pw) >= 6:
        pw.sort()
        med_pw = max(0.0, min(0.20, pw[len(pw) // 2]))
        c["pace_per_wear"] = _blend(c.get("pace_per_wear"), med_pw)
    # ── INTELLIGENZA PER CURVA: apex/frenate/stress gomma dai giri migliori ──
    try:
        from core.corner_learn import analyze as _corners
        new_c = _corners(con)
        if new_c:
            old_c = c.get("corners") or []
            if not old_c:
                c["corners"] = new_c
            else:
                # fondi per distanza: media vecchio/nuovo, curve nuove aggiunte
                merged = []
                used = set()
                for oc in old_c:
                    match = [x for x in new_c
                             if abs(x["d"] - oc["d"]) < 80.0]
                    if match:
                        nc = match[0]; used.add(id(nc))
                        m = dict(oc)
                        for k in ("vmin", "ventry", "drop", "brake_d",
                                  "brake_peak", "spike"):
                            m[k] = _blend(oc.get(k), nc.get(k))
                        if nc.get("hot_wheel") is not None:
                            m["hot_wheel"] = nc["hot_wheel"]
                        merged.append(m)
                    else:
                        merged.append(oc)
                for nc in new_c:
                    if id(nc) not in used and all(
                            abs(nc["d"] - m["d"]) >= 80.0 for m in merged):
                        merged.append(nc)
                merged.sort(key=lambda x: x["d"])
                for idx, m in enumerate(merged, 1):
                    m["n"] = idx
                c["corners"] = merged[:40]
    except Exception:
        pass

    best = min(laptimes) if laptimes else None
    if best is not None:
        c["best_lap"] = best if c.get("best_lap") is None else min(c["best_lap"], best)
    for i, arr in enumerate((s1s, s2s, s3s)):
        if arr:
            mn = min(arr)
            cur = c["sectors"][i]
            c["sectors"][i] = mn if cur is None else min(cur, mn)

    c["samples"] = int(c.get("samples") or 0) + len(laptimes)
    prof["updated"] = time.strftime("%Y-%m-%d %H:%M")
    save(prof)
    mark_learned(con)
    return prof


# ──────────────────────────────────────────────────────────────────────────
#  Stime iniziali per l'Engineer (a inizio gara)
# ──────────────────────────────────────────────────────────────────────────
def baseline(track, car_class, energy_car=False, wet=False):
    """Stima di partenza dal profilo appreso, per condizione. samples basso =
    stima provvisoria (l'ingegnere lo segnala)."""
    prof = load(track, car_class)
    c = prof["cond"]["wet" if wet else "dry"]
    n = int(c.get("samples") or 0)
    return {
        "per_lap": c.get("energy_per_lap") if energy_car else c.get("fuel_per_lap"),
        "deg_front": c.get("deg_front"),
        "deg_rear": c.get("deg_rear"),
        "deg_wheel": c.get("deg_wheel"),
        "corners": c.get("corners") or [],
        "best_lap": c.get("best_lap"),
        "sectors": c.get("sectors"),
        "samples": n,
        "provisional": n < 5,          # poche evidenze: prudenza
        "wet": bool(wet),
    }


# ── self-test ──
if __name__ == "__main__":
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE laps(lap INT,stint INT,lap_time REAL,invalid INT,"
                "fuel_used REAL,ve_used REAL,w_fl REAL,w_fr REAL,w_rl REAL,w_rr REAL,"
                "s1 REAL,s2 REAL,s3 REAL)")
    con.executemany("INSERT INTO laps VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (1, 1, 90.0, 0, 0, 0, 100, 100, 100, 100, 30, 35, 25),   # out-lap
        (2, 1, 82.0, 0, 2.6, 1.1, 99, 99, 98, 98, 27, 31, 24),
        (3, 1, 81.5, 0, 2.5, 1.0, 98, 98, 96, 96, 27, 31, 23.5),
        (4, 1, 82.4, 0, 2.7, 1.2, 96, 96, 92, 92, 28, 31, 23.4),
    ])
    con.commit()
    p = update_from_session(con, "Monza Circuit", "GT3")
    c = p["cond"]["dry"]
    print("fuel/lap:", round(c["fuel_per_lap"], 2), "deg F/R:",
          round(c["deg_front"], 2), "/", round(c["deg_rear"], 2),
          "deg wheel:", [round(x, 2) if x else x for x in c["deg_wheel"]],
          "best:", c["best_lap"], "samples:", c["samples"])
    print("baseline:", baseline("Monza Circuit", "GT3"))
