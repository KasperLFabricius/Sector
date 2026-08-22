# PR-03 v0.96 Brief report acceptance

## Outcome and boundary

PR-03 defines Brief by information depth rather than page count. Brief remains
independently readable: it publishes calculation identity, selected basis,
complete effective inputs for every active result it reports, governing results
and concise warnings or limitations. It is not a worked calculation report.

This slice changes report composition and wording only. It does not change a
solver, input value, applicability decision, status, governing selection,
project schema, product version, Standard/Audit depth or package surface.

## Required Brief content

Brief retains:

- project, tool, source-revision and calculation-state identity;
- selected design basis and methods;
- the complete effective section geometry, reinforcement and tendon inputs used
  by its reported results;
- the complete effective assigned material values used by those results;
- every named active action set and all of its action components;
- every active analysis, crack, detailing, shear, torsion, combined and fatigue
  setting needed to reproduce a reported result;
- one governing retained row per semantic check type, with governing case or
  direction, numerical result, criterion and status; and
- active warnings and concise scope limitations.

Inactive or unused inputs may be omitted. An input is not omitted merely because
its value is a default or because it is repeated across active action sets.

## Excluded depth

Brief does not publish:

- substituted equations, derivations or a worked result chain;
- candidate searches, branch inventories or per-angle/per-element traces;
- non-governing load-case or fatigue-spectrum result registers;
- selected-"worked example" tables or wording that promises such examples;
- exhaustive hashes, equation inventories, implementation theory or complete
  provenance; or
- a page-count target or visual exception process.

Standard and Audit own deeper calculation evidence. The omission of derivations
does not permit the omission of effective inputs or governing conclusions.

## Figure contract

Figures remain an independent export choice. With figures disabled, Brief
exports none and does not start the figure service. With figures enabled:

- the selected governing Plastic case contributes one M-M capacity/interaction
  figure when a retained Plastic result exists;
- the selected governing Elastic case contributes one strain/element-response
  figure when the retained data support it;
- each figure caption identifies its governing action set; and
- no geometry preview, material-law plot, secondary N-M plot, detailing,
  shear/torsion/combined diagram or decorative figure is included.

Brief therefore contains zero, one or two figures depending on active retained
results and the export choice. The report never ranks or recalculates a figure
case during publication.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| B96-01 | Brief has active Plastic and Elastic results | Complete effective geometry, materials, actions and active settings remain present. |
| B96-02 | An inactive setting is present in the input payload | It may be omitted and is not presented as active. |
| B96-03 | Brief is generated | No wording promises a governing result chain or selected worked examples. |
| B96-04 | Multiple result rows/cases are retained | Only the semantic governing rows are conclusions; the non-governing register is absent. |
| B96-05 | Candidate, substitution and branch evidence exists | It is absent from Brief and remains available to deeper profiles. |
| B96-06 | Figures are disabled | No figure is requested and no image service is started. |
| B96-07 | Figures are enabled with selected Plastic and Elastic cases | Exactly one selected Plastic and one selected Elastic key figure is requested. |
| B96-08 | A selected result or required plot payload is absent | Its figure is omitted without inventing or ranking a replacement. |
| B96-09 | Geometry/material/secondary plot builders are instrumented | None is requested by Brief. |
| B96-10 | Profile policy is inspected | Brief has no hard or target page limit and no page-target exception flags. |
| B96-11 | Repository scope is inspected | Standard/Audit policies, solvers, schema and product version remain unchanged. |

## Focused verification

- cross-profile profile-policy and wording tests;
- Brief PDF extracted-text inventories for required inputs and prohibited depth;
- direct figure-selection tests using retained case identities and forbidden
  secondary builders;
- figures-disabled no-browser checks; and
- report, manual, version and programme guards.

Full publication/raster and package qualification remains at G1 and G2.
