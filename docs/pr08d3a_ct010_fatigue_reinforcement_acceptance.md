# PR-08D.3a CT-010a acceptance (reinforcement fatigue)

This slice freezes retained reinforcement-fatigue mechanics in registry
`sector-ct-010-fatigue-v1`, family `ct-010-fatigue`. Sector remains `0.91`.
Concrete fatigue is the later CT-010b sibling; CT-009 is PR-08D.1.

| Invariant | Frozen acceptance |
| --- | --- |
| Applicability | Fatigue off, absent section, and retained section errors publish no family. Retained fatigue-preflight errors publish one failed invalid member before candidate numerics are read. A valid reinforcement check publishes one member per spectrum/element and a reinforcement-output member; concrete-only publishes no CT-010a family. |
| Replay | Exact retained `validation_errors`/`invalid_result`/`prepare`/`run_analysis` replay, including elastic solves, two-slope S-N life, Palmgren-Miner damage, yield screen, governing selection, convergence and PASS/FAIL. No mechanics change. |
| Reader boundary | Finite evidence accepts only the three exact retained edition strings. Integer and substring aliases fail closed. Valid/invalid key order, dataclass inventories and exact retained types are pinned. Concrete method/parameter and nested concrete-result siblings retain presence, position and type while their values remain CT-010b scope. |
| Complete identity | Every spectrum/bin identity and published bin description, cycle count, six action components, factor, mesh control, element/detail/material identity, complete immutable section geometry and complete concrete/bar/tendon material law reaches its member final. A changed same-law concrete or reinforcement material ID reseals the bundle. |
| Optional concrete law | Reinforcement-only/headless inputs legitimately may omit `concrete`; the trace binds that absence explicitly through `input-concrete-material-present = 0`. When concrete is present, its exact identity, law and provenance join the material vector. Concrete checks still fail through retained preflight if their required law is absent. |
| Material provenance | Catalog-backed explicit laws require exact aligned catalogs and assignments. Valid catalog-free explicit bar/tendon laws are exact aligned uncited project evidence. A present malformed catalog fails closed. Published 2023 material-law provenance remains excluded until implemented, independently of the selected fatigue-detail edition. |
| Standards evidence | Edition-specific S-N, Miner and mixed-bond steps carry the frozen DS/EN 1992 citations. Input, adapter, engine, verdict and catalog-free laws remain explicitly input/project evidence with no fabricated citation. |
| Integrity and verdicts | Exact registry audit and full reconstruction reject stale hashes, value/source/unit/axis/order reseals, identity substitutions and dependency changes. Element and output finals are genuine retained aggregations. Joint output does not fabricate concrete utilisation; non-finite retained quantities use explicit trace states. |

Hard exclusions: CT-010b concrete-fatigue values/verdicts, CT-009/CT-009b,
chord/off-util/biaxial join, publication activation, UI/report/manual/
persistence/package/schema/workflow/version changes, F-020, and all
rejected-head implementations.
