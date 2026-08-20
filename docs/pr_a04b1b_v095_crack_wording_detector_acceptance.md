# PR-A04b1b v0.95 retired crack-wording detector acceptance

## Exact boundary

- Exact base: `f954e525f90f5abf6e8364470088442d52773d08`.
- Base tree: `c87e7195b097985e5518c39f275c461d695af8c9`.
- Product version remains `0.94`; project schema remains `25`.
- Dependency: PR-A04b1a freezes the independent per-action request gate.
- This is a dormant QA prerequisite for the later dual-criterion activation.

## Detector contract

`tools.crack_publication_wording.retired_crack_wording_rules` consumes one
publication passage and returns stable rule IDs. It normalizes whitespace and
case, but does not rewrite its input.

The detector owns semantic families rather than a finite exact-phrase list:

1. `shared-crack-limit-language` catches `shared` in the same local phrase as a
   crack, permitted-width or criterion reference in either word order, with at
   most five intervening words and without crossing sentence or clause
   punctuation. This avoids conflating nearby but independent shared
   reinforcement or member-check language.
2. `blank-or-absent-criterion-language` catches blank/no-criterion instructions
   that contradict always-present numeric duration limits.
3. `singular-optional-criterion-language` catches one/an optional permitted
   width or one optional user-specified criterion.
4. Non-text input returns `invalid-text`; it is never silently treated as clean.

This covers all exact-base variants in README, app input help, input issues,
load-case/project contracts, manual, reproducible reference text, reports and
product identity. It also catches wording variants not yet known verbatim.

## Activation use

PR-A04b2 must extract each current user-facing Python string constant and each
current README/product-identity paragraph, pass them individually to the
detector and require no rule hits. Historical decision registers and released
version-programme documents remain immutable and are not scanned.

The detector intentionally permits:

- `optional crack width` when it describes the per-action calculation request;
- independent or duration-matched criterion wording;
- `shared closed stirrup`, common angle and other unrelated engineering uses;
- `0 mm` no-comparison wording; and
- historical evidence outside the current-surface allowlist.

## Exclusions

- No request-gate decision; PR-A04b1a owns it.
- No schema, solver, app, report, manual, README or product-identity activation.
- No runtime callsite or automatic text replacement.
- No unrelated v0.95 feature, version bump, qualification or release work.
