# PR-13A2 F-013 capacity boundary acceptance

## Base and purpose

Exact accepted base: `599c6d8f506f335f9dee9c7355b0efee3b345596`.

This bounded slice closes the remaining F-013 engineering catches and selected
standards-routing boundary in `sector.capacity`. It changes no section,
plasticity, shear, torsion, combined-interaction or detailing equation and no
accepted finite result, tolerance, method, citation, warning or verdict.

Expected plastic non-convergence remains explicit solver state. Unexpected
exceptions must propagate unchanged. Malformed returned solver state or a
non-finite returned resistance/lever arm becomes a typed result-contract failure
and must never be published as an engineering value.

## Exact method identity

The selected shear-method identity is one exact key, in existing insertion
order, of `sector.capacity.SHEAR_METHODS`:

1. `DS/EN 1992-1-1:2005 + DK NA:2024`;
2. `EN 1992-1-1:2005`;
3. `DS/EN 1992-1-1:2023`.

The selected torsion/combined-method identity is one exact key, in existing
insertion order, of `sector.capacity.SHEAR_CODES`:

1. `DS/EN 1992-1-1:2005 + DK NA:2024`;
2. `EN 1992-1-1:2005`.

An active solver family resolves that identity before geometry or numerical
mechanics. Missing, blank, non-string or unknown identity raises
`CapacityMethodError`; it must not silently select the Danish default. A current
project pins every present `shear_method`, `torsion_method` and
`combined_method` through the same resolver on save and load, whether or not the
corresponding optional calculation is active. Missing optional scalar keys remain
permitted and retain the current UI defaults.

## Original-input inventory

### Plastic internal shear lever arm

- `section` and its current geometry;
- `concrete`, `steel`, optional `prestress`;
- aligned optional `bar_materials` and `tendon_materials`;
- tendon presence;
- `P_pl`;
- exact axis `x` or `y` and `tension_low` face identity;
- fallback effective depth `d_mm`.

### Conditional longitudinal-chord resistance

- the same section, geometry and material identities;
- `P_pl`;
- exact axis and face identity;
- signed coexisting companion moment `m_off`.

### Active shear/torsion method routing

- exact selected method identity;
- all existing family-specific original inputs consumed after successful method
  resolution remain unchanged and are owned by their retained kernels.

## Candidate-output inventory and dependency graph

`shear_lever_arm` retains the two-item result `(z_mm, z_source)`:

1. no section -> existing `0.9 * d_mm` fallback;
2. plastic point with concrete `converged is False` -> existing fallback;
3. finite converged lever no greater than `1e-6 m` -> existing fallback;
4. finite converged lever above the threshold -> exact lever in millimetres and
   `plastic internal lever arm`;
5. malformed convergence state or non-finite converged lever ->
   `CapacityResultError` and no lever publication.

`shear_face_mrd` retains the two-item result `(mrd_kNm, conditional)`:

1. no section -> `(0.0, False)`;
2. finite non-negative conditional result with `exact is True` -> publish it,
   including honest zero;
3. exact `False` with the required zero placeholder -> run the existing pure-axis
   fallback at `FACE_ANGLE[(axis, tension_low)]`;
4. finite converged pure-axis point -> publish the absolute owning-axis moment
   with `conditional=False`;
5. non-converged pure-axis point -> `(0.0, False)`;
6. malformed tuple/state, a nonzero non-exact placeholder, negative or non-finite
   returned resistance -> `CapacityResultError` and no resistance publication.

`CapacityInputError` is the expected invalid-input base. `CapacityMethodError`
specialises it for method identity. `CapacityResultError` identifies a returned
solver-contract violation. These exceptions do not convert unexpected
`RuntimeError`, `AssertionError`, `KeyError` or other implementation exceptions;
those propagate unchanged from the low-level solver.

## Required adversarial evidence

- all retained finite lever-arm and conditional/pure-axis resistance benchmarks
  remain bit-for-bit or approximately unchanged under their existing assertions;
- expected `converged=False`, exact-false fallback and honest conditional zero
  retain their current semantics and warnings;
- unexpected faults from both low-level solver calls propagate unchanged;
- malformed convergence/exact states, malformed conditional result shape,
  nonzero non-exact placeholders and non-finite/negative returned numerical values
  produce the exact typed result failure;
- unknown shear, torsion and combined methods fail before any mechanics and never
  select a default;
- current-project save/load/resave retains every valid method identity and rejects
  a coherently re-hashed unsupported identity;
- focused capacity/conditional/project tests, directly affected shear/torsion and
  presentation tests, compile/import/static checks, ASCII, version, base, scope and
  rejected-ancestry guards pass.

## Explicit exclusions

No formula, arithmetic order, search grid, convergence tolerance, fallback value,
ordinary finite result, utilization, warning, verdict, standard edition, source,
citation, user-visible schema version, Streamlit layout, report/manual wording,
calculation trace, other solver family, broad static-debt cleanup, CI/workflow,
dependency gate, package, signing, release, application version, PR-14 or v0.93
change is included. F-012 staged gates remain separate later PR-13 slices.
