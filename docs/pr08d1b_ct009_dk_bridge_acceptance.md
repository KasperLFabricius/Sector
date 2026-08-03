# PR-08D.1b CT-009 2004 DK and bridge route acceptance

This slice extends the accepted CT-009 base replay from exact `main`. It uses the
retained application and low-level mechanics, accepted tests, and local Design
Basis documents. It does not use any rejected head. Sector remains `0.91`.

| Boundary | Frozen acceptance |
| --- | --- |
| Exact routes | The four active 2004 tuples are: `EN 1992-1-1:2005` without DK, `DS/EN 1992-1-1 + DK NA` with DK, `DS/EN 1992-2:2005 + AC:2008` without DK, and `DS/EN 1992-2 DK NA:2015` with DK. Selector types and tuple relationships are exact. Other type-valid tuples are inactive. |
| Member and tendon controls | `sls_member` is exact and limited to `Beam` or `Slab` on DK routes. It is present and type-pinned but value-inert on non-DK routes. `sls_tendon_xi` is present and built-in-numeric-type-pinned but value-inert for every 2004 route. Tendon presence independently activates the DK `(h-x)/3` fine-system term. |
| Members and order | Building and bridge base routes emit long-term fine, short-term fine, then aggregate. Building and bridge DK routes emit long-term fine, short-term fine, long-term coarse, short-term coarse, then aggregate. Failure emits one failed member. Insertion order and cardinality are exact. |
| Mechanics | Every route independently reconstructs combined elastic response, sustained and peak cracking, governing cracked state, transformed properties, and candidate crack widths through the accepted low-level kernels. DK fine replay applies the member/prestress effective-height rule and cover-dependent `k3`. DK coarse replay uses the centroid-matched effective area and the one-half crack-width factor. No second mechanics engine is introduced. |
| DK publication shape | Successful cracked DK output requires the exact ordered `crack`, `crack_short`, route identity, member identity, `crack_coarse`, `crack_short_coarse`, and four-label aggregate. Every public leaf and every internal used candidate quantity reaches its own final. Unreinforced and uncracked cases are explicit undefined results. |
| Bridge routing | Bridge base replay adds the exact `DS/EN 1992-2:2005 + AC:2008` 7.3.4(101) route to the retained EN 1992-1-1 method. Bridge DK replay additionally binds the `DS/EN 1992-2 DK NA:2015` 7.3.4(101) no-national-choice identity and the retained DK mechanics route. Numerically identical building/bridge results remain source- and identity-distinct. |
| Sources | Base equations cite local `DS/EN 1992-1-1:2004 + A1:2014 + AC:2010`. DK changes cite local `DS/EN 1992-1-1 DK NA:2024 rev. 2024-02-01`, clauses 7.3.2(3), 7.3.4(1), and 7.3.4(3). Bridge routing cites local `DS/EN 1992-2:2005 + AC:2008` and `DS/EN 1992-2 DK NA:2015`, clause 7.3.4(101). Route sources reach every final. Project/input replay boundaries remain uncited. |
| Output closure | Successful crack-owned inventory and values are exact. Complete recursive key/order/cardinality/container/leaf-type identity of non-owned siblings remains pinned while values stay inert. Failure applicability and convergence are established before failure-only numerics; exact INVALID aggregate and route structure are retained without a fabricated value or verdict. |
| Hostile closure | Parameterized tests cover every route, every owned public leaf, missing/unknown/reordered owned surfaces, source reachability, route identity, member identity, DK formulas, same-mechanics/different-route separation, inert 2004 tendon ratio, minimal DK failure, and coherent trace reseals. Existing base regressions remain green. |

Explicit exclusions: EN 1992-1-1:2023 refined/direct-tension replay, concrete
fatigue, chord/off-util/biaxial and CT-002 joins, trace activation, UI, report,
manual, persistence, packaging, workflow, version changes, solver/formula
changes, PR-07 removals, F-020, v0.93, and all rejected heads.
