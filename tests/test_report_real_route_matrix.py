"""Executable real-route coverage matrix for the report equation catalogue."""

from __future__ import annotations

import copy
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import material_catalog
import report_equation_contract as contracts
import result_presentation
import sector_report
import test_report as report_data

from sector import codes, detailing, shear
from sector.section import Section
from tools import report_render_fixture

_PRODUCTION_BUILD_REPORT = report_data._build_report_from_completed_payload
_STEEL_EQUATION_KEY = re.compile(r"materials\.steel\.fyd-\d+")


def _canonical(identity: tuple[str, str | None]) -> tuple[str, str | None]:
    key, variant = identity
    if _STEEL_EQUATION_KEY.fullmatch(key):
        key = "materials.steel.fyd-N"
    return key, variant


def _complete(inp: dict, out: dict) -> tuple[dict, dict]:
    out["worked_example_selection"] = (
        result_presentation.worked_example_selection(inp, out)
    )
    return inp, out


def _build(inp: dict, out: dict, scenario: str) -> bytes:
    return _PRODUCTION_BUILD_REPORT(
        {
            "proj_no": f"QA-PR07A-{scenario}",
            "proj_name": "Equation real-route matrix",
            "section": scenario,
            "author": "Sector QA",
        },
        inp,
        out,
        figures=False,
        qa_appendix=False,
    )


def _minimum_2023(inp: dict, *, tension: bool) -> dict:
    section = Section.from_polygon(inp["outer"], inp["bars"])
    elements = [
        {"id": f"R{index + 1}", "material_id": "M1"}
        for index, _bar in enumerate(inp["bars"])
    ]
    materials = [inp["steel"]] * len(elements)
    return detailing.minimum_reinforcement(
        section,
        elements,
        materials,
        inp["concrete"],
        edition=detailing.EC2_2023,
        fctm_mpa=inp["sls_fctm"],
        n_ed_tension_kn=100.0 if tension else 0.0,
        mx_ed_knm=0.0 if tension else 100.0,
        my_ed_knm=0.0,
    )


def _fixture_transverse(predicate) -> dict:
    fixture_inp = report_render_fixture._inputs()
    result = copy.deepcopy(
        report_render_fixture._results(fixture_inp)["transverse_reinforcement"]
    )
    governing = next(check for check in result["checks"] if predicate(check))
    result["governing"] = copy.deepcopy(governing)
    result["governing_utilisation"] = governing["utilisation"]
    result["status"] = governing["status"]
    return result


def _set_transverse(inp: dict, out: dict, predicate) -> None:
    result = _fixture_transverse(predicate)
    inp["transverse_detailing_on"] = True
    inp["detailing_edition"] = result["edition"]
    inp["detailing_member_type"] = result["member_type"]
    out["transverse_reinforcement"] = result


def _add_builtin_prestress(inp: dict, out: dict) -> None:
    entry = material_catalog.default_entry(
        "prestress", preset="Curve 1 (built-in)"
    )
    law = material_catalog.build_material(entry, "prestress")
    inp.update(
        {
            "tendons": [(0.0, -0.12, 5.0e-4)],
            "tendon_elements": [
                {
                    "id": "T1",
                    "x_mm": 0.0,
                    "y_mm": -120.0,
                    "area_mm2": 500.0,
                    "diameter_mm": 25.23,
                    "size_mode": "Area",
                    "material_id": "P1",
                    "fatigue_detail_id": "",
                }
            ],
            "prestress_material_catalog": {
                "version": 1,
                "next_id": 2,
                "items": [entry],
            },
            "prestress_materials": {"P1": law},
            "tendon_materials": [law],
            "prestress": law,
            "prestress_preset": entry["preset"],
        }
    )
    locked_stress = law.Es * law.IS
    force = locked_stress * 500.0 / 1000.0
    out["material_properties"]["prestress"] = [
        {
            "material_id": "P1",
            "characteristic_stress_at_rupture_mpa": law.stress(
                law.rupture_strain, design=False
            ),
        }
    ]
    out["prestress_initial"] = {
        "elements": [
            {
                "tendon_index": 0,
                "element_id": "T1",
                "material_id": "P1",
                "initial_strain": law.IS,
                "modulus_mpa": law.Es,
                "locked_in_stress_mpa": locked_stress,
                "area_mm2": 500.0,
                "force_kn": force,
                "x_m": 0.0,
                "y_m": -0.12,
                "mx_knm": force * -0.12,
                "my_knm": 0.0,
            }
        ],
        "internal_resultant_origin": {
            "n_kn": force,
            "mx_knm": force * -0.12,
            "my_knm": 0.0,
        },
        "equivalent_action_origin": {
            "n_kn": -force,
            "mx_knm": force * -0.12,
            "my_knm": 0.0,
        },
    }


