# PR-08D.1a CT-009 base crack-width acceptance matrix

## Frozen boundary

| Item | Frozen acceptance |
|---|---|
| Base | Exact accepted `main` `98a82b622d1ade333c04e36f3991664f07444c50`; version `0.91`. |
| Family | CT-009, EN 1992-1-1:2004 base crack-width replay only. |
| Selector | Active only for `mode in {Elastic, Both}`, `sls_cw=true`, `sls_code=EN 1992-1-1:2005`, `sls_edition=2004`, and `sls_dk_na=false`. A missing section is inactive; an active valid section requires the retained `elastic` result. |
| Members | Exact order: long-term fine, short-term fine, aggregate. Case, branch, code, edition, direction, system, context, and member cardinality are explicit axes. |
| Mechanics | Independent replay through accepted low-level elastic, cracking, transformed-property, crack-width, and aggregate kernels. Sustained action uses `n_l` and `k_t=0.4`; peak/short action uses the combined-creep state with `n_s` and `k_t=0.6`. The smaller first-cracking factor selects the retained cracked state, with sustained action winning ties. Locked tendon prestress is removed from the short-term load-induced crack stress. |
| Inputs | Exact typed/order/cardinality/float-bit identities for raw and resolved geometry; concrete, mild, and prestress laws; concrete identity when present; complete aligned material catalogues and descriptions; material assignments; actions; modular ratios; crack controls; and selected method identity. Raw polygon, raw reinforcement, element records, and `Section` geometry must align before replay. `Area` and `Diameter` sizing require their derived circular duplicate to align; positive-finite `Independent` sizing preserves area for stiffness and diameter separately for crack geometry. `n_l` and `n_s` must match `E_c` and creep. |
| Excluded siblings | `fatigue_detail_id` values, DK-only `sls_member` values, and 2023-only `sls_tendon_xi` values are inert. Their presence, position, current-schema container/leaf type, and surrounding record identity remain pinned. |
| Retained outputs | Exact owned order and values: `converged`, `cracked`, `lambda_cr`, `sigma_ct`, `fctm`, `show_cw`, `props_un`, `props_cr`, `crack`, `crack_short`; on calculated branches `crack_code`, `crack_edition`, `crack_member`; then `crack_output`. Missing, reordered, type-replaced, unknown `crack*`, stale coarse, unknown `props_*`, and nested candidate mutations are rejected. |
| Candidate identity | Every candidate retains element type/number/ID, coordinate, area, stress, effective area/height/reinforcement components, reinforcement ratio, diameter, cover, strain difference, spacing branch, categorical method identity, and crack width. Every leaf reaches the governing final. |
| Units | Actions: kN/kNm. Solver concrete-reference plane: `q0` in kN/m2 and `qx`,`qy` in kN/m3. Physical stress: MPa. Strain: 1. Geometry: m, mm, m2, mm2. Transformed second moments: m4. Crack width: mm. |
| Result states | Calculated finite/positive-infinite values are explicit. Uncracked/unsupported case results are `undefined` with no fabricated crack width. Solver failure is `failed`, requires the exact ordered five-field `INVALID` `crack_output`, and does not traverse failure-only candidate numerical values. |
| Verdict semantics | No crack-width limit, resistance, utilisation, compliance state, or engineering verdict is created. The retained aggregate is a demand/output selection only. |

## Source lifecycle

All standard leaves use the selected local current building document identity
`DS/EN 1992-1-1:2004 + A1:2014 + AC:2010`:

- 7.3.2(3), Figure 7.1 and the effective tension-height definition;
- 7.3.4(1), Expression (7.8), crack width;
- 7.3.4(2), Expression (7.9), mean strain difference;
- 7.3.4(3), Expression (7.11), close-centre spacing;
- 7.3.4(4), Expression (7.14), wide spacing.

Geometry clipping, solver reconstruction, categorical boundary sealing, and
governing selection are explicit uncited project methods. No DK NA, EN 1992-2,
or EN 1992-1-1:2023 citation is attached to this family.

## Failure-first and adversarial matrix

- Applicability and original-input type/finiteness/sign/duplicate consistency are
  determined before untrusted candidate numerical leaves are used.
- Every owned top-level output, transformed-property leaf, crack-result leaf,
  candidate leaf, and aggregate leaf is deletion-tested.
- Record/catalogue key order, element container type, unknown record siblings,
  stale duplicate geometry, concrete identity, and published catalogue
  descriptions are independently mutation-tested.
- Coherently resealed trace tampering is rejected by reconstruction from original
  inputs and retained outputs.
- Real application payloads cover ordinary reinforcement and mixed mild/tendon
  sections.

## Explicit exclusions

- Danish National Annex fine/coarse mechanics and building-source overrides;
- EN 1992-2 base/DK source routing;
- EN 1992-1-1:2023 refined and direct-tension mechanics;
- crack limits, exposure/durability acceptance, utilisation, and verdicts;
- UI/report/publication wiring, which belongs to PR-08E;
- shear, torsion, detailing, fatigue, and deferred v0.93 work.
