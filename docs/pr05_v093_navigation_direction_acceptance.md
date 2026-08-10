# PR-05 Sector v0.93 navigation and modelled-direction acceptance

Status: candidate acceptance contract for the PR-05 development branch.
GitHub records the eventual pull request, exact candidate, tree and squash
identities; this document does not invent evidence that has not been run.

## Exact accepted base

- Repository revision: `d653ba66478425093a10e893ce5cc38447f2db85`
- Repository tree: `23514088b253f5e9f81dcec5301fc4498487d23d`
- Programme branch: `codex/pr05-v093-navigation-direction`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Upstream acceptance: [PR-04 input-correctness acceptance](pr04_v093_input_correctness_acceptance.md)

The base revision is the exact squash merge of PR-04. Its tree is identical to
the accepted PR-04 candidate tree.

## Owner-confirmed objective

PR-05 replaces the outer input-stage dropdown with five native stateful tabs,
while continuing to build only the open stage. It preserves the existing
complete-input snapshot and genuine-event journal boundaries so rapid changes,
fragment returns and result navigation do not discard a completed draft.

PR-05 also gives minimum-reinforcement checks one explicit member-relative
direction. Sector's canonical `Longitudinal` or `Transverse` meaning is always
shown first. A project may append a short local alias, but that wording is
presentation metadata and never changes a calculation, standard route,
selection or result.

## Native active-stage contract

The five frozen stage labels are shown below using the ASCII escape
`\u00B7` for their middle-dot separator:

1. `1 \u00B7 Analysis settings`
2. `2 \u00B7 Section`
3. `3 \u00B7 Material parameters`
4. `4 \u00B7 Loads`
5. `Project & report`

