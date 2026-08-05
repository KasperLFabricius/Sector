# PR-12D PR-12 closure map

## Purpose

This document reconciles the completed PR-12 Streamlit responsiveness,
active-pane, fragment-safety and performance program with the v0.92 QA closure
ledger. The QA workbook remains a finding index, not a live approval surface.
Closure means that the frozen slice evidence passed, Codex Review left zero
unresolved P1/P2 on the accepted candidate head, and the candidate tree was
verified exactly after squash merge.

PR-12 changes only UI construction, rerun ownership and opt-in local performance
measurement. It changes no solver, formula, result, project schema, report/manual
content, package, release, application version or calculation-trace surface.

## Exact accepted lineage

| Slice | Accepted candidate head | Accepted tree | Squash-merge commit | Merged PR |
|---|---|---|---|---|
| PR-12A1 | `40a0e581631b9538c6af0f1f7241d9e6310690c0` | `602608b50c1a27a0ed436513b2efa3a53d7c0d0d` | `81e0310790246b2445a65c0d564e8a211d3024d2` | [#334](https://github.com/KasperLFabricius/Sector/pull/334) |
| PR-12A2 | `3da762b31dfa449d3e1e72f68eaab433089574c9` | `dca6f71c2e6d26292c6b9631674d493d9c0da71d` | `1398b5ac7b1b0e8c2fc209dae764d5fa09df1c8c` | [#335](https://github.com/KasperLFabricius/Sector/pull/335) |
| PR-12B | `1f47e8ccd88465a95434d3d3384937af6e46567d` | `0821ecd55dcf8c28420ff8a25a243aaf97494e3b` | `051d6ad4b096b775d7d3ca9ef44af9ab635f0609` | [#336](https://github.com/KasperLFabricius/Sector/pull/336) |
| PR-12C1 | `412463883e1a98a134773bbe3965335d660aa326` | `b567d807b0d73789a7d848aeee76acb4009b194b` | `3d997cea4058f5b0b916e75e88bbc18a235be29a` | [#339](https://github.com/KasperLFabricius/Sector/pull/339) |
| PR-12C2 | `2e2a4bdcb296bf100339860de4518dd2eeb48b61` | `fee56dce295af06cb7ac64a0ffe7885622c70d0c` | `f4f725a21eda897dbaf98126e509bed21001bdc1` | [#340](https://github.com/KasperLFabricius/Sector/pull/340) |

The merge commits form one consecutive first-parent chain from
`ef0362a09a8c2c5e6eef1e8cd225534619c74ccd` through
`f4f725a21eda897dbaf98126e509bed21001bdc1`. Every merge has exactly one parent
and its tree equals the accepted candidate tree in the same row.

## Finding-to-slice closure

| Finding | Accepted slices | Closure evidence |
|---|---|---|
| F-018 | PR-12A1 | The full-width five-choice outer selector stays inside 390, 768, 1280 and 1920 px viewports, exposes the exact ordered choices and mounts one outer stage. |
| F-025 | PR-12B, PR-12C2 | Ordinary pane changes execute inside the sequential Inputs fragment. Exact owner telemetry and default/dense warm rerun distributions prove the outer application and unrelated workspaces are not rebuilt. |
| F-026 | PR-12A1, PR-12A2 | Exactly one outer stage and one applicable material family render while inactive values, tables, catalogues, assignments and complete analysis inputs are reconstructed from one canonical draft. |
| F-027 | PR-12B, PR-12C2 | A normal complete build is the only commit boundary; interrupted builds restore and replay genuine events. Root identity prevents coalesced parent/nested queues from splitting one rerun between owners. |
| F-028 | PR-12C1, PR-12C2 | Disabled instrumentation is inert. Enabled local records cover the complete app, five root fragments, six closed phases, ForwardMsg sizes and frozen cold/default/dense performance tripwires. |

The reported sparse fatigue row (`1`, `Train`, 36,000 cycles and only
`Delta Mx,Ed = 17 kNm`) is included in F-027 evidence: omitted action components
receive explicit zero defaults, the row survives pane navigation and it reaches
calculation.

## Review and correction record

- PR-12A1 was accepted after one immutable clean exact-head review.
- PR-12A2 corrected one hidden-family Auto-calc journal class from superseded
  head `928f17200f0aef27ba5e00ad8c2fa014dfcec451`, then received a clean review on
  accepted head `3da762b31dfa449d3e1e72f68eaab433089574c9`.
- PR-12B corrected one fragment-exit callback class from superseded head
  `55730a3ed65276b8e05da85e0a5c0e1d9ed8d1b1`, then received a clean review on
  accepted head `1f47e8ccd88465a95434d3d3384937af6e46567d`.
- PR-12C1 corrected one interrupted-enqueue accounting class from superseded
  head `ac9e5ca989d967a05970fec602964f28764b5dcf`, then received a clean review on
  accepted head `412463883e1a98a134773bbe3965335d660aa326`.
- PR-12C2 was accepted after one immutable clean exact-head review.

The superseded heads above are negative evidence only. They are absent from the
accepted lineage and must not be reused. Rejected PR-12C predecessor candidates
remain rejected and are not implementation evidence for this map.

## Evidence boundary

- PR-12A1: `tests/test_input_stage_host.py`, retained focused UI/mechanics tests,
  and [outer-stage acceptance](pr12a1_f018_outer_stage_acceptance.md).
- PR-12A2: `tests/test_input_stage_host.py`, `tests/test_app_smoke.py`, and
  [material-family acceptance](pr12a2_f026_material_family_acceptance.md).
- PR-12B: `tests/test_app_smoke.py` plus
  [fragment acceptance](pr12b_f027_input_fragment_acceptance.md).
- PR-12C1/C2: `tests/test_app_run_probe.py`, directly affected Streamlit tests,
  [full-app acceptance](pr12c1_f028_full_app_probe_acceptance.md), and
  [fragment-performance acceptance](pr12c2_f028_fragment_performance_acceptance.md).

The in-app browser automation surface does not expose `PerformanceObserver`
Long Task entries. PR-12 does not add client instrumentation merely to benchmark
itself and makes no zero-long-task claim. The accepted non-invasive blocking
boundary is browser interaction-to-visible-pane duration supported by exact
server phases and ForwardMsg deltas.

Sector remains version `0.91`. PR-13 and PR-14 remain planned and start only from
the newly verified accepted main. PR-14 retains the genuine-signing-authority
stop condition; this closure grants no signing or release authority.
