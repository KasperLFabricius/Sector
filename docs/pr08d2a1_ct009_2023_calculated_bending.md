# PR-08D2a1 CT-009 calculated 2023 bending acceptance

## Boundary

This slice activates only finite refined-bending replay for the exact
`EN 1992-1-1:2023`, edition `2023`, non-DK selector. It also retains explicit
uncracked and non-converged states. It replays the accepted section, elastic and
crack-width kernels and changes no solver or engineering formula.

Cracked cases that are not calculated fail closed as deferred applicability.
Uniform direct tension and all tendon cases fail closed as separately deferred
subfamilies. These states are not represented by the bending method. Danish NA
and bridge 2023 routes are excluded.

## Calculated contract

Long-term, short-term and aggregate members retain exact order. Every calculated
candidate exposes final-reaching evidence for effective height and area, mild and
prestressing areas, weighted prestressing area, effective reinforcement ratio,
reinforcement stress, diameter, cover, `kw`, `k1/r`, `kfl`, `kb`, mean strain,
bending direction and calculated width.

Formula (9.15) is reconstructed as an explicit branch. The trace publishes:

- the cracked tension-zone depth `h-x`;
- `1.5c + (kfl*kb/7.2)*(phi/rho_p,eff)`;
- the geometric cap `(1.3/kw)*(h-x)`;
- the selected minimum, checked against the accepted kernel result.

Both uncapped-governing and cap-governing cases are independently tested. Every
standard step, including the case `kt`, uses local
`DS/EN 1992-1-1:2023` 9.2.3 provenance: Formulae (9.8), (9.9), (9.11), (9.12),
(9.15), (9.17), (9.18), and Figure 9.3.

Complete current-schema geometry, material catalogues, selected IDs, assignments,
controls and retained outputs remain sealed. Actually selected published 2023
concrete or reinforcing-steel laws fail closed. No limit, resistance, utilisation
or engineering verdict is introduced. Accepted 2004 base, building-DK,
bridge-base and bridge-DK bytes remain frozen.
