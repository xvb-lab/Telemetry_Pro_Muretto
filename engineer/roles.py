"""engineer/roles.py — i 3 ruoli radio e le loro voci.

Ogni codice-messaggio appartiene a un ruolo (RACE / STRATEGY / PERFORMANCE);
ogni ruolo ha una voce edge-tts per lingua (3 voci x 4 lingue = 12). Tabella
portata INVARIATA dal vecchio engineer_overlay.py (collaudata).

Regola: un codice senza ruolo assegnato parla come RACE ENGINEER (default).
"""

# ── codice-messaggio -> ruolo ────────────────────────────────────────────
_MSG_ROLE = {}


def _role(codes, r):
    for c in codes:
        _MSG_ROLE[c] = r


_role(["gap_ahead", "gap_behind", "gap_both", "gap_undercut", "blue_flag",
       "blue_flag_multi", "blue_flag_simple", "traffic_ahead",
       "local_yellow", "yellow_flag", "yellow_pit"], "spotter")
_role(["brief_strat_data", "brief_strat_new"], "strategist")
_role(["brief_spot", "pit_exit_clean", "pit_exit_fast", "pit_exit_hole",
       "pit_exit_traffic"], "spotter")
_role(["lap_fast", "lap_fast_clean", "lap_slow", "sector_loss",
       "perf_report", "ref_pace", "under_pace", "on_pace", "pace_margin",
       "lap_time_call"], "spotter")
_role(["fin_strat_good", "fin_strat_ok"], "strategist")
_role(["fin_spot_good", "fin_spot_ok"], "spotter")
_role(["plan_nostop", "plan_stops", "plan_stops_solo", "plan_eco_save",
       "plan_eco_stint"], "strategist")
_role(["plan_wx_arc", "plan_model_stops", "plan_model_stint"], "strategist")
_role(["plan_tyre_stock", "plan_tyre_short", "plan_compound",
       "plan_prelim"], "strategist")
_role(["strat_extra_yes", "strat_extra_no", "rain_early", "rain_window",
       "dry_early", "dry_window", "dry_save", "dry_late", "rain_save",
       "rain_late", "rain_clear", "rain_fc", "rain_fc_now", "rain_fc_end",
       "rain_fc_wet_end", "rain_fc_wet_all"], "strategist")
# tutta la strategia operativa = voce STRATEGY (Diego/Christopher/Jorge/Jean)
_role([
    "box_now", "box_last", "box_s2", "box_tyre", "box_tyre_dead",
    "box_tyre_worn", "box_damage", "box_aero", "box_body", "box_susp",
    "box_flat", "box_wheel", "box_penalty", "box_retire", "box_anticipate",
    "box_delay", "chk_ok", "chk_over", "chk_push", "target_save", "save_stop",
    "manage_fuel", "briefing_save", "briefing_strat", "strat_normal",
    "strat_nostop", "strat_save", "strat_extra_free", "fuel_short",
    "fuel_laps", "status_fuel", "status_fuel_end", "pit_in", "pit_window",
    "pit_ack", "pit_ack_fuel", "rain_box_now", "rain_box_pace", "wet_fuel",
    "wet_fuel_end", "yellow_pit", "briefing_plan"
], "strategist")


def role_for(code):
    return _MSG_ROLE.get(code, "engineer")


# ── ruolo -> voce edge-tts per lingua (12 voci, collaudate) ───────────────
ROLE_VOICES = {
    "engineer":   {"it": "it-IT-GiuseppeNeural", "en": "en-GB-RyanNeural",
                   "es": "es-ES-AlvaroNeural",   "fr": "fr-FR-HenriNeural"},
    "strategist": {"it": "it-IT-DiegoNeural",    "en": "en-US-ChristopherNeural",
                   "es": "es-MX-JorgeNeural",     "fr": "fr-CA-JeanNeural"},
    "spotter":    {"it": "it-IT-IsabellaNeural", "en": "en-GB-SoniaNeural",
                   "es": "es-ES-ElviraNeural",    "fr": "fr-FR-DeniseNeural"},
}

ROLE_LABEL = {
    "engineer": "RACE ENGINEER",
    "strategist": "STRATEGY ENGINEER",
    "spotter": "PERFORMANCE ENGINEER",
}

ROLE_COLOR = {
    "engineer": "#e8802a",
    "strategist": "#45b4ef",
    "spotter": "#37d67a",
}


def voice_for(code, lang="it"):
    """Voce edge-tts per il codice-messaggio, nella lingua data."""
    role = role_for(code)
    lg = str(lang).lower()[:2]
    voices = ROLE_VOICES.get(role, ROLE_VOICES["engineer"])
    return voices.get(lg, voices["it"])
