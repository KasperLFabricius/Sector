"""Preserve unavailable-case reasons and their literal report identities."""
from __future__ import annotations

import ast
import copy
import inspect
import io
import re

from reportlab.platypus import Paragraph, Table
from test_report_heading_layout import _pdf

from app import sector_report as report
from sector import serviceability
from sector.engineer_message import EngineerMessage


def _markup(value):
    if isinstance(value, Paragraph):
        yield value.text
    elif isinstance(value, Table):
        yield from _markup(value._cellvalues)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _markup(item)
    elif hasattr(value, "_content"):
        yield from _markup(value._content)


def test_all_native_crack_scope_reasons_have_exact_authored_provenance():
    tree = ast.parse(inspect.getsource(serviceability))
    reasons = set()
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_not_assessed" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                reasons.add(node.args[0].value)
            if (function.name == "_direct_tension_area_2023"
                    and isinstance(node, ast.Return) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                reasons.add(node.value.value)
    assert len(reasons) >= 27
    for reason in reasons:
        assert str(report.presentation.result_reason(reason, "crack")) == reason


def test_unknown_diagnostic_fails_closed_while_typed_and_source_text_stay_literal():
    text = "Untrusted <sub>TAG</sub> sigma m2 1e-9 & ^2"
    assert text not in str(report.presentation.result_reason(text, "crack"))
    assert report.presentation.result_reason(EngineerMessage("QA-TYPED", text), "crack") == text
    output = {"calculation_state": "NOT ASSESSED", "reason": text,
              "criterion_source": text, "case": text, "governing": text}
    row = report.presentation._ordinary_crack_summary_row({}, output)
    assert row["status"] == "NOT ASSESSED"
    assert str(row["note"]).count(text) == 3
    assert str(report.presentation.result_reason(text, "crack")) in str(row["note"])


def test_every_nonbinary_status_has_unique_linked_reason_and_colocated_source(monkeypatch):
    statuses = report.presentation.GOVERNING_OVERVIEW_STATUS_PRECEDENCE
    rows = []
    literal = "Case <north> & sigma m2 1e-9"
    for index, status in enumerate(statuses):
        rows.append({"check": f"Check {index}", "case": literal,
                     "status": status, "result": f"Retained result {index}",
                     "note": f"UNIQUE-REASON-{index:02}: This case retains its specific assessment condition.",
                     "source": f"UNIQUE-SOURCE-{index:02}: Project <basis> & sigma m2 1e-9"})
    original = copy.deepcopy(rows)
    monkeypatch.setattr(report.presentation, "multi_case_summary_rows", lambda *a: rows)
    monkeypatch.setattr(report.presentation, "non_governing_summary_rows", lambda values: list(values))
    monkeypatch.setattr(report.presentation, "non_governing_fatigue_spectrum_rows", lambda *a: [])
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=False, profile="Standard")
    builder._h1("Retained non-governing states")
    builder._non_governing_status_register()
    assert rows == original
    markup = "\n".join(_markup(builder.flow))
    expected = [index for index, status in enumerate(statuses) if status not in {"PASS", "FAIL", "CALCULATED"}]
    names = re.findall(r'name="(availability-note-\d+)"', markup)
    links = re.findall(r'href="#(availability-note-\d+)"', markup)
    assert len(names) == len(expected) == len(set(names))
    assert links == names
    reader, texts = _pdf(builder)
    combined = " ".join(" ".join(texts).split())
    assert literal in combined and "Project <basis> & sigma m2 1e-9" in combined
    for index in expected:
        reason_pages = [i for i, text in enumerate(texts) if f"UNIQUE-REASON-{index:02}" in text]
        source_pages = [i for i, text in enumerate(texts) if f"UNIQUE-SOURCE-{index:02}" in text]
        assert len(reason_pages) == 1 and source_pages == reason_pages
    for index in set(range(len(statuses))) - set(expected):
        assert f"UNIQUE-REASON-{index:02}" not in combined
    destinations = []
    page_ids = {page.indirect_reference.idnum for page in reader.pages}
    for page in reader.pages:
        for annotation in page.get("/Annots", []):
            item = annotation.get_object()
            if item.get("/Subtype") != "/Link":
                continue
            destination = item.get("/Dest")
            if destination is not None:
                assert destination[0].idnum in page_ids
                destinations.append(tuple(str(value) for value in destination))
    assert len(destinations) == len(expected) == len(set(destinations))
