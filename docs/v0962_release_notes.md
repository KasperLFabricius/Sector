# Sector 0.96.2 notes

Sector 0.96.2 strengthens project replacement, calculation boundaries and the
evidence used in issued results for the internal structural cross-section
calculation tool. Supported project schema: 27.

## Projects and calculation inputs

- Opening a project replaces the working input state transactionally and
  consistently, including optional settings and analysis selections.
- Material and section solvers reject malformed or invalid input domains.
  Plastic sweep limits and angle spacing use one bounded contract across the
  application and calculations.
- Corrected slab reinforcement spacing density and refined the nominal
  resistance envelope.

## Shear, torsion and combined results

- Corrected the implemented Danish action-alone shear-torsion interaction and
  longitudinal torsion assessment for the supported 2005 route.
- The existing 2023 shear route assesses both longitudinal chords.
- Applied the retained section-form, duct, effective-wall and strut-angle rules
  to their relevant calculation routes. Sparse links retain the applicable
  concrete shear route.
- Torsion and dependent combined results require the applicable design basis,
  member scope and current calculation evidence. Results remain unassessed
  when the required conditions are unavailable.

## Reports and manual

- Publication uses current case actions, operands and member evidence. Stale,
  incomplete or inapplicable retained results cannot supply a valid assessment.
- Reports retain applied shear demands when resistance is unavailable and use
  eligible directional results for governing combined worked examples.
- Calculated elastic outputs in the overview select the maximum stress or
  minimum cracking threshold. These remain numerical outputs without a stress
  limit comparison. Report equations use explicit grouping and retain readable
  material, torsion and contents layout.
- Corrected manual crack-spacing terminology, equation references and the
  description of generated reinforcement and tendon IDs.
- Improved startup imports and updated the locked GitPython and PDF-reader
  dependencies to address identified security vulnerabilities.

## Portable build and compatibility

Extract the complete `Sector-v0.96.2-windows-portable` folder from the ZIP and
run `Sector.exe`, keeping its `_internal` folder beside it. The package includes
a SHA-256 sidecar for checking the downloaded ZIP.

- Supported project schema: 27, with bounded migrations from schemas 25 and 26.
- Schema 24 and future schemas remain unsupported.
- The Windows portable package remains unsigned and is not an installer.
- Report figures require Microsoft Edge or another supported Chromium browser.

The engineer remains responsible for inputs, load combinations, selected
methods, project applicability and independent review of the issued result.
