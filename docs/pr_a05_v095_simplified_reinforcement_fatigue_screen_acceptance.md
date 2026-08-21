# PR-A05a/PR-A05b v0.95 simplified reinforcement-fatigue screen acceptance

## Exact boundary

- Exact base: `3bc69d5c6623b5052b8e463edd605e393ce3fb42`.
- Product version remains `0.94`; project schema remains 26.
- Owner outcome: `OA095-004` - add a supported simplified
  reinforcement-fatigue screen before the existing detailed reinforcement
  fatigue assessment.
- Dependency: PR-A00b is merged. The PR-A05a/PR-A05b pair owns the complete
  screen mapping and its calculation, result, app, report and manual surfaces.
- Change family: one fatigue-screen result composed with the existing grouped
  reinforcement S-N/Miner and yield/proof calculation.

The unpublished monolithic candidate was resliced under D095-006 after two
distinct exact-head findings. PR-A05a owns the mapping, calculation,
application adapter, retained result, currentness token and interactive result
surface. PR-A05b follows on the accepted PR-A05a head and owns only Standard,
Audit, Brief and end-user-manual publication. Neither slice is a dormant
prerequisite: PR-A05a exposes the complete supported calculation in the running
application, while PR-A05b completes the frozen publication matrix.

This PR adds no selectable design basis, traffic model, load-combination
generator, global project verdict, certification claim or engineering-approval
claim. The engineer remains responsible for the selected basis and for supplying
the grouped basic and frequent cyclic actions.

## Standards and applicability boundary

The screen applies only to unchanged named Sector fatigue presets whose selected
fatigue basis belongs to the same standard generation. A custom/imported detail
is never reclassified from its numerical values.

For the first-generation routes, DS/EN 1992-1-1:2004 with A1:2014 and AC:2010,
6.8.6(1)-(2), permits a simplified stress-range verification for reinforcing
bars in tension. The recommended values are 70 MPa for unwelded bars and 35 MPa
for welded bars. DS/EN 1992-1-1 DK NA:2024 marks 6.8.6(1) unchanged, so the same
values apply to Sector's Danish first-generation route.

For Sector's already selectable published-2023 route, DS/EN 1992-1-1:2023,
10.4(1), gives detail- and diameter-dependent design stress-range limits for a
frequent cyclic load with no more than `1e8` cycles. These limits include the
fatigue action factor in the stress calculation. The route remains disclosed as
published without a Danish National Annex; this PR does not make it applicable
under Danish building regulation.

## Exact eligible mapping

`phi` is the retained element diameter. `D` is the user-entered mandrel diameter
for a named bent-bar preset. A row marked unsupported has no shortcut and keeps
the detailed S-N/Miner assessment.

| Selected route and unchanged named preset | Screen limit |
|---|---:|
| First generation - straight reinforcing bars | 70 MPa characteristic range |
| First generation - bent reinforcing bars | 70 MPa characteristic range |
| First generation - welded bars and fabrics | 35 MPa characteristic range |
| First generation - reinforcing-steel couplers | Unsupported |
| First generation - every prestressing preset | Unsupported |
| Published 2023 - straight reinforcing bars, `phi <= 12 mm` | 90 MPa design range |
| Published 2023 - straight reinforcing bars, `phi > 12 mm` | 73 MPa design range |
| Published 2023 - bent reinforcing bars, `phi <= 12 mm` | `90 * min(1, 0.35 + 0.026 D/phi)` MPa design range |
| Published 2023 - bent reinforcing bars, `phi > 12 mm` | `73 * min(1, 0.35 + 0.026 D/phi)` MPa design range |
| Published 2023 - tack-welded bars and fabrics, `phi <= 12 mm` | 40 MPa design range |
| Published 2023 - tack-welded bars and fabrics, `phi > 12 mm` | 30 MPa design range |
| Published 2023 - reinforcing-steel couplers | 19 MPa design range |
| Published 2023 - pretensioning | 95 MPa design range |
| Published 2023 - strand in plastic duct | 95 MPa design range |
| Published 2023 - tendon in plastic duct | 80 MPa design range |
| Published 2023 - curved tendon in steel duct | 55 MPa design range |
| Published 2023 - prestress anchorage/coupler | Unsupported |
| Any route - custom/imported detail | Unsupported |

