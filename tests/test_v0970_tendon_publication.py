"""TB-05 and TA-08 through the app: publication, default and stored diagram data.

Default app section 400 x 600 mm, C35, six bars of 314.16 mm2 at y = -250 mm
(As = 1884.96 mm2, ds = 550 mm) and two at y = +250 mm. One bonded tendon of
600 mm2 at y = -200 mm (dp = 500 mm). VEd = 120 kN, Mx = 400 kNm.

Hand values:
- EN 1992-1-1:2004 family, area-weighted mean d (EN 1992-2 6.2.2(101)):
  d = (550 x 1884.96 + 500 x 600)/2484.96 = 537.93 mm.
- DS/EN 1992-1-1:2023 (8.36): d = (550^2 x 1884.96 + 500^2 x 600)/
  (550 x 1884.96 + 500 x 600) = 538.78 mm; (8.37): rho_l =
  (550 x 1884.96 + 500 x 600)/(400 x 538.78^2) = 0.011512.
- Strands only (bottom bars removed), DK NA: k = 1 + (200/500)^0.5 = 1.6325,
  rho_l = 600/(400 x 500) = 0.003, CRd,c = 0.18/1.45,
  VRd,c = 0.12414 x 1.6325 x (100 x 0.003 x 35)^(1/3) x 400 x 500 = 88.75 kN
  (v_min = 0.035 x 1.6325^1.5 x 35^0.5 = 0.432 MPa < 0.444 MPa).
"""

from __future__ import annotations

import copy
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from streamlit.testing.v1 import AppTest  # noqa: E402

from app import reinforcement_table  # noqa: E402
from app_case_inputs import CALCULATION_RUN_TIMEOUT, apply_widget_changes  # noqa: E402
from app_workflow_navigation import goto_page  # noqa: E402
import result_presentation  # noqa: E402
from sector import capacity, codes  # noqa: E402

APP = str(ROOT / "app" / "sector_app.py")
EDITORS = {"bars_base": "ed_bars", "tendons_base": "ed_tendons"}
AS_BARS = 6 * math.pi * 10.0 ** 2


def _replace_base(at, base_key, value):
    goto_page(at, "Inputs")
    editor = EDITORS[base_key]
    try:
        version = at.session_state[editor + "_ver"]
    except KeyError:
        version = 0
    at.session_state[base_key] = value
    at.session_state[editor + "_ver"] = version + 1
    try:
        del at.session_state[editor]
    except KeyError:
        pass
    at.run()


def _calculate(*, include, strands_only=False, method=None, links=False,
               v=120.0, m=400.0, monkeypatch=None, tmp_path=None):
    if monkeypatch is not None:
        monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    at = AppTest.from_file(APP, default_timeout=120).run()
    apply_widget_changes(at, [("checkbox", "shear_on", True)])
    if method:
        apply_widget_changes(at, [("selectbox", "shear_method", method)])
    apply_widget_changes(at, [("checkbox", capacity.SHEAR_TENDONS_KEY, include)])
    if links:
        apply_widget_changes(at, [("checkbox", "shear_links", True)])
    _replace_base(at, "tendons_base", reinforcement_table.table_from_points(
        [(0.0, -200.0, 600.0)], "tendon"))
    if strands_only:
        _replace_base(at, "bars_base", reinforcement_table.table_from_points(
            [(-150.0, 250.0, 314.16), (150.0, 250.0, 314.16)], "bar"))
    apply_widget_changes(at, [("number_input", "shear_V", v),
                              ("number_input", "pl_Mx", m)])
    goto_page(at, "Analysis")
    at.button(key="calculate").click()
    at.run(timeout=CALCULATION_RUN_TIMEOUT)
    assert not at.exception
    inp = copy.deepcopy(at.session_state["result_input_snapshot"])
    out = copy.deepcopy(at.session_state["results"])
    return inp, out


def _shear_rows(inp, out):
    return {
        row["check"]: row
        for row in result_presentation.multi_case_summary_rows(inp, out)
        if row["check"].startswith("Shear")
    }


def _assert_published(inp, out, check):
    sh = out["shear"]
    assert result_presentation.concrete_shear_publication_input_is_current(
        inp, sh
    ) == (True, None)
    rows = _shear_rows(inp, out)
    assert rows[check]["status"] in {"PASS", "FAIL"}, rows[check]
    return sh, rows


def test_mixed_section_2005_publishes_shear_and_chord(monkeypatch, tmp_path):
    inp, out = _calculate(include=True, monkeypatch=monkeypatch, tmp_path=tmp_path)
    sh, rows = _assert_published(inp, out, "Shear without links")
    d_hand = (550.0 * AS_BARS + 500.0 * 600.0) / (AS_BARS + 600.0)
    assert sh["d"] == pytest.approx(d_hand, rel=1.0e-6)
    assert sh["asl"] == pytest.approx(AS_BARS + 600.0, rel=1.0e-6)
    assert rows["Shear tension chord (a_l = d)"]["status"] in {"PASS", "FAIL"}
    assert sh["asl_split"]["rule"] == capacity.SHEAR_ASL_AREA_WEIGHTED


