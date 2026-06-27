# Sector

**Reinforced-concrete cross-section analysis for structural engineering.**

Sector analyses a polygonal reinforced (and optionally prestressed) concrete
cross-section and reports, for the same section:

* **Elastic analysis** - the concrete and reinforcement stresses of the cracked
  section under an eccentric axial force (axial load with biaxial bending),
  including combined long- and short-term load effects. The service/fatigue
  side of the work.
* **Plastic analysis** - the ultimate bending capacity under a given axial force
  and biaxial bending, traced as the neutral axis is rotated through the section
  to give the full N-M interaction envelope. The ultimate-limit-state side.
* **Extended elastic checks (SLS)** - two optional serviceability checks on top
  of the elastic analysis (EN 1992-1-1). The **cracking threshold** decides
  whether the section has cracked (comparing the uncracked concrete tension with
  the tensile strength `fctm`) and reports the governing stage's stresses; the
  **tension-stiffening** check adds the tension-stiffened mean state and the
  crack width `wk`. The plain elastic analysis is unchanged - it stays the
  cracked-section result with zero concrete tensile strength - so these only
  refine it when you ask for them.

You choose elastic, plastic, the extended SLS checks, or any combination from one
section definition.

## Goals

A fast, modern tool with the rigour engineers expect: define a section by its
shape and reinforcement (not by typing coordinates), choose the analysis, press
**Calculate**, and review the stresses, the capacity envelope, and the governing
results visually. Reports and an in-app manual round it out.

The numerical core is exhaustively validated against established cross-section
analysis results before any feature is built on it, so every number Sector
reports can be trusted.

## Running the app

```
pip install -r requirements.txt
python run_app.py          # or: streamlit run app/sector_app.py
```

Define the section (shape, dimensions, reinforcement), set the materials and
loads, pick the analysis mode, and press **Calculate**. The section drawing
updates live as you type; results update when you calculate.

The solver's inner loops are compiled with Numba, which the app warms up once at
startup (a few seconds, cached on disk thereafter) so every calculation after
that is near-instant. If Numba is not installed the solver still runs, just more
slowly.

## Project layout

```
sector/        computation core (headless, exhaustively tested)
  geometry     exact polygon area-moment integrals and clipping
  materials    concrete / mild-steel / prestress stress-strain laws
  section      the cross-section model
  elastic      cracked-section elastic stresses
  plastic      ultimate capacity (neutral-axis sweep, governing failure)
  serviceability  cracking threshold, tension stiffening, crack width (SLS)
  templates    parametric section + reinforcement builders
app/           Streamlit interface (sector_app, viz)
tools/         developer tooling (e.g. regression-fixture generation)
tests/         unit tests + the verification regression
```

## Development

```
pip install -r requirements-dev.txt
pytest
```

The test suite includes a permanent verification regression; the whole tree is
kept strictly ASCII (enforced by a test).
