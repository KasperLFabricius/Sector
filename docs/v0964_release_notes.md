# Sector 0.96.4 notes

Sector 0.96.4 is the working Part B identity for report presentation, interface
navigation, document control and runtime maintenance. Supported project schema: 27.
Final manual/report publication qualification and the integrated portable build
are pending at this intermediate source stage; this document does not record a
completed release.

## Changes incorporated

- Brief shows governing results and relevant unavailable/failure states.
  Standard gives the calculation explanation and results; Audit retains detailed
  numerical substitutions.
- Input navigation groups material, reinforcement and analysis controls while
  retaining saved inputs and selected result cases. Elastic strength percentages
  use stress magnitudes; stress values retain their sign conventions.
- Optional Checker and Approver fields accompany Author in report document
  control when supplied. Existing projects default to empty optional fields.
- Source and build environments use 64-bit CPython 3.13.15. Both build entry
  points check the exact `.python-version` pin. Hash-locked application, test and
  build dependencies are unchanged.
- The documentation index separates current guidance from retained decision and
  acceptance history. The project layout omits the removed bridge marker, and
  geometry compatibility identifies the current schema.

The final Part B publication pass covers manual organization, report navigation,
source locations, typography and pagination. Its final acceptance remains pending.
The separate torsion/M-V-T programme is deferred to a later release.

## Portable build and compatibility

The intended package is `Sector-v0.96.4-windows-portable`. Extract its complete
folder and run `Sector.exe`, keeping `_internal` beside it. The package includes
its Python runtime; report figures require Microsoft Edge or another supported
Chromium browser. Distribution remains an unsigned folder/ZIP with a SHA-256
sidecar.

- Project schema 27 and the existing schema 25/26 migrations are retained.
- Schema 24 and future schemas remain unsupported.
- Geometry winding, closed-ring handling and the explicit `holes` representation
  retain their behavior.
- Calculation methods and engineering assessment rules are unchanged by Part B.

The engineer remains responsible for inputs, load combinations, method and
project applicability, and independent review of the issued results.
