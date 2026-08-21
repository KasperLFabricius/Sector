# PR-A04b2 v0.95 dual crack-width activation acceptance

## Exact boundary

- Exact base: `d65199984c2dea07f4fefc31af0fa7fade47be22`.
- Base tree: `beb3a5532e20dc7a71c8241614c0d2e137bd1db8`.
- Product version remains `0.94`; this PR alone advances the project schema from
  25 to 26.
- Owner outcome: `OA095-003` - replace the single ordinary crack-width
  criterion with independent long-term and short-term user criteria while
  isolating the separate Formula 7.100 NA permitted-width operand.
- Dependencies: PR-A00b and PR-A04a are merged; PR-A04b1a freezes the request
  gate and PR-A04b1b1 freezes the shared-limit language detector used by this
  activation. This PR directly owns exact assertions for its retired blank,
  no-criterion and singular optional-limit publication phrases; it does not
  introduce a generic prose parser.
- Change family: ordinary crack-limit identity, duration-matched assessment,
  exact schema migration and the directly dependent app/report surfaces.

This PR does not infer a Eurocode limit, load-combination classification,
project compliance, certification or engineering approval. It does not decide
whether a long-term comparison is required. The user owns both optional limits
and the applicability of each comparison.

## Engineering and standards boundary

Sector retains two existing calculation branches for each crack-enabled Elastic
case:

- the long-term branch uses the existing sustained action and `k_t = 0.4`; and
- the short-term branch uses the existing instantaneous total action and
  `k_t = 0.6`.

The selected ordinary crack-width design basis and solver equations are
unchanged. EN 1992-1-1 clause 7.3.4 uses the relevant load combination, while
the clause 7.3.1 acceptance context depends on member and combination. Sector
therefore does not relabel either stored action as a code-defined frequent or
quasi-permanent combination and does not supply a default limit. Project inputs
must establish that relationship.

The optional Danish heightened calculation remains a separate section-level
Formula 7.100 NA calculation. Its permitted-width operand is not either
ordinary duration limit.

## Persisted identity and input contract

Schema 26 owns exactly these three width keys:

| Purpose | Key |
|---|---|
| Ordinary long-term comparison | `sls_long_term_permitted_crack_width_mm` |
| Ordinary short-term comparison | `sls_short_term_permitted_crack_width_mm` |
| Heightened Formula 7.100 NA operand | `sls_heightened_permitted_crack_width_mm` |

1. Each ordinary key is a finite non-negative number in millimetres. `0.0`
   means that the duration is calculated and stated without an acceptance
   comparison. A positive value enables only its matching comparison.
2. Boolean, text, negative and non-finite values are rejected. Canonical saves
   always write both ordinary keys; a missing in-memory value is normalized to
   `0.0` before save.
3. The heightened operand is independent. When heightened control is enabled it
   must be a positive finite number. When disabled, a finite non-negative value
   may be retained but is not applied; `0.0` is the canonical unset value.
4. Changing any of the three keys invalidates the retained Elastic/result
   signature. No prior single-width result may be reused as current.
5. The Analysis panel shows two ordinary inputs together and the heightened
   operand only within the heightened controls. Help text states that all three
   are user-specified and that Sector infers no acceptance limit.

## Duration-matched retained result contract

`elastic.crack_output` becomes a mapping with exactly two assessment members,
`long_term` and `short_term`. Each member retains its own:

- calculated maximum over the fine/coarse candidates for that duration;
- branch/case and governing element identity;
- unit, calculation state and diagnostic reason;
- user criterion and criterion source; and
- comparison ratio/equation only when its own positive criterion applies.

There is no cross-duration acceptance state or global ordinary crack verdict.
The largest long-term width is never compared with the short-term limit, and the
largest short-term width is never compared with the long-term limit. A zero
criterion is retained as `0.0`, produces
`CALCULATED - ACCEPTANCE NOT ASSESSED`, and emits no ratio or comparison
equation. Missing/invalid calculation evidence remains `NOT ASSESSED`; a case
that did not request cracking remains `NOT REQUESTED` for both durations.

Within one duration the existing deterministic fine-before-coarse tie behavior
is retained. Where the heightened adapter needs one ordinary reinforcement
evidence branch, it selects the largest calculated width across the two retained
duration outputs; an exact numeric tie remains long-term first. This selection
does not transfer either ordinary criterion into Formula 7.100 NA.

## Schema-25 to schema-26 migration

The retired schema-25 key is `sls_permitted_crack_width_mm`.

1. A positive finite schema-25 shared value migrates to both ordinary schema-26
   keys. This reproduces the only comparison that a schema-25 project requested;
   the migration warning tells the user to review the two now-independent
   values.
2. A blank, null or exact numeric zero shared value migrates to `0.0` for both
   ordinary keys and issues no comparison.
3. Boolean, text, negative and non-finite shared values are rejected rather than
   coerced.
4. If schema-25 heightened control is exactly enabled, the shared value must be
   positive and is also copied to the separate schema-26 heightened operand.
   This preserves the Formula 7.100 NA operand that schema 25 actually used.
5. If heightened control is disabled or missing, the schema-26 heightened
   operand becomes `0.0`, even when the old ordinary shared value was positive.
   Sector must not infer an inactive heightened operand from an ordinary limit.
6. An ordinary zero never becomes a heightened operand. Enabled heightened
   control combined with a blank/null/zero shared value is rejected because the
   old Formula 7.100 NA calculation lacked its required positive operand.
7. Existing bounded migration of retired schema-25 heightened reinforcement
   operands is preserved and composes with this width migration.
