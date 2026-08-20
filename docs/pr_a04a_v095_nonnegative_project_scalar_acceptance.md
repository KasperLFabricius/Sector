# PR-A04a v0.95 non-negative project-scalar boundary acceptance

## Exact boundary

- Exact base: `9679df947ffed1ab65893de916c442323ec4d4b9`.
- Product version remains Sector 0.94 and project schema remains 25.
- Change family: one dormant project-persistence numeric normalizer and its
  direct tests.

This prerequisite exists so the later dual crack-criteria slice can persist
zero-or-positive criteria without coercing Boolean-like values into numbers.
It has no production call site in this PR and therefore changes no current
runtime, schema, calculation, result, report or manual behavior.

## Numeric contract

1. Built-in and NumPy real values are normalized to a built-in finite float.
2. Zero and positive finite values are accepted without clamping.
3. Negative values, NaN, either infinity and conversion failures are rejected
   with `ValueError`.
4. Built-in Boolean and NumPy Boolean scalars are rejected before numeric
   conversion. Text and bytes are also rejected rather than parsed.
5. The source value is not mutated.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| A04a-01 | `0`, `0.25`, NumPy real or a finite value above one | Return the same numeric value as a built-in `float`. |
| A04a-02 | `True`, `False`, `np.bool_(True)` or `np.bool_(False)` | Reject; never persist `1.0` or `0.0`. |
| A04a-03 | Text, bytes, negative, NaN or infinity | Reject with `ValueError`. |
| A04a-04 | Conversion raises type, value or overflow error | Reject with `ValueError`. |
| A04a-05 | Repository call sites are inspected | The helper is dormant outside direct tests. |

## Focused verification

- direct parameterized normalization and rejection tests;
- exact signature, built-in output type and no-mutation controls;
- Ruff, strict mypy, compile and diff checks.

The dual crack-width inputs, schema migration and every end-user surface remain
owned by the replacement PR-A04 feature slice.
