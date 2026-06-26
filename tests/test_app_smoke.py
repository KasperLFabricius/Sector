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
