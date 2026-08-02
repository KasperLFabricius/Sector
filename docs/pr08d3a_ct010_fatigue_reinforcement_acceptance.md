# PR-08D.3a — CT-010a reinforcement-fatigue acceptance

Scope: the retained grouped-spectrum reinforcement assessment in `sector.fatigue`; concrete fatigue remains CT-010b. This slice is independent of CT-009 (PR-08D.1).

| Surface | Retained proof and closure |
|---|---|
| Shape | One member per input-derived reinforcement element, one reinforcement-output member, or one failure-only invalid member. Spectrum, bin and element order/cardinality come from validated input normalisation. |
| Complete input identity | The immutable section geometry, concrete/reinforcement material IDs and laws, all material/fatigue-detail catalogue entries, element records, bin names/descriptions/actions/cycles, factors, edition, basis and solver vectors form explicit leaves reaching every final. |
| Material/detail provenance | Selected material and fatigue-detail IDs are retained independently of numerical-law equality. Standard S-N values carry their exact 2005 or 2023 source; custom/project values remain uncited. DK provenance is per value, never promoted to the family. |
| Elastic evidence | Every retained reinforcement vector and nested `CombinedElasticResult`/array is cross-checked against a fresh reinforcement-only replay with exact type, dtype, shape and content. |
| Mixed bond evidence | 2005 correction and 2023 equivalent-tendon-area routes are selected from validated inputs. Authoritative combined convergence is retained; original-solve implications are checked without falsely assuming that an equivalent-area-only failure must appear in an original result. |
| Bin proof | Long, uncorrected total, bond-corrected total, action-factored total, elastic/corrected/design ranges, bond adjustment, S-N branch, logarithmic life, cycles, damage, governing stress, signed proof/yield limit and utilisation are independently reconstructed for every bin. |
| Numerical states | Damage is reconstructed in the log domain (`10^(log10(n)-log10(N))`) so life underflow cannot create a division contradiction. Overflow, underflow and non-convergence remain explicit trace states. |
| Element/output proof | Damage sum, maximum yield utilisation, convergence, utilisation and verdict are independently selected. Every non-governing bin and element reaches its member final and the joint output final. |
| Joint factors | `gamma_s`, `gamma_Ff` and `gamma_c` are present on every normalised-input graph. The reinforcement-output final explicitly reaches `gamma_c`, including when the concrete sibling is disabled and the retained value is absent. |
| CT-010b fence | `concrete_method`, `concrete_parameters` and concrete result fields retain their key position and concrete Python types; incompatible replacements fail closed while their numerical values remain outside CT-010a. |
| Exact reader | No Boolean/string/number laundering. Missing, extra, reordered, duplicated, wrong-type and stale/resealed candidate surfaces fail closed before candidate numerics can select a branch. |
| Invalid branch | The retained invalid payload inventory and ordered error identities produce a failure-only member; no resistance, utilisation or verdict is fabricated. |

Acceptance requires a zero-finding exact-head review, focused hostile tests, affected fatigue/application tests, sibling trace guards, ASCII/version gates, and the frozen squash-merge/post-merge lineage checks.
