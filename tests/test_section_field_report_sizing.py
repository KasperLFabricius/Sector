"""Report field figures preserve their native canvas proportions."""
import io
from types import SimpleNamespace

import pytest
from app import sector_report as report
from app import section_fields as fields
from test_section_fields import native_case


@pytest.fixture(scope="module")
def field():
    inp, result, _, _ = native_case()
    return fields.build_field(inp, result, family="Elastic")


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
@pytest.mark.parametrize("width,height", [(760, 665), (760, 713), (760, 2000), (1000, 610)])
def test_map_dimensions_preserve_ratio_and_page_bounds(profile, width, height, field, monkeypatch):
    figure = SimpleNamespace(layout=SimpleNamespace(width=width, height=height))
    monkeypatch.setattr(report.section_fields, "field_pair", lambda *a, **kw: (field, [("strain", figure), ("stress", figure)]))
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=True, profile=profile)
    captured = []
    monkeypatch.setattr(builder, "_fig", lambda fig, w, h, **kw: captured.append((fig, w, h, kw)))
    builder._section_field_maps({}, family="Elastic")
    assert len(captured) == 2
    for fig, w, h, options in captured:
        assert fig is figure
        assert options["export_size"] == (width, height)
        assert w / h == pytest.approx(width / height, rel=1e-15, abs=0)
        assert 0 < w <= 170 and 0 < h <= 160
        assert field.state in options["caption"]
        assert "Unnamed action: elastic" in options["caption"]


@pytest.mark.parametrize("width,height", [(0, 665), (760, -1), (float("nan"), 665), (760, float("inf"))])
def test_map_invalid_dimensions_fail_before_export(width, height, field, monkeypatch):
    figure = SimpleNamespace(layout=SimpleNamespace(width=width, height=height))
    monkeypatch.setattr(report.section_fields, "field_pair", lambda *a, **kw: (field, [("stress", figure)]))
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=True, profile="Standard")
    monkeypatch.setattr(builder, "_fig", lambda *a, **kw: pytest.fail("Invalid dimensions reached export"))
    with pytest.raises(report.ReportFigureError, match="dimensions are invalid"):
        builder._section_field_maps({}, family="Elastic")


def test_figures_off_does_not_build_or_size_maps(monkeypatch):
    monkeypatch.setattr(report.section_fields, "field_pair", lambda *a, **kw: pytest.fail("Figures-off maps evaluated"))
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=False, profile="Standard")
    builder._section_field_maps({}, family="Elastic")
    assert not builder.flow


@pytest.mark.parametrize("native", [False, True])
def test_native_canvas_export_is_optional_and_keeps_caption_with_image(native, monkeypatch):
    from PIL import Image
    import plotly.graph_objects as go
    data = io.BytesIO()
    Image.new("RGB", (760, 665), "white").save(data, format="PNG")
    calls = []
    def export(figure, width, height):
        calls.append((width, height))
        return data.getvalue(), False
    monkeypatch.setattr(report, "_fig_png", export)
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=True, profile="Standard")
    options = {"export_size": (760, 665)} if native else {}
    builder._fig(go.Figure(), 170, 148.75, caption="Exact retained state", **options)
    assert calls == ([(760, 665)] if native else [(int(170 * 3.78), int(148.75 * 3.78))])
    table = builder.flow[0]
    assert table.splitByRow == 0 and table.splitInRow == 0
    image, caption = table._cellvalues[0][0], table._cellvalues[1][0]
    assert image.drawWidth / image.drawHeight == pytest.approx(760 / 665, rel=1e-15, abs=0)
    assert "Exact retained state" in caption.getPlainText()


def test_map_reading_notes_precede_bounded_figures(field, monkeypatch):
    from reportlab.platypus import KeepTogether, Paragraph
    figure = SimpleNamespace(layout=SimpleNamespace(width=760, height=665))
    monkeypatch.setattr(report.section_fields, "field_pair", lambda *a, **kw: (field, [("stress", figure)]))
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, figures=True, profile="Standard")
    def capture(*a, **kw):
        builder.flow.append(Paragraph("ACTUAL MAP CAPTION", builder.s["small"]))
    monkeypatch.setattr(builder, "_fig", capture)
    builder._section_field_maps({}, family="Elastic")
    def texts(flow):
        for item in flow:
            if isinstance(item, KeepTogether):
                yield from texts(item._content)
            elif isinstance(item, Paragraph):
                yield item.getPlainText()
    visible = list(texts(builder.flow))
    caption = visible.index("ACTUAL MAP CAPTION")
    for phrase in ("For the section maps, color limits stay fixed", "Display bands show"):
        assert next(i for i, text in enumerate(visible) if phrase in text) < caption
    assert any("Tension is positive" in text for text in visible[caption + 1:])


@pytest.mark.parametrize("profile", ["Standard", "Audit"])
@pytest.mark.parametrize("long_identity", [False, True])
def test_complete_map_caption_and_native_extrema_share_page(profile, long_identity, field, monkeypatch):
    from PIL import Image
    import pypdf
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    case_id = "ACTION <&> " + ("Long identity " * 12 if long_identity else "SLS1")
    figures = [(quantity, fields.section_field_figure(field, quantity, title=case_id + ": " + quantity))
               for quantity in ("strain", "stress")]
    monkeypatch.setattr(report.section_fields, "field_pair", lambda *a, **kw: (field, figures))
    def export(figure, width, height):
        assert (width, height) == (figure.layout.width, figure.layout.height)
        data = io.BytesIO()
        Image.new("RGB", (width, height), "white").save(data, format="PNG")
        return data.getvalue(), False
    monkeypatch.setattr(report, "_fig_png", export)
    builder = report.ReportBuilder(io.BytesIO(), {}, {"elastic_case": {"id": case_id}}, {}, figures=True, profile=profile)
    builder._h1("Native elastic section fields")
    builder._section_field_maps({}, family="Elastic")
    stream = io.BytesIO()
    document = report._ReportDocTemplate(stream, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                                         topMargin=25 * mm, bottomMargin=20 * mm)
    document.multiBuild(builder.flow)
    texts = [page.extract_text() for page in pypdf.PdfReader(io.BytesIO(stream.getvalue())).pages]
    assert all(text.strip() for text in texts)
    for index, quantity in enumerate(("strain", "stress"), 1):
        pages = [text for text in texts if f"Figure 1.{index}." in text]
        assert len(pages) == 1
        text = pages[0]
        assert " ".join(case_id.split()) in " ".join(text.split())
        assert f"elastic {quantity}" in text
        assert f"Table 1.{index}." in text
        for label, value, x, y in fields.extrema(field, quantity):
            assert label in text
            assert report._fmt(value, 5) in text
            assert report._fmt(x * 1000, 2) in text and report._fmt(y * 1000, 2) in text
        assert "Tension is positive. Compression is negative." in text
