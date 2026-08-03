# PR-08D.1c acceptance: CT-009 bridge routes

Base: the exact accepted `main` after PR #271. Scope is the retained 2004
crack-width replay for the two current bridge selectors only; no solver or
formula changes are permitted.

## Frozen routes

- `DS/EN 1992-2:2005 + AC:2008`, edition `2004`, `sls_dk_na=False`: exact
  long-term, short-term, aggregate order and the already accepted base
  EN 1992-1-1:2004 mechanics.
- `DS/EN 1992-2 DK NA:2015`, edition `2004`, `sls_dk_na=True`: exact
  long/short fine, long/short coarse, aggregate order and the already accepted
  building-DK mechanics, including member/prestress, cover-k3, effective-area,
  and half-width rules.

## Provenance and closure

- DS/EN 1992-2:2005 clause 7.3.4(101) recommends EN 1992-1-1 clause 7.3.4;
  AC:2008 contains no crack-width correction to that route.
- DS/EN 1992-2 DK NA:2015 clause 7.3.4(101) states `No national choice`.
- Every route citation depends directly on every sealed original-input identity
  word and reaches its member final. The DK member/prestress selector remains
  independently bound to the complete input identity.
- Every successful crack-owned output leaf is independently reconstructed.
  Non-owned recursive sibling presence, order, cardinality, and type are pinned.
- Failure is decided from original inputs and retained mechanics before candidate
  numerical parsing. Both bridge routes seal the exact failed code, edition, and
  member metadata to the failure final while arbitrary failure-only numerics stay
  inert. No value or engineering verdict is fabricated.
- Accepted base and building-DK success and failure bundles remain byte-exact.

## Explicit exclusions

EN 1992-1-1:2023; concrete fatigue; chord/off-utilisation/biaxial and CT-002
joins; activation, UI, persistence, report, manual, package, workflow, and
version wiring; limits, utilisation, resistance, verdicts, solver/formula
changes, PR-07 removals, F-020, v0.93, and all rejected heads.
