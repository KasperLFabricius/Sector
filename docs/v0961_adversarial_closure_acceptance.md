# v0.96.1 adversarial closure acceptance

## Scope and release boundary

This bounded change closes the three minor findings left open by the independent
review of merged Sector 0.96. It does not change an engineering equation,
calculation route, input, result, status, project-file format or product version.
Sector remains 0.96 with project format 27 until the exact candidate is accepted
and the separate release step elevates the product to 0.96.1.

## AR-05: compression-resultant notation

`F_c` remains reserved for the concrete compression resultant in the manual and
plastic equilibrium relation. The total compression resultant reported by the
plastic solution is now consistently identified as `F_comp` in the Streamlit
per-angle table, selected-point summary, Audit sweep table, worked calculation
and manual glossary.

The total is the concrete contribution plus any reinforcement force acting in
compression. Prestressing steel remains tension-only under Sector's current
material model. An executable solver case contains compression reinforcement
and proves that `F_comp` equals the concrete resultant plus all compression-side
reinforcement forces and is greater than `F_c` for that case.

## AR-07: engineer-facing failure boundaries

Visible manual, report, calculation, Quick Section, material, project-load and
fatigue failures state the engineering action without exposing software
diagnostics. Publication now uses positive provenance: only an immutable,
explicitly authored `EngineerMessage`, or an exception carrying one, can provide
detailed visible copy. Plain strings, arbitrary exceptions, deserialised text,
unknown objects and calculation-result errors are logged and replaced by
action-specific guidance regardless of their wording.

Controlled tests inject development terms into calculation, fatigue, report,
manual-generation, manual-figure and project-file failure paths. None reaches a
visible message. The saved-report warning, fatigue edition mismatch, section
comparison and plastic worked-point wording were also rewritten in engineering
language.

The authored-copy check explicitly preserves familiar Eurocode notation such as
`gamma_Ff`, `gamma_s`, `gamma_V`, `gamma_c,fat`, `beta_cc(t0)`, `alpha_cc`,
strength notation and action/resistance symbols. Messages that mix this notation
with development-process text are replaced. Runtime and static checks use the
same case/separator normalisation. Ordinary engineering words are not banned in
isolation.

The syntax-tree inventory covers 3,106 UI, manual and report surfaces and finds
zero development-process candidates. A separate test-owned oracle scans the
manual PDF, accessible manual HTML and every report profile and finds zero hits.
An AST guard prevents exception, formatted-string or join laundering when an
authored message is constructed.

## AR-09: retained QA evidence

The workflow validator now pins exactly one unconditional real-figure report
render to `qa-artifacts/report`, exactly one unconditional real-figure manual
render to `qa-artifacts/manual`, and the complete `qa-artifacts/` upload. Names,
commands, destinations, execution conditions, upload action, missing-file
behaviour and retention period are exact.

The full test-and-coverage step, branch-coverage step and both real-render
steps must all precede the upload. A mutation that moves any evidence producer
after the upload fails the workflow validator.

The dependency validator independently pins its report to
`qa-artifacts/dependency-audit.json`. Negative mutations prove that removing or
renaming either render, masking it, changing a render destination, narrowing the
upload or relocating the dependency report all fail validation. The existing
exact test commands retain every coverage file, branch-coverage file and JUnit
result under the uploaded directory.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| AR05-01 | Concrete-only resultant is discussed | It is identified as `F_c`. |
| AR05-02 | Plastic total compression is published | It is identified as `F_comp` and defined as the total compression resultant. |
| AR05-03 | Compression reinforcement is present | The proved total includes its positive force contribution and exceeds the concrete-only resultant. |
| AR07-01 | A controlled engineering validation fails | The useful engineering reason and next action remain visible. |
| AR07-02 | A software diagnostic reaches a publication boundary | It is logged and replaced; no development term is visible. |
| AR07-03 | Manual and all report profiles are rendered | No development term, clipping or new layout failure is present. |
| AR07-04 | A validation reason contains familiar Eurocode notation | The factor name and field-specific correction remain visible and distinct. |
| AR07-05 | Raw text is harmless-looking or serialised/deserialised | It remains untrusted and is replaced. |
| AR07-06 | Authored copy and static copy inventory are checked | Both use identical normalisation and development-process detection. |
| AR09-01 | A real render step is removed, renamed, masked or redirected | Workflow validation fails. |
| AR09-02 | The QA upload is narrowed or masked | Workflow validation fails. |
| AR09-03 | The dependency report is relocated | Dependency-policy validation fails. |
| AR09-04 | A QA evidence-producing step is moved after upload | Workflow validation fails. |
| SCOPE-01 | Product identity and calculation scope are inspected | Sector remains 0.96, project format 27 and numerical behaviour is unchanged. |

## Verification evidence

- Compression-notation and evidence-retention suite: 131 passed.
- Superseding positive-provenance focused gate: 743 checks across capacity,
  project, fatigue, geometry, report, copy and actual UI boundaries; zero
  product failures.
- Independent raw-diagnostic result: **0 raw leaks; 0 false suppressions**.
- Static user-copy audit: 3,106 surfaces; zero development-process candidates.
- Independent publication extraction: manual PDF, accessible manual HTML and
  Brief, Standard and Audit PDFs contain zero oracle hits. Hostile injected
  result messages are hidden in every report profile.
- Ruff policy, strict mypy policy, bytecode compilation and diff-whitespace
  checks pass. Existing coverage-workflow and dependency-workflow policy gates
  remain unchanged.
- Sector remains 0.96 with project format 27. Exact-candidate adversarial review
  and exact-head CI remain the final gates before the separate release step.
