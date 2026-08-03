# PR-08D.1 CT-009 acceptance matrix

Status: frozen unpublished implementation slice.

Base: accepted `main` at `98a82b622d1ade333c04e36f3991664f07444c50`.

Application version: `0.91` (unchanged).

## Family boundary

CT-009 replays the already retained EN 1992-1-1:2004 crack-width response. It
applies only when all of these original inputs agree:

- analysis mode is exactly `Elastic` or `Both`;
- crack width is enabled by the exact Boolean `sls_cw`;
- `sls_edition` is exactly `2004`;
- `sls_dk_na` is an exact Boolean and agrees with the selected crack-code label;
- member type is exactly `Beam` or `Slab`.

The base branch publishes ordered long-term and short-term cases. The Danish NA
branch publishes ordered long-term fine, short-term fine, long-term coarse, and
short-term coarse cases. The aggregate is always last.

EN 1992-1-1:2023 refined and direct-tension mechanics are excluded from this
slice and remain CT-009b. The 2004 and 2023 families are not interchangeable.

## Original-input identity

The trace independently retains and closes:

- mode, opt-in, edition, crack-code label, Danish-NA selector, and member type;
- `fctm`, diameter override, mild-steel `k1`, tendon bond ratio, `ns`, `nl`,
  concrete modulus, and creep coefficient;
- all six signed long- and short-term actions;
- every outer and void vertex in exact order;
- every original bar and tendon x/y/area tuple in exact order;
- every element ID, kind, material ID, x/y duplicate, original area, diameter,
  and size mode;
- the exact selected concrete identity and concrete law;
- the exact selected mild and prestress catalogue ID, name, description, preset,
  curve, and active numerical law;
- the exact aligned per-element material law and its standard/project identity.

The fatigue-detail assignment is outside CT-009. Its field presence, position,
and retained text type are pinned, while its value is deliberately inert.

The immutable `Section` must match the original geometry exactly. Reinforcement
areas use the same construction path as `Section.from_polygon`:

`area_m2 = area_mm2 * MM2_TO_M2`

Division by one million is not substituted because it can change a valid custom
area by one binary64 unit. Retained SLS element rows are reconstructed from the
original mm2 tuples, so both template-derived and custom areas remain exact.

## Retained output inventory

The retained `elastic` mapping is reconstructed independently from original
inputs with the accepted low-level kernels. Its insertion order and every nested
mapping, sequence, leaf type, cardinality, and binary64 value are exact.

Core fields, in order:

`total`, `long`, `dif`, `rst1`, `max_conc`, `max_conc_xy`,
`max_conc_point`, `na_x`, `na_y`, `max_steel`, `max_steel_bar`,
`max_steel_type`, `max_steel_element`, `prestress`, `converged`,
`stress_plane`, `elements`, `concrete_corners`, `stress_outputs`.

Serviceability fields, in order:

`cracked`, `lambda_cr`, `sigma_ct`, `fctm`, `show_cw`, `props_un`,
`props_cr`, `crack`, `crack_short`.

Calculated metadata follows as `crack_code`, `crack_edition`, and
`crack_member`. The Danish branch then adds `crack_coarse` and
`crack_short_coarse`. `crack_output` is last.

Each crack result retains exactly:

`wk`, `sr_max`, `esm_ecm`, `sigma_s`, `rho_p_eff`, `ac_eff`, `hc_ef`,
`phi`, `cover`, `gov_bar`, `element_type`, `element_no`, `element_id`,
`coarse`, `edition`, `kw`, `k1_r`, `kfl`, `sr_max_geometric`, `candidates`.

Each ordered candidate retains exactly:

`element_type`, `element_no`, `element_id`, `x_mm`, `y_mm`, `area_mm2`,
`wk`, `sr_max`, `esm_ecm`, `sigma_s`, `rho_p_eff`, `ac_eff`, `hc_ef`,
`phi`, `cover`, `coarse`, `edition`, `kw`, `k1_r`, `kfl`,
`sr_max_geometric`.

The aggregate retains exactly `value`, `case`, `governing`, `unit`, and
`calculation_state`. No candidate-selected state, governing element, aggregate,
or verdict is trusted.

## Mechanics replay

The trace uses, without changing them:

- `solve_elastic_combined` for the retained long/short superposition;
- `analyse_cracking` for the sustained Stage I/Stage II path;
- `combined_cracking` for the peak cracking selector;
- `transformed_properties` for uncracked and governing cracked properties;
- `crack_width` for each long/short and fine/coarse case;
- the retained SLS serializers for element, corner, stress, and aggregate rows.

User normal force is tension-positive. It is negated once at the solver boundary.
The short-term width uses the retained combined total steel stress with locked
tendon prestress removed. Material alignment follows the actual selected
catalogue ID, never numerical-law equality.

## Source lifecycle

Local Design Basis sources only:

- `DS/EN 1992-1-1:2004 + A1:2014 + AC:2010`, clauses 7.3.2(3) and 7.3.4,
  equations (7.8), (7.9), (7.11), and (7.14), and Figure 7.1;
- `DS/EN 1992-1-1 DK NA:2024, revision 2024-02-01`, clauses 7.3.4(1)
  and 7.3.4(3), and Figure 7.100.

The retained elastic equilibrium, combined-creep superposition, aggregate
selection, and fixed-prestress replay remain transparent Sector project methods.
Project methods carry no invented standards citation.

## Result states

- Calculated: complete finite reconstruction; all ordered candidate and aggregate
  values are independently validated.
- Uncracked: one explicit undefined final; no fabricated crack width.
- No applicable tension candidate: one explicit undefined final; no fabricated
  crack width.
- Failed: one explicit failed final. Failure applicability and convergence are
  determined before parsing untrusted failure-only numerical fields. The payload
  shape, false convergence flag, and INVALID aggregate remain pinned.

Promotion from a failed or undefined state to a finite result must traverse the
complete finite reconstruction path.

## Explicit exclusions

This slice publishes no allowable crack width, exposure/durability limit,
utilisation, acceptance status, compliance verdict, or multidirectional crack
overlay. It changes no solver formula, UI, report, manual, persistence schema,
package, workflow, or publication wiring. Those remain assigned to their frozen
later slices, with consolidated activation and the full gate reserved for PR-08E.
