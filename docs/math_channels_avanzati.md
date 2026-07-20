# Math channels avanzati (MoTeC i2) — riferimento SETUP / futuro

Formule MoTeC i2 (fornite dall'utente 2026-07-20). **Una parte è LIVE-usable**:
i canali servono ci sono già nel nostro reader. Il resto richiede canali profondi
(coppia freno per ruota, carico gomma, posizione sospensioni) che non arrivano
dalla shared memory (vivono nell'export **DuckDB**) → riferimento setup/futuro.

**✅ LIVE-usable ORA (abbiamo i canali) → candidate a nuove voci del muretto:**
- **Grip Utilization %** = √(g_lat²+g_long²)/target·100 — `g_lat`/`g_long` ci sono
  → coaching "quanto sei al limite" / gestione passo.
- **Delta temp gomma attraverso la larghezza** (inner vs outer) — `tyre_inner[3]`
  (inner/mid/outer) c'è → segnale **camber** (>15° = troppo camber, dai consigli).
- **Delta superficie−core** — `tyre_inner` + `tyre_carcass` ci sono → surriscaldo/
  blister.
- **Glazing Index** (vedi `LMU_Degradation`): superficie >105°C sostenuta →
  vetrificazione, anticipa il pit — costruibile dai temp gomma live.

**🔧 SOLO SETUP (canali mancanti live):** brake migration/brake-by-wire, roll
stiffness/mechanical balance, aero pitch/diffuser, bumpstop.

---

## 1. Dinamica pneumatici (grip residuo e vettori)
Formula pMBI attrito dinamico:
`Mu_dyn = Mu_peak * (1 - C_load*dFz) * (1 - C_temp*dT^2) * (1 - C_slip*V_slip)`

- `Combined G = sqrt(G_Lat^2 + G_Long^2)` [G]
- `Grip Utilization % = (Combined G / 3.2) * 100`  (3.2 G = target max HY a 250 km/h)
- `Tyre Temp Delta <wheel> = Tyre_Temp_Spline_Middle - Tyre_Temp_Core` [°C] (per FL/FR/RL/RR)

## 2. Aerodinamica (pitch e stallo diffusore)
- `Aero Platform Pitch = atan((RideHeightRear - RideHeightFront)/3140) * 180/π` [deg]
  · target in curva 0.3°-0.8° · passo HY 3140 mm
- `Rear Diffuser Stall Alarm = IF(RideHeightRear < 22, 1, 0)`
- `Suspension Travel FL % = (SuspPos FL / SuspMaxTravel FL) * 100`
- `FL Bumpstop Touch = IF(Suspension Travel FL % > 95, 1, 0)`

## 3. Brake migration (brake-by-wire Hypercar)
`Bias_dyn = Bias_base + (Delta_Brake_Pressure * Migration_Rate)`
- `Total Brake Torque = BT_FL + BT_FR + BT_RL + BT_RR` [Nm]
- `Front Brake Bias % = (BT_FL + BT_FR)/Total * 100`
- `Brake Migration Rate = derivative(Front Brake Bias %, 1)` (positivo al rilascio =
  bias migra all'anteriore per stabilizzare il retrotreno / trail braking)

## 4. Kinematics & roll stiffness (bilanciamento meccanico)
Carreggiata 1720 mm ant / 1680 mm post.
- `Front Roll Angle = (RideHeight FL - RideHeight FR)/1720` [deg/m]
- `Rear Roll Angle = (RideHeight RL - RideHeight RR)/1680`
- `Front Roll Stiffness = (TyreLoad FL - TyreLoad FR)/Front Roll Angle` [N/deg]
- `Rear Roll Stiffness = (TyreLoad RL - TyreLoad RR)/Rear Roll Angle`
- `Mechanical Balance Front % = FrontRS/(FrontRS+RearRS) * 100`
  · target **48-52%** · sotto **45%** = forte sovrasterzo meccanico in uscita

---

*Stato: riferimento. Non collegato al muretto live. Utile per un futuro modulo
di analisi setup basato sull'export DuckDB.*
