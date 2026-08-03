# PR-08D2b CT-009 2023 direct-tension and tendon acceptance

## Boundary

This slice completes the accepted CT-009 `EN 1992-1-1:2023`, edition `2023`,
non-DK route by tracing the retained uniform-direct-tension kernel and bonded
tendon contribution. It changes no solver, crack-width formula, candidate-output
adapter, material law, limit, resistance, utilisation or verdict.

Long-term, short-term and aggregate members retain exact order. Calculated
direct-tension cases use method
`sector-en-1992-1-1-2023-uniform-direct-tension-replay`, calculated branch,
`uniform-direct-tension` scope and direction, and the exact retained scope
warning. Calculated dominant-gradient cases retain the accepted refined-bending
identity and bytes. Unsupported direct geometry remains explicit `NOT ASSESSED`.

## Direct-tension replay

The accepted low-level direct-tension geometry kernel is replayed from the
original section and aligned element diameters. It requires a solid rectangular
section with reinforcement assigned to distinct opposed faces. Each calculated
candidate exposes final-reaching evidence for selected element identity,
coordinates and area; Figure 9.3 effective height, width and perimeter-union
area; mild, prestressing and bond-weighted areas; Formula (9.12) ratio; stress,
diameter and cover; `kw`; the uniform-strain `k1/r = 1`; Formula (9.20)
`kfl = 1.00`; Formula (9.18) bond factor; Formula (9.11) mean strain; uncapped
Formula (9.15) spacing; and recomposed Formula (9.8) width.

No geometric spacing cap is fabricated for uniform strain: the cracked neutral
axis is at infinity and the retained direct branch uses the uncapped Formula
(9.15) expression. Non-rectangular, missing-opposed-face, multi-layer or other
unsupported direct geometries retain their exact `NOT ASSESSED` reason.

## Bonded-tendon replay

`sls_tendon_xi` becomes a value-bearing input only for this exact 2023 route when
at least one tendon is selected. It must retain built-in numeric type, be finite
and non-negative. Zero retains the kernel's explicit missing-bond `NOT ASSESSED`
state; values above one retain its out-of-range `NOT ASSESSED` state. Without a
selected tendon, and on every 2004 route, its position and type remain pinned
while its value stays inert.

The range applies to every selected tendon, including tendons outside a
particular candidate's effective area. If the retained output attempts to
publish a calculated case from an out-of-range value that the low-level
effective-area mask did not consume, CT-009 rejects that candidate rather than
publishing finite evidence.

Formula (9.6) `xi1` is reconstructed through the accepted effective-ratio kernel
from aligned element type, diameter and the selected bond ratio. The aligned
`xi1` vector and weighted tendon area reach every calculated candidate final.
Formula (9.6) uses exact local `DS/EN 1992-1-1:2023` clause 9.2.2(3) provenance;
Figure 9.3 and Formulae (9.8), (9.11), (9.12), (9.15), (9.18) and (9.20) use
9.2.3 provenance. The user-entered bond ratio itself remains an input source.

## Closure and exclusions

Complete current-schema geometry, material catalogues, selected concrete/bar/
tendon IDs, assignments, controls and retained outputs remain sealed. Selected
published 2023 material laws still fail closed; accepted 2004 base, building-DK,
bridge, calculated-bending, applicability, uncracked and failure behavior remains
unchanged. Concrete fatigue; chord/off-utilisation/biaxial and CT-002 joins;
publication/UI/report/manual/persistence/package/workflow wiring; DK/bridge 2023;
F-020; and v0.93 remain excluded. Sector remains version `0.91`.
