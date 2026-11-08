"""MEd,max input of the 6.2.3(7) cap: blank values and the moment reference."""

from __future__ import annotations

import pytest

from sector import capacity, combined


def _inp(on, value):
    inp = {capacity.MED_MAX_ON_KEY: on}
    inp.update({key: value for key in capacity.MED_MAX_KEYS.values()})
    return inp


def test_zero_or_switch_off_means_not_entered():
    # A zero cap would remove the whole shear term at a zero-moment section.
    assert capacity.chord_med_max(_inp(True, 0.0), "x", True) is None
    assert capacity.chord_med_max(_inp(False, 150.0), "x", True) is None
    assert capacity.chord_med_max(_inp(True, 150.0), "y", False) == 150.0


def test_cap_moves_with_the_2023_moment_reference():
    # The 2023 chord moment is about the web centre: M = M_origin + s on the low
    # face and -M_origin - s on the high face. MEd,max moves by the same amount.
    assert capacity.chord_cap_in_reference(400.0, 50.0, True) == 450.0
    assert capacity.chord_cap_in_reference(400.0, 50.0, False) == 350.0
    assert capacity.chord_cap_in_reference(None, 50.0, True) is None


def test_shifted_reference_keeps_the_origin_verdict():
    # Review case: origin MEd = 250, MEd,max = 400, MRd = 360 kNm, |VEd| d = 190
    # kNm, shift s = +50 kNm. In the origin frame 250 + 150 = 400 > 360 (FAIL).
    # In the shifted frame 300 + 150 = 450 > 410 gives the same verdict.
    cap = capacity.chord_cap_in_reference(400.0, 50.0, True)
    check = combined.concrete_route_chord_check(300.0, 410.0, 190.0, 1.0, m_ed_max=cap)
    assert check["m_total"] == pytest.approx(450.0)
    assert check["status"] == "FAIL"
