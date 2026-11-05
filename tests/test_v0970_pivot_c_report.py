"""Pivot C in the report: basis formula, material table and governing label.

EN 1992-1-1:2004 6.1(6) and Figure 6.1: when the whole section is in
compression, the strain at (1 - eps_c2/eps_cu2) h from the more compressed face
is limited to eps_c2. The curvature candidate is then

    kappa_C = eps_c2 / (c - (1 - eps_c2/eps_cu2) h),

so its distance from the neutral axis is c - (3/7) h for eps_c2 = 2.0 and
eps_cu2 = 3.5 per mille. Default section of the app: h = 600 mm about x.

Case: N = -6000 kN (compression) and Mx = 50 kNm. The squash load with pivot C
is about fcd Ac + Es eps_c2 As = 24.14 x 240000 + 400 x 2513 = 6799 kN, so the
governing capacity point at N = -6000 kN has the whole section in compression.
"""

from __future__ import annotations

import copy
import io
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import result_presentation  # noqa: E402

APP = str(ROOT / "app" / "sector_app.py")
H_M = 0.600
PIVOT_LABEL = (
    "Concentric compression (pivot C, EN 1992-1-1:2004, 6.1(6) and Figure 6.1)"
)
ROW_2004 = "Pivot C strain limit (EN 1992-1-1:2004, 6.1(6) and Figure 6.1) \u03b5c2"


def _run(pivot_c, preset=None):
    from streamlit.testing.v1 import AppTest
    from app_case_inputs import CALCULATION_RUN_TIMEOUT, apply_widget_changes
    from app_workflow_navigation import goto_page

    at = AppTest.from_file(APP, default_timeout=120).run()
    if preset is not None:
        apply_widget_changes(at, (("selectbox", "conc_preset", preset),))
    if not pivot_c:
        apply_widget_changes(at, (("checkbox", "conc_pivot_c", False),))
    apply_widget_changes(at, (
        ("number_input", "pl_P", -6000.0),
        ("number_input", "pl_Mx", 50.0),
    ))
    goto_page(at, "Analysis")
    at.button(key="calculate").click()
    at.run(timeout=CALCULATION_RUN_TIMEOUT)
    assert not at.exception
    return (
        copy.deepcopy(at.session_state["result_input_snapshot"]),
        copy.deepcopy(at.session_state["results"]),
    )


def _text(inp, out, profile):
    import pypdf
    import sector_report

    inp, out = copy.deepcopy((inp, out))
    out["worked_example_selection"] = result_presentation.worked_example_selection(inp, out)
    pdf = sector_report.build_report({}, inp, out, figures=False, profile=profile)
    return " ".join(
        " ".join((page.extract_text() or "").split())
        for page in pypdf.PdfReader(io.BytesIO(pdf)).pages
    )


def _governing_point(out):
    plastic = out["plastic"]
    return plastic["points"][plastic["worked_point_index"]]


@pytest.fixture(scope="module")
def pivot_on():
    return _run(True)


@pytest.fixture(scope="module")
def pivot_off():
    return _run(False)


def test_pivot_c_governs_with_the_figure_6_1_distance(pivot_on):
    inp, out = pivot_on
    assert inp["concrete"].pivot_c is True
    point = _governing_point(out)
    candidates = {item["mode"]: item for item in point["curvature_candidates"]}
    pivot = candidates["concrete_concentric_compression"]
    c = candidates["concrete_crushing"]["distance_from_na_m"]
    assert c > H_M
    assert pivot["strain_limit"] == pytest.approx(0.002)
    assert pivot["distance_from_na_m"] == pytest.approx(c - (1.0 - 2.0 / 3.5) * H_M)
    assert pivot["selected"] is True


@pytest.mark.parametrize("profile", ("Standard", "Audit"))
def test_report_documents_pivot_c_when_it_is_on(pivot_on, profile):
    inp, out = pivot_on
    text = _text(inp, out, profile)
    if profile == "Audit":
        # The calculation basis (theory) section is an Audit section.
        assert "Pivot C (EN 1992-1-1:2004, 6.1(6) and Figure 6.1)" in text
        assert "The limit is on in this calculation." in text
    assert f"{ROW_2004} On" in text
    assert PIVOT_LABEL in text
    assert "from the more compressed face" in text
    assert "6.1(6))" not in text


def test_report_states_that_pivot_c_is_off(pivot_off):
    inp, out = pivot_off
    assert inp["concrete"].pivot_c is False
    point = _governing_point(out)
    assert all(
        item["mode"] != "concrete_concentric_compression"
        for item in point["curvature_candidates"]
    )
    standard = _text(inp, out, "Standard")
    assert f"{ROW_2004} Off" in standard
    assert PIVOT_LABEL not in standard
    audit = _text(inp, out, "Audit")
    assert "The limit is off in this calculation" in audit
    assert PIVOT_LABEL not in audit


def test_2023_report_states_that_the_limit_is_off_and_names_the_edition():
    # DS/EN 1992-1-1:2023 8.1.1(3) limits only eps_cu, so the 2023 preset clears
    # the pivot C limit. The row names the edition and does not cite a bare
    # 2004 clause number (in the 2023 edition, 6.1 is a durability clause).
    from sector import codes

    inp, out = _run(False, preset=codes.EC2_2023.label)
    assert inp["concrete"].pivot_c is False
    standard = _text(inp, out, "Standard")
    assert (
        "Pivot C strain limit \u03b5c2 Off (DS/EN 1992-1-1:2023, 8.1.1(3) "
        "limits only \u03b5cu)"
    ) in standard
    assert "(6.1(6) and Figure 6.1)" not in standard
    audit = _text(inp, out, "Audit")
    assert "DS/EN 1992-1-1:2023, 8.1.1(3) limits only \u03b5cu, so the" in audit
