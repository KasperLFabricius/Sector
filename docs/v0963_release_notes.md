# Sector 0.96.3 notes

Sector 0.96.3 delivers Part A's focused engineering-language and result-display
improvements. Supported project schema: 27.

## Results and calculation reports

- Elastic stress outputs include percentages of concrete f_ck, reinforcing steel
  f_yk, and prestressing steel f_pk and f_p0.1k where those characteristic
  strengths are declared. The displayed element and assigned material determine
  the reference. Compression signs remain visible in the element and corner
  tables; the existing maximum-compression magnitude and maximum-tension outputs
  retain their conventions and governing selection.
- Missing or invalid strengths are shown as unavailable. Fixed tendon curves
  1-5 do not provide the declared characteristic law fields used for this display.
  Strength percentages are descriptive comparisons, with no new PASS/FAIL check.
- Primary plastic summaries display the existing four face-specific effective
  depths beside z. Axis and tension-face labels distinguish these values from a
  universal depth normal to a biaxial neutral axis.
- The spacing criterion keeps its greater-than-or-equal symbol, missing values
  remain visible, and nominal shear component results are labelled separately
  from the overall shear/chord assessment.

## Interface and manual

Project loading, fatigue Spectrum grouping and the governing simplified fatigue
screen are described consistently with the existing behavior. Multi-cell torsion
still requires a separate applicable model; entering component rectangles does
not establish that model. Reports omit load-table entry instructions while the
input field guide and manual retain that guidance. Known labels, notation and
example descriptions are clearer, and a compact main header contains the logo.

Report-profile depth, navigation and saved input identities are unchanged. The
keyed Mild steel tab rename remains deferred with the larger Part B interface,
report/manual organization and runtime work. The separate 0.96.4 torsion/M-V-T
programme remains deferred.

## Portable build and compatibility

Extract the complete `Sector-v0.96.3-windows-portable` folder from the ZIP and run
`Sector.exe`, keeping its `_internal` folder beside it. The release includes a
SHA-256 sidecar for checking the downloaded ZIP.

- Project schema 27 and the existing schema 25/26 migrations are unchanged.
- Schema 24 and future schemas remain unsupported.
- The Windows portable package is unsigned and is not an installer.
- Report figures require Microsoft Edge or another supported Chromium browser.
- Runtime, dependencies, solver methods and assessment rules are unchanged.

The engineer remains responsible for inputs, load combinations, method and
project applicability, and independent review of the issued results.
