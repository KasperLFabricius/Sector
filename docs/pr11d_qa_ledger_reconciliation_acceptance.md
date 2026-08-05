# PR-11D acceptance matrix - QA ledger reconciliation

## Candidate boundary

- Exact base: `f0aa5b8de644a2a24d01a58a6e26c7af4b0690c7`.
- Base tree: `75af5e68aa661e2d13c567efd87363a5d8cd7f3e`.
- Application version: `0.91` (unchanged).
- Family: tracked QA-roadmap documentation and its consistency guard only.

This slice reconciles the implementation ledger with accepted merged history.
It neither reopens retired calculation traces nor changes a calculation,
publication artifact, user interface, project schema, package or release gate.

## Closure terminology

The original QA workbook is the immutable finding index, not a live approval
service. In the tracked ledger, `Merged and independently closed` means that an
immutable candidate passed its frozen independent/adversarial evidence, received
an exact-head Codex Review with no unresolved P1/P2 finding, and was squash-merged
with the accepted tree verified on `main`. The ledger records the accepted
candidate head separately from the squash-merge commit.

## Owner-directed calculation-trace retirement

The calculation-trace subsystem was removed in five independently reviewed,
accepted slices. Their exact identities are:

| Slice | Accepted candidate | Squash merge | Pull request |
|---|---|---|---|
| R1 publication surfaces | `e88763932cd8917a572c657aa1d8bef5503e2f50` | `b162dd31ae0948c8238adae834682835f7355014` | #311 |
| R2 elastic and interaction stacks | `ad7f231b07378666233aeeb0575ad408bb78dd5d` | `39e6ff832da2b485c494d2e7931a21ee7e1cff08` | #312 |
| R3 bridge, crack and fatigue stacks | `8f9504a50f59119c5c979dde8e7bf4479120f6d5` | `f20b8e22656c621c5f8c10f96308587d8178dc76` | #314 |
| R4 shear, torsion and detailing stacks | `bf0acc136db7eb069029cdb5f980482f1a1b73b3` | `d3e9769b227506cb34a3a78ffd859527ad45b417` | #315 |
| R5 core residue | `8c79f48365671960e8ad53d584605aca742cd1e5` | `3e05c71ebb65ddc3ea8a00f8d7f2f81fcfce2c5b` | #316 |

F-016, F-030 and F-031 were calculation-trace publication objectives and are
therefore superseded. Sector retains the direct solver results and the
calculations displayed in the UI, report and manual. It intentionally has no
calculation-trace payload, trace view, optional trace toggle or trace report
appendix. The earlier PR-08 trace implementations are historical lineage only,
not current product requirements and not a source for later work.

## Accepted PR-09 to PR-11 lineage

The ledger must bind every closed row to these accepted candidate heads:

- PR-09: #283 `8de002c85e4bac0c24b6075319c519cfb44f71ba` and
  #287 `204a83b89b1df62779179f6e84c52916673a46db`.
- PR-10: #290 `9b5d11a4529581f6404941cca3355d27b637bc58`,
  #291 `e602901161dfa463145fc10e848f3d197a587d76`,
  #295 `bc74309e193d362ae015fc68e78a802a9e43a87d`,
  #296 `bda00599af25f2d3b1869b1469987db85cc0e1de`, and
  #297 `48faa10364473c2245b4a04632fafa7f32f052cf`.
- PR-11: #299 `257adb0171ef47327300041b580c5a6ed54245ad`,
  #301 `bda23848498c21766134d276c1e5824d16cbc66a`,
  #302 `0852b6abb8f95bbb097b117bc4f658406b26ccfd`,
  #308 `75d5e2a07876185abda439344cb2c0472c70e058`,
  #309 `abc2eb7d6ba49116ec51f110383106d1e95e619b`,
  #317 `1b9c87536ba8b2709c1e737b3629f452ef5819d3`,
  #318 `7e88b5599159a699152345151ee9f4eedf3bb12c`,
  #320 `d396238727172849b7ffa6d299fdb5916e05f200`,
  #322 `5cb7e63f3e22d4495c98168c7fe33d989c6b9bb4`,
  #325 `e812dc7c92c31c6bb6f62e287b07502e7f08ceb4`,
  #326 `ab1456e6e2b5f628353053bdc39ba1532a161441`,
  #328 `fa000b0feabdb6355e11b7a339a0b0a5f9ca3d12`, and
  #329 `f95b6d92afea4de92bb8f76820761631566af938`.

## Consistency guard

The focused guard parses the Markdown table rather than searching loose text.
It requires the trace-only findings to be superseded, every PR-09 to PR-11 row
to be closed and bound to its accepted head(s), and PR-12 to PR-14 rows to remain
planned. It also pins the R1-R5 identities and the unchanged `0.91` version.

## Explicit exclusions

- No original QA workbook edit or retrospective claim that an external reviewer
  approved an SHA it did not review.
- No change to PR-01 through PR-07 closure claims in this bounded reconciliation.
- No PR-12 performance implementation, PR-13 quality-gate implementation,
  PR-14 packaging/release implementation, v0.93 work or version change.
