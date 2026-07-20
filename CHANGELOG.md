# Sector changelog

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
