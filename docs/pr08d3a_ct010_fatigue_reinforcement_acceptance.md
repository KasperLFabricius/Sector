# PR-08D.3a - CT-010a reinforcement-fatigue acceptance

CT-010a owns every retained reinforcement assessment and the joint reinforcement output. CT-010b owns concrete-fatigue values. CT-009 is PR-08D.1 and is not imported by this slice.

| Surface | Acceptance closure |
|---|---|
| Branch | Success versus invalid is selected explicitly from the retained payload, never from error cardinality. An invalid payload with zero error strings remains a failure-only invalid member. |
| Members | One member per input-derived reinforcement element and independent spectrum, plus the joint output. Identity, order and cardinality are reconstructed before candidate numerics. |
| Complete input | Geometry, descriptions/actions/cycles, edition, factors, basis, solver vectors, IDs, whole optional catalogues and every dataclass field of every live concrete/mild/prestress material object are sealed leaves reaching every final. Runtime laws remain sealed when catalogs are absent. |
| Provenance | Same-law/different-ID assignments differ. Standard S-N and bond values carry exact 2005 or 2023 citations; custom details remain uncited. User-entered factors and proof stresses carry input provenance. |
| Replay | The full authoritative analysis is replayed. Reinforcement states, nested Elastic results and arrays are exact in type, dtype, shape and content. Combined convergence preserves equivalent-tendon-area-only failure. |
| Independent proof | Each bin reconstructs stresses, ranges, bond factor, S-N branch, logarithmic life, log-domain Miner damage and signed yield proof. Each independent spectrum reconstructs selectors, sums, convergence, utilisation and verdict. |
| Result states | Member contracts admit finite, positive/negative infinity, undefined and failed finals. No overflow, underflow or non-convergence is fabricated as finite. |
| Joint | Every assessment, the complete input vector and `gamma_s`, `gamma_Ff`, and `gamma_c` reach the joint final. Independent-spectrum utilisations are selected, never damage-summed across groups. |
| Concrete fence | Excluded concrete keys, tuples, search evidence and results are recursively pinned by field/key position, container type, cardinality, array dtype/shape and member type; their numerical values remain CT-010b scope. |
| Strict reader | Original Booleans and numbers are not coerced. Candidate inventories and nested reinforcement evidence require exact retained types. Invalid inputs seal ordered raw/error identity without inventing calculation values. |

Ship requires zero exact-head review findings, focused hostile tests, affected fatigue/core tests, sibling trace guards, ASCII/version gates, and the frozen squash/post-merge lineage checks.
