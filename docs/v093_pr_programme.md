# Sector v0.93 pull-request programme

## 1. Programme outcome

Sector 0.93 will be a robust source/application release with an additional
unsigned portable Windows application. The programme corrects input behaviour,
removes component-mapped bridge calculations that Sector cannot support
honestly, expands crack-control calculations, completes numerical substitutions,
and redesigns the user interface, manual and reports for efficient
engineering review.

This is an implementation and publication programme. It does not make Sector a
complete Eurocode, National Annex, bridge-owner, project-design-basis,
certification or sign-off system. The immutable owner choices are in the
[v0.93 decision register](v093_decision_register.md).

Exact starting point:

- Git revision: `decd1232abb0a082639de90726c125dc988e1078`
- Git tree: `f09bf8cb500f2ae02c2c30a8f085c67153fe619a`
- release tag: `v0.92-source.1`
- tracked tree and index: clean at programme start
- open pull requests: none at programme start

Programme status is updated only after objective evidence exists. The controlled
lifecycle is `Planned` -> `In progress` -> `Merged`: completed slices form one
contiguous prefix, at most one following slice is in progress, and all remaining
slices stay planned.

| Order | Slice | Depends on | Status |
|---|---|---|---|
| 1 | PR-01 - Programme, decisions and acceptance freeze | v0.92 baseline | Merged |
| 2 | PR-02 - Bridge scope reset, schema 24 and design-standard registry | PR-01 | Merged |
| 3 | PR-03 - Textbook worked calculations and complete substitutions | PR-02 | Merged |
| 4 | PR-04 - Input correctness, reusable IDs and mathematical table guides | PR-02 | Merged |
| 5 | PR-05 - Stateful input tabs and explicit modelled direction | PR-04 | Merged |
| 6 | PR-06 - Optional crack criterion and DK/NA heightened check | PR-03, PR-04, PR-05 | Merged |
| 7 | PR-07A - Eurocode-style shared equation renderer | PR-03 | Merged |
| 8 | PR-07B - Manual/report information architecture and profiles | PR-06, PR-07A | Merged |
| 9 | PR-08 - Double-click portable Windows packaging | PR-07B | Merged |
| 10 | PR-09 - Full qualification and Sector 0.93 release | PR-01 through PR-08 | In progress |

Historical v0.92 acceptance documents and preserved QA artifacts remain
evidence. They are not rewritten to make later policy look historical. Every
new behaviour is introduced and accepted in a v0.93 PR.

## 2. Review of the current implementation

### 2.1 Input tables and lifecycle

The canonical load normalizer in `app/load_cases.py` already maps `None`, blank
text and missing numeric values to `0.0`. The Streamlit editor defeats that
behaviour by declaring every numeric load column required and assigning a coarse
`10.0` step. A sparse row can therefore fail in the widget lifecycle before the
canonical boundary gets a chance to normalize it. The correction belongs at
both boundaries: permissive decimal editing in Streamlit and deterministic
normalization in the headless input model.

The rule cannot be applied indiscriminately. A blank action means zero, while a
blank optional crack-width criterion means "no criterion supplied." The shared
field metadata must encode that distinction; ad-hoc blank conversion would turn
an omitted criterion into an accidental zero limit.

The material and fatigue catalogues persist an ever-increasing `next_id`.
Consequently a deleted `M2`, `P2` or `F2` remains reserved even when no element
uses it. Stable IDs are still required for assigned objects, but an unassigned
deleted ID has no identity to preserve. Allocation must be derived from the
lowest unused positive suffix after normalization.

### 2.2 Table descriptions and mathematics

Streamlit's data editor does not render Markdown or LaTeX inside editable cells.
Trying to place TeX in a column header would expose punctuation rather than
mathematics. Sector therefore needs two coordinated surfaces:

1. a compact mathematical field guide above each editor; and
2. plain, accessible headers and tooltips inside the editor.

A shared field-definition record will own the stable field key, short plain
label, display symbol, unit, definition, sign convention, default/blank
semantics, required status and source note. UI cards, manual input-reference
tables and report legends will consume the same record. This prevents a symbol
from being explained differently on three surfaces.

The guide should default to a compact two- or three-column layout at desktop
width and collapse cleanly on a narrow viewport. Long derivations do not belong
above a table: one or two sentences define each field, with a link or expander
to the relevant manual section.

### 2.3 Input-stage navigation and modelled direction

The outer workflow currently uses a dropdown keyed by `_input_tab`. The existing
input-stage host already has active-only wrappers and can detect the open state
of a stateful Streamlit tab. The safe change is therefore not to render all tab
bodies. Native stateful tabs become the navigation control, while the host
mounts only the open stage and retains the completed-input snapshot callback.

The minimum-reinforcement solver already distinguishes longitudinal and
transverse member-relative directions. The direction is not prominent enough
before the user enables the check and is described inconsistently across the
UI, result and report. One shared label helper will publish the canonical
member-relative direction plus an optional user alias, for example
"Longitudinal (project alias: span direction)." The alias never replaces the
canonical direction.

### 2.4 Bridge-specific workflow

The three current optional bridge tables cannot be made automatic from the
available section model:

- brittle Method B requires declared tensile regions;
- box-wall shear/torsion requires individual wall identities and decomposed
  actions/resistances; and
- minimum crack reinforcement requires web/flange component meaning.

Geometry alone does not uniquely establish those engineering semantics.
Automatic inference would conceal a modelling assumption, and keeping empty
tables would preserve the same burden under a different layout. The complete
component-mapped workflow is therefore removed from input, adapter, project,
result, report and manual surfaces in one PR. Concrete compression fatigue and
ordinary whole-section calculations remain in their genuine generic modules;
they are not relabelled as complete bridge checks.

The corrected concrete compression-fatigue route sourced specifically from
DS/EN 1992-2:2005/AC:2008 Formula 6.106 is the only retained explicitly
bridge-sourced non-component calculation. It remains a bounded method using the
user-supplied section-action spectrum, not a complete bridge-fatigue check.

