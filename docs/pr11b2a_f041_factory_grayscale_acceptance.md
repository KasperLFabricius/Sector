# PR-11B2A / F-041 factory-grayscale acceptance

## Exact boundary

- Exact base: `ed20ae984165750fc1a560d591ac9b1e1a3d1fe9`.
- Sector version: `0.91`, unchanged.
- Scope: visible non-colour identities authored by Sector's 17 Plotly factories.
- Rejected PR #321 heads
  `b139ed7b7b7c366aafefc6f45704134636879386` and
  `14b923ecc8a0cae798321e501727d69f1e253f65` are negative evidence only and
  are excluded from reuse.

This reslice introduces no generic Plotly post-processor and does not mutate an
arbitrary caller-owned figure at a Streamlit or PDF boundary. Every changed cue
is authored where the program-owned semantic trace is created.

## Frozen factory inventory

The independent inventory constructs all 17 public figure families:

1. elastic strain;
2. concrete, prestress and reinforcement material laws;
3. section state;
4. fatigue utilisation, S-N and damage;
5. detailing geometry;
6. directional and biaxial shear geometry;
7. M-M, N-M and V-T interaction;
8. torsion tube and subtube; and
9. variable-strut truss.

Only visible named legend traces are advertised. Layout-disabled legends,
unnamed traces, hidden traces and traces with `showlegend=False` remain outside
the inventory.

## Authored visible channels

- Compression and tension section zones retain their exact polygon coordinates
  and fill colours, and gain positive-width solid/dashed neutral outlines.
- Material element keys use circles and diamonds; sign-state keys use neutral
  square and square-x glyphs, avoiding array/scalar aliases in the rendered
  legend.
- The detailing inclusion highlight remains circle-open, while the governing
  spacing pair is diamond-open.
- The torsion outline receives its explicit rendered width.
- Compression chord, tension chord, strut and link identities use authored
  solid, dashed, width and dotted channels.

The test oracle resolves Plotly's rendered marker-array first value and rendered
line/marker defaults independently. Colour is absent from every comparison.
Every advertised trace must have a visible line, marker, fill or bar channel,
and all cues within a factory output must be unique.

## Focused evidence

- All 17 factory families have unique visible non-colour legend identities.
- Section zone boundaries and state keys are independently pinned.
- Detailing and truss authored cues are independently pinned.
- The complete retained `tests/test_viz.py` group remains authoritative for
  coordinates, labels, axes, values, colours and existing visual semantics.

## Explicit exclusions

- Unowned arbitrary Plotly figures supplied directly to private publication
  helpers.
- Shared publication style and structural/raster PDF preflight: PR-11C / F-042.
- The Plotly/Kaleido server `kopts` warning correction: PR-11C.
- Solver, formula, material, result, verdict, standards or project-schema work.
- Calculation-trace restoration or an optional trace toggle.
- PR-12+, packaging, signing, release, version or v0.93 roadmap work.
