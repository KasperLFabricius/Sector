"""Closed native minimum-reinforcement diagnostics retain their assessment state."""
import ast
import copy
import logging
from pathlib import Path

import pytest
from app import result_presentation as presentation
from sector import detailing
from sector.materials import Concrete
from sector.section import Section


@pytest.mark.parametrize("edition", [detailing.EC2_2005, detailing.EC2_2005_DKNA, detailing.EC2_2023])
def test_native_secondary_slab_limitation_is_visible_without_repeated_warning(edition, caplog):
    section = Section.from_polygon([(-0.15, -0.3), (0.15, -0.3), (0.15, 0.3), (-0.15, 0.3)], [])
    retained = detailing.minimum_reinforcement(
        section, [], [], Concrete(30.0, gamma_c=1.5), edition=edition,
        fctm_mpa=2.9, n_ed_tension_kn=0.0, mx_ed_knm=100.0, my_ed_knm=0.0,
        member_type=detailing.MEMBER_SLAB, cut_direction=detailing.CUT_LONGITUDINAL,
    )
    before = copy.deepcopy(retained)
    caplog.set_level(logging.WARNING)
    for _ in range(3):
        rows = presentation.result_summary_rows(
            {"minimum_reinforcement_on": True}, {"minimum_reinforcement": retained}
        )
        row = next(r for r in rows if r.get("overview_key") == "minimum_reinforcement")
        assert row["status"] == "NOT ASSESSED"
        assert row["note"] == (
            "The minimum secondary reinforcement depends on the orthogonal primary reinforcement. "
            "This section cut does not represent that primary reinforcement."
        )
    assert retained == before
    assert not [r for r in caplog.records if "Suppressed untrusted diagnostic" in r.message]


