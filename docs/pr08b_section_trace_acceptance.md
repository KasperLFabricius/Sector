# PR-08B.2 shared-contract acceptance map

This unpublished slice extends the accepted geometry/action foundation only. Sector remains 0.91; CT-002 and later builders, numerical mechanics, UI, reports, persistence, packaging, and publication remain out of scope.

| Contract | Accepted declaration | Required hostile closure |
| --- | --- | --- |
| Section context identity | Empty context remains `section` with no axes. Context order is irrelevant; context keys are injectively encoded in calculation IDs and axis names, while family-owned extra axis names remain unchanged. | Distinct raw keys cannot collide, and an extra/reserved axis cannot replace either a raw context key or its encoded axis identity. |
| Registry step contracts | Existing members with no step contract remain valid. Exact step order and exact dependency graph are independently optional immutable tuples. | Duplicate steps/dependencies, missing or forward dependency IDs, wrong declared/actual order, and actual graph drift fail closed. |
| Material assignments | One immutable solver-law vector and material identity exists for concrete and for every geometry-aligned bar/tendon. Explicit per-element laws require exact, non-blank element/catalog identities and complete equality to the curve-aware catalog reconstruction after unit conversion. | Missing, duplicate, swapped, malformed, incomplete, or numerically different assignment evidence fails closed; built-in tendon curves ignore only fields that their solver law does not consume. |
| Provenance and method identity | Only an exact canonical edition law retains its local standard citation. Exact method IDs distinguish one common standard, cross-edition standards, mixed standard/project laws, and all-project laws. | Edited or forged named presets remain usable project laws without a standard citation; no material can inherit another material's edition or method identity. |
