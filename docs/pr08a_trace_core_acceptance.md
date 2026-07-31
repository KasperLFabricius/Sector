# PR-08A calculation-trace core acceptance

This matrix freezes the recovery scope before implementation. Sector remains
version 0.91. All evidence uses synthetic traces; retained calculation families,
renderers, reports, the manual, and project persistence are outside this change.

| Invariant | Frozen acceptance |
| --- | --- |
| Schema identity | One immutable `sector.calculation-trace.v1` model accepts only its exact JSON fields, dataclasses, built-in scalars, and collection shapes. |
| Dependency DAG | Every dependency ID is unique, resolves to an earlier step, and declares the exact unit it consumes; missing, duplicate, forward, cyclic, and unit-mismatched edges fail closed. |
| Injectivity | Calculation and step IDs are unique, registry member IDs are unique, and arbitrary user-visible labels have a stable collision-free ID token. |
| Explicit result state | Finite values are finite non-Boolean numbers. Positive infinity, negative infinity, undefined outcomes, and solver failures use named states, a null numeric value, and a non-empty reason; serialized NaN/Infinity is forbidden. |
| Calculation-local provenance | Every step owns its input, project-method, or cited standard source. Mixed concrete, reinforcement, and tendon methods/editions remain distinct leaf data; there is no calculation-global standard edition. |
| Tamper rejection | The bundle seal covers all trace content, and optional expected input/result fingerprints reject stale bundles. |
| Stable round trip | Canonical JSON is byte-stable across deserialize/validate/serialize and rejects duplicate keys, unknown fields, and shape-shifted fields. |
| Renderer boundary | Expressions, substitutions, units, evaluated results, warnings, assumptions, and citations are complete data. The core exposes no formula evaluation API and no renderer is changed. |

The declarative registry may state exact selected members, coverage IDs, methods,
axes, local source identities/editions, and allowed result states. It contains no
built-in CT-002 through CT-027 family policy.
