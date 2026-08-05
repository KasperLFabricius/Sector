# PR-11D1 calculation-trace retirement reconciliation

## Boundary

- Base commit: `f0aa5b8de644a2a24d01a58a6e26c7af4b0690c7`.
- Base tree: `75af5e68aa661e2d13c567efd87363a5d8cd7f3e`.
- Sector version: `0.91`, unchanged.
- Scope: F-016, F-030 and F-031 roadmap disposition only.

The owner retired the complete calculation-trace subsystem after PR-08. The
accepted retirement sequence is authoritative for those three trace-publication
findings:

| Slice | Candidate head | Accepted merge | PR |
|---|---|---|---|
| R1 publication output | `e88763932cd8917a572c657aa1d8bef5503e2f50` | `b162dd31ae0948c8238adae834682835f7355014` | `311` |
| R2 elastic and interaction families | `ad7f231b07378666233aeeb0575ad408bb78dd5d` | `39e6ff832da2b485c494d2e7931a21ee7e1cff08` | `312` |
| R3 bridge, crack and fatigue families | `8f9504a50f59119c5c979dde8e7bf4479120f6d5` | `f20b8e22656c621c5f8c10f96308587d8178dc76` | `314` |
| R4 shear, torsion and detailing families | `bf0acc136db7eb069029cdb5f980482f1a1b73b3` | `d3e9769b227506cb34a3a78ffd859527ad45b417` | `315` |
| R5 core removal | `8c79f48365671960e8ad53d584605aca742cd1e5` | `3e05c71ebb65ddc3ea8a00f8d7f2f81fcfce2c5b` | `316` |

The resulting product has no calculation-trace data contract, trace viewer,
trace switch or trace appendix. Sector still publishes the direct calculations
and results used by the Streamlit UI and generated report; the manual and worked
example remain the hand-check route. Retiring traces did not authorize a solver,
formula, result, verdict, schema or Product Identity change.

## Closure requirements

The focused guard must:

1. Parse the retirement table and compare the five complete row tuples, so a
   candidate head cannot be paired with another slice's merge or PR.
2. Parse the QA ledger by columns and require F-016, F-030 and F-031 to carry
   the retired status, the final R5 closure head and exactly PRs 311, 312, 314,
   315 and 316 in the merged-PR column.
3. Pin the explicit absence of any optional trace mode and Sector version 0.91.

## Exclusions

- PR-09 through PR-11 closure-row reconciliation is the independent PR-11D2
  slice and is not claimed here.
- The original QA workbook is preserved unchanged.
- No PR-12 or later implementation, v0.93 candidate or rejected-head content is
  introduced.
