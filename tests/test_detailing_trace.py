"""Independent CT-008 numerical, inventory, provenance, and graph controls."""

from __future__ import annotations

import copy
import dataclasses
import math
from collections.abc import Mapping

import pytest

from app import material_catalog
from app.sector_app import (
    _run_capacity_checks, _transverse_detailing_result, run_analysis,
)
from sector import codes, detailing, templates
from sector.calculation_trace import (
    TraceDependency, TraceUnit, TraceValidationError, seal_bundle,
)
from sector import capacity
from sector.detailing_trace import (
    _long_branch, _replay_clear, _replay_longitudinal, _replay_screen,
    _replay_transverse, _validate_clear_candidate,
    _validate_longitudinal_candidate, _validate_screen_member,
    _validate_transverse_candidate, build_detailing_trace_family,
    detailing_trace_applicability, validate_detailing_trace_family,
)
from sector.detailing_trace_contract import (
    ADAPTER_SOURCE, DetailingShape, RATIO_SOURCE_2023, RATIO_SOURCE_BASE,
    RATIO_SOURCE_DK, REQUIRED_LINKS_RES_2023, SCREEN_STATE_CODES,
    STATUS_CODES, concrete_leaf_id, expected_registry,
)
from sector.torsion_trace import torsion_trace_applicability
from sector.section import Section
from sector.trace_registry import audit_trace_registry


INPUT_SHA, RESULT_SHA = "a" * 64, "b" * 64
CONTEXT = {"case": "CT-008 detailing"}
PASS, FAIL = STATUS_CODES["PASS"], STATUS_CODES["FAIL"]
NA, NAP, INVALID = (STATUS_CODES["NOT ASSESSED"],
                    STATUS_CODES["NOT APPLICABLE"], STATUS_CODES["INVALID"])


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct008-detailing-no-autosave")


def _bar(identifier, x, y, dia, kind="bar"):
    return {"id": identifier, "kind": kind, "x_mm": x, "y_mm": y,
            "diameter_mm": dia}


def _input(*, method=codes.EC2_2005_DKNA, **changes):
    outer = templates.rectangle(0.3, 0.6)
    bars = [(-0.10, -0.25, 500.0)]
    entries = [material_catalog.default_entry(
        "mild", material_id=material_id, preset=method.label
    ) for material_id in ("M1", "M2")]
    steel = material_catalog.build_material(entries[1], "mild")
    inp = dict(
        outer=outer, holes=[], bars=bars, tendons=[],
        section=Section.from_polygon(outer, bars),
        concrete=method.concrete(35.0), steel=steel, prestress=None,
        concrete_preset=method.label, mild_preset=method.label,
        bar_elements=[dict(_bar("B1", -100.0, -250.0, 25.0),
                           material_id="M1")],
        bar_materials=[material_catalog.build_material(entries[0], "mild")],
        mild_material_catalog={"version": 1, "next_id": 3, "items": entries},
        capacity_steel_material_id="M2", P_pl=0.0, Mx_pl=0.0, My_pl=0.0,
        shear_on=False, shear_method=method.label, shear_axis="x",
        shear_tension=True, shear_bw=0.0, shear_dlower=16.0, shear_V=0.0,
        shear_links=False, shear_link_legs=2.0, shear_link_dia=10.0,
        shear_link_s=150.0, shear_fywk=500.0,
        strut_cot_min=1.0, strut_cot_max=2.5,
        torsion_on=False, torsion_method=method.label, torsion_tef=0.0,
        torsion_nu_v=False, torsion_gamma_ct=method.gamma_ct,
        torsion_T=0.0, torsion_subdivide=False, torsion_subrects=[],
        combined_on=False, combined_method="DS/EN 1992-1-1 + DK NA",
        combined_mv_independent=False,
        clear_spacing_on=False, transverse_detailing_on=False,
        detailing_edition=detailing.EC2_2005_DKNA,
        detailing_member_type=detailing.MEMBER_BEAM,
        detailing_d_upper=16.0, detailing_include_tendons=False,
        transverse_ductility_class="B",
        transverse_apply_ductility_reduction=False,
        shear_vx_link_legs=2.0, shear_vy_link_legs=2.0,
        shear_vx_transverse_leg_spacing=0.0,
        shear_vy_transverse_leg_spacing=0.0,
    )
    inp.update(changes)
    return inp


def _candidate(inp, upstream=None):
    """Build candidates exactly like the retained run-analysis level does."""
    out = {}
    if upstream is None:
        _run_capacity_checks(inp, out)
    else:
        out.update(upstream)
    if inp.get("transverse_detailing_on"):
        out["transverse_reinforcement"] = _transverse_detailing_result(inp, out)
    if inp.get("minimum_reinforcement_on"):
        out["minimum_reinforcement"] = detailing.minimum_reinforcement(
            inp["section"],
            inp.get("bar_elements") or [],
            inp.get("bar_materials") or [],
            inp["concrete"],
            edition=inp["detailing_edition"],
            fctm_mpa=inp["sls_fctm"],
            n_ed_tension_kn=inp["P_pl"],
            mx_ed_knm=inp["Mx_pl"],
            my_ed_knm=inp["My_pl"],
            member_type=inp.get("detailing_member_type",
                                detailing.MEMBER_BEAM),
            cut_direction=inp.get("detailing_cut_direction",
                                  detailing.CUT_TRANSVERSE),
        )
    if inp.get("clear_spacing_on"):
        out["clear_spacing"] = detailing.clear_spacing(
            list(inp.get("bar_elements") or [])
            + list(inp.get("tendon_elements") or []),
            d_upper_mm=inp["detailing_d_upper"],
            edition=inp["detailing_edition"],
            include_tendons=inp.get("detailing_include_tendons", False),
        )
    return out


def _bundle(inp, out=None, upstream=None):
    bundle = build_detailing_trace_family(
        inp, _candidate(inp, upstream) if out is None else out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA, context=CONTEXT,
    )
    assert bundle is not None
    return bundle


def _steps(bundle, member):
    for calculation in bundle.calculations:
        if calculation.calculation_id.endswith(member):
            return {step.step_id: step for step in calculation.steps}
    raise AssertionError(f"member {member} not published")


LEG_AREA = math.pi * 10.0 ** 2 / 4.0


def test_clear_spacing_pair_oracle_covers_all_three_required_terms():
    cases = (
        # (phi, d_upper, clear, expected required term)
        (32.0, 16.0, 40.0, 32.0),   # largest diameter governs
        (12.0, 30.0, 40.0, 35.0),   # d_upper + 5 governs
        (12.0, 10.0, 40.0, 20.0),   # absolute 20 mm floor governs
    )
    for phi, d_upper, clear, required in cases:
        inp = _input(clear_spacing_on=True, detailing_d_upper=d_upper)
        inp["bar_elements"] = [
            _bar("R1", 0.0, 0.0, phi),
            _bar("R2", phi + clear, 0.0, phi),
        ]
        steps = _steps(_bundle(inp), "clear-spacing")
        assert steps["pair-000-001-centre-distance"].result.value == (
            pytest.approx(phi + clear))
        assert steps["pair-000-001-clear"].result.value == pytest.approx(clear)
        assert steps["pair-000-001-required"].result.value == (
            pytest.approx(required))
        assert steps["pair-000-001-margin"].result.value == (
            pytest.approx(clear - required))
        assert steps["pair-000-001-verdict"].result.value == float(
            clear + 1e-9 >= required)
        assert steps["ct-008-clear-spacing-result"].result.value == (
            PASS if clear + 1e-9 >= required else FAIL)

    failing = _input(clear_spacing_on=True, detailing_d_upper=16.0)
    failing["bar_elements"] = [
        _bar("R1", 0.0, 0.0, 20.0),
        _bar("R2", 60.0, 0.0, 20.0),       # clear 40, PASS
        _bar("R3", 60.0, 30.0, 20.0),      # clear 10 against R2, FAIL
    ]
    steps = _steps(_bundle(failing), "clear-spacing")
    assert steps["pair-001-002-clear"].result.value == pytest.approx(10.0)
    assert steps["pair-001-002-verdict"].result.value == 0.0
    assert steps["governing-pair"].result.value == 2.0
    assert steps["governing-margin"].result.value == pytest.approx(-11.0)
    assert steps["clear-spacing-status"].result.value == FAIL
    assert steps["ct-008-clear-spacing-result"].result.value == FAIL


