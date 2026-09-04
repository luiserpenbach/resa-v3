# Spark-50 cooling redesign

**Goal:** keep the hot wall under the material limit with the corrected RESA
physics (CEA frozen expansion, delivery-temperature propellant cards, raw
Bartz × 1.0 ± 0.3 with CEA frozen transport, Taylor GH2 correlation).

## Starting point

50 N, 7 bar, O/F 4.2, ε 80, IN718 liner, 14 channels 1.3 × 0.8 mm at the
throat, 2.2 g/s GH2 counterflow from the nozzle exit at 15 bar.

| Quantity | As found |
|---|---|
| Peak hot wall | 1848 K (band 1609 to 2015 K) vs 1000 K IN718 limit |
| Throat heat flux | 15 MW/m² |
| Coolant at throat | 511 K bulk, 220 m/s, Re 12 000 |
| Wall stress / yield | 3.1 |

The old 909 K result came from solving with the oxidizer flow (9.1 g/s of
"hydrogen") and a 0.6 Bartz factor inherited from N2O/ethanol anchoring.

## What moved the wall (sweeps on the corrected solver)

| Lever | Effect at the throat | Notes |
|---|---|---|
| IN718 → copper alloy (CuCrZr, GRCop-42) | −130 K | conduction drop small once the fins work; stress ratio 3 → 0.7 |
| Throat channel 0.8 → 0.3 mm high, 14 → 26 channels, 0.4 mm ribs | −450 K | plateaus below 0.3 mm: hydrogen Taylor correction and Mach 0.4 cap the gain |
| Feed 15 → 25 bar | ≈ 0 K on wall, Mach 0.43 → 0.26 | needed to allow the small channels |
| O/F 4.2 → 2.5 | −280 K | Tc 3160 → 2560 K, 42 % more H2; frozen Isp +20 s |
| pc 7 → 6 bar | −20 to −40 K | flux ∝ pc^0.8; throat 9 % larger |
| Jacket to ε 40 + C-103 skirt | throat coolant 450 → 385 K | skirt 1397 K vs 1600 K limit |
| Chamber channels 0.8 → 0.45 mm high, 1.6 mm ribs | injector-end wall 928 → 836 K | second hot spot: warm coolant, slow channel |
| 15 to 30° helix through the throat | −15 to −40 K | width falls below 0.6 mm at 6 to 7 bar; kept as an option |
| 30 channels with 0.3 mm ribs | −35 K | at the LPBF limit; kept as an option |

Screening grid (GRCop-42, 26 ch × 0.3 mm, 0.4 mm ribs, 25 bar, jacket to ε 40):

| O/F | pc [bar] | Isp [s] | T_wall nominal [K] | at Bartz × 1.3 [K] |
|---|---|---|---|---|
| 4.2 | 7 | 437 | 1209 | 1365 |
| 3.5 | 7 | 449 | 1136 | 1281 |
| 3.0 | 7 | 455 | 1024 | 1170 |
| 3.0 | 6 | 454 | 1007 | 1167 |
| 2.5 | 7 | 457 | 951 | 1066 |
| 2.5 | 6 | 457 | 931 | 1035 |
| 2.5 | 5 | 456 | 888 | 1014 |

## Selected design (this config)

| Item | Value |
|---|---|
| Operating point | 50 N, 6 bar, O/F 2.5, ε 80 |
| Liner | GRCop-42, 0.5 mm hot wall |
| Channels | 26; 0.3 mm high × 0.69 mm wide at the throat, 0.4 mm ribs; 0.45 mm high with 1.6 mm ribs in the chamber; 1.0 mm high at the jacket end |
| Coolant | 3.18 g/s GH2, 250 K / 25 bar in at ε 40, counterflow |
| Jacket end | ε 40 (x ≈ 43 mm); C-103 radiation skirt to ε 80 |

| Result | Value |
|---|---|
| Delivered vacuum Isp (frozen, η_c* 0.95, η_CF 0.977) | 458 s |
| Peak hot wall | 911 K at the throat (836 K at the injector end) |
| Bartz band ± 0.3 | 755 to 1040 K |
| Coolant outlet | 626 K, 23.2 bar (Δp 1.85 bar) |
| Coolant Mach / Re | 0.26 max / 5 600 to 23 000 |
| Wall stress / yield, thermal strain | 0.51, 0.9 % |
| Skirt | 1397 K max, 1232 K at the exit, 1.2 kW radiated |
| Feed margin over pc × 1.2 | 16 bar |

## Open points

- The +0.3 end of the Bartz band is 40 K over the limit. Two documented ways
  to close it: a 15 to 30° helix through the throat (needs 0.55 mm channels)
  or 30 channels with 0.3 mm ribs; either brings the +0.3 case to ≈ 1000 K.
  Better: anchor the Bartz factor on a hot-fire of this chamber.
- O/F 2.5 raises hydrogen consumption by 42 % versus O/F 4.2 for the same
  thrust; storage volume grows accordingly. If the mixture ratio is fixed by
  the system, pc 5 bar with the helix option reaches ≈ 860 K at O/F 2.5 and
  ≈ 1000 K at O/F 3.0.
- The frozen-flow Isp trend that makes O/F 2.5 free is a model choice; the
  equilibrium bound favours O/F 3.5 to 4. Real kinetics at 6 bar sit between.
- GRCop-42 limit (1000 K), C-103 limit (1600 K, coated) and the LPBF minimum
  features (0.4 mm ribs, 0.6 mm channels, 2 mm closeout span) are the
  database screening values in `regen_channels/materials.py`; confirm with
  the supplier before release.
- The skirt model neglects conduction along the wall and inner-face
  radiation; the 1400 K figure is a first-order estimate.
