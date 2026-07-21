# Muretto — mappa capacità (stato reale vs visione)

Verificato nel codice (0.3b). Legenda: ✅ c'è e wired · 🟡 parziale · ❌ manca
(spesso il MESSAGGIO c'è ma il modulo che lo fa scattare non è stato portato).

## Passo / tempi / posizione
| Capacità | Stato | Note |
|---|---|---|
| Tempo giro ogni giro (coi **decimali**) | ✅ | `lap_time_call`, `_fmt_lap_round` (decimale default on) |
| Posizione ogni giro | ✅ | `pos_call` |
| **Settori dove perdo** | ✅ | `sector_delta` (vs tuo best, all'asciutto) |
| **Curve dove perdo TEMPO** | ❌ | riconoscimento curve c'è (`corner_learn`, apex come TinyPedal) ma manca il confronto tempo-per-curva live |
| Bloccaggi per curva | ✅ | `pace_notes_call` (dove blocchi) |

## Meteo / gomme
| Capacità | Stato | Note |
|---|---|---|
| Briefing meteo al rolling start | ✅ | `race_briefing` (forecast pre-verde) |
| Finestra pioggia (apre al giro X) | ✅ | `wx_segments` + `plan_wx_arc` |
| Wet = ORDINE quando scivola | ✅ | `rain_live` → `rain_box_now` (state-aware: muto se già wet) |
| **Perdo passo per la pioggia (2s in un settore su slick) → box** | ❌ | messaggio `rain_box_pace` c'è, **modulo che calcola la perdita MANCA** |
| Slick = solo CONSIGLIO (temp/stint/usura) | ✅ | avvisi, non ordini |
| **Auto-pit monta la WET da sé** | ❌ | ora setta solo l'energia |
| **Inventario gomme parlato** (set usati/rimasti, usate da quali) | ❌ | dato LMU c'è (`_fetch_tyre_inventory`), muretto non lo recupera/annuncia |

## Strategia
| Capacità | Stato | Note |
|---|---|---|
| Endurance a tempo (4/6/8h) | ✅ | `core/muretto.py` (giri = tempo/passo − soste) |
| Multi-sosta + ricalcolo a ogni giro | ✅ | pit fuori strategia → ripianifica |
| Auto-pit VE per finire la gara | ✅ | (ripristinato: laps_needed+2) |
| **Gestire sì/no nel briefing** | 🟡 | il piano ha save/push ma non c'è un annuncio "gestisci" netto nel briefing |
| Consumi da dati DIRETTI LMU (no ipotesi) | ✅ | `per_lap` MISURATO (aspetta il dato) |

## Rivali
| Capacità | Stato | Note |
|---|---|---|
| Gap avanti/dietro | ✅ | `gap_call` |
| **Rivale di classe che chiude da dietro in modo precipitoso** | ✅ | `gap_closing` |
| **Rivale che perde passo di colpo** | ❌ | messaggio `opp_best` c'è, **modulo MANCA** |
| **Rivale ha preso penalità (e quale)** | ❌ | dato LMU c'è (`num_penalties` per auto), non annunciato |
| Pre-blu classe veloce | ✅ | `fast_class_call` (voce spotter, gated al via) |

## Track limits
| Capacità | Stato | Note |
|---|---|---|
| Avviso track limits + penalità | ✅ | `tlimits_call` (conteggio + soglia) |
| **Dove/quale curva li prendo** | ❌ | serve la posizione (lapdist → curva appresa) |

---

## Buchi da colmare (proposta di priorità)
1. **Rain pace-loss → box** (`rain_box_pace`): confronta il passo attuale col tuo passo asciutto; se perdi ≥ soglia su slick col bagnato → suggerisci le wet. *(alto valore, dati già presenti)*
2. **Auto-pit monta la wet** quando è bagnato. *(concreto)*
3. **Inventario gomme parlato** + set usati dalla quali. *(dato pronto)*
4. **Penalità rivali** annunciate (chi e quale). *(dato pronto)*
5. **Rivale che perde passo** (`opp_best` + calo passo). *(dato pronto)*
6. **Curve dove perdo tempo** (tracking per-curva live). *(modulo serio)*
7. **Track limits: dove/quale curva**. *(serve mappa curve)*
8. **"Gestisci sì/no" netto nel briefing**. *(ritocco)*
