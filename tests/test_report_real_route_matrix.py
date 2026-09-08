"""Executable real-route coverage matrix for the report equation catalogue."""

from __future__ import annotations

import copy
import functools
import json
import pickle
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest

import material_catalog
import report_equation_contract as contracts
import result_presentation
import sector_report
import test_report as report_data

from native_member_report_fixtures import (
    native_member_report_cases, native_subdivided_report_case,
)
from test_shear import pub_m01_signed_2023_cases
from sector import detailing
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
        profile="Audit",
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


@functools.cache
def _default_transverse_bundle() -> dict:
    fixture_inp = report_render_fixture._inputs()
    return report_render_fixture._results(fixture_inp)["transverse_reinforcement"]


def _fixture_transverse(predicate) -> dict:
    result = copy.deepcopy(_default_transverse_bundle())
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




def _verify_native_members(inp, out, *, combined):
    rows = out.get("plastic_cases") or ()
    assert rows
    for row in rows:
        case_input = report_data.case_analysis.plastic_case_input(inp, row["actions"])
        members = row["results"]
        shear = members["shear"]
        torsion = members["torsion"]
        assert result_presentation.directional_shear_publication_evidence_is_current(
            case_input, shear, plastic_result=members["plastic"],
        ) == (True, None)
        assert result_presentation.torsion_publication_evidence_is_current(
            case_input, shear, torsion,
        ) == (True, None)
        if combined:
            assert result_presentation.combined_publication_evidence_is_current(
                case_input, members,
            ) == (True, None)


@pytest.mark.xdist_group("native-member-report")
@result_presentation.publication_calculation_scope()
def test_normal_report_routes_cover_the_complete_equation_catalogue(
    monkeypatch, tmp_path, native_member_report_cases,
    native_subdivided_report_case, pub_m01_signed_2023_cases,
):
    calls: list[tuple[str, str | None]] = []
    original_formula = sector_report.ReportBuilder._formula

    def capture(self, expression, *args, **kwargs):
        value = original_formula(self, expression, *args, **kwargs)
        calls.append((str(kwargs["equation_key"]), kwargs.get("equation_variant")))
        return value

    monkeypatch.setattr(sector_report.ReportBuilder, "_formula", capture)
    scenarios = {}
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    report_render_fixture.validate_fixture_engineering(inp, out)
    scenarios["S0"] = (inp, out)
    for name, factory in (("S1", _scenario_1), ("S2", _scenario_2),
                          ("S3", _scenario_3), ("S4", _scenario_4)):
        scenarios[name] = factory()
    scenarios["S5-native-2005"] = copy.deepcopy(native_member_report_cases["biaxial"])
    scenarios["S5-native-2005-zero-bending"] = copy.deepcopy(native_member_report_cases["two-face"])
    for sign, label in ((1, "positive"), (-1, "negative")):
        native = pub_m01_signed_2023_cases[sign]
        scenarios["S6-native-2023-" + label] = copy.deepcopy((native["input"], native["results"]))
    scenarios["S7-native-subdivided"] = copy.deepcopy(native_subdivided_report_case)
    for name, (inp, out) in scenarios.items():
        if name.startswith(("S5-", "S6-", "S7-")):
            _verify_native_members(inp, out, combined=name.startswith("S5-"))

    raw = {}
    actual = {}
    for name, (inp, out) in scenarios.items():
        _complete(inp, out)
        before = pickle.dumps((inp, out))
        calls.clear()
        pdf = _build(inp, out, name)
        (tmp_path / (name + ".pdf")).write_bytes(pdf)
        assert pdf.startswith(b"%PDF")
        raw[name] = tuple(calls)
        actual[name] = {_canonical(identity) for identity in calls}
        (tmp_path / (name + "-equations.json")).write_text(json.dumps({
            "raw": raw[name], "canonical": sorted(actual[name], key=repr),
        }, indent=2), encoding="utf-8")
        assert pickle.dumps((inp, out)) == before

    supported = {identity for identity, _ in contracts.supported_equation_contract_items()}
    deferred = {identity for identity, _ in contracts.deferred_equation_contract_items()}
    catalogue = {identity for identity, _ in contracts.equation_contract_items()}
    covered = set().union(*actual.values())
    (tmp_path / "coverage.json").write_text(json.dumps({
        "counts": {name: {"raw": len(raw[name]), "unique": len(identities)}
                   for name, identities in actual.items()},
        "supported": sorted(supported, key=repr),
        "covered": sorted(covered, key=repr),
        "missing": sorted(supported - covered, key=repr),
        "extra": sorted(covered - supported, key=repr),
        "deferred": sorted(deferred, key=repr),
    }, indent=2), encoding="utf-8")
    assert len(catalogue) == 145 and len(supported) == 144
    assert deferred == {("combined.chord.demand", "2023")}
    assert supported.isdisjoint(deferred) and supported | deferred == catalogue
    assert all(any(key.startswith(family + ".") for key, _ in actual["S0"])
               for family in ("shear", "torsion", "combined"))
    assert {("combined.chord.demand", None), ("combined.chord.utilisation", None)} <= actual["S5-native-2005"]
    assert ("torsion.minimum-reinforcement.screen", None) in actual["S5-native-2005-zero-bending"]
    for name in ("S6-native-2023-positive", "S6-native-2023-negative"):
        assert {("shear.chord.demand", "2023"), ("shear.2023.vrdc", None)} <= actual[name]
    assert {("torsion.subtube." + suffix, None) for suffix in (
        "governing-utilisation", "stiffness-share", "torque-share",
    )} <= actual["S7-native-subdivided"]
    assert not covered & deferred
    assert covered == supported, {"missing": sorted(supported - covered, key=repr),
                                  "extra": sorted(covered - supported, key=repr)}
