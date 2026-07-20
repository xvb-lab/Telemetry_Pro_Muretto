# Dati di dominio LMU — riferimento AUTOREVOLE

Valori forniti dall'utente (esperto di dominio) il 2026-07-20. Sono la **base
della strategia e degli allarmi** del muretto: il codice va calibrato su
QUESTI numeri, non su assunzioni. Non contraddire con l'intuizione.

---

## 1. Virtual Energy vs Benzina — per classe

In LMU l'auto può avere **VE e benzina insieme**: si consumano in parallelo.
Il vincolo che LEGA lo stint dipende dalla classe.

| Classe | Vincolo stint | Valore | Note |
|---|---|---|---|
| **Hypercar (HY)** | **Virtual Energy** | ~880–910 MJ/stint (BoP per costruttore) | consuma **VE *e* benzina**; VE a 0% = **Stop&Go 100 s** |
| **LMGT3** | **Virtual Energy** | ~350–380 MJ/stint (BoP circuito) | auto a benzina, ma VE a 0% = **Stop&Go 100 s** (~53–55 min a pieno regime) |
| **LMP2** | **Benzina** | serbatoio 75 L | niente VE nell'HUD; stint finisce coi litri |
| **LMGTE AM** | **Benzina** | ~88–90 L (BoP classico) | reg. 2023, zero VE |
| **LMP3** | **Benzina** | 100 L | nessun sistema VE/ibrido |

**Implicazioni muretto:**
- HY e LMGT3 → il vincolo è la **VE**; finirla = penalità 100 s (grave quanto
  restare a secco → chiamata di sicurezza).
- HY → tenere d'occhio **anche i litri** (si consumano entrambi).
- LMP2/LMP3/GTE AM → vincolo **benzina**, niente VE.
- Il constraint si rileva dai dati LMU (presenza voce VIRTUAL ENERGY), MAI
  assunto dal buonsenso. Vedi memoria `lmu-gt3-energia`.

---

## 2. Gomme e freni — finestre per gruppo di classe

### Prototipi (Hypercar / LMP2 / LMP3)
**Gomme slick (S/M/H)**
- Finestra esercizio (core/carcassa): **75–87 °C**
- Picco max (inizio perdita grip): 90–95 °C
- Minima di funzionamento: 60 °C (sotto = scivola completamente)
- Pressione minima a caldo: **1.80–1.95 bar** (mai sotto 1.80)

**Freni (carbonio)**
- Minima efficienza: **250 °C** (sotto = non frena alla prima staccata)
- Finestra ottimale: **350–650 °C**
- Overheating: **800 °C**
- Setup: regola i brake ducts per tenerli verdi nell'MFD.

### Gran Turismo (LMGT3 / LMGTE)
**Gomme slick (S/M/H)**
- Finestra esercizio (core/carcassa): **70–90 °C**
- Picco max (inizio perdita grip): 95–100 °C
- Minima di funzionamento: 55 °C
- Pressione minima a caldo: **1.90–2.00 bar**

**Freni (acciaio / carbonio GT)**
- Minima efficienza: **150 °C**
- Finestra ottimale: **300–550 °C**
- Overheating: **700 °C**
- Nota: le GT3 accumulano calore nei circuiti stop-and-go (Imola/Fuji).

---

## 3. Temperature motore (tutte le classi)
- **Olio**: ottimale **95–110 °C** · max **130 °C** (poi rottura)
- **Acqua**: ottimale **90–100 °C** · max **110 °C** (poi rottura)
- Sotto **80 °C** olio/acqua la mappa motore **taglia potenza** in automatico.

---

*Da usare per calibrare `_thermal_windows` / allarmi motore / strategia energia
del cervello. Verificare che i valori nel codice coincidano con questi.*
