# Sector

Reinforced-concrete cross-section analysis for structural engineering.

Sector analyses a polygonal reinforced (and optionally prestressed) concrete
cross-section and returns either:

* **Elastic analysis** -- the concrete and reinforcement stresses of the cracked
  section under an eccentric axial force (combined axial load and biaxial
  bending), including combined long- and short-term load effects.
* **Plastic analysis** -- the ultimate bending capacity of the section under a
  given axial force and biaxial bending, traced as the neutral axis is rotated
  through the section.

The user interacts with Sector through a live Streamlit interface that
visualises the input and output and generates succinct reports.

## Project layout

```
sector/        Computation core (pure, headless, exhaustively unit-tested)
  geometry.py    Exact polygon area-moment integrals and half-plane clipping
tests/         Test suite (run with pytest)
assets/        Static assets (logo)
```

## Approach

The computation core is built and verified headless before the UI is layered on
top. The elastic and plastic engines are validated against an extensive set of
results from established cross-section analysis tools before any additional
functionality is added, so every number Sector reports is trusted.

## Development

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```
