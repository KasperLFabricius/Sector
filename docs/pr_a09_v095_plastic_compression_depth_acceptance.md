# PR-A09 v0.95 plastic compression-zone depth acceptance

## Exact boundary

- Exact base: `3cd5a169603603a547db8063aca3b66c7079d1a2`.
- Product version remains Sector 0.94 and project schema remains 26 on this
  branch.
- Owner outcome: publish the retained plastic compression-zone depth `c` in
  the selected-state summary.
- Change family: presentation of one already-retained plastic result operand.

This PR does not change the plastic solver, neutral-axis search, material laws,
capacity, utilisation, persistence or result selection. It adds no new
calculation, project-wide pass/fail conclusion or engineering approval.

## Retained-result contract

1. The only authority is the selected plastic point's existing
   `compression_depth` field, retained by the plastic solver in metres.
2. The presentation layer converts that retained value to millimetres. It does
   not reconstruct depth from neutral-axis intercepts, section geometry or any
   other result.
3. A built-in or NumPy real that is finite and non-negative, and remains finite
   after conversion to millimetres, is displayable. Boolean, text, missing,
   negative, non-finite and conversion-overflow values remain unavailable.
4. Unavailable legacy or malformed evidence is shown as `-`; it never becomes
   zero and never aborts the Plastic Results view or report.
5. The user-facing identity is **Compression-zone depth `c`**. It is not called
   effective reinforcement depth `d`, effective tension-zone height, neutral-
   axis depth or a generic effective height.

## Publication surfaces

- Plastic Results adds `Compression-zone depth c` to the selected neutral-axis
  summary beside compression force, lever arm and strains.
- The governing worked plastic table in Standard/Audit reports adds the same
  retained quantity and unit.
- Brief/Results Overview and the full per-angle table remain unchanged.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| A09-01 | Retained `compression_depth=0.275` m | UI and worked report state `275.000 mm`. |
| A09-02 | Retained exact zero | UI/report state `0.000 mm`; no absence coercion occurs. |
| A09-03 | Missing or `None` field | UI/report show `-` and remain usable. |
| A09-04 | Boolean, text, negative, NaN or infinity | Evidence is unavailable; no coercion, recomputation or crash. |
| A09-05 | NumPy finite real | It is normalized and displayed in millimetres. |
| A09-06 | Source point inspected before and after presentation | The retained mapping is unchanged. |
| A09-07 | Labels and scope inspected | Only `compression-zone depth c` is used; no solver/schema/version/global-verdict change enters the PR. |

## Focused verification

- direct retained-value normalization and non-mutation tests;
- focused Plastic Results AppTest;
- focused semantic report assertion;
- Ruff, strict mypy, compile and diff checks.

Full-suite, real-render, package and release qualification remain at the
governed v0.95 release gate.
