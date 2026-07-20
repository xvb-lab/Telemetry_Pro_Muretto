"""Entry point del MURETTO — processo separato.

Mette insieme la catena: dati LMU (core.reader + core.strategy) -> cervello
(engineer.brain.Engineer) -> voce (core.voice), coi 3 ruoli/voci
(engineer.roles). Parlato-only.

Uso:
  python -m engineer.run_engineer          # loop live (legge LMU in sessione)
  python -m engineer.run_engineer --demo   # simulazione: fa parlare la
                                            # strategia senza essere in pista
"""
import sys
import time
from pathlib import Path

from core.reader import TelemetryReader
from core.strategy import StrategyFeed
from core.shared_memory import SharedMemory
from core.voice import Voice
from core import engineer_cfg
from engineer.brain import Engineer
from engineer.roles import voice_for, role_for, ROLE_LABEL

_BEEP = Path(__file__).resolve().parent.parent / "assets" / "audio" / "radio.mp3"


def _apply_cfg(vox, cfg):
    """Applica le opzioni (volume voce, beep on/off, ritardo tono) alla voce.
    Chiamata all'avvio e periodicamente, così i cambi dalle Opzioni si sentono
    senza riavviare l'ingegnere."""
    try:
        vox.set_volume(int(cfg.get("voice_vol", 100)))
    except Exception:
        pass
    try:
        vox.set_beep(str(_BEEP) if _BEEP.exists() else None,
                     bool(cfg.get("beep_on", True)))
    except Exception:
        pass
    try:
        vox.set_tone_delay(float(cfg.get("beep_delay_s", 2.0)))
    except Exception:
        pass


def _speak(vox, msgs, lang, seen):
    """Manda i messaggi alla voce col voce-per-ruolo. Salta vuoti e ripetizioni
    immediate identiche (l'anti-ripetizione vera e' nel cervello)."""
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        code = m.get("code")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if seen.get("last") == (code, text):
            continue
        seen["last"] = (code, text)
        role = role_for(code)
        print("[%s] %s" % (ROLE_LABEL.get(role, role), text))
        vox.speak(text, voice=voice_for(code, lang), beep=bool(m.get("beep")))


def _emit_all(vox, brain, raw, ld, pace, lang, seen):
    """Chiama i moduli-voce collaudati del cervello e manda a voce ciò che
    producono. Ognuno è difensivo (torna [] se manca il dato) e protetto da
    try/except: un modulo che sbaglia NON ferma il muretto. I moduli senza il
    dato necessario restano muti finché il glue non fornisce quel dato."""
    mods = (
        # 🟠 RACE ENGINEER — sicurezza / auto
        (brain.flags_call, (raw,)),
        (brain.damage_call, (raw,)),
        (brain.aero_call, (raw,)),
        (brain.contact_call, (raw,)),
        (brain.engine_check, (raw,)),
        (brain.battery_check, (raw, ld)),
        (brain.wet_tyre, (raw,)),
        (brain.pit_ack, (raw, ld)),
        # 🔵 STRATEGY
        (brain.race_plan, (raw,)),
        (brain.box_call, (raw, ld)),
        (brain.strategy_check, (raw, pace, ld)),
        (brain.weather_check, (raw, ld)),
        (brain.strat_extra_stop, (raw, ld)),
        (brain.status_update, (raw, ld)),
        (brain.autofuel_call, (raw, ld)),
        (brain.position_strategy, (raw, ld)),
        (brain.pos_call, (raw,)),
        (brain.countdown, (raw, ld)),
        # 🟢 PERFORMANCE / spotter
        (brain.lap_time_call, (raw,)),
        (brain.lap_feedback, (raw, ld)),
        (brain.tyre_life, (raw, ld)),
        (brain.grip_call, (raw, ld)),
        (brain.temp_call, (raw, ld)),
        (brain.gap_call, (raw, ld)),
        (brain.traffic_ahead_call, (raw,)),
        (brain.lock_pattern_call, (raw, ld)),
        (brain.pace_notes_call, (raw, ld)),
        (brain.tlimits_call, (raw, ld)),
        (brain.rain_live, (raw, ld)),
        (brain.wet_patches, (raw,)),
    )
    for fn, args in mods:
        try:
            _speak(vox, fn(*args), lang, seen)
        except Exception:
            pass


def _lang():
    return (engineer_cfg.load().get("lang") or "it")


