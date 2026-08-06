# PR-14A1 F-014 Windows identity acceptance

## Frozen boundary

This slice starts from accepted main `006fadf287c1213d1a788538097bfa4261f14a6f`.
It establishes the static Windows product identity and the identity retained in
the packaged provenance manifest. Sector remains version `0.91`; its Windows
file and product version is `0.91.0.0`.

The exact identity is:

- product: Sector;
- description: Structural-analysis and design calculation tool;
- original filename: Sector.exe;
- author and copyright holder: Kasper Lindskov Fabricius;
- licensed organisation: Sweco Danmark A/S, for internal organisational use;
- copyright: Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved.

Sweco Danmark A/S is not represented as author, copyright holder, company,
publisher, certifier or owner. Windows resources therefore contain no
`CompanyName` or publisher field.

## Package surfaces

The PyInstaller specification applies the committed Windows version resource and
retains product, description, Sector version, exact source revision, author,
licensee, copyright and build timestamp in `sector_build_info.json`. The existing
timestamp is not claimed to be reproducible; F-021 remains owned by PR-14C.

All ordinary build paths are explicitly unsigned QA paths. The local PowerShell
and batch wrappers and the normal QA workflow say that the result must not be
launched or distributed. The QA artifact is named
`Sector-Windows-unsigned-QA`, and its Windows metadata is checked before upload.

## Exclusions

No signing certificate, secret, protected environment, release workflow,
timestamp-authority call, signed artifact, executable launch, solver/formula,
standard, Streamlit/UI, report/manual calculation, project schema, dependency,
cold-start, reproducibility, application-version or v0.93 change is included.
PR-14A2 owns genuine signing authority and signed-release verification.
