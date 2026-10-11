"""Regression checks for readable manual paragraphs and page breaks."""

import io
from html.parser import HTMLParser

import pypdf
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app import manual
from app import sector_report


def test_numbered_procedure_keeps_its_heading_on_the_same_page():
    styles = manual._manual_pdf_styles(
        sector_report, colors, ParagraphStyle, getSampleStyleSheet, TA_CENTER,
    )
    heading = "Calculate and check the results"
    flow = [
        Spacer(1, 220 * mm),
        Paragraph(heading, styles["MH2"]),
    ]
    manual._render_md_pdf(
        "1. Open Analysis and press Calculate.\n"
        "2. Review Results Overview.\n"
        "3. Open Elastic Results.\n"
        "4. Compare the stresses with the example.",
        flow, styles, Paragraph,
    )
    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=(210 * mm, 297 * mm),
        topMargin=25 * mm, bottomMargin=25 * mm,
    ).build(flow)
    pages = [page.extract_text() for page in pypdf.PdfReader(buffer).pages]
    assert len(pages) == 2
    assert heading not in pages[0]
    assert heading in pages[1]
    assert "Open Analysis and press Calculate." in pages[1]
    assert "Compare the stresses with the example." in pages[1]


def test_html_callouts_preserve_paragraphs_and_vertical_lists():
    class Callouts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.active = None
            self.items = []

        def handle_starttag(self, tag, attrs):
            if tag == "aside":
                self.active = {"p": 0, "li": 0}
            elif self.active is not None and tag in self.active:
                self.active[tag] += 1

        def handle_endtag(self, tag):
            if tag == "aside" and self.active is not None:
                self.items.append(self.active)
                self.active = None

    parser = Callouts()
    parser.feed(manual.build_manual_html_bytes().decode("utf-8"))
    blocks = [block for block in manual.manual_blocks() if block[0] == "callout"]
    assert len(parser.items) == len(blocks)
    checked_paragraphs = checked_lists = 0
    for block, item in zip(blocks, parser.items):
        if "\n\n" in block[2]:
            assert item["p"] >= 2, block[2]
            checked_paragraphs += 1
        bullets = sum(line.startswith("- ") for line in block[2].splitlines())
        if bullets:
            assert item["li"] == bullets, block[2]
            checked_lists += 1
    assert checked_paragraphs >= 5
    assert checked_lists >= 1


def test_inline_code_keeps_native_text_in_pdf_and_html():
    literal = r"C:\Sector\_internal $x$ *file* 1e-9 mm2 <tag> &"
    source = "Open `" + literal + "`."
    styles = manual._manual_pdf_styles(
        sector_report, colors, ParagraphStyle, getSampleStyleSheet, TA_CENTER,
    )
    paragraph = Paragraph(manual._inline_md_to_rl(source), styles["MBody"])
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer).build([paragraph])
    text = pypdf.PdfReader(buffer).pages[0].extract_text().strip()
    assert text == "Open " + literal + "."
    assert "`" not in text

    class Code(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []
            self.text = []
        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)
        def handle_data(self, text):
            self.text.append(text)

    parser = Code()
    parser.feed(manual._inline_md_to_html(source))
    assert parser.tags == ["code"]
    assert "".join(parser.text) == "Open " + literal + "."


def test_html_math_inequalities_preserve_visible_and_accessible_values():
    expression = "0<e<0.6 & e>0"
    rendered, label = manual._html_math_parts(expression)
    assert label == expression
    assert "&lt;" in rendered and "&gt;" in rendered and "&amp;" in rendered
    assert "<e" not in rendered
    html = manual._inline_md_to_html("$" + expression + "$")
    assert 'aria-label="Mathematical expression: 0&lt;e&lt;0.6 &amp; e&gt;0"' in html


