# PR-08D.3a / CT-010a reinforcement fatigue acceptance

## Scope

CT-010a publishes one reinforcement-fatigue member per retained element and
independent spectrum, an aggregate reinforcement-output member, and an explicit
invalid-input member. Numerical concrete-fatigue assessment remains CT-010b.

Member inventory comes from a fresh `fatigue_analysis.prepare` replay. Candidate
results are compared against a fresh `fatigue_analysis.run_analysis` replay
before sealing; candidate cardinality never defines the family.

## Identity closure

The normalized input seals section rings; bar and tendon coordinates, areas and
order; all spectrum/bin names, descriptions, cycles and actions; element,
material and detail IDs; edition, basis and factors; complete detail and
material catalogs including unused records; runtime material classes and every
runtime material field.

The optional concrete law retains three input states: key absent, key present
with null, and key present with a law. Both absent and null are allowed for a
reinforcement-only run. A live law remains fully sealed even though its
numerical calculation belongs to CT-010b.

Concrete-side output siblings are excluded numerically but recursively fenced:
their presence, key position, container and dataclass types, cardinalities,
nested field positions, and array dtypes/shapes cannot change. Their scalar
values are not interpreted here.

## Calculation closure

Every member final reaches the complete input vector and gamma_s, gamma_ff and
gamma_c. Per-bin proof binds cycles, authoritative combined convergence,
long/elastic/bond-adjusted/design stresses, all stress ranges, bond adjustment,
selected standard or custom S-N parameters, logarithmic life, life, Miner
damage, governing stress, yield limit and yield utilization. Damage and yield
are independently reconstructed, as are governing bins, sums, utilization and
verdicts. Combined convergence includes the equivalent-tendon-area solve.

The aggregate final consumes every assessment summary and the same complete
input/factor identity. Finite, failed, positive-infinity, negative-infinity and
undefined final states are explicit.

## Invalid branch

The retained invalid payload selects the invalid member before success-only
input typing. Missing or malformed flags are therefore traceable, matching the
application boundary for incomplete project input. Error cardinality does not
select the branch: an invalid payload with an empty error tuple still terminates
in a failed final. Error order and text are sealed.

## Gates

Acceptance requires the focused hostile suite, affected fatigue and trace-core
suites, sibling trace suites, ASCII/version guards, compilation, pyflakes, and
an exact-head review with thread-level inspection. Any review finding rejects
the candidate unchanged and requires another fresh branch from accepted main.

Sector remains publicly versioned 0.91 during this internal v0.92 slice.
