# Sector 0.96.5 manual revision plan

Status: the expanded revision produces a 143-page manual. The source and rendered
review records close the planned content, notation, language and figure changes.
Publication requires final candidate approval, full validation and a matching
executable package.

## Review basis and conclusion

The review covers the manual source, numerical core, application controls,
publication renderers and the existing 89-page PDF. All eight page contact sheets
were inspected. Representative dense pages were also inspected at reading size.
An independent agent reviewed coverage and technical consistency against the code.
Its audit is retained in `output/v0965-qa/holistic-independent-audit.md` outside
the source checkout.

The reviewed source baseline is
`c942454722cdd4853578e4e9d9e95e6efb2f9b64`. Its earlier review covered a narrower
scope. It is not the release candidate for this expanded revision.

A substantial rewrite of the structure and explanatory prose is justified.
The manual contains useful equations, examples, field definitions and result
statuses. However, the reader must assemble a complete procedure from separated
chapters. Additional paragraphs alone would preserve that problem.

The revision must support three tasks:

1. Complete a calculation and preserve its inputs and report.
2. Understand each input, result, criterion and method selection.
3. Reproduce the elastic and plastic calculations without reading program code.

## Findings and planned corrections

Priorities describe the effect on this manual revision. P1 identifies a technical
contradiction. P2 identifies missing or misleading guidance. P3 identifies a
presentation or navigation improvement.

| ID | Priority | Verified finding | Planned correction |
| --- | --- | --- | --- |
| M01 | P1 | The equilibrium summary uses a different plastic axial sign and elastic moment target from the detailed methods (`manual.py`, Equilibrium check). | Define public and internal signs once. Use the same residual definitions throughout. Add a nonzero axial-force example. |
| M02 | P2 | Part A assumes an application that is already running. | Add portable extraction, startup, browser prerequisite, shutdown and update instructions from verified package behaviour. |
| M03 | P2 | The introduction does not establish the intended reader or required project inputs. | State audience, prior engineering knowledge, supplied inputs, derived quantities and calculation scope. |
| M04 | P2 | Quick start lists screens but supplies no complete input schedule or expected outputs. | Replace it with a reproducible first calculation, including save, reopen, recalculate and report generation. |
| M05 | P2 | The opening feature list omits N-M, directional shear, torsion, combined checks and transverse detailing. | Add a complete capability map with prerequisites, outputs and destinations. |
| M06 | P2 | The introductory standards note singles out 2023. | Identify all three available design bases and show availability by calculation capability. Explain independent selections and the combined-mode lock. |
| M07 | P2 | Input settings mix operating instructions, long derivations and detailed edition exceptions. | Keep control meanings and selection consequences in the operating reference. Put derivations in the corresponding method chapter. |
| M08 | P2 | Detailing interrupts the explanation of the two core solvers. | Group geometry, conventions, materials and the core solvers. Place dependent checks after their prerequisites. |
| M09 | P2 | The parent shear chapter says 'without shear reinforcement' but also contains the linked method. | Use 'Shear resistance' with explicit subsections for both routes, directions and method choices. |
| M10 | P2 | N-M is described as another presentation of the fixed-N sweep. The application performs additional axial sweeps at fixed orientations. | Explain its enabling control, axial sampling, retained orientations, plotted components and asymmetric-section interpretation. |
| M11 | P2 | Local workflow descriptions can omit Calculate. Dedicated shear, torsion and combined workflows are missing. | Make each procedure usable from a direct link, with prerequisites, action, Calculate, result location and expected state. |
| M12 | P2 | The elastic example gives moduli in MPa while the input fields use GPa. | Give calculation values and exact application entries in separate columns. Apply this approach to strain fractions and per mille. |
| M13 | P2 | General section reproduction requires polygon clipping and six integrals whose arithmetic is omitted. | Add edge intersections, signed polygon sums, hole subtraction and a numerical clipped-section example. |
| M14 | P2 | The elastic matrix is described without a complete substituted iteration. | Show initialization, matrix assembly, reference plane, compressed polygon, resultants, residual, correction and stopping test. |
| M15 | P2 | Plastic grouped resultants conceal the individual band operands and depth search. | Add a bisection trace, one complete band calculation, plateau calculation and element stress/force/moment rows. |
| M16 | P2 | Duration combination gives one bar's values but omits the complete retained force vector. | Publish every element's retained stress, neutralising resultants, adjusted target, both solves and TOTAL/LONG/DIF/RST1 reconstruction. |
| M17 | P2 | The tendon law is represented as an unspecified function, while several material curves are selectable. | Supply a material-law reference for each selectable curve family, parameters, branches, factors and strain units. Include a complete prestress example. |
| M18 | P2 | Literal carets, plain subscripts and unit powers occur in prose and tables. | Audit all mathematical text, headings, captions and axes. Use one notation policy in all three publication formats. |
| M19 | P2 | Project preservation and recovery guidance is brief. | Explain saved inputs, recalculation, autosave, issued PDF, application version and bounded compatibility guidance. |
| M20 | P2 | Several troubleshooting entries only direct the reader back to an error message. | Add concrete checks for startup, geometry, material assignment, unreachable axial force, convergence and figure export. |
| M21 | P3 | Most result views have descriptions but no worked interpretation. | Trace one named case from summary through governing component to detailed output and report. Explain each utilization denominator. |
| M22 | P3 | Dense prose combines conditions, instructions and exceptions in one paragraph. | Rewrite every passage under the technical-writing skill. Use short paragraphs, one action per procedural sentence and focused lists where useful. |
| M23 | P3 | Some figures are separated from their introductory text. Some captions describe an inventory rather than the information shown. | Keep figure, caption and explanation together. Give each figure a specific teaching purpose and a descriptive caption. |
| M24 | P3 | Repeated equation metadata and symbol tables can dominate the explanation. | Keep necessary definitions near equations. Present extended symbol/source information consistently without interrupting the calculation sequence. |
| M25 | P3 | The reading paths do not directly serve installation, result interpretation or independent reproduction. | Add task routes, numerical-appendix links, a complete symbol index and consistent input-method-result cross-references. |

