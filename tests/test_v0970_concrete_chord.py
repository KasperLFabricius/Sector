"""TB-03: the a_l = d tension chord of the concrete shear route on every surface.

The expected values are hand calculations from the clause text, independent of
Sector output. Default section of the app: 400 x 600 mm, C35 with gamma_c = 1.45
and alpha_cc = 1.0 (fcd = 24.138 MPa); six bars of 314.16 mm2 at y = -250 mm
(As = 1885.0 mm2) and two bars of 314.16 mm2 at y = +250 mm (As2 = 628.3 mm2,
d2 = 50 mm); B550 with gamma_s = 1.20 (fyd = 458.33 MPa), Es = 200 GPa;
eps_c2 = 2.0 and eps_cu2 = 3.5 per mille. Shear method DS/EN 1992-1-1:2005 +
DK NA:2024 without links. Review case: VEd = 120 kN, Mx = 400 kNm.

Effective depth: d = 300 + 250 = 550 mm.

Concrete shear resistance, 6.2.2(1) with the DK NA CRd,c = 0.18/gamma_c:
    k = 1 + sqrt(200/550) = 1.603, rho_l = 1885.0/(400 x 550) = 0.00857,
    VRd,c = 0.1241 x 1.603 x (100 x 0.00857 x 35)^(1/3) x 400 x 550 = 136.0 kN.
    VEd = 120 kN <= 136.0 kN, so the concrete route applies.

Tension chord, 6.2.2(5) and 9.2.1.3(2): MEd + |VEd| d = 400 + 120 x 0.55 =
466.0 kNm.

Face resistance MRd of the bottom face (parabola-rectangle block: alpha =
1 - eps_c2/(3 eps_cu2) = 0.8095 and k_a = 0.4160; top bars elastic):
    0.8095 b fcd x + As2 Es eps_cu2 (x - d2)/x = As fyd  gives  x = 86.7 mm,
    MRd = Fc (d - k_a x) + Fs2 (d - d2) = 441.4 kNm.
    466.0/441.4 = 1.056 > 1, so the chord check gives FAIL.

With MEd,max = 420 kNm (6.2.3(7)): MEd + min(66.0, 420 - 400) = 420.0 kNm,
420.0/441.4 = 0.952, PASS.
"""

from __future__ import annotations

import copy
import io
import math
import pathlib
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app_case_inputs import overview_table  # noqa: E402

import result_presentation  # noqa: E402
from app import mvt_workspace  # noqa: E402
from sector import capacity, codes  # noqa: E402

APP = str(ROOT / "app" / "sector_app.py")
CHECK = "Shear tension chord (a_l = d)"

# Hand values (module docstring).
B, H, D, D2 = 400.0, 600.0, 550.0, 50.0
FCD = 35.0 / 1.45
FYD = 550.0 / 1.20
ES = 200000.0
EPS_C2, EPS_CU2 = 0.002, 0.0035
AS = 6 * math.pi * 10.0 ** 2
AS2 = 2 * math.pi * 10.0 ** 2
V_ED, M_ED = 120.0, 400.0


def _hand_vrd_c():
    k = 1.0 + math.sqrt(200.0 / D)
    rho = AS / (B * D)
    return (0.18 / 1.45) * k * (100.0 * rho * 35.0) ** (1.0 / 3.0) * B * D / 1000.0


def _hand_mrd():
    alpha = 1.0 - EPS_C2 / (3.0 * EPS_CU2)
    xi = EPS_C2 / EPS_CU2
    k_a = 1.0 - (
        (1.0 - xi) * (xi + (1.0 - xi) / 2.0) + xi ** 2 * 5.0 / 12.0
    ) / alpha
    k_c = alpha * B * FCD
    k_2 = AS2 * ES * EPS_CU2
    f_s = AS * FYD
    # k_c x^2 + (k_2 - f_s) x - k_2 d2 = 0 (top bars elastic).
    x = (-(k_2 - f_s) + math.sqrt((k_2 - f_s) ** 2 + 4.0 * k_c * k_2 * D2)) / (2.0 * k_c)
    sigma_2 = ES * EPS_CU2 * (x - D2) / x
    assert sigma_2 < FYD
    return (k_c * x * (D - k_a * x) + AS2 * sigma_2 * (D - D2)) / 1.0e6


