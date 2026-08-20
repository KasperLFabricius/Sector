# PR-A04b1b1 v0.95 shared crack-wording detector acceptance

## Exact boundary

- Exact base: `f954e525f90f5abf6e8364470088442d52773d08`.
- Base tree: `c87e7195b097985e5518c39f275c461d695af8c9`.
- Product version remains `0.94`; project schema remains `25`.
- This is a dormant QA prerequisite for the later dual-criterion activation.

## Contract

`retired_crack_wording_rules` returns `shared-crack-limit-language` when
`shared` and a crack, permitted-width, criterion or criteria identity occur in
the same local phrase, in either order, with at most five intervening words.
Sentence and clause punctuation terminate the phrase. Nearby but independent
shared reinforcement, stirrup or member-check language remains permitted.

Non-text input returns `invalid-text`; input is never rewritten. This slice
does not yet detect blank/absent or singular optional-criterion wording. Those
independent rule families belong to the following dormant slices.

## Exclusions

- No blank/absent or optional-limit rule.
- No request-gate decision, text rewrite or runtime callsite.
- No schema, solver, app, report, manual, README or product-identity activation.
- No unrelated v0.95 feature, version bump, qualification or release work.