The host uses Streamlit's keyed native tabs and trusts only an exact `.open is
True` state. Exactly one returned tab must be open and it must match the
canonical keyed selection; an ambiguous, missing or contradictory host state
mounts no expensive stage. Closed-stage wrappers remain inert, including when
nested below a closed parent.

The selected label is navigation state, not an engineering input. Completed
input snapshots, pending genuine widget events and inactive material-family
values remain owned by their existing durability boundaries. Switching stage,
returning from Results or applying Quick Section does not make a hidden stage
execute merely to recover its values.

## Canonical modelled direction

Once a calculation is retained, the result-owned direction is authoritative.
Before calculation, the selected section cut supplies the same deterministic
fallback: a transverse cut models longitudinal reinforcement and a longitudinal
cut models transverse reinforcement. Unknown retained directions and unsupported
cuts fail closed; labels are never used for dispatch.

The optional project alias is normalized to one line with collapsed horizontal
whitespace and a shared maximum of 60 characters. Values above that bound are
rejected symmetrically on entry, save and current-schema load; they are never
silently truncated by the widget. Every surface publishes the canonical
direction before the alias.

Streamlit Markdown receives punctuation-escaped literal project text. Report
markup receives HTML-escaped literal text before Sector's trusted notation
normalizer. Aliases that resemble Markdown directives, links, emphasis,
scientific notation, Greek substitutions or ReportLab tags therefore remain
project wording rather than executable presentation markup.

## Persistence, freshness and calculation identity

Project schema remains 24. The alias is stored under the current-schema
top-level `presentation` mapping, not among engineering input scalars. Unknown
presentation keys and malformed aliases fail closed. The alias is excluded from
the canonical calculation input digest, so changing terminology does not stale
or relabel engineering evidence.

Presentation metadata is nevertheless included in a separate persistence
fingerprint, so an alias-only edit is written by autosave. It is also included
in the report signature, so an already generated document becomes stale when
its published wording no longer matches the project. Save/load and report
freshness therefore preserve the alias without pretending it is a calculation
input.

## Cross-surface publication and density boundary

The canonical direction is published before the detailing selection, on the
calculated minimum-reinforcement result card, in result summaries, in report
cover/settings/basis/minimum-reinforcement content and in the manual. The same
resolver supplies every surface; retained result identity wins wherever it is
available.

PR-05 does not change PR-03's worked-calculation policy. Reports continue to
show a full textbook substitution only for the globally governing or extremum
example in each calculation family, while non-governing cases remain compact
summary evidence. An alias does not create another worked example or duplicate
a calculation chapter.

## Browser, JavaScript and performance boundary

PR-05 adds no custom JavaScript, component or client dependency. The tab host is
a small Python adapter over the version-matched native Streamlit tab contract.
Host tests exercise exact open-state agreement, and browser-free Streamlit
AppTest exercises all five server-side active-stage lifecycles, interrupted
draft recovery, fragment/result transitions and the calculated direction card.

AppTest does not emulate a physical browser tab click. Local PR-05 acceptance
therefore makes no claim about browser interaction latency and launches no
browser, Electron process or JavaScript runtime. Fresh-process AppTest wall
times and the existing opt-in server probe are retained as descriptive
cold-start/active-stage observations only, with no brittle millisecond pass
threshold. A final remote packaged-app browser interaction check remains part
of release qualification before v0.93 is declared ready.

## Schema, identity and programme boundaries

PR-05 keeps project schema 24 and runtime/publication version 0.92. PR-09 owns
the final version transition after the complete programme gate. The immutable
PR-01 workbook remains a planning snapshot; living Markdown status changes do
not mutate or rehash it.

PR-05 does not implement the PR-06 ordinary crack criterion or heightened
DK/NA calculation, PR-07 equation rendering or report profiles, PR-08 portable
packaging, or PR-09 release identity. It introduces no solver, engineering
equation, generic trace/evidence framework, project migration, compliance claim
or certification claim.

## Acceptance requirements

Acceptance requires:

- direct keyed navigation mounts exactly one matching input stage and never
  executes hidden expensive stages;
- interrupted or rapid widget changes preserve the last complete draft and
  genuine pending events;
- Quick Section, save/load, result navigation and inactive material-family
  transitions preserve their independent fragment and session boundaries;
- every retained minimum-reinforcement result owns and publishes exactly one
  canonical longitudinal or transverse direction;
- project aliases remain optional, literal, canonical-after, presentation-only
  and at most 60 normalized characters;
- alias-only edits persist and stale the report, but do not alter the canonical
  engineering input hash or any calculated result;
- calculated UI, result summary, report and manual surfaces use the shared
  direction contract; and
- schema 24, runtime version 0.92, PR-03 global-critical worked-example density
  and all existing engineering calculations remain unchanged.

## Verification evidence

The final local affected-surface gate on the exact PR-04-rebased candidate
produced:

- 218 passed: complete modelled-direction, input-stage host, project-I/O,
  result-presentation, run-probe and lazy-startup suites;
- 195 passed: complete manual, publication-object and browser-free semantic
  report suites;
- 144 passed: the complete browser-free semantic report suite after the final
  canonical-first cover correction;
- 18 passed: the focused direction/persistence/AppTest nodes, including
  overlength project-load rejection and the calculated Detailing result card;
- 190 passed: programme-document and repository ASCII guards; and
- Ruff policy, strict owned-mypy policy, focused import ordering and
  `git diff --check` passed.

Three fresh Python processes used empty temporary autosave directories and
visited all five stages with no application exception. The descriptive outer
AppTest wall-time ranges were 4,314.154-4,578.896 ms for the first usable stage,
780.257-927.524 ms for Section, 502.931-697.251 ms for Material parameters,
490.287-717.208 ms for Loads and 541.235-640.036 ms for Project & report. The
corresponding in-app probe ranges were 1,230.894-1,513.520 ms,
397.715-503.042 ms, 136.118-208.797 ms, 122.904-153.429 ms and
171.412-215.619 ms. Each record contained exactly one finite, nonnegative
`pane_construction` phase and positive message counts.

The Section stage intentionally carried the existing custom point-grid payload
(2,024,291 measured bytes in each sample); the other warm stage payloads were
32,993 bytes or less except the first settings response. These observations are
diagnostic evidence, not release budgets or proof of browser interaction
latency.

Independent rebased-diff review found one publication ambiguity: the cover
initially showed an alias-only row, which could leave its longitudinal or
transverse meaning unstated when minimum reinforcement was disabled. The cover
now publishes one canonical-first `Modelled reinforcement direction` row, and
browser-free PDF-text regressions cover both an enabled calculation and the
minimum-check-off case.

The first exact-head GitHub gate, run `31345580007`, confirmed 3,013 passed,
one skipped, 91.34% coverage, all policy/static checks and the real report
render. It stopped only because the manual cover/contents crop still carried
its pre-PR-05 fingerprint. Evidence artifact `9047703619`, whose downloaded
ZIP independently matched GitHub's SHA-256 digest, contained the exact 47-page
manual. PDFium inspection found the cover, contents and `Page 1 of 47` footer
sharp, aligned and unclipped. The independently reproduced cover and footer
fingerprints are now pinned; the corrected exact head must pass the complete
gate and two-build unsigned-package reproducibility job before merge.

The first sandboxed pytest attempts encountered the known Python 3.13 Windows
temporary-directory ACL error before any test body ran. Identical commands on
verified-new external temporary roots produced the passing results above. No
local browser, JavaScript runtime, raster renderer or Windows package build was
launched. GitHub must record the exact candidate revision/tree and pass the
complete coverage, real report/manual render and unsigned Windows package
workflows on that same head before merge.