M_TOTAL = M_ED + V_ED * D / 1000.0
MRD = _hand_mrd()


def _fresh():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=120)


def _calculate(at, *changes):
    from app_case_inputs import CALCULATION_RUN_TIMEOUT, apply_widget_changes
    from app_workflow_navigation import goto_page

    apply_widget_changes(at, changes)
    goto_page(at, "Analysis")
    at.button(key="calculate").click()
    return at.run(timeout=CALCULATION_RUN_TIMEOUT)


def _set(at, *changes):
    from app_case_inputs import apply_widget_changes

    return apply_widget_changes(at, changes)


def _pdf_text(inp, out, profile):
    import pypdf
    import sector_report

    inp, out = copy.deepcopy((inp, out))
    out["worked_example_selection"] = result_presentation.worked_example_selection(inp, out)
    pdf = sector_report.build_report({}, inp, out, figures=False, profile=profile)
    return " ".join(
        " ".join((page.extract_text() or "").split())
        for page in pypdf.PdfReader(io.BytesIO(pdf)).pages
    )


def _rows(inp, out):
    return {
        row["check"]: row
        for row in result_presentation.multi_case_summary_rows(inp, out)
        if row["check"].startswith("Shear")
    }


@pytest.fixture(scope="module")
def failed_app():
    at = _fresh().run()
    _set(at, ("checkbox", "shear_on", True))
    _calculate(
        at,
        ("number_input", "shear_V", V_ED),
        ("number_input", "pl_Mx", M_ED),
    )
    assert not at.exception
    return at


@pytest.fixture()
def failed_case(failed_app):
    return (
        copy.deepcopy(failed_app.session_state["result_input_snapshot"]),
        copy.deepcopy(failed_app.session_state["results"]),
    )


def test_hand_values():
    assert _hand_vrd_c() == pytest.approx(136.0, abs=0.05)
    assert MRD == pytest.approx(441.4, abs=0.1)
    assert M_TOTAL == pytest.approx(466.0)
    assert M_TOTAL / MRD > 1.0


def test_producer_retains_the_failed_chord_and_the_shear_status(failed_case):
    inp, out = failed_case
    shear = out["shear"]
    assert shear["util"] == pytest.approx(V_ED / _hand_vrd_c(), rel=1.0e-3)
    chord = shear["concrete_chord"]
    assert chord["valid"] is True
    assert chord["d"] == pytest.approx(D / 1000.0)
    assert chord["m_ed"] == pytest.approx(M_ED)
    assert chord["mv"] == pytest.approx(V_ED * D / 1000.0)
    assert chord["m_total"] == pytest.approx(M_TOTAL)
    assert chord["m_rd"] == pytest.approx(MRD, rel=1.0e-3)
    assert chord["util"] == pytest.approx(M_TOTAL / MRD, rel=1.0e-3)
    assert chord["status"] == "FAIL" and chord["ok"] is False
    assert chord["m_ed_max"] is None and chord["capped"] is False
    assert shear["resistance_status"] == "PASS"
    assert shear["assessment_status"] == "FAIL"
    assert shear["assessment_ok"] is False
    publication = result_presentation.concrete_route_chord_publication_assessment(
        inp, shear
    )
    assert publication["required"] is True and publication["valid"] is True


def test_producer_states_not_assessed_or_not_applicable(failed_case):
    inp, out = failed_case
    shear = out["shear"]
    concrete = SimpleNamespace(valid=True, route="concrete")
    without_plastic = capacity.concrete_route_chord(inp, None, shear, concrete)
    assert without_plastic["status"] == "NOT ASSESSED"
    assert without_plastic["valid"] is False and without_plastic["util"] is None
    links = SimpleNamespace(valid=True, route="links")
    assert capacity.concrete_route_chord(inp, out["plastic"], shear, links) is None


