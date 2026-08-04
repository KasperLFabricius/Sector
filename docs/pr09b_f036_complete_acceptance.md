# PR-09B recut acceptance: complete F-036 method contract and hand pack

Exact base: `7512c3ed01e41100cee59893ce9beab381bec890`. Sector remains
`0.91`; project schema remains `23`. Closed PR #284, #285 and #286 heads are
negative evidence only and are absent from this candidate's ancestry.

## Frozen boundary

F-036 is the sole finding. The manual must state the retained normal and
exceptional branches for plastic axial equilibrium, cracked-Elastic iteration,
applied-ray intersection, concrete-fatigue adaptive search and report precision.
The manual dialog must download one current-schema project and one checking pack
whose input SHA-256 is identical.

The project is one centred rectangular reinforced-concrete section with one
Plastic case, one Elastic/crack case, one two-bin fatigue spectrum and all three
independent bridge tables. It enables Plastic, Elastic, crack width, clear
spacing, minimum longitudinal reinforcement, transverse detailing, directional
shear with links, torsion, combined M-V-T, reinforcement fatigue, concrete
fatigue and bridge calculations. Its actual calculated result must therefore
emit every main report chapter: conventions, section/materials, analysis basis,
clear spacing, Plastic, minimum reinforcement, transverse detailing, shear,
torsion, combined M-V-T, Elastic, cracking, grouped fatigue, bridge calculations,
and provenance/QA appendix.

## Independent oracle

The frozen oracle must not import or call Sector production solvers, selectors,
or result-presentation functions. From parsed original project
inputs and explicitly retained low-level section intermediates it independently
establishes:

- geometry area, centroid, gross inertias, reinforcement areas and material IDs;
- one plastic equilibrium/capacity member by independent rectangular-fibre
  integration and bisection, plus applied-ray demand/intersection;
- cracked transformed-section neutral axis, curvature, bar stresses and force/
  moment residuals for the pure-bending Elastic case;
- the governing 2004/DK crack candidate from its effective area, stress-difference
  and crack-spacing equations;
- shear, torsion, combined, clear-spacing, longitudinal/transverse detailing,
  steel/concrete Miner and all three bridge formula outputs by direct published
  equations;
- the exact expected result states and report chapter inventory.

The combined branch owns the one shared shear/torsion strut angle. The project
must retain the selected concrete identity and every direct calculation input in
the ordinary solver and publication payloads.

The downloadable checking pack records the formulas, substituted original
inputs, unrounded reference outputs, units, method/edition/source identities and
failure-state rules. The focused app test loads the real download, calculates it,
compares every family to this oracle and builds the ordinary tables-only PDF to
prove every main chapter is emitted.

## Failure and identity rules

The project uses genuine current `source_revision`, ordinary project metadata,
selected concrete/reinforcement/fatigue-detail IDs and current method labels.
Failure, unsupported, non-converged and positive-infinite branches are described
without fabricated resistance, utilization or verdict. Calculations and verdicts
use retained unrounded values; formatting is presentation only.

## Exclusions

No production solver, formula, material law, project schema, report renderer,
application version, standard applicability, publication activation, PR-10--14,
v0.93, PR-07 removal or rejected-head implementation is in scope. The bounded
concrete-identity adapter and publication-metadata replay fence above are required
integration closure for the downloadable example, not mechanics changes.
