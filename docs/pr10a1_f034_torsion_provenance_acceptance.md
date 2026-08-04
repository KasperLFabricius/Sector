# PR-10A1 F034 transverse torsion provenance acceptance

## Frozen boundary

This slice corrects the directly published provenance of the retained transverse
torsion resistance only. The numerical expression, solver result, method identity,
edition, units, output inventory, result states, selectors, utilisation, verdicts,
and application version remain unchanged.

## Required identity

- Standard: DS/EN 1992-1-1:2004 + A1:2014 + AC:2010.
- Transverse resistance: the thin-wall torsional shear flow in 6.3.2(1), Formula
  (6.27), combined with the transverse-reinforcement equilibrium in 6.2.3(3),
  Formula (6.8).
- Longitudinal torsion reinforcement: 6.3.2(3), Formula (6.28).
- These are distinct sources and must remain distinct on every live publication
  surface.

## Publication closure

The corrected transverse identity must reach the mechanics documentation,
Streamlit result caption, calculation report, and user manual. Each surface must
retain Formula (6.28) for longitudinal reinforcement and must not attribute the
transverse resistance directly to Formula (6.28).

## Explicit exclusions

- No formula, solver, geometry, material, resistance, utilisation, or verdict change.
- No notation normalisation, PDF layout, pagination, typography, or styling change.
- No schema, persistence, UI-input, workflow, packaging, or version change.
- No 2023-edition torsion implementation and no v0.93 roadmap work.