def test_clear_spacing_tendons_invalid_ids_and_empty_branches():
    inp = _input(clear_spacing_on=True, detailing_d_upper=16.0)
    inp["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                           _bar("R2", 65.0, 0.0, 20.0)]
    inp["tendon_elements"] = [_bar("P1", 5.0, 0.0, 10.0, kind="tendon")]
    excluded = _steps(_bundle(inp), "clear-spacing")
    assert excluded["element-002-is-bar"].result.value == 0.0
    assert excluded["element-002-included"].result.value == 0.0
    assert excluded["ct-008-clear-spacing-result"].result.value == PASS
    assert "element-002-x" not in excluded

    included = dict(inp, detailing_include_tendons=True)
    steps = _steps(_bundle(included), "clear-spacing")
    out = _candidate(included)
    # Governing bar-tendon pair: centre 5, clear 5 - 15 = -10.
    assert steps["pair-000-002-clear"].result.value == pytest.approx(-10.0)
    assert steps["governing-pair"].result.value == 1.0
    assert steps["ct-008-clear-spacing-result"].result.value == FAIL
    assert out["clear_spacing"]["governing"]["clear_mm"] == pytest.approx(-10.0)

    invalid = _input(clear_spacing_on=True)
    invalid["bar_elements"] = [
        _bar("R1", 0.0, 0.0, 20.0),
        {"id": "R2", "kind": "bar", "x_mm": 10.0, "y_mm": 0.0},
        {"id": "R3", "kind": "bar", "x_mm": math.nan, "y_mm": 0.0,
         "diameter_mm": 12.0},
    ]
    invalid_out = _candidate(invalid)
    assert invalid_out["clear_spacing"]["invalid_ids"] == ["R2", "R3"]
    steps = _steps(_bundle(invalid, invalid_out), "clear-spacing")
    assert steps["invalid-geometry-state"].result.value == 2.0
    assert steps["ct-008-clear-spacing-result"].result.value == INVALID
    assert "pair-000-001-clear" not in steps

    empty = _input(clear_spacing_on=True)
    empty["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0)]
    empty_out = _candidate(empty)
    assert empty_out["clear_spacing"]["reason"] == (
        "fewer than two included reinforcement elements")
    steps = _steps(_bundle(empty, empty_out), "clear-spacing")
    assert steps["no-pairs-state"].result.value == 1.0
    assert steps["ct-008-clear-spacing-result"].result.value == NA


def test_minimum_ratio_editions_ductility_and_sources_close_dk_base_2023():
    oracle = {
        detailing.EC2_2005_DKNA: (0.063, RATIO_SOURCE_DK),
        detailing.EC2_2005: (0.08, RATIO_SOURCE_BASE),
        detailing.EC2_2023: (0.08, RATIO_SOURCE_2023),
    }
    for edition, (coefficient, source) in oracle.items():
        inp = _input(transverse_detailing_on=True, detailing_edition=edition)
        steps = _steps(_bundle(inp), "transverse-links")
        assert steps["minimum-ratio-coefficient"].result.value == coefficient
        assert steps["minimum-ratio-coefficient"].source == source
        assert steps["minimum-ratio"].result.value == pytest.approx(
            coefficient * math.sqrt(35.0) / 500.0)
        assert steps["ductility-factor"].result.value == 1.0
        # No active action: retained NOT APPLICABLE is finite evidence.
        assert steps["ct-008-transverse-links-result"].result.value == NAP
        assert "governing-utilisation" not in steps

    for ductility, factor in (("A", 1.0), ("B", 0.90), ("C", 0.80)):
        reduced = _steps(_bundle(_input(
            transverse_detailing_on=True,
            detailing_edition=detailing.EC2_2023,
            transverse_ductility_class=ductility,
            transverse_apply_ductility_reduction=True,
        )), "transverse-links")
        assert reduced["ductility-factor"].result.value == factor
        assert reduced["minimum-ratio"].result.value == pytest.approx(
            0.08 * math.sqrt(35.0) / 500.0 * factor)
    # The favourable reduction never applies outside the 2023 edition.
    off_edition = _steps(_bundle(_input(
        transverse_detailing_on=True,
        transverse_ductility_class="C",
        transverse_apply_ductility_reduction=True,
    )), "transverse-links")
    assert off_edition["ductility-factor"].result.value == 1.0


def test_shear_rows_links_on_ratio_and_spacing_oracle_via_real_run():
    inp = _input(transverse_detailing_on=True, shear_on=True,
                 shear_links=True, shear_V=100.0)
    out = _candidate(inp)
    steps = _steps(_bundle(inp, out), "transverse-links")
    # 0.3 x 0.6 section, bar at y = -250: bw = 300, d = 550.
    provided = 2.0 * LEG_AREA / (150.0 * 300.0)
    minimum = 0.063 * math.sqrt(35.0) / 500.0
    assert steps["shear-vy-legs"].result.value == 2.0
    assert steps["shear-vy-detailing-depth"].result.value == pytest.approx(550.0)
    assert steps["check-00-provided"].result.value == pytest.approx(provided)
    assert steps["check-00-utilisation"].result.value == pytest.approx(
        minimum / provided)
    assert steps["check-01-limit"].result.value == pytest.approx(412.5)
    assert steps["check-01-utilisation"].result.value == pytest.approx(
        150.0 / 412.5)
    # Gross-web screen: 300 <= min(412.5, 600) proves the PASS.
    assert steps["check-02-provided"].result.value == pytest.approx(300.0)
    assert steps["check-02-status"].result.value == PASS
    rows = out["transverse_reinforcement"]["checks"]
    assert [row["kind"] for row in rows] == [
        "minimum_ratio", "longitudinal_spacing", "transverse_leg_spacing"]
    assert rows[2]["spacing_source"] == "gross-web upper-bound screen"
    utils = [minimum / provided, 150.0 / 412.5, 300.0 / 412.5]
    governing = max(range(3), key=lambda index: utils[index])
    assert steps["governing-check"].result.value == float(governing)
    assert steps["governing-utilisation"].result.value == pytest.approx(
        max(utils))
    assert steps["ct-008-transverse-links-result"].result.value == PASS


def _shear_direction(**changes):
    direction = {
        "component": "vy", "axis": "x", "bw": 600.0, "d": 305.0,
        "links": {"legs": 2.0}, "res": {"valid": True, "vrd_c": 200.0},
        "v_ed": 50.0, "model_2023": False,
    }
    direction.update(changes)
    return direction


def test_gross_web_screen_demotes_fail_and_user_spacing_fails_definitively():
    inp = _input(transverse_detailing_on=True, shear_on=True, shear_links=True)
    out = _candidate(inp, upstream={"shear": _shear_direction()})
    row = out["transverse_reinforcement"]["checks"][2]
    assert row["status"] == "NOT ASSESSED"
    assert row["utilisation"] is None
    assert row["measurement_axis"] == "x"
    assert row["reason"] == (
        "gross web breadth exceeds the spacing limit; enter the actual "
        "maximum centre-to-centre leg spacing for a definitive assessment")
    steps = _steps(_bundle(inp, out), "transverse-links")
    assert steps["check-02-provided"].result.value == pytest.approx(600.0)
    assert steps["check-02-limit"].result.value == pytest.approx(0.75 * 305.0)
    assert steps["check-02-status"].result.value == NA
    assert steps["check-02-status"].source == ADAPTER_SOURCE
    assert "check-02-utilisation" not in steps

    entered = _input(transverse_detailing_on=True, shear_on=True,
                     shear_links=True, shear_vy_transverse_leg_spacing=600.0)
    out = _candidate(entered, upstream={"shear": _shear_direction()})
    row = out["transverse_reinforcement"]["checks"][2]
    assert row["status"] == "FAIL" and row["spacing_source"] == "user"
    steps = _steps(_bundle(entered, out), "transverse-links")
    assert steps["check-02-utilisation"].result.value == pytest.approx(
        600.0 / (0.75 * 305.0))
    assert steps["ct-008-transverse-links-result"].result.value == FAIL


def test_no_links_branches_forced_required_unknown_and_2023_applicability():
    forced_inp = _input(transverse_detailing_on=True, shear_on=True,
                        shear_links=False, shear_V=50.0)
    forced_out = _candidate(forced_inp)
    forced = forced_out["transverse_reinforcement"]
    assert forced["status"] == "FAIL"
    assert forced["checks"][0]["clause"] == "9.2.2(2), (5)"
    assert forced["checks"][0]["requirement"] == (
        "minimum beam shear reinforcement")
    assert forced["governing_utilisation"] == math.inf
    steps = _steps(_bundle(forced_inp, forced_out), "transverse-links")
    assert steps["check-00-utilisation"].result.state == "positive_infinity"
    assert steps["governing-utilisation"].result.state == "positive_infinity"
    assert steps["ct-008-transverse-links-result"].result.value == FAIL

    slab = _input(transverse_detailing_on=True, shear_on=True,
                  shear_links=False,
                  detailing_member_type=detailing.MEMBER_SLAB)
    required = _candidate(slab, upstream={
        "shear": _shear_direction(v_ed=300.0, model_2023=True)})
    row = required["transverse_reinforcement"]["checks"][0]
    assert row["kind"] == "required_links" and row["status"] == "FAIL"
    assert row["clause"] == "8.2.2"
    steps = _steps(_bundle(slab, required), "transverse-links")
    assert steps["shear-vy-links-required"].result.value == 1.0
    assert steps["check-00-status"].source == REQUIRED_LINKS_RES_2023

    unknown = _candidate(slab, upstream={
        "shear": _shear_direction(res={"valid": False})})
    row = unknown["transverse_reinforcement"]["checks"][0]
    assert row["status"] == "NOT ASSESSED"
    assert row["reason"] == "shear resistance without links is invalid"
    steps = _steps(_bundle(slab, unknown), "transverse-links")
    assert steps["shear-vy-links-required"].result.value == 2.0
    assert steps["ct-008-transverse-links-result"].result.value == NA

    beam_2023 = _input(transverse_detailing_on=True, shear_on=True,
                       shear_links=False,
                       detailing_edition=detailing.EC2_2023)
    deep = _candidate(beam_2023, upstream={"shear": _shear_direction(d=550.0)})
    row = deep["transverse_reinforcement"]["checks"][0]
    assert row["kind"] == "minimum_link_applicability"
    assert row["clause"] == "8.2.1(2), 12.2(4)"
    assert row["d_mm"] == pytest.approx(550.0)
    assert "statically determinate" in row["reason"]
    assert _steps(_bundle(beam_2023, deep), "transverse-links")[
        "ct-008-transverse-links-result"].result.value == NA
    shallow = _candidate(beam_2023, upstream={
        "shear": _shear_direction(d=450.0)})
    assert shallow["transverse_reinforcement"]["status"] == "NOT APPLICABLE"
    assert shallow["transverse_reinforcement"]["checks"] == []
    assert _steps(_bundle(beam_2023, shallow), "transverse-links")[
        "ct-008-transverse-links-result"].result.value == NAP

    missing = _input(transverse_detailing_on=True, shear_on=True,
                     shear_links=True)
    missing_out = _candidate(missing, upstream={
        "shear": _shear_direction(bw=None)})
    rows = missing_out["transverse_reinforcement"]["checks"]
    assert [row["status"] for row in rows] == ["NOT ASSESSED"] * 3
    assert all(row["reason"] == "missing shear-link geometry" for row in rows)
    assert _steps(_bundle(missing, missing_out), "transverse-links")[
        "ct-008-transverse-links-result"].result.value == NA


def test_torsion_rows_close_uk8_versus_minimum_dimension_and_suppression():
    inp = _input(transverse_detailing_on=True, torsion_on=True, torsion_T=20.0)
    out = _candidate(inp)
    steps = _steps(_bundle(inp, out), "transverse-links")
    # 0.3 x 0.6 tube: tef = 100 mm, uk = 1400 mm, minimum dimension 300 mm.
    assert steps["upstream-torsion-tube-00-tef"].result.value == (
        pytest.approx(100.0))
    assert steps["upstream-torsion-tube-00-uk"].result.value == (
        pytest.approx(1400.0))
    assert steps["check-00-provided"].result.value == pytest.approx(
        LEG_AREA / (150.0 * 100.0))
    assert steps["check-01-limit"].result.value == pytest.approx(175.0)
    row = out["transverse_reinforcement"]["checks"][1]
    assert row["governing_limit"] == "u_k/8"
    assert row["spacing_limits_mm"]["u_k/8"] == pytest.approx(175.0)
    assert row["spacing_limits_mm"]["minimum section dimension"] == (
        pytest.approx(300.0))

    outer = templates.rectangle(2.0, 0.25)
    flat = _input(transverse_detailing_on=True, torsion_on=True,
                  torsion_T=20.0, outer=outer, bars=[],
                  section=Section.from_polygon(outer), bar_elements=[],
                  bar_materials=None)
    flat_out = _candidate(flat)
    tef = 0.5 / 4.5 * 1000.0
    uk = 2.0 * (2.0 + 0.25 - 2.0 * 0.5 / 4.5) * 1000.0
    flat_steps = _steps(_bundle(flat, flat_out), "transverse-links")
    assert flat_steps["check-01-limit"].result.value == pytest.approx(250.0)
    assert flat_steps["upstream-torsion-tube-00-tef"].result.value == (
        pytest.approx(tef))
    row = flat_out["transverse_reinforcement"]["checks"][1]
    assert row["governing_limit"] == "minimum section dimension"
    assert row["spacing_limits_mm"]["u_k/8"] == pytest.approx(uk / 8.0)

    slab = dict(inp, detailing_member_type=detailing.MEMBER_SLAB)
    slab_out = _candidate(slab)
    rows = slab_out["transverse_reinforcement"]["checks"]
    assert all(row["status"] == "NOT ASSESSED" for row in rows)
    assert all("beam torsion" in row["reason"] for row in rows)
    assert _steps(_bundle(slab, slab_out), "transverse-links")[
        "ct-008-transverse-links-result"].result.value == NA

    invalid_tube = _candidate(inp, upstream={"torsion": {
        "valid": False, "reason": None, "subdivided": False,
        "min_reinf": {"applicable": False, "reason": "no shear check"},
        "tube": {"valid": False, "reason": "compound outline needs sub-tubes",
                 "tef": 0.0, "uk": 0.0, "minimum_dimension_mm": 0.0},
    }})
    rows = invalid_tube["transverse_reinforcement"]["checks"]
    assert [row["status"] for row in rows] == ["NOT ASSESSED"] * 2
    assert all(row["reason"] == "compound outline needs sub-tubes"
               for row in rows)
    assert _bundle(inp, invalid_tube) is not None


def test_subdivided_torsion_keeps_tube_order_and_cardinality():
    outer = templates.t_section(1.0, 0.2, 0.3, 0.6)
    inp = _input(transverse_detailing_on=True, torsion_on=True,
                 torsion_T=40.0, torsion_subdivide=True,
                 torsion_subrects=[(0.0, -100.0, 300.0, 600.0),
                                   (0.0, 300.0, 1000.0, 200.0)],
                 outer=outer, bars=[], section=Section.from_polygon(outer),
                 bar_elements=[], bar_materials=None)
    out = _candidate(inp)
    rows = out["transverse_reinforcement"]["checks"]
    assert [row["scope"] for row in rows] == [
        "Torsion Tube 1", "Torsion Tube 1", "Torsion Tube 2", "Torsion Tube 2"]
    steps = _steps(_bundle(inp, out), "transverse-links")
    assert steps["upstream-torsion-tube-00-uk"].result.value == (
        pytest.approx(1400.0))
    tef2 = 0.2 / 2.4 * 1000.0
    uk2 = 2.0 * (1.0 + 0.2 - 2.0 * 0.2 / 2.4) * 1000.0
    assert steps["upstream-torsion-tube-01-tef"].result.value == (
        pytest.approx(tef2))
    assert steps["check-03-limit"].result.value == pytest.approx(
        min(uk2 / 8.0, 200.0))
    assert rows[3]["governing_limit"] == "minimum section dimension"


def _walk(value, path=()):
    if isinstance(value, Mapping):
        keys = tuple(value)
        yield "mapping", path, keys
        for key in keys:
            yield from _walk(value[key], (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, (*path, index))
    else:
        yield "leaf", path, value


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _replaced(value, path, replacement):
    if not path:
        return replacement
    key, *tail = path
    clone = dict(value) if isinstance(value, Mapping) else list(value)
    clone[key] = _replaced(clone[key], tail, replacement)
    return clone


def _mutated(value):
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if isinstance(value, float):
        return 1.0 if math.isinf(value) else value + 0.271828
    if isinstance(value, str):
        return value + "-tampered"
    return 0.0


def _refreshed_screen(upstream):
    """Independent replica of the retained 6.31 screen for crafted upstream."""
    torsion = upstream["torsion"]
    shear = upstream.get("shear")
    if torsion.get("subdivided"):
        return {"applicable": False, "reason": "subdivided (compound) section"}
    resistance = (shear or {}).get("res") or {}
    if not shear or not resistance.get("valid"):
        return {"applicable": False, "reason": "no shear check"}
    trd_c = torsion["primary"]["trd_c"]
    vrd_c = resistance["vrd_c"]
    if trd_c <= 0.0 or vrd_c <= 0.0:
        return {"applicable": False, "reason": "zero resistance"}
    value = torsion["t_ed"] / trd_c + shear["v_ed"] / vrd_c
    return {"applicable": True, "value": value,
            "ok": bool(value <= 1.0 + 1e-9), "t_ed": torsion["t_ed"],
            "trd_c": trd_c, "v_ed": shear["v_ed"], "vrd_c": vrd_c,
            "solid": True, "model_2023": bool(shear.get("model_2023"))}


def _with_screen(upstream):
    refreshed = copy.deepcopy(upstream)
    refreshed["torsion"] = dict(refreshed["torsion"],
                                min_reinf=_refreshed_screen(refreshed))
    return refreshed


def _rich_inputs():
    inp = _input(clear_spacing_on=True, transverse_detailing_on=True,
                 shear_on=True, shear_links=True, torsion_on=True,
                 shear_vy_transverse_leg_spacing=600.0)
    inp["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                           _bar("R2", 45.0, 0.0, 20.0),
                           _bar("R3", 90.0, 40.0, 25.0)]
    inp["tendon_elements"] = [_bar("P1", 200.0, 0.0, 60.0, kind="tendon")]
    upstream = _with_screen({
        "shear": _shear_direction(v_ed=300.0),
        "torsion": {"valid": True, "subdivided": False, "t_ed": 20.0,
                    "primary": {"trd_c": 50.0}, "tube": {
                        "valid": True, "reason": None, "tef": 100.0,
                        "uk": 1.4, "minimum_dimension_mm": 300.0}},
    })
    return inp, _candidate(inp, upstream=upstream)


def test_every_retained_output_member_is_exact_and_siblings_stay_inert():
    inp, out = _rich_inputs()
    clear_expected = _replay_clear(inp, CONTEXT)[1].expected
    transverse_expected = _replay_transverse(inp, out, CONTEXT)[1].expected
    for candidate_key, expected, validator in (
        ("clear_spacing", clear_expected, _validate_clear_candidate),
        ("transverse_reinforcement", transverse_expected,
         _validate_transverse_candidate),
    ):
        candidate = out[candidate_key]
        validator(copy.deepcopy(candidate), expected)
        for kind, path, detail in list(_walk(candidate)):
            if kind == "leaf":
                with pytest.raises(TraceValidationError):
                    validator(_replaced(copy.deepcopy(candidate), path,
                                        _mutated(detail)), expected)
                continue
            changed = copy.deepcopy(candidate)
            _at(changed, path)["unexpected-ct008-field"] = 0.0
            with pytest.raises(TraceValidationError):
                validator(changed, expected)
            for key in detail:
                changed = copy.deepcopy(candidate)
                del _at(changed, path)[key]
                with pytest.raises(TraceValidationError):
                    validator(changed, expected)
            if len(detail) > 1:
                changed = copy.deepcopy(candidate)
                node = _at(changed, path)
                items = [(key, node[key]) for key in reversed(detail)]
                node.clear()
                node.update(items)
                with pytest.raises(TraceValidationError):
                    validator(changed, expected)
    for list_key, expected, validator in (
        ("clear_spacing", clear_expected, _validate_clear_candidate),
        ("transverse_reinforcement", transverse_expected,
         _validate_transverse_candidate),
    ):
        rows_key = "pairs" if list_key == "clear_spacing" else "checks"
        for operation in ("duplicate", "pop", "reverse"):
            changed = copy.deepcopy(out[list_key])
            if operation == "duplicate":
                changed[rows_key].append(copy.deepcopy(changed[rows_key][0]))
            elif operation == "pop":
                changed[rows_key].pop()
            else:
                changed[rows_key].reverse()
            with pytest.raises(TraceValidationError):
                validator(changed, expected)

    baseline = _bundle(inp, out).to_dict()
    # C.3b registry-composition edit: minimum_reinforcement and the torsion
    # min_reinf screen are now CT-008 members, no longer inert siblings.
    inert = dict(out)
    inert["directional_interactions"] = object()
    inert["report_rows"] = object()
    inert["shear"] = dict(out["shear"], min_reinf=math.nan,
                          directional_min_reinf_status=math.nan,
                          report_rows=object())
    inert["torsion"] = dict(out["torsion"], interaction=math.nan,
                            directional_interactions=object())
    assert _bundle(inp, inert).to_dict() == baseline


def test_applicability_separation_absent_flags_and_masking():
    neither = _input()
    assert detailing_trace_applicability(neither) == ()
    assert build_detailing_trace_family(
        neither, {}, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA) is None

    clear_only = _input(clear_spacing_on=True)
    clear_only["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                                  _bar("R2", 45.0, 0.0, 20.0)]
    clear_bundle = _bundle(clear_only)
    assert [c.calculation_id.rsplit("-", 2)[-2:] for c in
            clear_bundle.calculations] == [["clear", "spacing"]]

    transverse_only = _input(transverse_detailing_on=True)
    transverse_bundle = _bundle(transverse_only)
    assert len(transverse_bundle.calculations) == 1
    assert transverse_bundle.calculations[0].calculation_id.endswith(
        "transverse-links")

    both = _input(clear_spacing_on=True, transverse_detailing_on=True)
    both["bar_elements"] = clear_only["bar_elements"]
    assert len(_bundle(both).calculations) == 2

    # A candidate supplied for an absent flag fails closed.
    with pytest.raises(TraceValidationError, match="absent CT-008"):
        build_detailing_trace_family(
            _input(), {"clear_spacing": {"status": "PASS"}},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA)
    with pytest.raises(TraceValidationError, match="absent CT-008"):
        build_detailing_trace_family(
            _input(clear_spacing_on=True, section=None),
            {"clear_spacing": {"status": "PASS"}},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA)
    assert build_detailing_trace_family(
        _input(clear_spacing_on=True, transverse_detailing_on=True,
               section=None), {},
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA) is None
    with pytest.raises(TraceValidationError, match="not-applicable"):
        validate_detailing_trace_family(
            clear_bundle, _input(), {}, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_detailing_trace_family(
        None, _input(), {}, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA) is None

    # Unrelated invalid CT-002..CT-007, bridge, and SLS data cannot mask.
    masked = dict(both, Mx_pl=math.nan, My_pl=math.inf, shear_V=math.nan,
                  shear_dlower=math.nan, v_min=math.nan, torsion_T=math.nan,
                  sls_fctm=math.nan, bridge_standard=object(),
                  bar_materials=[object()])
    clean_out = _candidate(both)
    assert build_detailing_trace_family(
        masked, clean_out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT).to_dict() == _bundle(both, clean_out).to_dict()

    with pytest.raises(TraceValidationError):
        _bundle(_input(clear_spacing_on="yes"))
    with pytest.raises(TraceValidationError):
        _bundle(_input(transverse_detailing_on=True, shear_fywk=math.nan))


def test_all_editions_finite_unknown_edition_and_2023_concrete_boundary():
    for edition in detailing.EDITIONS:
        inp = _input(clear_spacing_on=True, transverse_detailing_on=True,
                     detailing_edition=edition)
        inp["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                               _bar("R2", 45.0, 0.0, 20.0)]
        bundle = _bundle(inp)
        for calculation in bundle.calculations:
            assert calculation.steps[-1].result.state == "finite"
    unknown = _input(clear_spacing_on=True,
                     detailing_edition="EN 1992-1-1:1991")
    with pytest.raises(TraceValidationError, match="unknown detailing edition"):
        _bundle(unknown, {"clear_spacing": None})

    concrete_2023 = _input(
        transverse_detailing_on=True,
        concrete=codes.EC2_2023.concrete(35.0),
        concrete_preset=codes.EC2_2023.label,
    )
    with pytest.raises(TraceValidationError, match="2023 material provenance"):
        _bundle(concrete_2023, {"transverse_reinforcement": {}})
    # Clear spacing binds no materials at all: 2023 concrete stays inert.
    clear_2023 = _input(
        clear_spacing_on=True,
        concrete=codes.EC2_2023.concrete(35.0),
        concrete_preset=codes.EC2_2023.label,
    )
    clear_2023["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                                  _bar("R2", 45.0, 0.0, 20.0)]
    assert _bundle(clear_2023).calculations[0].steps[-1].result.state == (
        "finite")


def test_failing_statuses_publish_genuine_fail_and_precedence_oracle():
    # FAIL from a definitive utilisation > 1 row wins over NOT ASSESSED rows.
    inp = _input(transverse_detailing_on=True, shear_on=True,
                 shear_links=True, shear_vy_transverse_leg_spacing=600.0)
    upstream = {"shear": {"directions": {
        "vx": _shear_direction(component="vx", bw=None),
        "vy": _shear_direction(),
    }}}
    out = _candidate(inp, upstream=upstream)
    rows = out["transverse_reinforcement"]["checks"]
    statuses = [row["status"] for row in rows]
    assert "FAIL" in statuses and "NOT ASSESSED" in statuses
    assert out["transverse_reinforcement"]["status"] == "FAIL"
    steps = _steps(_bundle(inp, out), "transverse-links")
    assert steps["ct-008-transverse-links-result"].result.value == FAIL
    fail_util = 600.0 / (0.75 * 305.0)
    assert fail_util > 1.0
    assert steps["governing-utilisation"].result.value == pytest.approx(
        fail_util)

    # INVALID input evidence wins over everything and binds no kernel numerics.
    invalid = _input(transverse_detailing_on=True, shear_link_s=0.0)
    invalid_out = _candidate(invalid)
    assert invalid_out["transverse_reinforcement"]["status"] == "INVALID"
    assert invalid_out["transverse_reinforcement"]["reason"] == (
        "invalid spacing")
    steps = _steps(_bundle(invalid, invalid_out), "transverse-links")
    assert steps["ct-008-transverse-links-result"].result.value == INVALID
    assert "minimum-ratio" not in steps and "governing-utilisation" not in steps

    # Retained precedence order INVALID > FAIL > NOT ASSESSED > PASS.
    order = [detailing._status(statuses) for statuses in (
        ["INVALID", "FAIL", "PASS"], ["FAIL", "NOT ASSESSED", "PASS"],
        ["NOT ASSESSED", "PASS"], ["PASS", "PASS"])]
    assert order == ["INVALID", "FAIL", "NOT ASSESSED", "PASS"]


def test_graph_reachability_edges_sources_units_axes_and_stale_seals():
    inp, out = _rich_inputs()
    bundle = _bundle(inp, out)
    clear_shape = _replay_clear(inp, CONTEXT)[0]
    transverse_shape = _replay_transverse(inp, out, CONTEXT)[0]
    screen_shape = _replay_screen(inp, out, CONTEXT)[0]
    registry = expected_registry(DetailingShape(
        clear_shape, transverse_shape, None, screen_shape))
    for calculation in bundle.calculations:
        by_id = {step.step_id: step for step in calculation.steps}
        reached, pending = set(), [calculation.final_step_id]
        while pending:
            step_id = pending.pop()
            reached.add(step_id)
            pending.extend(dep.step_id for dep in by_id[step_id].dependencies
                           if dep.step_id not in reached)
        assert reached == set(by_id)

    for ci, calculation in enumerate(bundle.calculations):
        for si, step in enumerate(calculation.steps):
            for di in range(len(step.dependencies)):
                steps = list(calculation.steps)
                steps[si] = dataclasses.replace(
                    step, dependencies=step.dependencies[:di]
                    + step.dependencies[di + 1:])
                calculations = list(bundle.calculations)
                calculations[ci] = dataclasses.replace(
                    calculation, steps=tuple(steps))
                with pytest.raises(TraceValidationError):
                    tampered = seal_bundle(dataclasses.replace(
                        bundle, calculations=tuple(calculations)))
                    audit_trace_registry(tampered, registry)

    def _retarget(calculation_index, **changes):
        calculations = list(bundle.calculations)
        calculations[calculation_index] = dataclasses.replace(
            calculations[calculation_index], **changes)
        return seal_bundle(dataclasses.replace(
            bundle, calculations=tuple(calculations)))

    transverse = bundle.calculations[1]
    steps = list(transverse.steps)
    index = next(i for i, s in enumerate(steps)
                 if s.step_id == "minimum-ratio-coefficient")
    steps[index] = dataclasses.replace(steps[index], source=RATIO_SOURCE_BASE)
    source_tamper = _retarget(1, steps=tuple(steps))

    target, wrong = "minimum-ratio", TraceUnit("kN", "force")
    unit_steps = tuple(dataclasses.replace(
        step, unit=wrong if step.step_id == target else step.unit,
        dependencies=tuple(TraceDependency(
            dep.step_id, wrong if dep.step_id == target else dep.unit)
            for dep in step.dependencies)
    ) for step in transverse.steps)
    unit_tamper = _retarget(1, steps=unit_steps)

    value_steps = list(transverse.steps)
    value_steps[-1] = dataclasses.replace(
        value_steps[-1],
        result=dataclasses.replace(value_steps[-1].result, value=PASS))
    content_tamper = _retarget(1, steps=tuple(value_steps))

    identity_tamper = _retarget(0, method_id="wrong-method")
    axes_tamper = _retarget(1, axes=tuple(
        dataclasses.replace(axis, value=detailing.EC2_2005)
        if axis.name == "detailing_edition" else axis
        for axis in transverse.axes))
    swapped = list(bundle.calculations[0].steps)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    reorder_tamper = _retarget(0, steps=tuple(swapped))

    for candidate in (source_tamper, unit_tamper, content_tamper,
                      identity_tamper, axes_tamper, reorder_tamper,
                      dataclasses.replace(bundle, input_sha256="c" * 64),
                      dataclasses.replace(bundle, result_sha256="c" * 64),
                      dataclasses.replace(bundle,
                                          calculations=bundle.calculations * 2)):
        with pytest.raises(TraceValidationError):
            validate_detailing_trace_family(
                candidate, inp, out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_detailing_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def _with(upstream, path, value):
    clone = copy.deepcopy(upstream)
    node = clone
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return clone


def test_upstream_evidence_leaves_bind_exactly_and_mutations_are_rejected():
    inp = _input(transverse_detailing_on=True, shear_on=True,
                 shear_links=False, torsion_on=True)
    upstream = _with_screen({
        "shear": _shear_direction(),
        "torsion": {"valid": True, "subdivided": False, "t_ed": 15.0,
                    "primary": {"trd_c": 60.0}, "tube": {
                        "valid": True, "reason": None, "tef": 100.0,
                        "uk": 1.4, "minimum_dimension_mm": 300.0}},
    })
    out = _candidate(inp, upstream=upstream)
    bundle = _bundle(inp, out)
    steps = _steps(bundle, "transverse-links")
    # (a) Every bound upstream leaf carries the exact retained payload value.
    assert steps["upstream-shear-vy-bw"].result.value == 600.0
    assert steps["upstream-shear-vy-vrd-c"].result.value == 200.0
    assert steps["upstream-shear-vy-v-ed"].result.value == 50.0
    assert steps["upstream-shear-vy-model-2023"].result.value == 0.0
    assert steps["upstream-shear-vy-resistance-valid"].result.value == 1.0
    assert steps["shear-vy-links-required"].result.value == 0.0
    assert steps["upstream-torsion-tube-00-valid"].result.value == 1.0
    assert steps["upstream-torsion-tube-00-minimum-dimension"].result.value == (
        300.0)
    baseline = bundle.to_dict()
    # (b) Mutating any consumed upstream value invalidates the sealed bundle
    # and produces a visibly different trace on rebuild.
    mutations = (
        ("shear", "v_ed"), ("shear", "bw"), ("shear", "res", "vrd_c"),
        ("shear", "model_2023"), ("shear", "res", "valid"),
        ("torsion", "tube", "valid"),
        ("torsion", "tube", "minimum_dimension_mm"),
    )
    replacements = {
        ("shear", "v_ed"): 150.0, ("shear", "bw"): 500.0,
        ("shear", "res", "vrd_c"): 100.0, ("shear", "model_2023"): True,
        ("shear", "res", "valid"): False,
        ("torsion", "tube", "valid"): False,
        ("torsion", "tube", "minimum_dimension_mm"): 250.0,
    }
    for path in mutations:
        mutated_out = _candidate(inp, upstream=_with_screen(_with(
            upstream, path, replacements[path])))
        with pytest.raises(TraceValidationError):
            validate_detailing_trace_family(
                bundle, inp, mutated_out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)
        rebuilt = _bundle(inp, mutated_out)
        assert rebuilt.to_dict() != baseline


def test_status_encoding_is_pinned_literally_and_reached_end_to_end():
    # REVIEW is retained precedence but unreachable in this slice's row
    # builders, so the literal mapping pin below is its only control.
    assert STATUS_CODES == {
        "PASS": 1.0, "FAIL": 0.0, "REVIEW": 2.0, "NOT ASSESSED": 3.0,
        "NOT APPLICABLE": 4.0, "INVALID": 5.0,
    }
    passing = _input(clear_spacing_on=True)
    passing["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                               _bar("R2", 60.0, 0.0, 20.0)]
    assert _steps(_bundle(passing), "clear-spacing")[
        "ct-008-clear-spacing-result"].result.value == 1.0

    failing = _input(transverse_detailing_on=True, shear_on=True,
                     shear_links=True, shear_vy_transverse_leg_spacing=600.0)
    failing_out = _candidate(failing, upstream={"shear": _shear_direction()})
    steps = _steps(_bundle(failing, failing_out), "transverse-links")
    assert steps["check-02-status"].result.value == 0.0
    assert steps["ct-008-transverse-links-result"].result.value == 0.0

    demoted = _input(transverse_detailing_on=True, shear_on=True,
                     shear_links=True)
    demoted_out = _candidate(demoted, upstream={"shear": _shear_direction()})
    steps = _steps(_bundle(demoted, demoted_out), "transverse-links")
    assert steps["check-02-status"].result.value == 3.0
    assert steps["ct-008-transverse-links-result"].result.value == 3.0

    idle = _input(transverse_detailing_on=True)
    assert _steps(_bundle(idle), "transverse-links")[
        "ct-008-transverse-links-result"].result.value == 4.0

    invalid = _input(transverse_detailing_on=True, shear_link_s=0.0)
    assert _steps(_bundle(invalid), "transverse-links")[
        "ct-008-transverse-links-result"].result.value == 5.0


def test_retained_run_analysis_composition_builds_and_validates():
    # The case-table aggregate path (plastic_cases/elastic_cases) re-enters the
    # same _run_single_analysis gate per case and is covered by the app suite;
    # here the retained single-analysis run_analysis composition is used.
    # C.3b registry-composition edit: torsion_on now also publishes the 6.31
    # screen member, and minimum_reinforcement_on the longitudinal member.
    inp = _input(clear_spacing_on=True, transverse_detailing_on=True,
                 torsion_on=True, torsion_T=20.0, mode="Capacity only",
                 minimum_reinforcement_on=True, sls_fctm=2.9)
    inp["bar_elements"] = [dict(_bar("R1", -100.0, -250.0, 25.0),
                                material_id="M1")]
    out = run_analysis(inp)
    assert "clear_spacing" in out and "transverse_reinforcement" in out
    assert "minimum_reinforcement" in out
    assert out["torsion"]["min_reinf"]["applicable"] is False
    bundle = build_detailing_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)
    assert bundle is not None and len(bundle.calculations) == 4
    for calculation in bundle.calculations:
        assert calculation.steps[-1].result.state == "finite"
    assert validate_detailing_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def test_2023_beam_depth_unavailable_publishes_exact_retained_row():
    inp = _input(transverse_detailing_on=True, shear_on=True,
                 shear_links=False, detailing_edition=detailing.EC2_2023)
    out = _candidate(inp, upstream={"shear": _shear_direction(d=None)})
    row = out["transverse_reinforcement"]["checks"][0]
    assert row["kind"] == "minimum_link_applicability"
    assert row["status"] == "NOT ASSESSED"
    assert "d_mm" not in row
    assert row["reason"] == ("effective depth is unavailable for the 2023 "
                             "minimum-link applicability check")
    bundle = _bundle(inp, out)
    steps = _steps(bundle, "transverse-links")
    assert steps["shear-vy-detailing-depth"].result.value == 0.0
    assert steps["check-00-status"].result.value == 3.0
    assert steps["ct-008-transverse-links-result"].result.value == 3.0
    assert validate_detailing_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def test_reordered_bar_records_invalidate_a_sealed_clear_bundle():
    inp = _input(clear_spacing_on=True)
    inp["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                           _bar("R2", 45.0, 0.0, 20.0),
                           _bar("R3", 120.0, 60.0, 25.0)]
    bundle = _bundle(inp)
    permuted = dict(inp, bar_elements=[inp["bar_elements"][index]
                                       for index in (2, 0, 1)])
    permuted_out = _candidate(permuted)
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, permuted, permuted_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_detailing_trace_family(
        _bundle(permuted, permuted_out), permuted, permuted_out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def test_direct_invalid_inputs_publish_and_upstream_junk_stays_inert():
    # The retained kernel selects INVALID from the direct inputs before any
    # direction/tube geometry is read; junk upstream payloads must be inert.
    junk = {
        "shear": _shear_direction(bw=math.nan, d=math.nan, v_ed=math.inf,
                                  res={"valid": True, "vrd_c": math.nan},
                                  links={"legs": math.nan}),
        "torsion": {"valid": True, "tube": {
            "valid": True, "reason": None, "tef": math.nan, "uk": math.nan,
            "minimum_dimension_mm": math.nan}},
    }
    # C.3b registry-composition edit: torsion stays off here so the junk
    # torsion payload remains pure unread upstream data for this member.
    inp = _input(transverse_detailing_on=True, shear_on=True,
                 shear_links=True, torsion_on=False, shear_link_s=0.0)
    out = _candidate(inp, upstream=junk)
    assert out["transverse_reinforcement"]["status"] == "INVALID"
    bundle = _bundle(inp, out)
    steps = _steps(bundle, "transverse-links")
    assert steps["ct-008-transverse-links-result"].result.value == 5.0
    assert not any(step_id.startswith("upstream-") for step_id in steps)
    assert "input-vy-fallback-legs" not in steps
    assert validate_detailing_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None
    baseline = bundle.to_dict()
    mutated = _with(junk, ("shear", "bw"), math.inf)
    mutated = _with(mutated, ("torsion", "tube", "uk"), -1.0e300)
    mutated_out = _candidate(inp, upstream=mutated)
    assert _bundle(inp, mutated_out).to_dict() == baseline
    assert validate_detailing_trace_family(
        bundle, inp, mutated_out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None


def test_changed_record_id_or_kind_invalidates_a_sealed_clear_bundle():
    bars = [_bar("R1", 0.0, 0.0, 20.0), _bar("R2", 60.0, 0.0, 20.0)]
    tendons = [_bar("P1", 200.0, 0.0, 30.0, kind="tendon")]
    inp = _input(clear_spacing_on=True, detailing_include_tendons=True)
    inp["bar_elements"] = bars
    inp["tendon_elements"] = tendons
    bundle = _bundle(inp)

    # Changing only one record ID (identical geometry) must change the seal.
    renamed = dict(inp, bar_elements=[dict(bars[0], id="RX"), bars[1]])
    renamed_out = _candidate(renamed)
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, renamed, renamed_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_detailing_trace_family(
        _bundle(renamed, renamed_out), renamed, renamed_out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None

    # Changing only one kind string (same geometry, same inclusion) likewise.
    rekinded = dict(inp, tendon_elements=[dict(tendons[0], kind="duct")])
    rekinded_out = _candidate(rekinded)
    assert rekinded_out["clear_spacing"]["governing"] is not None
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, rekinded, rekinded_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_detailing_trace_family(
        _bundle(rekinded, rekinded_out), rekinded, rekinded_out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def test_changed_tube_reason_invalidates_a_sealed_stale_bundle():
    inp = _input(transverse_detailing_on=True, torsion_on=True, torsion_T=20.0)
    upstream = {"torsion": {
        "valid": False, "reason": None, "subdivided": False,
        "min_reinf": {"applicable": False, "reason": "no shear check"},
        "tube": {"valid": False, "reason": "compound outline needs sub-tubes",
                 "tef": 0.0, "uk": 0.0, "minimum_dimension_mm": 0.0}}}
    out = _candidate(inp, upstream=upstream)
    bundle = _bundle(inp, out)
    steps = _steps(bundle, "transverse-links")
    assert any(step_id.startswith("upstream-torsion-tube-00-reason-")
               for step_id in steps)
    changed = _with(upstream, ("torsion", "tube", "reason"),
                    "user-declared invalid tube")
    changed_out = _candidate(inp, upstream=changed)
    assert changed_out["transverse_reinforcement"]["checks"][0]["reason"] == (
        "user-declared invalid tube")
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, inp, changed_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    rebuilt = _bundle(inp, changed_out)
    assert rebuilt.to_dict() != bundle.to_dict()
    assert validate_detailing_trace_family(
        rebuilt, inp, changed_out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None


def test_changed_concrete_material_id_same_law_invalidates_sealed_bundle():
    # Two byte-identical concrete laws under different retained material IDs
    # must seal differently (CT-007 material_prefix idiom).
    first = _input(transverse_detailing_on=True, concrete_material_id="C1")
    out = _candidate(first)
    bundle = _bundle(first, out)
    steps = _steps(bundle, "transverse-links")
    assert concrete_leaf_id("C1", "fck") in steps
    second = dict(first, concrete_material_id="C2")
    second_out = _candidate(second)
    assert second_out["transverse_reinforcement"] == (
        out["transverse_reinforcement"])
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, second, second_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    rebuilt = _bundle(second, second_out)
    assert concrete_leaf_id("C2", "fck") in _steps(rebuilt, "transverse-links")
    assert rebuilt.to_dict() != bundle.to_dict()
    assert validate_detailing_trace_family(
        rebuilt, second, second_out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None


# ---------------------------------------------------------------------------
# PR-08C.3b: longitudinal minimum reinforcement and the 6.31 screen members.
# ---------------------------------------------------------------------------

def _long_input(*, fyks=(500.0, 500.0, 500.0, 500.0), **changes):
    method = codes.EC2_2005_DKNA
    outer = [(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)]
    bars = [(-0.12, -0.25, 491.0), (0.12, -0.25, 491.0),
            (-0.12, 0.25, 491.0), (0.12, 0.25, 491.0)]
    entries, materials, elements = [], [], []
    for index, ((x, y, _area), fyk) in enumerate(zip(bars, fyks), start=1):
        entry = material_catalog.default_entry(
            "mild", material_id=f"L{index}", preset=method.label)
        entry["fytk"] = fyk
        entries.append(entry)
        materials.append(material_catalog.build_material(entry, "mild"))
        elements.append(dict(_bar(f"R{index}", x * 1000.0, y * 1000.0, 25.0),
                             material_id=f"L{index}"))
    inp = _input(
        minimum_reinforcement_on=True, sls_fctm=2.9, outer=outer, bars=bars,
        section=Section.from_polygon(outer, bars), bar_elements=elements,
        bar_materials=materials,
        mild_material_catalog={"version": 1, "next_id": 9, "items": entries},
    )
    inp.update(changes)
    return inp


def test_longitudinal_2005_as_min_oracle_signs_and_two_material_fyk():
    # Both governing terms of as_min = max(0.26 fctm/fyk, 0.0013) bt d.
    for fctm, fyk, factor in ((2.9, 500.0, 0.26 * 2.9 / 500.0),
                              (2.0, 500.0, 0.0013)):
        inp = _long_input(fyks=(fyk,) * 4, sls_fctm=fctm, Mx_pl=100.0)
        out = _candidate(inp)
        steps = _steps(_bundle(inp, out), "longitudinal-minimum")
        as_min = factor * 300.0 * 550.0
        assert steps["row-as-min-mm2"].result.value == pytest.approx(as_min)
        assert steps["row-bt-mm"].result.value == pytest.approx(300.0)
        assert steps["row-d-mm"].result.value == pytest.approx(550.0)
        assert steps["row-utilisation"].result.value == pytest.approx(
            as_min / 982.0)
        assert steps["row-status"].result.value == (
            1.0 if as_min <= 982.0 + 1e-9 else 0.0)
        row = out["minimum_reinforcement"]["checks"][0]
        assert row["face"] == "bottom" and row["bar_ids"] == ["R1", "R2"]
        assert row["material_ids"] == ["L1", "L2"]

    # Tension-face fyk is the retained minimum fytk over tension-face bars.
    mixed = _long_input(fyks=(400.0, 500.0, 500.0, 500.0), Mx_pl=100.0)
    steps = _steps(_bundle(mixed), "longitudinal-minimum")
    assert steps["row-fyk-mpa"].result.value == 400.0
    assert steps["row-as-min-mm2"].result.value == pytest.approx(
        (0.26 * 2.9 / 400.0) * 300.0 * 550.0)

    # Moment sign flips the retained face; the trace binds the centroid moment.
    top = _long_input(Mx_pl=-100.0)
    top_out = _candidate(top)
    assert top_out["minimum_reinforcement"]["checks"][0]["face"] == "top"
    assert top_out["minimum_reinforcement"]["checks"][0]["bar_ids"] == (
        ["R3", "R4"])
    assert _steps(_bundle(top, top_out), "longitudinal-minimum")[
        "mx-centroid"].result.value == pytest.approx(-100.0)

    # Tension-positive N moves the centroidal moment: M_C = M_O + N c.
    outer = [(-0.10, 0.0), (0.10, 0.0), (0.10, 0.60), (-0.10, 0.60)]
    bars = [(0.0, 0.05, 100.0), (0.0, 0.55, 500.0)]
    entry = material_catalog.default_entry(
        "mild", material_id="L1", preset=codes.EC2_2005_DKNA.label)
    material = material_catalog.build_material(entry, "mild")
    axial = _input(
        minimum_reinforcement_on=True, sls_fctm=2.9, P_pl=100.0,
        outer=outer, bars=bars, section=Section.from_polygon(outer, bars),
        bar_elements=[dict(_bar(f"R{i}", x * 1000.0, y * 1000.0, 16.0),
                           material_id="L1")
                      for i, (x, y, _a) in enumerate(bars, start=1)],
        bar_materials=[material, material],
        mild_material_catalog={"version": 1, "next_id": 2, "items": [entry]},
    )
    axial_out = _candidate(axial)
    steps = _steps(_bundle(axial, axial_out), "longitudinal-minimum")
    assert steps["mx-centroid"].result.value == pytest.approx(30.0)
    assert axial_out["minimum_reinforcement"]["checks"][0]["status"] == "FAIL"
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 0.0

    # Zero centroidal moment is the retained 2005 NOT ASSESSED scope-out.
    zero = _long_input()
    zero_out = _candidate(zero)
    assert "needs a bending tension face" in (
        zero_out["minimum_reinforcement"]["reason"])
    steps = _steps(_bundle(zero, zero_out), "longitudinal-minimum")
    assert "assessment-scope-state" in steps
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 3.0


def test_longitudinal_identity_swaps_and_2023_material_boundary():
    inp = _long_input(Mx_pl=100.0)
    bundle = _bundle(inp)

    # Same-law different bar material ID must seal differently.
    swapped = copy.deepcopy(inp)
    clone = dict(swapped["mild_material_catalog"]["items"][0], id="L9")
    swapped["mild_material_catalog"]["items"].append(clone)
    swapped["bar_elements"][0] = dict(swapped["bar_elements"][0],
                                      material_id="L9")
    swapped_out = _candidate(swapped)
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, swapped, swapped_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_detailing_trace_family(
        _bundle(swapped, swapped_out), swapped, swapped_out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None

    # Renaming a compression-face element changes no retained row value,
    # but the tokenized element identity still changes the seal.
    renamed = copy.deepcopy(inp)
    renamed["bar_elements"][2] = dict(renamed["bar_elements"][2], id="RX")
    renamed_out = _candidate(renamed)
    assert renamed_out["minimum_reinforcement"]["checks"][0]["bar_ids"] == (
        ["R1", "R2"])
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, renamed, renamed_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)

    # A used 2023 bar-material assignment can never produce finite evidence.
    entry_2023 = material_catalog.default_entry(
        "mild", material_id="L1", preset=codes.EC2_2023.label)
    future = copy.deepcopy(inp)
    future["mild_material_catalog"]["items"][0] = entry_2023
    future["bar_materials"] = [
        material_catalog.build_material(entry_2023, "mild"),
        *future["bar_materials"][1:],
    ]
    with pytest.raises(TraceValidationError, match="2023 material provenance"):
        _bundle(future, {"minimum_reinforcement": {}})
    concrete_2023 = _long_input(
        Mx_pl=100.0, concrete=codes.EC2_2023.concrete(35.0),
        concrete_preset=codes.EC2_2023.label)
    with pytest.raises(TraceValidationError, match="2023 material provenance"):
        _bundle(concrete_2023, {"minimum_reinforcement": {}})
    with pytest.raises(TraceValidationError, match="cut direction"):
        _bundle(_long_input(detailing_cut_direction="Diagonal"),
                {"minimum_reinforcement": {}})


def test_longitudinal_2023_branches_slab_shapes_and_determinism():
    base = dict(detailing_edition=detailing.EC2_2023)
    tension = _long_input(P_pl=100.0, **base)
    tension_out = _candidate(tension)
    steps = _steps(_bundle(tension, tension_out), "longitudinal-minimum")
    assert steps["row-demand-kn"].result.value == pytest.approx(
        0.18 * 2.9 * 1000.0)
    assert steps["row-resistance-kn"].result.value == pytest.approx(982.0)
    assert tension_out["minimum_reinforcement"]["clause"] == (
        "12.2(2)(b), Formula (12.2)")

    compressed = _long_input(P_pl=-1.0e5, Mx_pl=100.0, **base)
    compressed_out = _candidate(compressed)
    steps = _steps(_bundle(compressed, compressed_out), "longitudinal-minimum")
    limit = 0.5 * 0.18 * compressed["concrete"].fcd * 1000.0
    assert steps["compression-limit"].result.value == pytest.approx(limit)
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 4.0

    idle = _long_input(P_pl=-10.0, **base)
    idle_out = _candidate(idle)
    assert idle_out["minimum_reinforcement"]["clause"] == "12.2(5)"
    steps = _steps(_bundle(idle, idle_out), "longitudinal-minimum")
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 4.0
    assert "compression-limit" not in steps

    bending = _long_input(Mx_pl=100.0, **base)
    bending_out = _candidate(bending)
    first = build_detailing_trace_family(
        bending, bending_out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT)
    second = build_detailing_trace_family(
        bending, bending_out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT)
    # The kernel-internal 2023 nominal-capacity solve must replay
    # deterministically: repeated builds seal identically.
    assert first.to_dict() == second.to_dict()
    steps = {step.step_id: step for step in first.calculations[0].steps}
    assert steps["row-m-cr-knm"].result.value == pytest.approx(
        2.9 * 1000.0 * 0.3 * 0.6 ** 2 / 6.0)
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 1.0

    slab_cut = _long_input(detailing_member_type=detailing.MEMBER_SLAB,
                           detailing_cut_direction=detailing.CUT_LONGITUDINAL,
                           Mx_pl=100.0)
    slab_cut_out = _candidate(slab_cut)
    assert "orthogonal primary reinforcement" in (
        slab_cut_out["minimum_reinforcement"]["reason"])
    steps = _steps(_bundle(slab_cut, slab_cut_out), "longitudinal-minimum")
    assert "slab-cut-scope" in steps
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 3.0

    slab = _long_input(detailing_member_type=detailing.MEMBER_SLAB,
                       Mx_pl=100.0)
    slab_out = _candidate(slab)
    assert slab_out["minimum_reinforcement"]["clause"] == (
        "9.3.1.1(1); 9.2.1.1(1), Formula (9.1N)")
    assert _bundle(slab, slab_out) is not None


def _screen_upstream(*, trd_c=60.0, t_ed=15.0, v_ed=30.0, vrd_c=200.0,
                     model=False, res_valid=True):
    upstream = {
        "torsion": {"subdivided": False, "t_ed": t_ed,
                    "primary": {"trd_c": trd_c}},
        "shear": {"res": {"valid": res_valid, "vrd_c": vrd_c}, "v_ed": v_ed,
                  "model_2023": model},
    }
    upstream["torsion"]["min_reinf"] = _refreshed_screen(upstream)
    return upstream


def test_screen_uniaxial_oracle_branches_and_shared_angle_independence():
    inp = _input(shear_on=True, torsion_on=True, shear_V=30.0, torsion_T=15.0)
    out = _candidate(inp)
    assert detailing_trace_applicability(inp) == ("min-reinf-screen",)
    bundle = _bundle(inp, out)
    assert len(bundle.calculations) == 1
    steps = _steps(bundle, "min-reinf-screen")
    value = (out["torsion"]["t_ed"] / out["torsion"]["primary"]["trd_c"]
             + out["shear"]["v_ed"] / out["shear"]["res"]["vrd_c"])
    assert steps["screen-primary-value"].result.value == pytest.approx(value)
    assert out["torsion"]["min_reinf"]["value"] == pytest.approx(value)
    assert steps["screen-primary-solid"].result.value == 1.0
    assert steps["ct-008-min-reinf-screen-result"].result.value == 1.0

    over = _input(shear_on=True, torsion_on=True, shear_V=200.0,
                  torsion_T=60.0)
    over_out = _candidate(over)
    assert over_out["torsion"]["min_reinf"]["ok"] is False
    assert _steps(_bundle(over, over_out), "min-reinf-screen")[
        "ct-008-min-reinf-screen-result"].result.value == 0.0

    alone = _input(torsion_on=True, torsion_T=15.0)
    alone_out = _candidate(alone)
    assert alone_out["torsion"]["min_reinf"]["reason"] == "no shear check"
    steps = _steps(_bundle(alone, alone_out), "min-reinf-screen")
    assert steps["ct-008-min-reinf-screen-result"].result.value == 4.0
    assert "screen-primary-value" not in steps

    outer = templates.t_section(1.0, 0.2, 0.3, 0.6)
    subdivided = _input(torsion_on=True, torsion_T=40.0,
                        torsion_subdivide=True,
                        torsion_subrects=[(0.0, -100.0, 300.0, 600.0),
                                          (0.0, 300.0, 1000.0, 200.0)],
                        outer=outer, bars=[],
                        section=Section.from_polygon(outer),
                        bar_elements=[], bar_materials=None)
    subdivided_out = _candidate(subdivided)
    assert subdivided_out["torsion"]["min_reinf"]["reason"] == (
        "subdivided (compound) section")
    steps = _steps(_bundle(subdivided, subdivided_out), "min-reinf-screen")
    assert steps["upstream-screen-primary-subdivided"].result.value == 1.0
    assert steps["ct-008-min-reinf-screen-result"].result.value == 4.0

    zero = _input(shear_on=True, torsion_on=True)
    zero_out = _screen_upstream(trd_c=0.0)
    steps = _steps(_bundle(zero, zero_out), "min-reinf-screen")
    assert zero_out["torsion"]["min_reinf"]["reason"] == "zero resistance"
    assert steps["upstream-screen-primary-trd-c"].result.value == 0.0
    assert steps["ct-008-min-reinf-screen-result"].result.value == 4.0

    # The screen is independent of CT-007 family applicability: with links on
    # the torsion family publishes nothing, the retained screen still seals.
    shared = _input(shear_on=True, shear_links=True, torsion_on=True,
                    shear_V=30.0, torsion_T=15.0)
    assert torsion_trace_applicability(shared) != "torsion"
    shared_out = _candidate(shared)
    assert validate_detailing_trace_family(
        _bundle(shared, shared_out), shared, shared_out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def test_screen_operand_mutations_are_rejected_and_replayed_exactly():
    inp = _input(shear_on=True, torsion_on=True)
    out = _screen_upstream()
    bundle = _bundle(inp, out)
    steps = _steps(bundle, "min-reinf-screen")
    assert steps["upstream-screen-primary-t-ed"].result.value == 15.0
    assert steps["upstream-screen-primary-trd-c"].result.value == 60.0
    assert steps["upstream-screen-primary-v-ed"].result.value == 30.0
    assert steps["upstream-screen-primary-vrd-c"].result.value == 200.0
    assert steps["screen-primary-value"].result.value == pytest.approx(0.4)
    baseline = bundle.to_dict()
    for changes in (dict(t_ed=16.0), dict(trd_c=50.0), dict(v_ed=40.0),
                    dict(vrd_c=150.0), dict(model=True),
                    dict(res_valid=False)):
        mutated_out = _screen_upstream(**changes)
        with pytest.raises(TraceValidationError):
            validate_detailing_trace_family(
                bundle, inp, mutated_out, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)
        rebuilt = _bundle(inp, mutated_out)
        assert rebuilt.to_dict() != baseline


_PRIORITY = {"INVALID": 4, "FAIL": 3, "NOT ASSESSED": 2, "NOT RUN": 2,
             "PASS": 1, "NOT APPLICABLE": 0}


def _face_state(row):
    torsion = row.get("torsion")
    if torsion is None:
        return "NOT RUN", 0.0
    check = torsion.get("min_reinf") or {}
    if not check.get("applicable"):
        return "NOT ASSESSED", 0.0
    value = check.get("value")
    if value is None or not math.isfinite(float(value)):
        return "INVALID", math.inf
    return ("PASS" if check.get("ok") else "FAIL"), float(value)


def test_screen_directional_single_biaxial_and_ordering_oracle():
    single = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                    shear_V=40.0, shear_Vx=40.0, shear_Vy=0.0)
    out = _candidate(single)
    top = out["torsion"]["min_reinf"]
    assert top["directional_status"] == (
        out["torsion"]["directional_min_reinf_status"])
    bundle = _bundle(single, out)
    steps = _steps(bundle, "min-reinf-screen")
    faces = out["shear"]["face_candidates"]
    states = [_face_state(row) for row in faces]
    governing = max(range(len(states)),
                    key=lambda i: (_PRIORITY[states[i][0]], states[i][1]))
    aggregate = next(status for status in
                     ("INVALID", "FAIL", "NOT ASSESSED", "NOT RUN", "PASS")
                     if status in {state for state, _ in states})
    assert steps["screen-primary-governing-face"].result.value == float(
        governing)
    assert steps["screen-primary-directional-status"].result.value == (
        SCREEN_STATE_CODES[aggregate])
    assert top["governing_face"] == (
        "negative" if faces[governing]["tension_low"] else "positive")

    biaxial = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=20.0, shear_Vy=30.0)
    biaxial_out = _candidate(biaxial)
    assert tuple(biaxial_out["torsion"]["min_reinf"]) == (
        "applicable", "reason")
    biaxial_bundle = _bundle(biaxial, biaxial_out)
    steps = _steps(biaxial_bundle, "min-reinf-screen")
    for component in ("vx", "vy"):
        entry = biaxial_out["torsion"]["directional_interactions"][component]
        screen = entry["min_reinf"]
        assert screen["directional_status"] == (
            entry["directional_min_reinf_status"])
        # The retained assessment_key prefers NOT ASSESSED faces over PASS;
        # the published component screen is the conservative governing face.
        if screen["applicable"]:
            assert steps[f"screen-{component}-value"].result.value == (
                pytest.approx(screen["value"]))
        else:
            assert steps[f"screen-{component}-status"].result.value == 4.0
    tampered = copy.deepcopy(biaxial_out)
    tampered["shear"]["directions"]["vx"]["face_candidates"][0][
        "torsion"]["min_reinf"]["value"] += 0.1
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            biaxial_bundle, biaxial, tampered, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)

    # Crafted metric tiebreak: two PASS faces, the larger 6.31 value governs.
    crafted = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=30.0, shear_Vy=0.0)
    shear_face = {"res": {"valid": True, "vrd_c": 200.0}, "v_ed": 30.0,
                  "model_2023": False}

    def _face(tension_low, trd_c, screen=None):
        torsion = {"subdivided": False, "t_ed": 15.0,
                   "primary": {"trd_c": trd_c}}
        torsion["min_reinf"] = screen if screen is not None else (
            _refreshed_screen({"torsion": torsion, "shear": shear_face}))
        return {"tension_low": tension_low, "shear": dict(shear_face),
                "torsion": torsion}

    face_a, face_b = _face(False, 60.0), _face(True, 25.0)
    top_torsion = dict(face_b["torsion"])
    top_torsion["min_reinf"] = dict(face_b["torsion"]["min_reinf"],
                                    directional_status="PASS",
                                    governing_face="negative")
    top_torsion["directional_min_reinf_status"] = "PASS"
    top_torsion["directional_min_reinf_governing_face"] = "negative"
    # Retained auto + zero-moment face order is (negative, positive).
    crafted_out = {
        "shear": dict(shear_face, face_candidates=[face_b, face_a]),
        "torsion": top_torsion,
    }
    steps = _steps(_bundle(crafted, crafted_out), "min-reinf-screen")
    assert steps["screen-primary-governing-face"].result.value == 0.0
    assert steps["screen-primary-value"].result.value == pytest.approx(0.75)

    # FAIL beats NOT ASSESSED in the retained aggregate ordering. Every
    # face screen must agree with its own siblings, so the NOT ASSESSED face
    # carries a genuinely invalid retained shear resistance.
    face_na = _face(False, 60.0,
                    screen={"applicable": False, "reason": "no shear check"})
    face_na["shear"] = {"res": {"valid": False}, "v_ed": 30.0,
                        "model_2023": False}
    face_fail = _face(True, 10.0)
    top_torsion = dict(face_fail["torsion"])
    top_torsion["min_reinf"] = dict(face_fail["torsion"]["min_reinf"],
                                    directional_status="FAIL",
                                    governing_face="negative")
    top_torsion["directional_min_reinf_status"] = "FAIL"
    top_torsion["directional_min_reinf_governing_face"] = "negative"
    mixed_out = {
        "shear": dict(shear_face, face_candidates=[face_fail, face_na]),
        "torsion": top_torsion,
    }
    steps = _steps(_bundle(crafted, mixed_out), "min-reinf-screen")
    assert steps["screen-primary-directional-status"].result.value == (
        SCREEN_STATE_CODES["FAIL"])
    assert steps["ct-008-min-reinf-screen-result"].result.value == 0.0


def test_new_member_candidates_walk_exactly():
    long_2005 = _long_input(Mx_pl=100.0)
    long_2023 = _long_input(Mx_pl=100.0,
                            detailing_edition=detailing.EC2_2023)
    for inp in (long_2005, long_2023):
        out = _candidate(inp)
        expected = _replay_longitudinal(inp, CONTEXT)[1].expected
        candidate = out["minimum_reinforcement"]
        _validate_longitudinal_candidate(copy.deepcopy(candidate), expected)
        for kind, path, detail in list(_walk(candidate)):
            if kind == "leaf":
                with pytest.raises(TraceValidationError):
                    _validate_longitudinal_candidate(
                        _replaced(copy.deepcopy(candidate), path,
                                  _mutated(detail)), expected)
                continue
            changed = copy.deepcopy(candidate)
            _at(changed, path)["unexpected-ct008-field"] = 0.0
            with pytest.raises(TraceValidationError):
                _validate_longitudinal_candidate(changed, expected)
            for key in detail:
                changed = copy.deepcopy(candidate)
                del _at(changed, path)[key]
                with pytest.raises(TraceValidationError):
                    _validate_longitudinal_candidate(changed, expected)
            if len(detail) > 1:
                changed = copy.deepcopy(candidate)
                node = _at(changed, path)
                items = [(key, node[key]) for key in reversed(detail)]
                node.clear()
                node.update(items)
                with pytest.raises(TraceValidationError):
                    _validate_longitudinal_candidate(changed, expected)

    screen_inp = _input(shear_on=True, torsion_on=True)
    screen_out = _screen_upstream()
    expected = _replay_screen(screen_inp, screen_out, CONTEXT)[1].expected
    _validate_screen_member(copy.deepcopy(screen_out), expected)
    published = screen_out["torsion"]["min_reinf"]
    for kind, path, detail in list(_walk(published)):
        if kind == "leaf":
            changed = copy.deepcopy(screen_out)
            changed["torsion"]["min_reinf"] = _replaced(
                copy.deepcopy(published), path, _mutated(detail))
            with pytest.raises(TraceValidationError):
                _validate_screen_member(changed, expected)
        else:
            for operation in ("add", "reorder"):
                changed = copy.deepcopy(screen_out)
                node = changed["torsion"]["min_reinf"]
                if operation == "add":
                    node["unexpected-ct008-field"] = 0.0
                else:
                    items = [(key, node[key]) for key in reversed(detail)]
                    node.clear()
                    node.update(items)
                with pytest.raises(TraceValidationError):
                    _validate_screen_member(changed, expected)
            for key in detail:
                changed = copy.deepcopy(screen_out)
                del changed["torsion"]["min_reinf"][key]
                with pytest.raises(TraceValidationError):
                    _validate_screen_member(changed, expected)

    single = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                    shear_V=40.0, shear_Vx=40.0, shear_Vy=0.0)
    single_out = _candidate(single)
    expected = _replay_screen(single, single_out, CONTEXT)[1].expected
    tampered = copy.deepcopy(single_out)
    tampered["torsion"]["directional_min_reinf_status"] = "PASS-tampered"
    with pytest.raises(TraceValidationError):
        _validate_screen_member(tampered, expected)
    biaxial = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=20.0, shear_Vy=30.0)
    biaxial_out = _candidate(biaxial)
    expected = _replay_screen(biaxial, biaxial_out, CONTEXT)[1].expected
    tampered = copy.deepcopy(biaxial_out)
    entry = tampered["torsion"]["directional_interactions"]["vx"]["min_reinf"]
    key = next(k for k in entry if k != "applicable")
    entry[key] = _mutated(entry[key])
    with pytest.raises(TraceValidationError):
        _validate_screen_member(tampered, expected)


def test_new_member_applicability_scope_selection_and_masking():
    # The screen exists whenever torsion_on has a retained section, entirely
    # independent of the detailing flags; both new members co-publish.
    both = _long_input(Mx_pl=100.0, torsion_on=True, torsion_T=15.0)
    both_out = _candidate(both)
    bundle = _bundle(both, both_out)
    assert detailing_trace_applicability(both) == (
        "longitudinal-minimum", "min-reinf-screen")
    assert len(bundle.calculations) == 2

    # Candidates supplied for absent flags fail closed.
    with pytest.raises(TraceValidationError,
                       match="absent CT-008 longitudinal-minimum"):
        build_detailing_trace_family(
            _input(), {"minimum_reinforcement": {"status": "PASS"}},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA)
    with pytest.raises(TraceValidationError,
                       match="absent CT-008 min-reinf-screen"):
        build_detailing_trace_family(
            _input(), {"torsion": {"min_reinf": {"applicable": False}}},
            input_sha256=INPUT_SHA, result_sha256=RESULT_SHA)

    # Scope-out branches select from validated direct inputs; junk in unread
    # inputs cannot mask either new member.
    slab_cut = _long_input(detailing_member_type=detailing.MEMBER_SLAB,
                           detailing_cut_direction=detailing.CUT_LONGITUDINAL)
    clean_out = _candidate(slab_cut)
    masked = dict(slab_cut, shear_V=math.nan, v_min=math.nan,
                  torsion_T=math.nan, shear_dlower=math.nan,
                  bridge_standard=object())
    assert build_detailing_trace_family(
        masked, clean_out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT).to_dict() == _bundle(slab_cut, clean_out).to_dict()
    with pytest.raises(TraceValidationError):
        _bundle(_long_input(sls_fctm=math.nan), {"minimum_reinforcement": {}})


# ---------------------------------------------------------------------------
# Adversarial-review additions for the C.3b members.
# ---------------------------------------------------------------------------

def _custom_long_input(outer, bars, dia=25.0, **changes):
    entries, materials, elements = [], [], []
    for index, (x, y, _area) in enumerate(bars, start=1):
        entry = material_catalog.default_entry(
            "mild", material_id=f"L{index}", preset=codes.EC2_2005_DKNA.label)
        entries.append(entry)
        materials.append(material_catalog.build_material(entry, "mild"))
        elements.append(dict(_bar(f"R{index}", x * 1000.0, y * 1000.0, dia),
                             material_id=f"L{index}"))
    inp = _input(
        minimum_reinforcement_on=True, sls_fctm=2.9, outer=outer,
        bars=list(bars), section=Section.from_polygon(outer, list(bars)),
        bar_elements=elements, bar_materials=materials,
        mild_material_catalog={"version": 1, "next_id": 9, "items": entries},
    )
    inp.update(changes)
    return inp


def _walk_rejects(candidate, expected, validator):
    validator(copy.deepcopy(candidate), expected)
    for kind, path, detail in list(_walk(candidate)):
        if kind == "leaf":
            with pytest.raises(TraceValidationError):
                validator(_replaced(copy.deepcopy(candidate), path,
                                    _mutated(detail)), expected)
            continue
        changed = copy.deepcopy(candidate)
        _at(changed, path)["unexpected-ct008-field"] = 0.0
        with pytest.raises(TraceValidationError):
            validator(changed, expected)
        for key in detail:
            changed = copy.deepcopy(candidate)
            del _at(changed, path)[key]
            with pytest.raises(TraceValidationError):
                validator(changed, expected)
        if len(detail) > 1:
            changed = copy.deepcopy(candidate)
            node = _at(changed, path)
            items = [(key, node[key]) for key in reversed(detail)]
            node.clear()
            node.update(items)
            with pytest.raises(TraceValidationError):
                validator(changed, expected)


def test_slab_2023_scope_cells_and_compression_boundary():
    # P1-A control: the Slab dispatch overwrites the 12.2(5) clause in place;
    # the scope-out branch is selected by the unique retained key shape.
    slab_scope = _long_input(P_pl=-10.0,
                             detailing_edition=detailing.EC2_2023,
                             detailing_member_type=detailing.MEMBER_SLAB)
    slab_out = _candidate(slab_scope)
    result = slab_out["minimum_reinforcement"]
    assert result["status"] == "NOT APPLICABLE"
    assert result["clause"] == "Table 12.2, item 1; 12.2(2)(a), Formula (12.1)"
    bundle = _bundle(slab_scope, slab_out)
    steps = _steps(bundle, "longitudinal-minimum")
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 4.0
    assert validate_detailing_trace_family(
        bundle, slab_scope, slab_out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None

    # High-compression scope-out exactly at the 0.5 Ac fcd boundary.
    base = _long_input(detailing_edition=detailing.EC2_2023, Mx_pl=100.0)
    limit = 0.5 * 0.18 * base["concrete"].fcd * 1000.0
    boundary = dict(base, P_pl=-limit)
    boundary_out = _candidate(boundary)
    assert boundary_out["minimum_reinforcement"]["status"] == "NOT APPLICABLE"
    steps = _steps(_bundle(boundary, boundary_out), "longitudinal-minimum")
    assert steps["compression-limit"].result.value == pytest.approx(limit)
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 4.0


def test_longitudinal_2023_invalid_branch_classification():
    # Neither retained cracking-INVALID reason is constructible from valid
    # retained inputs (a moment on positive-area concrete always produces a
    # tension candidate, and the plain-concrete uncracked solve converges),
    # so the branch is controlled at the classification/contract level.
    synthetic = {
        "status": "INVALID", "edition": detailing.EC2_2023,
        "clause": "12.2(2)(a), Formula (12.1)", "n_ed_tension_kn": 0.0,
        "mx_ed_centroid_knm": 50.0, "my_ed_centroid_knm": 0.0, "checks": [],
        "reason": "uncracked section solve did not converge",
        "limitations": [], "member_type": detailing.MEMBER_BEAM,
        "cut_direction": detailing.CUT_TRANSVERSE,
        "modelled_reinforcement_direction": "longitudinal",
    }
    state = dict(member=detailing.MEMBER_BEAM,
                 cut=detailing.CUT_TRANSVERSE,
                 edition=detailing.EC2_2023)
    assert _long_branch(state, synthetic) == "2023-invalid"


def test_longitudinal_none_fields_my_axis_and_remaining_shape_walks():
    outer = [(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)]
    # 2005 invalid tension zone: bars on the compression face only. The FAIL
    # row keeps as_min/utilisation/fyk absent-by-state; nothing is fabricated.
    empty_zone = _custom_long_input(
        outer, [(-0.12, 0.25, 491.0), (0.12, 0.25, 491.0)], Mx_pl=100.0)
    empty_out = _candidate(empty_zone)
    row = empty_out["minimum_reinforcement"]["checks"][0]
    assert row["status"] == "FAIL"
    assert row["as_min_mm2"] is None and row["utilisation"] is None
    assert row["fyk_mpa"] is None
    assert row["reason"] == "no usable tension reinforcement or geometry"
    steps = _steps(_bundle(empty_zone, empty_out), "longitudinal-minimum")
    assert "row-as-min-mm2" not in steps and "row-fyk-mpa" not in steps
    assert "row-utilisation" not in steps
    assert steps["row-as-provided-mm2"].result.value == 0.0
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 0.0

    # My-axis sign convention: opposite My signs select opposite faces.
    left = _long_input(My_pl=100.0)
    right = _long_input(My_pl=-100.0)
    left_out, right_out = _candidate(left), _candidate(right)
    left_row = left_out["minimum_reinforcement"]["checks"][0]
    right_row = right_out["minimum_reinforcement"]["checks"][0]
    assert left_row["axis"] == "y" and right_row["axis"] == "y"
    assert {left_row["face"], right_row["face"]} == {"left", "right"}
    assert set(left_row["bar_ids"]).isdisjoint(right_row["bar_ids"])
    assert _steps(_bundle(left, left_out), "longitudinal-minimum")[
        "my-centroid"].result.value == pytest.approx(100.0)

    # Biaxial resultant tension zone.
    biaxial = _long_input(Mx_pl=100.0, My_pl=100.0)
    biaxial_out = _candidate(biaxial)
    row = biaxial_out["minimum_reinforcement"]["checks"][0]
    assert row["axis"] == "xy" and row["face"] == "resultant tension zone"
    assert _bundle(biaxial, biaxial_out) is not None

    # Adversarial walks over the remaining frozen longitudinal shapes.
    cells = (
        _long_input(P_pl=-1.0e5, Mx_pl=100.0,
                    detailing_edition=detailing.EC2_2023),   # high compression
        _long_input(P_pl=-10.0, detailing_edition=detailing.EC2_2023),
        _long_input(P_pl=100.0, detailing_edition=detailing.EC2_2023),
        _long_input(detailing_member_type=detailing.MEMBER_SLAB,
                    detailing_cut_direction=detailing.CUT_LONGITUDINAL),
        empty_zone,
    )
    for inp in cells:
        out = _candidate(inp)
        expected = _replay_longitudinal(inp, CONTEXT)[1].expected
        _walk_rejects(out["minimum_reinforcement"], expected,
                      _validate_longitudinal_candidate)


def test_longitudinal_2023_tension_fail_zero_resistance_and_finiteness():
    outer = [(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)]
    weak = _custom_long_input(outer, [(0.0, -0.25, 50.0)], dia=8.0,
                              P_pl=100.0,
                              detailing_edition=detailing.EC2_2023)
    weak_out = _candidate(weak)
    row = weak_out["minimum_reinforcement"]["checks"][0]
    assert row["status"] == "FAIL" and row["utilisation"] > 1.0
    steps = _steps(_bundle(weak, weak_out), "longitudinal-minimum")
    resistance_kn = 50.0e-6 * weak["bar_materials"][0].fytk * 1000.0
    assert steps["row-utilisation"].result.value == pytest.approx(
        (0.18 * 2.9 * 1000.0) / resistance_kn)
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 0.0

    bare = _custom_long_input(outer, [], P_pl=100.0,
                              detailing_edition=detailing.EC2_2023)
    bare_out = _candidate(bare)
    row = bare_out["minimum_reinforcement"]["checks"][0]
    assert row["status"] == "FAIL" and row["utilisation"] is None
    assert row["resistance_kn"] == 0.0
    steps = _steps(_bundle(bare, bare_out), "longitudinal-minimum")
    assert "row-utilisation" not in steps
    assert steps["row-resistance-kn"].result.value == 0.0
    assert steps["ct-008-longitudinal-minimum-result"].result.value == 0.0

    for key in ("P_pl", "Mx_pl", "My_pl"):
        for bad in (math.nan, math.inf):
            with pytest.raises(TraceValidationError):
                _bundle(_long_input(**{key: bad}),
                        {"minimum_reinforcement": {}})


def test_longitudinal_concrete_identity_same_law_different_id():
    first = _long_input(Mx_pl=100.0, concrete_material_id="C1")
    first_out = _candidate(first)
    bundle = _bundle(first, first_out)
    assert concrete_leaf_id("C1", "fck") in _steps(bundle,
                                                   "longitudinal-minimum")
    second = dict(first, concrete_material_id="C2")
    second_out = _candidate(second)
    assert second_out["minimum_reinforcement"] == first_out[
        "minimum_reinforcement"]
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, second, second_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    assert validate_detailing_trace_family(
        _bundle(second, second_out), second, second_out,
        input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT) is not None


def test_screen_holed_section_publishes_solid_false_end_to_end():
    outer = templates.rectangle(0.4, 0.6)
    hole = templates.rectangle(0.2, 0.4)
    bars = [(-0.15, -0.25, 500.0)]
    inp = _input(shear_on=True, torsion_on=True, shear_V=30.0,
                 torsion_T=15.0, outer=outer, holes=[hole], bars=bars,
                 section=Section.from_polygon(outer, bars, [hole]))
    out = _candidate(inp)
    assert out["torsion"]["min_reinf"]["solid"] is False
    steps = _steps(_bundle(inp, out), "min-reinf-screen")
    assert steps["input-holes-count"].result.value == 1.0
    assert steps["screen-primary-solid"].result.value == 0.0


def test_screen_face_states_legends_reorder_and_governing_tampers():
    # SCREEN_STATE_CODES is a distinct literal legend from STATUS_CODES.
    assert SCREEN_STATE_CODES == {
        "NOT APPLICABLE": 0.0, "PASS": 1.0, "NOT ASSESSED": 2.0,
        "NOT RUN": 3.0, "FAIL": 4.0, "INVALID": 5.0,
    }
    crafted = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=30.0, shear_Vy=0.0)
    shear_face = {"res": {"valid": True, "vrd_c": 200.0}, "v_ed": 30.0,
                  "model_2023": False}

    def _face(tension_low, trd_c):
        torsion = {"subdivided": False, "t_ed": 15.0,
                   "primary": {"trd_c": trd_c}}
        torsion["min_reinf"] = _refreshed_screen(
            {"torsion": torsion, "shear": shear_face})
        return {"tension_low": tension_low, "shear": dict(shear_face),
                "torsion": torsion}

    # NOT RUN face (absent torsion) reaches a built, validated bundle.
    not_run = {"tension_low": False, "shear": dict(shear_face),
               "torsion": None}
    face_fail = _face(True, 10.0)
    top_torsion = dict(face_fail["torsion"])
    top_torsion["min_reinf"] = dict(face_fail["torsion"]["min_reinf"],
                                    directional_status="FAIL",
                                    governing_face="negative")
    top_torsion["directional_min_reinf_status"] = "FAIL"
    top_torsion["directional_min_reinf_governing_face"] = "negative"
    out = {"shear": dict(shear_face, face_candidates=[face_fail, not_run]),
           "torsion": top_torsion}
    bundle = _bundle(crafted, out)
    steps = _steps(bundle, "min-reinf-screen")
    assert steps["upstream-screen-primary-face-01-run"].result.value == 0.0
    assert steps["screen-primary-face-01-assessment-status"].result.value == (
        SCREEN_STATE_CODES["NOT RUN"])
    # P1-B control: each sealed legend matches the map the step actually uses.
    face_step = steps["screen-primary-face-00-assessment-status"]
    assert "NOT RUN=3" in face_step.actual_expression
    assert "REVIEW" not in face_step.actual_expression
    directional_step = steps["screen-primary-directional-status"]
    assert "NOT RUN=3" in directional_step.actual_expression
    scope_step = steps["screen-primary-status"]
    assert "REVIEW=2" in scope_step.actual_expression
    assert "NOT RUN" not in scope_step.actual_expression
    assert validate_detailing_trace_family(
        bundle, crafted, out, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None

    # An INVALID (nonfinite) face always governs, and a published nonfinite
    # screen is never sealed as finite evidence: the trace fails closed.
    invalid_face = _face(False, 60.0)
    invalid_face["torsion"]["min_reinf"] = dict(
        invalid_face["torsion"]["min_reinf"], value=math.nan)
    invalid_top = dict(invalid_face["torsion"])
    invalid_top["min_reinf"] = dict(invalid_top["min_reinf"],
                                    directional_status="INVALID",
                                    governing_face="positive")
    invalid_top["directional_min_reinf_status"] = "INVALID"
    invalid_top["directional_min_reinf_governing_face"] = "positive"
    invalid_out = {
        "shear": dict(shear_face,
                      face_candidates=[_face(True, 60.0), invalid_face]),
        "torsion": invalid_top,
    }
    with pytest.raises(TraceValidationError):
        build_detailing_trace_family(
            crafted, invalid_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)

    # Ordering oracle across all five states against the retained callables.
    literal = {"INVALID": 4, "FAIL": 3, "NOT ASSESSED": 2, "NOT RUN": 2,
               "PASS": 1, "NOT APPLICABLE": 0}
    cases = (("INVALID", math.inf), ("FAIL", 1.4), ("NOT ASSESSED", 0.0),
             ("NOT RUN", 0.0), ("PASS", 0.9), ("PASS", 1.1))
    for status, metric in cases:
        assert capacity.assessment_key(status, metric) == (
            literal[status], metric)
    ordered = ("INVALID", "FAIL", "NOT ASSESSED", "NOT RUN", "PASS")
    for index, status in enumerate(ordered):
        assert capacity.aggregate_assessment_status(
            list(ordered[index:])) == status

    # Governing-face tampers on a real single-active dispatch are rejected.
    single = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                    shear_V=40.0, shear_Vx=40.0, shear_Vy=0.0)
    single_out = _candidate(single)
    single_bundle = _bundle(single, single_out)
    flipped = {"negative": "positive", "positive": "negative"}
    for tamper in ("top", "sibling"):
        changed = copy.deepcopy(single_out)
        if tamper == "top":
            screen = changed["torsion"]["min_reinf"]
            screen["governing_face"] = flipped[screen["governing_face"]]
        else:
            changed["torsion"]["directional_min_reinf_governing_face"] = (
                flipped[changed["torsion"][
                    "directional_min_reinf_governing_face"]])
        with pytest.raises(TraceValidationError):
            validate_detailing_trace_family(
                single_bundle, single, changed, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)

    # P2-C control: a reordered directional-interaction container fails.
    biaxial = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=20.0, shear_Vy=30.0)
    biaxial_out = _candidate(biaxial)
    biaxial_bundle = _bundle(biaxial, biaxial_out)
    reordered = copy.deepcopy(biaxial_out)
    interactions = reordered["torsion"]["directional_interactions"]
    reordered["torsion"]["directional_interactions"] = dict(
        reversed(list(interactions.items())))
    with pytest.raises(TraceValidationError, match="keys/order"):
        validate_detailing_trace_family(
            biaxial_bundle, biaxial, reordered, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)


def test_non_governing_face_screens_are_fully_validated():
    # P1 control: every face-specific screen is exact-map validated against
    # its own sibling payloads, so mutating a NON-governing face screen can
    # never reseal coherently.
    crafted = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=30.0, shear_Vy=0.0)
    shear_face = {"res": {"valid": True, "vrd_c": 200.0}, "v_ed": 30.0,
                  "model_2023": False}

    def _face(tension_low, trd_c):
        torsion = {"subdivided": False, "t_ed": 15.0,
                   "primary": {"trd_c": trd_c}}
        torsion["min_reinf"] = _refreshed_screen(
            {"torsion": torsion, "shear": shear_face})
        return {"tension_low": tension_low, "shear": dict(shear_face),
                "torsion": torsion}

    face_a, face_b = _face(False, 60.0), _face(True, 25.0)
    top_torsion = dict(face_b["torsion"])
    top_torsion["min_reinf"] = dict(face_b["torsion"]["min_reinf"],
                                    directional_status="PASS",
                                    governing_face="negative")
    top_torsion["directional_min_reinf_status"] = "PASS"
    top_torsion["directional_min_reinf_governing_face"] = "negative"
    out = {"shear": dict(shear_face, face_candidates=[face_b, face_a]),
           "torsion": top_torsion}
    bundle = _bundle(crafted, out)
    steps = _steps(bundle, "min-reinf-screen")
    assert steps["screen-primary-governing-face"].result.value == 0.0

    mutations = (("t_ed", 16.0), ("trd_c", 55.0), ("v_ed", 40.0),
                 ("vrd_c", 150.0), ("solid", False), ("model_2023", True),
                 ("value", 0.5), ("ok", False))
    for key, replacement in mutations:
        changed = copy.deepcopy(out)
        changed["shear"]["face_candidates"][1]["torsion"]["min_reinf"][
            key] = replacement
        with pytest.raises(TraceValidationError):
            validate_detailing_trace_family(
                bundle, crafted, changed, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)

    # Full inventory walk over the non-governing face screen.
    face_screen = out["shear"]["face_candidates"][1]["torsion"]["min_reinf"]
    for kind, path, detail in list(_walk(face_screen)):
        if kind == "leaf":
            variants = [_replaced(copy.deepcopy(face_screen), path,
                                  _mutated(detail))]
        else:
            added = copy.deepcopy(face_screen)
            added["unexpected-ct008-field"] = 0.0
            reordered = dict(reversed(list(face_screen.items())))
            variants = [added, reordered]
            for key in detail:
                removed = copy.deepcopy(face_screen)
                del removed[key]
                variants.append(removed)
        for variant in variants:
            changed = copy.deepcopy(out)
            changed["shear"]["face_candidates"][1]["torsion"][
                "min_reinf"] = variant
            with pytest.raises(TraceValidationError):
                validate_detailing_trace_family(
                    bundle, crafted, changed, input_sha256=INPUT_SHA,
                    result_sha256=RESULT_SHA, context=CONTEXT)

    # Real biaxial dispatch: the applicable face is NON-governing (the
    # retained ordering prefers the NOT ASSESSED face); it must still be
    # exact-map validated per component.
    biaxial = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=20.0, shear_Vy=30.0)
    biaxial_out = _candidate(biaxial)
    biaxial_bundle = _bundle(biaxial, biaxial_out)
    faces = biaxial_out["shear"]["directions"]["vx"]["face_candidates"]
    assert len(faces) == 2
    states = [_face_state(row) for row in faces]
    governing = max(range(len(states)),
                    key=lambda i: (_PRIORITY[states[i][0]], states[i][1]))
    other = 1 - governing
    target = faces[other]["torsion"]["min_reinf"]
    assert target["applicable"] is True
    for key in ("t_ed", "trd_c", "v_ed", "vrd_c", "solid", "model_2023"):
        changed = copy.deepcopy(biaxial_out)
        screen = changed["shear"]["directions"]["vx"]["face_candidates"][
            other]["torsion"]["min_reinf"]
        screen[key] = _mutated(screen[key])
        with pytest.raises(TraceValidationError):
            validate_detailing_trace_family(
                biaxial_bundle, biaxial, changed, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)


def test_face_candidate_set_must_match_the_input_contract():
    # P1 control: the required face set derives from the INPUT specification
    # (capacity.shear_face_candidates over the retained direction spec), so a
    # resealed result cannot drop, duplicate, reorder, or relabel faces.
    crafted = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=30.0, shear_Vy=0.0)
    shear_face = {"res": {"valid": True, "vrd_c": 200.0}, "v_ed": 30.0,
                  "model_2023": False}

    def _face(tension_low, trd_c):
        torsion = {"subdivided": False, "t_ed": 15.0,
                   "primary": {"trd_c": trd_c}}
        torsion["min_reinf"] = _refreshed_screen(
            {"torsion": torsion, "shear": shear_face})
        return {"tension_low": tension_low, "shear": dict(shear_face),
                "torsion": torsion}

    def _top(face, status):
        torsion = dict(face["torsion"])
        governing = "negative" if face["tension_low"] else "positive"
        torsion["min_reinf"] = dict(face["torsion"]["min_reinf"],
                                    directional_status=status,
                                    governing_face=governing)
        torsion["directional_min_reinf_status"] = status
        torsion["directional_min_reinf_governing_face"] = governing
        return torsion

    face_true, face_false = _face(True, 25.0), _face(False, 10.0)
    assert face_false["torsion"]["min_reinf"]["ok"] is False
    valid_out = {
        "shear": dict(shear_face, face_candidates=[face_true, face_false]),
        "torsion": _top(face_false, "FAIL"),
    }
    bundle = _bundle(crafted, valid_out)
    assert _steps(bundle, "min-reinf-screen")[
        "ct-008-min-reinf-screen-result"].result.value == 0.0

    # (a) Deleting the failing face and republishing the survivor as a
    # governing PASS must be rejected against the two-face input contract.
    deleted = {
        "shear": dict(shear_face, face_candidates=[face_true]),
        "torsion": _top(face_true, "PASS"),
    }
    with pytest.raises(TraceValidationError, match="face candidates"):
        build_detailing_trace_family(
            crafted, deleted, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    with pytest.raises(TraceValidationError):
        validate_detailing_trace_family(
            bundle, crafted, deleted, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)

    # (b) duplicated, (c) reordered, and (d) mislabelled face sets fail too.
    mislabelled = copy.deepcopy(valid_out)
    mislabelled["shear"]["face_candidates"][1]["tension_low"] = True
    for candidates in ([face_true, face_true],
                       [face_false, face_true],
                       mislabelled["shear"]["face_candidates"]):
        broken = dict(valid_out,
                      shear=dict(shear_face, face_candidates=candidates))
        with pytest.raises(TraceValidationError, match="face candidates"):
            build_detailing_trace_family(
                crafted, broken, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)

    # (e) An explicit selector requires exactly one face.
    explicit = dict(crafted, shear_face_x="negative")
    single_face = {
        "shear": dict(shear_face, face_candidates=[face_true]),
        "torsion": _top(face_true, "PASS"),
    }
    assert build_detailing_trace_family(
        explicit, single_face, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None
    with pytest.raises(TraceValidationError, match="face candidates"):
        build_detailing_trace_family(
            explicit, valid_out, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)

    # (f) A nonzero associated moment selects one specific face; the wrong
    # single face is rejected and the right one builds.
    moment = dict(crafted, My_pl=50.0)
    wrong_face = {
        "shear": dict(shear_face, face_candidates=[face_false]),
        "torsion": _top(face_false, "FAIL"),
    }
    with pytest.raises(TraceValidationError, match="face candidates"):
        build_detailing_trace_family(
            moment, wrong_face, input_sha256=INPUT_SHA,
            result_sha256=RESULT_SHA, context=CONTEXT)
    assert build_detailing_trace_family(
        moment, single_face, input_sha256=INPUT_SHA,
        result_sha256=RESULT_SHA, context=CONTEXT) is not None

    # Biaxial component: the same contract applies per component.
    biaxial = _input(shear_on=True, torsion_on=True, torsion_T=15.0,
                     shear_V=30.0, shear_Vx=20.0, shear_Vy=30.0)
    biaxial_out = _candidate(biaxial)
    biaxial_bundle = _bundle(biaxial, biaxial_out)
    dropped = copy.deepcopy(biaxial_out)
    dropped["shear"]["directions"]["vx"]["face_candidates"].pop()
    flipped = copy.deepcopy(biaxial_out)
    flipped["shear"]["directions"]["vx"]["face_candidates"][0][
        "tension_low"] = not flipped["shear"]["directions"]["vx"][
            "face_candidates"][0]["tension_low"]
    for tampered in (dropped, flipped):
        with pytest.raises(TraceValidationError):
            validate_detailing_trace_family(
                biaxial_bundle, biaxial, tampered, input_sha256=INPUT_SHA,
                result_sha256=RESULT_SHA, context=CONTEXT)
