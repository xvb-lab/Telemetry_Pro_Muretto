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


_role(["fast_class_close", "fast_class_now", "opp_penalty", "opp_slow",
       "gap_ahead", "gap_behind", "gap_both", "gap_undercut", "blue_flag",
       "blue_flag_multi", "blue_flag_simple", "blue_flag_train", "traffic_ahead",
       "local_yellow", "yellow_flag", "yellow_pit", "yellow_sector"], "spotter")
_role(["brief_strat_data", "brief_strat_new",
       "weather_dry", "weather_wet", "rain_box_pace",
       "briefing_save", "briefing_manage", "briefing_push",
       "garage_wrong_tyre", "tyre_stock"], "strategist")
_role(["brief_spot", "pit_exit_clean", "pit_exit_fast", "pit_exit_hole",
       "pit_exit_traffic", "pit_release_wait", "pit_release_clear"], "spotter")
_role(["contact_ok", "contact_who", "contact_ok_who",
       "contact_where", "contact_where_who", "driver_check",
       "contact_damage", "contact_damage_who",
       "wheel_bent", "wheel_bent_bad",
       "retire_engine", "retire_susp", "retire_accident"], "engineer")
_role(["gap_attack", "gap_attack_simple", "gap_defend",
       "gap_defend_simple"], "spotter")
_role(["lap_fast", "lap_fast_clean", "lap_slow", "sector_loss",
       "perf_report", "ref_pace", "under_pace", "on_pace", "pace_margin",
       "lap_time_call", "quali_pole_gap", "quali_pole_lead",
       "quali_top5", "overtake_done"], "spotter")
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


# MODALITA' TEST: piani/consumi = STRATEGY; giro secco = PERFORMANCE
_role(["longrun_on", "longrun_on_nodata", "racesim_on", "racesim_on_nodata",
       "test_over", "test_margin", "test_good", "test_off",
       "eco_on", "eco_on_nodata", "eco_off"], "strategist")
_role(["hotlap_on", "hotlap_loss", "hotlap_clean"], "spotter")


# CANTIERE 2 (23/07): findings pro. Salute macchina/assetto = RACE
# ENGINEER; guida e rivali = PERFORMANCE; energia = STRATEGY.
_role(["camber_spread", "tyre_glaze", "brake_fade", "diffuser_stall",
       "press_high", "press_low", "power_clip"], "engineer")
_role(["grip_margin", "grip_over", "abs_high", "tc_high", "dirty_air",
       "opp_fading", "timeloss_focus", "brake_potential", "coast_waste",
       "brake_release_dirty", "gas_earlier"], "spotter")
_role(["ve_burn", "grip_loss"], "strategist")
_role(["penalty_sg", "penalty_sg_nolaps", "penalty_served"], "engineer")
_role(["bias_ack", "adv_bias_back", "adv_bias_fwd", "adv_wing_front",
       "adv_wing_less", "setup_garage_front", "setup_garage_rear"],
      "engineer")


def role_for(code):
    return _MSG_ROLE.get(code, "engineer")


# ── ruolo -> voce edge-tts per lingua ─────────────────────────────────────
# FORMAZIONE 23/07 (provino con l'utente, voci Multilingual = modello
# nuovo, gratis come le vecchie): Florian ingegnere di gara (tedesco), Remy stratega (accento
# francese, Le Mans), Ava performance. Scambio provato 23/07.
# Le Multilingual parlano OGNI lingua: stessa voce su it/en/es/fr.
ROLE_VOICES = {
    "engineer":   {"it": "de-DE-FlorianMultilingualNeural",
                   "en": "de-DE-FlorianMultilingualNeural",
                   "es": "de-DE-FlorianMultilingualNeural",
                   "fr": "de-DE-FlorianMultilingualNeural"},
    "strategist": {"it": "fr-FR-RemyMultilingualNeural",
                   "en": "fr-FR-RemyMultilingualNeural",
                   "es": "fr-FR-RemyMultilingualNeural",
                   "fr": "fr-FR-RemyMultilingualNeural"},
    "spotter":    {"it": "en-US-AvaMultilingualNeural",
                   "en": "en-US-AvaMultilingualNeural",
                   "es": "en-US-AvaMultilingualNeural",
                   "fr": "en-US-AvaMultilingualNeural"},
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

# ── VOCI SELEZIONABILI dal menu Engineer (23/07, tutte edge-tts free).
# Le "multilingual" parlano OGNI lingua dell'app (ma su qualche parola
# possono scivolare nell'accento); le classiche sono madrelingua FISSE
# della loro lingua. (label, id) — id vuoto = titolare di ROLE_VOICES.
VOICE_CHOICES = [
    ("Default", ""),
    ("Florian (DE) — multilingual", "de-DE-FlorianMultilingualNeural"),
    ("Seraphina (DE) — multilingual", "de-DE-SeraphinaMultilingualNeural"),
    ("Remy (FR) — multilingual", "fr-FR-RemyMultilingualNeural"),
    ("Vivienne (FR) — multilingual", "fr-FR-VivienneMultilingualNeural"),
    ("Ava (US) — multilingual", "en-US-AvaMultilingualNeural"),
    ("Andrew (US) — multilingual", "en-US-AndrewMultilingualNeural"),
    ("Emma (US) — multilingual", "en-US-EmmaMultilingualNeural"),
    ("Brian (US) — multilingual", "en-US-BrianMultilingualNeural"),
    ("Giuseppe (IT)", "it-IT-GiuseppeNeural"),
    ("Diego (IT)", "it-IT-DiegoNeural"),
    ("Isabella (IT)", "it-IT-IsabellaNeural"),
    ("Christopher (EN-US)", "en-US-ChristopherNeural"),
    ("Guy (EN-US)", "en-US-GuyNeural"),
    ("Ryan (EN-GB)", "en-GB-RyanNeural"),
    ("Conrad (DE)", "de-DE-ConradNeural"),
    ("Henri (FR)", "fr-FR-HenriNeural"),
    ("Jean (FR-CA)", "fr-CA-JeanNeural"),
    ("Alvaro (ES)", "es-ES-AlvaroNeural"),
    ("Jorge (ES-MX)", "es-MX-JorgeNeural"),
]


def voice_for(code, lang="it"):
    """Voce edge-tts per il codice-messaggio, nella lingua data.
    L'utente puo' cambiare la formazione dal menu Engineer
    (engineer_cfg 'voices': {ruolo: voce}); vuoto = titolare."""
    role = role_for(code)
    try:
        from core.engineer_cfg import load as _ld_cfg
        _ov = (_ld_cfg().get("voices") or {}).get(role)
        if _ov:
            return _ov
    except Exception:
        pass
    lg = str(lang).lower()[:2]
    voices = ROLE_VOICES.get(role, ROLE_VOICES["engineer"])
    return voices.get(lg, voices["it"])
