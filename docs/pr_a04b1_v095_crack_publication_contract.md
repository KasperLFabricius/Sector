# PR-A04b1 v0.95 crack-criterion publication contract

## Exact boundary

- Exact base: `438cf70bc9d4865ca10abb00af29537c7b905e67`.
- Base tree: `4d2f695b6b1bbee3c49c575b0c396226aef8ef25`.
- Product version remains `0.94` and project schema remains `25` in this
  dormant contract slice.
- Owner outcome: `OA095-003`.
- Dependency: merged PR-A04a owns strict non-negative project scalar parsing.
- Activation: PR-A04b2 will atomically add schema 26, the dual-duration
  calculation/application behavior and every publication update below.

This slice changes no runtime, project schema, calculation, report or manual.
It freezes one wording family after repeated review findings exposed ambiguity
between an absent shared criterion and two present user-owned numeric limits.

## Canonical meaning

1. Analysis settings contain independent long-term and short-term ordinary
   crack-width limits.
2. The per-action crack-width request remains authoritative. When calculation
   is not requested, the result is `NOT REQUESTED` and no width is published,
   irrespective of either stored limit.
3. When crack-width calculation is requested, each limit is numeric. A value
   of `0 mm` means calculate and state that duration's crack width without
   comparison.
4. A positive value compares only the matching duration and produces a bounded
   user-limit result. It is not a code-compliance or project verdict.
5. The Formula 7.100 NA permitted width is a separate input. It is not either
   ordinary duration limit and has no fallback to them.
6. Sector does not infer a Eurocode limit, exposure class, load-combination
   classification, owner requirement, certification or engineering approval.

## Required publication sweep

PR-A04b2 must update all of these surfaces in the same activation:

- Analysis input labels and help;
- Elastic result and Results Overview wording;
- Standard, Audit and Brief reports;
- `README.md` feature summary;
- `app/manual.py`, including overview, results, detailed crack-width,
  project-schema and troubleshooting passages;
- `app/manual_information_architecture.py` warning guidance;
- `docs/product_identity.md`;
- `app/load_cases.py` module contract;
- reproducible and rendered fixtures; and
- direct tests that inspect each retained/public surface.

## Required language

Every general summary must communicate all of the following where space permits:

- independent long-term and short-term limits;
- `0 mm` disables only the matching comparison while retaining the calculation;
- a positive value enables only the matching duration comparison; and
- the Formula 7.100 NA operand is separate wherever heightened control is
  discussed.

The following retired language is forbidden on current user-facing surfaces:

- `With no criterion`;
- `Without a criterion`;
- `If no criterion is entered`;
- `if a criterion is entered`;
- `optional user-specified crack-width criterion`;
- `one optional positive permitted width`;
- `blank ordinary crack criterion`;
- `One optional permitted width in Analysis settings is shared by`;
- `shared by every ordinary and heightened crack check`;
- `shared Analysis permitted width`; and
- `supply the shared permitted width`.

Historical decision registers and older version-programme documents remain
immutable evidence and are excluded from the current-surface wording sweep.

## Acceptance matrix

| ID | Surface condition | Required result |
|---|---|---|
| A04b1-00 | Per-action crack-width calculation is disabled | Result is `NOT REQUESTED`; stored limits do not request, calculate or publish a width. |
| A04b1-01 | Crack calculation is requested; long-term limit is 0; short-term is positive | Long-term is stated without comparison; short-term alone is compared. |
| A04b1-02 | Crack calculation is requested; short-term limit is 0; long-term is positive | Short-term is stated without comparison; long-term alone is compared. |
| A04b1-03 | Crack calculation is requested; both limits are 0 | Both widths remain stated; neither is described as blank, missing, passing or failing. |
| A04b1-04 | Crack calculation is requested; both limits are positive | Each width is compared only with its duration-matched value. |
| A04b1-05 | Heightened control is discussed | Formula 7.100 NA uses its separate positive permitted-width operand. |
| A04b1-06 | Manual and product summaries are searched | Every retired phrase above is absent from current surfaces. |
| A04b1-07 | Historical documents are searched | They are not rewritten to pretend the former released behavior never existed. |

## Exclusions

- No schema or project migration.
- No solver, action, stiffness, `k_t`, crack-width or comparison change.
- No application, report, manual or README activation.
- No Results Overview redesign, fatigue, hover, EC-reference, plastic-summary,
  report-layout or unrelated manual cleanup.
- No version bump, full suite, packaging or release publication.
