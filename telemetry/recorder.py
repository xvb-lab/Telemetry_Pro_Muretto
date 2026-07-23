"""
telemetry/recorder.py — Campionatore live + registrazione su file evento.

Thread dedicato (~20 Hz): legge il reader, alimenta la strategia live,
registra tracce (per la mappa/guida) e aggregati per settore/giro su un
file .lmtel SQLite (uno per evento). Mai I/O sul thread grafico: qui si
accumula e si fa flush a lotti ogni ~1.5 s.

Espone latest() per il widget piccolo strategia (strategia + stint).
"""
import threading
import time
import traceback

from .reader import TelemetryReader
from . import db as _db
from . import strategy as _strat


# ── Forecast meteo (statico): letto UNA volta a inizio sessione dal REST LMU
#    e salvato come 5 icone nei metadati. Stessa logica dell'overlay.
_FC_SLOTS = ["START", "NODE_25", "NODE_50", "NODE_75", "FINISH"]
_FC_KEY = {1: "PRACTICE", 2: "PRACTICE", 3: "PRACTICE",
           4: "QUALIFY", 5: "QUALIFY",
           6: "RACE", 7: "RACE", 8: "RACE"}


def _wx_icon(rain, sky, tod=43200):
    """rain 0-100, sky 0=sereno..4+ coperto -> nome icona meteo."""
    is_night = tod < 21600 or tod > 72000
    if rain >= 50:
        return "rain"
    if rain >= 20:
        return "rain_light"
    if sky >= 3:
        return "cloud"
    if sky >= 1:
        return "cloud_light"
    return "moon" if is_night else "sun"


def _fetch_weather5(session_type, tod=43200, timeout=0.5):
    """GET /rest/sessions/weather una volta -> dict con:
      icons: 'sun,cloud,...' per i 5 nodi
      rain:  [c0,c25,c50,c75,c100] probabilita' pioggia 0-100 ai 5 nodi
    I 5 nodi sono a 0/25/50/75/100% della durata sessione. None se non disp."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/sessions/weather"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            fc = json.loads(resp.read())
    except Exception:
        return None
    if not isinstance(fc, dict):
        return None
    key = _FC_KEY.get(int(session_type or 0))
    sess = fc.get(key) if key else None
    if not isinstance(sess, dict):
        sess = fc.get("RACE") or fc.get("PRACTICE") or fc.get("QUALIFY")
    if not isinstance(sess, dict):
        return None
    icons, rains = [], []
    for slot in _FC_SLOTS:
        nd = sess.get(slot, {}) or {}
        rain = (nd.get("WNV_RAIN_CHANCE", {}) or {}).get("currentValue", 0)
        sky = (nd.get("WNV_SKY", {}) or {}).get("currentValue", 0)
        try:
            rains.append(float(rain))
            icons.append(_wx_icon(float(rain), float(sky), tod))
        except Exception:
            rains.append(0.0)
            icons.append("sun")
    # SCALA: alcune build rispondono 0-1 invece di 0-100. Con la frazione
    # nessuna soglia (30/40/50) scatta mai: pioggia invisibile al muretto.
    if rains and 0.0 < max(rains) <= 1.5:
        rains = [r * 100.0 for r in rains]
    return {"icons": ",".join(icons), "rain": rains}


def _fetch_tyre_inventory(timeout=0.4):
    """Dotazione gomme dal REST (localhost:6397). Ritorna dict:
      max_tires:  treni slick totali per l'evento
      new_tires:  treni nuovi ancora disponibili
      slick_new/slick_used: conteggio treni slick per stato
      options:    per-treno [{compound, is_used, wear}] (slick + wet)
    None se non disponibile (offline/menu). Le wet sono illimitate."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/garage/UIScreen/TireManagement"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    inv = d.get("tireInventory") or {}
    go = d.get("tireInvGarageOptions") or {}
    out = {"max_tires": inv.get("maxAvailableTires"),
           "new_tires": inv.get("newTires"),
           "new_remaining": go.get("newTiresRemaining")}
    opts = []
    for axle in (go.get("tireOptions") or []):
        if isinstance(axle, list):
            for t in axle:
                if isinstance(t, dict):
                    opts.append({"compound": t.get("compoundIndex"),
                                 "is_used": bool(t.get("isUsed")),
                                 "wear": t.get("wearValue"),
                                 "type": t.get("type")})
    out["options"] = opts
    # conteggio SLICK disponibili (compound 0), separati nuovi/usati.
    # tireOptions e' per-asse e ripete lo stesso set: prendo il primo asse.
    slick_new = slick_used = 0
    first_axle = (go.get("tireOptions") or [[]])[0]
    for t in first_axle:
        if isinstance(t, dict) and t.get("compoundIndex") == 0:
            if t.get("isUsed"):
                slick_used += 1
            else:
                slick_new += 1
    out["slick_new"] = slick_new
    out["slick_used"] = slick_used
    # MESCOLE disponibili con consumo/giro e temp ottimale (per il consiglio
    # gomma: GTE ha S/M/H/W, Hypercar M/H/W). compoundIndex 0=slick 1=wet,
    # ma i tipi veri (Soft/Medium/Hard/Wet) stanno in expectedUsage.
    comp_wear = {}
    for cw in ((d.get("expectedUsage") or {}).get("compoundsWearPerLap") or []):
        if isinstance(cw, dict) and cw.get("type"):
            comp_wear[cw["type"]] = cw.get("wearPerLap")
    comp_temp = {}
    for oc in ((d.get("optimalCompoundConditions") or {}).get("compounds") or []):
        if isinstance(oc, dict) and oc.get("type"):
            comp_temp[oc["type"]] = oc.get("optimalTemperature")
    out["compounds"] = [{"type": k, "wear_per_lap": v,
                         "optimal_temp": comp_temp.get(k)}
                        for k, v in comp_wear.items()]
    # temperatura pista attuale (per confronto con l'ottimale)
    out["track_temp_k"] = ((d.get("currentWeather") or {})
                           .get("trackTempKelvin"))
    return out


def _fetch_lap_history(timeout=0.7):
    """GET /rest/watch/standings/history -> PASSO VERO per pilota:
    mediana degli ultimi 3 giri validi (tempo>20s, non in pit).
    {driverName: secs}. E' la base MISURATA per undercut/overcut."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/watch/standings/history"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    out = {}
    for _slot, laps in d.items():
        if not isinstance(laps, list) or not laps:
            continue
        name = None
        times = []
        for e in laps:
            if not isinstance(e, dict):
                continue
            name = e.get("driverName") or name
            try:
                t = float(e.get("lapTime"))
            except (TypeError, ValueError):
                continue
            if t > 20.0 and not e.get("pitting"):
                times.append(t)
        if name and times:
            last = sorted(times[-3:])
            out[str(name).strip()] = last[len(last) // 2]
    return out or None


def _fetch_pit_menu(timeout=0.5):
    """GET /rest/garage/PitMenu/receivePitMenu -> il pit menu VOCE PER VOCE
    {nome: testo_impostazione_corrente} — accesso strutturato, niente
    scraping dello schermo garage."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/garage/PitMenu/receivePitMenu"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
    except Exception:
        return None
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
        # TABELLA %->giri DEL GIOCO dalle opzioni VIRTUAL ENERGY
        # ("77% 33 laps"...): e' il conto di LMU, la strategia usa QUELLA
        if name.upper().startswith("VIRTUAL ENERGY"):
            try:
                import re as _re0
                tab = []
                for op in (ss if isinstance(ss, list) else []):
                    m = _re0.match(r"(\d+)%\s+(\d+)\s+laps",
                                   str((op or {}).get("text") or ""))
                    if m:
                        tab.append([int(m.group(1)), int(m.group(2))])
                if tab:
                    out["_ve_table"] = tab
            except Exception:
                pass
    if out:
        out["_raw"] = d      # lista integrale: serve all'AUTO FUEL per
    return out or None       # scrivere (POST rivuole il menu completo)


def _fetch_weather_next(timeout=0.5):
    """GET GetGameState -> closeestWeatherNode: il PROSSIMO nodo meteo in
    arrivo (chance pioggia, cielo, inizio, durata, temperatura)."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/sessions/GetGameState"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
    except Exception:
        return None
    n = (d or {}).get("closeestWeatherNode")
    if not isinstance(n, dict):
        return None
    return {"rain": n.get("RainChance"), "sky": n.get("Sky"),
            "start": n.get("StartTime"), "duration": n.get("Duration"),
            "temp": n.get("Temperature")}


def _fetch_session_rules(timeout=0.5):
    """GET /rest/sessions -> REGOLE della sessione (dato CERTO, non dedotto):
    giri gara impostati, moltiplicatori consumo/usura, bandiere blu, regole
    taglio, moltiplicatore danni. Ogni voce SESSSET_* ha currentValue +
    stringValue. None se REST non disponibile."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/sessions"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
    except Exception:
        return None
    if not isinstance(d, dict):
        return None

    def _v(key):
        it = d.get(key) or {}
        return (it.get("currentValue"), str(it.get("stringValue") or ""))
    out = {}
    _rl, _rls = _v("SESSSET_Race_Laps")
    try:
        _rl = int(float(_rl or 0))
    except (TypeError, ValueError):
        _rl = 0
    out["race_laps_set"] = _rl if _rl > 0 else None      # N/A = gara a tempo
    out["fuel_usage"] = _v("SESSSET_Fuel_Usage")[1]      # es. "Realistic"/"2x"
    out["tire_wear"] = _v("SESSSET_Tire_Wear")[1]
    out["blue_flags"] = _v("SESSSET_blue_flags")[1]
    out["cut_rules"] = _v("SESSSET_cut_rules")[1]
    out["damage_multi"] = _v("SESSSET_Damage_Multi")[1]
    return out


def _fetch_forecast5(session_type, tod=43200, timeout=0.5):
    """Compatibilita': solo la stringa icone."""
    w = _fetch_weather5(session_type, tod, timeout)
    return w["icons"] if w else None


def _fetch_est_lap(timeout=0.5):
    """Compat: solo il tempo giro stimato (player). Vedi _fetch_player."""
    p = _fetch_player(timeout)
    return p.get("est_lap") if p else None


