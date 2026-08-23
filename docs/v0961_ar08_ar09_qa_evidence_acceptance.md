# v0.96.1 AR-08/AR-09 QA evidence acceptance

## Scope

This change closes two QA-depth findings without changing calculations, inputs,
results, the user interface, the manual, or report content:

- AR-08: measure and ratchet branch coverage where decisions and fail-closed
  outcomes are selected.
- AR-09: make the minimum retention of review evidence an executable policy.

## Branch-coverage contract

The complete suite continues to measure `app` and `sector` line coverage with the
existing 90% minimum. A separate bounded gate measures branches in six
decision-heavy modules:

- load-case normalization;
- modelled reinforcement direction;
- result status and governing-result presentation;
- project-state migration;
- design-standard selection; and
- heightened crack-control selection and validation.

The gate runs the six directly corresponding test modules. The Windows
calibration executed 213 tests in 11.80 seconds and measured 486 of 596 branches,
or 81.54%. The accepted minimum is 81%. The module inventory, test inventory and
minimum are all non-shrinking against the accepted base.

Branch tracing is deliberately isolated from the numerical solver suite. A trial
that traced every calculation module made the full test run unsuitable for the
60-minute CI limit. The bounded gate measures the control-flow code that motivated
AR-08, while the complete line-coverage suite and all existing engineering tests
remain mandatory.

## Evidence-retention contract

Policy tests now require:

- QA diagnostics to be uploaded even after a failed gate and retained for at
  least 7 days; and
- the portable ZIP and checksum to be retained for at least 14 days.

Reducing either period, disabling the unconditional QA upload, changing the
artifact contents, omitting a declared branch module, removing branch tracing, or
lowering an accepted threshold fails the policy suite.

## Closure evidence

- decision-branch calibration: 213 passed; 81.54% branch coverage;
- coverage, retention, portable and image policy tests: 50 passed;
- adjacent dependency, typing and lint policy tests: 130 passed;
- contract validation against the accepted main branch: passed;
- focused Ruff and bytecode compilation: passed.
