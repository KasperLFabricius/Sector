"""Overview names use trusted fragments and preserve literal result data."""
import ast
import copy
from pathlib import Path

import pytest
from app import report_summary_notation as notation

APP = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"


def renderer():
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_ui_summary_quantity")
    namespace = {"summary_notation": notation}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP), "exec"), namespace)
    return namespace[node.name], node


@pytest.mark.parametrize("token,expected", [
    ("f_ck", "characteristic concrete strength"),
    ("f_yk", "characteristic reinforcement yield strength"),
    ("f_pk", "characteristic tendon tensile strength"),
    ("f_p0.1k", "characteristic tendon 0.1% proof strength"),
    ("lambda_cr", "cracking factor"),
    ("VRd,max", "concrete-strut shear resistance"),
])
def test_overview_exact_known_symbol_keeps_every_literal_operand(token, expected):
    row = notation.attach({"result": notation.concat("9.072 MPa; 22.7% of ", notation.symbol(token), " | ID=user_f_ck_$x"), "status": "CALCULATED"})
    before = copy.deepcopy(row)
    function, _ = renderer()
    assert function(row, "result") == "9.072 MPa; 22.7% of " + expected + " | ID=user_f_ck_$x"
    assert row == before


@pytest.mark.parametrize("value", ["f_ck; lambda_cr; <sub>user</sub>", "0", 0, None, "-", "inf"])
def test_overview_plain_or_missing_metadata_stays_exact(value):
    function, _ = renderer()
    assert function({"result": value}, "result") == value


@pytest.mark.parametrize("metadata", [
    {"result": (("catalogue", "f_yk"),)},
    {"result": (("catalogue", "user_f_ck"),)},
    {"result": (("raw_html", "f_ck"),)},
    {"result": (("catalogue", "f_ck<script>"),)},
    "f_ck",
])
def test_overview_stale_or_untrusted_metadata_fails_closed(metadata):
    function, _ = renderer()
    row = {"result": "f_ck", "report_fields": metadata}
    before = copy.deepcopy(row)
    assert function(row, "result") == "f_ck"
    assert row == before


def test_overview_maps_every_current_authored_token_and_keeps_scientific_digits():
    function, node = renderer()
    labels = next(n.value for n in ast.walk(node) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "labels" for t in n.targets))
    labels = ast.literal_eval(labels)
    assert labels.keys() == notation.CATALOGUE.keys()
    for token in labels:
        row = notation.attach({"criterion": notation.concat(notation.symbol(token), " = ", notation.number("1.2300e-09"), " | source=f_ck")})
        assert function(row, "criterion") == labels[token] + " = 1.2300e-09 | source=f_ck"


def test_overview_literal_fragment_is_never_interpreted_as_a_symbol():
    function, _ = renderer()
    row = notation.attach({"result": notation.concat(notation.field("f_ck"), " / ", notation.symbol("f_ck"))})
    assert function(row, "result") == "f_ck / characteristic concrete strength"
