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

from core.reader import TelemetryReader
from core.strategy import StrategyFeed
from core.voice import Voice
from core import engineer_cfg
from engineer.brain import Engineer
from engineer.roles import voice_for, role_for, ROLE_LABEL


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
        vox.speak(text, voice=voice_for(code, lang))


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
    vox = Voice(lang=lang)
    brain = Engineer(lang=lang)
    brain.new_session()
    seen = {}
    print("[muretto] loop live avviato (lang=%s). In attesa di una sessione LMU..."
          % lang)
    _last_class = None
    try:
        while True:
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
            # cervello: fotografia stato, poi moduli strategia
            try:
                brain.update_situation(raw)
            except Exception:
                pass
            _speak(vox, brain.race_plan(raw), lang, seen)
            _speak(vox, brain.strategy_check(raw, est or None, ld), lang, seen)
            _speak(vox, brain.box_call(raw, ld), lang, seen)
            _speak(vox, brain.countdown(raw, ld), lang, seen)
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
