# Muretto — mappa capacità (stato reale vs visione)

Verificato nel codice (0.3b, aggiornato **23/07 sera** dopo il Cantiere 2).
Legenda: ✅ c'è e wired · 🟡 parziale · ❌ manca.

## Passo / tempi / posizione
| Capacità | Stato | Note |
|---|---|---|
| Tempo giro ogni giro (coi **decimali**) | ✅ | `lap_time_call`, `_fmt_lap_round` (decimale default on) |
| Posizione ogni giro | ✅ | `pos_call` |
| **Settori dove perdo** | ✅ | `sector_delta` (vs tuo best, all'asciutto) |
| **Curve dove perdo TEMPO** | ✅ | Time-Loss Matrix per curva (recorder) + `hotlap_loss` (test hotlap) + `timeloss_focus_call` (23/07: curva peggiore ricorrente, live in prova) |
| Bloccaggi per curva | ✅ | `pace_notes_call` (dove blocchi) |

## Findings PRO da math channel live (Cantiere 2, 23/07)
Un verdetto al giro al massimo, in ordine di priorità (salute macchina prima
del coaching), one-shot per stint, reset al pit. Modulo `pro_findings_call`.
| Capacità | Stato | Note |
|---|---|---|
| **Freni in fade** (stessa pressione, meno G, temp alte) | ✅ | critical + beep |
| **Pressioni vs finestra a caldo per classe** | ✅ | target_pitwall (HY 182-188, P2 172-178, GT3 163-168), dal 3° giro di stint |
| **Gomma vetrificata** (superficie ≫ carcassa) | ✅ | per ruota |
| **Camber da rivedere** (spread interno-esterno >15°) | ✅ | solo prova (roba da assetto) |
| **Stallo diffusore** (posteriore bassa in velocità) | ✅ | solo prototipi, da `ride_h` |
| **ABS/TC che lavorano troppo** (GT: >15% / >8%) | ✅ | % interventi sul giro |
| **Power clip** (HY: tetto di potenza sul dritto) | ✅ | consiglia deploy anticipato |
| **Burn energia MJ/km sopra target** (HY) | ✅ | da VE consumata × 9 MJ |
| **Aria sporca** (>30% del giro incollato davanti) | ✅ | solo gara |
| **Margine grip** (usi <86% del potenziale di classe) | ✅ | solo prova, combined-G vs target |
| **Anti-ripetizione coaching** | ✅ | stesso finding mai entro 4 min (`emit_log` 240s); salute macchina esente |

## Meteo / gomme
| Capacità | Stato | Note |
|---|---|---|
| Briefing meteo al rolling start | ✅ | `race_briefing` (forecast pre-verde) |
| Finestra pioggia (apre al giro X) | ✅ | `wx_segments` + `plan_wx_arc` |
| Wet = ORDINE quando scivola | ✅ | `rain_live` → `rain_box_now` (state-aware: muto se già wet) |
| **Perdo passo per la pioggia su slick → box** | ✅ | `rain_pace_call` (23/07): passo vs la TUA mediana asciutta, −3s su slick col bagnato → `rain_box_pace` |
| Slick = solo CONSIGLIO (temp/stint/usura) | ✅ | avvisi, non ordini |
| **Auto-pit monta la WET da sé** | ❌ | **unico buco grosso rimasto**: auto-pit setta solo l'energia; la scrittura pit-menu via REST (`loadPitMenu`) è già collaudata, manca solo il collegamento |
| **Inventario gomme parlato** (treni nuovi/usati) | ✅ | `tyre_stock` (in box, dato REST dotazione) |

## Strategia
| Capacità | Stato | Note |
|---|---|---|
| Endurance a tempo (4/6/8h) | ✅ | `core/muretto.py` (giri = tempo/passo − soste) |
| Multi-sosta + ricalcolo a ogni giro | ✅ | pit fuori strategia → ripianifica |
| Auto-pit VE per finire la gara | ✅ | laps_needed+2 |
| **Gestire sì/no nel briefing** | ✅ | `briefing_manage` / `briefing_push` / `briefing_save` emessi dal piano |
| Consumi da dati DIRETTI LMU (no ipotesi) | ✅ | `per_lap` MISURATO (aspetta il dato) |

## Rivali
| Capacità | Stato | Note |
|---|---|---|
| Gap avanti/dietro | ✅ | `gap_call` |
| Rivale di classe che chiude precipitoso | ✅ | `gap_closing` |
| **Rivale che perde passo** | ✅ | `opp_slow` (calo secco) + `opp_fading` (23/07: gap davanti che scende 3-4 giri di fila → "lo prendi") |
| **Rivale ha preso penalità (chi)** | ✅ | `rival_watch_call` (23/07): pen per auto dal field → `opp_penalty` col nome |
| Pre-blu classe veloce | ✅ | `fast_class_call` (voce spotter, gated al via) |

## Track limits
| Capacità | Stato | Note |
|---|---|---|
| Avviso track limits + penalità | ✅ | `tlimits_call` (conteggio + soglia) |
| **Dove/quale curva li prendo** | ✅ | `tl_where_call` (23/07): curva NOMINATA dalla geometria mappa (`map_turns`), "di nuovo T4" se recidivo |

## Danni fisici (dal trace + shared memory)
| Capacità | Stato | Note |
|---|---|---|
| Verdetto post-impatto (aero/sospensioni, con chi) | ✅ | `damage_call` (~6s dopo la botta) |
| Ruota piegata (toe/camber storti) | ✅ | `wheel_bend_call` — trace `Bending wheel` (unica fonte). Soglia 0.20, "forte" ≥ 0.50 |
| Causa ritiro certificata (motore/telaio) | ✅ | trace `LocalDNF due to Engine/Suspension/Accident`; solo gara |
| Fondo che tocca (bottoming) | ✅ | debrief fine stint (≥5 tocchi, `ride_h` < 2mm oltre 90 km/h) |
| Avvertimento antisportiva di LMU | ❌ | verificato 23/07: NON esiste in nessun dato (solo grafica del gioco). Alternativa già attiva: chiamata contatto nostra da `mLastImpact` |

## Voci / radio (23/07)
| Capacità | Stato | Note |
|---|---|---|
| 3 ruoli (race/strategy/performance), voce per ruolo | ✅ | titolari Florian / Remy / Ava (Multilingual) |
| **Selettore voci dal menu Engineer** | ✅ | 20 voci edge-tts free, provino ▶, cambio LIVE (engineer_cfg riletto a ogni frase) |
| Uscita vs rientro dal garage | ✅ | il briefing d'uscita parte SOLO dalla piazzola dopo motore spento; il rientro è muto |

---

## Buchi rimasti (in ordine)
1. **Auto-pit monta la wet** quando è bagnato — scrittura pit-menu REST già
   collaudata, manca il collegamento nel flusso auto-pit. *(unico buco "dati
   pronti")*
2. Backlog non ancora portato: modalità quali-info (confronto pole/rivale),
   debrief di stint in garage, riscrittura "frasi umane" (contatto+danno in
   una frase sola), `opp_slow` arricchito col danno del rivale. Vedi memoria
   di progetto.
