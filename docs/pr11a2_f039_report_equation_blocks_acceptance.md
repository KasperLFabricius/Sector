# PR-11A2 F039 generated-report equation-block acceptance

## Exact base and bounded scope

- Exact base: `96e1c5dfe9e6d48e9ff848ad025ed2806202b383`.
- Base tree: `82439dd47045243e098100fcdf67e5fa00b1a0e1`.
- Sector remains version `0.91`.
- This slice owns only the generated report's F039 equation-block presentation:
  role labels, result units, per-equation symbol definitions and long-expression
  wrapping.
- The accepted F038 public keys, numbering, anchors, same-subsection references,
  source/method notes and indivisible `_EquationFlowable` boundary remain intact.

No solver, formula text, numerical substitution, result value, applicability,
governing selection, verdict, standard selection or trace contract changes.

## Frozen retained inventory

- `app/sector_report.py` contains exactly 61 retained `_formula` calls and 57
  stable semantic keys.
- Every retained call resolves through the code-authored catalog. Production
  calls cannot provide an ad-hoc specification override.
- The catalog contains exactly 62 key/variant specifications:
  - the two concrete-strength laws use explicit `2005` and `2023` variants;
  - reinforced-shear `V_Rd,s` and `V_Rd,max` use explicit `2005` and `2023`
    variants;
  - the two retained 2005 crack-spacing branches use explicit `coarse` and
    `fine` variants;
  - the runtime chord-demand expression resolves explicitly to its `2005` or
    `2023` symbol inventory;
  - the code-controlled steel material ordinal resolves to the single wildcard
    catalog identity without accepting a user-shaped key.
- Forty-five calls publish results and require a non-blank canonical result unit.
  Sixteen relations publish no result and are forbidden from advertising one.

## Standard block and symbol contract

Each published block has this exact semantic order:

1. stable public identity;
2. `Symbolic expression`;
3. optional `Numerical substitution`;
4. optional `Result` followed by its mandatory `Unit`;
5. `Symbols` followed by one row per code-authored symbol;
6. optional prior-equation references;
7. retained `Source / method note`.

Every symbol row contains a non-blank display name, contextual meaning and unit.
Names are unique within their equation variant. Canonical units follow the trace
vocabulary (`1`, `mm`, `m`, `mm2`, `m2`, `kN`, `kNm`, `MPa`, `cycles`, and the
explicit compound/context units required by the equation). The accepted trusted
notation layer supplies superscripts and Greek display tokens; literal user text
does not enter the catalog.

The catalog is publication data only. It neither evaluates formula strings nor
creates another mechanics engine. Branch-specific symbol sets describe the exact
already-authored expression selected by the retained report code.

## Failure and layout contract

- A blank expression, substitution or result fails before numbering/publication.
- An unknown key/variant, malformed specification, missing required result,
  result without a unit, or combined variant/override fails atomically: no flow,
  number or equation-register state is consumed.
- Catalog construction rejects missing, blank or duplicate symbol definitions and
  blank result units.
- Expression and symbol styles explicitly retain left-to-right wrapping and long
  word splitting. A real A4 PDF probe freezes a long unbroken expression plus 12
  symbol rows inside one complete equation block without horizontal overflow or
  a layout exception.
- Every child paragraph carries its semantic role. Symbol rows additionally carry
  their immutable `(name, meaning, unit)` tuple, while the parent flowable carries
  the complete symbol inventory and result unit for audit probes.

## Focused evidence required

- Catalog/AST completeness and exact result-unit co-occurrence.
- Standard role order, flowable metadata, extracted PDF labels and notation.
- Parameterized malformed-content/specification and atomic-recovery probes.
- Long-expression and dense-symbol A4 wrapping.
- Accepted F038 identity/source/link/grouping regressions.
- Directly affected retained report, vertical-rhythm, pagination and F032 table
  layout suites.
- ASCII/version, pyflakes, compile, import and diff guards.

All pytest runs use a new unique output parent and a previously absent
`pytest-base`; no prior QA artifact is removed or overwritten.

## Explicit exclusions

- No manual equation catalog, numbering, symbols or cross-reference change
  (PR-11A3).
- No Figure/Table numbering, captions, repeated units or grayscale work
  (PR-11B).
- No shared manual/report publication-style extraction or structural/raster PDF
  preflight (PR-11C).
- No UI, persistence, schema, trace, solver, mechanics, package, workflow,
  application-version, PR-12+, release, signing or v0.93 change.
