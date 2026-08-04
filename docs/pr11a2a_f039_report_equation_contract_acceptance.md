# PR-11A2a F039 report equation contract acceptance

## Exact base and bounded purpose

- Exact accepted base: `96e1c5dfe9e6d48e9ff848ad025ed2806202b383`.
- Base tree: `82439dd47045243e098100fcdf67e5fa00b1a0e1`.
- Sector remains version `0.91`.
- Family: generated-report equation semantic contracts only.
- This is the independently required contract half of F039. PR-11A2b owns
  visible role labels, result/unit rows, symbol rows and long-expression layout.

The rejected PR #300 head `75e3056d3eb2663892b07a7d6a7373dec48c159a`
is negative evidence only. No code, patch, commit or ancestry from that head is
reused.

## Frozen inventory

The merged report has 61 live `_formula` call sites and 57 semantic keys. Five
keys have independently required variants, producing 62 exact contracts:

- concrete design strength: 2005 and 2023;
- link-yield shear resistance: 2005 and 2023;
- maximum link/strut shear resistance: 2005 and 2023;
- longitudinal shear chord demand: 2005 and 2023;
- 2005 crack spacing: geometric and reinforcement expressions.

The dynamic mild-steel key retains the concrete material ordinal pattern
`materials.steel.fyd-N`; every positive integer ordinal resolves to one contract
without weakening the exact public key stored on its equation flowable.

Every contract pins:

- equation key and required variant;
- every advertised symbol, its meaning and its unit;
- the exact final result symbol and final unit, or relation-only status;
- one intermediate-evidence role: `numerical`, `applicability-note`, or `none`.

The frozen cardinalities are:

- 62 key/variant contracts;
- 46 result contracts and 16 relation-only contracts (the second runtime branch
  of `shear.chord.demand` accounts for the one-contract excess over call sites);
- 42 numerical-intermediate contracts;
- 2 applicability-note contracts;
- 18 contracts with no intermediate row.

## Validation and dependency closure

The live builder resolves the contract before numbering or publication. Unknown
keys, missing/unknown variants, blank symbolic expressions, missing results,
unexpected results, and intermediate evidence supplied through the wrong sibling
field fail before the equation number, registry or flow is changed.

The resolved immutable contract reaches the equation flowable as:

- exact variant;
- complete ordered symbol tuple;
- final result symbol;
- final result unit;
- intermediate-evidence role.

Production call sites cannot supply an override contract. A typed override exists
only so the existing synthetic identity probes can exercise arbitrary keys; an AST
guard proves no retained production call uses it.

## Rejected-review regression closure

The two independent PR #300 review classes are separated structurally:

1. `combined.dk-na.sum` and the geometric `crack.2005.spacing` branch pass prose
   through the dedicated `note` field and retain the role
   `applicability-note`. A prose note can no longer occupy the numerical
   substitution field, and a numerical substitution cannot occupy the note field.
2. `crack.2023.width` declares both `w_k,cal` and the published `w_k`; the latter
   is the exact final result symbol and is explicitly defined as equal to the
   calculated value.

The visible text remains unchanged in this contract slice. PR-11A2b will render
the pinned roles and symbol/unit inventory without changing the authored
expressions, values, sources, verdicts or equation identities.

## Focused evidence

- Independent contract and retained equation-identity tests: 24 passed.
- Directly affected retained report suite: 103 passed.
- Directly affected pagination, table-layout and vertical-rhythm suites: 33 passed.
- ASCII and version guards: 157 passed.
- Catalogue/runtime inventory: all 61 calls covered by exactly 62 contracts.
- Pyflakes, byte compilation, import smoke and diff checks: passed.
- All pytest runs use a new unique parent and previously absent `pytest-base`;
  no prior output is removed or overwritten.

## Explicit exclusions

- No visible standardized equation-block redesign (PR-11A2b).
- No manual equation catalog, numbering, symbols or cross-references (PR-11A3).
- No figure/table numbering, captions, repeated units or grayscale changes
  (PR-11B).
- No shared report/manual publication-style extraction or structural/raster PDF
  preflight (PR-11C).
- No solver, mechanics, values, source identities, verdicts, trace, schema, UI,
  persistence, package, workflow, version, PR-12+, signing or v0.93 change.
