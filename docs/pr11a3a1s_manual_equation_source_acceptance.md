# PR-11A3a1S acceptance - manual equation source provenance

## Exact base and bounded purpose

- Exact accepted base: `469b7463da1d2b0fce819099751c86cdc35356ec`.
- Base tree: `ecb9a2949d563d854da3dc0ea54703e7db6dd6c2`.
- Sector remains version `0.91`.
- Family: source classification and source text for the 32 accepted Part C
  manual equation locations only.
- The location contract is authoritative for expression identity and authored
  position. This slice cannot select an equation or source from a numerical law,
  solver result, renderer or candidate-supplied identity.

All rejected PR11 source/location heads remain negative evidence only. No code,
patch, commit, branch, rewrite or ancestry from them is reused.

## Local Design Basis identities

- `DS/EN 1992-1-1:2004 + A1:2014 + AC:2010` is the retained base identity.
- `DS/EN 1992-1-1 DK NA:2024` is the retained Danish national annex identity.
- `DS/EN 1992-1-1:2023` is locally published-not-implemented and is cited only
  for edition-specific methods Sector already retains; this slice makes no
  applicability or implementation claim beyond those methods.
- `DS/EN 1992-2:2005 + AC:2008` supplies the corrected concrete-fatigue route.
- Project-defined methods remain explicitly `Project-defined / uncited` and are
  never assigned an invented standard source.

No online standard, numerical-law equality or rejected catalogue is a source.

## Frozen source inventory

| No. | Kind | Exact retained authority |
| --- | --- | --- |
| C3-1 | standard | Base 3.1.7, Formula (3.17), Table 3.1; 2023 8.1.2(1), Formula (8.4) |
| C3-2 | project | Project-defined general Curve 3 mild-steel law |
| C3-3 | mixed | Project-defined total-strain composition; base 3.3.6 or 2023 5.3.3 selected tendon law |
| C4-1 | project | Project-defined first-material-limit capacity search |
| C5-1 | standard | Base 9.2.1.1(1), Formula (9.1N); Danish annex where selected |
| C5-2 | standard | 2023 12.2(2)(a), Formula (12.1) |
| C5-3 | standard | 2023 12.2(2)(b), Formula (12.2) |
| C5-4 | standard | Base 8.2(2); 2023 11.2(2) |
| C5-5 | standard | Base 9.2.2(5), Formulas (9.4), (9.5N); Danish (9.5N NA); 2023 (12.4) |
| C5-6 | standard | Base (9.6N), (9.8N) and slab branches; 2023 Tables 12.1/12.2 and 12.4.2 |
| C5-7 | standard | Base 9.2.3(2)/9.2.2(5); Danish (9.5N NA); 2023 (12.4), Table 12.1 item 2 |
| C7-1 | standard | Base 7.3.4, Formulas (7.8), (7.9) |
| C7-2 | standard | Base 7.3.4, Formulas (7.11), (7.14) |
| C7-3 | standard | 2023 9.2.3, Formulas (9.8), (9.9) |
| C7-4 | standard | 2023 9.2.3, Formulas (9.15)-(9.18) |
| C8-1 | mixed | Project-defined Elastic reconstruction; base 2.4.2.3/6.8.4(1) or 2023 10.2/Annex E fatigue action |
| C8-2 | mixed | Project-defined custom/imported characteristic range; Base 6.8.4, Tables 6.3N/6.4N or 2023 Annex E.5, Tables E.1/E.2 for edition presets |
| C8-3 | mixed | Project-defined custom/imported S-N relationship; Base 6.8.4, Tables 6.3N/6.4N or 2023 Annex E.5, Tables E.1/E.2 for edition presets |
| C8-4 | standard | Base 6.8.4; 2023 Annex E.5 Palmgren-Miner summation |
| C8-5 | standard | Base 3.1.6 and 6.8.7, Formula (6.76) |
| C8-6 | standard | 2023 5.1.6(1), Formula (5.3), and 10.5, Formula (10.5) |
| C8-7 | mixed | Project-defined user-defined Miner S-N relation; Bridge corrected 6.106 or 2023 E.5.3, Formulas (E.7)-(E.8) for standard Miner methods |
| C8-8 | standard | Base 6.8.7, Formula (6.72); 2023 E.4.3, Formula (E.2) |
| C9-1 | standard | Base 6.2.2(1), Formula (6.2a); Danish annex where selected |
| C9-2 | standard | Base 6.2.2(1), Formula (6.2b); Danish annex where selected |
| C9-3 | standard | 2023 8.2.2(3)-(4), Formulas (8.30), (8.31) |
| C9-4 | standard | Base 6.2.3(3), Formulas (6.8), (6.9); Danish 6.2.3(2)-(3) |
| C9-5 | standard | 2023 8.2.3(5), Formulas (8.42), (8.44) |
| C10-1 | standard | Base 6.3.2(1)/(4), Formulas (6.27), (6.30), and 6.2.3(3), Formula (6.8); Danish annex where selected |
| C10-2 | standard | Base 6.3.2(4), Formula (6.29) |
| C11-1 | standard | Base 6.3.2(4), Formula (6.29) |
| C11-2 | standard | Danish annex 6.3.2(6) |

The exact classification is 25 `standard`, 5 `mixed` and 2 `project` records.
Every record freezes ordinal, location key, public number, kind and complete
ASCII source text. The complete catalogue has one deterministic SHA-256 seal.

## Failure and hostile closure

- Missing, duplicate, reordered, unknown, shape-shifted and valid-looking
  coherently changed source catalogues fail closed.
- Every field of every source record is mutated independently.
- Source binding accepts only the exact 32 canonical located equations in tuple
  order and recomputes every expression digest before assigning a source.
- Mutated, stale, reordered, duplicated, non-ASCII and noncanonical located
  equations cannot inherit a canonical source.
- Standard records require a complete local document identity. Mixed records
  require both the project definition and a standard portion. Project records
  reject every standard document identity.
- The module imports only the accepted location contract and Python standard
  library; no manual renderer, solver, trace or report module may be imported.

## Explicit exclusions

- No symbol, unit, dimension, dependency, renderer or visible manual block.
- No report equation, PDF, Streamlit view, trace, solver, formula, resistance,
  demand, utilization, verdict, applicability or result change.
- No figure/table numbering, captions, repeated units, grayscale, shared style,
  PDF preflight, schema, persistence, workflow, package, signing, version,
  PR12+, release, trace-retirement implementation or v0.93 work.
