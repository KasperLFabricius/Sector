"""Current descriptive torsion evidence must retain the actual assessment state."""
import copy
import io
import pickle
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import sector_report as report
import result_presentation as presentation
from native_member_report_fixtures import native_base_en_report_case  # noqa: F401
from native_member_report_fixtures import native_subdivided_report_case  # noqa: F401


@pytest.mark.parametrize("kind", ["single", "compound"])
@pytest.mark.parametrize("state", ["current", "changed-wall", "invalid", "stale-case"])
def test_nonselected_audit_torsion_evidence_respects_native_guards(
    kind, state, request, monkeypatch,
):
    fixture = "native_base_en_report_case" if kind == "single" else "native_subdivided_report_case"
    inp, out = copy.deepcopy(request.getfixturevalue(fixture))
    if state == "changed-wall":
        inp["torsion_tef"] = 149.0
    elif state == "invalid":
        out["torsion"]["valid"] = False
    elif state == "stale-case":
        inp["_report_case_current"] = False
    original = pickle.dumps((inp, out))
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, out, profile="Audit", figures=False)
    monkeypatch.setattr(builder, "_selected_family", lambda *args: None)
    calls = []
    for name in ("_single_tube_evidence_tables", "_subtube_evidence_tables"):
        method = getattr(builder, name)
        def capture(value, _name=name, _method=method):
            calls.append(_name)
            return _method(value)
        monkeypatch.setattr(builder, name, capture)
    formulas = []
    monkeypatch.setattr(builder, "_formula", lambda *args, **kwargs: formulas.append(kwargs))
    builder._torsion()
    assert pickle.dumps((inp, out)) == original
    assert not formulas
    if state == "current":
        assert calls == ["_single_tube_evidence_tables" if kind == "single" else "_subtube_evidence_tables"]
        status = presentation.torsion_assessment_status(out["torsion"], input_payload=inp)
        assert builder._table_assessment_context == (
            "Assessment: Overall torsion status: " + status, status,
        )
        tables = [item for item in builder.flow if getattr(item, "_cellvalues", None)]
        table_text = " ".join(
            getattr(cell, "text", "")
            for table in tables for row in table._cellvalues for cell in row
        )
        assert "Overall torsion status: " + status in table_text
    else:
        assert not calls
