"""Generate a QA-able PDF report of a Sector cross-section analysis.

Modelled on the BriCoS report: a sectioned reportlab document with a numbered
footer, every case summarised and each computed case reported in detail, and
every computed quantity tied to its formula and the selected
``EN 1992-1-1`` edition.

The builder is fed the same two objects the result views use -- the collected
inputs ``inp`` and the analysis payload ``out = run_analysis(inp)`` -- plus the
report ``meta`` (project / author fields), so the report cannot drift from what
the app computes. Figures are the on-screen Plotly figures exported to PNG.

Engineering symbols are written in ASCII (``eps_cu2``, ``sigma_s``, ``w_k``) with
``<sub>`` markup: the source stays ASCII (the repo enforces it) and the PDF does
not depend on a Greek-capable font.
"""

from __future__ import annotations

import atexit
import datetime
import html as html_lib
import io
import math
import os
import re
import threading

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (Image, KeepTogether, NotAtTopPageBreak,
                                Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

import case_analysis
import fatigue_inputs
import fatigue_presentation
import material_catalog
from publication_items import PublicationCounter
from publication_notation import normalize_trusted_markup, shield_literal_markup
import report_equation_contract
import viz
import result_presentation as presentation
from sector import codes as ec2_codes
from sector import detailing
from sector import __licensee__ as SECTOR_LICENSEE
from sector.build_info import short_revision

_MM = 1000.0                       # metres -> millimetres for display
_KN = 1.0                          # forces already in kN
_BLUE = colors.HexColor("#1F3B66")
_GREY = colors.HexColor("#5A5A5A")
_LINE = colors.HexColor("#9AA5B1")
_HEAD_BG = colors.HexColor("#E8ECF2")
_A4_CONTENT_WIDTH = A4[0] - 40 * mm
_REPORT_FRAME_PADDING = 6.0
_A4_FRAME_USABLE_HEIGHT = A4[1] - 45 * mm - 2 * _REPORT_FRAME_PADDING
_MIN_REPORT_TABLE_FONT = 7.2
_REPORT_TABLE_HORIZONTAL_PADDING = 3.0
_ASSESSMENT_PALETTE = {
    "PASS": ("#E8F5E9", "#1B5E20"),
    "OK": ("#E8F5E9", "#1B5E20"),
    "FAIL": ("#FDECEC", "#9B1C1C"),
    "EXCEEDED": ("#FDECEC", "#9B1C1C"),
    "INVALID": ("#FDECEC", "#9B1C1C"),
    "REVIEW": ("#FFF4D6", "#7A4E00"),
    "NOT ASSESSED": ("#FFF4D6", "#7A4E00"),
    "NOT APPLICABLE": ("#EEF2F6", "#374151"),
}
_NUMERIC_TABLE_WORD = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"[+-]?(?:(?:\d+(?:[.,]\d*)?)|(?:[.,]\d+))(?:[eE][+-]?\d+)?%?"
    r"(?![A-Za-z0-9_.])"
)
_CRACK_CANDIDATE_COL_WIDTHS = tuple(
    value * mm
    for value in (17, 7, 16, 13, 13, 10, 10, 17, 18, 18, 13, 13)
)
_EQUATION_KEY_RE = re.compile(
    r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$"
)
_DERIVED_EQUATION_SOURCE = (
    "Derived relation; no separate normative source assigned."
)

# A Unicode (Greek-capable) font for the report. DejaVuSans is free and shipped
# with the app; Helvetica is the fallback (Greek glyphs then render as boxes, but
# the report still generates). BriCoS uses Helvetica -- DejaVuSans keeps the same
# clean sans-serif look while adding the Greek the engineering notation needs.
_FONT, _FONT_BOLD = "Helvetica", "Helvetica-Bold"


def _steel_standard_reference(preset):
    """Return a normative steel-law reference only for a recognised EC2 preset."""
    code = ec2_codes.CODES.get(str(preset))
    if code is None:
        return None
    if code.key == "EC2-2023":
        return "EN 1992-1-1:2023 &#167;5.2.4"
    return f"{code.label} &#167;3.2.7"


def _steel_reference_set(presets):
    references = [_steel_standard_reference(value) for value in presets]
    known = list(dict.fromkeys(value for value in references if value))
    return known, any(value is None for value in references)


def _steel_theory_reference(presets):
    known, has_unassigned = _steel_reference_set(presets)
    if not has_unassigned and len(known) == 1:
        return known[0]
    if not has_unassigned:
        return "material-specific catalogue references (mixed recognised editions)"
    if known:
        return ("material-specific catalogue references; custom/generic laws "
                "have no assigned normative source")
    return "custom/generic constitutive laws; no normative source assigned"


def _register_fonts():
    global _FONT, _FONT_BOLD
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(d, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold",
                                       os.path.join(d, "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("DejaVuSans", normal="DejaVuSans",
                                      bold="DejaVuSans-Bold", italic="DejaVuSans",
                                      boldItalic="DejaVuSans-Bold")
        _FONT, _FONT_BOLD = "DejaVuSans", "DejaVuSans-Bold"
    except Exception:
        pass


_register_fonts()

# ASCII engineering tokens -> their Greek glyph (numeric entity, so the source
# stays ASCII). Applied at render time with word boundaries, so Python identifiers
# (c.eps_c2) and dict keys (cw.get("phi")) are never touched.
_GREEK = {"eps": "&#949;", "sigma": "&#963;", "lambda": "&#955;", "alpha": "&#945;",
          "beta": "&#946;", "eta": "&#951;", "gamma": "&#947;",
          "kappa": "&#954;", "rho": "&#961;", "phi": "&#966;",
          "theta": "&#952;", "nu": "&#957;", "tau": "&#964;", "permille": "&#8240;"}
_GREEK_RE = re.compile(r"\b(" + "|".join(_GREEK) + r")\b")


class _LiteralReportText(str):
    """Escaped identity/description text that remains wrappable in tables."""


class _NumericalReportText(str):
    """Escaped mixed text with an explicit numerical-evidence source."""

    def __new__(cls, markup, evidence):
        value = super().__new__(cls, markup)
        value._sector_numeric_evidence = str(evidence)
        return value


def _html_escape(value, quote=True):
    """Escape literal/user text and shield it from engineering-token rendering.

    Report text intentionally converts trusted standalone tokens such as ``sigma``
    to Greek glyphs. Numeric entities keep those same words literal when they came
    from a user-controlled identifier, while remaining safe ReportLab markup.
    """

    escaped = shield_literal_markup(value, quote=quote)
    return _LiteralReportText(_GREEK_RE.sub(
        lambda match: "".join(
            f"&#{ord(character)};" for character in match.group(1)
        ),
        escaped,
    ))


def _greek(s):
    """Replace the ASCII engineering tokens in display text with Greek glyphs."""
    s = _GREEK_RE.sub(lambda m: _GREEK[m.group(1)], s)
    s = s.replace("&lt;=", "&#8804;").replace("&gt;=", "&#8805;")
    return normalize_trusted_markup(s)


_EQUATION_MATH_TOKENS = {"Delta": "&#916;", "sum": "&#8721;"}
_EQUATION_MATH_RE = re.compile(
    r"\b(" + "|".join(_EQUATION_MATH_TOKENS) + r")\b"
)


def _equation_math(s):
    """Render the additional ASCII tokens reserved for equation mathematics."""
    return _EQUATION_MATH_RE.sub(
        lambda match: _EQUATION_MATH_TOKENS[match.group(1)], _greek(s)
    )


def _numerical_table_text(markup, evidence):
    """Retain escaped mixed cell text while identifying its numeric evidence."""
    return _NumericalReportText(markup, evidence)


def _assessment_colors(status):
    """Return the shared print palette for assessment banners and context."""
    background, foreground = _ASSESSMENT_PALETTE.get(
        status, _ASSESSMENT_PALETTE["NOT APPLICABLE"]
    )
    return colors.HexColor(background), colors.HexColor(foreground)


class _PaginatedReportTable(Table):
    """A4 data table with bounded fragments and complete tall-row fallback."""

    def split(self, availWidth, availHeight):
        # ReportLab applies rowSplitRange to both its between-row attempt and its
        # in-row fallback. Retain three data rows at each ordinary fragment edge,
        # but only when those groups can themselves fit a complete report frame.
        # Using the full frame (not the current residual height) lets an ordinary
        # table move to the next page without weakening the publication contract.
        self._calc(availWidth, availHeight)
        repeat_rows = self.repeatRows
        if isinstance(repeat_rows, int):
            repeat_count = max(0, repeat_rows)
        else:
            repeat_count = max(repeat_rows) + 1 if repeat_rows else 0
        repeat_count = min(repeat_count, len(self._rowHeights))
        data_count = len(self._rowHeights) - repeat_count

        row_split_range = None
        if data_count >= 6:
            repeated_height = sum(self._rowHeights[:repeat_count])
            leading_height = sum(self._rowHeights[:repeat_count + 3])
            trailing_height = repeated_height + sum(self._rowHeights[-3:])
            if (
                leading_height <= _A4_FRAME_USABLE_HEIGHT + 1e-7
                and trailing_height <= _A4_FRAME_USABLE_HEIGHT + 1e-7
            ):
                row_split_range = (repeat_count + 3, -3)

        self._rowSplitRange = row_split_range
        self._sector_row_split_range = row_split_range
        fragments = super().split(availWidth, availHeight)

        caption_row = getattr(self, "_sector_caption_row", None)
        if caption_row is None or not fragments:
            return fragments

        inherited = (
            "_sector_caption_row",
            "_sector_caption_markup",
            "_sector_continued_caption_markup",
            "_sector_caption_style",
            "_sector_publication_label",
            "_sector_header_row",
            "_sector_data_start",
            "_sector_context_count",
            "_sector_context_labels",
        )
        already_continued = bool(
            getattr(self, "_sector_is_continuation", False)
        )
        for index, fragment in enumerate(fragments):
            for attribute in inherited:
                if hasattr(self, attribute):
                    setattr(fragment, attribute, getattr(self, attribute))
            is_continuation = already_continued or index > 0
            fragment._sector_is_continuation = is_continuation
            # Repeated rows can be shared between ReportLab fragments. Detach
            # the caption row before adding continuation text so the first
            # fragment retains its only destination anchor.
            fragment._cellvalues = list(fragment._cellvalues)
            fragment._cellvalues[caption_row] = list(
                fragment._cellvalues[caption_row]
            )
            markup = (
                self._sector_continued_caption_markup
                if is_continuation
                else self._sector_caption_markup
            )
            fragment._cellvalues[caption_row][0] = Paragraph(
                markup, self._sector_caption_style
            )
        return fragments


def _kaleido_server_api():
    """``(start, stop)`` callables for the kaleido sync server, or ``(None, None)``
    when kaleido (or its sync-server API) is unavailable. Split out so tests can
    stand in a fake server without a real browser."""
    try:
        import kaleido
    except Exception:
        return None, None
    return (getattr(kaleido, "start_sync_server", None),
            getattr(kaleido, "stop_sync_server", None))


def _kaleido_page_path():
    """Create one persistent Plotly launcher page outside Kaleido's temp tree.

    Kaleido normally writes a fresh ``index.html`` in a random temporary folder
    every time its browser starts. Endpoint protection can lock that just-created
    file, which makes report generation time out before the first figure. A stable
    page also avoids repeated temp-file scanning in the packaged desktop app.
    """
    try:
        import kaleido

        generator = kaleido.PageGenerator(mathjax=False)
        html = generator.generate_index()
        configured = (
            os.environ.get("SECTOR_KALEIDO_DIR")
            or os.environ.get("SECTOR_AUTOSAVE_DIR")
        )
        if configured:
            folder = os.path.abspath(configured)
        else:
            base = os.environ.get("LOCALAPPDATA")
            folder = (
                os.path.join(base, "Sector", "kaleido")
                if base
                else os.path.join(os.path.expanduser("~"), ".sector", "kaleido")
            )
        os.makedirs(folder, exist_ok=True)
        page = os.path.join(folder, "plotly_export.html")
        current = None
        try:
            with open(page, "r", encoding="utf-8") as handle:
                current = handle.read()
        except OSError:
            pass
        if current != html:
            with open(page, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(html)
        return page
    except Exception:
        return None


_image_server_started = False
_image_server_lock = threading.Lock()


def _safe_stop(stop):
    try:
        stop(silence_warnings=True)
    except Exception:
        pass


def ensure_image_server():
    """Start the kaleido export server once per process and leave it running.

    With kaleido 1.x each ``to_image`` otherwise spawns and tears down a headless
    browser. The per-report context manager that used to do this paid that cost on
    every report; starting the server once and keeping it alive for the app's
    lifetime means only the first report pays the browser start-up and the rest are
    just render time. Idempotent (started exactly once, even across threads) and
    best-effort: it returns silently -- falling back to one browser per image, or
    the per-image error path -- when kaleido or a browser is unavailable. The report
    build then fails explicitly if a requested engineering figure cannot be embedded.
    The server is stopped at interpreter exit.
    """
    global _image_server_started
    if _image_server_started:
        return
    with _image_server_lock:
        if _image_server_started:
            return
        _image_server_started = True          # attempt exactly once per process
        start, stop = _kaleido_server_api()
        if start is None:
            return                            # nothing to start; per-image fallback
        try:
            page = _kaleido_page_path()
            kwargs = {"page_generator": page} if page else {}
            start(silence_warnings=True, **kwargs)
        except Exception:
            return                            # browser unavailable; per-image fallback
        if stop is not None:
            atexit.register(lambda: _safe_stop(stop))


class _NumberedCanvas(canvas.Canvas):
    """Adds document-control furniture once the final page count is known."""

    def __init__(self, *args, footer="", header="", revision="", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []
        self._bookmark_specs = {}
        self._footer = footer
        self._header = header
        self._revision = revision

    def bookmarkPage(
        self, key, fit="Fit", left=None, top=None, bottom=None, right=None,
        zoom=None,
    ):
        """Record bookmarks so delayed pages receive their real destinations."""
        self._bookmark_specs.setdefault(self._pageNumber, []).append((
            key, fit, left, top, bottom, right, zoom,
        ))
        return super().bookmarkPage(
            key, fit=fit, left=left, top=top, bottom=bottom, right=right,
            zoom=zoom,
        )

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            for spec in self._bookmark_specs.get(self._pageNumber, ()):
                canvas.Canvas.bookmarkPage(
                    self, spec[0], fit=spec[1], left=spec[2], top=spec[3],
                    bottom=spec[4], right=spec[5], zoom=spec[6],
                )
            self._draw_furniture(n)
            super().showPage()
        super().save()

    @staticmethod
    def _fit(text, width, font, size):
        """Ellipsise a document-control label to its available width."""
        text = str(text)
        if pdfmetrics.stringWidth(text, font, size) <= width:
            return text
        suffix = "..."
        while text and pdfmetrics.stringWidth(text + suffix, font, size) > width:
            text = text[:-1]
        return text.rstrip() + suffix

    def _draw_furniture(self, total):
        self.saveState()
        if self._header:
            self.setFont(_FONT, 7.5)
            self.setFillColor(_GREY)
            revision = self._fit(
                f"Rev: {self._revision or '-'}",
                30 * mm,
                _FONT,
                7.5,
            )
            self.drawString(
                20 * mm,
                286 * mm,
                self._fit(self._header, 136 * mm, _FONT, 7.5),
            )
            self.drawRightString(190 * mm, 286 * mm, revision)
            self.setStrokeColor(_LINE)
            self.line(20 * mm, 282 * mm, 190 * mm, 282 * mm)
        self.setFont(_FONT, 8)
        self.setFillColor(_GREY)
        self.drawString(20 * mm, 12 * mm, self._footer)
        self.drawRightString(190 * mm, 12 * mm,
                             "Page %d of %d" % (self._pageNumber, total))
        self.setStrokeColor(_LINE)
        self.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
        self.restoreState()


class _ReportDocTemplate(SimpleDocTemplate):
    """Registers the numbered report sections as PDF outline entries."""

    def afterFlowable(self, flowable):
        key = getattr(flowable, "_sector_bookmark", None)
        if key:
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(
                getattr(flowable, "_sector_outline", key),
                key,
                level=0,
                closed=False,
            )


def _styles():
    ss = getSampleStyleSheet()
    out = {}
    out["title"] = ParagraphStyle("t", parent=ss["Title"], fontSize=20,
                                  fontName=_FONT_BOLD, textColor=_BLUE, spaceAfter=4)
    out["subtitle"] = ParagraphStyle("st", parent=ss["Normal"], fontSize=11,
                                     fontName=_FONT, textColor=_GREY, spaceAfter=2)
    out["h1"] = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=14,
                              fontName=_FONT_BOLD, textColor=_BLUE, spaceBefore=10,
                              spaceAfter=6, keepWithNext=1)
    out["h2"] = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11.5,
                              fontName=_FONT_BOLD, textColor=_BLUE, spaceBefore=8,
                              spaceAfter=4, keepWithNext=1)
    out["body"] = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5,
                                fontName=_FONT, leading=13, spaceAfter=4)
    out["small"] = ParagraphStyle("s", parent=ss["Normal"], fontSize=8.5,
                                 fontName=_FONT, leading=11, textColor=_GREY)
    out["formula"] = ParagraphStyle(
        "f", parent=ss["Normal"], fontSize=9.5, leading=14,
        leftIndent=12, rightIndent=6, spaceBefore=2, spaceAfter=3,
        fontName=_FONT, wordWrap="LTR", splitLongWords=True,
    )
    out["formula_id"] = ParagraphStyle(
        "fi", parent=ss["Normal"], fontSize=8, fontName=_FONT_BOLD,
        leading=11, leftIndent=12, rightIndent=6, textColor=_BLUE,
        spaceBefore=2, spaceAfter=1,
    )
    out["ref"] = ParagraphStyle("r", parent=ss["Normal"], fontSize=8,
                               fontName=_FONT, leading=11, leftIndent=12,
                               rightIndent=6, textColor=_GREY, spaceAfter=6)
    out["publication_ref"] = ParagraphStyle(
        "pr", parent=ss["Normal"], fontSize=8, leading=10,
        fontName=_FONT, textColor=_GREY, spaceBefore=2, spaceAfter=2,
        keepWithNext=1,
    )
    out["publication_caption"] = ParagraphStyle(
        "pc", parent=ss["Normal"], fontSize=8, leading=10,
        fontName=_FONT, textColor=colors.HexColor("#2C2C2A"),
        spaceBefore=2, spaceAfter=2, keepWithNext=1,
    )
    out["formula_symbol"] = ParagraphStyle(
        "fs", parent=ss["Normal"], fontSize=8.1, leading=11,
        leftIndent=18, rightIndent=6, spaceAfter=1, fontName=_FONT,
        wordWrap="LTR", splitLongWords=True,
    )
    return out


_FIG_EXPORT_TIMEOUT_S = 20.0


def _equation_anchor_key(equation_key):
    """Encode a validated equation key without collapsing its separators."""
    # Underscores are outside _EQUATION_KEY_RE, so this replacement is
    # injective while leaving authored hyphens readable in the destination.
    return equation_key.replace(".", "__")


class ReportFigureError(RuntimeError):
    """Raised when a requested engineering figure cannot be embedded."""


class _EquationFlowable(KeepTogether):
    """Indivisible equation whose complete text remains visible to audit probes."""

    def __init__(
        self, content, *, key, variant, contract, anchor, number, section,
        subsection,
    ):
        super().__init__(content)
        self._sector_equation_key = key
        self._sector_equation_variant = variant
        self._sector_equation_symbols = contract.symbols
        self._sector_equation_result_symbol = contract.result_symbol
        self._sector_equation_result_unit = contract.result_unit
        self._sector_equation_substitution_role = contract.substitution_role
        self._sector_equation_anchor = anchor
        self._sector_equation_number = number
        self._sector_equation_section = section
        self._sector_equation_subsection = subsection
        self._sector_equation_roles = tuple(
            child._sector_equation_role for child in content
        )

    def getPlainText(self):
        return " ".join(
            child.getPlainText()
            for child in self._content
            if hasattr(child, "getPlainText")
        )


def _equation_paragraph(markup, style, role, *, symbol=None):
    """Build one auditable row in a standard report equation block."""
    paragraph = Paragraph(markup, style)
    paragraph._sector_equation_role = role
    if symbol is not None:
        paragraph._sector_equation_symbol = symbol
    return paragraph


def _equation_result_unit(unit, result):
    """Retain the canonical unit while naming percentage presentation."""
    if unit == "dimensionless" and "%" in result:
        return "dimensionless; displayed as %"
    return unit


