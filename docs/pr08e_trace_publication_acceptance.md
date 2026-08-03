# PR-08E trace publication acceptance matrix

Base: exact accepted `main` `9f09ac0765d11af47a70667eafc8f8f1faa24d95`.
Application version: `0.91` (unchanged). Project schema: `23` (unchanged).

## Frozen boundary

- Activate the already accepted CT-002 through CT-011 trace builders. Do not add,
  change or duplicate solver mechanics.
- Publish Plastic cases in retained table order, then Elastic cases in retained
  table order, then project-level fatigue and bridge calculations.
- Pin every case by family, one-based position, exact name and a SHA-256 of the
  retained typed case signature. Pin single/project analyses explicitly.
- Pin exact project-input identity in the live app. Direct headless callers use
  the strict type-retaining payload fingerprint as the deterministic fallback.
- Pin every case/global result with an order-independent, type-tagged SHA-256.
  Boolean/integer/float, list/tuple, NumPy dtype, pandas dtype/index, dataclass
  identity, negative zero and explicit non-finite values remain distinct. The
  recursively reserved publication key is inert to prevent self-reference.
- A sealed publication contains exact context, result scope, ordered sealed trace
  bundles and family-local errors. Case CT-008 may consume the shared root clear-
  spacing result; that composite scope is explicit and revalidated.
- Applicable order is CT-002, CT-003/004, CT-005, CT-006, CT-007, CT-008,
  CT-009, CT-010 and CT-011. Inactive builders publish nothing. One rejected
  family publishes a transparent local error and cannot hide another valid family
  or its retained solver result.
- CT-002 and CT-003/004 gain public replay validators matching CT-005--CT-011.
  Every stored bundle traverses its family validator from original inputs and
  retained results again before any app or PDF renderer may consume its rows.
- The app, report and manual consume one common row formatter. It carries exact
  step order/ID/title, quantity role, symbol, symbolic expression, numerical
  substitution, genuine result state/value/reason, unit, source/citation,
  dependencies, warnings and assumptions. Renderers do not decode status legends,
  choose governing state or recompute formulas.
- Standard sources retain document, edition, clause, locator and method. Input
  sources remain input. Project methods remain `Project-defined / uncited`.
- The manual includes one complete real CT-011 worked example. The issued report
  gets an ordinary calculation-trace chapter whenever publication data exists.
- The calculation record stores both exact input and result fingerprints while
  project files continue to exclude calculation results.

## Adversarial acceptance

- Reject missing/extra publication fields, invalid hashes, changed result values,
  changed result types, reordered positional collections, changed context axes,
  altered bundle content, coherently resealed downstream chains and duplicate
  calculation identities.
- Prove mapping insertion order and recursive publication content are hash-inert.
- Prove family-local publication failure remains visible without removing the
  retained result.
- Prove UI, report and manual consume the same 12-step real standards fixture and
  retain the DS/EN 1992-2 source, clause, substitutions, units and final state.
- Run focused trace/publication/persistence/case/UI/report/manual tests first;
  then directly affected retained mechanics and cheap guards; then the designated
  PR-08E full regression, rendered report/manual inspection, package/workflow gate
  and affected viewport inspection.

## Explicit exclusions

No formula/solver change, standards expansion, generic compliance claim, status-
legend reinterpretation, legacy schema, removed PR-07 function, report-only
recalculation, signing, release/version change, PR-09--PR-14 work, v0.93 candidate,
rejected-head code or excluded path is in scope.
