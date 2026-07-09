"""Tests for the combined bending + shear + torsion (M-V-T) interaction checks."""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

from sector import codes, combined

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
APP = str(ROOT / "app" / "sector_app.py")


# -- engine -----------------------------------------------------------------

def test_ratio_helper():
    assert combined.ratio(1.0, 2.0) == pytest.approx(0.5)
    assert combined.ratio(0.0, 0.0) == 0.0
    assert math.isinf(combined.ratio(1.0, 0.0))


def test_crushing_interaction():
    assert combined.crushing_interaction(40.0, 80.0, 150.0, 600.0) == pytest.approx(0.75)
    assert math.isinf(combined.crushing_interaction(1.0, 0.0, 0.0, 1.0))


def test_dkna_sum_summed_vs_independent():
    assert combined.dkna_sum(0.3, 0.4, 0.2, m_v_independent=False) == pytest.approx(0.9)
    # independent -> max(M+T, V+T) = max(0.5, 0.6) = 0.6
    assert combined.dkna_sum(0.3, 0.4, 0.2, m_v_independent=True) == pytest.approx(0.6)


# -- app integration (AppTest) ----------------------------------------------

def _fresh():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(APP, default_timeout=90)


def _enable_all(at, mv_independent=False):
    at.number_input(key="pl_Mx").set_value(100.0).run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="shear_links").set_value(True).run()
    at.number_input(key="shear_V").set_value(150.0).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.number_input(key="torsion_T").set_value(40.0).run()
    at.checkbox(key="combined_on").set_value(True).run()
    if mv_independent:
        at.checkbox(key="combined_mv_independent").set_value(True).run()
    at.button(key="calculate").click().run()
    return at


def test_app_combined_assembles_all_three():
    at = _fresh()
    at.run()
    _enable_all(at)
    assert not at.exception
    c = at.session_state["results"]["combined"]
    assert c["valid"]
    assert c["dkna_sum"] == pytest.approx(c["r_m"] + c["r_v"] + c["r_t"])
    assert c["crushing"] is not None            # shear links present -> crushing check
    assert c["asl_torsion"] > 0.0


def test_app_combined_mv_independent_uses_max():
    at = _fresh()
    at.run()
    _enable_all(at, mv_independent=True)
    c = at.session_state["results"]["combined"]
    assert c["dkna_sum"] == pytest.approx(max(c["r_m"] + c["r_t"], c["r_v"] + c["r_t"]))


def test_app_combined_edition_lock():
    at = _fresh()
    at.run()
    at.checkbox(key="shear_on").set_value(True).run()
    at.checkbox(key="torsion_on").set_value(True).run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.selectbox(key="combined_method").set_value(codes.EC2_2005.label).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    # both checks follow the shared edition, and their own selectors are locked.
    assert res["shear"]["method"] == codes.EC2_2005.label
    assert res["torsion"]["method"] == codes.EC2_2005.label
    assert at.selectbox(key="shear_method").disabled
    assert at.selectbox(key="torsion_method").disabled


def test_app_combined_incomplete_flags_missing():
    at = _fresh()
    at.run()
    at.checkbox(key="combined_on").set_value(True).run()   # no shear / torsion
    at.button(key="calculate").click().run()
    assert not at.exception
    assert not at.session_state["results"]["combined"]["valid"]
    at.selectbox(key="view").set_value("M-V-T Interaction").run()
    assert any("needs all three" in w.value for w in at.warning)


def test_app_combined_view_renders():
    at = _fresh()
    at.run()
    _enable_all(at)
    at.selectbox(key="view").set_value("M-V-T Interaction").run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert any("Bending" in lbl for lbl in labels)
    assert any("SEd/SRd" in lbl for lbl in labels)


def test_app_combined_is_saved_and_restored():
    import project_io
    at = _fresh()
    at.run()
    at.checkbox(key="combined_on").set_value(True).run()
    at.selectbox(key="combined_method").set_value(codes.EC2_2005.label).run()
    scalars = {k: at.session_state[k] for k in project_io.SCALAR_KEYS
               if k in at.session_state}
    assert scalars["combined_on"] is True
    at2 = _fresh()
    at2.run()
    at2.session_state["_pending_project"] = project_io.dump_project({}, scalars)
    at2.run()
    assert not at2.exception
    assert at2.session_state["combined_on"] is True
    assert at2.session_state["combined_method"] == codes.EC2_2005.label
