# PR-14C F-021 publication activation acceptance

## Exact base and frozen boundary

This final v0.92 integration candidate starts from accepted main
`80469ec1af101d67884f32d38b69a2071bfa22c1`. It owns only controlled Windows
build reproducibility, publication-gate activation, final coverage calibration
and consolidated exact-head evidence, including closure of vulnerabilities
found by the activated live audit. Sector remains version `0.91`.

The frozen implementation inventory is limited to the two QA/release workflows,
the Windows packaging build/specification/guide, the release and coverage
verifiers, one narrow PyInstaller archive canonicalizer, one independent
package-tree comparator, their focused tests, this acceptance record, the v0.92
closure ledger, and the three generated dependency locks with their two direct
input files. No application or numerical module is in scope.

## Locked dependency closure

The first functioning strict audit identified known vulnerabilities in the
previous `GitPython 3.1.52`, `pypdf 5.9.0` and `pytest 8.4.2` locks. Their direct
security floors are now `GitPython >=3.1.57`, `pypdf >=6.14.2` and
`pytest >=9.0.3`; the regenerated exact locks resolve to `3.1.58`, `6.14.2` and
`9.1.1`, respectively. No vulnerability is ignored. The corrected locks must
pass the same isolated live audit and the affected publication, packaging and
complete-suite regressions before review.

## Controlled unsigned-build identity

1. A controlled build has one exact lowercase 40-hex source revision and one
   non-negative integer source commit epoch.
2. The source commit epoch is exported as `SOURCE_DATE_EPOCH`. It controls both
   PyInstaller's PE timestamp and the packaged `built_at_utc` value. The
   manifest also records the integer `source_date_epoch`; wall-clock assembly
   time is not part of package identity.
3. The QA and protected-release workflows derive the epoch from the exact
   checked-out commit. The protected workflow does this only after proving the
   requested revision is current `main`, and before checkout credentials are
   removed.
4. Package verification fails on a missing, malformed or inconsistent epoch,
   timestamp, source revision, product identity, legal notice or required file.

## Two-build reproducibility gate

The same locked Windows environment builds two clean unsigned package trees.
PyInstaller can enumerate byte-identical stored `base_library.zip` members in a
different order between runs. Each generated archive is therefore validated for
safe, unique, unencrypted stored members and rewritten in deterministic member
order without filtering or changing any member payload.

An independent standard-library comparator inventories every regular file by
normalized relative path, byte length and SHA-256 digest. Missing, extra,
case-colliding, symbolic-link, special or byte-different entries fail. A green
comparison writes a deterministic JSON evidence record containing the source
identity, epoch, file count, total bytes and canonical package-tree SHA-256.
The two resolved package roots must be distinct. Local double-builds use a
unique directory beneath the already ignored `build/` tree, so their large QA
artifacts cannot be staged and no earlier evidence is overwritten.

Both unsigned package trees must first pass the complete release verifier. In
the protected release workflow, comparison and Windows identity checks finish
before any signing secret is exposed. Only the first proven package is signed.
The reproducibility claim therefore applies to the controlled **unsigned**
package. Authenticode/RFC3161 signing intentionally changes `Sector.exe`; no
signed-byte-identity claim is made.

## Final exact-head gate

Before review, the immutable candidate must provide:

- the complete test suite with coverage for both `app` and `sector`;
- removal of the temporary PR-14 coverage-calibration waiver and an integer
  floor no higher than the stable exact-head measured percentage;
- a zero-finding locked dependency audit plus Ruff and mypy policy execution;
- real-figure report and manual renders with structural and visual inspection;
- two controlled unsigned Windows builds, complete package verification and
  exact byte-tree comparison, without launching either executable;
- representative source-run Streamlit viewport inspection;
- exact base, version, ASCII, workflow, diff and rejected-ancestry guards.

The candidate remains one readable `[skip ci]` commit. Its manual exact-head QA
workflow run is the publication evidence; the protected signing workflow is
not dispatched without genuine external certificate authority.

## Explicit exclusions

No solver formula, standard, method, material law, result, verdict, input,
project schema, persistence behavior, report/manual calculation content,
calculation-trace restoration, application version or v0.93 roadmap behavior
is changed. Dependency changes are limited to the audited security floors above.
No unsigned executable is launched or distributed, no certificate is fabricated
and unavailable genuine signing authority is never bypassed.
