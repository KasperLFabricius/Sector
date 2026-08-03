# PR-09B F-036 frozen acceptance

Base: `7512c3ed01e41100cee59893ce9beab381bec890` (Sector `0.91`).

## Required deliverables

1. The manual has a numerical-method appendix that states each actual algorithm,
   residual, tolerance, stopping rule and failure state without changing mechanics.
2. The in-app manual downloads one current-schema project JSON and one compact
   Markdown hand-calculation pack. The JSON includes every key in
   `project_io.SCALAR_KEYS` and every table in `project_io.PROJECT_TABLE_KEYS`.
3. Loading and calculating the JSON exercises every main report calculation
   chapter: clear spacing; Plastic; longitudinal and transverse detailing; shear;
   torsion; combined M-V-T; Elastic; cracking; grouped fatigue; and the three
   independent bridge calculations. The trace and QA appendices remain generated
   by their accepted publication paths.
4. A test-only frozen oracle, derived independently of the candidate module,
   records unrounded headline values, statuses and governing expressions. Tests
   compare a fresh app calculation and the hand pack with that oracle.

## Numerical-method inventory

- Plastic capacity: material-limit curvature, monotone axial-equilibrium
  bisection, `100` iterations maximum, depth-width stop
  `1e-12 * c_full`, residual `sum(F)-N`, force tolerance
  `1e-6 * max(1, abs(N))`, and explicit endpoint reachability.
- Elastic Stage II: uncracked linear initial guess followed by compression-zone
  Newton iteration, `100` iterations maximum, residual vector
  `[N_internal-N_target, Mx_internal-Mx_target, My_internal-My_target]`, and
  infinity-norm tolerance `1e-9 * max(1, max(abs(target)))`. Stage I is one
  linear solve. The long/short combined solve retains LONG, RST1, TOTAL and DIF.
- Cracking: Stage-I load factor (or fixed-prestress decompression factor), Stage
  I/II routing, and tension-stiffening interpolation. Uncracked is genuinely not
  applicable for crack width; invalid solver states do not publish a width.
- Shared strut angle: `1501` uniformly spaced candidates across the entered band;
  minimise the worst dependent utilisation, then the sum, then lower `cot(theta)`.
- Concrete fatigue fibre: priority branch-and-bound with a conservative global
  upper damage bound, initial `4 x 4` boxes, depth limit `26`, box limit `200000`,
  and certified gap `1e-8 + 1e-3 * max(abs(best), 1e-12)`.
- Direct algebraic resistance/detailing/bridge checks do not claim iteration.

## Frozen worked project

- 400 x 600 mm solid C35 section; six bottom and two top B550 `phi20` bars.
- `PL-DEMO`: N = 0 kN, Mx = 90 kNm, My = 25 kNm, Vx = 80 kN,
  Vy = 0 kN, T = 20 kNm; minimum and transverse detailing selected.
- `EL-DEMO`: long Mx/My = 60/5 kNm and short Mx/My = 60/3 kNm;
  crack width selected.
- `S1/FAT-DEMO`: 100000 cycles, long Mx = 30 kNm and cyclic Mx = 20 kNm;
  every bar uses fatigue detail F1.
- Explicit clear-spacing, DK member methods and factors, base bridge method, and
  one finite row for brittle Method B, box-wall interaction and minimum crack
  reinforcement.

## Explicit exclusions

- No solver, formula, tolerance, schema, standard applicability, preset value,
  report layout, publication numbering, version, UI architecture or release change.
- The hand pack is reproducibility evidence for this declared example, not a
  compliance certificate or a second mechanics engine.
- PR-10 owns layout/numeric integrity; PR-11 owns global publication numbering and
  PDF preflight; PR-12 through PR-14 remain untouched.
