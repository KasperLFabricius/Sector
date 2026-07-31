# PR-08B.3 CT-002 acceptance freeze

This unpublished recovery slice starts at `18150c6b5860e109c165d3e11c33f39938ad4cde`
and keeps Sector at version 0.91. It adds only the selected plastic section-capacity
trace family, its exact registry declaration, and solver-adjacent retained evidence.

| Gate | Frozen acceptance |
| --- | --- |
| Selection and cardinality | `util_gov` is a required non-Boolean integer in range. `points`, `mx`, and `my` are non-empty, equally sized, and every point's retained moments equal the corresponding array member. Exact member index and count are registry axes. |
| Identity and provenance | One exact CT-002 calculation declares its context, method, source kinds, standard editions, project laws, allowed finite/failure states, step order, and dependency graph. |
| Solver evidence | The selected point, both capacity arrays, requested and achieved axial action, tolerance/residual/convergence, curvature and neutral-axis terms, concrete/bar/tendon force and moment resultants, compression resultant, lever arm, governing resistance, utilisation, and final finite/failure result are reconstructable. |
| Dependency closure | Every used geometry coordinate/area, action, and solver-aligned concrete/bar/tendon law value reaches its material resultant and the final result through explicit dependencies. |
| Failure closure | Missing, duplicated, misaligned, non-finite, stale, tampered, wrong-member, wrong-edition, or dependency-drift evidence fails closed. Genuine solver non-convergence is an explicit failed result and is never replaced by another member. |
| Independent proof | A test oracle reconstructs representative CT-002 values without calling the production trace builder, and hostile mutations cover selection, masking, residual/convergence, array alignment, dependency omission, content tamper, and stale identity. |
| Exclusions | CT-003 and later families, elastic/cracking, shear, torsion, SLS, fatigue, bridge, UI, reports, manual, persistence, packaging, schema, workflow, and version changes remain out of scope. |

The review candidate is limited to 5-8 files. Approximately 1,500 net lines is
an architecture guard, not a formatting cap: the candidate keeps idiomatic
imports, whitespace, named construction, and explicit field maps, and reports
any honest excess. Focused tests plus compile/import, ASCII, base, and scope
guards must complete in under ten minutes.
