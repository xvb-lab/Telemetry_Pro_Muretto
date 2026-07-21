# -*- mode: python ; coding: utf-8 -*-
"""
TelemetryPro.spec — build onedir di LMU Telemetry Pro 0.3b (app autonoma).

Asset inclusi mantenendo la struttura cartelle, cosi' i path
Path(__file__).parent... continuano a funzionare nell'exe.
Inclusa fonts/ (con la sottocartella wec/): senza, l'exe ripiega sui font
di sistema e i titoli WEC (Druk) non si vedono.

Architettura 0.3b a processi separati: la UI (main.py) lancia muretto e
overlay via `sys.executable -m ...`. Nel frozen `sys.executable` e' l'exe:
i moduli engineer/overlays sono inclusi come hiddenimports; il rilancio dei
sottoprocessi va verificato sull'exe (se non partono, gestirli a parte).
"""
import os
from PyInstaller.utils.hooks import collect_submodules

# build_debug.bat imposta TP_DEBUG=1 -> exe CON console per vedere gli errori
_DEBUG = os.environ.get("TP_DEBUG") == "1"

block_cipher = None

datas = [
    ("fonts", "fonts"),                       # include anche fonts/wec/ (Druk)
    ("settings", "settings"),
    ("assets", "assets"),
    ("brandlogo", "brandlogo"),
    ("data", "data"),
    ("pyLMUSharedMemory", "pyLMUSharedMemory"),
]

hiddenimports = (
    collect_submodules("core")
    + collect_submodules("telemetry")
    + collect_submodules("ui")
    + collect_submodules("widgets")           # tab Overlay: window.py li carica
    + collect_submodules("gui")               # ConfigWindow dei widget
    + collect_submodules("engineer")          # muretto (sottoprocesso)
    + collect_submodules("overlays")          # overlay (sottoprocesso)
    + collect_submodules("edge_tts")          # TTS radio: import dentro funzioni
    + [
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtMultimedia",               # intro video/audio
        "certifi",                            # SSL per edge-tts
    ]
)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LMU_TelemetryPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=_DEBUG,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LMU_TelemetryPro",
)
