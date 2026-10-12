"""Keep report labels, numerical evidence and literal identities separate."""
from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import plotly.graph_objects as go
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import report_equation_contract as contracts
import sector_report as report


def test_report_equation_meanings_use_consistent_spelling():
    for contract in contracts._CONTRACTS.values():
        for symbol in contract.symbols:
            assert not any(word in symbol.meaning for word in (
                "utilisation", "fibre", "centre", "modelled", "mild-reinforcement",
                "mild reinforcement", "mild bar",
            ))
    # The names are source identifiers and remain unchanged.
    assert ("fatigue.reinforcement.yield-utilisation", None) in contracts._CONTRACTS
    assert len(contracts._CONTRACTS) == 145


@pytest.mark.parametrize("valid", [False, True])
@pytest.mark.parametrize("lam,cracked", [(0.103, True), (1.0, False), (1.2, False)])
@pytest.mark.parametrize("prestressed", [False, True])
def test_threshold_answer_and_exact_boundary_are_separate(valid, lam, cracked, prestressed):
    builder = object.__new__(report.ReportBuilder)
    builder.inp = {"tendons": [object()] if prestressed else []}
    builder.out = {"elastic": {"lambda_cr": lam, "cracked": cracked,
        "converged": valid, "fctm": 2.9, "sigma_ct": 28.223}}
    builder._selected_cracking_threshold = {"case_id": "LITERAL <sub>ID</sub>"}
    builder._selected_crack_examples = []
    builder._selected_crack_comparison = None
    builder._case_id = lambda *a: "LITERAL <sub>ID</sub>"
    builder.flow = []
    builder._case_heading = lambda *a, **k: None
    builder._keep_measured_calculation_from = lambda *a: None
    formulas = []
    notes = []
    builder._formula = lambda *a, **k: formulas.append((a, k))
    builder._small = notes.append
    before = copy.deepcopy(builder.out)
    builder._cracking()
    args = formulas[0][1]
    assert args["equation_key"] == "cracking.threshold"
    assert args["equation_variant"] == ("prestress" if prestressed else "ordinary")
    if prestressed:
        assert args["result"] is None and args["note"] is None
        assert any("prestress stays fixed" in text for text in notes)
    else:
        assert args["result"] == f"lambda<sub>cr</sub> = {report._fmt(lam, 3)}"
        assert "->" not in args["result"]
        if valid:
            assert args["note"] == (
                f"The section is {'cracked' if cracked else 'uncracked'}. "
                "Strictly below 1 means cracked. A value of 1 or above means uncracked."
            )
        else:
            assert args["note"] == "INVALID; no verified cracking classification"
    assert builder.out == before