def _equivalent_fatigue(inp: dict, out: dict) -> None:
    method = "Damage-equivalent stress amplitude"
    inp["fatigue_concrete_method"] = method
    payload = out["fatigue"]
    payload["concrete_method"] = method
    payload["concrete_parameters"]["method"] = method
    for spectrum in payload["spectra"]:
        spectrum.concrete_method = method
        for result in spectrum.concrete:
            result.method = method
            result.equivalent_utilisation = 0.82
            result.governing_equivalent_bin = result.bins[0].bin_name
            result.damage = 0.0
            result.damage_utilisation = 0.0
            result.utilisation = 0.82
            for item in result.bins:
                item.damage = 0.0
                item.cycles_to_failure = math.inf
                item.log10_cycles_to_failure = math.inf
                item.equivalent_utilisation = 0.82
        spectrum.concrete_search.method = method
        spectrum.concrete_search.damage = 0.82
        spectrum.concrete_search.upper_damage = 0.821


def _set_governing_concrete_life(out: dict, branch: str) -> None:
    payload = out["fatigue"]
    selection = payload["governing_concrete_example"]
    spectrum = next(
        item
        for item in payload["spectra"]
        if item.spectrum_name == selection["spectrum_name"]
    )
    result = next(
        item
        for item in spectrum.concrete
        if item.fibre_index == selection["fibre_index"]
    )
    fatigue_bin = next(
        item for item in result.bins if item.bin_name == selection["bin_name"]
    )
    fatigue_bin.life_branch = branch
    fatigue_bin.cycles_to_failure = math.inf
    fatigue_bin.log10_cycles_to_failure = math.inf
    fatigue_bin.damage = 0.0
    fatigue_bin.life_coefficient = 14.0
    fatigue_bin.life_range_term = 0.0
    if branch == "zero compression":
        fatigue_bin.compression_long_mpa = 0.0
        fatigue_bin.compression_total_mpa = 0.0
        fatigue_bin.compression_min_design_mpa = 0.0
        fatigue_bin.compression_max_design_mpa = 0.0
        fatigue_bin.compression_total_design_mpa = 0.0
        fatigue_bin.e_cd_min = 0.0
        fatigue_bin.e_cd_max = 0.0
        fatigue_bin.stress_ratio = 0.0
    else:
        maximum = fatigue_bin.compression_max_design_mpa
        fatigue_bin.compression_min_design_mpa = maximum
        fatigue_bin.compression_long_mpa = fatigue_bin.compression_total_mpa
        fatigue_bin.e_cd_min = fatigue_bin.e_cd_max
        fatigue_bin.stress_ratio = 1.0


def _set_governing_reinforcement_zero_range(out: dict) -> None:
    payload = out["fatigue"]
    selection = payload["governing_reinforcement_example"]
    spectrum = next(
        item
        for item in payload["spectra"]
        if item.spectrum_name == selection["spectrum_name"]
    )
    result = next(
        item
        for item in spectrum.reinforcement
        if item.element_id == selection["element_id"]
    )
    fatigue_bin = next(
        item for item in result.bins if item.bin_name == selection["bin_name"]
    )
    fatigue_bin.stress_total_design_elastic_mpa = fatigue_bin.stress_long_mpa
    fatigue_bin.design_stress_range_elastic_mpa = 0.0
    fatigue_bin.design_stress_range_mpa = 0.0
    fatigue_bin.sn_reference_ratio = None
    fatigue_bin.cycles_to_failure = math.inf
    fatigue_bin.log10_cycles_to_failure = math.inf
    fatigue_bin.damage = 0.0
    fatigue_bin.sn_branch = "zero stress range"


def _shear_links_2023() -> dict:
    area = 2.0 * math.pi * 10.0**2 / 4.0
    result = shear.vrd_links(
        35.0,
        codes.EC2_2023,
        300.0,
        550.0,
        area / 150.0,
        500.0,
        0.0,
        0.18,
        1.0,
        2.5,
        fcd_mpa=20.0,
        gamma_s=1.15,
        v_ed_kn=50.0,
    )
    return {
        "res": result,
        "util": 50.0 / result["vrd"],
        "asw": area,
        "asw_over_s": area / 150.0,
        "legs": 2.0,
        "dia": 10.0,
        "s": 150.0,
        "fywk": 500.0,
        "cot_min": 1.0,
        "cot_max": 2.5,
        "delta_ftd": None,
        "longitudinal_shear_force": 50.0 * result["cot"],
        "cot_limit_lo": 1.0,
        "cot_limit_hi": 2.5,
        "angle_limits": {
            "clause": "DS/EN 1992-1-1:2023, 8.2.3(4), Formula (8.41)"
        },
        "model_2023": True,
        "z_source": "0.9 d",
        "out_of_limits": False,
        "required": False,
    }


