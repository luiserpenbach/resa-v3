# RESA configuration reference

Complete reference for engine YAML configs and high-fidelity regen cooling configs.
All lengths are **metres** unless the key name says otherwise (`*_bar`, `*_deg`,
`*_K`, `*_N`, `*_mm` in regen export filenames only).

Validation runs at load time. Unknown keys are rejected. See `resa/config/schema.py`
and `resa/regen_channels/config.py` for the authoritative schema.

---

## Config file layout

```
configs/
├── shared/                     reusable fragments (referenced by engine configs)
│   ├── prop_n2o_ethanol.yaml
│   ├── chamber_e2.yaml
│   └── cooling_e2_c1.yaml
└── e2_c1/                      one engine / campaign
    ├── design.yaml             full engine config (design mode)
    ├── asbuilt.yaml            inherits design → analyze mode
    ├── hf02.yaml               inherits asbuilt → HF02 variant
    ├── regen.yaml              regen fragment (not a full engine config)
    ├── design_regen.yaml       design + regen
    ├── asbuilt_regen.yaml
    └── hf02_regen.yaml
└── ex15/                       15 kN H2/GOX (see design.yaml for ε)
    ├── design.yaml
    ├── regen.yaml
    └── design_regen.yaml
└── ci/                         offline table configs for tests / CI
    ├── e2_c1_design.yaml
    ├── e2_c1_asbuilt.yaml
    ├── e2_c1_hf02.yaml
    └── ex15_design.yaml
```

### Campaign runner

Multi-config report batches live in `campaigns/*.yaml`:

```yaml
name: e2_regen
output: e2_output_regen
rollup: true
configs:
  - ../configs/e2_c1/design_regen.yaml
diffs:
  - a: ../configs/e2_c1/asbuilt_regen.yaml
    b: ../configs/e2_c1/hf02_regen.yaml
    output: diff_asbuilt_vs_hf02.txt
regen_diffs:
  - a: ../configs/e2_c1/asbuilt_regen.yaml
    b: ../configs/e2_c1/hf02_regen.yaml
    output: regen_diff_asbuilt_vs_hf02.html
```

Run with `python -m resa campaign campaigns/e2_c1/e2_regen.yaml`.

**RESA Studio** can also run campaigns from the sidebar; see [STUDIO.md](STUDIO.md).

### CI / golden tests

Golden regression uses **offline combustion tables** in `configs/shared/cea_tables/`
via `configs/ci/*.yaml` — no Fortran required. Reference values live in
`tests/fixtures/*/expected.yaml`. GitHub Actions runs `pytest` on every push.

---

## Loading and composition

### File references

