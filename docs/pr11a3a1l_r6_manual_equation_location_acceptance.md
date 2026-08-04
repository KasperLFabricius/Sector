# PR-11A3a1L R6 - manual equation identity and authored location

## Exact base and independent recut

- Base commit: `e25e730c5129a1b5f5a9a194e6bb91e2e5f761cf`.
- Base tree: `e6e3de5d543893b8f39ee63ec2f4f335fd68c8dc`.
- Base parent: `6d3336867ddaa449f9887551c96b76125dedb6c5`.
- Application version: `0.91` and unchanged.
- This is a new implementation derived from the exact merged manual block stream.
  It does not reuse a file, patch, commit, branch or ancestry from any rejected
  PR head.
- The two PR #307 heads `65238faf46bad963c796d3923baee09f40595247`
  and `e0bfbb6e60b7f7b86a18b22abdb2cd034f24a50d` join the rejected-head set.

## Frozen catalogue

Exactly 32 authored display equations are registered, in this order:

| Number | Semantic key | Section | Subsection |
|---|---|---|---|
| C3-1 | `manual.material.concrete-law` | Material laws | Concrete (parabola-rectangle) |
| C3-2 | `manual.material.steel-law` | Material laws | Mild steel |
| C3-3 | `manual.material.prestress-law` | Material laws | Prestressing steel |
| C4-1 | `manual.plastic.governing-curvature` | Plastic capacity analysis | The governing curvature |
| C5-1 | `manual.detailing.minimum-2005` | Reinforcement detailing | EN 1992-1-1:2005 and DK NA:2024 |
| C5-2 | `manual.detailing.minimum-2023-bending` | Reinforcement detailing | EN 1992-1-1:2023 |
| C5-3 | `manual.detailing.minimum-2023-axial` | Reinforcement detailing | EN 1992-1-1:2023 |
| C5-4 | `manual.detailing.clear-spacing` | Reinforcement detailing | Clear spacing |
| C5-5 | `manual.detailing.links.minimum-ratio` | Reinforcement detailing | Shear and torsion reinforcement |
| C5-6 | `manual.detailing.links.spacing` | Reinforcement detailing | Shear and torsion reinforcement |
| C5-7 | `manual.detailing.torsion.minimum-ratio` | Reinforcement detailing | Shear and torsion reinforcement |
| C7-1 | `manual.crack.2005.width` | Serviceability: cracking and crack width | Crack width - EN 1992-1-1:2005 |
| C7-2 | `manual.crack.2005.spacing` | Serviceability: cracking and crack width | Crack width - EN 1992-1-1:2005 |
| C7-3 | `manual.crack.2023.width` | Serviceability: cracking and crack width | EN 1992-1-1:2023 refined model |
| C7-4 | `manual.crack.2023.spacing` | Serviceability: cracking and crack width | EN 1992-1-1:2023 refined model |
| C8-1 | `manual.fatigue.stress-range` | Grouped fatigue | Elastic stress ranges |
| C8-2 | `manual.fatigue.reinforcement.design-range` | Grouped fatigue | Reinforcement S-N and Miner check |
| C8-3 | `manual.fatigue.reinforcement.life` | Grouped fatigue | Reinforcement S-N and Miner check |
| C8-4 | `manual.fatigue.reinforcement.miner` | Grouped fatigue | Reinforcement S-N and Miner check |
| C8-5 | `manual.fatigue.concrete.strength-2005` | Grouped fatigue | Concrete compression fatigue |
| C8-6 | `manual.fatigue.concrete.strength-2023` | Grouped fatigue | Concrete compression fatigue |
| C8-7 | `manual.fatigue.concrete.life` | Grouped fatigue | Concrete compression fatigue |
| C8-8 | `manual.fatigue.concrete.equivalent` | Grouped fatigue | Concrete compression fatigue |
| C9-1 | `manual.shear.no-links.variable` | Shear resistance without shear reinforcement | *(H1 level)* |
| C9-2 | `manual.shear.no-links.minimum` | Shear resistance without shear reinforcement | *(H1 level)* |
| C9-3 | `manual.shear.action-factor-2023` | Shear resistance without shear reinforcement | *(H1 level)* |
| C9-4 | `manual.shear.links-2005` | Shear resistance without shear reinforcement | Members with shear reinforcement (links) |
| C9-5 | `manual.shear.links-2023` | Shear resistance without shear reinforcement | Members with shear reinforcement (links) |
| C10-1 | `manual.torsion.resistance` | Torsion (thin-walled tube) | *(H1 level)* |
| C10-2 | `manual.torsion.strut-interaction` | Torsion (thin-walled tube) | *(H1 level)* |
| C11-1 | `manual.combined.strut-interaction` | Combined M-V-T interaction | *(H1 level)* |
| C11-2 | `manual.combined.utilisation` | Combined M-V-T interaction | *(H1 level)* |

Each catalogue record freezes its contiguous ordinal, semantic key, public
number, exact Part C name, section, subsection and SHA-256 of the whitespace-
normalised ASCII expression. C10-2 and C11-1 deliberately retain distinct
identities despite sharing the same Formula (6.29) expression.
The complete catalogue seal is
`68a50835e369abfde610085c040a7b934a87634d6a0271fa596f63088ab45579`.

## Complete Part C boundary

- A manual block must remain a tuple with at least a string kind and payload.
- `part`, `h1`, `h2` and `md` primary payloads retain string type.
- Within Part C, every structural primary payload and every structural extra
  field is recursively scanned for display delimiters before headings change.
- A Part C Markdown primary payload is the only place a display may exist. Every
  `$$` delimiter must belong to a paired, non-empty ASCII display expression.
- Every textual key or value nested in an excluded callout, table, mapping,
  sequence, set, unknown sibling or cyclic container is inspected without
  trusting a fixed tuple position.
- Display equations outside Part C are inert and do not change the catalogue.
- Missing, duplicate, extra, reordered, moved or expression-mutated Part C
  displays fail closed. A valid-looking coherently resealed catalogue also fails.

## Evidence matrix

- Exact catalogue order, cardinality, locations, digests and full-catalogue seal.
- Parameterised mutation of every retained catalogue field.
- Missing, duplicate, reordered and extra equation probes.
- Primary-payload and extra-field probes for each Part C structural block kind.
- Nested callout, table, mapping, sequence, set and cyclic-container probes.
- Empty, adjacent, unpaired and non-ASCII display probes.
- Non-tuple, short, non-string-kind and non-string-structural-payload probes.
- Explicit inert probes for display content in Parts A, B and D.
- Import/scope guard proving no manual renderer, solver, source, symbol, unit,
  dimensional, dependency or report-equation contract is introduced.

## Explicit exclusions

- No standard, project or mixed source kind and no citation text.
- No symbol, unit, dimensional or dependency inventory.
- No PDF or Streamlit rendering and no visible publication block.
- No solver, mechanics, resistance, demand, utilisation, verdict, trace,
  report-equation or application behaviour change.
- No figure/table numbering, captions, repeated units, grayscale, shared style,
  PDF preflight, schema, persistence, workflow, package, signing, version,
  PR-12+, release or v0.93 work.
