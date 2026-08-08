# PR-01 Sector v0.93 programme acceptance

Status: candidate acceptance contract for pull request 382. GitHub records the
eventual squash identity; this document does not invent or self-reference a
commit that does not yet exist.

## Exact planning base

- Repository revision: `decd1232abb0a082639de90726c125dc988e1078`
- Repository tree: `f09bf8cb500f2ae02c2c30a8f085c67153fe619a`
- Release tag: `v0.92-source.1`
- Programme branch: `codex/pr01-v093-programme-contract`
- Governing identity: [Sector product identity](product_identity.md)

The revision-to-tree pair was independently resolved with Git immediately
before this record was written. The tree value is a tree object, not the parent
release commit.

## Frozen programme artifacts

- Canonical decisions: [v0.93 decision register](v093_decision_register.md)
- Living execution plan: [v0.93 pull-request programme](v093_pr_programme.md)
- Formatted snapshot: [Sector v0.93 Excel decision register](sector_v093_decision_register.xlsx)
- Workbook generator: `tools/build_v093_decision_workbook.ps1`
- Workbook SHA-256:
  `0F6400E4C548334799BE795AB7F10E59FE34A33E85D9754C4A15EF029C5B4B4E`
- LF-normalized canonical Markdown SHA-256 stored in the workbook:
  `4BA8FEA833BF453BE627C59B1828C70140C11453B9F0B7E16D5F8C67C46F88B8`

The Excel snapshot is generated from the Markdown decisions and selected
programme tables. The Markdown record remains authoritative if a discrepancy
is ever found. The workbook is macro-free and contains no engineering solver
logic. The committed package is sanitized after Excel closes: local paths,
corporate sensitivity-label properties, tenant identifiers, external
relationships and active OOXML parts are rejected before publication.

## Accepted decisions and boundaries

PR-01 freezes D093-001 through D093-027, the ten-slice dependency order, the
risk-based test policy, standards status, publication acceptance rules and the
Sector identity boundary. In particular, it records that:

- confinement enhancement is deferred beyond 0.93 and relevant scopes must
  disclose that it is not included or assessed;
- component-mapped bridge checks are removed in PR-02;
- ordinary crack acceptance is optional and uses controlled
  `WITHIN USER-SPECIFIED LIMIT` / `EXCEEDS USER-SPECIFIED LIMIT` wording rather
  than demand/resistance `PASS`/`FAIL`, while the separately selected DK/NA
  heightened calculation requires its permitted crack width;
- complete calculations must read like student-accessible worked examples,
  with every meaningful live substitution and numerical decision visible;
- formula typography, manuals and reports receive semantic and rendered QA;
- the v0.93 Windows deliverable is a verified unsigned portable application,
  not a signed production release; and
- Sector never issues a global code-compliance conclusion.

## Workbook acceptance evidence

The final workbook was opened independently in hidden Excel as read-only after
generation. Verification established:

- exact sheet order: `Read Me`, `Decisions`, `PR Programme`, `Standards`, and
  `Publication QA`;
- 27 unique decision IDs from D093-001 through D093-027;
- ten programme rows, with PR-01 in progress and nine planned slices;
- summary formulas evaluating exactly to 27 frozen decisions, 26 implementation
  decisions, one deferred decision, nine planned slices and one in-progress
  slice;
- no formula error in any used cell;
- the exact baseline revision, tree, release and canonical Markdown digest on
  the Read Me sheet; and
- the expected filter tables and frozen-header layout.

Excel exported every sheet to PDF. All eight resulting pages were rendered at
120 dpi and visually inspected: Read Me (1), Decisions (3), PR Programme (1),
Standards (1), and Publication QA (2). The final pages have readable text,
balanced decision pagination, complete repeated table headings, no clipping and
no stranded programme row. Preview PDFs and PNGs are temporary QA evidence and
are not release artifacts.

The user explicitly authorized the non-destructive Microsoft Excel automation
fallback after the bundled spreadsheet package was found incomplete. The
reviewable PowerShell generator creates a temporary workbook first, refuses an
unrequested overwrite, and preserves an earlier generated workbook on an
authorized rebuild.

The final focused gate used a verified previously nonexistent QA basetemp and
passed 203 tests:

```text
python -m pytest tests/test_v093_programme_docs.py tests/test_version.py tests/test_ascii_only.py -q
203 passed
```

The generator also passed the PowerShell parser before execution. These checks
are intentionally bounded because PR-01 does not alter application code; the
full programme gate remains mandatory in PR-09.

## PR-01 exclusions

PR-01 changes documentation, its contract tests, the workbook generator and the
generated workbook only. It makes no runtime, solver, Streamlit, project-schema,
version, packaging, Sector runtime manual/report publication-generation or
release-behaviour change. Sector therefore remains version 0.92 and the
historical v0.92 acceptance records stay unchanged.

The focused automated gate and GitHub checks are recorded in pull request 382;
merge is permitted only after they are green and the exact diff remains within
this scope.
