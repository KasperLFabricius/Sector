# PR-08D2 CT-009 EN 1992-1-1:2023 acceptance

## Frozen boundary

This slice activates CT-009 only for the exact selector
`EN 1992-1-1:2023`, edition `2023`, with the Danish national annex disabled.
It independently replays the already accepted section, elastic and crack-width
kernels. It does not change a solver or engineering formula.

The family contains long-term, short-term and ordered aggregate members. A
calculated case uses one of two distinct methods: refined bending or the
validated uniform direct-tension branch for a solid rectangle with reinforcement
on opposed faces. Unsupported 2023 geometry or strain regimes remain explicitly
`NOT ASSESSED`; an uncracked section remains `NOT APPLICABLE`; a non-converged
solve remains failed. No undefined or failed member publishes a fabricated
number.

## Identity and reconstruction

The trace seals the complete current-schema geometry, material catalogues,
selected material IDs, element assignments, route controls, actions and retained
output inventory. `sls_member` is type-pinned and value-inert. `sls_tendon_xi` is
type-pinned and value-inert unless a 2023 route has an actual tendon; then it is a
finite active value in `(0, 1]` and reaches Formula (9.6), Formula (9.12) and the
final width.

Every calculated candidate exposes final-reaching evidence for the effective
height and area, mild and prestressing areas, `xi1` where applicable, weighted
prestressing area, effective reinforcement ratio, reinforcement stress,
diameter, cover, `kw`, `k1/r`, `kfl`, `kb`, mean strain, calculated spacing,
scope identity and calculated width. The registry uses distinct method identities
for bending, direct tension, applicability, aggregate and failure members.

## Provenance

The method sources are the local `DS/EN 1992-1-1:2023` lifecycle:

- 9.2.3 Formula (9.8), including `kw = 1.7`;
- 9.2.3 Formula (9.9), curvature factor;
- 9.2.3 Formula (9.11), mean strain difference;
- 9.2.3 Formula (9.12), effective reinforcement ratio;
- 9.2.3 Figure 9.3, effective tension area;
- 9.2.3 Formula (9.15), calculated mean crack spacing;
- 9.2.3 Formula (9.17), bending flexural coefficient;
- 9.2.3 Formula (9.18), bond factor;
- 9.2.3 Formula (9.20), pure-tension coefficient;
- 9.2.2(3) Formula (9.6), tendon bond conversion.

Published 2023 concrete, reinforcing-steel or prestressing-steel material laws
remain outside CT-009 implementation scope. If an actually selected material has
that provenance, the trace fails closed instead of converting the crack method's
2023 source into material-law evidence.

## Exclusions

No crack limit, resistance, utilisation or engineering verdict is introduced.
No generic orthogonal or inclined crack-system interaction is inferred. No Danish
NA or bridge mechanics are extended to 2023. Accepted 2004 base, building-DK,
bridge-base and bridge-DK bundle bytes remain frozen.
