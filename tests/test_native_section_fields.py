"""Native currentness and report integration for retained section maps."""
from __future__ import annotations

import copy

import pytest
from test_app_smoke import _calculate, _fresh, _set_and_click


@pytest.mark.parametrize("family", ["plastic", "elastic"])
def test_pre_map_cache_is_recalculated_and_acquires_field_evidence(family):
    import case_analysis
    import section_fields
    import sector_app

    at = _fresh().run()
    _set_and_click(at, "calculate", ("radio", "mode", "Both"))
    assert not at.exception
    results = at.session_state["results"]
    original = results[family]
    other = "elastic" if family == "plastic" else "plastic"
    unchanged = results[other]
    payloads = original["points"] if family == "plastic" else [original]
    for payload in payloads:
        payload.pop("field_context")
    token = getattr(sector_app, f"_{family.upper()}_RESULT_CONTRACT_TOKEN")
    legacy_token = tuple(part for part in token if part != "section-fields-v1")
    signature_keys = ["result_sig", f"result_{family}_sig", f"result_{family}_case_context_sig"]
    if family == "plastic":
        signature_keys.append("result_plastic_bending_context_sig")
    for key in signature_keys:
        at.session_state[key] = tuple(legacy_token if item == token else item
                                      for item in at.session_state[key])
    _calculate(at)
    assert not at.exception
    refreshed = at.session_state["results"]
    assert refreshed[family] is not original
    assert refreshed[other] is unchanged
    assert refreshed[f"{family}_cases"][0]["reused"] is False
    entry = refreshed[f"{family}_cases"][0]
    inp = getattr(case_analysis, f"{family}_case_input")(
        copy.deepcopy(at.session_state["result_input_snapshot"]), entry["actions"])
    result = entry["results"][family]
    kwargs = {"point_index": result["worked_point_index"]} if family == "plastic" else {}
    field, maps = section_fields.field_pair(inp, result, family=family.title(), **kwargs)
    assert field.elements
    assert len(maps) == 2


@pytest.fixture(scope="module")
def native_report_fields():
    import result_presentation

    from tools.report_render_fixture import _inputs, _results

    inp = _inputs()
    out = _results(inp)
    out["worked_example_selection"] = result_presentation.worked_example_selection(inp, out)
    return inp, out


@pytest.mark.parametrize("profile", ["Standard", "Audit", "Brief"])
def test_report_profiles_publish_each_current_case_map_with_native_values(
    profile, native_report_fields, monkeypatch,
):
    import case_analysis
    import section_fields
    import sector_report

    inp, out = copy.deepcopy(native_report_fields)
    expected = []
    for family in ("plastic", "elastic"):
        entries = out[f"{family}_cases"]
        assert len(entries) == 2
        for entry in entries:
            case_inp = getattr(case_analysis, f"{family}_case_input")(inp, entry["actions"])
            result = entry["results"][family]
            options = {"point_index": result["worked_point_index"]} if family == "plastic" else {}
            _, figures = section_fields.field_pair(case_inp, result, family=family.title(), **options)
            expected.extend(figure.to_json() for _, figure in figures)

    captured = []
    warmup_calls = []

    def capture_warmup():
        warmup_calls.append(True)

    def unexpected_worker():
        raise AssertionError("Map-capture test started a real image worker")

    def capture(self, figure, *args, **kwargs):
        if any(trace.name == "Concrete display band" for trace in figure.data):
            assert "<" not in kwargs["caption"]
            captured.append(figure.to_json())
    monkeypatch.setattr(sector_report.ReportBuilder, "_fig", capture)
    monkeypatch.setattr(sector_report, "ensure_image_server", capture_warmup)
    monkeypatch.setattr(
        sector_report.publication_image_export._COORDINATOR,
        "_worker_launcher",
        unexpected_worker,
    )
    pdf = sector_report.build_report({}, inp, out, profile=profile, figures=True)
    assert pdf.startswith(b"%PDF")
    assert warmup_calls == [True]
    assert sorted(captured) == (sorted(expected) if profile != "Brief" else [])


def test_figures_off_never_evaluates_a_section_map(native_report_fields, monkeypatch):
    import section_fields
    import sector_report

    def unexpected(*args, **kwargs):
        raise AssertionError("Figures-off report evaluated a section map")
    monkeypatch.setattr(section_fields, "field_pair", unexpected)
    inp, out = copy.deepcopy(native_report_fields)
    pdf = sector_report.build_report({}, inp, out, profile="Standard", figures=False)
    assert pdf.startswith(b"%PDF")