The first and second Eurocode generations still need honest selection where an
implemented non-component calculation differs by edition. The registry will
model three facts separately: standard family, national choice and calculation
capability. A UI choice is generated only when a solver implementation declares
the corresponding capability.

Important naming and status rules are:

- first-generation bridge family: DS/EN 1992-2:2005 with AC; DK NA:2015 is
  project context only and is not selectable unless a retained solver declares
  an exact verified NA-specific capability;
- second-generation concrete/bridge family: DS/EN 1992-1-1:2023, including
  normative Annex K as standard scope, not a Sector implementation claim; and
- never expose `EN 1992-2:2023`, because the second-generation bridge provisions
  are incorporated into Part 1-1.

The 2023 option is a published reference option requiring project adoption. No
Danish National Annex for that edition is applied. Any Eurocode recommended
value used by Sector for a Nationally Determined Parameter must be displayed and
published with the statement that no Danish national choice is applied.

The registry also prevents edition labels from outrunning implementations.
Current torsion and combined M-V-T solvers remain first-generation only and are
disabled or reported `NOT ASSESSED` under a 2023 selection. Generic editable
mild-steel and prestress families remain project-defined material laws unless
their complete edition-specific parameters and domain are explicitly fixed and
published; a familiar family name does not silently turn a custom law into an
EC2 preset.

### 2.5 Crack width and heightened Danish crack control

The current ordinary crack result is deliberately output-only. The v0.93
contract adds a nullable, positive finite user criterion. The result state is:

| Calculation state | Published status | Required publication |
|---|---|---|
| Width available; criterion omitted | `CALCULATED - ACCEPTANCE NOT ASSESSED` | Calculated width, method and warning that no criterion was supplied |
| Width and criterion available | `WITHIN USER-SPECIFIED LIMIT` or `EXCEEDS USER-SPECIFIED LIMIT` | Width, user limit, ratio, equation, units and criterion source; no demand/resistance `PASS`/`FAIL` terminology |
| Width unavailable because the section/case does not permit it | `NOT ASSESSED` or an existing typed calculation failure | Exact reason; no invented zero |
| Crack calculation not requested | `NOT REQUESTED` | No acceptance icon or compliance wording |

No exposure class, owner rule or National Annex limit is inferred from
incomplete context. If a future option offers a standard-derived limit, the
edition, table, environmental class, load combination and reinforcement or
prestress category must all be explicit inputs and report provenance.

The DK/NA heightened check is a separate first-generation calculation. The
permitted crack width is mandatory because it appears in Formula 7.100 NA. The
user must opt into its applicability; Sector must not infer that a member is
restrained, in pure tension or otherwise within the supplementary provision.
The result exposes the selected fine/coarse crack system, effective tensile
strength, crack-system factor, effective tension area, required reinforcement
ratio/area, provided area and bounded comparison. It must not appear beneath
the 2023 option as if a Danish National Annex had been adopted there.

The local text extraction corrupts the displayed Formula 7.100 NA fraction.
Implementation therefore requires two independent human readings of the
licensed visual formula, reconciliation against the symbol definitions and
dimensions, and an independently calculated benchmark before code review. OCR
text must never be copied directly into the solver.

### 2.6 Textbook worked calculations and numerical substitution

Sector already owns a strong equation-contract spine. The report has 62 known
equation contracts and the manual has a fail-closed inventory of 32 Part-C
equations. The weakness is that the contract currently permits a live
calculation relation to look the same as a theory-only relation. Eighteen report
equations have neither numerical substitution nor an applicability note.

The most visible gap is crack calculation. The final crack width is substituted,
but crack spacing and mean-strain calculations are incomplete or symbolic. The
serviceability solver retains many final values, yet several branch operands
remain local variables: first-generation spacing coefficients and strain terms,
and second-generation `k_b`, cap/raw-spacing and tension-stiffening operands.
Reconstructing them later from formatted values could select the wrong branch
or introduce rounding disagreement.

Crack spacing is the example that exposed the defect, not the scope boundary.
The required outcome applies to geometry properties, elastic and cracked
section response, plastic resistance/envelopes, shear, torsion, interaction,
detailing, fatigue, ordinary crack width and every other existing calculation
family published by Sector. A reader must not need prior
experience with the formula sequence to understand how Sector moved from the
input values to the reported result.

PR-03 is a publication-completeness change for calculations Sector already
performs. It must not revive the calculation-trace programme retired after the
previous PR-08. There is no new cross-family trace/evidence data contract,
trace payload, trace view, switch, appendix, generic calculation DAG, parallel
calculation engine, persisted calculation history or raw iteration log.

The existing calculation result remains the authority. Where a solver currently
discards a meaningful interim value, the owning family result is extended with
the smallest explicit named field or family-specific immutable record needed to
publish that value. Report code may select, order, round and format those retained
fields; it may not rerun a material law, reconstruct an operand from rounded text,
repeat a search or choose a governing branch. Dict-heavy families may be made
more explicit within their existing result boundary, but do not feed a second
generic tracing subsystem.

Every calculated case remains visible in the consolidated result summaries, but
the report publishes a complete textbook derivation only for the globally
governing or extremal result in each calculation family. This prevents repeated
load cases from turning the report into many copies of the same method. The
first-generation DK/NA crack-width route is the deliberate exception: it
publishes one globally governing fine-system example and one globally governing
coarse-system example because they are distinct calculation branches. PR-07B
later applies density profiles without changing this selection rule or the
following sequence for each selected worked example:

1. **Question.** State the quantity/check being calculated and, where one
   exists, the criterion being tested.
2. **Given data.** List the exact user inputs, derived/canonical inputs, units,
   sign convention, selected edition/method and relevant assumptions.
3. **Preparation.** Calculate geometry, material and state quantities needed by
   later equations, each with its own substitution and result.
4. **Equation.** Show the symbolic relation in Eurocode-style notation, explain
   in one short sentence why it is the applicable branch, and cite the source.
5. **Substitution.** Insert numerical values with units in the same order as the
   symbolic expression. Values must remain traceable to Given data or an earlier
   numbered step.