def test_report_fatigue_map_changes_only_closed_labels(monkeypatch):
    literal = "USER utilisation sigma <sub>ID</sub> & fibre"
    native = go.Figure()
    native.add_scatter(x=[1, 2], y=[3, 4], name="concrete fibres",
        marker={"symbol": ["square", "star"], "color": [.2, .4]},
        text=[literal, "C4"], hovertext=[literal, "adaptive search"])
    native.add_scatter(x=[5], y=[6], name=literal, text=[literal])
    native.update_layout(title=literal, coloraxis={"colorbar": {"title": "Utilisation"}},
        annotations=[{"text": "utilisation limit = 1.00"}, {"text": literal}])
    before = native.to_plotly_json()
    def factory(*args, **kwargs):
        assert kwargs["title"] == literal
        return go.Figure(native)
    monkeypatch.setattr(report.viz, "fatigue_utilisation_map_figure", factory)
    result = report._report_fatigue_utilization_map([], [], [], [], {}, title=literal)
    expected = copy.deepcopy(before)
    expected["data"][0]["name"] = "concrete fibers"
    expected["layout"]["coloraxis"]["colorbar"]["title"]["text"] = "Utilization"
    expected["layout"]["annotations"][0]["text"] = "utilization limit = 1.00"
    assert result.to_plotly_json() == expected
    assert native.to_plotly_json() == before


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
def test_governing_fiber_bins_have_their_own_context(profile):
    from test_report import _fatigue_report_fixture

    inp, out = _fatigue_report_fixture()
    before = copy.deepcopy((inp, out))
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, out,
        figures=False, profile=profile)
    recorded = []
    h2 = builder._h2
    table = builder._table
    def heading(text):
        recorded.append(("heading", str(text)))
        return h2(text)
    def capture(rows, widths, **kwargs):
        recorded.append(("table", str(builder._table_subsection_context),
            copy.deepcopy(rows), kwargs.get("caption")))
        return table(rows, widths, **kwargs)
    builder._h2 = heading
    builder._table = capture
    builder._fatigue()
    tables = [row for row in recorded if row[0] == "table" and row[3] and
        (row[3].startswith("Concrete stress history at governing fiber ") or
         row[3].startswith("Concrete fatigue results at governing fiber "))]
    assert len(tables) == 2
    for row in tables:
        assert "Governing concrete fiber bin results - 4" in row[1]
        assert "Bounded governing-fiber search" not in row[1]
        assert row[3].endswith(" 4")
        assert all(bin_row[0] == "FAT-B1" for bin_row in row[2][1:])
    labels = [row[1] for row in recorded if row[0] == "heading"]
    assert labels.index("Bounded governing-fiber search") < labels.index(
        "Governing concrete fiber bin results - 4")
    # The presentation pass keeps the native objects unchanged.
    assert repr((inp, out)) == repr(before)


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
@pytest.mark.parametrize("valid", [False, True])
@pytest.mark.parametrize("lam,cracked", [(0.103, True), (1.0, False), (1.2, False)])
@pytest.mark.parametrize("prestressed", [False, True])
def test_threshold_real_pdf_keeps_answer_classification_and_variant_contract(
    profile, valid, lam, cracked, prestressed,
):
    from test_report import _inp
    from test_report_heading_layout import _pdf

    inp = _inp()
    if prestressed:
        inp["tendons"] = [(0., -.1, 100.)]
    out = {"elastic": {"lambda_cr": lam, "cracked": cracked,
        "converged": valid, "fctm": 2.9, "sigma_ct": 28.223}}
    before = copy.deepcopy((inp, out))
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, out,
        figures=False, profile=profile)
    builder._selected_cracking_threshold = {"case_id": "__single__"}
    builder._selected_crack_examples = []
    builder._selected_crack_comparison = None
    # Run the actual equation contract, layout and PDF paths together.
    builder._cracking()
    reader, pages = _pdf(builder)
    assert len(reader.pages) >= 1
    text = " ".join(" ".join(pages).split())
    import re
    prefix = "Calculated " if prestressed else ""
    answer = re.search(prefix + r"\u03bbcr\s*=\s*([0-9.]+)", text)
    assert answer is not None
    assert float(answer.group(1).rstrip(".")) == pytest.approx(lam)
    if valid:
        assert f"The section is {'cracked' if cracked else 'uncracked'}." in text
        assert "1 or above means uncracked." in text
        assert ("Below 1 means cracked." if prestressed else
            "Strictly below 1 means cracked.") in text
    else:
        assert "INVALID" in text
        if not prestressed:
            assert "no verified cracking classification" in text
    if prestressed:
        assert "Locked-in prestress stays fixed." in text
    elif profile == "Audit":
        assert "Applicability / method note:" in text
        assert "Equation (1.1)" in text
    assert repr((inp, out)) == repr(before)


def test_ordinary_threshold_requires_its_note_and_prestress_forbids_one():
    ordinary = contracts.equation_contract("cracking.threshold", "ordinary")
    prestress = contracts.equation_contract("cracking.threshold", "prestress")
    assert ordinary.applicability_note_required
    assert not prestress.applicability_note_required
    with pytest.raises(ValueError, match="requires an applicability note"):
        contracts.validate_equation_payload("cracking.threshold", ordinary,
            expression="lambda<sub>cr</sub> = f<sub>ct,eff</sub>/sigma<sub>ct,I</sub>",
            substitution="= 2.9/28.223", applicability_note=None,
            result="lambda<sub>cr</sub> = 0.103")
    with pytest.raises(ValueError, match="requires no applicability note"):
        contracts.validate_equation_payload("cracking.threshold", prestress,
            expression="sigma<sub>pre,i</sub> + lambda<sub>cr</sub> sigma<sub>ext,i</sub> = f<sub>ct,eff</sub>",
            substitution=None, applicability_note="Unexpected ordinary classification",
            result=None)