def test_failed_chord_reaches_the_summary_rows(failed_case):
    inp, out = failed_case
    rows = _rows(inp, out)
    assert rows["Shear without links"]["status"] == "PASS"
    chord = rows[CHECK]
    assert chord["status"] == "FAIL"
    assert chord["util"] == pytest.approx(M_TOTAL / MRD, rel=1.0e-3)
    assert chord["result"] == f"{100.0 * M_TOTAL / MRD:.1f} %"
    assert chord["overview_key"] == "shear:concrete_chord"
    assert "466.0 kNm" in chord["note"]
    governing = result_presentation.governing_summary_rows(
        result_presentation.multi_case_summary_rows(inp, out)
    )
    assert any(row["check"] == CHECK and row["status"] == "FAIL" for row in governing)


def test_failed_chord_reaches_the_results_overview(failed_app):
    from app_workflow_navigation import goto_page

    goto_page(failed_app, "Analysis")
    failed_app.selectbox(key="view").set_value("Results Overview").run()
    table = overview_table(failed_app)
    row = table.loc[table["Check"] == CHECK]
    assert len(row) == 1
    assert row.iloc[0]["Status"] == "FAIL"
    assert row.iloc[0]["Result"] == f"{100.0 * M_TOTAL / MRD:.1f} %"


def test_shear_view_shows_the_failed_chord(failed_app):
    from app_workflow_navigation import goto_page

    goto_page(failed_app, "Analysis")
    failed_app.selectbox(key="view").set_value("Shear").run()
    visible = " ".join(
        str(item.value) for item in (*failed_app.markdown, *failed_app.caption)
    )
    assert "Tension chord with the moment shift" in visible
    assert "466.00 kNm" in visible
    assert "(FAIL)" in visible


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_failed_chord_reaches_every_report_profile(failed_case, profile):
    inp, out = failed_case
    text = _pdf_text(inp, out, profile)
    percent = f"{100.0 * M_TOTAL / MRD:.1f} %"
    assert f"{CHECK} PL-01 FAIL {percent}" in text
    if profile in {"Standard", "Audit"}:
        assert "Tension chord with the moment shift" in text
        assert "466.00 kNm" in text
        assert f"{percent} (FAIL)" in text


def _edit_chord(out, *, shared, **changes):
    shear = out["shear"]
    if not shared:
        shear["concrete_chord"] = copy.deepcopy(shear["concrete_chord"])
    shear["concrete_chord"].update(changes)
    shear["assessment_status"] = "PASS"
    shear["assessment_ok"] = True


def _assert_not_published(inp, out, *forbidden):
    assert result_presentation.shear_publication_input_is_current(
        inp, out["shear"], plastic_result=out.get("plastic"),
        validate_directions=False,
    )[0] is False
    rows = _rows(inp, out)
    assert all(row["status"] != "PASS" for row in rows.values() if row["check"] != "Shear Vx")
    assert rows["Shear without links"]["status"] == "NOT ASSESSED"
    for profile in ("Brief", "Standard"):
        text = _pdf_text(inp, out, profile)
        assert "NOT ASSESSED" in text
        assert "Overall shear status PASS" not in text
        for token in forbidden:
            assert token not in text


@pytest.mark.parametrize("shared", (True, False))
def test_stale_moment_with_consistent_arithmetic_is_not_published(failed_case, shared):
    # Review case P1-02 (a): MEd = 300 kNm gives 300 + 66 = 366 kNm and
    # 366/441.4 = 82.9 % PASS, while the input keeps Mx = 400 kNm.
    inp, out = failed_case
    m_rd = out["shear"]["concrete_chord"]["m_rd"]
    _edit_chord(
        out, shared=shared, m_ed=300.0, m_ed_signed=300.0, m_total=366.0,
        util=366.0 / m_rd, ok=True, status="PASS",
    )
    publication = result_presentation.concrete_route_chord_publication_assessment(
        inp, out["shear"]
    )
    assert publication["required"] is True and publication["valid"] is False
    _assert_not_published(inp, out, f"{36600.0 / m_rd:.1f} %", "366.00 kNm")


