# PR-08D.3a - CT-010a reinforcement-fatigue acceptance

CT-010a owns each retained `ReinforcementFatigueResult` and the joint reinforcement output. CT-010b owns concrete-fatigue values. This slice is independent of CT-009 (PR-08D.1).

| Boundary | Closed acceptance condition |
|---|---|
| Member set | One member for every input-derived element in every independent spectrum, plus one joint output; invalid input produces only an invalid member. Missing, extra, duplicate or reordered identities fail closed. |
| Input identity | Complete geometry, material/detail IDs and laws, whole material and fatigue-detail catalogues, bin names/descriptions/actions/cycles, solver vectors, factors, edition and basis are immutable leaves reaching every final. |
| Material provenance | Same-law/different-ID assignments seal differently. Standard S-N values carry exact 2005 or 2023 citations; custom values remain uncited. Entered factors and proof stresses retain input provenance. |
| Elastic/bond replay | Every reinforcement state, nested Elastic result and array dtype/shape/content is compared to a full authoritative replay. Combined convergence is retained without assuming that an equivalent-area-only failure appears in an original solve. |
| Independent proof | Every bin independently reconstructs long/total/design stress, ranges, bond factor, S-N branch, logarithmic life, log-domain Miner damage, signed yield limit and utilisation. Each spectrum independently reconstructs its sums, selectors, convergence, utilisation and verdict. |
| Grouping | Spectrum groups are independent. Damage is summed within one spectrum only; the joint output selects the maximum across element-spectrum results. |
| Engineering states | Finite, positive/negative infinity, undefined and failed states are admitted by every member registry. No overload, underflow or failed convergence is coerced to a fabricated finite value. |
| Joint closure | `gamma_s`, `gamma_Ff`, `gamma_c`, every element-spectrum summary and the complete input vector reach the joint final. |
| Concrete fence | `concrete_method`, `concrete_parameters`, concrete tuples/search evidence and concrete result fields are compared recursively for exact container type, key/field position, cardinality, array dtype/shape and member type. Numerical values remain outside CT-010a. |
| Reader strictness | Original Booleans/text/numbers are validated without coercion; candidate output and nested reinforcement evidence require exact retained types and inventories. |
| Invalid branch | Ordered retained errors seal a failure-only final; no utilisation, resistance or verdict is invented. |

Ship only after a zero-finding exact-head review, focused hostile tests, affected fatigue/core tests, sibling trace guards, ASCII/version gates, and frozen squash/post-merge lineage verification.