def _fig_png(fig, w_px, h_px, timeout=_FIG_EXPORT_TIMEOUT_S):
    """Export a Plotly figure to PNG bytes off the main thread.

    Returns ``(png_bytes, timed_out)``: ``png_bytes`` is the PNG (``None`` when export
    failed or timed out), and ``timed_out`` is True when the worker was still running
    at the join timeout. kaleido's headless browser can block indefinitely in a bad
    state, so a timeout means it is wedged and the caller should STOP retrying -- each
    further export would block for the full timeout again.
    """
    box = {}

    def _work():
        try:
            box["v"] = fig.to_image(format="png", width=w_px, height=h_px, scale=2)
        except Exception:
            box["v"] = None

    worker = threading.Thread(target=_work, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return None, True
    return box.get("v"), False


def _fmt(v, nd=3):
    if v is None:
        return "-"
    if isinstance(v, float) and not math.isfinite(v):
        return "-inf" if math.isinf(v) and v < 0.0 else "inf"
    return f"{v:.{nd}f}"


def _fmt_sig(v, sig=6):
    """Format small engineering values without rounding nonzero evidence to zero."""
    if v is None:
        return "-"
    if isinstance(v, float) and not math.isfinite(v):
        return "-inf" if math.isinf(v) and v < 0.0 else "inf"
    return f"{v:.{sig}g}"


_pct = viz.pct   # shared util-% formatter (see app/viz.py); keeps report == screen


def _report_action_set_text(inp, family):
    """Escape user-entered action provenance before ReportLab paragraph parsing."""
    record = presentation.action_set(inp, family)
    parts = [_html_escape(record["id"] or "ID NOT SET")]
    if record["type"]:
        parts.append(_html_escape(record["type"]))
    if record["source"]:
        parts.append("Source: " + _html_escape(record["source"]))
    return _LiteralReportText(" | ".join(parts))


def _demand_resistance_verdict(ok):
    """Verdict for a genuine demand-versus-resistance equation."""
    return "PASS" if ok else "FAIL"


class ReportBuilder:
    """Builds the PDF into ``buffer`` from ``meta``, ``inp`` and ``out``."""

    def __init__(
        self,
        buffer,
        meta,
        inp,
        out,
        version="",
        figures=True,
        progress=None,
        qa_appendix=True,
    ):
        self.buffer = buffer
        self.meta = meta or {}
        self.inp = inp
        self.out = out or {}
        # Keep the complete table-level payload available while detail renderers
        # are pointed at each current action in turn.
        self._base_inp = inp
        self._base_out = out or {}
        self.version = version
        self.figures = figures
        self.qa_appendix = bool(qa_appendix)
        self._progress = progress
        self.s = _styles()
        self.flow = []
        self._chapter = 0
        self._subsection = 0
        self._equation_number = 0
        self._equations = {}
        self._export_hung = False   # set once a kaleido export hits the join timeout
        self._table_section_context = None
        self._table_subsection_context = None
        self._table_assessment_context = None
        self._publication_counter = PublicationCounter("0")
        self._publication_section_title = "Document control"
        self._publication_subsection_title = None

    def _case_contexts(self, family):
        """Return ordered ``(case_input, case_results)`` report contexts."""
        entries = self._base_out.get(f"{family}_cases")
        if entries is not None:
            contexts = []
            for entry in entries:
                actions = entry.get("actions") or {}
                if family == "plastic":
                    case_inp = case_analysis.plastic_case_input(
                        self._base_inp, actions
                    )
                else:
                    case_inp = case_analysis.elastic_case_input(
                        self._base_inp, actions
                    )
                case_inp["_report_case_actions"] = dict(actions)
                contexts.append((case_inp, entry.get("results") or {}))
            return contexts

        # The current direct report API also accepts one calculation input/result
        # mapping without a surrounding action table.
        result_key = "elastic" if family == "elastic" else None
        active = (
            result_key in self._base_out
            if result_key is not None
            else any(
                key in self._base_out
                for key in (
                    "plastic", "shear", "torsion", "combined",
                    "minimum_reinforcement", "transverse_reinforcement",
                )
            )
        )
        return [(self._base_inp, self._base_out)] if active else []

    def _result_values(self, key):
        family = "elastic" if key == "elastic" else "plastic"
        return [
            result[key]
            for _, result in self._case_contexts(family)
            if key in result
        ]

    def _case_register(self, family):
        """Escaped case register for cover-page document control."""
        contexts = self._case_contexts(family)
        return _LiteralReportText("; ".join(
            _report_action_set_text(case_inp, family)
            for case_inp, _ in contexts
        ))

    def _tick(self, frac, text):
        if self._progress is not None:
            self._progress(frac, text)

    # -- flowable helpers --------------------------------------------------
    def _h1(self, text):
        self._chapter += 1
        self._subsection = 0
        self._equation_number = 0
        numbered = f"{self._chapter}. {text}"
        self._table_section_context = _greek(
            f"Section {self._chapter}: {text}"
        )
        self._table_subsection_context = None
        self._table_assessment_context = None
        self._publication_counter.enter_section(str(self._chapter))
        self._publication_section_title = Paragraph(
            _greek(str(text)), self.s["small"]
        ).getPlainText().strip()
        self._publication_subsection_title = None
        heading = Paragraph(_greek(numbered), self.s["h1"])
        heading._sector_bookmark = f"sector-section-{self._chapter}"
        # The outline API does not parse Paragraph markup or numeric entities.
        # Reuse the Paragraph's decoded plain text so escaped user identifiers
        # appear in bookmarks exactly as they do on the page.
        heading._sector_outline = heading.getPlainText()
        self.flow.append(heading)

    def _h2(self, text):
        self._subsection += 1
        self._table_subsection_context = _greek(f"Subsection: {text}")
        self._publication_subsection_title = Paragraph(
            _greek(str(text)), self.s["small"]
        ).getPlainText().strip()
        self.flow.append(Paragraph(_greek(text), self.s["h2"]))

    def _p(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["body"]))

    def _small(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["small"]))

    def _status_block(self, text, status):
        """Add a prominent, print-readable assessment banner."""
        bg, fg = _assessment_colors(status)
        self._table_assessment_context = (_greek(f"Assessment: {text}"), status)
        style = ParagraphStyle(
            "status", parent=self.s["body"], fontName=_FONT_BOLD,
            textColor=fg, leading=13,
        )
        table = Table(
            [[Paragraph(_greek(text), style)]],
            colWidths=[160 * mm],
            hAlign="LEFT",
            spaceBefore=2,
            spaceAfter=6,
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 0.8, fg),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        table._sector_status_banner = True
        self.flow.append(KeepTogether(table))

    def _case_line(self, family, title=""):
        self._small("<b>Case:</b> " + _report_action_set_text(self.inp, family))
        actions = self.inp.get("_report_case_actions") or {}
        if family == "plastic" and actions:
            self._table(
                [[
                    "N<sub>Ed</sub> (kN)", "M<sub>x,Ed</sub> (kNm)",
                    "M<sub>y,Ed</sub> (kNm)", "V<sub>x,Ed</sub> (kN)",
                    "V<sub>y,Ed</sub> (kN)",
                    "T<sub>Ed</sub> (kNm)",
                ], [
                    _fmt(actions.get("n_ed_kn"), 3),
                    _fmt(actions.get("mx_ed_knm"), 3),
                    _fmt(actions.get("my_ed_knm"), 3),
                    _fmt(actions.get("vx_ed_kn"), 3),
                    _fmt(actions.get("vy_ed_kn"), 3),
                    _fmt(actions.get("t_ed_knm"), 3),
                ]],
                [28 * mm] * 6,
                font=6.9,
            )
            if title.startswith(("Shear", "Combined", "Torsion")):
                self._small(
                    "<b>Shear tension faces:</b> V<sub>x,Ed</sub> = "
                    f"{_html_escape(actions.get('vx_face', 'auto'))}; "
                    "V<sub>y,Ed</sub> = "
                    f"{_html_escape(actions.get('vy_face', 'auto'))}."
                )
            if "minimum reinforcement" in title.lower():
                self._small(
                    "<b>Minimum reinforcement:</b> "
                    f"{'selected' if actions.get('check_minimum_reinforcement') else 'not selected'}."
                )
        elif family == "elastic" and actions:
            self._table(
                [[
                    "Part", "N<sub>Ed</sub> (kN)",
                    "M<sub>x,Ed</sub> (kNm)", "M<sub>y,Ed</sub> (kNm)",
                ], [
                    "Long-term", _fmt(actions.get("n_long_ed_kn"), 3),
                    _fmt(actions.get("mx_long_ed_knm"), 3),
                    _fmt(actions.get("my_long_ed_knm"), 3),
                ], [
                    "Short-term", _fmt(actions.get("n_short_ed_kn"), 3),
                    _fmt(actions.get("mx_short_ed_knm"), 3),
                    _fmt(actions.get("my_short_ed_knm"), 3),
                ]],
                [28 * mm, 47 * mm, 47 * mm, 47 * mm],
                font=7.2,
            )
            self._small(
                "<b>Outputs:</b> stresses are always reported; crack width "
                f"{'requested' if actions.get('calculate_crack_width') else 'not requested'}."
            )

    def _case_heading(self, title, family):
        start = len(self.flow)
        case_id = presentation.action_set(self.inp, family)["id"] or "ID NOT SET"
        self._h1(f"{title} - {_html_escape(case_id)}")
        self._case_line(family, title)
        self._keep_from(start + 1)

    def _table_context_rows(self, column_count, row_offset=0):
        """Freeze active publication context as complete-width table rows."""
        entries = []
        if self._table_section_context is not None:
            entries.append((
                "section", self._table_section_context, _HEAD_BG, _BLUE,
            ))
        if self._table_subsection_context is not None:
            entries.append((
                "subsection", self._table_subsection_context,
                colors.HexColor("#F7F8FA"), _GREY,
            ))
        if self._table_assessment_context is not None:
            markup, status = self._table_assessment_context
            background, foreground = _assessment_colors(status)
            entries.append(("assessment", markup, background, foreground))

        rows = []
        commands = []
        labels = []
        for local_index, (role, markup, background, foreground) in enumerate(entries):
            row_index = row_offset + local_index
            style = ParagraphStyle(
                f"table-context-{role}",
                parent=self.s["small"],
                fontName=_FONT_BOLD,
                fontSize=_MIN_REPORT_TABLE_FONT,
                leading=_MIN_REPORT_TABLE_FONT + 2,
                textColor=foreground,
            )
            paragraph = Paragraph(markup, style)
            labels.append(paragraph.getPlainText())
            rows.append([paragraph] + [""] * (column_count - 1))
            commands.extend([
                ("SPAN", (0, row_index), (-1, row_index)),
                ("BACKGROUND", (0, row_index), (-1, row_index), background),
                ("VALIGN", (0, row_index), (-1, row_index), "MIDDLE"),
                ("LEFTPADDING", (0, row_index), (-1, row_index), 4),
                ("RIGHTPADDING", (0, row_index), (-1, row_index), 4),
                ("TOPPADDING", (0, row_index), (-1, row_index), 3),
                ("BOTTOMPADDING", (0, row_index), (-1, row_index), 3),
            ])
        return rows, commands, tuple(labels)

    def _results_overview(self):
        rows = presentation.multi_case_summary_rows(
            self._base_inp, self._base_out
        )
        governing = presentation.summary_governing_case_flags(rows)
        self._h2("Results overview")
        self._small(
            "Demand-versus-resistance checks retain their individual verdicts. "
            "Output-only quantities and the project as a whole have no verdict."
        )
        data = [[
            "Check", "Action set", "Status", "Result", "Criterion", "Gov."
        ]]
        data.extend([
            [
                row["check"], _html_escape(row["case"]), row["status"],
                row["result"], row["criterion"], "YES" if is_governing else "-",
            ]
            for row, is_governing in zip(rows, governing)
        ])
        body = ParagraphStyle(
            "summary-cell", parent=self.s["body"], fontSize=7.2,
            fontName=_FONT, leading=9.2,
        )
        head = ParagraphStyle(
            "summary-head", parent=body, fontName=_FONT_BOLD,
        )
        formatted = []
        for index, row in enumerate(data):
            style = head if index == 0 else body
            formatted.append([
                Paragraph(_greek(str(cell)), style) for cell in row
            ])
        table_item = self._publication_counter.issue(
            "Table", "Results overview across calculated checks"
        )
        self.flow.append(Paragraph(
            f'See <link href="#{table_item.anchor}">{table_item.label}</link>.',
            self.s["publication_ref"],
        ))
        caption_markup = (
            f'<a name="{table_item.anchor}"/><b>{table_item.label}.</b> '
            f"{_greek(_html_escape(table_item.caption))}"
        )
        continuation_markup = (
            f"<b>{table_item.label} (continued).</b> "
            f"{_greek(_html_escape(table_item.caption))}"
        )
        caption_row = [[
            Paragraph(caption_markup, self.s["publication_caption"])
        ] + [""] * (len(formatted[0]) - 1)]
        context_rows, context_style, context_labels = self._table_context_rows(
            len(formatted[0]), row_offset=1
        )
        context_count = len(context_rows)
        formatted = caption_row + context_rows + formatted
        header_row = 1 + context_count
        table = _PaginatedReportTable(
            formatted,
            colWidths=[42 * mm, 25 * mm, 23 * mm, 31 * mm, 36 * mm, 13 * mm],
            repeatRows=1 + context_count + 1,
            hAlign="LEFT",
            splitByRow=1,
            splitInRow=1,
        )
        style = [
            ("SPAN", (0, 0), (-1, 0)),
            ("GRID", (0, 1), (-1, -1), 0.4, _LINE),
            ("BACKGROUND", (0, header_row), (-1, header_row), _HEAD_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
        ]
        style.extend(context_style)
        fills = {
            "PASS": colors.HexColor("#E8F5E9"),
            "FAIL": colors.HexColor("#FDECEC"),
            "INVALID": colors.HexColor("#FDECEC"),
            "REVIEW": colors.HexColor("#FFF4D6"),
            "NOT ASSESSED": colors.HexColor("#FFF4D6"),
            "NOT RUN": colors.HexColor("#EEF2F6"),
            "NOT APPLICABLE": colors.HexColor("#EEF2F6"),
        }
        for row_index, row in enumerate(rows, start=header_row + 1):
            fill = fills.get(row["status"])
            if fill is not None:
                style.append(("BACKGROUND", (2, row_index), (2, row_index), fill))
        table.setStyle(TableStyle(style))
        table._sector_context_labels = context_labels
        table._sector_context_count = context_count
        table._sector_caption_row = 0
        table._sector_caption_markup = caption_markup
        table._sector_continued_caption_markup = continuation_markup
        table._sector_caption_style = self.s["publication_caption"]
        table._sector_is_continuation = False
        table._sector_publication_label = table_item.label
        table._sector_header_row = header_row
        table._sector_data_start = header_row + 1
        table._sector_results_overview = True
        self.flow.append(table)
        self._small(
            "Gov. marks the highest PASS/FAIL utilisation for each check; ties "
            "remain marked. NOT APPLICABLE means the row action is zero."
        )
        self._gap(4)

    def _gap(self, h=4):
        self.flow.append(Spacer(1, h))

    def _page_break(self):
        """Start a page without carrying a layout-only trailing gap onto it."""
        while self.flow:
            trailing = self.flow[-1]
            if isinstance(trailing, Spacer):
                self.flow.pop()
                continue
            if isinstance(trailing, KeepTogether):
                while trailing._content and isinstance(trailing._content[-1], Spacer):
                    trailing._content.pop()
                if not trailing._content:
                    self.flow.pop()
                    continue
            break
        self.flow.append(NotAtTopPageBreak())

    def _keep_from(self, start):
        """Keep the flowables added since ``start`` together when they fit a page."""
        block = []
        for item in self.flow[start:]:
            # _table() already protects a short table with KeepTogether. Nesting
            # that wrapper makes ReportLab measure the inner block as effectively
            # page-height, which forces every following semantic group onto a new
            # page. The outer group provides the protection here, so flatten it.
            if isinstance(item, KeepTogether) and not isinstance(
                item, _EquationFlowable
            ):
                block.extend(item._content)
            else:
                block.append(item)
        self.flow[start:] = [KeepTogether(block)]

    def _formula(
        self,
        expr,
        ref=None,
        subst=None,
        result=None,
        *,
        equation_key,
        equation_variant=None,
        equation_spec=None,
        note=None,
        references=(),
        numbered=True,
    ):
        """Append one stable, source-labelled and cross-referenceable equation."""
        if self._chapter < 1:
            raise ValueError("A report equation requires an active section.")
        equation_key = str(equation_key)
        if not _EQUATION_KEY_RE.fullmatch(equation_key):
            raise ValueError(f"Invalid report equation key: {equation_key!r}.")
        if equation_spec is None:
            contract = report_equation_contract.equation_contract(
                equation_key, equation_variant
            )
        else:
            if equation_variant is not None:
                raise ValueError(
                    "An explicit equation contract cannot also select a variant."
                )
            if not isinstance(
                equation_spec, report_equation_contract.EquationContract
            ):
                raise TypeError("equation_spec must be an EquationContract.")
            contract = equation_spec
        report_equation_contract.validate_equation_payload(
            equation_key,
            contract,
            expression=expr,
            substitution=subst,
            applicability_note=note,
            result=result,
        )
        scope = (self._chapter, self._subsection, equation_key)
        if scope in self._equations:
            raise ValueError(
                f"Duplicate report equation key in subsection: {equation_key}."
            )
        targets = []
        for target_key in references:
            target = self._equations.get(
                (self._chapter, self._subsection, str(target_key))
            )
            if target is None:
                raise ValueError(
                    f"Equation {equation_key} references unknown prior key "
                    f"{target_key!r} in its subsection."
                )
            targets.append(target)

        source = ref if ref is not None else _DERIVED_EQUATION_SOURCE
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"Equation {equation_key} requires source text.")

        number = None
        if numbered:
            self._equation_number += 1
            number = f"{self._chapter}.{self._equation_number}"
        anchor = (
            f"sector-equation-{self._chapter}-{self._subsection}-"
            + _equation_anchor_key(equation_key)
        )
        record = {
            "key": equation_key,
            "anchor": anchor,
            "number": number,
        }
        self._equations[scope] = record

        public = f"EQ-{equation_key.upper()}"
        identity = (
            f"Equation ({number}) | {public}"
            if number is not None else public
        )
        content = [
            _equation_paragraph(
                f'<a name="{anchor}"/><b>{identity}</b>',
                self.s["formula_id"],
                "identity",
            ),
            _equation_paragraph(
                f"<b>Symbolic expression:</b> {_equation_math(expr)}",
                self.s["formula"],
                "symbolic-expression",
            ),
        ]
        if subst:
            content.append(_equation_paragraph(
                f"<b>Numerical substitution:</b> {_equation_math(subst)}",
                self.s["formula"],
                "numerical-substitution",
            ))
        if note:
            content.append(_equation_paragraph(
                f"<b>Applicability / method note:</b> {_greek(note)}",
                self.s["formula"],
                "applicability-note",
            ))
        if result:
            display_unit = _equation_result_unit(contract.result_unit, result)
            content.append(_equation_paragraph(
                "<b>Result &#8212; "
                f"{_equation_math(contract.result_symbol)} "
                f"[{_greek(display_unit)}]:</b> {_equation_math(result)}",
                self.s["formula"],
                "result",
            ))
        content.append(_equation_paragraph(
            "<b>Symbols:</b>", self.s["formula_symbol"], "symbols-heading"
        ))
        for symbol in contract.symbols:
            content.append(_equation_paragraph(
                f"{_equation_math(symbol.markup)} &#8212; "
                f"{_greek(symbol.meaning)} [{_greek(symbol.unit)}]",
                self.s["formula_symbol"],
                "symbol",
                symbol=symbol,
            ))
        if targets:
            links = []
            for target in targets:
                label = (
                    f"Equation ({target['number']})"
                    if target["number"] else f"EQ-{target['key'].upper()}"
                )
                links.append(
                    f'<link href="#{target["anchor"]}">{label}</link>'
                )
            content.append(_equation_paragraph(
                "<b>Uses:</b> " + ", ".join(links),
                self.s["ref"],
                "uses",
            ))
        content.append(_equation_paragraph(
            _greek(f"<b>Source / method note:</b> {source}"),
            self.s["ref"],
            "source",
        ))
        self.flow.append(_EquationFlowable(
            content,
            key=equation_key,
            variant=equation_variant,
            contract=contract,
            anchor=anchor,
            number=number,
            section=self._chapter,
            subsection=self._subsection,
        ))

    @staticmethod
    def _table_column_floors(
        cells, markups, literals, numeric_sources, widths, header
    ):
        """Return per-column floors from authored roles and rendered content."""
        floors = []
        first_body_row = 1 if header else 0
        for column, nominal_width in enumerate(widths):
            authored_width = max(
                0.0,
                float(nominal_width) - 2 * _REPORT_TABLE_HORIZONTAL_PADDING,
            )
            required = 0.0
            for row_index, row in enumerate(cells):
                paragraph = row[column]
                numeric_width = 0.0
                numeric_source = numeric_sources[row_index][column]
                if row_index >= first_body_row and (
                    numeric_source is not None
                    or not literals[row_index][column]
                ):
                    # Work from markup-aware source text. Replacing tags with spaces
                    # retains boundaries such as ``123<br/>method`` that
                    # Paragraph.getPlainText() flattens to ``123method``.
                    source_text = (
                        _greek(numeric_source)
                        if numeric_source is not None
                        else markups[row_index][column]
                    )
                    atom_text = html_lib.unescape(
                        re.sub(r"<[^>]*>", " ", source_text)
                    )
                    numeric_width = max(
                        (
                            pdfmetrics.stringWidth(
                                match.group(0),
                                paragraph.style.fontName,
                                paragraph.style.fontSize,
                            )
                            for match in _NUMERIC_TABLE_WORD.finditer(atom_text)
                        ),
                        default=0.0,
                    )
                # ReportLab losslessly wraps long words. The authored width is the
                # semantic floor for prose and machine identities; numeric evidence
                # retains its independently measured atom.
                required = max(
                    required,
                    min(paragraph.minWidth(), authored_width),
                    numeric_width,
                )
            floors.append(required + 2 * _REPORT_TABLE_HORIZONTAL_PADDING)
        return floors

    @staticmethod
    def _reallocate_table_widths(preferred, floors):
        """Shrink preferred widths proportionally without crossing any floor."""
        if sum(floors) > _A4_CONTENT_WIDTH + 1e-7:
            return None
        target = [
            max(float(width), floor)
            for width, floor in zip(preferred, floors)
        ]
        if sum(target) <= _A4_CONTENT_WIDTH + 1e-7:
            return target
        adjustable = [width - floor for width, floor in zip(target, floors)]
        adjustable_total = sum(adjustable)
        if adjustable_total <= 0.0:
            return list(floors)
        available_growth = _A4_CONTENT_WIDTH - sum(floors)
        return [
            floor + available_growth * growth / adjustable_total
            for floor, growth in zip(floors, adjustable)
        ]

    @staticmethod
    def _table_panels(floors, repeat_cols):
        """Partition a wide table while retaining its leading identity columns."""
        column_count = len(floors)
        if sum(floors) <= _A4_CONTENT_WIDTH + 1e-7:
            return [tuple(range(column_count))]
        repeat_count = max(0, min(int(repeat_cols), column_count - 1))
        identity = tuple(range(repeat_count))
        panels = []
        current = []
        for column in range(repeat_count, column_count):
            proposed = (*identity, *current, column)
            if sum(floors[index] for index in proposed) > _A4_CONTENT_WIDTH + 1e-7:
                if not current:
                    raise ValueError(
                        "A report table contains numeric evidence wider than the "
                        "available A4 content width."
                    )
                panels.append((*identity, *current))
                current = [column]
                if (
                    sum(floors[index] for index in (*identity, column))
                    > _A4_CONTENT_WIDTH + 1e-7
                ):
                    raise ValueError(
                        "A report table contains numeric evidence wider than the "
                        "available A4 content width."
                    )
            else:
                current.append(column)
        panels.append((*identity, *current))
        return panels

    def _table(
        self,
        data,
        widths,
        header=True,
        font=8.5,
        keep=True,
        repeat_cols=1,
        caption=None,
    ):
        if not data or not data[0]:
            raise ValueError("A report table requires at least one cell.")
        column_count = len(data[0])
        if any(len(row) != column_count for row in data):
            raise ValueError("Every report table row must retain the same columns.")
        if len(widths) != column_count:
            raise ValueError("Report table widths must match the column count.")
        font = max(float(font), _MIN_REPORT_TABLE_FONT)
        body = ParagraphStyle("c", parent=self.s["body"], fontSize=font,
                              fontName=_FONT, leading=font + 2)
        head = ParagraphStyle("ch", parent=body, fontName=_FONT_BOLD)
        rows = []
        markups = []
        literals = []
        numeric_sources = []
        for r, row in enumerate(data):
            cells = []
            rendered_row = []
            literal_row = []
            numeric_source_row = []
            for ci, cell in enumerate(row):
                st = head if (header and r == 0) else body
                st = ParagraphStyle("x", parent=st,
                                    alignment=TA_LEFT if ci == 0 else TA_CENTER)
                markup = _greek(str(cell))
                cells.append(Paragraph(markup, st))
                rendered_row.append(markup)
                literal_row.append(isinstance(cell, _LiteralReportText))
                numeric_source_row.append(
                    getattr(cell, "_sector_numeric_evidence", None)
                )
            rows.append(cells)
            markups.append(rendered_row)
            literals.append(literal_row)
            numeric_sources.append(numeric_source_row)
        floors = self._table_column_floors(
            rows, markups, literals, numeric_sources, widths, header
        )
        panels = self._table_panels(floors, repeat_cols)
        subject = (
            self._publication_subsection_title
            or self._publication_section_title
            or "Published data"
        )
        if caption is None:
            first_header = rows[0][0].getPlainText().strip() if header else "Data"
            caption = f"Published evidence for {subject}"
            if first_header.lower() not in subject.lower():
                caption += f": {first_header}"
        table_item = self._publication_counter.issue("Table", str(caption))
        self.flow.append(Paragraph(
            f'See <link href="#{table_item.anchor}">{table_item.label}</link>.',
            self.s["publication_ref"],
        ))
        # A long table (the sweep / per-bar tables) may split across pages; a short
        # one is kept whole so it never strands a row on an otherwise empty page.
        # Any table can outgrow one page when it contains user-pasted geometry or
        # reinforcement. Repeat the labelled header regardless of whether the normal
        # short-table path first tries to keep the table together.
        for panel_number, columns in enumerate(panels, start=1):
            panel_floors = [floors[index] for index in columns]
            panel_widths = self._reallocate_table_widths(
                [widths[index] for index in columns], panel_floors
            )
            if panel_widths is None:
                raise ValueError("Unable to fit a report table column panel.")
            if len(panels) > 1:
                labels = (
                    [rows[0][index].getPlainText() for index in columns]
                    if header else [f"Column {index + 1}" for index in columns]
                )
                self._small(
                    f"<b>Column panel {panel_number} of {len(panels)}:</b> "
                    + ", ".join(_html_escape(label) for label in labels)
                )
            source_rows = [[row[index] for index in columns] for row in rows]
            panel_note = (
                f" Column panel {panel_number} of {len(panels)}."
                if len(panels) > 1
                else ""
            )
            continued = panel_number > 1
            visible_label = (
                f"{table_item.label} (continued)"
                if continued
                else table_item.label
            )
            anchor = f'<a name="{table_item.anchor}"/>' if not continued else ""
            caption_markup = (
                f"{anchor}<b>{visible_label}.</b> "
                f"{_greek(_html_escape(table_item.caption))}"
                f"{_greek(_html_escape(panel_note))}"
            )
            continuation_markup = (
                f"<b>{table_item.label} (continued).</b> "
                f"{_greek(_html_escape(table_item.caption))}"
                f"{_greek(_html_escape(panel_note))}"
            )
            caption_row = [[
                Paragraph(caption_markup, self.s["publication_caption"])
            ] + [""] * (len(columns) - 1)]
            context_rows, context_style, context_labels = self._table_context_rows(
                len(columns), row_offset=1
            )
            context_count = len(context_rows)
            panel_rows = caption_row + context_rows + source_rows
            header_row = 1 + context_count if header else None
            repeat_rows = 1 + context_count + (1 if header else 0)
            table = _PaginatedReportTable(
                panel_rows,
                colWidths=panel_widths,
                hAlign="LEFT",
                repeatRows=repeat_rows,
                splitByRow=1,
                splitInRow=1,
            )
            table._sector_source_columns = tuple(columns)
            table._sector_panel_number = panel_number
            table._sector_panel_count = len(panels)
            table._sector_width_floors = tuple(panel_floors)
            table._sector_font_size = font
            table._sector_context_labels = context_labels
            table._sector_context_count = context_count
            table._sector_caption_row = 0
            table._sector_caption_markup = caption_markup
            table._sector_continued_caption_markup = continuation_markup
            table._sector_caption_style = self.s["publication_caption"]
            table._sector_is_continuation = continued
            table._sector_publication_label = table_item.label
            table._sector_header_row = header_row
            table._sector_data_start = repeat_rows
            table_style = [
                ("SPAN", (0, 0), (-1, 0)),
                ("GRID", (0, 1), (-1, -1), 0.4, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1),
                 _REPORT_TABLE_HORIZONTAL_PADDING),
                ("RIGHTPADDING", (0, 0), (-1, -1),
                 _REPORT_TABLE_HORIZONTAL_PADDING),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
            if header:
                table_style.append(
                    ("BACKGROUND", (0, header_row), (-1, header_row), _HEAD_BG)
                )
            table_style.extend(context_style)
            table.setStyle(TableStyle(table_style))
            self.flow.append(KeepTogether(table) if keep else table)
            self._gap(4)

    def _fig(self, fig, w_mm=150, h_mm=95, caption=None):
        if not self.figures:
            return
        # Once an export has wedged the browser (a full-timeout hang), stop trying:
        # every further _fig_png would block for the whole timeout again.
        if self._export_hung:
            raise ReportFigureError(
                "Engineering-figure export previously timed out; report not created."
            )
        png, timed_out = _fig_png(fig, int(w_mm * 3.78), int(h_mm * 3.78))
        if timed_out:
            self._export_hung = True
        if png is None:
            detail = "timed out" if timed_out else "failed"
            raise ReportFigureError(
                f"Engineering-figure export {detail}; report not created."
            )
        if caption is None:
            layout = getattr(fig, "layout", None)
            title = getattr(getattr(layout, "title", None), "text", None)
            title = Paragraph(
                _greek(str(title or "")), self.s["small"]
            ).getPlainText().strip()
            caption = (
                title
                or self._publication_subsection_title
                or self._publication_section_title
                or "Engineering figure"
            )
        figure_item = self._publication_counter.issue("Figure", str(caption))
        reference = Paragraph(
            f'See <link href="#{figure_item.anchor}">{figure_item.label}</link>.',
            self.s["publication_ref"],
        )
        caption_flowable = Paragraph(
            f'<a name="{figure_item.anchor}"/><b>{figure_item.label}.</b> '
            f"{_greek(_html_escape(figure_item.caption))}",
            self.s["publication_caption"],
        )
        figure_table = Table(
            [
                [reference],
                [Image(io.BytesIO(png), width=w_mm * mm, height=h_mm * mm)],
                [caption_flowable],
            ],
            colWidths=[w_mm * mm],
            hAlign="LEFT",
            splitByRow=0,
            splitInRow=0,
        )
        figure_table.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        figure_table._sector_publication_label = figure_item.label
        self.flow.append(figure_table)
        self._gap(4)

    # -- build -------------------------------------------------------------
    def build(self):
        # Reuse the one process-wide kaleido server (started on the first report and
        # left running) rather than starting and stopping one per report. A
        # tables-only report renders no figures, so it never starts a browser.
        if self.figures:
            ensure_image_server()
        self._tick(0.05, "Cover and conventions...")
        self._cover()
        self._conventions()
        self._theory()
        self._tick(0.2, "Section and materials...")
        self._inputs()
        if self._base_out.get("clear_spacing") is not None:
            self.flow.append(NotAtTopPageBreak())
            self.inp, self.out = self._base_inp, self._base_out
            self._clear_spacing()
        jobs = []
        for case_inp, case_out in self._case_contexts("plastic"):
            case_id = presentation.action_set(case_inp, "plastic")["id"] or "-"
            for key, label, method in (
                ("plastic", "Plastic capacity", "_plastic"),
                ("minimum_reinforcement", "Minimum reinforcement",
                 "_minimum_reinforcement"),
                ("transverse_reinforcement", "Shear/torsion link detailing",
                 "_transverse_reinforcement"),
                ("shear", "Shear resistance", "_shear"),
                ("torsion", "Torsion resistance", "_torsion"),
                ("combined", "Combined M-V-T", "_combined"),
            ):
                if key not in case_out:
                    continue
                if (
                    key == "combined"
                    and not case_out[key].get("valid")
                    and not case_out[key].get("biaxial")
                ):
                    continue
                jobs.append((
                    case_inp, case_out, f"{label} - {case_id}...", method, True
                ))
        for case_inp, case_out in self._case_contexts("elastic"):
            case_id = presentation.action_set(case_inp, "elastic")["id"] or "-"
            if "elastic" in case_out:
                jobs.extend([
                    (case_inp, case_out,
                     f"Elastic stresses - {case_id}...", "_elastic", True),
                    (case_inp, case_out,
                     f"Cracking - {case_id}...", "_cracking", False),
                ])

        try:
            for index, (case_inp, case_out, label, method, new_page) in enumerate(jobs):
                self.inp, self.out = case_inp, case_out
                fraction = 0.42 + 0.5 * (index / max(len(jobs), 1))
                self._tick(fraction, label)
                if new_page:
                    self.flow.append(NotAtTopPageBreak())
                getattr(self, method)()
        finally:
            self.inp, self.out = self._base_inp, self._base_out
        if self._base_out.get("fatigue") is not None:
            self._tick(0.88, "Grouped fatigue...")
            self.flow.append(NotAtTopPageBreak())
            self._fatigue()
        if self._base_out.get("bridge") is not None:
            self._tick(0.9, "Independent bridge calculations...")
            self.flow.append(NotAtTopPageBreak())
            self._bridge()
        if self.qa_appendix:
            self._appendix()
        self._tick(0.92, "Writing PDF...")
        revision_id = short_revision(self.meta.get("source_revision"))
        footer = f"Sector {self.version}  -  {revision_id}  -  {SECTOR_LICENSEE}".strip()
        project = str(self.meta.get("proj_no", "")).strip() or "-"
        section = str(self.meta.get("section", "")).strip() or "-"
        revision = str(self.meta.get("rev", "")).strip()
        active_families = [
            family
            for family in ("plastic", "elastic")
            if self._case_contexts(family)
        ]
        cases = [
            presentation.action_set(case_inp, family)["id"]
            for family in active_families
            for case_inp, _ in self._case_contexts(family)
            if presentation.action_set(case_inp, family)["id"]
        ]
        cases.extend([
            str(fatigue_presentation.value(spectrum, "spectrum_name", ""))
            for spectrum in fatigue_presentation.items(
                self._base_out.get("fatigue"), "spectra"
            )
            if str(fatigue_presentation.value(
                spectrum, "spectrum_name", ""
            )).strip()
        ])
        case_text = " / ".join(cases) or "-"
        header = (
            f"Project: {project}  |  Section: {section}  |  Cases: {case_text}"
        )
        title = f"Sector cross-section report - {project} - {section}"
        doc = _ReportDocTemplate(self.buffer, pagesize=A4,
                                 leftMargin=20 * mm, rightMargin=20 * mm,
                                 topMargin=25 * mm, bottomMargin=20 * mm,
                                 title=title)
        doc.build(self.flow,
                  canvasmaker=lambda *a, **k: _NumberedCanvas(
                      *a,
                      footer=footer,
                      header=header,
                      revision=revision,
                      **k,
                  ))
        self._tick(1.0, "Done")

    # -- sections ----------------------------------------------------------
    def _cover(self):
        m = self.meta
        self.flow.append(Paragraph("Cross-section analysis report", self.s["title"]))
        self.flow.append(Paragraph("Reinforced-concrete / prestressed section "
                                   "(Sector)", self.s["subtitle"]))
        self._gap(8)
        date = m.get("date") or datetime.date.today().isoformat()
        rows = [["Field", "Value"],
                ["Project no.", _html_escape(m.get("proj_no", ""))],
                ["Project name", _html_escape(m.get("proj_name", ""))],
                ["Section", _html_escape(m.get("section", ""))],
                ["Revision", _html_escape(m.get("rev", ""))],
                ["Prepared by", _html_escape(m.get("author", ""))],
                ["Date", _html_escape(date)],
                ["Tool version", self.version or "-"],
                ["Source revision", short_revision(m.get("source_revision"))],
                [
                    "Report content",
                    (
                        "Default report + QA appendix"
                        if self.qa_appendix else "Default report"
                    ),
                ]]
        if self._case_contexts("plastic"):
            rows.append([
                "Plastic analysis cases",
                self._case_register("plastic"),
            ])
        if self._case_contexts("elastic"):
            rows.append([
                "Elastic analysis cases",
                self._case_register("elastic"),
            ])
        fatigue = self._base_out.get("fatigue")
        if fatigue is not None:
            rows.append([
                "Fatigue spectra",
                _LiteralReportText("; ".join(
                    _html_escape(str(fatigue_presentation.value(
                        spectrum, "spectrum_name", "-"
                    )))
                    for spectrum in fatigue_presentation.items(
                        fatigue, "spectra"
                    )
                ) or "-"),
            ])
        self._table(rows, [55 * mm, 110 * mm])
        if m.get("comments"):
            self._h2("Comments")
            self._p(str(m["comments"]))
        mode = self.inp.get("mode", "")
        labels = []
        for key, label in (
            ("plastic", "plastic bending"),
            ("elastic", "elastic stresses / cracking"),
            ("shear", "shear"),
            ("torsion", "torsion"),
            ("minimum_reinforcement", "modelled-direction minimum reinforcement"),
            ("transverse_reinforcement", "shear/torsion link detailing"),
        ):
            count = len(self._result_values(key))
            if count:
                labels.append(f"{label} ({count} case{'s' if count != 1 else ''})")
        if any(result.get("valid") for result in self._result_values("combined")):
            labels.append("combined M-V-T")
        if fatigue is not None:
            count = len(fatigue_presentation.items(fatigue, "spectra"))
            labels.append(
                f"grouped fatigue ({count} spectrum"
                f"{'s' if count != 1 else ''})"
            )
        bridge_payload = self._base_out.get("bridge") or {}
        bridge_calculations = bridge_payload.get("calculations") or {}
        if bridge_calculations or bridge_payload.get("errors"):
            labels.append(
                "independent bridge calculations ("
                f"{len(bridge_calculations)} method"
                f"{'s' if len(bridge_calculations) != 1 else ''})"
            )
        ran = ", ".join(labels) or "none"
        self._small(f"Analysis mode: {mode}. Result sections included: {ran}.")
        self._results_overview()
        self.flow.append(NotAtTopPageBreak())

    def _conventions(self):
        self._h1("Conventions and units")
        self._p("Coordinates are entered in the section plane with the origin as "
                "input; the x-axis is horizontal and the y-axis vertical. "
                "<b>M<sub>x</sub></b> bends about the x-axis (stress varies with y) "
                "and is drawn on the vertical axis of the interaction diagram; "
                "<b>M<sub>y</sub></b> bends about the y-axis.")
        self._p("Axial force <b>N</b> is positive in tension (compression negative), "
                "so its sign agrees with the stresses and strains -- a crushing "
                "concrete strain reads negative. Concrete carries compression only "
                "(no tension). Strains are plane (Bernoulli).")
        rows = [["Quantity", "Unit"],
                ["Coordinates, neutral-axis intercepts, lever arm", "mm"],
                ["Axial force N", "kN"],
                ["Moments M<sub>x</sub>, M<sub>y</sub>", "kNm"],
                ["Stresses", "MPa"],
                ["Strains", "permille / percent as noted"],
                ["Curvature kappa", "1/m"],
                ["Areas / second moments", "m<super>2</super> / m<super>4</super>"]]
        self._table(rows, [120 * mm, 45 * mm])

    def _inputs(self):
        self._h1("Section and materials")
        inp = self.inp
        # Geometry drawing.
        self._h2("Geometry")
        bar_xy = [(b[0], b[1]) for b in inp.get("bars", [])]
        ten_xy = [(t[0], t[1]) for t in inp.get("tendons", [])]
        fig = viz.section_figure(inp.get("outer", []), inp.get("holes", []), bar_xy,
                                 title="Section", tendons=ten_xy, show_labels=True,
                                 scale=_MM, unit="mm", height=420,
                                 bar_ids=[item.get("id") for item in inp.get("bar_elements", [])],
                                 tendon_ids=[item.get("id") for item in inp.get("tendon_elements", [])])
        self._fig(fig, 150, 100)
        self._geometry_tables()
        # Materials are reported only when the section actually uses them: mild
        # steel when there are bars, prestress when there are tendons.
        start = len(self.flow)
        self._h2("Concrete")
        self._concrete_block()
        self._keep_from(start)
        if inp.get("bars") or inp.get("shear_on") or inp.get("torsion_on"):
            start = len(self.flow)
            self._h2("Reinforcement")
            self._steel_block()
            self._keep_from(start)
        if inp.get("tendons") and inp.get("prestress") is not None:
            start = len(self.flow)
            self._h2("Prestressing steel")
            self._prestress_block()
            self._keep_from(start)
        # Loads and settings each start on a predictable, dedicated page. Their
        # data tables retain the universal split contract rather than entering one
        # combined KeepTogether block.
        self._page_break()
        self._h2("Loads")
        self._loads_block()
        self._page_break()
        self._h2("Analysis settings")
        self._settings_block()

    def _geometry_tables(self):
        inp = self.inp
        corners = inp.get("outer", [])
        if corners:
            rows = [["#", "x (mm)", "y (mm)"]]
            for i, p in enumerate(corners, 1):
                rows.append([i, _fmt(p[0] * _MM, 3), _fmt(p[1] * _MM, 3)])
            self._h2("Concrete corners")
            self._table(rows, [15 * mm, 40 * mm, 40 * mm])
        holes = inp.get("holes", [])
        for hi, ring in enumerate(holes, 1):
            rows = [["#", "x (mm)", "y (mm)"]]
            for i, p in enumerate(ring, 1):
                rows.append([i, _fmt(p[0] * _MM, 3), _fmt(p[1] * _MM, 3)])
            self._h2(f"Void {hi}")
            self._table(rows, [15 * mm, 40 * mm, 40 * mm])
        def reinforcement_tables(title, points, elements, prefix):
            if not points:
                return
            records = list(elements or [])
            if len(records) != len(points):
                records = [
                    {
                        "id": f"{prefix}{index}", "x_mm": point[0] * _MM,
                        "y_mm": point[1] * _MM, "area_mm2": point[2],
                        "diameter_mm": math.sqrt(4.0 * point[2] / math.pi),
                        "size_mode": "Area", "material_id": "-",
                        "fatigue_detail_id": "",
                    }
                    for index, point in enumerate(points, 1)
                ]
            self._h2(title)
            rows = [["ID", "x (mm)", "y (mm)", "Area (mm<super>2</super>)",
                     "Diameter (mm)", "Size basis"]]
            rows.extend([
                [record.get("id", "-"), _fmt(record.get("x_mm"), 3),
                 _fmt(record.get("y_mm"), 3), _fmt(record.get("area_mm2"), 3),
                 _fmt(record.get("diameter_mm"), 3), record.get("size_mode", "-")]
                for record in records
            ])
            self._table(rows, [18 * mm, 26 * mm, 26 * mm, 31 * mm,
                               31 * mm, 31 * mm], font=7.2, keep=False)
            assignments = [["ID", "Material ID", "Fatigue detail ID"]]
            assignments.extend([
                [record.get("id", "-"), record.get("material_id", "-"),
                 record.get("fatigue_detail_id") or "-"]
                for record in records
            ])
            self._table(assignments, [25 * mm, 55 * mm, 70 * mm],
                        font=7.2, keep=False)

        reinforcement_tables("Reinforcing bars", inp.get("bars", []),
                             inp.get("bar_elements", []), "R")
        reinforcement_tables("Tendons", inp.get("tendons", []),
                             inp.get("tendon_elements", []), "P")

    def _concrete_block(self):
        c = self.inp["concrete"]
        preset = str(self.inp.get("concrete_preset", ""))
        is_2023 = "2023" in preset
        rows = [["Parameter", "Symbol", "Value"],
                 ["Characteristic strength", "f<sub>ck</sub>", f"{_fmt(c.fck, 3)} MPa"],
                 ["Partial factor", "gamma<sub>c</sub>", _fmt(c.gamma_c, 3)]]
        if is_2023:
            eta_cc = self.inp.get("concrete_eta_cc")
            k_tc = self.inp.get("concrete_k_tc")
            rows.extend([
                ["Strength factor", "eta<sub>cc</sub>", _fmt(eta_cc, 6)],
                ["Sustained-load / time factor", "k<sub>tc</sub>", _fmt(k_tc, 2)],
                ["Effective design coefficient", "eta<sub>cc</sub> k<sub>tc</sub>",
                 _fmt(c.alpha_cc, 6)],
            ])
        else:
            rows.append(
                ["Design coefficient", "alpha<sub>cc</sub>", _fmt(c.alpha_cc, 3)]
            )
        rows.extend([
                 ["Curve", "-", "parabola-rectangle" if c.curve == 2 else "cubic"],
                 ["Peak strain", "eps<sub>c2</sub>", f"{_fmt(c.eps_c2*1000, 3)} permille"],
                 ["Ultimate strain", "eps<sub>cu2</sub>", f"{_fmt(c.eps_cu2*1000, 3)} permille"],
                 ["Exponent", "n", _fmt(c.n, 3)],
                 ["Design strength", "f<sub>cd</sub>", f"{_fmt(c.fcd, 3)} MPa"],
        ])
        self._table(rows, [60 * mm, 35 * mm, 50 * mm])
        if is_2023:
            self._formula(
                "f<sub>cd</sub> = eta<sub>cc</sub> &#183; k<sub>tc</sub> &#183; "
                "f<sub>ck</sub> / gamma<sub>c</sub>",
                equation_key="materials.concrete.fcd",
                equation_variant="2023",
                ref="EN 1992-1-1:2023 &#167;5.1.6(1), Formulae (5.3) and (5.4)",
                subst=f"= {_fmt(self.inp.get('concrete_eta_cc'),6)} &#183; "
                      f"{_fmt(self.inp.get('concrete_k_tc'),2)} &#183; "
                      f"{_fmt(c.fck, 3)} / {_fmt(c.gamma_c, 3)}",
                result=f"= {_fmt(c.fcd, 3)} MPa")
            if math.isclose(float(self.inp.get("concrete_k_tc") or 0.0), 1.0):
                self._small(
                    "<b>Applicability assumption:</b> k<sub>tc</sub> = 1.00 was "
                    "selected assuming t<sub>ref</sub> &#8804; 28 days for CR/CN "
                    "or &#8804; 56 days for CS and that design loading is not "
                    "expected until at least 3 months after casting, unless the "
                    "governing National Annex states otherwise (5.1.6(1))."
                )
            else:
                self._small(
                    "k<sub>tc</sub> = 0.85 is the general / other-case value stated "
                    "in EN 1992-1-1:2023 5.1.6(1)."
                )
        else:
            self._formula(
                "f<sub>cd</sub> = alpha<sub>cc</sub> &#183; f<sub>ck</sub> / "
                "gamma<sub>c</sub>",
                equation_key="materials.concrete.fcd",
                equation_variant="2005",
                ref="DS/EN 1992-1-1 &#167;3.1.6, Eq (3.15)",
                subst=f"= {_fmt(c.alpha_cc,3)} &#183; {_fmt(c.fck, 3)} / "
                      f"{_fmt(c.gamma_c, 3)}",
                result=f"= {_fmt(c.fcd, 3)} MPa")
        if c.curve == 2:
            self._formula(
                "sigma<sub>c</sub> = f<sub>cd</sub> &#183; [1 - (1 - eps<sub>c</sub>/"
                "eps<sub>c2</sub>)<super>n</super>],  for eps<sub>c</sub> &lt;= eps<sub>c2</sub>; "
                "then f<sub>cd</sub> up to eps<sub>cu2</sub>",
                equation_key="materials.concrete.curve-2",
                ref=("EN 1992-1-1:2023 &#167;8.1.2(1), Formula (8.4)"
                     if is_2023 else
                     "DS/EN 1992-1-1 &#167;3.1.7, Eq (3.17); strains from Table 3.1"))
        if self.figures:
            self._fig(viz.concrete_curve_figure(c), 130, 80)

    def _steel_block(self):
        catalogue = (self.inp.get("mild_material_catalog") or {}).get("items", [])
        laws = self.inp.get("mild_materials") or {}
        used_ids = list(dict.fromkeys(
            [item.get("material_id") for item in self.inp.get("bar_elements", [])]
            + ([self.inp.get("capacity_steel_material_id")]
               if self.inp.get("shear_on") or self.inp.get("torsion_on") else [])
        ))
        records = [item for item in catalogue if item.get("id") in used_ids]
        if not records:
            records = [{"id": "-", "name": "Reinforcement", "description": "",
                        "preset": self.inp.get("mild_preset", "-")}]
            laws = {"-": self.inp["steel"]}
        summary = [["ID", "Name", "Preset / source", "Use"]]
        for item in records:
            material_id = item.get("id", "-")
            preset = item.get("preset", "-")
            uses = []
            count = sum(element.get("material_id") == material_id
                        for element in self.inp.get("bar_elements", []))
            if count:
                uses.append(f"{count} bar{'s' if count != 1 else ''}")
            if material_id == self.inp.get("capacity_steel_material_id"):
                uses.append("member-check reference")
            summary.append([
                material_id, _html_escape(item.get("name", "")),
                _html_escape(material_catalog.mild_preset_display_label(preset)),
                ", ".join(uses) or "-",
            ])
        self._table(summary, [18 * mm, 42 * mm, 66 * mm, 40 * mm],
                    font=7.0, keep=False, repeat_cols=3)
        self._small("Partial factors are the final effective user inputs; Sector "
                    "applies no hidden control-, construction- or consequence-"
                    "category multiplier.")
        for material_index, item in enumerate(records):
            if self.figures and material_index:
                self.flow.append(NotAtTopPageBreak())
            block_start = len(self.flow)
            material_id = item.get("id", "-")
            st = laws.get(material_id)
            if st is None:
                continue
            title = f"{material_id} - {_html_escape(item.get('name', ''))}"
            self._p(f"<b>{title}</b>")
            if item.get("description"):
                self._small(_html_escape(item["description"]))
            fyd = st.fytk / st.gamma_y if st.gamma_y else st.fytk
            rows = [["Parameter", "Symbol", "Value"],
                    ["Preset identity", "-", _html_escape(
                        material_catalog.mild_preset_classification(
                            item.get("preset", "")
                        )
                    )],
                    ["Implemented law", "-", _html_escape(
                        material_catalog.mild_preset_kernel_note(
                            item.get("preset", "")
                        )
                    )],
                    ["Yield strength", "f<sub>ytk</sub>", f"{_fmt(st.fytk, 3)} MPa"],
                    ["Compression yield", "f<sub>yck</sub>", f"{_fmt(st.fyck, 3)} MPa"],
                    ["Ultimate strength", "f<sub>utk</sub>", f"{_fmt(st.futk, 3)} MPa"],
                    ["Rupture strain", "eps<sub>ut</sub>",
                     f"{_fmt(st.eut*1000, 3)} permille"],
                    ["Elastic modulus", "E<sub>s</sub>", f"{_fmt(st.Es/1000,1)} GPa"],
                    ["Yield partial factor", "gamma<sub>y</sub>", _fmt(st.gamma_y, 3)],
                    ["Ultimate partial factor", "gamma<sub>u</sub>", _fmt(st.gamma_u, 3)],
                    ["Modulus factor", "gamma<sub>E</sub>", _fmt(st.gamma_E, 3)],
                    ["Active in compression", "-",
                     "yes" if st.active_in_compression else "no"],
                    ["Design yield", "f<sub>yd</sub>", f"{_fmt(fyd, 3)} MPa"]]
            self._table(rows, [60 * mm, 35 * mm, 50 * mm])
            source_ref = _steel_standard_reference(item.get("preset"))
            self._formula("f<sub>yd</sub> = f<sub>ytk</sub> / gamma<sub>y</sub>",
                          equation_key=f"materials.steel.fyd-{material_index + 1}",
                          ref=(source_ref or
                               "User-defined or generic constitutive law; no "
                               "normative curve source assigned."),
                          subst=f"= {_fmt(st.fytk, 3)} / {_fmt(st.gamma_y, 3)}",
                          result=f"= {_fmt(fyd, 3)} MPa")
            if self.figures:
                self._fig(viz.steel_curve_figure(
                    st, title=f"{material_id} - {item.get('name', '')}"
                ), 130, 80)
            self._keep_from(block_start)

    def _prestress_block(self):
        catalogue = (self.inp.get("prestress_material_catalog") or {}).get(
            "items", []
        )
        laws = self.inp.get("prestress_materials") or {}
        used_ids = list(dict.fromkeys(
            item.get("material_id") for item in self.inp.get("tendon_elements", [])
        ))
        records = [item for item in catalogue if item.get("id") in used_ids]
        if not records:
            records = [{"id": "-", "name": "Prestressing steel",
                        "description": "",
                        "preset": self.inp.get("prestress_preset", "-")}]
            laws = {"-": self.inp["prestress"]}
        summary = [["ID", "Name", "Preset / source", "Tendons"]]
        for item in records:
            material_id = item.get("id", "-")
            count = sum(element.get("material_id") == material_id
                        for element in self.inp.get("tendon_elements", []))
            summary.append([material_id, _html_escape(item.get("name", "")),
                            _html_escape(item.get("preset", "-")), count])
        self._table(summary, [18 * mm, 45 * mm, 78 * mm, 25 * mm],
                    font=7.0, keep=False, repeat_cols=3)
        for material_index, item in enumerate(records):
            if self.figures and material_index:
                self.flow.append(NotAtTopPageBreak())
            block_start = len(self.flow)
            material_id = item.get("id", "-")
            p = laws.get(material_id)
            if p is None:
                continue
            self._p(f"<b>{material_id} - {_html_escape(item.get('name', ''))}</b>")
            if item.get("description"):
                self._small(_html_escape(item["description"]))
            rows = [["Parameter", "Symbol", "Value"],
                    ["Initial prestrain", "eps<sub>p</sub><super>(0)</super>",
                     f"{_fmt(p.IS*1000, 3)} permille"]]
            if p.curve in (1, 2, 3, 4, 5):
                characteristic_at_rupture = p.stress(
                    p.rupture_strain, design=False
                )
                rows.extend([
                    ["Curve definition", "-", f"Built-in fixed curve {p.curve}"],
                    ["Curve source", "-", "Sector fixed polynomial; normative "
                     "source not assigned"],
                    ["Characteristic stress at rupture strain",
                     "sigma<sub>p</sub>(eps<sub>ut</sub>)",
                     f"{_fmt(characteristic_at_rupture, 3)} MPa"],
                    ["Elastic-analysis modulus", "E<sub>p</sub>",
                     f"{_fmt(p.Es/1000, 1)} GPa"],
                    ["Fixed rupture strain", "eps<sub>ut</sub>",
                     f"{_fmt(p.rupture_strain*1000, 3)} permille"],
                    ["Design factor on fixed workline", "gamma<sub>y</sub>",
                     _fmt(p.gamma_y, 3)],
                ])
            else:
                rows.extend([
                    ["Proof strength", "f<sub>p0.1k</sub>",
                     f"{_fmt(p.fytk, 3)} MPa"],
                    ["Ultimate strength", "f<sub>pk</sub>",
                     f"{_fmt(p.futk, 3)} MPa"],
                    ["Elastic modulus", "E<sub>p</sub>",
                     f"{_fmt(p.Es/1000, 1)} GPa"],
                    ["Rupture strain", "eps<sub>ut</sub>",
                     f"{_fmt(p.rupture_strain*1000, 3)} permille"],
                    ["Yield partial factor", "gamma<sub>y</sub>",
                     _fmt(p.gamma_y, 3)],
                    ["Ultimate partial factor", "gamma<sub>u</sub>",
                     _fmt(p.gamma_u, 3)],
                    ["Modulus factor", "gamma<sub>E</sub>",
                     _fmt(p.gamma_E, 3)],
                ])
            self._table(rows, [60 * mm, 35 * mm, 50 * mm])
            if self.figures:
                self._fig(viz.prestress_curve_figure(
                    p, title=f"{material_id} - {item.get('name', '')}"
                ), 130, 80)
            self._keep_from(block_start)

    def _loads_block(self):
        inp = self._base_inp
        out = self._base_out
        if "plastic_cases" in inp or "elastic_cases" in inp:
            plastic = (
                case_analysis.case_records(inp, "plastic")
                if self._case_contexts("plastic") else []
            )
            if plastic:
                self._small("<b>Plastic / capacity cases</b>")
                rows = [[
                    "Case", "Description", "N<sub>Ed</sub>",
                    "M<sub>x,Ed</sub>", "M<sub>y,Ed</sub>",
                    "V<sub>x,Ed</sub>", "V<sub>y,Ed</sub>",
                    "T<sub>Ed</sub>", "Faces", "Min. reinf.",
                ]]
                rows.extend([
                    [
                        _html_escape(row["name"]),
                        _html_escape(row["description"]),
                        _fmt(row["n_ed_kn"], 3),
                        _fmt(row["mx_ed_knm"], 3),
                        _fmt(row["my_ed_knm"], 3),
                        _fmt(row["vx_ed_kn"], 3),
                        _fmt(row["vy_ed_kn"], 3),
                        _fmt(row["t_ed_knm"], 3),
                        f"Vx {row['vx_face']}; Vy {row['vy_face']}",
                        "yes" if row.get("check_minimum_reinforcement") else "no",
                    ]
                    for row in plastic
                ])
                self._table(
                    rows,
                    [15 * mm, 24 * mm] + [16 * mm] * 6 + [21 * mm, 14 * mm],
                    font=5.8,
                    keep=False,
                    repeat_cols=2,
                )
                self._small("N, Vx and Vy in kN; M and T in kNm. A zero shear "
                            "component or torsion is not evaluated for that case.")

            elastic = (
                case_analysis.case_records(inp, "elastic")
                if self._case_contexts("elastic") else []
            )
            if elastic:
                self._small("<b>Elastic cases</b>")
                rows = [[
                    "Case", "Description", "Part", "N<sub>Ed</sub>",
                    "M<sub>x,Ed</sub>", "M<sub>y,Ed</sub>",
                    "Stress output", "Crack output",
                ]]
                for row in elastic:
                    common = [
                        _html_escape(row["name"]),
                        _html_escape(row["description"]),
                    ]
                    flags = [
                        "always",
                        "yes" if row["calculate_crack_width"] else "no",
                    ]
                    rows.append(common + [
                        "Long",
                        _fmt(row["n_long_ed_kn"], 3),
                        _fmt(row["mx_long_ed_knm"], 3),
                        _fmt(row["my_long_ed_knm"], 3),
                    ] + flags)
                    rows.append(["", "", "Short",
                                 _fmt(row["n_short_ed_kn"], 3),
                                 _fmt(row["mx_short_ed_knm"], 3),
                                 _fmt(row["my_short_ed_knm"], 3), "", ""])
                self._table(
                    rows,
                    [20 * mm, 35 * mm, 17 * mm, 22 * mm, 24 * mm,
                     24 * mm, 14 * mm, 14 * mm],
                    font=6.7,
                    keep=False,
                    repeat_cols=3,
                )
                self._small(
                    "N in kN; M in kNm. Stresses are always reported and "
                    "crack-width calculation is optional per case. No stress or "
                    "crack-width limit is applied."
                )
            fatigue_rows = (
                fatigue_inputs.spectrum_records(
                    inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
                )
                if inp.get("fatigue_on") else []
            )
            if fatigue_rows:
                self._small("<b>Grouped fatigue spectra</b>")
                rows = [[
                    "Spectrum", "Bin", "Description", "Cycles",
                    "N<sub>long,Ed</sub>", "M<sub>x,long,Ed</sub>",
                    "M<sub>y,long,Ed</sub>", "N<sub>short,Ed</sub>",
                    "M<sub>x,short,Ed</sub>", "M<sub>y,short,Ed</sub>",
                ]]
                rows.extend([
                    [
                        _html_escape(row[fatigue_inputs.SPECTRUM]),
                        _html_escape(row[fatigue_inputs.NAME]),
                        _html_escape(row[fatigue_inputs.DESCRIPTION]),
                        _fmt(row[fatigue_inputs.CYCLES], 3),
                        _fmt(row["n_long_ed_kn"], 3),
                        _fmt(row["mx_long_ed_knm"], 3),
                        _fmt(row["my_long_ed_knm"], 3),
                        _fmt(row["n_short_ed_kn"], 3),
                        _fmt(row["mx_short_ed_knm"], 3),
                        _fmt(row["my_short_ed_knm"], 3),
                    ]
                    for row in fatigue_rows
                ])
                self._table(
                    rows,
                    [18 * mm, 18 * mm, 24 * mm, 15 * mm]
                    + [15 * mm] * 6,
                    font=5.1,
                    keep=False,
                    repeat_cols=3,
                )
                self._small(
                    "N in kN; M in kNm. Long is the sustained state; short is "
                    "the cyclic increment. N is tension-positive."
                )
            if not plastic and not elastic and not fatigue_rows:
                self._small("No active load cases.")
            return

        rows = [["Load case", "N (kN)", "M<sub>x</sub> (kNm)", "M<sub>y</sub> (kNm)"]]
        if "plastic" in out:
            # In a capacity-only run the applied moments are ignored, so only the
            # axial force (which defines the envelope) is listed.
            cap_only = not out["plastic"].get("check_util", True)
            case = _html_escape(
                presentation.action_set(inp, "plastic")["id"] or "-"
            )
            label = (
                f"{case} - axial, capacity only"
                if cap_only else f"{case} - plastic applied"
            )
            mx = "-" if cap_only else _fmt(inp.get("Mx_pl"), 3)
            my = "-" if cap_only else _fmt(inp.get("My_pl"), 3)
            rows.append([
                _LiteralReportText(label), _fmt(inp.get("P_pl"), 3), mx, my
            ])
        if "elastic" in out:
            case = _html_escape(
                presentation.action_set(inp, "elastic")["id"] or "-"
            )
            rows.append([_LiteralReportText(f"{case} - long-term"),
                         _fmt(inp.get("P_el_l"), 3),
                         _fmt(inp.get("Mx_el_l"), 3), _fmt(inp.get("My_el_l"), 3)])
            rows.append([_LiteralReportText(f"{case} - short-term"),
                         _fmt(inp.get("P_el_s"), 3),
                         _fmt(inp.get("Mx_el_s"), 3), _fmt(inp.get("My_el_s"), 3)])
        self._table(rows, [55 * mm, 35 * mm, 38 * mm, 38 * mm])

    def _settings_block(self):
        # Every input that influences the reported results is documented here so the
        # report is self-contained and QA-able.
        inp = self.inp
        rows = [["Setting", "Value"]]
        rows.append(["Analysis mode", str(inp.get("mode", "-"))])
        torsion_results = self._result_values("torsion")
        if (
            self._result_values("shear")
            or torsion_results
            or self._result_values("combined")
        ):
            material_id = inp.get("capacity_steel_material_id") or "-"
            material_name = next(
                (item.get("name", "") for item in
                 (inp.get("mild_material_catalog") or {}).get("items", [])
                 if item.get("id") == material_id),
                "",
            )
            rows.append([
                "Member-check reinforcing material",
                f"{material_id} - {material_name}" if material_name else material_id,
            ])
            rows.extend([
                [
                    "Shared compression-strut cot theta<sub>min</sub>",
                    _fmt(inp.get("strut_cot_min"), 2),
                ],
                [
                    "Shared compression-strut cot theta<sub>max</sub>",
                    _fmt(inp.get("strut_cot_max"), 2),
                ],
            ])
        if torsion_results:
            torsion_result = torsion_results[0]
            rows.extend([
                ["Torsion method", str(torsion_result.get("method") or "-")],
                [
                    "Concrete tensile factor gamma<sub>ct</sub>",
                    _fmt(
                        torsion_result.get(
                            "gamma_ct", inp.get("torsion_gamma_ct")
                        ),
                        3,
                    ),
                ],
            ])
        plastic_results = self._result_values("plastic")
        if plastic_results:
            rows.append(["Sweep start phi<sub>NA,min</sub>",
                         f"{_fmt(inp.get('v_min'),0)}&#176;"])
            rows.append(["Sweep end phi<sub>NA,max</sub>",
                         f"{_fmt(inp.get('v_max'),0)}&#176;"])
            rows.append(["Sweep increment &#916;phi<sub>NA</sub>",
                         f"max {_fmt(inp.get('v_inc'),0)}&#176;"])
            checked = plastic_results[0].get("check_util", True)
            rows.append(["Utilisation check",
                         "applied moment checked" if checked else "capacity only"])
        if inp.get("minimum_reinforcement_on"):
            rows.extend([
                ["Minimum reinforcement", "selected per capacity case"],
                ["Detailing edition", str(inp.get("detailing_edition") or "-")],
                ["Member type", str(inp.get("detailing_member_type") or "Beam")],
                [
                    "Section cut direction",
                    str(inp.get("detailing_cut_direction") or "Transverse cut"),
                ],
            ])
            if not self._result_values("elastic"):
                rows.append([
                    "Mean tensile strength f<sub>ctm</sub>",
                    f"{_fmt(inp.get('sls_fctm'), 3)} MPa",
                ])
        if inp.get("transverse_detailing_on"):
            rows.append(
                [
                    "Shear/torsion link detailing",
                    "selected per active capacity case",
                ]
            )
            if not inp.get("minimum_reinforcement_on"):
                rows.extend([
                    [
                        "Detailing edition",
                        str(inp.get("detailing_edition") or "-"),
                    ],
                    [
                        "Member type",
                        str(inp.get("detailing_member_type") or "Beam"),
                    ],
                ])
            rows.extend([
                [
                    "Maximum spacing of V<sub>x</sub>-parallel legs along y",
                    (
                        f"{_fmt(inp.get('shear_vx_transverse_leg_spacing'), 1)} mm"
                        if inp.get("shear_vx_transverse_leg_spacing")
                        else "gross-web upper-bound screen"
                    ),
                ],
                [
                    "Maximum spacing of V<sub>y</sub>-parallel legs along x",
                    (
                        f"{_fmt(inp.get('shear_vy_transverse_leg_spacing'), 1)} mm"
                        if inp.get("shear_vy_transverse_leg_spacing")
                        else "gross-web upper-bound screen"
                    ),
                ],
            ])
            if inp.get("detailing_edition") == detailing.EC2_2023:
                rows.extend([
                    [
                        "Link reinforcement ductility class",
                        str(inp.get("transverse_ductility_class") or "B"),
                    ],
                    [
                        "2023 minimum-ratio ductility reduction",
                        (
                            "selected"
                            if inp.get(
                                "transverse_apply_ductility_reduction"
                            )
                            else "not selected"
                        ),
                    ],
                ])
        if (
            inp.get("shear_links")
            and "2023" in str(inp.get("shear_method") or "")
            and not (
                inp.get("transverse_detailing_on")
                and inp.get("detailing_edition") == detailing.EC2_2023
            )
        ):
            rows.append([
                "Link reinforcement ductility class",
                str(inp.get("transverse_ductility_class") or "B"),
            ])
        if inp.get("clear_spacing_on"):
            rows.extend([
                ["Clear-spacing check", "section-wide"],
                ["Upper aggregate size D<sub>upper</sub>",
                 f"{_fmt(inp.get('detailing_d_upper'), 1)} mm"],
                ["Tendons included in spacing",
                 "yes - entered diameter is detailing envelope"
                 if inp.get("detailing_include_tendons") else "no"],
            ])
        elastic_results = self._result_values("elastic")
        if elastic_results:
            # Modular ratios are derived from the elastic moduli and creep, not entered;
            # document the inputs (Ec, phi) and the derived mild + prestress ratios.
            if inp.get("conc_Ec") is not None:
                rows.append(["Concrete elastic modulus E<sub>c</sub>",
                             f"{_fmt(inp.get('conc_Ec'), 3)} GPa"])
            if inp.get("el_phi") is not None:
                rows.append(["Creep coefficient &#966; (long-term)",
                             _fmt(inp.get("el_phi"), 3)])
            ec_mpa = float(inp.get("conc_Ec") or 0.0) * 1000.0
            phi = float(inp.get("el_phi") or 0.0)
            material_pairs = []
            material_pairs.extend(
                (element.get("material_id"), material)
                for element, material in zip(inp.get("bar_elements", []),
                                             inp.get("bar_materials", []))
            )
            material_pairs.extend(
                (element.get("material_id"), material)
                for element, material in zip(inp.get("tendon_elements", []),
                                             inp.get("tendon_materials", []))
            )
            if not material_pairs:
                if inp.get("bars") and inp.get("steel") is not None:
                    material_pairs.append(("M1", inp["steel"]))
                if inp.get("tendons") and inp.get("prestress") is not None:
                    material_pairs.append(("P1", inp["prestress"]))
            for material_id, material in dict(material_pairs).items():
                ns_v = material.Es / ec_mpa if ec_mpa > 0.0 else None
                nl_v = ns_v * (1.0 + phi) if ns_v is not None else None
                rows.append([
                    f"{material_id} modular ratios n<sub>s</sub> / n<sub>l</sub>",
                    f"{_fmt(ns_v, 3)} / {_fmt(nl_v, 3)}",
                ])
            rows.append(["Mean tensile strength f<sub>ctm</sub>",
                         f"{_fmt(inp.get('sls_fctm'), 3)} MPa"])
            rows.append([
                "Elastic stress treatment",
                "Numerical output only; no stress limit applied",
            ])
            crack_results = [item for item in elastic_results if item.get("show_cw")]
            rows.append(["Crack width calculated",
                         "yes" if crack_results else "no"])
            if crack_results:
                crack_el = crack_results[0]
                rows.append(["Crack-width code", str(crack_el.get("crack_code", "-"))])
                rows.append([
                    "Crack-width treatment",
                    "Numerical output only; no crack-width limit applied",
                ])
                if crack_el.get("crack_member"):
                    rows.append(["Member type", str(crack_el["crack_member"])])
                dia = inp.get("sls_phi") or 0.0
                rows.append(["Crack-width element diameter",
                             ("per-element table values" if not dia
                              else f"{_fmt(dia, 3)} mm global override")])
                rows.append(["Mild-steel bond coefficient k<sub>1</sub>",
                             _fmt(inp.get("sls_k1"), 3)])
        fatigue_rows = None
        fatigue = self._base_out.get("fatigue")
        if fatigue is not None:
            checks = fatigue.get("checks") or {}
            factors = fatigue.get("partial_factors") or {}
            concrete = fatigue.get("concrete_parameters") or {}
            fatigue_basis = fatigue.get("basis") or {}
            fatigue_rows = [["Setting", "Value"]]
            fatigue_rows.extend([
                ["Fatigue edition", str(fatigue.get("edition") or "-")],
                [
                    "Fatigue checks",
                    ", ".join(
                        label
                        for key, label in (
                            ("reinforcement", "reinforcement"),
                            ("concrete", "concrete"),
                        )
                        if checks.get(key)
                    ) or "-",
                ],
                ["Fatigue gamma<sub>Ff</sub>",
                 _fmt(factors.get("gamma_ff"), 3)],
            ])
            if checks.get("reinforcement"):
                fatigue_rows.append([
                    "Fatigue gamma<sub>s</sub>",
                    _fmt(factors.get("gamma_s"), 3),
                ])
            if checks.get("concrete"):
                fatigue_rows.extend([
                    ["Concrete fatigue method",
                     _html_escape(str(
                         fatigue.get("concrete_method") or "-"
                     ))],
                    ["Fatigue gamma<sub>c,fat</sub>",
                     _fmt(factors.get("gamma_c"), 3)],
                    ["Concrete age t<sub>0</sub>",
                     f"{_fmt(fatigue.get('t0_days'), 2)} days"],
                    ["beta<sub>cc</sub>(t<sub>0</sub>)",
                     _fmt(concrete.get("beta_cc_t0"), 4)],
                    ["Concrete fatigue f<sub>ck</sub>",
                     f"{_fmt(concrete.get('fck_mpa'), 2)} MPa"],
                    ["Concrete fatigue alpha<sub>cc</sub>",
                     _fmt(concrete.get("alpha_cc"), 3)],
                    ["Concrete fatigue k<sub>1</sub>",
                     _fmt(concrete.get("k1"), 3)],
                    ["Concrete fatigue C", _fmt(concrete.get("c"), 3)],
                ])
            fatigue_rows.extend([
                ["Fatigue n<sub>l</sub> / n<sub>s</sub>",
                 f"{_fmt(inp.get('nl'), 3)} / {_fmt(inp.get('ns'), 3)}"],
                ["Fatigue method",
                 _html_escape(str(fatigue_basis.get("method") or "-"))],
                ["Action-set notes",
                 _html_escape(str(fatigue_basis.get("notes") or "-"))],
                ["Method reference",
                 _html_escape(str(fatigue.get("method_reference") or "-"))],
            ])
            for detail in fatigue.get("fatigue_detail_basis") or ():
                fatigue_rows.append([
                    "Fatigue detail "
                    + _html_escape(str(detail.get("id", "-"))),
                    (
                        _html_escape(str(
                            detail.get("name")
                            or detail.get("preset")
                            or "-"
                        ))
                        + "; source: "
                        + _html_escape(str(
                            detail.get("source") or "not stated"
                        ))
                    ),
                ])
        self._table(rows, [110 * mm, 55 * mm], keep=False)
        if fatigue_rows:
            self.flow.append(NotAtTopPageBreak())
            self._h2("Grouped fatigue settings")
            self._table(fatigue_rows, [110 * mm, 55 * mm], keep=False)

    def _theory(self):
        self._h1("Basis of analysis")
        plastic_results = self._result_values("plastic")
        elastic_results = self._result_values("elastic")
        minimum_results = self._result_values("minimum_reinforcement")
        transverse_results = self._result_values("transverse_reinforcement")
        fatigue = self._base_out.get("fatigue")
        fatigue_errors = tuple((fatigue or {}).get("errors") or ())
        if plastic_results:
            material_2023 = "2023" in str(self.inp.get("concrete_preset", ""))
            steel_presets = [
                str(item.get("preset", ""))
                for item in (self.inp.get("mild_material_catalog") or {}).get(
                    "items", [])
                if item.get("id") in {
                    element.get("material_id")
                    for element in self.inp.get("bar_elements", [])
                }
            ] or [str(self.inp.get("mild_preset", ""))]
            concrete_ref = (
                "EN 1992-1-1:2023 &#167;8.1.1-8.1.2 and &#167;5.1.6"
                if material_2023 else
                "DS/EN 1992-1-1 &#167;6.1 and &#167;3.1.7"
            )
            steel_ref = _steel_theory_reference(steel_presets)
            self._p("<b>Plastic section capacity.</b> Plane sections; concrete in "
                    "compression follows the design curve above, reinforcement the "
                    "design stress-strain law. For a trial neutral axis the strain "
                    "plane is scaled to the governing curvature - the first material "
                    "limit reached:")
            self._formula("kappa<sub>u</sub> = min( eps<sub>cu2</sub>/c ,  "
                           "min<sub>i</sub>[eps<sub>su,i</sub>/d<sub>s,i</sub>] ,  "
                           "min<sub>j</sub>[(eps<sub>pu,j</sub>-"
                           "eps<sub>p0,j</sub>)/d<sub>p,j</sub>] )",
                           equation_key="basis.plastic.governing-curvature",
                           ref=f"Concrete: {concrete_ref}; reinforcement: {steel_ref}")
            self._small("Each bar and tendon uses its assigned material law and "
                        "strain limit in the element-wise minima.")
            self._p("The compression depth c is solved from axial equilibrium and "
                    "the moments follow from the force resultants:")
            self._formula("F<sub>c</sub> + F<sub>s</sub> + F<sub>p</sub> = N ;   "
                          "M = &#8721;(F<sub>i</sub> &#183; d<sub>i</sub>)",
                          equation_key="basis.plastic.equilibrium")
        if elastic_results:
            self._p("<b>Cracked-section elastic stresses.</b> Transformed section "
                    "(reinforcement weighted by the modular ratio), concrete tension "
                    "ignored once cracked; long-term and short-term actions are "
                    "carried at their own modular ratios so creep is explicit. The "
                    "ratios are derived from the moduli, not entered: each bar or "
                    "tendon uses its assigned n<sub>i</sub> = E<sub>i</sub>/"
                    "E<sub>c</sub>, creep-reduced to "
                    "E/E<sub>c,eff</sub> with E<sub>c,eff</sub> = "
                    "E<sub>c</sub>/(1+&#966;) for the long-term state.")
            self._p("<b>Cracking threshold.</b> The Stage-I extreme tensile stress "
                    "is compared with f<sub>ct,eff</sub>.")
            if any(result.get("show_cw") for result in elastic_results):
                self._p("<b>Crack width.</b> The requested crack-width calculation "
                        "follows the selected code method and is worked below.")
        if fatigue is not None and not fatigue_errors:
            references = fatigue.get("calculation_references") or {}
            self._p(
                "<b>Grouped fatigue.</b> Each named spectrum is checked "
                "independently with the cracked Elastic solver. For each bin, "
                "the long action is the sustained state and the short action is "
                "the cyclic increment."
            )
            self._formula(
                "&#916;sigma<sub>i</sub> = | sigma(long + "
                "gamma<sub>Ff</sub> &#183; short)<sub>i</sub> - "
                "sigma(long)<sub>i</sub> |",
                equation_key="basis.fatigue.stress-range",
                ref=(
                    "gamma<sub>Ff</sub> is applied to the cyclic section "
                    "actions before solving; stresses are not scaled afterwards."
                ),
            )
            if (fatigue.get("checks") or {}).get("reinforcement"):
                self._p(
                    "<b>Reinforcement fatigue.</b> The assigned two-slope S-N "
                    "curve gives N<sub>R,i</sub> for each design stress range. "
                    "The same bin also checks yield or proof stress."
                )
                self._formula(
                    "D = &#8721;(n<sub>i</sub> / N<sub>R,i</sub>) &#8804; 1.00",
                    equation_key="basis.fatigue.reinforcement-miner",
                    ref=_html_escape(
                        references.get("reinforcement") or "-"
                    ),
                )
            if (fatigue.get("checks") or {}).get("concrete"):
                self._p(
                    "<b>Concrete fatigue.</b> Compression minima and maxima are "
                    "evaluated at the same fibre for every bin. Miner damage and "
                    "the maximum compressive-stress ratio are checked. An "
                    "adaptive section search reports a bounded upper damage "
                    "bound."
                )
                self._formula(
                    "D<sub>c</sub> = &#8721;(n<sub>i</sub> / "
                    "N<sub>R,i</sub>) &#8804; 1.00",
                    equation_key="basis.fatigue.concrete-miner",
                    ref=_html_escape(references.get("concrete") or "-"),
                )
            self._small(
                "Miner damage is accumulated within each named spectrum only; "
                "different spectrum names are not combined."
            )
        elif fatigue_errors:
            self._p(
                "<b>Grouped fatigue.</b> Fatigue was requested but not assessed "
                "because the input preflight was invalid. No fatigue calculation "
                "method was applied."
            )
        if minimum_results:
            edition = str(self.inp.get("detailing_edition") or "")
            if edition == detailing.EC2_2023:
                self._p(
                    "<b>Minimum reinforcement in the modelled direction.</b> The nominal section "
                    "resistance at characteristic reinforcement yield is compared "
                    "with the cracking action for each selected case. Pure tension "
                    "uses direct force equilibrium."
                )
                self._small(
                    "Reference: EN 1992-1-1:2023, 12.2(2), Formulae (12.1) and "
                    "(12.2). Prestressing tendons are not credited."
                )
            else:
                self._p(
                    "<b>Minimum reinforcement in the modelled direction.</b> The resultant "
                    "gross-concrete tension zone is checked using "
                    "A<sub>s,min</sub> = max(0.26 "
                    "f<sub>ctm</sub>/f<sub>yk</sub>, 0.0013) b<sub>t</sub>d."
                )
                self._small(
                    "Reference: EN 1992-1-1, 9.2.1.1(1), Formula (9.1N). "
                    "Prestressing tendons are not credited."
                )
        if transverse_results:
            edition = str(self.inp.get("detailing_edition") or "")
            self._p(
                "<b>Shear/torsion link detailing.</b> Vertical "
                "shear links are checked for minimum ratio, longitudinal spacing "
                "and transverse leg spacing. Closed torsion links are checked for "
                "minimum ratio and longitudinal spacing."
            )
            self._formula(
                "&#961;<sub>w</sub> = A<sub>sw</sub> / (s b<sub>w</sub>);   "
                "&#961;<sub>w,T</sub> = A<sub>leg</sub> / "
                "(s t<sub>ef</sub>)",
                equation_key="basis.detailing.transverse-ratios",
                ref=_html_escape(edition),
            )
            self._small(
                "The model contains vertical stirrups only and treats the torsion "
                "reinforcement as closed stirrups. Anchorage is assumed; reduce "
                "f<sub>ywk</sub> when full anchorage is unavailable."
            )
            self._small(
                "Transverse leg spacing is measured in the section plane between "
                "adjacent parallel legs: along y for V<sub>x</sub> and along x for "
                "V<sub>y</sub>. It is not the longitudinal stirrup spacing. A gross-"
                "web upper-bound screen can prove PASS, but cannot prove FAIL."
            )
        if self._base_out.get("clear_spacing") is not None:
            clause = "11.2(2)" if self.inp.get("detailing_edition") == detailing.EC2_2023 else "8.2(2)"
            self._p(
                "<b>Clear spacing.</b> Pairwise edge-to-edge distance is compared "
                "with max(phi, D<sub>upper</sub> + 5 mm, 20 mm)."
            )
            self._small(
                f"Reference: {self.inp.get('detailing_edition', '-')} {clause}. "
                "Lap and bundle verification remains outside this section-plane check."
            )
        if (not plastic_results and not elastic_results and not minimum_results
                and not transverse_results
                and fatigue is None
                and self._base_out.get("clear_spacing") is None):
            self._p("No bending-capacity or elastic-stress result was included in "
                    "this report.")

    def _minimum_reinforcement(self):
        result = self.out["minimum_reinforcement"]
        direction = str(
            result.get("modelled_reinforcement_direction") or "longitudinal"
        ).capitalize()
        self._case_heading(f"{direction} minimum reinforcement", "plastic")
        status = str(result.get("status") or "NOT ASSESSED").upper()
        checks = result.get("checks") or []
        utilisations = [
            float(check["utilisation"])
            for check in checks
            if check.get("utilisation") is not None
            and math.isfinite(float(check["utilisation"]))
        ]
        summary = (
            f"governing utilisation {_pct(max(utilisations))}"
            if utilisations else str(result.get("reason") or "not evaluated")
        )
        self._status_block(f"{status} - {summary}", status)
        self._small(
            f"<b>Method:</b> {_html_escape(result.get('member_type', '-'))}; "
            f"{_html_escape(result.get('cut_direction', '-'))} | "
            f"{_html_escape(result.get('edition', '-'))} | "
            f"{_html_escape(result.get('clause', '-'))}."
        )

        highlight_ids = sorted({
            str(element_id)
            for check in checks
            for element_id in check.get("bar_ids") or []
        })
        self._fig(viz.detailing_geometry_figure(
            self.inp.get("outer") or [],
            self.inp.get("holes") or [],
            self.inp.get("bars") or [],
            self.inp.get("tendons") or [],
            bar_elements=self.inp.get("bar_elements") or [],
            tendon_elements=self.inp.get("tendon_elements") or [],
            highlight_ids=highlight_ids,
            tension_zone=checks[0] if checks else None,
            title="Minimum-reinforcement geometry",
        ), 150, 108)

        if checks and presentation.minimum_area_check(result, checks[0]):
            self._formula(
                "A<sub>s,min</sub> = max(0.26 f<sub>ctm</sub> / "
                "f<sub>yk</sub>, 0.0013) b<sub>t</sub>d",
                equation_key="detailing.minimum.area-2005",
                ref=(f"{_html_escape(result.get('edition', '-'))} "
                     "&#167;9.2.1.1(1), Formula (9.1N)"),
            )
            rows = [[
                "Axis", "Face", "A<sub>s,prov</sub>", "A<sub>s,min</sub>",
                "Util.", "b<sub>t</sub>", "d", "f<sub>ctm</sub>",
                "f<sub>yk</sub>", "Bars", "Status",
            ]]
            rows.extend([
                [
                    (
                        "Mx + My" if check.get("axis") == "xy"
                        else f"M{check.get('axis', '-')}"
                    ),
                    check.get("face", "-"),
                    _fmt(check.get("as_provided_mm2"), 1),
                    _fmt(check.get("as_min_mm2"), 1),
                    _pct(check.get("utilisation")),
                    _fmt(check.get("bt_mm"), 1), _fmt(check.get("d_mm"), 1),
                    _fmt(check.get("fctm_mpa"), 2),
                    _fmt(check.get("fyk_mpa"), 1),
                    _html_escape(", ".join(check.get("bar_ids") or [])),
                    check.get("status", "-"),
                ]
                for check in checks
            ])
            self._table(
                rows,
                [14 * mm, 22 * mm, 17 * mm, 17 * mm, 14 * mm,
                 14 * mm, 14 * mm, 13 * mm, 13 * mm, 18 * mm, 14 * mm],
                font=5.9,
                keep=False,
                repeat_cols=2,
            )
            self._small(
                "Areas in mm<super>2</super>; b<sub>t</sub> and d in mm; "
                "strengths in MPa."
            )
            for check in checks:
                if check.get("reason"):
                    self._small(
                        "<b>Outcome:</b> " + _html_escape(check["reason"])
                    )
        elif checks and checks[0].get("type") == "pure tension":
            self._formula(
                "R<sub>nom</sub> = &#8721;(A<sub>s,i</sub> f<sub>yk,i</sub>) "
                "&#8805; R<sub>cr</sub> = A<sub>c</sub> f<sub>ctm</sub>",
                equation_key="detailing.minimum.tension-2023",
                ref="EN 1992-1-1:2023 &#167;12.2(2)(b), Formula (12.2)",
            )
            rows = [[
                "R<sub>cr</sub> (kN)", "R<sub>nom</sub> (kN)", "Utilisation",
                "A<sub>s,prov</sub> (mm<super>2</super>)", "Bars", "Status",
            ]]
            rows.extend([
                [
                    _fmt(check.get("demand_kn"), 2),
                    _fmt(check.get("resistance_kn"), 2),
                    _pct(check.get("utilisation")),
                    _fmt(check.get("as_provided_mm2"), 1),
                    _html_escape(", ".join(check.get("bar_ids") or [])),
                    check.get("status", "-"),
                ]
                for check in checks
            ])
            self._table(rows, [27 * mm, 27 * mm, 26 * mm, 35 * mm,
                               35 * mm, 20 * mm], font=7.0)
        elif checks:
            self._formula(
                "M<sub>R,nom</sub>(N<sub>Ed</sub>) &#8805; "
                "M<sub>cr</sub>(N<sub>Ed</sub>)",
                equation_key="detailing.minimum.bending-2023",
                ref="EN 1992-1-1:2023 &#167;12.2(2)(a), Formula (12.1)",
            )
            rows = [[
                "M<sub>cr</sub> (kNm)", "M<sub>R,nom</sub> (kNm)",
                "Utilisation", "N<sub>nom,t</sub> (kN)", "Axial eq.",
                "A<sub>s,prov</sub> (mm<super>2</super>)", "Status",
            ]]
            rows.extend([
                [
                    _fmt(check.get("m_cr_knm"), 2),
                    _fmt(check.get("mr_nom_knm"), 2),
                    _pct(check.get("utilisation")),
                    _fmt(check.get("nominal_axial_resistance_kn"), 2),
                    ("yes" if check.get("axial_feasible") is True
                     else "no" if check.get("axial_feasible") is False else "-"),
                    _fmt(check.get("as_provided_mm2"), 1),
                    check.get("status", "-"),
                ]
                for check in checks
            ])
            self._table(rows, [24 * mm, 24 * mm, 20 * mm, 26 * mm,
                               22 * mm, 30 * mm, 19 * mm], font=6.4)
            for check in checks:
                self._small(
                    "<b>Nominal-resistance model:</b> "
                    + _html_escape(check.get("model") or "-")
                    + f"; cracking factor {_fmt(check.get('cracking_factor'), 4)}."
                )
        elif result.get("reason"):
            self._small(_html_escape(result["reason"]))

        for limitation in result.get("limitations") or []:
            self._small("<b>Scope:</b> " + _html_escape(limitation))

    def _transverse_reinforcement(self):
        result = self.out["transverse_reinforcement"]
        self._case_heading("Shear/torsion link detailing", "plastic")
        status = str(result.get("status") or "NOT ASSESSED").upper()
        governing = result.get("governing") or {}
        utilisation = governing.get("utilisation")
        incomplete_reason = next((
            str(check["reason"])
            for check in result.get("checks") or []
            if check.get("status") == "NOT ASSESSED" and check.get("reason")
        ), None)
        summary = (
            incomplete_reason
            if status == "NOT ASSESSED" and incomplete_reason
            else str(
                governing.get("scope")
                or result.get("reason")
                or "not evaluated"
            )
        )
        if (
            status != "NOT ASSESSED"
            and utilisation is not None
            and math.isfinite(float(utilisation))
        ):
            summary += f"; utilisation {_pct(utilisation)}"
        self._status_block(f"{status} - {summary}", status)

        minimum = result.get("minimum_ratio") or {}
        self._small(
            f"<b>Method:</b> {_html_escape(result.get('member_type', '-'))}; "
            f"{_html_escape(result.get('edition', '-'))}; "
            f"stirrup &#966; = {_fmt(result.get('diameter_mm'), 1)} mm; "
            f"s = {_fmt(result.get('spacing_mm'), 1)} mm; "
            f"f<sub>ywk</sub> = {_fmt(result.get('fywk_mpa'), 1)} MPa."
        )
        if minimum:
            self._formula(
                "&#961;<sub>w,min</sub> = "
                f"{_fmt(minimum.get('coefficient'), 3)} "
                "&#8730;f<sub>ck</sub> / f<sub>ywk</sub>"
                + (
                    " &#183; "
                    + _fmt(minimum.get("ductility_factor"), 2)
                    if minimum.get("ductility_reduction_applied")
                    else ""
                ),
                equation_key="detailing.links.minimum-ratio",
                ref=_html_escape(minimum.get("clause") or "-"),
            )

        labels = {
            "minimum_ratio": "Minimum ratio",
            "longitudinal_spacing": "Longitudinal spacing",
            "transverse_leg_spacing": "Transverse leg spacing",
            "torsion_spacing": "Closed-link spacing",
            "required_links": "Required links",
            "minimum_link_applicability": "Minimum-link applicability",
        }
        rows = [[
            "Scope", "Check", "Provided", "Limit", "Util.", "Status",
            "Reference",
        ]]
        for check in result.get("checks") or []:
            kind = check.get("kind")
            ratio = kind == "minimum_ratio"
            required_links = kind == "required_links"
            check_label = labels.get(kind, kind or "-")
            if kind == "transverse_leg_spacing" and check.get("measurement_axis"):
                check_label += f" (along {check['measurement_axis']})"
            provided = check.get("provided")
            limit = check.get("limit")
            if required_links:
                provided_text = "not defined"
                limit_text = "required"
            elif ratio:
                provided_text = (
                    "-" if provided is None else _fmt(provided, 5)
                )
                limit_text = "-" if limit is None else _fmt(limit, 5)
            else:
                provided_text = (
                    "-" if provided is None else f"{_fmt(provided, 1)} mm"
                )
                limit_text = (
                    "-" if limit is None else f"{_fmt(limit, 1)} mm"
                )
            rows.append([
                _html_escape(check.get("scope") or "-"),
                _html_escape(check_label),
                provided_text,
                limit_text,
                _pct(check.get("utilisation")),
                _html_escape(check.get("status") or "-"),
                _html_escape(check.get("clause") or "-"),
            ])
        if len(rows) > 1:
            self._table(
                rows,
                [24 * mm, 32 * mm, 21 * mm, 21 * mm, 17 * mm,
                 20 * mm, 33 * mm],
                font=6.2,
                keep=False,
                repeat_cols=2,
            )
        for check in result.get("checks") or []:
            details = []
            if check.get("spacing_source"):
                details.append(
                    "spacing source: " + str(check["spacing_source"])
                )
            if check.get("governing_limit"):
                details.append(
                    "governing limit: " + str(check["governing_limit"])
                )
            if check.get("reason"):
                details.append(str(check["reason"]))
            if details:
                self._small(
                    f"<b>{_html_escape(check.get('scope') or 'Check')}:</b> "
                    + _html_escape("; ".join(details))
                )
        for limitation in result.get("limitations") or []:
            self._small("<b>Scope:</b> " + _html_escape(limitation))

    def _clear_spacing(self):
        result = self.out["clear_spacing"]
        self._h1("Reinforcement clear spacing")
        status = str(result.get("status") or "NOT ASSESSED").upper()
        governing = result.get("governing") or {}
        summary = (
            f"{_fmt(governing.get('clear_mm'), 1)} mm clear; "
            f"{_fmt(governing.get('required_mm'), 1)} mm required"
            if governing else str(result.get("reason") or "not evaluated")
        )
        self._status_block(f"{status} - {summary}", status)
        self._small(
            f"<b>Method:</b> {_html_escape(result.get('edition', '-'))} | "
            f"{_html_escape(result.get('clause', '-'))}; "
            f"D<sub>upper</sub> = {_fmt(result.get('d_upper_mm'), 1)} mm."
        )
        self._fig(viz.detailing_geometry_figure(
            self.inp.get("outer") or [],
            self.inp.get("holes") or [],
            self.inp.get("bars") or [],
            self.inp.get("tendons") or [],
            bar_elements=self.inp.get("bar_elements") or [],
            tendon_elements=self.inp.get("tendon_elements") or [],
            spacing_pair=governing,
            title="Governing clear-spacing pair",
        ), 150, 108)
        self._formula(
            "c<sub>req</sub> = max(phi<sub>max</sub>, "
            "D<sub>upper</sub> + 5 mm, 20 mm)",
            equation_key="detailing.clear-spacing.requirement",
            ref=(f"{_html_escape(result.get('edition', '-'))} "
                 f"&#167;{_html_escape(result.get('clause', '-'))}"),
        )
        if governing:
            self._small(
                "<b>Governing pair:</b> "
                f"{_html_escape(governing.get('first_id', '?'))} - "
                f"{_html_escape(governing.get('second_id', '?'))}; "
                f"margin {_fmt(governing.get('margin_mm'), 1)} mm."
            )
        pairs = result.get("pairs") or []
        if pairs:
            rows = [[
                "Pair", "Elements", "Clear (mm)", "Required (mm)",
                "Margin (mm)", "Status",
            ]]
            rows.extend([
                [
                    f"{_html_escape(pair.get('first_id', '?'))} - "
                    f"{_html_escape(pair.get('second_id', '?'))}",
                    f"{_html_escape(pair.get('first_kind', '-'))} / "
                    f"{_html_escape(pair.get('second_kind', '-'))}",
                    _fmt(pair.get("clear_mm"), 1),
                    _fmt(pair.get("required_mm"), 1),
                    _fmt(pair.get("margin_mm"), 1),
                    pair.get("status", "-"),
                ]
                for pair in pairs
            ])
            self._table(
                rows,
                [38 * mm, 30 * mm, 26 * mm, 30 * mm, 26 * mm, 20 * mm],
                font=6.4,
                keep=False,
                repeat_cols=2,
            )
        for limitation in result.get("limitations") or []:
            self._small("<b>Scope:</b> " + _html_escape(limitation))

    def _plastic(self):
        pl = self.out["plastic"]
        self._case_heading("Plastic section capacity", "plastic")
        assessment = presentation.plastic_action_assessment(pl)
        status = assessment["status"]
        self._status_block(
            presentation.plastic_assessment_text(assessment),
            status,
        )
        applied = pl.get("applied")   # None for a capacity-only run
        self._fig(viz.interaction_figure(
            pl["mx"], pl["my"], applied=applied, title="M-M interaction",
            angles=[pt["V"] for pt in pl["points"]], util=pl.get("util"),
            closed=pl.get("closed", True)), 130, 100)
        rows = [["Quantity", "Value"],
                ["Applied N<sub>Ed</sub>",
                 f"{_fmt(self.inp.get('P_pl', 0.0), 3)} kN (tension +)"],
                ["Max / Min M<sub>x</sub> capacity",
                 f"{_fmt(pl['max_mx'], 3)} / "
                 f"{_fmt(pl.get('min_mx', min(pl['mx'])), 3)} kNm"],
                ["Max / Min M<sub>y</sub> capacity",
                 f"{_fmt(pl['max_my'], 3)} / "
                 f"{_fmt(pl.get('min_my', min(pl['my'])), 3)} kNm"]]
        if not pl.get("check_util", True):
            rows.append(["Utilisation", "not checked (capacity only)"])
        elif pl.get("util") is not None:
            if applied is not None:
                rows.append(["Applied M<sub>x</sub>, M<sub>y</sub>",
                             f"{_fmt(applied[0], 3)}, {_fmt(applied[1], 3)} kNm"])
            rows.append(["Utilisation (applied direction)",
                         f"{_fmt(pl['util']*100, 3)} %"])
        else:
            rows.append(["Utilisation", "open arc (no closed envelope)"])
        self._table(rows, [90 * mm, 60 * mm])
        # N-M interaction diagrams (opt-in): the capacity boundary about each bending
        # axis, from pure tension to the squash load.
        nm = pl.get("interaction")
        if nm:
            nm_valid = all(
                (nm.get(axis) or {}).get("converged", True)
                for axis in ("x", "y")
            )
            if not nm_valid:
                self._status_block(
                    "INVALID - N-M boundary | One or more points did not converge; "
                    "values are diagnostic only.",
                    "INVALID",
                )
            for axis, mlab, mtag in (("x", "M<sub>x</sub>", "Mx"),
                                     ("y", "M<sub>y</sub>", "My")):
                d = nm[axis]
                self._h2(f"Axial-moment (N-{mlab}) interaction")
                self._fig(viz.interaction_nm_figure(
                    d["N"], d["M"], axis=axis,
                    applied=d.get("applied") if pl.get("check_util", True) else None,
                    title=f"N-{mtag} interaction"), 130, 95)
                self._small(f"Capacity boundary about the {axis}-axis, from pure "
                            "tension to the squash load (concrete carries compression "
                            "only, so the tension end is reinforcement-controlled). "
                            "The marked point is the applied plastic action.")
            self._h2("Numerical N-M boundary")
            boundary_rows = presentation.nm_boundary_rows(nm)
            rows = [[
                "Point",
                "N (M<sub>x</sub> curve)",
                "M<sub>x</sub>",
                "N (M<sub>y</sub> curve)",
                "M<sub>y</sub>",
            ]]
            for row in boundary_rows:
                def value(key):
                    number = row[key]
                    return "-" if number is None else _fmt(number, 3)

                rows.append([
                    str(row["Point"]),
                    value("N, Mx boundary (kN)"),
                    value("Mx (kNm)"),
                    value("N, My boundary (kN)"),
                    value("My (kNm)"),
                ])
            self._table(
                rows,
                [18 * mm, 38 * mm, 38 * mm, 38 * mm, 38 * mm],
                font=7.2,
                keep=False,
            )
            self._small(
                "Point order is the exact plotted boundary order. N in kN; M in "
                "kNm; N is tension-positive. Separate N columns are retained "
                "because the two traces may use different numerical points."
            )
        # Per-angle results tables -- split into readable groups with the NA angle
        # repeated as
        # the row key. A single 12-14-column table forced values to wrap digit by
        # digit in the issued PDF.
        self._h2("Capacity over the neutral-axis sweep")
        cable = bool(self.inp.get("tendons"))
        # Split the bar-strain column into the most tensile and the most compressed
        # bar only when there are mild bars active in compression (a tendon-only
        # section has none). Guard on the field so an older payload does not raise.
        comp = (bool(self.inp.get("bars"))
                and any(getattr(material, "active_in_compression", False)
                        for material in (self.inp.get("bar_materials")
                                         or [self.inp.get("steel")]))
                and bool(pl["points"]) and "eps_s_comp" in pl["points"][0])
        capacity_rows = [[
            "NA angle",
            "M<sub>x</sub>",
            "M<sub>y</sub>",
            "NA x",
            "NA y",
        ]]
        eps_s_head = (["eps<sub>s,t</sub>", "eps<sub>s,c</sub>"]
                      if comp else ["eps<sub>s</sub>"])
        detail_head = (["NA angle", "eps<sub>c</sub>"] + eps_s_head
                       + ["kappa", "F<sub>c</sub>", "lever L",
                          "d<sub>x</sub>", "d<sub>y</sub>"])
        if cable:
            detail_head.append("eps<sub>p</sub>")
        detail_rows = [detail_head]
        for p in pl["points"]:
            capacity_rows.append([
                _fmt(p["V"], 0),
                _fmt(p["Mx"], 3),
                _fmt(p["My"], 3),
                _fmt(p["na_x"] * _MM, 3),
                _fmt(p["na_y"] * _MM, 3),
            ])
            eps_s_vals = ([_fmt(p["eps_s"], 3), _fmt(p["eps_s_comp"], 3)] if comp
                          else [_fmt(p["eps_s"], 3)])
            row = ([_fmt(p["V"], 0), _fmt(p["eps_c"], 3)]
                   + eps_s_vals
                   + [_fmt(p["kappa"], 4), _fmt(p["comp_force"], 3),
                      _fmt(p["lever"] * _MM, 3), _fmt(p["dx"] * _MM, 3),
                      _fmt(p["dy"] * _MM, 3)])
            if cable:
                row.append(_fmt(p["eps_cable"], 3))
            detail_rows.append(row)
        self._small("<b>Capacity and neutral axis</b>")
        self._table(
            capacity_rows,
            [18 * mm, 38 * mm, 38 * mm, 38 * mm, 38 * mm],
            font=7.5,
            keep=False,
        )
        self._small("<b>Strain and equilibrium detail</b>")
        detail_cols = len(detail_head)
        self._table(
            detail_rows,
            [170 * mm / detail_cols] * detail_cols,
            font=7.2,
            keep=False,
        )
        self._small("NA angle in &#176;; M in kN&#183;m; NA x/y, lever L, d<sub>x</sub> "
                    "and d<sub>y</sub> in mm; strain in %; kappa in 1/m; "
                    "F<sub>c</sub> in kN.")
        # Governing case worked.
        self._plastic_worked(pl)

    def _plastic_worked(self, pl):
        # Show the state relevant to the check: when a utilisation was computed, the
        # angle governing the applied load's direction (so the worked strain plane and
        # equilibrium describe the section under that load); for a capacity-only run
        # there is no applied direction, so fall back to the strongest envelope point.
        gov_i = pl.get("util_gov")
        pts = pl["points"]
        if gov_i is not None and 0 <= gov_i < len(pts):
            gov = pts[gov_i]
            heading = "Governing case worked (utilisation direction)"
        else:
            gov = max(pts, key=lambda p: math.hypot(p["Mx"], p["My"]))
            heading = "Governing case worked (peak resultant moment)"
        P = self.inp.get("P_pl", 0.0) or 0.0   # applied axial, tension-positive
        Fc = gov["comp_force"]                  # concrete compression resultant (positive)
        T = Fc + P                              # tension resultant (solver: Fc - T = -N)
        start = len(self.flow)
        self._h2(heading)
        self._p(f"Neutral-axis angle = {_fmt(gov['V'],0)}&#176;. The extreme "
                f"concrete fibre is at the ultimate strain; the curvature scales "
                f"the strain plane to that limit.")
        comp = (bool(self.inp.get("bars"))
                and any(getattr(material, "active_in_compression", False)
                        for material in (self.inp.get("bar_materials")
                                         or [self.inp.get("steel")]))
                and "eps_s_comp" in gov)
        steel_rows = ([["Most-tensile bar strain", "eps<sub>s,t</sub>",
                        f"{_fmt(gov['eps_s'], 3)} %"],
                       ["Most-compressed bar strain", "eps<sub>s,c</sub>",
                        f"{_fmt(gov['eps_s_comp'], 3)} %"]] if comp else
                      [["Most-tensile bar strain", "eps<sub>s</sub>",
                        f"{_fmt(gov['eps_s'], 3)} %"]])
        rows = [["Quantity", "Symbol", "Value"],
                ["NA intercepts", "x<sub>na</sub>, y<sub>na</sub>",
                 f"{_fmt(gov['na_x']*_MM, 3)}, {_fmt(gov['na_y']*_MM, 3)} mm"],
                ["Extreme concrete strain", "eps<sub>c</sub>", f"{_fmt(gov['eps_c'], 3)} %"],
                *steel_rows,
                ["Curvature", "kappa", f"{_fmt(gov['kappa'],4)} 1/m"],
                ["Concrete compression resultant", "F<sub>c</sub>", f"{_fmt(Fc, 3)} kN"],
                ["Internal lever arm", "L", f"{_fmt(gov['lever']*_MM, 3)} mm"],
                ["Lever components", "d<sub>x</sub>, d<sub>y</sub>",
                 f"{_fmt(gov['dx']*_MM, 3)}, {_fmt(gov['dy']*_MM, 3)} mm"],
                ["Capacity", "M<sub>x</sub>, M<sub>y</sub>",
                 f"{_fmt(gov['Mx'], 3)}, {_fmt(gov['My'], 3)} kNm"]]
        self._table(rows, [70 * mm, 30 * mm, 60 * mm])
        self._keep_from(start)
        self._h2("Axial equilibrium check")
        self._formula("T - F<sub>c</sub> = N",
                      equation_key="plastic.worked.axial-equilibrium",
                      subst=f"{_fmt(T, 3)} - {_fmt(Fc, 3)} = {_fmt(T-Fc, 3)} kN",
                      result=f"applied N = {_fmt(P, 3)} kN  (residual "
                             f"{_fmt(abs(T - Fc - P),3)} kN)")
        self._small("The tension resultant T = F<sub>c</sub> + N balances the "
                    "section (N tension-positive); the moments above are the "
                    "resultants about the origin.")
        evidence = presentation.plastic_state_evidence(self.inp, gov)
        concrete_rows = evidence["concrete"]
        if concrete_rows:
            self._h2("Governing concrete corner response")
            rows = [[
                "Point", "Ring", "Ring point", "x", "y", "Strain", "Design stress",
            ]]
            for row in concrete_rows:
                rows.append([
                    str(row["point_no"]),
                    row["ring"],
                    str(row["ring_point_no"]),
                    _fmt(row["x_mm"], 2),
                    _fmt(row["y_mm"], 2),
                    _fmt(row["strain_permille"], 5),
                    _fmt(row["stress_mpa"], 3),
                ])
            self._table(
                rows,
                [14 * mm, 24 * mm, 19 * mm, 22 * mm, 22 * mm,
                 32 * mm, 37 * mm],
                font=6.8,
                keep=False,
                repeat_cols=3,
            )
            self._small(
                "Coordinates in mm; strain in permille; design stress in MPa. "
                "Strain and stress are tension-positive."
            )
        element_rows = evidence["elements"]
        if element_rows:
            self._h2("Governing reinforcement and tendon response")
            rows = [[
                "Element", "Material", "State", "x", "y", "Area", "Strain",
                "Design stress", "Force",
            ]]
            for row in element_rows:
                rows.append([
                    row["element_id"],
                    row.get("material_id") or "-",
                    row["state"],
                    _fmt(row["x_mm"], 2),
                    _fmt(row["y_mm"], 2),
                    _fmt(row["area_mm2"], 2),
                    _fmt(row["strain_permille"], 5),
                    _fmt(row["stress_mpa"], 3),
                    _fmt(row["force_kn"], 3),
                ])
            self._table(
                rows,
                [21 * mm, 18 * mm, 17 * mm, 15 * mm, 15 * mm, 18 * mm,
                 22 * mm, 22 * mm, 20 * mm],
                font=6.1,
                keep=False,
                repeat_cols=3,
            )
            self._small(
                "Coordinates in mm; area in mm<super>2</super>; strain in "
                "permille; design stress in MPa; force in kN. Signs are "
                "tension-positive; force = stress x entered area."
            )
        # Section state at the governing angle (neutral axis + compression zone).
        if self.figures:
            inp = self.inp
            hp = evidence["halfplane"]
            na = viz.na_line_at(hp[0], hp[1], hp[2], inp.get("extent", 1.0))
            zones = viz.compression_zones(inp.get("outer", []), hp)
            bars = inp.get("bars", [])
            tendons = inp.get("tendons", [])
            bar_colors = viz.halfplane_bar_colors(
                bars, hp, kappa=gov["kappa"],
            )
            tendon_colors = viz.halfplane_bar_colors(
                tendons,
                hp,
                kappa=gov["kappa"],
                prestrain=(
                    [material.IS for material in inp.get("tendon_materials", [])]
                    if inp.get("tendon_materials") else
                    float(getattr(inp.get("prestress"), "IS", 0.0))
                ),
            )
            self._h2("Section state at the governing angle")
            self._fig(viz.section_figure(
                inp.get("outer", []), inp.get("holes", []), bars,
                bar_colors=bar_colors, na_line=na, tendons=tendons,
                tendon_colors=tendon_colors, zones=zones, show_labels=False,
                scale=_MM, unit="mm",
                bar_ids=[item.get("id") for item in inp.get("bar_elements", [])],
                tendon_ids=[item.get("id") for item in inp.get("tendon_elements", [])],
                title=f"Plastic state at NA angle = {_fmt(gov['V'],0)}{chr(0x00B0)} "
                      "(tension + / compression -)"), 150, 100)
            self._small(
                "Blue/plain markers are tension (+); vermillion/x markers are "
                "compression (-). Bar circles and tendon diamonds identify the "
                "element type. Element IDs and coordinates are tabulated above."
            )

    def _shear_2023(self, sh, res):
        """The EN 1992-1-1:2023 strain-based tau_Rd,c body (sec. 8.2.2)."""
        bw_src = "user input" if sh["bw_user"] else "derived (minimum solid width)"
        fck = sh["fck"]
        rows = [["Quantity", "Symbol", "Value"],
                ["Effective depth", "d", f"{_fmt(sh['d'], 1)} mm"],
                ["Web width", "b<sub>w</sub>", f"{_fmt(sh['bw'], 1)} mm ({bw_src})"],
                ["Lever arm", "z", f"{_fmt(res['z'], 1)} mm (0.9 d)"],
                ["Tension reinforcement", "A<sub>sl</sub>",
                 f"{_fmt(sh['asl'], 1)} mm<sup>2</sup>"],
                ["Reinforcement ratio", "rho<sub>l</sub>", f"{_fmt(res['rho_l'], 4)}"],
                ["Action moment at centroid", "M<sub>Ed</sub>",
                 f"{_fmt(sh.get('m_ed_2023'), 3)} kNm"],
                ["Effective shear span", "a<sub>cs</sub>",
                 (f"{_fmt(res.get('a_cs'), 1)} mm"
                  if res.get("a_cs", 0.0) > 0.0 else "not applicable (VEd = 0)")],
                ["Axial-force factor", "k<sub>vp</sub>",
                 f"{_fmt(res.get('k_vp'), 4)} (>= 0.1)"],
                ["Modified depth in Formula (8.27)", "k<sub>vp</sub>d",
                 f"{_fmt(res.get('d_kvp'), 1)} mm"],
                ["Aggregate size", "d<sub>dg</sub>", f"{_fmt(res['ddg'], 1)} mm"],
                ["Flexural design yield", "f<sub>yd</sub>",
                 f"{_fmt(res['fyd'], 1)} MPa"],
                ["Shear partial factor", "gamma<sub>v</sub>",
                 f"{_fmt(res['gamma_v'], 2)}"]]
        self._table(rows, [55 * mm, 25 * mm, 70 * mm])
        self._h2("Resistance")
        if res.get("a_cs", 0.0) > 0.0:
            self._formula(
                "a<sub>cs</sub> = max(|M<sub>Ed</sub>/V<sub>Ed</sub>|, d)",
                equation_key="shear.2023.effective-span",
                ref="EN 1992-1-1:2023 Formula (8.30)",
                subst=f"max(|{_fmt(sh.get('m_ed_2023'), 3)}| / "
                      f"{_fmt(sh.get('v_ed'), 3)} &#183; 1000, {_fmt(sh['d'], 1)})",
                result=f"a<sub>cs</sub> = {_fmt(res.get('a_cs'), 1)} mm")
            self._formula(
                "k<sub>vp</sub> = max(1 + N<sub>Ed</sub>/|V<sub>Ed</sub>| &#183; "
                "d/(3a<sub>cs</sub>), 0.1)",
                equation_key="shear.2023.axial-factor",
                ref="EN 1992-1-1:2023 &#167;8.2.2(4), Formula (8.31)",
                subst=f"N<sub>Ed</sub> = {_fmt(res.get('n_ed_tension'), 3)} kN; "
                      f"k<sub>vp</sub> = {_fmt(res.get('k_vp'), 4)}",
                result=f"k<sub>vp</sub>d = {_fmt(res.get('d_kvp'), 1)} mm")
        self._formula(
            "tau<sub>Rd,c</sub> = (0.66/gamma<sub>v</sub>)(100 rho<sub>l</sub> "
            "f<sub>ck</sub> d<sub>dg</sub>/(k<sub>vp</sub>d))<sup>1/3</sup>",
            equation_key="shear.2023.tau-basic",
            ref="EN 1992-1-1:2023 (8.27), stress",
            subst=f"(0.66/{_fmt(res['gamma_v'], 2)})(100 &#183; "
                  f"{_fmt(res['rho_l'], 4)} &#183; {_fmt(fck, 0)} &#183; "
                  f"{_fmt(res['ddg'], 1)}/{_fmt(res.get('d_kvp'), 1)})"
                  "<sup>1/3</sup>",
            result=f"tau = {_fmt(res['tau_basic'], 3)} MPa")
        self._formula(
            "tau<sub>Rd,c,min</sub> = (11/gamma<sub>v</sub>) "
            "&#8730;(f<sub>ck</sub>/f<sub>yd</sub> &#183; d<sub>dg</sub>/d)",
            equation_key="shear.2023.tau-minimum",
            ref="EN 1992-1-1:2023 (8.20)",
            subst=f"(11/{_fmt(res['gamma_v'], 2)}) &#8730;({_fmt(fck, 0)}/"
                  f"{_fmt(res['fyd'], 1)} &#183; {_fmt(res['ddg'], 1)}/"
                  f"{_fmt(sh['d'], 1)})",
            result=f"tau<sub>min</sub> = {_fmt(res['tau_min'], 3)} MPa")
        self._formula(
            "V<sub>Rd,c</sub> = max(tau<sub>Rd,c</sub>, tau<sub>Rd,c,min</sub>) "
            "b<sub>w</sub> z",
            equation_key="shear.2023.vrdc",
            references=("shear.2023.tau-basic", "shear.2023.tau-minimum"),
            subst=f"max({_fmt(res['tau_rdc'], 3)}, {_fmt(res['tau_min'], 3)}) &#183; "
                  f"{_fmt(sh['bw'], 1)} &#183; {_fmt(res['z'], 1)} / 1000",
            result=f"V<sub>Rd,c</sub> = {_fmt(res['vrd_c'], 3)} kN")
        util = sh["util"]
        util_txt = _pct(util)
        verdict = "OK" if viz.util_ok(util) else "EXCEEDED"
        self._h2("Utilisation")
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd,c</sub>",
                      equation_key="shear.2023.utilisation",
                      subst=f"{_fmt(sh['v_ed'], 3)} / {_fmt(res['vrd_c'], 3)}",
                      result=f"{util_txt}  ({verdict})")
        self._small(
            "The 2023 tau<sub>Rd,c</sub> uses d<sub>dg</sub> = 16 + "
            "D<sub>lower</sub>, the flexural design yield and the Formula (8.31) "
            "axial-force modification. N<sub>Ed</sub> and M<sub>Ed</sub> include "
            "the locked-in tendon prestress effects in accordance with 8.2.1(8). "
            "Tendons are assumed parallel to the member axis "
            "(cos beta = 1)."
        )
        if sh.get("links") is not None:
            self._shear_links(sh)

    def _shear(self):
        aggregate = self.out["shear"]
        directions = aggregate.get("directions") or {}
        if not directions:
            self._shear_direction(aggregate)
            return

        self._case_heading("Shear resistance", "plastic")
        if aggregate.get("biaxial") and self.figures:
            components = self.inp.get("shear_components") or {}
            self._fig(
                viz.biaxial_shear_overview_figure(
                    self.inp.get("outer", []), self.inp.get("holes", []),
                    self.inp.get("bars", []),
                    vx_ed=(components.get("vx") or {}).get(
                        "signed_v_ed", self.inp.get("shear_Vx", 0.0)
                    ),
                    vy_ed=(components.get("vy") or {}).get(
                        "signed_v_ed", self.inp.get("shear_Vy", 0.0)
                    ),
                    title="Directional shear actions",
                ),
                145,
                100,
            )
        rows = [["Direction", "V<sub>Ed</sub>", "V<sub>Rd</sub>",
                 "Utilisation", "Status", "Tension face"]]
        for component in ("vx", "vy"):
            if component not in directions:
                continue
            item = directions[component]
            links = item.get("links") or {}
            resistance = (
                (links.get("res") or {}).get("vrd")
                if self.inp.get("shear_links") else (item.get("res") or {}).get("vrd_c")
            )
            utilisation = links.get("util") if self.inp.get("shear_links") else item.get("util")
            rows.append([
                "V<sub>x,Ed</sub>" if component == "vx" else "V<sub>y,Ed</sub>",
                f"{_fmt(item.get('signed_v_ed', item.get('v_ed')), 3)} kN",
                f"{_fmt(resistance, 3)} kN",
                _pct(utilisation), item.get("status", "NOT ASSESSED"),
                viz.tension_face_label(item.get("tension_low", True), item.get("axis")),
            ])
        self._table(rows, [25 * mm, 27 * mm, 27 * mm, 27 * mm, 28 * mm, 38 * mm])
        if aggregate.get("biaxial"):
            self._small(
                "V<sub>x</sub> and V<sub>y</sub> are calculated independently. "
                "Generic cross-direction interaction is not calculated and no "
                "aggregate shear verdict is issued."
            )
        for component in ("vx", "vy"):
            if component in directions:
                label = "V<sub>x,Ed</sub>" if component == "vx" else "V<sub>y,Ed</sub>"
                self._h2(f"{label} directional check")
                self._shear_direction(
                    directions[component], include_case_heading=False,
                    component=component,
                )

    def _shear_direction(self, sh, *, include_case_heading=True, component=None):
        res = sh["res"]
        if include_case_heading:
            self._case_heading("Shear resistance", "plastic")
        component = component or sh.get("component") or (
            "vy" if sh["axis"] == "x" else "vx"
        )
        axis = ("Vy along y, paired with Mx" if component == "vy"
                else "Vx along x, paired with My")
        action = "V<sub>y,Ed</sub>" if component == "vy" else "V<sub>x,Ed</sub>"
        face = viz.tension_face_label(sh["tension_low"], sh["axis"])
        clause = "8.2.2" if sh.get("model_2023") else "6.2.2(1)"
        self._p(f"Design shear resistance V<sub>Rd,c</sub> of a member not requiring "
                f"shear reinforcement (EN 1992-1-1 sec. {clause}), method "
                f"<b>{sh['method']}</b>. {axis}, with the "
                f"tension reinforcement on the {face} face.")
        signed_action = float(sh.get("signed_v_ed", sh.get("v_ed", 0.0)))
        self._small(
            f"Entered {action} = {_fmt(signed_action, 3)} kN; resistance and "
            f"utilisation use |{action}| = {_fmt(abs(signed_action), 3)} kN."
        )
        if sh.get("face_mode") == "auto":
            self._small(
                "Automatic face selection uses the associated moment at the "
                "concrete centroid: "
                f"{_fmt(sh.get('associated_moment'), 3)} kNm."
            )
        if not res["valid"]:
            self._small("Warning: V<sub>Rd,c</sub> is zero -- no tension "
                        "reinforcement on the chosen face, or a zero effective depth "
                        "/ web width.")
        if sh.get("both_faces_evaluated"):
            face_rows = [["Candidate face", "V<sub>Rd,c</sub>",
                          "|V<sub>Ed</sub>|/V<sub>Rd,c</sub>",
                          "|V<sub>Ed</sub>|/V<sub>Rd</sub>",
                          "Shear", "V+T", "Combined"]]
            for candidate in sh.get("face_candidates", []):
                candidate_shear = candidate.get("shear") or {}
                candidate_links = candidate_shear.get("links") or {}
                face_rows.append([
                    viz.tension_face_label(
                        candidate.get("tension_low", True), sh["axis"]
                    ),
                    f"{_fmt((candidate_shear.get('res') or {}).get('vrd_c'), 3)} kN",
                    _pct(candidate_shear.get("util")),
                    ("-" if candidate_links.get("util") is None
                     else _pct(candidate_links.get("util"))),
                    candidate.get("shear_status", "NOT ASSESSED"),
                    candidate.get("torsion_status", "NOT RUN"),
                    candidate.get("combined_status", "NOT RUN"),
                ])
            self._small(
                "The associated bending moment is effectively zero; both faces are "
                "mandatory. Shear, V+T and combined checks may govern on different "
                "faces."
            )
            self._table(
                face_rows,
                [30 * mm, 23 * mm, 26 * mm, 23 * mm, 21 * mm, 21 * mm, 26 * mm],
                font=5.8,
            )
            governing_domains = sh.get("governing_domains") or {}
            labels = {
                "shear": "Shear",
                "vt": "V+T (6.29)",
                "minimum_reinforcement": "Minimum reinf. (6.31)",
                "combined": "Combined",
            }
            governing_rows = [["Check", "Governing face", "cot theta",
                               "Value / util.", "Status / outcome"]]
            for key in ("shear", "vt", "minimum_reinforcement", "combined"):
                domain = governing_domains.get(key)
                if not domain:
                    continue
                status = domain.get("status")
                if key == "minimum_reinforcement":
                    status = {
                        "PASS": "minimum sufficient",
                        "FAIL": "designed reinforcement required",
                    }.get(status, str(status or "NOT ASSESSED").lower())
                governing_rows.append([
                    labels[key],
                    viz.directional_face_label(component, domain.get("face")),
                    _fmt(domain.get("cot"), 3),
                    _pct(domain.get("util")),
                    status,
                ])
            self._h2("Independent governing selections")
            self._table(
                governing_rows,
                [35 * mm, 38 * mm, 24 * mm, 31 * mm, 42 * mm],
                font=6.5,
            )
        links_payload = sh.get("links") or {}
        link_res = links_payload.get("res") or {}
        z_geometry = float(link_res.get("z", res.get("z", 0.9 * sh["d"])))
        bw_src = "user input" if sh["bw_user"] else "auto minimum solid width"
        if self.figures:
            self._h2("Derived shear geometry")
            self._fig(
                viz.shear_geometry_figure(
                    self.inp.get("outer", []), self.inp.get("holes", []),
                    self.inp.get("bars", []), axis=sh["axis"],
                    tension_low=sh["tension_low"],
                    centroid=sh.get("centroid", (0.0, 0.0)),
                    asl_bar_ids=sh.get("asl_bar_ids", []),
                    asl_cg_m=sh.get("asl_cg"), asl_mm2=sh["asl"],
                    d_mm=sh["d"], z_mm=z_geometry, bw_mm=sh["bw"],
                    bw_source=bw_src,
                    signed_v_ed=sh.get("signed_v_ed", sh.get("v_ed")),
                    title=f"{action} geometry - {face} tension",
                ),
                145,
                103,
            )
            self._small(
                "Star markers are the bars included in A<sub>sl</sub>; the dotted "
                "line is the gross-section centroid used as the selection boundary."
            )
        if sh.get("model_2023"):
            self._shear_2023(sh, res)
            return
        bw_src = "user input" if sh["bw_user"] else "derived (minimum solid width)"
        fck = sh["fck"]
        k1 = res["k1"]
        rows = [["Quantity", "Symbol", "Value"],
                ["Effective depth", "d", f"{_fmt(sh['d'], 1)} mm"],
                ["Web width", "b<sub>w</sub>", f"{_fmt(sh['bw'], 1)} mm ({bw_src})"],
                ["Tension reinforcement", "A<sub>sl</sub>",
                 f"{_fmt(sh['asl'], 1)} mm<sup>2</sup>"],
                ["Reinforcement ratio", "rho<sub>l</sub>",
                 f"{_fmt(res['rho_l'], 4)} (&#8804; 0.02)"],
                ["Size factor", "k", f"{_fmt(res['k'], 3)} (&#8804; 2.0)"],
                ["Concrete area", "A<sub>c</sub>",
                 f"{_fmt(sh['ac'] * 1e6, 0)} mm<sup>2</sup>"],
                ["Axial force (Plastic)", "N", f"{_fmt(sh['n_ed'], 3)} kN (tension +)"],
                ["Axial stress", "sigma<sub>cp</sub>",
                 f"{_fmt(res['sigma_cp'], 3)} MPa (&#8804; 0.2 f<sub>cd</sub>)"],
                ["Design concrete strength", "f<sub>cd</sub>",
                 f"{_fmt(res['fcd'], 2)} MPa"],
                ["Coefficient", "C<sub>Rd,c</sub>", f"{_fmt(res['crd_c'], 4)}"],
                ["Coefficient", "k<sub>1</sub>", f"{_fmt(k1, 2)}"],
                ["Lower-bound stress", "v<sub>min</sub>",
                 f"{_fmt(res['vmin'], 3)} MPa"]]
        if sh.get("n_prestress"):
            rows.insert(8, ["Tendon precompression", "P<sub>m</sub>",
                            f"{_fmt(sh['n_prestress'], 3)} kN (compression +)"])
        self._table(rows, [55 * mm, 25 * mm, 70 * mm])
        self._h2("Resistance")
        # The two 6.2.a/6.2.b terms are stresses (MPa); the resistance multiplies the
        # governing stress by b_w*d (and /1000 for MPa*mm^2 = N -> kN). Keep each
        # substitution in its own units so the worked calc is dimensionally consistent.
        self._formula(
            "v = C<sub>Rd,c</sub> k (100 rho<sub>l</sub> f<sub>ck</sub>)<sup>1/3</sup> "
            "+ k<sub>1</sub> sigma<sub>cp</sub>",
            equation_key="shear.2005.stress-basic",
            ref="EN 1992-1-1 (6.2.a), stress",
            subst=f"{_fmt(res['crd_c'], 4)} &#183; {_fmt(res['k'], 3)} &#183; (100 "
                  f"&#183; {_fmt(res['rho_l'], 4)} &#183; {_fmt(fck, 0)})<sup>1/3</sup> "
                  f"+ {_fmt(k1, 2)} &#183; {_fmt(res['sigma_cp'], 3)}",
            result=f"v = {_fmt(res['v_basic'], 3)} MPa")
        self._formula(
            "v<sub>min,eff</sub> = v<sub>min</sub> + k<sub>1</sub> sigma<sub>cp</sub>",
            equation_key="shear.2005.stress-minimum",
            ref="EN 1992-1-1 (6.2.b), lower-bound stress",
            subst=f"{_fmt(res['vmin'], 3)} + {_fmt(k1, 2)} &#183; "
                  f"{_fmt(res['sigma_cp'], 3)}",
            result=f"v<sub>min,eff</sub> = {_fmt(res['v_floor'], 3)} MPa")
        self._formula(
            "V<sub>Rd,c</sub> = max(v, v<sub>min,eff</sub>) &#183; b<sub>w</sub> "
            "&#183; d",
            equation_key="shear.2005.vrdc",
            references=("shear.2005.stress-basic", "shear.2005.stress-minimum"),
            subst=f"max({_fmt(res['v_basic'], 3)}, {_fmt(res['v_floor'], 3)}) &#183; "
                  f"{_fmt(sh['bw'], 1)} &#183; {_fmt(sh['d'], 1)} / 1000",
            result=f"V<sub>Rd,c</sub> = {_fmt(res['vrd_c'], 3)} kN")
        util = sh["util"]
        util_txt = _pct(util)
        verdict = "OK" if viz.util_ok(util) else "EXCEEDED"
        self._h2("Utilisation")
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd,c</sub>",
                      equation_key="shear.2005.utilisation",
                      subst=f"{_fmt(sh['v_ed'], 3)} / {_fmt(res['vrd_c'], 3)}",
                      result=f"{util_txt}  ({verdict})")
        self._small("A<sub>sl</sub> is the tension reinforcement on the chosen face, "
                    "assumed fully anchored (&#8805; l<sub>bd</sub> + d) beyond the "
                    "section. sigma<sub>cp</sub> uses the plastic axial force "
                    "plus any tendon precompression from the prestress. A section with "
                    "V<sub>Ed</sub> &gt; V<sub>Rd,c</sub> requires designed shear "
                    "reinforcement.")
        if sh.get("links") is not None:
            self._shear_links(sh)

    def _shear_links(self, sh):
        links = sh["links"]
        lk = links["res"]
        self._h2("Shear reinforcement (links)")
        model_2023 = bool(links.get("model_2023"))
        clause = "8.2.3" if model_2023 else "6.2.3"
        req = ("required (V<sub>Ed</sub> &gt; V<sub>Rd,c</sub>)" if links["required"]
               else "not strictly required (V<sub>Ed</sub> &#8804; V<sub>Rd,c</sub>); "
                    "minimum reinforcement rules still apply")
        self._p(f"With vertical links the resistance is the compression-field "
                f"V<sub>Rd</sub> = min(V<sub>Rd,s</sub>, V<sub>Rd,max</sub>) "
                f"(EN 1992-1-1 sec. {clause}). For this V<sub>Ed</sub>, links are {req}.")
        if not lk["valid"]:
            self._small("Warning: the link resistance is zero -- check the leg count, "
                        "diameter and spacing (A<sub>sw</sub>/s must be &gt; 0).")
            return
        if links["out_of_limits"]:
            limit_ref = (
                (links.get("angle_limits") or {}).get("clause")
                or "EN 1992-1-1:2005, 6.2.3(2)"
            )
            self._small(f"Warning: the strut bounds cot theta in "
                        f"[{_fmt(links['cot_min'], 2)}, {_fmt(links['cot_max'], 2)}] "
                        f"fall outside the selected method's default range "
                        f"[{_fmt(links['cot_limit_lo'], 1)}, "
                        f"{_fmt(links['cot_limit_hi'], 1)}] ({limit_ref}). "
                        "The actual values are retained in the links and dependent "
                        "interaction calculations.")
        rows = [["Quantity", "Symbol", "Value"],
                ["Links", "n x phi / s",
                 f"{_fmt(links['legs'], 0)} x {_fmt(links['dia'], 0)} / "
                 f"{_fmt(links['s'], 0)} mm"],
                ["Link area / spacing", "A<sub>sw</sub>/s",
                 f"{_fmt(links['asw'], 1)} / {_fmt(links['s'], 0)} mm<sup>2</sup>/mm"],
                ["Design link yield", "f<sub>ywd</sub>", f"{_fmt(lk['fywd'], 1)} MPa"],
                ["Lever arm", "z",
                 f"{_fmt(lk['z'], 1)} mm ({links.get('z_source', '0.9 d')})"],
                ["Strut angle", "theta",
                 f"{_fmt(lk['theta_deg'], 1)}&#176; "
                 f"(cot theta = {_fmt(lk['cot'], 3)})"],
                [
                    "Compression factor" if model_2023 else "Strut factor",
                    "nu" if model_2023 else "nu<sub>1</sub>",
                    f"{_fmt(lk['nu'] if model_2023 else lk['nu1'], 3)}",
                ]]
        if model_2023:
            angle_limits = links.get("angle_limits") or {}
            rows.extend([
                ["Permitted angle range", "cot theta",
                 f"{_fmt(links['cot_limit_lo'], 2)} to "
                 f"{_fmt(links['cot_limit_hi'], 2)} "
                 f"(class {angle_limits.get('ductility_class', 'B')})"],
                ["Link ratio", "rho<sub>w</sub>", _fmt(lk["rho_w"], 5)],
                ["Applied shear stress", "tau<sub>Ed</sub>",
                 f"{_fmt(lk['tau_ed'], 3)} MPa"],
                ["Link-yield resistance", "tau<sub>Rd,sy</sub>",
                 f"{_fmt(lk['tau_rd_sy'], 3)} MPa"],
                ["Compression-field stress", "sigma<sub>cd</sub>",
                 f"{_fmt(lk['sigma_cd'], 3)} MPa"],
                ["Compression-field limit", "nu f<sub>cd</sub>",
                 f"{_fmt(lk['nu_fcd'], 3)} MPa"],
                ["Additional chord force", "N<sub>Vd</sub>",
                 f"{_fmt(links['longitudinal_shear_force'], 1)} kN"],
            ])
        else:
            rows.append(
                ["Chord factor", "alpha<sub>cw</sub>",
                 f"{_fmt(lk['alpha_cw'], 3)}"]
            )
        self._table(rows, [55 * mm, 25 * mm, 70 * mm])
        self._fig(viz.truss_figure(lk["theta_deg"], lk["z"], links["legs"],
                                   links["dia"], links["s"]), 130, 80)
        if model_2023:
            self._formula(
                "tau<sub>Rd,sy</sub> = rho<sub>w</sub> f<sub>ywd</sub> cot theta",
                equation_key="shear.links.tau-yield",
                ref="EN 1992-1-1:2023 Formula (8.42)",
                subst=f"{_fmt(lk['rho_w'], 5)} &#183; {_fmt(lk['fywd'], 1)} "
                      f"&#183; {_fmt(lk['cot'], 3)}",
                result=f"tau<sub>Rd,sy</sub> = {_fmt(lk['tau_rd_sy'], 3)} MPa")
            self._formula(
                "sigma<sub>cd</sub> = tau<sub>Ed</sub>"
                "(cot theta + tan theta) &#8804; nu f<sub>cd</sub>",
                equation_key="shear.links.sigma-field",
                ref="EN 1992-1-1:2023 Formula (8.44)",
                subst=f"{_fmt(lk['tau_ed'], 3)} &#183; "
                      f"({_fmt(lk['cot'], 3)} + {_fmt(1.0 / lk['cot'], 3)}) "
                      f"&#8804; {_fmt(lk['nu'], 3)} &#183; {_fmt(lk['fcd'], 2)}",
                result=f"sigma<sub>cd</sub> = {_fmt(lk['sigma_cd'], 3)} MPa; "
                       f"limit = {_fmt(lk['nu_fcd'], 3)} MPa")
            self._formula(
                "V<sub>Rd,s</sub> = tau<sub>Rd,sy</sub> b<sub>w</sub> z",
                equation_key="shear.links.vrds",
                equation_variant="2023",
                references=("shear.links.tau-yield",),
                subst=f"{_fmt(lk['tau_rd_sy'], 3)} &#183; {_fmt(sh['bw'], 1)} "
                      f"&#183; {_fmt(lk['z'], 1)} / 1000",
                result=f"V<sub>Rd,s</sub> = {_fmt(lk['vrd_s'], 3)} kN")
            self._formula(
                "V<sub>Rd,max</sub> = nu f<sub>cd</sub> b<sub>w</sub> z / "
                "(cot theta + tan theta)",
                equation_key="shear.links.vrdmax",
                equation_variant="2023",
                references=("shear.links.sigma-field",),
                subst=f"{_fmt(lk['nu_fcd'], 3)} &#183; {_fmt(sh['bw'], 1)} "
                      f"&#183; {_fmt(lk['z'], 1)} / "
                      f"({_fmt(lk['cot'], 3)} + {_fmt(1.0 / lk['cot'], 3)}) / 1000",
                result=f"V<sub>Rd,max</sub> = {_fmt(lk['vrd_max'], 3)} kN")
        else:
            self._formula(
                "V<sub>Rd,s</sub> = (A<sub>sw</sub>/s) z f<sub>ywd</sub> cot theta",
                equation_key="shear.links.vrds",
                equation_variant="2005",
                ref="EN 1992-1-1 (6.8)",
                subst=f"{_fmt(links['asw_over_s'], 4)} &#183; {_fmt(lk['z'], 1)} "
                      f"&#183; {_fmt(lk['fywd'], 1)} &#183; {_fmt(lk['cot'], 3)} / 1000",
                result=f"V<sub>Rd,s</sub> = {_fmt(lk['vrd_s'], 3)} kN")
            self._formula(
                "V<sub>Rd,max</sub> = alpha<sub>cw</sub> b<sub>w</sub> z "
                "nu<sub>1</sub> f<sub>cd</sub> / (cot theta + tan theta)",
                equation_key="shear.links.vrdmax",
                equation_variant="2005",
                ref="EN 1992-1-1 (6.9)",
                subst=f"{_fmt(lk['alpha_cw'], 3)} &#183; {_fmt(sh['bw'], 1)} &#183; "
                      f"{_fmt(lk['z'], 1)} &#183; {_fmt(lk['nu1'], 3)} &#183; "
                      f"{_fmt(lk['fcd'], 2)} / ({_fmt(lk['cot'], 3)} + "
                      f"{_fmt(1.0 / lk['cot'], 3)}) / 1000",
                result=f"V<sub>Rd,max</sub> = {_fmt(lk['vrd_max'], 3)} kN")
        self._formula(
            "V<sub>Rd</sub> = min(V<sub>Rd,s</sub>, V<sub>Rd,max</sub>)",
            equation_key="shear.links.vrd",
            references=("shear.links.vrds", "shear.links.vrdmax"),
            result=f"V<sub>Rd</sub> = {_fmt(lk['vrd'], 3)} kN "
                   f"(governed by {lk['governs']})")
        util = links["util"]
        util_txt = _pct(util)
        verdict = _demand_resistance_verdict(viz.util_ok(util))
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd</sub>",
                      equation_key="shear.links.utilisation",
                      references=("shear.links.vrd",),
                      subst=f"{_fmt(sh['v_ed'], 3)} / {_fmt(lk['vrd'], 3)}",
                      result=f"{util_txt}  ({verdict})")
        if links.get("theta_mode") == "utilisation":
            shared_note = (
                "shared with torsion when enabled"
                if model_2023
                else "shared with torsion when enabled under 6.3.2(2)"
            )
            angle_note = (f"The strut angle is the one member angle ({shared_note}), "
                          "selected within the bounds to minimise the governing utilisation: a "
                          "flatter strut relaxes the stirrups but raises the crushing "
                          "demand and the longitudinal chord tension, so the angle "
                          "depends on the applied actions.")
        else:
            angle_note = ("The strut angle is auto-optimised within the bounds to "
                          "maximise V<sub>Rd</sub>.")
        if model_2023:
            self._small(
                angle_note + " The additional longitudinal force is "
                "N<sub>Vd</sub> = |V<sub>Ed</sub>| cot theta = "
                f"{_fmt(links['longitudinal_shear_force'], 1)} kN (8.50). "
                "The support/load-specific relief in (8.53) is not credited."
            )
        else:
            self._small(
                angle_note + " The shear adds a longitudinal tension "
                "&#916;F<sub>td</sub> = 0.5 V<sub>Ed</sub> cot theta = "
                f"{_fmt(links['longitudinal_shear_force'], 1)} kN (6.18)."
            )
        # Longitudinal chord under M + V (+ T), at the member strut angle -- the
        # same check the combined section shows; printed here so a shear + bending
        # run without torsion still documents it.
        ch = links.get("chord")
        if ch is not None and ch.get("valid"):
            self._h2("Longitudinal chord: bending + shear"
                     + (" + torsion" if ch.get("has_torsion") else "") + " tension")
            vv = _demand_resistance_verdict(ch["ok"])
            coverage = ch.get("off_not_evaluated")
            face = viz.tension_face_label(
                ch.get("tension_low", True), ch.get("axis")
            )
            if model_2023:
                chord_formula = (
                    "M<sub>Ed,total</sub> = M<sub>Ed</sub> + "
                    "N<sub>Vd</sub>&#183;z + F<sub>td,T</sub>&#183;z/2"
                )
                chord_ref = "EN 1992-1-1:2023, 8.2.3(8), Formulae (8.50)-(8.52)"
            else:
                chord_formula = (
                    "M<sub>Ed,total</sub> = M<sub>Ed</sub> + "
                    "&#916;F<sub>td</sub>&#183;z + F<sub>td,T</sub>&#183;z/2"
                )
                chord_ref = "EN 1992-1-1 6.2.3(7) + 6.3.2"
            self._formula(
                chord_formula,
                equation_key="shear.chord.demand",
                equation_variant="2023" if model_2023 else "2005",
                ref=chord_ref,
                subst=f"{_fmt(ch['m_ed'], 1)} + {_fmt(ch['mv'], 1)} + "
                      f"{_fmt(ch['mt'], 1)} kNm  (z = {_fmt(ch['z'], 3)} m)",
                result=f"M<sub>Ed,total</sub> = {_fmt(ch['m_total'], 1)} kNm")
            fallback = presentation.required_chord_fallback(links)
            fell_back = fallback is not None
            if coverage:
                verdict_suffix = (
                    "  (NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE)"
                )
            elif fell_back:
                verdict_suffix = (
                    "  (NOT ASSESSED - DISPLAYED CAPACITY IS PURE-AXIS FALLBACK)"
                    if not ch.get("conditional", True)
                    else "  (NOT ASSESSED - ANOTHER REQUIRED FACE USES FALLBACK)"
                )
            else:
                verdict_suffix = f"  ({vv})"
            self._formula(
                "M<sub>Ed,total</sub> / M<sub>Rd</sub>",
                equation_key="shear.chord.utilisation",
                references=("shear.chord.demand",),
                subst=f"{_fmt(ch['m_total'], 1)} / {_fmt(ch['m_rd'], 1)}",
                result=f"utilisation = {_pct(ch['util'])}{verdict_suffix}")
            face_desc = (f"the shear tension face ({face})" if ch.get("gets_shift", True)
                         else f"the shear compression face ({face}) -- the torsion "
                         "tension governs there, with no shear shift and the bending "
                         "relieving rather than adding")
            note = (f"Tension chord = {face_desc}; M<sub>Rd</sub> "
                    + viz.chord_mrd_label(ch["axis"], ch.get("m_off", 0.0),
                                          ch.get("conditional", True)) + ".")
            if ch.get("theta_mode") == "utilisation":
                demand_word = "uncapped" if model_2023 else "capped"
                note += (f" This {demand_word} demand is part of the strut-angle objective, "
                         "so theta backs off the band edge when the chord would "
                         "otherwise govern.")
            if fell_back:
                fallback_axis = fallback.get("axis", "?")
                fallback_face = (
                    "negative" if fallback.get("tension_low", True)
                    else "positive"
                )
                note += (
                    f" The required {fallback_axis}-axis {fallback_face} face "
                    "uses a pure-axis fallback because its conditional capacity "
                    "solve did not converge. The complete chord check can be "
                    "optimistic; rely on the combined "
                    "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>)."
                )
            if coverage == "subdivided":
                note += (" Compound (subdivided) section: the torsion longitudinal "
                         "steel is per sub-tube, so the off-axis chord's torsion "
                         "share is not evaluated here -- rely on the combined "
                         "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>).")
            elif coverage == "not_solved":
                note += (" One or more chord faces carrying the torsion share could "
                         "not be evaluated (a conditional solve failed or a face has "
                         "no tension steel), so they are not checked and the governing "
                         "chord shown may not be the critical face -- rely on the "
                         "combined &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>).")
            self._small(note)
            self._chord_off_block(
                links.get("chord_off"),
                assessment_complete=not bool(coverage) and not fell_back,
            )

    def _combined(self):
        aggregate = self.out["combined"]
        directions = aggregate.get("directions") or {}
        if not aggregate.get("biaxial") or not directions:
            self._combined_direction(aggregate)
            return

        self._case_heading(
            "Combined bending + directional shear + torsion", "plastic"
        )
        self._small(
            "V<sub>x,Ed</sub> + T<sub>Ed</sub> and "
            "V<sub>y,Ed</sub> + T<sub>Ed</sub> are calculated independently. "
            "Generic simultaneous V<sub>x</sub> + V<sub>y</sub> + T interaction "
            "is not calculated and no aggregate verdict is issued."
        )
        rows = [["Screen", "r<sub>M</sub>", "r<sub>V</sub>",
                 "r<sub>T</sub>", "DK NA sum", "Governing face",
                 "cot theta", "DK NA sum status"]]
        for component in ("vx", "vy"):
            item = directions.get(component)
            if not item:
                continue
            rows.append([
                "Vx+T" if component == "vx" else "Vy+T",
                _pct(item.get("r_m")), _pct(item.get("r_v")),
                _pct(item.get("r_t")), _pct(item.get("dkna_sum")),
                viz.directional_face_label(
                    component, item.get("governing_face")
                ),
                _fmt(item.get("governing_cot"), 3),
                (
                    "NOT ASSESSED" if not item.get("valid")
                    else "PASS" if item.get("dkna_ok") else "FAIL"
                ),
            ])
        self._table(
            rows,
            [20 * mm, 17 * mm, 17 * mm, 17 * mm, 23 * mm,
             34 * mm, 18 * mm, 24 * mm],
            font=5.8,
        )
        for component in ("vx", "vy"):
            if component in directions:
                block_start = len(self.flow)
                label = "V<sub>x,Ed</sub> + T<sub>Ed</sub>" if component == "vx" \
                    else "V<sub>y,Ed</sub> + T<sub>Ed</sub>"
                self._h2(f"Directional screen: {label}")
                self._combined_direction(
                    directions[component], include_case_heading=False,
                    component=component,
                )
                # A directional screen is a single auditable result.  Keep its
                # heading, inputs and verdict together when the complete block
                # fits on one page, instead of starting it at the foot of a page
                # and continuing without context on the next one.
                self._keep_from(block_start)

    def _combined_direction(self, c, *, include_case_heading=True, component=None):
        if include_case_heading:
            self._case_heading(
                "Combined bending + shear + torsion (M-V-T)", "plastic"
            )
        if not c.get("valid"):
            missing = []
            if not c.get("have_m", True):
                missing.append("bending")
            if not c.get("have_v", True):
                missing.append("shear")
            if not c.get("have_t", True):
                missing.append("torsion")
            detail = ", ".join(missing) or "one or more component checks"
            self._small(f"Directional combined check not evaluated: {detail} missing or invalid.")
            return
        if c.get("governing_face"):
            component = component or c.get("component") or "vy"
            angle_note = (
                ""
                if c.get("governing_cot") is None
                else f" at cot theta = {_fmt(c.get('governing_cot'), 3)}"
            )
            self._small(
                "Independent directional governing selection: "
                f"{viz.directional_face_label(component, c['governing_face'])}"
                f"{angle_note}."
            )
        self._p("The three checks tied together under the shared edition <b>"
                + str(c["method"]) + "</b>. The bending utilisation is the plastic "
                "M-M envelope at the applied N; the shear and torsion utilisations "
                "are the stand-alone checks.")
        rows = [["Action", "Utilisation"],
                ["Bending M", _pct(c["r_m"])],
                ["Shear V", _pct(c["r_v"])],
                ["Torsion T", _pct(c["r_t"])]]
        self._table(rows, [90 * mm, 60 * mm])
        self._h2(
            "DK NA 6.3.2(6): "
            "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) &#8804; 1"
        )
        if c.get("outside_default_range"):
            self._small("Warning: the shared compression-strut bounds fall outside "
                        "the selected method's default range. The actual values are "
                        "retained in the combined calculations.")
        verdict = _demand_resistance_verdict(c["dkna_ok"])
        if c["m_v_independent"]:
            expr = "max(r<sub>M</sub> + r<sub>T</sub>, r<sub>V</sub> + r<sub>T</sub>)"
            note = ("M and V checked separately (shear longitudinal steel provided); "
                    "N is folded into the bending utilisation.")
        else:
            expr = "r<sub>M</sub> + r<sub>V</sub> + r<sub>T</sub>"
            note = "each action alone; N folded into the bending utilisation."
        self._formula(
            expr,
            equation_key="combined.dk-na.sum",
            note=note,
            result=(
                "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) = "
                f"{_pct(c['dkna_sum'])}  ({verdict})"
            ),
        )
        self._h2("Physical resistance components")
        component_rows = [["Component", "Utilisation", "Status", "QA note"]]
        component_rows.extend([
            [
                component["label"],
                _pct(component["util"]),
                component["status"],
                component["note"],
            ]
            for component in presentation.combined_physical_components(c)
        ])
        self._table(
            component_rows,
            [48 * mm, 28 * mm, 29 * mm, 65 * mm],
            font=7.5,
        )
        self._small(
            "Concrete strut, closed stirrup and longitudinal reinforcement are "
            "independent physical checks. The worst value may govern the case, but "
            "it is not reported as a combined transverse-reinforcement utilisation."
        )
        cr = c.get("crushing")
        if cr is not None and cr.get("valid"):
            self._h2("Concrete compression strut (6.29)")
            val = cr["value"]
            vv = _demand_resistance_verdict(viz.util_ok(val))
            self._formula(
                "T<sub>Ed</sub>/T<sub>Rd,max</sub> + V<sub>Ed</sub>/V<sub>Rd,max</sub>",
                equation_key="combined.crushing.interaction",
                ref="EN 1992-1-1 (6.29)",
                subst=f"{_fmt(cr['t_ed'], 3)}/{_fmt(cr['trd_max'], 3)} + "
                      f"{_fmt(cr['v_ed'], 3)}/{_fmt(cr['vrd_max'], 3)}",
                result=f"{_pct(val)}  ({vv})")
            self._small(f"At a common strut cot theta = {_fmt(cr['cot'], 2)} "
                        f"(theta = {_fmt(cr['theta_deg'], 1)}&#176;).")
            self._fig(viz.vt_interaction_figure(cr["vrd_max"], cr["trd_max"],
                                                cr["v_ed"], cr["t_ed"],
                                                show_verdict=True),
                      120, 100)
        elif cr is not None and not cr.get("valid"):
            self._h2("Concrete compression strut (6.29)")
            self._small(
                "Not evaluated: the shared member-angle calculation is invalid."
            )
        tr = c.get("transverse")
        if tr is not None and not tr.get("valid"):
            self._h2("Shared stirrup (shear + torsion transverse steel)")
            self._small(
                "Not evaluated: the shared member-angle calculation is invalid."
            )
        elif tr is not None:
            self._h2("Shared stirrup (shear + torsion transverse steel)")
            vv = _demand_resistance_verdict(viz.util_ok(tr["u_stirrup"]))
            if tr["shear_credited"]:
                note = (f"V<sub>Ed</sub> = {_fmt(tr['v_ed'], 1)} &#8804; V<sub>Rd,c</sub>"
                        f" = {_fmt(tr['vrd_c'], 1)} kN, so the concrete carries the "
                        "shear (6.2.1) and the whole closed stirrup serves torsion.")
            else:
                note = ("V<sub>Ed</sub> &gt; V<sub>Rd,c</sub>: shear and torsion "
                        "demands add on the shared closed stirrup.")
            self._formula(
                "shear share + torsion share (shared closed stirrup)",
                equation_key="combined.stirrup.utilisation",
                subst=f"{_pct(tr['shear_fraction'])} + {_pct(tr['torsion_fraction'])}",
                result=(
                    "closed-stirrup utilisation = "
                    f"{_pct(tr['u_stirrup'])}  ({vv})"
                ))
            self._small(note + f" At the member strut angle cot theta = "
                        f"{_fmt(tr['cot'], 2)} "
                        f"(theta = {_fmt(tr['theta_deg'], 1)}&#176;) -- "
                        "the one angle shared by every shear and torsion check "
                        "(6.3.2(2)), selected to minimise the governing utilisation.")
        lg = c.get("longitudinal")
        if lg is not None and lg["valid"]:
            self._h2("Longitudinal reinforcement: combined M + V + T tension chord")
            vv = _demand_resistance_verdict(lg["ok"])
            coverage = lg.get("off_not_evaluated")
            ax = lg["axis"]
            face = viz.tension_face_label(
                lg.get("tension_low", True), lg.get("axis")
            )
            face_desc = (f"the shear tension face ({face})" if lg.get("gets_shift", True)
                         else f"the shear compression face ({face}) -- the torsion "
                         "tension governs there, with no shear shift and the bending "
                         "relieving rather than adding")
            self._p(
                f"The governing tension chord is {face_desc} about the "
                f"{ax}-axis; M<sub>Ed</sub> and M<sub>Rd</sub> are taken on that face. "
                "The chord carries the bending tension plus the shear shift "
                "&#916;F<sub>td</sub> = "
                "0.5&#183;V<sub>Ed</sub>&#183;cot theta (6.18, only on the flexural "
                "tension face) and the torsion "
                "longitudinal force F<sub>td,T</sub> = T<sub>Ed</sub>&#183;u<sub>k</sub>"
                "&#183;cot theta/(2A<sub>k</sub>) (6.28, distributed round the "
                "perimeter, so half acts on this chord). Each is turned into an "
                "equivalent moment on the lever arm z and checked against "
                "M<sub>Rd</sub> "
                + viz.chord_mrd_label(ax, lg.get("m_off", 0.0),
                                      lg.get("conditional", True)) + ".")
            self._formula(
                "M<sub>Ed,total</sub> = M<sub>Ed</sub> + &#916;F<sub>td</sub>&#183;z + "
                "F<sub>td,T</sub>&#183;z/2",
                equation_key="combined.chord.demand",
                ref="EN 1992-1-1 6.2.3(7) + 6.3.2",
                subst=f"{_fmt(lg['m_ed'], 1)} + {_fmt(lg['mv'], 1)} + "
                      f"{_fmt(lg['mt'], 1)} kNm  (z = {_fmt(lg['z'], 3)} m, "
                      f"&#916;F<sub>td</sub> = {_fmt(lg['ftd_v'], 1)} kN, "
                      f"F<sub>td,T</sub> = {_fmt(lg['ftd_t'], 1)} kN)",
                result=f"M<sub>Ed,total</sub> = {_fmt(lg['m_total'], 1)} kNm")
            biaxial = lg.get("biaxial", False)
            fallback = presentation.required_chord_fallback(c)
            fell_back = fallback is not None
            if coverage:
                verdict_suffix = (
                    "  (NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE)"
                )
            elif fell_back:
                verdict_suffix = (
                    "  (NOT ASSESSED - DISPLAYED CAPACITY IS PURE-AXIS FALLBACK)"
                    if not lg.get("conditional", True)
                    else "  (NOT ASSESSED - ANOTHER REQUIRED FACE USES FALLBACK)"
                )
            else:
                verdict_suffix = f"  ({vv})"
            self._formula(
                "M<sub>Ed,total</sub> / M<sub>Rd</sub>",
                equation_key="combined.chord.utilisation",
                references=("combined.chord.demand",),
                subst=f"{_fmt(lg['m_total'], 1)} / {_fmt(lg['m_rd'], 1)}",
                result=f"utilisation = {_pct(lg['util'])}{verdict_suffix}")
            if fell_back:
                fallback_axis = fallback.get("axis", "?")
                fallback_face = (
                    "negative" if fallback.get("tension_low", True)
                    else "positive"
                )
                self._p(
                    f"The required {fallback_axis}-axis {fallback_face} face "
                    "uses a pure-axis fallback because its conditional capacity "
                    "solve did not converge. The complete chord check can be "
                    "optimistic; rely on the "
                    "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check above, "
                    "which uses the full biaxial bending utilisation."
                )
            note = viz.chord_angle_note(lg.get("theta_mode"))
            if coverage == "subdivided":
                note += (" Compound (subdivided) section: the torsion longitudinal "
                         "steel is per sub-tube, so the off-axis chord's torsion "
                         "share is not evaluated; the "
                         "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check covers the "
                         "interaction.")
            elif coverage == "not_solved":
                note += (" One or more chord faces carrying the torsion share could "
                         "not be evaluated (a conditional solve failed or a face has "
                         "no tension steel), so they are NOT checked and the governing "
                         "chord shown may not be the critical face; the "
                         "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) "
                         "check above remains the combined verification.")
            elif biaxial and not lg.get("has_torsion"):
                note += (" The off-axis chord carries only its bending tension (no "
                         "torsion is acting), which the biaxial bending utilisation "
                         "in the &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) "
                         "check already covers.")
            elif not biaxial:
                note += (" The &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check above "
                         "uses the full biaxial bending "
                         "utilisation and remains the primary combined check.")
            if lg["capped"]:
                note = ("The shear shift is capped so bending + shear does not exceed "
                        "M<sub>Rd</sub> (6.2.3(7): the added tension need not exceed "
                        "the peak-moment tension; a section tool uses M<sub>Rd</sub> as "
                        "that cap). ") + note
            self._small(note)
            self._chord_off_block(
                c.get("chord_off"),
                assessment_complete=not bool(coverage) and not fell_back,
            )
        else:
            self._small(f"Additional longitudinal steel: torsion "
                        "&#8721;A<sub>sl</sub> = "
                        f"{_fmt(c['asl_torsion'], 0)} mm<sup>2</sup> round the perimeter "
                        f"(6.28); shear &#916;F<sub>td</sub> = {_fmt(c['delta_ftd'], 1)} "
                        "kN on the tension chord (6.18) -- both beyond the bending "
                        "steel. Enable shear links for the full utilisation check.")

    def _chord_off_block(self, och, *, assessment_complete=True):
        """Off-axis chord check (bending + torsion share), shared by the shear and
        combined sections. Rendered when torsion is live on a single-tube section:
        the chord about the OTHER axis carries its bending tension plus its share
        of the distributed torsion longitudinal force, against the capacity
        conditional on the shear-axis moment."""
        if och is None or not och.get("valid"):
            return
        self._h2(f"Off-axis chord (about {och['axis']}, governing face): "
                 "bending + torsion tension")
        vv = _demand_resistance_verdict(och["ok"])
        face = viz.tension_face_label(
            och.get("tension_low", True), och.get("axis")
        )
        self._p(
            f"The governing tension chord is the {face} face about the "
            f"{och['axis']}-axis (the axis the shear does not act on; the torsion "
            "tensions both faces and the worse is reported). No shear shift acts "
            "on this "
            "chord; the torsion adds its perimeter share F<sub>td,T</sub>&#183;z/2, "
            "and the capacity is checked against M<sub>Rd</sub> "
            + viz.chord_mrd_label(och["axis"], och.get("m_off", 0.0), True) + ".")
        self._formula(
            "M<sub>Ed,total</sub> = M<sub>Ed</sub> + F<sub>td,T</sub>&#183;z/2",
            equation_key="torsion.off-axis-chord.demand",
            ref="EN 1992-1-1 6.3.2",
            subst=f"{_fmt(och['m_ed'], 1)} + {_fmt(och['mt'], 1)} kNm  "
                  f"(z = {_fmt(och['z'], 3)} m, "
                  f"F<sub>td,T</sub> = {_fmt(och['ftd_t'], 1)} kN)",
            result=f"M<sub>Ed,total</sub> = {_fmt(och['m_total'], 1)} kNm")
        self._formula(
            "M<sub>Ed,total</sub> / M<sub>Rd</sub>",
            equation_key="torsion.off-axis-chord.utilisation",
            references=("torsion.off-axis-chord.demand",),
            subst=f"{_fmt(och['m_total'], 1)} / {_fmt(och['m_rd'], 1)}",
            result=(
                f"utilisation = {_pct(och['util'])}  "
                + (
                    f"({vv})"
                    if assessment_complete
                    else "(NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE)"
                )
            ))
        self._small(f"z = {_fmt(och['z'], 3)} m ({och.get('z_src') or '0.9 d'}). "
                    "Each chord's capacity is conditional on the OTHER axis' "
                    "bending moment only; the longitudinal steel the two chords "
                    "share also carries both their shear/torsion tensions, an "
                    "interaction the DK NA "
                    "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check captures and which "
                    "stays the authoritative combined verification.")

    def _subtube_section(self, t):
        """Torsion of a subdivided compound section (EN 1992-1-1 6.3.1(3)-(4))."""
        subs = t["subtubes"]
        c_tot = sum(s["stiffness"] for s in subs) or 1.0
        self._p("Compound section: modelled as component rectangles, each an equivalent "
                "thin-walled tube. T<sub>Rd</sub> is the SUM of the sub-tube capacities "
                "(6.3.1(3)) and the applied T<sub>Ed</sub> is split by uncracked "
                "torsional stiffness C = beta h b<sup>3</sup> (6.3.1(4)). The first "
                "rectangle (web) carries the shear in the combined V+T checks. Its "
                "positioned rectangle union has been validated against the concrete "
                "outline and voids before these results are issued.")
        rows = [["Sub-tube", "centre x, y<br/>b x h (mm)", "t<sub>ef</sub>",
                 "A<sub>k</sub> (mm2)", "share", "T<sub>Ed,i</sub>",
                 "T<sub>Rd,i</sub>", "util", "governs"]]
        for i, s in enumerate(subs):
            role = "web" if i == 0 else f"part {i + 1}"
            ut = ("inf" if not math.isfinite(s["util"])
                  else f"{_fmt(s['util'] * 100, 0)}%")
            rows.append([role,
                         f"({_fmt(s['x_mm'], 0)}, {_fmt(s['y_mm'], 0)})<br/>"
                         f"{_fmt(s['b_mm'], 0)}x{_fmt(s['h_mm'], 0)}",
                         _fmt(s["tube"]["tef"], 1), _fmt(s["tube"]["Ak"] * 1e6, 0),
                         f"{_fmt(s['stiffness'] / c_tot * 100, 0)}%",
                         _fmt(s["t_ed"], 2), _fmt(s["trd"], 2), ut, s["governs"]])
        self._table(rows, [16 * mm, 24 * mm, 14 * mm, 18 * mm, 13 * mm, 16 * mm,
                           16 * mm, 12 * mm, 25 * mm])
        # The torque is split by STIFFNESS, not capacity, so the governing check is the
        # WORST sub-tube (max util), not TEd / sum(TRd_i).
        util = t["util"]
        util_txt = _pct(util)
        verdict = _demand_resistance_verdict(viz.util_ok(util))
        g = t.get("governing_sub")
        gov = ("web" if g == 0 else f"part {g + 1}") if g is not None else "-"
        self._formula(
            "governing utilisation = max(T<sub>Ed,i</sub> / T<sub>Rd,i</sub>)",
            equation_key="torsion.subtube.governing-utilisation",
            ref=f"worst sub-tube: {gov}", result=f"{util_txt}  ({verdict})")
        self._small("The applied torque is split by stiffness, not capacity, so a "
                    "sub-tube can be overstressed even while T<sub>Ed</sub> &#8804; sum "
                    "T<sub>Rd,i</sub> = " + f"{_fmt(t['trd'], 2)}"
                    + " kN&#183;m; the section "
                    "passes only when every sub-tube passes. Total longitudinal steel "
                    "&#8721;A<sub>sl</sub> = " + f"{_fmt(t['asl_req'], 0)}" +
                    " mm<sup>2</sup> (sum over the sub-tubes), in addition to the "
                    "bending steel; the combined V+T crushing pairs the shear with the "
                    "web sub-tube.")
        self._fig(viz.subtube_figure(subs), 150, 90)
        self._crushing_interaction(t)

    def _crushing_interaction(self, t):
        """Combined shear + torsion concrete crushing (6.29), if it was evaluated.

        Shared by the single-tube and the sub-tube torsion reports so a subdivided run
        with shear links still prints the crushing verdict even when the separate
        combined M-V-T section is not enabled.
        """
        inter = t.get("interaction")
        if inter is None:
            return
        self._h2("Combined shear + torsion (concrete crushing)")
        if not inter.get("valid"):
            self._small(
                "Not evaluated: the shared member-angle calculation is invalid."
            )
            return
        val = inter["value"]
        val_txt = _pct(val)
        verdict_i = _demand_resistance_verdict(viz.util_ok(val))
        self._formula(
            "T<sub>Ed</sub>/T<sub>Rd,max</sub> + V<sub>Ed</sub>/V<sub>Rd,max</sub>",
            equation_key="torsion.shear.crushing-interaction",
            ref="EN 1992-1-1 (6.29)",
            subst=f"{_fmt(inter['t_ed'], 3)}/{_fmt(inter['trd_max'], 3)} + "
                  f"{_fmt(inter['v_ed'], 3)}/{_fmt(inter['vrd_max'], 3)}",
            result=f"{val_txt}  ({verdict_i})")
        self._small("Evaluated at the common strut angle cot theta = "
                    f"{_fmt(inter['cot'], 2)} "
                    f"(theta = {_fmt(inter['theta_deg'], 1)}&#176;); "
                    "T<sub>Rd,max</sub> and V<sub>Rd,max</sub> here are at that shared "
                    "angle.")
        self._fig(viz.vt_interaction_figure(inter["vrd_max"], inter["trd_max"],
                                            inter["v_ed"], inter["t_ed"],
                                            show_verdict=True),
                  120, 100)

    def _torsion(self):
        t = self.out["torsion"]
        tube = t["tube"]
        self._case_heading("Torsion (thin-walled tube)", "plastic")
        self._p("Torsion resistance from the thin-walled closed-tube idealisation "
                "(EN 1992-1-1 sec. 6.3), method <b>" + str(t["method"]) + "</b>. The "
                "tube is derived from the outline; the closed stirrups and the "
                "concrete struts give the resistance at the member strut angle "
                + ("(one angle shared with the shear check, 6.3.2(2), selected to "
                   "minimise the governing utilisation)."
                   if t.get("theta_mode") == "utilisation"
                   else "(auto-optimised for the torsion resistance)."))
        directional = t.get("directional_interactions") or {}
        if directional:
            self._small(
                "Generic V<sub>x,Ed</sub> + V<sub>y,Ed</sub> + T<sub>Ed</sub> "
                "interaction is <b>NOT CALCULATED</b>. Standalone torsion is reported "
                "below; Vx+T and Vy+T are calculated independently."
            )
            rows = [["Screen", "T<sub>Ed</sub>/T<sub>Rd</sub>",
                     "6.29 V+T", "Governing face", "cot theta", "Status"]]
            min_reinf_rows = [["Screen", "6.31 sum", "Governing face", "Outcome"]]
            for component in ("vx", "vy"):
                item = directional.get(component)
                if not item:
                    continue
                interaction = item.get("interaction") or {}
                value = interaction.get("value")
                rows.append([
                    "Vx+T" if component == "vx" else "Vy+T",
                    _pct(item.get("util")),
                    ("-" if value is None else _pct(value)),
                    viz.directional_face_label(
                        component,
                        item.get("directional_governing_face"),
                    ),
                    _fmt(item.get("directional_governing_cot"), 3),
                    item.get("directional_interaction_status") or (
                        presentation.interaction_assessment_status(interaction)
                    ),
                ])
                min_reinf = item.get("min_reinf") or {}
                if min_reinf:
                    outcome = (
                        "not assessed"
                        if not min_reinf.get("applicable")
                        else "minimum sufficient"
                        if min_reinf.get("ok")
                        else "designed reinforcement required"
                    )
                    min_reinf_rows.append([
                        "Vx+T" if component == "vx" else "Vy+T",
                        (_fmt(min_reinf.get("value"), 3)
                         if min_reinf.get("applicable") else "-"),
                        viz.directional_face_label(
                            component,
                            item.get(
                                "directional_min_reinf_governing_face"
                            ),
                        ),
                        outcome,
                    ])
            self._table(
                rows,
                [27 * mm, 28 * mm, 25 * mm, 38 * mm, 20 * mm, 32 * mm],
                font=6.5,
            )
            if len(min_reinf_rows) > 1:
                self._h2("Directional minimum-reinforcement screens (Eq. 6.31)")
                self._table(
                    min_reinf_rows,
                    [31 * mm, 28 * mm, 39 * mm, 72 * mm],
                    font=6.5,
                )
                self._small(
                    "Equation 6.31 determines whether minimum shear/torsion "
                    "reinforcement is sufficient; it is not an overall resistance "
                    "verdict."
                )
        if not t["valid"]:
            if t.get("reason") == "multi-cell (2+ voids)":
                self._small("Torsion not evaluated: a multi-cell section (two or "
                            "more voids) needs sub-division into separate tubes "
                            "(6.3.2(1)); the single-tube idealisation is not applied.")
            elif t.get("reason") == "compound outline requires subdivision":
                self._small("Torsion not evaluated: the re-entrant/compound outline "
                            "(for example T, L or I) requires component sub-sections "
                            "under EN 1992-1-1 6.3.1(3). Enable sub-tubes and define "
                            "rectangles that partition the section before a "
                            "resistance result can be calculated.")
            elif str(t.get("reason") or "").startswith(
                    "invalid sub-tube partition:"):
                detail = (t.get("subdivision_reason")
                          or str(t["reason"]).split(":", 1)[-1].strip())
                self._small(
                    "Torsion not evaluated: the positioned sub-rectangles do not "
                    f"form the concrete section ({detail}). Adjust each centre x/y "
                    "and b/h so their non-overlapping union equals the concrete net "
                    "area and does not enter a void. Torsion and dependent "
                    "interaction are not calculated."
                )
            else:
                self._small("Warning: the tube could not be formed (a degenerate or "
                            "too-thin section).")
            return
        if t["out_of_limits"]:
            self._small("Warning: the strut bounds cot theta in "
                        f"[{_fmt(t['cot_min'], 2)}, {_fmt(t['cot_max'], 2)}] fall "
                        "outside the selected method's default range 1..2.5 "
                        "(6.7N / 6.7a NA). The actual values are retained in the "
                        "torsion and dependent interaction calculations.")
        self._small(
            "Torsional cracking uses the actual direct input "
            "gamma<sub>ct</sub> = "
            f"{_fmt(t.get('gamma_ct'), 3)}: "
            "f<sub>ctd</sub> = f<sub>ctk,0.05</sub> / "
            "gamma<sub>ct</sub> = "
            f"{_fmt(t.get('fctd'), 3)} MPa."
        )
        if t.get("subdivided"):
            self._h2("Sub-tubes (compound section, 6.3.1(3))")
            self._subtube_section(t)
            return
        tef_src = ("user input" if tube["tef_user"]
                   else ("A/u, capped at the wall" if tube["tef_capped"] else "A/u"))
        rows = [["Quantity", "Symbol", "Value"],
                ["Gross area (incl. hollow)", "A", f"{_fmt(tube['A'] * 1e6, 0)} mm<sup>2</sup>"],
                ["Outer perimeter", "u", f"{_fmt(tube['u'] * 1e3, 0)} mm"],
                ["Wall thickness", "t<sub>ef</sub>",
                 f"{_fmt(tube['tef'], 1)} mm ({tef_src})"],
                ["Enclosed area", "A<sub>k</sub>", f"{_fmt(tube['Ak'] * 1e6, 0)} mm<sup>2</sup>"],
                ["Centre-line perimeter", "u<sub>k</sub>", f"{_fmt(tube['uk'] * 1e3, 0)} mm"],
                ["Strut angle", "theta",
                 f"{_fmt(t['theta_deg'], 1)}&#176; "
                 f"(cot theta = {_fmt(t['cot'], 3)})"],
                ["Strut factor", "nu", f"{_fmt(t['nu'], 3)}"],
                ["Chord factor", "alpha<sub>cw</sub>", f"{_fmt(t['alpha_cw'], 3)}"],
                ["Concrete tensile factor", "gamma<sub>ct</sub>",
                 _fmt(t.get("gamma_ct"), 3)],
                ["Design tensile strength", "f<sub>ctd</sub>",
                 f"{_fmt(t.get('fctd'), 3)} MPa"],
                ["Design link yield", "f<sub>ywd</sub>", f"{_fmt(t['fywd'], 1)} MPa"]]
        self._table(rows, [55 * mm, 25 * mm, 70 * mm])
        self._fig(viz.tube_figure(self.inp["outer"], self.inp.get("holes"),
                                  tube["tef"], ak_m2=tube["Ak"]), 120, 100)
        if t.get("n_prestress"):
            self._small("alpha<sub>cw</sub> uses sigma<sub>cp</sub> = "
                        f"{_fmt(t['sigma_cp'], 3)} MPa, which includes the tendon "
                        f"precompression {_fmt(t['n_prestress'], 3)} kN (from the "
                        "prestress initial strain) as well as the axial N.")
        if t.get("nu_v_detailing"):
            self._small("nu = nu<sub>v</sub> (raised from nu<sub>t</sub>) under DK NA "
                        "Figur 5.100 NA: closed stirrups round the periphery and "
                        "distributed longitudinal steel on both faces.")
        self._h2("Resistances")
        self._formula(
            "T<sub>Rd,s</sub> = (A<sub>sw</sub>/s) 2 A<sub>k</sub> f<sub>ywd</sub> "
            "cot theta",
            equation_key="torsion.resistance.steel",
            ref="EN 1992-1-1 wall shear flow (6.27) and transverse equilibrium (6.8)",
            subst=f"{_fmt(t['asw_over_s'], 4)} &#183; 2 &#183; {_fmt(tube['Ak'], 4)} "
                  f"&#183; {_fmt(t['fywd'], 1)} &#183; {_fmt(t['cot'], 3)}",
            result=f"T<sub>Rd,s</sub> = {_fmt(t['trd_s'], 3)} kN&#183;m")
        self._formula(
            "T<sub>Rd,max</sub> = 2 nu alpha<sub>cw</sub> f<sub>cd</sub> "
            "A<sub>k</sub> t<sub>ef</sub> sin theta cos theta",
            equation_key="torsion.resistance.crushing",
            ref="EN 1992-1-1 (6.30)",
            subst=f"2 &#183; {_fmt(t['nu'], 3)} &#183; {_fmt(t['alpha_cw'], 3)} &#183; "
                  f"{_fmt(t['fcd'], 2)} &#183; {_fmt(tube['Ak'], 4)} &#183; "
                  f"{_fmt(tube['tef'] / 1000.0, 4)} &#183; "
                  f"{_fmt(t['cot'] / (1.0 + t['cot'] ** 2), 4)} &#183; 1000",
            result=f"T<sub>Rd,max</sub> = {_fmt(t['trd_max'], 3)} kN&#183;m")
        self._formula(
            "T<sub>Rd</sub> = min(T<sub>Rd,s</sub>, T<sub>Rd,max</sub>)",
            equation_key="torsion.resistance.governing",
            references=("torsion.resistance.steel", "torsion.resistance.crushing"),
            result=f"T<sub>Rd</sub> = {_fmt(t['trd'], 3)} kN&#183;m "
                   f"(governed by {t['governs']})")
        self._formula(
            "f<sub>ctd</sub> = f<sub>ctk,0.05</sub> / gamma<sub>ct</sub>",
            equation_key="torsion.cracking.fctd",
            ref="selected torsion method; f<sub>ctk,0.05</sub> = 0.7 f<sub>ctm</sub>",
            subst=f"{_fmt(t.get('fctk_005'), 3)} / "
                  f"{_fmt(t.get('gamma_ct'), 3)}",
            result=f"f<sub>ctd</sub> = {_fmt(t['fctd'], 3)} MPa")
        self._formula(
            "T<sub>Rd,c</sub> = 2 A<sub>k</sub> t<sub>ef</sub> f<sub>ctd</sub>",
            equation_key="torsion.cracking.resistance",
            references=("torsion.cracking.fctd",),
            ref="cracking (tau = f<sub>ctd</sub>)",
            subst=f"2 &#183; {_fmt(tube['Ak'], 4)} &#183; "
                  f"{_fmt(tube['tef'] / 1000.0, 4)} &#183; {_fmt(t['fctd'], 3)} "
                  "&#183; 1000",
            result=f"T<sub>Rd,c</sub> = {_fmt(t['trd_c'], 3)} kN&#183;m")
        util = t["util"]
        util_txt = _pct(util)
        verdict = _demand_resistance_verdict(viz.util_ok(util))
        self._h2("Utilisation and longitudinal steel")
        self._formula("T<sub>Ed</sub> / T<sub>Rd</sub>",
                      equation_key="torsion.utilisation",
                      subst=f"{_fmt(t['t_ed'], 3)} / {_fmt(t['trd'], 3)}",
                      result=f"{util_txt}  ({verdict})")
        self._formula(
            "&#8721;A<sub>sl</sub> = T<sub>Ed</sub> u<sub>k</sub> cot theta / "
            "(2 A<sub>k</sub> f<sub>yd</sub>)",
            equation_key="torsion.longitudinal-steel",
            ref="EN 1992-1-1 (6.28)",
            subst=f"{_fmt(t['t_ed'], 3)} &#183; {_fmt(tube['uk'], 4)} &#183; "
                  f"{_fmt(t['cot'], 3)} / (2 &#183; {_fmt(tube['Ak'], 4)} &#183; "
                  f"{_fmt(t['fyd_long'], 1)}) &#183; 1000",
            result=f"&#8721;A<sub>sl</sub> = {_fmt(t['asl_req'], 0)} mm<sup>2</sup> "
                   "(in addition to the bending steel)")
        self._small("Lengths shown in m and f in MPa; the &#183; 1000 converts "
                    "MN&#183;m to kN&#183;m (resistances) and m<sup>2</sup> "
                    "to mm<sup>2</sup> "
                    "(A<sub>sl</sub>).")
        # Biaxial runs report Eq. 6.31 per shear direction above. The standalone
        # torsion payload has no shear companion and must not replace those screens.
        mr = None if directional else t.get("min_reinf")
        if mr is not None and mr.get("applicable"):
            self._h2("Minimum-reinforcement screen (6.3.2(5), Eq 6.31)")
            vv = ("minimum reinforcement suffices" if mr["ok"]
                  else "designed reinforcement required")
            self._formula(
                "T<sub>Ed</sub>/T<sub>Rd,c</sub> + V<sub>Ed</sub>/V<sub>Rd,c</sub>",
                equation_key="torsion.minimum-reinforcement.screen",
                ref="EN 1992-1-1 (6.31)",
                subst=f"{_fmt(mr['t_ed'], 3)}/{_fmt(mr['trd_c'], 3)} + "
                      f"{_fmt(mr['v_ed'], 3)}/{_fmt(mr['vrd_c'], 3)}",
                result=f"{_fmt(mr['value'], 3)}  ({vv})")
            solid_note = ("Assumes an approximately solid rectangular section."
                          if mr["solid"] else "This section has a void: 6.31 is for "
                          "solid sections, so it does not strictly apply.")
            self._small("If &#8804; 1, only minimum shear + torsion reinforcement is "
                        "required (no designed stirrups for these actions). "
                        + solid_note)
        self._crushing_interaction(t)

    def _elastic(self):
        el = self.out["elastic"]
        self._case_heading(
            "Elastic section response and stresses", "elastic"
        )
        valid = el.get("converged", True)
        if not valid:
            self._status_block(
                "INVALID - Elastic result | Solver did not converge; values are "
                "diagnostic only.",
                "INVALID",
            )
        if valid:
            state = "cracked" if el.get("cracked") else "uncracked"
            self._p(f"The section is <b>{state}</b> (governing of the long-term "
                    f"and total actions). Neutral-axis intercepts: "
                    f"x<sub>na</sub> = {_fmt(el['na_x']*_MM, 3)} mm, "
                    f"y<sub>na</sub> = {_fmt(el['na_y']*_MM, 3)} mm.")
        else:
            self._p(
                "No verified cracked/uncracked classification is issued. "
                "Diagnostic neutral-axis intercepts: "
                f"x<sub>na</sub> = {_fmt(el['na_x']*_MM, 3)} mm, "
                f"y<sub>na</sub> = {_fmt(el['na_y']*_MM, 3)} mm."
            )
        ps = el.get("prestress")
        if ps is not None:
            # ps[0] is the tendon tension resultant; the prestress precompresses the
            # section, so as an axial action (tension-positive) it is a compression.
            self._p(f"The tendon prestress is applied from its initial strain (so N "
                    f"is the external force only): equivalent prestress action "
                    f"N = {_fmt(-ps[0], 3)} kN, M<sub>x</sub> = {_fmt(ps[1], 3)} kNm, "
                    f"M<sub>y</sub> = {_fmt(ps[2], 3)} kNm (N tension-positive).")
        checks = el.get("stress_outputs") or {}
        if checks:
            self._h2("Elastic stress outputs")
            rows = [["Quantity", "Result", "Governing element", "State"]]
            for label, key in (
                ("Concrete compression", "concrete"),
                ("Reinforcement tension", "reinforcement"),
                ("Tendon tension", "prestress"),
            ):
                item = checks.get(key)
                if not item or (key == "prestress" and not self.inp.get("tendons")):
                    continue
                rows.append([
                    label,
                    "-" if item.get("value") is None else
                    f"{_fmt(item.get('value'), 3)} MPa",
                    item.get("governing") or "-",
                    item.get("calculation_state") or "NOT CALCULATED",
                ])
            self._table(rows, [55 * mm, 35 * mm, 45 * mm, 35 * mm],
                        font=7.5)
            self._small(
                "Numerical outputs for the actual named Elastic action. No "
                "stress-limit criterion is applied."
            )
        # Elastic state diagram (bars coloured by stress sign, compression zone).
        if self.figures and el.get("max_conc", 0.0) > 0.0:
            hp = viz.elastic_halfplane(el["na_x"], el["na_y"],
                                       el.get("max_conc_xy", (0.0, 0.0)))
            if hp is not None:
                inp = self.inp
                na = viz.na_line_at(hp[0], hp[1], hp[2], inp.get("extent", 1.0))
                zones = viz.compression_zones(inp.get("outer", []), hp)
                nb = len(inp.get("bars", []))
                total = el.get("total", [])
                sgn = lambda s: viz.BAR_TENSION if s >= 0 else viz.BAR_COMPRESSION
                self._fig(viz.section_figure(
                    inp.get("outer", []), inp.get("holes", []),
                    inp.get("bars", []),
                    bar_colors=[sgn(s) for s in total[:nb]],
                    tendons=inp.get("tendons", []),
                    tendon_colors=[sgn(s) for s in total[nb:]], na_line=na, zones=zones,
                    show_labels=False, scale=_MM, unit="mm",
                    bar_ids=[item.get("id") for item in inp.get("bar_elements", [])],
                    tendon_ids=[item.get("id") for item in inp.get("tendon_elements", [])],
                    title="Elastic state (tension + / compression -)"), 150, 100)
                self._small(
                    "Blue/plain markers are tension (+); vermillion/x markers are "
                    "compression (-). Bar circles and tendon diamonds identify the "
                    "element type. Element IDs and coordinates are tabulated below."
                )
        if self.figures and el.get("concrete_corners"):
            self._fig(viz.elastic_strain_figure(
                el.get("concrete_corners"), el.get("elements"),
                el.get("stress_plane"),
                ec_mpa=float(self.inp.get("conc_Ec", 0.0)) * 1000.0,
                title="Elastic strain profile"), 150, 100)
        # Transformed properties: uncracked and (when cracked) cracked, n_l-weighted.
        self._h2("Transformed section properties (n<sub>l</sub>)")
        pu = el.get("props_un") or {}
        pc = el.get("props_cr")
        specs = [("Area A", "area", 4, "m<super>2</super>", 1.0, False),
                 ("Centroid x", "cx", 1, "mm", _MM, False),
                 ("Centroid y", "cy", 1, "mm", _MM, False),
                 ("I<sub>x</sub>", "Ix", 6, "m<super>4</super>", 1.0, True),
                 ("I<sub>y</sub>", "Iy", 6, "m<super>4</super>", 1.0, True),
                 ("I<sub>xy</sub>", "Ixy", 6, "m<super>4</super>", 1.0, True)]
        head = ["Property", "Uncracked"] + (["Cracked"] if pc else [])
        rows = [head]
        for label, k, nd, unit, sc, significant in specs:
            formatter = _fmt_sig if significant else _fmt
            row = [f"{label} ({unit})", formatter(pu.get(k, 0.0) * sc, nd)]
            if pc:
                row.append(formatter(pc.get(k, 0.0) * sc, nd))
            rows.append(row)
        self._table(rows, [55 * mm, 45 * mm] + ([45 * mm] if pc else []))
        self._small("Transformed (n<sub>l</sub>-weighted) about the centroid; the "
                    "cracked column drops the concrete in tension.")
        # Complete, explicitly typed bar/tendon evidence.
        self._h2("Reinforcement and tendon response")
        self._small("TOTAL = long + short; LONG = long-term; DIF = TOTAL - LONG; "
                    "RST1 = instantaneous response after neutralising the "
                    "long-term concrete stress. Tension positive.")
        element_rows = el.get("elements") or []
        if element_rows:
            rows = [["Element", "Material", "x", "y", "Area", "Strain", "TOTAL",
                     "LONG", "DIF", "RST1"]]
            for row in element_rows:
                rows.append([
                    row["element_id"],
                    row.get("material_id") or "-",
                    _fmt(row["x_mm"], 1),
                    _fmt(row["y_mm"], 1),
                    _fmt(row["area_mm2"], 1),
                    _fmt(row["strain_permille"], 4),
                    _fmt(row["total_mpa"], 2),
                    _fmt(row["long_mpa"], 2),
                    _fmt(row["dif_mpa"], 2),
                    _fmt(row["rst1_mpa"], 2),
                ])
            self._table(
                rows,
                [19 * mm, 17 * mm, 13 * mm, 13 * mm, 17 * mm, 18 * mm,
                 18 * mm, 18 * mm, 17 * mm, 18 * mm],
                font=6.0, keep=False,
                repeat_cols=2,
            )
            self._small("Coordinates in mm; area in mm<super>2</super>; strain in "
                        "permille; stresses in MPa.")
        corner_rows = el.get("concrete_corners") or []
        if corner_rows:
            self._h2("Concrete corner stress and strain")
            rows = [["Point", "Ring", "Ring point", "x", "y",
                     "Strain", "Concrete stress"]]
            for row in corner_rows:
                rows.append([
                    row["point_no"], row["ring"], row["ring_point_no"],
                    _fmt(row["x_mm"], 1), _fmt(row["y_mm"], 1),
                    _fmt(row["strain_permille"], 5),
                    _fmt(row["stress_mpa"], 3),
                ])
            self._table(
                rows,
                [16 * mm, 29 * mm, 20 * mm, 19 * mm, 19 * mm,
                 28 * mm, 29 * mm],
                font=7, keep=False,
                repeat_cols=3,
            )
            self._small("Coordinates in mm; strain in permille; stress in MPa "
                        "(compression negative). Cracked concrete carries "
                        "compression only; compatible tensile strains remain in "
                        "the plane while tensile stress is zero.")
        rows = [["Quantity", "Value"],
                ["Max concrete compression", f"{_fmt(el.get('max_conc'), 3)} MPa "
                 f"(point {el.get('max_conc_point', '-')})"],
                ["Max steel-element tension", f"{_fmt(el.get('max_steel'), 3)} MPa "
                 f"({el.get('max_steel_element') or 'not in tension'})"]]
        self._table(rows, [70 * mm, 90 * mm])

    def _cracking(self):
        el = self.out["elastic"]
        self._case_heading(
            "Cracking and crack width" if el.get("show_cw")
            else "Cracking threshold",
            "elastic",
        )
        # Threshold.
        if el.get("show_cw"):
            self._h2("Cracking threshold")
        lam = el.get("lambda_cr")
        verdict = "cracked" if el.get("cracked") else "uncracked"
        valid = el.get("converged", True)
        crack_2023 = (
            el.get("crack_edition") == "2023"
            or "2023" in str(el.get("crack_code", ""))
        )
        self._formula("lambda<sub>cr</sub> = f<sub>ct,eff</sub> / sigma<sub>ct,I</sub>",
                      equation_key="cracking.threshold",
                      ref=("Stage-I extreme tensile stress reaches f<sub>ct,eff</sub> "
                           "(EN 1992-1-1:2023 &#167;9.2.1)"
                           if crack_2023 else
                           "Stage-I extreme tensile stress reaches f<sub>ct,eff</sub> "
                           "(DS/EN 1992-1-1 &#167;7.1)"),
                      subst=f"f<sub>ct,eff</sub> = {_fmt(el.get('fctm'), 3)} MPa,  "
                            f"sigma<sub>ct,I</sub> = {_fmt(el.get('sigma_ct'), 3)} MPa",
                      result=(
                          f"lambda<sub>cr</sub> = {_fmt(lam,3)}  ->  section is "
                          f"{verdict} (cracks when lambda<sub>cr</sub> &lt;= 1)"
                          if valid else
                          f"lambda<sub>cr</sub> = {_fmt(lam,3)}  ->  INVALID; "
                          "no verified cracking classification"
                      ))
        if valid:
            self._small(
                "Governing of the long-term and total (long + short) actions: "
                "cracking is triggered by the peak tension the section sees, and "
                "is irreversible."
            )
        else:
            self._small(
                "Diagnostic value only: at least one elastic solve did not "
                "converge, so no cracked/uncracked verdict is issued."
            )
        if not el.get("show_cw"):
            self._small("Crack width was not requested for this run.")
            return
        cl, cs = el.get("crack"), el.get("crack_short")
        clc, csc = el.get("crack_coarse"), el.get("crack_short_coarse")
        no_results = cl is None and cs is None and clc is None and csc is None
        assessment = el.get("crack_output") or {}
        status = assessment.get("calculation_state", "NOT CALCULATED")
        value = assessment.get("value")
        text = (
            f"Crack-width output | governing w<sub>k</sub> "
            f"{'-' if value is None else _fmt(value, 3) + ' mm'} | "
            f"case {assessment.get('case') or '-'} | "
            f"element {assessment.get('governing') or '-'}"
        )
        self._p(text)
        self._small(
            f"Calculation state: {status}. No crack-width limit, exposure "
            "acceptance or action-set completeness criterion is applied."
        )
        if no_results:
            self._small("No crack width: section uncracked or no reinforcement "
                        "in tension.")
            return
        self._crack_table(cl, cs, clc, csc)
        # Work the case that actually governs (the larger crack width) over every
        # reported load case and crack system.
        if clc is not None or csc is not None:
            cases = [(cl, "long-term (fine)"), (cs, "short-term (fine)"),
                     (clc, "long-term (coarse)"), (csc, "short-term (coarse)")]
        else:
            cases = [(cl, "long-term"), (cs, "short-term")]
        gov_case, gov_which = max(((c, w) for c, w in cases if c),
                                  key=lambda cw: cw[0].get("wk", 0.0))
        self._crack_worked(gov_case, gov_which)
        self._crack_candidates(cases)

    def _crack_table(self, cl, cs, clc=None, csc=None):
        # The full crack-width breakdown for both load cases, matching the view.
        self._h2("Crack width - both load cases")
        # wk, sr_max, phi and cover come from the engine already in mm; hc_ef (m)
        # and ac_eff (m^2) are metric.
        specs = [("Crack width w<sub>k</sub> (mm)", "wk", 3, 1.0),
                 ("Crack spacing s<sub>r,max</sub> (mm)", "sr_max", 1, 1.0),
                 ("Mean strain eps<sub>sm</sub>-eps<sub>cm</sub> (permille)", "esm_ecm", 4, 1000.0),
                 ("Steel stress sigma<sub>s</sub> (MPa)", "sigma_s", 1, 1.0),
                 ("Effective ratio rho<sub>p,eff</sub>", "rho_p_eff", 4, 1.0),
                 ("Effective height h<sub>c,ef</sub> (mm)", "hc_ef", 1, _MM),
                 ("Effective area A<sub>c,eff</sub> (m<super>2</super>)", "ac_eff", 5, 1.0),
                 ("Clear cover c (mm)", "cover", 1, 1.0),
                 ("Element diameter phi (mm)", "phi", 1, 1.0),
                 ("Governing element", "element_id", None, 1.0)]

        def col(c):
            if c is None:
                return ["-"] * len(specs)
            out = []
            for _label, key, nd, scale in specs:
                value = c.get(key, "-")
                out.append(str(value) if nd is None else
                           _fmt(float(value) * scale, nd))
            return out

        if clc is not None or csc is not None:
            # DK NA: fine and coarse crack systems, each for both load cases.
            header = ["Quantity", "Long-term (fine)", "Short-term (fine)",
                      "Long-term (coarse)", "Short-term (coarse)"]
            cols = [col(cl), col(cs), col(clc), col(csc)]
            widths = [66 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm]
        else:
            header = ["Quantity", "Long-term", "Short-term"]
            cols = [col(cl), col(cs)]
            widths = [85 * mm, 38 * mm, 38 * mm]
        rows = [header]
        for i, spec in enumerate(specs):
            rows.append([spec[0]] + [c[i] for c in cols])
        self._table(rows, widths)

    def _crack_worked(self, cw, which=""):
        if not cw:
            return
        self._h2(f"Crack width worked - governing case ({which})" if which
                 else "Crack width worked (governing element)")
        self._small(f"Governing element (largest w<sub>k</sub>): "
                    f"{cw.get('element_id', 'element ' + str(cw.get('gov_bar','-')))}; "
                    f"clear cover c = {_fmt(cw.get('cover',0), 3)} mm.")
        code = self.out["elastic"].get("crack_code")
        if cw.get("edition") == "2023":
            self._crack_worked_2023(cw, code)
            return
        coarse = bool(cw.get("coarse"))
        if cw.get("sr_max_geometric"):
            # Wide/isolated bars (spacing > 5(c+phi/2)): EC2 assigns the geometric
            # spacing 1.3(h-x) directly (Eq 7.14), so the (7.11) formula would not
            # reproduce the reported value.
            self._formula(
                "s<sub>r,max</sub> = 1.3&#183;(h - x)",
                equation_key="crack.2005.spacing",
                equation_variant="geometric",
                ref="DS/EN 1992-1-1 &#167;7.3.4, Eq (7.14)",
                note="bars not at close centres (spacing &gt; 5(c + phi/2))",
                result=f"s<sub>r,max</sub> = {_fmt(cw.get('sr_max',0), 3)} mm")
        else:
            self._formula(
                "s<sub>r,max</sub> = k<sub>3</sub>&#183;c + "
                "k<sub>1</sub>&#183;k<sub>2</sub>&#183;k<sub>4</sub>&#183;phi / rho<sub>p,eff</sub>",
                equation_key="crack.2005.spacing",
                equation_variant="reinforcement",
                ref="DS/EN 1992-1-1 &#167;7.3.4, Eq (7.11)")
        self._formula(
            "eps<sub>sm</sub> - eps<sub>cm</sub> = [ sigma<sub>s</sub> - "
            "k<sub>t</sub>&#183;f<sub>ct,eff</sub>/rho<sub>p,eff</sub>&#183;"
            "(1 + alpha<sub>e</sub>&#183;rho<sub>p,eff</sub>) ] / E<sub>s</sub> "
            "&gt;= 0.6&#183;sigma<sub>s</sub>/E<sub>s</sub>",
            equation_key="crack.2005.mean-strain",
            ref="Eq (7.9)")
        self._formula(
            ("w<sub>k</sub> = &#189;&#183;s<sub>r,max</sub> &#183; "
             "(eps<sub>sm</sub> - eps<sub>cm</sub>)" if coarse else
             "w<sub>k</sub> = s<sub>r,max</sub> &#183; "
             "(eps<sub>sm</sub> - eps<sub>cm</sub>)"),
            equation_key="crack.2005.width",
            references=("crack.2005.spacing", "crack.2005.mean-strain"),
            ref="DS/EN 1992-1-1 DK NA &#167;7.3.4(1), Eq (7.8)" if coarse else "Eq (7.8)",
            subst=("= &#189; &#183; " if coarse else "= ")
                  + f"{_fmt(cw.get('sr_max',0), 3)} mm &#183; "
                    f"{_fmt(cw.get('esm_ecm',0)*1000,4)} permille",
            result=f"w<sub>k</sub> = {_fmt(cw.get('wk',0),3)} mm")
        if code:
            note = f"Crack-width code: {code}. "
            if "DK NA" in code:
                note += ("k<sub>3</sub> = 3.4&#183;(25/c)<super>2/3</super> "
                         "(&#167;7.3.4(3)). ")
                if coarse:
                    note += ("Coarse crack system (&#167;7.3.4(1)): A<sub>c,eff</sub> "
                             "is the tension-face band whose centroid matches the "
                             "tension reinforcement (figure 7.100 NA), and w<sub>k</sub> "
                             "is halved.")
                else:
                    note += ("The (h-x)/3 term in h<sub>c,ef</sub> applies to slabs "
                             "and prestressed members only.")
            self._small(note)

    def _crack_candidates(self, cases):
        """Append the complete sorted per-element crack-width audit table."""
        rows = [["Case", "#", "Element", "x", "y", "c", "phi",
                 "sigma<sub>s</sub>", "A<sub>c,eff</sub>", "&#916;eps",
                 "s<sub>r</sub>", "w<sub>k</sub>"]]
        for case, label in cases:
            candidates = [] if not case else case.get("candidates", [])
            if not candidates:
                continue
            case_max = float(case.get("wk", 0.0))
            for rank, row in enumerate(candidates, start=1):
                wk = float(row.get("wk", 0.0))
                marker = ("G" if rank == 1 else
                          ("N" if case_max > 0.0 and wk >= 0.9 * case_max else ""))
                rows.append([
                    label.replace("Long-term", "LT").replace("long-term", "LT")
                    .replace("Short-term", "ST").replace("short-term", "ST"),
                    f"{rank}{marker}",
                    row.get("element_id", "-"),
                    _fmt(row.get("x_mm"), 1),
                    _fmt(row.get("y_mm"), 1),
                    _fmt(row.get("cover"), 1),
                    _fmt(row.get("phi"), 1),
                    _fmt(row.get("sigma_s"), 1),
                    _fmt(row.get("ac_eff"), 5),
                    _fmt(row.get("esm_ecm"), 6),
                    _fmt(row.get("sr_max"), 1),
                    _fmt(wk, 3),
                ])
        if len(rows) == 1:
            return
        # Keep the heading, compact table and legend together. ReportLab can place
        # the block in remaining space when it fits, avoiding an unnecessary
        # mostly-empty continuation page.
        block_start = len(self.flow)
        self._h2("Crack-width candidates - all checked cases")
        self._table(
            rows,
            _CRACK_CANDIDATE_COL_WIDTHS,
            font=5.4, keep=False, repeat_cols=3,
        )
        self._small(
            "LT = long-term; ST = short-term. Coordinates, c, phi and "
            "s<sub>r</sub> in mm; sigma<sub>s</sub> in MPa; "
            "A<sub>c,eff</sub> in m<super>2</super>; &#916;eps "
            "dimensionless; w<sub>k</sub> in mm. G = governing; "
            "N = within 10% of governing."
        )
        self._keep_from(block_start)

    def _crack_worked_2023(self, cw, code):
        """The EN 1992-1-1:2023 refined crack-width worked example (9.2.3)."""
        self._formula(
            "s<sub>r,m,cal</sub> = 1.5&#183;c + (k<sub>fl</sub>&#183;k<sub>b</sub>/7.2)"
            "&#183;phi/rho<sub>p,eff</sub> &lt;= (1.3/k<sub>w</sub>)&#183;(h-x)",
            equation_key="crack.2023.spacing",
            ref="EN 1992-1-1:2023 &#167;9.2.3, Eq (9.15)",
            subst=f"k<sub>fl</sub> = {_fmt(cw.get('kfl',1),3)}; "
                  f"s<sub>r,m,cal</sub> = {_fmt(cw.get('sr_max',0), 3)} mm")
        self._formula(
            "eps<sub>sm</sub> - eps<sub>cm</sub> = [ sigma<sub>s</sub> - "
            "k<sub>t</sub>&#183;f<sub>ct,eff</sub>/rho<sub>p,eff</sub>&#183;"
            "(1 + alpha<sub>e</sub>&#183;rho<sub>p,eff</sub>) ] / E<sub>s</sub> "
            "&gt;= (1 - k<sub>t</sub>)&#183;sigma<sub>s</sub>/E<sub>s</sub>",
            equation_key="crack.2023.mean-strain",
            ref="Eq (9.11)")
        self._formula(
            "w<sub>k,cal</sub> = k<sub>w</sub>&#183;k<sub>1/r</sub>&#183;"
            "s<sub>r,m,cal</sub>&#183;(eps<sub>sm</sub> - eps<sub>cm</sub>)",
            equation_key="crack.2023.width",
            references=("crack.2023.spacing", "crack.2023.mean-strain"),
            ref="Eq (9.8)",
            subst=f"= {_fmt(cw.get('kw',1.7), 3)} &#183; {_fmt(cw.get('k1_r',1),3)} &#183; "
                  f"{_fmt(cw.get('sr_max',0), 3)} mm &#183; "
                  f"{_fmt(cw.get('esm_ecm',0)*1000,4)} permille",
            result=f"w<sub>k</sub> = {_fmt(cw.get('wk',0),3)} mm")
        if code:
            self._small(f"Crack-width code: {code}. Refined control of cracking "
                        "(&#167;9.2.3): k<sub>w</sub> = 1.7 converts the mean crack "
                        "width to the calculated value, k<sub>1/r</sub> = (h-x)/"
                        "(h-a<sub>y</sub>-x) accounts for curvature, and the mean "
                        "strain lower bound is (1 - k<sub>t</sub>)&#183;sigma<sub>s</sub>"
                        "/E<sub>s</sub>.")

    def _bridge(self):
        """Independent retained bridge kernels with their actual row inputs."""
        payload = self._base_out.get("bridge") or {}
        self._h1("Independent bridge calculations")
        self._p(
            "<b>Selected method family:</b> "
            + _html_escape(str(payload.get("selected_standard") or "-"))
            + ". These are separate numerical methods; generic bridge-code "
            "coverage and generic cross-method interaction are not calculated."
        )
        errors = tuple(payload.get("errors") or ())
        if errors:
            for error in errors:
                self._small("<b>Invalid bridge input:</b> " + _html_escape(str(error)))
            return
        calculations = payload.get("calculations") or {}
        if not calculations:
            self._small("No bridge calculation rows were supplied.")
            return

        brittle = calculations.get("brittle_method_b")
        if brittle:
            self._h2("Optional brittle Method B")
            self._small(
                f"<b>Equation:</b> {_html_escape(brittle.get('equation', '-'))}; "
                f"<b>reference:</b> {_html_escape(brittle.get('source', '-'))}."
            )
            if brittle.get("warning"):
                self._small("<b>Warning:</b> " + _html_escape(brittle["warning"]))
            rows = [[
                "Region", "Mrep (kNm)", "zs (m)", "fyk (MPa)",
                "As,req (mm2)", "As,prov (mm2)", "Util.", "Status",
            ]]
            rows.extend([
                [
                    _html_escape(row["region_id"]),
                    _fmt(row["m_rep_knm"], 3),
                    _fmt(row["z_s_m"], 3),
                    _fmt(row["f_yk_mpa"], 2),
                    _fmt(row["as_required_mm2"], 1),
                    _fmt(row["as_provided_mm2"], 1),
                    _pct(row["utilisation"]),
                    row["status"],
                ]
                for row in brittle["rows"]
            ])
            self._table(
                rows,
                [23 * mm, 21 * mm, 17 * mm, 20 * mm, 23 * mm, 23 * mm,
                 18 * mm, 18 * mm],
                font=6.7,
            )

        walls = calculations.get("box_walls")
        if walls:
            self._h2("Box-wall shear and torsion")
            self._small(
                f"<b>Equation:</b> {_html_escape(walls.get('equation', '-'))}; "
                f"<b>reference:</b> {_html_escape(walls.get('source', '-'))}."
            )
            for warning in walls.get("warnings") or ():
                self._small("<b>Warning:</b> " + _html_escape(str(warning)))
            rows = [[
                "Wall", "cot(theta)", "VEd", "VRd,max", "TEd,eq",
                "TRd,max,eq", "Util.", "Status",
            ]]
            rows.extend([
                [
                    _html_escape(row["wall_id"]),
                    _fmt(row["cot_theta"], 3),
                    _fmt(row["v_ed_kn"], 2),
                    _fmt(row["v_rd_max_kn"], 2),
                    _fmt(row["t_ed_equivalent_kn"], 2),
                    _fmt(row["t_rd_max_equivalent_kn"], 2),
                    _pct(row["utilisation"]),
                    row["status"],
                ]
                for row in walls["rows"]
            ])
            self._table(
                rows,
                [22 * mm, 19 * mm, 20 * mm, 22 * mm, 21 * mm, 25 * mm,
                 19 * mm, 18 * mm],
                font=6.7,
            )

        minimum = calculations.get("minimum_crack_reinforcement")
        if minimum:
            self._h2("Web/flange minimum crack reinforcement")
            self._small(
                f"<b>Equation:</b> {_html_escape(minimum.get('equation', '-'))}; "
                f"<b>reference:</b> {_html_escape(minimum.get('source', '-'))}."
            )
            rows = [[
                "Component", "Act (mm2)", "fct,eff used", "sigma_s",
                "As,req", "As,prov", "Util.", "Status",
            ]]
            rows.extend([
                [
                    _html_escape(row["component"].capitalize()),
                    _fmt(row["act_mm2"], 1),
                    _fmt(row["fct_eff_used_mpa"], 3),
                    _fmt(row["sigma_s_mpa"], 2),
                    _fmt(row["as_required_mm2"], 1),
                    _fmt(row["as_provided_mm2"], 1),
                    _pct(row["utilisation"]),
                    row["status"],
                ]
                for row in minimum["rows"]
            ])
            self._table(
                rows,
                [24 * mm, 23 * mm, 23 * mm, 20 * mm, 20 * mm, 20 * mm,
                 18 * mm, 18 * mm],
                font=6.7,
            )

    def _fatigue(self):
        payload = self._base_out["fatigue"]
        status = fatigue_presentation.overall_status(payload)
        errors = tuple(payload.get("errors") or ())
        governing_name = str(payload.get("governing_spectrum") or "-")
        self._h1("Grouped fatigue")
        self._status_block(
            (
                f"{status} - fatigue not assessed; "
                "other requested analyses were calculated"
                if errors
                else (
                    f"{status} - {_html_escape(governing_name)} | utilisation "
                    f"{_pct(fatigue_presentation.evidence_number(
                        payload.get('utilisation')
                    ))}"
                )
            ),
            status,
        )
        checks = payload.get("checks") or {}
        check_text = ", ".join(
            label
            for key, label in (
                ("reinforcement", "reinforcement"),
                ("concrete", "concrete"),
            )
            if checks.get(key)
        ) or "-"
        self._small(
            f"<b>Edition:</b> {_html_escape(str(payload.get('edition') or '-'))}; "
            f"<b>checks:</b> {check_text}. Each spectrum is independent."
        )
        warnings = tuple(payload.get("warnings") or ())
        for warning in warnings:
            self._small("<b>Review:</b> " + _html_escape(str(warning)))
        if errors:
            self._p(
                "Fatigue input was incomplete or invalid at calculation time. "
                "No fatigue resistance verdict has been issued."
            )
            for error in errors:
                self._small("<b>Input error:</b> " + _html_escape(str(error)))
            return

        self._h2("Basis and provenance")
        basis = payload.get("basis") or {}
        factors = payload.get("partial_factors") or {}
        concrete_parameters = payload.get("concrete_parameters") or {}
        basis_rows = [
            ["Item", "Value"],
            ["Method", _html_escape(str(basis.get("method") or "-"))],
            ["Method reference",
             _html_escape(str(payload.get("method_reference") or "-"))],
            ["Action-set notes",
             _html_escape(str(basis.get("notes") or "-"))],
            ["gamma<sub>Ff</sub>", _fmt(factors.get("gamma_ff"), 3)],
        ]
        if checks.get("reinforcement"):
            basis_rows.append([
                "gamma<sub>s</sub>", _fmt(factors.get("gamma_s"), 3)
            ])
        if checks.get("concrete"):
            basis_rows.extend([
                ["gamma<sub>c,fat</sub>", _fmt(factors.get("gamma_c"), 3)],
                ["t<sub>0</sub> (days)", _fmt(payload.get("t0_days"), 2)],
                ["beta<sub>cc</sub>(t<sub>0</sub>)",
                 _fmt(concrete_parameters.get("beta_cc_t0"), 4)],
                ["f<sub>ck</sub> (MPa)",
                 _fmt(concrete_parameters.get("fck_mpa"), 2)],
                ["alpha<sub>cc</sub>",
                 _fmt(concrete_parameters.get("alpha_cc"), 3)],
                ["k<sub>1</sub>",
                 _fmt(concrete_parameters.get("k1"), 3)],
                ["C", _fmt(concrete_parameters.get("c"), 3)],
            ])
        if basis.get("notes"):
            basis_rows.append([
                "Notes", _html_escape(str(basis.get("notes")))
            ])
        self._table(basis_rows, [52 * mm, 113 * mm], keep=False)

        references = payload.get("calculation_references") or {}
        if references:
            self._h2("Calculation references")
            self._table(
                [["Check", "Reference"]]
                + [
                    [
                        key.capitalize(),
                        _html_escape(str(reference)),
                    ]
                    for key, reference in references.items()
                ],
                [35 * mm, 130 * mm],
                font=7.2,
                keep=False,
            )
        details = payload.get("fatigue_detail_basis") or ()
        if details:
            self._h2("Assigned fatigue details")
            rows = [[
                "ID", "Name", "Type", "Preset", "N<super>*</super>", "k<sub>1</sub>",
                "k<sub>2</sub>", "&#916;sigma<sub>Rsk</sub>", "Source",
            ]]
            rows.extend([
                [
                    _html_escape(str(detail.get("id") or "-")),
                    _html_escape(str(detail.get("name") or "-")),
                    _html_escape(str(detail.get("kind") or "-")),
                    _html_escape(str(detail.get("preset") or "-")),
                    _fmt(detail.get("n_star"), 3),
                    _fmt(detail.get("k1"), 2),
                    _fmt(detail.get("k2"), 2),
                    f"{_fmt(detail.get('delta_sigma_rsk_mpa'), 2)} MPa",
                    _html_escape(str(detail.get("source") or "not stated")),
                ]
                for detail in details
            ])
            self._table(
                rows,
                [12 * mm, 22 * mm, 14 * mm, 31 * mm, 15 * mm,
                 10 * mm, 10 * mm, 23 * mm, 31 * mm],
                font=5.3,
                keep=False,
                repeat_cols=4,
            )

        summary_rows = fatigue_presentation.spectrum_rows(payload)
        self._h2("Spectrum summary")
        rows = [[
            "Spectrum", "Status", "Bins", "Steel", "Concrete", "Governing",
            "Utilisation", "Search upper D",
        ]]
        rows.extend([
            [
                _html_escape(row["spectrum"]),
                row["status"],
                row["bins"],
                row["reinforcement_elements"],
                row["concrete_fibres"],
                _html_escape(row["governing"]),
                _pct(row["utilisation"]),
                _fmt_sig(row["search_upper_damage"], 6),
            ]
            for row in summary_rows
        ])
        self._table(
            rows,
            [24 * mm, 16 * mm, 10 * mm, 12 * mm, 15 * mm,
             44 * mm, 22 * mm, 23 * mm],
            font=6.0,
            keep=False,
        )
        self._small(
            "Miner sums are accumulated within each spectrum; different "
            "spectrum names are not combined."
        )

        input_records = fatigue_inputs.spectrum_records(
            self._base_inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
        )
        spectra = fatigue_presentation.items(payload, "spectra")
        for spectrum in spectra:
            # Each independently assessed spectrum starts as a coherent report
            # unit; do not strand its heading below the aggregate summary.
            self.flow.append(NotAtTopPageBreak())
            spectrum_name = str(
                fatigue_presentation.value(spectrum, "spectrum_name", "-")
            )
            spectrum_status = fatigue_presentation.result_status(spectrum)
            self._h2("Spectrum - " + _html_escape(spectrum_name))
            self._status_block(
                f"{spectrum_status} - utilisation "
                f"{_pct(fatigue_presentation.evidence_number(
                    fatigue_presentation.value(spectrum, 'utilisation')
                ))} | {_html_escape(
                    fatigue_presentation.governing_criterion(spectrum)
                )}",
                spectrum_status,
            )

            self._fig(
                viz.fatigue_utilisation_map_figure(
                    self._base_inp.get("outer", []),
                    self._base_inp.get("holes", []),
                    self._base_inp.get("bar_elements", []),
                    self._base_inp.get("tendon_elements", []),
                    spectrum,
                    title=f"Fatigue utilisation - {spectrum_name}",
                ),
                150,
                105,
            )

            selected_inputs = [
                row for row in input_records
                if row[fatigue_inputs.SPECTRUM] == spectrum_name
            ]
            if selected_inputs:
                self._h2("Entered spectrum actions")
                rows = [[
                    "Bin", "Description", "Cycles", "N<sub>long,Ed</sub>",
                    "M<sub>x,long,Ed</sub>", "M<sub>y,long,Ed</sub>",
                    "N<sub>short,Ed</sub>", "M<sub>x,short,Ed</sub>",
                    "M<sub>y,short,Ed</sub>",
                ]]
                rows.extend([
                    [
                        _html_escape(row[fatigue_inputs.NAME]),
                        _html_escape(row[fatigue_inputs.DESCRIPTION]),
                        _fmt(row[fatigue_inputs.CYCLES], 3),
                        _fmt(row["n_long_ed_kn"], 3),
                        _fmt(row["mx_long_ed_knm"], 3),
                        _fmt(row["my_long_ed_knm"], 3),
                        _fmt(row["n_short_ed_kn"], 3),
                        _fmt(row["mx_short_ed_knm"], 3),
                        _fmt(row["my_short_ed_knm"], 3),
                    ]
                    for row in selected_inputs
                ])
                self._table(
                    rows,
                    [18 * mm, 30 * mm, 16 * mm] + [17 * mm] * 6,
                    font=5.3,
                    keep=False,
                    repeat_cols=2,
                )
                self._small(
                    "N in kN; M in kNm; N tension-positive. "
                    "Long is sustained; short is the cyclic increment."
                )

            state_rows = fatigue_presentation.spectrum_bin_rows(spectrum)
            if state_rows:
                self._h2("Elastic solver states")
                rows = [[
                    "Bin", "Status", "gamma<sub>Ff</sub>", "Bond method",
                    "Max design &#916;sigma", "Max concrete compression",
                ]]
                rows.extend([
                    [
                        _html_escape(row["bin"]),
                        row["status"],
                        _fmt(row["gamma_ff"], 3),
                        _html_escape(row["bond_method"]),
                        f"{_fmt(row['max_design_stress_range_mpa'], 3)} MPa",
                        f"{_fmt(row['max_concrete_compression_mpa'], 3)} MPa",
                    ]
                    for row in state_rows
                ])
                self._table(
                    rows,
                    [22 * mm, 18 * mm, 22 * mm, 42 * mm, 31 * mm, 31 * mm],
                    font=6.4,
                    keep=False,
                )

            reinforcement_rows = fatigue_presentation.reinforcement_rows(
                spectrum
            )
            if reinforcement_rows:
                self._h2("Reinforcement fatigue")
                rows = [[
                    "Element", "Type", "Detail", "phi", "Miner D",
                    "Yield / proof util.", "Governing", "Util.", "Status",
                ]]
                rows.extend([
                    [
                        _html_escape(row["element_id"]),
                        _html_escape(row["kind"]),
                        _html_escape(row["detail_id"]),
                        f"{_fmt(row['diameter_mm'], 1)} mm",
                        _fmt_sig(row["damage"], 6),
                        _pct(row["yield_utilisation"]),
                        _html_escape(row["governing"]),
                        _pct(row["utilisation"]),
                        row["status"],
                    ]
                    for row in reinforcement_rows
                ])
                self._table(
                    rows,
                    [18 * mm, 14 * mm, 15 * mm, 15 * mm, 18 * mm,
                     23 * mm, 29 * mm, 19 * mm, 16 * mm],
                    font=5.7,
                    keep=False,
                    repeat_cols=3,
                )
                governing_id = fatigue_presentation.value(
                    spectrum, "governing_reinforcement_id"
                )
                if governing_id is None:
                    governing_id = max(
                        reinforcement_rows,
                        key=lambda row: row["utilisation"] or -math.inf,
                    )["element_id"]
                result = fatigue_presentation.result_by_element(
                    spectrum, governing_id
                )
                properties = fatigue_presentation.reinforcement_property(
                    payload, governing_id
                )
                if result is not None and properties is not None:
                    self._h2(
                        "Governing reinforcement element - "
                        + _html_escape(str(governing_id))
                    )
                    self._table(
                        [[
                            "Detail", "N<super>*</super>", "k<sub>1</sub>", "k<sub>2</sub>",
                            "&#916;sigma<sub>Rsk</sub>", "f<sub>yk</sub> / proof",
                            "Bond factor",
                        ], [
                            _html_escape(str(fatigue_presentation.value(
                                properties, "detail_id", "-"
                            ))),
                            _fmt(fatigue_presentation.value(
                                properties, "n_star"
                            ), 3),
                            _fmt(fatigue_presentation.value(
                                properties, "k1"
                            ), 2),
                            _fmt(fatigue_presentation.value(
                                properties, "k2"
                            ), 2),
                            f"{_fmt(fatigue_presentation.value(
                                properties, 'delta_sigma_rsk_mpa'
                            ), 2)} MPa",
                            f"{_fmt(fatigue_presentation.value(
                                properties, 'fytk_mpa'
                            ), 2)} MPa",
                            _fmt(fatigue_presentation.value(
                                properties, "bond_ratio_xi"
                            ), 3),
                        ]],
                        [22 * mm, 20 * mm, 15 * mm, 15 * mm,
                         32 * mm, 32 * mm, 24 * mm],
                        font=6.2,
                    )
                    self._fig(
                        viz.fatigue_sn_figure(
                            result,
                            properties,
                            factors.get("gamma_s"),
                            title=f"S-N assessment - {governing_id}",
                        ),
                        150,
                        95,
                    )
                    self._fig(
                        viz.fatigue_damage_figure(
                            result,
                            title=f"Miner damage - {governing_id}",
                        ),
                        150,
                        82,
                    )
                    bin_rows = fatigue_presentation.reinforcement_bin_rows(
                        result
                    )
                    rows = [[
                        "Bin", "Cycles", "Status", "Long stress",
                        "Fatigue total", "Design total", "Elastic &#916;sigma",
                        "Design &#916;sigma", "Bond factor / method",
                    ]]
                    rows.extend([
                        [
                            _html_escape(row["bin"]),
                            _fmt(row["cycles"], 3),
                            row["status"],
                            _fmt(row["stress_long_mpa"], 3),
                            _fmt(row["stress_total_mpa"], 3),
                            _fmt(row["stress_total_design_mpa"], 3),
                            _fmt(row["stress_range_elastic_mpa"], 3),
                            _fmt(row["design_stress_range_mpa"], 3),
                            (
                                f"{_fmt(row['bond_adjustment'], 3)}<br/>"
                                f"{_html_escape(row['bond_method'])}"
                            ),
                        ]
                        for row in bin_rows
                    ])
                    self._table(
                        rows,
                        [18 * mm, 18 * mm, 16 * mm, 18 * mm, 18 * mm,
                         19 * mm, 20 * mm, 21 * mm, 20 * mm],
                        font=5.2,
                        keep=False,
                    )
                    self._small(
                        "All stresses are in MPa. Fatigue total includes the bond "
                        "transformation; elastic &#916;sigma is the raw solver "
                        "range; design values include action-level "
                        "gamma<sub>Ff</sub>."
                    )
                    rows = [[
                        "Bin", "&#916;sigma<sub>Rsk</sub>",
                        "&#916;sigma<sub>Rd</sub>", "k", "N<sub>R</sub>",
                        "Miner D", "Gov. stress", "Yield / proof", "Yield util.",
                    ]]
                    rows.extend([
                        [
                            _html_escape(row["bin"]),
                            _fmt(row["delta_sigma_rsk_mpa"], 3),
                            _fmt(row["delta_sigma_rd_mpa"], 3),
                            _fmt(row["sn_exponent"], 2),
                            _fmt_sig(row["cycles_to_failure"], 6),
                            _fmt_sig(row["damage"], 6),
                            _fmt(row["governing_stress_mpa"], 3),
                            _fmt(row["yield_limit_mpa"], 3),
                            _pct(row["yield_utilisation"]),
                        ]
                        for row in bin_rows
                    ])
                    self._table(
                        rows,
                        [18 * mm, 20 * mm, 20 * mm, 12 * mm, 21 * mm,
                         18 * mm, 20 * mm, 21 * mm, 18 * mm],
                        font=5.4,
                        keep=False,
                    )

            concrete_rows = fatigue_presentation.concrete_rows(spectrum)
            if concrete_rows:
                equivalent_method = any(
                    row.get("equivalent_utilisation") is not None
                    for row in concrete_rows
                )
                self._h2("Concrete fatigue")
                rows = [[
                    "Fibre", "Source", "x", "y", "f<sub>cd,fat</sub>",
                    (
                        "Equivalent util." if equivalent_method else "Miner D"
                    ),
                    "Stress util.", "Governing", "Util.", "Status",
                ]]
                rows.extend([
                    [
                        row["fibre_index"],
                        row["source"],
                        _fmt(row["x_mm"], 1),
                        _fmt(row["y_mm"], 1),
                        _fmt(row["fcd_fat_mpa"], 3),
                        (
                            _pct(row["equivalent_utilisation"])
                            if equivalent_method
                            else _fmt_sig(row["damage"], 6)
                        ),
                        _pct(row["stress_utilisation"]),
                        row["governing"],
                        _pct(row["utilisation"]),
                        row["status"],
                    ]
                    for row in concrete_rows
                ])
                self._table(
                    rows,
                    [11 * mm, 20 * mm, 13 * mm, 13 * mm, 17 * mm,
                     16 * mm, 18 * mm, 22 * mm, 16 * mm, 14 * mm],
                    font=5.4,
                    keep=False,
                    repeat_cols=2,
                )
                self._small(
                    "Coordinates in mm; f<sub>cd,fat</sub> in MPa. The selected "
                    "criterion and stress are evaluated at the same fixed fibre."
                )
                governing_fibre = fatigue_presentation.value(
                    spectrum, "governing_concrete_fibre"
                )
                result = fatigue_presentation.result_by_fibre(
                    spectrum, governing_fibre
                )
                if result is None:
                    result = max(
                        fatigue_presentation.items(spectrum, "concrete"),
                        key=lambda item: (
                            fatigue_presentation.evidence_number(
                                fatigue_presentation.value(
                                    item, "utilisation"
                                )
                            ) or -math.inf
                        ),
                    )
                    governing_fibre = fatigue_presentation.value(
                        result, "fibre_index"
                    )
                self._h2(
                    "Governing concrete fibre - "
                    + _html_escape(str(governing_fibre))
                )
                self._fig(
                    viz.fatigue_damage_figure(
                        result,
                        title=(
                            "Damage-equivalent criterion"
                            if equivalent_method
                            else "Miner damage"
                        ) + f" - concrete fibre {governing_fibre}",
                    ),
                    150,
                    82,
                )
                search = fatigue_presentation.value(
                    spectrum, "concrete_search"
                )
                if search is not None:
                    search_status = (
                        "BOUNDED"
                        if fatigue_presentation.value(
                            search, "converged", False
                        )
                        else "INVALID"
                    )
                    self._h2("Bounded governing-fibre search")
                    self._table(
                        [[
                            "Status", "x", "y",
                            (
                                "Point util. [%]"
                                if equivalent_method else "Point D"
                            ),
                            (
                                "Upper util. [%]"
                                if equivalent_method else "Upper D"
                            ),
                            (
                                "Abs. gap [%]"
                                if equivalent_method else "Abs. gap"
                            ),
                            "Rel. gap", "Divisions", "Boxes", "Points",
                        ], [
                            search_status,
                            f"{_fmt(1000.0 * fatigue_presentation.value(
                                search, 'x_m', 0.0
                            ), 2)} mm",
                            f"{_fmt(1000.0 * fatigue_presentation.value(
                                search, 'y_m', 0.0
                            ), 2)} mm",
                            (
                                _pct(fatigue_presentation.value(
                                    search, "damage"
                                ))
                                if equivalent_method
                                else _fmt_sig(fatigue_presentation.value(
                                    search, "damage"
                                ), 6)
                            ),
                            (
                                _pct(fatigue_presentation.value(
                                    search, "upper_damage"
                                ))
                                if equivalent_method
                                else _fmt_sig(fatigue_presentation.value(
                                    search, "upper_damage"
                                ), 6)
                            ),
                            (
                                _pct(fatigue_presentation.value(
                                    search, "absolute_gap"
                                ))
                                if equivalent_method
                                else _fmt_sig(fatigue_presentation.value(
                                    search, "absolute_gap"
                                ), 6)
                            ),
                            _pct(fatigue_presentation.value(
                                search, "relative_gap"
                            )),
                            fatigue_presentation.value(search, "divisions", "-"),
                            fatigue_presentation.value(
                                search, "boxes_evaluated", "-"
                            ),
                            fatigue_presentation.value(
                                search, "points_evaluated", "-"
                            ),
                        ]],
                        [16 * mm, 16 * mm, 16 * mm, 16 * mm, 16 * mm,
                         16 * mm, 16 * mm, 16 * mm, 18 * mm, 18 * mm],
                        font=5.3,
                    )
                bin_rows = fatigue_presentation.concrete_bin_rows(result)
                rows = [[
                    "Bin", "Cycles", "Status", "Long comp.", "Total comp.",
                    "Design min", "Design max", "Ratio", "E<sub>cd,min</sub>",
                    "E<sub>cd,max</sub>",
                ]]
                rows.extend([
                    [
                        _html_escape(row["bin"]),
                        _fmt(row["cycles"], 3),
                        row["status"],
                        _fmt(row["compression_long_mpa"], 3),
                        _fmt(row["compression_total_mpa"], 3),
                        _fmt(row["compression_min_design_mpa"], 3),
                        _fmt(row["compression_max_design_mpa"], 3),
                        _fmt(row["stress_ratio"], 4),
                        _fmt(row["e_cd_min"], 4),
                        _fmt(row["e_cd_max"], 4),
                    ]
                    for row in bin_rows
                ])
                self._table(
                    rows,
                    [17 * mm, 17 * mm, 15 * mm, 18 * mm, 18 * mm,
                     18 * mm, 18 * mm, 14 * mm, 15 * mm, 15 * mm],
                    font=5.2,
                    keep=False,
                )
                self._small(
                    "Compression values in MPa; E<sub>cd</sub> is the "
                    "normalised design compression level."
                )
                rows = [[
                    "Bin",
                    (
                        "Equivalent utilisation"
                        if equivalent_method else "N<sub>R</sub>"
                    ),
                    (
                        "Basis" if equivalent_method
                        else "log<sub>10</sub>N<sub>R</sub>"
                    ),
                    (
                        "Cycle count" if equivalent_method
                        else "Miner D"
                    ),
                    "Stress utilisation",
                ]]
                rows.extend([
                    [
                        _html_escape(row["bin"]),
                        (
                            _pct(row["equivalent_utilisation"])
                            if equivalent_method
                            else _fmt_sig(row["cycles_to_failure"], 6)
                        ),
                        (
                            "N = 10<super>6</super>"
                            if equivalent_method
                            else _fmt(row["log10_cycles_to_failure"], 5)
                        ),
                        (
                            "Not used"
                            if equivalent_method
                            else _fmt_sig(row["damage"], 6)
                        ),
                        _pct(row["stress_utilisation"]),
                    ]
                    for row in bin_rows
                ])
                self._table(
                    rows,
                    [28 * mm, 35 * mm, 35 * mm, 32 * mm, 35 * mm],
                    font=6.5,
                    keep=False,
                )
                if equivalent_method:
                    self._small(
                        "Concrete criterion: E<sub>cd,max</sub> + 0.43 "
                        "&#8730;(1 - E<sub>cd,min</sub>/E<sub>cd,max</sub>) "
                        "&#8804; 1. Each action pair is user-supplied as a "
                        "damage-equivalent amplitude for 10<super>6</super> "
                        "cycles; the entered cycle count is not used for concrete."
                    )

    def _appendix(self):
        self.flow.append(NotAtTopPageBreak())
        self._h1("QA appendix - references and notes")
        lines = []
        plastic_results = self._result_values("plastic")
        elastic_results = self._result_values("elastic")
        shear_results = self._result_values("shear")
        torsion_results = self._result_values("torsion")
        combined_results = self._result_values("combined")
        if plastic_results:
            if "2023" in str(self.inp.get("concrete_preset", "")):
                lines.append(
                    "Selected concrete material - EN 1992-1-1:2023: &#167;5.1.6 "
                    "and Formulae (5.3)-(5.4) (f<sub>cd</sub>, eta<sub>cc</sub>, "
                    "k<sub>tc</sub>), and &#167;8.1.1-8.1.2 / Formula (8.4) "
                    "(bending and concrete compression law)."
                )
            else:
                lines.append(
                    "Selected concrete material - DS/EN 1992-1-1: &#167;3.1.6 "
                    "(f<sub>cd</sub>), &#167;3.1.7 / Table 3.1 (concrete curve and "
                    "strains), and &#167;6.1 (bending)."
                )
            if self.inp.get("bars"):
                steel_presets = [
                    str(item.get("preset", ""))
                    for item in (self.inp.get("mild_material_catalog") or {}).get(
                        "items", [])
                    if item.get("id") in {
                        element.get("material_id")
                        for element in self.inp.get("bar_elements", [])
                    }
                ] or [str(self.inp.get("mild_preset", ""))]
                standard_refs, has_unassigned = _steel_reference_set(steel_presets)
                if not has_unassigned and len(standard_refs) == 1:
                    lines.append(
                        "Selected reinforcing-steel material - "
                        f"{standard_refs[0]}."
                    )
                elif not has_unassigned:
                    lines.append(
                        "Reinforcing-steel catalogue uses mixed recognised "
                        "editions; each material definition and source is listed "
                        "in Section and materials."
                    )
                elif standard_refs:
                    lines.append(
                        "Reinforcing-steel catalogue includes recognised standard "
                        "presets and custom/generic laws. Standard references: "
                        + "; ".join(standard_refs)
                        + ". Custom/generic laws have no assigned normative curve "
                        "source; use the material description as project evidence."
                    )
                else:
                    lines.append(
                        "Reinforcing-steel catalogue uses custom/generic "
                        "constitutive laws; no normative curve source is assigned. "
                        "Use the material description as project evidence."
                    )
            lines.append(
                "The capacity solver is covered by independent hand-calculation "
                "regression cases."
            )
        if elastic_results:
            elastic = elastic_results[0]
            crack_2023 = (
                elastic.get("crack_edition") == "2023"
                or "2023" in str(elastic.get("crack_code", ""))
            )
            clauses = (
                "&#167;9.2 (cracking threshold)"
                if crack_2023 else
                "&#167;7.2 (cracking threshold)"
            )
            if any(result.get("show_cw") for result in elastic_results):
                clauses += (
                    " and &#167;9.2.3 (refined crack control)"
                    if crack_2023 else
                    " and &#167;7.3.2-7.3.4 (crack width)"
                )
            edition = "EN 1992-1-1:2023" if crack_2023 else "DS/EN 1992-1-1"
            lines.append(f"{edition} (Eurocode 2): {clauses}.")
            lines.append(
                "Stresses and crack widths are numerical outputs for the named "
                "user-defined actions. No exposure, durability, decompression or "
                "action-combination acceptance criterion is applied."
            )
            if any(
                "DK NA" in str(result.get("crack_code", ""))
                for result in elastic_results
            ):
                lines.append(
                    "The Danish National Annex modifications to crack spacing and "
                    "effective tension-area height are stated with the calculation."
                )
        if shear_results:
            sh = shear_results[0]
            if sh.get("model_2023"):
                lines.append(
                    "EN 1992-1-1:2023 &#167;8.2.1-8.2.2: Formulae (8.18), "
                    "(8.20), (8.27), (8.30) and (8.31), including the axial-force "
                    "factor k<sub>vp</sub> and prestressing effects."
                )
            elif "DK NA" in str(sh.get("method", "")):
                lines.append(
                    "The selected Danish shear method applies the DK NA:2024 "
                    "v<sub>min</sub> and, where links are checked, the stated "
                    "Danish concrete-strut factor. Intermediate values are printed "
                    "with the calculation."
                )
            else:
                lines.append(
                    "The selected shear method and its clause references are stated "
                    "with the shear-resistance calculation."
                )
        if torsion_results:
            tor = torsion_results[0]
            if "DK NA" in str(tor.get("method", "")):
                lines.append(
                    "The Danish torsion method applies the reported DK NA:2024 "
                    "pure-torsion strut factor and any explicitly selected closed-"
                    "stirrup detailing enhancement."
                )
            else:
                lines.append(
                    "The selected torsion method and its clause references are "
                    "stated with the torsion-resistance calculation."
                )
        if any(result.get("valid") for result in combined_results):
            lines.append(
                "The combined M-V-T chapter states the selected edition, the common "
                "strut-angle basis and the applicable interaction expressions."
            )
        fatigue = self._base_out.get("fatigue")
        fatigue_errors = tuple((fatigue or {}).get("errors") or ())
        if fatigue is not None and not fatigue_errors:
            references = fatigue.get("calculation_references") or {}
            lines.append(
                "Grouped fatigue spectra are assessed independently with the "
                "cracked Elastic solver. gamma<sub>Ff</sub> is applied to the "
                "cyclic actions before solving; gamma<sub>s</sub> is applied to "
                "the reinforcement S-N resistance."
            )
            for label, reference in references.items():
                lines.append(
                    f"Fatigue - {_html_escape(label)}: "
                    f"{_html_escape(str(reference))}."
                )
            method_reference = fatigue.get("method_reference")
            if method_reference:
                lines.append(
                    "Fatigue calculation-method reference: "
                    + _html_escape(str(method_reference))
                    + "."
                )
            lines.append(
                "Torsion and shear fatigue are not assessed in this version."
            )
        elif fatigue_errors:
            lines.append(
                "Fatigue was requested but not assessed because the input "
                "preflight was invalid. No fatigue methodology or resistance "
                "verdict was applied."
            )
        lines.append(
            "The printed gamma<sub>c</sub>, gamma<sub>s</sub> and reinforcement "
            "factors are the final user-entered partial factors. Sector applies no "
            "hidden construction-, control- or consequence-category multiplier."
        )
        lines.append(
            "All results follow from the documented inputs and cited formulas; "
            "intermediate values are shown for the governing cases."
        )
        for line in lines:
            self._p("- " + line)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self._small(f"Generated {ts} by Sector {self.version}.")


def build_report(
    meta,
    inp,
    out,
    version="",
    figures=True,
    progress=None,
    qa_appendix=True,
) -> bytes:
    """Build the PDF report and return its bytes.

    ``progress`` is an optional ``callable(fraction, text)`` invoked as the report
    is assembled, so the UI can show a progress bar. ``qa_appendix`` adds the
    consolidated references-and-notes chapter.
    """
    buffer = io.BytesIO()
    ReportBuilder(
        buffer,
        meta,
        inp,
        out,
        version=version,
        figures=figures,
        progress=progress,
        qa_appendix=qa_appendix,
    ).build()
    buffer.seek(0)
    return buffer.getvalue()
