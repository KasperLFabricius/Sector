# Sector

**Reinforced-concrete cross-section analysis for structural engineering.**

Current release: **Sector 0.90**. See [CHANGELOG.md](CHANGELOG.md).

Sector analyses a polygonal reinforced (and optionally prestressed) concrete
cross-section and reports, for the same section:

* **Elastic analysis** - cracked-section concrete and reinforcement stresses
  from long- and short-term action components, including creep.
* **Plastic analysis** - nonlinear bending capacity at a given axial force,
  traced as a full biaxial M-M envelope with optional applied-action utilisation.
* **Stress and crack-width acceptance** - user-defined stress limits, cracking
  threshold, transformed properties and optional crack width `wk`, reported with
  the elastic result.
* **Section capacity checks** - shear, torsion and combined M-V-T checks where
  supported by the selected Eurocode method.
* **Longitudinal detailing checks** - per-case minimum reinforcement, including
  resultant biaxial tension zones, and a section-wide clear-spacing review with
  stable element IDs.

Plastic and Elastic identify the calculation method, not the limit state. Each
named row carries the user's project-defined description or classification (for
example ULS, ALS, SLS or FLS). Plastic/capacity rows contain NEd, MxEd, MyEd,
Vx,Ed, Vy,Ed and TEd. Elastic rows contain long- and short-term NEd/MxEd/MyEd components
and select stress-limit and crack-width acceptance per row.

Mild-steel and prestress catalogues provide stable material IDs. Each bar or
tendon is assigned an ID, so mixed strengths, moduli, partial factors, worklines
and tendon prestrains remain traceable in the UI, project file and PDF report.

## Goals

A fast, modern tool with the rigour engineers expect: define a section by its
shape and reinforcement (not by typing coordinates), choose the analysis, press
**Calculate**, and review every named case, the stresses, the capacity envelope,
and the governing results visually. Reports and an in-app manual round it out.

The numerical core is covered by independent hand checks, regression fixtures
and automated tests. The project engineer remains responsible for inputs,
method applicability and acceptance criteria.

## Running the app

```
pip install --require-hashes -r requirements.txt
python run_app.py          # or: streamlit run app/sector_app.py
```

Sector uses port 8502 so it can run alongside BriCoS on Streamlit's default
port 8501. Both launch methods bind to `127.0.0.1`, so the application is
accessible only from the computer running Sector.

Define the section (shape, dimensions, reinforcement), set the materials, add
named rows to the Plastic/capacity and Elastic load tables, pick the analysis
mode, and press **Calculate**. The section drawing updates live as you type;
results update when you calculate.

The solver's inner loops are compiled with Numba, which the app warms up once at
startup (a few seconds, cached on disk thereafter) so every calculation after
that is near-instant. If Numba is not installed the solver still runs, just more
slowly.

## Project layout

```
sector/        computation core (headless, regression-tested)
  geometry     exact polygon area-moment integrals and clipping
  materials    concrete / mild-steel / prestress stress-strain laws
  section      the cross-section model
  elastic      cracked-section elastic stresses
  plastic      nonlinear capacity (neutral-axis sweep, governing failure)
  capacity     headless shear, torsion, and M-V-T result orchestration
  detailing    longitudinal minimum reinforcement and clear spacing
  serviceability  cracking threshold, tension stiffening, crack width
  templates    parametric section + reinforcement builders
app/           Streamlit interface (sector_app, viz)
tools/         developer tooling (e.g. regression-fixture generation)
tests/         unit tests + the verification regression
```

## Development

```
pip install --require-hashes -r requirements-dev.txt
python -m pytest tests -n 4
```

The four-worker command matches the GitHub QA gate and keeps the solver-heavy
verification cases distributed. Run without ``-n 4`` only when a serial diagnostic
trace is useful. The test suite includes a permanent verification regression; the
whole tree is kept strictly ASCII (enforced by a test).

The live Streamlit UI stages the engineering inputs in full-width workflow tabs and
keeps view navigation, result-detail controls, Quick Section, report metadata and
save/load controls in independent fragments. Those interactions therefore avoid
rebuilding the complete input workspace in a browser. Streamlit's
``AppTest`` runner always executes a full script rerun and does not emulate browser
fragment reruns; UI tests consequently stage already-rendered widget changes and
submit them together. The Quick Section Apply and Back buttons are the exception:
they deliberately escalate from a fragment to a full-app rerun, so AppTest stages
their input edits once before clicking the exit button. Preserve those patterns
when adding UI coverage so test time tracks engineering work rather than redundant
page construction without retaining a stale fragment tree.

The supported runtime is pinned in `.python-version`. Runtime, development and
Windows-build environments are locked in `requirements*.txt`; edit the matching
`requirements*.in` file and regenerate the lock instead of editing a lock by
hand.

## Distribution

Sector is proprietary software authored by Kasper Lindskov Fabricius and licensed
to Sweco Danmark A/S for internal use. Access to the repository or application
does not grant a personal or public licence. See [LICENSE](LICENSE). Windows builds
include a generated third-party notice bundle beside `Sector.exe`; the source
process is documented in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
