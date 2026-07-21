# Piano reintegrazione UI vecchia + overlay + online (in 0.3b)

Obiettivo: riportare la **UI vecchia + overlay + online** (collaudati, nel
backup) dentro la 0.3b, **senza tradire l'architettura**: il muretto resta un
processo a sé.

## Principio FISSO
**Muretto = processo separato.** L'app UI **lancia** muretto e overlay, non li
esegue dentro. Nessun engine ingegnere né il suo driver nel processo UI: era
quello a ingolfare (stutter). Il recorder telemetria può restare nell'app (serve
alla review/live), ma senza guidare l'ingegnere.

## Cosa si PORTA (dal backup)
- **Overlay**: `widgets/` (map, standings, relative, flag, tyres, hud, tower,
  wec26mfd/board/…) + `run_overlay.py` + il registro `WIDGETS` in
  `ui/tab_overlay.py`. **Erano GIÀ processi separati** → più facili.
- **UI app**: `telemetry/window.py` (11k righe), tab in `ui/`
  (overview/community/team/circuits/settings/overlay), `gui/config_window.py`.
- **Online**: `core/online.py` (+ tab community).
- **Dati per la UI**: `telemetry/recorder.py` (col **fix `list_sessions`** cache
  mtime), `db.py`, `strategy.py`, `common.py`, `trace_view.py`. (`reader.py` e
  `shared_memory.py` già in `core/`.)

## Cosa si STACCA / NON si porta
- **Engineer in-process**: `telemetry/engineer_tab.py` (il tab che GUIDAVA il
  brain a ogni tick) e le parti in-process di `engineer_overlay.py`. Il **muretto
  separato** (`engineer/`) li sostituisce.
- **Team-radio a schermo**: overlay `wec26radio` + il display team-radio → il
  muretto è **voice-only**, niente doppione a video.
- Nel processo UI: **niente avvio dell'Engineer**; solo il **lancio** del
  processo muretto (già in `main.py::start_muretto`).

## Ordine (fasi, UNA alla volta, testate)
1. **FASE 1 — Overlay** (basso rischio, alto valore): porta `widgets/` +
   `run_overlay.py` + `ui/tab_overlay`; `main.py::start_overlays` li lancia.
   Test: un overlay (es. `map`) parte come processo separato e legge LMU.
2. **FASE 2 — Shell UI**: porta `window.py` + tab come processo APP.
   **Decoupling**: trovare dove `window.py` crea/guida engineer+recorder;
   rimuovere l'avvio dell'engineer (l'app lancia il muretto separato); tenere il
   recorder per la review col fix `list_sessions`.
3. **FASE 3 — Online**: `core/online.py` + tab community.
4. **FASE 4 — Fusione Opzioni**: le opzioni muretto attuali (`main.py`) diventano
   una pagina/tab dentro la UI; l'interruttore ingegnere ON/OFF resta e lancia il
   processo muretto. Tono-test e beep restano.
5. **FASE 5 — Pulizia + test end-to-end**: percorsi (`core.paths`, assets,
   settings) allineati; una prova completa in pista.

## Rischi / note
- `window.py` 11k righe: pezzo grosso; il decoupling dell'engineer va fatto con
  cura (potrebbe intrecciarsi col recorder e con la pagina stint live).
- Allineare import/percorsi alla struttura 0.3b (core/, settings/, assets/).
- Mantenere il **fix `list_sessions`** (cache per mtime) in `db.py`.
- Gli overlay vanno lanciati con lo stesso interprete (`pythonw`) e cwd della root.

## Scelte utente (2026-07-21)
- **Recorder nell'app: SÌ** (per review/overview/stint), ma **senza guidare
  l'engineer** (quello è il muretto separato).
- **Overlay: solo il set WEC** che l'utente usa (non tutta la cartella widgets).
  Set di partenza (quelli che girava): `map`, `wec26board`, `wec26flag`,
  `wec26mfd` (+ standings/relative se servono al timing) — da confermare dai
  `WIDGETS` di `ui/tab_overlay.py`.
