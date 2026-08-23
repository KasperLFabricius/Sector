# PR-08 acceptance - publication navigation and page composition

## Frozen base and product boundary

- Base: `42a6b100af81946595850dcb0cb069d7b335be0c` (`origin/main`
  after PR-07).
- Base tree: `4dc503c7a62becd7f674cd63185071263dc95495`.
- Decision owner: D096-017; finding owner: F096-012.
- Product version remains `0.95`; project schema remains `27`.

PR-08 changes report navigation, pagination and typesetting only. It does not
change a solver, input, equation, applicability rule, governing selector,
comparison, numerical value, persistence field, schema or package surface.
Brief retains the complete effective inputs required by its active reported
results; navigation and pagination do not reduce that inventory.

## Visible navigation contract

Every report profile has a visible, clickable contents block after the cover.
Brief and Standard list their numbered top-level calculation sections. Audit
also lists numbered subsections because its reconstruction depth makes those
destinations useful. Contents entries show resolved page numbers and target
the same named destinations as the PDF outline. The cover is not repeated as a
contents entry.

Report section and subsection destination keys are deterministic and unique.
A contents link and an outline entry must resolve to the page containing the
matching visible heading. Adding navigation does not change which engineering
sections a profile includes.

## Composition and typesetting contract

- No profile has a hard or target page count, or a page-target exception
  workflow. Readability and information depth control composition.
- A numbered heading remains with substantive following content. Routine Audit
  chapters flow continuously instead of forcing a new page for every check;
  deliberate document boundaries such as cover, contents and appendix remain.
- A between-row table continuation contains at least two complete data rows
  whenever the table has enough rows to form two meaningful fragments. A
  caption/header-only or one-complete-row continuation is not produced.
- A subgroup heading inside a table cannot be separated from its first data
  row. Results Overview group labels therefore never appear alone at a page
  foot.
- Continued tables retain their caption identity, column headings and the
  context needed to interpret the rows on that page.
- Table and figure captions retain labels and destinations, but the redundant
  self-reference `See Table/Figure ...` is removed. Automatically generated
  captions use the section subject directly rather than generic `Reported
  information for ...` boilerplate.
- Figures remain intact with their captions. No figure identity, report-profile
  figure policy or engineering result changes.

## Retained diagnostic composition

The inherited Standard-profile fatigue edge is part of this slice. When no
converged governing reinforcement example exists but retained simplified
screens are invalid, Standard publishes every retained invalid screen together
with its element, detail class, range basis, reason and source. It does not
silently remove the diagnostic rows, select an invalid row as governing or
manufacture a verdict. Brief and Audit retain their already-correct depth.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| PC96-01 | Brief, Standard and Audit are rendered | Each has visible linked contents; entries and page numbers resolve to matching headings. |
| PC96-02 | Report profiles are inspected | No hard/target page count or exception flags remain; numerical/profile depth is unchanged. |
| PC96-03 | A heading lands near a page foot | It moves with substantive following content and is not orphaned. |
| PC96-04 | A long table splits | Every ordinary continuation has meaningful data, repeated headings and its continued caption/context. |
| PC96-05 | Results Overview splits at a group boundary | The group label and first child row remain together. |
| PC96-06 | Table and figure publication text is scanned | Captions remain; redundant self-referential `See Table/Figure` and generic caption boilerplate are absent. |
| PC96-07 | Standard has retained INVALID fatigue screens but no governing example | All retained invalid screen details are published without a manufactured governing selection or verdict. |
| PC96-08 | Scope and identity are compared with the base | Inputs, equations, values, statuses, selection, profile depth, schema 27 and product version 0.95 are unchanged. |

## Verification order

1. New structural contents, destination, pagination, caption and retained-
   diagnostic adversarial tests.
2. Existing report profile, outline, table pagination/colocation, equation
   pagination and rendered-publication tests affected by composition.
3. Targeted compile, Ruff, ASCII-source, version, schema and diff guards.
4. Real Brief, Standard and Audit PDFs with extracted-text, object/navigation,
   every-page density and focused raster inspection.
