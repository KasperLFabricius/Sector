# PR-10B2 acceptance matrix - F019/F037 publication rhythm

## Candidate identity

- Exact base: `def49c5f88da485950e82d74427d5c71e2326b2c`.
- Base tree: `8fed21d8e7fe8fcb5255fdeb7881a0a7865fd279`.
- Application version: `0.91` (unchanged).
- Family: PDF report/manual publication geometry only.
- Objective: predictable section starts and readable vertical rhythm without
  changing authored evidence or the accepted pagination engine.

## Authoritative retained boundary

1. `app/sector_report.py` supplies the current report section order, formula and
   reference styles, assessment banner, table pagination and retained payload.
2. `app/manual.py` is the one source for both interactive and PDF manual content;
   ReportLab imports remain lazy inside PDF generation.
3. Existing report/manual tests retain all published text, formulas, references,
   tables, outlines, links and version identity.
4. Accepted PR-10B1a2 and PR-10B1b own horizontal fit and vertical table splitting;
   this slice must consume those contracts without changing them.

## Frozen report page sequence

- `Loads` starts after an explicit `PageBreak`.
- `Analysis settings` starts after a second explicit `PageBreak`.
- Before either break, remove only a trailing explicit layout gap, including a gap
  inside the last `KeepTogether`, so a postponed spacer cannot create a
  furniture-only blank page. Semantic content and flowable-owned spacing remain.
- The former combined `KeepTogether` wrapper over Loads plus settings is removed.
- Main and grouped-fatigue settings tables pass `keep=False`, so the accepted
  pagination engine can split them rather than treating either as one short block.
- Authored section/subsection order and all settings rows remain unchanged.

## Frozen report rhythm

- Formula style: 9.5 pt type, 14 pt leading, 12 pt left indent, 6 pt right indent,
  2 pt before and 3 pt after.
- Formula references: 8 pt type, 11 pt leading, 12 pt left indent, 6 pt right
  indent and 6 pt after.
- Assessment banners retain wording, type, palette, border and padding. Their
  flowable owns 2 pt before and 6 pt after; the separate trailing spacer is removed.
- Headings, body styles, table styles and figure geometry remain unchanged.

## Frozen manual rhythm

- Manual H1 retains 15 pt type and 14 pt before, with 8 pt after.
- Manual small text retains 8 pt type with 11 pt leading.
- Authored manual data tables retain equal column widths, header repetition, grid,
  header fill and top alignment; they add 2 pt before and use 5 pt padding on all
  four sides.
- Callouts, figures, equations, contents, outlines, links and content blocks remain
  unchanged.
- A dependency-injected style helper may expose the PDF styles for focused tests,
  but no ReportLab import may move to module import time.

## Focused evidence required

- Direct style probes freeze every numeric report/manual value above.
- Flowable probes prove the two page breaks immediately precede the Loads and
  Analysis-settings headings, no combined KeepTogether remains, and top-level /
  nested trailing gaps are discarded without removing semantic content.
- Settings inventory probes prove both main and fatigue tables are splittable.
- Assessment probes prove the banner remains a plain table with the shared palette
  and owns its spacing without a trailing spacer.
- A lazy-import manual build capture proves data-table spacing/padding and the H1 /
  small-text styles without launching figures or changing authored content.
- Focused PDF extraction proves Loads and Analysis settings occupy distinct pages.

## Explicit exclusions

- No table width, panel, identity, context, fragment or fallback change (PR-10B1).
- No equation IDs/numbers, equation block mechanics, captions, cross-references,
  grayscale or preflight change (PR-11).
- No calculation mechanics, provenance, schema, UI, persistence, package, workflow,
  version, PR-12+, or v0.93 change.
