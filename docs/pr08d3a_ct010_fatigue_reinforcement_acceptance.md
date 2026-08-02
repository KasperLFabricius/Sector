# PR-08D.3a — CT-010a reinforcement-fatigue acceptance

## Frozen scope

CT-010a publishes auditable reinforcement-fatigue evidence for the already
implemented grouped-spectrum calculation. It does not add fatigue mechanics,
traffic models, national choices, material laws, or concrete-fatigue evidence.
Concrete fatigue remains PR-08D.3b. CT-009 crack width is PR-08D.1 (not
PR-08D.2) and is independent of this family.

The accepted editions are the exact retained application strings for
DS/EN 1992-1-1:2005, DS/EN 1992-1-1:2005 + DK NA:2024, and
DS/EN 1992-1-1:2023. Edition aliases are not accepted at the trace boundary.
Published 2023 fatigue-detail equations may be traced; a 2023 concrete,
reinforcement, or tendon material law remains unimplemented and is rejected.

## Member matrix

| Retained state | CT-010a publication |
|---|---|
| Fatigue inactive, absent section, or retained section error | No fatigue surface and no CT-010 bundle |
| Active input failing application preflight | One `invalid` member with exact ordered error evidence and a failed final |
| Valid concrete-only check | No CT-010a member; owned by PR-08D.3b |
| Valid reinforcement-only check | One member per spectrum/element plus `reinforcement-output` |
| Valid joint reinforcement/concrete check | Reinforcement members and reinforcement-only output selection; concrete siblings retain presence, position, and type but their values remain outside CT-010a |

## Closed input identity

Every finite member binds the exact edition, partial factors, modular ratios,
element/detail identity, diameter, resolved S–N data, proof strengths, optional
bond parameters, bin names/descriptions/cycles/actions, every concrete polygon
coordinate, every reinforcement/tendon coordinate and area, concrete presence,
concrete material identity and law when supplied, and every assigned
reinforcement/tendon material identity and law. Geometry and material vectors
are dependencies of the normalised-input node, which is itself a dependency of
the member final.

A present mild/prestress material catalogue must be a complete current-schema
canonical catalogue. Version, `next_id`, container types, item order, exact
field inventories, identifiers, metadata, curves, Boolean fields, and every
finite law value are validated for assigned and unassigned items. Explicit
aligned laws with no catalogue key remain valid project provenance; a present
`null` or malformed catalogue is not treated as catalogue-free.

## Numerical and replay closure

The candidate result is reconstructed through the accepted application
boundary. Owned mappings, sequences, dataclasses, primitive values, and the
complete retained `CombinedElasticResult`/`ElasticResult` graphs are compared
exactly, including all array dtype/shape/content, strain-plane values,
convergence flags, and iteration counts. Only the named concrete-fatigue
siblings are value-excluded, with their presence, order, and type pinned.

Trace values are then independently derived from operands: characteristic,
elastic and design stress ranges; mixed-bond adjustment; two-slope S–N branch
and life; Palmgren–Miner bin and total damage; sign-dependent proof limit;
governing bins; utilisation; convergence; and PASS/FAIL. Any contradiction
between those derivations and the retained result prevents publication.

The reinforcement S–N sources are DS/EN 1992-1-1:2005 clause 6.8.4 and Tables
6.3N/6.4N, or DS/EN 1992-1-1:2023 E.5.2 and Tables E.1/E.2. Miner summation is
traced to the corresponding 2005 clause 6.8.4(2) or 2023 E.5.2. Mixed-bond
adjustment is traced separately. Material-law provenance and fatigue-detail
provenance remain distinct.

## Acceptance gates

- Exact contract, registry, source, role, unit, axis, dependency, expression,
  value, warning, assumption, input-hash, and result-hash reconstruction.
- Every calculation final reaches every declared step.
- Hostile tests cover raw-solver mutation, malformed and noncanonical catalogue
  siblings, catalogue-free laws, edition/Boolean/numeric coercion, concrete
  sibling replacement, bin/geometry/material identity changes, independent
  numerical contradictions, stale hashes, and coherently resealed tampering.
- The affected fatigue and calculation-trace regression suites remain green.
