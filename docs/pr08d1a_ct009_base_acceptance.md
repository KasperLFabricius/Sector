# PR-08D.1a CT-009 EN 1992-1-1:2004 base acceptance

This candidate is a fresh implementation from accepted `main`, retained
application/solver payloads and the local Design Basis. No rejected CT-009
head is reused. Sector remains `0.91`.

| Boundary | Frozen acceptance |
| --- | --- |
| Dispatch | The current elastic/Both crack-width branch is active only for exact built-in selector types, `EN 1992-1-1:2005`, edition `2004`, no DK NA and an available section. Building DK, bridge and 2023 selectors remain inactive. Retained sibling values outside this base method are inert, while their presence and concrete type stay pinned. |
| Members | Publish exactly long-term, short-term and aggregate members in that order for a finite reconstruction. A genuinely non-converged reconstruction publishes exactly one failed member. Uncracked or unreinforced sections publish explicit undefined/NOT APPLICABLE case and aggregate finals. |
| Input identity | Full SHA-256 vectors bind exact typed/order/cardinality identity for the Section, raw and resolved rings/elements, all duplicate geometry representations, material laws, selected concrete identity, complete material catalogs including descriptions, aligned assignments and all base-method controls. `Independent` retains separate positive area and diameter; `Area` and `Diameter` require their circular duplicate representations to agree. |
| Mechanics | Reconstruct the accepted elastic combined state, long-term cracking state, governing cracking factor, transformed properties and both crack cases from original inputs with retained low-level kernels. Material moduli come from the selected aligned material entries. Candidate selectors, governing state and crack payloads are never trusted. |
| Outputs | Require the exact ordered CT-009 elastic inventory and recursively exact values/types/order/cardinality for transformed properties, long/short crack payloads, every candidate row and the retained crack aggregate. Every advertised output leaf is independently reconstructed and reaches a final. Crack limits, utilisation and verdict are absent. |
| Units | Actions use kN/kNm; candidate stresses use MPa; concrete-reference plane `q0` uses kN/m2 and `qx`/`qy` use kN/m3; area, length, strain and transformed second moments use m2, m/mm, scalar and m4 respectively. |
| Provenance | Effective-area, mean-strain, close/wide spacing and crack-width mechanics cite the local `DS/EN 1992-1-1:2004 + A1:2014 + AC:2010` clauses. Input, geometry, elastic replay, boundary validation and governing selection remain uncited project/input evidence. |
| Failure first | Applicability and original-input reconstruction precede untrusted candidate numerics. A failed solver requires the exact retained INVALID crack aggregate, publishes no resistance/utilisation/verdict or fabricated finite value, and does not traverse arbitrary failure-only numerical values. |
| Hostile closure | Reject missing, extra, reordered, duplicated, type-changed, non-finite or stale retained identity/output data; mismatched duplicate geometry; changed catalog descriptions/material IDs; changed candidate leaves; unknown owned outputs; coherent reseals; and source/unit/axis/dependency/final tampering. |

Excluded: building DK and bridge 2004 branches, CT-009b 2023, CT-010b,
chord/off-util/biaxial and CT-002 joins, activation/UI/report/manual/persistence/
package/workflow/version, solver/formula changes, PR-07 removals, F-020,
v0.93 and every rejected head.
