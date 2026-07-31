# PR-08B.2 shared-contract acceptance map

PR-08B.2a is the generic trace-core foundation described below; the other accepted PR-08B.2 rows remain context only. Sector remains 0.91; CT-002 and later builders, numerical mechanics, UI, reports, persistence, packaging, and publication remain out of scope.

## PR-08B.2a exact per-step metadata matrix

This foundation slice adds one independently optional immutable metadata tuple. Each row is keyed by step ID and fixes that step's canonical quantity role plus its complete `TraceSource` identity: kind, method ID, edition, and citation document/clause/locator.

| Case | Legacy source/dependency outcome | Per-step metadata outcome |
| --- | --- | --- |
| No metadata declaration, including a simple context-free registry | Accept | Not opted in; accept unchanged |
| Complete rows in calculation step order with exact role/source values | Accept | Accept |
| Action-input and material-law role/source pairs exchanged and trace resealed | Accept because source set and graph are unchanged | Reject by both affected step IDs |
| Same-kind material sources exchanged, or project and standard material sources exchanged | Accept because source set and graph are unchanged | Reject by both affected step IDs |
| Standard edition, citation document, clause, or equation/table locator changed | Edition may already fail the legacy set; citation-only drift passes it | Reject the changed step exactly |
| Metadata row missing, duplicated, unknown/extra, or reordered | Not represented | Reject the declaration |

Step order, dependency graph, and per-step metadata remain separately optional. Opting into any one does not require either of the others.

| Contract | Accepted declaration | Required hostile closure |
| --- | --- | --- |
| Section context identity | Empty context remains `section` with no axes. Context order is irrelevant; context keys are injectively encoded in calculation IDs and axis names, while family-owned extra axis names remain unchanged. | Distinct raw keys cannot collide, and an extra/reserved axis cannot replace either a raw context key or its encoded axis identity. |
| Registry step contracts | Existing members with no step contract remain valid. Exact step order, dependency graph, and per-step role/source metadata are independently optional immutable tuples. | Duplicate, missing, unknown/extra, reordered, incomplete, or misassigned declarations and actual contract drift fail closed. |
| Material assignments | One immutable solver-law vector and material identity exists for concrete and for every geometry-aligned bar/tendon. Explicit per-element laws require exact, non-blank element/catalog identities and complete equality to the curve-aware catalog reconstruction after unit conversion. | Missing, duplicate, swapped, malformed, incomplete, or numerically different assignment evidence fails closed; built-in tendon curves ignore only fields that their solver law does not consume. |
| Provenance and method identity | Only an exact canonical edition law retains its local standard citation. Exact method IDs distinguish one common standard, cross-edition standards, mixed standard/project laws, and all-project laws. | Edited or forged named presets remain usable project laws without a standard citation; no material can inherit another material's edition or method identity. |