8. Loading never modifies the source file. Resaving writes schema 26 with the
   three new keys and no retired shared key. Schema 24 becomes unsupported; no
   backward schema-25 writer is added. Future schemas remain rejected.

## Application and publication contract

1. Elastic Results states the long-term and short-term widths separately with
   their matching criterion/status. A zero-limit row says that no comparison was
   requested; it is not a pass.
2. Until PR-A06 replaces Results Overview, the existing overview may emit one
   ordinary crack row per duration. It must not collapse the two into a global
   verdict or rank a smaller width as physically governing merely because its
   user limit is tighter.
3. Standard, Audit and Brief report content lists both ordinary criteria and the
   separate heightened operand. Ordinary result text and tables keep the two
   duration comparisons distinct.
4. Formula 7.100 NA validation, calculation and publication consume only
   `sls_heightened_permitted_crack_width_mm`. Neither ordinary key is a fallback.
5. Reproducible fixtures, project import/export, manual wording and input-issue
   navigation use the same three identities. No surface calls an ordinary
   long-term comparison a Eurocode requirement.

## Acceptance matrix

| ID | Authoritative condition | Required result |
|---|---|---|
| A04-01 | Long-term limit positive; short-term limit zero | Only the long-term width is compared; short-term is stated unassessed. |
| A04-02 | Long-term limit zero; short-term limit positive | Only the short-term width is compared; long-term is stated unassessed. |
| A04-03 | Both ordinary limits positive and each width is below/equal/above its own limit | Each duration emits its own exact ratio and within/exceeds state at the inclusive boundary. |
| A04-04 | Both ordinary limits are zero | Both widths remain visible; neither emits a ratio, equation, pass or fail. |
| A04-05 | Long-term width is numerically larger but short-term ratio is worse | Physical width provenance remains duration-local; no cross-duration comparison or global ordinary verdict is invented. |
| A04-06 | Fine and coarse candidates exist for both durations | Each duration selects only among its own candidates; deterministic same-duration ties remain stable. |
| A04-07 | Crack calculation was not requested | Both duration states are `NOT REQUESTED`, irrespective of stored limits. |
| A04-08 | Elastic result/candidate is invalid or unavailable for one duration | That duration is `NOT ASSESSED`; valid evidence in the other duration remains independently publishable. |
| A04-09 | Ordinary key is Boolean, text, negative, NaN or infinity | Save/load or direct assessment rejects/fails closed; no truthiness or numeric-string coercion. |
| A04-10 | Schema-25 shared limit is positive and heightened is disabled | Both ordinary limits receive it; heightened operand is `0.0`; one visible migration warning requests review. |
| A04-11 | Schema-25 shared limit is blank, null or zero and heightened is disabled | Both ordinary limits and heightened operand become `0.0`; no comparison is inferred. |
| A04-12 | Schema-25 shared limit is positive and heightened is enabled | Both ordinary limits and the separate heightened operand receive the exact old value. |
| A04-13 | Schema-25 heightened is enabled with blank/null/zero shared value | Migration rejects the project because the old heightened operand was incomplete. |
| A04-14 | Schema-25 shared value is malformed | Migration rejects it without changing the source file. |
| A04-15 | Migrated schema-25 project is resaved | Output is schema 26, contains exactly the three new width keys, and omits the retired shared key. |
| A04-16 | Current schema-26 heightened disabled with retained positive heightened operand | Operand may round-trip but is not calculated, compared or published as applicable. |
| A04-17 | Current schema-26 heightened enabled | Separate heightened operand must be positive; ordinary zero/positive values cannot satisfy it. |
| A04-18 | Any criterion changes after calculation | Elastic/result signature changes and stale retained results are not published as current. |
| A04-19 | Heightened reference evidence is selected | Largest calculated ordinary branch may supply reinforcement provenance, but Formula 7.100 receives only its separate permitted-width operand. |
| A04-20 | App, overview, Standard, Audit, Brief and manual are inspected | All use duration-specific ordinary wording and separate heightened wording; none emits certification, approval or a global crack verdict. |
| A04-21 | Schema support is inspected | Current is 26, only 25 is migratable, 24/future schemas are rejected, and no backward writer exists. |
| A04-22 | Repository scope is inspected | No fatigue screen, Results-Overview redesign, hover, EC-input provenance, plastic-summary, unrelated manual cleanup, governed version bump or release work enters this PR. |

## Focused verification

- headless crack-output tests for duration isolation, zero, boundaries,
  unavailable evidence, malformed criteria and deterministic candidates;
- case-signature and reuse tests for both ordinary keys and the separate
  heightened key;
- schema-26 save/load/resave plus every schema-25 migration row above, including
  unchanged-source and retired-key omission checks;
- heightened validation/calculation tests proving there is no ordinary fallback;
- Streamlit controls for the two ordinary inputs, the separate heightened input,
  zero behavior and stale-result invalidation;
- Results, Standard/Audit/Brief report, fixture and manual controls for distinct
  duration wording and omission of global-verdict language, plus exact
  publication-surface assertions for retired and required current phrases; and
- Ruff policy, strict mypy, compile, ASCII, diff, exact-scope, product-version
  and schema guards.

The full suite, coverage, portable package and release qualification remain at
the governed G1/G2 gates under D095-002.

## Explicit exclusions

- No default or inferred crack-width limit and no new selectable design basis.
- No change to crack-width equations, `k_t`, elastic actions, cracking threshold
  or fine/coarse system mechanics.
- No relabelling of stored action parts as a code-defined load combination.
- No global crack/project verdict, certification or engineering approval.
- No PR-A05 through PR-A10 implementation.
- No product-version bump, full-suite, packaging or release work.
