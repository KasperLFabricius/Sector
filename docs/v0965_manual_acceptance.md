# Sector 0.96.5 manual acceptance

Base: 4d4a5fd6f40fc03b7b4b8d6517f0e6d76057b741.
Scope: whole-manual revision, technical English, worked examples, figures,
publication layout, offline HTML, release metadata and portable distribution.
The earlier c942454 candidate is superseded. Its review and package evidence
do not approve this revision. See `v0965_manual_revision_plan.md` for the audit
and detailed implementation plan.

| Requirement | Evidence required |
| --- | --- |
| Elastic reproduction | Independent rectangular transformed-section arithmetic agrees with native stresses and compression depth. |
| General numerical reproduction | Independent biaxial polygon clipping, void subtraction, tangent matrix, Newton steps and tendon resultants agree with the native solver. |
| Plastic reproduction | Published band and reinforcement resultants balance the named action and reproduce its moment. Band refinement values are retained. |
| Duration combination | LONG, retained component, instantaneous response, TOTAL and DIF reproduce the native combination. |
| Honest approximations | Polygon geometry, 80 midpoint bands, angular sampling, first strain limit and displaced-concrete choices are explicit. |
| Broader explanations | Crack geometry, shear truss, torsion tube, combined demands, detailing and fatigue each have a physical explanation and relevant figure. |
| Publication integrity | The 33 governed equations retain semantic keys, expressions, sources, units and dependencies. Editorial ordinals follow the revised chapter order, with an explicit migration record. Table and figure inventories remain fixed and checked. |
| Complete operating guide | Startup, tutorial, every feature and design basis, input definitions, named result views, saving, reporting and recovery have accurate routes. |
| Feature inventory | Each of the 124 audited features has a purpose, applicable inputs, operating steps and result interpretation. Resolve every missing, partial or disputed row against the application. |
| Whole-manual language | All authored and retained text, captions, table cells, notes and appendices receive an STE rule and vocabulary review. |
| Offline HTML | Every figure has an embedded image, useful alternative and caption. No script or network resource is required. |
| Visual quality | Every PDF page and every existing or new figure is inspected at reading size. Navigation, symbols, layout and image checks pass. |
| Figure opportunities | Review every chapter for useful additional figures. Record the reader question, source evidence and placement for each addition. Record why existing text, tables or figures are sufficient elsewhere. |
| Numerical scope | Production solver modules and saved-project schema remain unchanged. |
| Distribution | Version 0.96.5, matching build metadata, portable executable startup, image export, ZIP and SHA-256 verified. |

Run independent examples and focused manual checks during revision. Before any
new full CLI/CI validation run, obtain an adversarial review of the revised
manual against all user requirements. Resolve the findings and repeat the
independent review of the corrected source and rendered PDF/HTML until the
reviewer reports no further findings. This pre-CI gate follows
the user's explicit instruction. It covers scope, organization, density,
technical detail, reproducibility, notation, standards, STE language and every
figure. The review also assesses where additional figures improve understanding.
Preserve existing numerical and release checks. Record the final
commands, results and exact reviewed revision in the release evidence.

The user explicitly approves the necessary GitHub actions. Merge to main and
the final installation package follow only after this review gate and the
full CLI checks pass. Material changes after a review require another review.

The feature audit includes the five input stages, nine result views, point-grid
operations, every builder shape, material and fatigue catalogs, conditional
checks, project records, recovery and both manual exports. The inventory and
closure reports are retained under output/v0965-qa in the task workspace.
Coverage of a control name alone does not close a feature. The reviewer must
check its inputs, operation and consequences.

## Manual review closure

The final independent manual review records no open findings. The approved
publication has 143 pages, 677 source blocks, 36 figure placements, 77 tables
and 33 governed equations. The feature matrix closes 122 public features and
records the scope decisions for its two remaining entries.

The language record covers all 53 ASD-STE100 Issue 9 rules, with applicable
vocabulary and technical-term decisions. The chapter-by-chapter figure review
led to six additional diagrams. Existing figures also received readability
corrections and checks at their published size.

