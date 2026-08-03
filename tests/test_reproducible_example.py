"""Independent acceptance for the PR-09B downloadable reference project."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import load_cases  # noqa: E402
import material_catalog  # noqa: E402
import project_io  # noqa: E402
import reinforcement_table  # noqa: E402
import reproducible_example  # noqa: E402
from sector import __version__  # noqa: E402
from sector.build_info import source_revision  # noqa: E402
from sector.combined import radial_util_result  # noqa: E402
from sector.elastic import solve_elastic_combined  # noqa: E402
from sector.materials import Concrete  # noqa: E402
from sector.material_presets import CONCRETE_PRESETS  # noqa: E402
from sector.plastic import solve_plastic  # noqa: E402
from sector.section import Section  # noqa: E402
from sector.serviceability import (  # noqa: E402
    analyse_cracking,
    combined_cracking,
    crack_width,
)


APP = str(ROOT / "app" / "sector_app.py")


def _parsed_project():
    return project_io.parse_project(reproducible_example.project_json())


def _independent_model():
    tables, scalars = _parsed_project()
    bars = reinforcement_table.valid_elements(tables["bars_base"], "bar")
    corners = (
        tables["corners_base"][["x (mm)", "y (mm)"]]
        .to_numpy(dtype=float)
        / 1000.0
    )
    section = Section.from_polygon(
        corners=corners,
        bars_xy_area_mm2=[
            (item["x_mm"] / 1000.0, item["y_mm"] / 1000.0, item["area_mm2"])
            for item in bars
        ],
    )
    concrete_preset = CONCRETE_PRESETS[scalars["conc_preset"]]
    concrete = Concrete(
        fck=scalars["conc_fck"],
        gamma_c=scalars["conc_gamma_c"],
        curve=int(concrete_preset["curve"]),
        alpha_cc=scalars["conc_alpha_cc"],
        eps_c2=scalars["conc_eps_c2"] / 1000.0,
        eps_cu2=scalars["conc_eps_cu2"] / 1000.0,
        n=scalars["conc_n"],
    )
    mild_catalog = scalars[material_catalog.MILD_CATALOG_KEY]
    mild_entry = material_catalog.entry_map(mild_catalog, "mild")["M1"]
    steel = material_catalog.build_material(mild_entry, "mild")
    return tables, scalars, bars, section, concrete, steel


def test_reference_project_is_current_genuine_and_hash_stable():
    text = reproducible_example.project_json()
    payload = json.loads(text)
    provenance = project_io.project_provenance(text)

    assert payload["format"] == project_io.FORMAT
    assert payload["version"] == project_io.VERSION == 23
    assert payload["provenance"]["sector_version"] == __version__ == "0.91"
    assert payload["provenance"]["source_revision"] == source_revision()
    assert payload["provenance"]["results_included"] is False
    assert "calculation" not in payload
    assert provenance["input_hash_valid"] is True
    assert provenance["input_sha256"] == reproducible_example.input_sha256()

    tables, scalars = project_io.parse_project(text)
    assert project_io.input_sha256(tables, scalars) == provenance["input_sha256"]
    assert project_io.project_provenance(
        project_io.dump_project(tables, scalars, app_version=__version__)
    )["input_sha256"] == provenance["input_sha256"]

    bars = reinforcement_table.valid_elements(tables["bars_base"], "bar")
    assert [item["id"] for item in bars] == ["R1", "R2", "R3", "R4", "R5"]
    assert {item["material_id"] for item in bars} == {"M1"}
    entry = material_catalog.entry_map(
        scalars[material_catalog.MILD_CATALOG_KEY], "mild"
    )["M1"]
    assert entry["name"] == "B550 reinforcement"
    assert entry["preset"] == reproducible_example.DK_PRESET
    for key in (
        "fatigue_on",
        "minimum_reinforcement_on",
        "transverse_detailing_on",
        "clear_spacing_on",
        "shear_on",
        "torsion_on",
        "combined_on",
    ):
        assert scalars[key] is False


def test_checking_pack_seals_every_exceptional_method_branch():
    text = " ".join(reproducible_example.checking_pack().split())
    for expected in (
        "bisection cap is not an independent failure flag",
        "start from zero",
        "A singular iteration tangent",
        "nearest forward crossing",
        "equal endpoint distances select the first endpoint",
        "fully dominated unresolved heaps are converged",
        "best sampled damage is positive infinity",
        "converged true",
        "absolute and relative gaps remain infinity",
        "six-significant-digit diagnostic formatting",
        reproducible_example.input_sha256(),
    ):
        assert expected in text


def test_reference_mechanics_reconstruct_from_parsed_original_inputs():
    tables, scalars, bars, section, concrete, steel = _independent_model()
    plastic_case = load_cases.table_records(
        tables[load_cases.PLASTIC_TABLE_KEY], load_cases.PLASTIC_TABLE_KEY
    )[0]
    elastic_case = load_cases.table_records(
        tables[load_cases.ELASTIC_TABLE_KEY], load_cases.ELASTIC_TABLE_KEY
    )[0]

    points = solve_plastic(
        section,
        concrete,
        steel,
        -plastic_case["n_ed_kn"],
        scalars["v_min"],
        scalars["v_max"] - scalars["v_inc"],
        scalars["v_inc"],
        bar_materials=[steel] * len(bars),
    )
    assert len(points) == 24
    assert all(point.converged for point in points)
    radial = radial_util_result(
        [point.Mx for point in points],
        [point.My for point in points],
        plastic_case["mx_ed_knm"],
        plastic_case["my_ed_knm"],
    )
    assert radial.demand == pytest.approx(182.4828759089466, abs=1e-12)
    assert radial.resistance == pytest.approx(330.5985879649080, abs=1e-12)
    assert radial.utilisation == pytest.approx(0.5519771788266579, abs=1e-15)
    assert radial.governing_index == 3
    governing = points[radial.governing_index]
    assert governing.V == 45.0
    assert governing.Mx == pytest.approx(323.4705855644198, abs=1e-12)
    assert governing.My == pytest.approx(58.22334819001088, abs=1e-12)
    assert governing.axial_residual == pytest.approx(
        8.436700227321126e-10, abs=1e-18
    )

    ec_mpa = scalars["conc_Ec"] * 1000.0
    nl = steel.Es / (ec_mpa / (1.0 + scalars["el_phi"]))
    ns = steel.Es / ec_mpa
    elastic = solve_elastic_combined(
        section,
        -elastic_case["n_long_ed_kn"],
        elastic_case["mx_long_ed_knm"],
        elastic_case["my_long_ed_knm"],
        nl,
        -elastic_case["n_short_ed_kn"],
        elastic_case["mx_short_ed_knm"],
        elastic_case["my_short_ed_knm"],
        ns,
    )
    assert elastic.converged
    assert elastic.bar_stress_total / 1000.0 == pytest.approx(
        [
            163.1938982695797,
            128.33217244841316,
            93.47044662724659,
            -23.970703497881885,
            -93.694155140215,
        ],
        abs=1e-12,
    )
    assert elastic.max_concrete_compression / 1000.0 == pytest.approx(
        9.05607047052657, abs=1e-14
    )

    diameters = [item["diameter_mm"] for item in bars]
    long_cracking = analyse_cracking(
        section,
        -elastic_case["n_long_ed_kn"],
        elastic_case["mx_long_ed_knm"],
        elastic_case["my_long_ed_knm"],
        nl,
        fctm=scalars["sls_fctm"],
        Es=[steel.Es] * len(bars),
        beta=0.5,
        kt=0.4,
        bar_diameter=diameters,
        k1=[0.8] * len(bars),
        k3_cover_dependent=True,
        include_hx_term=False,
        edition="2004",
    )
    _peak_cracked, peak_factor, _peak_stress = combined_cracking(
        section,
        -elastic_case["n_long_ed_kn"],
        elastic_case["mx_long_ed_knm"],
        elastic_case["my_long_ed_knm"],
        nl,
        -elastic_case["n_short_ed_kn"],
        elastic_case["mx_short_ed_knm"],
        elastic_case["my_short_ed_knm"],
        ns,
        fctm=scalars["sls_fctm"],
    )
    assert long_cracking.lambda_cr == pytest.approx(
        1.180243298120012, abs=1e-14
    )
    assert peak_factor == pytest.approx(0.7095506619292463, abs=1e-14)

    short_state = dataclasses.replace(
        elastic.short_term,
        bar_stress=np.asarray(elastic.bar_stress_total, dtype=float),
    )
    short_crack = crack_width(
        section,
        short_state,
        ns,
        fctm=scalars["sls_fctm"],
        Es=[steel.Es] * len(bars),
        kt=0.6,
        bar_diameter=diameters,
        k1=[0.8] * len(bars),
        k3_cover_dependent=True,
        include_hx_term=False,
        edition="2004",
    )
    assert short_crack is not None
    assert short_crack.wk == pytest.approx(0.11424400413978118, abs=1e-15)
    assert short_crack.sr_max == pytest.approx(233.3502362346533, abs=1e-12)
    assert short_crack.gov_bar == 0


def test_applied_ray_tie_uses_first_chord_endpoint():
    result = radial_util_result(
        [1.0, 0.0, -1.0, 0.0],
        [0.0, 1.0, 0.0, -1.0],
        1.0,
        1.0,
    )
    assert result.governing_index == 0
    assert result.demand == pytest.approx(2.0**0.5)
    assert result.resistance == pytest.approx(2.0**-0.5)


def test_reference_download_loads_and_calculates_in_the_real_app():
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["_pending_project"] = reproducible_example.project_json()
    at.run()
    assert not at.exception
    at.session_state["_main_page"] = "Analysis"
    at.run()
    at.button(key="calculate").click().run()
    assert not at.exception

    results = at.session_state["results"]
    plastic = results["plastic"]
    elastic = results["elastic"]
    assert plastic["util"] == pytest.approx(0.5519771788266579, abs=1e-15)
    assert plastic["util_gov"] == 3
    assert elastic["total"] == pytest.approx(
        [
            163.1938982695797,
            128.33217244841316,
            93.47044662724659,
            -23.970703497881885,
            -93.694155140215,
        ],
        abs=1e-12,
    )
    assert elastic["max_conc"] == pytest.approx(9.05607047052657, abs=1e-14)
    assert elastic["lambda_cr"] == pytest.approx(
        0.7095506619292463, abs=1e-14
    )
    assert elastic["crack_short"]["wk"] == pytest.approx(
        0.11424400413978118, abs=1e-15
    )
    assert elastic["crack_short"]["element_id"] == "R1"
    assert at.session_state["calculation_record"]["source_revision"] == (
        source_revision()
    )
