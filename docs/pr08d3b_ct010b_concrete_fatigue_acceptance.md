# PR-08D.3b CT-010b concrete-fatigue acceptance

This candidate starts from accepted `main` after PR #278. It extends CT-010
without changing the fatigue solver, accepted material laws, search algorithm,
limits or verdicts. Sector remains `0.91`.

| Boundary | Frozen acceptance |
| --- | --- |
| Applicability | Exact built-in dispatch Booleans control disabled, absent, concrete-only, reinforcement-only and mixed branches. A genuine concrete-only invalid payload publishes one calculation-free failed member. |
| Identity and joins | Complete typed original input, geometry, selected concrete/material/catalog identity, spectrum/bin descriptions and order, exact adapter signature and aligned preparation are sealed. Every spectrum, state, fibre and bin is joined by exact position and retained identity. |
| Strength | The selected concrete properties reconstruct `fcd,fat`. The 2005 route cites DS/EN 1992-1-1:2005+A1:2014 6.8.7 Formula (6.76); the 2023 route cites DS/EN 1992-1-1:2023 Formula (10.5). Age, `beta_cc(t0)`, factors and edition-specific operands remain explicit. |
| Fixed-fibre mechanics | Raw long/total and action-level design compression are reconstructed from retained Elastic planes at every exact concrete fibre. Each bin retains min/max compression, ratio, normalized levels, life/log-life, Miner damage or equivalent utilisation, direct stress utilisation and convergence. Damage is summed only at one fixed fibre. |
| Method provenance | Standard Miner cites corrected DS/EN 1992-2:2005/AC:2008 6.106 or DS/EN 1992-1-1:2023 E.5.3 Formulae (E.7)-(E.8). Damage-equivalent cites 6.8.7 Formulae (6.72)-(6.75) or E.4.3 Formula (E.2). User-defined Miner is project-owned and uncited in both adapter and trace. |
| Bounded search | The accepted adaptive kernel is rerun from retained solver intermediates. Method defaults, best point/objective, conservative upper bound, divisions, box/point counts, absolute/relative gap and convergence are all retained. The upper bound governs utilisation and PASS. |
| Aggregates | Per-fibre selectors and verdicts, concrete-spectrum governing fibre/utilisation/convergence/PASS, mixed spectrum values and the global governing spectrum/utilisation/convergence/PASS are independently reconstructed. PASS remains a genuine implemented demand/resistance result, never a compliance statement. |
| Anti-regression | The accepted reinforcement-only bundle remains byte-identical. Parameterized hostile probes cover every concrete bin, fibre and search output leaf; cardinality/order/type, solver-plane contradiction, aggregate masking, stale/coherent reseal and failed-to-success promotion fail closed. |

Excluded: chord/off-utilisation/biaxial and the CT-002 join; publication,
Streamlit, report, manual, persistence, package and workflow activation; solver
or formula changes; PR-07 removals; F-020; v0.93 work and rejected heads.
