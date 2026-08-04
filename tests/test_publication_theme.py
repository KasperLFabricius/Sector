"""Independent PR-11C2A publication-theme and export-noise contracts."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import pathlib
import sys
import warnings

import pytest
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import publication_theme  # noqa: E402
import sector_report  # noqa: E402


REPORT_MATRIX = {
    "title": (20, None, 0, 4, "#1f3b66", True, False),
    "subtitle": (11, None, 0, 2, "#5a5a5a", False, False),
    "h1": (14, None, 10, 6, "#1f3b66", True, True),
    "h2": (11.5, None, 8, 4, "#1f3b66", True, True),
    "body": (9.5, 13, 0, 4, None, False, False),
    "small": (8.5, 11, 0, 0, "#5a5a5a", False, False),
    "publication_ref": (8, 10, 2, 2, "#5a5a5a", False, True),
    "publication_caption": (8, 10, 2, 2, "#2c2c2a", False, True),
}

MANUAL_MATRIX = {
    "title": (20, None, 0, 6, None, True, False),
    "part": (17, None, 18, 8, "#0d2440", True, True),
    "h1": (15, None, 14, 8, "#1f3b66", True, True),
    "h2": (12.5, None, 9, 4, None, True, True),
    "h3": (11, None, 6, 3, None, True, True),
    "body": (9.5, 13, 0, 4, None, False, False),
    "math": (11, 15, 6, 6, None, False, False),
    "small": (8, 11, 0, 0, "#808080", False, False),
    "publication_ref": (8, 10, 2, 2, "#808080", False, True),
    "publication_caption": (8, 10, 2, 3, "#2c2c2a", False, True),
}


def _style_tuple(style):
    return (
        style.size,
        style.leading,
        style.before,
        style.after,
        style.color.lower() if style.color else None,
        style.bold,
        style.keep_next,
    )


def _color_hex(value):
    if value is None:
        return None
    encoded = value.hexval().lower()
    return f"#{encoded[2:]}" if encoded.startswith("0x") else encoded


def test_theme_is_immutable_and_keeps_manual_reportlab_lazy():
    source = pathlib.Path(publication_theme.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(name == "reportlab" or name.startswith("reportlab.")
                   for name in imports)
    with pytest.raises(TypeError):
        publication_theme.REPORT_TEXT["body"] = object()
    with pytest.raises(FrozenInstanceError):
        publication_theme.PALETTE.primary = "#000000"


def test_frozen_role_inventory_matches_retained_merged_values():
    assert set(publication_theme.REPORT_TEXT) == set(REPORT_MATRIX)
    assert set(publication_theme.MANUAL_TEXT) == set(MANUAL_MATRIX)
    assert {
        role: _style_tuple(spec)
        for role, spec in publication_theme.REPORT_TEXT.items()
    } == REPORT_MATRIX
    assert {
        role: _style_tuple(spec)
        for role, spec in publication_theme.MANUAL_TEXT.items()
    } == MANUAL_MATRIX


def test_report_and_manual_reconstruct_every_frozen_text_role():
    report_styles = sector_report._styles()
    manual_styles = manual._manual_pdf_styles(
        sector_report,
        colors,
        ParagraphStyle,
        getSampleStyleSheet,
        TA_CENTER,
    )
    report_names = {
        "title": "title",
        "subtitle": "subtitle",
        "h1": "h1",
        "h2": "h2",
        "body": "body",
        "small": "small",
        "publication_ref": "publication_ref",
        "publication_caption": "publication_caption",
    }
    manual_names = {
        "title": "MTitle",
        "part": "MPart",
        "h1": "MH1",
        "h2": "MH2",
        "h3": "MH3",
        "body": "MBody",
        "math": "MMath",
        "small": "MSmall",
        "publication_ref": "MPubRef",
        "publication_caption": "MPubCaption",
    }

    for role, name in report_names.items():
        actual = report_styles[name]
        expected = publication_theme.REPORT_TEXT[role]
        assert actual.fontSize == pytest.approx(expected.size)
        assert actual.spaceBefore == pytest.approx(expected.before)
        assert actual.spaceAfter == pytest.approx(expected.after)
        assert bool(getattr(actual, "keepWithNext", 0)) is expected.keep_next
        if expected.leading is not None:
            assert actual.leading == pytest.approx(expected.leading)
        if expected.color is not None:
            assert _color_hex(actual.textColor) == expected.color.lower()

    for role, name in manual_names.items():
        actual = manual_styles[name]
        expected = publication_theme.MANUAL_TEXT[role]
        assert actual.fontSize == pytest.approx(expected.size)
        assert actual.spaceBefore == pytest.approx(expected.before)
        assert actual.spaceAfter == pytest.approx(expected.after)
        assert bool(getattr(actual, "keepWithNext", 0)) is expected.keep_next
        if expected.leading is not None:
            assert actual.leading == pytest.approx(expected.leading)
        if expected.color is not None:
            assert _color_hex(actual.textColor) == expected.color.lower()


@pytest.mark.parametrize("path", ["report", "manual"])
def test_export_path_hides_exact_server_kopts_noise_only(path):
    class Figure:
        def emit(self):
            warnings.warn_explicit(
                publication_theme.KALEIDO_SERVER_KOPTS_WARNING,
                UserWarning,
                "plotly/io/_kaleido.py",
                400,
                module="plotly.io._kaleido",
            )
            warnings.warn_explicit(
                "independent Kaleido warning",
                UserWarning,
                "plotly/io/_kaleido.py",
                401,
                module="plotly.io._kaleido",
            )

        def to_image(self, **_kwargs):
            self.emit()
            return b"report-bytes"

        def write_image(self, target, **_kwargs):
            self.emit()
            target.write(b"manual-bytes")

    figure = Figure()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if path == "report":
            result, timed_out = sector_report._fig_png(
                figure, 100, 100, timeout=2
            )
            assert (result, timed_out) == (b"report-bytes", False)
        else:
            assert manual._fig_to_png(
                lambda: figure, timeout=2
            ) == b"manual-bytes"
    assert [str(item.message) for item in caught] == [
        "independent Kaleido warning"
    ]


@pytest.mark.parametrize(
    ("message", "module"),
    [
        (
            publication_theme.KALEIDO_SERVER_KOPTS_WARNING,
            "sector.synthetic_exporter",
        ),
        ("different server warning", "plotly.io._kaleido"),
    ],
)
def test_suppression_boundary_retains_other_message_or_source(message, module):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with publication_theme.without_kaleido_server_kopts_noise():
            warnings.warn_explicit(
                message,
                UserWarning,
                "synthetic.py",
                1,
                module=module,
            )
    assert [str(item.message) for item in caught] == [message]