The retained review includes every PDF page, browser navigation, all embedded
HTML images and accessible figure names. Independent arithmetic and a live
tutorial replay support the numerical examples. The exact candidate review,
full validation and executable verification remain release requirements.

## Validation environment corrections

Two test-harness failures were reproduced on the unchanged 0.96.4 base.
The Quick Section adapter now removes retired widget references and completes
the pending full rerun when the input-stage selector has not yet remounted.
Checks cover live controls, session-state preservation and native report routes.

The native handle-isolation test uses the underlying Python interpreter for its
standard-library worker. This avoids measuring the Windows virtual-environment
redirector's child-process lifetime. The private-handle assertions, expected
protocol output and 1.5-second limit remain in place. Both corrections affect
tests only.

The complete CI run also exposed three fatigue-test failures that reproduce on
the unchanged base. The mixed-bond arithmetic now covers both displaced-concrete
settings explicitly. The report-depth checks accept either symmetric top corner
only after verifying their raw criterion values and the narrow governing tie.
They still require one Standard row, all Audit rows and matching profile headings.
The introduced strain-notation finding uses the established U+2030 symbol in the
manual text, captions, alternatives and figure axis. Its PNG and manifest are
regenerated from the corrected source.

The report CI group exposed one further test failure on the unchanged base.
The appendix text reader now descends into its existing layout groups and
requires the appendix heading before checking method references. The test
retains its eligible, mixed and rejected case assertions and its PDF text
checks. Production report code is unchanged.

Two independent reference-example comparisons also failed on the unchanged
0.96.4 base. Their rectangular elastic calculation counted the concrete inside
compressed reinforcing bars twice. The independent first-moment and second-moment
sums now use the net transformed area in the compression zone. The original
comparison tolerances stay unchanged. The elastic, crack-width and fatigue
comparisons pass with that correction. Production solvers are unchanged.

Independent review resolved twelve further failures reproduced on the unchanged
base: eight native-application tests and four report-profile tests. The review
checked obsolete geometry and numerical snapshots against independent arithmetic
and controlled comparisons with the former model. It also corrected native-tab
test setup and selected the fatigue element that the test changes. All original
tolerances and required assertions remain. Thirteen focused cases pass because
the report-placement test checks both Standard and Audit profiles. The detailed
causes and evidence are in the task's independent-ci-failure-review.md record.

The next complete CI run passed the native, report and combined primary groups
with 882, 1,014 and 202 tests respectively. Its remaining primary group found
eleven assertions that still used the former manual wording, equation numbers
or markup. Nine test files now check the reviewed publication. The corrections
retain all 70 test functions, all three numerical tolerance checks and the
50-word limit for interactive explanations. Manual procedures, numerical tables
and figure descriptions remain subject to the manual content checks. All 111
focused tests pass. Independent review records zero findings in this correction.

The standalone report fixture also retained a stress value from the former
gross-concrete model. Both the unchanged 0.96.4 base and the release candidate
produce 956.4877695572533 MPa. Independent rectangular-section equilibrium gives
956.4877695572573 MPa. The fixture now requires the published 956.488 MPa and
adds a numerical check with relative and absolute tolerances of 1e-10. A report
page fingerprint was updated after a pixel comparison isolated the change to
the footer version digit. All report checks pass across 82 pages.

The dependency audit identified nine advisories in two locked packages. The
security correction updates urllib3 from 2.7.0 to 2.8.0 and the QA dependency
pypdf from 6.18.0 to 6.19.0. All other locked versions and hashes are retained.
The audit policy, empty suppression list and workflow remain unchanged. The
updated audit covers 101 packages with zero reported vulnerabilities. A fresh
hash-locked installation passes 121 focused tests. All 143 manual pages retain
identical text, pixels, dimensions, links and bookmarks; HTML is byte-identical.
Independent review records zero findings for these corrections. The final
commit review and complete CI remain required before publication.
