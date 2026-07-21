"""core/online.py — client per il Worker LMU Ref API (Cloudflare D1).

Sostituisce il vecchio pace.py (CSV OhneSpeed). Legge i best globali via
GET /refs (una volta, poi cache locale + refresh in background) e invia il
proprio best via POST /ref (Bearer token).

Config in settings/online.json:
    {"url": "https://lmu-ref-api.<account>.workers.dev",
     "write_token": "...", "enabled": true}

Se url manca o enabled=false, tutte le funzioni degradano in modo sicuro
(nessuna rete, la card resta sui placeholder).
"""
import json
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CFG_FILE = _ROOT / "settings" / "online.json"        # config read-only (bundle)
try:
    from core import paths as _paths
    CACHE_FILE = _paths.USER_DIR / "online_cache.json"   # cache scrivibile (esterna)
except Exception:
    CACHE_FILE = _ROOT / "settings" / "online_cache.json"
MAX_AGE = 15 * 60          # 15 min

# refs: dict key -> row ; done/loading come in pace.py
_CACHE = {"refs": None, "done": False, "loading": False}


def _cfg():
    try:
        return json.loads(_CFG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _base():
    c = _cfg()
    if not c.get("enabled", True):
        return None
    u = (c.get("url") or "").strip().rstrip("/")
    return u or None


def _token():
    return (_cfg().get("write_token") or "").strip() or None


def enabled():
    return _base() is not None


# ── chiave: CLASSE_pista_COND (deve passare KEY_RE del Worker) ──────────────
def _slug(s):
    s = "".join(ch for ch in str(s or "") if ch.isalnum() or ch in " -_")
    return s.strip().replace(" ", "-")


def make_key(car_class, track, wet):
    cls = _slug(car_class)
    trk = _slug(track)
    cond = "WET" if wet else "DRY"
    if not cls or not trk:
        return None
    return "%s_%s_%s" % (cls, trk, cond)


# ── cache su disco (come pace.py) ───────────────────────────────────────────
def _cache_age():
    try:
        return time.time() - CACHE_FILE.stat().st_mtime
    except Exception:
        return None


def _load_cache_into_ram():
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            _CACHE["refs"] = {r["key"]: r for r in data.get("refs", []) if r.get("key")}
            _CACHE["done"] = True
            return True
    except Exception:
        pass
    return False


def fetch_refs(timeout=8):
    """GET /refs (BLOCCANTE) + scrittura cache. La UI usa load_async()."""
    base = _base()
    if not base:
        return _CACHE["refs"] or {}
    try:
        req = urllib.request.Request(base + "/refs",
                                     headers={"User-Agent": "LMU-TelemetryPro"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        data = json.loads(raw)
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass
        _CACHE["refs"] = {r["key"]: r for r in data.get("refs", []) if r.get("key")}
    except Exception:
        _CACHE["refs"] = _CACHE["refs"] or {}
    _CACHE["done"] = True
    return _CACHE["refs"]


def load_async(timeout=8):
    """Pronta-subito (cache locale) + refresh max 1/MAX_AGE in un thread."""
    if not _base():
        return
    if _CACHE["refs"] is None:
        _load_cache_into_ram()
    age = _cache_age()
    fresh = age is not None and age < MAX_AGE
    if _CACHE["loading"] or fresh:
        return
    _CACHE["loading"] = True

    def _work():
        try:
            fetch_refs(timeout=timeout)
        finally:
            _CACHE["loading"] = False

    threading.Thread(target=_work, name="online-fetch", daemon=True).start()


def ready():
    return _CACHE["refs"] is not None


def get_ref(key):
    """Best globale per la chiave, o None. Non scarica nulla."""
    if not key:
        return None
    if _CACHE["refs"] is None:
        _load_cache_into_ram()
    return (_CACHE["refs"] or {}).get(key)


def all_refs(refresh=False):
    """Lista di tutti i best (1 per chiave). refresh=True forza il download."""
    if refresh:
        fetch_refs()
    elif _CACHE["refs"] is None and not _load_cache_into_ram():
        fetch_refs()
    return list((_CACHE["refs"] or {}).values())


def cached_refs():
    """Best in cache (RAM/disco), senza rete. Usare con load_async() per il bg."""
    if _CACHE["refs"] is None:
        _load_cache_into_ram()
    return list((_CACHE["refs"] or {}).values())


def top(key, n=20, timeout=8):
    """Classifica giocatori per una chiave (GET /top). Lista {player, lap_ms}."""
    base = _base()
    if not base or not key:
        return []
    try:
        import urllib.parse
        q = urllib.parse.urlencode({"key": key, "n": int(n)})
        req = urllib.request.Request(base + "/top?" + q,
                                     headers={"User-Agent": "LMU-TelemetryPro"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data.get("top", []) or []
    except Exception:
        return []


# ── invio del proprio best ──────────────────────────────────────────────────
def submit(rec, timeout=8):
    """POST /ref con Bearer token (BLOCCANTE). Ritorna dict risposta o None.
    rec: dict con almeno key, lap_ms, player. Il Worker tiene il best."""
    base = _base()
    tok = _token()
    if not base or not tok or not rec or not rec.get("key"):
        return None
    try:
        body = json.dumps(rec).encode("utf-8")
        req = urllib.request.Request(
            base + "/ref", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + tok,
                     "User-Agent": "LMU-TelemetryPro"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def update_helmet_async(player, helmet, timeout=8):
    """POST /helmet: cambia la livrea su TUTTI i record del player online
    (senza dover rifare il tempo). Fire-and-forget in background."""
    base = _base(); tok = _token()
    if not base or not tok or not player or not helmet:
        return

    def _work():
        try:
            body = json.dumps({"player": player, "helmet": helmet}).encode("utf-8")
            req = urllib.request.Request(
                base + "/helmet", data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + tok,
                         "User-Agent": "LMU-TelemetryPro"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read()
            # cache locale invalidata: al prossimo load_async arrivano
            # i record con la livrea nuova
            try:
                CACHE_FILE.unlink()
            except Exception:
                pass
            _CACHE["refs"] = None
        except Exception:
            pass
    threading.Thread(target=_work, name="online-helmet", daemon=True).start()


def submit_async(rec, timeout=8):
    """submit() in un thread di sfondo (non blocca la UI)."""
    if not _base() or not _token() or not rec:
        return
    threading.Thread(target=submit, args=(rec, timeout),
                     name="online-submit", daemon=True).start()


# ── statistiche globali (driver unici) per l'header del menu ──
_STATS = {"drivers": 0, "refs": 0, "submissions": 0}


def fetch_stats(timeout=8):
    """GET /stats (BLOCCANTE). Aggiorna e ritorna il dict statistiche."""
    base = _base()
    if not base:
        return dict(_STATS)
    try:
        req = urllib.request.Request(base + "/stats",
                                     headers={"User-Agent": "LMU-TelemetryPro"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if isinstance(data, dict):
            for k in ("drivers", "refs", "submissions"):
                try:
                    _STATS[k] = int(data.get(k) or 0)
                except Exception:
                    pass
    except Exception:
        pass
    return dict(_STATS)


def stats_async(timeout=8):
    """fetch_stats() in background (non blocca la UI)."""
    if not _base():
        return
    threading.Thread(target=fetch_stats, args=(timeout,),
                     name="online-stats", daemon=True).start()


def drivers_count():
    """Numero di driver unici in classifica (valore in cache)."""
    return _STATS.get("drivers", 0)


def submissions_count():
    """Totale tempi inviati dalla community (valore in cache)."""
    return _STATS.get("submissions", 0)


def refs_count():
    """Numero di record best attivi in classifica (valore in cache)."""
    return _STATS.get("refs", 0)
