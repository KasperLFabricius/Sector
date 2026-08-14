"""Browser-free acceptance tests for manual publication equation layout."""

from __future__ import annotations

import io
import os
import pathlib
import re
import subprocess
import sys
import textwrap

import pypdf
import pypdfium2
import pytest
from PIL import Image, ImageChops
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm

from tools.publication_preflight import validate_raster_pages

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual
import publication_image_export

from app import publication_equation_layout as equations

FRAME_WIDTH = A4[0] - 4.4 * cm - 12.0
SEMANTIC_MARKER = "SECTOR-MATH[manual-expression]"


def _published_blocks():
    return tuple(
        manual.publish_manual_blocks(
            manual.manual_publication_blocks(manual.manual_blocks())
        )
    )


def _governed(published):
    return tuple(
        item.block[1]
        for item in published
        if item.block[0] == manual.EQUATION_BLOCK
    )


@pytest.fixture(scope="module")
def manual_pdf() -> bytes:
    return manual.build_manual_pdf_bytes(figures=False)


@pytest.fixture(scope="module")
def pdf_reader(manual_pdf: bytes) -> pypdf.PdfReader:
    return pypdf.PdfReader(io.BytesIO(manual_pdf))


@pytest.fixture(scope="module")
def page_texts(pdf_reader: pypdf.PdfReader) -> tuple[str, ...]:
    return tuple(
        re.sub(r"\s+", " ", page.extract_text() or "")
        for page in pdf_reader.pages
    )


def _font_objects(reader: pypdf.PdfReader) -> list[object]:
    found = []
    for page in reader.pages:
        resources = page["/Resources"].get_object()
        fonts = resources.get("/Font")
        if fonts is None:
            continue
        found.extend(reference.get_object() for reference in fonts.get_object().values())
    return found