6. **Interim result.** State the value, unit and sufficient precision for the
   following step. If a min/max/cap governs, show every candidate and the chosen
   value.
7. **Numerical solution summary.** For iterative or search-based methods, show
   the equation or method, declared range/tolerance or selection rule, accepted
   engineering state and final residual or gap where already retained or needed
   to establish validity. Do not add iteration/evaluation telemetry solely for
   publication, and never retain or print the internal trial history.
8. **Final result and criterion.** Show demand/result, resistance/limit where
   present, ratio or margin, controlled status and governing case.
9. **Interpretation and scope.** Explain in plain engineering language what the
   result means and what Sector has not assessed, without adding a global
   compliance conclusion.

The default report must be independently followable from start to finish. Its
overview identifies every calculated case and the selected governing cases;
the complete chains then teach each implemented method once. PR-07B later lets
Brief summarize the derivation and Audit add precision or wider compact result
tables without duplicating full non-governing derivations or changing any
calculation result.

The initial family inventory freezes the minimum migration boundary:

| Calculation family | Current publication strength | Missing student-readable content required in v0.93 |
|---|---|---|
| Materials, geometry and prestress | Material tables and selected design-strength substitutions exist. | Workline evaluations; prestress strain/stress/force; transformed area, first/second moments, centroid, modular ratios and effective geometry, all linked to source inputs. |
| Plastic resistance and envelopes | Result/envelope/strain/resultant tables exist; axial equilibrium is substituted. | Strain plane, governing curvature, accepted neutral-axis state, concrete/steel force and moment sums, axial residual/tolerance and governing-point selection. |
| Elastic and cracked response | Stress, property and element tables exist. | Modular ratios, transformed matrix/centroid, equivalent prestress actions, strain-plane/resultant equations, final equilibrium residual, cracked active zone and long/short/difference state chain. |
| Ordinary crack control | Cracking/final width substitutions and rich candidate tables exist. | Stage-I threshold chain, effective area/ratio, selected reinforcement/prestress, cover/equivalent diameter, all coefficients and candidates, spacing/strain branches, caps and governing choice. PR-06 separately adds the optional comparison and heightened Formula 7.100 NA calculation in this same worked-example style. |
| Shear | Most 2005/2023 resistance equations already substitute. | Effective geometry/steel derivations, explicit numerical governing min/max, per-face provenance, permitted cotangent range, selected angle and selection rule. |
| Torsion | Main steel/crushing/cracking/utilisation substitutions exist. | Effective torsion geometry, stiffness torque distribution, complete subtube chains, numerical governing selections, permitted cotangent range and selected angle. |
| Combined M-V-T | Main interaction/chord expressions substitute. | Component source-node references, inclusion/zero rules, all component ratios, Danish-sum substitution and independent direction/face/angle selections. |
| Minimum reinforcement and detailing | Result tables and mostly symbolic equations exist. | All 2005/2023 area/resistance candidates, link ratio, transverse spacing, clear-spacing max candidates, selected bars/area/direction/tension face and deterministic governing-pair selection. |
| Fatigue | Typed bin/life/fibre-search result hierarchy and detailed tables exist. | Numerical Miner chains, S-N branch/exponent/life/damage per governing bin, concrete fatigue strength/normalized stress/life, sums/criteria and the compact governing fibre/selection already retained by the calculation result. |
| Bridge-specific publication | Current component-mapped tables contain equations/results without full substitutions. | Remove the mapped workflows under PR-02. Any retained mapping-free calculation must satisfy the same chain contract; no effort is spent expanding a calculation being removed. |

For numerical searches, the current report shows the governing solution and a
compact summary of the method, declared range/tolerance or selection rule,
accepted state and final residual or gap where those facts already exist or are
needed to explain validity. PR-03 does not add iteration/evaluation counters for
publication. Raw debug iterations, full angle arrays, integration bands and
branch-and-bound box histories are not retained or published.

The report is a consumer of existing calculation results, not a second
calculator. At minimum,
both crack editions publish effective tension area, reinforcement ratio, each
spacing term, raw and limited spacing where relevant, mean steel/concrete strain
terms, tension stiffening, final spacing, final strain difference, crack width
without an optional comparison until PR-06 supplies one. Formula 7.100 NA is
implemented and published later under PR-06, using the same reading sequence.

The inventory audit covers every calculation chapter, not only the currently
known omissions in crack control, detailing, links, shear and torsion. Basis
equations that genuinely introduce a method without producing a live value
remain symbolic and are explicitly typed as theory relations. A chain cannot be
accepted merely because its final equation has a substitution: every dependency
needed by a student to reproduce that final value must be visible or explicitly
linked to an earlier numbered step.

### 2.7 Formula typography

Current ReportLab helpers flatten important structures into linear text such as
`a/b` and `sqrt(...)`. That is semantically testable but slower to scan than the
typesetting used by Eurocodes and professional calculation notes. v0.93 adds a
single constrained equation layout model for manuals and reports.

The target grammar supports:

- built-up fractions with a visible rule;
- radicals with a vinculum over the radicand;
- nested super- and subscripts;
- italic scalar variables;
- bold or arrow notation only where the implemented method genuinely uses it;
- upright functions, operators, units and descriptive subscripts;
- balanced delimiters that scale with their contents;
- multiplication signs and decimal points that remain unambiguous;
- aligned equality chains for symbolic expression, substitution and result;
- a right-aligned equation identity where space permits;
- a separate source line rather than a citation embedded in the formula; and
- line-breaking rules that never split a fraction, radical or subscript from
  its base.

Every equation block follows the same reading order:

1. calculation purpose and stable identity;
2. symbolic equation;
3. numerical substitution for a live step;
4. result and unit;
5. symbol definitions not already established locally;
6. branch/applicability note; and
7. source and clause.

The layout model is deliberately smaller than general TeX. Unsupported syntax
fails in tests instead of silently degrading to plain text. A plain-text semantic
representation remains in the PDF text layer for search and accessibility.

