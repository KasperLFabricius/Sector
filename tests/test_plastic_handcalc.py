"""Regression of the plastic solver against real handcalc example outputs.

The fixtures in ``handcalc_fixtures.py`` are reconstructed from the handcalc ``.pcr``
output PDFs (geometry, materials and sampled expected result rows). This test
rebuilds each section and checks the solver reproduces the published ultimate
moments and strains. The mild-steel sections (including the 74-corner circular
ones) match to ~0.1 %; the prestressed sections to within a couple of percent.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from sector.materials import Concrete, MildSteel, Prestress
from sector.plastic import plastic_capacity_at_angle
from sector.section import Section

_spec = importlib.util.spec_from_file_location(
    "handcalc_fixtures", pathlib.Path(__file__).with_name("handcalc_fixtures.py")
)
_fix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fix)
CASES = _fix.CASES


def _build(case):
    section = Section.from_polygon(
        corners=case["corners"],
        bars_xy_area_mm2=case["bars"],
        tendons_xy_area_mm2=case["tendons"],
    )
    concrete = Concrete(**case["concrete"])
    mild = MildSteel(**case["mild"])
    prestress = None if case["prestress"] is None else Prestress(**case["prestress"])
    return section, concrete, mild, prestress


def test_fixtures_present():
    assert len(CASES) >= 12


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_handcalc_example(case):
    section, concrete, mild, prestress = _build(case)
    for (P, V, Mx, My, ec, es, ecab, curv) in case["rows"]:
        r = plastic_capacity_at_angle(section, concrete, mild, P, V,
                                      prestress=prestress, n_bands=50)
        assert r.converged
        scale = max(abs(Mx), abs(My), 1.0)
        # Ultimate moments: ~3 % (mild sections far tighter; prestress ~1.5 %).
        assert abs(r.Mx - Mx) <= 0.03 * scale + 1.0
        assert abs(r.My - My) <= 0.03 * scale + 1.0
        # Strains (percent) and curvature.
        assert abs(r.eps_concrete - ec) <= 0.03
        assert abs(r.eps_steel - es) <= 0.08
        if ecab is not None:
            assert abs(r.eps_cable - ecab) <= 0.08
        assert abs(r.curvature - curv) <= 0.05 * abs(curv) + 1e-4
