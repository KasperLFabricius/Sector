# Sector changelog

## 0.93 release candidate - 2026-08-11

Sector 0.93 completes the governed implementation, publication-readiness and
unsigned portable-release programme with exact-head qualification while
retaining Sector's calculation-tool identity. Its authenticated seven-asset
draft was freshly downloaded and reverified; it remains unpublished.

- Advanced projects to current-only schema 24, retired unsupported
  component-mapped bridge workflows and added a capability-scoped standards
  registry with explicit adoption and exclusion disclosures.
- Hardened editable decimal/blank handling, reusable material and fatigue IDs,
  table-field guidance, stateful input navigation and explicit modelled
  reinforcement direction through persistence and reporting.
- Added optional ordinary crack-width criteria and the bounded first-generation
  Danish Formula 7.100 NA heightened check, with user-limit statuses that do not
  claim code compliance.
- Rendered globally governing or extremal worked examples through one shared
  Eurocode-style vector equation renderer; the Danish fine/coarse heightened
  pair remains the deliberate separate-example exception.
- Added Brief, Standard and Audit report profiles, reorganised the manual around
  task/input/method reading paths, and added its accessible HTML counterpart.

- Added a separate double-click portable Windows builder for provenance-bearing
  extracted source releases. It produces a verified complete unsigned ONEDIR
  folder, deterministic ZIP, SHA-256 sidecar and canonical receipt without
  administrator elevation; user guidance states the SmartScreen/corporate-
  policy and proprietary-licence boundaries. The existing unsigned-QA and
  protected signing paths remain separate.
- Hardened extracted-source and portable-package authentication against
  symlinks, junctions, generic Windows reparse points, special files, archive
  traversal/collisions and mutation during verification. Added a controlled
  headless loopback startup/termination gate for the exact portable ZIP.
- Corrected unsigned QA builds from the official extracted source archive. The
  source-release manifest now seals the commit object and every source file, so
  `packaging/build.bat` can authenticate and isolate an archive without `.git`;
  changed, missing or extra files fail closed. Git-checkout builds retain their
  raw-object export path, and no signing, launch or distribution authority was
  added.

Project schema is version 24. The release candidate is implementation QA, not
engineering certification, code-completeness approval or a global compliance
verdict. The proposed Windows deliverable is a verified unsigned portable ZIP;
no signed installer or trusted-publisher claim is included.

## 0.92 - 2026-08-08

Sector 0.92 completes the implementation and independent QA programme for the
current source application.

- Added scale-aware geometry and topology validation across direct APIs,
  project loading, application inputs and solver entry points.
- Corrected Danish fatigue defaults and the EC2:2023 effective reinforcement
  ratio for mixed reinforcing and prestressing steel.
- Simplified Sector around its transparent calculation-tool identity while
  retaining direct calculations, inputs, provenance, warnings and genuine
  demand/resistance results.
- Improved report and manual equations, tables, notation, cross-references,
  grayscale figures, pagination and structural/raster preflight.
- Reworked Streamlit navigation and state ownership so only the active input
  stage is mounted, interrupted edits recover deterministically and ordinary
  interactions avoid unrelated workspace rebuilds.
- Added stricter typed boundaries, Ruff and strict-mypy gates, a 90% coverage
  floor, locked dependency auditing and exact-commit source/build identity.
- Added static Windows product metadata, reproducible unsigned QA builds and a
  fail-closed protected signing path without claiming unavailable signing or
  publisher authority.
- Published 0.92 as a provenance-bearing exact-commit source/application ZIP.
  The release contains no Windows executable or installer; unsigned Windows QA
  artifacts remain non-distributable test evidence.

Project schema remains version 23. The release is implementation QA, not
engineering certification or code-completeness approval.

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
  explicit scope limitations for laps and bundles.
- Added per-case shear/torsion link detailing for active actions: minimum
  ratios, longitudinal stirrup spacing, transverse leg spacing and closed-link
  torsion spacing. Beam/slab applicability and slab spacing limits are explicit;
  ordinary 2005 beams require minimum links, while slab omissions follow the
  verified no-link resistance. The 2023 structural-system condition is explicitly
  not assessed when it cannot be established. Missing links are reported without
  changing the input.
  Automatic transverse spacing uses the full web width, and the torsion spacing
  check uses a rotation-invariant physical section dimension.
- Added member type and slab section-cut direction to detailing. Minimum-bar
  checks apply only to reinforcement represented by the cut; secondary slab
  minima are not inferred from an unmodelled orthogonal layer.
- Added EN 1992-1-1:2023 shear resistance with links using the simplified
  compression-field method in 8.2.3. Results expose link yielding,
  compression-field stress, action- and ductility-dependent angle limits and
  the uncapped longitudinal force from Formula (8.50).
- Added selectable concrete-fatigue verification: explicit grouped
  Palmgren-Miner damage or the damage-equivalent 10^6-cycle criterion in
  Formula (6.72) / Formula (E.2), with method-specific UI and report evidence.
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
- Added a report-content selector for the default calculation report or the
  default report plus a consolidated QA appendix. Removed redundant
  percentage-point margins from utilisation verdicts.
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
