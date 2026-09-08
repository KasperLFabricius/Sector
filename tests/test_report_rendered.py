"""Rendered-artifact regression tests for the issued Sector PDF."""

from __future__ import annotations

import copy
import io

import pypdf
import pytest

from tools.report_render_fixture import (
    _EXPECTED_PLASTIC_WORKED_HEADING,
    _inputs,
    _results,
    build_fixture_pdf,
    detect_sparse_report_pages,
    render_pdf,
    validate_equation_source_colocation,
    validate_fixture_engineering,
    validate_outline_destinations,
    validate_pdf_content,
    validate_rendered_pages,
    validate_results_overview_pagination,
    validate_worked_example_text,
)

import result_presentation
import case_analysis
import load_cases


def test_outline_validation_accepts_a_visible_heading_wrapped_by_pdf_layout(
    tmp_path,
):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "wrapped-outline.pdf"
    title = "11. Governing shear + torsion concrete-strut interaction - PL-QA-1"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.bookmarkPage("wrapped")
    pdf.addOutlineEntry(title, "wrapped", level=0)
    pdf.drawString(72, 760, "11. Governing shear + torsion concrete-strut")
    pdf.drawString(72, 740, "interaction - PL-QA-1")
    pdf.save()

    reader = pypdf.PdfReader(str(path))
    assert validate_outline_destinations(reader) == [(title, 1)]


def test_outline_validation_still_rejects_a_destination_on_the_wrong_page(
    tmp_path,
):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path = tmp_path / "wrong-outline-page.pdf"
    title = "11. Governing shear + torsion concrete-strut interaction - PL-QA-1"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.bookmarkPage("wrong")
    pdf.addOutlineEntry(title, "wrong", level=0)
    pdf.drawString(72, 760, "Unrelated preceding page")
    pdf.showPage()
    pdf.drawString(72, 760, "11. Governing shear + torsion concrete-strut")
    pdf.drawString(72, 740, "interaction - PL-QA-1")
    pdf.save()

    with pytest.raises(
        AssertionError, match="outline destination misses its heading"
    ):
        validate_outline_destinations(pypdf.PdfReader(str(path)))


def test_reference_fixture_engineering_is_internally_consistent():
    inp = _inputs()
    out = _results(inp)
    validate_fixture_engineering(inp, out)
    for entry, actions in zip(out["elastic_cases"], inp["elastic_cases"]):
        assert entry["actions"] == actions
        assert entry["evaluated"] is True and entry["reused"] is False
        assert entry["signature"] == case_analysis.case_signature(
            actions, load_cases.ELASTIC_TABLE_KEY, inp,
        )
    first, second = [entry["results"]["elastic"] for entry in out["elastic_cases"]]
    assert second["max_steel"] > first["max_steel"]
    assert second["max_conc"] > first["max_conc"]
    assert second["lambda_cr"] < first["lambda_cr"]
    selection = result_presentation.worked_example_selection(inp, out)
    assert selection["families"]["elastic"]["case_id"] == "EL-QA-2"
    assert selection["cracking_threshold"] == {"case_id": "EL-QA-2"}
    assert selection["crack_examples"] == [
        {"case_id": "EL-QA-1", "system": "fine", "branch": "crack_short",
         "label": "short-term (fine)"},
        {"case_id": "EL-QA-1", "system": "coarse", "branch": "crack_short_coarse",
         "label": "short-term (coarse)"},
    ]
    assert first["crack_short"]["wk"] > first["crack"]["wk"]
    assert first["crack_short_coarse"]["wk"] > first["crack_coarse"]["wk"]
    assert first["crack_output"]["short_term"]["ratio"] > first["crack_output"]["long_term"]["ratio"]
    assert selection["crack_comparison"] == {"case_id": "EL-QA-1", "duration": "short_term"}
    assert inp["elastic_cases"][1]["calculate_crack_width"] is False
    assert second["show_cw"] is False
    assert all(second.get(key) is None for key in ("crack", "crack_short", "crack_coarse", "crack_short_coarse"))
    for duration in ("long_term", "short_term"):
        output = second["crack_output"][duration]
        assert output["calculation_state"] == "NOT REQUESTED"
        assert output["value"] is None and output["ratio"] is None
        assert output["governing"] is None and output["case"] is None
    rows = result_presentation.multi_case_summary_rows(inp, out)
    selected = result_presentation.governing_summary_rows(rows)
    assert not result_presentation.governing_information_rows(selected)
    output_checks = {"Concrete stress", "Reinforcement stress", "Cracking threshold/state"}
    governing_outputs = [row for row in selected if row["check"] in output_checks]
    assert len(governing_outputs) == 3
    assert {row["case"] for row in governing_outputs} == {"EL-QA-2"}
    assert all(row["status"] == "CALCULATED" and row["util"] is None
               and row["criterion"] == "Output only" for row in governing_outputs)
    complement = result_presentation.non_governing_summary_rows(rows)
    assert {row["case"] for row in complement if row["check"] in output_checks} == {"EL-QA-1"}
    # Both Elastic cases inherit the global detailing toggles. They must not
    # create extra Plastic NOT RUN rows or repeat the section-wide spacing check.
    assert len(out["elastic_cases"]) == 2
    assert [row["case"] for row in rows if row["check"] == "Concrete stress"] == [
        "EL-QA-1", "EL-QA-2",
    ]
    assert inp["minimum_reinforcement_on"] is True
    assert inp["clear_spacing_on"] is True
    assert [
        (row["case"], row["status"]) for row in rows
        if row.get("overview_key") == "minimum_reinforcement"
    ] == [("PL-QA-1", "PASS")]
    assert [
        (row["case"], row["status"]) for row in rows
        if row.get("overview_key") == "clear_spacing"
    ] == [("-", "PASS")]