These top-level keys may be a path to another YAML file (relative to the
config file's directory):

| Key | Loads |
|-----|-------|
| `propellants` | `PropellantConfig` |
| `combustion` | `CombustionConfig` (usually inline) |
| `chamber` | `ChamberConfig` |
| `cooling` | `CoolingConfig` |
| `regen` | `RegenConfig` |

Example:

```yaml
engine: "E2-C1"
propellants: ../shared/prop_n2o_ethanol.yaml
chamber: ../shared/chamber_e2.yaml
cooling: ../shared/cooling_e2_c1.yaml
regen: regen.yaml
```

### Inheritance (`base:`)

Any config may start from another file. The child is deep-merged over the base.
Use `null` to clear a key from the base (e.g. switch design → analyze mode).

```yaml
base: design.yaml
engine: "E2-C1-ASBUILT"
operating_point: null
geometry:
  throat_diameter_m: 0.027903
  exit_diameter_m: 0.052202
analyze_point:
  mdot_ox_kg_s: 0.81
  mdot_fuel_kg_s: 0.205
  eta_cstar: 0.92
```

Each loaded config gets a `config_hash` (12-char SHA-256 of the resolved dict)
attached at runtime for traceability in report folders.

---

## Engine config

Top-level keys for a full engine definition:

| Key | Required | Description |
|-----|----------|-------------|
| `engine` | yes | Human-readable engine name (used in reports) |
| `propellants` | yes | Propellant pair and delivery temperatures |
| `combustion` | yes | CEA table or rocketcea backend |
| `chamber` | yes | Contour / chamber geometry generation |
| `cooling` | yes | Simple cooling sanity-check block |
| `operating_point` | design | Targets → geometry sizing |
| `analyze_point` | analyze | Measured flows → performance |
| `geometry` | analyze | Measured throat / exit geometry |
| `offdesign` | no | Throttle and O/F sweeps |
| `regen` | no | High-fidelity regen channel analysis |

**Mode rule:** provide exactly one of `operating_point` (design) or
`analyze_point` (analyze). Analyze mode also requires `geometry`.

---

### `propellants`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Label for reports |
| `oxidizer` | string | yes | CoolProp fluid name (e.g. `NitrousOxide`) |
| `fuel` | string | yes | CoolProp fluid name (e.g. `Ethanol`) |
| `ox_temp_K` | float > 0 | yes | Delivered oxidizer temperature [K] |
| `fuel_temp_K` | float > 0 | yes | Delivered fuel temperature [K] |
| `cea_oxidizer` | string | no | CEA oxidizer name if different from CoolProp |
| `cea_fuel` | string | no | CEA fuel name if different from CoolProp |

---

### `combustion`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `backend` | `"table"` \| `"rocketcea"` | `"table"` | Property source |
| `table` | object | — | Required when `backend: table` |

#### `combustion.table`

Either a **single point** (all scalars) or a **1-D table over O/F** (all lists
plus `of`). A table is required for O/F optimization and off-design sweeps.

| Field | Type | Description |
|-------|------|-------------|
| `of` | list[float] | O/F grid; strictly increasing; required for tables |
| `cstar_m_s` | float \| list | Ideal characteristic velocity [m/s] |
| `tc_K` | float \| list | Chamber temperature [K] |
| `gamma` | float \| list | Ratio of specific heats |
| `mw_kg_kmol` | float \| list | Mean molecular weight [kg/kmol] |

All list fields must have the same length as `of`.

---

### `operating_point` (design mode)

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `thrust_N` | float | — | > 0 | Target thrust [N] |
| `pc_bar` | float | — | > 0 | Target chamber pressure [bar] |
| `eta_cstar` | float | — | 0.5–1.0 | Combustion efficiency on c* |
| `eta_cstar_tol` | float | null | 0–0.3 | ± band for uncertainty re-runs |
| `eta_cf` | float | 1.0 | 0.5–1.0 | Nozzle thrust-coefficient efficiency |
| `p_amb_bar` | float | 1.01325 | ≥ 0 | Ambient pressure [bar] |
| `of_ratio` | float | null | > 0 | Fixed O/F; omit → max-Isp optimum |
| `pe_bar` | float | null | > 0, < pc | Fixed exit pressure [bar] |
| `eps` | float | null | > 1 | Fixed area ratio |

**Exit condition:** give at most one of `pe_bar` / `eps`. If both omitted →
optimum expansion (`pe = p_amb`). In vacuum (`p_amb_bar = 0`) you must give
`eps` or `pe_bar`.

**Validation:** `eta_cstar + eta_cstar_tol ≤ 1.0`.

---

### `geometry` (analyze mode)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `throat_diameter_m` | float > 0 | yes | Measured throat diameter [m] |
| `eps` | float > 1 | one of | Area ratio A_exit / A_throat |
| `exit_diameter_m` | float > 0 | one of | Measured exit diameter [m] |

Give exactly one of `eps` or `exit_diameter_m`.

---

### `analyze_point` (analyze mode)

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `mdot_ox_kg_s` | float | — | > 0 | Measured oxidizer mass flow [kg/s] |
| `mdot_fuel_kg_s` | float | — | > 0 | Measured fuel mass flow [kg/s] |
| `eta_cstar` | float | — | 0.5–1.0 | Combustion efficiency on c* |
| `eta_cstar_tol` | float | null | 0–0.3 | ± band for uncertainty re-runs |
| `eta_cf` | float | 1.0 | 0.5–1.0 | Nozzle thrust-coefficient efficiency |
| `p_amb_bar` | float | 1.01325 | ≥ 0 | Ambient pressure [bar] |

---

### `chamber`

Controls Rao/Bell (or conical) contour generation.

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `contraction_ratio` | float | — | > 1 | Chamber-to-throat area ratio |
| `l_star_m` | float | — | > 0 | Characteristic length L* [m] |
| `contour` | string | `"rao_bell"` | `rao_bell`, `conical`, `moc` | Contour method |
| `bell_fraction` | float | 0.8 | 0.5–1.0 | Bell length vs 15° cone reference |
| `conv_half_angle_deg` | float | 30 | 0–60 | Convergent half-angle [deg] |
| `rt_upstream_factor` | float | 1.5 | > 0 | Upstream throat arc R / R_t |
| `rt_downstream_factor` | float | 0.382 | > 0 | Downstream throat arc R / R_t |
| `rc_entrance_factor` | float | 0.5 | 0–1.5 | Cylinder→convergent fillet R / D_c |
| `bartz_correction` | float | 0.75 | 0–1.5 | Small-engine Bartz correction (also synced to regen) |
| `n_stations` | int | 200 | ≥ 20 | Contour discretisation points |
| `theta_n_deg` | float | null | 0–60 | Bell initial angle; omit → calculated |
| `theta_e_deg` | float | null | 0–30 | Bell exit angle; omit → calculated |

---

### `cooling`

Simple regen layout used for pipeline sanity checks (circumference fit). Not the
high-fidelity regen solver — use the `regen:` block for that.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `coolant` | string | — | Coolant label |
| `n_channels` | int | — | ≥ 4 | Number of channels |
| `channel_width_m` | float | — | > 0 | Channel width [m] |
| `channel_height_m` | float | — | > 0 | Channel height [m] |
| `rib_width_m` | float | — | > 0 | Rib width [m] |
| `inner_wall_thickness_m` | float | — | > 0 | Hot-side wall thickness [m] |
| `wall_material` | string | `"IN718"` | Wall material label |
| `mdot_coolant_kg_s` | float | null | > 0 | Optional fixed coolant flow [kg/s] |
| `inlet_T_K` | float | — | > 0 | Coolant inlet temperature [K] |
| `inlet_p_bar` | float | — | > 0 | Coolant inlet pressure [bar] |
| `correlation` | string | `"gnielinski"` | `gnielinski`, `chen`, `jackson` | HTC correlation |

---

### `offdesign`

All sweeps use **fixed nominal geometry**. Optional blocks:

#### `offdesign.ox_throttle`

Vary oxidizer flow; fuel flow constant (E2-style single-side throttling).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ox_fraction` | [min, max] | [0.5, 1.15] | Multiplier on nominal ṁ_ox |
| `n` | int | 25 | ≥ 5 | Number of points |

#### `offdesign.of_sweep`

Vary O/F at constant **total** mass flow.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `of_range` | [min, max] | — | O/F sweep bounds |
| `n` | int | 30 | ≥ 5 | Number of points |

#### `offdesign.envelope`

2-D grid: total-flow throttle fraction × O/F.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `throttle_fraction` | [min, max] | [0.6, 1.15] | Multiplier on nominal ṁ_total |
| `of_range` | [min, max] | [3.5, 7.0] | O/F bounds |
| `n` | [n_t, n_of] | [20, 20] | Grid resolution |

---

### `regen` (optional)

Attach a high-fidelity regen channel config (inline or file ref). When present,
the report writer runs the regen solver after the engine pipeline and writes
artifacts into the same output folder. See [Regen config](#regen-config) below.

```yaml
regen: regen.yaml
```

---

## Regen config

Used standalone (`python -m resa.regen_channels.run regen.yaml`) or attached
to an engine config. Top-level keys:

| Key | Required | Description |
|-----|----------|-------------|
| `meta` | no | Name and description |
| `contour` | yes | Chamber inner contour for channel layout |
| `channels` | yes | Channel count, profiles, helix |
| `geometry` | no | Layout discretisation |
| `solver` | no | Thermal-hydraulic solve |
| `sync` | no | RESA auto-sync opt-out flags |
| `export` | no | Output artifacts (overridden when run via RESA reports) |

---

### Profile values (`ProfileSpec`)

Many regen fields accept axial profiles along engine axis x [m]:

| Form | Example | Description |
|------|---------|-------------|
| Scalar | `height: 2.0e-3` | Constant |
| Breakpoints | `height: [[0.0, 3e-3], [0.2, 1.5e-3]]` | PCHIP interpolation (default) |
| Dict | `{points: [[...]], interp: linear}` | Explicit interpolation |

Outside the breakpoint range values are clamped to the endpoint values.

Applicable fields: `channels.inner_wall_thickness`, `channels.height`,
`channels.rib.width`, `channels.helix.profile`.

---

### `meta`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `"unnamed"` | Tag for output filenames |
| `description` | string | `""` | Free text |
| `version` | string | `"0.1"` | Config version label |

---

### `contour`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `"parametric"` | `parametric`, `points`, `from_engine` |

#### `type: parametric`

Requires `contour.parametric`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `chamber_radius` | float | — | Cylindrical section radius [m] |
| `chamber_length` | float | — | Cylindrical section length [m] |
| `throat_radius` | float | — | Throat radius [m] |
| `contraction_angle_deg` | float | 30 | Convergent half-angle [deg] |
| `r1_factor` | float | 1.5 | Chamber-side blend arc R₁ / R_c |
| `r2_factor` | float | 1.5 | Upstream throat arc R₂ / R_t |
| `rd_factor` | float | 0.382 | Downstream throat arc R_d / R_t |
| `expansion_ratio` | float | 4.0 | Nozzle area ratio |
| `nozzle_type` | string | `"bell"` | `cone` or `bell` |
| `cone_half_angle_deg` | float | 15 | Cone divergent half-angle [deg] |
| `bell_fraction` | float | 0.8 | Bell length vs 15° cone |
| `theta_n_deg` | float | 21 | Bell initial angle [deg] |
| `theta_e_deg` | float | 9 | Bell exit angle [deg] |

#### `type: points`

Provide `contour.points` as `[[x, r], ...]` in metres, or `contour.points_file`
(path to CSV with x, r columns).

#### `type: from_engine`

Uses the RESA engine contour from the nominal pipeline run. Only valid when
regen is attached to an engine config and `sync.contour: true`. Cannot be used
in standalone regen runs.

**Axis convention (important):** RESA places the **throat at x = 0**. The
chamber extends to **negative x** (injector ≈ −130 mm for E2-C1), and the
nozzle divergent is **positive x**. Profile breakpoints (`height`, `helix.profile`)
and `channels.start_x` / `stop_x` must use this frame — not the regen parametric
frame where x = 0 is the injector face.

| Location | Typical x [m] (E2-C1) |
|----------|------------------------|
| Injector face | ≈ −0.133 |
| Throat | 0 |
| Nozzle exit | ≈ +0.036 |

Omit `start_x` and `stop_x` for full-length channels. Setting `start_x > 0`
limits cooling to the nozzle only.

---

### `sync`

Opt-out flags for RESA auto-sync. **All default to `true`.** Set to `false` to
keep the regen YAML value instead of the engine result.

| Flag | When true (default) | RESA source |
|------|---------------------|-------------|
| `contour` | Use engine contour | `contour.type: from_engine` |
| `hot_gas_pc_bar` | Sync Pc | `thrust_chamber.pc_bar` |
| `hot_gas_tc_K` | Sync Tc | `combustion.tc_K` |
| `hot_gas_gamma` | Sync γ | `combustion.gamma` |
| `hot_gas_mol_mass_kg_kmol` | Sync MW | `combustion.mw_kg_kmol` |
| `hot_gas_c_star_m_s` | Sync c* | `combustion.cstar_ideal_m_s` |
| `hot_gas_bartz_correction` | Sync Bartz factor | `chamber.bartz_correction` |
| `of_ratio` | Sync O/F | `thrust_chamber.of_ratio` |
| `mdot` | Sync coolant mdot from engine | `mdot_ox` or `mdot_fuel` (see `coolant_side`) |

**Never synced from RESA** (always from regen YAML): `hot_gas.mu_pa_s`,
`hot_gas.pr`, all channel geometry, inlet, wall, roughness settings.

**Legacy:** `solver.mdot_from_engine: false` automatically sets `sync.mdot: false`.
When `sync.mdot: false`, you must set `solver.mdot_total` [kg/s].

**Validation:** `contour.type: from_engine` with `sync.contour: false` is rejected.

Example — manual hot gas, engine contour and mdot still synced:

```yaml
sync:
  contour: true
  hot_gas_pc_bar: false
  hot_gas_tc_K: false
  hot_gas_gamma: false
  hot_gas_mol_mass_kg_kmol: false
  hot_gas_c_star_m_s: false
  hot_gas_bartz_correction: false
  of_ratio: true
  mdot: true
```

---

### `channels`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `count` | int | — | > 0 | Number of channels around circumference |
| `start_x` | float | null | Axial start [m]; default = contour start |
| `stop_x` | float | null | Axial stop [m]; default = contour end |
| `inner_wall_thickness` | ProfileSpec | 0.8e-3 | Hot-side wall thickness [m] |
| `height` | ProfileSpec | 2.0e-3 | Channel height [m] |
| `rib` | object | — | Rib configuration |
| `helix` | object | — | Helix / spiral configuration |
| `min_channel_width` | float | 0.4e-3 | LPBF manufacturability guard [m] |

#### `channels.rib`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `"fixed_width"` | `fixed_width` or `variable` |
| `width` | ProfileSpec | 1.0e-3 | Rib width [m]; scalar if fixed, profile if variable |

With `fixed_width`, channel width follows local circumference automatically.

#### `channels.helix`

Helix angle β measured from the **axial** direction [deg]: 0 = straight,
constant β = spiral, breakpoints = axial ↔ spiral switching.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `profile` | ProfileSpec | 0.0 | Helix angle β(x) [deg] |
| `interp` | string | `"pchip"` | `pchip` or `linear` |
| `handedness` | string | `"right"` | `right` or `left` |

---

### `geometry` (regen layout)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `n_stations` | int | 300 | Axial stations for layout/solver |
| `width_reference` | string | `"mid_height"` | `mid_height` or `floor` — where channel width is measured |

---

### `solver`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | true | Run thermal-hydraulic solve |
| `coolant` | string | `"NitrousOxide"` | CoolProp fluid name |
| `hot_gas` | object | — | Bartz hot-gas side properties |
| `wall` | object | — | Wall conduction settings |
| `mdot_total` | float | null | Fixed total coolant flow [kg/s] (all channels) |
| `mdot_from_engine` | bool | true | Legacy alias for `sync.mdot` |
| `of_ratio` | float | 4.0 | O/F for legacy mdot split when `mdot_total` unset |
| `coolant_side` | string | `"oxidizer"` | `oxidizer` or `fuel` — which engine mdot to use when syncing |
| `coolant_fraction` | float | null | Override: `mdot = fraction × mdot_total_engine` (e.g. H2 fuel regen) |
| `inlet` | object | — | Coolant inlet boundary condition |
| `roughness` | float | 8e-6 | Wall roughness [m] |
| `curvature_enhancement` | bool | true | Helix curvature on HTC and friction |
| `max_iter_wall` | int | 80 | Wall temperature iteration limit |

#### `solver.hot_gas`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pc_bar` | float | 25 | Chamber pressure [bar] |
| `tc_K` | float | 2950 | Chamber temperature [K] |
| `gamma` | float | 1.22 | Ratio of specific heats |
| `mol_mass_kg_kmol` | float | 26 | Mean molecular weight [kg/kmol] |
| `mu_pa_s` | float | 9e-5 | Gas viscosity at chamber conditions [Pa·s] |
| `pr` | float | null | Prandtl number; default 4γ/(9γ−5) |
| `c_star_m_s` | float | 1580 | Ideal c* [m/s] |
| `bartz_correction` | float | 0.75 | Small-engine Bartz multiplier |

#### `solver.wall`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `material` | string | `"Inconel 718"` | Material label |
| `conductivity` | float \| `"inconel718"` | `"inconel718"` | Constant [W/m/K] or temperature-dependent fit |
| `max_wall_temp_K` | float | 1200 | Report warning threshold [K] |

#### `solver.inlet`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pressure_bar` | float | — | Inlet pressure [bar] |
| `temperature_K` | float | — | Inlet temperature [K] |
| `location` | string | `"nozzle_end"` | `nozzle_end` (counterflow) or `injector_end` (co-flow) |

---

### `export`

Controls artifacts written by the regen runner. When regen runs through RESA
reports, output goes to the engine report folder and `out_dir` is overridden.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `out_dir` | string | `"outputs"` | Output directory (standalone runs) |
| `channel` | int \| null | null | Export one channel for STL, STEP, centerlines, and 3D HTML (overrides per-format channel lists) |
| `stl` | bool | true | Binary STL of channel volumes [mm] |
| `stl_channels` | `"all"` \| int \| list[int] | `"all"` | Which channels to mesh for STL |
| `step` | bool | false | STEP export of channel solids [mm] |
| `step_channels` | `"all"` \| int \| list[int] | `"all"` | Which channels to include in STEP |
| `step_faceted` | bool | false | If true, export tessellated STL geometry instead of smooth B-spline surfaces |
| `centerlines_csv` | bool | true | Centreline CSV [mm] for CAD import |
| `centerlines_channels` | `"all"` \| int \| list[int] | `"all"` | Which channels to include in centreline CSV |
| `geometry_csv` | bool | true | Per-station layout table |
| `results_csv` | bool | true | Solver results table |
| `html_3d` | bool | true | Interactive 3D Plotly view |
| `html_3d_channels` | `"all"` \| int \| list[int] | `"all"` | Which channels to show in 3D HTML |
| `html_plots` | bool | true | Geometry + results dashboards |
| `color_3d_by` | string | `"T_wall_hot"` | Result column or `"channel"` for 3D colour |

Single-channel exports use filenames like `{tag}_channel_00_mm.step`;
multi-channel exports use `{tag}_channels_mm.step`.

Example — export only channel 0 everywhere:

```yaml
export:
  channel: 0
  step: true
```

Or per format only:

```yaml
export:
  step_channels: 0
  stl_channels: [0, 1]
```

Typical result columns for `color_3d_by`: `T_wall_hot`, `T_wall_cold`,
`T_cool`, `q_w_W_m2`, `p_cool_bar`, `v_m_s`, `channel`.

**Siemens NX:** Import via **File → Import → STEP**. Use **New Part** and
enable **Solids**. STEP files are written as a single AP214 part (not an
assembly) with **six smooth B-spline faces per channel** (four walls + two
end caps). Set `export.step_faceted: true` to revert to triangle-facet STEP.
If import still fails, try the matching STL file instead.

---

## Workflows

### Engine sizing only

```bash
python -m resa run    configs/e2_c1/design.yaml
python -m resa report configs/e2_c1/design.yaml
```

### Engine + regen campaign

```bash
python E2_Main_Analysis_Regen.py
# or
python -m resa report configs/e2_c1/design_regen.yaml
```

### Standalone regen (no engine)

```bash
python -m resa.regen_channels.run path/to/regen.yaml
python -m resa.regen_channels.diff configs/a.yaml configs/b.yaml --solve --html diff.html
```

Use `contour.type: parametric` or `points` for standalone runs.

### Compare two report folders

```bash
python -m resa diff out/E2-C1-ASBUILT_xxx out/E2-C1-HF02_yyy
```

---

## Report outputs

### Engine report (`out/<engine>_<hash>/`)

| File | Contents |
|------|----------|
| `report.md` | Key results with provenance, warnings, full config |
| `report.pdf` | Printable full analysis: inputs, results, static plots |
| `results.yaml` | Machine-readable scalars + provenance |
| `summary.csv` | One flat row for campaign rollup |
| `contour.{html,csv}` | Chamber contour and Mach distribution |
| `mach.html` | Quasi-1D Mach plot |
| `offdesign_*.{html,csv}` | Throttle / O/F / envelope sweeps |
| `config_resolved.yaml` | Composed config snapshot |

#### PDF report contents

Generated automatically when `matplotlib` and `reportlab` are installed
(`pip install -e ".[report]"`). The PDF includes:

1. **Cover** — engine name, mode, config hash, timestamp
2. **Key results** — provenance table (same as report.md)
3. **Analysis inputs** — propellants, operating/analyze point, chamber, cooling
4. **Combustion properties** — c*, Tc, gamma, MW at nominal O/F
5. **Uncertainty band** — table when `eta_cstar_tol` is set
6. **Off-design summary** — sweep ranges and extrema
7. **Regen summary** — heat load, dp, outlet state, sync flags (when configured)
8. **Figures** — one plot per page for readability:
   - Chamber contour and Mach distribution
   - Ox throttle, O/F sweep, operating envelope (when configured)
   - Regen geometry and thermal-hydraulic results (when configured)
9. **Appendix** — full resolved YAML config

### Regen artifacts (when `regen:` is configured)

Written to the same folder with prefix `<meta.name>_`:

| File | Contents |
|------|----------|
| `*_geometry.csv` | Channel layout per station |
| `*_results.csv` | Thermal-hydraulic results |
| `*_centerlines_mm.csv` | 3D centreline points [mm] (all channels) |
| `*_channel_NN_centerline_mm.csv` | Single-channel centreline CSV |
| `*_channels_mm.stl` | Watertight channel volume mesh (binary STL) |
| `*_channel_NN_mm.stl` | Single-channel STL |
| `*_channels_mm.step` | Channel solid as AP214 B-spline surfaces (6 faces/channel; requires `cadquery-ocp`) |
| `*_channel_NN_mm.step` | Single-channel smooth STEP (recommended for Siemens NX import) |
| `*_3d.html` | Interactive 3D view (all channels) |
| `*_channel_NN_3d.html` | Interactive 3D view (one channel) |
| `*_geometry_plots.html` | Layout dashboard |
| `*_results_plots.html` | Temperature, flux, pressure plots |

---

## Provenance tags

Reports label each quantity with how it was determined:

| Tag | Meaning |
|-----|---------|
| `input` | Given explicitly in config |
| `calculated` | Derived from other quantities |
| `optimized: max Isp` | O/F chosen by tool |
| `optimized: pe = p_amb` | Expansion ratio chosen by tool |
| `calculated (from mdots)` | O/F from measured flows (analyze) |
| `calculated (from exit dia)` | ε from measured exit diameter |

---

## Validation errors (common)

| Error | Cause |
|-------|-------|
| Unknown YAML key | Typo — schema uses strict mode |
| `give exactly one of operating_point / analyze_point` | Both or neither mode block |
| `analyze_point requires a geometry block` | Analyze mode without geometry |
| `contour.type=from_engine requires sync.contour=true` | Invalid opt-out combo |
| `sync.mdot=false requires solver.mdot_total` | Fixed mdot not specified |
| `channel layout exceeds 1 m circumference` | Cooling block units wrong |
| `table: give of plus ALL properties as lists` | Incomplete combustion table |
