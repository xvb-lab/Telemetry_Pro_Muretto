"""telemetry/engineer_tab.py — pannello Ingegnere nella UI (SNELLO, 0.3b).

Nella 0.3b il cervello ingegnere e' un PROCESSO SEPARATO
(`engineer/run_engineer.py`): questo tab NON esegue piu' l'engine in-process,
che era la causa degli scatti (UI+recorder+engineer nello stesso processo/GIL).

Per ora e' un segnaposto con l'API minima che la UI (tab_overlay) si aspetta,
tutta no-op o su `engineer_cfg`. Le impostazioni complete (lingua, 3 voci,
volumi, ritardo tono, beep, on/off, i tre toni) + il lancio/stop del processo
muretto arrivano qui con la FUSIONE OPZIONI (FASE 4).

Il vecchio `_EngineerTab` importava `engineer_overlay` e guidava il brain a ogni
tick: rimosso di proposito.
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


class _EngineerTab(QWidget):
    """Segnaposto pannello ingegnere. API minima usata da tab_overlay/window,
    tutta difensiva → sicura anche minimale."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app = parent
        self._ov = None                      # niente overlay in-process qui
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        title = QLabel("Ingegnere / Muretto")
        title.setStyleSheet("font-size:15px; font-weight:600;")
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel("Gira come processo separato (voce).\n"
                     "Impostazioni complete in arrivo qui.")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(sub)

    # ── API minima attesa da tab_overlay (tutta difensiva) ────────────────
    def is_enabled(self):
        try:
            from core.engineer_cfg import load
            return bool(load().get("engineer_on", False))
        except Exception:
            return False

    def set_enabled(self, on):
        try:
            from core.engineer_cfg import save
            save(engineer_on=bool(on))
        except Exception:
            pass

    def is_radio_only(self):
        return True                          # il muretto e' voce-only

    def set_radio_only(self, on):
        pass

    def add_mirror(self, *a, **k):
        pass

    def remove_mirror(self, *a, **k):
        pass

    def settings_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lab = QLabel("Impostazioni ingegnere — in arrivo (FASE 4).")
        lab.setAlignment(Qt.AlignCenter)
        lay.addWidget(lab)
        return w

    def log(self, text):
        """No-op: era il log del motore in-process. Il muretto e' separato."""
        pass
