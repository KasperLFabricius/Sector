# Sector 0.96 notes

Sector 0.96 is an internal structural cross-section calculation tool. It is not
engineering certification, a global code-compliance conclusion or a complete
implementation of any Eurocode, National Annex, bridge-owner requirement or
project design basis.

## Results and report profiles

- Results Overview is always fully expanded and contains the most unfavourable
  retained result for each stable semantic check type. Detailed views and the
  deeper report registers retain load-case, direction and branch evidence.
- Brief is independently readable without becoming a worked calculation
  report. It retains calculation identity, selected basis, complete effective
  geometry, materials, reinforcement and tendons, actions, active settings and
  factors for every active result it reports, plus governing results, criteria,
  statuses and concise warnings. It omits derivations, candidate searches and
  non-governing result registers. When figures are requested, only the governing
  plastic and governing elastic result plots are eligible.
- Standard is the ordinary calculation report. It retains complete used inputs,
  governing and compact non-governing results, and one reproducible governing
  worked calculation per active family without reproducing exhaustive retained
  searches.
- Audit adds the complete retained candidates, branches, substitutions,
  internal equation identities, source inventories and diagnostic evidence.
  All profiles use the same retained inputs, selections, values and statuses.

## Engineering input and references

- The DS/EN 1992-1-1:2023 concrete shear calculation without shear
  reinforcement now uses a positive finite user-specified `gamma_V`. The input
  defaults to 1.40, is persisted in schema 27 and is published consistently in
  every applicable report profile. The 2005, link-reinforced, torsion and
  combined routes are unchanged.
- Creep and detailing guidance now uses tighter edition-specific references for
  the selected implemented route. Project-defined material curves remain
  uncited rather than being assigned a source by numerical similarity.
- User-facing manual and report strain values use the per-thousand symbol `‰`.
  Calculation-language wording is neutral and does not imply certification,
  approval or a result beyond the implemented comparison.

## Manual, navigation and accessibility

- Task workflows now give explicit routes through the visible Inputs, Analysis
  and Report stages. The end-user manual describes current operation only and
  omits former-version narrative and internal build or distribution
  administration.
- Brief, Standard and Audit have visible linked contents and matching PDF
  outlines. Headings stay with substantive content, split tables retain useful
  context and repeated headings, and captions avoid redundant boilerplate.
- The self-contained HTML manual has a keyboard skip link, one main-content
  landmark, descriptive alternatives for every governed figure and semantic
  mathematical markup with clean accessible names.
- The manual and every report profile declare English PDF language metadata.
  Copied/extracted PDF text no longer exposes internal QA marker tokens.

## Portable build

Double-click the root `BUILD.bat` in a complete extracted project. It produces
one complete `Sector-v0.96-windows-portable` folder, matching ZIP and SHA-256
sidecar. The build completes only after the packaged `Sector.exe` starts,
exports a real engineering figure and executes its first Streamlit page
without an application exception.

The portable ZIP is unsigned and is not an installer. Windows SmartScreen or
organisational policy may warn or block it. Sector claims no trusted publisher,
administrator approval or managed deployment status.

## Compatibility and scope

- Supported project schema: 27.
- Bounded in-memory migrations: schemas 25 and 26. Migrated projects receive
  the former fixed 2023 shear value as the explicit default `gamma_V = 1.40`;
  the schema-25 crack-width migration remains deterministic.
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
