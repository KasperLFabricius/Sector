"""Adversarial Standard/Audit depth contracts for Sector v0.96."""

from __future__ import annotations

import copy
import io
import pathlib
import pickle
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_presentation
import result_presentation as presentation
import sector_report

from tools import report_render_fixture


def _builder(profile: str):
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    out["worked_example_selection"] = presentation.worked_example_selection(
        inp, out
    )
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, inp, out, figures=False, profile=profile
    )


def _snapshot(value) -> bytes:
    return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)


def _capture(builder):
    headings = []
    tables = []
    equations = []
    builder._case_heading = lambda text, _family: headings.append(text)
    builder._h1 = lambda text, **_kwargs: headings.append(text)
    builder._h2 = lambda text, **_kwargs: headings.append(text)
    builder._table = (
        lambda rows, *_args, **_kwargs: tables.append(copy.deepcopy(rows))
    )
    builder._formula = lambda *_args, **kwargs: equations.append(
        kwargs.get("equation_key")
    )
    builder._fig = lambda *_args, **_kwargs: None
    builder._status_block = lambda *_args, **_kwargs: None
    builder._small = lambda *_args, **_kwargs: None
    builder._p = lambda *_args, **_kwargs: None
    builder._keep_from = lambda *_args, **_kwargs: None
    builder._keep_measured_calculation_from = lambda *_args, **_kwargs: None
    return headings, tables, equations


def _selected_plastic_builder(profile: str):
    builder = _builder(profile)
    selected = builder._selected_families["plastic"]["case_id"]
    case_inp, case_out = next(
        (case_inp, case_out)
        for case_inp, case_out in builder._case_contexts("plastic")
        if builder._case_id(case_inp, "plastic") == selected
    )
    builder.inp, builder.out = case_inp, case_out
    return builder


def test_profile_policy_names_governing_standard_and_exhaustive_audit_depth():
    standard = sector_report.report_profiles.STANDARD_PROFILE
    audit = sector_report.report_profiles.AUDIT_PROFILE

    assert standard.substitution_scope == "governing"
    assert "one governing worked calculation per active check family" in (
        standard.description
    )
    assert "exhaustive" in standard.omitted_detail
    for expected in ("candidates", "branches", "substitutions", "provenance"):
        assert expected in audit.description


def test_standard_omits_plastic_populations_but_keeps_selected_calculation():
    captured = {}
    payloads = {}
    for profile in ("Standard", "Audit"):
        builder = _selected_plastic_builder(profile)
        plastic = builder.out["plastic"]
        second_point = copy.deepcopy(plastic["points"][0])
        second_point.update({"V": 123.0, "Mx": 12.345, "My": 67.89})
        plastic["points"].append(second_point)
        plastic["mx"].append(second_point["Mx"])
        plastic["my"].append(second_point["My"])
        plastic["interaction"] = {
            "x": {
                "N": [0.0, -1234.5], "M": [100.0, 0.0],
                "applied": (0.0, 125.0), "converged": True,
            },
            "y": {
                "N": [0.0, -1234.5], "M": [100.0, 0.0],
                "applied": (0.0, 0.0), "converged": True,
            },
        }
        candidates = plastic["points"][0]["curvature_candidates"]
        non_governing = copy.deepcopy(candidates[0])
        non_governing.update({
            "mode": "bar_tension_rupture",
            "element_id": "R-NON-GOV",
            "curvature_per_m": 0.987654321,
            "selected": False,
        })
        candidates.append(non_governing)
        before = _snapshot(builder._base_out)
        headings, tables, equations = _capture(builder)

        builder._plastic()

        captured[profile] = (headings, tables, equations)
        payloads[profile] = (builder._base_out, before)

    standard_headings, standard_tables, standard_equations = captured["Standard"]
    audit_headings, audit_tables, audit_equations = captured["Audit"]
    audit_headers = [rows[0] for rows in audit_tables if rows]
    standard_headers = [rows[0] for rows in standard_tables if rows]

    for heading in (
        "Numerical N-M boundary",
        "Capacity over the neutral-axis sweep",
        "Ultimate-curvature candidates",
    ):
        assert heading not in standard_headings
        assert heading in audit_headings
    assert ["Candidate", "Element", "Strain limit", "Distance to NA",
            "Curvature", "Selected"] not in standard_headers
    assert ["Candidate", "Element", "Strain limit", "Distance to NA",
            "Curvature", "Selected"] in audit_headers
    for key in (
        "plastic.worked.curvature-candidate",
        "plastic.worked.curvature-selection",
        "plastic.worked.axial-equilibrium",
    ):
        assert key in standard_equations
        assert key in audit_equations
    assert all(_snapshot(current) == before for current, before in payloads.values())