@pytest.mark.parametrize("field, value", (
    ("v_ed", 60.0),
    ("d", 0.45),
    ("m_rd", 500.0),
))
def test_stale_shear_depth_or_resistance_operand_is_not_published(failed_case, field, value):
    inp, out = failed_case
    chord = out["shear"]["concrete_chord"]
    changes = {field: value}
    v_ed = changes.get("v_ed", chord["v_ed"])
    d = changes.get("d", chord["d"])
    m_rd = changes.get("m_rd", chord["m_rd"])
    mv = v_ed * d
    m_total = chord["m_ed"] + mv
    changes.update(
        a_l=d, mv=mv, mv_uncapped=mv, m_total=m_total, util=m_total / m_rd,
        ok=m_total <= m_rd, status="PASS" if m_total <= m_rd else "FAIL",
    )
    _edit_chord(out, shared=True, **changes)
    assert result_presentation.concrete_route_chord_publication_assessment(
        inp, out["shear"]
    )["valid"] is False
    _assert_not_published(inp, out)


def test_stale_med_max_input_is_not_published(failed_case):
    # The input now has MEd,max = 420 kNm, but the retained chord has no cap.
    inp, out = failed_case
    inp[capacity.MED_MAX_ON_KEY] = True
    inp[capacity.MED_MAX_KEYS[("x", True)]] = 420.0
    assert result_presentation.concrete_route_chord_publication_assessment(
        inp, out["shear"]
    )["valid"] is False
    assert result_presentation.shear_publication_input_is_current(
        inp, out["shear"], plastic_result=out.get("plastic"),
        validate_directions=False,
    )[0] is False


def test_missing_chord_record_is_not_published(failed_case):
    # Review case P1-02 (b): the record is removed and the status set to PASS.
    inp, out = failed_case
    for candidate in out["shear"].get("face_candidates") or ():
        candidate["shear"] = dict(candidate["shear"])
        candidate["shear"].pop("concrete_chord", None)
    out["shear"].pop("concrete_chord")
    out["shear"]["assessment_status"] = "PASS"
    out["shear"]["assessment_ok"] = True
    publication = result_presentation.concrete_route_chord_publication_assessment(
        inp, out["shear"]
    )
    assert publication["required"] is True and publication["valid"] is False
    _assert_not_published(inp, out)


def test_overall_status_less_severe_than_the_chord_is_not_published(failed_case):
    inp, out = failed_case
    out["shear"]["assessment_status"] = "PASS"
    out["shear"]["assessment_ok"] = True
    _assert_not_published(inp, out)


def test_med_max_keys_route_to_the_shared_settings_page():
    keys = (capacity.MED_MAX_ON_KEY, *capacity.MED_MAX_KEYS.values(), "shear_med_max_copy")
    for key in keys:
        assert mvt_workspace.field_page(key) == "Shared reinforcement"


def test_entered_med_max_limits_the_shift_through_the_app():
    # 6.2.3(7) with MEd,max = 420 kNm: 400 + min(66, 20) = 420 kNm, 420/441.4.
    at = _fresh().run()
    _set(
        at,
        ("checkbox", "shear_on", True),
        ("checkbox", capacity.MED_MAX_ON_KEY, True),
        ("number_input", capacity.MED_MAX_KEYS[("x", True)], 420.0),
    )
    _calculate(
        at,
        ("number_input", "shear_V", V_ED),
        ("number_input", "pl_Mx", M_ED),
    )
    assert not at.exception
    inp = at.session_state["result_input_snapshot"]
    out = at.session_state["results"]
    chord = out["shear"]["concrete_chord"]
    assert chord["m_ed_max"] == pytest.approx(420.0)
    assert chord["capped"] is True
    assert chord["mv"] == pytest.approx(20.0)
    assert chord["m_total"] == pytest.approx(420.0)
    assert chord["util"] == pytest.approx(420.0 / MRD, rel=1.0e-3)
    assert chord["status"] == "PASS"
    row = _rows(inp, out)[CHECK]
    assert row["status"] == "PASS"
    # P1-10: the label "MEd + |VEd| d" keeps the uncapped value.
    assert "MEd + |VEd| d = 466.0 kNm, limited to MEd,max = 420.0 kNm" in row["note"]


