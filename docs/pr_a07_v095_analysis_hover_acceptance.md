# PR-A07 v0.95 analysis-hover acceptance

## Outcome and boundary

PR-A07 makes analysis figures explain the retained result at the hovered point.
Plastic M-M and N-M capacity curves show the capacity actions represented by
the selected curve vertex. Plastic and Elastic section-result figures show the
retained element identity, material, stress and strain instead of repeating
input geometry.

Section input and preview figures continue to show coordinates, area and
material assignment. This distinction is based on the figure's purpose, not on
the element type. Detailed result tables remain unchanged and retain geometry
beside the response values for direct checking.

This slice changes no solver, interpolation, capacity, stress, strain, action,
material law, persistence, schema, report, design basis, status or product
version. Hover text is derived only from values already retained for the
rendered result.

## Capacity-curve hover

- Every M-M capacity-boundary vertex shows retained `Mx,Rd` and `My,Rd` in kNm.
- Where a neutral-axis sweep angle is retained for that vertex, the same hover
  also shows that angle. No angle is reconstructed when it is unavailable.
- The capacity marker on an applied-action ray uses the same capacity labels;
  the applied marker remains explicitly labelled with `Mx,Ed` and `My,Ed`.
- Every N-M capacity-boundary and landmark point shows retained `NRd` in kN and
  the applicable retained `Mx,Rd` or `My,Rd` in kNm.
- An applied N-M marker remains explicitly labelled with `NEd` and `Mx,Ed` or
  `My,Ed`.
- Hover values are the plotted retained vertices. PR-A07 does not interpolate a
  new resistance or infer an uncalculated capacity between vertices.

## Section-result hover

- Plastic bar and tendon markers show stable element ID, material ID/name when
  retained, design stress and strain for the selected neutral-axis state.
- Elastic bar and tendon markers show stable element ID, material ID/name,
  retained total stress and retained strain for the selected Elastic action.
- Elastic concrete-corner markers show point/ring identity, retained concrete
  stress and retained strain.
- Analysis section hovers omit x/y coordinates and reinforcement area. The
  response tables continue to publish those fields.
- If optional material text is absent, the retained element identity and
  numerical response remain visible without inventing a material label.

## Input and preview preservation

- Section input, Quick Section and other geometry-preview figures keep their
  existing corner, bar and tendon coordinate hovers.
- Reinforcement preview hovers keep area and material-assignment information.
- Changing analysis hover semantics does not change labels, geometry, marker
  positions, colours, legends, selection or calculation state.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| A07-01 | M-M boundary has retained angle evidence | Hover shows `Mx,Rd`, `My,Rd`, units and the retained angle. |
| A07-02 | M-M boundary has no angle evidence | Hover shows both capacity moments and does not invent an angle. |
| A07-03 | Applied M-M ray has a capacity crossing | Capacity and applied markers are explicitly distinguished with Rd/Ed labels. |
| A07-04 | N-M capacity or landmark point is hovered | Hover shows retained `NRd` and the axis-specific retained moment capacity. |
| A07-05 | Applied N-M point is hovered | Hover shows `NEd` and the axis-specific applied moment. |
| A07-06 | Plastic result bar/tendon is hovered | ID, optional material, retained stress and strain are shown; geometry and area are absent. |
| A07-07 | Elastic result bar/tendon is hovered | ID, optional material, retained total stress and strain are shown; geometry and area are absent. |
| A07-08 | Elastic result concrete point is hovered | Point/ring identity and retained stress/strain are shown; coordinates are absent. |
| A07-09 | Section input or preview point is hovered | Existing coordinates, area and assignment context remain available. |
| A07-10 | Repository scope is inspected | No solver, result value, persistence, schema, report, design-basis, status or version change is included. |

## Focused verification

- Plotly trace tests pin exact capacity/applied labels, units, axes and optional
  neutral-axis evidence;
- section-figure tests pin the analysis-versus-input hover boundary for concrete,
  mild reinforcement and tendons;
- focused Streamlit tests pin Plastic and Elastic retained-response routing; and
- programme-contract and static release-blocker checks pin scope and identity.

The full suite, coverage, portable package and release qualification remain at
the governed G1/G2 gates.
