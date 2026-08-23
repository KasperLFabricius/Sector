# G1 v0.96 report raster-oracle repair acceptance

## Exact base and failure

- Base commit: `0695992046491a19df7b1c10867169b6e702ba78`
- Base tree: `e59b881aeca5f0d1133f8ada6926c1bc3487dec4`
- Product version remains `0.95`; project schema remains `27`.
- Formal G1 run: `32620872654` on the exact base commit.

The complete 6,000-plus-test coverage suite and the real issued-manual render
passed. The real issued-report step then rejected the page-2 raster crop. PR-08
had inserted the visible linked Audit contents page at page 2, but the two
page-2 fingerprints and the former `report overview` crop label still described
the preceding report composition.

## Bounded repair

This repair changes only the two stable page-2 crop fingerprints and renames
the content crop to `report contents`. It changes no report flowable, text,
number, figure, page, destination, calculation, result, profile, project field,
schema, product identity or package surface.

The failed CI artifact and a fresh local render both contain 68 pages and
produce the same fingerprints:

| Crop | Relative box | Exact fingerprint |
|---|---|---|
| report contents | `(0.10, 0.08, 0.92, 0.90)` | `8316f5bc9afb2c7cba26d6c2555d05969f9f44a9c092857bf37f95c9f80f7575` |
| report page furniture | `(0.09, 0.02, 0.92, 0.98)` | `67af0e27a25c0c6ea99c26f6ffbd0e34630ac27a7224592af60da4a25e84b34c` |

Visual inspection of the exact CI page confirms readable contents, resolved
page numbers, intact header/footer furniture, no clipping, overlap or orphaned
entry, and a `Page 2 of 68` footer consistent with the PDF.

## Required closure

1. Re-run the real issued-report fixture and require all 68 pages plus both
   crop checks to pass.
2. Run the report/publication crop tests, compile, focused Ruff, version/schema
   guards and a diff-scope audit.
3. Review the exact candidate head with zero unresolved findings.
4. Merge with `[skip ci]`, then rerun complete G1 on the exact repaired main
   head before the governed v0.96 version bump.
