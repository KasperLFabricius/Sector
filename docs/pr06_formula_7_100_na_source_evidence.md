# PR-06 Formula 7.100 NA controlled-source evidence

Status: controlled source and independent benchmark record for the PR-06
development candidate. This record identifies and checks the implementation
source without redistributing licensed standard content.

## Controlled document identity

- Designation: `DS/EN 1992-1-1 DK NA:2024`
- Library-relative location:
  `01_Denmark_Eurocodes/03_Concrete/00_Current/DS-EN 1992-1-1 - DK NA (2024, rev 2024-02-01) [DA].pdf`
- File size: 1,167,264 bytes
- Page count: 50
- Encryption state: unencrypted at inspection
- SHA-256:
  `2cb9eb45b195391563d2a19d5e6a154b6095aa49c70716c630948639ce9f65b2`
- Inspection date: 2026-08-10
- Target: PDF/printed page 40, clause 7.3.2(1)P, Formula 7.100 NA
- Associated figure/context: PDF/printed page 41

The controlled file was readable at inspection. Its local library location is
discovery metadata, not proof of project applicability or a redistribution
licence. The file is visibly marked Confidential. No screenshot, copied
standard prose or normalized transcription is committed to Sector.

## Visible identity anomaly

The document title page identifies the compiled annex as 2024, revision
2024-02-01. The red footer visible on target pages 40-41 instead says
`DS/EN 1992-1-1 DK NA:2021 rev. 2024-01-09`; the embedded PDF title metadata is
also stale. This discrepancy is recorded rather than silently normalized. The
implementation source identity follows the compiled document designation while
preserving this page-level anomaly in the acceptance evidence.

## Independent visual transcription procedure

Two independent visual readers used the pinned bytes above and inspected the
target pages from rendered pixels. OCR/text extraction was used only to locate
pages 40-41 and was not an implementation authority.

Each reader independently recorded symbol mapping, grouping, operators and
factor placement in a private normalized transcription. The two normalized
records agreed exactly and produced this common SHA-256:

`a90395d4718ed7069ad52828edbd76b58d347ca195e6e2151d77ac22063bb8fa`

A mismatch would have required a third source-led read. No mismatch occurred.
Only the digest and reviewer procedure are retained here; the controlled
formula transcription itself is not published.

## Current Danish context checked separately

The following public sources were checked on 2026-08-10:

- [BR18 current Eurocode 2 National Annex list](https://www.bygningsreglementet.dk/nationale-annekser/nationale-annekser/nationale-annekser/eurocode-2-betonkonstruktioner/)
  lists `DS/EN 1992-1-1 + AC:2008 DK NA:2024`.
- [BR18 section 345](https://www.bygningsreglementet.dk/tekniske-bestemmelser/15/krav/345/)
  routes concrete design through `DS/EN 1992-1-1 + AC:2008` with the Danish
  National Annex.
- [Danish Standards National Annex list](https://www.ds.dk/da/fagomraader/byggeri-og-anlaeg/eurocodes/nationale-annekser/groenlandske-annekser/dk-annekser)
  includes `DS/EN 1992-1-1 DK NA:2024`.

These sources support current Danish first-generation context. They do not
decide the governing basis for an individual project; Sector therefore keeps
the route separately selected and states that applicability remains the
engineer's responsibility.

## Independent numerical benchmark

The non-degenerate benchmark inputs are:

- bar diameter: 16 mm;
- effective tensile strength: 2.9 MPa;
- reinforcement modulus: 200,000 MPa;
- permitted crack width: 0.30 mm;
- effective tension area: 60,000 mm2; and
- provided reinforcement area: 1,600 mm2.

Independent full-precision results are:

| Crack system / surface | Base ratio | Required ratio | Required area (mm2) | Required/provided |
|---|---:|---:|---:|---:|
| Fine / ribbed | 0.01390443574307614 | 0.01390443574307614 | 834.26614458456845 | 0.52141634036535534 |
| Coarse / ribbed | 0.00983192080250175 | 0.00983192080250175 | 589.91524815010496 | 0.36869703009381560 |
| Fine / smooth | 0.01390443574307614 | 0.019663841605003504 | 1179.8304963002101 | 0.73739406018763132 |
| Coarse / smooth | 0.00983192080250175 | 0.01390443574307614 | 834.26614458456845 | 0.52141634036535534 |

The benchmark locks the fine/coarse square-root relationship, the smooth
surface multiplier outside the complete base result, every retained area and
comparison intermediate, positivity and finite outputs. Raw ratio checks use an
absolute tolerance of 1e-12; area checks use 1e-9 mm2.

The executable regression is
`tests/test_heightened_crack_control.py::test_dual_visual_source_benchmark_closes_fine_coarse_and_smooth_routes`.
It compares Sector to the independent values above and does not derive its
expected values from the production function.

## Scope boundary

This evidence supports only the explicitly selected first-generation Danish
Formula 7.100 NA calculation. It does not create a 2023 Danish option, infer
applicability, replace ordinary crack-width checks, assess confinement, claim
complete bridge coverage, or issue a compliance/certification verdict.
