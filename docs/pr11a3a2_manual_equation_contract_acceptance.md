# PR-11A3a2 acceptance - manual equation semantic contracts

## Exact base and bounded purpose

- Exact accepted base: 3e05c71ebb65ddc3ea8a00f8d7f2f81fcfce2c5b.
- Base tree: 0fdd5a13c0228bf68e86cb90989a0c37594dc5a2.
- Base parent: d3e9769b227506cb34a3a78ffd859527ad45b417.
- Sector remains version 0.91.
- Family: non-visual symbol, unit, result, dimensional and dependency
  contracts for the 32 accepted Part C manual equations.
- The accepted location and source contracts remain authoritative. This slice
  cannot select an expression, location, number or source from a renderer,
  solver result or candidate-supplied identity.

No rejected or superseded head is reused. Current merged code and the live
manual block stream are the implementation source; the local Design Basis
identities remain those frozen by PR-11A3a1S.

## Canonical unit system

Publication terms use the explicit ASCII units MPa, mm, mm^2, 1/mm, N, N mm,
cycles, days and rad. Pure ratios, strains, coefficients, indices and
utilization values use 1. Action-state functions use case action; the Danish
all-action ratio uses matching action because each demand and resistance pair
must share its own force or moment dimension.

This unit inventory describes the equations before report/UI display
conversion. It changes no calculation input, solver unit or output precision.

## Frozen semantic inventory

| No. | Symbols | Results | Dimensional class | Numbered equation dependencies |
| --- | ---: | --- | --- | --- |
| C3-1 | 6 | concrete stress | stress law | none |
| C3-2 | 7 | steel stress, design strength, yield strain | stress and strain law | none |
| C3-3 | 11 | tendon strain, selected law, stress, design proof strength | strain and stress law | none |
| C4-1 | 11 | governing curvature | curvature selection | C3-1, C3-2, C3-3 |
| C5-1 | 6 | minimum area | area check | none |
| C5-2 | 3 | nominal resistance | moment check | none |
| C5-3 | 5 | provided tensile resistance | force check | none |
| C5-4 | 3 | clear distance | length check | none |
| C5-5 | 8 | provided and minimum link ratios | dimensionless ratio check | none |
| C5-6 | 3 | longitudinal and transverse spacing | length checks | none |
| C5-7 | 5 | torsion-link wall ratio | dimensionless ratio check | C5-5 |
| C7-1 | 10 | crack width and strain difference | crack-width relation | C7-2 |
| C7-2 | 10 | maximum crack spacing | length relation | none |
| C7-3 | 10 | crack width and curvature factor | crack-width relation | C7-4 |
| C7-4 | 9 | mean crack spacing | length relation | none |
| C8-1 | 6 | design stress range | stress-range relation | none |
| C8-2 | 3 | design detail range | stress relation | none |
| C8-3 | 6 | resistant cycles | cycle-life relation | C8-1, C8-2 |
| C8-4 | 4 | Miner damage | dimensionless damage check | C8-3 |
| C8-5 | 7 | 2005 concrete fatigue strength | stress relation | none |
| C8-6 | 7 | 2023 strength factors and fatigue strength | factors and stress relation | none |
| C8-7 | 4 | resistant cycles | cycle-life relation | C8-5, C8-6 |
| C8-8 | 2 | equivalent fatigue criterion | dimensionless fatigue check | C8-5, C8-6 |
| C9-1 | 9 | variable shear resistance | force relation | none |
| C9-2 | 6 | minimum shear resistance | force relation | none |
| C9-3 | 6 | shear span and axial-action factor | length and dimensionless factor | none |
| C9-4 | 11 | link and concrete-strut resistances | force relations | none |
| C9-5 | 8 | link-provided and strut stresses | stress relations | C5-5 |
| C10-1 | 11 | link and concrete-strut torsion resistances | moment relations | none |
| C10-2 | 4 | torsion-shear strut utilization | dimensionless interaction | C9-4, C10-1 |
| C11-1 | 4 | torsion-shear strut utilization | dimensionless interaction | C9-4, C10-1 |
| C11-2 | 2 | Danish all-action utilization | dimensionless interaction | C9-4, C9-5, C10-1 |

The catalogue freezes 207 symbol records, 46 result records and 21 ordered
dependency leaves. Every symbol and result freezes exact ASCII markup, meaning
and unit. C10-2 and C11-1 deliberately retain separate identities even though
their expression, result and dependencies are the same. The complete semantic
catalogue seal is
bf761eb9014419e5c42e6f04e0a0c05628bb21549d5f8abe0c76d9f4e433613b.

## Dependency closure

- Dependencies reference canonical semantic keys, are unique and never self
  referential, and the complete graph is acyclic.
- Crack-width equations explicitly depend on their numbered spacing equations,
  including the authored forward references.
- Concrete life and equivalent-action routes depend on both mutually exclusive
  edition strength equations. The renderer must later select the applicable
  route; this contract does not change edition applicability.
- The shared torsion/shear Formula (6.29) identities depend on the accepted
  shear-strut and torsion-strut resistance equations.
- The Danish general interaction retains both 2005 and 2023 shear alternatives
  plus torsion resistance without pretending they apply simultaneously.

## Failure and hostile closure

- Binding accepts only an exact tuple of 32 canonical sourced equations.
- Every expression digest, location identity and source record is independently
  revalidated before semantics are attached.
- Missing, duplicate, reordered, unknown, list-replaced, shape-shifted and
  valid-looking coherently changed catalogues fail closed.
- Every top-level field of every contract and every nested markup, meaning and
  unit field is mutation-tested.
- Unknown, duplicate, cyclic and self dependencies, unsupported units,
  non-ASCII strings and mutable container replacements fail validation.
- The module imports only Python standard library plus the two accepted manual
  equation predecessor contracts.

## Explicit exclusions

- No manual, PDF or Streamlit rendering and no visible equation block.
- No report-equation contract or report layout change.
- No formula, solver, material law, resistance, demand, utilization, verdict,
  standard applicability, source identity or numerical-result change.
- No figure/table numbering, captions, repeated units, grayscale work, shared
  style, PDF preflight, schema, persistence, workflow, package, signing,
  version, PR-12+, release or v0.93 work.
