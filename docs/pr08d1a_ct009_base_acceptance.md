# PR-08D.1a CT-009 EN 1992-1-1:2004 base acceptance

This is a fresh implementation from accepted `main`, retained application and
solver payloads, and the local Design Basis. No rejected CT-009 head is reused.
Sector remains `0.91`.

| Boundary | Frozen acceptance |
| --- | --- |
| Applicability | The family exists only for exact current built-in selector types and the tuple Elastic/Both, crack enabled, `EN 1992-1-1:2005`, edition `2004`, no DK NA, and an available section. Every other type-valid code/edition/DK tuple is inactive, including a mismatched flag paired with the base code label. Active retained siblings outside this method keep exact presence and type while their values remain inert. |
| Current schema | Bar and tendon records require the exact ordered current key inventory before a trace can be built. Missing, extra, duplicated, reordered or type-incompatible records cannot be legitimised by a new seal. Raw tuples, records, the Section and resolved geometry must agree exactly. `Independent` keeps separate positive area and diameter; `Area` and `Diameter` require circular duplicates to agree. Empty reinforcement is valid and publishes NOT APPLICABLE where the retained kernels do. |
| Input identity | Complete SHA-256 vectors bind exact typed/order/cardinality identity for Section geometry, raw and resolved rings/elements, material laws, selected concrete identity, complete material catalogs including descriptions, aligned assignments and every base-method control. The inert fatigue-detail, member and 2023 tendon-ratio values contribute their exact retained concrete type. Every vector word reaches each final. |
| Mechanics | Reconstruct the combined elastic state, sustained cracking state, governing cracking factor, transformed properties and long/short crack cases from original inputs with retained low-level kernels. Element moduli resolve through exact selected catalog IDs and aligned entries. Candidate-selected states, governing indices and results are never trusted. |
| Successful output | Require the exact ordered crack-owned elastic surface and recursively exact values, types, order and cardinality for both transformed-property blocks, long/short crack payloads, every candidate row and the aggregate. Every advertised leaf and every used intermediate reaches a final. Crack limits, utilisation and verdict are excluded. |
| Failed output | Determine applicability and genuine non-convergence before untrusted candidate numerics. Require the exact ordered current crack-owned failure inventory, exact `converged is False`, and exact retained INVALID aggregate; the retained failure-only property/numeric values are not traversed. Missing or unknown crack-owned fields, including any utilisation, status or verdict, are rejected. Unrelated failure-only numeric values remain inert while their structure stays pinned; no fabricated resistance, utilisation, verdict or finite substitute is published. |
| Members and states | Finite reconstruction publishes exactly long-term, short-term and aggregate members in that order. Uncracked/unreinforced dispositions publish explicit undefined case and aggregate finals. Non-convergence publishes one failed member. Finite, undefined and failed are the only final states; a genuine unbounded cracking factor remains an explicit positive-infinity intermediate. |
| Units and provenance | Actions use kN/kNm; reinforcement stress MPa; the concrete-reference `q0` uses kN/m2 and `qx`/`qy` use kN/m3; transformed second moments use m4. Effective area, mean strain, close/wide spacing and crack width cite exact clauses in local `DS/EN 1992-1-1:2004 + A1:2014 + AC:2010`; input, geometry, elastic replay, boundary checking and selection remain uncited. |
| Hostile closure | Reject stale/unknown/reordered schema and output surfaces, non-finite active inputs, geometry/material/catalog/description/ID drift, mismatched duplicate representations, candidate-leaf changes, coherent reseals and source/unit/axis/dependency/final tampering. Regression coverage includes every defect found on all earlier CT-009 candidates. |

Excluded: building DK and bridge 2004 branches, CT-009b 2023, CT-010b,
chord/off-util/biaxial and CT-002 joins, activation/UI/report/manual/persistence/
package/workflow/version, solver/formula changes, PR-07 removals, F-020,
v0.93 and every rejected head.