def test_strand_only_section_2005_has_a_shear_result(monkeypatch, tmp_path):
    inp, out = _calculate(include=True, strands_only=True,
                          monkeypatch=monkeypatch, tmp_path=tmp_path)
    sh, _rows = _assert_published(inp, out, "Shear without links")
    assert (sh["d"], sh["asl"]) == pytest.approx((500.0, 600.0))
    k = 1.0 + math.sqrt(200.0 / 500.0)
    vrd_hand = (0.18 / 1.45) * k * (100.0 * 0.003 * 35.0) ** (1.0 / 3.0) * 400.0 * 500.0 / 1000.0
    assert sh["res"]["vrd_c"] == pytest.approx(vrd_hand, rel=2.0e-3)


def test_mixed_section_2023_uses_formulae_8_36_and_8_37(monkeypatch, tmp_path):
    inp, out = _calculate(include=True, method=codes.EC2_2023.label,
                          monkeypatch=monkeypatch, tmp_path=tmp_path)
    sh, _rows = _assert_published(inp, out, "Shear without links")
    first = 550.0 * AS_BARS + 500.0 * 600.0
    d_hand = (550.0 ** 2 * AS_BARS + 500.0 ** 2 * 600.0) / first
    assert sh["d"] == pytest.approx(d_hand, rel=1.0e-6)
    bw = sh["res"]["bw"]
    assert sh["res"]["rho_l"] == pytest.approx(first / (bw * d_hand ** 2), rel=1.0e-6)


def test_links_route_publishes_with_the_tendon_depth(monkeypatch, tmp_path):
    inp, out = _calculate(include=True, links=True, v=400.0,
                          monkeypatch=monkeypatch, tmp_path=tmp_path)
    rows = _shear_rows(inp, out)
    assert rows["Shear with links"]["status"] in {"PASS", "FAIL"}, rows


def test_option_follows_the_shear_method_until_the_user_sets_it(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    key = capacity.SHEAR_TENDONS_KEY
    at = AppTest.from_file(APP, default_timeout=120).run()
    apply_widget_changes(at, [("checkbox", "shear_on", True)])
    assert at.session_state[key] is False
    apply_widget_changes(at, [("selectbox", "shear_method", codes.EC2_2023.label)])
    assert at.session_state[key] is True
    apply_widget_changes(at, [("checkbox", key, False)])
    apply_widget_changes(at, [("selectbox", "shear_method", codes.EC2_2005_DKNA.label)])
    apply_widget_changes(at, [("selectbox", "shear_method", codes.EC2_2023.label)])
    assert at.session_state[key] is False


def test_interaction_diagram_stores_its_companion_moment_and_limits(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    at = AppTest.from_file(APP, default_timeout=120).run()
    apply_widget_changes(at, [("checkbox", "pl_interaction", True),
                              ("number_input", "pl_Mx", 100.0),
                              ("number_input", "pl_My", 30.0)])
    goto_page(at, "Analysis")
    at.button(key="calculate").click()
    at.run(timeout=CALCULATION_RUN_TIMEOUT)
    assert not at.exception
    nm = at.session_state["results"]["plastic"]["interaction"]
    assert nm["x"]["companion"] == pytest.approx(30.0)
    assert nm["y"]["companion"] == pytest.approx(100.0)
    # Consistency check of the stored data. The hand values of the axial
    # limits are in tests/test_v0970_uniaxial_interaction.py.
    for axis in ("x", "y"):
        squash, tension = nm[axis]["limits"]
        assert squash < 0.0 < tension
        assert all(squash - 1.0e-6 <= n <= tension + 1.0e-6 for n in nm[axis]["N"])


def test_strand_only_section_2023_publishes_with_fpd(monkeypatch, tmp_path):
    # rho_l = Ap/(bw dp) = 600/(400 x 500) = 0.003 ((8.37) with As = 0);
    # fyd of Formula (8.20) is fpd of the tendon material (8.2.1(4)).
    inp, out = _calculate(include=True, strands_only=True,
                          method=codes.EC2_2023.label,
                          monkeypatch=monkeypatch, tmp_path=tmp_path)
    sh, _rows = _assert_published(inp, out, "Shear without links")
    assert (sh["d"], sh["asl"]) == pytest.approx((500.0, 600.0))
    assert sh["res"]["rho_l"] == pytest.approx(600.0 / (sh["res"]["bw"] * 500.0))
    material = (inp.get("tendon_materials") or [None])[0] or inp["prestress"]
    assert sh["res"]["fyd"] == pytest.approx(material.fytk / material.gamma_y)


def test_links_route_2023_publishes_with_the_tendon_depth(monkeypatch, tmp_path):
    inp, out = _calculate(include=True, links=True, v=400.0,
                          method=codes.EC2_2023.label,
                          monkeypatch=monkeypatch, tmp_path=tmp_path)
    rows = _shear_rows(inp, out)
    assert rows["Shear with links"]["status"] in {"PASS", "FAIL"}, rows
