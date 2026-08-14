# Sector 0.94 notes

Sector 0.94 is an internal structural cross-section calculation tool. It is not
engineering certification, a global code-compliance conclusion or a complete
implementation of any Eurocode, National Annex, bridge-owner requirement or
project design basis.

## What changed

- Prestressed N-M boundary sampling now retains the exact tensile and
  compression endpoints. Exact-zero fatigue increments reuse the sustained
  state, while genuine non-zero increments retain their calculated range.
- Fatigue results distinguish Miner damage from prestressing-steel proof/yield
  utilisation.
- Eurocode-related input guidance identifies its document, edition and source
  location for the selected design basis.
- The optional permitted crack width is now one Analysis setting shared by
  ordinary and heightened crack checks. Project schema 25 is current; schema 24
  has one bounded migration that warns and uses the conservative minimum when
  populated legacy values conflict.
- The Danish heightened crack-control calculation evaluates fine and coarse
  systems together. Each has its own effective tension area, while bar
  diameter, reinforcement modulus and provided area are derived from retained
  ordinary crack-width evidence.
- Blocking input issues are shown separately and can navigate to their owning
  workspace and input stage. Material families use stateful peer tabs.
- Quick Sections now include trapezoid, L, I, U and circular hollow/annulus
  sections. Inverted T remains an orientation of the T-section.
- Report metadata, content options, generation and downloads now live in the
  dedicated Report workspace. Unknown persisted report-profile selections
  recover safely to Standard instead of aborting the app.
- Brief reports include relevant geometry, reinforcement, materials, actions,
  settings, criteria, warnings and governing results. Report table scripts and
  square-root equations retain readable PDF placement.
- Shear plot annotations use responsive placement to reduce collisions.

## Portable build

Double-click the root `BUILD.bat` in a complete extracted project. It produces
one complete `Sector-v0.94-windows-portable` folder, matching ZIP and SHA-256
sidecar. The build is accepted only after the packaged `Sector.exe` starts and
executes its first Streamlit page without an application exception. Startup is
also checked against recognised legacy and hostile stale report-profile state.

The portable ZIP is unsigned and is not an installer. Windows SmartScreen or
organisational policy may warn or block it. Sector claims no trusted publisher,
administrator approval or managed deployment status.

## Compatibility and scope

- Supported project schema: 25, plus the bounded schema-24 migration described
  above.
- Unsupported project schemas: schema 23 and future schemas.
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
