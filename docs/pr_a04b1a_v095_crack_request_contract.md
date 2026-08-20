# PR-A04b1a v0.95 crack-width request contract

## Exact boundary

- Exact base: `438cf70bc9d4865ca10abb00af29537c7b905e67`.
- Base tree: `4d2f695b6b1bbee3c49c575b0c396226aef8ef25`.
- Product version remains `0.94`; project schema remains `25`.
- Owner outcome: `OA095-003`.
- This is a dormant prerequisite for the later dual-criterion activation.

No production callsite, runtime result, project file, report or manual changes in
this slice.

## Authoritative request gate

1. Each Elastic action owns `calculate_crack_width` independently of the
   project-level permitted-width settings.
2. `calculate_crack_width is False` means the calculation was not requested.
   Its retained result state is `NOT REQUESTED`; no ordinary crack width, ratio
   or comparison is published for that action.
3. A stored ordinary limit, including `0 mm` or a positive value, never turns
   the per-action request on.
4. Only when `calculate_crack_width is True` may the ordinary long-term and
   short-term crack-width branches be calculated and stated.
5. For a requested calculation, `0 mm` means state the matching duration width
   without comparison. A positive value enables only that duration's bounded
   user-limit comparison.
6. The request gate does not infer a required load combination, code limit,
   project verdict, certification or engineering approval.

## Acceptance matrix

| ID | Action request | Stored duration limit | Required state |
|---|---|---|---|
| A04b1a-01 | False | 0 mm | `NOT REQUESTED`; no width or comparison. |
| A04b1a-02 | False | Positive | `NOT REQUESTED`; the positive value does not request a calculation. |
| A04b1a-03 | True | 0 mm | Width may be calculated and stated without comparison. |
| A04b1a-04 | True | Positive | Width may be calculated and compared only with the matching duration limit. |
| A04b1a-05 | Different Elastic rows use different request flags | Any | Each row follows only its own flag. |

## Later activation requirements

The dual-criterion activation must preserve all of the following:

- the action-table `calculate_crack_width` identity and default-off behavior;
- `sector.sls.crack_outputs(..., requested=...)` fail-closed routing;
- separate `NOT REQUESTED` results for long-term and short-term branches;
- project-level limits as comparison inputs only, never request inputs; and
- direct disabled-action controls with both zero and positive stored limits.

## Exclusions

- No retired-language inventory; PR-A04b1b owns that independent prerequisite.
- No schema migration or dual-duration result activation.
- No solver, stiffness, action, crack-width equation or `k_t` change.
- No app, Results Overview, report, manual, README or product-identity update.
- No unrelated v0.95 feature, version bump, qualification or release work.
