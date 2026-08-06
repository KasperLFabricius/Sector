# PR-14A1A-R3 F-014 static Windows identity acceptance

## Frozen boundary

This fresh candidate starts from accepted main
`006fadf287c1213d1a788538097bfa4261f14a6f`. It establishes only the static
identity carried by Sector source metadata, the Windows executable resource and
the packaged provenance manifest. Sector remains version `0.91`; the Windows
file and product version is `0.91.0.0`.

The exact identity is:

- product: Sector;
- description: Structural-analysis and design calculation tool;
- original filename: Sector.exe;
- author and copyright holder: Kasper Lindskov Fabricius;
- licensed organisation: Sweco Danmark A/S, for internal organisational use;
- copyright: Copyright (c) 2026 Kasper Lindskov Fabricius. All rights reserved.

Sweco Danmark A/S is not represented as author, copyright holder, company,
publisher, certifier or owner. The Windows resource contains no company or
publisher field.

## Provenance closure

Package creation requires a complete 40-hex Git commit identity. Resolution is
independent of the Git executable and covers an explicit build environment, an
ordinary checkout, detached HEAD, loose or packed refs, and linked worktrees
whose per-worktree metadata redirects refs through `commondir`. Missing,
abbreviated, malformed and `unavailable` identities fail before the manifest is
written.

The manifest maps product, description, Sector version, source revision,
author, licensee and copyright from retained source identity. The existing
build timestamp is retained without a reproducibility claim; F-021 remains in
PR-14C.

## Exclusions

No ordinary-build instruction, QA artifact label, distribution policy,
certificate, secret, protected environment, release workflow, signing or
timestamp operation, executable build/launch, solver/formula/standard, project
schema, Streamlit/UI, report/manual calculation, dependency, cold-start,
application-version or v0.93 change is included. PR-14A1B owns the complete
unsigned-QA surface. PR-14A2 owns protected genuine signing.
