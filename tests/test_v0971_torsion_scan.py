"""0.97.1 S2 (AR-02): scan values of the torsion tube and payload at one angle.

The member strut-angle scan (EN 1992-1-1:2005 6.3.2(2): one strut angle for
shear and torsion, inside the limits of 6.2.3(2)) evaluates 1501 angles. Each
angle now uses ``capacity.tube_torsion_scan_values``, and the full tube payload
is built only at the selected angle.

Reference hand calculation (EN 1992-1-1:2005, recommended values): a solid
300 x 600 mm rectangle with four corner bars at 50 mm from the faces, C30,
gamma_c = 1.5, alpha_cc = 1.0, so fcd = 20 MPa. 6.3.2(1): A = 0.18 m2,
u = 1.8 m, tef = A/u = 100 mm (2a = 100 mm), Ak = 0.2 x 0.5 = 0.1 m2,
uk = 2 x (0.2 + 0.5) = 1.4 m. Closed phi10 links at s = 150 mm:
Asw/s = 78.54/150 mm2/mm, fywd = fyd = 500/1.15 MPa. 6.3.2(4) with 6.2.2(6):
nu = 0.6 x (1 - 30/250) = 0.528, alpha_cw = 1.0.
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

from sector import capacity, codes, torsion  # noqa: E402

SCAN_KEYS = ("t_ed", "trd_s", "trd_max", "util", "asl_req")

FCK = 30.0
FCD = 20.0
FYD = 500.0 / 1.15
ASW_OVER_S = math.pi * 10.0**2 / 4.0 / 150.0
NU = 0.6 * (1.0 - FCK / 250.0)
AK = 0.1
UK = 1.4
TEF_M = 0.1


def _rect_tube():
    a = 0.05
    bars = [(a, a, 100.0), (0.3 - a, a, 100.0), (0.3 - a, 0.6 - a, 100.0),
            (a, 0.6 - a, 100.0)]
    outer = [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)]
    return torsion.tube_properties_with_reinforcement(outer, None, bars)


def _kwargs(cot, **changes):
    kwargs = dict(
        closed_links_present=True,
        tcode=codes.EC2_2005,
        fck=FCK,
        fcd=FCD,
        alpha_cw=1.0,
        fywd=FYD,
        asw_over_s=ASW_OVER_S,
        cot_min=cot,
        cot_max=cot,
        nu_detail=False,
        fctd=0.7 * 2.9 / 1.5,
        fyd_long=FYD,
    )
    kwargs.update(changes)
    return kwargs


def _hand(t_ed, cot):
    """Hand formulas of 6.3.2 at one strut angle (kN.m, mm2)."""
    trd_s = ASW_OVER_S * 2.0 * AK * FYD * cot
    sin_cos = cot / (1.0 + cot * cot)
    trd_max = 2.0 * NU * 1.0 * FCD * AK * TEF_M * sin_cos * 1000.0  # (6.30)
    asl = t_ed * UK * cot / (2.0 * AK * FYD) * 1000.0  # (6.28)
    return trd_s, trd_max, t_ed / min(trd_s, trd_max), asl


def test_reference_tube_matches_the_hand_geometry():
    tube = _rect_tube()
    assert tube["valid"] is True
    assert tube["tef"] == pytest.approx(100.0)
    assert tube["Ak"] == pytest.approx(AK)
    assert tube["uk"] == pytest.approx(UK)


@pytest.mark.parametrize("cot", [1.0, 1.5, 1.75, 2.5])
def test_scan_values_follow_the_hand_formulas(cot):
    t_ed = 30.0
    values = capacity.tube_torsion_scan_values(_rect_tube(), t_ed, **_kwargs(cot))
    trd_s, trd_max, util, asl = _hand(t_ed, cot)
    assert tuple(values) == SCAN_KEYS
    assert values["t_ed"] == t_ed
    assert values["trd_s"] == pytest.approx(trd_s, rel=1e-12)
    assert values["trd_max"] == pytest.approx(trd_max, rel=1e-12)
    assert values["util"] == pytest.approx(util, rel=1e-12)
    assert values["asl_req"] == pytest.approx(asl, rel=1e-12)


def _same(left, right):
    if isinstance(left, float) and isinstance(right, float):
        return (
            (math.isnan(left) and math.isnan(right))
            or left.hex() == right.hex()
        )
    return type(left) is type(right) and left == right


def _invalid_tube():
    tube = dict(_rect_tube())
    tube["wall_evidence"] = dict(tube["wall_evidence"], complete=False)
    return tube


@pytest.mark.parametrize(
    ("tube_factory", "t_ed", "changes"),
    [
        (_rect_tube, 30.0, {}),
        (_rect_tube, 0.0, {}),
        (_rect_tube, 500.0, {}),
        (_rect_tube, 30.0, {"asw_over_s": 0.0, "fywd": 0.0}),
        (_rect_tube, 30.0, {"closed_links_present": False}),
        (_rect_tube, 30.0, {"nu_detail": True, "tcode": codes.EC2_2005_DKNA}),
        (_invalid_tube, 30.0, {}),
    ],
    ids=["live", "zero-torque", "over-limit", "no-links", "open-links",
         "dkna-detailing", "invalid-wall"],
)
@pytest.mark.parametrize("cot", [0.8, 1.0, 1.0 + 1.5 / 1500.0, 1.751, 2.5, 3.0])
def test_scan_values_are_the_payload_values_at_each_angle(
    tube_factory, t_ed, changes, cot
):
    """Equivalence contract of the split: same branches, same objects.

    The angles 0.8 and 3.0 are outside the 6.2.3(2) range of the method, so
    the payload is NOT ASSESSED and the scan values are its None values.
    """
    kwargs = _kwargs(cot, **changes)
    payload = capacity.tube_torsion(tube_factory(), t_ed, **kwargs)
    values = capacity.tube_torsion_scan_values(tube_factory(), t_ed, **kwargs)
    assert tuple(values) == capacity.TUBE_TORSION_SCAN_KEYS == SCAN_KEYS
    for key in SCAN_KEYS:
        assert _same(values[key], payload[key]), key


def test_scan_values_keep_the_payload_exceptions():
    kwargs = _kwargs(1.5, asw_over_s=math.inf)
    with pytest.raises(ValueError) as payload_error:
        capacity.tube_torsion(_rect_tube(), 30.0, **kwargs)
    with pytest.raises(ValueError) as scan_error:
        capacity.tube_torsion_scan_values(_rect_tube(), 30.0, **kwargs)
    assert str(scan_error.value) == str(payload_error.value)


def _torsion_inputs(t_ed=25.0):
    from tools import report_render_fixture

    inp = report_render_fixture._inputs()
    inp.update(
        mode="Plastic",
        shear_on=False,
        combined_on=False,
        torsion_method=codes.EC2_2005.label,
        torsion_gamma_ct=codes.EC2_2005.gamma_ct,
        torsion_T=t_ed,
        torsion_T_signed=t_ed,
        P_pl=0.0,
        Mx_pl=0.0,
        My_pl=0.0,
        shear_V=0.0,
        shear_Vx=0.0,
        shear_Vy=0.0,
    )
    return inp


def _count_calls(monkeypatch, module, name):
    calls = []
    original = getattr(module, name)

    def counted(*args, **kwargs):
        calls.append(kwargs.get("cot_min"))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)
    return calls


def _analytic_cot(context):
    """Minimax of TEd/TRd,s and TEd/TRd,max: TRd,s = TRd,max (6.30), clamped."""

    tk = context["_tk"]
    tube = context["subtubes"][0]
    a = tk["asw_over_s"] * 2.0 * tube["Ak"] * tk["fywd"]
    nu = 0.6 * (1.0 - tk["fck"] / 250.0)
    b = 2.0 * nu * tk["alpha_cw"] * tk["fcd"] * tube["Ak"] * tube["tef"]
    # a*c = b*c/(1 + c^2) -> c = sqrt(b/a - 1); b carries tef in mm (x 1000).
    crossover = math.sqrt(max(b / a - 1.0, 0.0))
    return min(max(crossover, tk["cot_min"]), tk["cot_max"]), a, b


def test_service_scan_builds_the_tube_payload_only_at_the_selected_angle(
    monkeypatch,
):
    from app import calculation_service

    inp = _torsion_inputs()
    payload_calls = _count_calls(monkeypatch, calculation_service, "_tube_torsion")
    scan_calls = _count_calls(monkeypatch, capacity, "tube_torsion_scan_values")
    out = {}
    calculation_service._run_uniaxial_capacity_checks(inp, out)

    result = out["torsion"]
    selected = result["cot"]
    assert payload_calls == [selected]
    assert len(set(scan_calls)) == 1501

    context = capacity.build_torsion_context(inp, 0.0)
    expected_cot, a, b = _analytic_cot(context)
    step = (context["tcot_max"] - context["tcot_min"]) / 1500.0
    assert abs(selected - expected_cot) <= step
    t_ed = inp["torsion_T"]
    hand_util = t_ed / min(a * selected, b * selected / (1.0 + selected**2))
    assert result["util"] == pytest.approx(hand_util, rel=1e-12)


def test_publication_scan_builds_the_tube_payload_only_at_the_selected_angle(
    monkeypatch,
):
    import result_presentation

    inp = _torsion_inputs()
    payload_calls = _count_calls(monkeypatch, capacity, "tube_torsion")
    scan_calls = _count_calls(monkeypatch, capacity, "tube_torsion_scan_values")
    current = result_presentation._current_torsion_only_children(inp)

    selection = current["member_angle_selection"]
    assert payload_calls == [selection["cot"]]
    assert len(set(scan_calls)) == 1501
    assert current["torsion_primary"]["cot"] == selection["cot"]
    assert current["torsion_primary"]["util"] == selection["utilisation"]

    context = capacity.build_torsion_context(inp, 0.0)
    expected_cot, _a, _b = _analytic_cot(context)
    step = (context["tcot_max"] - context["tcot_min"]) / 1500.0
    assert abs(selection["cot"] - expected_cot) <= step


def test_scan_never_reaches_a_tube_with_incomplete_wall_evidence(monkeypatch):
    from app import calculation_service

    inp = _torsion_inputs()
    inp["bars"] = [bar for bar in inp["bars"] if bar[0] < 0.0]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("incomplete wall evidence reached the torsion scan")

    monkeypatch.setattr(capacity, "tube_torsion_scan_values", forbidden)
    monkeypatch.setattr(calculation_service, "_tube_torsion", forbidden)
    out = {}
    calculation_service._run_uniaxial_capacity_checks(inp, out)
    assert out["torsion"]["util"] is None
    assert out["torsion"]["valid"] is False
