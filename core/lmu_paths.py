"""core/lmu_paths.py — Individua le cartelle setup di Le Mans Ultimate.

I setup (.svm) di LMU stanno in:
    <LMU install>\\UserData\\<profilo>\\Settings\\<circuito>\\*.svm

L'install viene trovato via Steam (registro + libraryfolders.vdf, AppID 2399420).
Tutto difensivo: su sistemi non Windows o se non trovato ritorna None.
"""
import os
import re

LMU_APPID = "2399420"
LMU_DIRNAME = "Le Mans Ultimate"


def _steam_path():
    """Percorso d'installazione di Steam (solo Windows)."""
    try:
        import winreg
    except Exception:
        return None
    for hive, key in ((getattr(winreg, "HKEY_CURRENT_USER"), r"Software\Valve\Steam"),
                      (getattr(winreg, "HKEY_LOCAL_MACHINE"), r"SOFTWARE\WOW6432Node\Valve\Steam")):
        try:
            k = winreg.OpenKey(hive, key)
            for name in ("SteamPath", "InstallPath"):
                try:
                    val, _ = winreg.QueryValueEx(k, name)
                    if val and os.path.isdir(val):
                        return val
                except Exception:
                    pass
        except Exception:
            pass
    return None


def _steam_libraries(steam):
    """Lista delle library Steam (compresa quella base)."""
    libs = [steam]
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        for m in re.finditer(r'"path"\s*"([^"]+)"', txt):
            p = m.group(1).replace("\\\\", "\\")
            if os.path.isdir(p):
                libs.append(p)
    except Exception:
        pass
    return libs


def lmu_install_dir():
    """Cartella d'installazione di LMU, o None."""
    steam = _steam_path()
    if not steam:
        return None
    for lib in _steam_libraries(steam):
        cand = os.path.join(lib, "steamapps", "common", LMU_DIRNAME)
        if os.path.isdir(cand):
            return cand
    return None


def lmu_settings_dir():
    """Cartella base dei Settings (contiene le sottocartelle per circuito), o None.

    Prova prima il profilo 'player', poi cerca un profilo qualunque con Settings.
    """
    inst = lmu_install_dir()
    if not inst:
        return None
    userdata = os.path.join(inst, "UserData")
    cand = os.path.join(userdata, "player", "Settings")
    if os.path.isdir(cand):
        return cand
    try:
        for prof in os.listdir(userdata):
            s = os.path.join(userdata, prof, "Settings")
            if os.path.isdir(s):
                return s
    except Exception:
        pass
    return None


def lmu_tracks(settings_dir=None):
    """Sottocartelle circuito dentro Settings: [(label, fullpath)]."""
    base = settings_dir or lmu_settings_dir()
    out = []
    if not base:
        return out
    try:
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isdir(full):
                out.append((name, full))
    except Exception:
        pass
    return out


def lmu_setups(track_dir):
    """File .svm dentro una cartella circuito: [(filename, fullpath)]."""
    out = []
    try:
        for name in sorted(os.listdir(track_dir)):
            if name.lower().endswith(".svm"):
                out.append((name, os.path.join(track_dir, name)))
    except Exception:
        pass
    return out
