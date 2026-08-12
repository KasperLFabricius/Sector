# PR-09 Sector 0.93 release acceptance

Status: accepted for release readiness. Sector 0.93, its exact source and its
unsigned portable Windows distribution are qualified. The authenticated GitHub
release remains a draft with `published_at=null`; this record does not authorize
or claim public publication.

## Accepted release source

- Release-source revision: `d0f08295b528f42493f5e8dd4b438c17dc304ec4`
- Release-source tree: `9ac057f723ce8d6b0844541c3573e133fa1b5519`
- Annotated tag: `v0.93`
- Annotated-tag object: `d3bebfaf16f10f83e3da9bc804103b5eabf04331`
- Draft release ID: `368822456`
- Draft release node: `RE_kwDOTFQLds4V-8i4`
- Release-notes SHA-256:
  `8BFE1D04E79D102D459D4333FA6FEEBB8D332D3E0E5332587526153D61B9DDA6`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Decision register: [Sector v0.93 decision register](v093_decision_register.md)
- Release notes: [Sector 0.93 release-candidate notes](v093_release_notes.md)

The release source is the accepted PR-09 squash, not a later administrative or
recovery correction. All later corrections preserve the tagged revision, tree,
draft body and seven release assets.

## Reconciled programme lineage

The table records each reviewed implementation PR head, squash commit, accepted
tree and successful terminal Sector QA run. Historical candidate wording and
intermediate failed or superseded runs do not override these receipts.

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
| PR-09 | #391 | `f60437ca73c6ce992957af8931e73c346d707172` | `d0f08295b528f42493f5e8dd4b438c17dc304ec4` | `9ac057f723ce8d6b0844541c3573e133fa1b5519` | `31525047117` |

PR-09 exact-head run `31517557242` passed all seven jobs before merge. The
main-push authority `31525047117`, attempt 1, then passed 3,631 tests with one
skip, the coverage gate, 69 report pages, 68 manual pages, both independent
portable producers, byte comparison, controlled startup smoke and final
portable re-verification. Its exact seven job IDs are:

| Job | ID |
| --- | ---: |
| Full test and report gate | `93891180278` |
| Unsigned QA Windows package | `93901841194` |
| Unsigned portable producer A | `93901841185` |
| Unsigned portable producer B | `93901841206` |
| Compare immutable portable producers | `93904131230` |
| Isolated verified portable startup smoke | `93905080229` |
| Unsigned portable Windows distribution | `93905809165` |

## Recovery correction lineage

The first draft workflow created the exact annotated tag and attached the exact
assets, but GitHub's draft-release read semantics exposed retry and visibility
defects. PRs #392 through #395 corrected only the recovery verifier and its
policy boundary. They did not change the tagged source or release assets.

| PR | Main commit | Main tree | Purpose |
| --- | --- | --- | --- |
| #392 | `a55916ba4e922389963c2a3658d46cbbbd6537a5` | `6ea08f7c4dcde1ba24ce1ee912d74eb372ee73b2` | Add one-shot recovery verification. |
| #393 | `d808b23dbf630257aea534713506f45769c22840` | `341d166b15fe4c8b6becb2e71830178d674e53e5` | Make draft-readable authority explicit and GET-only in implementation. |
| #394 | `1f038ef92743c1b07315ca89aac561118489ae3e` | `59a7cfa834428f57c8013e61b30b60c72553b3aa` | Retry bounded GitHub API reads. |
| #395 | `8d4e0f5d074d37b994c3fe9e5408faf3afce6ef4` | `c54d1922ddb25242790751de078c645578f211e3` | Validate retained artifacts by run attempt and select the successful attempt. |

PR #395 passed exact-head review with no P0-P2 finding and all seven QA jobs.
Its main-push run `31592234099` also passed all seven jobs. Recovery run
`31596775357`, attempt 1, job `94114107683`, then:

- authenticated the original successful main QA authority and current control
  main `8d4e0f5d074d37b994c3fe9e5408faf3afce6ef4`;
- anonymously checked out the exact tagged source and verified tree
  `9ac057f723ce8d6b0844541c3573e133fa1b5519`;
- freshly downloaded all seven draft assets and passed the standalone verifier;
- confirmed source archive SHA-256
  `DF94CED02726350F9C31BAA0D5E88D0C0DE78BD54D63504527C736CCC4A21D1A`;
