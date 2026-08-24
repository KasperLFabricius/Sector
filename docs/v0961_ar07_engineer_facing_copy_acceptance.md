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
boundary. Detailed diagnostic text is publishable only when it is an immutable,
explicitly authored `EngineerMessage`, either passed directly or attached to a
deliberate validation exception. Plain strings, arbitrary exceptions, unknown
objects, deserialised text and calculation-result failures are untrusted. They
are logged and replaced by contextual authored guidance.

Trust does not depend on a list of forbidden words. The copy policy remains a
separate check on authored messages and catches development-process language
such as GitHub references, pull requests, source-control history, hashes,
payloads, schemas and internal identifiers. Ordinary engineering use of words
such as stable, retained, authoritative and identity is not prohibited.

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

The publication gate uses positive provenance. A frozen neutral message type is
defined in the headless package, while `app/engineer_messages.py` is the sole
resolver allowed to return diagnostic copy for display. Capacity input,
project-file and fatigue validation attach only literal authored messages.
Capacity-result failures and unknown paths cannot acquire publication trust.

An AST guard rejects message construction from `str(exc)`, formatted exception
text or joined diagnostics. A test-owned hostile corpus imports no production
vocabulary constants. It exercises raw strings, exceptions, unknown objects,
filesystem errors, result errors, JSON round trips and the actual UI, project,
fatigue and report boundaries.

The copy inventory uses the syntax tree rather than a hand-selected source-file
sample. Runtime and static authored-copy checks call the same case/separator
normalisation and detector.

The candidate inventory contains 3,090 visible surfaces:

- 2,114 Streamlit and supporting-message surfaces;
- 459 manual surfaces; and
- 517 report surfaces.

The final automated result is zero development-process candidates. Generated
manual PDF, accessible manual HTML and all three report PDFs are also extracted
and scanned with an independent test-owned oracle.

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
| AR07-11 | A plain string, arbitrary exception, unknown object or result error reaches a boundary | It is logged and replaced even when its text appears harmless. |
| AR07-12 | A deliberate validation has useful engineering guidance | Only its explicitly attached `EngineerMessage` is published; the exception text is not used. |
| AR07-13 | A trusted message contains recognised Eurocode notation | `gamma_Ff`, `gamma_s`, `gamma_V`, `gamma_c,fat`, `beta_cc(t0)`, `alpha_cc`, strength and action notation survive exactly. |
| AR07-14 | A message is serialised and read back | The reconstructed text has no publication trust. |
| AR07-15 | A developer attempts diagnostic laundering | The AST guard rejects exception conversion, formatted strings and joined diagnostics in `EngineerMessage` construction. |

## Verification evidence

- Positive-provenance and laundering guard: 31 passed.
- Independent publication-oracle checks: 12 passed; 3,090 inventoried surfaces
  and zero development-process candidates.
- Independent real-publication oracle: manual PDF, manual HTML and Brief,
  Standard and Audit PDFs all have zero hits; hostile injected result messages
  are hidden in every report profile.
- Exact-head focused project, fatigue, geometry, result-presentation, report,
  copy and actual UI-boundary gate: 257 passed with zero failures, errors or
  skipped tests.
- Ruff policy, strict mypy policy, bytecode compilation and diff-whitespace
  checks pass.
- Explicit result: **0 raw leaks; 0 false suppressions** in the independent
  hostile and recognised-notation corpora.

The product remains Sector 0.96 throughout this PR. Version elevation is owned by
the final v0.96.1 release step after adversarial-review greenlight and exact-head
CI. Those two final gates remain pending for this candidate.
