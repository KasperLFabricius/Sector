# PR-08D.1a CT-009 EN 1992-1-1:2004 base acceptance

This replacement is implemented independently from accepted `main`, the retained
application/solver payloads, accepted tests, and the local Design Basis. Rejected
CT-009 heads are negative evidence only. Sector remains `0.91`.

| Boundary | Frozen acceptance |
| --- | --- |
| Applicability | Emit this family only for built-in selector types and the exact tuple Elastic/Both, crack enabled, `EN 1992-1-1:2005`, edition `2004`, and no DK NA. Type-valid selector tuples for another branch are inactive. `sls_member` and `sls_tendon_xi` must remain present with their current concrete types, but their values are inert here. |
| Geometry and materials | Require the exact ordered current bar/tendon record schema. Raw tuples, records, resolved `Section` geometry, circular duplicates, element IDs, assigned catalogue IDs, and reconstructed material laws must agree exactly. Area and diameter are independently positive in `Independent` mode. Complete catalogue identity includes descriptions and the selected concrete identity. |
| Inputs | Bind exact type, order, cardinality, dtype, value, and resolved immutable-block identity for every base-method input. Excluded fatigue-detail values and the two branch-only crack controls retain only concrete type. Missing, duplicate, reordered, unknown, non-finite, stale, or silently ignored active representations are rejected. |
| Mechanics | Independently reconstruct combined elastic response, sustained cracking, peak cracking, governing state, transformed properties, and long/short crack cases from original inputs through retained low-level kernels. Candidate state, selector, result, and governing element are never trusted. |
| Successful output | Require the exact ordered crack-owned surface and recursively exact replayed values. Also bind the complete recursive presence, insertion order, cardinality, key identity, and concrete leaf/container types of every non-owned successful sibling; sibling values remain inert. Every advertised crack field is independently reconstructed and reaches its final. Crack limits, utilisation, status, resistance, and verdict fields are not part of this method and are rejected if introduced as crack-owned output. |
| Failed output | Establish applicability and non-convergence before reading failure-only numerics. Require the exact retained crack-owned failure inventory, exact `converged is False`, and exact INVALID aggregate. Bind the complete output structure while keeping arbitrary failure-only numeric values inert. Publish one failed final and no fabricated engineering value or verdict. |
| Members and states | Successful reconstruction emits long-term, short-term, then aggregate. Uncracked or unreinforced cases emit explicit undefined case/aggregate finals. Non-convergence emits one failed member. Finite, undefined, and failed are the only final states; genuine positive infinity is retained only where a reconstructed intermediate is unbounded. |
| Units and source | Actions are kN/kNm; reinforcement stress MPa; concrete-reference plane is kN/m2 and kN/m3; properties are m2/m/m4; crack quantities are mm or scalar. Effective area, mean strain, close/wide spacing, and crack width cite the exact local `DS/EN 1992-1-1:2004 + A1:2014 + AC:2010` clauses. Replay, boundary, geometry, selection, and inputs remain project/input sourced and uncited. |
| Hostile closure | Adversarial coverage mutates every owned output, nested candidate leaves, complete identities, duplicate geometry, catalogue descriptions/IDs, success sibling structure, failed inventories, units, sources, axes, dependencies, finals, and coherent downstream reseals. Regressions include every defect class exposed on prior CT-009 candidates. |

Excluded: building DK and bridge 2004 branches, EN 1992-1-1:2023,
concrete fatigue, chord/off-util/biaxial and CT-002 joins, activation/UI/report/
manual/persistence/package/workflow/version wiring, solver/formula changes,
PR-07 removals, F-020, v0.93, and all rejected heads.
