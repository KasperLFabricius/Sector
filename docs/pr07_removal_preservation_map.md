# PR-07 product-reset removal and preservation map

This map fixes the implementation boundary for the v0.92 PR-07 product reset.
The governing acceptance contract is [Product identity](product_identity.md).
Sector's product version remains 0.91.

| Surface | Remove | Preserve |
|---|---|---|
| Core calculation | Compliance/conformance aggregates; crack-limit, stress-limit, exposure, decompression and combination acceptance; multidirectional crack overlay; generic multidirectional shear interaction and power sum; authority/approval rejection latches | Section solvers; ordinary crack width from section-solution longitudinal reinforcement stress; independent Vx and Vy resistance checks; genuine demand/resistance verdicts; positive finite custom coefficients as entered, including the distinct `gamma_ct` input for torsional cracking |
| Bridge calculations | Coverage/cardinality matrices, manager/project-basis routing, Danish cover calculator, bridge SLS acceptance and blocking unimplemented rows | Optional brittle Method B with a warning for incompatible Danish selections; box-wall shear/torsion; concrete compression fatigue; web/flange minimum crack reinforcement; direct crack-width numerical methods |
| Streamlit | Manager, asset-class, project-authority, approval, departure, coverage, cover-calculator, SLS-limit and required-combination controls | Calculation inputs first; direct method choices; action identity and user labels; assumptions/warnings; numerical results; stable widget/session-state migration |
| Project schema | All legacy project-schema migration/carry-over; deprecated compliance, authority, coverage, cover-calculator, multidirectional-interaction and SLS-acceptance fields | New current-schema geometry, materials, reinforcement and user cover geometry, action tables, solver inputs, method choices, custom numerical factors, provenance and integrity hashes; current-session result freshness/corruption protection |
| Publication/report | Global or aggregate compliance verdicts; output-only PASS/FAIL; approval/source workflows; coverage evidence and compliance fingerprints | App/source version, actual inputs, selected method/equation and citation, action identity, result freshness, numerical outputs, independent resistance checks |
| Manual/README/QA | Claims of code completeness, certification, approval or sign-off; superseded F-011/F-024/F-029 PR-07 plan | Transparent calculation-tool scope, user responsibility, reproducibility, warnings and retained numerical-method scope |
| Tests/fixtures/oracles | Tests that exist solely to enforce removed compliance routes, multidirectional overlays, legacy-schema migration or cover/authority workflows | Numerical benchmarks, current-schema integrity tests, custom-factor routing, ordinary combined-action crack regression, independent shear checks, report/manual/UI absence checks |

No future QA finding expands this product identity without explicit owner
direction.

Owner decision, 2026-07-29: Sector is unreleased. PR-07 intentionally provides
no compatibility with earlier app/project/schema versions; older files may be
rejected explicitly.
