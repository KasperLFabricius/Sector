# PR-13A1A F-013 bridge raw-input boundary acceptance

Exact base: `89fbc4a9713727093f453d0af7ffdce2dae17393`.

Sector remains version `0.91`. This bounded slice owns only the three retained
bridge tables from edited/imported raw cells through canonical column ordering,
project round-trip identity, application signature identity and pre-calculation
validation. It does not type or alter any numerical bridge kernel or result.

## Frozen identities

The retained table-family order is `bridge_brittle_base`,
`bridge_box_walls_base`, then `bridge_minimum_crack_base`. Each family retains
its existing column order and cardinality from `bridge_inputs.TABLE_COLUMNS`.
Unknown columns remain excluded; duplicate columns are rejected.

Text cells retain the existing trimmed string contract. Valid numerical and
Boolean cells retain their ordinary canonical values. A missing numerical cell
remains a blank numerical value and a missing Boolean defaults to `False`.
Critically, a nonblank malformed numerical or Boolean cell remains distinguishable
through repeated normalization, project save/load and application signature
construction until `records()` rejects its actual field and row. It cannot become
a blank row, `False`, zero or another plausible engineering input.
Positive and negative infinity, and any other non-JSON numeric-cell object, use
an explicit type-tagged, JSON-safe invalid identity. Strict project hashing,
Save/Autosave and repeated current-schema round trips therefore preserve the
malformed field instead of failing serialization.

One-shot tabular iterables are materialized exactly once. Genuine all-blank rows
remain inert. A row containing any malformed nonblank cell remains active and
must fail validation.

## Evidence contract

Focused tests pin direct and repeated normalization, invalid numeric and Boolean
retention, one-shot iterable handling, duplicate columns, stable invalid-cell
signature identity and current-schema save/load preservation. Existing valid
bridge numerical benchmarks remain unchanged.

## Explicit exclusions

No bridge formula, method, citation, warning, numerical result, utilization,
verdict, typed failure payload, Streamlit/report failure presentation, coverage
or compliance route, section solver, other input family, schema version,
calculation trace, packaging, workflow, signing, release, application version,
PR-14 or v0.93 work is included. The typed kernel/result adapter and finite-result
failure publication remain the next independent F-013 slice.
