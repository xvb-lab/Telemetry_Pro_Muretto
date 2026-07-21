"""core/profile.py — profilo/team salvato (condiviso)."""

from pathlib import Path
try:
    from core.paths import PROFILE_FILE as _PROFILE_FILE
except Exception:
    _PROFILE_FILE = Path(__file__).resolve().parent.parent / "settings" / "profile.json"


def _load_profile():
    try:
        import json
        return json.loads(_PROFILE_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_profile(d):
    try:
        import json
        _PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PROFILE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:
        pass


def get_team():
    """Nome team salvato nel profilo (per card e upload online). '' se assente."""
    return (_load_profile().get("team") or "").strip()
