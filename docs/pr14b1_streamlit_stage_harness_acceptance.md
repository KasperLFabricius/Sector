# PR-14B.1 Streamlit active-stage harness acceptance

## Exact base and defect class

This bounded correction starts from accepted main
`237e09ff7ce095a0b2c99e1548aed1b52451f721`. The PR-14C consolidated gate
proved one deterministic Streamlit compatibility class: retained tests written
before PR-12 still addressed inactive-stage widgets directly, while Streamlit
1.59 AppTest retained the preceding Quick Section fragment nodes after the app
had correctly completed its full-workspace transition.

The product state after Quick Section Apply/Back was already correct: the
builder was closed, Inputs was active, explicit section tables were committed
and the durable `qsv_` mirror retained every builder setting. The stale client
tree nevertheless attempted to serialize the removed `shape` widget and raised
before the next test action.

## Frozen correction

1. The retained AppTest harness removes only the two retired Quick Section
   sibling containers after Streamlit has completed the full-app replacement.
   This mirrors the browser's replacement delta; application state, builder
   values and the replacement Inputs tree are untouched.
2. Retained tests explicitly open the active Section, Loads or material-family
   owner before exercising controls that PR-12 deliberately unmounted.
3. Manual lifecycle tests open the Concrete material owner before editing
   `conc_fck`.

Acceptance requires the complete previously failing 54-test inventory, the
direct PR-12 stage/fragment suites and cheap guards. PR-14C remains the owner of
the consolidated full-suite gate. No test is skipped, xfailed or weakened.

## Explicit exclusions

No production module, solver, formula, standard, result, verdict, input value, project schema,
report/manual content, package, workflow, dependency, application version,
calculation-trace or v0.93 behavior changes. This correction does not remount
inactive engineering stages or restore work removed by PR-07/R1-R5.
