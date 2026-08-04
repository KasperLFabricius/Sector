# PR-11A3aR3 - F039 manual equation semantic contract

## Exact base and independent recut

- Base commit: `e25e730c5129a1b5f5a9a194e6bb91e2e5f761cf`.
- Base tree: `e6e3de5d543893b8f39ee63ec2f4f335fd68c8dc`.
- Application version: `0.91` and unchanged.
- This slice is independently authored from accepted `main`, the retained Part C
  manual source, accepted solver/report contracts and local Design Basis
  identities.
- No code, patch, commit or ancestry is reused from rejected PR #303 or #304.

## Frozen catalogue

- Exactly 32 Part C display equations are registered in authored order.
- Stable section-based identities run from `C3-1` through `C11-2`.
- Every equation retains its part, section, subsection and exact expression
  SHA-256.
- The two identical Formula (6.29) expressions remain distinct semantic records:
  torsion `C10-2` and combined interaction `C11-1`.
- Missing, duplicated, reordered, moved or altered source equations are rejected.

## Complete retained fields

Every record has independently authored and immutable:

- semantic key and public number;
- exact source location and expression identity;
- complete equation-local symbol, meaning and unit inventory;
- dimensional-closure note;
- standard, mixed or project source identity;
- genuine dependency links only.

The complete catalogue contains 201 local symbol definitions and nine dependency
links. Complete identity, source, symbol, dimensional and dependency inventories
have stable SHA-256 seals. Missing, duplicated, reordered, unknown, altered or
coherently resealed retained fields are rejected rather than ignored.

## Dimensional closure pins

- Curvature is `1/m`; plastic and prestress projected coordinates are metres.
- The minimum-link coefficient `c` is `MPa^(1/2)`, so
  `c sqrt(f_ck) / f_ywk` is dimensionless.
- `C_Rd,c` is `MPa^(2/3)`, so its product with `f_ck^(1/3)` is a stress in MPa.
- In `C9-3`, `M_Ed / V_Ed`, `a_cs` and the converted effective depth are metres.
- In `C10-1`, `A_k` is square metres and `t_ef` is metres; the retained mixed-unit
  conversion from link area/spacing and MPa produces kNm.
- Fatigue constants 40 and 250 explicitly carry MPa in their dimensional notes;
  `N^*`, `N_R` and `n_i` carry cycles.
- Generic `S_Ed` and `S_Rd` carry matching action identity rather than being
  advertised as dimensionless quantities.

## Source and dependency rules

- Project-defined methods remain uncited.
- Standard equations retain only their selected local Design Basis identity; no
  new external source or published-not-implemented method is introduced.
- Formula dependencies are explicit for minimum torsion links, both crack-width
  families, reinforcement fatigue life and Miner damage, 2023 shear links, the
  torsion strut interaction and the combined strut reuse.
- No candidate-selected result, source, symbol, unit or dependency is trusted.

## Explicit exclusions

- No PDF or Streamlit rendering; renderer fidelity is owned by PR-11A3bR3.
- No solver, formula, resistance, demand, utilization, verdict or trace change.
- No report-equation change.
- No Figure/Table numbering, captions, repeated units or grayscale work (PR-11B).
- No shared publication-style or PDF-preflight work (PR-11C).
- No schema, persistence, workflow, package, signing, version, PR-12+, release or
  v0.93 work.
