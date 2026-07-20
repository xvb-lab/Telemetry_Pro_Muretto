# Numeri strategia — costanti quantitative (→ codice)

Valori quantitativi forniti dall'utente (2026-07-20, raccolti via ricerca).
Diventano **costanti Python** del calcolatore strategico. **Regola d'oro:** in
gara il muretto usa PRIMA il dato VIVO di LMU (usura reale, per_lap misurato,
pit-estimate del gioco); questi numeri sono **calibrazione / fallback /
riferimento** quando il dato live manca. Verificare contro LMU dove possibile.

---

## 1. Undercut / Overcut & Pit Delta

**Vantaggio gomme nuove** (vs set al 35-40% di usura), s/giro:
| Classe | Δ gomme nuove |
|---|---|
| Hypercar | 1.2 – 1.6 |
| LMP2 | 1.5 – 1.8 |
| LMGT3 | 1.8 – 2.3 |

**Penalità out-lap** (gomme fredde ~60-70°C dalle coperte), s:
| Classe | Penalità out-lap |
|---|---|
| Hypercar | +2.5 – +3.5 (sensibili alla pressione min 1.80 bar) |
| LMP2 | +2.0 – +3.0 |
| LMGT3 | +3.0 – +4.2 (rischio bloccaggio/ABS che rovina la superficie) |

**Pit delta** (perdita netta per attraversare la corsia box al limitatore, escluso
lo stazionamento), s:
| Circuito | Pit delta |
|---|---|
| Monza | ~21.5 |
| Imola | ~24.0 |
| Fuji | ~26.5 |
| Spa | ~29.0 |
| Le Mans | ~34.5 |

## 2. Rateo usura gomme & cliff

**Usura % per giro** (asfalto ~28°C):
| Classe | Soft | Medium | Hard |
|---|---|---|---|
| Hypercar | 1.1% | 0.8% | 0.5% |
| LMP2 | — | 0.9% (mescola unica) | — |
| LMGT3 | 1.4% | 1.0% | 0.6% |

**Cliff** (crollo NON lineare, motore rF2):
- **35% usura** = soglia allarme: drop costante ~0.3 s/giro.
- **45% usura** = cliff: carcassa cede, +3.0/4.0 s/giro, spiattellamento ad ogni
  staccata. **Non superare.**

**Asse ant/post:**
- HY **4WD** (Toyota/Ferrari/Peugeot): usura simmetrica (ant 48% / post 52%) →
  **double-stint totale** ok.
- HY **LMDh RWD** (Porsche/BMW/Cadillac) e **LMGT3**: asimmetrica, il **posteriore
  si consuma ~40% più veloce** → basare la strategia sulla **posteriore interna
  alla curva più sollecitata** (es. post. destra a Spa).

## 3. Consumi di riferimento + Lift&Coast

**Consumo/giro** (pieno regime, mappa gara 1):
| Circuito | HY (MJ) | LMGT3 (MJ) | LMP2 (L) |
|---|---|---|---|
| Le Mans | 22.5 | 9.2 | 3.45 |
| Spa | 14.8 | 6.1 | 2.20 |
| Monza | 13.2 | 5.4 | 1.95 |
| Fuji | 12.8 | 5.2 | 1.85 |
| Imola | 11.5 | 4.7 | 1.65 |

**Lift & Coast** (100 m prima della staccata): risparmia **+6% … +8%** di VE/benzina
per giro; costo cronometrico solo **0.15–0.25 s/giro**.
**Mappa conserve** (2/3): **+3%** di risparmio extra, ma **-4/6 km/h** di punta.

## 4. Dinamica meteo

**Salita wetness (pioggia):**
| Intensità | Δ wetness | Note |
|---|---|---|
| Pioggerellina | +0.5%/min | slick ok fino a ~15 min |
| Pioggia costante | +2%/min | |
| Temporale | +6%/min | allagamento immediato |

**Asciugatura:** la **traiettoria ideale asciuga 3× più veloce** dell'esterno. Con
aria 25°C, la traiettoria ideale passa da 40% (wet pieno) a 0% (dry) in **~8-10
min** senza pioggia.

## 5. Penalità e bandiere

- **FCY / Safety Car**: limitatore auto 80 km/h; consumo VE **-70%**. Fermarsi sotto
  FCY abbatte il pit delta di **~65%** → guadagno netto **15-22 s** vs sosta in verde.
- **Track limits**: 3 warning; **4°** = drive-through; **5°+** = penalità di tempo
  cumulative (5 s).
- **Sforamento VE (0% NRG)**: 5 s di tolleranza per rientrare ai box; se completi un
  giro a secco di VE → **Stop&Go 100 s** al passaggio dopo.

## 6. Regolamento

- **Soste obbligatorie**: nessuna, strategia libera.
- **Cambio pilota**: eventi endurance multiplayer/ufficiali → ogni pilota registrato
  deve coprire un minimo (~**20%** della durata) o DSQ.
- **Allocazione gomme**: eventi avanzati limitano i treni slick per weekend (es. 9-12
  per una 4h) → il **double-stint diventa obbligo regolamentare**, non solo di tempo.

## 7. Scelta mescole (finestre temp ASFALTO)

| Mescola | Finestra asfalto | Vita |
|---|---|---|
| **Soft** | < 19°C (notte/mattina) | max 1 stint (HY ~45-50 min, GT3 ~50 min); sopra 25°C surriscalda dopo 4 giri |
| **Medium** | 20-36°C (standard) | 2 stint pieni (HY ~95-100 min, GT3 ~105 min); resta sotto il cliff 45% |
| **Hard** | > 37°C | 3 stint HY / 2 pesanti GT3; -0.6 s vs Medium ma stabilità termica totale |

---

*Questi valori → costanti in `core/` (es. `PIT_DELTA`, `TYRE_WEAR_PL`,
`CONSUMPTION`, `TYRE_DELTA_NEW`, `CLIFF_*`). Il calcolo LIVE preferisce sempre il
dato reale di LMU; le costanti sono riferimento/fallback.*
