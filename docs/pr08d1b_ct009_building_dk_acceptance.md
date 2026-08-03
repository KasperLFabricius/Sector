# PR-08D.1b CT-009 building-DK crack-width acceptance

This bounded replacement is derived from accepted `main`, retained application
payloads and low-level kernels, accepted tests, and the local Design Basis.
Rejected CT-009 heads are negative evidence only. Sector remains `0.91`.

| Boundary | Frozen acceptance |
| --- | --- |
| Applicability | Add only the exact `DS/EN 1992-1-1 + DK NA`, edition `2004`, `sls_dk_na is True` route. Exact Beam/Slab member identity is active; tendon presence is active; `sls_tendon_xi` remains type-pinned and value-inert for every 2004 route. All mismatched and deferred selector tuples remain inactive. |
| Identity | Preserve the accepted complete geometry, selected catalogue/material, assignment, and controls identities. Route citations and the DK fine-system member/tendon rule are computed intermediates depending directly on the complete sealed input identity. Same-law different IDs, missing identities, stale duplicates, and reordered or unknown records fail closed. |
| Mechanics | Reconstruct through the retained combined-elastic and crack kernels. Emit exact long-fine, short-fine, long-coarse, short-coarse, aggregate order. Fine effective height uses `(h-x)/3` only for Slab or prestressed members. Close-spacing `k3 = 3.4(25/c)^(2/3)` is cover-derived. Coarse area is centroid matched and coarse width is one half of the retained expression. No second mechanics engine is introduced. |
| Successful output | Require the exact owned insertion order and every public leaf, including both coarse payloads and the exact aggregate. Preserve complete recursive shape and concrete types of non-owned siblings while keeping their values inert. Every input, route choice, method selector, intermediate, candidate, and case reaches its own final. |
| Failed output | Determine applicability and solver failure before reading failure-only numerics. Require exact failed inventory, `converged is False`, INVALID aggregate, and independently reconstructed `crack_code`, `crack_edition`, and `crack_member`. Other failure-only numerics remain inert. Publish no fabricated crack width, resistance, utilisation, or verdict. |
| Sources | Unchanged rules cite local `DS/EN 1992-1-1:2004 + A1:2014 + AC:2010`. DK-changed fine/coarse area, cover coefficient, one-half width factor, and route cite local `DS/EN 1992-1-1 DK NA:2024 rev. 2024-02-01` clauses 7.3.2(3), 7.3.4(1), and 7.3.4(3). Selected route steps are input-derived, not independent citation roots. |
| States and verdict | Case and aggregate finals are finite or undefined; non-convergence is failed. Crack width remains an output-only quantity with no limit, resistance, utilisation, PASS/FAIL, compliance, or authority inference. The one-directional limitation remains explicit. |
| Hostile closure | Parameterized probes cover every owned success leaf; missing, unknown and reordered inventories; Beam/Slab/tendon selection; exact route/member dependencies; fine/coarse formulas and sources; same-typed failed metadata tampering; minimal failure numerics; coherent trace reseals; accepted base-route equality; and rejected ancestry. |

Excluded: bridge routes, EN 1992-1-1:2023 refined/direct tension, concrete
fatigue, chord/off-util/biaxial and CT-002 joins, activation/UI/report/manual/
persistence/package/workflow/version wiring, solver changes, PR-07 removals,
F-020, v0.93, and every rejected head.
