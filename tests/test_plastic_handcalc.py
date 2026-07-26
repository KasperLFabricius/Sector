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


def _rings(case):
    """Map legacy annulus fixtures to the canonical outer-plus-hole topology.

    Eight circular hand-calculation cases store two independently closed
    37-point rings back-to-back. Their numerical expectations remain unchanged,
    but the concatenated self-touching polygon is not a valid section boundary.
    """
    corners = case["corners"]
    for index in range(2, len(corners) - 2):
        if corners[index] == corners[0]:
            possible_hole = corners[index + 1:]
            if possible_hole and possible_hole[-1] == possible_hole[0]:
                return corners[:index + 1], [possible_hole]
    return corners, []


def _build(case):
    corners, holes = _rings(case)
    section = Section.from_polygon(
        corners=corners,
        holes=holes,
        bars_xy_area_mm2=case["bars"],
        tendons_xy_area_mm2=case["tendons"],
    )
    concrete = Concrete(**case["concrete"])
    mild = MildSteel(**case["mild"])
    prestress = None if case["prestress"] is None else Prestress(**case["prestress"])
    return section, concrete, mild, prestress


def test_fixtures_present():
    assert len(CASES) >= 12


def test_legacy_annulus_fixtures_are_mapped_to_two_valid_rings():
    annulus_cases = [case for case in CASES if len(case["corners"]) == 74]
    assert len(annulus_cases) == 8
    for case in annulus_cases:
        outer, holes = _rings(case)
        section = Section.from_polygon(outer, holes=holes)
        assert len(section.concrete) == 2


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