- confirmed portable archive SHA-256
  `FE0FA0BA01D6203B83D6A0F00318A7B5C40301E46BC1FD63C86CA35105AA5BF8`;
- confirmed combined asset-list SHA-256
  `E835F18C43BAA3ABEAD46999A78C9FC6906F320266D38012AC14D3E1F1521A20`;
  and
- compared the complete tag, draft and asset state before and after recovery
  byte-for-byte with no external mutation.

The one-shot workflow is now preserved verbatim as reviewed evidence at
`docs/v093_release_recovery_workflow.yml` and is absent from
`.github/workflows`, so it is no longer dispatchable from the default branch.

## Canonical release assets

Draft release `368822456` contains exactly these seven uploaded assets:

| Asset | ID | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `SHA256SUMS.txt` | `510578229` | 647 | `E835F18C43BAA3ABEAD46999A78C9FC6906F320266D38012AC14D3E1F1521A20` |
| `Sector-v0.93-release-qa-receipt.json` | `510578240` | 3,872 | `E3FB413F2D7E60D631212D3992E98BC4825B07FFB196FDBA07E9BC85AC3EE8F1` |
| `Sector-v0.93-source.zip` | `510578248` | 8,000,728 | `DF94CED02726350F9C31BAA0D5E88D0C0DE78BD54D63504527C736CCC4A21D1A` |
| `Sector-v0.93-source.zip.sha256` | `510578280` | 90 | `33F9C24C3510999AEBF8C668793E2FF73FDEE88B093F2E307D03D6F447B5EF71` |
| `Sector-v0.93-windows-portable-unsigned.portable-distribution.json` | `510578283` | 988 | `E30D71F873945B3DA16D92E58BDED3D6764231D660571EA7654880EAD7A106D0` |
| `Sector-v0.93-windows-portable-unsigned.zip` | `510578287` | 431,949,189 | `FE0FA0BA01D6203B83D6A0F00318A7B5C40301E46BC1FD63C86CA35105AA5BF8` |
| `Sector-v0.93-windows-portable-unsigned.zip.sha256` | `510578521` | 109 | `197C6E4946347B240263B3FD50E8134FD9B1D60E961FE47E3AC5EFBD04CF4AD3` |

The draft remains `draft=true`, `prerelease=false` and `published_at=null`.
Its body, tag target and seven asset IDs, sizes and digests were unchanged by
the successful recovery. Public publication requires separate owner action and
is outside this acceptance.

## PR-09 affected surfaces and preserved boundaries

| Surface | Accepted change | Preserved boundary |
| --- | --- | --- |
| Runtime and resources | Live Sector version is `0.93`; PE version is `0.93.0.0`. | Product name, description, author, copyright and licensee remain byte-identical. Project schema remains 24. |
| Product wording | Optional crack criteria and the 0.93 release candidate are described honestly. | No global compliance, certification, complete-code, signed-publisher or public-release claim. |
| Programme/workbook | PR-01 through PR-09 are reconciled and the canonical decision workbook is regenerated. | D093-001 through D093-027 and historical v0.92 evidence remain unchanged. |
| QA | A unique create-only pytest basetemp and the exact seven-job authority are retained. | Coverage, Ruff, strict mypy, dependency, PDF and packaging gates do not shrink. |
| Release | Exact source and unsigned portable assets were attached, freshly downloaded and reverified. | No signing workflow, protected environment, certificate, installer, overwrite path or publication action. |

## Refreshed decision-workbook receipt

- Refreshed workbook SHA-256:
  `C9101A8A3B5068E3AC414069CC038A4A0CF0D9E758ABC7847826F1E86759C61C`
- Canonical decision Markdown SHA-256:
  `4BA8FEA833BF453BE627C59B1828C70140C11453B9F0B7E16D5F8C67C46F88B8`

Hidden Excel regenerated the five-sheet administrative closure workbook with
PR-01 through PR-09 in their evidence-backed `Merged` state. Its five PDF
previews contain eight pages in total. All eight were rendered at 160 DPI and
inspected at original resolution; headings, tables, wrapped text, formula
summaries and footers were readable and unclipped, with no overlap or broken
layout. This workbook is a post-release administrative snapshot on `main`; it
does not claim to be inside the already frozen `d0f08295...` source archive.
