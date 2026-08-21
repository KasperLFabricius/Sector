# Sector 0.95 notes

Sector 0.95 is an internal structural cross-section calculation tool. It is not
engineering certification, a global code-compliance conclusion or a complete
implementation of any Eurocode, National Annex, bridge-owner requirement or
project design basis.

## Calculation and serviceability changes

- Plastic capacity now requires exact origin-containment evidence for its M-M
  boundary, and prestress-only cracking thresholds retain the correct current
  reinforcement state.
- Torsion checks reject invalid effective-wall and subdivision geometry. A full
  torsion resistance assessment requires current closed-link evidence. Where
  links are absent, Sector may still state retained torsional-cracking evidence,
  but it does not present that as a completed torsion resistance assessment.
- Ordinary crack-width checks have independent user-specified long-term and
  short-term limits. A limit of 0 mm disables comparison for that duration while
  preserving the calculated crack width. Positive limits produce only
  `WITHIN USER-SPECIFIED LIMIT` or `EXCEEDS USER-SPECIFIED LIMIT`. The separate
  Danish Formula 7.100 operand is retained only for that heightened calculation.
- The reinforcement-fatigue workflow includes the simplified minimum
  stress-range screen for its selected implemented basis. A conclusive screen
  is published early; otherwise the detailed S-N/Miner assessment remains
  required and visible.

## Results and input guidance

- Results Overview is one always-expanded table containing the governing result
  for each stable check family. Reports separately retain every non-governing
  requested status and result, including each independently checked fatigue
  spectrum.
- Plastic M-M and N-M plot hover states publish retained capacity values and,
  where available, their angle. Elastic and plastic analysis points publish
  element/material identity plus retained stress and strain. Coordinate hover
  remains available on section-input plots rather than analysis-output plots.
- Creep and detailing controls include clause-specific Eurocode source help for
  the selected implemented basis.
- Plastic summaries and worked reports state the retained compression-zone
  depth `c`; Sector does not relabel it as a generic effective height.

## Reports, manual and maintenance

- The retained plastic ultimate-curvature selection now states the candidate
  count, selected ordinal and retained value instead of repeating every numeric
  candidate in one substitution. The complete candidate table remains in the
  report, while the 29-candidate owner reproduction no longer creates an
  unbreakable equation atom wider than its column.
- Plotly/Kaleido report-image export runs through a bounded worker with explicit
  timeout and process-tree cleanup on Windows and POSIX. A failed export cannot
  silently become a successful report.
- Brief, Standard and Audit reports use the same governing overview and complete
  requested-result status register at their declared presentation depth.
- The user manual describes only the current application. Internal complete
  reference-project and independent-checking-pack prose is no longer presented
  as end-user guidance.
- Measured superfluous and outdated code was removed after caller, coverage and
  behavior checks.

## Portable build

Double-click the root `BUILD.bat` in a complete extracted project. It produces
one complete `Sector-v0.95-windows-portable` folder, matching ZIP and SHA-256
sidecar. The build is accepted only after the packaged `Sector.exe` starts and
executes its first Streamlit page without an application exception.

The portable ZIP is unsigned and is not an installer. Windows SmartScreen or
organisational policy may warn or block it. Sector claims no trusted publisher,
administrator approval or managed deployment status.

## Compatibility and scope

- Supported project schema: 26, plus the bounded schema-25 migration described
  above.
- Unsupported project schemas: schema 24 and future schemas.
- Supported local runtime: the pinned Python version and locked dependencies in
  the release source.
- Portable Windows runtime: unsigned 64-bit ONEDIR distribution; Microsoft Edge
  supplies the supported Chromium-family report-figure prerequisite and is not
  bundled.
- Signed installer: not included.
- Global compliance verdict: never issued.

The engineer remains responsible for inputs, load combinations, selected
methods, project applicability and independent review of the issued result.
