# Sector 0.93 release-candidate notes

Sector 0.93 is a structural cross-section calculation-tool release candidate.
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

## Release assets

The guarded workflow prepares a draft GitHub release containing exactly seven
authenticated assets:

1. `Sector-v0.93-source.zip`
2. `Sector-v0.93-source.zip.sha256`
3. `Sector-v0.93-windows-portable-unsigned.zip`
4. `Sector-v0.93-windows-portable-unsigned.zip.sha256`
5. `Sector-v0.93-windows-portable-unsigned.portable-distribution.json`
6. `Sector-v0.93-release-qa-receipt.json`
7. `SHA256SUMS.txt`

The source ZIP carries exact-commit provenance. The portable ZIP is a complete
unsigned ONEDIR application; keep the whole extracted directory together.
Neither archive is a signed installer. Windows SmartScreen or organisational
policy may warn or block the portable application, and Sector claims no trusted
publisher, administrator approval or managed deployment status.

The release QA receipt binds the exact commit and tree, the seven required
Sector QA jobs, immutable producer comparison, controlled loopback startup
smoke and final portable artifact. The release workflow freshly downloads and
reverifies all seven assets without launching `Sector.exe`.

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
