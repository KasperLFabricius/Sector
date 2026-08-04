# PR-11A3 F039 manual equation-catalog acceptance

## Exact base and bounded purpose

- Exact accepted base: `e25e730c5129a1b5f5a9a194e6bb91e2e5f761cf`.
- Base tree: `e6e3de5d543893b8f39ee63ec2f4f335fd68c8dc`.
- Sector remains version `0.91`.
- Family: visible Part C manual equations only.
- The 32 existing authored display equations remain the sole formula text. This
  slice binds them to immutable public identities, positions, symbol inventories,
  provenance and genuine prior-equation links, then publishes those records in
  the Streamlit manual and generated manual PDF.

No rejected or superseded PR head is reused as code, patch, commit or ancestry.

## Frozen equation inventory

The exact ordered manual numbers are:

`C.3.1-1`, `C.3.2-1`, `C.3.3-1`, `C.4.2-1`, `C.5.1-1`, `C.5.2-1`,
`C.5.2-2`, `C.5.3-1`, `C.5.4-1`, `C.5.4-2`, `C.5.4-3`, `C.7.2-1`,
`C.7.2-2`, `C.7.5-1`, `C.7.5-2`, `C.8.1-1`, `C.8.2-1`, `C.8.2-2`,
`C.8.2-3`, `C.8.4-1`, `C.8.4-2`, `C.8.4-3`, `C.8.4-4`, `C.9-1`,
`C.9-2`, `C.9-3`, `C.9.1-1`, `C.9.1-2`, `C.10-1`, `C.10-2`,
`C.11-1`, `C.11-2`.

Each equation has one semantic key, public `MEQ-...` identity and deterministic
anchor. Its exact part, section, subsection, number and normalized expression
digest are pinned. Strict segmentation rejects an unknown, missing, duplicate,
moved, reordered or altered display equation before either publication surface
can render it, while reconstructing every original Markdown block byte for byte.

## Symbols, sources and dependencies

- The catalogue contains exactly 208 ordered symbol rows. Each row retains its
  LaTeX identity, plain-language meaning and unit.
- Source identity is complete for all 32 equations: 24 standard, six mixed
  standard/project and two project-defined equations.
- Project-defined relations say `Project-defined / uncited.`. Mixed relations
  expose both the standard source and the project-defined/uncited part.
- The complete ordered source inventory and complete ordered symbol inventory
  are independently SHA-256 sealed in the focused tests.
- Internal plastic/prestress curvature retains the solver and glossary unit
  `1/m`; its strain-gradient coordinates and compression depth retain metres.
- Every catalogued unit is passed through the real PDF converter in the focused
  gate. The degree unit uses supported braced superscript syntax, and no unit
  leaves a literal caret or LaTeX command in ReportLab markup.
- Only four genuine equation dependencies are published: reinforcement fatigue
  life uses the design stress range; reinforcement Miner damage uses life;
  torsion/shear interaction uses torsion resistance; and combined strut
  interaction uses torsion/shear interaction.

The concrete Curve 2 source distinguishes the 2005 Formula (3.17)/Table 3.1
path from the 2023 Formula (8.4) path and retains 5.1.6(1) only for the 2023
design-strength factors.

## Publication rendering

Both manual surfaces show, for every catalogued equation:

1. stable equation number, public semantic ID and anchor;
2. the exact authored display expression;
3. every ordered symbol, meaning and unit;
4. genuine prior-equation links, when present;
5. exact standard, mixed or project source identity.

The PDF keeps each identity/expression/symbol/source record together where it
fits, uses explicit left-to-right mathematical wrapping and permits long-token
splitting. A focused A4 extraction proves all 32 public IDs survive rendering.

## Focused evidence

- Corrected-head manual catalogue, adversarial, Streamlit, symbol-unit and A4
  PDF gate: **47 passed**.
- Directly affected retained manual suite: **41 passed**.
- Retained vertical-rhythm run: **6 passed** before its sole strict-boundary
  fixture was updated; the corrected fixture and new equation style probe then
  passed **2 localized tests** on the final code. Unchanged broad evidence was
  not rerun after that test-only fixture correction.
- ASCII and version guards: **160 passed**.
- `pyflakes`, `py_compile`, import smoke and Markdown/equation count smoke: clean.
- Every pytest run used a new unique output parent and a previously absent
  `pytest-base`; no prior QA artifact was removed or overwritten.

## Explicit exclusions

- No generated-report equation contract or block change (PR-11A1/A2).
- No Figure/Table numbering, captions, references, repeated units or grayscale
  work (PR-11B).
- No shared manual/report publication-style extraction or structural/raster PDF
  preflight (PR-11C).
- No authored manual formula, solver, trace, calculation mechanics, standard
  applicability, result, verdict, schema, persistence, package, workflow,
  application-version, PR-12+, signing, release or v0.93 change.
