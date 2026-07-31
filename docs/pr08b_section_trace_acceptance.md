# PR-08B section-trace acceptance map
This map freezes the CT-002 through CT-005 recovery scope on the accepted
PR-08A trace core. Sector remains version 0.91 and these builders remain
unpublished until PR-08E.
| Family member | Required identity and cardinality | Required closure and state |
| --- | --- | --- |
| CT-002 plastic capacity | Exactly one selected-context member. Method is the one common selected EC2 edition, `mixed-standard-project-material-section-solve` for cross-edition or standard/project mixtures, or `user-defined-material-section-solve` when every law is project-defined. | Exact ordered rings, every bar/tendon coordinate and area, every assigned constitutive law, applied action, selected solver state, curvature, axial equilibrium, compression resultant, lever arm, and both moment components. Final is finite or explicit `failed`. |
| CT-003 radial utilisation | Exactly one member whenever radial utilisation is retained, independent of CT-002. Method is `sector-radial-envelope-intersection`. | Applied biaxial demand and every ordered envelope vertex. Finite utilisation stays finite; a missed ray is explicit `positive_infinity`; malformed solver output is explicit `undefined` or `failed`. |
| CT-004 N-M interaction | Exactly two members whenever interaction output is retained: axis `x` and axis `y`, each with the exact CT-002 material-method identity. Neither axis may mask the other. | Exact section/material closure and every ordered axial/moment boundary pair for that axis. Final is finite or explicit `failed`. |
| CT-005 elastic equilibrium | Exactly one selected-context member. Method is `sector-transformed-section-equilibrium`; no standards citation is attached to the numerical procedure. | Exact geometry, long/short action vectors, reference modulus, creep multiplier, short/long modular ratios, every aligned bar/tendon modulus and tendon prestrain/locked stress, and retained solver stresses. Final is finite or explicit `failed`. |
| CT-005 first cracking | Exactly one additional member whenever `lambda_cr` is retained, independent of equilibrium. Method is `sector-linear-elastic-scaling` or `sector-fixed-prestress-decompression`. | `fctm`, solver-owned tensile reachability leaves, geometry/material/action closure, and the exact finite or explicit infinite/undefined/failed outcome. |
Registry auditing is exact: calculation IDs, axes, methods, editions, source
sets, result states, and member count must match. Missing, duplicate,
wrong-axis, wrong-edition, masking, tampered, or stale evidence fails closed.
Project-defined material and numerical methods carry no invented standard
citation.
