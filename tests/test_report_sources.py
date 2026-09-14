"""Publication reference scope and completeness, without engineering authority."""

import copy
import io
import pathlib
import sys

import pandas as pd
import pypdf
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from app import report_sources as sources
import sector_report as report


def entry(scope="Elastic", name="EL-1", document="QA & <record>", locator="Section 2, p. 7"):
    return dict(scope=scope, case_name=name, document=document, locator=locator)


@pytest.mark.parametrize("invalid", [None, {}, "[]", [None], [{}],
    [entry() | {"extra": "x"}], [entry(locator=None)],
    [entry(scope="Unknown")], [entry(scope="Project")],
    [entry(name="")], [entry(), entry()],
])
def test_reference_register_is_strict(invalid):
    with pytest.raises(ValueError):
        sources.validate(invalid)


def test_reference_completeness_is_not_verification_and_assignment_is_exact():
    original = [entry(), entry(name="el-1", locator="")]
    frozen = copy.deepcopy(original)
    assert sources.reference_status(original[0]) == "User-supplied reference"
    assert "section/page locator not supplied" in sources.reference_status(original[1])
    changed = sources.replace_entry(original, "Elastic", "EL-1", "New", "p. 8")
    assert changed[1] == original[1]
    assert original == frozen
    assert sources.signature(changed) != sources.signature(original)
    assert sources.replace_entry(changed, "Elastic", "EL-1", "", "") == [original[1]]


def test_reference_identity_remains_available_with_malformed_numeric_actions():
    inp = {
        "elastic_cases": pd.DataFrame([{"name": "EL-1", "n_long_ed_kn": "unfinished"}]),
        "plastic_cases": [{"name": "PL-1", "mx_ed_knm": "bad"}],
        "fatigue_spectrum_base": pd.DataFrame([
            {"spectrum": "S-1", "cycles": "bad"}, {"spectrum": "S-1", "cycles": None},
        ]),
    }
    assert sources.available_assignments(inp) == [
        ("Project", ""), ("Plastic", "PL-1"), ("Elastic", "EL-1"), ("Fatigue", "S-1"),
    ]


def test_result_only_reference_resolves_and_preserves_literal_source():
    buffer = io.BytesIO()
    builder = report.ReportBuilder(buffer, {"source_register": [entry()]},
        {"elastic_case": {"id": "EL-1", "type": "Original description", "source": "QA register"}},
        {}, figures=False, profile="Standard")
    builder._h1("Selected result")
    builder._case_line("elastic")
    builder._p("Stress = -20 MPa")
    builder._write_pdf()
    pdf = pypdf.PdfReader(buffer)
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "QA & <record>" in text and "Section 2, p. 7" in text
    assert "Original description" in text and "QA register" in text
    assert text.count("QA & <record>") == 1
    assert builder._project_sources_emitted
    assert "Stress = -20 MPa" in text


def test_standard_adjacent_groups_retain_rows_and_stop_at_source_or_prose():
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=False, profile="Standard")
    builder._h1("Results")
    builder._standard_result_projection("a", "R", "100 kN", "Source A", None, "R")
    builder._standard_result_projection("b", "u", "80%", "Source A", None, "u")
    assert len(builder._standard_projection_group["rows"]) == 2
    assert builder._standard_projection_group["item"].number == "1.1"
    builder._standard_result_projection("c", "d", "500 mm", "Source B", "Face x+", "d")
    assert len(builder._standard_projection_group["rows"]) == 1
    assert builder._standard_projection_group["item"].number == "1.2"
    builder._p("Separate assessment")
    builder._standard_result_projection("d", "z", "450 mm", "Source B", None, "z")
    assert builder._standard_projection_group["item"].number == "1.3"
    builder._write_pdf()
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(builder.buffer).pages)
    assert all(value in text for value in ("100 kN", "80%", "500 mm", "450 mm", "Face x+"))
