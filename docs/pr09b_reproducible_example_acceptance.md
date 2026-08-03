# PR-09B acceptance matrix: numerical methods and reproducible example

Base: `7512c3ed01e41100cee59893ce9beab381bec890`

Finding: F-036 only.

## Required publication contract

- The manual states the exact accepted plastic axial bracket, iteration cap,
  depth stopping rule, residual tolerance, reachability state and the fact that
  cap exhaustion is not an independent failure state.
- The manual states the exact accepted cracked-elastic residual norm, scaling,
  tolerance, iteration cap and singular-Jacobian failure state.
- The manual states the accepted applied-ray/chord selection rules and numerical
  bands used by the plotted plastic envelope.
- The manual states the accepted concrete-fatigue branch-and-bound defaults,
  certified gap and resource-limit failure state.
- The manual states that engineering calculations and verdicts use unrounded
  values; report formatting is presentation only.
- The app publishes a current-schema project JSON and a compact calculation pack
  for one complete reference project.
- Project provenance uses Sector's genuine current `source_revision`; the example
  name is retained only in ordinary project metadata.
- The project and pack identify the exact input hash and cover every main report
  section emitted by the example: conventions, section/materials, basis,
  actions, plastic capacity/utilisation, elastic response/cracking and
  provenance.
- An independent frozen oracle reconstructs the section directly from the saved
  inputs and checks key unrounded results, states and formulas without trusting
  candidate-produced result fields.

## Frozen reference project

- Section: centred 300 x 600 mm solid rectangle.
- Reinforcement: three 25 mm B550 bars at y = -250 mm and two 16 mm B550 bars at
  y = +250 mm; material ID `M1` is retained by every bar.
- Concrete: C40/50, DS/EN 1992-1-1:2005 + DK NA:2024 starting values, with the
  stored final factors controlling the calculation.
- Plastic case `PL-REF`: N = 0 kN, Mx = 180 kNm, My = 30 kNm; 15 degree envelope
  resolution without the duplicated 360 degree endpoint.
- Elastic case `EL-REF`: long-term (0, 60, 10) kN/kNm/kNm plus short-term
  (0, 30, 5), creep coefficient 3.0 and DK NA crack-width calculation.
- The exact saved project uses current schema version 23 and Sector version 0.91.

## Explicit exclusions

- No solver, formula, material law, report renderer or project schema change.
- No fatigue spectrum, shear, torsion, combined M-V-T, detailing or independent
  bridge example; those optional report families are deliberately disabled and
  therefore absent from this reference project's report.
- No report/manual layout or notation cleanup (PR-10), publication identity or
  PDF preflight work (PR-11), UI responsiveness (PR-12), CI changes (PR-13),
  packaging/signing work (PR-14), version change or v0.93 roadmap feature.
