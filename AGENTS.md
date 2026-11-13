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
| Application | `app/sector_app.py` | Streamlit script: input pages, `build_inputs`, result views. It imports the names of the calculation service again for one release (0.97.1). |
| Calculation service | `app/calculation_service.py` | Calculation orchestration without Streamlit (`run_analysis`, `_run_uniaxial_capacity_checks`, `_run_capacity_checks`), `calculate_project` and the command line `python app/calculation_service.py <project file>`. Until AR-09, `project_inputs` builds the inputs of a project file in a headless Streamlit session of the application. |
| Project files | `app/project_io.py`, `app/session_state_migrations.py` | Schema, validation and migrations of `.sector` project files. |
| Presentation | `app/result_presentation.py`, `app/fatigue_presentation.py` | Result rows, statuses and the publication validators that re-check retained results. |
| Stored presentation | `app/stored_presentation.py` | The result register of the last Calculate, keyed by section, stage and case, with its digests (structure in the module docstring). |
| Report | `app/sector_report.py`, `app/report_*.py`, `app/publication_*.py` | PDF reports (Brief, Standard, Audit). |
| Manual | `app/manual*.py` | Built-in manual content and renderers. |
| Tests | `tests/` | pytest suite. `tests/test_v0970_*.py` hold the 0.97.0 hand-calculation tests. |

## Data flow

1. The input pages write Streamlit session state.
2. `build_inputs` in `app/sector_app.py` converts session state to one `inp`
   dictionary (materials, section, actions, method options).
3. `run_analysis` in `app/calculation_service.py` runs the engine for each
   action case and returns `results`. `calculate_project` gives the same
   calculation without the browser interface.
4. `app/result_presentation.py` turns results into rows, statuses and notes. Its
   validators recompute the retained values from `inp`; a mismatch gives NOT
   ASSESSED instead of a stale verdict. After each Calculate, the application
   builds the result register one time and stores it beside the results
   (`app/stored_presentation.py`). A rerun reads the stored rows only when
   all digests agree, and calculates them again otherwise.
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
the coverage, Ruff, mypy and dependency gates, and the performance budget
(`tools/perf_budget.py`). The budget compares each phase time, divided by the
time of a fixed calibration workload, with `tools/perf_budget_baseline.json`:
a warning above 1.25 times the baseline ratio, a failure above 2 times. After
an intended change of the run time, write a new baseline from the CI evidence
(artefact `sector-perf-<run id>-<attempt>`).

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

## CI hang guard and reruns

- A real-image test has a hard limit of 300 s (`tests/real_image_guard.py`).
  A test that runs longer writes the stack of every thread. Then its process
  stops with exit code 124.
- Each in-process Kaleido start has a limit of 90 s. After a time-out or an
  error in the start, the start is tried one more time. The test itself never
  runs again.
- The render fixtures start the shared exporter with `tools/kaleido_start.py`.
  Each attempt has a limit of 60 s, and a failed start is tried one more time.
- In `tools/qa_core_shards.py`, each real-image phase stops after 480 s,
  together with its process tree. All phases together have a budget of 900 s,
  so the shard always writes its evidence. Exit code 124 marks a stopped
  phase, and the gate names it.
- The step limit in `qa.yml` is 20 min for the real-image shard and 60 min for
  the other shards. A job that runs more than three times its normal duration
  is a hang. Cancel the run, and run the failed jobs again one time.
- A rerun of failed jobs is valid. The gate takes the newest evidence of each
  shard from all attempts of the run, so a shard that fails again stays failed.
  When the evidence of a shard is missing or not valid, the gate tells you to
  run all jobs again.

## Pre-review checklist

Go through this list before review round 1. Give the result in the PR body:
each item done, or not applicable with its reason. The items come from the
finding types of the 0.97.0 review rounds, in the order of their count.

Engineering results:

1. Run each new or changed solver or search over a scripted sweep of
   realistic and edge sections. Include several tendons, asymmetric sections,
   both axial ends and axial forces that the section cannot reach. Compare the
   results with an independent brute-force scan. Give the worst error and the
   number of failed points.
2. Read the full clause and its companion formulas in the source PDF. Compare
   each term and parameter with the code and with a sibling route that has the
   same check. Make sure that each clause reference has the correct number,
   edition and condition.
3. Find each new except branch, None return, zero fallback and converged
   flag. For each one, add a test that forces the failure. In that test, the
   results that depend on the failed value show NOT ASSESSED or INVALID with
   the cause. The other results keep their status.
4. Find each place where the producer, the publication validator or the
   strut-angle objective calculate the same quantity again. Make them use one
   shared function.
5. Time the changed calculation on the reference sections before and after
   the change. Give the two times.

Surfaces and text:

6. Search `app/` and `sector/` for each changed term, symbol and synonym.
   Correct each occurrence, also outside the diff.
