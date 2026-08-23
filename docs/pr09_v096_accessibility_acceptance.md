# PR09 v0.96 accessibility and clean text-layer acceptance

## Frozen base and scope

- Exact base commit: `c132d391184f95bef839ce1eb60b86a740eedb86`
- Exact base tree: `87d2a8ea502f731d519c6fc1e2465b9ffaacf114`
- Product version remains `0.95`; project schema remains `27`.
- This PR owns D096-018 and findings F096-013/F096-014 only.
- It changes publication navigation, alternatives, math presentation, metadata,
  extracted text and their QA controls. It does not change solver inputs,
  solver values, applicability, governing selections, conclusions or the
  Brief/Standard/Audit depth contract.

## Accessible HTML manual

The self-contained HTML manual has one keyboard-focusable skip link as the
first body control. It targets the one main-content landmark and becomes
visibly apparent when focused.

Every governed manual figure has a separately authored text alternative that
describes the important geometry, curves, axes, states or comparisons in the
figure. An alternative is not accepted when it merely repeats the caption.
Figure identities, captions and alternatives remain fail-closed against the
authored figure inventory.

Inline, display and governed-equation math is emitted as safe semantic HTML:
Unicode mathematical characters and real `sub`/`sup` elements are visible,
and every math object has a clean plain-text accessible name. Raw TeX commands,
escaped pseudo-tags and the former malformed `N^*` emphasis artifact are not
present in the issued HTML. The HTML remains JavaScript-free, self-contained
and within the generator-owned vocabulary.

## PDF metadata and extracted text

The manual PDF and every report profile declare English document language in
the PDF catalogue. No claim of tagged-PDF or accessibility certification is
made.

Searchable equation alternatives use the user-facing prefix `Mathematical
expression:`. Extracted/copied text contains neither `SECTOR-MATH[...]` nor
`SECTOR-SOURCE-END[...]` QA tokens. Removing those tokens does not weaken the
structural QA contract: equation identities, semantic rows and complete visible
source/method notes remain counted and colocated by document objects and page
text.

## Adversarial acceptance matrix

| ID | Case | Required outcome |
|---|---|---|
| AC96-01 | Keyboard enters the HTML document | Skip link is first, visible on focus and targets the unique main landmark. |
| AC96-02 | Every governed figure is inspected | One non-empty alternative per figure; no alternative equals its caption. |
| AC96-03 | Inline, display and governed math is parsed | Real `sub`/`sup`, clean accessible names and no raw TeX or pseudo-tags. |
| AC96-04 | Generated-envelope parser sees a hostile tag, class or attribute | It fails closed; the newly governed safe vocabulary passes. |
| AC96-05 | Brief, Standard, Audit and manual PDFs are opened strictly | Every catalogue declares `/Lang` as `en`. |
| AC96-06 | PDF text is copied/extracted | No hidden Sector QA/source marker token is exposed. |
| AC96-07 | Equation/source colocation is challenged at a page boundary | Each indivisible equation retains its identity, semantic rows and visible source note. |
| AC96-08 | Publication outputs are rasterised | No clipping, overlap, blank page or visual equation regression is introduced. |

## Required evidence

1. New PR09 HTML parser, figure-alternative, semantic-math, PDF metadata and
   clean-text tests.
2. Existing generated-envelope, manual/report equation, profile, strict-PDF
   and publication preflight suites.
3. Browser inspection of the generated HTML at the skip link, representative
   figure alternative, inline math and governed equation where the QA host
   permits local-file navigation. If host policy blocks the local file, the
   same acceptance is evidenced by the fail-closed DOM/parser contract,
   explicit focus-style assertion and visual inspection of the issued PDF.
4. Rendered manual and report artifact checks plus compile, Ruff, diff, version,
   schema and scope guards.