# ─────────────────────────────────────────────────────────────────────────
#  LOOP LIVE
# ─────────────────────────────────────────────────────────────────────────
def run():
    lang = _lang()
    reader = TelemetryReader()
    feed = StrategyFeed()
    feed.start()
    mem = SharedMemory.instance()
    vox = Voice(lang=lang)
    _apply_cfg(vox, engineer_cfg.load())      # volume/beep/ritardo dalle Opzioni
    brain = Engineer(lang=lang)
    brain.new_session()
    seen = {}
    print("[muretto] loop live avviato (lang=%s). In attesa di una sessione LMU..."
          % lang)
    _last_class = None
    _cfg_ts = 0.0
    try:
        while True:
            _now = time.monotonic()
            if _now - _cfg_ts > 2.0:         # opzioni live (volume/beep/ritardo)
                _apply_cfg(vox, engineer_cfg.load())
                _cfg_ts = _now
            d = reader.read()
            if not d:
                time.sleep(0.5)              # LMU nei menu / fuori sessione
                continue
            drv = d.get("driver") or ""
            ld = int(d.get("laps_completed") or 0)
            feed.set_context(drv, ld)
            cls = d.get("car_class")
            if cls and cls != _last_class:
                _last_class = cls
                brain.set_class(cls)
            est = float(d.get("est_lap") or d.get("best_lap") or 0.0)
            live = feed.lmu_live(d, est)
            # raw per il cervello: fisica + blocco strategia
            raw = dict(d)
            raw["ts"] = time.monotonic()
            raw["on_track"] = True
            raw["lmu_live"] = live
            if live:
                raw["lmu_per_lap"] = live.get("per_lap")
                raw["lmu_strat"] = {
                    "constraint": live.get("constraint"),
                    "fuel_max": live.get("fuel_max"),
                    "fuel_cur": live.get("fuel_l"),
                    "per_lap": live.get("per_lap"),
                    "pit_target": live.get("pit_target"),
                    "autonomy": live.get("autonomy_laps"),
                }
            # SCORING dalla shared memory -> attiva bandiere/gap/traffico/posizioni
            try:
                _fl = mem.flags()
                if _fl:
                    raw["flags"] = _fl
                    raw["checkered"] = _fl.get("checkered")
                    raw["penalties"] = _fl.get("num_penalties")
                _rv = mem.rivals()
                if _rv:
                    raw["rivals"] = _rv
                _nc = mem.nearest_car()
                if _nc:
                    raw["nearest_car"] = _nc
            except Exception:
                pass
            # tick strappato (dato incoerente) -> salta
            try:
                if brain.glitch(raw):
                    time.sleep(0.2)
                    continue
            except Exception:
                pass
            # fotografia stato PRIMA di tutto (state-aware), poi tutti i moduli
            try:
                brain.update_situation(raw)
            except Exception:
                pass
            _emit_all(vox, brain, raw, ld, est or None, lang, seen)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        feed.stop()
        reader.stop()


# ─────────────────────────────────────────────────────────────────────────
#  DEMO — fa parlare la strategia senza pista (valida tutta la catena)
# ─────────────────────────────────────────────────────────────────────────
def demo():
    lang = _lang()
    vox = Voice(lang=lang)
    brain = Engineer(lang=lang)
    brain.new_session()
    brain.set_class("LMGT3")
    seen = {}
    # GT3: serbatoio 119, carico 98, 1.74 L/giro, giro 54.8s, gara ~96 giri
    raw0 = {"session_type": 10, "track": "TEST SIM", "driver": "Jona",
            "max_laps": 2147483647, "est_lap": 54.8, "best_lap": 54.8,
            "race_total": 5260.0, "race_remaining": 5260.0,
            "lmu_per_lap": 1.74,
            "lmu_strat": {"constraint": "FUEL", "fuel_max": 119.0,
                          "fuel_cur": 98.0, "per_lap": 1.74,
                          "autonomy": 56, "fulltank": 68},
            "forecast_rain": [0, 0, 10, 90, 100], "raining": 0.0}
    print("[muretto] DEMO — briefing di gara:")
    try:
        brain.update_situation(raw0)
    except Exception:
        pass
    _speak(vox, brain.race_plan(raw0), lang, seen)
    time.sleep(7)
    fuel = 98.0
    for lap in range(1, 13):
        per = 1.95 if lap <= 4 else (1.74 if lap <= 8 else 1.55)
        fuel -= per
        raw = dict(raw0, laps_completed=lap, lmu_per_lap=per)
        raw["race_remaining"] = max(0.0, 5260.0 - lap * 54.8)
        raw["lmu_strat"] = dict(raw0["lmu_strat"], fuel_cur=fuel)
        _speak(vox, brain.strategy_check(raw, 54.8, lap), lang, seen)
        time.sleep(3)
    print("[muretto] DEMO finita")


def main():
    if "--demo" in sys.argv:
        demo()
    else:
        run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
