# Sector 0.96.1 notes

Sector 0.96.1 strengthens assessment prerequisites, result interpretation and
visible validation guidance for the internal structural cross-section
calculation tool while retaining project schema 27.

## Calculation prerequisites and result interpretation

- Shear resistance with links is assessed only when its own valid link lever
  arm is available. Sector does not substitute the plastic lever arm or the
  geometric effective depth for this quantity.
- Full torsion resistance requires closed torsion links and valid wall data.
  Torsion and dependent combined checks remain not assessed when those
  prerequisites are unavailable; no resistance is inferred from incomplete
  detailing.
- Plastic result tables, summaries and reports distinguish the concrete
  compression resultant `F_c` from the total compression resultant `F_comp`.
  They also distinguish total lever arm `L`, its axis components, geometric
  effective depth `d` and the shear lever arm `z`.

## Validation and visible guidance

- Expected input and geometry problems state the engineering correction at the
  point of use. Unexpected calculation, material, project, figure, manual and
  report failures use concise contextual guidance without exposing software
  diagnostics.
- Quick Section retains specific corrective relations for T, I, L, U and
  annulus dimensions. If a material cannot be constructed from the selected
  values, calculation remains blocked rather than using a substitute material.
- Fatigue, result and report warnings follow the same rule while preserving
  familiar notation such as `gamma_Ff`, `gamma_s`, `gamma_V`, `gamma_c,fat`,
  `beta_cc(t0)`, `alpha_cc`, strengths, actions and resistances.

## Reports, manual and verification

- The Brief, Standard and Audit profiles retain their Sector 0.96 information
  depth. Their engineering results and authored warnings remain consistent,
  while software-oriented identifiers and diagnostics are excluded.
- Independent hand-calculation comparisons cover the retained plastic cases and
  key calculation outcomes. Release verification also opens real engineering
  figures, the issued manual, every report profile and the packaged application.
- Unused bridge and crack-helper modules were removed, and the Windows package
  was reduced without removing required runtime modules or libraries.

## Portable build and compatibility

Double-click the root `BUILD.bat` in a complete extracted project. It produces
one complete `Sector-v0.96.1-windows-portable` folder, matching ZIP and SHA-256
sidecar. The build completes only after the packaged `Sector.exe` starts,
exports a real engineering figure and opens its first calculation page without
a visible error.

- Supported project schema: 27.
- Bounded in-memory migrations: schemas 25 and 26.
- Unsupported project schemas: schema 24 and future schemas.
- Calculation equations and accepted numerical routes are unchanged from
  Sector 0.96; invalid or incomplete prerequisites now fail closed.
- The portable ZIP is unsigned and is not an installer. Its checksum lets the
  recipient verify that the downloaded file is unchanged.

The engineer remains responsible for inputs, load combinations, selected
methods, project applicability and independent review of the issued result.
