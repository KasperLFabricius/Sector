# PR-08D.3a.1 CT-010a successful reinforcement-fatigue acceptance

This resliced matrix freezes only the unpublished successful reinforcement
fatigue evidence. Sector remains `0.91`. The retained invalid/applicability
member is explicitly deferred to PR-08D.3a.2.

| Family or invariant | Frozen acceptance |
| --- | --- |
| Applicability | Validate `fatigue_on`, `fatigue_check_steel` and `fatigue_check_concrete` as required exact built-in Booleans before dispatch. This slice exists only for an exact successful fatigue payload when both `fatigue_on` and `fatigue_check_steel` are true. Disabled, missing, concrete-only and retained-invalid candidates are inapplicable and cannot carry this family. The invalid branch is selected before any section/geometry traversal. |
| Inventory | Successful output is an exact built-in `dict` in the ordered `SUCCESS_KEYS` inventory. Missing, additional, reordered, differently typed or mapping-subclass payloads fail closed. Every reinforcement-owned field is exact replay. Concrete-owned values are excluded, while their recursive position, shape, cardinality and retained types remain pinned. |
| Input identity | Every applicable member seals raw controls/factors; spectrum rows including descriptions; complete section ring/bar/tendon geometry with original retained scalar types; concrete, bar, tendon, fatigue-detail, mild-material and prestress-material identities; element tables; and the retained analysis signature. Every identity leaf reaches its member final. |
| Matched-state proof | Join each assessment by spectrum position, bin position/name and solver element position to its authoritative retained `FatigueBinState`. Derive cycles, convergence, bond method/factor, long stress, fatigue-total stress, design fatigue-total stress and perfect-bond stress from that state. Independently reconstruct stress ranges, two-slope S-N branch/life, log-domain damage, proof-stress limit, absolute-stress utilisation, governing identities, convergence and PASS/FAIL. |
| Provenance | S-N nodes use the selected retained DS/EN 1992-1-1 edition. Mild proof-stress nodes cite 5.2.4 / 3.2; prestressing-tendon proof nodes cite 5.3.3 / 3.3.6 with distinct method identities. Input identity is input provenance; boundary, matched Elastic replay and aggregation are uncited project methods. |
| Aggregate closure | Every assessment contributes separate utilisation, convergence and PASS/FAIL evidence. Spectrum governing identities are reconstructed. Aggregate status depends on both all assessment utilisations and all convergence nodes; the final binds input identity, all raw factors, every assessment, every convergence, every spectrum governing identity, global utilisation and worst-first status. |
| Hostile closure | Reject stale seals, coherent reseals, output inventory drift, mapping subclasses, Boolean lookalikes, property/stress/bin/source/unit/axis/order/dependency/final tamper, geometry value/type substitutions, material/description substitutions, concrete sibling shape/type replacement, missing assessments and unrelated evidence on every inapplicable branch. |

Explicit exclusions: retained invalid-member evidence (PR-08D.3a.2), concrete
fatigue proof (CT-010b), CT-009/CT-009b, chord/off_util/biaxial and CT-002
sweep joins, UI/report/manual/publication/persistence/package/schema/workflow/
version changes, solver/formula changes, F-020, PR-07 removals, v0.93 work and
every rejected head.
