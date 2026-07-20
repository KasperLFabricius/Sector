"""Headless orchestration tests for member shear, torsion and M-V-T checks."""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

import pytest

from sector import capacity, codes


def _rect(b=0.3, h=0.6):
    return [(0.0, 0.0), (b, 0.0), (b, h), (0.0, h)]


def _materials():
    concrete = SimpleNamespace(fck=35.0, fcd=35.0 / 1.45, gamma_c=1.45)
    steel = SimpleNamespace(fytk=550.0, gamma_y=1.20)
    return concrete, steel


def _member_input(**overrides):
    concrete, steel = _materials()
    inp = {
        "outer": _rect(),
        "holes": [],
        "bars": [(0.05, 0.05, 1473.0)],
        "section": object(),
        "concrete": concrete,
        "steel": steel,
        "prestress": None,
        "tendons": [],
        "P_pl": 0.0,
        "Mx_pl": 100.0,
        "My_pl": 0.0,
        "shear_on": True,
        "shear_method": codes.EC2_2005_DKNA.label,
        "shear_axis": "x",
        "shear_tension": True,
        "shear_bw": 0.0,
        "shear_dlower": 16.0,
        "shear_V": 75.0,
        "shear_links": False,
        "shear_cot_min": 1.0,
        "shear_cot_max": 2.5,
        "shear_link_legs": 2,
        "shear_link_dia": 10.0,
        "shear_link_s": 150.0,
        "shear_fywk": 550.0,
        "torsion_on": False,
        "torsion_method": codes.EC2_2005_DKNA.label,
        "torsion_tef": 0.0,
        "torsion_cot_min": 1.0,
        "torsion_cot_max": 2.5,
        "torsion_nu_v": False,
        "torsion_T": 40.0,
        "torsion_subdivide": False,
        "torsion_subrects": [],
        "combined_on": False,
        "combined_method": "DS/EN 1992-1-1 + DK NA",
        "combined_mv_independent": False,
    }
    inp.update(overrides)
    return inp


def test_capacity_module_has_no_ui_dependency():
    """Engineering orchestration must remain importable without Streamlit."""
    source = pathlib.Path(capacity.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not any(name == "streamlit" or name.startswith("streamlit.") for name in imports)


def test_build_shear_context_returns_payload_without_ui():
    inp = _member_input()
    payload, links = capacity.build_shear_context(inp, 0.0, 0.0)
    assert links is None
    assert payload["res"]["valid"]
    assert payload["axis"] == "x"
    assert payload["bw"] == pytest.approx(300.0)
    assert payload["d"] == pytest.approx(550.0)
    assert payload["asl"] == pytest.approx(1473.0)
    assert payload["centroid"] == pytest.approx((0.15, 0.30))


def test_build_torsion_context_accepts_exact_partition_and_rejects_gap():
    valid = _member_input(
        torsion_on=True,
        torsion_subdivide=True,
        torsion_subrects=[(150.0, 300.0, 300.0, 600.0)],
    )
    ctx = capacity.build_torsion_context(valid, 0.0)
    assert ctx["subdivision_requested"]
    assert ctx["subdivision_valid"]
    assert ctx["subdivide"]
    assert ctx["sub_dims"] == [(150.0, 300.0, 300.0, 600.0)]

    invalid = dict(valid)
    invalid["torsion_subrects"] = [(150.0, 300.0, 290.0, 600.0)]
    bad = capacity.build_torsion_context(invalid, 0.0)
    assert not bad["subdivision_valid"]
    assert not bad["subdivide"]
    assert not bad["tube"]["valid"]
    assert "invalid sub-tube partition" in bad["tube"]["reason"]


def test_finalize_combined_builds_valid_payload():
    inp = _member_input(combined_on=True)
    out = {
        "plastic": {"util": 0.20},
        "shear": {"res": {"valid": True}, "util": 0.30},
        "torsion": {
            "valid": True,
            "util": 0.40,
            "code_applicable": True,
            "interaction": None,
            "asl_req": 125.0,
            "asw_over_s": 0.0,
        },
    }
    capacity.finalize_combined(inp, out)
    result = out["combined"]
    assert result["valid"]
    assert result["dkna_sum"] == pytest.approx(0.90)
    assert result["dkna_ok"]
    assert result["r_m"] == pytest.approx(0.20)
    assert result["r_v"] == pytest.approx(0.30)
    assert result["r_t"] == pytest.approx(0.40)


def test_finalize_combined_discloses_missing_component():
    inp = _member_input(combined_on=True)
    out = {
        "plastic": {"util": 0.20},
        "shear": {"res": {"valid": True}, "util": 0.30},
    }
    capacity.finalize_combined(inp, out)
    assert out["combined"] == {
        "valid": False,
        "have_m": True,
        "have_v": True,
        "have_t": False,
        "method": inp["combined_method"],
    }
