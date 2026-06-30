# RESA — Rocket Engine Sizing & Analysis

Library-first rocket engine sizing and analysis. YAML in, typed results out,
self-contained report folders. Optional **RESA Studio** web UI for interactive
editing and previews.

**Config reference:** [docs/CONFIGURATION.md](docs/CONFIGURATION.md)  
**Studio UI:** [docs/STUDIO.md](docs/STUDIO.md)

## Quick start

```bash
pip install -e ".[report,dev]"

# Engine sizing (design mode)
python -m resa run    configs/projects/e2_c1/design.yaml
python -m resa run    configs/projects/E2-1A/design.yaml
python -m resa report configs/projects/e2_c1/design.yaml

# Campaigns (multi-config reports + rollups + diffs)
python -m resa campaign campaigns/e2_c1/e2.yaml
python -m resa campaign campaigns/e2_c1/e2_regen.yaml
python -m resa campaign campaigns/E2-1A/e2_1a.yaml
python -m resa campaign campaigns/EX15-1A/ex15_regen.yaml

# Legacy entry points
python E2_Main_Analysis.py          # E2-1A campaign
python E2_Main_Analysis_Regen.py    # E2-C1 regen campaign
```

### RESA Studio (web UI)

```bash
pip install -e ".[studio,report]"
python -m resa_studio
# → http://127.0.0.1:8000
```

Edit configs with live contour/cooling previews, run fast or full reports, compare
saved runs, and launch campaigns from the sidebar. See [docs/STUDIO.md](docs/STUDIO.md).

## Config layout

```
configs/
├── shared/                 propellants, chamber, cooling, CEA tables (global fragments)
├── ci/                     offline table configs for CI / golden tests
├── projects/               engine projects (each folder = one project)
│   ├── e2_c1/              project.yaml + design.yaml, asbuilt.yaml, …
│   ├── E2-1A/
│   └── ex15/
└── …

campaigns/                  campaign runner YAML (multi-config reports)
├── e2_c1/
│   ├── e2.yaml
│   └── e2_regen.yaml
├── E2-1A/
│   └── e2_1a.yaml
├── EX15-1A/
│   └── ex15_regen.yaml
└── ci_golden.yaml            CI / golden tests (table backend)
```

Engine configs support **file references** (`propellants: ../shared/...`) and
**inheritance** (`base: design.yaml`). See
[docs/CONFIGURATION.md](docs/CONFIGURATION.md) for every field.

## Two analysis modes

| Mode | Config block | Input | Output |
|------|--------------|-------|--------|
| **Design** | `operating_point` | Thrust, Pc, O/F, ε targets | Sized geometry + performance |
| **Analyze** | `analyze_point` + `geometry` | Measured throat/exit + mass flows | Calculated Pc, thrust, Isp |

Omit `of_ratio` → max-Isp O/F is found (needs combustion table over O/F).
Omit `eps` / `pe_bar` → optimum expansion at `p_amb`.

## Regen cooling

Attach a regen block to any engine config:

```yaml
base: design.yaml
regen: regen.yaml
```

The regen solver runs during report generation and writes geometry, thermal,
3D, and STL artifacts into the same output folder. RESA auto-syncs contour,
hot-gas properties, O/F, and coolant mdot from the engine run by default.
Opt out per parameter with the `sync:` block — documented in
[docs/CONFIGURATION.md#sync](docs/CONFIGURATION.md#sync).

Standalone regen (no engine):

```bash
python -m resa.regen_channels.run path/to/regen.yaml
```

## Commands

```bash
python -m resa run    configs/projects/e2_c1/design.yaml       # summary to stdout
python -m resa run    configs/projects/E2-1A/design.yaml
python -m resa report configs/projects/e2_c1/*.yaml           # report folders + rollup
python -m resa campaign campaigns/e2_c1/e2_regen.yaml
python -m resa campaign campaigns/E2-1A/e2_1a.yaml
python -m resa diff   out/A_xxx out/B_yyy             # compare two runs
pytest tests/                                         # CI golden suite (table backend)
```

## Report folder

```
out/<engine>_<config_hash>/
├── report.md                  human summary + provenance + warnings
├── report.pdf                 printable full analysis with plots
├── results.yaml               machine-readable results (+ off-design sweeps)
├── summary.csv                flat row (campaign rollup)
├── config_resolved.yaml       composed config snapshot
├── contour.{html,csv}         chamber geometry
├── mach.html                  Mach distribution
├── offdesign_*.{html,csv}     throttle / O/F / envelope (if configured)
└── <tag>_*.html/csv/stl/step   regen artifacts (if regen configured)
```

Every key result in `report.md` carries a **source** tag (`input`, `calculated`,
`optimized: …`) so assumptions never masquerade as outputs.

`report.pdf` is generated automatically when matplotlib and reportlab are
installed (`pip install -e ".[report]"`). It includes input tables, key results,
uncertainty and regen summaries, and static versions of all relevant plots.

## Design principles

1. **Config is the only source of truth** — physics modules take validated dataclasses, not raw YAML.
2. **Stages are pure functions** — no globals, no hidden state.
3. **One kernel per physics** — analyze mode and all off-design sweeps share the same evaluation kernel.
4. **Provenance travels with results** — every quantity is tagged in reports.
5. **Accuracy lives in tests** — golden regressions guard validated numbers.

## Project layout

```
resa/
├── config/           schema + YAML loader (refs, base inheritance, hash)
├── properties/       CoolProp fluids + combustion model
├── models/           thrust chamber, contour, off-design
├── regen_channels/   high-fidelity regen channel generator + solver
├── regen/            RESA ↔ regen integration bridge
├── pipeline.py       stage wiring + sanity checks
├── reporting/        plots, markdown report, PDF report
└── results.py        frozen result dataclasses + sweep serialization
resa_studio/          FastAPI UI (see docs/STUDIO.md)
frontend/public/      static SPA assets
docs/
├── CONFIGURATION.md  complete engine + regen config reference
└── STUDIO.md         web UI guide
campaigns/            multi-config batch YAML
tests/                pytest golden + unit suite
```

## Built-in sanity checks

Reports include warnings for:

- Flow separation risk (Summerfield criterion)
- Cooling channel fit at throat circumference
- Chamber L* feasibility
- Regen: bulk coolant saturation, wall temperature limit exceeded
- Sweep truncation outside combustion table range

## Status

- [x] Design + analyze modes through one shared kernel
- [x] O/F and ε optimization with provenance
- [x] Off-design: ox throttle, O/F sweep, 2-D envelope
- [x] Config inheritance, campaign rollup, run diff
- [x] η_c* uncertainty bands
- [x] High-fidelity regen channel solver + RESA integration
- [x] RESA Studio web UI (fast/full runs, previews, compare, campaigns)
- [x] MoC contour option (`chamber.contour: moc`)