def test_2023_links_chord_states_that_med_max_is_not_used():
    # DS/EN 1992-1-1:2023 (8.53) applies only at direct intermediate supports or
    # concentrated loads. Sector does not establish that condition, so an
    # entered MEd,max must not change the 2023 link-truss chord.
    def run(med_max_on):
        at = _fresh().run()
        _set(
            at,
            ("checkbox", "shear_on", True),
            ("selectbox", "shear_method", codes.EC2_2023.label),
            ("checkbox", "shear_links", True),
        )
        if med_max_on:
            _set(
                at,
                ("checkbox", capacity.MED_MAX_ON_KEY, True),
                ("number_input", capacity.MED_MAX_KEYS[("x", True)], 100.0),
            )
        _calculate(
            at,
            ("number_input", "shear_V", 300.0),
            ("number_input", "pl_Mx", 90.0),
        )
        assert not at.exception
        return at

    plain = run(False)
    entered = run(True)
    plain_chord = plain.session_state["results"]["shear"]["links"]["chord"]
    entered_chord = entered.session_state["results"]["shear"]["links"]["chord"]
    assert plain_chord["chord_formula"] and entered_chord["chord_formula"]
    assert entered_chord["m_total"] == pytest.approx(plain_chord["m_total"])
    assert entered_chord["util"] == pytest.approx(plain_chord["util"])

    from app_workflow_navigation import goto_page

    goto_page(entered, "Analysis")
    entered.selectbox(key="view").set_value("Shear").run()
    captions = " ".join(str(item.value) for item in entered.caption)
    assert "Sector does not use the entered member maximum moment MEd,max" in captions
    # P1-12: (8.53) limits the chord force Ftd; NVd is the additional tensile
    # axial force from shear (8.50).
    assert "chord force Ftd" in captions
    assert "Formula (8.53) limits Ftd only at a direct intermediate support" in captions
    assert "chord force NVd" not in captions
    from app_workflow_navigation import goto_widget_owner

    goto_widget_owner(entered, capacity.MED_MAX_ON_KEY)
    help_text = entered.checkbox(key=capacity.MED_MAX_ON_KEY).help
    # The help stays within 50 words (test_user_copy); the (8.53) statement is
    # in the caption above and in the report.
    assert "DS/EN 1992-1-1:2023 links route does not use them" in help_text
    assert "N_{Vd}" not in help_text and "chord force" not in help_text
    text = _pdf_text(
        entered.session_state["result_input_snapshot"],
        entered.session_state["results"],
        "Standard",
    )
    assert "Formula (8.53) applies only at a direct intermediate support" in text
    assert "Sector does not limit the chord force Ftd" in text
    assert "Additional tensile axial force from shear NVd" in text


# ---------------------------------------------------------------------------
# Torsion share on the a_l = d chord (EN 1992-1-1:2004 6.3.2(3), Formula (6.28)).
#
# Hand calculation, default section with closed links and cot(theta) = 1.0
# (cot_min = cot_max = 1.0, so the member angle is fixed):
#   tef = A/u = 240000/2000 = 120 mm >= 2 x 50 mm (6.3.2(1)).
#   Ak = (400 - 120)(600 - 120) = 134400 mm2, uk = 2 (280 + 480) = 1520 mm.
#   Ftd,T = TEd uk cot(theta) / (2 Ak) = 20e6 x 1520 x 1.0 / 268800 = 113.10 kN.
#   z (face-aligned plastic lever arm at N = 0) = MRd / (As fyd) = 510.9 mm.
#   Torsion share on the chord: Ftd,T z/2 = 113.10 x 0.5109 / 2 = 28.89 kNm.
#   MEd = 360 kNm: 360 + 120 x 0.55 = 426.0 kNm, 426.0/441.4 = 0.965 PASS;
#   with the torsion share 426.0 + 28.9 = 454.9 kNm, 454.9/441.4 = 1.031 FAIL.
# ---------------------------------------------------------------------------

T_ED, M_ED_T = 20.0, 360.0
T_EF = 240000.0 / 2000.0
A_K = (B - T_EF) * (H - T_EF)
U_K = 2.0 * ((B - T_EF) + (H - T_EF))
FTD_T = T_ED * 1.0e6 * U_K * 1.0 / (2.0 * A_K) / 1000.0
Z_T = MRD * 1.0e6 / (AS * FYD)
MT = FTD_T * Z_T / 1000.0 / 2.0
M_SHIFT_T = M_ED_T + V_ED * D / 1000.0


