# Sector changelog

## Unreleased

## 0.91 - 2026-07-24

Sector 0.91 adds mixed reinforcement, directional shear, longitudinal detailing
and grouped fatigue workflows.

- Opened the user manual in a large in-context dialog so the current workspace
  and edited inputs remain visible and intact.
- Added stable bar and tendon IDs with area-, diameter- and independent-size
  definitions, plus material, fatigue-detail and group assignments.
- Added reinforcing- and prestressing-steel catalogues with per-element
  constitutive laws throughout plastic, elastic, crack-width and member checks.
  Material definitions, assignments and individual stress-strain curves remain
  traceable in the UI, project file and report.
- Replaced the single shear action with signed `Vx,Ed` and `Vy,Ed` inputs.
  Each direction is checked independently against its associated bending axis
  and faces. Sector does not claim a general biaxial shear interaction verdict.
- Added per-case longitudinal minimum-reinforcement checks for the 2005/DK NA
  and 2023 Eurocode methods, including resultant biaxial tension-zone geometry.
  Added a section-wide clear-spacing check with tendon-envelope opt-in and
  explicit lap/bundle review flags.
- Added grouped fatigue spectra using the cracked Elastic long-/short-action
  states, stable S-N detail IDs, verified 2005 and 2023 presets and complete
  user-entered partial factors. Authority declarations record VD/BN provenance
  and do not modify actions, cycle counts or resistances.
- Added reinforcing- and prestressing-steel S-N/Miner damage, yield/proof
  acceptance and same-fibre concrete compression fatigue. Results retain raw,
  bond-transformed and design stress ranges, solver convergence and a certified
  section-wide concrete-search bound.
- Added dedicated fatigue summaries and drill-down results, labelled
  colour-accessible section maps, S-N and cumulative-damage figures, complete
  PDF report evidence and matching manual guidance.
- Advanced project files through deterministic migrations for the richer
  element, material, shear, detailing and fatigue records.

Shear- and torsion-induced fatigue remain outside the implemented fatigue scope.
Plastic and Elastic remain solver names and do not prescribe a limit state.

## 0.90 - 2026-07-22

Sector 0.90 completes the interface and multi-case workflow review.

- Restricted the Streamlit service to the local computer and migrated point
  tables to Streamlit Components v2 with reliable state transport.
- Reduced unnecessary reruns, preserved input state across workspace navigation,
  and co-located section and material-law previews with their inputs.
- Replaced scalar actions with uniquely named Plastic/capacity and Elastic case
  tables, including descriptions and per-case stress/crack acceptance selections.
- Ran every case through the verified solvers and added combined summaries plus
  individual-case navigation in the UI and PDF report.
- Added complete multi-case report chapters and working manual contents links,
  and corrected report/manual bookmark destinations.
- Clarified project recovery, ownership and distribution: Kasper Lindskov
  Fabricius remains the author, and Sweco Danmark A/S is the internal licensee.

Plastic and Elastic remain solver names and do not prescribe a limit state.

## 0.80 - 2026-07-20

Sector 0.80 is the holistic QA remediation release.

- Corrected EN 1992-1-1:2023 concrete and shear behaviour, including `k_tc` and
  the axial-force modification, while keeping EC2:2023 independently selectable.
- Made anchorage and final user-entered material factors explicit; control,
  construction and consequence categories apply no hidden program multiplier.
- Added user-defined stress and crack-width criteria, full SLS element evidence,
  N-M boundary data, calculation provenance and action-set identification.
- Added a governing-results overview, responsive full-width inputs, clear/undo
  protection, solver-neutral result naming and concise PASS/FAIL presentation.
- Corrected and hardened PDF units, freshness, figure completeness, pagination,
  bookmarks, filenames, result summaries and rendered-artifact QA.
- Added annotated shear geometry in the UI and PDF, clearer material-law and
  neutral-axis terminology, and an expanded engineering-symbol glossary.
- Established locked dependencies, full CI/report/package gates, a proprietary
  notice and generated third-party licence records for Windows releases.

Plastic and Elastic name calculation methodologies, not fixed limit states.
Project action-set classification remains user-defined.
