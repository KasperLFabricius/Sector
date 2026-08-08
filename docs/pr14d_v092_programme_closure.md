# PR-14D v0.92 programme closure map

## Purpose and closure rule

This documentation-only audit reconciles the completed v0.92 programme with
the QA closure ledger. The workbook remains the immutable finding index, not a
live approval surface. A slice is accepted only when its frozen evidence is
green, the accepted candidate has zero unresolved P1/P2 review threads, and the
squash merge has the expected parent and the exact candidate tree.

The implementation baseline entering this audit is accepted main
`db8e96ea09c8a4a6685350d162164896a65b35bd`. Sector remains version `0.91`.
The QA workbook remains untouched at SHA-256
`1DE1CA43F0155A282BE7228DFB8480189301071EC21A38DECB34254ABFCC9854`.

## PR-01 through PR-07 accepted closure

| Slice / findings | Accepted candidate | Accepted tree | Squash merge | PR |
|---|---|---|---|---|
| PR-01 / F-001 | `f3d609499af0d7c8fc9520e6131e81fcf72b19ef` | `ffaf6dc7a0756558fda0518b65af025e32193e6e` | `91b2470e463a29c70e6cc6b08b123bcee84aa78d` | [#204](https://github.com/KasperLFabricius/Sector/pull/204) |
| PR-02 / F-004 | `c789ad9bfc94921f3383e9bce3c056b8e445cdcd` | `db596d97e4c27402fc114aafaf32b7e510d266e5` | `91bb63f9bd05050f508334202ca531367420062e` | [#205](https://github.com/KasperLFabricius/Sector/pull/205) |
| PR-03 / F-003 | `298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec` | `1f0ed6d315be027cb3070967ab22cd8cc606b98a` | `760db72914f341b9d69a4033ef2676f75bf10ced` | [#206](https://github.com/KasperLFabricius/Sector/pull/206) |
| PR-07 reset / F-002, F-005--F-011, F-022--F-024, F-029 | `3ef90fd11d002ae21b24c32f979ba7371f8a8428` | `99de31aec11d39d837e1a7755ec125b3ddfb6202` | `88c93d9e1e62d69e596d36631ea644d81bda9cdd` | [#210](https://github.com/KasperLFabricius/Sector/pull/210) |

PR-07 is the accepted product-identity authority for the reset findings. The
earlier merged PR-04, PR-05 and PR-06 implementations are historical ancestry,
not accepted current behavior:

| Superseded slice | Candidate | Tree | Squash merge | PR |
|---|---|---|---|---|
| PR-04 | `047b0a3f54746a624233680e0b83492d4aad24e7` | `18f03e6ec6bd25fac184555359e50e414ac2af47` | `6428bf315a15bd8904451de3d70d400fc79d8d47` | [#207](https://github.com/KasperLFabricius/Sector/pull/207) |
| PR-05 | `a53aa76b3fb7618c9fa2cf6a7437fac364c762a2` | `e014b24b5e70e6756bd7ecf0b3b52a87c261cd4b` | `82551e98714dfd47ff7f631685cc791c1431385f` | [#208](https://github.com/KasperLFabricius/Sector/pull/208) |
| PR-06 | `a88e5dabe84368ff701ec184418813d291c2bbb3` | `f02c53e1878e1956ed0508a6d6e3a093a7d847c2` | `e4580241a7fe726cd4f718edfa990e1aafcb48ff` | [#209](https://github.com/KasperLFabricius/Sector/pull/209) |

PR #209 retains one unresolved historical thread. It is not resolved or reused:
PR #210 supersedes the implementation and has zero unresolved threads.

## PR-13 exact accepted lineage

| Slice / finding | Accepted candidate | Accepted tree | Squash merge | PR |
|---|---|---|---|---|
| PR-13A1A-R2 / F-013 | `0d2d325298a70a901f15f1ed4889320a932be0ee` | `09d19b57b87f8fbc715ab498907947cd30cd5df7` | `f133ebae880b27e07a71586a0aea8fa920306e79` | [#344](https://github.com/KasperLFabricius/Sector/pull/344) |
| PR-13A1B / F-013 | `10d1617b54042b5e4bff898c00d6a58ad433091d` | `cc7c9013a6244c85435d115192b19953e34f5fa2` | `599c6d8f506f335f9dee9c7355b0efee3b345596` | [#345](https://github.com/KasperLFabricius/Sector/pull/345) |
| PR-13A2 / F-013 | `328d4fa681db07909b47a911e794690d46c8ca4e` | `310d24e31f2368a903cf4936530e87403de62217` | `65452fc9013150ff7cff3507debae7bb34ed3d1c` | [#346](https://github.com/KasperLFabricius/Sector/pull/346) |
| PR-13B1A / F-012 coverage | `86ed9cae8519d90cb8a2b474a0076855fe73b547` | `7ac394c0debc72db2073bb74546a8aa58d162a57` | `c67ea2b3640580786f4b12e2c316c5f142d11e93` | [#349](https://github.com/KasperLFabricius/Sector/pull/349) |
| PR-13B1B-R2 / F-012 Ruff | `e48e4847d4d368e9044dfac04b536b93a08652ca` | `14a812867bd5ad12ee11b49111483332a7e0a7f0` | `33ce159264fcfaab7032d5ef62ee2f27323749eb` | [#351](https://github.com/KasperLFabricius/Sector/pull/351) |
| PR-13B2 / F-012 strict mypy | `0f092e67031015f3825a1c128d231ff7e93ce873` | `95dd6ffddc5335ed022e5375ff7ef273d6dda63a` | `1f47b8747be54b48bab6205eef111f8869e4984e` | [#352](https://github.com/KasperLFabricius/Sector/pull/352) |
| PR-13B3-R2 / F-012 audit | `85cd6d1b4881afeaf63985f2ee57eac8b79007c3` | `808ece4e5ae5008159bb091dfaec25c596d42c3e` | `006fadf287c1213d1a788538097bfa4261f14a6f` | [#354](https://github.com/KasperLFabricius/Sector/pull/354) |

PR-13 closes F-013 at the raw bridge-input, typed bridge-failure and capacity
result boundaries. It closes F-012 with non-shrinking coverage, Ruff and strict
mypy ratchets plus a hash-locked dependency audit. PR-14C4 removes the temporary
coverage-calibration waiver and raises the enforced floor to 90%.

## PR-14 exact accepted lineage

| Slice / finding | Accepted candidate | Accepted tree | Squash merge | PR |
|---|---|---|---|---|
| PR-14A1A-R3 / F-014 | `5d9c3a899dd0f47b5d51895df09d79ebaa2479c8` | `e954cad490170307becb931321cff7f58f846b38` | `ab4ef9eb77d246a8a32d196ae2e01e7168555a2c` | [#358](https://github.com/KasperLFabricius/Sector/pull/358) |
| PR-14A1B / F-014 | `9dc236e102b801cfd0b7bc296633ea234356ea36` | `0046d5657b68e1707ea3bdffc0743a5b565114ee` | `fa99c278ee52edc7b8cf635aedb848211dc0e3ac` | [#359](https://github.com/KasperLFabricius/Sector/pull/359) |
| PR-14A2-R2 / F-014 | `0067ae1172617dab19247a67782d78d084482803` | `566a533922ec662a48fd3f0bc88834e93b4473cb` | `af23b3c89751d19f7146f588434eb89d69bd06fd` | [#361](https://github.com/KasperLFabricius/Sector/pull/361) |
| PR-14B / F-015 | `80e67d500ae06ef07be72fd0e65ed84f8738dd60` | `c946168cc04992f1d89b2e086e4abc2386060ffd` | `237e09ff7ce095a0b2c99e1548aed1b52451f721` | [#362](https://github.com/KasperLFabricius/Sector/pull/362) |
| PR-14B.1 / F-015 | `b4b3cd9bca45b5f0102592daf08ca60b79d3c05c` | `f2009b1d79072b68c4826351c6670f1f14d12d8d` | `80469ec1af101d67884f32d38b69a2071bfa22c1` | [#363](https://github.com/KasperLFabricius/Sector/pull/363) |
| PR-14C1A-R3 / F-021 | `ed55d46488e2f336109231972b40ffd60bfcb656` | `2020b630cf89c05712142b1e0f790e4b9dddbfac` | `8962315e77e7127c0f65d85c4d607b63fa44de27` | [#368](https://github.com/KasperLFabricius/Sector/pull/368) |
| PR-14C1B / F-021 | `6a412aec742ce037abbb276028b541a8d4456e11` | `2e04e0972e579f47a3991bc307c7121513bfd79d` | `a98026dd0959eea6e1ee54b0f403dc5e67d2d23c` | [#369](https://github.com/KasperLFabricius/Sector/pull/369) |
| PR-14C2R3 / F-021 | `85cab3d5ae2c1f7be759fbd8ead6a5cb608eb520` | `230b77234f4bdb1181286b161954d0e21ce7ffe8` | `bbab7c55e1499a53d61768bf627257a6300ad99d` | [#372](https://github.com/KasperLFabricius/Sector/pull/372) |
| PR-14C3 / F-021 | `b3fd4f2f8771b5fbfc2e9aeb6b38bb77a9c9791b` | `e13f49d86d4e57ce4674f08efd038a441092d214` | `e4a8f319fe2b8bfc57a711d84be36b56d20b3a6f` | [#374](https://github.com/KasperLFabricius/Sector/pull/374) |
| PR-14C4R2 / F-012, F-021 | `e3a60ea9adccf156d8940aed10a4c9f9fb52ee35` | `45ff8bccc657a0aa7a22e64b361399a66bf2fd7c` | `db8e96ea09c8a4a6685350d162164896a65b35bd` | [#376](https://github.com/KasperLFabricius/Sector/pull/376) |

PR-14A closes the software-controlled Windows identity, unsigned-QA fence and
protected-signing gate. Genuine certificate, publisher, timestamp/reputation
and environment approval remain external release authority. The protected
`sector-production-signing` environment and its secret inventory both return
API 404 to the authorized principal, so no protected release was dispatched and
no signature was fabricated.

PR-14B reduced bare `import sector` from a measured 1,429.105 ms median to
4.506 ms median and reduced the measured Streamlit startup path from 5,694.9 ms
to 4,260.2 ms, while retaining explicit launcher progress and the active-stage
AppTest lifecycle.

PR-14C closes the source/build reproducibility boundary: authenticated raw
commit export, isolated exact-source build, sealed package source identity, two
independent builds, complete-package byte comparison and a consolidated
publication gate. The accepted C4 run
[31222928878](https://github.com/KasperLFabricius/Sector/actions/runs/31222928878)
passed 2,964 tests with 1 skip, 90.95% coverage, 101 audited dependencies with
zero vulnerabilities/fixes, a clean 56-page report and 46-page manual, and
byte identity across 6,888 package files / 438,653,453 bytes.

## Rejected, corrected and retired evidence

- PR [#375](https://github.com/KasperLFabricius/Sector/pull/375) is closed
  unmerged and preserved at `e0a3d1b60b8ae43d8c6ff74805acc3484129535f`
  with three unresolved P1 threads. It is negative evidence only and is not an
  ancestor of accepted C4.
- PR #376's initial head
  `fb676d25394f8277133250c4dc7bb5b9494f9785` received one P1. The sole bounded
  correction produced accepted head `e3a60ea9adccf156d8940aed10a4c9f9fb52ee35`,
  resolved the thread and received a clean corrected-head review.
- Calculation-trace implementation from PR-08 is not current product evidence.
  It was retired by accepted PRs #311, #312, #314, #315 and #316 and is
  reconciled in [the trace-retirement map](pr11d1_trace_retirement_reconciliation.md).

All accepted PRs listed in this document have zero unresolved review threads.
Historical or rejected threads are preserved rather than falsely resolved.

## Complete finding boundary

- F-001--F-015 and F-021--F-024/F-029 are closed by the lineages above.
- F-016, F-030 and F-031 are closed as retired product surfaces by the accepted
  R1--R5 trace-retirement sequence.
- F-017, F-019 and F-032--F-042 are closed in the
  [PR-09 through PR-11 map](pr11d2_pr09_pr11_closure_map.md).
- F-018 and F-025--F-028 are closed in the
  [PR-12 map](pr12d_pr12_closure_map.md).
- F-020 remains intentionally excluded. No untracked/ignored QA artifact or
  local build output was converted into source or removed by this programme.

This closure is implementation QA, not engineering certification. Sector is a
transparent calculation tool; a qualified engineer remains responsible for
input validity, standards applicability, independent verification, design
judgement and acceptance of every engineering result.

## Release transition

This closure map records the accepted programme while the application remained
at version 0.91. The subsequent, bounded release-identity transition to the
0.92 source/application release is specified separately in the
[PR-15 release acceptance](pr15_v092_source_app_release_acceptance.md). That
transition does not rewrite the historical identities or claims above.
