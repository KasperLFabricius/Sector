"""Independent oracle for the downloadable F-036 reference project."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import load_cases  # noqa: E402
import project_io  # noqa: E402
import reference_project  # noqa: E402
from sector.build_info import source_revision  # noqa: E402
from sector.combined import radial_util_result  # noqa: E402
from sector.elastic import solve_elastic_combined  # noqa: E402
from sector.materials import Concrete, MildSteel  # noqa: E402
from sector.plastic import solve_plastic  # noqa: E402
from sector.section import Section  # noqa: E402
from sector.serviceability import (  # noqa: E402
    analyse_cracking,
    combined_cracking,
    crack_width,
)


def _saved_inputs():
    text = reference_project.project_download()
    tables, scalars = project_io.parse_project(text)
    return text, tables, scalars


def _independent_model(tables, scalars):
    corners = [
        (float(row["x (mm)"]) / 1000.0, float(row["y (mm)"]) / 1000.0)
        for row in tables["corners_base"].to_dict("records")
    ]
    bar_rows = tables["bars_base"].to_dict("records")
    bars = [
        (
            float(row["x (mm)"]) / 1000.0,
            float(row["y (mm)"]) / 1000.0,
            float(row["area (mm2)"]),
        )
        for row in bar_rows
    ]
    section = Section.from_polygon(corners=corners, bars_xy_area_mm2=bars)
    concrete = Concrete(
        fck=float(scalars["conc_fck"]),
        gamma_c=float(scalars["conc_gamma_c"]),
        curve=2,
        alpha_cc=float(scalars["conc_alpha_cc"]),
        eps_c2=float(scalars["conc_eps_c2"]) / 1000.0,
        eps_cu2=float(scalars["conc_eps_cu2"]) / 1000.0,
        n=float(scalars["conc_n"]),
    )
    steel = MildSteel(
        fytk=float(scalars["mild_fytk"]),
        fyck=float(scalars["mild_fyck"]),
        futk=float(scalars["mild_futk"]),
        eut=float(scalars["mild_eut"]) / 1000.0,
        gamma_y=float(scalars["mild_gamma_y"]),
        gamma_u=float(scalars["mild_gamma_u"]),
        gamma_E=float(scalars["mild_gamma_E"]),
        curve=3,
        k=float(scalars["mild_k"]),
        ey0t=float(scalars["mild_ey0t"]) / 1000.0,
        ey0c=float(scalars["mild_ey0c"]) / 1000.0,
        Es=float(scalars["mild_Es"]) * 1000.0,
        active_in_compression=bool(scalars["mild_active_comp"]),
    )
    return section, concrete, steel, bar_rows


def test_reference_download_is_current_schema_with_genuine_provenance():
    text, tables, scalars = _saved_inputs()
    payload = json.loads(text)
    provenance = project_io.project_provenance(text)

    assert payload["format"] == project_io.FORMAT
    assert payload["version"] == 23 == project_io.VERSION
    assert payload["provenance"]["sector_version"] == "0.91"
    assert payload["provenance"]["source_revision"] == source_revision()
    assert payload["provenance"]["results_included"] is False
    assert provenance["input_hash_valid"] is True
    assert provenance["input_sha256"] == reference_project.project_input_sha256()
    assert scalars["rep_proj_no"] == "SECTOR-REF-091"
    assert scalars["rep_proj_no"] != payload["provenance"]["source_revision"]
    assert len(tables["bars_base"]) == 5
    assert set(tables["bars_base"]["material ID"]) == {"M1"}

    # A load/resave keeps the complete original-input identity. Timestamps may
    # differ and are deliberately not compared.
    resaved = project_io.dump_project(tables, scalars)
    assert project_io.project_provenance(resaved)["input_sha256"] == (
        provenance["input_sha256"]
    )


def test_reference_pack_is_bound_to_project_and_declares_exclusions():
    pack = reference_project.calculation_pack()
    digest = reference_project.project_input_sha256()

    assert digest in pack
    for token in (
        "Project schema: `23`",
        "all 24 angle solves converged",
        "0.5519771788266579",
        "0.1142440041397812 mm",
        "Optional fatigue, shear, torsion",
        "bisection cap is not an independent failure state",
        "Display formatting never feeds a calculation",
    ):
        assert token in pack


def test_frozen_oracle_reconstructs_unrounded_plastic_result_from_inputs():
    _text, tables, scalars = _saved_inputs()
    section, concrete, steel, _bars = _independent_model(tables, scalars)
    action = tables[load_cases.PLASTIC_TABLE_KEY].iloc[0]

    # A full turn omits the duplicated 360-degree endpoint, matching the app's
    # accepted envelope mechanics while deriving the actual angle list here.
    last_angle = float(scalars["v_max"]) - float(scalars["v_inc"])
    points = solve_plastic(
        section,
        concrete,
        steel,
        float(action["n_ed_kn"]),
        float(scalars["v_min"]),
        last_angle,
        float(scalars["v_inc"]),
    )
    radial = radial_util_result(
        [point.Mx for point in points],
        [point.My for point in points],
        float(action["mx_ed_knm"]),
        float(action["my_ed_knm"]),
    )

    assert len(points) == 24
    assert all(point.converged for point in points)
    assert radial.demand == pytest.approx(182.4828759089466, rel=1e-12)
    assert radial.resistance == pytest.approx(330.5985879649080, rel=1e-12)
    assert radial.utilisation == pytest.approx(0.5519771788266579, rel=1e-12)
    assert radial.governing_index == 3
    governing = points[radial.governing_index]
    assert governing.V == pytest.approx(45.0)
    assert governing.Mx == pytest.approx(323.4705855644198, rel=1e-12)
    assert governing.My == pytest.approx(58.22334819001088, rel=1e-12)
    assert governing.axial_residual == pytest.approx(
        8.436700227321126e-10, abs=1e-15
    )
    assert governing.axial_reachable is True
    assert abs(governing.axial_residual) <= governing.axial_tolerance


def test_frozen_oracle_reconstructs_elastic_and_crack_results_from_inputs():
    _text, tables, scalars = _saved_inputs()
    section, _concrete, steel, bar_rows = _independent_model(tables, scalars)
    action = tables[load_cases.ELASTIC_TABLE_KEY].iloc[0]
    ec_mpa = float(scalars["conc_Ec"]) * 1000.0
    nl = steel.Es * (1.0 + float(scalars["el_phi"])) / ec_mpa
    ns = steel.Es / ec_mpa

    result = solve_elastic_combined(
        section,
        float(action["n_long_ed_kn"]),
        float(action["mx_long_ed_knm"]),
        float(action["my_long_ed_knm"]),
        nl,
        float(action["n_short_ed_kn"]),
        float(action["mx_short_ed_knm"]),
        float(action["my_short_ed_knm"]),
        ns,
    )
    total_mpa = result.bar_stress_total / 1000.0
    assert result.converged is True
    assert total_mpa == pytest.approx([
        163.1938982695797,
        128.33217244841316,
        93.47044662724659,
        -23.970703497881885,
        -93.694155140215,
    ], rel=1e-12)
    assert result.max_concrete_compression / 1000.0 == pytest.approx(
        9.056070470526570, rel=1e-12
    )

    diameters = [float(row["diameter (mm)"]) for row in bar_rows]
    crack_long = analyse_cracking(
        section,
        float(action["n_long_ed_kn"]),
        float(action["mx_long_ed_knm"]),
        float(action["my_long_ed_knm"]),
        nl,
        fctm=float(scalars["sls_fctm"]),
        Es=[steel.Es] * len(bar_rows),
        beta=0.5,
        kt=0.4,
        bar_diameter=diameters,
        k1=[0.8] * len(bar_rows),
        k3_cover_dependent=True,
        include_hx_term=False,
        edition="2004",
    )
    cracked_peak, lambda_peak, _sigma_peak = combined_cracking(
        section,
        float(action["n_long_ed_kn"]),
        float(action["mx_long_ed_knm"]),
        float(action["my_long_ed_knm"]),
        nl,
        float(action["n_short_ed_kn"]),
        float(action["mx_short_ed_knm"]),
        float(action["my_short_ed_knm"]),
        ns,
        fctm=float(scalars["sls_fctm"]),
    )
    short_state = dataclasses.replace(
        result.short_term,
        bar_stress=np.asarray(result.bar_stress_total, dtype=float),
    )
    short_crack = crack_width(
        section,
        short_state,
        ns,
        fctm=float(scalars["sls_fctm"]),
        Es=[steel.Es] * len(bar_rows),
        kt=0.6,
        bar_diameter=diameters,
        k1=[0.8] * len(bar_rows),
        k3_cover_dependent=True,
        include_hx_term=False,
        edition="2004",
        reinforcement_types=["mild"] * len(bar_rows),
    )

    assert crack_long.cracked is False
    assert crack_long.lambda_cr == pytest.approx(1.180243298120012, rel=1e-12)
    assert cracked_peak is True
    assert lambda_peak == pytest.approx(0.7095506619292463, rel=1e-12)
    assert short_crack.wk == pytest.approx(0.1142440041397812, rel=1e-12)
    assert short_crack.sr_max == pytest.approx(233.3502362346533, rel=1e-12)
    assert short_crack.gov_bar == 0
