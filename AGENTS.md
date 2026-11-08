# Sector: guide for agents and developers

Sector calculates one reinforced or prestressed concrete cross-section: elastic
stresses, plastic N-Mx-My capacity, crack width, shear, torsion, combined M-V-T,
detailing and fatigue, with PDF reports and a built-in manual. It is a Streamlit
application with a pure Python calculation engine.

Read `docs/product_identity.md` before you change a calculation or a result
label. It governs every change.

## Module map

| Area | Location | Contents |
|---|---|---|
| Engine | `sector/` | Pure calculation code, no Streamlit. One module per family. |
| Section model | `sector/section.py`, `sector/geometry.py` | Polygon section, bars, tendons, clipping, topology checks. |
| Materials | `sector/materials.py`, `sector/material_presets.py`, `sector/codes.py` | Concrete, reinforcing steel and tendon laws; edition presets and coefficients. |
| Plastic ULS | `sector/plastic.py`, `sector/plastic_sweep.py` | Strain-plane capacity, pivot C, neutral-axis sweep, N-M and M-M envelopes. |
| Elastic SLS | `sector/elastic.py` | Cracked elastic Newton solver, long-term and short-term superposition, bonded prestress. |
| Crack width | `sector/serviceability.py`, `sector/heightened_crack_control.py` | EN 1992-1-1 7.3.4 (2005 and DK NA) and 2023 9.2.3, Formula 7.100 NA. |
| Shear, torsion, M-V-T | `sector/shear.py`, `sector/torsion.py`, `sector/combined.py`, `sector/capacity.py` | Resistances, chord checks, shared strut angle, result validators. |
| Detailing | `sector/detailing.py` | Minimum reinforcement, spacing, link rules. |
| Fatigue | `sector/fatigue.py` | Reinforcement S-N and Miner, concrete fatigue with the fibre search. |
| Application | `app/sector_app.py` | Streamlit script: input pages, `build_inputs`, calculation orchestration (`run_analysis`, `_run_uniaxial_capacity_checks`), result views. |
| Project files | `app/project_io.py`, `app/session_state_migrations.py` | Schema, validation and migrations of `.sector` project files. |
| Presentation | `app/result_presentation.py`, `app/fatigue_presentation.py` | Result rows, statuses and the publication validators that re-check retained results. |
| Report | `app/sector_report.py`, `app/report_*.py`, `app/publication_*.py` | PDF reports (Brief, Standard, Audit). |
| Manual | `app/manual*.py` | Built-in manual content and renderers. |
| Tests | `tests/` | pytest suite. `tests/test_v0970_*.py` hold the 0.97.0 hand-calculation tests. |

## Data flow

1. The input pages write Streamlit session state.
2. `build_inputs` in `app/sector_app.py` converts session state to one `inp`
   dictionary (materials, section, actions, method options).
3. `run_analysis` runs the engine for each action case and returns `results`.
4. `app/result_presentation.py` turns results into rows, statuses and notes. Its
   validators recompute the retained values from `inp`; a mismatch gives NOT
   ASSESSED instead of a stale verdict.
5. The views, the PDF report and the manual read the same results.

Session state lives in `st.session_state` and is saved in project files through
`app/project_io.py`. A new persisted input needs: a key in `SCALAR_KEYS` (and in
`_BOOLEAN_SCALAR_KEYS` when Boolean), the staleness signature keys in
`app/sector_app.py`, the widget, the `inp` entry and a migration default.

## Invariants

- Product identity: the engineer controls methods and coefficients. Warn when a
  value differs from a default; do not clamp or replace it.
- Fail closed: an incomplete or non-converged calculation gives NOT ASSESSED or
  INVALID with its cause, never a favourable verdict.
- Every new defect test comes from the standard text or an independent hand
  calculation, not from Sector output. Name the clause and the source PDF.
- Source files are ASCII only (`tests/test_ascii_only.py`).
- Program text (UI, help, report, manual) follows ASD-STE100 with British
  spelling and no em dashes.

