"""engineer/radio.py — gestore radio del muretto.

Coda a PRIORITÀ (tier), cadenza minima, mutua esclusione per gruppo, scadenza
(TTL) dei messaggi vecchi, e PREEMPTION della GIALLA (taglia il messaggio in
corso e lo RIACCODA, poi parla la gialla). Un messaggio alla volta.

Portato fedele dal gestore radio della v2 (engineer_overlay.push_msgs /
_radio_tick). I moduli producono candidati (già passati dal sanity_filter); qui
si decide COSA dire e QUANDO.
"""
import time

from engineer.roles import voice_for, role_for, ROLE_LABEL


def _write_team_radio(role, text):
    """Scrive il messaggio corrente in USER_DIR/team_radio.json: ponte per il
    futuro overlay grafico WEC (text-less), che leggerà chi parla. Difensivo."""
    try:
        import json
        from core.paths import USER_DIR
        (USER_DIR / "team_radio.json").write_text(
            json.dumps({"t": time.time(), "role": role, "text": text or ""},
                       ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

# ── tier di priorità: 0 = sicurezza (passa sempre) … 4 = coaching ─────────
_MSG_TIER = {}


def _mk(codes, tier):
    for c in codes:
        _MSG_TIER[c] = tier


# P0 sicurezza: box gravi, gialla, surriscaldi critici, benzina/energia finita
_mk(["box_wheel", "box_aero", "box_susp", "box_body", "box_s2", "box_now",
     "box_last", "box_retire", "tyres_over", "brakes_over", "engine_over",
     "yellow_flag", "yellow_sector", "fuel_short", "box_flat", "box_penalty",
     "box_tyre_dead", "box_tyre", "rain_box_now", "rain_box_pace", "local_yellow",
     "retire_race", "retire_practice", "retire_quali", "driver_check",
     "limits_review", "limits_review_lap", "limits_review_pos",
     "engine_stall", "engine_dead", "engine_restart",
     "stopped_check", "stopped_check_dmg",
     "pit_release_wait", "pit_release_clear", "garage_wrong_tyre"], 0)
# TRACK LIMITS esiti/conteggi: importanti ma non da preemption
_mk(["limits_clear", "limits_warning", "limits_warning_n", "tlimits_lap", "tlimits_warn",
     "tlimits_pen", "tlimits_warn_where", "tlimits_pen_where",
     "tlimits_repeat"], 2)
# P1 strategia / meteo / briefing (devono essere detti)
_mk(["ready", "briefing_strat", "briefing_laps", "briefing_save", "plan",
     "plan_hist", "learn_prov", "pit_window", "fuel_laps", "energy_laps",
     "rain_now", "drying", "rain_in", "tyre_wet", "tyre_dry", "briefing_plan",
     "strat_normal", "strat_save", "strat_nostop", "plan_wx_arc",
     "plan_model_stops", "plan_model_stint", "plan_tyre_stock",
     "plan_tyre_short", "plan_compound", "plan_prelim", "rain_early",
     "rain_window", "dry_early", "dry_window", "dry_save", "dry_late",
     "rain_save", "rain_late", "rain_clear", "box_damage", "box_tyre_worn",
     "rain_starting", "rain_fc", "rain_fc_now", "rain_fc_end", "rain_fc_wet_end",
     "rain_fc_wet_all", "wet_stay_end", "wet_fuel", "wet_fuel_end", "tyre_short",
     "tyre_manage", "tyre_rain_nomanage", "strat_extra_yes", "strat_extra_no",
     "strat_extra_free", "plan_nostop", "plan_stops", "plan_stops_solo",
     "plan_eco_save", "plan_eco_stint", "yellow_pit", "green_restart",
     "wet_patchy", "wet_tyre_hot", "wet_tyre_cold", "rain_dryline",
     "gap_undercut", "gap_pit_called", "pit_ack", "pit_ack_fuel",
     "wet_manage_choice", "advise_slick", "advise_wet", "session_end",
     "chk_over", "chk_push", "chk_ok"], 1)
# BLU: SICUREZZA, appena sotto la gialla — auto veloce che ti sta per
# doppiare: chiamata REATTIVA, va detta subito e mai scartata come info gara.
# Promossa a P0 (era P1, restava sepolta dietro strategia/briefing). Rich. utente.
_mk(["blue_flag", "blue_flag_multi", "blue_flag_simple", "blue_flag_train"], 0)
# PRE-BLU (classe veloce in arrivo, prima della flag del gioco): P1 —
# era senza tier (=P4 coaching) e arrivava in super ritardo o mai.
_mk(["fast_class_close", "fast_class_now"], 1)
# Semaforo pit (prova/quali) + conferma pit pronta + briefing box: detti, ma
# SOTTO il safe-release (P0) -> il briefing si accoda e lo senti in out-lap.
_mk(["pit_closed", "pit_open", "pit_ready", "tyre_stock", "garage_brief",
     "garage_prep", "garage_prep_go", "garage_out_new_cold",
     "garage_out_new_warm", "garage_out_used_cold", "garage_out_used_warm",
     "session_time_up"], 1)
# benvenuto + finale a tre voci (v2): detti, non scartabili come info
_mk(["brief_spot", "fin_eng_good", "fin_eng_ok", "fin_strat_good",
     "fin_strat_ok", "fin_spot_good", "fin_spot_ok"], 1)
# MODALITA' TEST dal dash: attivazioni P1 (ack immediato), check P2
_mk(["longrun_on", "longrun_on_nodata", "racesim_on", "racesim_on_nodata",
     "hotlap_on", "test_off", "eco_on", "eco_on_nodata", "eco_off"], 1)
_mk(["test_over", "test_margin", "test_good",
     "hotlap_loss", "hotlap_clean"], 2)
# P2 stato vettura + check consumi
_mk(["tyres_cold", "tyres_warm", "brakes_cold", "tyres_hot", "brakes_hot",
     "aero_light", "aero_bad", "susp_light", "susp_bad", "damage_body",
     "tyre_flat", "engine_hot", "status_dry", "status_wet", "status_fuel",
     "status_tyre", "sector_loss", "wet_sector", "fuel_practice",
     "tyre_worn_info", "contact_who", "contact_ok_who", "contact_ok",
     "contact_where", "contact_where_who",
     "quali_pole_gap", "quali_pole_lead", "quali_top5", "overtake_done",
     "debrief_stint", "debrief_sectors", "debrief_tyre", "debrief_improve",
     "debrief_balance_us", "debrief_balance_os", "debrief_wear_wheel",
     "debrief_press_hi", "debrief_press_lo", "debrief_camber_much",
     "debrief_camber_little", "debrief_brake_front", "debrief_brake_rear",
     "debrief_bottoming", "debrief_aero_bal",
     "debrief_wear_wheel_corner", "debrief_brake_corner",
     "flatspot_confirmed",
     "lap_time_call"], 2)
# P3 info gara
_mk(["leader", "pole_pos", "pos_race", "pos_qualy", "pos_lead", "pos_pole",
     "near_ahead", "near_behind", "opp_best", "time_left", "time_hours",
     "laps_left", "last_lap", "last_min",
     "traffic_ahead", "ahead_pit", "gap_both", "gap_ahead",
     "gap_behind", "gap_closing", "pos_gain", "pos_loss", "best_lap_new",
     "batt_info", "lap_fast", "lap_fast_clean", "lap_slow", "perf_report",
     "grip_status", "grip_up", "grip_down",
     "gap_attack", "gap_attack_simple", "gap_defend", "gap_defend_simple"], 3)
# contatto+danno: il verdetto post-impatto parla presto
_mk(["contact_damage", "contact_damage_who", "contact_ok_dmgd"], 2)
# ruota piegata (assetto storto dal trace): informazione danni, presto
_mk(["wheel_bent", "wheel_bent_bad"], 2)
# causa ritiro certificata dal trace (motore/telaio morto): P1
_mk(["retire_engine", "retire_susp", "retire_accident"], 1)
# coaching guida "caldo" (scivolate, spiattellamento, cordoli, out-lap): P2
_mk(["car_sliding", "flatspot_check", "kerb_zone_corner", "kerb_zone",
     "outlap_gt3", "outlap_hy", "outlap_p2", "outlap_p3",
     "coast_corner"], 2)
# CANTIERE 2: salute macchina subito (P2), coaching/energia P3
_mk(["brake_fade", "press_high", "press_low", "tyre_glaze",
     "diffuser_stall", "power_clip", "camber_spread",
     "tl_corner", "tl_corner_again"], 2)
_mk(["grip_margin", "grip_over", "abs_high", "tc_high", "ve_burn",
     "dirty_air", "opp_fading", "timeloss_focus", "brake_potential",
     "coast_waste", "brake_release_dirty", "gas_earlier"], 3)
_mk(["grip_loss"], 2)
_mk(["engine_suffer"], 0)
_mk(["penalty_sg", "penalty_sg_nolaps", "penalty_dt",
     "penalty_sg2", "penalty_time", "penalty_boxcall_sg",
     "penalty_boxcall_dt"], 0)
_mk(["penalty_served"], 1)
_mk(["bias_ack"], 2)
_mk(["adv_bias_back", "adv_bias_fwd", "adv_wing_front", "adv_wing_less",
     "setup_garage_front", "setup_garage_rear"], 3)
# default 4 = coaching (passo, settori, note curva)

_TIER_TTL = {0: 999, 1: 30, 2: 12, 3: 8, 4: 10}
_RADIO_MIN_GAP = 5.0       # secondi tra due messaggi non critici
_RADIO_NO_REPEAT = 20.0    # non ripetere la stessa frase entro N secondi
_GROUP_GAP = 8.0           # un solo messaggio per gruppo entro N secondi
# gruppi "monologo" (strategia/meteo): UNA frase e stop, niente disco
# rotto — si riparla dell'argomento solo dopo minuti (i critici P0
# passano sempre: il tier 0 non e' mai deduplicato). Richiesta utente.
_GROUP_GAP_BY = {"strategia": 180.0, "pioggia": 180.0,
                 "consumi": 90.0, "gomme": 90.0,
                 "test": 40.0}
_YELLOW = ("local_yellow", "yellow_flag", "yellow_sector")
# cosa TAGLIA il messaggio in corso: gialle + il safe-release "aspetta" (auto in
# arrivo mentre esci dal box) -> deve passare subito, non dopo il briefing.
# anche la BLU taglia il parlato in corso: reattiva (richiesta utente),
# arrivava a fine frase = super ritardo
_PREEMPT = _YELLOW + ("pit_release_wait", "blue_flag", "blue_flag_multi",
                      "blue_flag_simple", "blue_flag_train")
# Tono SENZA ritardo (subito dopo il beep): gialle + blu (urgenza) e pit_ready
# (i suoi 3s sono gia' l'attesa; il ritardo tono NON deve sommarsi). Richiesta utente.
_URGENT_TONE = _YELLOW + ("blue_flag", "blue_flag_multi", "blue_flag_simple",
                          "blue_flag_train", "pit_ready", "pit_open",
                          "pit_release_wait", "pit_release_clear")

# ── gruppi di mutua esclusione (la sicurezza tier 0 non è mai deduplicata) ─
_MSG_GROUP = {}


def _grp(codes, g):
    for c in codes:
        _MSG_GROUP[c] = g


_grp(["chk_over", "chk_push", "chk_ok", "status_fuel", "status_dry",
      "fuel_practice", "fuel_laps", "energy_laps"], "consumi")
_grp(["tyre_manage", "tyre_rain_nomanage", "tyre_short", "box_tyre_worn",
      "status_tyre", "strat_extra_yes", "strat_extra_no", "strat_extra_free",
      "tyre_worn_info", "flatspot_check"], "gomme")
_grp(["rain_starting", "rain_fc", "rain_fc_now", "rain_fc_end", "rain_fc_wet_end",
      "rain_fc_wet_all", "wet_stay_end", "rain_early", "rain_window", "dry_early",
      "dry_window", "dry_save", "dry_late", "rain_save", "rain_late", "rain_clear",
      "advise_wet", "advise_slick", "rain_dryline", "wet_manage_choice",
      "wet_patchy", "wet_sector", "wet_tyre_hot", "wet_tyre_cold"], "pioggia")
_grp(["tyres_cold", "tyres_warm", "brakes_cold", "tyres_hot", "brakes_hot"], "temp")
_grp(["test_over", "test_margin", "test_good",
      "hotlap_loss", "hotlap_clean"], "test")
_grp(["plan", "plan_hist", "plan_nostop", "plan_stops", "plan_stops_solo",
      "plan_eco_save", "plan_eco_stint", "plan_wx_arc", "plan_model_stops",
      "plan_model_stint", "plan_tyre_stock", "plan_tyre_short",
      "plan_compound", "plan_prelim", "briefing_plan", "briefing_laps",
      "briefing_strat", "briefing_manage", "briefing_push", "briefing_save",
      "strat_normal", "strat_save", "strat_nostop"], "strategia")


def tier_of(code):
    return _MSG_TIER.get(code, 4)


class RadioManager:
    """Coda radio: accoda i candidati, poi `tick()` decide cosa dire e quando."""

    def __init__(self):
        self._q = []
        self._said = {}          # testo -> ultimo istante detto
        self._group_said = {}    # gruppo -> ultimo istante servito
        self._last = 0.0         # ultimo messaggio non critico
        self._cur = None         # messaggio in bocca ora (per la preemption)

    def reset(self):
        """Svuota la coda e il messaggio in bocca (es. all'ingresso in pausa/
        menu): il muretto NON deve continuare frasi fuori sessione."""
        self._q = []
        self._cur = None

    def push(self, msgs):
        """Accoda i candidati: salta doppioni, frasi dette da poco, e gruppi
        già serviti (tier>=1)."""
        now = time.monotonic()
        qtexts = {x["m"].get("text") for x in self._q}
        for m in msgs or []:
            if not m:
                continue
            t = m.get("text", "")
            if not t or t in qtexts:
                continue
            ls = self._said.get(t)
            if ls and (now - ls) < _RADIO_NO_REPEAT:
                continue
            tier = _MSG_TIER.get(m.get("code"), 4)
            grp = _MSG_GROUP.get(m.get("code"))
            if tier >= 1 and grp:
                gs = self._group_said.get(grp)
                if gs and (now - gs) < _GROUP_GAP_BY.get(grp, _GROUP_GAP):
                    continue
            self._q.append({"m": m, "tier": tier, "ts": now})
            qtexts.add(t)

    def tick(self, vox, lang):
        """Sceglie il messaggio a priorità più alta e lo manda alla voce, uno
        alla volta. La GIALLA taglia il messaggio in corso e lo riaccoda."""
        now = time.monotonic()
        if self._cur is not None and not vox.busy():
            self._cur = None                    # ha finito di parlare
        # scadenza: i messaggi vecchi e inutili spariscono (tier 0 mai)
        self._q = [x for x in self._q
                   if x["tier"] == 0 or now - x["ts"] <= _TIER_TTL[x["tier"]]]
        if not self._q:
            return
        self._q.sort(key=lambda x: (x["tier"], x["ts"]))
        top = self._q[0]
        busy = self._cur is not None or vox.busy()
        if busy:
            cur = self._cur
            cur_t0 = _MSG_TIER.get((cur or {}).get("code"), 4) == 0
            # solo GIALLA/safe-release (e solo se il corrente non è già
            # sicurezza) preempta -> il briefing tagliato si riaccoda e lo senti dopo
            if not (top["m"].get("code") in _PREEMPT and not cur_t0):
                return
            # riaccoda SOLO se tagliato SUBITO (< 0.8s): se l'hai gia' sentito
            # quasi tutto, scartalo -> niente ripetizione imbarazzante del briefing
            if cur and (now - self._last) < 0.8:
                ct = cur.get("text")
                if ct:
                    self._said.pop(ct, None)
                cg = _MSG_GROUP.get(cur.get("code"))
                if cg:
                    self._group_said.pop(cg, None)
                self._q.append({"m": cur,
                                "tier": _MSG_TIER.get(cur.get("code"), 4),
                                "ts": now})
            vox.interrupt()
            self._cur = None
        # cadenza: critico subito, gli altri rispettano il gap minimo
        if top["tier"] == 0 or (now - self._last) >= _RADIO_MIN_GAP:
            self._q.remove(top)
            self._last = now
            m = top["m"]
            self._said[m.get("text")] = now
            g = _MSG_GROUP.get(m.get("code"))
            if g:                               # servito il gruppo: scarta gli altri
                self._group_said[g] = now
                self._q = [x for x in self._q
                           if not (x["tier"] >= 1
                                   and _MSG_GROUP.get(x["m"].get("code")) == g)]
            self._said = {k: v for k, v in self._said.items() if now - v < 120}
            self._cur = m
            code = m.get("code")
            role = role_for(code)
            print("[%s] %s" % (ROLE_LABEL.get(role, role), m.get("text")))
            _write_team_radio(role, m.get("text"))   # ponte per la futura grafica WEC
            # lo spotter (lei) un filo piu' alta: bandiere/gap sempre ben udibili
            _vol = "+22%" if role == "spotter" else None
            vox.speak(m.get("text"), voice=voice_for(code, lang),
                      beep=bool(m.get("beep")), vol=_vol,
                      urgent=(code in _URGENT_TONE))
