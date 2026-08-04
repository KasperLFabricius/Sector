# PR-10B1a2 acceptance matrix - F032 report table widths

Exact base: `af2a835c3da31adc41ac3075dee0fb794ffa305b`

## Frozen scope

- Generic report tables retain at least 7.2 pt type.
- Escaped user identities and descriptions carry an explicit literal cell role.
  Their digit-only segments remain losslessly wrappable and cannot be mistaken
  for numerical evidence because of punctuation or whitespace.
- Numerical body cells are measured from markup-aware source text. Every concrete
  numeric word retains an indivisible width floor when bare, beside a unit or
  annotation, or immediately before a ReportLab line-break tag.
- Escaped mixed equation cells identify their structured substitution and result
  evidence explicitly; escaping provenance cannot make used numbers inert, while
  equation identities remain losslessly wrappable.
- Authored widths are reallocated inside the 170 mm A4 frame without crossing
  content floors. Wider tables become ordered sequential panels; configured
  leading identity columns repeat, and each panel lists its source headers.
- Composite row identities are explicit at production call sites. Case and
  description, case/description/part, spectrum/bin/description, scope/check,
  geometric point/ring indices, element/material/state, crack candidate keys,
  equation/result, and fatigue detail/result identities remain present on every
  panel where their table can split horizontally.
- Missing, empty, ragged and width/cardinality-mismatched table inventories fail
  before rendering. A single numeric atom wider than A4 fails explicitly.
- Small and dense fixtures preserve ordering and token cardinality and rasterise
  with white A4 page edges.

## Review regressions frozen before publication

- Mixed cells retain numeric atoms independently of their units and annotations.
- Digit-only segments inside published bin identities remain wrappable, including
  after hyphen, slash, colon and whitespace separators.
- A numeric value followed by `<br/>` retains the line break as a token boundary;
  a following method annotation cannot mask the evidence width.
- Plastic, elastic and grouped-fatigue load tables freeze repeat counts of two,
  three and three respectively; an elastic short-term row cannot lose its `Part`
  identity when its case/description cells are intentionally blank.

## Explicit exclusions

- No vertical splitting, in-row fragmentation, continuation context, three-row
  fragment rule, Results-overview routing, loads/settings page sequencing,
  formula/status/manual spacing, mechanics, provenance, notation, schema, UI,
  persistence, package, workflow or version change.
- F019 vertical pagination remains PR-10B1b. Remaining F019 page rhythm and F037
  vertical geometry remain PR-10B2.
- Rejected #292, #293 and #294 heads are negative evidence only and absent from
  this candidate ancestry.
