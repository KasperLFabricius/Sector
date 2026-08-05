# PR-11D2 PR-09 through PR-11 closure map

## Purpose

This document reconciles the completed PR-09, PR-10 and PR-11 publication
program with the v0.92 QA closure ledger. The original QA workbook remains the
finding index; it is not a live approval surface. Closure here means that the
frozen slice evidence passed, Codex Review found no unresolved P1/P2 on the
exact accepted candidate head, and the candidate tree was verified after its
squash merge.

Each row below binds one finding, one implementation slice, one accepted
candidate head, its squash-merge commit and its merged PR. Repeated findings are
intentional: those findings required several independently reviewed slices. The
row set is complete and ordered by implementation lineage.

## Exact accepted lineage

| Finding | Slice | Accepted candidate head | Squash-merge commit | Merged PR |
|---|---|---|---|---|
| F-017 | PR-09A | `8de002c85e4bac0c24b6075319c519cfb44f71ba` | `7512c3ed01e41100cee59893ce9beab381bec890` | [#283](https://github.com/KasperLFabricius/Sector/pull/283) |
| F-033 | PR-09A | `8de002c85e4bac0c24b6075319c519cfb44f71ba` | `7512c3ed01e41100cee59893ce9beab381bec890` | [#283](https://github.com/KasperLFabricius/Sector/pull/283) |
| F-035 | PR-09A | `8de002c85e4bac0c24b6075319c519cfb44f71ba` | `7512c3ed01e41100cee59893ce9beab381bec890` | [#283](https://github.com/KasperLFabricius/Sector/pull/283) |
| F-036 | PR-09B | `204a83b89b1df62779179f6e84c52916673a46db` | `563d107d223541703f848e44c07ddfbcc22bd2d7` | [#287](https://github.com/KasperLFabricius/Sector/pull/287) |
| F-034 | PR-10A1 | `9b5d11a4529581f6404941cca3355d27b637bc58` | `c19eaa4efdb6ee91a597bdc241ec08a24074dc9c` | [#290](https://github.com/KasperLFabricius/Sector/pull/290) |
| F-040 | PR-10A2 | `e602901161dfa463145fc10e848f3d197a587d76` | `af2a835c3da31adc41ac3075dee0fb794ffa305b` | [#291](https://github.com/KasperLFabricius/Sector/pull/291) |
| F-032 | PR-10B1a2 | `bc74309e193d362ae015fc68e78a802a9e43a87d` | `efd5516212777269be13a48c207ad1ad3c3b3050` | [#295](https://github.com/KasperLFabricius/Sector/pull/295) |
| F-019 | PR-10B1b | `bda00599af25f2d3b1869b1469987db85cc0e1de` | `def49c5f88da485950e82d74427d5c71e2326b2c` | [#296](https://github.com/KasperLFabricius/Sector/pull/296) |
| F-019 | PR-10B2 | `48faa10364473c2245b4a04632fafa7f32f052cf` | `2c75c81b47e55e41a27dcf9d0351773672023ed0` | [#297](https://github.com/KasperLFabricius/Sector/pull/297) |
| F-037 | PR-10B2 | `48faa10364473c2245b4a04632fafa7f32f052cf` | `2c75c81b47e55e41a27dcf9d0351773672023ed0` | [#297](https://github.com/KasperLFabricius/Sector/pull/297) |
| F-038 | PR-11A1R2 | `257adb0171ef47327300041b580c5a6ed54245ad` | `96e1c5dfe9e6d48e9ff848ad025ed2806202b383` | [#299](https://github.com/KasperLFabricius/Sector/pull/299) |
| F-039 | PR-11A2a | `bda23848498c21766134d276c1e5824d16cbc66a` | `6d3336867ddaa449f9887551c96b76125dedb6c5` | [#301](https://github.com/KasperLFabricius/Sector/pull/301) |
| F-039 | PR-11A2b | `0852b6abb8f95bbb097b117bc4f658406b26ccfd` | `e25e730c5129a1b5f5a9a194e6bb91e2e5f761cf` | [#302](https://github.com/KasperLFabricius/Sector/pull/302) |
| F-039 | PR-11A3a1L | `75d5e2a07876185abda439344cb2c0472c70e058` | `469b7463da1d2b0fce819099751c86cdc35356ec` | [#308](https://github.com/KasperLFabricius/Sector/pull/308) |
| F-039 | PR-11A3a1S | `abc2eb7d6ba49116ec51f110383106d1e95e619b` | `8f687b0af00bc79748860cc5df9ccf9e451f793e` | [#309](https://github.com/KasperLFabricius/Sector/pull/309) |
| F-039 | PR-11A3a2 | `1b9c87536ba8b2709c1e737b3629f452ef5819d3` | `141b1a9cb0ebed18d7ed84124d54327bae48909c` | [#317](https://github.com/KasperLFabricius/Sector/pull/317) |
| F-039 | PR-11A3b | `7e88b5599159a699152345151ee9f4eedf3bb12c` | `061d15cda6bb137068bcae2d31a97729500443df` | [#318](https://github.com/KasperLFabricius/Sector/pull/318) |
| F-041 | PR-11B1 | `d396238727172849b7ffa6d299fdb5916e05f200` | `ed20ae984165750fc1a560d591ac9b1e1a3d1fe9` | [#320](https://github.com/KasperLFabricius/Sector/pull/320) |
| F-041 | PR-11B2A | `5cb7e63f3e22d4495c98168c7fe33d989c6b9bb4` | `738a31a32868adaedf32ecccbffde43d19de6d09` | [#322](https://github.com/KasperLFabricius/Sector/pull/322) |
| F-041 | PR-11C1A | `e812dc7c92c31c6bb6f62e287b07502e7f08ceb4` | `fbc2acffa5a9fa65be3d78a5def6219004c03038` | [#325](https://github.com/KasperLFabricius/Sector/pull/325) |
| F-041 | PR-11C1B | `ab1456e6e2b5f628353053bdc39ba1532a161441` | `e5c90ccc8c8ce730d534deba9331f8af6fcd36df` | [#326](https://github.com/KasperLFabricius/Sector/pull/326) |
| F-042 | PR-11C2A | `fa000b0feabdb6355e11b7a339a0b0a5f9ca3d12` | `53b0d7895a45ab570d04a5651d2502e873b0688a` | [#328](https://github.com/KasperLFabricius/Sector/pull/328) |
| F-042 | PR-11C2B | `f95b6d92afea4de92bb8f76820761631566af938` | `f0aa5b8de644a2a24d01a58a6e26c7af4b0690c7` | [#329](https://github.com/KasperLFabricius/Sector/pull/329) |

## Closure boundary

- Every accepted candidate above had one immutable exact-head review cycle (or
  the bounded corrected-head cycle recorded on its PR) and zero unresolved
  P1/P2 when accepted.
- Each squash merge was checked to have the prior accepted `main` as its sole
  parent and the accepted candidate tree as its exact tree.
- The ledger binds candidate heads to PR numbers by position. It does not infer
  a pair from unrelated SHA or PR text elsewhere in the row.
- Calculation-trace retirement is reconciled separately in PR-11D1. Removed
  trace files and surfaces are not evidence for any row in this map.
- This reconciliation changes no calculation, publication output, schema,
  version, workflow or release surface. PR-12 through PR-14 remain planned.
