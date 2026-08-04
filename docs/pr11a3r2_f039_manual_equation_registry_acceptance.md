# PR-11A3R2 F039 manual equation-registry acceptance

## Exact base and independent recut

- Exact accepted base: `e25e730c5129a1b5f5a9a194e6bb91e2e5f761cf`.
- Base tree: `e6e3de5d543893b8f39ee63ec2f4f335fd68c8dc`.
- Sector remains version `0.91`.
- Family: visible Part C manual equations only.

PR #303 and both of its heads, `88d586a62aec7a00e4cb8844f5c17e1cda5e424e`
and `4106086db2e8025502780b9bafc07b869ff8ff47`, are rejected negative
evidence. This candidate was independently rebuilt from exact merged main, the
authored manual equations, retained solver/trace units, accepted report
contracts and existing local source identities. It reuses no code, patch, commit
or ancestry from PR #303.

## Frozen equation and publication identity

Exactly 32 authored Part C display equations are bound, in order, to their
section/subsection, section-based number, semantic public ID, deterministic
anchor and exact expression digest. The formula text remains authored only in
`manual.py`.

Before either renderer publishes, strict registration rejects an unknown,
missing, duplicate, moved, reordered or altered display equation. Segmentation
reconstructs every source Markdown block byte for byte. Each rendered record
contains:

1. stable equation number, public ID and anchor;
2. the exact authored expression;
3. its complete local Symbol / Meaning / Unit table;
4. an equation-specific dimensional-closure note;
5. genuine links to other numbered equations it uses;
6. an exact standard, mixed or project source/method line.

## Complete symbols and dimensional closure

- There are exactly 205 local symbol definitions. An independent formula-token
  audit proves that every identifier used by every expression reaches its own
  local inventory.
- The complete ordered symbol, source and dimensional-note inventories are
  separately SHA-256 sealed.
- Sources comprise 24 standard, six mixed and two project-defined equations.
  Project-defined content remains explicitly uncited.
- Nine genuine dependency links connect eight equations, including crack width
  to spacing, fatigue life to design range, Miner damage to life, the 2023 link
  relation to its link ratio, and torsion/shear interaction to both resistances.

The dimensional matrix closes every review-sensitive path:

- plastic and prestress curvature uses `1/m`, with solver coordinates and depths
  in `m`;
- the 2023 shear action-factor relation expresses `M_Ed/V_Ed`, `a_cs` and `d`
  coherently in metres and states the solver's equivalent stored-mm conversion;
- torsion retains `A_k` in `m2` and expresses `t_ef` in metres for the crushing
  equation, while documenting the retained mixed-unit steel kernel;
- the literal concrete-fatigue reference strengths 40 and 250 are explicitly
  defined in MPa;
- each interaction demand/resistance pair retains matching units;
- every registered unit passes through the real PDF converter with no residual
  caret or LaTeX command text, including the braced degree form.

## Focused evidence

- Final registry, adversarial, token-closure, dimension, Streamlit and A4 PDF
  gate: **50 passed**.
- Directly affected retained manual suite: **41 passed**.
- Directly affected publication-rhythm suite: **7 passed**.
- ASCII and version guards: **160 passed**.
- Pyflakes, byte compilation, import/registration smoke and diff checks: pass.
- Every pytest run used a new unique output parent and a previously absent
  `pytest-base`; no prior QA artifact was removed or overwritten.

## Explicit exclusions

- No generated-report equation contract or block change (PR-11A1/A2).
- No Figure/Table numbering, captions, references, repeated units or grayscale
  work (PR-11B).
- No shared publication style or structural/raster PDF preflight (PR-11C).
- No authored formula, solver, trace, mechanics, result, verdict, schema,
  persistence, package, workflow, version, PR-12+, signing, release or v0.93
  change.
