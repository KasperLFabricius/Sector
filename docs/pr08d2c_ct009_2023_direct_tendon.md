# PR-08D2c CT-009 2023 direct-tension and tendon acceptance

## Boundary

This replacement slice completes the retained `EN 1992-1-1:2023`, edition
`2023`, non-DK CT-009 route for uniform direct tension and bonded tendons. It
changes no solver, crack-width kernel, output adapter, material law, limit,
resistance, utilisation or verdict.

Long-term, short-term and aggregate members keep exact order. Calculated
uniform-tension cases use their own method, scope, direction and retained scope
warning. Calculated dominant-gradient cases keep the accepted refined-bending
identity and bytes. Unsupported direct geometry remains explicit
`NOT ASSESSED`.

## Direct tension

The replay independently invokes the retained solid-rectangle/opposed-face
effective-area kernel from original section geometry and aligned element
diameters. Every calculated candidate exposes final-reaching evidence for its
element identity and geometry; Figure 9.3 effective dimensions and union area;
Formula (9.12) reinforcement ratio; stress, cover and diameter; the uniform
`k1/r = 1`; Formula (9.20) `kfl = 1.00`; Formula (9.18) bond factor; Formula
(9.11) strain; uncapped Formula (9.15) spacing; and recomposed Formula (9.8)
width. No geometric spacing cap is invented for the infinite-neutral-axis
uniform-strain branch.

The Figure 9.3 evidence retains the rectangle width and height and all four
face-specific band depths. It reconstructs the uncovered inner width and height,
then recomposes `Ac,eff = b*h - b_inner*h_inner`. This keeps unequal
left/right or bottom/top layers auditable; the published maximum `bc,eff` and
`hc,eff` values are not used as substitutes for the four face depths.

## Bonded tendons

`sls_tendon_xi` is value-bearing only on this exact route when at least one
tendon is selected. It retains built-in numeric type and must be finite and
non-negative. Zero or a value above one cannot publish calculated evidence:
when the retained effective-area kernel consumes the tendon it yields its
explicit `NOT ASSESSED` result; when every tendon lies outside the effective
area, CT-009 rejects the otherwise calculated candidate at the trace boundary.
The fence is therefore complete for `xi <= 0 or xi > 1`, independent of the
effective-area mask. Without a tendon, and on every 2004 route, the control's
presence, position and type remain pinned while its value stays inert.

For valid `0 < xi <= 1`, Formula (9.6) `xi1` is reconstructed from aligned
element type, diameter and the selected ratio. The aligned `xi1` vector and
bond-weighted tendon area reach every calculated candidate final. Formula (9.6)
uses local `DS/EN 1992-1-1:2023` clause 9.2.2(3); the remaining 2023 crack
formulae use clause 9.2.3. The entered ratio remains an input source.

## Exclusions

Concrete fatigue; chord/off-utilisation/biaxial and CT-002 joins; publication,
UI, report, manual, persistence, packaging and workflow activation; DK/bridge
2023; F-020; solver/formula changes; and v0.93 remain excluded. Tendon-only
cracked direct tension retains the solver failure path and publishes no
fabricated finite result. Sector remains version `0.91`.
