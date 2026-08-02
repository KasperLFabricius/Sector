# PR-08D.3a.1 CT-010a successful reinforcement-fatigue acceptance

This candidate is a fresh implementation from accepted `main`, retained
application/solver payloads and the local Design Basis. No rejected CT-010
head is reused. Sector remains `0.91`.

| Boundary | Frozen acceptance |
| --- | --- |
| Dispatch | Three required controls are exact built-in Booleans before candidate dispatch. Disabled/absent output is inapplicable. Deferred invalid output requires genuine current validation errors, exact ordered inventory, exact `valid is False`, and complete invalid adapter replay. Every other payload containing `valid` fails closed before success-only geometry access. |
| Prepared/output join | Each output spectrum is joined by exact position and name to `prepared.spectra`; every solver state is joined by exact bin position, name, description and cycles to its prepared bin. Each assessment is joined by element position, ID, kind, fatigue-detail ID and diameter to aligned prepared properties. Cardinality/order drift fails. |
| Inventory | Exact ordered success inventory. Reinforcement-owned and reinforcement-only shared values replay exactly. Concrete-owned/mixed values are excluded only with recursive position, cardinality, order and concrete retained type pinned. |
| Input identity | Full SHA-256 numeric vectors bind complete original input, raw controls, descriptions/actions, geometry with original scalar types, concrete/material/catalog IDs, element assignments, details, basis, exact adapter signature and aligned preparation. Every vector leaf reaches every final. |
| Mechanics | From each matched `FatigueBinState`, independently reconstruct all stress levels/ranges, bond factor/method, S-N branch/life, log-domain damage, proof limit/utilisation, governing selectors, convergence and PASS/FAIL. Reported bin convergence must equal its matched state. |
| Provenance | Standard S-N details cite the selected fatigue edition; custom/imported details are project-defined/uncited and expose retained source text. Mild/tendon proof sources are distinct and kind-correct. Input, boundary, matched Elastic replay and aggregation remain uncited. |
| Aggregate | Separate utilisation, convergence and PASS/FAIL nodes exist for every assessment. Spectrum governing IDs and global governing spectrum/utilisation/convergence/status are reconstructed and reach the aggregate final. |
| Hostile closure | Exact type/order/cardinality, mapping-subclass, Boolean-lookalike, malformed-`valid`, identity/order/join, solver-state/report contradiction, stale/coherent reseal, source/unit/axis/dependency/final, geometry/material/description and convergence-masking probes fail closed. |

Excluded: retained invalid-member trace publication (PR-08D.3a.2), concrete
fatigue proof (CT-010b), CT-009/CT-009b, chord/off-util/biaxial and CT-002
sweep joins, activation/UI/report/manual/persistence/package/workflow/version,
solver/formula changes, PR-07 removals, F-020, v0.93 and rejected heads.