Named preset identity includes the preset's standard-defining S-N values and
detail class. Existing catalogue normalization already changes an edited named
preset to `Custom / imported`; changing only the user-owned mandrel or mixed-bond
parameters does not change the named detail identity.

## Calculation contract

1. The screen is evaluated independently for each reinforcement element and
   each named spectrum after the existing mixed-bond correction.
2. A first-generation screen compares the largest retained characteristic
   stress range `abs(sigma_total - sigma_long)` with 70 MPa or 35 MPa.
3. A published-2023 screen compares the largest retained action-factored design
   range `abs(sigma_design_total - sigma_long)` with the mapped limit.
4. The inclusive relation is `range <= limit`. Exact equality therefore passes.
   The reported screen utilisation is `range / limit`.
5. Every grouped bin must converge and have a tensile endpoint for the screen to
   apply to that element. A compression-only or malformed result falls back to
   the detailed assessment rather than being called a screen failure.
6. For the published-2023 route, the sum of the positive retained bin cycles in
   one spectrum must be no greater than `1e8`. Exact equality remains eligible.
   Exceeding the cap falls back to the detailed assessment.
7. A screen within its limit emits `PASS - DETAILED CHECK NOT REQUIRED`. The
   screen ratio, not Miner damage, controls the reinforcement range criterion.
8. A supported screen above its limit emits `DETAILED CHECK REQUIRED`; it is not
   itself a fatigue failure. The existing S-N/Miner result controls instead.
9. An unsupported detail or inapplicable state emits `NOT APPLICABLE`; the
   existing S-N/Miner result controls instead.
10. Sector still calculates and retains the detailed S-N/Miner evidence in all
    three outcomes for transparency and fallback. It must not hide or relabel it.

## Independent checks and result composition

- The existing long-term and design-total yield/proof checks always remain
  independent. A passing simplified range screen cannot override their failure.
- The concrete fatigue result and bounded concrete search remain independent and
  are neither skipped nor reclassified by a reinforcement screen.
- If the screen passes, the element utilisation is the maximum of its screen
  utilisation and yield/proof utilisation. Otherwise it remains the maximum of
  Miner damage and yield/proof utilisation.
- Spectrum and overall fatigue status continue to compose the retained element,
  concrete and convergence results. No new project-wide status is introduced.
- Deterministic ordering and ties remain element order then bin order. Equality
  at the screen limit is a screen pass; equality between screen and yield/proof
  retains the screen as the range criterion without suppressing yield evidence.

## Application and publication contract

1. Reinforcement result rows show the screen outcome, mapped class/source,
   governing range, limit, ratio and governing bin alongside Miner and
   yield/proof evidence.
2. Detailed element output states whether the operand is characteristic or
   action-factored design range and why a shortcut is unavailable.
3. Standard, Audit and Brief fatigue publication state the screen outcome when
   reinforcement fatigue is enabled. Standard/Audit retain the governing
   operands and the existing detailed calculation evidence.
4. The manual describes the supported first-generation and 2023 mappings,
   cycle/tension boundaries and fallback. It does not call the screen a complete
   fatigue, bridge or code-compliance assessment.
5. Existing calculation references remain visible. The screen adds only its
   exact clause reference and does not replace the detailed S-N/Miner source.

## Acceptance matrix

