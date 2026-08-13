# Sector 0.93 notes

Sector 0.93 is an internal structural cross-section calculation tool.
It is not engineering certification, a global code-compliance conclusion or a
complete implementation of any Eurocode, National Annex, bridge-owner
requirement or project design basis.

## What changed

- Project files now use current-only schema 24. Released Sector 0.92 schema 23
  projects fail closed and must be recreated and verified; no silent migration
  is performed.
- Unsupported component-mapped bridge workflows were removed. Standards and
  national-annex choices are capability-scoped and retain exact provenance and
  applicability disclosures.
- Editable tables now share canonical labels, symbols, units, blank policies
  and decimal handling. Material and fatigue IDs are reusable without rebinding
  assigned elements.
- Inputs use stateful full-width stages, and the modelled reinforcement
  direction is explicit in the application, project and publications.
- Elastic cases can optionally compare ordinary crack width with a user-entered
  criterion. Omitting the criterion leaves a calculated output; entering one
  gives only `WITHIN USER-SPECIFIED LIMIT` or
  `EXCEEDS USER-SPECIFIED LIMIT` with the criterion source.
- The bounded first-generation Danish heightened crack-control check implements
  Formula 7.100 NA for the visually verified 2024 source route. It does not add
  a general bridge, confinement or Eurocode 2023 heightened-control claim.
- Manual and report equations use one searchable vector renderer. Complete
  substitutions are published for globally governing or extremal examples;
  the Danish fine/coarse heightened pair is the deliberate separate-example
  exception.
- Brief, Standard and Audit report profiles share identical calculation
  results while varying presentation depth. The reorganised manual includes
  task, input and method reading paths plus a semantic accessible HTML version.

## Portable build

Double-click the root `BUILD.bat` in a complete extracted project. It produces
one complete `Sector-v0.93-windows-portable` folder, matching ZIP and SHA-256
sidecar. The build is accepted only after the packaged `Sector.exe` starts and
executes its first Streamlit page without an application exception.

The portable ZIP is unsigned and is not an installer. Windows SmartScreen or
organisational policy may warn or block it. Sector claims no trusted publisher,
administrator approval or managed deployment status.

## Compatibility and scope

- Supported project schema: 24 only.
- Supported local runtime: the pinned Python version and locked dependencies in
  the release source.
- Portable Windows runtime: unsigned 64-bit ONEDIR distribution; Microsoft Edge
  supplies the supported Chromium-family report-figure prerequisite and is not
  bundled.
- Signed installer: not included.
- Component-mapped bridge calculations: not included.
- Eurocode 2023 confinement enhancement: not included or assessed.
- Global compliance verdict: never issued.

The engineer remains responsible for inputs, load combinations, selected
methods, project applicability and independent review of the issued result.
