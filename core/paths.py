r"""
core/paths.py — Percorsi dei dati UTENTE (Windows), separati dall'app.

Problema risolto: prima `config.json` e `overlay_positions.json` (e i log)
stavano dentro la cartella dell'app. Aggiornando l'app si sovrascrivevano e
l'utente doveva riconfigurare tutto / rischiava di perdere i log.

Da qui in poi:
- I DEFAULT di fabbrica restano nell'app: settings/config.default.json
  (aggiornati ad ogni release).
- I DATI UTENTE vivono in:  %APPDATA%\LMU_TelemetryPro
    config.json, overlay_positions.json, logs\*.lmtel
  Gli update non toccano più questa cartella.

Al primo avvio migra automaticamente eventuali file di una vecchia
installazione (settings\config.json, settings\overlay_positions.json, logs\).
"""
import os
import shutil
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
_APP_SETTINGS = _APP_ROOT / "settings"

DEFAULT_CONFIG = _APP_SETTINGS / "config.default.json"


def _user_dir() -> Path:
    # Windows: %APPDATA%\LMU_TelemetryPro (es. C:\Users\<nome>\AppData\Roaming\...)
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    d = Path(base) / "LMU_TelemetryPro"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        d = _APP_SETTINGS  # fallback estremo: torna dentro l'app
    return d


USER_DIR = _user_dir()
CONFIG_FILE = USER_DIR / "config.json"
POSITIONS_FILE = USER_DIR / "overlay_positions.json"
PROFILE_FILE = USER_DIR / "profile.json"   # nome team/pilota (dato UTENTE)
LOGS_DIR = USER_DIR / "logs"
REFS_DIR = USER_DIR / "refs"          # reference lap per classe+pista+meteo
TEAM_DIR = USER_DIR / "team_sessions" # sessioni importate da compagni (isolate)
try:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    TEAM_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


def _migrate_first_run():
    """Primo avvio: crea la config utente dai default (o migra quella vecchia
    che stava in settings/), così non si riparte mai da zero."""
    old_cfg = _APP_SETTINGS / "config.json"
    old_pos = _APP_SETTINGS / "overlay_positions.json"
    try:
        if not CONFIG_FILE.exists():
            if old_cfg.exists():
                shutil.copyfile(old_cfg, CONFIG_FILE)        # preserva config esistente
            elif DEFAULT_CONFIG.exists():
                shutil.copyfile(DEFAULT_CONFIG, CONFIG_FILE)  # parte dai default
    except Exception:
        pass
    try:
        if not POSITIONS_FILE.exists() and old_pos.exists():
            shutil.copyfile(old_pos, POSITIONS_FILE)         # preserva posizioni esistenti
    except Exception:
        pass
    # migra i log telemetria (.lmtel) di una vecchia installazione
    try:
        old_logs = _APP_ROOT / "logs"
        if old_logs.is_dir():
            for f in old_logs.glob("*.lmtel"):
                dst = LOGS_DIR / f.name
                if not dst.exists():
                    shutil.copyfile(f, dst)
    except Exception:
        pass
    # migra i dati dell'ingegnere (profili appresi + lingua) fuori dal bundle
    try:
        old_learn = _APP_SETTINGS / "learn"
        if old_learn.is_dir():
            dst_dir = USER_DIR / "learn"
            dst_dir.mkdir(parents=True, exist_ok=True)
            for f in old_learn.glob("*.json"):
                dst = dst_dir / f.name
                if not dst.exists():
                    shutil.copyfile(f, dst)
        old_eng = _APP_SETTINGS / "engineer.json"
        new_eng = USER_DIR / "engineer.json"
        if old_eng.exists() and not new_eng.exists():
            shutil.copyfile(old_eng, new_eng)
    except Exception:
        pass
    # migra il profilo (team/pilota) fuori dal bundle; nel repo non c'e' piu'
    try:
        old_prof = _APP_SETTINGS / "profile.json"
        if old_prof.exists() and not PROFILE_FILE.exists():
            shutil.copyfile(old_prof, PROFILE_FILE)
    except Exception:
        pass


_migrate_first_run()
