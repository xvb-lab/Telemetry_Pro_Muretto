"""core/strategy.py — motore strategia LMU (`lmu_live`), il CUORE del muretto.

Produce il blocco `lmu_live` a **0% errore** dai dati DIRETTI di LMU:
  - pit menu (tabella %->giri della VIRTUAL ENERGY)  -> PitMenu/receivePitMenu
  - consumo MISURATO giro-per-giro                    -> /rest/strategy/usage
  - vincolo + obiettivo sosta (fuelInfo/pit menu)     -> UIScreen/RepairAndRefuel
  - fisica (VE%, fuel, race_remaining, ...)           -> core.reader

Regola SACRA: dati SOLO da LMU. Campo mancante = None, MAI inventato. Se LMU
non ha ancora giri puliti a sufficienza, `per_lap` resta None e il muretto
tace sui consumi invece di stimare.

Estratto invariato nella LOGICA dal vecchio recorder v3 (collaudato). Le fetch
REST sono sincrone ma vanno chiamate SOLO dal thread dedicato di `StrategyFeed`
(mai dal loop di campionamento): e' la regola "REST non-bloccante" della bibbia.
"""
import re
import json
import threading
import time
import urllib.request

_BASE = "http://localhost:6397"


# ─────────────────────────────────────────────────────────────────────────
#  FETCH REST (sincrone — solo da thread dedicato)
# ─────────────────────────────────────────────────────────────────────────
def _get(path, timeout):
    """GET JSON grezzo da LMU. None su qualsiasi errore (gioco chiuso, ecc.)."""
    try:
        req = urllib.request.Request(_BASE + path,
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_pit_menu(timeout=0.5):
    """PitMenu/receivePitMenu -> {nome: testo_corrente, _ve_table:[[%,giri]], _raw}.
    `_ve_table` = la tabella %->giri della VIRTUAL ENERGY: il conto DI LMU, la
    base della strategia energia."""
    d = _get("/rest/garage/PitMenu/receivePitMenu", timeout)
    if not isinstance(d, list):
        return None
    out = {}
    for it in d:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        try:
            idx = int(it.get("currentSetting") or 0)
        except (TypeError, ValueError):
            idx = 0
        ss = it.get("settings") or []
        txt = ""
        if isinstance(ss, list) and 0 <= idx < len(ss) and isinstance(ss[idx], dict):
            txt = str(ss[idx].get("text") or "")
        out[name] = txt
        if name.upper().startswith("VIRTUAL ENERGY"):
            try:
                tab = []
                for op in (ss if isinstance(ss, list) else []):
                    m = re.match(r"(\d+)%\s+(\d+)\s+laps",
                                 str((op or {}).get("text") or ""))
                    if m:
                        tab.append([int(m.group(1)), int(m.group(2))])
                if tab:
                    out["_ve_table"] = tab
            except Exception:
                pass
    if out:
        out["_raw"] = d          # lista integrale: serve all'auto-fuel (POST)
    return out or None


def fetch_strategy_usage(timeout=6.0):
    """/rest/strategy/usage -> storia GIRO PER GIRO di ogni pilota, come la
    calcola LMU. Voce player: {lap, pit, stint, ve:0..1, fuel:0..1, tyres[4]}.
    ATTENZIONE: ~2s di latenza e ~90 KB. Solo dal thread dedicato, al cambio
    giro (il dato cambia una volta per giro)."""
    d = _get("/rest/strategy/usage", timeout)
    return d if isinstance(d, dict) else None


def fetch_refuel_strategy(timeout=0.5):
    """RepairAndRefuel -> vincolo + obiettivo sosta + autonomia dal PIT MENU del
    gioco. `constraint` ENERGY/FUEL e' AFFIDABILE (presenza voce VIRTUAL ENERGY,
    vale per tutte le Hypercar WEC anche non ibride). `per_lap`/`autonomy` qui
    sono da regex sul menu = SOLO fallback/diagnosi: il per_lap buono e' quello
    MISURATO (vedi measured_per_lap). None se non disponibile."""
    data = _get("/rest/garage/UIScreen/RepairAndRefuel", timeout)
    if not isinstance(data, dict):
        return None
    try:
        fi = data.get("fuelInfo", {}) or {}
        max_b = float(fi.get("maxBattery") or 0.0)
        f_cur = fi.get("currentFuel")
        f_max = fi.get("maxFuel")
        pm = (data.get("pitMenu", {}) or {}).get("pitMenu", []) or []
        has_energy = any("ENERG" in ((it.get("name") or "").upper()) for it in pm)
        strat = {
            "constraint": "ENERGY" if (has_energy or max_b > 0) else "FUEL",
            "fuel_cur": f_cur, "fuel_max": f_max,
            "nrg_cur": fi.get("currentBattery"), "nrg_max": fi.get("maxBattery"),
            "autonomy": None, "fulltank": None, "per_lap": None,
            "pit_target": None,
        }
        for it in pm:
            nm = (it.get("name") or "").upper()
            ss = it.get("settings", []) or []
            cs = int(it.get("currentSetting", 0) or 0)
            cur_txt = ss[cs]["text"] if 0 <= cs < len(ss) else ""
            full_txt = ss[-1]["text"] if ss else ""
            is_nrg = ("ENERG" in nm)
            is_fuel = ("FUEL" in nm) or ("CARBUR" in nm) or ("BENZ" in nm)
            if (strat["constraint"] == "ENERGY" and is_nrg) or \
               (strat["constraint"] == "FUEL" and is_fuel):
                rate = _rate(cur_txt) or _rate(full_txt)
                strat["per_lap"] = rate
                strat["pit_target"] = _target(cur_txt)
                if strat["constraint"] == "FUEL":
                    strat["autonomy"] = _laps(cur_txt)
                    if rate and rate > 0 and f_max:
                        strat["fulltank"] = int(round(float(f_max) / rate))
                    else:
                        strat["fulltank"] = _laps(full_txt)
                else:
                    strat["autonomy"] = _laps(cur_txt)
                    strat["fulltank"] = _laps(full_txt) or _laps(cur_txt)
                    if strat["autonomy"] and not strat["per_lap"]:
                        strat["per_lap"] = 100.0 / strat["autonomy"]
        if not strat["per_lap"]:
            if strat["constraint"] == "FUEL" and strat["autonomy"] and strat["fuel_cur"]:
                try:
                    strat["per_lap"] = float(strat["fuel_cur"]) / strat["autonomy"]
                except Exception:
                    pass
            elif strat["constraint"] == "ENERGY" and strat["autonomy"]:
                strat["per_lap"] = 100.0 / strat["autonomy"]
        return strat
    except Exception:
        return None


# ── helper regex sul testo del pit-menu (fallback/diagnosi) ───────────────
def _laps(t):
    """"100% 63 laps" / "56%/40 laps" / "98l/56 laps" -> 63/40/56."""
    mm = re.search(r"(\d+)\s*(?:laps?|giri)", t or "", re.I)
    return int(mm.group(1)) if mm else None


def _rate(t):
    """consumo/giro: "100% 63 laps" -> 100/63; "98l/56 laps" -> 98/56."""
    mm = re.search(r"(\d+(?:\.\d+)?)\s*[l%]?\s*[/ ]+\s*(\d+)\s*(?:laps?|giri)",
                   t or "", re.I)
    if mm and int(mm.group(2)) > 0:
        return float(mm.group(1)) / int(mm.group(2))
    return None


def _target(t):
    """obiettivo sosta = primo numero della voce selezionata (LMU lo suggerisce)."""
    mm = re.match(r"\s*(\d+(?:\.\d+)?)", t or "")
    return float(mm.group(1)) if mm else None


# ─────────────────────────────────────────────────────────────────────────
#  CALCOLO PURO (deterministico, niente I/O)
# ─────────────────────────────────────────────────────────────────────────
def usage_per_lap(laps, key):
    """Consumo/giro REALE dallo storico LMU di UN pilota. key = "ve" o "fuel".

    ve/fuel arrivano quantizzati a byte (1/255). NON si usano i delta adiacenti
    (errore ~±24%): si misura sull'ARCO piu' lungo dello stint (dal giro col
    carico PIU' ALTO all'ultimo) / numero giri, cosi' la quantizzazione si
    spalma e sparisce. I giri con pit=True NON si escludono (LMU li conta).
    None se meno di 2 giri nello stint."""
    try:
        if not laps:
            return None
        cur = laps[-1].get("stint")
        st = [l for l in laps if l.get("stint") == cur and l.get(key) is not None]
        if len(st) < 2:
            return None
        st.sort(key=lambda l: int(l.get("lap") or 0))
        b = st[-1]                                   # ultimo giro dello stint
        a = max(st, key=lambda l: float(l.get(key)))  # carico piu' alto
        n = int(b.get("lap") or 0) - int(a.get("lap") or 0)
        if n <= 0:
            return None
        delta = float(a.get(key)) - float(b.get(key))
        if delta <= 0:
            return None
        return delta / n
    except Exception:
        return None


def measured_per_lap(u_ve, u_fu, constraint, fuel_max):
    """usage da' FRAZIONI 0..1; il resto del codice vuole ENERGY -> % per giro,
    FUEL -> LITRI per giro. Ritorna (per_lap_nell_unita_del_vincolo,
    consumo_fuel_litri). None dove il dato manca."""
    per_lap = None
    cons_fuel = None
    try:
        fmax = float(fuel_max or 0.0)
        if u_fu and fmax > 0:
            cons_fuel = float(u_fu) * fmax             # frazione -> litri
        if (constraint or "FUEL") == "ENERGY":
            if u_ve:
                per_lap = float(u_ve) * 100.0          # frazione -> %
        else:
            per_lap = cons_fuel                        # gia' in litri
    except Exception:
        per_lap = None
    return per_lap, cons_fuel


def build_lmu_live(d, ve_table, constraint, meas_per_lap, est_lap):
    """Assembla `lmu_live` dai dati DIRETTI di LMU. Deterministico, nessun I/O.

    d           = dict fisica (core.reader): ve_pct, fuel, fuel_max,
                  race_remaining, max_laps, laps_completed, tyre_compound4,
                  raining, wetness
    ve_table    = tabella %->giri del pit menu (fetch_pit_menu)
    constraint  = "ENERGY"/"FUEL" (fetch_refuel_strategy); None = deduci da VE
    meas_per_lap= consumo/giro MISURATO nell'unita' del vincolo (measured_per_lap)
    est_lap     = tempo giro stimato (s)

    per_lap: preferisce il MISURATO; senno' la tabella del pit menu (conto del
    gioco). Campo mancante = None. Ritorna None su errore."""
    try:
        vt = ve_table or []
        ve_now = d.get("ve_pct")
        fu_now = d.get("fuel")
        cstr = constraint or ("ENERGY" if vt else None)
        # consumo/giro: misurato da LMU, senno' la tabella del pit menu
        plap = meas_per_lap
        psrc = "measured" if plap else None
        if not plap and vt:
            top = max(vt, key=lambda r: r[0])
            if top[0] > 0 and top[1] > 0:
                plap = float(top[0]) / float(top[1])
                psrc = "menu"
        autol = None
        if plap:
            if cstr == "ENERGY" and ve_now is not None:
                autol = float(ve_now) / plap
            elif cstr == "FUEL" and fu_now is not None:
                autol = float(fu_now) / plap
        rem = float(d.get("race_remaining") or 0.0)
        est = float(est_lap or 0.0)
        need = int(rem / est) + 1 if (rem > 0 and est > 20.0) else None
        tgt = None
        if need is not None and vt:
            cov = [r for r in vt if r[1] >= need + 2]
            tgt = min(cov)[0] if cov else 100
        return {
            "constraint": cstr,
            "ve_pct": ve_now, "fuel_l": fu_now,
            "fuel_max": d.get("fuel_max"),
            "per_lap": plap, "per_lap_src": psrc,
            "autonomy_laps": round(autol, 2) if autol is not None else None,
            "race_remaining": rem or None,
            "est_lap": est or None,
            "max_laps": d.get("max_laps"),
            "laps_completed": d.get("laps_completed"),
            "laps_needed": need, "target_pct": tgt,
            "ve_table": vt or None,
            "compound4": d.get("tyre_compound4"),
            "raining": d.get("raining"),
            "wetness": d.get("wetness"),
        }
    except Exception:
        return None


_FC_SLOTS = ["START", "NODE_25", "NODE_50", "NODE_75", "FINISH"]
_FC_KEY = {1: "PRACTICE", 2: "PRACTICE", 3: "PRACTICE", 4: "QUALIFY",
           5: "QUALIFY", 6: "RACE", 7: "RACE", 8: "RACE"}


def fetch_weather5(session_type, timeout=0.6):
    """Probabilita' pioggia 0-100 ai 5 nodi (START..FINISH) dal forecast LMU
    (gia' esposto PRIMA del via). Lista di 5 float, o None se non disponibile."""
    d = _get("/rest/sessions/weather", timeout)
    if not isinstance(d, dict):
        return None
    key = _FC_KEY.get(int(session_type or 0))
    sess = (d.get(key) if key else None) or d.get("RACE") \
        or d.get("QUALIFY") or d.get("PRACTICE")
    if not isinstance(sess, dict):
        return None
    rains = []
    for slot in _FC_SLOTS:
        nd = sess.get(slot, {}) or {}
        r = (nd.get("WNV_RAIN_CHANCE", {}) or {}).get("currentValue", 0)
        try:
            rains.append(float(r))
        except (TypeError, ValueError):
            rains.append(0.0)
    if rains and max(rains) <= 1.0:          # alcune build: 0-1 invece di 0-100
        rains = [r * 100.0 for r in rains]
    return rains


def auto_fuel_target(menu_raw, laps_needed, margin=2):
    """AUTO-FUEL (collaudato 20/07): dalla tabella %->giri del pit menu di LMU
    la % di VIRTUAL ENERGY *minima* che copre `laps_needed + margin` giri.
    Ritorna (indice_opzione, pct) da scrivere, o None se non calcolabile.
    Se il pieno non basta -> (ultima_opzione, 100). Deterministico, niente I/O."""
    if not menu_raw or laps_needed is None:
        return None
    item = None
    for it in menu_raw:
        nm = str((it or {}).get("name") or "")
        if nm.startswith("VIRTUAL ENERGY"):
            item = it
            break
        if item is None and nm.startswith("FUEL") \
                and not nm.startswith("FUEL RATIO"):
            item = it        # SOLO BENZINA (P2/P3/GTE, 23/07): litri
    if item is None:
        return None
    opts = item.get("settings") or []
    best = None
    for ix, op in enumerate(opts):
        # VE: "55% 12 laps" — FUEL: "65L 23 laps" (o "giri" se IT)
        m = re.match(r"(\d+)\s*(?:%|L)\s+(\d+)\s+(?:laps|giri)",
                     str((op or {}).get("text") or ""), re.I)
        if m and int(m.group(2)) >= int(laps_needed) + margin:
            if best is None or int(m.group(1)) < best[1]:
                best = (ix, int(m.group(1)))
    if best is None:
        if not opts:
            return None
        best = (len(opts) - 1, 100)      # il pieno non basta: TUTTO
    return best


# ─────────────────────────────────────────────────────────────────────────
#  FEED — tiene i dati REST in cache (thread dedicato, non-bloccante) e
#  produce `lmu_live` su richiesta con la fisica fresca. La usa il muretto.
# ─────────────────────────────────────────────────────────────────────────
class StrategyFeed:
    def __init__(self):
        self._lock = threading.Lock()
        self._pit_menu = None        # {nome:txt, _ve_table, _raw}
        self._strat = None           # constraint/per_lap(regex)/autonomy/pit_target/fuel_max
        self._usage_ve = None        # frazione misurata
        self._usage_fu = None
        self._usage_stint = None
        self._driver = ""
        self._last_lap = -1
        self._running = False
        self._wake = threading.Event()

    # chiamato dal loop muretto a ogni tick: chi siamo + campanello al cambio giro
    def set_context(self, driver, laps_completed):
        self._driver = driver or ""
        try:
            lc = int(laps_completed or 0)
        except (TypeError, ValueError):
            return
        if lc != self._last_lap:
            self._last_lap = lc
            self._wake.set()

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False
        self._wake.set()

    def _loop(self):
        """Ogni ~3s aggiorna pit menu + vincolo (fetch veloci). Al cambio giro
        (campanello) aggiorna anche il consumo misurato (fetch lenta ~2s)."""
        while self._running:
            woke = self._wake.wait(timeout=3.0)
            self._wake.clear()
            if not self._running:
                break
            pm = fetch_pit_menu()
            rs = fetch_refuel_strategy()
            with self._lock:
                if pm is not None:
                    self._pit_menu = pm
                if rs is not None:
                    self._strat = rs
            if woke and self._driver:
                usage = fetch_strategy_usage()
                mine = (usage or {}).get(self._driver)
                if mine:
                    ve = usage_per_lap(mine, "ve")
                    fu = usage_per_lap(mine, "fuel")
                    st = mine[-1].get("stint")
                    with self._lock:
                        self._usage_ve = ve
                        self._usage_fu = fu
                        self._usage_stint = st

    def pit_menu_raw(self):
        """Lista integrale del pit menu (per la scrittura auto-fuel POST)."""
        with self._lock:
            pm = self._pit_menu or {}
        return pm.get("_raw")

    def lmu_live(self, physics, est_lap):
        """Combina la cache REST + la fisica fresca -> blocco lmu_live."""
        with self._lock:
            pm = self._pit_menu or {}
            strat = self._strat or {}
            u_ve, u_fu = self._usage_ve, self._usage_fu
        ve_table = pm.get("_ve_table")
        constraint = strat.get("constraint")
        fuel_max = strat.get("fuel_max") or (physics or {}).get("fuel_max")
        mpl, _cons_fuel = measured_per_lap(u_ve, u_fu, constraint, fuel_max)
        live = build_lmu_live(physics or {}, ve_table, constraint, mpl, est_lap)
        if live is not None:
            live["pit_target"] = strat.get("pit_target")
            # STOP/GO dal pit menu (23/07 notte): la fonte VELOCE della
            # penalita' del pilota — la stessa che usa la card
            for _k9, _v9 in pm.items():
                if str(_k9).upper().startswith("STOP"):
                    live["stop_go"] = _v9
                    break
        return live