def test_consecutive_workflow_links_stay_on_one_pdf_page():
    styles = manual._manual_pdf_styles(
        sector_report, colors, ParagraphStyle, getSampleStyleSheet, TA_CENTER,
    )
    flow = [Spacer(1, 231 * mm)]
    manual._render_md_pdf(
        "[Status and next action](#status)\n\n[Troubleshooting](#troubleshooting)",
        flow, styles, Paragraph,
    )
    # Replace internal destinations for this small isolated layout proof.
    for item in flow[1:]:
        item.frags = [fragment for fragment in item.frags]
        for fragment in item.frags:
            fragment.link = []
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=(210 * mm, 297 * mm),
                      topMargin=25 * mm, bottomMargin=25 * mm).build(flow)
    pages = [page.extract_text() for page in pypdf.PdfReader(buffer).pages]
    assert all(("Status and next action" in page) == ("Troubleshooting" in page)
               for page in pages)
    assert sum("Troubleshooting" in page for page in pages) == 1


def test_prose_heading_stays_with_governed_equation_on_pdf_page():
    from reportlab.platypus import KeepTogether, Table, TableStyle
    styles = manual._manual_pdf_styles(
        sector_report, colors, ParagraphStyle, getSampleStyleSheet, TA_CENTER,
    )
    published = tuple(manual.publish_manual_blocks(
        manual.manual_publication_blocks(manual.manual_blocks())))
    equation = next(item.block[1] for item in published
                    if item.block[0] == manual.EQUATION_BLOCK)
    width = 160 * mm
    compiled = manual._compile_manual_equation_pdf_flowables(published, width)
    flow = [Spacer(1, 220 * mm)]
    manual._render_md_pdf("**Equation context heading**", flow, styles, Paragraph)
    manual._render_manual_equation_pdf(
        equation, compiled[equation.contract.key], flow, styles, Paragraph,
        Table, TableStyle, KeepTogether, Spacer, colors, width,
    )
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=(210 * mm, 297 * mm),
                      topMargin=25 * mm, bottomMargin=25 * mm).build(flow)
    pages = [page.extract_text() for page in pypdf.PdfReader(buffer).pages]
    heading_page = next(index for index, text in enumerate(pages)
                        if "Equation context heading" in text)
    assert heading_page > 0
    assert f"Equation {equation.contract.number}" in pages[heading_page]
    assert "Mathematical expression:" in pages[heading_page]


def test_math_preserves_authored_number_unit_spacing():
    import html
    expression = r"150\,\text{mm}^{2}"
    pdf = Paragraph(manual._inline_md_to_rl("$" + expression + "$"),
                    getSampleStyleSheet()["Normal"])
    assert pdf.getPlainText().replace("\xa0", " ") == "150 mm2"
    _rendered, accessible = manual._html_math_parts(expression)
    assert accessible == "150 mm2"


def test_fatigue_metadata_formats_reference_star_and_radical():
    assert manual._latex_to_rl(r"N^*") == "N<super>*</super>"
    rendered, label = manual._html_math_parts(r"N^*")
    assert rendered == "N<sup>*</sup>"
    assert label == "N*"
    expression = r"E_{max}+0.43\sqrt{1-E_{min}/E_{max}}"
    for markup in (manual._latex_to_rl(expression), manual._html_math_parts(expression)[0]):
        assert "&#8730;(1-E" in markup
        assert "sqrt" not in markup and "^" not in markup


def test_inline_script_rises_are_visible_and_clear_the_next_line():
    import pytest
    from reportlab.pdfbase.pdfmetrics import getAscentDescent
    styles = manual._manual_pdf_styles(
        sector_report, colors, ParagraphStyle, getSampleStyleSheet, TA_CENTER,
    )
    style = styles["MBody"]
    paragraph = Paragraph(manual._inline_md_to_rl(r"$M_{Ed}$, $F_{td}$ and $x^2$"), style)
    scripts = {fragment.text: fragment for fragment in paragraph.frags
               if fragment.text in {"Ed", "td", "2"}}
    assert set(scripts) == {"Ed", "td", "2"}
    for text in ("Ed", "td"):
        fragment = scripts[text]
        assert fragment.rise == pytest.approx(-2.625)
        assert fragment.fontSize < style.fontSize
        _ascent, descent = getAscentDescent(fragment.fontName, fragment.fontSize)
        next_ascent, _descent = getAscentDescent(style.fontName, style.fontSize)
        clearance = style.leading - next_ascent + fragment.rise + descent
        assert clearance >= 1.0
    assert scripts["2"].rise == pytest.approx(3.675)