def _fetch_player(timeout=0.5):
    """Dallo standings LMU prende i dati della TUA auto (player=true):
      est_lap   tempo giro stimato (affidabile anche al via)
      penalties penalita' da scontare (>0)
    None se non disponibile."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/watch/standings"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        entries = data if isinstance(data, list) else (
            data.get("vehicles") or data.get("standings") or [])
        first_el = None
        for e in entries:
            if not isinstance(e, dict):
                continue
            el = float(e.get("estimatedLapTime") or 0.0)
            ok = 20.0 < el < 1200.0
            if e.get("player"):
                return {"est_lap": el if ok else first_el,
                        "penalties": int(e.get("penalties") or 0)}
            if ok and first_el is None:
                first_el = el
        return {"est_lap": first_el, "penalties": 0}
    except Exception:
        return None


def _fetch_pit_est(timeout=0.5):
    """GET /rest/strategy/pitstop-estimate -> secondi di sosta stimati DAL
    GIOCO per la prossima fermata col pit-menu attuale: benzina, energia (ve),
    gomme, driverSwap, penalita', damage, total. None se non disponibile."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/strategy/pitstop-estimate"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _fetch_pit_entry(timeout=0.5):
    """GET /rest/sessions/GetGameState -> PitEntryDist (metri di lapdist
    dell'INGRESSO corsia box). Verificato su dato reale: e' l'entrata vera,
    non la piazzola (mPitLapDist della shared memory e' vicino al traguardo).
    None se non disponibile."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/sessions/GetGameState"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        v = float(data.get("PitEntryDist") or 0.0)
        return v if v > 0 else None
    except Exception:
        return None


def _fetch_strategy_usage(timeout=6.0):
    """GET /rest/strategy/usage -> storia GIRO PER GIRO di ogni pilota, come
    la calcola LMU stesso. Per il PLAYER ogni voce ha:
        {"lap":n, "pit":bool, "stint":n, "ve":0..1, "fuel":0..1,
         "tyres":[fl,fr,rl,rr]}
    E' la VERITA' del gioco: niente regex sul pit-menu, niente delta grezzi.

    ATTENZIONE: ~2 secondi di latenza e ~90 KB (costruisce tutti i piloti).
    NON chiamarla dal loop del recorder (campiona a 64Hz) ne' dalla GUI:
    va solo dal thread dedicato _strategy_loop, che ne mette il frutto in
    cache. Il dato cambia una volta per giro, quindi non serve di piu'.
    """
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/strategy/usage"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _usage_per_lap(laps, key):
    """Consumo per giro REALE dallo storico LMU di UN pilota.

    laps: lista di voci /rest/strategy/usage; key: "ve" oppure "fuel".

    ATTENZIONE — QUANTIZZAZIONE: ve/fuel arrivano come BYTE, cioe' multipli di
    1/255 (~0.39%). Il delta fra due giri CONSECUTIVI vale quindi 4/255 (1.57%)
    o 5/255 (1.96%) a seconda dell'arrotondamento: su un consumo reale di
    ~1.64%/giro sono ±24% di errore, e la stima giri ballava 59 <-> 47.
    Percio' NON si usano i delta adiacenti: si misura sull'ARCO PIU' LUNGO
    possibile dello stint e si divide per il numero di giri percorsi. Cosi'
    l'errore di quantizzazione si spalma su N giri (0.39%/N) e sparisce.

    ARCO = dal giro col carico PIU' ALTO dello stint fino all'ULTIMO giro.
    Dentro uno stint il carico scende sempre, quindi il massimo e' il primo
    giro utile e il conto e' semplicemente (carico_iniziale - carico_ora) / giri.
    Partire dal massimo, e non dal primo giro in assoluto, rende il conto
    immune al giro di rifornimento in testa allo stint (li' il carico RISALE).

    ATTENZIONE — i giri con pit=True NON si escludono: consumano come gli altri
    e LMU li conta. Verificato sul dato vero: al via il giro 1 ha pit=True (si
    lascia la griglia). Scartandolo l'arco si spezzava e restavano 2 giri soli,
    dove la quantizzazione gonfia la stima del ~7% (misurato: 1.76%/giro contro
    l'1.65% di LMU -> 52 giri invece di 56). Includendolo si ottiene 1.6471%,
    cioe' il "Consumo stimato" del pannello di LMU.
    Ritorna None se non ci sono almeno 2 giri nello stint.
    """
    try:
        if not laps:
            return None
        _cur = laps[-1].get("stint")
        _st = [l for l in laps if l.get("stint") == _cur
               and l.get(key) is not None]
        if len(_st) < 2:
            return None
        _st.sort(key=lambda l: int(l.get("lap") or 0))
        _b = _st[-1]                                  # ultimo giro dello stint
        _a = max(_st, key=lambda l: float(l.get(key)))  # carico piu' alto
        _n = int(_b.get("lap") or 0) - int(_a.get("lap") or 0)
        if _n <= 0:
            return None
        _delta = float(_a.get(key)) - float(_b.get(key))
        if _delta <= 0:
            return None
        return _delta / _n
    except Exception:
        return None


def _fetch_wearables(timeout=0.5):
    """GET /rest/garage/UIScreen/RepairAndRefuel -> {'susp':[4], 'aero':float}.
    susp/aero = frazione di DANNO (0 = integro). None se non disponibile."""
    try:
        import json
        import urllib.request
        url = "http://localhost:6397/rest/garage/UIScreen/RepairAndRefuel"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        w = data.get("wearables", {}) or {}
        out = {}
        su = w.get("suspension", [])
        if isinstance(su, list) and len(su) >= 4:
            out["susp"] = [float(x) for x in su[:4]]
        body = w.get("body", {}) or {}
        if isinstance(body, dict) and "aero" in body:
            out["aero"] = float(body.get("aero", 0.0))
        # ── STRATEGIA LMU (numeri del HUD): benzina/energia -> autonomia giri ──
        import re as _re
        def _laps(t):
            # giri per stint dalla voce pit-menu: "100% 63 laps", "56%/40 laps",
            # "98l/56 laps" -> 63/40/56. Accetta 'laps' o 'giri'.
            mm = _re.search(r"(\d+)\s*(?:laps?|giri)", t or "", _re.I)
            return int(mm.group(1)) if mm else None
        def _rate(t):
            # consumo per giro: "100% 63 laps" -> 100/63 ; "56%/40 laps" -> 56/40 ;
            # "98l/56 laps" -> 98/56. Separatore = slash O spazio.
            mm = _re.search(r"(\d+(?:\.\d+)?)\s*[l%]?\s*[/ ]+\s*(\d+)\s*(?:laps?|giri)",
                            t or "", _re.I)
            if mm and int(mm.group(2)) > 0:
                return float(mm.group(1)) / int(mm.group(2))
            return None
        def _target(t):
            # QUANTO LMU SUGGERISCE DI METTERE alla sosta: e' il primo numero
            # della voce pit-menu selezionata ("100% 60 laps" -> 100 ;
            # "98l/56 laps" -> 98). E' l'OBIETTIVO (riempi fino a...), non un
            # rabbocco: e' lo stesso valore del "100% VE necessaria" che LMU
            # scrive nel pannello Strategia. Lo suggerisce il gioco, quindi si
            # legge e basta invece di ricalcolarlo.
            mm = _re.match(r"\s*(\d+(?:\.\d+)?)", t or "")
            return float(mm.group(1)) if mm else None
        fi = data.get("fuelInfo", {}) or {}
        max_b = float(fi.get("maxBattery") or 0.0)
        f_cur = fi.get("currentFuel")
        f_max = fi.get("maxFuel")
        pm = (data.get("pitMenu", {}) or {}).get("pitMenu", []) or []
        # VINCOLO dal PIT-MENU: se c'e' la voce VIRTUAL ENERGY la gara e' limitata
        # dall'ENERGIA — vale per TUTTE le Hypercar WEC, anche quelle NON ibride
        # (es. Aston Martin Valkyrie: niente batteria). La batteria ibrida resta
        # solo come fallback. Cosi' non serve indovinare dal maxBattery.
        _has_energy = any("ENERG" in ((it.get("name") or "").upper()) for it in pm)
        strat = {
            "constraint": "ENERGY" if (_has_energy or max_b > 0) else "FUEL",
            "fuel_cur": f_cur, "fuel_max": f_max,
            "nrg_cur": fi.get("currentBattery"), "nrg_max": fi.get("maxBattery"),
            "autonomy": None, "fulltank": None, "per_lap": None,
            # obiettivo suggerito da LMU per la prossima sosta (% se ENERGY,
            # litri se FUEL): quanto mettere, secondo il gioco.
            "pit_target": None,
        }
        for it in pm:
            nm = (it.get("name") or "").upper()
            ss = it.get("settings", []) or []
            cs = int(it.get("currentSetting", 0) or 0)
            cur_txt = ss[cs]["text"] if 0 <= cs < len(ss) else ""
            full_txt = ss[-1]["text"] if ss else ""
            is_nrg = ("ENERG" in nm)                 # ENERGY / ENERGIA
            is_fuel = ("FUEL" in nm) or ("CARBUR" in nm) or ("BENZ" in nm)
            if (strat["constraint"] == "ENERGY" and is_nrg) or \
               (strat["constraint"] == "FUEL" and is_fuel):
                # rate (per giro) dalla voce selezionata: dato più affidabile
                rate = _rate(cur_txt) or _rate(full_txt)
                strat["per_lap"] = rate
                strat["pit_target"] = _target(cur_txt)
                if strat["constraint"] == "FUEL":
                    # STINT = giri col carburante CARICATO (= "Carburante iniziale
                    # (X laps)" del HUD), cioè i giri della voce selezionata.
                    strat["autonomy"] = _laps(cur_txt)
                    # pieno vero (solo riferimento, non è lo stint pianificato)
                    if rate and rate > 0 and f_max:
                        strat["fulltank"] = int(round(float(f_max) / rate))
                    else:
                        strat["fulltank"] = _laps(full_txt)
                else:
                    # ENERGIA: stint = giri col carico selezionato
                    strat["autonomy"] = _laps(cur_txt)
                    strat["fulltank"] = _laps(full_txt) or _laps(cur_txt)
                    if strat["autonomy"] and not strat["per_lap"]:
                        strat["per_lap"] = 100.0 / strat["autonomy"]
        # consumo per giro: fallback solo se il rate non è stato letto
        if not strat["per_lap"]:
            if strat["constraint"] == "FUEL" and strat["autonomy"] and strat["fuel_cur"]:
                try:
                    strat["per_lap"] = float(strat["fuel_cur"]) / strat["autonomy"]
                except Exception:
                    pass
            elif strat["constraint"] == "ENERGY" and strat["autonomy"]:
                try:
                    strat["per_lap"] = 100.0 / strat["autonomy"]
                except Exception:
                    pass
        out["lmu_strat"] = strat
        # DIAGNOSTICO: se non ricavo per_lap, stampo i nomi delle voci del pit menu
        # (una volta), per vedere come si chiamano davvero su questa auto/lingua.
        if not strat.get("per_lap"):
            global _PM_DUMPED
            if not globals().get("_PM_DUMPED"):
                _PM_DUMPED = True
                names = [(it.get("name"),
                          (it.get("settings", [{}]) or [{}])[
                              int(it.get("currentSetting", 0) or 0)
                          ].get("text") if it.get("settings") else "")
                         for it in pm]
                _diag("PITMENU constraint=%s voci=%r" % (strat.get("constraint"), names))
        return out or None
    except Exception:
        return None


def _diag(msg):
    """Scrive una riga di diagnostica in logs/recorder.log (per capire perché
    non registra). Non lancia mai."""
    try:
        _db.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_db.LOGS_DIR / "recorder.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:
        pass


class TelemetryRecorder:
    # 100 Hz = rate reale della shared memory LMU in guida (sonda 23/07,
    # doc ingegneria_telemetria §14.1): a 64 se ne perdeva ~1/3
    def __init__(self, sample_hz=100, margin_laps=2.0, window=3, record=True):
        self._reader = TelemetryReader()
        from core.shared_memory import SharedMemory
        self._mem = SharedMemory.instance()
        self._tracker = _strat.StintTracker(window=window)
        self._margin = margin_laps
        self._record = record
        self._dt = 1.0 / max(5, sample_hz)
        self._dt_game = 1.0 / 10        # gioco aperto, non in registrazione
        self._dt_idle = 0.25           # gioco chiuso / fuori sessione
        self._has_data = False

        self._lock = threading.Lock()
        self._latest = {"strat": {}, "stint": {}, "raw": {}}

        # ── STRATEGIA LMU (/rest/strategy/usage) su thread DEDICATO ──
        # La chiamata costa ~2s: non puo' stare nel loop del recorder (perde
        # campioni) ne' sotto _lock (bloccherebbe la GUI, il bug degli scatti).
        # Qui il thread lavora da solo e pubblica in _usage_lock; il tick legge
        # solo l'ultimo risultato pronto.
        self._usage_lock = threading.Lock()
        self._usage_pl = {}        # {"ve": float|None, "fuel": float|None}
        self._usage_stint = None   # stint corrente secondo LMU
        self._usage_wake = threading.Event()
        self._usage_lap = -1       # giro per cui abbiamo gia' scaricato

        self._db = None
        self._evt_track = None
        self._evt_session = None
        self._evt_car = None
        self._was_active = False
        self._file_stint = 1       # stint corrente nel file (1 = primo)
        self._stint_lap_count = 0  # giri validi/registrati nello stint corrente (per il banner)
        self._stint_started = False
        self._garage_seen = False
        self._strat_last = None    # ultima strategia pit-menu valida (per_lap/autonomia)
        self._last_num_pit = None  # rileva il pit (num_pit che sale) = fine stint

        # stato giro/settore
        self._prev_sector = None
        self._prev_laps = None
        self._cur_lap_id = None
        self._lap_start_fuel = None
        self._lap_start_ve = None
        self._sec_start_fuel = None
        self._sec_start_ve = None
        self._sec_start_wear = [None] * 4
        self._sec_t_sum = [0.0] * 4
        self._sec_ts_sum = [0.0] * 4
        self._sec_ti_sum = [0.0] * 4
        self._sec_p_sum = [0.0] * 4
        self._sec_b_sum = [0.0] * 4
        self._sec_regen_sum = 0.0
        self._sec_spd_sum = 0.0
        self._sec_spd_max = 0.0
        self._sec_n = 0
        # energia elettrica (integrali kWh, firmati per recupero/deploy)
        self._prev_et = None
        self._prev_soc = None
        self._sec_regen_pos = 0.0    # recuperata (regen_kw>0) nel settore
        self._sec_boost = 0.0        # spesa/deploy (regen_kw<0) nel settore
        self._sec_soc_start = None
        self._lap_regen_pos = 0.0
        self._lap_boost = 0.0
        self._lap_soc_start = None
        self._last_flush = 0.0

        self._running = False
        self._armed = False        # registrazione: parte da sola (auto-start in pista)
        self._autostart = True     # AUTOMATICO: l'app arma/chiude da sola, zero bottoni
        self._auto_paused = False  # STOP manuale (se usato): sospende l'auto fino a uscita pista
        self._ever_active = False   # True dopo la prima volta in pista (per il no-data)
        self._wait_green = False    # in gara: armato ma in attesa del verde
        self._writing = False      # True solo quando registra davvero (in pista)
        self._arm_sig = None       # (track, session_type) di quando si è armato
        self._nodata_t0 = None     # da quando manca il dato (uscita sessione)
        self._offtrack_t0 = None   # da quando sei uscito dalla pista (menu/fine)
        self._garage_excursion = False  # in garage/menu setup della STESSA sessione
        self.start()

    # ── controllo manuale (AVVIA / STOP) ───────────────────────────────
    def arm(self):
        """AVVIA: abilita la registrazione (nuovo file alla prima attività)."""
        self._reset_session_state()
        self._arm_sig = None
        self._nodata_t0 = None
        self._armed = True
        _diag("START (manual recording)")

    def disarm(self):
        """STOP manuale: ferma e chiude il file (liberandolo)."""
        self._auto_paused = True          # non ri-armare finché non esci dalla pista
        self._auto_disarm("STOP (manual)")

    def is_armed(self):
        return self._armed

    def is_recording(self):
        """True solo se armato E sta scrivendo (auto in pista)."""
        return self._armed and self._writing

    def current_file(self):
        """Path del file .lmtel attualmente in scrittura (None se nessuno)."""
        db = self._db
        try:
            return str(db.path) if db is not None else None
        except Exception:
            return None

    def current_track(self):
        """Pista della sessione in registrazione (la sa sempre, anche prima che
        i metadati su disco siano leggibili da list_sessions)."""
        return getattr(self, "_evt_track", None)

    def banner(self):
        """Stato per il banner UI: (kind, testo inglese).
        kind in: idle | wait | rec."""
        if not self._armed:
            return ("idle", "Press START to begin telemetry analysis")
        if self._writing:
            return ("rec", "Recording \u2014 " + (self._evt_track or "track"))
        st = getattr(self, "_status", "") or ""
        if getattr(self, "_wait_green", False):
            return ("wait", "Armed \u00b7 waiting for green light\u2026")
        if st.startswith("garage"):
            nxt = self._file_stint + (1 if self._stint_lap_count >= 1 else 0)
            return ("wait", "Garage \u00b7 waiting for stint %d" % nxt)
        if st.startswith("no_data"):
            return ("wait", "Waiting for the game\u2026")
        if st.startswith("GAME DATA FROZEN"):
            return ("wait", "Game data FROZEN \u2014 restart the LMU session")
        return ("wait", "Waiting for session\u2026")

    def _auto_disarm(self, reason):
        self._armed = False
        self._writing = False
        self._arm_sig = None
        self._nodata_t0 = None
        self._offtrack_t0 = None
        if self._db is not None:
            _old = getattr(self._db, "path", None)
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None
            self._discard_if_empty(_old)
        self._reset_session_state()
        _diag("stop: " + reason)

    def _reset_session_state(self):
        self._pit_entry = None     # PitEntryDist: si ricattura sulla nuova pista
        self._pit_entry_ts = 0.0
        self._evt_track = None
        self._evt_session = None
        self._evt_car = None
        self._was_active = False
        self._ever_active = False
        self._file_stint = 1
        self._stint_lap_count = 0
        self._stint_started = False
        self._garage_seen = False
        self._garage_excursion = False
        self._strat_last = None    # nuova sessione: dimentica la strategia vecchia
        self._last_num_pit = None
        self._prev_sector = None

    def _discard_if_empty(self, path):
        """Cancella un file sessione VUOTO (0 giri e 0 campioni = entrato in
        garage e uscito senza mai guidare). Sessioni con giri/telemetria si
        tengono sempre."""
        if not path:
            return
        try:
            import sqlite3
            from pathlib import Path as _P
            con = sqlite3.connect(str(path))
            try:
                nl = con.execute("SELECT COUNT(*) FROM laps").fetchone()[0]
                ns = con.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            finally:
                con.close()
            if (nl or 0) == 0 and (ns or 0) == 0:
                _P(str(path)).unlink()
                _diag("scartata sessione vuota: %s" % path)
        except Exception:
            pass

    # ── ciclo ──────────────────────────────────────────────────────────
    def _strategy_loop(self):
        """Thread dedicato: scarica /rest/strategy/usage e ne ricava il consumo
        per giro MISURATO DA LMU. Si sveglia al cambio giro (il dato cambia una
        volta per giro), non a timer: cosi' la chiamata da 2s pesa una volta
        ogni ~60-100 secondi e non tocca nessun altro thread."""
        while self._running:
            # aspetta il campanello del tick (cambio giro); il timeout e' solo
            # una rete di sicurezza se i giri non arrivano.
            self._usage_wake.wait(timeout=30.0)
            self._usage_wake.clear()
            if not self._running:
                break
            try:
                _me = (self._latest.get("raw") or {}).get("driver") or ""
                if not _me:
                    continue
                _all = _fetch_strategy_usage()
                if not _all:
                    continue
                _mine = _all.get(_me)
                if not _mine:
                    continue
                _ve = _usage_per_lap(_mine, "ve")
                _fu = _usage_per_lap(_mine, "fuel")
                _st = _mine[-1].get("stint") if _mine else None
                with self._usage_lock:
                    self._usage_pl = {"ve": _ve, "fuel": _fu}
                    self._usage_stint = _st
            except Exception:
                pass

    def _rest_loop(self):
        """Thread CORSIA LENTA: TUTTE le urlopen al WebUI di LMU vivono qui.
        Prima stavano nel tick e ogni timeout (0.4-1.5s) FERMAVA il
        campionamento: misurati buchi fino a 3.8s nei samples (le traiettorie
        a corde sulla mappa). Il tick ora legge solo attributi-cache;
        l'assegnazione e' atomica (GIL), niente lock necessari."""
        while self._running:
            _t0 = time.monotonic()
            if getattr(self, "_has_data", False):
                now = _t0
                try:      # wearables sospensione/aero (2s)
                    if now - getattr(self, "_wear_ts", 0.0) >= 2.0:
                        self._wear_cache = _fetch_wearables()
                        self._wear_ts = now
                except Exception:
                    pass
                try:      # est_lap + penalita' dallo standings (2s)
                    if now - getattr(self, "_estlap_ts", 0.0) >= 2.0:
                        self._player_cache = _fetch_player()
                        self._estlap_ts = now
                except Exception:
                    pass
                try:      # stima sosta del gioco (3s)
                    if now - getattr(self, "_pit_est_ts", 0.0) >= 3.0:
                        self._pit_est_ts = now
                        self._pit_est = _fetch_pit_est()
                except Exception:
                    pass
                try:      # pit menu strutturato (3s)
                    if now - getattr(self, "_pmenu_ts", 0.0) >= 3.0:
                        self._pmenu_cache = _fetch_pit_menu()
                        self._pmenu_ts = now
                except Exception:
                    pass
                try:      # storico passi rivali (10s)
                    if now - getattr(self, "_pace_ts", 0.0) >= 10.0:
                        self._pace_cache = _fetch_lap_history()
                        self._pace_ts = now
                except Exception:
                    pass
                try:      # prossimo nodo meteo (30s)
                    if now - getattr(self, "_wxn_ts", 0.0) >= 30.0:
                        self._wxn_cache = _fetch_weather_next()
                        self._wxn_ts = now
                except Exception:
                    pass
                try:      # forecast pioggia 5 nodi (30s; input dal tick)
                    _styp = getattr(self, "_rest_styp", None)
                    if (_styp is not None
                            and now - getattr(self, "_fcr_ts", 0.0) >= 30.0):
                        self._fcr_cache = _fetch_weather5(
                            _styp, getattr(self, "_rest_tod", None) or 43200)
                        self._fcr_ts = now
                except Exception:
                    pass
                try:      # dotazione gomme (30s; primo fetch generoso)
                    if now - getattr(self, "_tinv_ts", 0.0) >= 30.0:
                        _first = not hasattr(self, "_tinv_seen")
                        self._tinv_cache = _fetch_tyre_inventory(
                            timeout=1.5 if _first else 0.4)
                        self._tinv_ts = now
                        if self._tinv_cache and self._tinv_cache.get("max_tires"):
                            self._tinv_seen = True
                except Exception:
                    pass
                try:      # regole sessione (60s)
                    if now - getattr(self, "_rules_ts", 0.0) >= 60.0:
                        self._rules_cache = _fetch_session_rules()
                        self._rules_ts = now
                except Exception:
                    pass
                try:      # PitEntryDist (una volta; ritenta ogni 30s)
                    if getattr(self, "_pit_entry", None) is None:
                        if now - getattr(self, "_pit_entry_ts", 0.0) >= 30.0:
                            self._pit_entry_ts = now
                            self._pit_entry = _fetch_pit_entry()
                except Exception:
                    pass
            _sl = 0.7 - (time.monotonic() - _t0)
            if _sl > 0:
                time.sleep(_sl)

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        # thread separato per la strategia LMU: la sua chiamata da ~2s non
        # deve mai rallentare il campionamento telemetria qui sopra.
        threading.Thread(target=self._strategy_loop, daemon=True).start()
        # corsia lenta REST: meteo/regole/pit menu/stime — mai nel tick
        threading.Thread(target=self._rest_loop, daemon=True).start()
        _diag("recorder avviato (record=%s)" % self._record)

    def stop(self):
        self._running = False
        self._usage_wake.set()      # sblocca subito il thread strategia
        if self._db:
            _old = getattr(self._db, "path", None)
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None
            self._discard_if_empty(_old)

    def _loop(self):
        self._last_err = None
        while self._running:
            t0 = time.monotonic()
            try:
                self._tick()
            except Exception:
                tb = traceback.format_exc()
                if tb != self._last_err:      # evita spam: logga solo errori nuovi
                    self._last_err = tb
                    _diag("ERRORE _tick:\n" + tb)
            # frequenza adattiva: piena solo durante la registrazione in pista;
            # altrimenti rallenta per non rubare CPU/GIL alla UI (app fluida)
            if getattr(self, "_writing", False):
                target = self._dt
            elif self._has_data:
                target = self._dt_game
            else:
                target = self._dt_idle
            dt = target - (time.monotonic() - t0)
            if dt > 0:
                time.sleep(dt)

    # ── un campione ────────────────────────────────────────────────────
    def _st(self, s):
        if getattr(self, "_status", None) != s:
            self._status = s
            _diag("stato: " + s)

    def _tick(self):
        d = self._reader.read()
        self._has_data = bool(d)
        if not d:
            # nessun dato = gioco fuori sessione. Disarma SOLO se avevi già
            # iniziato a girare (sessione finita). Se sei armato in attesa del
            # via (prep/allineamento), resta armato: niente disarm.
            if self._armed and self._ever_active:
                now = time.monotonic()
                if self._nodata_t0 is None:
                    self._nodata_t0 = now
                elif now - self._nodata_t0 > 2.0:
                    self._auto_disarm("session ended / left the session")
            else:
                self._nodata_t0 = None
            self._st("no_data (gioco/shared memory non leggibile)")
            return
        self._nodata_t0 = None

        # auto-chiusura intelligente: mInRealtime cade in garage, menu setup E menu
        # principale, quindi da solo non basta. Discrimino col TEMPO di sessione
        # (mCurrentET): avanza finché la sessione è viva (anche in garage/setup),
        # si ferma ai menu / a fine sessione. Quindi chiudo in fretta SOLO quando
        # il tempo è fermo. Garage e cambio gomme nel setup restano protetti.
        # GUARDIA: sganciamo anche PRIMA del primo stint (bug: armato in garage
        # "waiting for stint 1", torni al menu e la pill restava incollata perche'
        # _ever_active era ancora False). Protetto l'online: in attesa del verde
        # _wait_green=True -> non sgancia; garage vivo -> ET avanza (et_running).
        if self._armed and not self._wait_green:
            now = time.monotonic()
            try:
                rt = self._mem.in_realtime()
            except Exception:
                rt = None
            if rt is False:
                try:
                    et = self._mem.session_et()
                except Exception:
                    et = None
                et_running = (et is not None and et != getattr(self, "_last_et_close", None))
                self._last_et_close = et
                if et_running:
                    self._offtrack_t0 = None       # sessione viva (garage/setup): non chiudere
                elif self._offtrack_t0 is None:
                    self._offtrack_t0 = now
                elif now - self._offtrack_t0 > 5.0:
                    self._auto_disarm("session ended / back to menu")
                    return
            else:
                self._offtrack_t0 = None
                self._last_et_close = None

        # strategia live (sempre, anche senza registrazione)
        self._tracker.update(d)
        measured = self._tracker.measured(d)
        # dati extra per il calcolo giri: perdita sosta (stima del gioco +
        # transito corsia) e distanza gara nelle gare A GIRI
        measured["max_laps"] = d.get("max_laps")
        # PIANO MURETTO (live_strategy.json): la finestra pit dell'overlay non
        # deve MAI superare la prossima sosta pianificata (es. muro pioggia).
        # "Finestra fino al 30" col diluvio al 19 e' un numero vero e inutile.
        try:
            import time as _t2
            _now3 = _t2.monotonic()
            if _now3 - getattr(self, "_ls_ts", 0.0) >= 3.0:
                self._ls_ts = _now3
                self._next_stop_lap = None
                from core.paths import USER_DIR as _UD2
                import json as _json2
                _f2 = _UD2 / "live_strategy.json"
                if _f2.exists():
                    _dd = _json2.loads(_f2.read_text(encoding="utf-8"))
                    _fresh = (_dd.get("ts")
                              and _t2.time() - float(_dd["ts"]) <= 60.0)
                    if _fresh:
                        _st2 = ((_dd.get("model") or {}).get("stops")) or []
                        _ld2 = int(d.get("laps_completed") or 0)
                        _nx = [float(s2.get("lap")) for s2 in _st2
                               if s2.get("lap") and float(s2["lap"]) > _ld2]
                        self._next_stop_lap = min(_nx) if _nx else None
            measured["next_stop_lap"] = getattr(self, "_next_stop_lap", None)
        except Exception:
            measured["next_stop_lap"] = None
        try:
            _pe = self._pit_est_cached() or {}
            _tot = float(_pe.get("total") or 0.0)
            measured["pit_loss"] = (_tot + 22.0) if _tot > 0 else 50.0
        except Exception:
            measured["pit_loss"] = 50.0
        strat = _strat.compute(measured, self._margin)
        stint = self._tracker.stint_info(d)
        # stato pista (per overlay automatico: in pista mostra, menu/pausa nascondi)
        try:
            _ot = self._mem.is_on_track()
        except Exception:
            _ot = True
        # temperature medie per ruota (gomma = media 3 zone superficie; freno)
        def _avg4(arr):
            out = []
            for x in (arr or []):
                if isinstance(x, (list, tuple)):
                    v = [z for z in x if z is not None]
                    out.append(sum(v) / len(v) if v else None)
                else:
                    out.append(x)
            return (out + [None, None, None, None])[:4]
        _tyre_c = _avg4(d.get("tyre_carcass"))
        _brake_c = _avg4(d.get("brake_temp"))
        _press = _avg4(d.get("tyre_press"))
        # track limits del pilota (per avviso preventivo)
        _tl_steps = _tl_pen = None
        try:
            _tl = self._mem.player_track_limits()
            if _tl:
                _tl_steps = _tl.get("steps"); _tl_pen = _tl.get("per_penalty")
        except Exception:
            pass
        # rivali (nomi/gap/pit/gialla), aggiornati al massimo ogni ~1s
        _riv = None
        try:
            now = time.monotonic()
            if now - getattr(self, "_riv_ts", 0.0) >= 1.0:
                self._riv_cache = self._mem.rivals()
                self._riv_ts = now
            _riv = getattr(self, "_riv_cache", None)
        except Exception:
            _riv = None
        # PASSO VERO dei piloti (storico giri dal REST, cache 10s): arricchisce
        # i rivali con la mediana MISURATA degli ultimi 3 giri — la base per
        # undercut/overcut su dati, non su stime
        # (fetch nel thread _rest_loop: il tick legge SOLO la cache)
        _pace = getattr(self, "_pace_cache", None)
        if _riv and _pace:
            _riv = dict(_riv)
            _riv["ahead_pace"] = _pace.get(str(_riv.get("name_ahead") or "").strip())
            _riv["behind_pace"] = _pace.get(str(_riv.get("name_behind") or "").strip())
            _riv["my_pace"] = _pace.get(str(d.get("driver") or "").strip())
        # pit menu STRUTTURATO + prossimo nodo meteo (cache dal thread REST)
        _pmenu = getattr(self, "_pmenu_cache", None)
        # il menu integrale ("_raw") resta QUI per l'auto fuel: nel raw
        # pubblicato va solo la versione leggera {nome: testo}
        _pm_raw = None
        if _pmenu and "_raw" in _pmenu:
            _pm_raw = _pmenu.get("_raw")
            _pmenu = {k: v for k, v in _pmenu.items() if k != "_raw"}
        _wxnext = getattr(self, "_wxn_cache", None)
        # STIMA GIRI TOTALI (gare a tempo): la bandiera la decide il LEADER.
        # totale = giri leader + rimanente / passo leader (mediana ultimi 5,
        # robusta a traffico e giri sporchi; fallback best leader).
        try:
            _ldr = (_riv or {}).get("leader") or {}
            _ll = int(_ldr.get("laps") or 0)
            if _ll and _ll != getattr(self, "_ldr_laps", None):
                self._ldr_laps = _ll
                _lt2 = float(_ldr.get("last") or 0.0)
                if _lt2 > 20.0 and not _ldr.get("in_pits"):
                    _dq = getattr(self, "_ldr_lt", None)
                    if _dq is None:
                        from collections import deque as _mk_dq
                        _dq = self._ldr_lt = _mk_dq(maxlen=5)
                    _dq.append(_lt2)
            _rrs2 = float(d.get("race_remaining") or 0.0)
            _dq = getattr(self, "_ldr_lt", None)
            _pace = None
            if _dq:
                _srt = sorted(_dq)
                _pace = _srt[len(_srt) // 2]
            if not _pace:
                _pace = float(_ldr.get("best") or 0.0) or None
            if _rrs2 > 0 and _pace and _ll:
                # +1: allo scadere del tempo il leader chiude il giro iniziato
                self._race_laps_est = _ll + int(_rrs2 / _pace) + 1
            elif _rrs2 <= 0:
                self._race_laps_est = None
        except Exception:
            pass
        # danni/flat gomme (cache ~1s)
        _dmg = None
        try:
            now2 = time.monotonic()
            if now2 - getattr(self, "_dmg_ts", 0.0) >= 1.0:
                self._dmg_cache = self._mem.tyre_damage()
                self._dmg_ts = now2
            _dmg = getattr(self, "_dmg_cache", None)
        except Exception:
            _dmg = None
        # wearables (sospensione/aero) — cache dal thread REST
        _susp = _aero = None
        try:
            _w = getattr(self, "_wear_cache", None) or {}
            _susp = _w.get("susp")
            _aero = _w.get("aero")
            _lmu_strat = _w.get("lmu_strat")
            # La strategia (per_lap/autonomia) arriva dallo screen GARAGE: col verde,
            # menu chiuso, puo' sparire -> tieni l'ultima valida cosi' il piano non
            # resta muto in gara. Aggiorna i valori LIVE se il fetch attuale li ha.
            if _lmu_strat and (_lmu_strat.get("per_lap") or _lmu_strat.get("autonomy")):
                self._strat_last = dict(_lmu_strat)
            else:
                _prev = getattr(self, "_strat_last", None)
                if _prev:
                    _merged = dict(_prev)
                    # aggiorna SOLO i valori live realmente presenti. NON toccare il
                    # 'constraint' (proprieta' dell'auto: in gara il menu chiuso fa
                    # leggere maxBattery=0 e lo farebbe diventare FUEL, rompendo il
                    # piano energia dell'Hypercar).
                    if _lmu_strat:
                        for _k in ("nrg_cur", "nrg_max", "fuel_cur", "fuel_max"):
                            if _lmu_strat.get(_k) is not None:
                                _merged[_k] = _lmu_strat[_k]
                    _lmu_strat = _merged
        except Exception:
            _susp = _aero = None
            _lmu_strat = None
        # RIPIEGO STRUTTURATO: se il garage screen non da' la strategia
        # (per_lap/autonomia), la STESSA voce arriva dal PIT MENU vero
        # (receivePitMenu, "100% 26 laps"), che risponde ANCHE in pista a
        # menu garage chiuso — il buco per cui il piano restava muto.
        try:
            if _pmenu and (not _lmu_strat
                           or not (_lmu_strat.get("per_lap")
                                   or _lmu_strat.get("autonomy"))):
                import re as _re9
                _is_ve = bool((_pmenu.get("VIRTUAL ENERGY:") or "").strip())
                _txt9 = (_pmenu.get("VIRTUAL ENERGY:")
                         or _pmenu.get("FUEL:") or "")
                _mm9 = _re9.search(
                    r"(\d+(?:\.\d+)?)\s*[l%]?\s*[/ ]+\s*(\d+)\s*(?:laps?|giri)",
                    _txt9, _re9.I)
                if _mm9 and int(_mm9.group(2)) > 0:
                    _base9 = dict(_lmu_strat or {})
                    _base9.setdefault("constraint",
                                      "ENERGY" if _is_ve else "FUEL")
                    _base9["per_lap"] = float(_mm9.group(1)) / int(_mm9.group(2))
                    _base9["autonomy"] = int(_mm9.group(2))
                    _lmu_strat = _base9
                    self._strat_last = dict(_base9)
        except Exception:
            pass
        # dati della tua auto dallo standings — cache dal thread REST
        _est_standings = None
        _penalties = 0
        try:
            _pl = getattr(self, "_player_cache", None) or {}
            _est_standings = _pl.get("est_lap")
            _penalties = int(_pl.get("penalties") or 0)
        except Exception:
            _est_standings = None
            _penalties = 0
        # est_lap affidabile: telemetria se valida, altrimenti standings
        _est_tel = float(d.get("est_lap") or 0.0)
        _est_lap = _est_tel if _est_tel > 0 else (_est_standings or 0.0)
        # forecast pioggia ai 5 nodi (cache dal thread REST; qui solo gli input)
        _fc_rain = None
        try:
            self._rest_styp = d.get("session_type")
            self._rest_tod = d.get("time_of_day")
            _w5 = getattr(self, "_fcr_cache", None) or {}
            _fc_rain = _w5.get("rain")
            _fc_ico = _w5.get("icons")      # "sun,cloud,rain,..." per i 5 nodi
        except Exception:
            _fc_rain = None
            _fc_ico = None
        # dotazione gomme dal REST (cache dal thread REST)
        _tyre_inv = getattr(self, "_tinv_cache", None)
        # OROLOGIO SESSIONE LISCIO: lo scoring arriva a raffiche e a volte
        # strappato -> race_remaining ballava avanti/indietro e i secondi
        # saltellavano su TUTTI i display. Conto alla rovescia locale
        # (wall clock), riallineato al dato solo se scarta >1.5s (evento
        # vero: pausa, cambio sessione — non jitter).
        try:
            _rrv = float(d.get("race_remaining") or 0.0)
            _nowr = time.monotonic()
            _pvr = getattr(self, "_rr_smooth", None)
            if _rrv > 0 and _pvr is not None:
                _expr = _pvr[0] - (_nowr - _pvr[1])
                if abs(_rrv - _expr) <= 1.5:
                    _rrv = max(0.0, _expr)
            if _rrv > 0:
                self._rr_smooth = (_rrv, _nowr)
                d["race_remaining"] = _rrv
            else:
                self._rr_smooth = None
        except Exception:
            pass
        # REGOLE sessione dal REST (cache dal thread REST)
        _rules = getattr(self, "_rules_cache", None)
        # bandiere (gialla a distanza, blu per classe), cache ~0.5s
        _flags = None
        try:
            now4 = time.monotonic()
            if now4 - getattr(self, "_flags_ts", 0.0) >= 0.5:
                self._flags_cache = self._mem.flags()
                self._flags_ts = now4
            _flags = getattr(self, "_flags_cache", None)
        except Exception:
            _flags = None
        # I fetch REST cache-miss (pit-est ~3s, pit-entry ~30s) fanno una
        # urlopen BLOCCANTE fino a 500ms. Vanno calcolati QUI, FUORI dal
        # lock: se restano dentro 'with self._lock', il thread recorder
        # tiene il lock durante l'HTTP e il main thread (rec.latest()) si
        # BLOCCA fino a 500ms ogni 3s -> i famosi scatti periodici.
        try:
            _pit_entry = self._pit_entry_cached()
        except Exception:
            _pit_entry = None
        try:
            _pit_est = self._pit_est_cached()
        except Exception:
            _pit_est = None
        # CONSUMO MISURATO DA LMU (/rest/strategy/usage): il thread strategia
        # lo tiene aggiornato; qui prendo solo l'ultimo pronto (lock brevissimo,
        # nessuna rete). Sveglio il thread quando cambia il giro.
        try:
            _lc = int(d.get("laps_completed") or 0)
            if _lc != self._usage_lap:
                self._usage_lap = _lc
                self._usage_wake.set()
        except (TypeError, ValueError):
            pass
        with self._usage_lock:
            _u_ve = self._usage_pl.get("ve")
            _u_fu = self._usage_pl.get("fuel")
            _u_st = self._usage_stint
        # per_lap di LMU nell'UNITA' GIUSTA del vincolo. Attenzione: /usage da'
        # sempre FRAZIONI (0..1), ma il resto del codice vuole
        #   ENERGY -> % per giro   |   FUEL -> LITRI per giro
        # (il per_lap del pit-menu e' "100%/63 laps" vs "98l/56 laps").
        _lmu_per_lap = None
        _lmu_cons_fuel = None
        try:
            _c = (_lmu_strat or {}).get("constraint") or "FUEL"
            _fmax = float((_lmu_strat or {}).get("fuel_max") or 0.0)
            if _u_fu and _fmax > 0:
                _lmu_cons_fuel = float(_u_fu) * _fmax      # frazione -> litri
            if _c == "ENERGY":
                if _u_ve:
                    _lmu_per_lap = float(_u_ve) * 100.0    # frazione -> %
            else:
                _lmu_per_lap = _lmu_cons_fuel              # gia' in litri
        except Exception:
            _lmu_per_lap = None
        # FONTE UNICA del consumo: qui 'lmu_strat["per_lap"]' diventa il dato
        # MISURATO da /rest/strategy/usage. Serve perche' il muretto lo legge da
        # una decina di punti diversi (engineer.py: piano, box, radio, delta...)
        # e cambiarli uno per uno lascerebbe meta' cervello sulla vecchia regex.
        # Se LMU non ha ancora abbastanza giri puliti il valore e' None: il
        # muretto resta muto sui consumi invece di inventare una stima. Il valore
        # vecchio (regex sul testo del pit-menu) resta come 'per_lap_menu' a solo
        # scopo di diagnosi: NON va usato per la strategia.
        if _lmu_strat is not None:
            _lmu_strat = dict(_lmu_strat)      # copia: non sporcare la cache
            _lmu_strat["per_lap_menu"] = _lmu_strat.get("per_lap")
            _lmu_strat["per_lap"] = _lmu_per_lap
        # stato TELEMETRIA per la Dashboard card (scritto SOLO al cambio)
        try:
            _rec_on = bool(self._armed and self._writing)
            if _rec_on != getattr(self, "_rec_flag_last", None):
                self._rec_flag_last = _rec_on
                from core.paths import USER_DIR as _UD3
                import json as _js3
                (_UD3 / "telemetry_state.json").write_text(
                    _js3.dumps({"rec": _rec_on}), encoding="utf-8")
        except Exception:
            pass
        # ── LMU LIVE: blocco DEDICATO alla strategia, dati DIRETTI di LMU
        # assemblati QUI e solo qui (che gomma monto, quanto carico ho,
        # quanto serve, quando). Campo mancante = None, MAI assunto: il
        # 19/07 il muretto e' rimasto cieco perche' "ve" si era perso
        # nella spedizione del raw generico.
        _live = None
        try:
            _vt = (_pmenu or {}).get("_ve_table") or []
            _ve_now = d.get("ve_pct")
            _fu_now = d.get("fuel")
            _cstr9 = (_lmu_strat or {}).get("constraint") \
                or ("ENERGY" if _vt else None)
            # consumo/giro: MISURATO da LMU (usage); senno' la TABELLA
            # del pit menu (100% -> N giri, sempre conto del gioco)
            _plap9 = _lmu_per_lap
            _psrc9 = "measured" if _plap9 else None
            if not _plap9 and _vt:
                _top9 = max(_vt, key=lambda r: r[0])
                if _top9[0] > 0 and _top9[1] > 0:
                    _plap9 = float(_top9[0]) / float(_top9[1])
                    _psrc9 = "menu"
            _autol = None
            if _plap9:
                if _cstr9 == "ENERGY" and _ve_now is not None:
                    _autol = float(_ve_now) / _plap9
                elif _cstr9 == "FUEL" and _fu_now is not None:
                    _autol = float(_fu_now) / _plap9
            _rem9 = float(d.get("race_remaining") or 0.0)
            _est9 = float(_est_lap or 0.0)
            _need9 = int(_rem9 / _est9) + 1 \
                if (_rem9 > 0 and _est9 > 20.0) else None
            _tgt9 = None
            if _need9 is not None and _vt:
                _cov9 = [r for r in _vt if r[1] >= _need9 + 2]
                _tgt9 = min(_cov9)[0] if _cov9 else 100
            _live = {
                "constraint": _cstr9,
                "ve_pct": _ve_now, "fuel_l": _fu_now,
                "fuel_max": d.get("fuel_max"),
                "per_lap": _plap9, "per_lap_src": _psrc9,
                "autonomy_laps": round(_autol, 2)
                if _autol is not None else None,
                "race_remaining": _rem9 or None,
                "est_lap": _est9 or None,
                "max_laps": d.get("max_laps"),
                "laps_completed": d.get("laps_completed"),
                "laps_needed": _need9, "target_pct": _tgt9,
                "ve_table": _vt or None,
                "compound4": d.get("tyre_compound4"),
                "raining": d.get("raining"),
                "wetness": d.get("wetness"),
            }
        except Exception:
            _live = None
        # ── AUTO FUEL (opt-in dal tab Engineer): tiene la VE del pit
        # menu allineata al fabbisogno, SOLO in gara. Il confronto e'
        # col currentSetting ATTUALE del gioco (dopo la sosta LMU
        # azzera il menu). Collaudato come prototipo il 20/07.
        try:
            if _live and int(d.get("session_type") or 0) >= 10:
                self._auto_fuel_tick(_pm_raw, _live)
            elif _live:
                self._af_pct = None      # fuori gara: spento e muto
        except Exception:
            pass
        if _live is not None:
            _live["auto_fuel_pct"] = getattr(self, "_af_pct", None)
        with self._lock:
            self._latest = {
                "strat": strat,
                "stint": stint,
                "raw": {**{k: d.get(k) for k in (
                    "fuel", "fuel_max", "ve_pct", "soc", "regen_kw", "boost_state",
                    "battery",
                    "lift_coast", "in_pits", "in_pitlane", "num_pit", "laps_completed",
                    "car_class", "track", "wetness", "raining", "garage", "session_type",
                    "wetness_min", "wetness_max", "track_grip", "track_temp",
                    "impact_et", "impact_mag",
                    # (chiavi da d; session_rules aggiunto sotto)
                    "tyre_compound4", "compound_front", "compound_rear",
                    "eng_oil", "eng_water", "overheating",
                    "max_laps", "game_phase", "est_lap", "driver",
                    "race_total", "race_remaining", "best_lap",
                    "last_s1", "last_s2")},
                    "on_track": _ot, "ts": time.monotonic(),
                    "est_lap": _est_lap, "forecast_rain": _fc_rain,
                    "forecast_icons": _fc_ico,
                    "tyre_inventory": _tyre_inv,
                    "penalties": _penalties,
                    "tyre_wear": d.get("tyre_wear"), "tyre_grip": d.get("tyre_grip"),
                    "wheel_flat": d.get("wheel_flat"), "wheel_off": d.get("wheel_off"),
                    "dent_sev": d.get("dent_sev"), "parts_off": d.get("parts_off"),
                    "tyre_temp": _tyre_c, "brake_temp": _brake_c,
                    "tyre_press": _press,
                    "tl_steps": _tl_steps, "tl_pen": _tl_pen,
                    "rivals": _riv, "damage": _dmg,
                    "race_laps_est": getattr(self, "_race_laps_est", None),
                    "lock_events": list(getattr(self, "_lock_ev", None) or []),
                    "susp": _susp, "aero": _aero,
                    "lap_time": d.get("last_lap"),
                    "flags": _flags, "sector": d.get("sector"),
                    "surface_type": d.get("surface_type"),
                    "pit_state": d.get("pit_state"),
                    "session_rules": _rules,
                    "pace_by_name": _pace,
                    "pit_menu": _pmenu,
                    "weather_next": _wxnext,
                    "lapdist": d.get("lapdist"),
                    "pit_entry_dist": _pit_entry,
                    "pit_est": _pit_est,
                    # consumo/stint MISURATI da LMU (/rest/strategy/usage):
                    # giri col pit gia' esclusi. Fonte da preferire al delta
                    # grezzo dell'ultimo giro, che out-lap/SC/pit falsavano.
                    "lmu_per_lap": _lmu_per_lap,      # unita' del vincolo
                    "lmu_cons_ve": (_u_ve * 100.0) if _u_ve else None,  # %
                    "lmu_cons_fuel": _lmu_cons_fuel,                    # litri
                    "lmu_stint": _u_st,
                    "lmu_live": _live,
                    "lmu_strat": _lmu_strat},
                "measured": measured,
            }

        # ── AUTO-START: arma da solo quando entri in pista (prima del return) ──
        try:
            _ot_auto = self._mem.is_on_track()
        except Exception:
            _ot_auto = False
        if not _ot_auto:
            self._auto_paused = False     # uscito dalla pista: riabilita auto-start
        if (getattr(self, "_autostart", False) and _ot_auto
                and not self._armed and not self._auto_paused):
            self.arm()                    # _armed diventa True: il loop prosegue

        if not self._armed:
            self._st("stopped (press START)")
            return

        # cambio sessione (tipo o pista) mentre si registra = fine sessione -> stop
        sig = (d.get("track"), d.get("session_type"))
        if self._arm_sig is None:
            self._arm_sig = sig
        elif d.get("track") and sig != self._arm_sig:
            if self._ever_active:
                # cambio sessione DOPO aver girato = sessione finita -> stop
                self._auto_disarm("session changed")
                return
            # ancora in attesa del via (la prep si chiude e parte la gara):
            # NON disarmare, riallinea l'armamento alla nuova sessione.
            self._arm_sig = sig
            self._reset_session_state()

        # registra SOLO quando giri davvero: in pista e non fermo in garage.
        # (la strategia live sopra gira comunque sempre)
        on_track = False
        try:
            on_track = self._mem.is_on_track()
        except Exception:
            on_track = True
        # ROBUSTEZZA: i flag dello scoring (mInRealtime, pausa da ET fermo)
        # hanno FALSI NEGATIVI mentre guidi (lo scoring aggiorna a ~0.2-0.5s:
        # un hiccup > 0.5s sembrava "pausa") -> il recorder smetteva di
        # scrivere e la traiettoria aveva i BUCHI. La telemetria non mente:
        # se il SUO tempo avanza e l'auto si muove, sei in pista, qualunque
        # cosa dica lo scoring.
        _tel_et = d.get("elapsed")
        _tel_live = False
        try:
            if (_tel_et is not None
                    and getattr(self, "_ontrack_et", None) is not None):
                _tel_live = float(_tel_et) > float(self._ontrack_et) + 1e-4
        except (TypeError, ValueError):
            _tel_live = False
        self._ontrack_et = _tel_et
        try:
            _moving = float(d.get("speed") or 0.0) > 3.0
        except (TypeError, ValueError):
            _moving = False
        active = (on_track or (_tel_live and _moving)) \
            and not bool(d.get("garage"))
        # in GARA (session_type >= 10): aspetta il VERDE. Durante prep/gridwalk/
        # formation/countdown (fasi 0-4) resta armato in WAIT e parte da solo al
        # via (mGamePhase 5 verde, 6 full-course yellow). Pratica/Qualify invariati.
        try:
            _styp = int(d.get("session_type") or 0)
        except Exception:
            _styp = 0
        self._wait_green = False
        if _styp >= 10:
            ph = None
            try:
                ph = self._mem.game_phase()
            except Exception:
                ph = None
            if ph is not None and ph < 5 and not self._ever_active:
                active = False           # ancora in preparazione: non scrivere
                self._wait_green = True
        # SESSIONE SUBITO: pista, auto, pilota, team, classe, forecast sono già
        # noti appena sei in garage -> crea il file ORA, non all'uscita dai box.
        # In attesa del verde (gara) NON creare: evita la falsa sessione pre-grid.
        if not self._wait_green and d.get("track"):
            self._maybe_new_event(d)

        if not active:
            self._writing = False
            # DIAGNOSI CONGELAMENTO: mCurrentET fermo per MINUTI = plugin
            # shared memory di LMU morto in sessione (non e' una pausa).
            # L'app non puo' sbloccarlo: lo si DICE nel banner, invece di
            # lasciare card vuote mute (successo in gara il 18/07).
            try:
                _frz = self._mem.frozen_secs()
            except Exception:
                _frz = 0.0
            if _frz > 120.0:
                self._st("GAME DATA FROZEN %.0fs — restart the LMU session"
                         % _frz)
            else:
                self._st("garage" if bool(d.get("garage")) else
                         ("not_on_track (is_on_track=False)" if not on_track else "inattivo"))
            if self._db is not None:
                self._db.flush()      # salva quel che c'è, ma non aprire nuovi file
            if bool(d.get("garage")):
                self._garage_seen = True
            self._was_active = False
            return

        # transizione inattivo->attivo: nuovo stint SOLO se si è usciti dal garage
        if not self._was_active:
            if not self._stint_started:
                self._stint_started = True            # primo stint del file
            elif self._db is not None and self._garage_seen:
                self._file_stint += 1                 # uscita dal box = stint successivo
                self._stint_lap_count = 0
                self._prev_sector = None              # reinit pulito per il nuovo stint
            self._garage_seen = False
        self._was_active = True
        self._ever_active = True

        # PIT STOP (gara): num_pit che sale = fine stint, senza passare dal garage.
        # In pit l'auto resta "attiva", quindi va rilevato qui, non sulla
        # transizione attivo/inattivo.
        np = int(d.get("num_pit", 0) or 0)
        if (self._last_num_pit is not None and np > self._last_num_pit
                and self._stint_started and self._db is not None):
            self._file_stint += 1
            self._stint_lap_count = 0
            self._prev_sector = None
            self._garage_seen = False     # evita doppio incremento se segue il garage
        self._last_num_pit = np

        # nuovo evento? (cambio pista o auto) -> nuovo file
        self._maybe_new_event(d)
        if self._db is None:
            self._st("db_none (track='%s' car='%s' -> file non creato)"
                     % (d.get("track") or "", d.get("car_class") or ""))
            return
        self._writing = True
        self._st("recording %s" % (self._evt_track or ""))

        sector = int(d.get("sector", 0) or 0)
        laps = int(d.get("laps_completed", 0) or 0)
        fuel = d.get("fuel")
        ve = d.get("ve_pct")

        # init contatori al primo campione utile
        if self._prev_sector is None:
            self._prev_sector = sector
            self._prev_laps = laps
            self._cur_lap_id = laps + 1
            self._lap_start_fuel = fuel
            self._lap_start_ve = ve
            self._prev_et = None
            self._prev_soc = d.get("soc")
            self._lap_regen_pos = 0.0
            self._lap_boost = 0.0
            self._lap_soc_start = d.get("soc")
            self._lap_wmin = None
            self._lap_wmax = None
            self._ld_anchor = None
            self._lock_ev = None
            self._lock_now = set()
            self._reset_sector_acc(d)

        # accumula per il settore corrente
        carc = d.get("tyre_carcass") or [None] * 4
        surf = d.get("tyre_surf") or [None] * 4     # battistrada (3 punti L/C/R)
        inner = d.get("tyre_inner") or [None] * 4   # strato interno (3 punti L/C/R)
        press = d.get("tyre_press") or [None] * 4   # pressione (kPa)
        brk = d.get("brake_temp") or [None] * 4
        for i in range(4):
            if carc[i] is not None:
                self._sec_t_sum[i] += carc[i]
            sv = self._mean3(surf[i])
            if sv is not None:
                self._sec_ts_sum[i] += sv
            iv = self._mean3(inner[i])
            if iv is not None:
                self._sec_ti_sum[i] += iv
            if press[i] is not None:
                self._sec_p_sum[i] += press[i]
            if brk[i] is not None:
                self._sec_b_sum[i] += brk[i]
        self._sec_regen_sum += float(d.get("regen_kw", 0.0) or 0.0)
        # integrale energia: regen_kw firmato (+recupero / -deploy) * dt
        et = d.get("elapsed")
        if et is not None and self._prev_et is not None:
            dt = et - self._prev_et
            if 0.0 < dt < 0.5:
                rk = float(d.get("regen_kw", 0.0) or 0.0)
                e = abs(rk) * dt / 3600.0
                if rk > 0:
                    self._sec_regen_pos += e; self._lap_regen_pos += e
                elif rk < 0:
                    self._sec_boost += e; self._lap_boost += e
        self._prev_et = et
        self._prev_soc = d.get("soc")
        sp = d.get("speed")
        if sp is not None:
            self._sec_spd_sum += sp
            if sp > self._sec_spd_max:
                self._sec_spd_max = sp
        self._sec_n += 1

        # lapdist CONTINUO: mLapDist arriva dallo scoring a ~2Hz e resta
        # congelato ~0.5s (i grafici a distanza collassavano 10 campioni su
        # una x sola). Dead-reckoning con la velocita' tra un update e l'altro.
        _ld_raw = d.get("lapdist")
        _et_now = d.get("elapsed")
        _ld_cont = _ld_raw
        if _ld_raw is not None and _et_now is not None:
            _a = getattr(self, "_ld_anchor", None)
            if _a is None or _ld_raw != _a[0]:
                self._ld_anchor = (_ld_raw, _et_now)
            else:
                _spd = (d.get("speed") or 0.0) / 3.6
                _ld_cont = _ld_raw + max(0.0, _et_now - _a[1]) * _spd
        # BLOCCAGGI: in staccata (freno >=40%, >60 km/h) una ruota quasi
        # ferma mentre le altre girano = lock. UN evento per ruota per
        # staccata (si riarma quando la ruota riprende a girare).
        try:
            _rots = d.get("wheel_rot") or []
            _brk_in = float(d.get("brake") or 0.0)
            _spd_k = float(d.get("speed") or 0.0)
            if len(_rots) == 4 and _brk_in >= 0.4 and _spd_k >= 60.0:
                _vr = [r for r in _rots if r is not None]
                _mx = max(_vr) if _vr else 0.0
                if _mx > 8.0:
                    _lk = {i for i, r in enumerate(_rots)
                           if r is not None and r < 0.30 * _mx}
                    _pl2 = getattr(self, "_lock_now", set())
                    for _i in (_lk - _pl2):
                        _dq = getattr(self, "_lock_ev", None)
                        if _dq is None:
                            from collections import deque as _mkd
                            _dq = self._lock_ev = _mkd(maxlen=200)
                        _dq.append((float(_ld_cont or 0.0), _i))
                        # evento su db (marker mappa): ruota bloccata, dove
                        try:
                            self._db.add_event({
                                "lap": self._cur_lap_id,
                                "t": float(d.get("elapsed", 0)) - float(d.get("lap_start_et", 0)),
                                "lapdist": _ld_cont,
                                "x": d.get("pos_x"), "z": d.get("pos_z"),
                                "kind": "lock", "val": float(_i)})
                        except Exception:
                            pass
                    self._lock_now = _lk
            else:
                self._lock_now = set()
        except (TypeError, ValueError):
            pass

        # traccia lap_start: serve alla stima del tempo giro quando LMU
        # non lo fornisce (mLastLapTime <= 0, es. giro del via)
        _ls = d.get("lap_start_et")
        if _ls is not None and _ls != getattr(self, "_ls_cur", None):
            self._ls_prev = getattr(self, "_ls_cur", None)
            self._ls_cur = _ls
        # bagnatura pista del giro: min scia / max fuori scia (per giro)
        _wmn = d.get("wetness_min"); _wmx = d.get("wetness_max")
        if _wmn is not None:
            _c0 = getattr(self, "_lap_wmin", None)
            self._lap_wmin = _wmn if _c0 is None else min(_c0, _wmn)
        if _wmx is not None:
            _c1 = getattr(self, "_lap_wmax", None)
            self._lap_wmax = _wmx if _c1 is None else max(_c1, _wmx)

        # traccia (campione alta frequenza, taggato per giro)
        samp = {
            "lap": self._cur_lap_id,
            "t": float(d.get("elapsed", 0)) - float(d.get("lap_start_et", 0)),
            "lapdist": _ld_cont,
            "pos_x": d.get("pos_x"), "pos_y": d.get("pos_y"), "pos_z": d.get("pos_z"),
            "speed": d.get("speed"),
            "throttle": d.get("throttle"), "brake": d.get("brake"), "steer": d.get("steer"),
            "g_long": d.get("g_long"), "g_lat": d.get("g_lat"),
            "tc_active": d.get("tc_active"), "abs_active": d.get("abs_active"),
            "brake_bias": d.get("brake_bias"),
            "tc_map": d.get("tc_map"), "abs_map": d.get("abs_map"),
            "tc_slip": d.get("tc_slip"), "tc_cut": d.get("tc_cut"),
            "gear": d.get("gear"), "rpm": d.get("rpm"),
            "overheating": d.get("overheating"),
            "compound_f": d.get("compound_f"), "compound_r": d.get("compound_r"),
            "tyre_compound4": d.get("tyre_compound4"),
            "emotor_rpm": d.get("emotor_rpm"), "emotor_tq": d.get("emotor_tq"),
            "water_temp": d.get("water_temp"), "oil_temp": d.get("oil_temp"),
            "soc": d.get("soc"), "regen_kw": d.get("regen_kw"),
            "boost_state": d.get("boost_state"),
            "fuel": d.get("fuel"), "ve": d.get("ve_pct"),
            "tyre_t": self._mean4(carc),
            "tyre_ts": self._mean4([self._mean3(surf[i]) for i in range(4)]),
            "tyre_ti": self._mean4([self._mean3(inner[i]) for i in range(4)]),
            "tyre_p": self._mean4(press),
            "brake_t": self._mean4(brk),
        }
        # canali PER RUOTA (FL/FR/RL/RR) per i grafici gomma dedicati
        wear_s = d.get("tyre_wear") or [None] * 4
        sdefl_s = d.get("susp_defl") or [None] * 4
        rideh_s = d.get("ride_h") or [None] * 4
        bpress_s = d.get("brake_press") or [None] * 4
        sforce_s = d.get("susp_force") or [None] * 4
        slat_s = d.get("slip_lat") or [None] * 4
        for i, wn in enumerate(("fl", "fr", "rl", "rr")):
            samp["tyre_t_" + wn] = carc[i]
            samp["tyre_ts_" + wn] = self._mean3(surf[i])
            samp["tyre_ti_" + wn] = self._mean3(inner[i])
            samp["tyre_p_" + wn] = press[i]
            samp["brake_t_" + wn] = brk[i]
            samp["susp_d_" + wn] = sdefl_s[i]
            samp["ride_h_" + wn] = rideh_s[i]
            samp["brake_p_" + wn] = bpress_s[i]
            samp["tyre_w_" + wn] = wear_s[i]
            samp["sforce_" + wn] = sforce_s[i]
            samp["slat_" + wn] = slat_s[i]
        # METEO per-sample (continuo): asfalto + pioggia
        _rn = d.get("raining")
        samp["track_temp"] = d.get("track_temp")
        samp["rain_pct"] = (float(_rn) * 100.0) if _rn is not None else None
        self._db.add_sample(samp)

        # ── EVENTI puntuali su db (marker mappa / pagina FIA) ──
        try:
            # contatto: mLastImpactET nuovo (soglia 120 = via il rumore cordoli)
            _iet = d.get("impact_et"); _img = d.get("impact_mag")
            if _iet and _iet != getattr(self, "_ev_imp_et", None):
                self._ev_imp_et = _iet
                if _img and float(_img) >= 120.0:
                    self._db.add_event({
                        "lap": samp["lap"], "t": samp["t"], "lapdist": _ld_cont,
                        "x": d.get("pos_x"), "z": d.get("pos_z"),
                        "kind": "contact", "val": float(_img)})
            # track limits: gli steps salgono -> taglio QUI (val = totale steps)
            _ptl = getattr(self, "_ev_tl_prev", None)
            if _tl_steps is not None:
                if _ptl is not None and _tl_steps > _ptl:
                    self._db.add_event({
                        "lap": samp["lap"], "t": samp["t"], "lapdist": _ld_cont,
                        "x": d.get("pos_x"), "z": d.get("pos_z"),
                        "kind": "tl", "val": float(_tl_steps)})
                self._ev_tl_prev = _tl_steps
        except Exception:
            pass

        # DURATA SESSIONE: race_total all'apertura non e' assestato (legge 0/5/60),
        # cosi' la card mostrava "1m". Aggiorno col valore reale appena stabile.
        _rt = d.get("race_total")
        try:
            _rt = float(_rt) if _rt is not None else 0.0
        except (TypeError, ValueError):
            _rt = 0.0
        if _rt > 120.0 and _rt > getattr(self, "_sess_len_seen", 0.0) + 1.0:
            self._sess_len_seen = _rt
            self._db.update_session_len(_rt)

        # cambio settore -> scrivi aggregato del settore appena chiuso
        if sector != self._prev_sector:
            self._write_sector(d, self._prev_sector, self._cur_lap_id)
            self._prev_sector = sector
            self._reset_sector_acc(d)

        # ACQUA SOTTO LE RUOTE (64Hz, per giro): mSurfaceType per ruota e'
        # binario (1 = asfalto bagnato). Ogni tick vale RUOTE BAGNATE / 4
        # (0, .25, .5, .75, 1): con la dry line che si forma, 2 ruote sulle
        # chiazze contano meta', non un tick pieno — la percentuale del giro
        # riflette quanta acqua hai DAVVERO toccato, non arrotonda per eccesso.
        st = d.get("surface_type") or []
        try:
            _ww = sum(1 for x in st if int(x or 0) == 1)
            if len(st) >= 4:
                self._lap_wet_ticks = getattr(self, "_lap_wet_ticks", 0.0) + _ww / 4.0
                self._lap_surf_ticks = getattr(self, "_lap_surf_ticks", 0) + 1
        except (TypeError, ValueError):
            pass

        # giro completato -> scrivi riga giro
        if self._prev_laps is not None and laps > self._prev_laps:
            self._write_lap(d, laps)
            self._prev_laps = laps
            self._cur_lap_id = laps + 1
            self._lap_start_fuel = fuel
            self._lap_start_ve = ve
            self._lap_regen_pos = 0.0
            self._lap_boost = 0.0
            self._lap_soc_start = d.get("soc")
            self._lap_wet_ticks = 0.0
            self._lap_surf_ticks = 0
            self._lap_wmin = None
            self._lap_wmax = None

        # flush periodico
        now = time.monotonic()
        if now - self._last_flush > 1.5:
            self._db.flush()
            self._last_flush = now

    # ── eventi/file ────────────────────────────────────────────────────
    def _auto_fuel_tick(self, menu_raw, live):
        """AUTO FUEL (opt-in): scrive nel pit menu la VE MINIMA che copre
        i giri rimanenti (+2 di margine), dalla tabella %->giri DEL GIOCO.
        Regole dal collaudo del 20/07:
          - confronto col currentSetting ATTUALE (LMU azzera dopo la sosta)
          - mai sotto 2 minuti di gara (transizioni/fine)
          - ciclo 5s; POST solo se il valore nel gioco e' diverso
        Espone self._af_pct per l'annuncio dell'ingegnere."""
        import re as _re
        now = time.monotonic()
        if now - getattr(self, "_af_ts", 0.0) < 5.0:
            return
        self._af_ts = now
        try:
            from engineer_overlay import _load_cfg as _lc
            if not bool(_lc().get("auto_pit", False)):
                self._af_pct = None
                return
        except Exception:
            return
        need = live.get("laps_needed")
        if not menu_raw or need is None:
            return
        if float(live.get("race_remaining") or 0.0) < 120.0:
            return
        item = None
        for it in menu_raw:
            if str((it or {}).get("name") or "").startswith(
                    "VIRTUAL ENERGY"):
                item = it
                break
        if item is None:
            return
        try:
            cur_ix = int(item.get("currentSetting") or 0)
        except (TypeError, ValueError):
            cur_ix = 0
        best = None
        opts = item.get("settings") or []
        for ix, op in enumerate(opts):
            m = _re.match(r"(\d+)%\s+(\d+)\s+laps",
                          str((op or {}).get("text") or ""))
            if m and int(m.group(2)) >= int(need) + 2:
                if best is None or int(m.group(1)) < best[1]:
                    best = (ix, int(m.group(1)))
        if best is None:
            if not opts:
                return
            best = (len(opts) - 1, 100)      # il pieno non basta: TUTTO
        self._af_pct = best[1]
        if best[0] == cur_ix:
            return
        item["currentSetting"] = best[0]

        # POST fuori dal tick (fino a 1.5s): fire-and-forget su thread
        def _send(_payload=menu_raw):
            try:
                import json as _js
                import urllib.request as _ur
                req = _ur.Request(
                    "http://localhost:6397/rest/garage/PitMenu/loadPitMenu",
                    data=_js.dumps(_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST")
                _ur.urlopen(req, timeout=1.5)
            except Exception:
                pass
        threading.Thread(target=_send, daemon=True).start()

    def _pit_est_cached(self):
        """Stima sosta del gioco: cache riempita dal thread _rest_loop."""
        return getattr(self, "_pit_est", None)

    def _pit_entry_cached(self):
        """PitEntryDist della pista: cache riempita dal thread _rest_loop
        (fetch una volta, ritenta ogni 30s; azzerata a cambio evento)."""
        return getattr(self, "_pit_entry", None)

    def _maybe_new_event(self, d):
        track = d.get("track") or ""
        car = d.get("car_class") or ""
        session = d.get("session_type")
        if not track:
            return
        # stesso evento = stessa pista + stessa auto + stessa sessione. Pausa e
        # garage NON aprono un nuovo file (oscillano realtime/garage, non la
        # sessione): proseguono lo stesso file, nuovo stint. Nuovo file solo se
        # cambia pista, auto, o il tipo di sessione (Practice->Quali->Race, cioè
        # quando il tempo di sessione finisce e ne parte un'altra).
        if (self._db is not None and track == self._evt_track
                and (car == self._evt_car or not car)
                and session == self._evt_session):
            return
        # chiudi il precedente
        if self._db is not None:
            _old = getattr(self._db, "path", None)
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None
            self._discard_if_empty(_old)
        # apri il nuovo
        try:
            fn = _db.LOGS_DIR / _db.make_filename(track, car, session)
            self._db = _db.TelemetryDB(fn)
            self._sess_len_seen = 0.0          # ricattura la durata reale per la nuova sessione
            self._db.write_meta({
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "started_et": d.get("cur_et"),
                "session_len": d.get("race_total"),
                "track": track,
                "track_logo": None,
                "vehicle": d.get("vehicle"),
                "car_class": car,
                "session_type": session,
                "fuel_max": d.get("fuel_max"),
                "ve_max": 100.0,
                "app_version": "v0.1 beta",
                "car_num": self._player_num(),
                "driver": d.get("driver"),
                "team": d.get("team"),
                "fuel_start": d.get("fuel"),
                "air_temp": d.get("air_temp"),
                "track_temp": d.get("track_temp"),
                "wetness": d.get("wetness"),
                "compound_f": d.get("compound_front"),
                "compound_r": d.get("compound_rear"),
                "compounds4": ",".join(d.get("tyre_compound4") or []),
                "forecast5": _fetch_forecast5(session, d.get("time_of_day") or 43200),
            })
            _diag("FILE CREATO: %s" % fn)
            self._evt_track = track
            self._evt_session = session
            self._evt_car = car
            self._prev_sector = None      # forza re-init contatori
            self._file_stint = 1
            self._stint_lap_count = 0
            self._stint_started = False    # lo stint 1 parte all'uscita dai box
            self._garage_seen = False
            self._last_num_pit = None
            try:
                self._tracker.reset_all()  # stint riparte da 1 sul nuovo evento
            except Exception:
                pass
        except Exception:
            _diag("ERROR creating file:\n" + traceback.format_exc())
            self._db = None

    def _reset_sector_acc(self, d):
        self._sec_start_fuel = d.get("fuel")
        self._sec_start_ve = d.get("ve_pct")
        wear = d.get("tyre_wear") or [None] * 4
        self._sec_start_wear = list(wear)
        self._sec_t_sum = [0.0] * 4
        self._sec_ts_sum = [0.0] * 4
        self._sec_ti_sum = [0.0] * 4
        self._sec_p_sum = [0.0] * 4
        self._sec_b_sum = [0.0] * 4
        self._sec_regen_sum = 0.0
        self._sec_spd_sum = 0.0
        self._sec_spd_max = 0.0
        self._sec_n = 0
        self._sec_regen_pos = 0.0
        self._sec_boost = 0.0
        self._sec_soc_start = d.get("soc")

    def _write_sector(self, d, sec_idx, lap):
        n = max(1, self._sec_n)
        wear = d.get("tyre_wear") or [None] * 4
        row = {"lap": lap, "sector": int(sec_idx), "s_time": None,
               "fuel_used": self._delta(self._sec_start_fuel, d.get("fuel")),
               "ve_used": self._delta(self._sec_start_ve, d.get("ve_pct")),
               "regen_kwh": self._sec_regen_sum / n,
               "spd_avg": self._sec_spd_sum / n,
               "spd_max": self._sec_spd_max,
               "regen_gain_kwh": self._sec_regen_pos,
               "boost_kwh": self._sec_boost,
               "soc_used": self._delta(self._sec_soc_start, d.get("soc"))}
        keys = ("fl", "fr", "rl", "rr")
        for i, k in enumerate(keys):
            row["t_" + k] = self._sec_t_sum[i] / n
            row["ts_" + k] = self._sec_ts_sum[i] / n
            row["ti_" + k] = self._sec_ti_sum[i] / n
            row["p_" + k] = self._sec_p_sum[i] / n
            row["b_" + k] = self._sec_b_sum[i] / n
            sw = self._sec_start_wear[i]
            row["w_" + k] = self._delta(sw, wear[i]) if (sw is not None and wear[i] is not None) else None
        self._db.add_sector(row)

    def _write_lap(self, d, lap):
        s1 = d.get("last_s1") or 0.0
        s2sum = d.get("last_s2") or 0.0
        lt = d.get("last_lap") or 0.0
        if lt <= 0:
            # LMU non ha dato il tempo (es. giro del via): stima dalla
            # telemetria hi-res = differenza fra i due lap_start_et
            _lp = getattr(self, "_ls_prev", None)
            _lc = getattr(self, "_ls_cur", None)
            if _lp is not None and _lc is not None and _lc > _lp:
                lt = _lc - _lp
        sec1 = s1
        sec2 = (s2sum - s1) if s2sum and s1 else None
        sec3 = (lt - s2sum) if (lt > 0 and s2sum) else None
        if sec3 is not None and sec3 < 0:
            sec3 = None                        # niente settori negativi spazzatura
        carc = d.get("tyre_carcass") or [None] * 4
        surf = d.get("tyre_surf") or [None] * 4
        inner = d.get("tyre_inner") or [None] * 4
        press = d.get("tyre_press") or [None] * 4
        wear = d.get("tyre_wear") or [None] * 4
        brk = d.get("brake_temp") or [None] * 4
        row = {"lap": lap, "stint": self._file_stint,
               "lap_time": lt, "s1": sec1, "s2": sec2, "s3": sec3,
               "invalid": 1 if d.get("lap_invalid") else 0,
               "fuel_used": self._delta(self._lap_start_fuel, d.get("fuel")),
               "ve_used": self._delta(self._lap_start_ve, d.get("ve_pct")),
               "fuel_end": d.get("fuel"), "ve_end": d.get("ve_pct"),
               "regen_gain_kwh": self._lap_regen_pos, "boost_kwh": self._lap_boost,
               "soc_start": self._lap_soc_start, "soc_end": d.get("soc")}
        # posizione DI CLASSE al completamento del giro (dal rivals cache)
        try:
            row["pos"] = int((getattr(self, "_riv_cache", None) or {}).get("class_place") or 0) or None
        except (TypeError, ValueError):
            row["pos"] = None
        try:
            # frazione del GIRO passata con le ruote sull'asfalto BAGNATO
            # (mSurfaceType per ruota a 64Hz): la telemetria sotto le gomme.
            _wt = getattr(self, "_lap_wet_ticks", 0)
            _tt = getattr(self, "_lap_surf_ticks", 0)
            row["wet_max"] = (float(_wt) / float(_tt)) if _tt > 0 else None
        except (TypeError, ValueError, ZeroDivisionError):
            row["wet_max"] = None
        keys = ("fl", "fr", "rl", "rr")
        for i, k in enumerate(keys):
            row["t_" + k] = carc[i]
            row["ts_" + k] = self._mean3(surf[i])
            row["ti_" + k] = self._mean3(inner[i])
            row["p_" + k] = press[i]
            row["w_" + k] = wear[i]
            row["b_" + k] = brk[i]
        # PISTA del giro: dichiarazione NETTA WET/DRY da LMU mSurfaceType (asfalto
        # sotto le gomme: 0=asciutto, 1=bagnato). Unica fonte per tempi/REF/stint.
        _rain = d.get("raining")
        _wetp = d.get("wetness")
        row["air_temp"] = d.get("air_temp")
        row["track_temp"] = d.get("track_temp")
        row["wetness"] = _wetp
        row["wetness_min"] = getattr(self, "_lap_wmin", None)   # scia
        row["wetness_max"] = getattr(self, "_lap_wmax", None)   # fuori scia
        row["rain_pct"] = (float(_rain) * 100.0) if _rain is not None else None
        row["declared_wet"] = _db.declared_wet_from_surface(d.get("surface_type"))
        # MESCOLA del giro (per-stint): congela la gomma montata in questo giro
        # (4 ruote dal reader), così al pit lo stint precedente mantiene la sua.
        row["compounds4"] = ",".join(d.get("tyre_compound4") or []) or None
        self._db.add_lap(row)
        self._stint_lap_count += 1
        # auto-reference: se il giro è valido e batte il record (classe+pista+CONDIZIONE)
        if not d.get("lap_invalid") and lt and lt > 0:
            try:
                self._db.flush()              # committa samples del giro per lo snapshot
                # condizione = GOMMA montata (wet -> WET), non la superficie:
                # in gara wet con linea che asciuga, la superficie dava DRY e il
                # giro wet veniva confrontato col record DRY (slick, piu' veloce)
                # -> perdeva -> il best WET non veniva mai caricato online.
                # Fallback alla superficie solo se la gomma non e' nota.
                _l4 = [str(x).strip() for x in (d.get("tyre_compound4") or []) if x]
                if _l4:
                    _dw = 1.0 if _l4[0].upper().startswith("W") else 0.0
                else:
                    _dw = _db.declared_wet_from_surface(d.get("surface_type")) or 0.0
                _newref = _db.update_reference_if_better(
                    self._db._con, lap, d.get("car_class"), d.get("track"), _dw)
                if _newref:                   # nuovo best salvato -> condividi online
                    self._upload_online_best(d, lt, sec1, sec2, sec3, wear)
            except Exception:
                pass

    def _upload_online_best(self, d, lt, sec1, sec2, sec3, wear):
        """Invia il best appena salvato al Worker (POST /ref, async). Stessa
        chiave della lettura: CLASSE_pista_DRY|WET. Degrada in sicurezza."""
        try:
            from core import online
            from core.classes import class_tag
        except Exception:
            return
        c4 = ""; fmax = None
        try:
            r = self._db._con.execute(
                "SELECT compounds4, fuel_max FROM session_meta WHERE id=1").fetchone()
            if r:
                c4 = (r[0] or ""); fmax = r[1]
        except Exception:
            pass
        # GOMME DEL GIRO, non della sessione: session_meta tiene la mescola
        # d'inizio sessione — su pista che cambia (wet->dry o viceversa)
        # finivano le WET in classifica DRY e il contrario. La verita' e'
        # la mescola montata ORA, a fine giro (stessa fonte della riga giro).
        _live4 = [str(x).strip() for x in (d.get("tyre_compound4") or []) if x]
        if len(_live4) == 4:
            c4 = ",".join(_live4)
        four = [x.strip() for x in c4.split(",") if x.strip()]
        single = four[0] if (four and all(x == four[0] for x in four)) else None
        # DRY/WET dalla GOMMA MONTATA a fine giro, non dalla superficie: un giro
        # su WET va in classifica WET anche se LMU dichiara la pista asciutta
        # (e viceversa). Fallback alla superficie solo se la gomma non e' nota.
        if four:
            wet = str(four[0]).strip().upper().startswith("W")
        else:
            wet = bool(_db.declared_wet_from_surface(d.get("surface_type")))
        # TRACK dall'_evt_track CONFERMATO della sessione (non da d['track']
        # live: mTrackName scoring lagga dopo un cambio pista/sessione -> un
        # giro fatto a Silverstone National finiva su 'Monza' stantìo e
        # sporcava la leaderboard di TUTTI). _evt_track e' l'ancora con cui il
        # giro e' stato accettato/registrato, quindi coerente col file DB.
        _sub_track = getattr(self, "_evt_track", None) or d.get("track") or ""
        key = online.make_key(class_tag(d.get("car_class") or ""),
                              _db._short_track(_sub_track), wet)
        if not key:
            return
        ws = [x for x in (wear or []) if x is not None]
        state = (sum(ws) / len(ws)) if ws else None
        fuel_pct = None
        fu = d.get("fuel")
        if fu is not None and fmax:
            try:
                fuel_pct = fu / fmax * 100.0
            except Exception:
                fuel_pct = None
        team = None
        try:
            import json
            from core.paths import PROFILE_FILE as _pf    # SOLO profilo utente (APPDATA)
            if _pf.exists():
                team = (json.loads(_pf.read_text(encoding="utf-8")).get("team") or None)
        except Exception:
            team = None
        payload = {
            "key": key,
            "lap_ms": int(round(lt * 1000)),
            "s1_ms": int(round(sec1 * 1000)) if sec1 else None,
            "s2_ms": int(round(sec2 * 1000)) if sec2 else None,
            "s3_ms": int(round(sec3 * 1000)) if sec3 else None,
            "car": d.get("vehicle"),
            "compound": single,
            "compounds4": c4 or None,
            "tyre_state_pct": state,
            "ve_pct": d.get("ve_pct"),
            "fuel_pct": fuel_pct,
            "fuel_l": self._lap_start_fuel,
            "session_type": d.get("session_type"),
            "team": team,
            "player": d.get("driver"),
            "game_ver": d.get("game_ver"),
        }
        online.submit_async(payload)

    def _player_num(self):
        """Numero mostrato sul dot = posizione in classe del pilota (come il
        widget mappa). Calcolato una volta alla creazione del file."""
        try:
            sim = self._mem._get_sim()
            si = sim.scoring.scoringInfo
            from pyLMUSharedMemory.lmu_data import MAX_MAPPED_VEHICLES as _MAX
            from core.classes import class_tag
            n = int(si.mNumVehicles)
            counter = {}
            pnum = ""
            for i in range(min(n, _MAX)):
                v = sim.scoring.vehScoringInfo[i]
                cls = bytes(v.mVehicleClass).split(b"\x00")[0].decode("utf-8", "ignore")
                tag = class_tag(cls)
                counter[tag] = counter.get(tag, 0) + 1
                if bool(v.mIsPlayer):
                    pnum = str(counter[tag])
            return pnum
        except Exception:
            return ""

    @staticmethod
    def _mean4(v):
        xs = [x for x in (v or []) if x is not None]
        return sum(xs) / len(xs) if xs else None

    @staticmethod
    def _mean3(v):
        if not v:
            return None
        xs = [x for x in v if x is not None]
        return sum(xs) / len(xs) if xs else None

    @staticmethod
    def _delta(a, b):
        if a is None or b is None:
            return None
        return a - b

    # ── per il widget ──────────────────────────────────────────────────
    def latest(self):
        with self._lock:
            return dict(self._latest)
