"""Only authored note boundaries and exact native symbols receive presentation."""

import io

import pytest
import sector_report as report
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate

from app import report_summary_notation as notation


@pytest.mark.parametrize(
    "literal",
    ["user; source", "fyk; <sub>x</sub>& u_k/8", "1e-9; fywk", "\u03c3; Source: PASS"],
)
def test_note_clauses_preserve_all_literal_characters(literal):
    value = notation.text("fyk {}; fywk {}; u_k/8", literal, literal)
    parts = notation.note_parts(value)
    assert len(parts) == 3
    assert "".join(parts) == value
    assert sum(str(p).count(literal) for p in parts) == 2
    assert notation.note_parts(literal) == (literal,)
    assert report._html_escape(value).count(report._html_escape(literal)) == 2


@pytest.mark.parametrize(
    "fragments",
    [[("clause", "user")], [("clause", "; ")], [("unknown", "changed; text")]],
)
def test_invalid_or_stale_note_boundaries_are_literal(fragments):
    value = notation.ReportText("changed; text", fragments)
    assert notation.note_parts(value) == (value,)


@pytest.mark.parametrize(
    "plain",
    [
        "Ordinary reinforcement is assumed anchored to develop the entered fyk; reduce fyk where it cannot.",
        "The nominal resistance uses the entered design concrete law and limits every mild bar to its characteristic fyk.",
        "Stirrup anchorage is assumed. Reduce fywk when full anchorage is not available.",
    ],
)
def test_native_scope_match_is_exact_and_unknown_text_stays_literal(plain):
    assert str(notation.native_scope(plain)) == plain
    assert "<sub>" in report._html_escape(notation.native_scope(plain))
    for other in (
        plain + " extra",
        "prefix " + plain,
        plain.replace("fyk", "fyk_user"),
        "<b>" + plain + "</b>",
    ):
        if other == plain:
            continue
        assert type(notation.native_scope(other)) is str
        assert report._html_escape(notation.native_scope(other)) == report._html_escape(
            other
        )


@pytest.mark.parametrize("count", [8, 80])
def test_availability_notes_stay_together_when_short_and_split_when_oversized(
    monkeypatch, count
):
    rows = [
        {
            "check": f"Check-{i:03d}",
            "case": f"Case-{i:03d}",
            "status": "NOT ASSESSED",
            "result": "-",
            "note": f"Reason-{i:03d}",
            "source": f"Source-{i:03d}",
        }
        for i in range(count)
    ]
    monkeypatch.setattr(report.presentation, "multi_case_summary_rows", lambda *a: rows)
    monkeypatch.setattr(report.presentation, "non_governing_summary_rows", lambda r: r)
    monkeypatch.setattr(
        report.presentation, "non_governing_fatigue_spectrum_rows", lambda *a: []
    )
    b = report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, profile="Standard"
    )
    b._non_governing_status_register()
    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=56,
        rightMargin=56,
        topMargin=56,
        bottomMargin=56,
    ).build(b.flow)
    pdf = PdfReader(buffer)
    text = [p.extract_text() for p in pdf.pages]
    occupied = set()
    for i in range(count):
        hits = [j for j, t in enumerate(text) if f"Reason-{i:03d}" in t]
        assert len(hits) == 1
        assert f"Source: Source-{i:03d}" in text[hits[0]]
        assert f"Assessment note {i + 1}." in text[hits[0]]
        occupied.update(hits)
    assert len(occupied) == 1 if count == 8 else len(occupied) > 1
    destinations = [
        a.get_object()["/Dest"]
        for p in pdf.pages
        for a in p.get("/Annots", [])
        if "/Dest" in a.get_object()
    ]
    assert len(destinations) == count
