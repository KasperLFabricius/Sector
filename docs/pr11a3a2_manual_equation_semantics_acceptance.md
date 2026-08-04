# PR-11A3a2 acceptance - manual equation semantics

## Exact base and bounded purpose

- Exact accepted base: 8f687b0af00bc79748860cc5df9ccf9e451f793e.
- Base tree: ec15151579bf76a8e5cbfb41a426cfbd22719b9a.
- Sector remains version 0.91.
- Family: symbols, meanings, units, dimensional notes and direct equation uses
  for the 32 accepted Part C manual equations only.
- The accepted location and source contracts remain authoritative for equation
  identity, live expression identity and provenance. This slice cannot select
  or alter an equation, source, result or governing state.

All rejected and superseded PR11 heads remain negative evidence only. No code,
patch, commit, branch, rewrite or ancestry from them is reused.

## Frozen semantic inventory

The catalogue contains exactly 32 immutable records and 200 immutable symbol
rows. Each record pins ordinal, semantic key, public number, ordered
symbol/meaning/unit rows, one dimensional note and ordered direct uses.

| Equation | Symbol rows | Dimensional closure |
| --- | ---: | --- |
| C3-1 | 6 | MPa concrete stress from a dimensionless law |
| C3-2 | 7 | MPa modulus-strength relations and dimensionless strain |
| C3-3 | 11 | 1/m curvature times m gives strain; law returns MPa |
| C4-1 | 9 | Every material-limit quotient has unit 1/m |
| C5-1 | 6 | Dimensionless strength ratio times mm x mm gives mm2 |
| C5-2 | 3 | Two kNm functions at the same kN axial force |
| C5-3 | 4 | MPa x mm2 gives force on both sides |
| C5-4 | 3 | Every maximum branch is in mm |
| C5-5 | 8 | c retains MPa^(1/2); both link ratios are dimensionless |
| C5-6 | 3 | Every spacing branch is in mm |
| C5-7 | 5 | A_leg/(s t_ef) is dimensionless; uses C5-5 |
| C7-1 | 10 | Stress ratios give strain; spacing x strain gives mm |
| C7-2 | 10 | Both crack-spacing branches give mm |
| C7-3 | 9 | Dimensionless factors x spacing x strain gives mm |
| C7-4 | 9 | Calculated spacing and cap both give mm |
| C8-1 | 5 | Elastic action-to-stress mapping gives a range in MPa |
| C8-2 | 3 | MPa divided by a partial factor remains MPa |
| C8-3 | 5 | Dimensionless stress ratio power times N* gives cycles |
| C8-4 | 3 | Cycles/cycles gives dimensionless Miner damage |
| C8-5 | 7 | Literal 250 is MPa; result is MPa |
| C8-6 | 7 | Literal 40 is MPa; result is MPa |
| C8-7 | 4 | log10 acts on N_R/(1 cycle); both sides dimensionless |
| C8-8 | 2 | Equivalent-stress criterion is dimensionless |
| C9-1 | 9 | C_Rd,c retains MPa^(2/3); MPa x mm2 is published as kN |
| C9-2 | 6 | MPa x mm2 is published as kN |
| C9-3 | 6 | kNm/kN and d are m; k_vp is dimensionless |
| C9-4 | 11 | Link/strut areas x MPa are published as kN |
| C9-5 | 8 | Link and strut branches both compare MPa; uses C5-5 |
| C10-1 | 11 | Explicit mm/mm2 and m/m2 conversions publish kNm |
| C10-2 | 4 | Matched kNm and kN demand/resistance ratios; uses C10-1/C9-4 |
| C11-1 | 4 | Matched demand/resistance ratios; uses C10-2 |
| C11-2 | 2 | Each paired action and resistance has the same action unit |

The exact unit vocabulary is:

dimensionless, actions, cycles, days, degrees, MPa, MPa^(1/2), MPa^(2/3),
mm, mm2, m, m2, 1/m, kN and kNm.

Every unit is used by at least one retained symbol. Numerical literals with
physical units are stated in the dimensional notes rather than advertised as
symbols.

## Exact direct dependency graph

1. C5-7 -> C5-5
2. C7-1 -> C7-2
3. C7-3 -> C7-4
4. C8-3 -> C8-2
5. C8-3 -> C8-1
6. C8-4 -> C8-3
7. C9-5 -> C5-5
8. C10-2 -> C10-1
9. C10-2 -> C9-4
10. C11-1 -> C10-2

No other direct edge is admitted. C11-2 has no direct dependency. The graph is
acyclic even though the crack-width equations reference spacing equations that
appear later in authored order.

## Failure and hostile closure

- Semantic binding first revalidates all 32 sourced live expressions through
  the accepted source and location binders.
- Exact nested source and location dataclass types and every retained scalar
  field are validated before equality can be consulted; equality-spoofing
  objects and fields fail closed.
- Missing, duplicate, reordered, unknown, shape-shifted, stale-expression,
  changed-location, changed-source and foreign-type candidates fail closed.
- Every outer field of every semantic record is mutated independently.
- Every markup, meaning and unit field of all 200 nested symbols is mutated
  independently: 600 nested hostile cases.
- Exact separate seals pin mark/unit inventory, meanings, dimensional notes and
  the complete catalogue.
- The module imports only the accepted source contract and Python standard
  library. It cannot consult the manual renderer, report, solver or trace.

## Explicit exclusions

- No renderer, visible equation block, caption, cross-reference rendering,
  substitution, result row or style change; PR-11A3b owns those mechanics.
- No report equation, figure/table numbering, repeated units, grayscale change,
  shared publication style or PDF preflight.
- No solver, formula, source, resistance, demand, utilisation, verdict,
  applicability, trace, schema, persistence, workflow, package, signing,
  application version, PR12+, release, trace-retirement implementation or
  v0.93 work.
