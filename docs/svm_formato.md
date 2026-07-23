# Formato .svm — l'assetto LMU su file (censito 23/07)

Fonte: `HY_GMR_Balanced_MonzaGrande_test_per muretto.svm` salvato dal
pilota (Genesis GMR-001 Hypercar, Monza). Cartella:
`Steam\...\Le Mans Ultimate\UserData\player\Settings\<Pista>\*.svm`
(una cartella per pista: Monza, Lemans, Spa, Imola, Fuji, Bahrain...).

## La regola d'oro del formato

Ogni riga è: `NomeSetting=<INDICE>//<valore umano mostrato>`

- L'**indice** è la posizione nella tabella opzioni di QUELLA macchina
  (0-based). È ciò che LMU legge.
- Il commento `//` è solo display — ma per noi è ORO: ci dice il valore
  reale senza dover conoscere le tabelle (es. `RWSetting=4//P5`:
  indice 4 = posizione "P5" — occhio all'off-by-one col label).
- `Symmetric=1` in GENERAL: le 4 sezioni ruota vanno tenute coerenti.
- Righe con `//Non-adjustable`, `//N/A`, `//N/D`: non toccare.
- Testo semplice, niente firma/checksum visibile → **scrivibile da noi**
  (il Garage scriverà questi file; LMU li carica dal suo menu setup).

## Le sezioni e cosa contengono (con esempi VERI)

| Sezione | Roba | Esempi dal file |
|---|---|---|
| header | macchina+classe | `VehicleClassSetting="Genesis_GMR001 Hypercar WEC2026"` |
| `[GENERAL]` | fuel/VE, pit programmati | `FuelSetting=87//0.92` · `VirtualEnergySetting=100//100% (28.9 laps)` |
| `[FRONTWING]` | ala anteriore | `FWSetting=0//Standard` |
| `[REARWING]` | ala posteriore | `RWSetting=4//P5` ← **stesso valore del pit menu R WING** |
| `[BODYAERO]` | nastri radiatore + condotti freni | `WaterRadiatorSetting=0//No tape` · `BrakeDuctSetting=0//Open` ← **= pit menu GRILLE/DUCT** |
| `[SUSPENSION]` | **BARRE** F/R, toe, TERZO elemento (packer/molla/slow-fast bump/rebound) | `FrontAntiSwaySetting=4//P4` · `RearAntiSwaySetting=2//P2` · `Front3rdSlowBumpSetting=1//2` |
| `[CONTROLS]` | **BIAS** (`RearBrakeSetting=16//52.8:47.2`), brake migration, pressione freno, sterzo, **3 mappe TC** (TC/PowerCut/SlipAngle) | ← il 52.8 è lo stesso `brake_bias` che leggiamo live |
| `[ENGINE]` | mappe ibrido: `RegenerationMapSetting=10//170kW` · `ElectricMotorMapSetting=5//50kW` · mixture | |
| `[DRIVELINE]` | rapporti (con set: `RatioSetSetting=1//Le Mans`), differenziale power/coast/preload | `DiffCoastSetting=13//75%` |
| `[FRONTLEFT/FRONTRIGHT/REARLEFT/REARRIGHT]` | per ruota: **camber, PRESSIONE a freddo, molla, altezza, slow/fast bump/rebound, disco/pastiglia, mescola+usura** | `CamberSetting=30//-1.0 deg` · `PressureSetting=23//154 kPa` · `RideHeightSetting=5//4.5 cm` |
| `[BASIC]` | gli slider semplificati del gioco + `Custom=1` | `Downforce=0.5 Balance=0.5 ...` |

## Perché è perfetto per il Setup Advisor

1. **Tutto ciò che i libri regolano è QUI**: barre (Tune to Win), damping
   slow/fast per ruota + terzo elemento (istogrammi Segers cap.11),
   camber/pressioni (cap.8), bias/migration (cap.5), ali/duct/tape.
2. **I valori umani nei commenti** ci permettono di parlare da ingegneri
   ("porta la barra davanti da P4 a P3") e di scrivere l'indice giusto.
3. **Coerenza live**: bias del file = `brake_bias` telemetria; RW del
   file = R WING del pit menu; duct idem → il muretto può confrontare
   l'assetto SU FILE con ciò che vede in pista.
4. Flusso Garage: leggere lo .svm attivo → tab per sezione → modifiche →
   scrivere un NUOVO file (mai sovrascrivere l'originale: suffisso
   `_muretto`) → il pilota lo carica dal menu setup LMU.

Nota prudenza: gli INDICI sono per-macchina (la stessa barra P4 può
essere indice diverso su un'altra auto): mai copiare indici tra vetture,
sempre leggere il file della macchina in uso.
