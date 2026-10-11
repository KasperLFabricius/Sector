"""Independent manual worksheet against the production equilibrium solvers."""

import ast
import inspect
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from manual_numerics import biaxial_example, plastic_search_example, polygon_sums, clip_polygon
from sector.elastic import solve_elastic, solve_elastic_combined
from sector.section import Section
from sector.materials import Concrete, MildSteel
from sector.plastic import plastic_capacity_at_angle


def test_scalar_equilibrium_solve_pivots_and_rejects_singular_matrix():
    from manual_numerics import _solve3

    # The first and second elimination columns each require a row swap.
    matrix = [[0., 0., 2.], [3., 0., 1.], [1., 4., 0.]]
    assert _solve3(matrix, [6., 6., 9.]) == pytest.approx([1., 2., 3.], rel=0, abs=1e-14)
    with pytest.raises(ValueError, match="singular"):
        _solve3([[1., 2., 3.], [2., 4., 6.], [0., 0., 0.]], [1., 2., 0.])


def test_published_worksheet_does_not_use_cpu_dispatched_linear_algebra(monkeypatch):
    import manual_numerics

    # ndarray's @ operator bypasses a patched np.matmul module attribute.
    source = ast.parse(inspect.getsource(manual_numerics))
    assert not any(isinstance(node, ast.MatMult) for node in ast.walk(source))

    def forbidden(*args, **kwargs):
        raise AssertionError("Published worksheet arithmetic must be independent of BLAS.")

    with monkeypatch.context() as patch:
        patch.setattr(np.linalg, "solve", forbidden)
        patch.setattr(np, "dot", forbidden)
        patch.setattr(np, "matmul", forbidden)
        # Bypass the cached result so all three elastic solves run in this test.
        case = biaxial_example.__wrapped__()
        patch.setattr(manual_numerics, "biaxial_example", lambda: case)
        assert len(manual_numerics.fig_elastic_iteration().data) == 10
    for route in ("elastic", "long", "instant"):
        result = case[route]
        assert result["tolerance"] == 1e-9 * max(1, max(abs(result["target"])))
        for state in result["trace"]:
            assert state["internal"] == pytest.approx(
                state["matrix"] @ state["plane"], rel=0, abs=1e-12)
            if max(abs(state["residual"])) > result["tolerance"]:
                assert state["correction"] == pytest.approx(
                    np.linalg.solve(state["matrix"], -state["residual"]), rel=1e-12, abs=1e-12)
        assert max(abs(result["trace"][-1]["residual"])) <= result["tolerance"]


def _native_section(case):
    return Section.from_polygon(
        corners=case["outer"], holes=case["holes"],
        bars_xy_area_mm2=[(x,y,area*1e6) for x,y,area,_n,_l in case["elements"]],
    )


def test_polygon_worksheet_has_correct_signed_area_and_clipping():
    square = [(0.,0.), (2.,0.), (2.,2.), (0.,2.)]
    clipped = clip_polygon(square, (-1.,1.,0.))
    assert polygon_sums(clipped) == pytest.approx([2,1,2,2/3,8/3,1])
    assert polygon_sums(list(reversed(clipped))) == pytest.approx(-polygon_sums(clipped))


def test_clipping_illustration_matches_independent_trapezoid_areas():
    from manual_numerical_figures import clipping_figure_data

    data = clipping_figure_data()
    assert data["fraction"] == pytest.approx(8 / 15)
    assert (400., 320.) in data["retained"]
    assert polygon_sums(data["retained"])[0] == pytest.approx(400 * (600 - 280))
    assert polygon_sums(data["removed_void"])[0] == pytest.approx(120 * (400 - 280))
    assert (polygon_sums(data["retained"])[0] -
            polygon_sums(data["removed_void"])[0]) == pytest.approx(113600)


def test_material_polynomial_and_degree_notation_survive_both_publications():
    import html
    import manual

    expression = r"-2500e^2+5000e-900"
    pdf_markup = manual._inline_md_to_rl("$" + expression + "$")
    html_markup = manual._inline_md_to_html("$" + expression + "$")
    for markup in (pdf_markup, html_markup):
        decoded = html.unescape(markup)
        assert "5000e-900" in decoded
        assert "\u00d7" not in decoded
    assert "^" not in manual._inline_md_to_rl(r"$90^\circ$")
    assert "&#215;" in manual._inline_md_to_rl("Residual 1e-9 kN")


def test_independent_biaxial_void_tendon_worksheet_matches_native():
    case = biaxial_example()
    native = solve_elastic(_native_section(case), 200, 100, 40, 6,
                          n_mult=np.array([1,1,1,1,.975]), prestress_stress=case["locked"])
    assert native.converged
    assert np.array([native.eps0,native.kx,native.ky]) == pytest.approx(case["elastic"]["plane"], abs=1e-7)
    assert native.bar_stress == pytest.approx(case["elastic"]["passive"], abs=1e-6)
    final = case["elastic"]["trace"][-1]
    assert max(abs(final["residual"])) <= case["elastic"]["tolerance"]
    assert len(case["elastic"]["trace"]) > 2
    assert len(final["voids"][0]) >= 3


def test_independent_duration_reconstruction_matches_all_native_elements():
    case = biaxial_example()
    native = solve_elastic_combined(_native_section(case), 200,70,30,18,0,30,10,6,
                                   n_mult=np.array([1,1,1,1,.975]), prestress_stress=case["locked"])
    assert native.converged
    for actual, expected in [(native.bar_stress_long, case["long_total"]),
                             (native.bar_stress_rst1, case["instant"]["passive"]),
                             (native.bar_stress_total, case["total"]),
                             (native.bar_stress_dif, case["difference"]),
                             (native.bar_stress_reduced_long, case["retained"])]:
        assert actual == pytest.approx(expected, abs=1e-6)
    reconstructed = case["instant"]["trace"][-1]["internal"] + case["neutralising"] + case["prestress"]
    assert reconstructed == pytest.approx(case["applied"], abs=1e-6)


def test_independent_plastic_search_and_individual_contributions_match_native():
    bars = [(-.1,-.25,math.pi*25**2/4), (0,-.25,math.pi*25**2/4), (.1,-.25,math.pi*25**2/4),
            (-.1,.25,math.pi*16**2/4), (.1,.25,math.pi*16**2/4)]
    section = Section.from_polygon(corners=[(-.15,-.3),(.15,-.3),(.15,.3),(-.15,.3)], bars_xy_area_mm2=bars)
    concrete = Concrete(fck=40, gamma_c=1.45, curve=2)
    steel = MildSteel(curve=3,fytk=550,fyck=550,futk=550,eut=.05,gamma_y=1.2,gamma_u=1.2,gamma_E=1,Es=200000,k=1,ey0t=0,ey0c=0)
    native = plastic_capacity_at_angle(section,concrete,steel,0,90)
    example = plastic_search_example()
    accepted = example["accepted"]
    assert native.converged
    assert accepted["depth"] == pytest.approx(native.compression_depth,abs=1e-11)
    assert accepted["moment"] == pytest.approx(native.Mx,abs=1e-7)
    assert accepted["axial"] == pytest.approx(native.axial,abs=1e-7)
    assert accepted["curvature"] == pytest.approx(native.curvature,abs=1e-10)
    assert len(accepted["bands"]) == 80
    assert accepted["plateau"][5] == pytest.approx(297.218602,abs=1e-5)
    assert example["trace"][-1][2]-example["trace"][-1][1] < 2e-12*.6
