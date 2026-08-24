# v0.96.1 AR-07 engineer-facing copy acceptance

## Outcome and boundary

AR-07 is a complete user-facing copy review, not a correction of only the
examples listed in the adversarial review. The reviewed audience is a practising
structural engineer who has taken no part in Sector's development and should not
need software-development vocabulary to operate or review the calculation.

The review covers the Streamlit application, generated manual and all report
profiles. It changes explanations, labels, warnings, report composition wording
and publication layout only. It does not change an engineering equation, input,
result, applicability decision, status, rounding rule, project-file format,
product version or package surface.

## Audience rule

Visible text must state the engineering fact, required action or calculation
boundary. It must not expose development-process detail such as source revisions,
SHA or hash values, payloads, schemas, migrations, solver contracts, internal
identifiers, retained-state terminology or implementation history.

Internal equation keys and calculation bookkeeping remain available to the
software's validation logic. Reports identify equations by ordinary report
numbers only. The project revision entered by the engineer remains visible as
document control; it is not a software revision.

## Report-profile philosophy

- Brief records all inputs relevant to its reported results, the governing
  results, concise limitations and only the key governing figures. It does not
  reproduce worked derivations, the result chain or non-governing results.
- Standard is the normal calculation report. It records all used inputs,
  complete result tables, key references and one governing worked calculation
  for each active check family.
- Audit is an expanded engineering review report. It adds non-governing results,
  intermediate values, substitutions, complete references and method theory,
  while retaining the same inputs, results and statuses as the other profiles.

None of the profiles publishes software-development identifiers. Publication
depth never reruns a calculation or changes an engineering result.

## Review method

The copy inventory uses the syntax tree rather than a hand-selected string list.
It includes Streamlit controls and messages, manual/report builders, equation
symbol meanings, editable-table field definitions, structured workflow and
warning records, and user-facing return messages from calculation adapters.

The final inventory contains 3,117 visible surfaces:

- 2,138 Streamlit and supporting-message surfaces;
- 459 manual surfaces; and
- 520 report surfaces.

The final automated result is zero development-process candidates. Generated
manual and report PDFs are also extracted and scanned, including dynamically
constructed text and internal-equation-identifier patterns that are not visible
as source literals.

Long passages and negative wording remain review signals, not automatic defects.
An explicit fail-closed calculation reason may need more words than a label.
Every candidate was judged by whether it helps the engineer understand the
calculation or correct the stated input.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| AR07-01 | A practising engineer reads any visible product text | The text explains an engineering input, result, limitation or next action without assuming development knowledge. |
| AR07-02 | Manual, UI or report text is inventoried | No SHA/hash, payload, schema, migration, internal-key, solver-contract or similar development-process wording is published. |
| AR07-03 | An Audit equation is published | It has an ordinary report equation number and source; its internal software key is not printed. |
| AR07-04 | A result cannot be assessed | The warning states the missing engineering evidence and the required recalculation or input correction. |
| AR07-05 | A report profile is selected | Its description matches the Brief, Standard or Audit philosophy above and does not imply a different calculation. |
| AR07-06 | The manual is generated | It describes the current program and user workflow, not former versions or development administration. |
| AR07-07 | Long or defensive copy is reviewed | Useful engineering boundaries remain; redundant assurances and development history are removed. |
| AR07-08 | A chapter starts near a page end | The heading remains with its first calculation input or substantive content. |
| AR07-09 | The final PDFs are rendered | No clipping, unbreakable equation, empty continuation or unintended sparse page remains. Figure-only plates may remain sparse when the figure is the page's intended content. |
| AR07-10 | Repository scope is inspected | Engineering values, statuses, project-file format and product version remain unchanged. |

## Verification evidence

- Static copy audit: 3,117 surfaces; zero development-process candidates.
- Exact-G1 correction recheck: 100 message, report-profile and portable-startup
  cases passed; `gamma_V` remains visible as Eurocode notation while the
  application field name remains hidden.
- Generated-artifact copy gate: 5 passed, including PDF text extraction and
  internal equation-identifier rejection.
- Consolidated manual/reference gate: 360 passed, 1 intentionally deselected
  real-image test covered by the separate rendered fixture.
- Consolidated report gate: 292 passed and 1 intentionally deselected; three
  stale wording expectations were updated and their focused recheck passed 3/3.
- Consolidated affected copy/calculation-message gate: 507 passed; one stale
  wording expectation was updated and its focused recheck passed 1/1.
- Earlier complete Streamlit smoke pass: all 262 tests closed after focused
  updates to seven deliberate wording assertions.
- Final manual fixture: 71 rendered pages plus accessible HTML.
- Final illustrated Audit fixture: 66 rendered pages; only pages 13 and 15 are
  sparse review signals, both intentional material-law figure plates. The
  browser-free Audit fixture has no sparse non-opener pages.
- Compile, focused Ruff and diff-whitespace checks pass.

The product remains Sector 0.96 throughout this PR. Version elevation is owned by
the final v0.96.1 release step after the remaining programme PRs and adversarial
review gate.
