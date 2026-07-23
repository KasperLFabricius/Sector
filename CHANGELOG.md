# Sector changelog

## Unreleased

- Added the headless grouped-spectrum fatigue engine for reinforcing and
  prestressing steel and for same-fibre concrete compression damage, including
  per-element yield checks, explicit partial factors, the EN 1992-2:2005
  concrete bridge method and the EN 1992-1-1:2023 method.
- Added the versioned fatigue input model: stable S-N detail IDs, verified 2005
  and 2023 Eurocode presets, grouped long-/short-action spectrum bins and
  lossless project-file migration. UI and report presentation follow in the
  next scoped change.
- Added stable reinforcing- and prestressing-steel catalogues with per-element
  assignment throughout plastic, elastic, crack-width and member checks.
- Added material IDs, names, definitions, assignment evidence and individual
  stress-strain curves to the UI, project files and PDF report.
- Added per-case longitudinal minimum-reinforcement checks for the 2005/DK NA
  and 2023 Eurocode methods, including resultant biaxial tension-zone geometry
  and retained ordinary-bar material assignments.
- Added a section-wide clear-spacing check, explicit tendon-envelope opt-in and
  lap/bundle review flags, plus matching UI, figures, report and manual evidence.

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
