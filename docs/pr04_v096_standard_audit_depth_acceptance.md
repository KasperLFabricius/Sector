# PR-04 v0.96 Standard and Audit depth acceptance

## Outcome and boundary

PR-04 makes Standard the ordinary calculation report and Audit the exhaustive
retained-evidence report. Both consume the same completed result payload.
Profile selection does not run a solver, rank a result, change a status, alter
rounding or invent missing evidence.

This slice changes report composition, profile wording and focused publication
tests only. It does not change Brief, engineering calculations, input values,
applicability, project schema, product version, Streamlit result views or the
package surface.

## Standard contract

Standard retains:

- complete used geometry, material, assignment, action and active-setting
  inputs;
- the governing Results overview and compact non-governing requested-result
  register;
- one preselected governing or diagnostic chapter for each active calculation
  family;
- the governing demand, resistance, utilisation or calculated output and its
  status, units and source;
- the symbolic relation, governing numerical substitution and result needed to
  reproduce each published worked calculation; and
- governing element, direction, branch and action-set identity.

Standard does not reproduce a complete search or candidate population merely
because it was retained by the solver. Its omission wording must say that
exhaustive candidate, trace, branch, internal-key and provenance evidence is
available in Audit.

## Audit-only population evidence

Audit retains everything published by Standard plus complete retained
population evidence, in original order, including when available:

- all M-M neutral-axis sweep rows and numerical N-M boundary points;
- all ultimate-curvature candidates, with the retained selected marker;
- every eligible clear-spacing pair;
- every reinforcement element and concrete fibre considered in the selected
  fatigue spectrum;
- all fatigue-bin state rows, crack-width candidates and elastic solver-state
  ledgers;
- additional retained shear-torsion subcheck chapters;
- internal `EQ-*` identities, theory context, complete source inventories,
  hashes and the QA appendix.

An Audit-only population table is not a second calculation and cannot replace
the retained governing identity used by Standard.

## Shared engineering identity

For a single completed payload, Standard and Audit must publish identical:

- effective used inputs;
- governing and non-governing result rows;
- governing case, direction, element, fibre, branch and candidate identity;
- numerical engineering values, display precision, units, statuses, warnings
  and source references; and
- governing symbolic expressions, substitutions and results.

Diagnostic chapters remain visible in Standard when the governing calculation
is invalid or not assessable. Figures remain a separate export choice and this
slice does not alter which figure a calculation chapter requests.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| SA96-01 | Standard is generated | Complete used inputs, governing overview, compact non-governing register and one governing worked chapter per active family remain. |
| SA96-02 | Plastic result retains many neutral-axis angles | Standard keeps the summary, plot contract and selected worked calculation; Audit alone lists the full sweep. |
| SA96-03 | N-M interaction retains numerical boundary points | Both profiles retain the result/figure contract; Audit alone lists every boundary point. |
| SA96-04 | Plastic worked point retains several curvature candidates | Both profiles calculate from the retained selected candidate; Audit alone lists the full candidate population. |
| SA96-05 | Clear-spacing result retains several eligible pairs | Standard publishes the governing pair only; Audit publishes every pair in retained order. |
| SA96-06 | Fatigue spectrum retains several reinforcement elements or concrete fibres | Standard publishes the retained governing element/fibre row and worked calculation; Audit publishes the complete population. |
| SA96-07 | Crack candidates or elastic solver-state ledgers exist | They remain Audit-only; the Standard governing crack/elastic calculation remains. |
| SA96-08 | Governing values and sources are compared across profiles | They are identical; no profile-side calculation or ranking occurs. |
| SA96-09 | Internal equation keys, theory/source inventories and QA appendix are inspected | They remain Audit-only. |
| SA96-10 | Profile descriptions are inspected | Standard says one governing worked calculation per active family; Audit says complete candidates, branches, substitutions and provenance. |
| SA96-11 | Repository scope is inspected | Brief, solvers, schema, product version and package surface are unchanged. |

## Focused verification

- cross-profile extracted-text and publication-object inventories;
- direct retained-order tests for spacing, Plastic and fatigue populations;
- governing equation/value/source equality checks;
- existing report-profile, equation-layout, manual and version guards; and
- one no-figure Standard/Audit render comparison.

Full real-figure, every-page raster, complete-repository and package
qualification remains at G1 and G2.
