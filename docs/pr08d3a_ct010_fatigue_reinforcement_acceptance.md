# PR-08D.3a / CT-010a fatigue reinforcement acceptance

## Scope

This slice adds the closed calculation-trace family for reinforcement fatigue.
It covers every element in every independent fatigue spectrum and the joint
assessment. Concrete fatigue calculation remains outside CT-010a.

## Frozen boundary

The trace is reconstructed from a fresh authoritative replay of the retained
fatigue input. The replay and the submitted result must agree exactly on the
retained result tree, including dataclass identity, sequence type, array dtype,
array shape, array content, bin order, bin descriptions, material identity,
catalog identity, and convergence state.

Concrete-side siblings remain excluded from the CT-010a calculation, but their
presence, position, container shape, cardinality, key names, and retained member
types are pinned. Their numerical values are not interpreted by this slice.

The optional concrete material law is handled explicitly. Its absence is part
of the sealed identity. When present, its concrete class and every dataclass
field are included in the immutable runtime material vector. The same complete
runtime-law snapshot is retained for every mild and prestressing steel law,
independently of material-catalog availability.

## Calculation closure

Each reinforcement assessment retains an immutable path from the normalized
input vector and runtime material vector through:

- element, spectrum, and bin selectors;
- stress ranges and yield proof;
- the selected standard or custom S-N source;
- fatigue life and log-domain damage reconstruction;
- the assessment sum, utilization, and final result; and
- the partial factors gamma_s, gamma_ff, and gamma_c.

The joint member consumes every assessment final together with the same input,
material, and partial-factor identity. This prevents a final member from being
replayed against a different geometry, material, catalog, spectrum, or bin
description while retaining the same trace bundle.

Finite results, failed results, positive infinity, negative infinity, and
undefined results have explicit final-state representations. Combined
convergence is taken from the authoritative replay, including the equivalent
tendon-area solve.

## Invalid-input branch

Invalid input has an explicit branch in the family contract. It cannot become a
success branch merely because the error collection is empty. The raw invalid
input, retained error sequence, error order, and error text are sealed and the
family terminates in the failed state.

## Verification

Acceptance requires:

- focused CT-010a tests;
- the affected fatigue, material-catalog, and trace-core suites;
- sibling calculation-trace suites;
- ASCII and version guards;
- Python compilation and pyflakes; and
- an exact-head review with all review threads inspected before merge.

The Sector public version remains 0.91 in this internal v0.92 programme slice.