def test_standard_names_the_retained_bar_governing_curvature_candidate():
    builder = _selected_plastic_builder("Standard")
    plastic = builder.out["plastic"]
    point = plastic["points"][plastic["worked_point_index"]]
    concrete = copy.deepcopy(point["curvature_candidates"][0])
    concrete["selected"] = False
    bar = copy.deepcopy(concrete)
    bar.update({
        "mode": "bar_tension_rupture",
        "element_index": 7,
        "element_id": "R-GOV-7",
        "strain_limit": 0.025,
        "distance_from_na_m": 0.5,
        "curvature_per_m": 0.05,
        "selected": True,
    })
    point["curvature_candidates"] = [concrete, bar]
    point["curvature_selection"] = {
        "mode": bar["mode"],
        "element_index": bar["element_index"],
        "curvature_per_m": bar["curvature_per_m"],
    }
    before = _snapshot(builder._base_out)
    _headings, _tables, equations = _capture(builder)
    notes = []
    builder._small = lambda text, **_kwargs: notes.append(text)

    builder._plastic_worked(plastic)

    assert any(
        "Selected candidate:" in note
        and "Bar tension rupture" in note
        and "element R-GOV-7" in note
        for note in notes
    )
    assert "plastic.worked.curvature-selection" in equations
    assert _snapshot(builder._base_out) == before


def test_curvature_selection_source_is_profile_neutral():
    references = []
    for profile in ("Standard", "Audit"):
        builder = _selected_plastic_builder(profile)
        _capture(builder)

        def capture_formula(*_args, **kwargs):
            if kwargs.get("equation_key") == (
                "plastic.worked.curvature-selection"
            ):
                references.append(kwargs.get("ref"))

        builder._formula = capture_formula
        builder._plastic_worked(builder.out["plastic"])

    assert references == [
        (
            "Sector governing-curvature minimum; the retained selected "
            "candidate identity is stated with the result."
        )
    ] * 2


def test_standard_clear_spacing_table_contains_only_the_retained_governing_pair():
    published = {}
    for profile in ("Standard", "Audit"):
        builder = _builder(profile)
        result = builder._base_out["clear_spacing"]
        result["pairs"].append({
            **copy.deepcopy(result["pairs"][0]),
            "first_id": "R-X",
            "second_id": "R-Y",
            "clear_mm": 999.0,
            "margin_mm": 973.77,
        })
        builder.inp, builder.out = builder._base_inp, builder._base_out
        before = _snapshot(builder._base_out)
        _headings, tables, _equations = _capture(builder)

        builder._clear_spacing()

        pair_table = next(rows for rows in tables if rows[0][0] == "Pair")
        published[profile] = pair_table
        assert _snapshot(builder._base_out) == before

    assert len(published["Standard"]) == 2
    assert published["Standard"][1][0] == "R1 - R2"
    assert [row[0] for row in published["Audit"][1:]] == [
        "R1 - R2",
        "R-X - R-Y",
    ]


def test_standard_fatigue_population_tables_keep_only_governing_element_and_fibre():
    published = {}
    for profile in ("Standard", "Audit"):
        builder = _builder(profile)
        before = _snapshot(builder._base_out)
        _headings, tables, _equations = _capture(builder)
        builder._fatigue_reinforcement_formulas = lambda *_args, **_kwargs: None
        builder._fatigue_concrete_formulas = lambda *_args, **_kwargs: None

        builder._fatigue()

        reinforcement = next(
            rows for rows in tables
            if rows and rows[0][:3] == ["Element", "Type", "Detail"]
        )
        screens = next(
            rows for rows in tables
            if rows and rows[0][:3] == ["Spectrum", "Element", "Status"]
        )
        concrete = next(
            rows for rows in tables
            if rows and rows[0][:4] == ["Fibre", "Source", "x", "y"]
        )
        published[profile] = (reinforcement, screens, concrete)
        assert _snapshot(builder._base_out) == before

    standard_reinforcement, standard_screens, standard_concrete = (
        published["Standard"]
    )
    audit_reinforcement, audit_screens, audit_concrete = published["Audit"]
    assert [row[0] for row in standard_reinforcement[1:]] == ["R1"]
    assert [row[0] for row in audit_reinforcement[1:]] == ["R1", "R2"]
    assert [row[1] for row in standard_screens[1:]] == ["R1"]
    assert [row[1] for row in audit_screens[1:]] == ["R1", "R2"]
    assert [row[0] for row in standard_concrete[1:]] == [2]
    assert [row[0] for row in audit_concrete[1:]] == [0, 1, 2, 3, 4]