def test_reference_fixture_rejects_inconsistent_native_plastic_operands():
    inp = _inputs()
    out = _results(inp)
    validate_fixture_engineering(inp, out)
    for field, value in (
        ("util", 1.25),
        ("applied", (80.0, 0.0)),
        ("util_demand", 80.0),
        ("util_resistance", 100.0),
    ):
        changed = copy.deepcopy(out)
        changed["plastic_cases"][1]["results"]["plastic"][field] = value
        with pytest.raises(AssertionError, match="inconsistent fixture plastic"):
            validate_fixture_engineering(inp, changed)


def test_reference_fixture_uses_independent_duration_crack_width_criteria():
    inp = _inputs()
    elastic_cases = inp["elastic_cases"]

    assert inp["sls_long_term_permitted_crack_width_mm"] == pytest.approx(0.20)
    assert inp["sls_short_term_permitted_crack_width_mm"] == pytest.approx(0.20)
    assert inp["sls_heightened_permitted_crack_width_mm"] == pytest.approx(0.20)
    assert all(
        "ordinary_crack_criterion_mm" not in case for case in elastic_cases
    )
    output = _results(inp)["elastic_cases"][0]["results"]["elastic"][
        "crack_output"
    ]
    assert set(output) == {"long_term", "short_term"}
    for duration in ("long_term", "short_term"):
        assert output[duration]["duration"] == duration
        assert output[duration]["criterion_mm"] == pytest.approx(0.20)
        assert output[duration]["criterion_source"] == (
            f"User input - Analysis settings - {duration.replace('_', '-')}"
        )


def test_native_fixture_rejects_elastic_case_stress_and_contributor_mismatches():
    inp = _inputs()
    out = _results(inp)
    paths_and_values = (
        (("elastic_cases", 1, "results", "elastic", "accepted_states", "long_term", "equilibrium", "target", "mx"), -80.0),
        (("elastic_cases", 1, "results", "elastic", "elements", 0, "total_mpa"), 245.0),
        (("elastic_cases", 1, "results", "elastic", "elements", 0, "dif_mpa"), 30.0),
        (("elastic_cases", 1, "results", "elastic", "max_conc"), 12.0),
        (("elastic_cases", 1, "results", "elastic", "max_conc_point"), 1),
        (("elastic_cases", 1, "results", "elastic", "superposition", "neutralising_resultant", "n"), 29.797979798),
        (("heightened_crack_control", "contributions", 0, "area_mm2"), 500.0),
        (("heightened_crack_control", "bar_diameter_mm"), 25.23),
        (("elastic_cases", 0, "results", "elastic", "crack_short", "governing_candidate", "mean_strain_operands", "sigma_s"), 150.0),
        (("elastic_cases", 0, "results", "elastic", "crack_short_coarse", "governing_candidate", "spacing_operands", "selected_spacing"), 235.0),
        (("elastic_cases", 0, "results", "elastic", "crack_short", "candidates", 1, "sigma_s"), 150.0),
        (("elastic_shared", "creep_coefficient"), 0.0),
        (("elastic_shared", "materials", 0, "short_term"), 6.0),
        (("elastic_cases", 1, "results", "elastic", "superposition", "long_term_modular_ratio"), 15.0),
    )
    for path, value in paths_and_values:
        changed = copy.deepcopy(out)
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(AssertionError, match="inconsistent fixture"):
            validate_fixture_engineering(inp, changed)
    for key, value in (("ns", 6.0), ("nl", 15.0), ("el_phi", 0.0)):
        changed_input = copy.deepcopy(inp)
        changed_input[key] = value
        with pytest.raises(AssertionError, match="inconsistent fixture input"):
            validate_fixture_engineering(changed_input, out)
    changed = copy.deepcopy(out)
    changed["elastic_cases"][0]["results"]["elastic"]["crack_short"]["candidates"].pop()
    with pytest.raises(AssertionError, match="crack candidate inventory"):
        validate_fixture_engineering(inp, changed)