def _add_shear_chord(links: dict, *, model_2023: bool) -> None:
    force = float(links["longitudinal_shear_force"])
    lever = float(links["res"]["z"]) / 1000.0
    moment_increment = force * lever
    moment = 75.0
    resistance = 400.0
    total = moment + moment_increment
    chord = {
        "valid": True,
        "axis": "x",
        "z": lever,
        "m_ed": moment,
        "m_rd": resistance,
        "ftd_v": force,
        "ftd_t": 0.0,
        "mv": moment_increment,
        "mt": 0.0,
        "m_total": total,
        "util": total / resistance,
        "ok": total <= resistance,
        "capped": False,
        "tension_low": True,
        "m_off": 0.0,
        "conditional": True,
        "gets_shift": True,
        "has_torsion": False,
        "theta_mode": "utilisation",
    }
    links["chord"] = chord
    links["chord_off"] = None
    links["chord_candidates"] = [chord]
    links["model_2023"] = model_2023


def _subdivided_torsion() -> dict:
    torsion = report_data._torsion_out(interaction=True)
    subtubes = [
        report_data._subtube(
            300,
            600,
            100.0,
            0.10,
            0.0037,
            24.6,
            90.0,
            24.6 / 90.0,
            "stirrups (TRd,s)",
            0.0,
            -100.0,
        ),
        report_data._subtube(
            1000,
            200,
            91.0,
            0.15,
            0.0023,
            15.4,
            20.0,
            15.4 / 20.0,
            "crushing (TRd,max)",
            0.0,
            300.0,
        ),
    ]
    torsion["subdivided"] = True
    torsion["subtubes"] = subtubes
    torsion["trd"] = sum(item["trd"] for item in subtubes)
    torsion["util"] = max(item["util"] for item in subtubes)
    torsion["governing_sub"] = max(
        range(len(subtubes)), key=lambda index: subtubes[index]["util"]
    )
    torsion["asl_req"] = 1400.0
    stiffness_sum = sum(item["stiffness"] for item in subtubes)
    torsion["torque_distribution"] = {
        "applied_torque": 40.0,
        "positive_stiffness_sum": stiffness_sum,
        "shares": tuple(
            {
                "index": index,
                "stiffness": item["stiffness"],
                "fraction": item["stiffness"] / stiffness_sum,
                "torque": item["t_ed"],
            }
            for index, item in enumerate(subtubes)
        ),
    }
    return torsion


def _add_combined_chords(out: dict) -> None:
    combined = report_data._combined_out()
    combined["transverse"] = {
        "valid": True,
        "cot": 2.0,
        "theta_deg": 26.6,
        "u_stirrup": 0.6,
        "u_crush": 0.4,
        "governing": 0.6,
        "governs": "stirrups",
        "ok": True,
        "shear_fraction": 0.0,
        "torsion_fraction": 0.6,
        "shear_credited": True,
        "vrd_c": 120.0,
        "v_ed": 40.0,
    }
    combined["longitudinal"] = {
        "valid": True,
        "axis": "x",
        "z": 0.5,
        "m_ed": 20.0,
        "m_rd": 250.0,
        "ftd_v": 187.5,
        "ftd_t": 100.0,
        "mv": 60.0,
        "mt": 25.0,
        "m_total": 105.0,
        "util": 105.0 / 250.0,
        "ok": True,
        "capped": False,
        "tension_low": True,
        "off_util": 0.4,
        "biaxial": True,
        "m_off": 90.0,
        "conditional": True,
        "has_torsion": True,
    }
    combined["chord_off"] = {
        "valid": True,
        "axis": "y",
        "z": 0.3,
        "m_ed": 90.0,
        "m_rd": 180.0,
        "ftd_v": 0.0,
        "ftd_t": 100.0,
        "mv": 0.0,
        "mt": 15.0,
        "m_total": 105.0,
        "util": 105.0 / 180.0,
        "ok": True,
        "capped": False,
        "tension_low": True,
        "m_off": 20.0,
        "conditional": True,
    }
    report_data._retain_combined_chords(
        combined, combined["longitudinal"], combined["chord_off"]
    )
    out["combined"] = combined


def _scenario_1() -> tuple[dict, dict]:
    inp, fatigue_out = report_data._fatigue_report_fixture()
    out = report_data._out()
    out.update(fatigue_out)
    elastic = out["elastic"]
    elastic["crack"] = report_data._wide_crack()
    elastic["crack_short"] = report_data._wide_crack()
    elastic["crack_coarse"] = report_data._coarse_crack(wk=0.31)
    elastic["crack_short_coarse"] = report_data._coarse_crack(wk=0.24)
    _equivalent_fatigue(inp, out)
    _add_builtin_prestress(inp, out)
    out["minimum_reinforcement"] = _minimum_2023(inp, tension=False)
    _set_transverse(
        inp,
        out,
        lambda check: check["kind"] == "minimum_ratio"
        and check.get("bw_mm") is not None,
    )
    shear_out = report_data._shear_out()
    links = report_data._links_out()
    _add_shear_chord(links, model_2023=False)
    shear_out["links"] = links
    out["shear"] = shear_out
    out["torsion"] = _subdivided_torsion()
    _add_combined_chords(out)
    return _complete(inp, out)


