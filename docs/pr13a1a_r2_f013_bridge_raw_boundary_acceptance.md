# PR-13A1A-R2 F-013 bridge raw-input boundary acceptance

Exact base: `89fbc4a9713727093f453d0af7ffdce2dae17393`.

Sector remains version `0.91`. This independent reslice owns only the three
retained bridge tables from edited/imported raw cells through canonical column
ordering, application signature identity, strict current-project persistence and
pre-calculation validation. It changes no numerical bridge kernel or result.

## Frozen identities

The table-family order is `bridge_brittle_base`, `bridge_box_walls_base`, then
`bridge_minimum_crack_base`. Each table retains the exact column order and
cardinality in `bridge_inputs.TABLE_COLUMNS`. Unknown columns are inert and
excluded. Duplicate columns fail before selection. One-shot tabular iterables are
materialized exactly once.

Text cells retain trimmed-string behavior. Valid numerical cells retain finite
floating-point values. Valid Boolean cells retain exact Boolean type. Missing
numerical cells remain blank and missing Boolean cells default to `False`.
Scalar pandas-null blanks, including `pd.NA` and `pd.NaT`, remain inert in every
column and cannot activate an otherwise blank row.

Every nonblank malformed numerical or Boolean cell remains active and retains a
stable concrete type/value identity across repeated normalization and application
signatures. JSON-safe primitives persist directly. Non-finite or otherwise
non-JSON objects use bridge-specific project encoding at the strict serialization
boundary. Project hashes, Save/Autosave and repeated current-schema round trips
therefore remain valid without turning malformed cells into blanks, zeros,
Booleans or plausible engineering values. `records()` rejects the actual field
and row before any bridge calculation.

## Evidence contract

The focused matrix covers every retained numeric field with malformed strings,
Booleans, positive/negative infinity and a non-JSON complex object. It covers the
retained Boolean field with incompatible primitive, non-finite and non-JSON
values. Every field is checked through repeated normalization, strict project
JSON, two save/load cycles, stable signatures and field-specific validation.
Scalar missingness, valid legacy signatures, exact order/defaults, unknown and
duplicate columns, one-shot inputs, accepted finite benchmarks and directly
affected report/oracle/Streamlit paths are pinned independently.

## Explicit exclusions

No bridge formula, method, citation, warning, numerical result, utilization,
verdict, typed failure payload, Streamlit/report failure presentation, coverage
or compliance route, section solver, other input family, project schema version,
calculation trace, packaging, workflow, signing, release, application version,
PR-14 or v0.93 work is included. The typed kernel/result adapter and finite-result
failure publication remain the next independent F-013 slice.
