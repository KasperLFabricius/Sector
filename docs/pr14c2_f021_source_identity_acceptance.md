# PR-14C2 F-021 source epoch and package identity acceptance

## Exact base and ownership

This slice starts from accepted main
`a98026dd0959eea6e1ee54b0f403dc5e67d2d23c`. It owns deterministic source-epoch
derivation and the final identity boundary between the accepted raw-commit
exporter, isolated build, package manifest, and pre-signing verifier. Sector
remains version `0.91`.

## Frozen acceptance matrix

- The authenticated raw commit has canonical nonnegative author and committer
  epochs. Its committer epoch is the only package timestamp authority. Negative,
  zero-padded, missing, overflowed, or mismatched epochs fail closed.
- Exact export evidence includes the selected revision, root tree, committer
  epoch, derived explicit-UTC timestamp, regular-file count, total bytes, and
  canonical inventory SHA-256.
- Every isolated build writes one create-only
  `<run-root>/source-identity.json`. It never overwrites an existing entry and
  remains beside the preserved exact source and build evidence.
- The build environment removes inherited Git/Python controls and replaces all
  source-identity variables with authenticated evidence. `SOURCE_DATE_EPOCH`
  must equal the Sector-specific source epoch.
- The PyInstaller spec requires one complete lowercase/canonical sealed
  identity. It has no `GITHUB_SHA`, Git-directory, ref, checkout, abbreviated
  revision, or wall-clock fallback.
- The generated package manifest contains the complete source seal. Its UTC
  timestamp is recomputed from the epoch instead of accepted as an independent
  input, and the generated manifest path is create-only.
- Package verification requires the preserved identity file and repository
  root. It independently re-authenticates the selected raw commit/tree/blob
  closure and requires exact equality between that closure, the evidence file,
  and every source field in the packaged manifest. A coherent reseal of both
  manifest and evidence therefore fails.
- The verifier inventories the post-build exported tree without following
  symlinks, junctions, or other reparse points. Every committed file byte and
  portable path must still match the authenticated closure; only the named
  generated notice and manifest files may be additional. The packaged `app`,
  `sector`, and `assets` file inventories and bytes must match that verified
  export before signing secrets are exposed.
- Ordinary unsigned QA and protected release builds delegate to the same
  accepted exact-source driver. Both run the standard-library package verifier
  before upload or signing-secret exposure. Protected certificate handling,
  Authenticode mechanics, and independent signature checks are unchanged.
- Existing paths, branches, artifacts, and partial evidence are never deleted
  or overwritten. Unsigned executables are never launched.

## Recorded evidence

- Red oracle: authenticated tree/epoch evidence, canonical epoch rejection, and
  removal of mutable spec fallbacks all failed before implementation (4 failed).
- Exact exporter/build, static identity, and protected release policy: 97 passed;
  one inherited real-symlink probe skipped because this Windows account cannot
  create directory symlinks.
- Retained packaging and ordinary unsigned-QA policy: 18 passed.
- ASCII and version guards: 184 passed. Pyflakes, `py_compile`, YAML-backed
  workflow policy parsing, and diff checks are clean.
- Independent review P1 regression: post-export source mutation, extra files,
  link-aware inventory, packaged-source mutation, and coherent reseal cases are
  rejected; corrected hostile subset 11 passed.
- The first authorized Action exposed 43 newly published findings in the
  inherited locks (GitPython, pypdf, and pytest). No advisory was ignored and
  the audit policy was not weakened. Only those three packages were refreshed
  to GitPython `3.1.58`, pypdf `6.15.0`, and pytest `9.1.1` in all applicable
  hashed locks.
- Fresh corrected-lock environment: complete C2 focus plus every pypdf-affected
  report/manual suite, 412 passed and two inherited environment skips.
- No real PyInstaller package or unsigned executable was produced or launched
  locally.

## Explicit exclusions

This slice does not compare two builds, define deterministic package digests,
redesign dependency/coverage publication gates, consolidate the final
publication workflow, change certificate/signature policy, or alter application
behavior, solver mechanics, Streamlit/UI, reports, manual, schema, version, or
v0.93 behavior. The narrow lock refresh is the fail-closed repair required by
the existing strict audit; remaining F-021 obligations belong to PR-14C3 and
PR-14C4.
