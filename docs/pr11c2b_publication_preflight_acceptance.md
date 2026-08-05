# PR-11C2B acceptance matrix - structural and raster PDF preflight

## Candidate boundary

- Exact base: `53b0d7895a45ab570d04a5651d2502e873b0688a`.
- Application version: `0.91` (unchanged).
- Family: F-042 report/manual structural and raster publication preflight.

## Retained authority

1. The exact merged report and manual PDFs and their accepted rendered pages are
   the content, navigation and visual authority.
2. Existing fixture payloads and the real Plotly/Kaleido publication paths stay
   unchanged; this slice validates their artifacts and does not redesign them.
3. PR-11C2A owns styling and warning behavior. This slice does not alter either.

## Structural contract

- Every page has an unrotated 210 x 297 mm A4 media box within 0.5 point and a
  content stream. Matching aspect ratio alone is explicitly insufficient.
- Every exact decimal report or lettered/hyphenated manual Figure/Table reference
  occurs once and retains an exact caption on the same page; longer identifiers
  cannot satisfy shorter ones.
- Every internal destination resolves to a page in the same document.
- Each publication reference is independently positioned from its embedded font
  widths. Exactly one link rectangle must cover that specific label and target
  its same-page caption. Unrelated contents/equation links cannot substitute.

## Raster contract

- Every page raster is A4 portrait, nonblank, plausibly inked and clear at all
  four physical edges.
- Configured report header/footer and manual footer regions contain visible ink
  on every page.
- Stable 80 x 80, 4-bit greyscale SHA-256 crop fingerprints pin the accepted
  report overview/furniture and manual cover/footer.

## Evidence

- Independent physical-A4, blank-stream, exact-label, unrelated-link,
  wrong-destination, furniture and crop-tamper adversaries.
- Directly affected report/manual rendered-fixture contracts.
- Complete 56-page report and 46-page manual real-Kaleido generation through the
  shared structural/raster/crop gate plus visual spot inspection.
- ASCII/version, pyflakes, py_compile, import, exact-base, scope and all rejected-
  ancestry guards.

## Exclusions

No style, warning, content, solver, formula, result, verdict, standard, trace,
schema, persistence, Streamlit, workflow, package, signing, version, PR-12+,
release or v0.93 roadmap change.
