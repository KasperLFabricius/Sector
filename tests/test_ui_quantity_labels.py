"""Keep UI names separate from native values and report notation."""
import ast
import copy
from pathlib import Path

import pytest
from app import elastic_display

APP = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"


def helpers():
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name in {"_ui_strength_label", "_ui_strength_comparison"}]
    assert len(selected) == 2
    namespace = {"elastic_display": elastic_display}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(APP), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("label,plain,math_label", [
    ("f_ck", "Characteristic concrete strength", "$f_{ck}$"),
    ("f_yk", "Characteristic reinforcing-steel yield strength", "$f_{yk}$"),
    ("f_pk", "Characteristic tendon tensile strength", "$f_{pk}$"),
    ("f_p0.1k", "Characteristic tendon 0.1% proof strength", "$f_{p0.1k}$"),
])
def test_ui_strength_labels_are_closed_and_surface_specific(label, plain, math_label):
    function = helpers()["_ui_strength_label"]
    assert function(label) == plain
    assert function(label, math_label=True) == math_label


@pytest.mark.parametrize("stress,strength", [
    (-250.0, 500.0), (250.0, 500.0), (0.0, 500.0),
    (10.0, None), (10.0, 0.0), (None, 500.0),
    (float("inf"), 500.0), (float("nan"), 500.0),
])
def test_ui_percentage_keeps_native_magnitude_and_unavailable_semantics(stress, strength):
    function = helpers()["_ui_strength_comparison"]
    references = {"f_yk": strength}
    before = copy.deepcopy(references)
    ratio = elastic_display.percentage(stress, strength)
    expected = ("$f_{yk}$: unavailable" if ratio is None else f"{ratio:.1f}% of $f_{{yk}}$")
    assert function(stress, references, math_labels=True) == expected
    assert references == before


def test_ui_unknown_reference_stays_literal_without_reinterpreting_user_syntax():
    functions = helpers()
    original = "user_f_ck_$[x]<b>"
    assert functions["_ui_strength_label"](original) == original
    assert functions["_ui_strength_label"](original, math_label=True) == r"user\_f\_ck\_\$\[x\]\<b\>"
    assert functions["_ui_strength_comparison"](0.0, {original: 100.0}) == "0.0% of " + original


def test_crack_display_names_keep_original_keys_and_format_precision():
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_crack_width_panel")
    assignments = {node.targets[0].id: node.value for node in function.body
                   if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
    assert ast.literal_eval(assignments["quants"]) == [
        "Crack width (mm)", "Maximum crack spacing (mm)", "Mean strain difference (steel - concrete)",
        "Reinforcement stress (MPa)", "Effective reinforcement ratio",
        "Effective tension height (m)", "Cover (mm)", "Element diameter (mm)", "Governing element"]
    assert ast.literal_eval(assignments["keys"]) == [
        "wk", "sr_max", "esm_ecm", "sigma_s", "rho_p_eff", "hc_ef", "cover", "phi", "element_id"]
    assert ast.literal_eval(assignments["fmts"]) == [
        "{:.3f}", "{:.3f}", "{:.3e}", "{:.3f}", "{:.4f}", "{:.3f}", "{:.3f}", "{:.3f}", "{}"]
