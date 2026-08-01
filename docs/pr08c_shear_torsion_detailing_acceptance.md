# PR-08C shear, torsion, and detailing trace acceptance

This matrix is frozen before implementation. The slice owns only unpublished
solver traces and their focused tests. Sector remains `0.91`; combined M-V-T,
SLS/crack/fatigue/bridge families, UI/report/manual output, persistence,
packaging, workflow, publication, and CT-002 through CT-005 are excluded.

## Retained family matrix

| Family | Mandatory members and order | Method and source route | Finite result and verdict |
| --- | --- | --- | --- |
| CT-006 directional shear | Active components are ordered `vx`, then `vy`. `Vx` is checked about axis `y`; `Vy` about axis `x`. Each component has the exact face sequence returned from original actions and face input: selected negative or positive face, or negative then positive when automatic selection has zero associated centroid moment. Cardinality is therefore one or two members per active component and never comes from candidate output. | The selected 2005 base or 2005+DK-NA shear method is retained, including final entered material factors and sign conventions. Exact unchanged 2005 rules may carry the existing local 2004+A1/AC and DK-NA identities. The selectable 2023 implementation remains an uncited Sector project method because its local document is classified published-not-implemented. Geometry selection, lever-arm fallback/solve, face selection, and shared-angle selection are uncited project mechanics; edited inputs are input/project sources. | Each member reconstructs signed and absolute demand, tension reinforcement, effective depth/web width, axial/prestress state, `VRd,c`, and, when links exist, the retained shared cotangent intermediate, `VRd,s`, `VRd,max`, governing `VRd`, utilisation, and genuine `PASS`/`FAIL`. Face aggregation is independently replayed; no `Vx`/`Vy` interaction or cross-direction verdict is added. |
| CT-007 torsion | One ordered tube member for a valid single tube, or one member per valid user sub-rectangle in original order, followed by one aggregate member. An invalid/no-subdivision branch has one minimal failed aggregate member. The expected tube count, stiffness split, and aggregate order derive only from original geometry and subdivision inputs. | Retained EN 1992-1-1:2005 or DS/EN 1992-1-1:2005+DK NA:2024 thin-wall mechanics only. Base rules retain the local 2004+A1/AC identity; unchanged DK effectiveness rules retain the DK-NA identity. User `gamma_ct`, wall override, strut range, link data, subdivision, and assigned material laws remain exact input/project sources. No 2023 torsion method exists. | Every valid tube reconstructs its torque share, tube geometry, `TRd,s`, `TRd,max`, `TRd,c`, governing `TRd`, longitudinal steel, utilisation, and verdict at the retained shared member-angle intermediate. Every live sub-tube enters the solver-owned minimax selector, and the selected angle is referenced across each tube's downstream mechanics. The aggregate independently sums valid resistance/steel, selects the worst tube utilisation, and checks the advertised governing tube. Invalid geometry publishes no resistance, utilisation, or verdict. |
| CT-008 detailing | Subfamilies are independently mandatory when enabled, in this order: one longitudinal-minimum member per retained check; clear-spacing pairs in original nested element order; transverse checks in retained order (each active shear direction, then each torsion tube, preserving each check kind). A genuine not-assessed/invalid subfamily still contributes one minimal failed member so another detailing result cannot mask it. | Retained 2005, 2005+DK-NA, and selectable 2023 detailing mechanics are used without alteration. Exact unchanged 2005 rules may use the local 2004+A1/AC and DK-NA identities. All 2023 detailing rules remain uncited Sector project methods at the published-not-implemented boundary. Member/cut choice, automatic zone selection, gross-web screens, and editable detailing values are input/project sources. | Longitudinal members reconstruct provided/required area or nominal demand/resistance, utilisation when genuinely published, and verdict. Spacing members reconstruct centre distance, clear distance, required maximum term, margin, and verdict without inventing a utilisation. Transverse members reconstruct provided/required ratio or provided/maximum spacing, genuine utilisation where present, and exact `PASS`/`FAIL`/not-assessed semantics. |

## Exact trace closure

Every member has an independently declared family/member ID, context, axes,
method, branch, cardinality, result state, exact step order, dependencies,
quantity roles, unit dimensions, and full source/citation identity. Finite traces
bind every used input and authoritative intermediate to their own final. Shared
leaves are referenced by dependency rather than copied into parallel formula
chains.

Candidate demand, resistance, utilisation, status, governing face/tube, order,
and cardinality are compared with a reconstruction from original input using the
retained low-level mechanics. A selected strut angle must equal an independent
replay of the existing solver-owned selector over the original input band; merely
pinning an in-band candidate angle is insufficient. The selected intermediate is
then referenced by every dependent mechanic and never used to select a face,
tube, or verdict.

Failure/non-finite/unsupported branches are selected before result numerical
fields are parsed. They publish only identity, governing original inputs, the
explicit reason/state, and the final failed result. Promotion to finite must pass
the complete finite reconstruction. Inputs owned only by CT-002 through CT-005,
or by another inactive PR-08C subfamily, are not validated.

Focused adversarial evidence covers family/member/direction omission and
duplication; method/edition/source/citation/axis/sign/action/order/cardinality/
dependency drift; coherent result tamper; material/provenance and same-kind
source swaps; stale input/result/content seals; unrelated-family masking;
finite/failure promotion; non-finite intermediates; omitted failure-only numeric
fields; unit substitution; and reachability of every used leaf to its own final.
Independent test oracles start at original input, avoid production trace builders
and validators, and cover each distinct retained mathematical method, with
edition/NA/preset variants tabulated where the equations are unchanged.

## Readability decision

The combined slice fits one contract module, one builder module, two focused test
modules, and this matrix. The five logical subfamilies above share three registry
families and do not require a new generic trace foundation or any solver change.
