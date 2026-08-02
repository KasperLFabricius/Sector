# PR-08D.3a CT-010a acceptance (reinforcement fatigue)

This matrix freezes the reinforcement-fatigue slice from retained main
mechanics. Sector remains `0.91`. It adds registry
`sector-ct-010-fatigue-v1`, family `ct-010-fatigue`; concrete fatigue is the
named CT-010b sibling for PR-08D.3b. CT-009 remains PR-08D.1.

| Family or invariant | Frozen acceptance |
| --- | --- |
| Applicability | No family when fatigue is off, the section is absent, or a retained section error is present. Retained fatigue preflight errors publish one failed invalid member before candidate numerics are read. A valid reinforcement check publishes one member per spectrum/element plus one reinforcement-output member. A valid concrete-only check publishes no CT-010a family. |
| Replay | Exact replay through `fatigue_analysis.validation_errors`, `invalid_result`, `prepare` and `run_analysis`, including the retained elastic solves, two-slope S-N law, Palmgren-Miner sum, yield screen, governing selections and PASS/FAIL decisions. No solver or formula changes. |
| Edition boundary | Finite standard evidence accepts only the three exact retained strings: `DS/EN 1992-1-1:2005`, `DS/EN 1992-1-1:2005 + DK NA:2024`, and `DS/EN 1992-1-1:2023`. Integer or substring aliases accepted by the application adapter fail closed at the trace reader. Invalid preflight states remain replayable even with a malformed selector. |
| Candidate closure | Valid and invalid payload keys, order, cardinality, dataclass fields and retained exact types are pinned. Candidate values owned by CT-010a replay exactly. Concrete method/parameter siblings and concrete fields inside retained spectrum/bin dataclasses keep their required presence, position and retained type, while their values remain outside this slice. Incompatible mapping/list replacements fail closed. |
| Complete input identity | The normalised-input node directly binds every spectrum name, bin name and published bin description; all six action components and cycles for every bin; factors, mesh controls, element/detail identities; the complete immutable section-ring/bar/tendon geometry vector; and the complete concrete/bar/tendon material-law vector. Concrete material identity, every assigned material ID and every detail ID are sealed. Every leaf reaches its member final. |
| Materials | Catalog-backed laws require exact complete catalog/assignment identity and preserve accepted standard or project provenance. A valid legacy/headless input with explicit `bar_materials`/`tendon_materials` and no corresponding catalog is accepted with exact aligned element/material identities and uncited `SOURCE_PROJECT` provenance. A present malformed catalog fails closed. Published 2023 material-law provenance remains rejected until its mechanics are implemented; this does not prevent a 2023 fatigue-detail edition from using an accepted older or uncited project material law. |
| Sources | Edition-specific S-N, Miner and mixed-bond steps carry the frozen DS/EN 1992 citations; input, adapter, engine, verdict and catalog-free project-law values remain explicitly uncited project/input evidence. No value is relabelled as standard-derived. |
| Verdicts | Element finals bind retained convergence, damage and yield screens. The reinforcement-output final genuinely aggregates all retained reinforcement members; joint concrete/reinforcement output does not fabricate the later concrete-family utilisation. Non-finite retained quantities use explicit trace states, never replacement numerics. |
| Integrity | Exact registry audit plus full bundle reconstruction rejects stale hashes, resealed value/source/unit/axis/order changes, identity substitutions and removed or redirected dependency edges. |

Hard exclusions: concrete-fatigue values and verdicts (PR-08D.3b), crack width
(PR-08D.1/CT-009 and PR-08D.2/CT-009b), chord/off-util/biaxial join,
publication activation, UI/report/manual/persistence/package/schema/workflow/
version changes, F-020, and every rejected-head implementation.
