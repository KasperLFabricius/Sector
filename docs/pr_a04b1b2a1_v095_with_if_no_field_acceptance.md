# PR-A04b1b2a1 v0.95 with-or-if-no field wording acceptance

## Exact boundary

- Exact base: `d65199984c2dea07f4fefc31af0fa7fade47be22`.
- Base tree: `beb3a5532e20dc7a71c8241614c0d2e137bd1db8`.
- Product version remains `0.94`; project schema remains `25`.
- Dependency: PR-A04b1b1 owns only the shared-language rule.

## Contract

`retired_crack_wording_rules` additionally returns
`with-or-if-no-crack-limit-field-language` only when `with no` or `if no`
immediately owns a criterion, crack criterion, crack-width criterion, crack
width, permitted width or permitted crack width identity. Singular and plural
width/criterion forms are accepted.

The rule excludes retained result, evidence, branch, calculation and output
suffixes. It does not interpret `without`, declared no-field, blank or absent
wording, or unrelated fatigue/torsion/reinforcement criteria. Input is never
rewritten and the existing shared-language behavior remains unchanged.

## Exclusions

- No `without`, declared no-field, blank/absent or optional-limit rule.
- No request-gate decision, text rewrite or runtime callsite.
- No schema, solver, app, report, manual, README or product-identity activation.
- No unrelated v0.95 feature, version bump, qualification or release work.