def test_every_registered_native_minimum_reason_has_source_provenance():
    source = Path(detailing.__file__).read_text(encoding="utf-8-sig")
    literals = {n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    inherited = presentation._PLASTIC_REASON_MESSAGES
    for raw in presentation._MINIMUM_REINFORCEMENT_REASON_MESSAGES:
        assert (raw in literals or raw in inherited or raw == "No ordinary reinforcement bar lies in the tension zone.")


@pytest.mark.parametrize("raw", ["<script>alert(1)</script>", "internal_key traceback secret", "no ordinary reinforcement ", {"reason": "no ordinary reinforcement"}])
def test_unknown_or_hostile_minimum_reason_still_fails_closed(raw, caplog):
    caplog.set_level(logging.WARNING)
    text = presentation.result_reason(raw, "minimum_reinforcement")
    assert text == presentation._RESULT_REASON_FALLBACKS["minimum_reinforcement"].text
    assert "Suppressed untrusted diagnostic" in caplog.text


def test_all_closed_minimum_reasons_remain_quiet(caplog):
    caplog.set_level(logging.WARNING)
    for raw in presentation._MINIMUM_REINFORCEMENT_REASON_MESSAGES:
        assert presentation.result_reason(raw, "minimum_reinforcement")
        assert presentation.result_reason(raw, "minimum_reinforcement")
    assert "Suppressed untrusted diagnostic" not in caplog.text


@pytest.mark.parametrize("direction,tube,member", [
    ({"component": "vx"}, None, "Beam"),
    ({"component": "vx", "bw_mm": 300, "d_mm": 0, "legs": 1}, None, "Beam"),
    ({"component": "vx", "bw_mm": 300, "d_mm": 600, "links_present": False, "links_required": False}, None, "Beam"),
    (None, {}, "Beam"),
    (None, {"valid": False}, "Beam"),
    (None, {"tef_mm": -1, "uk_mm": 1000, "minimum_dimension_mm": 300}, "Beam"),
    (None, {}, "Slab"),
])
def test_native_transverse_conditions_retain_status_and_explanation(direction, tube, member, caplog):
    retained = detailing.transverse_reinforcement(
        edition=detailing.EC2_2023, fck_mpa=30, fywk_mpa=500,
        diameter_mm=10, spacing_mm=150,
        shear_directions=[] if direction is None else [direction],
        torsion_tubes=[] if tube is None else [tube], member_type=member,
    )
    before = copy.deepcopy(retained)
    caplog.set_level(logging.WARNING)
    reasons = [c["reason"] for c in retained["checks"] if c.get("reason")]
    assert reasons
    for _ in range(2):
        rows = presentation.result_summary_rows({"transverse_detailing_on": True}, {"transverse_reinforcement": retained})
        assert rows
        for reason in reasons:
            assert presentation.result_reason(reason, "transverse_reinforcement") in " ".join(str(r["note"]) for r in rows)
    assert retained == before
    assert "Suppressed untrusted diagnostic" not in caplog.text


def test_all_native_invalid_transverse_input_combinations_are_closed(caplog):
    import itertools
    fields = {"fck_mpa": 30, "fywk_mpa": 500, "diameter_mm": 10, "spacing_mm": 150}
    caplog.set_level(logging.WARNING)
    for size in range(1, 5):
        for group in itertools.combinations(fields, size):
            values = dict(fields)
            values.update({name: 0 for name in group})
            retained = detailing.transverse_reinforcement(edition=detailing.EC2_2023, **values)
            assert retained["status"] == "INVALID"
            assert presentation.result_reason(retained["reason"], "transverse_reinforcement") != presentation._RESULT_REASON_FALLBACKS["transverse_reinforcement"].text
    assert "Suppressed untrusted diagnostic" not in caplog.text


@pytest.mark.parametrize("raw", ["invalid spacing, arbitrary", "missing shear-link geometry <script>", "effective depth is unavailable "])
def test_unknown_transverse_condition_still_fails_closed(raw, caplog):
    caplog.set_level(logging.WARNING)
    assert presentation.result_reason(raw, "transverse_reinforcement") == presentation._RESULT_REASON_FALLBACKS["transverse_reinforcement"].text
    assert "Suppressed untrusted diagnostic" in caplog.text

@pytest.mark.parametrize("elements,status", [
    ([], "NOT ASSESSED"),
    ([{"kind": "bar", "id": "B1", "x_mm": 0, "y_mm": 0, "diameter_mm": 16}], "NOT ASSESSED"),
    ([{"kind": "bar", "id": "B1", "x_mm": 0, "y_mm": 0, "diameter_mm": -1}], "INVALID"),
])
def test_native_clear_spacing_reasons_are_shared_with_ui_and_report(elements, status, caplog):
    retained = detailing.clear_spacing(elements, d_upper_mm=16, edition=detailing.EC2_2023)
    before = copy.deepcopy(retained)
    assert retained["status"] == status
    caplog.set_level(logging.WARNING)
    for context in ["clear-spacing card reason", "clear-spacing detail reason", "report clear-spacing reason"]:
        value = presentation.result_reason(retained["reason"], "generic", context=context)
        assert value == presentation._GENERIC_REASON_MESSAGES[retained["reason"]].text
    assert retained == before
    assert "Suppressed untrusted diagnostic" not in caplog.text


@pytest.mark.parametrize("raw", ["missing or invalid reinforcement geometry<script>", "fewer than two included reinforcement elements "])
def test_unknown_clear_spacing_reason_still_fails_closed(raw, caplog):
    caplog.set_level(logging.WARNING)
    assert presentation.result_reason(raw, "generic") == presentation._RESULT_REASON_FALLBACKS["generic"].text
    assert "Suppressed untrusted diagnostic" in caplog.text

@pytest.mark.parametrize("route", ["chord", "shear", "crack_long", "crack_short"])
def test_native_unavailable_resistance_and_invalid_elastic_reasons_are_registered(route, caplog):
    from sector import capacity, sls
    if route == "chord":
        result = capacity.provided_link_longitudinal_publication_assessment(None)
        assert result["status"] == "NOT ASSESSED"
        raw, family = result["reason"], "shear"
    elif route == "shear":
        result = capacity.select_nominal_shear_resistance({"res": {"valid": False}}, links_selected=False)
        assert result.valid is False and result.status == "INVALID"
        raw, family = result.reason, "shear"
    else:
        result = sls._duration_crack_output({}, duration="long_term" if route == "crack_long" else "short_term", valid=False, requested=True, criterion_mm=0.0)
        assert result["calculation_state"] == "NOT ASSESSED"
        raw, family = result["reason"], "crack"
    caplog.set_level(logging.WARNING)
    assert presentation.result_reason(raw, family) == presentation._RESULT_REASON_MESSAGES[family][raw].text
    assert "Suppressed untrusted diagnostic" not in caplog.text

@pytest.mark.parametrize("family", ["torsion", "combined"])
@pytest.mark.parametrize("payload", [None, {}, {"valid": True, "status": "PASS", "user_id": "<script>"}])
def test_missing_currentness_evidence_remains_rejected_with_known_explanation(family, payload, caplog):
    before = copy.deepcopy(payload)
    if family == "torsion":
        valid, reason = presentation.torsion_publication_evidence_is_current({}, None, payload)
    else:
        valid, reason = presentation.combined_publication_evidence_is_current({}, payload)
    assert valid is False
    assert payload == before
    caplog.set_level(logging.WARNING)
    text = presentation.result_reason(reason, family)
    assert text == presentation._RESULT_REASON_MESSAGES[family][reason].text
    assert "Calculate the current inputs again." in text
    assert "Suppressed untrusted diagnostic" not in caplog.text
    assert presentation.result_reason(reason + " <script>", family) == presentation._RESULT_REASON_FALLBACKS[family].text
    assert "Suppressed untrusted diagnostic" in caplog.text
