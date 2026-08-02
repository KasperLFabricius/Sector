# PR-08D.3a.1 CT-010a successful reinforcement-fatigue acceptance

This replacement slice is derived from accepted `main`, the retained fatigue
adapter and solver payloads, and the local Design Basis. It does not reuse any
closed CT-010 candidate. Sector remains `0.91`.

| Boundary | Frozen acceptance |
| --- | --- |
| Dispatch | `fatigue_on`, `fatigue_check_steel` and `fatigue_check_concrete` are required exact built-in Booleans before output dispatch. A disabled or absent payload is inapplicable. A retained invalid payload is deferred only after exact ordered invalid inventory, exact `valid is False`, and complete adapter replay. Any other payload containing `valid` fails closed before geometry traversal. |
| Success inventory | Exact built-in ordered `SUCCESS_KEYS`; reinforcement-owned and reinforcement-only aggregate values replay exactly. Concrete-owned/mixed values are excluded only while their recursive position, cardinality, order and retained types stay pinned. |
| Input identity | Full SHA-256 identity vectors bind the complete original mapping, raw controls, spectrum descriptions, section coordinates/areas with concrete scalar types, concrete and reinforcement material/catalog identities, element assignments, fatigue details, basis, and aligned prepared boundary. Every vector leaf reaches each final. |
| Mechanics | Assessments join by spectrum/bin/element position and identity to retained `FatigueBinState`. Cycles, convergence, bond method/factor and all stress levels derive from the matched state. S-N branch/life, log damage, proof limits, governing selectors, convergence and PASS/FAIL are reconstructed independently. |
| Provenance | Standard S-N details cite the selected fatigue edition. Custom/imported S-N details are project-defined and uncited and expose their retained source text. Mild and tendon proof checks use distinct kind-correct clauses. Input, matched Elastic replay, boundary normalization and verdict aggregation remain correctly uncited. |
| Aggregate | Every assessment contributes distinct utilisation, convergence and PASS/FAIL nodes. Spectrum governing reinforcement identities, global governing spectrum/utilisation, global convergence and worst-first status are reconstructed. All evidence reaches the aggregate final. |
| Hostile closure | Missing/extra/reordered keys, mapping subclasses, Boolean lookalikes, malformed `valid` payloads, stale/coherent reseals, bin/state/value/source/unit/axis/dependency/final tamper, geometry type changes, material/detail/source/description changes, concrete sibling type/shape changes, convergence masking and inapplicable evidence fail closed. |

Explicit exclusions: retained invalid-member trace publication (PR-08D.3a.2),
concrete fatigue proof (CT-010b), CT-009/CT-009b, chord/off-util/biaxial and
CT-002 sweep joins, activation/UI/report/manual/persistence/package/workflow/
version changes, solver/formula changes, PR-07 removals, F-020, v0.93 work and
all rejected heads.