## Target reading order

The structure separates learning, operation, calculation and reference. Existing
application help destinations remain available after reorganisation.

### Part A: Understand Sector and complete a first calculation

1. Purpose, audience, section model and required project information.
2. Complete capability map and selectable design bases.
3. Start and close the portable application; preserve work during an update.
4. Workspace map, calculation lifecycle, units, axes and action signs.
5. Complete rectangular tutorial with exact input entries and expected values.
6. Save, reopen, recalculate and produce a report from that tutorial.
7. Reading paths for input lookup, result interpretation and independent checks.

### Part B: Define, calculate and review a project

1. Geometry and reinforcement: point tables, builder, voids, bar areas, diameters,
   material IDs and slab-strip representation.
2. Materials: preset selection, editable values, factors, moduli, creep and tendon
   initial strain; explain the consequence of each control.
3. Actions: named capacity cases, sustained/additional elastic actions, fatigue
   spectra, units and source references.
4. Analysis selection: core analyses and each optional check, with activation and
   prerequisite tables.
5. Results: overview followed by each result view, its meaning and a traceable
   interpretation example.
6. Reports and projects: profile choice, references, stale output, save/load,
   autosave and the complete calculation record.

Place field dictionaries with the input family they describe. Provide links from
the application labels. Avoid placing geometry-field definitions in the Loads
chapter merely because they use the same table renderer.

### Part C: Understand the engineering methods

1. Common geometry, units, signs, equilibrium and material response.
2. Elastic response, uncracked properties and cracking classification.
3. Sustained/additional actions, creep and prestress.
4. Plastic strain limits, section capacity, M-M envelopes and N-M diagrams.
5. Crack width and the separate heightened crack-control assessment.
6. Fatigue stress ranges, resistance definitions, spectra and governing results.
7. Shear resistance with and without links, including directional geometry.
8. Torsion tube, transverse and longitudinal reinforcement, applicability.
9. Combined actions, common strut angle and governing component.
10. Minimum reinforcement and longitudinal/transverse spacing.

Each method follows this sequence: purpose; applicability; inputs and units;
physical explanation; calculation steps; example; interpretation; numerical or
method limitations; references. Introduce the physical mechanism before equations.

### Part D: Reproduce the numerical calculations

1. Calculation conventions and the conversion from application entries.
2. Polygon clipping, signed area moments and holes.
3. Complete elastic algorithm and an asymmetric biaxial iteration trace.
4. Complete plastic algorithm and depth-search trace.
5. Complete reinforcement and tendon force recovery.
6. Sustained/additional force reconstruction, including locked prestress.
7. Envelope sampling, segment intersection and N-M boundary construction.
8. Tolerances, singular systems, unreachable targets and accuracy checks.
9. Material-curve definitions required by the worked procedures.

Explain implementation choices in mathematical terms. A spreadsheet user must
know the operands, order, units and acceptance condition without a code listing.
Distinguish polygon resolution, stress integration bands and angular sampling.

### Part E: Reference and recovery

1. Standards and capability-specific source references.
2. Symbols, abbreviations, quantities, units and application-label mapping.
3. Status meanings and next actions.
4. Troubleshooting grouped by startup, inputs, calculation and publication.
5. Model assumptions and project information needed for a reproducible record.

## Notation policy

- Use mathematical subscripts for quantities such as M_Ed, s_na and f_cd.
- Use rendered powers for units and scientific notation, including mm squared,
  mm to the fourth power and negative powers of ten.
- Use Greek symbols consistently. Define ambiguous reuse, including curvature,
  creep, diameter and sweep angle, in its local context.
