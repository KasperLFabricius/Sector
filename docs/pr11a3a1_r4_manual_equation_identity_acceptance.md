# PR-11A3a1R4 - manual equation identity and source provenance

## Exact base and recut

- Base commit: `e25e730c5129a1b5f5a9a194e6bb91e2e5f761cf`.
- Base tree: `e6e3de5d543893b8f39ee63ec2f4f335fd68c8dc`.
- Application version: `0.91` and unchanged.
- This is an independent recut from accepted `main`, retained Part C content,
  accepted solver/report provenance and local Design Basis identities.
- No code, patch, commit or ancestry is reused from rejected PR #303, #304 or
  #305.

## Frozen boundary

- Exactly 32 display equations inside `Part C - Theory & methodology` are in
  scope. Display equations added to Parts A, B or D are inert to this catalogue.
- Stable authored order, ordinal, semantic key and public number run from `C3-1`
  through `C11-2`.
- Each record retains exact part, section, subsection, expression SHA-256, source
  kind and source text.
- Missing, duplicate, reordered, moved, unknown, altered and coherently resealed
  identities or sources fail closed.
- The identical Formula (6.29) expressions retain distinct torsion `C10-2` and
  combined `C11-1` identities.

## Source provenance

- Sources are reconstructed from accepted solver/report code and the retained
  local manual standards register, not from rejected candidates.
- Project-defined steel-law and capacity-search methods remain explicitly
  uncited.
- Mixed project/standard records identify both roles without converting a
  project convention into a standard requirement.
- C9-3 records DS/EN 1992-1-1:2023 8.2.2(4), Formulas (8.30) and (8.31), matching
  `sector/shear.py` and `app/sector_report.py`. Formula (8.27) remains the separate
  downstream resistance expression and is not assigned to C9-3.
- Concrete fatigue strength retains Formula (6.76) for the 2005 edition and
  Formula (10.5) for the 2023 edition. The separate equivalent-utilisation
  expression retains Formula (6.72) and Formula (E.2), respectively; the life
  relation alone retains Formula (6.106) and Formulas (E.7)-(E.8).
- The 2023 minimum-reinforcement records retain Formulas (12.1) and (12.2).
- Torsion transverse resistance retains the accepted distinction between wall
  shear flow Formula (6.27), transverse equilibrium Formula (6.8), and concrete
  strut Formula (6.30).

## Explicit exclusions

- No symbol, unit, dimensional or dependency inventory; PR-11A3a2 owns those
  fields after this identity/source catalogue is accepted.
- No PDF or Streamlit rendering; PR-11A3b owns visible equation blocks.
- No solver, formula, resistance, demand, utilization, verdict, trace or report
  equation change.
- No Figure/Table numbering, captions, repeated units or grayscale work (PR-11B).
- No shared publication style or PDF preflight work (PR-11C).
- No schema, persistence, workflow, package, signing, version, PR-12+, release or
  v0.93 work.
