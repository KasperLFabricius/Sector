# PR-08C.1 CT-006 acceptance matrix

This slice is unpublished and solver-owned. It adds no UI, report, persistence,
schema, workflow, package, or version activation. Sector remains 0.91.

| Family/member order | Retained method and authority | Required shape | Finite result semantics |
|---|---|---|---|
| `vx` directional shear, then `vy` directional shear | `EN 1992-1-1:2005`; canonical 2004+A1/AC rules retain that source. | Only positive-magnitude active inputs; physical axes are `vx -> y`, `vy -> x`. Candidate insertion order and cardinality must equal the original-input order. | Every required face publishes concrete demand, resistance, utilisation, concrete PASS/FAIL, and face PASS/FAIL. Links add `VRd,s`, `VRd,max`, `VRd`, linked utilisation and verdict. |
| Same two ordered members | `DS/EN 1992-1-1:2005 + DK NA:2024`; only DK `v_min` and DK `nu_v` values use their exact DK sources. | Face order is the retained `negative` then `positive` order when automatic zero-moment selection requires both; otherwise exactly one selected face. | DK value dependencies remain visible through `v_floor -> VRd,c -> concrete utilisation/verdict` and `VRd,max -> VRd -> linked utilisation/verdict`. |
| Same two ordered members | Retained 2023 solver method; local lifecycle is **published-not-implemented**, so its trace source is an uncited Sector project source. | Edition, physical axis, sign convention, face mode, link state, and branch are mandatory axes. | The retained 2023 fields are reconstructed but are not represented as an implemented standards claim. |

For linked faces with a closed checked plastic sweep, the retained longitudinal
chord representation is mandatory. `off_util` is reconstructed from original
inputs and the retained low-level plastic solve; `biaxial` is exactly
`off_util > 0.05`. Both the governing linked chord and every candidate chord are
checked. The member angle is an uncited Sector project selector, replayed as the
original 1,501-point minimax scan over the original band.

The direction aggregate is not a cross-direction interaction. It binds the exact
face cardinality, governing face, governing metric, and genuine aggregate
PASS/FAIL. Each direction is independently mandatory; another direction or an
unrelated trace family cannot replace it.

Authoritative validity is selected from original CT-006 inputs before reading
candidate numerical fields. A failed direction has only identity plus an explicit
failed final state. Omitted, changed, or non-finite failure-only candidate numbers
therefore cannot change its bytes. Promotion to finite necessarily traverses the
complete geometry, action, material, provenance, resistance, utilisation, chord,
and verdict reconstruction.

Focused acceptance includes independent numerical anchors for the base, DK, and
published-not-implemented 2023 variants, plus hostile controls for direction and
face identity/order/cardinality; finite/failure promotion; omitted failure fields;
coherent demand/resistance/utilisation/verdict/cot and paired chord tampering;
DK/base and same-kind source swaps; every declared operand edge; units; material
and provenance swaps; stale input/result/content seals; unrelated-input masking;
and reachability of every used shared leaf to its own final result.
