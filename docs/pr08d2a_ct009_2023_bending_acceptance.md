# PR-08D2a CT-009 2023 refined-bending acceptance

## Boundary

This slice activates the exact `EN 1992-1-1:2023`, edition `2023`, non-DK
selector for refined bending, applicability, failure and ordered aggregation. It
replays the accepted section, elastic and crack-width kernels. It changes no
solver or formula.

Uniform direct tension and every 2023 case containing tendons fail closed with an
explicit deferred-subfamily error. They belong to PR-08D2b and are not silently
represented by the bending method. Danish NA and bridge 2023 routes are also
excluded.

## Contract

The family contains long-term, short-term and aggregate members in that order.
A calculated case has the refined-bending method identity. Unsupported geometry
or strain regimes are `NOT ASSESSED`; an uncracked section is `NOT APPLICABLE`;
non-convergence is failed. Aggregate selection preserves the distinction: any
unsupported case reaches an explicit `not-assessed` aggregate when no finite case
exists, while an entirely uncracked family remains `not-applicable`.

Every calculated candidate publishes final-reaching evidence for effective
height and area, mild and prestressing areas, weighted prestressing area,
effective reinforcement ratio, reinforcement stress, diameter, cover, `kw`,
`k1/r`, `kfl`, `kb`, mean strain, calculated spacing, bending identity and
calculated width. Complete current-schema geometry, material catalogues, selected
IDs, assignments, controls and retained outputs remain sealed. Without tendons,
`sls_member` and `sls_tendon_xi` retain required types but are value-inert.

## Provenance

Every final-reaching standard step, including the case `kt` method value, uses
the local `DS/EN 1992-1-1:2023` lifecycle:

- 9.2.3 Formula (9.8), calculated crack width and `kw`;
- 9.2.3 Formula (9.9), curvature factor;
- 9.2.3 Formula (9.11), mean strain difference and `kt`;
- 9.2.3 Formula (9.12), effective reinforcement ratio;
- 9.2.3 Figure 9.3, bending effective tension area;
- 9.2.3 Formula (9.15), calculated mean crack spacing;
- 9.2.3 Formula (9.17), flexural coefficient;
- 9.2.3 Formula (9.18), bond factor.

Actually selected published 2023 concrete or reinforcing-steel laws fail closed;
this method slice does not convert crack-method provenance into material-law
evidence.

No crack limit, resistance, utilisation or engineering verdict is introduced.
Accepted 2004 base, building-DK, bridge-base and bridge-DK bytes remain frozen.