Formula QA has three independent levels:

1. semantic inventory: exact equation, symbols, source, operands, unit and
   substitution policy;
2. structural PDF checks: formula/source adjacency, no clipping, valid fonts,
   bookmarks and selectable text; and
3. raster checks at normal and grayscale output: fraction bars, radical bars,
   scripts, spacing, wrapping and collision-free page placement.

### 2.8 Manual review and target information architecture

The current manual is a substantial single generated document (the current QA
render is approximately 46 pages). It contains useful method text and a governed
formula inventory, but several sections place long paragraphs, notes and formula
material too close together. The document often asks a new user to read theory
before learning the immediate task, while an experienced reviewer must scan
through instructional prose to locate a limitation or input definition.

The visual audit established concrete reference points rather than relying on a
general impression:

| Current page | Observed issue | Required treatment |
|---|---|---|
| 1 | The visible contents lists only four Parts although the PDF outline contains 82 entries. | Show chapters and selected task/method subsections in a clickable visible TOC that agrees with the bookmark tree. |
| 2 | Scope and limitation material is valuable but fills a dense opening page. | Replace the long capability sequence with a compact workflow/capability matrix while retaining the responsibility boundary. |
| 11 | Modelled reinforcement direction is buried inside continuous detailing prose. | Give it a named terminology panel and diagram linked from UI and result explanations. |
| 19-40 | Nearly every equation repeats a full symbol table, so new information and repeated notation have equal visual weight. | Establish chapter notation once and define only new/ambiguous symbols locally. |
| 29-31 | Crack equations use slash division and linear grouping. | Render true fractions, radicals, scalable delimiters and right-aligned publication equation numbers. |
| 41 | Combined M-V-T explanation is a 29 percent ink-density mechanism wall. | Use a load-path diagram, responsibility cards and governing-sequence table, retaining detailed prose in the method reference. |
| 42, 44 and 46 | Approximately 4, 8 and 6 percent ink coverage respectively because of forced breaks/poor table balance. | Treat chapter openers intentionally and permit safe balancing/splitting of assumptions and glossary tables. |

The target manual uses progressive disclosure. It is still one offline PDF, but
its structure supports three reading paths:

- a new user can complete a section calculation from the first short workflow;
- an occasional user can find one input, warning or troubleshooting answer from
  the contents/bookmarks; and
- a reviewer can trace an implemented equation, assumption and limitation
  without reading the tutorial.

#### Manual front matter

The first pages contain:

1. title, exact Sector version and source/build revision;
2. one-paragraph product purpose and responsibility boundary;
3. "Start here" choice between quick calculation, input reference and method
   reference;
4. one-page quick start with a numbered workflow and a small annotated screen;
5. notation, units and status legend; and
6. a clickable detailed table of contents.

The responsibility statement appears once prominently and then by short links;
it is not repeated as dense boilerplate on every page.

#### Task-oriented workflows

Each workflow is written as a scan-friendly procedure:

- outcome and prerequisites;
- numbered inputs/actions;
- expected result state;
- one compact screenshot or diagram when it removes ambiguity;
- common warning and correction; and
- links to the input and theory references.

Required workflows cover section creation, materials/reinforcement, action
tables, elastic/crack calculation, plastic/capacity calculation, fatigue,
detailing, reviewing results, saving/loading, choosing a report profile and
building the portable Windows application.

#### Input reference

The reference is organized by the same input-stage tabs as the application.
Every table has one definition matrix generated from shared metadata. Each row
contains plain label, mathematical symbol, unit, definition, sign convention,
blank/default behaviour, validation rule and method dependency. Short examples
show decimal entry, blank-to-zero load rows, optional crack criteria and the
member-relative modelled direction.

#### Method reference

Methods are grouped by engineering task rather than source-code module. Every
method begins with scope, implemented edition, assumptions, inputs and explicit
non-goals. Equations then follow the common publication grammar. Branches and
caps are shown near the equation they affect. Each chapter ends with a compact
"Sector implements / Sector does not implement" table.

The crack chapter must distinguish:

- first-generation ordinary width;
- second-generation ordinary width;
- optional user-limit comparison;
- first-generation DK heightened minimum reinforcement; and
- deferred or unsupported bridge/component/confinement provisions.

#### Worked examples and verification

A worked example is not a screenshot of a final number. It states the section,
materials, actions, edition and assumptions, then publishes the complete
calculation chain using the same existing calculation result fields as the Audit
report. At least
one ordinary crack example per edition and one DK heightened example are
included. Expected values carry tolerances and independent source notes.

#### Limitations and troubleshooting

Limitations are collected in one indexed chapter and linked from relevant
workflows. Troubleshooting uses symptom/cause/correction tables for malformed
geometry, uncracked cases, missing criteria, stale results, project-version
rejection, report generation and portable-build prerequisites. It must explain
that a blank crack criterion is intentional while a blank heightened criterion
is invalid.

#### Manual typography acceptance

The manual will satisfy measurable publication rules:

- body type is at least 9.5 pt with line spacing of at least 1.25 times the type
  size;
- ordinary paragraphs target 45-85 characters per line;
- visible space separates paragraphs, headings, lists, figures, tables and
  equations;
- no heading is stranded at a page foot without following content;
- no table row, equation block, callout or caption is clipped or overlapped;
- long tables repeat their header and identify continued content;
- figures and tables have stable numbered captions and are referenced in text;
- colour is never the sole carrier of status and every page remains legible in
  grayscale;
- normal text contrast is at least 4.5:1 and large text at least 3:1; the current
  small `#808080` muted text is darkened or enlarged;
- bookmarks mirror the visible hierarchy and links resolve;
- page headers identify the chapter; footers identify version/revision and page;
  and
- an automated raster inventory is supplemented by human review of every page
  at 100 percent and representative pages at 150 percent zoom.

