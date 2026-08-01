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
from sector.detailing_trace import (
    _replay_clear, _replay_transverse, _validate_clear_candidate,
    _validate_transverse_candidate, build_detailing_trace_family,
    detailing_trace_applicability, validate_detailing_trace_family,
)
from sector.detailing_trace_contract import (
    ADAPTER_SOURCE, DetailingShape, RATIO_SOURCE_2023, RATIO_SOURCE_BASE,
    RATIO_SOURCE_DK, REQUIRED_LINKS_RES_2023, STATUS_CODES,
    concrete_leaf_id, expected_registry,
)
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
        "valid": False, "reason": None,
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


def _rich_inputs():
    inp = _input(clear_spacing_on=True, transverse_detailing_on=True,
                 shear_on=True, shear_links=True, torsion_on=True,
                 shear_vy_transverse_leg_spacing=600.0)
    inp["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                           _bar("R2", 45.0, 0.0, 20.0),
                           _bar("R3", 90.0, 40.0, 25.0)]
    inp["tendon_elements"] = [_bar("P1", 200.0, 0.0, 60.0, kind="tendon")]
    upstream = {
        "shear": _shear_direction(v_ed=300.0),
        "torsion": {"valid": True, "tube": {
            "valid": True, "reason": None, "tef": 100.0, "uk": 1.4,
            "minimum_dimension_mm": 300.0}},
    }
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
    inert = dict(out)
    inert["minimum_reinforcement"] = math.nan
    inert["directional_interactions"] = object()
    inert["shear"] = dict(out["shear"], min_reinf=math.nan,
                          directional_min_reinf_status=math.nan,
                          report_rows=object())
    inert["torsion"] = dict(out["torsion"], min_reinf=math.nan,
                            interaction=math.nan,
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
    registry = expected_registry(DetailingShape(clear_shape, transverse_shape))
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
    upstream = {
        "shear": _shear_direction(),
        "torsion": {"valid": True, "tube": {
            "valid": True, "reason": None, "tef": 100.0, "uk": 1.4,
            "minimum_dimension_mm": 300.0}},
    }
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
        mutated_out = _candidate(inp, upstream=_with(
            upstream, path, replacements[path]))
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
    inp = _input(clear_spacing_on=True, transverse_detailing_on=True,
                 torsion_on=True, torsion_T=20.0, mode="Capacity only")
    inp["bar_elements"] = [_bar("R1", 0.0, 0.0, 20.0),
                           _bar("R2", 45.0, 0.0, 20.0)]
    out = run_analysis(inp)
    assert "clear_spacing" in out and "transverse_reinforcement" in out
    bundle = build_detailing_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)
    assert bundle is not None and len(bundle.calculations) == 2
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
    inp = _input(transverse_detailing_on=True, shear_on=True,
                 shear_links=True, torsion_on=True, shear_link_s=0.0)
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
    upstream = {"torsion": {"valid": False, "reason": None, "tube": {
        "valid": False, "reason": "compound outline needs sub-tubes",
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