## Commands

The pinned interpreter is CPython 3.14 (`.python-version`) with
`requirements-dev.txt` (hash-locked).

- Source contracts: `python -m pytest tests/test_ascii_only.py -n 0 -q`
- Ruff policy: `python tools/verify_ruff_policy.py quality-ruff-policy.toml --execute`

CI (`.github/workflows/qa.yml`) runs the shards of `tools/qa_core_shards.py`,
the coverage, Ruff, mypy and dependency gates.

## Development test loop

Use the fast tier while you develop. CI runs the full suite on every pull
request and push to `main`, and CI is the gate.

- Fast tier, about 5 min on a 28-thread PC:
  `python -m pytest -m "not slow" -n auto -q`
- Slow tests of an area that you changed:
  `python -m pytest -m slow tests/test_x.py -n auto -q`
- Full suite: `python -m pytest -n auto -q`

`tests/conftest.py` marks a test `slow` when its CI duration in
`tools/qa_shard_durations.json`, or the mean CI duration of its module, is at
least `SLOW_SECONDS` (1 s). Tests of one module share report and native-run
caches, so one test alone can take the cost of the full module. The real-image
export tests are always slow. A module that is not in the table is slow until
the next refresh. The fast tier leaves out most report, publication, shear,
torsion and native application tests: before you push, run the slow tests of
each area that you changed. Under a full local load, a native image-export test
can fail. Run such a failure again alone before you examine it.

Refresh the duration table from the shard evidence of a completed QA run.
The table also sets the shard balance in CI, so commit the new table:

```
gh run download <run-id> --pattern "sector-core-<run-id>-<attempt>-core-*" --dir qa-durations
python tools/qa_core_shards.py durations --input qa-durations --output tools/qa_shard_durations.json
```

## Dependency updates

Dependabot opens weekly pull requests for the pip-compile locks and the GitHub
Actions. Each one runs the full QA workflow.

- The policy validators and tests pin the SHA of each action in
  `.github/workflows/qa.yml` (checkout, setup-python, upload-artifact and
  download-artifact): `tools/verify_coverage_gate.py`,
  `tools/verify_dependency_audit.py`, `tools/verify_mypy_policy.py`,
  `tools/verify_ruff_policy.py` and `tests/test_portable_windows_policy.py`.
  An action update must change the old SHA in each of these files that
  contains it. Search for the old SHA in `tools/` and `tests/`, and check the
  new SHA against the release tag of the action before you change it.
- A Streamlit update needs a review of `tests/native_callable_page_client.py`,
  which accepts one reviewed Streamlit release.
- Update the exact Python pin in `.python-version` by hand.
- pytest stays below 9.2 (`requirements-dev.in`, and an ignore entry in
  `.github/dependabot.yml`). pytest 9.2 stores node IDs in a structured form,
  so pytest-xdist 3.8 cannot add the `@group` suffix: the xdist groups split
  and the shard merge gate fails with "shard collection differs from its
  balanced assignment". Remove the cap and the ignore entry when a
  pytest-xdist release supports pytest 9.2. The fix on the pytest-xdist development
  branch sends the group names separately and drops the `@group` suffix for
  every pytest version. That release thus also needs a change to
  `tools/qa_core_shards.py` in the same pull request: the worker node IDs
  (shard collection) will not have the suffix, but the expected IDs from the
  reference collection are `nodeid@group`. Do not normalise the worker IDs
  before that release, because the gate failure is the only automatic
  detection of split xdist groups.

## Release steps

1. Update `sector/__init__.py` (`__version__`) and every version literal the
   tests report.
2. Add a `CHANGELOG.md` entry and `docs/vXYZ_release_notes.md`.
3. When a persisted input changes, increase `VERSION` in `app/project_io.py` and
   add the migration and its load message.

## History

The `docs/*_acceptance.md` records describe earlier releases. Do not edit them.
Release notes and tests are the record from 0.97.0 on.
