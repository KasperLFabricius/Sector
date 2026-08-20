# PR-A04b1b2a v0.95 explicit no-field wording acceptance

## Exact boundary

- Exact base: `d65199984c2dea07f4fefc31af0fa7fade47be22`.
- Base tree: `beb3a5532e20dc7a71c8241614c0d2e137bd1db8`.
- Product version remains `0.94`; project schema remains `25`.
- Dependency: PR-A04b1b1 owns only the shared-language rule.

## Contract

`retired_crack_wording_rules` additionally returns
`no-crack-limit-field-language` only for explicit no-field forms: `with no`,
`if no`, `without a` (or `without an`) and a declared no-field value that is
entered, supplied, provided or set. The owned field identities are criterion or
criteria, crack criterion, crack-width criterion, crack width, permitted width
and permitted crack width.

The rule does not interpret crack-result evidence, missing retained branches,
fatigue/torsion/reinforcement criteria, or blank/absent wording. Input is never
rewritten and the existing shared-language behavior remains unchanged.

## Exclusions

- No generic blank/absent field rule and no singular optional-limit rule.
- No request-gate decision, text rewrite or runtime callsite.
- No schema, solver, app, report, manual, README or product-identity activation.
- No unrelated v0.95 feature, version bump, qualification or release work.
