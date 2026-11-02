# Sector: guide for agents and developers

Sector calculates one reinforced or prestressed concrete cross-section: elastic
stresses, plastic N-Mx-My capacity, crack width, shear, torsion, combined M-V-T,
detailing and fatigue, with PDF reports and a built-in manual. It is a Streamlit
application with a pure Python calculation engine.

Read `docs/product_identity.md` before you change a calculation or a result
label. It governs every change.

## Module map

| Area | Location | Contents |
|---|---|---|
| Engine | `sector/` | Pure calculation code, no Streamlit. One module per family. |
| Section model | `sector/section.py`, `sector/geometry.py` | Polygon section, bars, tendons, clipping, topology checks. |
| Materials | `sector/materials.py`, `sector/material_presets.py`, `sector/codes.py` | Concrete, reinforcing steel and tendon laws; edition presets and coefficients. |
| Plastic ULS | `sector/plastic.py`, `sector/plastic_sweep.py` | Strain-plane capacity, pivot C, neutral-axis sweep, N-M and M-M envelopes. |
| Elastic SLS | `sector/elastic.py` | Cracked elastic Newton solver, long-term and short-term superposition, bonded prestress. |
| Crack width | `sector/serviceability.py`, `sector/heightened_crack_control.py` | EN 1992-1-1 7.3.4 (2005 and DK NA) and 2023 9.2.3, Formula 7.100 NA. |
| Shear, torsion, M-V-T | `sector/shear.py`, `sector/torsion.py`, `sector/combined.py`, `sector/capacity.py` | Resistances, chord checks, shared strut angle, result validators. |
| Detailing | `sector/detailing.py` | Minimum reinforcement, spacing, link rules. |
| Fatigue | `sector/fatigue.py` | Reinforcement S-N and Miner, concrete fatigue with the fibre search. |
| Application | `app/sector_app.py` | Streamlit script: input pages, `build_inputs`, calculation orchestration (`run_analysis`, `_run_uniaxial_capacity_checks`), result views. |
| Project files | `app/project_io.py`, `app/session_state_migrations.py` | Schema, validation and migrations of `.sector` project files. |
| Presentation | `app/result_presentation.py`, `app/fatigue_presentation.py` | Result rows, statuses and the publication validators that re-check retained results. |
| Report | `app/sector_report.py`, `app/report_*.py`, `app/publication_*.py` | PDF reports (Brief, Standard, Audit). |
| Manual | `app/manual*.py` | Built-in manual content and renderers. |
| Tests | `tests/` | pytest suite. `tests/test_v0970_*.py` hold the 0.97.0 hand-calculation tests. |

## Data flow

1. The input pages write Streamlit session state.
2. `build_inputs` in `app/sector_app.py` converts session state to one `inp`
   dictionary (materials, section, actions, method options).
3. `run_analysis` runs the engine for each action case and returns `results`.
4. `app/result_presentation.py` turns results into rows, statuses and notes. Its
   validators recompute the retained values from `inp`; a mismatch gives NOT
   ASSESSED instead of a stale verdict.
5. The views, the PDF report and the manual read the same results.

Session state lives in `st.session_state` and is saved in project files through
`app/project_io.py`. A new persisted input needs: a key in `SCALAR_KEYS` (and in
`_BOOLEAN_SCALAR_KEYS` when Boolean), the staleness signature keys in
`app/sector_app.py`, the widget, the `inp` entry and a migration default.

## Invariants

- Product identity: the engineer controls methods and coefficients. Warn when a
  value differs from a default; do not clamp or replace it.
- Fail closed: an incomplete or non-converged calculation gives NOT ASSESSED or
  INVALID with its cause, never a favourable verdict.
- Every new defect test comes from the standard text or an independent hand
  calculation, not from Sector output. Name the clause and the source PDF.
- Source files are ASCII only (`tests/test_ascii_only.py`).
- Program text (UI, help, report, manual) follows ASD-STE100 with British
  spelling and no em dashes.

## Commands

The pinned interpreter is CPython 3.13 with `requirements-dev.txt` (hash-locked).

- One area: `python -m pytest tests/test_combined.py -q -n 8`
- Full suite: `python -m pytest tests -q -n 20` (the app tests take most of the time)
- Source contracts: `python -m pytest tests/test_ascii_only.py -n 0 -q`
- Ruff policy: `python tools/verify_ruff_policy.py quality-ruff-policy.toml --execute`

CI (`.github/workflows/qa.yml`) runs the shards of `tools/qa_core_shards.py`,
the coverage, Ruff, mypy and dependency gates.

## Release steps

1. Update `sector/__init__.py` (`__version__`) and every version literal the
   tests report.
2. Add a `CHANGELOG.md` entry and `docs/vXYZ_release_notes.md`.
3. When a persisted input changes, increase `VERSION` in `app/project_io.py` and
   add the migration and its load message.

## History

The `docs/*_acceptance.md` records describe earlier releases. Do not edit them.
Release notes and tests are the record from 0.97.0 on.
