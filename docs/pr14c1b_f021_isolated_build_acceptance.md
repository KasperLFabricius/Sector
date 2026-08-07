# PR-14C1B F-021 isolated build integration acceptance

## Exact base and ownership

This slice starts from accepted main
`8962315e77e7127c0f65d85c4d607b63fa44de27`. It owns only integration between
the accepted raw-commit exporter and the existing unsigned QA packaging path.
Sector remains version `0.91`.

## Frozen acceptance matrix

- Every run names one exact lowercase 40-hex commit and a new, nonexistent run
  root. Existing filesystem entries, including dangling links, fail before path
  resolution. No prior output is removed or overwritten.
- The accepted exporter materializes `<run-root>/source` before any dependency,
  notice, spec, or package command is planned or executed.
- The hashed build lock, third-party-notice generator, PyInstaller spec, Windows
  version resource, launcher, application/core/assets, proprietary license, and
  every other packaging input are read from the exact exported source tree.
- A new virtual environment below the run root is created before installing the
  exported hashed lock. Notice generation and PyInstaller use that environment
  with the exported source as their working directory. Inherited Git
  repository-selection controls and Python path/home/startup injection are
  removed.
- PyInstaller receives unique work and distribution paths below the run root.
  Its destructive `--clean` option is not used.
- Generated notice and build-manifest paths must be new. License and notice
  assembly uses create-only file writes. Unexpected existing source/package
  files fail closed and remain unchanged.
- The PowerShell convenience build and the Windows QA job delegate to the single
  standard-library driver. They no longer install, generate, build, or assemble
  directly from mutable checkout paths.
- The run root preserves the exact source export, build work, distribution, and
  partial failure evidence. Unsigned executables are never launched.

Independent fixtures dirty every former worktree packaging input after commit,
then prove that the build plan and assembled notices/license still use only the
accepted exported bytes.

## Recorded evidence

- Exact-build plus retained packaging/workflow contracts: 28 passed.
- Retained ordinary unsigned-QA policy: 4 passed after updating its exact-step,
  environment, isolated-driver, and upload-path assertions.
- Combined accepted exporter and isolated-build boundary: 79 passed; one
  inherited real-symlink probe skipped because this Windows account cannot
  create directory symlinks, while both deterministic symlink-aware oracles
  passed.
- ASCII and version guards: 184 passed.
- Pyflakes, py_compile, PowerShell parsing, YAML parsing, and diff checks: clean.
- No real PyInstaller package or unsigned executable was produced locally.

## Explicit exclusions

This slice does not establish source epoch, seal final package identity, compare
two builds, add dependency/coverage publication gates, consolidate publication,
or modify signing. Application behavior, solver mechanics, Streamlit/UI,
reports, manual, schema, version, and v0.93 behavior remain unchanged. No real
unsigned executable is built, launched, zipped, uploaded, or distributed during
local acceptance.