def test_reference_fixture_retains_governing_worked_chains_without_figures():
    """Check the textbook payload and PDF text without launching a browser."""
    pdf = build_fixture_pdf(figures=False)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(page_texts)
    validate_worked_example_text(text)
    for heading in (
        "Elastic section response and stresses - EL-QA-2",
        "Cracking threshold - EL-QA-2",
        "Governing crack width - EL-QA-1",
        "Crack width worked - governing case (short-term (fine))",
        "Crack width worked - governing case (short-term (coarse))",
        "User-specified crack-width comparison - critical short-term case",
    ):
        assert heading in " ".join(text.split())
    assert "governing crack width - el-qa-2" not in " ".join(text.split()).casefold()
    assert "Candidate summary for governing crack example" in text
    heading_pages = [
        page_text
        for page_text in page_texts
        if (
            _EXPECTED_PLASTIC_WORKED_HEADING in page_text
            and "NA intercepts" in page_text
        )
    ]
    assert len(heading_pages) == 1
    concrete_pages = [
        page_text
        for page_text in page_texts
        if "Characteristic strength" in page_text
    ]
    assert len(concrete_pages) == 1
    assert "EQ-" not in concrete_pages[0]
    assert "= 20 MPa" in concrete_pages[0]
    assert validate_results_overview_pagination(page_texts)

    validate_equation_source_colocation(page_texts)


def test_audit_fixture_has_no_sparse_non_opener_pages():
    pdf = build_fixture_pdf(figures=False, profile="Audit")
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    opener_pages = {
        reader.get_destination_page_number(item) + 1
        for item in reader.outline
        if not isinstance(item, list)
    }
    sparse = detect_sparse_report_pages(
        render_pdf(pdf),
        page_texts,
        opener_pages=opener_pages,
    )
    assert sparse == ()
    assert all("EQ-" not in text for text in page_texts)


def test_worked_example_text_rejects_any_unavailable_placeholder():
    with pytest.raises(AssertionError, match="unavailable worked-example"):
        validate_worked_example_text(
            "Worked plastic calculation\n"
            "The completed retained operands are unavailable"
        )


def test_equation_source_colocation_rejects_a_page_split():
    with pytest.raises(AssertionError, match="equation/source page split"):
        validate_equation_source_colocation(
            [
                (
                    "Equation (1.1)\n"
                ),
                (
                    "Source / method note: retained source moved to another page\n"
                ),
            ],
            expected_equation_count=1,
        )


@pytest.mark.real_image_export
@pytest.mark.xdist_group(name="publication-real-figures")
def test_issued_report_renders_every_page_and_retains_expected_content():
    """Exercise the issued artifact once so Kaleido is never run concurrently.

    The full CI gate uses pytest-xdist.  Keeping rendering and content checks in
    separate tests allowed two workers to start independent headless-browser
    servers at the same time, intermittently exhausting the first export's
    timeout even though the subsequent standalone render succeeded.
    """
    pdf = build_fixture_pdf()
    validate_pdf_content(pdf)
    pages = render_pdf(pdf)
    validate_rendered_pages(pages, require_document_control=True)