| ID | Selected condition | Required result |
|---|---|---|
| A05-01 | First-generation unchanged straight or bent bar preset | 70 MPa characteristic-range screen. |
| A05-02 | First-generation unchanged welded preset | 35 MPa characteristic-range screen. |
| A05-03 | First-generation coupler or prestressing preset | `NOT APPLICABLE`; detailed result controls. |
| A05-04 | Published-2023 straight bar at `phi = 12 mm` / just above 12 mm | 90 MPa / 73 MPa design-range limits respectively. |
| A05-05 | Published-2023 bent bar | Diameter branch is selected first and the exact retained bend factor is applied once. |
| A05-06 | Published-2023 welded bar at `phi = 12 mm` / just above 12 mm | 40 MPa / 30 MPa design-range limits respectively. |
| A05-07 | Published-2023 mild coupler | 19 MPa design-range screen. |
| A05-08 | Published-2023 pretension, plastic strand, plastic tendon and curved steel-duct tendon | 95, 95, 80 and 55 MPa design-range screens respectively. |
| A05-09 | Published-2023 prestress anchorage/coupler | `NOT APPLICABLE`; detailed result controls. |
| A05-10 | Custom/imported detail whose numbers equal a standard preset | `NOT APPLICABLE`; values do not recreate provenance. |
| A05-11 | Eligible range is strictly below its limit | Screen passes and controls the range criterion. |
| A05-12 | Eligible range equals its limit exactly | Screen passes with utilisation exactly 1.0. |
| A05-13 | Eligible range is above its limit | `DETAILED CHECK REQUIRED`; existing Miner result controls. |
| A05-14 | Eligible detail has at least one compression-only bin | `NOT APPLICABLE`; detailed result controls. |
| A05-15 | Published-2023 total cycles equal / exceed `1e8` | Equality remains eligible; greater than `1e8` falls back. |
| A05-16 | A bin is unconverged or screen evidence is malformed | Screen is not used; existing invalid/convergence behavior remains fail closed. |
| A05-17 | Screen passes but yield/proof utilisation exceeds 1.0 | Reinforcement result fails on yield/proof stress. |
| A05-18 | Screen passes while concrete fatigue fails | Spectrum fails on the independent concrete result. |
| A05-19 | Screen passes | Detailed S-N life, Miner damage and source remain calculated and visible but do not determine the range criterion. |
| A05-20 | Inputs or retained results change | Existing fatigue signature/stale-result behavior prevents old screen evidence from being published as current. |
| A05-21 | UI, Standard, Audit, Brief and manual are inspected | Screen wording and operands agree; no global verdict, certification or engineering approval is emitted. |
| A05-22 | Repository scope is inspected | No schema/product bump, Results Overview redesign, hover, provenance, plastic-summary, unrelated manual cleanup, packaging or release work enters this PR. |

## Focused verification

- pure mapping tests for every row, diameter boundary, bent factor, basis/preset
  mismatch and custom fallback;
- core below/equal/above, tension, cycle-cap, convergence, ordering and
  independent yield/Miner composition tests;
- application-adapter tests proving exact preset and selected-basis propagation;
- presentation, Streamlit and Standard/Audit/Brief report tests for retained
  screen operands and fallback wording;
- manual/current-wording and product-identity guards; and
- release-policy Ruff, compile, ASCII, diff, exact-scope, product-version and
  schema guards; the existing strict-mypy policy ratchet remains unchanged.

PR-A05a closes the mapping, core, adapter, application-currentness and UI rows.
PR-A05b closes the report/manual portions of A05-21 without changing the
accepted calculation or interactive result.

The full suite, coverage, portable package and release qualification remain at
the governed G1/G2 gates under D095-002.

## Explicit exclusions

- No inferred traffic spectrum, load combination, action count or project
  applicability.
- No screen for an unsupported or custom/imported detail.
- No change to Elastic stresses, bond correction, S-N curves, Miner equations,
  concrete fatigue, yield/proof limits or partial-factor inputs.
- No omission of retained detailed evidence, even when the shortcut passes.
- No global fatigue/project verdict, certification or engineering approval.
- No PR-A06 through PR-A10 work, product-version bump, packaging or release.
