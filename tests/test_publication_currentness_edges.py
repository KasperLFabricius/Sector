"""Current native zero-capacity failures remain failed without accepting stale evidence."""
from __future__ import annotations

import copy
import math
import pickle

import pytest

import case_analysis
import result_presentation as presentation
from sector import capacity
from tools import report_render_fixture

pytestmark = pytest.mark.xdist_group("zero-capacity-publication")


@pytest.fixture(scope="module")
def zero_capacity_member():
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    inp = case_analysis.plastic_case_input(inp, inp["plastic_cases"][0])
    assert presentation.combined_publication_evidence_is_current(inp, out) == (True, None)
    assert presentation.directional_shear_publication_evidence_is_current(
        inp, out["shear"], plastic_result=out["plastic"],
    ) == (True, None)
    candidates = out["shear"]["links"]["chord_candidates"]
    candidate = next(item for item in candidates if item["m_rd"] == 0.0)
    assert candidate["conditional"] is True
    assert candidate["m_total"] > 0.0 and candidate["util"] == math.inf
    assert candidate["status"] == "FAIL" and candidate["ok"] is False
    return inp, out, candidate


def test_infinite_publication_value_requires_complete_zero_capacity_failure(zero_capacity_member):
    _inp, _out, candidate = zero_capacity_member
    assert presentation._publication_mapping_contains_current(candidate, candidate)
    for changes in (
        {"m_rd": 1.0}, {"m_total": 0.0}, {"ftd_t": math.inf},
        {"util": -math.inf}, {"util": math.nan}, {"status": "PASS"},
        {"ok": True}, {"conditional": False}, {"valid": False},
        {"ftd_t": candidate["ftd_t"] + 1.0},
    ):
        altered = dict(candidate, **changes)
        assert not presentation._publication_mapping_contains_current(altered, altered), changes
    assert not presentation._publication_mapping_contains_current(
        {"util": math.inf, "status": "FAIL", "ok": False},
        {"util": math.inf, "status": "FAIL", "ok": False},
    )
    for value in (math.inf, -math.inf, math.nan):
        assert not presentation._publication_mapping_contains_current({"m_rd": value}, {"m_rd": value})


@pytest.mark.parametrize("reconstruction", ((1.0, True), (0.0, False)))
def test_synchronized_zero_capacity_failure_requires_current_solver_reconstruction(
    zero_capacity_member, reconstruction, monkeypatch,
):
    inp, out, candidate = copy.deepcopy(zero_capacity_member)
    before = pickle.dumps((inp, out))
    original = capacity.conditional_capacity
    calls = []

    def changed_current_capacity(section, concrete, steel, n_ed, axis, tension_low, m_off, **kwargs):
        if ((axis, tension_low) == (candidate["axis"], candidate["tension_low"])
                and m_off == candidate["m_off"]):
            calls.append((axis, tension_low, m_off))
            return reconstruction
        return original(section, concrete, steel, n_ed, axis, tension_low, m_off, **kwargs)

    monkeypatch.setattr(capacity, "conditional_capacity", changed_current_capacity)
    assert presentation.combined_publication_evidence_is_current(inp, out)[0] is False
    assert presentation.directional_shear_publication_evidence_is_current(
        inp, out["shear"], plastic_result=out["plastic"],
    )[0] is False
    assert calls
    assert pickle.dumps((inp, out)) == before


@pytest.mark.parametrize("target", (
    "combined-face-nan", "combined-domain-nan", "shear-face-inf", "torsion-domain-inf",
))
def test_infinite_combined_failure_does_not_relax_other_face_metrics(zero_capacity_member, target):
    inp, out, _candidate = copy.deepcopy(zero_capacity_member)
    shear = out["shear"]
    if target == "combined-face-nan":
        shear["face_candidates"][0]["combined_metric"] = math.nan
    elif target == "combined-domain-nan":
        shear["governing_domains"]["combined"]["util"] = math.nan
    elif target == "shear-face-inf":
        shear["face_candidates"][0]["shear_metric"] = math.inf
    else:
        shear["governing_domains"]["vt"]["util"] = math.inf
    before = pickle.dumps((inp, out))
    assert presentation.directional_shear_publication_evidence_is_current(
        inp, shear, plastic_result=out["plastic"],
    )[0] is False
    assert pickle.dumps((inp, out)) == before
