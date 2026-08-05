# PR-13B1 / F-012 coverage and Ruff acceptance boundary

## Exact base and reslice reason

- Exact base: `main@65452fc9013150ff7cff3507debae7bb34ed3d1c`.
- Application version: `0.91`.
- Rejected head `9f289e708207a4419d94f6ae2c7b8daa558497e1` is negative
  evidence only. It is not reused, patched, reopened or merged.
- PR #347 exposed independent Ruff-waiver and mypy-import scope findings. This
  fresh slice owns only coverage and Ruff; type and dependency security remain
  separate later F-012 slices.

## Frozen contract

1. The full test workflow measures only `app` and `sector` and fails below 50
   whole percent. PR-14 must calibrate the threshold upward from its exact-head
   full-suite result when that stable result exceeds 50 percent.
2. Fatal Ruff rules `E9,F63,F7,F82` cover `app`, `sector`, `tools` and `tests`.
3. The capacity boundary owns `E4,E7,E9,F,I` with no ignore.
4. `tests/test_project_io.py` owns the same strict rules with its sole `E402`
   path-bootstrap exception. The workflow uses a separate command, so that
   exception cannot mask `sector/capacity.py` or `tests/test_capacity.py`.
5. The tracked contract pins minimum targets, paths, rules, exact workflow
   commands, waiver identity, owner, reason and objective exit condition.

## Evidence and exclusions

- Focused policy and controlled-failure tests own missing/renamed scope, ratchet
  rollback, path escape, waiver incompleteness, ignore escape and workflow drift.
- Exact locked Ruff and the directly affected reproducibility/packaging guards
  run before publication.
- The full suite and coverage measurement remain the PR-14 integration gate.
- No mypy or dependency-security gate; no solver, formula, standard, result,
  schema, Streamlit behavior, report/manual content, package, signing, release,
  version, v0.93 or rejected-head implementation is included.