def _scenario_2() -> tuple[dict, dict]:
    inp, fatigue_out = report_data._fatigue_report_fixture()
    out = report_data._out()
    out.update(fatigue_out)
    inp["concrete_preset"] = "DS/EN 1992-1-1:2023"
    inp["mild_preset"] = "DS/EN 1992-1-1:2023"
    out["material_properties"]["concrete"]["design_strength_mpa"] = inp[
        "concrete"
    ].fcd
    crack = report_data._crack_2023()
    out["elastic"]["crack"] = crack
    out["elastic"]["crack_short"] = copy.deepcopy(crack)
    out["minimum_reinforcement"] = _minimum_2023(inp, tension=True)
    _set_transverse(
        inp,
        out,
        lambda check: check["kind"] == "minimum_ratio"
        and check.get("tef_mm") is not None,
    )
    shear_out = report_data._shear_out_2023()
    links = _shear_links_2023()
    _add_shear_chord(links, model_2023=True)
    shear_out["links"] = links
    out["shear"] = shear_out
    _set_governing_concrete_life(out, "constant compression")
    _set_governing_reinforcement_zero_range(out)
    return _complete(inp, out)


def _scenario_3() -> tuple[dict, dict]:
    inp, fatigue_out = report_data._fatigue_report_fixture()
    out = report_data._out()
    out.update(fatigue_out)
    crack = report_data._crack_2023()
    width = 0.2
    height = 0.3
    inner_width = 0.18
    crack["effective_area_operands"] = {
        "record_kind": "CrackEffectiveArea2023Direct",
        "width": width,
        "height": height,
        "inner_width": inner_width,
        "inner_height": (width * height - crack["ac_eff"]) / inner_width,
        "ac_eff": crack["ac_eff"],
    }
    out["elastic"]["crack"] = crack
    out["elastic"]["crack_short"] = copy.deepcopy(crack)
    _set_transverse(
        inp,
        out,
        lambda check: check["kind"] == "longitudinal_spacing",
    )
    _set_governing_concrete_life(out, "zero compression")
    return _complete(inp, out)


def _scenario_4() -> tuple[dict, dict]:
    inp = report_data._inp()
    out = report_data._out()
    _set_transverse(
        inp,
        out,
        lambda check: check["kind"] == "transverse_leg_spacing",
    )
    return _complete(inp, out)


def test_normal_report_routes_cover_the_complete_equation_catalogue(
    monkeypatch,
):
    calls: list[tuple[str, str | None]] = []
    original_formula = sector_report.ReportBuilder._formula

    def capture(self, expression, *args, **kwargs):
        calls.append(
            (str(kwargs["equation_key"]), kwargs.get("equation_variant"))
        )
        return original_formula(self, expression, *args, **kwargs)

    monkeypatch.setattr(sector_report.ReportBuilder, "_formula", capture)

    def run(build) -> tuple[tuple[str, str | None], ...]:
        calls.clear()
        pdf = build()
        assert pdf.startswith(b"%PDF")
        return tuple(calls)

    report_render_fixture.build_fixture_pdf.cache_clear()
    raw = {
        "S0": run(
            lambda: report_render_fixture.build_fixture_pdf(figures=False)
        ),
        "S1": run(lambda: _build(*_scenario_1(), "S1")),
        "S2": run(lambda: _build(*_scenario_2(), "S2")),
        "S3": run(lambda: _build(*_scenario_3(), "S3")),
        "S4": run(lambda: _build(*_scenario_4(), "S4")),
    }
    actual = {
        scenario: {_canonical(identity) for identity in identities}
        for scenario, identities in raw.items()
    }
    expected = {
        identity for identity, _contract in contracts.equation_contract_items()
    }

    # S0 intentionally retains a pre-origin-contract plastic payload, so the
    # report suppresses its stale Combined worked blocks. Its governing overview
    # now publishes current equation families that previously appeared first in
    # S1. S1 still owns the remaining current routes, including the prestress
    # threshold.
    assert len(raw["S0"]) == 88
    assert len(actual["S0"]) == 87
    assert len(expected - actual["S0"]) == 57

    covered = set(actual["S0"])
    for scenario, expected_increment in zip(
        ("S1", "S2", "S3", "S4"), (32, 21, 3, 1), strict=True
    ):
        increment = actual[scenario] - covered
        assert len(increment) == expected_increment
        covered.update(actual[scenario])
    assert covered == expected
