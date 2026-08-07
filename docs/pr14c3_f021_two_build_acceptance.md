# PR-14C3 F-021 deterministic two-build acceptance

## Exact base and bounded objective

This slice starts from verified accepted main
`bbab7c55e1499a53d61768bf627257a6300ad99d`. It owns only the independent
two-build reproducibility boundary. Sector remains version `0.91`.

C2 already owns raw commit authentication, source epoch, canonical source
identity, isolated build execution, and package/source verification. C3 does
not duplicate that build engine or treat either exported source tree as an
authority.

## Frozen acceptance matrix

- QA and protected release each invoke the accepted exact-source driver twice,
  sequentially, for the same exact commit in different new build roots.
- The exact-source driver fixes both `SOURCE_DATE_EPOCH` and the documented
  PyInstaller build-time `PYTHONHASHSEED`; inherited random hash state cannot
  influence either controlled build. Its PyInstaller interpreter uses `-P -s`
  to retain safe-path and user-site isolation without the `-E` behavior that
  would ignore those controls.
- Both packages and both canonical source-identity files are independently
  authenticated against raw Git before comparison.
- Package roots, build roots, and identity files must be genuinely distinct.
  Nested roots, aliases to the same filesystem object, invalid exact-build
  layouts, links/reparse points, and evidence inside either build root fail
  closed.
- The comparator inventories the complete package trees and streams every pair
  of files byte-for-byte. This includes `Sector.exe`, bundled dependencies,
  notices, licenses, source, assets, and the embedded manifest.
- Two complete comparison passes must produce identical sorted per-file size
  and SHA-256 records, file/byte counts, and aggregate inventory digest. A
  matching package mutation or source-identity mutation between passes fails.
- Comparison evidence is canonical JSON, contains no machine-specific build
  path, and is opened create-only after every check succeeds. Existing or
  partial evidence is never overwritten or deleted.
- QA retains both unsigned package witnesses, both source identities, and the
  canonical comparison evidence. No unsigned executable is launched.
- Protected release performs the same two-build comparison before Windows
  identity inspection and before the only secret-bearing signing step. Only
  the first proven-identical package proceeds to signing.

## Recorded evidence

- red oracle: expected collection failure before the comparator module existed;
- initial comparator result exposed Windows path-stat/handle-stat differences
  in ctime and executable-extension mode for unchanged files; the stable race
  signature now uses filesystem identity, size, and mtime while direct bytes
  and two full passes remain authoritative;
- comparator and workflow contract: 11 passed;
- retained workflow/policy boundary before stale-name correction: 212 passed,
  4 expected stale single-build failures;
- corrected comparator and retained workflow/policy boundary: 226 passed.
- ASCII, version, legal, and retained Windows identity guards: 202 passed;
- pyflakes, py_compile, YAML parsing, enforced Ruff, enforced strict mypy, and
  diff checks: clean.
- the first exact-head Windows run built and independently authenticated both
  packages, then exposed the single missing build control through a byte
  difference in `_internal/base_library.zip`; the documented PyInstaller
  build-time hash seed is now fixed and protected against inherited overrides.
- a second exact-head Windows run proved the environment-only correction was
  ineffective: Python `-I` implies `-E` and ignored the fixed hash seed. A
  direct interpreter oracle produced different hashes across two `-I` starts
  but identical hashes across two `-P -s` starts. The clean reslice therefore
  retains safe-path/user-site isolation while allowing the fixed seed to act.
- clean-reslice exact-build/comparator contract: 22 passed; retained Windows
  packaging, unsigned-QA, product-identity, release-policy and version boundary:
  62 passed.
- the first clean-reslice Windows run proved `base_library.zip` byte identity,
  then isolated the next difference to `jsonschema-4.26.0.dist-info/RECORD`.
  That pip installer inventory hashes a generated `../Scripts/jsonschema.exe`
  launcher whose bytes embed the unique virtual-environment path, although the
  launcher is not part of Sector's frozen package. Hook-expanded data now omits
  only top-level `*.dist-info/RECORD`; runtime metadata, licences, entry points,
  package code, dependencies and all frozen outputs remain compared.
- post-filter focused packaging/exact-build/comparator contract: 37 passed;
  retained Windows release, product-identity, unsigned-QA and version policy:
  48 passed; compile, enforced Ruff/mypy and diff gates: clean.

## Explicit exclusions

This slice does not consolidate publication gates (C4), change dependency or
coverage policy, modify signing mechanics or secrets, add application/UI/report
or manual content, change solver behavior, implement v0.93 work, or change the
application version. A genuine signed release remains dependent on the
separately authorised protected signing environment; no signature is
fabricated or bypassed here.
