# Sector: guide for agents and developers

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
  An action update must change the old SHA in each of these files. Search for
  the old SHA in `tools/` and `tests/`, and check the new SHA against the
  release tag of the action before you change it.
- A Streamlit update needs a review of `tests/native_callable_page_client.py`,
  which accepts one reviewed Streamlit release.
- Update the exact Python pin in `.python-version` by hand.
