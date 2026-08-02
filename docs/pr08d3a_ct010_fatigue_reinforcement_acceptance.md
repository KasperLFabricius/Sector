# PR-08D.3a / CT-010a reinforcement-fatigue acceptance

## Boundary and members

CT-010a contains one reinforcement assessment for every retained element in
every independent spectrum, one reinforcement-output member, and an explicit
invalid-input member. Concrete-fatigue calculation is reserved for CT-010b.

The member inventory is derived from a fresh `fatigue_analysis.prepare` replay,
never from candidate cardinality. The submitted result is compared with a fresh
`fatigue_analysis.run_analysis` result before any trace is sealed.

## Complete retained identity

The normalized input identity includes section rings; reinforcement and tendon
coordinates, areas and order; spectrum and bin order; bin names, descriptions,
cycles and actions; element and assigned material IDs; fatigue-detail records;
the complete detail and material catalogs, including unused entries; selected
edition and basis; factors; runtime material-law class identity and every
runtime-law field.

The optional concrete law has three retained input states: key absent, key
present with a null value, and key present with a concrete law. Both absent and
null are valid when concrete checking is disabled. A live law retains its exact
class and every field even though its numerical use belongs to CT-010b.

Concrete-side output siblings remain outside the numerical scope. Their key
position, container type, dataclass type, sequence type, cardinality, nested
field position, and array dtype/shape are pinned recursively. Their scalar
values are deliberately not interpreted by CT-010a.

## Operand and verdict closure

Each assessment final is reachable from the complete input identity and from
gamma_s, gamma_ff and gamma_c. Every bin binds cycles, combined convergence,
long/elastic/bond-adjusted/design stresses, all three stress ranges, bond
adjustment, selected S-N exponent, logarithmic life, life, Miner damage,
governing stress, yield limit and yield utilization. Standard and custom S-N
sources and 2005/2023 bond sources are attached per value.

Damage is independently reconstructed in the logarithmic domain. Yield proof,
governing-bin selection, spectrum sums, utilization, convergence and verdict
are independently reconstructed. Combined convergence includes the
equivalent-tendon-area solve outcome from the authoritative replay.

The reinforcement-output final consumes every assessment summary plus the same
complete input and factor identity. Finite, failed, positive-infinity,
negative-infinity and undefined final states are explicit.

## Invalid branch

The invalid member is selected by the retained invalid payload, not by whether
its error tuple happens to be nonempty. It always terminates in a failed final
and seals the retained error order and text.

## Acceptance gates

Acceptance requires focused hostile tests, affected fatigue and trace-core
tests, sibling trace tests, ASCII/version guards, compilation, pyflakes, and an
exact-head review with thread-level inspection. Any review finding rejects the
candidate unchanged and requires a fresh branch from accepted main.

Sector remains publicly versioned 0.91 during this internal v0.92 slice.