def _torsion_app(t_ed, *, links=True, m_x=M_ED_T):
    at = _fresh()
    at.session_state[capacity.TORSION_CASE_AUTHORITIES_KEY] = {
        "PL-01": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_EQUILIBRIUM
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
        }
    }
    at.session_state["torsion_design_basis"] = capacity.TORSION_DESIGN_EQUILIBRIUM
    at.session_state["torsion_member_scope"] = capacity.TORSION_MEMBER_CLOSED
    at.run()
    _set(at, ("checkbox", "shear_on", True), ("checkbox", "torsion_on", True))
    changes = [
        ("number_input", "strut_cot_min", 1.0),
        ("number_input", "strut_cot_max", 1.0),
    ]
    if links:
        changes.insert(0, ("checkbox", "shear_links", True))
    _set(at, *changes)
    _calculate(
        at,
        ("number_input", "shear_V", V_ED),
        ("number_input", "pl_Mx", m_x),
        ("number_input", "torsion_T", t_ed),
    )
    assert not at.exception
    return at


@pytest.fixture(scope="module")
def torsion_app():
    return _torsion_app(T_ED)


@pytest.fixture()
def torsion_case(torsion_app):
    return (
        copy.deepcopy(torsion_app.session_state["result_input_snapshot"]),
        copy.deepcopy(torsion_app.session_state["results"]),
    )


def test_torsion_hand_values():
    assert A_K == pytest.approx(134400.0)
    assert U_K == pytest.approx(1520.0)
    assert FTD_T == pytest.approx(113.10, abs=0.01)
    assert Z_T == pytest.approx(510.9, abs=0.1)
    assert MT == pytest.approx(28.89, abs=0.01)
    assert M_SHIFT_T / MRD < 1.0 < (M_SHIFT_T + MT) / MRD


def test_torsion_share_turns_the_chord_from_pass_to_fail(torsion_case):
    without = _torsion_app(0.0)
    plain = without.session_state["results"]["shear"]["concrete_chord"]
    assert plain["has_torsion"] is False and plain["mt"] == 0.0
    assert plain["m_total"] == pytest.approx(M_SHIFT_T)
    assert plain["status"] == "PASS"

    inp, out = torsion_case
    tube = out["torsion"]["tube"]
    assert tube["Ak"] * 1.0e6 == pytest.approx(A_K)
    assert tube["uk"] * 1.0e3 == pytest.approx(U_K)
    chord = out["shear"]["concrete_chord"]
    assert chord["has_torsion"] is True and chord["valid"] is True
    assert chord["mv"] == pytest.approx(V_ED * D / 1000.0)
    assert chord["ftd_t"] == pytest.approx(FTD_T, rel=1.0e-6)
    assert chord["z"] * 1000.0 == pytest.approx(Z_T, rel=1.0e-3)
    assert chord["mt"] == pytest.approx(MT, rel=1.0e-3)
    assert chord["m_total"] == pytest.approx(M_SHIFT_T + MT, rel=1.0e-4)
    assert chord["util"] == pytest.approx((M_SHIFT_T + MT) / MRD, rel=1.0e-3)
    assert chord["status"] == "FAIL"
    assert out["shear"]["assessment_status"] == "FAIL"
    publication = result_presentation.concrete_route_chord_publication_assessment(
        inp, out["shear"], torsion_result=out["torsion"]
    )
    assert publication["valid"] is True
    row = _rows(inp, out)[CHECK]
    assert row["status"] == "FAIL"
    assert f"MEd + |VEd| d = {M_SHIFT_T:.1f} kNm" in row["note"]
    assert f"torsion share Ftd,T z/2 = {MT:.1f} kNm" in row["note"]
    assert f"total = {M_SHIFT_T + MT:.1f} kNm" in row["note"]
    text = _pdf_text(inp, out, "Standard")
    assert f"{CHECK} PL-01 FAIL {100.0 * (M_SHIFT_T + MT) / MRD:.1f} %" in text
    assert "carries half of the torsion longitudinal force" in text
    assert f"{MT:.2f} kNm" in text