- Keep exact interface labels distinct from mathematical symbols.
- Identify the units of the reference stress plane and its gradients explicitly.
- State conversions between GPa and MPa, mm and m, kNm and N mm, and strain
  fractions and per mille beside worked inputs.
- Preserve all governing signs, factors, formula conditions and source references.
- Check PDF and HTML visually. Text extraction can flatten valid subscripts.

## Whole-manual language review

Apply `technical-writing-ste` to every retained and new textual block. Review
headings, procedures, explanations, table cells, notes, captions, alternatives,
equation definitions, troubleshooting entries and the glossary.

For descriptive text, target no more than 25 STE-counted words per sentence and
six sentences per paragraph. For procedures, target 20 words and one instruction
per sentence. Put conditions before the applicable instruction. Use consistent
technical terms, active voice where appropriate and permitted verb forms.

Review vocabulary meanings and parts of speech against the skill's Issue 9
references. Record engineering terms and exact interface labels separately.
Automated sentence and vocabulary checks support the review; the reviewer must
also check engineering meaning and logical connections. Record the applicable
rule and vocabulary review before making any full conformity claim.

Use short paragraphs with one subject. Use lists for sequences or parallel
choices. Use tables for exact lookup and comparisons. Keep material exceptions
with the decision they affect. Keep developer procedures and release evidence
outside the user manual.

## Whole-manual figure review

Review every existing and new figure against `figure-presentation`.

For each figure, retain its reader question, source data, case, coordinates,
units, sign convention, approximation and intended published size. Verify
geometry, scales, numbers, dimensions, marks, legends and captions against the
calculation. Preserve zero references and distinguish calculated data from
schematic illustrations.

Use matching geometry and aligned panels for strain, stress and resultants.
Show the elastic compression-zone update, one clipped polygon and the plastic
depth-search sequence. Add a directional shear/face sketch where it removes
ambiguity. Keep essential distinctions visible in grayscale. Supply meaningful
text alternatives and exact values when they are needed for reproduction.

Inspect all figures after insertion into PDF, HTML and the in-app manual. Repair
small labels, substituted symbols, weak contrast, clipping and separated captions.
Use white space and hierarchy rather than smaller type to accommodate detail.
Application result contours remain a separate, later feature.

## Implementation and verification sequence

1. Complete this source-backed audit and freeze the coverage matrix.
2. Rebuild the opening guide and complete tutorial. Check its exact application
   values and saved project with the numerical reference results.
3. Reorganise the operating reference and rewrite dense passages. Retain useful
   input definitions, status distinctions and method-source information.
4. Add the numerical appendix and independently reproduce its examples. Include
   asymmetric biaxial response, a void and a tendon case.
5. Complete the mathematical notation, language and figure reviews across the
   whole manual. Correct cross-chapter contradictions and update all links.
6. Render every PDF page and inspect it at reading size. Check the offline HTML
   and in-app navigation, equations, figures, tables and text alternatives.
7. Run focused publication and numerical checks. Keep source identities and
   engineering formula evidence intact during deliberate editorial renumbering.
8. Before a new full CLI/CI run, obtain an adversarial review against every
   requested manual improvement. Review the source and rendered PDF/HTML.
   Resolve findings and review the corrected candidate. This is a mandatory
   pre-CI gate under the user's latest instruction.
9. Build the final 0.96.5 executable package and verify its embedded manual,
   version, startup, PDF generation, archive and checksum. Complete final CI.
10. Publish only the reviewed candidate under the user's existing conditional
    consent. Replace the earlier draft assets and verify the downloadable release.

## Acceptance scenarios

| Reader task | Required evidence |
| --- | --- |
| First use | A reader can extract the package, start Sector, complete the tutorial and identify matching numerical outputs. |
| Feature discovery | Every input stage, result view, enabled check and selectable design basis has an accurate destination. |
| Input lookup | Each field has a meaning, unit, source/default behaviour and relevant dependency. |
| Result interpretation | A reader can identify the case, state, location, criterion, governing component and next action. |
| Project preservation | The tutorial can be saved, reopened and recalculated from the supplied instructions. |
| Elastic reproduction | Independent polygon arithmetic and iteration reproduce plane coefficients, stresses, forces and moments within stated tolerances. |
| Plastic reproduction | Independent depth search, bands, plateau and reinforcement reproduce force balance and capacity moments. |
| Creep and prestress | Independent force reconstruction reproduces each named state and the stated initial-strain convention. |
| Numerical failure | Singular, nonconverged and unreachable examples retain their actual meaning and recovery guidance. |
| Language | Every text block receives a recorded STE review with engineering meaning preserved. |
| Figures | Every figure receives a source and final-size visual review against the figure skill. |
| Publication | Every page is visually checked; links, symbols, tables, bookmarks and offline assets work. |
| Release | Exact reviewed source, successful final checks and matching downloadable executable/manual assets. |