def test_standard_miner_sums_keep_all_retained_bin_operands():
    builder = _builder("Standard")
    before = _snapshot(builder._base_out)
    _headings, tables, _equations = _capture(builder)
    formulas = {}

    def capture_formula(_expression, **kwargs):
        key = kwargs.get("equation_key")
        if key:
            formulas[key] = kwargs

    builder._formula = capture_formula
    builder._fatigue()

    payload = builder._base_out["fatigue"]
    reinforcement_selection = payload["governing_reinforcement_example"]
    concrete_selection = payload["governing_concrete_example"]
    spectra = fatigue_presentation.items(payload, "spectra")
    reinforcement_spectrum = next(
        spectrum for spectrum in spectra
        if fatigue_presentation.value(spectrum, "spectrum_name")
        == reinforcement_selection["spectrum_name"]
    )
    concrete_spectrum = next(
        spectrum for spectrum in spectra
        if fatigue_presentation.value(spectrum, "spectrum_name")
        == concrete_selection["spectrum_name"]
    )
    reinforcement_result = fatigue_presentation.result_by_element(
        reinforcement_spectrum,
        reinforcement_selection["element_id"],
    )
    concrete_result = fatigue_presentation.result_by_fibre(
        concrete_spectrum,
        concrete_selection["fibre_index"],
    )
    reinforcement_bins = fatigue_presentation.reinforcement_bin_rows(
        reinforcement_result
    )
    concrete_bins = fatigue_presentation.concrete_bin_rows(concrete_result)
    assert len(reinforcement_bins) > 1
    assert len(concrete_bins) > 1

    reinforcement_sum = formulas["fatigue.reinforcement.miner-sum"]
    assert reinforcement_sum["subst"] == " + ".join(
        sector_report._fmt_sig(row["damage"], 8)
        for row in reinforcement_bins
    )
    assert reinforcement_sum["result"] == (
        "D = "
        + sector_report._fmt_sig(
            fatigue_presentation.value(reinforcement_result, "damage"), 8
        )
    )
    concrete_sum = formulas["fatigue.concrete.miner-sum"]
    assert concrete_sum["subst"] == " + ".join(
        sector_report._fmt_sig(row["damage"], 8)
        for row in concrete_bins
    )
    assert concrete_sum["result"] == (
        "D = "
        + sector_report._fmt_sig(
            fatigue_presentation.value(concrete_result, "damage"), 8
        )
    )

    reinforcement_table = next(
        rows for rows in tables
        if rows and rows[0][:3] == ["Bin", "Cycles", "Status / range"]
    )
    concrete_table = next(
        rows for rows in tables
        if rows and rows[0][:4] == ["Bin", "Cycles", "Status", "Long comp."]
    )
    assert len(reinforcement_table) == 2
    assert len(concrete_table) == 2
    assert _snapshot(builder._base_out) == before


def test_existing_audit_only_solver_and_crack_candidate_ledgers_remain_separate():
    texts = {}
    for profile in ("Standard", "Audit"):
        pdf = report_render_fixture.build_fixture_pdf(
            figures=False, profile=profile
        )
        reader = report_render_fixture.pypdf.PdfReader(io.BytesIO(pdf))
        texts[profile] = " ".join(
            " ".join((page.extract_text() or "").split())
            for page in reader.pages
        )

    for heading in (
        "Candidate summary for governing crack example",
        "Elastic solver states",
    ):
        assert heading not in texts["Standard"]
        assert heading in texts["Audit"]
    for heading in (
        "Worked plastic calculation (utilisation direction)",
        "Governing reinforcement element - R1",
        "Governing concrete fibre - 2",
    ):
        assert heading in texts["Standard"]
        assert heading in texts["Audit"]


def test_fixture_retains_multiple_fatigue_candidates_for_depth_test():
    builder = _builder("Audit")
    spectrum = fatigue_presentation.items(
        builder._base_out["fatigue"], "spectra"
    )[0]
    assert [row["element_id"] for row in fatigue_presentation.reinforcement_rows(
        spectrum
    )] == ["R1", "R2"]
    assert [row["fibre_index"] for row in fatigue_presentation.concrete_rows(
        spectrum
    )] == [0, 1, 2, 3, 4]