def test_shear_view_shows_the_torsion_share(torsion_app):
    from app_workflow_navigation import goto_page

    goto_page(torsion_app, "Analysis")
    torsion_app.selectbox(key="view").set_value("Shear").run()
    visible = " ".join(
        str(item.value)
        for item in (*torsion_app.markdown, *torsion_app.caption)
    )
    assert "F_{td,T} \\cdot z/2" in visible
    assert f"{MT:.2f} kNm" in visible
    assert "(FAIL)" in visible


def test_chord_without_the_torsion_share_is_not_published(torsion_case):
    # Codex case: the retained chord omits Ftd,T z/2 with consistent arithmetic
    # (426.0 kNm, 96.5 % PASS) while the input keeps TEd = 20 kNm.
    inp, out = torsion_case
    m_rd = out["shear"]["concrete_chord"]["m_rd"]
    out["shear"]["concrete_chord"].update(
        ftd_t=0.0, z=None, mt=0.0, m_total=M_SHIFT_T, util=M_SHIFT_T / m_rd,
        ok=True, status="PASS",
    )
    out["shear"]["assessment_status"] = "PASS"
    out["shear"]["assessment_ok"] = True
    assert result_presentation.concrete_route_chord_publication_assessment(
        inp, out["shear"], torsion_result=out["torsion"]
    )["valid"] is False
    assert result_presentation.shear_publication_input_is_current(
        inp, out["shear"], plastic_result=out.get("plastic"),
        torsion_result=out["torsion"], validate_directions=False,
    )[0] is False
    rows = _rows(inp, out)
    assert rows["Shear without links"]["status"] == "NOT ASSESSED"
    assert all(row["status"] != "PASS" for row in rows.values() if row["check"] != "Shear Vx")


def test_stale_torsion_action_is_not_published(torsion_case):
    inp, out = torsion_case
    inp["torsion_T"] = 10.0
    assert result_presentation.concrete_route_chord_publication_assessment(
        inp, out["shear"], torsion_result=out["torsion"]
    )["valid"] is False
    # Without any torsion result (neither passed nor on the face candidate),
    # the torsion share cannot be rebuilt.
    inp["torsion_T"] = T_ED
    for candidate in out["shear"].get("face_candidates") or ():
        candidate["torsion"] = None
    assert result_presentation.concrete_route_chord_publication_assessment(
        inp, out["shear"], torsion_result=None
    )["valid"] is False


def test_torsion_without_closed_links_is_not_assessed():
    at = _torsion_app(T_ED, links=False)
    inp = at.session_state["result_input_snapshot"]
    out = at.session_state["results"]
    chord = out["shear"]["concrete_chord"]
    assert chord["valid"] is False and chord["status"] == "NOT ASSESSED"
    assert chord["util"] is None and chord["has_torsion"] is True
    assert chord["reason"] == capacity.CONCRETE_CHORD_TORSION_UNAVAILABLE
    assert out["shear"]["assessment_status"] == "NOT ASSESSED"
    row = _rows(inp, out)[CHECK]
    assert row["status"] == "NOT ASSESSED"
    assert "torsion longitudinal force F_td,T" in row["note"]
    text = _pdf_text(inp, out, "Standard")
    assert "NOT ASSESSED: the torsion longitudinal force F_td,T" in text


def test_zero_moment_chord_prints_zero():
    # MEd = 0 on the top face: chord_applied_moment(0, False) is +0.0, so the
    # chord prints 0.00 kNm (review item R8).
    at = _fresh().run()
    _set(at, ("checkbox", "shear_on", True))
    _calculate(at, ("number_input", "shear_V", V_ED), ("number_input", "pl_Mx", 0.0))
    assert not at.exception
    inp = at.session_state["result_input_snapshot"]
    out = at.session_state["results"]
    chord = out["shear"]["concrete_chord"]
    assert chord["m_ed"] == 0.0 and math.copysign(1.0, chord["m_ed"]) == 1.0
    text = _pdf_text(inp, out, "Standard")
    assert "shear tension face 0.00 kNm" in text
    assert "-0.00" not in text
