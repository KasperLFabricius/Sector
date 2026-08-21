# PR-M01 v0.95 measured dead-code cleanup acceptance

## Purpose and frozen base

PR-M01 is the owner-approved maintenance addendum requested after historical
PR-13 and PR-14 had already merged. Their recorded order is therefore left
unchanged. PR-M01 follows PR-A10 and must merge before G1.

- exact base: `2e91bbcbe979a0debc0f7d8c07891c13a0d3e77f`
- exact base tree: `5b98b9e6c937a9c6c4bbba1c6f36d6ad1bc70883`
- product version: Sector 0.94
- project schema: 26

## Removal boundary

The slice removes exactly these six functions:

| Module | Removed function | Current replacement path |
|---|---|---|
| `app.fatigue_inputs` | `spectrum_signature` | live state uses `sector_app._fatigue_spectrum_signature`; catalogue identity remains `catalog_signature` |
| `app.load_cases` | `table_from_records` | project loading and callers use `normalise_table` / `active_table` |
| `app.manual` | `manual_publication_parts` | issued content uses `manual_published_item_parts` |
| `app.report_equation_contract` | `_calculation_relation` | live catalogue entries use `_relation` or `_result` |
| `app.result_presentation` | `required_chord_candidates` | live combined presentation is built by `combined_physical_components` and the retained fallback helper |
| `sector.serviceability` | `_direct_tension_effective_area_2023` | the crack solver consumes `_direct_tension_area_2023` and its typed retained evidence |

At the frozen base, an exact whole-tree identifier search returned one match for
each name: its own definition. There was no import, call, test reference, string
lookup, `__all__` entry, `sector.__init__` export, entry point, project-schema
field or serialised key using any removed name. The six frozen source blobs are
recorded in the machine-readable programme fixture.

## Retained measurement and proof

- production change: six functions and 72 production lines removed; zero
  production lines added;
- runtime callers removed: zero;
- public `sector` package exports removed: zero;
- schema fields, report fields and user controls removed: zero;
- no cache, solver, equation, design-basis, status, UI, report or package
  behaviour changes.

Static proof consists of the exact-base identifier inventory, the post-change
absence check, Python compilation, Ruff, strict mypy and `git diff --check`.
Dynamic proof runs the directly affected fatigue-input, load-case, manual,
report-equation, result-presentation and serviceability/crack test modules. G1
still owns the complete repository and packaged qualification.

## Exclusions

This PR does not remove test-only APIs, generator/oracle assets, constants,
decommissioning guards, compatibility fields, dynamically dispatched report
methods or anything reported only by heuristic unused-code scanning. It does not
change Sector 0.94, schema 26, selectable standards, engineering results,
published wording, status vocabulary or the release process.
