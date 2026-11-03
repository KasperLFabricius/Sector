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
each area that you changed.

Refresh the duration table from the shard evidence of a completed QA run.
The table also sets the shard balance in CI, so commit the new table:

```
gh run download <run-id> --pattern "sector-core-<run-id>-<attempt>-core-*" --dir qa-durations
python tools/qa_core_shards.py durations --input qa-durations --output tools/qa_shard_durations.json
```
