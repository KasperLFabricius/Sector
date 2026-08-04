# PR-11A2b F039 report equation-block acceptance

## Exact base and bounded purpose

- Exact accepted base: `6d3336867ddaa449f9887551c96b76125dedb6c5`.
- Base tree: `2e4ade610b88721c3e29e6aa900c8c5f09c65ff0`.
- Sector remains version `0.91`.
- Family: visible generated-report equation blocks only.
- PR-11A2a supplied the complete immutable semantic contracts. This slice
  renders those accepted contracts without changing solver mechanics, values,
  sources, verdicts or equation identities.

The rejected PR #300 head `75e3056d3eb2663892b07a7d6a7373dec48c159a`
remains negative evidence only. No code, patch, commit or ancestry from that head
is reused.

## Frozen visible block

Every one of the 62 accepted key/variant contracts now renders in this exact
role order:

1. stable equation number and public semantic ID;
2. labelled symbolic expression;
3. either a labelled numerical substitution, a labelled applicability/method
   note, or no intermediate row, as required by the contract;
4. for result equations, a labelled canonical result symbol and unit followed by
   the retained published result;
5. a Symbols heading and one ordered row for every contracted symbol, meaning
   and unit;
6. existing Uses links when present;
7. the existing source/method note.

Every paragraph carries an auditable row role. Every symbol row also carries its
exact immutable `EquationSymbol` identity. The equation flowable retains the
complete ordered role vector alongside the existing key, variant, number,
section, subsection, result and symbol metadata.

Dimensionless results represented as percentages say both facts explicitly:
`dimensionless; displayed as %`. Relation-only equations publish no fabricated
result row. Applicability prose cannot be labelled as a numerical substitution.

## Mathematical notation and layout

- Existing Greek rendering and the shared F040 notation layer remain the single
  general notation path.
- Equation-only ASCII tokens `Delta` and `sum` render as the mathematical Delta
  and summation glyphs. Prose meanings containing the word `sum` remain prose.
- Expression and symbol rows use explicit left-to-right wrapping with long-word
  splitting.
- A focused A4 probe renders the longest unbroken synthetic expression together
  with the maximum retained eight-symbol inventory on one page and proves the
  final expression and symbol tokens survive extraction.
- The complete equation remains an indivisible `_EquationFlowable`; released
  oversized surrounding groups still cannot split its audit text.

## Publication terminology closure

Rendering the previously inert symbol meanings exposed one retained terminology
conflict: both concrete-strut interaction equations described their final
`interaction` quantity as a crushing utilisation. Their symbol meaning is now
`combined concrete-strut interaction value`, matching the actual published
result identity and the retained report assertion. No equation, result value,
verdict or mechanics changed.

## Focused evidence

- Final consolidated equation contract/layout/identity gate: **93 passed**.
- Catalogue-wide visible-role probes cover all 62 key/variant contracts.
- Directly affected retained report run: **102 passed** before the sole
  terminology assertion; the corrected assertion plus both terminology
  contracts then passed **3 localized tests** on the final code. Unchanged broad
  evidence was not rerun after that localized wording correction.
- Pagination, table-layout, vertical-rhythm and rendered-report suites:
  **35 passed**.
- Long-expression A4 extraction, role-order, canonical-alias, percentage-unit,
  note/substitution fencing and math-token prose probes: passed.
- All pytest runs used a new unique output parent and a previously absent
  `pytest-base`; no prior QA artifact was removed or overwritten.

## Explicit exclusions

- No manual equation catalog, numbering, symbols or cross-references (PR-11A3).
- No Figure/Table numbering, captions, repeated units or grayscale work
  (PR-11B).
- No shared manual/report publication-style extraction or structural/raster PDF
  preflight (PR-11C).
- No solver, trace, calculation mechanics, standard applicability, source,
  numerical value, verdict, schema, UI, persistence, package, workflow,
  application-version, PR-12+, signing, release or v0.93 change.
