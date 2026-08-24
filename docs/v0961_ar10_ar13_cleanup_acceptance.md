# v0.96.1 AR-10 to AR-13 bounded cleanup acceptance

## Outcome and boundary

This change removes seven tracked files that had no live internal caller, moves
the PDF inspection library out of the application runtime, trims measured
PyArrow developer material from the Windows package, and corrects one stale QA
test name. Sector remains version 0.96 with project format 27.

No engineering equation, solver route, input, result, status, design standard,
rounding rule or saved-project field is changed. A torsion figure now handles a
deliberately withheld resistance as “not assessed” instead of failing while
drawing, and the accompanying explanation again identifies both the wall shear
flow and transverse-equilibrium clauses.

## AR-10: measured file removal

The following files are removed:

1. `app/bridge_analysis.py`
2. `sector/bridge.py`
3. `tests/test_bridge.py`
4. `app/crack_criterion_publication.py`
5. `app/crack_criterion_value.py`
6. `tests/test_crack_criterion_publication.py`
7. `tests/test_crack_criterion_value.py`

The bridge files contained only decommissioning markers and self-referential
tests. The crack-criterion helpers were imported only by each other and their
own tests; current duration-specific crack control uses the retained SLS paths.
Post-removal guards require all seven paths, imports and package exports to stay
absent.

Known repositories owned alongside Sector were inspected at these revisions:

- BriCoS: `9a31b11bd6ff01c59b9893cbcfbb41ea7f63fe37`
- Tradehelm: `3e6fa8567c1a47c6c07655a22b3fd80425c193f6`
- SteFaN: empty repository

No Sector bridge-module import or removed crack-helper import was found. This
does not prove that an unknown or private external consumer does not import
`sector.bridge`; such a consumer must remove that obsolete import when adopting
this version.

The strict-type ratchet retains eight production files. The two deleted bridge
files are replaced in the ratchet by the live `sector/sls_identity.py` and
`app/report_profiles.py` boundaries. The verifier permits this declared
one-for-one migration without permitting the policy to shrink.

## AR-11: QA-only PDF inspection

`pypdf` is retained as a direct development and QA dependency because tests and
publication tools inspect PDF structure. It is removed from the runtime input,
runtime lock, build lock and explicit package collection. Sector's report
generation continues to use ReportLab; application execution does not import
`pypdf`.

## AR-12: conservative PyArrow trim

PyArrow remains in the package for Streamlit and Pandas operation. The package
filter removes only PyArrow headers, C/C++/Cython sources, include trees and
test material after PyInstaller has completed its normal dependency analysis.
Runtime Python modules and compiled libraries remain.

The differential package inventory is:

| Inventory | Baseline | Candidate | Difference |
|---|---:|---:|---:|
| PyArrow files | 648 | 43 | -605 |
| PyArrow bytes | 81,561,173 | 73,862,259 | -7,698,914 |
| Total package files | 2,118 | 1,524 | -594 |
| Total package bytes | 355,061,808 | 347,410,920 | -7,650,888 |

The total file difference is smaller than the PyArrow removal because the
candidate package contains eleven retained files not present in the comparison
baseline. The filter is tested directly so similarly named material outside
PyArrow is retained.

The packaged-product probe starts the frozen executable and exercises the
editable section grid, project loading and rejection, project saving, manual
PDF and accessible HTML generation, Standard report generation and PDF
registration. It checks both a valid converted project and a deliberately
invalid saved report setting.

## AR-13: QA naming

The Windows product-identity test name now says version 0.96, matching the
identity it has always asserted. The product identity itself is unchanged.

## Engineer-facing copy addendum

Project loading, autosave and download errors are translated at the UI boundary
into engineering actions. They no longer expose hashes, software format
internals, field identifiers or conversion version numbers. A converted project
states that the source file was not changed and tells the engineer to review the
converted inputs before recalculating.

The final syntax-tree inventory covers 3,116 visible UI, manual and report
surfaces and reports zero development-process candidates. Generated Audit
reports show ordinary equation numbers and sources without internal equation
keys.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| AR10-01 | Repository and package exports are inspected | All seven stale paths and their imports are absent; live crack control and historical decision records remain. |
| AR10-02 | Known owner repositories are inspected | No known consumer uses the removed modules; the limitation for unknown external consumers is recorded. |
| AR11-01 | Dependency inputs, locks and package specification are inspected | `pypdf` is direct QA-only material and is absent from the application runtime and Windows package. |
| AR12-01 | PyArrow package material is filtered | Only developer sources, headers, include trees and tests are removed; runtime modules and binaries remain. |
| AR12-02 | The frozen application is exercised | Section editing, project load/rejection/save, manual generation and Standard report generation complete from the package. |
| AR13-01 | Windows identity QA is inspected | The test name and asserted Sector 0.96 identity agree. |
| COPY-01 | A project-file error reaches the UI | It states the engineering problem and next action without development terminology. |
| SCOPE-01 | Calculation and release identities are compared | Engineering behavior, version 0.96 and project format 27 remain unchanged. |

## Verification evidence

- Complete Streamlit application smoke family: 262 passed.
- Remaining non-Streamlit suite: 6,080 passed; fifteen deliberately revised
  wording/layout expectations and one new torsion-figure regression then passed
  together as a 16-test closure set.
- Engineer-copy and project/portable focused gate: 30 passed.
- Real image exports: 14 passed.
- Issued report with real figures: passed.
- Issued manual with real figures: passed.
- Ruff policy ratchet, strict mypy ratchet, dependency-lock preflight, executed
  vulnerability audit, bytecode compilation and whitespace checks: passed.
- User-copy inventory: 3,116 surfaces; zero development-process candidates.
- Windows differential build, packaged first-page execution and the expanded
  packaged-product probe: passed on the exact candidate.
- The complete Windows test/report job retains every test and publication gate;
  its time allowance is 90 minutes because the preceding release already used
  57.6 minutes before the decision-branch coverage gate was added. The focused
  workflow-policy recheck passed 179 tests.

The version elevation to 0.96.1 remains a later release step after the exact
candidate receives the requested adversarial-review greenlight.
