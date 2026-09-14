"""Signed, material-bound presentation ratios do not introduce an assessment."""

import copy
from types import SimpleNamespace as NS

import pytest

from app import elastic_display as display


def _fixture():
    inp = {
        "concrete": NS(fck=40.0),
        "bar_elements": [{"id": "R1", "material_id": "M1"},
                         {"id": "R2", "material_id": "M2"}],
        "bar_materials": [NS(fytk=500.0), NS(fytk=250.0)],
        "tendon_elements": [{"id": "P1", "material_id": "P7"}],
        "tendon_materials": [NS(curve=7, fytk=1600.0, futk=1860.0)],
    }
    rows = [
        {"element_id": "R1", "material_id": "M1", "element_type": "Bar",
         "total_mpa": 250.0, "long_mpa": 150.0, "dif_mpa": 100.0, "rst1_mpa": -50.0},
        {"element_id": "R2", "material_id": "M2", "element_type": "Bar",
         "total_mpa": -125.0, "long_mpa": -100.0, "dif_mpa": -25.0, "rst1_mpa": 0.0},
        {"element_id": "P1", "material_id": "P7", "element_type": "Tendon",
         "total_mpa": 930.0, "long_mpa": 800.0, "dif_mpa": 130.0, "rst1_mpa": -160.0},
    ]
    return inp, {"elements": rows}


def test_mixed_materials_signed_components_and_two_tendon_references():
    inp, elastic = _fixture()
    before = copy.deepcopy((inp, elastic))
    rows = display.element_comparison_rows(inp, elastic["elements"])
    assert [(r["Element"], r["Material"], r["Reference"]) for r in rows] == [
        ("R1", "M1", "f_yk"), ("R2", "M2", "f_yk"),
        ("P1", "P7", "f_pk"), ("P1", "P7", "f_p0.1k"),
    ]
    assert [r["Total"] for r in rows] == pytest.approx([50.0, -50.0, 50.0, 58.125])
    assert [r["Instantaneous response"] for r in rows] == pytest.approx([
        -10.0, 0.0, -160 / 1860 * 100, -10.0,
    ])
    assert rows[1]["Short-term increment"] == -10.0
    assert (inp, elastic) == before
    assert all("status" not in r and "utilisation" not in r for r in rows)


@pytest.mark.parametrize("strength", [None, 0, -1, True, "500", float("nan"),
                                     float("inf"), 10**1000])
def test_unavailable_characteristic_reference_is_not_a_zero_ratio(strength):
    assert display.percentage(250, strength) is None
    assert display.comparison_text(250, {"f_yk": strength}) == "f_yk: unavailable"


@pytest.mark.parametrize("stress", [None, True, "250", float("nan"), float("inf")])
def test_unavailable_stress_is_explicit(stress):
    assert display.percentage(stress, 500.0) is None


def test_concrete_signed_corner_and_existing_compression_magnitude():
    inp, elastic = _fixture()
    assert display.comparison_text(-10.0, {"f_ck": 40.0}) == "-25.0% of f_ck"
    assert display.output_comparison(inp, elastic, "concrete", {"value": 10.0}) == "25.0% of f_ck"


def test_existing_governing_identity_is_not_reselected_by_ratio_or_stress():
    inp, elastic = _fixture()
    output = {"value": 250.0, "governing": "R1", "calculation_state": "CALCULATED"}
    elastic["elements"][1]["total_mpa"] = 200.0  # 80%, larger ratio than R1
    before = copy.deepcopy(output)
    assert display.output_comparison(inp, elastic, "reinforcement", output) == "50.0% of f_yk"
    assert output == before
    # The selected top tension output remains floored at zero for compression.
    output.update(value=0.0, governing="R2")
    assert display.output_comparison(inp, elastic, "reinforcement", output) == "0.0% of f_yk"
    output["value"] = None
    assert display.output_comparison(inp, elastic, "reinforcement", output) == "f_yk: unavailable"


@pytest.mark.parametrize("change", ["id", "material", "duplicate", "missing_law", "no_id"])
def test_missing_or_ambiguous_assignment_is_unavailable(change):
    inp, elastic = _fixture()
    row = elastic["elements"][0]
    if change == "id":
        row["element_id"] = "R404"
    elif change == "material":
        row["material_id"] = "M2"
    elif change == "duplicate":
        inp["bar_elements"][1]["id"] = "R1"
    elif change == "missing_law":
        inp["bar_materials"].pop()
    else:
        row["element_id"] = None
        inp["bar_elements"][0]["id"] = None
    assert display.element_references(inp, row) == {"f_yk": None}


@pytest.mark.parametrize("curve", [1, 2, 3, 4, 5])
def test_fixed_tendon_law_defaults_are_not_characteristic_references(curve):
    inp, elastic = _fixture()
    inp["tendon_materials"][0].curve = curve
    assert display.element_references(inp, elastic["elements"][2]) == {
        "f_pk": None, "f_p0.1k": None,
    }


def test_absent_elastic_elements_does_not_infer_governing_material():
    inp, _ = _fixture()
    assert display.output_comparison(inp, {"elements": None}, "prestress",
                                     {"value": 930.0, "governing": "P1"}) == (
        "f_pk: unavailable; f_p0.1k: unavailable"
    )