PDF accessibility is part of publication quality. The preferred deliverable is
a tagged PDF with declared language, logical heading/list/table structure,
header-cell relationships, reading order, equation text alternatives and figure
alternative text. If the PDF toolchain cannot yet generate a conforming tagged
document, the same release must provide an equivalent accessible HTML manual;
an untagged PDF is not silently called accessible. Title, author, subject,
keywords, Sector version and exact revision metadata must be populated. The
current `(anonymous)` author metadata is not accepted.

### 2.9 Report review and target profiles

The current report is detailed (the representative QA render is approximately
56 pages) and already has useful tables, equation identities and provenance.
Its only depth control is effectively `Default report` versus a QA appendix.
That binary choice mixes audience, detail and evidence concerns. Dense repeated
method prose also competes with the case-specific values a reviewer needs first.

The reference report supplies concrete failure cases for the redesign:

| Current page | Observed issue | Required treatment |
|---|---|---|
| 2 | A 40-row mixed-state overview is set at 7.2 pt. | Separate acceptance, calculated-output and scope-state groups; place failures/warnings first and keep Standard tables at 8.5 pt or larger. |
| 3-4 and 27 | Internal `EQ-*` keys and text equations are visible to ordinary readers. | Show user-facing publication numbers/titles; retain internal keys only as Audit metadata. |
| 27 and 35 | Approximately 5 and 7 percent ink coverage follows over-broad keep-together rules. | Keep equation/substitution/result together but permit notation/prose to continue normally. |
| 42 | The report honestly states that crack width was calculated without a criterion. | Preserve the distinction using the controlled `CALCULATED - ACCEPTANCE NOT ASSESSED` state. |
| 43 | Crack spacing and mean-strain equations omit numerical substitution. | Publish every operand, substitution and interim result from typed solver evidence. |
| 49-54 | Fatigue detail is useful for audit but excessive for ordinary review. | Brief shows governing status; Standard shows spectrum/governing element; Audit retains bins and damage chains. |
| 55 | Component-mapped bridge checks remain visible. | Remove them completely under PR-02. |
| 56 | The QA appendix is a continuous bullet wall. | Replace it with a structured basis register: standard, edition, clause, option/NDP, assumption, limitation and affected result. |

Sector 0.93 introduces immutable report-profile policies:

| Content | Brief | Standard (default) | Audit |
|---|---|---|---|
| Cover, version, project and calculation basis | Yes | Yes | Yes |
| Prominent warnings/limitations | Yes | Yes | Yes |
| Geometry/material/action summary | Compact | Complete used inputs | Complete canonical inputs |
| Result summary and bounded statuses | All requested calculations | All requested calculations | All requested calculations |
| Governing case detail | Yes | Yes | Yes |
| Non-governing case results | Compact table | Complete result tables | Complete result tables |
| Symbolic equations | Only where needed to interpret result | All implemented live methods used | All used plus theory context |
| Numerical substitutions | Governing result chain | All material live calculation steps | Every retained live step and branch |
| Full-precision evidence/provenance | No, but exact revision retained | Key provenance | Complete evidence, hashes and inventories |
| Theory and symbol glossary | Link/short legend | Used symbols and concise assumptions | Full used-method appendix |

For the frozen representative fixture, Brief must fit within three pages.
Standard targets 30 pages or fewer; exceeding that target requires a recorded
content reason and visual approval. Audit has no hard page cap, but automated
sparse-page detection flags any non-opener below roughly 35 percent usable body
coverage for review. The target controls avoid both unreadable compression and
avoidable blank pages.

The profile is presentation policy only. Given one immutable result model:

- values, rounding policy, statuses, warnings and sources are identical across
  profiles;
- omitted detail is declared in the profile description;
- no profile recalculates a result;
- figures remain a separate user choice; and
- Audit does not mean approved, compliant or certified.

Every report begins with a review dashboard:

1. project and section identity;
2. software/source identity and selected report profile;
3. selected standards/methods and explicit adoption warnings;
4. calculation freshness and input hash;
5. concise result/status table; and
6. warnings, not-assessed items and excluded scope.

Detailed chapters then follow the user's calculation workflow. Inputs precede
the results they drive. Case headings repeat the action identity and selected
method. Equations are adjacent to their numerical substitutions. A result never
appears pages away from its units, case or criterion. Repeated generic theory is
moved to one appendix or the manual and cross-referenced.

Report visual acceptance uses the same typography rules as the manual, plus:

- result summaries must fit without horizontal clipping at A4 portrait;
- Standard table text is at least 8.5 pt; smaller Audit text requires a
  deliberate landscape or split-table treatment rather than automatic shrink;
- wide evidence tables use deliberate landscape pages or split semantic tables,
  never compressed unreadable type;
- statuses combine text, shape and restrained colour;
- units appear in headers or beside values, not in isolated legends;
- a governing marker is explained at first use;
- continuation pages repeat case identity and table headers; and
- Brief, Standard and Audit reference fixtures are manually reviewed in colour
  and grayscale.

### 2.10 External report/manual patterns used as inspiration

The design does not copy another product's visual identity. It adopts proven
information patterns:

