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

The Formula (6.31) screen member was an exclusion for PR-08C.3b. Its frozen
rows (screen applicability, screen replay, screen directional closure) were
inherited verbatim by `docs/pr08c3c_ct008_screen_acceptance.md`, which is the
owning matrix for that member and extends the rows with the published-summary
ownership, the input-derived face-set contract, the per-face full validation,
and the all-surface inapplicable rejection.

Hard exclusions: PR-08C.3c (the Formula (6.31) screen member, owned above),
any change to the merged clear-spacing/transverse members beyond registry
composition, CT-002 through CT-007 mechanics, solver/formula changes (the
2023 nominal-capacity solve is invoked only through the retained kernel),
SLS/crack/fatigue/bridges, UI/report/manual/publication/persistence/
package/schema/workflow/version changes, F-020, rejected-head work.
