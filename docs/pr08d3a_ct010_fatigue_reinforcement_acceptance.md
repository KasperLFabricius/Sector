# PR-08D.3a / CT-010a reinforcement fatigue acceptance

## Scope and inventory

CT-010a contains one member for each retained reinforcement element in each
independent fatigue spectrum, one reinforcement-output aggregate, and one
explicit invalid-input member. Concrete-fatigue numerics remain CT-010b.

Inventory is derived from a fresh `fatigue_analysis.prepare` replay. A candidate
result is compared with a fresh `fatigue_analysis.run_analysis` replay before
sealing, so candidate cardinality never defines the trace family.

## Complete input identity

The immutable input vector retains the raw pre-normalization scalar controls,
including their key presence and concrete Python type. It therefore preserves
all entered partial factors and disabled concrete controls independently of what
the reinforcement-only preparation normalizes away. The gamma_s, gamma_ff and
gamma_c steps carry the entered values; a factor is undefined only when the
entered value is genuinely absent or null.

The same vector seals section rings; bar/tendon coordinates, areas and order;
spectrum/bin order, names, descriptions, cycles and actions; element, assigned
material and detail IDs; basis and edition; complete detail/material catalogs
including unused records; runtime material classes and every runtime-law field.

The optional concrete law distinguishes key absent, present-null and
present-law states. Both absent and null are valid when concrete checking is
disabled. A present law is fully sealed although its numerical use belongs to
CT-010b.

Concrete-side output siblings remain numerically excluded but recursively
fenced: their presence, key position, container/dataclass type, cardinality,
nested field position, and array dtype/shape cannot change. Their scalar values
are not interpreted by CT-010a.

## Calculation and verdict closure

Every final reaches the complete input vector and all three entered factors.
Every bin binds cycles, authoritative combined convergence, long/elastic/
bond-adjusted/design stresses, all stress ranges, bond adjustment, standard or
custom S-N values, logarithmic life, life, Miner damage, governing stress,
yield limit and yield utilization. The trace independently reconstructs damage,
yield proof, governing bins, spectrum sums, utilization and verdict. Combined
convergence includes the equivalent-tendon-area solve outcome.

The aggregate consumes every assessment summary and the same input/factor
identity. Finite, failed, positive-infinity, negative-infinity and undefined
final states are explicit.

## Invalid branch

The invalid payload is selected before success-only input typing, preserving
incomplete or malformed flag states supported by the application. Error
cardinality never selects the branch: an empty-error invalid payload still ends
in a failed final. The complete invalid output, raw scalar boundary, error order
and error text are sealed.

## Gates

Acceptance requires focused hostile tests, affected fatigue/trace-core tests,
sibling trace tests, ASCII/version guards, compilation, pyflakes, and exact-head
review with thread-level inspection. Any finding rejects the candidate unchanged
and triggers a new branch from accepted main.

Sector remains publicly versioned 0.91 during this internal v0.92 slice.
