# Sector 0.96.5 notes

Sector 0.96.5 expands the illustrated manual with reproducible solver
explanations, worked force tables and clearer result interpretation.
Supported project schema: 27.

## Manual improvements

- The common section model connects geometry, strain compatibility, material
  stress and equilibrium. It distinguishes polygon geometry, plastic stress
  bands and angular sampling of capacity envelopes.
- The elastic chapter derives the rectangular neutral axis, transformed
  stiffness and stresses. It also explains the general biaxial equilibrium
  system, displaced concrete, iteration and physical strain units.
- The plastic chapter explains the first material strain limit, 80 midpoint
  bands, the stress plateau, reinforcement forces and axial-force bisection.
  Worked contribution tables reproduce the existing beam resistance.
- A sustained-plus-additional example explains LONG, retained stress, RST1,
  TOTAL and DIF. Numerical refinement results identify their example scope.
- New figures explain crack-width geometry, the shear truss, the torsion tube,
  concurrent chord/stirrup demands and fatigue action ranges.
- Larger manual body text and paragraph spacing support longer derivations.
  The offline HTML includes checked embedded images and text alternatives.
  Existing equation identities and calculation-method sources are retained.

## Portable build and compatibility

The package is `Sector-v0.96.5-windows-portable`. Extract the complete ZIP and
run `Sector.exe`, keeping the `_internal` folder beside it. The package includes
its Python runtime. PDF figure generation uses Microsoft Edge or another
supported Chromium browser. The distribution includes a SHA-256 sidecar.

Production solver methods and project schema are unchanged. Existing schema
25/26 migrations remain available. The engineer selects the project inputs,
methods and applicability conditions and reviews the reported results.
