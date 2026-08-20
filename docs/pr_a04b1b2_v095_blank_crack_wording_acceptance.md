# PR-A04b1b2 v0.95 blank crack-wording detector acceptance

## Exact boundary

- Exact base: `d65199984c2dea07f4fefc31af0fa7fade47be22`.
- Base tree: `beb3a5532e20dc7a71c8241614c0d2e137bd1db8`.
- Product version remains `0.94`; project schema remains `25`.
- Dependency: PR-A04b1b1 owns only the shared-language rule.

## Contract

`retired_crack_wording_rules` additionally returns
`blank-or-absent-criterion-language` for current prose that represents a crack,
permitted-width or criterion field as blank or absent, in either word
order and within one clause. It also detects the explicit `with no`, `if no`,
`without a`, and `no criterion is entered/supplied/provided/set` forms.

Numeric zero-limit/no-comparison wording is current and remains allowed. Blank
reinforcement/material language and missing retained crack-branch diagnostics
are unrelated and remain allowed. The existing shared-language rule and
non-text failure behavior remain unchanged.

## Exclusions

- No singular optional-limit rule.
- No request-gate decision, text rewrite or runtime callsite.
- No schema, solver, app, report, manual, README or product-identity activation.
- No unrelated v0.95 feature, version bump, qualification or release work.
