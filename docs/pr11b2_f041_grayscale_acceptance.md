# PR-11B2 / F-041 grayscale-publication acceptance

## Exact boundary

- Exact base: `ed20ae984165750fc1a560d591ac9b1e1a3d1fe9`.
- Sector version: `0.91`, unchanged.
- Scope: deterministic non-colour identities for Plotly publication series.
- PR #319 head `fd9728bddd5f33a4608e92bd8c9ea628312f57b1`
  is rejected and excluded from reuse.

PR-11B1 owns numbering, captions, references and pagination. This slice changes
no publication geometry, solver, formula, material, result, verdict, standard,
project schema or calculation-trace behavior.

## Frozen inventory and boundaries

All 17 public Plotly figure factories are finalized:

1. elastic strain;
2. concrete, prestress and reinforcement material laws;
3. section geometry;
4. fatigue utilisation, S-N and damage;
5. detailing, directional shear and biaxial shear geometry;
6. M-M, N-M and V-T interaction;
7. torsion tube and subtube; and
8. variable-strut truss.

The generated-report and both manual publication boundaries also finalize a
direct caller/manual-owned figure. Non-Plotly timeout doubles remain inert.

## Authored-cue preservation

Before changing a default, the finalizer inventories every explicitly authored
line dash, marker symbol and bar pattern across all visible named legend series.
Fallbacks cannot consume those reserved cues. A default series therefore cannot
force a later authored semantic series to be rewritten.

Existing authored dashes, symbols and patterns remain exact. If two authored
series deliberately start with the same primary cue, the later series gains a
secondary marker, dash, width, size or pattern-solidity cue while retaining its
authored primary identity.

Array-valued marker symbols and sizes use Plotly's first rendered legend glyph
for comparison. An omitted scatter mode resolves to Plotly's point-count default
(`lines+markers` below 20 points, otherwise `lines`) before cues are compared.

The transformation is deterministic and idempotent. It changes no coordinates,
values, colours, names, axes, annotations or engineering state. Unnamed,
legend-disabled and invisible series are not advertised and remain untouched.
If the supported channels cannot produce a unique cue, publication fails
explicitly instead of silently retaining a colour-only distinction.

## Focused evidence

- Defaults before later explicit `dot` and `dash` traces cannot consume either
  authored cue; data and colours remain exact and a second pass is inert.
- Marker and bar adversaries reserve a later `diamond` and `/` pattern.
- Duplicate authored primary cues retain the primary and gain a secondary cue.
- Array/scalar marker aliases and implicit/explicit scatter modes cannot conceal
  duplicate rendered legend glyphs.
- Every public factory exposes the finalization contract.
- Manual and report export-boundary adversaries cover direct figures.
- The complete retained `tests/test_viz.py` group remains authoritative for
  every existing plot value, label, axis and semantic identity.

## Explicit exclusions

- Shared publication style and structural/raster PDF preflight: PR-11C / F-042.
- The targeted Plotly/Kaleido server `kopts` warning correction: PR-11C.
- Calculation-trace restoration or an optional trace toggle.
- PR-12+, packaging, signing, release, version or v0.93 roadmap work.
