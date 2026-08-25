# Sector changelog

## Unreleased

## 0.96.1 - 2026-08-25

Sector 0.96.1 strengthens calculation prerequisites, result interpretation,
engineer-facing validation and release evidence without changing project schema
27.

- Shear resistance with links now requires its own valid link lever arm instead
  of substituting the plastic lever arm or effective depth. Full torsion and
  combined resistance remain not assessed when closed links or valid wall data
  are unavailable.
- Plastic publications distinguish the concrete compression resultant `F_c`
  from total compression `F_comp`, and distinguish total lever arm `L`, its
  components, effective depth `d` and the shear lever arm `z`.
- Validation failures throughout the application, manual and reports retain
  concise corrective engineering guidance while unexpected software details
  remain internal.
- Expanded independent hand-calculation comparisons, calculation-path checks,
  real manual/report renders and packaged-application safeguards.
- Removed unused bridge and crack-helper modules and reduced the Windows package
  without removing required runtime libraries.

Project schema remains version 27 with the existing bounded migrations from
schemas 25 and 26. Calculation equations and valid numerical routes are
unchanged from Sector 0.96.

## 0.96 - 2026-08-23

Sector 0.96 improves result review, report-profile purpose, manual usability,
engineering-input references and publication accessibility while retaining
Sector's bounded internal calculation-tool identity.

- Made Results Overview one always-expanded table containing the most
  unfavourable retained result for each stable semantic check type, without
  creating a section-wide or project-wide verdict.
- Defined Brief by information depth rather than page count. Brief retains the
  complete effective geometry, materials, reinforcement/tendons, actions,
  active settings and factors behind every reported active result, together
  with governing results and concise warnings. It omits worked derivations,
  candidate searches and non-governing registers; only governing plastic and
  elastic result plots are eligible when figures are requested.
- Made Standard the ordinary reproducible calculation report and Audit the
  exhaustive retained-evidence report, while preserving identical inputs,
  governing identities, values and statuses across profiles.
- Rewrote manual Task workflows as explicit application routes and kept the
  end-user manual current-only, without former-version or internal build and
  distribution administration.
- Added a positive finite user-controlled `gamma_V` for the implemented
  DS/EN 1992-1-1:2023 concrete shear calculation without shear reinforcement.
  The default remains 1.40; schemas 25 and 26 migrate deterministically to the
  explicit value in schema 27.
- Tightened edition-specific creep, detailing and material-law references,
  replaced user-facing per-thousand wording with the per-mille symbol, and
  removed language that could imply certification or a conclusion beyond the
  implemented comparison.
- Added linked report contents and matching outlines, improved heading/table/
  figure composition and removed redundant caption boilerplate.
- Added an HTML skip link and main landmark, authored figure alternatives,
  semantic mathematical markup, English PDF language metadata and clean PDF
  text extraction without internal QA marker tokens.

Project schema is version 27. Schemas 25 and 26 have bounded in-memory
migrations; schema 24 and future schemas remain unsupported. The Windows
deliverable remains an unsigned portable ZIP and is not an installer or
publisher certification.

## 0.95 - 2026-08-21

Sector 0.95 improves calculation currentness, serviceability controls, fatigue
screening, result review and report reliability while retaining Sector's
bounded internal calculation-tool identity.

- Hardened plastic, cracking and torsion boundaries, including exact M-M
  origin containment, prestress-only cracking, hollow/subdivided torsion
  geometry and current closed-link evidence for a full torsion resistance
  assessment. Torsional cracking may still be published transparently when a
  full resistance assessment is unavailable.
- Replaced the shared ordinary crack-width criterion with independent
  long-term and short-term user limits. A zero limit keeps that duration's
  calculated width without comparison; the Danish Formula 7.100 operand is
  retained separately.
- Added the simplified reinforcement-fatigue stress-range screen with its
  selected Eurocode basis, while preserving detailed fatigue evidence whenever
  the screen does not conclude the check.
- Reworked Results Overview into one always-expanded governing table and a
  separate complete status register for every other requested result,
  including independently checked fatigue spectra.
- Added retained capacity values to plastic and N-M plot hover, and retained
  material, stress and strain information to analysis-point hover. Analysis
  plots no longer use coordinate-only hover.
- Added clause-specific help for creep and detailing inputs, and published the
  retained plastic compression-zone depth in the UI and report.
- Compacted the retained ultimate-curvature selection substitution so the
  complete 29-candidate evidence no longer creates an unbreakable report atom,
  and isolated image export in a bounded worker so PDF generation fails cleanly
  without leaving browser descendants.
- Kept the manual current-only, removed internal reference/checking-pack prose,
  and removed measured obsolete code without changing supported behavior.

Project schema is version 26. Schema 25 has one bounded in-memory migration for
the former shared crack-width value; schema 24 and future schemas remain
unsupported. The Windows deliverable is an unsigned portable ZIP and is not an
installer or publisher certification.

## 0.94 - 2026-08-14

Sector 0.94 improves calculation robustness, input navigation, report evidence
and the ordinary internal portable build while retaining Sector's bounded
calculation-tool identity.

- Corrected prestressed N-M boundary endpoints and exact-zero fatigue cycles,
  and separated Miner damage from proof/yield utilisation in result surfaces.
- Added clause-specific Eurocode guidance, schema 25, one shared analysis-level
  permitted crack width and the bounded schema-24 migration.
- Added simultaneous Danish fine and coarse heightened crack-control systems,
  deriving diameter, modulus and provided area from retained ordinary crack
  evidence.
- Added individually navigable validation issues, stateful material-family tabs
  and trapezoid, L, I, U and annulus Quick Sections.
- Moved report metadata, options, generation and downloads into a dedicated
  Report workspace, with safe recovery from stale persisted profile values.
- Made Brief reports auditable with relevant inputs and governing results,
  corrected table script placement and preserved the radical renderer in PDF
  output.
- Reduced shear-plot label collisions and tightened visual report regressions.
- Simplified Windows distribution to one root `BUILD.bat`, one PyInstaller
  build, one portable folder/ZIP/checksum and one mandatory real first-page
  runtime smoke. Removed signing, release-recovery, exact-source certification,
  duplicate-build comparison and receipt machinery. A complete generic GitHub
  source download is again a supported input.

Project schema is version 25. Schema 24 has one bounded in-memory migration for
the shared permitted crack width; schema 23 and future schemas remain
unsupported. The Windows deliverable is an unsigned portable ZIP and is not an
installer or publisher certification.

## 0.93 - 2026-08-11

Sector 0.93 advances the calculation, reporting, manual and internal portable
Windows application while retaining Sector's calculation-tool identity.

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

- Added a double-click portable Windows builder that creates a complete
  unsigned ONEDIR folder, ZIP and SHA-256 sidecar without elevation. The build
  launches the packaged executable and executes its real first page before it
  can report success.

Project schema is version 24. The application is a calculation tool, not
engineering certification, code-completeness approval or a global compliance
verdict. The Windows deliverable is an unsigned portable ZIP;
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
