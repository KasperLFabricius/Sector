# PR-08D.3a — CT-010a reinforcement-fatigue acceptance

## Frozen scope

CT-010a makes the implemented grouped-spectrum reinforcement-fatigue result
auditable. It adds no traffic model, fatigue mechanics, national choice,
material law, or concrete-fatigue calculation. Concrete fatigue remains
PR-08D.3b. CT-009 crack width is PR-08D.1 and is independent of this family.

Only the exact retained edition strings for DS/EN 1992-1-1:2005,
DS/EN 1992-1-1:2005 + DK NA:2024, and DS/EN 1992-1-1:2023 can carry finite
fatigue citations. Published 2023 fatigue-detail equations are distinct from
material implementation: a 2023 concrete, bar, or tendon material law remains
unimplemented and cannot produce CT-010 evidence.

## Publication matrix

| Retained state | CT-010a publication |
|---|---|
| Fatigue inactive, section absent, or retained section error | No fatigue result surface and no trace bundle |
| Active input failing application preflight | One `invalid` member with exact ordered errors and a failed final |
| Valid concrete-only check | No CT-010a member; owned by PR-08D.3b |
| Valid reinforcement-only check | One member for every spectrum/element and one `reinforcement-output` member |
| Valid joint reinforcement/concrete check | The reinforcement members and reinforcement output only; concrete sibling values remain excluded while presence, position, and type are pinned |

## Input and provenance closure

Every finite element final reaches an immutable input identity containing the
exact edition, `gamma_s`, `gamma_Ff`, modular ratios, element/detail identity,
diameter, resolved S–N values, proof strengths, optional bond parameters, bin
names/descriptions/cycles/actions, every concrete-ring coordinate, every bar
and tendon coordinate and area, concrete presence and identity, and every
assigned material identity and law. In joint calculations `gamma_c` is an
explicit leaf in every element member and in `reinforcement-output`; it is in
the dependency closure of every joint final.

A present bar or tendon material catalogue must be a complete current-schema
canonical catalogue. Version, `next_id`, container type, item ordering, exact
field inventory, identifiers, descriptions, presets, curves, Booleans, and all
law values are checked for assigned and unassigned entries. The fatigue-detail
catalogue receives the equivalent whole-catalogue validation. Explicit aligned
material laws remain valid uncited project provenance only when the material
catalogue key is genuinely absent.

Material-law provenance and fatigue-equation provenance are separate sources.
The S–N calculation cites DS/EN 1992-1-1:2005 clause 6.8.4 and Tables 6.3N/
6.4N or DS/EN 1992-1-1:2023 E.5.2 and Tables E.1/E.2. Miner accumulation cites
the corresponding 2005 clause 6.8.4(2) or 2023 E.5.2. Mixed-bond adjustment is
identified separately.

## Replay and numerical closure

The candidate surface is reconstructed through the accepted application
boundary. Owned mappings, sequences, primitive values, pinned dataclasses, and
the entire retained `CombinedElasticResult`/`ElasticResult` graph are compared
exactly, including array dtype, shape and content, plane values, convergence
flags, and iteration counts.

The numerical trace is derived independently from each raw `FatigueBinState`:
raw Elastic vectors, corrected and design stresses, ranges, bond adjustment,
S–N branch and logarithmic life, proof limits, damage, governing bins,
utilisation, convergence and status. Every field of the retained
`ReinforcementBinResult` is cross-checked. Miner damage is reconstructed as
`10^(log10(n)-log10(N))`; it never divides by a life value that may have
underflowed to zero. Element summaries then drive the output selection and are
cross-checked against the spectrum and family result.

## Acceptance gates

- Exact registry, member identity, axes, sources, roles, units, dependency
  graphs, expressions, values, warnings, assumptions and hash reconstruction.
- Every final reaches every step declared for its member.
- Hostile probes cover extreme finite log-domain damage, complete raw Elastic
  mutations, raw-state/result contradictions, joint `gamma_c` reachability,
  geometry/bin/material identity, malformed material and fatigue-detail
  catalogues, concrete sibling type replacement, input coercion, inactive and
  invalid states, project provenance, and coherently resealed tampering.
- Focused, affected, sibling trace, ASCII/version, compile and lint gates pass
  before review.