7. List each consumer of a changed result key (`git grep -n "<key>"`). Make a
   failing case. With one AppTest or report-text probe, make sure that each
   surface shows the same value and status. The surfaces are the overview,
   the summary, the views and the Brief, Standard and Audit reports, for each
   edition route.
8. Find each printed formula next to a changed value. Put in the retained
   operands of each state (capped, uncapped, absent). The printed equation
   must give the printed value.
9. Render a Standard and an Audit report of a case that uses the change.
   Calculate each new value by hand from the printed text only.
10. Update the manual for each changed rule, option, default, NOT ASSESSED
    condition and known limitation. Write each cross-reference as a full
    path, for example "(Material laws > Prestressing steel)". Use raw strings
    for LaTeX in `app/manual*.py`.
11. Read each changed string as it shows in the program, with joined literals
    and f-strings. It must follow ASD-STE100 with British spelling. An
    interactive text has a maximum of 50 words.
12. Make each docstring, comment and procedure next to the changed code state
    the current rule.

Inputs, project files and migrations:

13. Do these checks for each new or changed input:
    - The input is editable in each mode where a result uses it.
    - Sector states when the input has no effect.
    - The default follows a later change of the input that sets it.
14. For a new persisted input, add the key to `SCALAR_KEYS` (and
    `_BOOLEAN_SCALAR_KEYS`). Also add it to the migration defaults,
    `_SHARED_KEYS` in `app/mvt_workspace.py`, the staleness signature keys and
    the reference project. When the meaning changes, increase `VERSION` in
    `app/project_io.py`. Add a save-load round-trip test.
15. Compare each migration default with the widget default and the loader
    default for each preset. Include a file with no preset key.
16. Run a load matrix: each older schema, each preset, and the key missing,
    true and false. Each sentence of a load message must occur only in the
    states where it is true.
17. Add each new dependency of a result to `_SHARED_SIG_KEYS`,
    `_PLASTIC_CONTEXT_SIG_KEYS` or `_ELASTIC_CONTEXT_SIG_KEYS`. Add a test
    that shows that a change of only that input makes the result stale.

Tests and coverage:

18. Write the source of each expected value in the test: the clause, a hand
    calculation or `tests/handcalc_fixtures.py`. Do not calculate it with a
    Sector function that the tested code also uses.
19. Revert the fix in a scratch copy and run the new tests. Each new test must
    fail. Compare the collected test IDs with `origin/main`, so that no
    negative case goes away.
20. Run the touched test modules with
    `--cov=app --cov=sector --cov-branch --cov-report=term-missing`. Add a
    test for each new branch, face, axis, route and failure path.
21. Run tests only in an idle worktree. Keep the `SECTOR_AUTOSAVE_DIR`
    isolation in each probe. Import shared fixtures only from
    `tests/conftest.py`.
22. Before each push, run `tests/test_ascii_only.py`, `tests/test_user_copy.py`,
    `tests/test_manual.py` and `tests/test_manual_equation_contract.py`.
    Do not add a skipped test: the CI gate counts each skip as not passed.
    Write a platform-dependent test so that it runs on each platform.

Release and dependencies:

23. Search the repository for each old version, action SHA, reference hash
    and render crop (`git grep -n "<old value>"`). Include
    `tools/*_render_fixture.py`, the policy validators in `tools/` and `docs/`.
    Update each occurrence in the same commit.
24. Refresh `tools/qa_shard_durations.json` when you add, split or rename
    many tests.
25. Compare each release-note claim with the code and with the default of each
    edition preset. Give the inputs of each example. State the known
    limitations from the PR body.
26. For a change of a dependency or an action, simulate the next update PR
    (exact version guards, groups, transitive pins). Update the manual steps
    in this file.

## Dependency updates

Dependabot opens weekly pull requests for the pip-compile locks and one grouped
pull request for the GitHub Actions. Each one runs the full QA workflow.

- The policy validators and tests pin the SHA of each action in
  `.github/workflows/qa.yml` (checkout, setup-python, cache, upload-artifact
  and download-artifact): `tools/verify_coverage_gate.py`,
  `tools/verify_dependency_audit.py`, `tools/verify_mypy_policy.py`,
  `tools/verify_ruff_policy.py` and `tests/test_portable_windows_policy.py`.
  An action update must change the old SHA in each of these files that
  contains it. Search for the old SHA in `tools/` and `tests/`, and check the
  new SHA against the release tag of the action before you change it.
- A Streamlit update needs a review of `tests/native_callable_page_client.py`,
  which accepts one reviewed Streamlit release.
- After a Kaleido update, review `tests/real_image_guard.py`. It replaces the
  one-shot runner of Kaleido 1.5, and `tests/test_real_image_guard.py` fails
  when Kaleido moves that runner.
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
