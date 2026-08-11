# PR-09 Sector 0.93 release acceptance

Status: implementation candidate. Exact-head qualification, squash/main parity
and the guarded post-merge draft-release receipt remain open until those events
exist; this record does not invent them.

## Accepted upstream base

- Programme branch: `codex/pr09-v093-release-closure`
- Upstream PR-08 squash revision: `470bbfbc4a80be524d32d1fd6f9509a1c60deede`
- Accepted upstream tree: `b47d4acfe1112a512d31ece0e300e7837bb304e6`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Decision register: [Sector v0.93 decision register](v093_decision_register.md)
- Release notes: [Sector 0.93 release-candidate notes](v093_release_notes.md)

PR-08 passed the full test/report/manual gate, two independently verified
portable producers, immutable byte comparison, controlled packaged-startup
smoke and final portable gather before squash merge. PR-09 starts from that
accepted squash and performs the single coordinated version and release
transition.

## Reconciled programme lineage

The table records each reviewed PR head, squash commit, accepted tree and exact
successful Sector QA run. Historical candidate wording and intermediate failed
or superseded runs do not override these terminal receipts.

| Slice | PR | Reviewed head | Squash commit | Accepted tree | Sector QA run |
| --- | --- | --- | --- | --- | --- |
| PR-01 | #382 | `f71ebb7aa6a901dbe443f90d62f50a2bb0113ffd` | `2f4934ec7c212fd39da9e3f19ba02292b5213c46` | `ce17dde757e7eae76d0fa39c103d20d2049de8bb` | `31284648970` |
| PR-02 | #383 | `49450886491e7c23d97ff434ee00b2f9c6dc2e81` | `b328144abf175e0025c796da929dfe01fd843293` | `b2edde56dc0b37dd19e3250011d04b1a3257f6cc` | `31293520526` |
| PR-03 | #384 | `9fdb4839fa2778e67e6d2c2324640f1c0755ff6c` | `115d78a5fec33bc6d7a614f6a526a17ab32c22e2` | `14ff5582bb6669d902e0ae4be32fd3bd9d626c84` | `31335521261` |
| PR-04 | #385 | `afdd5dd5af7447a592044b029c29d82f2ca4bf18` | `d653ba66478425093a10e893ce5cc38447f2db85` | `23514088b253f5e9f81dcec5301fc4498487d23d` | `31343111358` |
| PR-05 | #386 | `22bccddda637ab272fe295e2d8642b917db91281` | `e622dd1de7649fe2af974120922bd8ba8aec067a` | `bf2c8184d5289d1f1e7a17eb69c0e591aa16403a` | `31347533074` |
| PR-06 | #387 | `fbcd4917654fb4ed23465c4a554d1d208c80d5c3` | `1cf8cf536cc562998fd663a6b082021ace7aa7fb` | `f941158eab1f3caa7a61db066236269d69c7a83e` | `31353275467` |
| PR-07A | #388 | `9a4185e7bbe923032efdcf5a03461fdb7cdcd751` | `0b2ec0735a5f65b3889f2b5ec906f30399ccec11` | `934a288ed67d6f2d6c43b6f201f5e012eef054d1` | `31408881247` |
| PR-07B | #389 | `af908b0f7a1b8b954a02a4982947588a97b516b6` | `47be3326fa4abad5acdc356435dbeeed28d31d95` | `56266e0868093bc26e7bedcd1472721f3b60fb6d` | `31443362231` |
| PR-08 | #390 | `6847246b26fb7d598f909fac6a93628e8e914597` | `470bbfbc4a80be524d32d1fd6f9509a1c60deede` | `b47d4acfe1112a512d31ece0e300e7837bb304e6` | `31491022341` |

PR-08 run `31491022341` also published the exact terminal artifacts required
by its acceptance contract. The final portable artifact was ID `9103299450`
with artifact digest
`b581f70c7c29f28bf3cec2437563a4d3e49740aa2abd3c1d05b1403e22fc19dc`.

## PR-09 affected surfaces

| Surface | Change | Preserved boundary |
| --- | --- | --- |
| Runtime and resources | Change only live Sector version `0.92` to `0.93` and PE version `0.92.0.0` to `0.93.0.0`. | Product name, description, author, copyright and licensee remain byte-identical. Project schema remains 24. |
| Product wording | Publish optional crack criteria honestly and identify 0.93 as the release candidate prepared through a guarded draft-release workflow. | A draft is not a publicly published user release; no global compliance, certification, complete-code or signed-publisher claim. |
| Programme/workbook | Reconcile PR-01 through PR-09 and regenerate the canonical decision workbook. | D093-001 through D093-027 and historical v0.92 evidence remain unchanged. |
| QA | Add a unique create-only pytest basetemp and retain the exact seven-job authority. | Coverage, Ruff, strict mypy, dependency, PDF and packaging gates do not shrink. |
| Release | Add a guarded post-QA `workflow_run` path and a network-free verifier for exactly seven assets. | No executable launch, signing workflow, protected environment, certificate, installer or overwrite path. |

## Canonical release assets

The guarded draft release must contain exactly:

1. `Sector-v0.93-source.zip`
2. `Sector-v0.93-source.zip.sha256`
3. `Sector-v0.93-windows-portable-unsigned.zip`
4. `Sector-v0.93-windows-portable-unsigned.zip.sha256`
5. `Sector-v0.93-windows-portable-unsigned.portable-distribution.json`
6. `Sector-v0.93-release-qa-receipt.json`
7. `SHA256SUMS.txt`

The release QA receipt binds the accepted revision/tree, same-repository
successful `push` event on `main`, run ID/attempt, all seven exact successful
job names and IDs, final and chain artifact IDs/digests, source and portable
hashes, and the verified absence of a PE certificate table. The asset set is
canonical, create-only and path/time/secret-free.

## Mandatory qualification

- focused version, schema, manual, programme/workbook, source, portable,
  release-verifier and workflow-policy tests;
- consolidated publication, dependency-audit, Ruff and strict-mypy gates;
- complete multi-worker pytest with a new unique basetemp and coverage floor;
- real report/manual semantic, structure and raster gates;
- every-sheet decision-workbook formula, OOXML and visual review;
- exact-source and two-build Windows package identity;
- independent portable producers, byte comparison, controlled startup smoke
  and final re-verifying gather;
- independent exact-head Codex P0-P2 review with no blocking finding; and
- after squash merge, exact main-tree parity followed by guarded release
  assembly, draft-release attachment, fresh seven-asset download and full
  revalidation.

## Refreshed decision-workbook receipt

- Refreshed workbook SHA-256:
  `35DED863E0E69889807DFAD79BAE9EE541518BDB09324085AC6B56224E8F1941`
- Canonical decision Markdown SHA-256:
  `4BA8FEA833BF453BE627C59B1828C70140C11453B9F0B7E16D5F8C67C46F88B8`

Hidden Excel regenerated the five-sheet candidate workbook with PR-01 through
PR-08 in their evidence-backed `Merged` state and PR-09 `In progress`. Its five
PDF previews contain eight pages in total. All eight were rendered at 160 DPI
and inspected at original resolution; headings, tables, wrapped text, formula
summaries and footers were readable and unclipped, with no overlap or broken
layout.

The final accepted PR09 head/tree, exact QA run, squash revision, merged tree,
tag object, draft release ID and seven asset IDs/digests will be added only
after each corresponding event has occurred.
