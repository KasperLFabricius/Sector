# PR-08C.3b CT-008 acceptance (longitudinal minimum reinforcement)

This matrix freezes the third CT-008 slice from retained main mechanics.
Sector remains `0.91`. It adds the longitudinal minimum-reinforcement member
to the existing `sector-ct-008-detailing-v1` registry (family
`ct-008-detailing`, merged clear-spacing and transverse-links members
unchanged). Every applicable member is independently mandatory; no member can
mask another. The Formula (6.31) shear-torsion minimum-reinforcement screen
member is the named next slice (PR-08C.3c); its frozen rows are preserved
verbatim below as an exclusion so that slice inherits them unchanged.

| Family or invariant | Frozen acceptance |
| --- | --- |
| Longitudinal applicability | The member exists exactly when `minimum_reinforcement_on` is true and a retained section exists (the retained gate before capacity checks; the case adapter has already ANDed the per-row `check_minimum_reinforcement` flag into the solver-level switch). The retained kernel's own NOT APPLICABLE scope-outs (2023 high compression with `compression_limit_kn`, compression-only 12.2(5)) and the Slab longitudinal-cut early return are legitimate finite evidence states with their exact retained reasons and shapes. |
| Longitudinal replay | Exact replay through the authoritative `detailing.minimum_reinforcement` dispatcher with the retained argument mapping (`section`, `bar_elements`, `bar_materials`, `concrete`, `edition = detailing_edition`, `fctm_mpa = sls_fctm`, `n_ed_tension_kn = P_pl`, `mx_ed_knm = Mx_pl`, `my_ed_knm = My_pl`, `member_type`, `cut_direction`). All three retained detailing editions are implemented methods: 2005-family `9.2.1.1(1) (9.1N)` area check (`as_min = max(0.26 fctm/fyk, 0.0013) bt d`), 2023 `12.2(2)(a)/(b)` strength checks including the pure-tension branch and the kernel-internal characteristic-plateau substitution and nominal-capacity solve. The DK NA edition adds its exact extra side-face limitation. Frozen output shapes in exact key order: the 2005 9-key return plus appended `member_type`, `cut_direction`, `modelled_reinforcement_direction` and the Slab in-place clause overwrite; the four 2023 return shapes including both `compression_limit_kn` placements; the Slab longitudinal-cut 12-key early return; the 23-key 2005 check rows and the 2023 row shapes exactly as built. Tension-face `fyk` is the retained minimum `fytk` over tension-face bars. |
| Longitudinal identity | Every bar's selected catalog `material_id` and every element id is tokenized into its evidence leaves (the accepted material-prefix idiom); the selected concrete identity likewise. The retained `material_ids`/`bar_ids` row fields must replay exactly. Same-law different-ID assignments produce different sealed bundles. A used 2023 concrete or bar material assignment can never produce finite evidence; the 2023 DETAILING edition with 2004-route materials is legitimate. Unknown editions, member types or cut directions fail closed. |
| Verdicts | The longitudinal PASS/FAIL/NOT ASSESSED/NOT APPLICABLE/INVALID statuses are the retained genuine provided-versus-required decisions published exactly with the established literal status encoding; finals are genuine member statuses. No fabricated numerics on scope-out, invalid or not-applicable branches. |
| Candidate and dependency closure | Exact ordered inventories at member and row layers; named excluded siblings are the merged clear-spacing/transverse members' surfaces (unchanged), the torsion `min_reinf` screen and its directional surfaces (PR-08C.3c below), CT-006/CT-007 retained payload members other than the bound leaves, and report/presentation rows. Every leaf (including bar record identity and material identity) reaches its member final through exact operand-level dependencies. Stale seal, resealed value/source/unit/axes/order and dependency-edge removal fail. Unrelated invalid data cannot mask a valid member in either direction. |

## Named next-slice exclusion - PR-08C.3c: the Formula (6.31) screen member

The following rows are frozen for the PR-08C.3c screen member and are
inherited by that slice verbatim; they are an exclusion for PR-08C.3b.

| Family or invariant | Frozen acceptance |
| --- | --- |
| Screen applicability | The screen member exists exactly when the retained capacity path publishes the `min_reinf` sibling: `torsion_on` with a retained section (uniaxial and directional dispatches alike). It is independent of the detailing flags and of CT-007 family applicability (the retained app publishes the screen even in shared-angle branches where CT-007 publishes no family). The three retained not-applicable branches (`subdivided (compound) section`, `no shear check`, `zero resistance`) are legitimate finite evidence states with the exact retained 2-key shape and reasons, selected before any candidate numerics are parsed. |
| Screen replay | The applicable branch replays the exact retained arithmetic from bound operands: `value = t_ed/trd_c + v_ed/vrd_c`, `ok = value <= 1 + 1e-9`, `solid = not holes`, with the frozen 9-key shape (`applicable`, `value`, `ok`, `t_ed`, `trd_c`, `v_ed`, `vrd_c`, `solid`, `model_2023`). Operand values (`t_ed`, `trd_c`, `v_ed`, `vrd_c`, `model_2023`) are named upstream-evidence leaves from the retained torsion/shear payloads (validated by the accepted CT-006/CT-007 families over the same result set where those families apply; publication activates CT-008 only alongside them); `solid` binds the retained holes input directly. |
| Screen directional closure | In the directional dispatch the top-level screen is the governing candidate's screen extended in place with `directional_status` and `governing_face`, beside the `directional_min_reinf_status` and `directional_min_reinf_governing_face` siblings, and each `directional_interactions[component]` carries its own per-component screen. The trace replays the retained governing selection exactly: per-face `(status, metric)` via the retained `_minimum_reinf_assessment` states (NOT RUN / NOT ASSESSED / INVALID / PASS / FAIL), `capacity.assessment_key` ordering, and `capacity.aggregate_assessment_status` across candidates, from bound per-face upstream screens. Unknown, missing, duplicate or reordered retained keys fail closed at every layer. |

Hard exclusions: PR-08C.3c (the Formula (6.31) screen member, rows above),
any change to the merged clear-spacing/transverse members beyond registry
composition, CT-002 through CT-007 mechanics, solver/formula changes (the
2023 nominal-capacity solve is invoked only through the retained kernel),
SLS/crack/fatigue/bridges, UI/report/manual/publication/persistence/
package/schema/workflow/version changes, F-020, rejected-head work.