- IDEA StatiCa exposes Brief and detailed report modes, lets users select
  result depth, and concludes with symbols, code/calculation settings,
  assumptions and theoretical background. See
  [Report in Detail](https://www.ideastatica.com/support-center/report-in-detail-application).
- IDEA StatiCa separates quick-start, interface, theoretical background and
  verification material instead of forcing one reading sequence. See
  [manual and documentation overview](https://www.ideastatica.com/support-center/support-center-knowledge-base/looking-for-a-manual-user-guide-or-documentation).
- MIDAS Civil's Dynamic Report organizes images, tables, charts and text in a
  report tree, supports reusable templates and refreshes model-derived content
  while retaining user text. See
  [MIDAS Dynamic Report](https://manual.midasuser.com/EN_Common/Civil/895/Start/11_Tools/Dynamic_Report.htm).
- LUSAS report tooling selects model/loadcase/result content, regenerates from
  current model data, exports QA-friendly formats and allows chapter-specific
  numerical precision. See
  [LUSAS report capabilities](https://www.lusas.com/products/bridge_tour_results.html).

Sector adopts the useful principles - progressive disclosure, selectable depth,
current-data regeneration, stable templates, explicit precision and integrated
theory/provenance - while retaining its own calculation-tool identity and
offline deterministic PDF output.

### 2.11 Portable Windows application

The current `packaging/build.bat` already launches PowerShell internally and
can resolve an extracted official source release through
`sector/sector_build_info.json` when `.git` is absent. The remaining gap is
policy and deliverable construction: it creates isolated unsigned QA evidence
and explicitly forbids use or distribution.

One click does not mean zero prerequisites. Building from source requires
64-bit Python 3.13.0, sufficient disk space and either network access to the
hash-locked packages or an already populated package cache. The produced
portable application requires neither Python nor administrator access. Its
report-figure path also depends on a Chromium-family browser; Microsoft Edge is
the supported Windows platform prerequisite and its presence/version are
detected and recorded in packaging QA.
Bundling a browser is not implied by this programme.

PR-08 creates a separate portable-distribution contract. From an extracted
official Sector source ZIP, the user double-clicks the named BAT and the script:

1. locates its source root independently of the current working directory;
2. validates the embedded exact-source manifest and inventory;
3. detects a supported Python runtime and reports one actionable prerequisite
   if it is absent;
4. creates a unique isolated build environment without administrator access;
5. installs only hash-locked dependencies;
6. builds and verifies the complete ONEDIR application;
7. writes an obvious new output directory containing the portable folder and
   ZIP;
8. writes SHA-256, source revision/tree, version, deterministic source-commit
   time, inventory and unsigned-status receipts, without a wall-clock build
   time;
9. performs a controlled loopback startup/health smoke in the acceptance gate
   and terminates it cleanly; and
10. leaves the console open with the exact output paths and warning text.

The root convenience entry point is `BUILD_SECTOR_PORTABLE.bat`. It forwards to
the canonical packaging implementation so it works from Explorer even when the
current directory differs from the extracted folder. It never starts
`Sector.exe` itself. Runtime smoke occurs only in the controlled acceptance
environment after static verification.

The portable archive contains at least:

```text
Sector-v<version>-windows-portable-unsigned/
  Sector.exe
  _internal/
  README-PORTABLE.txt
  LICENSE
  THIRD_PARTY_NOTICES.txt
  sector_build_info.json
  package_manifest.json
  SHA256SUMS.txt
```

The sibling output also includes an archive `.sha256` sidecar and a canonical
portable-distribution JSON receipt. The ZIP cannot contain its own final digest,
so that digest lives beside it. Archive verification rejects traversal paths,
absolute paths, case-fold collisions, symbolic/reparse/special entries, missing
or extra files and mutation between creation and reopen. Existing outputs are
never overwritten and a failed build publishes no final ZIP.

The directory name intentionally says `unsigned`. The README explains that the
package is portable, does not install or require administrator privileges, may
be warned about or blocked by Windows/corporate policy, and may be shared only
under the Sector licence. It never claims a digital signature, trusted
publisher, SmartScreen reputation or managed production approval.

The internal CI reproducibility artifacts remain distinct and short lived. The
portable ZIP may be attached to the 0.93 source/application release only after
the exact release commit passes package identity, source-inventory, two-build
reproducibility, archive-path and controlled startup tests. The protected
signing workflow is not invoked.

## 3. Pull-request sequence

### PR-01 - Programme, decisions and acceptance freeze

Scope:

- add this programme and the version-controlled decision register;
- record the standards status, deferred scope and identity transitions;
- freeze the test-economy and publication acceptance rules; and
- create, independently inspect and hash-pin the formatted Excel decision
  snapshot. This is the immutable PR-01 planning snapshot, not a live status
  dashboard; routine programme-status changes do not regenerate it. Any refresh
  requires an explicit reviewed workbook and acceptance update, planned for
  PR-09.

Acceptance:

- documentation is ASCII-clean and link-valid;
- baseline revision/tree and owner decisions are exact;
- the Excel workbook matches the canonical decision IDs, programme rows,
  formulas and hashes and passes rendered review of every worksheet;
- historical v0.92 evidence is unchanged;
- no runtime, solver, schema, version or packaging behaviour changes; and
- review finds no contradiction with the product identity.

Tests: documentation/ASCII/link guards and identity tests only.

### PR-02 - Bridge scope reset, schema 24 and design-standard registry

Acceptance record: [PR-02 bridge-scope and standards-registry acceptance](pr02_v093_bridge_scope_registry_acceptance.md).

Scope:

- remove all three component-mapped bridge input/check pipelines end to end;
- bump the current-only project schema to 24 with no migration;
- remove obsolete result, report and manual surfaces and stale-result hashes;
- purge retired bridge keys once from live, durable, pending, latest-input,
  result-snapshot, calculation-record and report session state so hidden v0.92
  values cannot reappear after their widgets are removed;
- add a typed capability registry for first- and second-generation standards;
- expose no inert standard or bridge-compliance selector;
- keep DK NA:2015 as project context unless an exact retained calculation
  declares a verified NA-specific capability; and
- pin confinement enhancement as absent/deferred while publishing the
  limitation where relevant.

Acceptance:

- v23 projects fail closed with a clear current-version message;
- v24 round trips without bridge component tables;
- no region/wall/web/flange mapping input survives;
- generic fatigue/section calculations remain unchanged;
- second-generation labels use DS/EN 1992-1-1:2023 and disclose no Danish NA;
- stale bridge results cannot survive deletion; and
- the strict-mypy ratchet remains non-shrinking through typed decommission
  marker modules and addition of the standards registry;
- the package has no `EN 1992-2:2023` or complete-bridge-compliance wording.

Tests: project I/O, bridge absence, result freshness, registry, app smoke,
report/manual absence, version identity and directly affected static checks.

### PR-03 - Textbook worked calculations and complete substitutions

Acceptance record: [PR-03 textbook-publication acceptance](pr03_v093_textbook_calculation_publication_acceptance.md).

Scope:

- inventory every published calculation family from inputs to result;
- extend only the existing family results where a meaningful interim operand or
  selected branch is currently discarded;
- classify equations as theory relations or live calculation steps;
- require substitution/result/unit for every live step;
- complete both crack-spacing and mean-strain chains; and
- close every audited calculation-chain gap across geometry, elastic, plastic,
  capacity, detailing, fatigue and serviceability outputs.

Acceptance:

- the report performs no engineering recomputation;
- optional constitutive-law figures may sample the selected law solely to draw
  the curve; plot samples never become calculation evidence or report operands;
- independent benchmarks reproduce each intermediate at full precision;
- rounding happens only at publication;
- a missing required result field or substitution fails closed;
- every live equation contract has substitution, result and source; and
- every globally governing/extremal worked example in the current default report
  follows the nine-part textbook sequence and can be followed by a reader who
  has not previously used the formula;
- every non-governing case remains available in compact summaries but does not
  repeat the full derivation; DK/NA crack width publishes exactly the globally
  governing fine and coarse branches; PR-07B must preserve this density rule;
- iterative/search methods publish a compact existing-result summary
  without flooding the report with implementation noise; and
- existing final results remain numerically unchanged unless a separately
  documented defect is found and independently verified.

Tests: calculation-family publication inventory; directly affected solver tests;
equation-contract and identity inventories; independent end-to-end worked
examples; report block tests; trace-retirement guards; and focused rendered
report/pedagogical review.

### PR-04 - Input correctness, reusable IDs and mathematical table guides

Acceptance record: [PR-04 input-correctness acceptance](pr04_v093_input_correctness_acceptance.md).

Scope:

- permit decimal load actions without a coarse editor step;
- normalize ordinary blank load actions to zero while preserving each row;
- accept unambiguous dot/comma decimal paste/import at the canonical boundary;
- allocate the lowest unused M/P/F identifier;
- add the shared field-definition registry; and
- render mathematical notation guides above all editable tables.

Acceptance:

- sparse rows calculate and persist instead of disappearing;
- malformed nonblank cells remain visible with a precise field error;
- optional-null fields do not become zero;
- no input precision is silently rounded;
- deleting M2 then adding mild steel produces M2 when it is truly unused;
- assigned objects cannot be orphaned; and
- every editor field has definition, unit, blank/default and plain help.

Tests: input model, catalogues, save/load, AppTest table lifecycle, metadata
coverage, responsive UI and changed report/manual reference surfaces.

### PR-05 - Stateful input tabs and explicit modelled direction

Acceptance record: [PR-05 navigation and modelled-direction acceptance](pr05_v093_navigation_direction_acceptance.md).

Scope:

- replace the stage dropdown with native stateful tabs;
- mount only the open stage;
- preserve complete-draft snapshots and genuine-event journal behaviour;
- centralize modelled-direction labels and optional project alias; and
- publish the direction before selection, beside results and in documents.

Acceptance:

- direct tab navigation does not execute hidden expensive stages;
- interrupted/rapid widget changes do not lose a completed draft;
- save/load and result navigation retain their independent fragments;
- AppTest and browser lifecycle agree on the active stage; and
- every minimum-reinforcement result names the canonical direction.

Tests: input-stage host, fragment/state unit tests, bounded AppTest flows,
cold-start/active-stage performance probes and cross-surface direction tests.

### PR-06 - Optional crack criterion and DK/NA heightened check

Acceptance record: [PR-06 crack-control acceptance](pr06_v093_crack_control_acceptance.md).

Scope:

- add the nullable ordinary criterion to each eligible elastic case;
- include it in signatures, persistence, reuse and freshness boundaries;
- publish calculated/not-assessed or bounded comparison states;
- implement the separately selected first-generation DK heightened check;
- route verified current/next non-component crack design options; and
- publish complete typed evidence in UI/report/manual.

Acceptance:

- no criterion yields width only plus explicit not-assessed status;
- a positive criterion yields the exact ratio and the controlled
  `WITHIN USER-SPECIFIED LIMIT` or `EXCEEDS USER-SPECIFIED LIMIT` result;
- zero, negative, Boolean and non-finite criteria are rejected without data
  loss;
- the heightened option requires a positive criterion;
- Formula 7.100 NA is unavailable for the 2023 option;
- Formula 7.100 NA has dual visual transcription evidence from the licensed
  standard and no OCR-derived implementation path;
- independent fine/coarse/smooth-reinforcement benchmarks pass; and
- no exposure or bridge-owner applicability is inferred.

Tests: new independent numerical oracles, invalid boundaries, case signatures,
schema, AppTest, report/manual/equation inventories and stale-result tests.

### PR-07A - Eurocode-style shared equation renderer

Acceptance record: [PR-07A shared equation-renderer acceptance](pr07a_v093_equation_renderer_acceptance.md).

Scope:

- implement the constrained shared math layout model;
- migrate governed manual and report equations;
- retain searchable semantic text and stable equation/source identity; and
- add structural and raster formula QA.

Acceptance:

- fractions, radicals and scripts render structurally rather than as flattened
  approximations;
- unsupported constructs fail closed;
- substitution/result alignment is consistent across manual/report;
- formulas never clip, collide or separate from their source/result; and
- every governed equation passes semantic, PDF-structure and raster checks.

Tests: renderer unit/property tests, equation inventories, PDF extraction,
font/glyph checks, raster fixtures and targeted manual/report full renders.

### PR-07B - Manual/report information architecture and profiles

Acceptance record: [PR-07B manual/report profiles acceptance](pr07b_v093_report_manual_profiles_acceptance.md).

Scope:

- implement Brief, Standard and Audit policy objects;
- rebuild the manual around the specified reading paths;
- lead reports with basis/warnings/results and reduce repeated prose;
- add shared legends, input references, worked examples and limitations;
- implement bookmarks, captions, continuation rules and spacing metrics; and
- update the in-app profile controls and help.

Acceptance:

- all profiles publish identical engineering values/statuses;
- Standard is default and Audit is explicitly not certification;
- manual contents/bookmarks cover every implemented UI stage and calculation;
- all input fields and warnings are findable from the reference;
- current and next crack examples include every interim substitution;
- no page has clipping, collision, orphan headings or unreadable table type;
- colour and grayscale fixtures both communicate status; and
- every page of final reference PDFs receives recorded human visual review.

Tests: profile/content inventories, cross-profile equality, manual/report text
contracts, bookmark/link tests, full structural preflight, raster comparison and
human page checklist.

### PR-08 - Double-click portable Windows packaging

Acceptance record: [PR-08 portable Windows packaging acceptance](pr08_v093_portable_windows_acceptance.md).

Scope:

- add the separate portable build/orchestration path and BAT entry point;
- support official extracted source ZIPs without `.git`;
- create verified portable folder, ZIP, manifests, hashes and user README;
- preserve a separate unsigned-QA reproducibility path;
- add a controlled loopback startup smoke; and
- update packaging documentation and workflow artifacts without signing.

Acceptance:

- double-click is the only interactive action after extraction and prerequisites;
- no separate PowerShell command or administrator elevation is required;
- spaces/OneDrive paths and non-repository source roots work;
- output paths are obvious and printed at completion;
- the whole folder/ZIP, not the executable alone, is distributable;
- exact source, product/legal identity, dependency notices and unsigned status
  verify before publication;
- two independent builds are byte-identical under the accepted environment;
- a clean extracted package reaches the local health endpoint and terminates;
  and
- no signing secret, certificate or protected environment is used.

Tests: script policy, extracted-source adversaries, archive traversal/path
guards, manifest/hash/identity, two-build comparison, controlled startup and a
real exact-head Windows workflow artifact.

### PR-09 - Full qualification and Sector 0.93 release

Scope:

- reconcile every decision and PR acceptance row;
- run the complete exact-head qualification matrix;
- update version/resource/report/manual/package identity to 0.93;
- build and verify exact source and portable application assets;
- create the annotated tag and guarded draft source/application GitHub release;
  and
- attach hashes, limitations and QA receipts to that draft.

Acceptance:

- every earlier PR is merged with zero unresolved blocking review thread;
- complete tests, coverage, Ruff, strict owned mypy, dependency audit, app
  lifecycle, manual/report renders and Windows packaging pass;
- source and portable assets derive from the exact accepted commit;
- project schema, all product versions and report/manual provenance agree;
- Sector identity metadata is byte-for-byte correct on guarded surfaces;
- release notes distinguish source ZIP, unsigned portable ZIP and absent signed
  installer;
- no v0.93 scope item remains pending; and
- the Excel decision snapshot matches the accepted register revision.

Tests: full suite with a new unique pytest base temp, consolidated publication
gate, all PDF structural/raster gates, exact source archive verification, two
Windows builds, portable startup smoke and post-attachment draft-asset
revalidation.

## 4. Risk-based development test policy

Each PR owns a written affected-surface matrix before code changes. The minimum
per-PR gate is:

1. unit tests for every changed headless model/solver;
2. persistence/signature/freshness tests for every changed input or result;
3. focused AppTest flows for changed widgets;
4. equation/content/render tests for changed publication surfaces;
5. Ruff and strict owned mypy for changed modules;
6. product identity and ASCII guards; and
7. one regression around each adjacent boundary identified in the PR risk map.

The following may be skipped on a bounded PR when its affected-surface matrix
shows no dependency path:

- unrelated solver families;
- complete manual/report raster sets when no publication layout changes;
- full Streamlit lifecycle when no shared input/state code changes;
- real PyInstaller builds when no packaging/dependency/resource code changes;
  and
- the complete multi-worker test suite.

Broader gates are mandatory at coupling milestones:

- PR-02: schema and full project round-trip family;
- PR-03/PR-06: complete serviceability and equation-publication families;
- PR-05: complete active-stage/fragment family;
- PR-07B: complete manual/report family;
- PR-08: complete Windows package/release-policy family; and
- PR-09: every test and release gate without exception.

Every pytest run uses a verified previously nonexistent unique `--basetemp`.
No command may clean or reuse the preserved workspace QA corpus.

## 5. Review and merge protocol

For each PR:

1. branch from the exact current `main` using `codex/`;
2. confirm the tracked index/tree is clean without traversing or deleting the
   preserved untracked QA corpus;
3. edit only the declared scope and stage explicit paths;
4. run the bounded local acceptance matrix;
5. commit intentionally, push and open a draft PR;
6. allow directly relevant GitHub Actions to complete;
7. resolve actionable review/CI findings without broadening scope;
8. record the exact accepted head and tests in the PR acceptance document;
9. squash merge without deleting preserved historical branches; and
10. verify the accepted tree on `main` before starting the next PR.

Never use `git clean`, broad deletion, `git reset --hard`, untracked-inclusive
stash, `git add .`, `git add -A` or `git commit -a`. All GitHub actions remain
non-destructive to the repository history and preserved evidence.

## 6. Programme definition of done

The v0.93 programme is complete only when:

- D093-001 through D093-027 are implemented, verified or explicitly recorded
  as deferred/excluded exactly as frozen;
- every PR acceptance record identifies its accepted commit and evidence;
- no component-mapped bridge workflow or confinement enhancement/claim remains,
  and relevant 2023 scopes disclose that confinement is not included;
- load decimals/blanks, reusable IDs, table guides, tabs and direction labels
  work through save/load and calculation;
- ordinary crack comparison and DK heightened reinforcement behave exactly as
  specified and have independent numerical evidence;
- all complete Standard/Audit calculations read as traceable worked examples,
  and every live interim calculation has numerical substitution and provenance;
- formulas, manual and all report profiles pass semantic and visual QA;
- the double-click BAT produces a verified complete unsigned portable ZIP from
  an extracted official source release;
- the full exact-head qualification passes;
- source and portable release assets are reverified after attachment to the
  authenticated draft release;
- the Excel decision workbook matches the accepted Markdown register; and
- Sector 0.93 retains the exact product identity and responsibility boundary.
