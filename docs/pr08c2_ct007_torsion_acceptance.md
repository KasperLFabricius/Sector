# PR-08C.2 CT-007 thin-wall torsion acceptance

This matrix freezes the unpublished torsion-only slice from retained main mechanics.
Sector remains `0.91`. Rejected PRs are defect evidence only, never implementation
sources.

| Family or invariant | Frozen acceptance |
| --- | --- |
| Applicability and load | One CT-007 calculation represents one active retained torsion-only load case. `torsion_on=false` or no retained section is not applicable. A live `combined_on` branch or `shear_on && shear_links` reinforced-shear companion is also explicitly not applicable because retained main then admits shear/chord/shared-interaction terms into the one member-angle objective; that coupled payload is deferred and publishes no CT-007 family. Shear without links remains applicable because it cannot enter the angle objective. The solver-facing `torsion_T` is the exact non-negative capacity magnitude; its load-case identity remains in context. Zero demand is a finite capacity-only branch, not an arbitrary-angle branch. |
| Members, order and cardinality | A non-subdivided section has exactly one tube. A valid subdivision has exactly the entered sub-rectangle order and cardinality; stiffness shares conserve `T_Ed`. The aggregate names the exact worst-utilisation tube, retains the primary tube at index zero, sums tube resistance and longitudinal demand, and takes the maximum tube utilisation. Missing tubes or components cannot be masked by the aggregate. |
| Original-input inventory | Every active branch binds concrete outline/holes, concrete law, selected capacity-steel ID and aligned catalog law, axial action and locked tendon force, torsion method/demand, link diameter/spacing/strength, cotangent bounds, tensile factor and DK detailing switch. Single-tube branches also bind entered `tef`, including zero; subdivided branches instead bind every ordered `(x,y,b,h)` and treat unused `tef` as inert. Unused shear, bending/plastic sweep, elastic, detailing and bridge inputs are inert. |
| Retained methods and lifecycle | Finite evidence covers the retained DS/EN 1992-1-1:2004+A1/AC base method and its DK NA:2024 variant. The exact local route is the current 2004 document plus retained A1/AC identity and DK NA. The 2023 document remains under `96_Published_Not_Implemented`; neither it nor a used 2023 concrete, capacity-steel or tendon assignment may produce finite CT-007 evidence. |
| Tube geometry | Reconstruct gross outer area/perimeter, entered or automatic effective thickness, hollow cap/user flags, centre-line area/perimeter, minimum dimension and validity through the retained topology and thin-wall kernels. Sub-tubes additionally bind entered dimensions, rectangle torsion constant, total stiffness and exact torque share. |
| Material and resistance mechanics | Reconstruct `fcd`, `fctk,0.05`, direct positive `gamma_ct`, `fctd`, `fywd`, longitudinal `fyd`, prestress/axial stress, `alpha_cw`, base or DK `nu`, closed-link area and ratio, `TRd,s`, `TRd,max`, governing `TRd`, cracking `TRd,c`, longitudinal `Asl,req`, angle and tube utilisation. The selected capacity material identity, not equality of numerical laws, owns steel provenance. Custom/project laws remain uncited project sources. |
| Selector and zero demand | Positive demand independently enumerates the retained 1,501-point minimax objective over the exact original bound order after normalising the band; ties use worst utilisation, sum and lower cotangent. With zero demand the retained resistance-optimum low-level selector is replayed exactly for each tube, including its no-link-area rule; candidate cotangent is never an input to either selection. |
| Candidate inventories | Exact ordered inventories are frozen at top, tube, primary and sub-tube layers. Every retained sibling is independently compared. `min_reinf`, shear-torsion `interaction`, directional interaction wrappers and combined/detailing siblings are named exclusions and are never parsed; removing or mutating them is trace-inert. Unknown, missing, duplicate or reordered retained keys fail closed. |
| Branching and verdicts | Applicability and finite/failed state are chosen from validated original inputs and authoritative low-level results before candidate numerics are parsed. Failed tube/partition/non-finite branches publish minimal failure evidence; failure-only candidate numerics are inert. Finite promotion requires the complete reconstruction. Each tube and the aggregate receive genuine demand/resistance PASS/FAIL; `Asl,req` is a demand quantity only because retained main has no provided longitudinal-torsion capacity verdict. |
| Dependency and provenance closure | Immutable scoped geometry/action/material/provenance blocks feed exact operand-level dependencies. Every emitted leaf reaches the aggregate final. Per-step quantity role, complete source/citation, order, dependency unit and result state are exact registry contracts. DK `nu_t` or the explicit DK detailing allowance alone carries its matching DK source; unchanged base rules retain base sources. Resealed value, source, unit, dependency, content and stale-seal changes fail. |

Hard exclusions are CT-006 changes, shear-torsion interaction, CT-008 minimum
reinforcement/spacing/detailing, CT-002 through CT-005 mechanics, SLS/crack/fatigue
and retained bridges, UI/report/manual/persistence/package/schema/workflow/version,
F-020, solver formula changes and all rejected-head work.

## Branch-specific completeness audit record (2026-08-01)

The frozen inventories were audited line by line against retained main.
`TOP_KEYS` equals the exact insertion order of the torsion payload built in
`_run_uniaxial_capacity_checks`; the directional dispatch only appends named
excluded `directional_*` siblings before publication. `TUBE_KEYS` and
`RESULT_KEYS` equal the return orders of `torsion.tube_properties` and
`capacity.tube_torsion`; `SUBTUBE_SUFFIX_KEYS` equals the sub-tube augmentation
order. Every input consumed by `capacity.build_torsion_context`,
`capacity.prestress_axial` and the applicability gate appears in the frozen
branch-specific input inventory and vice versa; the retained case adapter
guarantees the non-negative `torsion_T` magnitude the inventory freezes. The
shared-angle boundary was verified in the retained member-angle objective:
every non-tube objective term is gated on reinforced-shear link validity or
`combined_on`, including at zero shear demand, so those branches publish no
CT-007 family while shear without links cannot enter the objective. Direct
hostile controls exist for used 2023 concrete, capacity-steel and tendon
assignments; the retained torsion method registry structurally excludes 2023.

An independent adversarial review of the draft (six lenses, refute-by-default
verification) found and this candidate corrects: the finite-branch final step
now binds the genuine aggregate PASS/FAIL verdict instead of a constant; the
raw-versus-retained tendon comparison now uses the accepted CT-006 tolerance
so the lossy mm2 unit round-trip cannot fail valid prestressed inputs closed;
and the `subdivision-applied` step no longer declares a compound-outline
operand the retained value does not have. Coverage added on review findings:
a failing section (utilisation above one) pins FAIL verdicts end to end, the
directional Vx/Vy dispatch payloads validate with their excluded siblings
inert, axial action signs drive `sigma_cp`/`alpha_cw` in both directions,
entered-thickness override and hollow wall-cap identities close, the
reinforced-shear exclusion holds at zero shear demand, the base-method
detailing flag stays base-sourced and inert, zero-demand selection clamps to
a non-default band, failed bundles are asserted minimal, and sealed axes and
step-order tampers are rejected.
