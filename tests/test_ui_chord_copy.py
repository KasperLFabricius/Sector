"""Check authored UI notation while preserving retained engineering values."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from sector import combined as sector_combined

APP =Path(__file__).resolve().parents[1] / "app" / "sector_app.py"


def _namespace(*names):
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == set(names)
    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("axis,off", [("x", "$M_y$"), ("y", "$M_x$")])
@pytest.mark.parametrize("moment", [-80.0, 80.0])
def test_ui_chord_condition_preserves_applied_axial_force_and_other_moment(axis, off, moment):
    label = _namespace("_ui_chord_mrd_label")["_ui_chord_mrd_label"](axis, moment, True)
    assert f"about {axis} at the applied $N$" in label
    assert f"{off} = {moment:.1f} kN\u00b7m" in label
    assert "carries both moments at once" in label
    assert "kNm" not in label and "--" not in label


@pytest.mark.parametrize("moment", [-1e-9, 0.0, 1e-9])
def test_ui_chord_threshold_keeps_native_inclusive_boundary(moment):
    function = _namespace("_ui_chord_mrd_label")["_ui_chord_mrd_label"]
    assert function("x", moment, True) == "(bending about x at the applied $N$)"
    assert "conditional on $M_y$" in function("x", 1.000001e-9, True)


def test_ui_chord_nonconvergence_keeps_the_overstatement_warning():
    label = _namespace("_ui_chord_mrd_label")["_ui_chord_mrd_label"]("y", 80.0, False)
    assert "pure-axis bending about y at the applied $N$" in label
    assert "conditional biaxial solve did not converge" in label
    assert "can overstate the chord capacity" in label


def test_ui_chord_unknown_axis_is_literal_and_gets_no_invented_symbol():
    label = _namespace("_ui_chord_mrd_label")["_ui_chord_mrd_label"]("user_$x[1]<b>", 8.0, True)
    assert r"user\_\$x\[1\]\<b\>" in label
    assert "the other-axis moment = 8.0" in label
    assert "$M_x$" not in label and "$M_y$" not in label


class _Box:
    def __init__(self):
        self.captions = []
        self.metrics = []

    def caption(self, value):
        self.captions.append(value)

    def metric(self, *args, **kwargs):
        self.metrics.append(args)

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class _UI(_Box):
    def columns(self, count):
        self.boxes = [_Box() for _ in range(count)]
        return self.boxes

    def markdown(self, *args, **kwargs):
        pass


@pytest.mark.parametrize("limit,expected", [
    (None, "User limit unavailable; no comparison is available."),
    (0.0, "User limit: 0 mm; no comparison requested."),
    (0.3, "User limit: 0.300 mm; $w_k$ / limit = 0.500."),
])
def test_ui_crack_missing_zero_and_nonzero_limits_keep_distinct_meanings(limit, expected):
    namespace = _namespace("_crack_width_panel")
    ui = _UI()
    namespace["st"] = ui
    result = {"crack_output": {
        duration: {"value": 0.15, "criterion_mm": limit, "ratio": 0.5,
                   "calculation_state": "CALCULATED", "case": "case_1", "governing": "bar_1"}
        for duration in ("long_term", "short_term")}}
    before = copy.deepcopy(result)
    namespace["_crack_width_panel"](result)
    assert result == before
    for box in ui.boxes:
        assert expected in box.captions[0]
        assert "case_1" in box.captions[0] and "bar_1" in box.captions[0]
        assert box.metrics[0][1] == "0.150 mm"


@pytest.mark.parametrize("capped", [False, True])
@pytest.mark.parametrize("sign", [-1, 1])
def test_four_chord_caption_branches_keep_balanced_math_and_exact_operands(sign, capped):
    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    namespace = _namespace("_ui_chord_mrd_label", "_ui_chord_demand_2005")
    namespace["combined"] = sector_combined
    count = 0
    demand_forms = 0
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or function.name not in {
            "shear_view", "_render_chord_off", "combined_view"
        }:
            continue
        for call in ast.walk(function):
            if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute)
                    or call.func.attr != "caption" or "Governing chord:" not in ast.get_source_segment(source, call)):
                continue
            values = {"axis": "x", "face_m_ed_signed": sign * 10.0,
                      "m_ed": sign * 10.0, "mv": 20.0, "mt": 30.0,
                      "m_total": 40.0, "m_rd": 50.0, "m_off": 2.0,
                      "z": 0.4, "conditional": True, "theta_mode": "fixed", "z_src": "selected"}
            if capped:
                # EN 1992-1-1 6.2.3(7) with an entered MEd,max = 15 and
                # dFtd z = 25: min(25, 15 - MEd) = 5 for MEd = 10 and 25 for
                # MEd = -10.
                values.update(mv_uncapped=25.0, m_ed_max=15.0,
                              mv=5.0 if sign > 0 else 25.0,
                              shear_term_selection="MEd,max cap" if sign > 0 else "uncapped")
            before = copy.deepcopy(values)
            ui = _Box()
            env = dict(namespace, st=ui, ch=values, och=values, lg=values, combined=sector_combined,
                       face_desc="negative x", face_lbl="negative x", ax_lbl="x",
                       shear_term=r"\Delta F_{td}\,z", obj_note="", concrete={"angle_valid": True},
                       chord_util=0.8, chord_status="PASS", _pct=lambda _: "80.0 %",
                       viz=SimpleNamespace(chord_angle_note=lambda *args, **kwargs: "Fixed angle."),
                       presentation=SimpleNamespace(shear_link_arm_source_label=lambda *args: "selected lever arm"))
            expression = ast.fix_missing_locations(ast.Module(body=[ast.Expr(call)], type_ignores=[]))
            exec(compile(expression, str(APP), "exec"), env)
            caption = ui.captions[0]
            assert values == before
            assert caption.count("$") % 2 == 0
            assert "40.0" in caption and "50.0" in caption and "0.400" in caption
            assert "kNm" not in caption and "kN\u00b7m" in caption
            assert all("\\" not in part for part in caption.split("$")[::2])
            if "_ui_chord_demand_2005" in ast.get_source_segment(source, call):
                demand_forms += 1
                m_ed = "10.0" if sign > 0 else "(-10.0)"
                if capped:
                    assert "M_{Ed,max}" in caption
                    assert f"\\min(25.0,\\,15.0-{m_ed})+30.0" in caption
                else:
                    assert "\\min" not in caption and "M_{Ed,max}" not in caption
                    assert f"={sign * 10.0:.1f}+20.0+30.0" in caption
            count += 1
    assert count == 4
    assert demand_forms == 2


def test_base_en_combined_chord_states_the_med_max_limit_only_when_it_was_evaluated():
    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    view = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_render_base_en_combined")
    guarded = [node for node in ast.walk(view)
               if isinstance(node, ast.If)
               and ast.get_source_segment(source, node.test) == "combined.chord_cap_evaluated(lg)"
               and any("6.2.3(7): the shear term is" in ast.get_source_segment(source, item)
                       for item in node.body)]
    assert len(guarded) == 1
    # EN 1992-1-1 6.2.3(7): dFtd z = 25, MEd,max = 15, MEd = 10 gives min(25, 15 - 10) = 5.
    lg = {"m_ed": 10.0, "mv_uncapped": 25.0, "m_ed_max": 15.0, "mv": 5.0,
          "shear_term_selection": "MEd,max cap"}
    assert sector_combined.chord_cap_evaluated(lg)
    assert not sector_combined.chord_cap_evaluated(dict(lg, m_ed_max=None, shear_term_selection="uncapped"))
    ui = _Box()
    expression = ast.fix_missing_locations(ast.Module(body=guarded[0].body, type_ignores=[]))
    exec(compile(expression, str(APP), "exec"), {"st": ui, "lg": lg})
    caption = ui.captions[0]
    assert r"\min(25.000,\,15.000-10.000)=5.000$" in caption
    assert caption.count("$") % 2 == 0
    assert "kNm" not in caption