def test_manual_import_keeps_canonical_equation_renderer_lazy() -> None:
    script = textwrap.dedent(
        f"""
        import pathlib
        import sys

        root = pathlib.Path({str(ROOT)!r})
        sys.path.insert(0, str(root / "app"))
        sys.path.insert(0, str(root))
        import manual

        assert "app.publication_equation_layout" not in sys.modules
        assert "publication_equation_layout" not in sys.modules
        published = tuple(
            manual.publish_manual_blocks(
                manual.manual_publication_blocks(manual.manual_blocks())
            )
        )
        compiled = manual._compile_manual_equation_pdf_flowables(
            published,
            {FRAME_WIDTH!r},
        )
        assert len(compiled) == 33
        assert "app.publication_equation_layout" in sys.modules
        assert "publication_equation_layout" not in sys.modules
        """
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


def test_all_33_governed_expressions_compile_with_exact_spine_association() -> None:
    published = _published_blocks()
    governed = _governed(published)
    compiled = manual._compile_manual_equation_pdf_flowables(
        published,
        FRAME_WIDTH,
    )

    assert len(governed) == len(compiled) == 33
    assert tuple(compiled) == tuple(item.contract.key for item in governed)
    for item in governed:
        source, flowable = compiled[item.contract.key]
        assert source is item
        assert type(flowable) is equations.EquationFlowable
        assert flowable.block.identity is None
        assert flowable.block.source is None
        assert len(flowable.block.lines) == 1
        assert flowable.block.lines[0].role == "manual-expression"
        assert flowable.block.lines[0].expression == equations.compile_manual_math(
            item.equation.equation.expression
        )


def test_manual_structural_fraction_radical_and_script_geometry_is_measured() -> None:
    published = _published_blocks()
    compiled = manual._compile_manual_equation_pdf_flowables(
        published,
        FRAME_WIDTH,
    )
    geometry_by_number = {}
    for item, flowable in compiled.values():
        width, height = flowable.wrap(FRAME_WIDTH, 700.0)
        assert width == pytest.approx(FRAME_WIDTH)
        assert 0.0 < height <= 700.0
        geometry_by_number[item.contract.number] = flowable.geometry

    curvature_kinds = {
        node.kind for node in geometry_by_number["C4-1"].nodes
    }
    heightened_kinds = {
        node.kind for node in geometry_by_number["C7-5"].nodes
    }
    assert {"fraction", "script", "delimited"} <= curvature_kinds
    assert {"fraction", "script", "radical", "radical-sign"} <= heightened_kinds
    assert geometry_by_number["C4-1"].rules
    assert geometry_by_number["C7-5"].rules
    curvature_rows = geometry_by_number["C4-1"].rows
    assert len(curvature_rows) == 4
    assert tuple(row.continuation for row in curvature_rows) == (
        False,
        True,
        True,
        True,
    )
    assert not {
        node.kind for node in geometry_by_number["C4-1"].nodes
    } & {"literal"}


def test_manual_pdf_is_searchable_vector_math_without_image_equations(
    pdf_reader: pypdf.PdfReader,
    page_texts: tuple[str, ...],
) -> None:
    text = " ".join(page_texts)
    assert text.count(SEMANTIC_MARKER) == 33
    for page in pdf_reader.pages:
        resources = page["/Resources"].get_object()
        assert not resources.get("/XObject")

    fonts = _font_objects(pdf_reader)
    equation_fonts = [
        font for font in fonts if "DejaVuSans" in str(font.get("/BaseFont"))
    ]
    assert equation_fonts
    assert all(font.get("/ToUnicode") is not None for font in equation_fonts)

    operators = []
    for page in pdf_reader.pages:
        content = pypdf.generic.ContentStream(page.get_contents(), pdf_reader)
        operators.extend(operator for _operands, operator in content.operations)
    assert operators.count(b"S") >= 2
    assert b"m" in operators and b"l" in operators
    assert b"Do" not in operators


def test_each_identity_expression_result_and_source_stay_ordered_on_one_page(
    page_texts: tuple[str, ...],
) -> None:
    published = _published_blocks()
    compiled = manual._compile_manual_equation_pdf_flowables(
        published,
        FRAME_WIDTH,
    )
    for item, flowable in compiled.values():
        semantic = (
            SEMANTIC_MARKER
            + " "
            + equations.linear_math_text(flowable.block.lines[0].expression)
        )
        heading = (
            f"Equation {item.contract.number} | "
            f"{item.contract.dimensional_class}"
        )
        matching = [page for page in page_texts if heading in page]
        assert len(matching) == 1, item.contract.number
        page = matching[0]
        source = item.equation.source.source_text
        source_label = manual.source_kind_label(item) + ":"
        heading_at = page.index(heading)
        semantic_at = page.index(semantic, heading_at)
        result_at = page.index("Result:", semantic_at)
        source_label_at = page.index(source_label, result_at)
        source_at = page.index(source, source_label_at)
        assert heading_at < semantic_at < result_at < source_label_at <= source_at


def test_last_compile_failure_precedes_figure_and_output_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = equations.compile_manual_math
    calls = []
    figure_starts = []

    def compile_or_fail(source: str):
        calls.append(source)
        if len(calls) == 33:
            raise equations.EquationLayoutError("deliberate final corpus failure")
        return original(source)

    monkeypatch.setattr(equations, "compile_manual_math", compile_or_fail)
    monkeypatch.setattr(
        publication_image_export,
        "ensure_ready",
        lambda *, timeout: figure_starts.append(timeout),
    )
    output = io.BytesIO()
    with pytest.raises(
        equations.EquationLayoutError,
        match="deliberate final corpus failure",
    ):
        manual.build_manual_pdf(output, figures=True)

    assert len(calls) == 33
    assert not figure_starts
    assert output.getvalue() == b""


def test_complex_manual_pages_are_visible_and_unclipped_in_both_rasters(
    manual_pdf: bytes,
    page_texts: tuple[str, ...],
) -> None:
    selected = [
        next(
            index
            for index, text in enumerate(page_texts)
            if f"Equation {number} |" in text and SEMANTIC_MARKER in text
        )
        for number in ("C4-1", "C7-5")
    ]
    document = pypdfium2.PdfDocument(manual_pdf)
    try:
        for index in selected:
            page = document[index]
            try:
                colour = page.render(scale=1.5).to_pil().convert("RGB")
                grayscale = page.render(
                    scale=1.5,
                    grayscale=True,
                ).to_pil().convert("L")
            finally:
                page.close()

            boxes = (
                ImageChops.difference(
                    colour,
                    Image.new("RGB", colour.size, "white"),
                ).getbbox(),
                ImageChops.difference(
                    grayscale,
                    Image.new("L", grayscale.size, "white"),
                ).getbbox(),
            )
            assert all(box is not None for box in boxes)
            validate_raster_pages([colour])
            validate_raster_pages([grayscale.convert("RGB")])
            for box in boxes:
                assert box is not None
                left, top, right, bottom = box
                assert right - left > 500 and bottom - top > 500
            assert all(
                abs(boxes[0][coordinate] - boxes[1][coordinate]) <= 2
                for coordinate in range(4)
            )
            assert sum(grayscale.histogram()[:245]) > 100_000
    finally:
        document.close()


def test_manual_adapter_sources_remain_ascii() -> None:
    for path in (
        ROOT / "app" / "manual.py",
        ROOT / "tests" / "test_manual_equation_layout.py",
    ):
        assert path.read_bytes().isascii()
