# PR-06 v0.96 gamma_V acceptance

## Exact base and bounded scope

- Base commit: `cc7eff84a754b5ea18281e1a5fe9c9e743fed1a9`
- Base tree: `9f9442dae05540001da3f269b573aef8a5687466`
- Product version retained by this PR: 0.95
- Project schema before this PR: 26
- Selected standard route: DS/EN 1992-1-1:2023

PR-06 replaces the fixed `gamma_V = 1.40` constant in the existing 2023
concrete-shear-without-links calculation with a positive finite user input.
The default remains 1.40. The selected value is carried consistently through
the Streamlit input, solver request/result, saved project and applicable report
profiles.

This PR does not change the 2005 EN or DK-NA shear methods, shear-link
resistance, torsion, the combined shear/torsion check, the 2023 equations apart
from selecting `gamma_V`, the report-profile depth contract or the product
version.

## Standards contract

| Purpose | Reference | Sector treatment |
|---|---|---|
| Definition/default | DS/EN 1992-1-1:2023, 4.3.3 and Table 4.3 (NDP) | The input defaults to 1.40 and is described as project/standard-basis dependent, not forced. |
| Calculation | DS/EN 1992-1-1:2023, 8.2.2 | The selected value is used only by the implemented concrete shear resistance without shear reinforcement. |

The 2023 route remains a selectable published method. Sector does not infer
that it governs a Danish project; the user remains responsible for the
applicable project basis and selected value.

## Affected-surface matrix

| Surface | Required result | Objective evidence |
|---|---|---|
| Solver | A custom positive finite non-Boolean value scales the existing 2023 resistance formula; the emitted result contains that exact value. | Direct formula and dispatch tests. |
| Validation | Missing, Boolean, zero, negative and non-finite active values fail before a resistance or verdict is emitted. | Solver, capacity and Streamlit adversarial tests. |
| Route isolation | The input is inactive for 2005 EN, 2005 DK-NA, shear-link, torsion and combined routes. | Paired isolation tests with deliberately different values. |
| Streamlit | The control is visible and enabled only for active 2023 shear, defaults to 1.40, carries exact help references and invalidates stale results when changed. | AppTest/widget/state tests. |
| Project persistence | The selected value round-trips. Schemas 25 and 26 migrate with 1.40; malformed and future schemas remain fail-closed. | Schema migration, round-trip and invalid-input tests. |
| Brief report | When the 2023 shear result is reported, the complete effective input table includes the actual `gamma_V`. | Brief profile input-inventory and rendered-text tests. |
| Standard/Audit reports | Both profiles reproduce the same actual value used by the solver, with the exact definition and calculation references. | Cross-surface semantic and report tests. |
| Manual | Current user guidance explains the selectable value, 1.40 default, activation boundary and exact references. | Source/text/render tests. |
| Version | Sector remains 0.95. | Version guard. |

## Adversarial cases

1. `gamma_V = 1.25` changes the 2023 no-links resistance by the exact inverse
   factor relative to 1.40 and is emitted as 1.25.
2. `True`, `False`, `0`, negative values, `NaN`, positive infinity and a
   missing active value are rejected before calculation.
3. Changing `gamma_V` while using either 2005 shear route changes no result.
4. Changing `gamma_V` changes no torsion, shear-link or combined result.
5. A saved current-schema project retains the selected value exactly.
6. Each supported older schema loads with a deterministic 1.40 default unless
   it already has a valid migrated value.
7. Brief, Standard and Audit agree with the solver value; Brief retains it as
   an effective calculation input without adding a worked result chain.
8. The UI, manual and reports distinguish the Table 4.3 definition/default
   reference from the 8.2.2 calculation reference.

## Closing evidence

The final candidate must record its exact head and tree, pass the new
adversarial cases and directly affected existing tests, compile cleanly, pass
targeted Ruff checks and retain product version 0.95. Any change after the
exact-head review invalidates that review receipt.
