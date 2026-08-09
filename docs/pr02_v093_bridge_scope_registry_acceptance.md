# PR-02 Sector v0.93 bridge-scope and standards-registry acceptance

Status: candidate acceptance contract for the PR-02 branch. GitHub records the
eventual pull-request and squash identities; this document does not invent or
self-reference a commit that does not yet exist.

## Exact accepted base

- Repository revision: `2f4934ec7c212fd39da9e3f19ba02292b5213c46`
- Repository tree: `ce17dde757e7eae76d0fa39c103d20d2049de8bb`
- Programme branch: `codex/pr02-v093-bridge-scope-registry`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)

The base revision is the exact squash merge of PR-01. Its tree is identical to
the independently accepted PR-01 candidate tree.

## Frozen scope transition

PR-02 removes the complete runtime, project, Streamlit, result, manual, report,
fixture and example pipelines for the three retired semantic bridge workflows:

- tensile-region brittle Method B;
- box-wall shear/torsion; and
- web/flange minimum crack reinforcement.

All three required user-defined region, wall or component mapping. Sector no
longer accepts, stores, dispatches or publishes those mappings. The former core
and adapter paths remain only as strict-typed decommission markers because they
are part of the accepted non-shrinking mypy boundary; they expose no calculation
or adapter API. `app/bridge_inputs.py` is removed.

The corrected concrete-fatigue damage-sum route sourced from
DS/EN 1992-2:2005/AC:2008 Formula 6.106 remains. It consumes a user-supplied
section-action spectrum and is not a bridge design-basis selector or a claim of
traffic-model, dynamic, lane/track, owner-requirement or complete bridge-fatigue
coverage.

## Schema 24 and live-state boundary

Project schema 24 is current-only. It contains none of `bridge_standard`,
`bridge_brittle_base`, `bridge_box_walls_base` or
`bridge_minimum_crack_base`. A schema-23 project fails before table, scalar,
hash or provenance interpretation with the exact current-schema message. A
coherently rehashed schema-24 payload containing any retired table or scalar
fails as an unknown current-schema input. No migration or silent field drop is
provided by the reader.

One pure once-only session transition runs before autosave or pending-project
restore. It removes the retired direct/widget/durable/pending state and
invalidates the whole schema-23 latest-input, result, signature, snapshot,
calculation-record, provenance, report, manual and figure-cache evidence bundle.
The marker `_sector_v093_bridge_state_purged_v1` is written last. An uploaded or
autosaved schema-23 project is not rewritten; it reaches the same explicit
loader rejection.

## Capability-scoped standard identity

The typed registry has exactly these stable selectable basis keys:

1. `ec2_1_1_first_gen_base`
2. `ec2_1_1_first_gen_dk_na_2024`
3. `ec2_1_1_2023_published`

PR-02 binds only reinforcement fatigue, concrete equivalent fatigue and
concrete damage-sum fatigue. The Streamlit selector persists a stable key;
labels never dispatch a solver. Unknown keys, display labels, substring matches
and whitespace variants fail closed. The 2023 basis is labelled as
DS/EN 1992-1-1:2023, requires project adoption and applies no Danish National
Annex. Its normative Annex K is standards context, not a Sector capability.

The first-generation DK key records the stated Danish project basis but does
not silently alter a fatigue equation or factor. The implemented first-
generation routes are numerically identical; every relevant factor remains an
explicit user input and the calculated evidence says so.

DS/EN 1992-2 DK NA:2015 is context-only and has no selector or binding. There is
no EN or DS/EN 1992-2:2023 identity, complete-bridge capability, component-
mapping capability or confinement capability. Relevant manual/report scopes
state that the 2023 confinement enhancement is not included or assessed.

Calculated fatigue evidence carries the stable basis key, human-readable label,
basis disclosure, solver edition, source and per-capability disclosure. A
project-defined concrete Miner relation remains explicitly uncited and is not
published as Formula 6.106 or as a registered standard capability.

## Publication and example boundary

The Bridge Calculations view, inputs, report chapter and manual worked example
are removed. A hot-reload alias sends an old view value to Results Overview and
does not expose a selectable legacy route. The complete reference project is
regenerated as schema 24 without bridge mappings and retains its independent
plastic, elastic, fatigue, detailing, shear, torsion and combined checks.

The manual publication-object contract intentionally drops the removed Method B
table and re-pins the changed workspace-view table. Historical v0.92 acceptance
records and their truthful descriptions remain unchanged.

## Identity and exclusions

Sector remains the product name and remains a transparent calculation tool.
This PR does not add certification, approval, a global compliance conclusion,
component inference or confinement. It does not change the numerical plastic,
elastic, detailing, shear, torsion, combined or fatigue kernels. It does not
change the Windows packaging/signing policy or create a release.

The runtime version remains 0.92 during programme development. The version and
all Windows release resources move to 0.93 only in PR-09 after the complete
programme gate. Released v0.92 projects used schema 23; the in-development v0.93
line uses schema 24.

## Verification evidence

The final local affected-suite gate on this candidate produced:

- 399 passed: project schema, standards registry, session transition, bridge
  decommissioning and absence, fatigue adapter/input/presentation, code,
  documentation, ASCII, version and strict-mypy policy tests;
- 213 passed and 1 skipped: complete semantic report, manual,
  publication-object, reference-example and result-presentation suites; and
- 15 passed: focused Streamlit hot-reload, project/fatigue restoration,
  configured calculation, provenance and complete lazy-startup regressions;
  and
- 3 passed plus standalone fixture generation: the real rendered report and
  manual gates produced 55 and 45 visually reviewed pages, respectively.

The Ruff policy executor, strict-mypy policy executor and `git diff --check`
also passed. An attempted full 216-test local Streamlit/lazy-startup run remained
CPU-active without a failure trace until the one-hour command wrapper ended; no
pytest summary was recoverable, so that attempt is not counted as evidence and
was not repeated. The focused affected UI gate above is green, while the full
repository and unsigned Windows QA-package workflows remain mandatory on the
exact committed GitHub head. Unrelated numerical solver and packaging suites
were not duplicated locally because this slice does not change those kernels or
the package boundary.
