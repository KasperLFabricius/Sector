"""Headless smoke tests for the Streamlit app via Streamlit's AppTest.

These run the app script in-process (no browser), exercise the Calculate flow
for each analysis mode, and assert it produces results without error.
"""

from __future__ import annotations

import pathlib

import pytest

from streamlit.testing.v1 import AppTest

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app" / "sector_app.py")


def _fresh():
    return AppTest.from_file(APP, default_timeout=90)


def test_app_loads_without_error():
    at = _fresh()
    at.run()
    assert not at.exception
    # Before any calculation the app prompts the user.
    assert "results" not in at.session_state


def test_calculate_plastic_produces_an_envelope():
    at = _fresh()
    at.run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res
    assert len(res["plastic"]["mx"]) > 0
    assert res["plastic"]["max_mx"] > 0  # a rectangle with bottom steel has +Mx capacity


def test_calculate_elastic_produces_bar_stresses():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "elastic" in res
    assert len(res["elastic"]["bar_stress"]) > 0


def test_both_mode_runs_elastic_and_plastic():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res and "elastic" in res


def test_circular_shape_calculates():
    at = _fresh()
    at.run()
    at.selectbox(key="shape").set_value("Circular").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_material_preset_switch_calculates():
    at = _fresh()
    at.run()
    at.selectbox(key="conc_preset").set_value("DS/EN 1992-1-1:2023").run()
    at.selectbox(key="mild_preset").set_value(
        "Curve 2 (elastic-perfectly-plastic)").run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_2023_concrete_fck_edit_calculates():
    # Editing fck under the strength-dependent 2023 preset (alpha_cc tracks fck).
    at = _fresh()
    at.run()
    at.selectbox(key="conc_preset").set_value("DS/EN 1992-1-1:2023").run()
    at.number_input(key="conc_fck").set_value(50.0).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_es_field_present_and_editable():
    # The steel modulus Es/Ep is a direct input for both materials (the prestress
    # panel appears once tendons are enabled).
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    keys = {ni.key for ni in at.number_input}
    assert "mild_Es" in keys and "pre_Es" in keys
    at.number_input(key="mild_Es").set_value(210000.0).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_eut_below_yield_strain_warns_and_calculates():
    # Meaningful constraint: a rupture strain below the yield strain is clamped
    # with a warning rather than accepted.
    at = _fresh()
    at.run()
    at.number_input(key="mild_eut").set_value(0.0005).run()  # below ey ~ 0.0025
    assert any("yield strain" in w.value for w in at.warning)
    at.button(key="calculate").click().run()
    assert not at.exception


def test_two_yield_fields_live_under_default_preset():
    # The default preset builds the general law, so editing a two-yield field
    # (k) is accepted and recomputes without error.
    at = _fresh()
    at.run()
    at.number_input(key="mild_k").set_value(0.8).run()
    at.number_input(key="mild_ey0t").set_value(0.003).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception


def test_mild_fyck_zero_is_allowed_and_calculates():
    # The old 100 MPa floor on fyck is gone; zero compression yield must be a
    # valid input and still compute.
    at = _fresh()
    at.run()
    at.number_input(key="mild_fyck").set_value(0.0).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_material_fields_are_flat_regardless_of_preset():
    # Every mild-steel field is shown for any preset (flat form): the two-yield
    # fields exist even under the elastic-perfectly-plastic (curve 2) preset.
    at = _fresh()
    at.run()
    at.selectbox(key="mild_preset").set_value(
        "Curve 2 (elastic-perfectly-plastic)").run()
    keys = {ni.key for ni in at.number_input}
    for f in ("mild_fytk", "mild_fyck", "mild_futk", "mild_eut", "mild_gamma_y",
              "mild_gamma_u", "mild_gamma_E", "mild_k", "mild_ey0t", "mild_ey0c"):
        assert f in keys, f


def test_degenerate_rupture_stress_does_not_crash():
    # A zero rupture stress on a hardening curve is degenerate; the app must warn
    # and still render rather than raise.
    at = _fresh()
    at.run()
    at.selectbox(key="mild_preset").set_value("Curve 1 (bilinear hardening)").run()
    at.number_input(key="mild_futk").set_value(0.0).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception


def test_view_dropdown_switches_without_error():
    # Every view must render. The live views (Section, Stress-Strain) need no
    # Calculate; the result views show a prompt until one is run.
    at = _fresh()
    at.run()
    for v in ["Section", "Stress-Strain diagrams", "Plastic Results",
              "Elastic Results"]:
        at.selectbox(key="view").set_value(v).run()
        assert not at.exception, v


def test_stress_strain_view_includes_prestress_when_enabled():
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.selectbox(key="view").set_value("Stress-Strain diagrams").run()
    assert not at.exception


def test_results_views_render_after_calculate():
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Both").run()
    at.button(key="calculate").click().run()
    for v in ["Plastic Results", "Elastic Results"]:
        at.selectbox(key="view").set_value(v).run()
        assert not at.exception, v


def test_section_view_warns_and_hides_stale_neutral_axis():
    # Run elastic (draws a neutral axis), then change a dimension and stay on
    # the Section view: the cached axis must be hidden with a stale warning.
    at = _fresh()
    at.run()
    at.radio(key="mode").set_value("Elastic").run()
    at.button(key="calculate").click().run()
    at.selectbox(key="view").set_value("Section").run()
    assert not at.exception
    assert not at.warning  # fresh results -> no stale notice

    at.number_input(key="h").set_value(0.75).run()  # geometry now differs
    assert not at.exception
    assert any("neutral axis is hidden" in w.value for w in at.warning)


def test_prestress_plastic_increases_capacity():
    # Enabling tendons in the tension zone must raise the plastic +Mx capacity.
    base = _fresh()
    base.run()
    base.button(key="calculate").click().run()
    assert not base.exception
    mx0 = base.session_state["results"]["plastic"]["max_mx"]

    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    assert "plastic" in res
    assert res["plastic"]["max_mx"] > mx0


def test_prestress_both_modes_run_with_tendons():
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.radio(key="mode").set_value("Both").run()
    at.button(key="calculate").click().run()
    assert not at.exception
    res = at.session_state["results"]
    # Elastic models each tendon as an extra bar, so its stress list grows.
    assert "plastic" in res and "elastic" in res
    assert len(res["elastic"]["bar_stress"]) > 0


def test_prestress_preset_curve6_calculates():
    at = _fresh()
    at.run()
    at.checkbox(key="use_pre").set_value(True).run()
    at.selectbox(key="pre_preset").set_value("Curve 6 (bilinear)").run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]


def test_material_manual_override_calculates():
    at = _fresh()
    at.run()
    # A picked preset must remain editable.
    at.number_input(key="conc_fck").set_value(45.0).run()
    at.number_input(key="mild_gamma_y").set_value(1.3).run()
    assert not at.exception
    at.button(key="calculate").click().run()
    assert not at.exception
    assert "plastic" in at.session_state["results"]
