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
import io
import math
import os
import re
import threading
from html import escape as _html_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

import case_analysis
import viz
import result_presentation as presentation
from sector import codes as ec2_codes
from sector import __licensee__ as SECTOR_LICENSEE
from sector.build_info import short_revision

_MM = 1000.0                       # metres -> millimetres for display
_KN = 1.0                          # forces already in kN
_BLUE = colors.HexColor("#1F3B66")
_GREY = colors.HexColor("#5A5A5A")
_LINE = colors.HexColor("#9AA5B1")
_HEAD_BG = colors.HexColor("#E8ECF2")
_A4_CONTENT_WIDTH = A4[0] - 40 * mm
_CRACK_CANDIDATE_COL_WIDTHS = tuple(
    value * mm
    for value in (17, 7, 16, 13, 13, 10, 10, 17, 18, 18, 13, 13)
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
          "gamma": "&#947;", "kappa": "&#954;", "rho": "&#961;", "phi": "&#966;",
          "theta": "&#952;", "nu": "&#957;", "tau": "&#964;", "permille": "&#8240;"}
_GREEK_RE = re.compile(r"\b(" + "|".join(_GREEK) + r")\b")


def _greek(s):
    """Replace the ASCII engineering tokens in display text with Greek glyphs."""
    s = _GREEK_RE.sub(lambda m: _GREEK[m.group(1)], s)
    return s.replace("&lt;=", "&#8804;").replace("&gt;=", "&#8805;")


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
            start(silence_warnings=True)
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
    out["formula"] = ParagraphStyle("f", parent=ss["Normal"], fontSize=9.5,
                                    leading=13, leftIndent=10, spaceAfter=2,
                                    fontName=_FONT)
    out["ref"] = ParagraphStyle("r", parent=ss["Normal"], fontSize=8,
                               fontName=_FONT, leading=10, leftIndent=10,
                               textColor=_GREY, spaceAfter=4)
    return out


_FIG_EXPORT_TIMEOUT_S = 20.0


class ReportFigureError(RuntimeError):
    """Raised when a requested engineering figure cannot be embedded."""


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
        return "inf"
    return f"{v:.{nd}f}"


def _fmt_sig(v, sig=6):
    """Format small engineering values without rounding nonzero evidence to zero."""
    if v is None:
        return "-"
    if isinstance(v, float) and not math.isfinite(v):
        return "inf"
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
    return " | ".join(parts)


def _code_verdict(ok, applicable=True):
    """Compliance wording that never turns an out-of-scope value into ``OK``."""
    if not applicable:
        return "NO CODE VERDICT - STRUT BOUNDS OUTSIDE RANGE"
    return "OK" if ok else "EXCEEDED"


class ReportBuilder:
    """Builds the PDF into ``buffer`` from ``meta``, ``inp`` and ``out``."""

    def __init__(self, buffer, meta, inp, out, version="", figures=True,
                 progress=None):
        self.buffer = buffer
        self.meta = meta or {}
        self.inp = inp
        self.out = out or {}
        # Keep the complete table-level payload available while the existing
        # detail renderers are temporarily pointed at one canonical case.  This
        # preserves their well-tested single-case contract without allowing the
        # first-row compatibility projection to hide later cases in the PDF.
        self._base_inp = inp
        self._base_out = out or {}
        self.version = version
        self.figures = figures
        self._progress = progress
        self.s = _styles()
        self.flow = []
        self._chapter = 0
        self._export_hung = False   # set once a kaleido export hits the join timeout

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

        # Legacy callers still provide one scalar action set and one flat result
        # mapping.  Keep that API fully supported.
        result_key = "elastic" if family == "elastic" else None
        active = (
            result_key in self._base_out
            if result_key is not None
            else any(
                key in self._base_out
                for key in ("plastic", "shear", "torsion", "combined")
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
        return "; ".join(
            _report_action_set_text(case_inp, family)
            for case_inp, _ in contexts
        )

    def _tick(self, frac, text):
        if self._progress is not None:
            self._progress(frac, text)

    # -- flowable helpers --------------------------------------------------
    def _h1(self, text):
        self._chapter += 1
        numbered = f"{self._chapter}. {text}"
        heading = Paragraph(_greek(numbered), self.s["h1"])
        heading._sector_bookmark = f"sector-section-{self._chapter}"
        heading._sector_outline = numbered
        self.flow.append(heading)

    def _h2(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["h2"]))

    def _p(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["body"]))

    def _small(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["small"]))

    def _status_block(self, text, status):
        """Add a prominent, print-readable assessment banner."""
        palette = {
            "PASS": ("#E8F5E9", "#1B5E20"),
            "OK": ("#E8F5E9", "#1B5E20"),
            "FAIL": ("#FDECEC", "#9B1C1C"),
            "EXCEEDED": ("#FDECEC", "#9B1C1C"),
            "INVALID": ("#FDECEC", "#9B1C1C"),
            "REVIEW": ("#FFF4D6", "#7A4E00"),
            "NOT ASSESSED": ("#FFF4D6", "#7A4E00"),
            "NOT APPLICABLE": ("#EEF2F6", "#374151"),
        }
        bg, fg = palette.get(status, palette["NOT APPLICABLE"])
        style = ParagraphStyle(
            "status", parent=self.s["body"], fontName=_FONT_BOLD,
            textColor=colors.HexColor(fg), leading=13,
        )
        table = Table([[Paragraph(_greek(text), style)]],
                      colWidths=[160 * mm], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(fg)),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        self.flow.append(KeepTogether(table))
        self._gap(4)

    def _case_line(self, family):
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
            self._small(
                "Tension-face selection: V<sub>x,Ed</sub> = "
                f"{_html_escape(actions.get('vx_face', 'auto'))}; "
                "V<sub>y,Ed</sub> = "
                f"{_html_escape(actions.get('vy_face', 'auto'))}."
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
                "<b>Acceptance:</b> stress limits "
                f"{'on' if actions.get('check_stress') else 'off'}; crack width "
                f"{'on' if actions.get('check_crack_width') else 'off'}."
            )

    def _case_heading(self, title, family):
        start = len(self.flow)
        case_id = presentation.action_set(self.inp, family)["id"] or "ID NOT SET"
        self._h1(f"{title} - {_html_escape(case_id)}")
        self._case_line(family)
        self._keep_from(start + 1)

    def _results_overview(self):
        rows = presentation.multi_case_summary_rows(
            self._base_inp, self._base_out
        )
        governing = presentation.summary_governing_case_flags(rows)
        overall = presentation.overall_summary_status(rows)
        self._h2(f"Results overview - {overall}")
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
        table = Table(
            formatted,
            colWidths=[42 * mm, 25 * mm, 23 * mm, 31 * mm, 36 * mm, 13 * mm],
            repeatRows=1,
            hAlign="LEFT",
        )
        style = [
            ("GRID", (0, 0), (-1, -1), 0.4, _LINE),
            ("BACKGROUND", (0, 0), (-1, 0), _HEAD_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        fills = {
            "PASS": colors.HexColor("#E8F5E9"),
            "FAIL": colors.HexColor("#FDECEC"),
            "INVALID": colors.HexColor("#FDECEC"),
            "REVIEW": colors.HexColor("#FFF4D6"),
            "NOT ASSESSED": colors.HexColor("#FFF4D6"),
            "NOT RUN": colors.HexColor("#EEF2F6"),
            "NOT APPLICABLE": colors.HexColor("#EEF2F6"),
        }
        for row_index, row in enumerate(rows, start=1):
            fill = fills.get(row["status"])
            if fill is not None:
                style.append(("BACKGROUND", (2, row_index), (2, row_index), fill))
        table.setStyle(TableStyle(style))
        self.flow.append(table)
        self._small(
            "Gov. marks the highest PASS/FAIL utilisation for each check; ties "
            "remain marked. NOT APPLICABLE means the row action is zero."
        )
        self._gap(4)

    def _gap(self, h=4):
        self.flow.append(Spacer(1, h))

    def _keep_from(self, start):
        """Keep the flowables added since ``start`` together when they fit a page."""
        block = []
        for item in self.flow[start:]:
            # _table() already protects a short table with KeepTogether. Nesting
            # that wrapper makes ReportLab measure the inner block as effectively
            # page-height, which forces every following semantic group onto a new
            # page. The outer group provides the protection here, so flatten it.
            if isinstance(item, KeepTogether):
                block.extend(item._content)
            else:
                block.append(item)
        self.flow[start:] = [KeepTogether(block)]

    def _formula(self, expr, ref=None, subst=None, result=None):
        self.flow.append(Paragraph(_greek(expr), self.s["formula"]))
        if subst:
            self.flow.append(Paragraph(_greek(subst), self.s["formula"]))
        if result:
            self.flow.append(Paragraph(_greek(f"<b>{result}</b>"), self.s["formula"]))
        if ref:
            self.flow.append(Paragraph(_greek(ref), self.s["ref"]))

    def _table(self, data, widths, header=True, font=8.5, keep=True):
        body = ParagraphStyle("c", parent=self.s["body"], fontSize=font,
                              fontName=_FONT, leading=font + 2)
        head = ParagraphStyle("ch", parent=body, fontName=_FONT_BOLD)
        rows = []
        for r, row in enumerate(data):
            cells = []
            for ci, cell in enumerate(row):
                st = head if (header and r == 0) else body
                st = ParagraphStyle("x", parent=st,
                                    alignment=TA_LEFT if ci == 0 else TA_CENTER)
                cells.append(Paragraph(_greek(str(cell)), st))
            rows.append(cells)
        # A long table (the sweep / per-bar tables) may split across pages; a short
        # one is kept whole so it never strands a row on an otherwise empty page.
        # Any table can outgrow one page when it contains user-pasted geometry or
        # reinforcement. Repeat the labelled header regardless of whether the normal
        # short-table path first tries to keep the table together.
        t = Table(
            rows,
            colWidths=widths,
            hAlign="LEFT",
            repeatRows=1 if header else 0,
        )
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, _LINE),
            ("BACKGROUND", (0, 0), (-1, 0), _HEAD_BG if header else colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        self.flow.append(KeepTogether(t) if keep else t)
        self._gap(4)

    def _fig(self, fig, w_mm=150, h_mm=95):
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
        self.flow.append(Image(io.BytesIO(png), width=w_mm * mm, height=h_mm * mm))
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
        jobs = []
        for case_inp, case_out in self._case_contexts("plastic"):
            case_id = presentation.action_set(case_inp, "plastic")["id"] or "-"
            for key, label, method in (
                ("plastic", "Plastic capacity", "_plastic"),
                ("shear", "Shear resistance", "_shear"),
                ("torsion", "Torsion resistance", "_torsion"),
                ("combined", "Combined M-V-T", "_combined"),
            ):
                if key not in case_out:
                    continue
                if key == "combined" and not case_out[key].get("valid"):
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
                    self.flow.append(PageBreak())
                getattr(self, method)()
        finally:
            self.inp, self.out = self._base_inp, self._base_out
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
                ["Project no.", m.get("proj_no", "")],
                ["Project name", m.get("proj_name", "")],
                ["Section", m.get("section", "")],
                ["Revision", m.get("rev", "")],
                ["Author", m.get("author", "")],
                ["Checker", m.get("checker", "")],
                ["Approver", m.get("approver", "")],
                ["Date", date],
                ["Tool version", self.version or "-"],
                ["Source revision", short_revision(m.get("source_revision"))]]
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
        ):
            count = len(self._result_values(key))
            if count:
                labels.append(f"{label} ({count} case{'s' if count != 1 else ''})")
        if any(result.get("valid") for result in self._result_values("combined")):
            labels.append("combined M-V-T")
        ran = ", ".join(labels) or "none"
        self._small(f"Analysis mode: {mode}. Result sections included: {ran}.")
        basis = self.inp.get("design_basis") or {}
        if basis:
            status = str(basis.get("status", "Design basis not identified"))
            qualifier = "<b>Design basis:</b> " + status
            if basis.get("mixed") or basis.get("limitations"):
                qualifier = "<b>Design basis qualification:</b> " + status
            self._p(qualifier)
            for limitation in basis.get("limitations", []):
                self._small("<b>Scope limitation:</b> " + str(limitation))
        self._results_overview()
        self.flow.append(PageBreak())

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
        # Loads & settings.
        start = len(self.flow)
        self._h2("Loads")
        self._loads_block()
        self._h2("Analysis settings")
        self._settings_block()
        self._keep_from(start)

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
                        "fatigue_detail_id": "", "group_id": "",
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
            assignments = [["ID", "Material ID", "Fatigue detail ID", "Group ID"]]
            assignments.extend([
                [record.get("id", "-"), record.get("material_id", "-"),
                 record.get("fatigue_detail_id") or "-", record.get("group_id") or "-"]
                for record in records
            ])
            self._table(assignments, [24 * mm, 42 * mm, 52 * mm, 42 * mm],
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
                ref="DS/EN 1992-1-1 &#167;3.1.6, Eq (3.15)",
                subst=f"= {_fmt(c.alpha_cc,3)} &#183; {_fmt(c.fck, 3)} / "
                      f"{_fmt(c.gamma_c, 3)}",
                result=f"= {_fmt(c.fcd, 3)} MPa")
        if c.curve == 2:
            self._formula(
                "sigma<sub>c</sub> = f<sub>cd</sub> &#183; [1 - (1 - eps<sub>c</sub>/"
                "eps<sub>c2</sub>)<super>n</super>],  for eps<sub>c</sub> &lt;= eps<sub>c2</sub>; "
                "then f<sub>cd</sub> up to eps<sub>cu2</sub>",
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
            uses = []
            count = sum(element.get("material_id") == material_id
                        for element in self.inp.get("bar_elements", []))
            if count:
                uses.append(f"{count} bar{'s' if count != 1 else ''}")
            if material_id == self.inp.get("capacity_steel_material_id"):
                uses.append("member-check reference")
            summary.append([
                material_id, _html_escape(item.get("name", "")),
                _html_escape(item.get("preset", "-")), ", ".join(uses) or "-",
            ])
        self._table(summary, [18 * mm, 42 * mm, 66 * mm, 40 * mm],
                    font=7.0, keep=False)
        self._small("Partial factors are the final effective user inputs; Sector "
                    "applies no hidden control-, construction- or consequence-"
                    "category multiplier.")
        for material_index, item in enumerate(records):
            if self.figures and material_index:
                self.flow.append(PageBreak())
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
                    font=7.0, keep=False)
        for material_index, item in enumerate(records):
            if self.figures and material_index:
                self.flow.append(PageBreak())
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
                    "T<sub>Ed</sub>", "Faces",
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
                    ]
                    for row in plastic
                ])
                self._table(
                    rows,
                    [15 * mm, 28 * mm] + [17 * mm] * 6 + [25 * mm],
                    font=6.1,
                    keep=False,
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
                    "Stress", "Crack",
                ]]
                for row in elastic:
                    common = [
                        _html_escape(row["name"]),
                        _html_escape(row["description"]),
                    ]
                    flags = [
                        "yes" if row["check_stress"] else "no",
                        "yes" if row["check_crack_width"] else "no",
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
                )
                self._small("N in kN; M in kNm. Stress and crack acceptance are "
                            "selected per case; their limits are global.")
            if not plastic and not elastic:
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
            rows.append([label, _fmt(inp.get("P_pl"), 3), mx, my])
        if "elastic" in out:
            case = _html_escape(
                presentation.action_set(inp, "elastic")["id"] or "-"
            )
            rows.append([f"{case} - long-term", _fmt(inp.get("P_el_l"), 3),
                         _fmt(inp.get("Mx_el_l"), 3), _fmt(inp.get("My_el_l"), 3)])
            rows.append([f"{case} - short-term", _fmt(inp.get("P_el_s"), 3),
                         _fmt(inp.get("Mx_el_s"), 3), _fmt(inp.get("My_el_s"), 3)])
        self._table(rows, [55 * mm, 35 * mm, 38 * mm, 38 * mm])

    def _settings_block(self):
        # Every input that influences the reported results is documented here so the
        # report is self-contained and QA-able.
        inp = self.inp
        rows = [["Setting", "Value"]]
        rows.append(["Analysis mode", str(inp.get("mode", "-"))])
        basis = inp.get("design_basis") or {}
        if basis:
            rows.append(["Design-basis status", str(basis.get("status", "-"))])
            for component in basis.get("components", []):
                rows.append([
                    "Design basis - " + str(component.get("role", "")),
                    str(component.get("selection", "-")),
                ])
            for limitation in basis.get("limitations", []):
                rows.append(["Scope limitation", str(limitation)])
        if self._result_values("shear") or self._result_values("torsion"):
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
        plastic_results = self._result_values("plastic")
        if plastic_results:
            rows.append(["Sweep start V.min", f"{_fmt(inp.get('v_min'),0)} deg"])
            rows.append(["Sweep end V.max", f"{_fmt(inp.get('v_max'),0)} deg"])
            rows.append(["Sweep increment V.inc", f"max {_fmt(inp.get('v_inc'),0)} deg"])
            checked = plastic_results[0].get("check_util", True)
            rows.append(["Utilisation check",
                         "applied moment checked" if checked else "capacity only"])
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
            rows.append(["Concrete compression criterion",
                         f"{_fmt(inp.get('sls_conc_limit_pct'), 1)} % f<sub>ck</sub>"
                         if inp.get("sls_conc_limit_pct") else "not assessed"])
            rows.append(["Reinforcement tension criterion",
                         f"{_fmt(inp.get('sls_steel_limit_pct'), 1)} % f<sub>yk</sub>"
                         if inp.get("sls_steel_limit_pct") else "not assessed"])
            if inp.get("tendons"):
                rows.append(["Tendon tension criterion",
                             f"{_fmt(inp.get('sls_pre_limit_pct'), 1)} % f<sub>pk</sub>"
                             if inp.get("sls_pre_limit_pct") else "not assessed"])
            rows.append(["Acceptance-criteria source",
                         str(inp.get("sls_limit_source") or "not stated")])
            crack_results = [item for item in elastic_results if item.get("show_cw")]
            rows.append(["Crack width checked",
                         "yes" if crack_results else "no"])
            if crack_results:
                crack_el = crack_results[0]
                rows.append(["Crack-width code", str(crack_el.get("crack_code", "-"))])
                rows.append(["Crack-width criterion",
                             f"{_fmt(inp.get('sls_wk_limit'), 3)} mm"
                             if inp.get("sls_wk_limit") else "not assessed"])
                if crack_el.get("crack_member"):
                    rows.append(["Member type", str(crack_el["crack_member"])])
                dia = inp.get("sls_phi") or 0.0
                rows.append(["Crack-width element diameter",
                             ("per-element table values" if not dia
                              else f"{_fmt(dia, 3)} mm global override")])
                rows.append(["Mild-steel bond coefficient k<sub>1</sub>",
                             _fmt(inp.get("sls_k1"), 3)])
        self._table(rows, [110 * mm, 55 * mm])

    def _theory(self):
        self._h1("Basis of analysis")
        plastic_results = self._result_values("plastic")
        elastic_results = self._result_values("elastic")
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
                           ref=f"Concrete: {concrete_ref}; reinforcement: {steel_ref}")
            self._small("Each bar and tendon uses its assigned material law and "
                        "strain limit in the element-wise minima.")
            self._p("The compression depth c is solved from axial equilibrium and "
                    "the moments follow from the force resultants:")
            self._formula("F<sub>c</sub> + F<sub>s</sub> + F<sub>p</sub> = N ;   "
                          "M = sum( F<sub>i</sub> &#183; d<sub>i</sub> )")
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
        if not plastic_results and not elastic_results:
            self._p("No bending-capacity or elastic-stress result was included in "
                    "this report.")

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
            if assessment["margin"] is not None:
                rows.append(["Margin to 100 % limit (pp)",
                             f"{assessment['margin'] * 100:+.1f}"])
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
        self._small("NA angle in deg; M in kNm; NA x/y, lever L, d<sub>x</sub> "
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
        self._p(f"Neutral-axis angle = {_fmt(gov['V'],0)} deg. The extreme "
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
                tendon_colors=tendon_colors, zones=zones, show_labels=True,
                scale=_MM, unit="mm",
                bar_ids=[item.get("id") for item in inp.get("bar_elements", [])],
                tendon_ids=[item.get("id") for item in inp.get("tendon_elements", [])],
                title=f"Plastic state at NA angle = {_fmt(gov['V'],0)} deg "
                      "(tension + / compression -)"), 150, 100)
            self._small(
                "Blue/plain markers are tension (+); vermillion/x markers are "
                "compression (-). Bar circles and tendon diamonds identify the "
                "element type. Status is therefore not communicated by colour alone."
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
                ref="EN 1992-1-1:2023 Formula (8.30)",
                subst=f"max(|{_fmt(sh.get('m_ed_2023'), 3)}| / "
                      f"{_fmt(sh.get('v_ed'), 3)} &#183; 1000, {_fmt(sh['d'], 1)})",
                result=f"a<sub>cs</sub> = {_fmt(res.get('a_cs'), 1)} mm")
            self._formula(
                "k<sub>vp</sub> = max(1 + N<sub>Ed</sub>/|V<sub>Ed</sub>| &#183; "
                "d/(3a<sub>cs</sub>), 0.1)",
                ref="EN 1992-1-1:2023 &#167;8.2.2(4), Formula (8.31)",
                subst=f"N<sub>Ed</sub> = {_fmt(res.get('n_ed_tension'), 3)} kN; "
                      f"k<sub>vp</sub> = {_fmt(res.get('k_vp'), 4)}",
                result=f"k<sub>vp</sub>d = {_fmt(res.get('d_kvp'), 1)} mm")
        self._formula(
            "tau<sub>Rd,c</sub> = (0.66/gamma<sub>v</sub>)(100 rho<sub>l</sub> "
            "f<sub>ck</sub> d<sub>dg</sub>/(k<sub>vp</sub>d))<sup>1/3</sup>",
            ref="EN 1992-1-1:2023 (8.27), stress",
            subst=f"(0.66/{_fmt(res['gamma_v'], 2)})(100 &#183; "
                  f"{_fmt(res['rho_l'], 4)} &#183; {_fmt(fck, 0)} &#183; "
                  f"{_fmt(res['ddg'], 1)}/{_fmt(res.get('d_kvp'), 1)})"
                  "<sup>1/3</sup>",
            result=f"tau = {_fmt(res['tau_basic'], 3)} MPa")
        self._formula(
            "tau<sub>Rd,c,min</sub> = (11/gamma<sub>v</sub>) "
            "sqrt(f<sub>ck</sub>/f<sub>yd</sub> &#183; d<sub>dg</sub>/d)",
            ref="EN 1992-1-1:2023 (8.20)",
            subst=f"(11/{_fmt(res['gamma_v'], 2)}) sqrt({_fmt(fck, 0)}/"
                  f"{_fmt(res['fyd'], 1)} &#183; {_fmt(res['ddg'], 1)}/"
                  f"{_fmt(sh['d'], 1)})",
            result=f"tau<sub>min</sub> = {_fmt(res['tau_min'], 3)} MPa")
        self._formula(
            "V<sub>Rd,c</sub> = max(tau<sub>Rd,c</sub>, tau<sub>Rd,c,min</sub>) "
            "b<sub>w</sub> z",
            subst=f"max({_fmt(res['tau_rdc'], 3)}, {_fmt(res['tau_min'], 3)}) &#183; "
                  f"{_fmt(sh['bw'], 1)} &#183; {_fmt(res['z'], 1)} / 1000",
            result=f"V<sub>Rd,c</sub> = {_fmt(res['vrd_c'], 3)} kN")
        util = sh["util"]
        util_txt = _pct(util)
        verdict = "OK" if viz.util_ok(util) else "EXCEEDED"
        self._h2("Utilisation")
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd,c</sub>",
                      subst=f"{_fmt(sh['v_ed'], 3)} / {_fmt(res['vrd_c'], 3)}",
                      result=f"{util_txt}  ({verdict})")
        self._small(
            "The 2023 tau<sub>Rd,c</sub> uses d<sub>dg</sub> = 16 + "
            "D<sub>lower</sub>, the flexural design yield and the Formula (8.31) "
            "axial-force modification. N<sub>Ed</sub> and M<sub>Ed</sub> include "
            "the locked-in tendon prestress effects in accordance with 8.2.1(8). "
            "Tendons are assumed parallel to the member axis "
            "(cos beta = 1). "
            "The with-links method (8.2.3) is not implemented."
        )

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
            self._status_block(
                f"{aggregate.get('status', 'REVIEW')} - independent Vx/Vy checks",
                aggregate.get("status", "REVIEW"),
            )
            self._small(
                "Biaxial interaction: <b>NOT ASSESSED</b>. Sector performs two "
                "directional checks and does not apply a resultant or an undocumented "
                "interaction expression. If both directions pass, the overall shear "
                "status remains REVIEW."
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
                          "Shear status", "Combined status", "Governing"]]
            for candidate in sh.get("face_candidates", []):
                candidate_shear = candidate.get("shear") or {}
                face_rows.append([
                    viz.tension_face_label(
                        candidate.get("tension_low", True), sh["axis"]
                    ),
                    f"{_fmt((candidate_shear.get('res') or {}).get('vrd_c'), 3)} kN",
                    _pct(candidate_shear.get("util")),
                    candidate.get("shear_status", "NOT ASSESSED"),
                    candidate.get("combined_status", "NOT RUN"),
                    ("Yes" if bool(candidate.get("tension_low"))
                     == bool(sh.get("tension_low")) else ""),
                ])
            self._small(
                "The associated bending moment is effectively zero; both faces are "
                "evaluated and the governing candidate is used."
            )
            self._table(
                face_rows,
                [38 * mm, 25 * mm, 34 * mm, 27 * mm, 25 * mm, 21 * mm],
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
            ref="EN 1992-1-1 (6.2.a), stress",
            subst=f"{_fmt(res['crd_c'], 4)} &#183; {_fmt(res['k'], 3)} &#183; (100 "
                  f"&#183; {_fmt(res['rho_l'], 4)} &#183; {_fmt(fck, 0)})<sup>1/3</sup> "
                  f"+ {_fmt(k1, 2)} &#183; {_fmt(res['sigma_cp'], 3)}",
            result=f"v = {_fmt(res['v_basic'], 3)} MPa")
        self._formula(
            "v<sub>min,eff</sub> = v<sub>min</sub> + k<sub>1</sub> sigma<sub>cp</sub>",
            ref="EN 1992-1-1 (6.2.b), lower-bound stress",
            subst=f"{_fmt(res['vmin'], 3)} + {_fmt(k1, 2)} &#183; "
                  f"{_fmt(res['sigma_cp'], 3)}",
            result=f"v<sub>min,eff</sub> = {_fmt(res['v_floor'], 3)} MPa")
        self._formula(
            "V<sub>Rd,c</sub> = max(v, v<sub>min,eff</sub>) &#183; b<sub>w</sub> "
            "&#183; d",
            subst=f"max({_fmt(res['v_basic'], 3)}, {_fmt(res['v_floor'], 3)}) &#183; "
                  f"{_fmt(sh['bw'], 1)} &#183; {_fmt(sh['d'], 1)} / 1000",
            result=f"V<sub>Rd,c</sub> = {_fmt(res['vrd_c'], 3)} kN")
        util = sh["util"]
        util_txt = _pct(util)
        verdict = "OK" if viz.util_ok(util) else "EXCEEDED"
        self._h2("Utilisation")
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd,c</sub>",
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
        req = ("required (V<sub>Ed</sub> &gt; V<sub>Rd,c</sub>)" if links["required"]
               else "not strictly required (V<sub>Ed</sub> &#8804; V<sub>Rd,c</sub>); "
                    "minimum reinforcement rules still apply")
        self._p(f"With vertical links the resistance is the variable-strut "
                f"V<sub>Rd</sub> = min(V<sub>Rd,s</sub>, V<sub>Rd,max</sub>) "
                f"(EN 1992-1-1 sec. 6.2.3). For this V<sub>Ed</sub>, links are {req}.")
        if not lk["valid"]:
            self._small("Warning: the link resistance is zero -- check the leg count, "
                        "diameter and spacing (A<sub>sw</sub>/s must be &gt; 0).")
            return
        if links["out_of_limits"]:
            self._small(f"Warning: the strut bounds cot theta in "
                        f"[{_fmt(links['cot_min'], 2)}, {_fmt(links['cot_max'], 2)}] "
                        f"fall outside the code range "
                        f"[{_fmt(links['cot_limit_lo'], 1)}, "
                        f"{_fmt(links['cot_limit_hi'], 1)}] (6.7N / 6.7a NA). "
                        "The values below are exploratory; no compliance verdict "
                        "applies to the links or dependent interaction checks.")
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
                 f"{_fmt(lk['theta_deg'], 1)} deg (cot theta = {_fmt(lk['cot'], 3)})"],
                ["Strut factor", "nu<sub>1</sub>", f"{_fmt(lk['nu1'], 3)}"],
                ["Chord factor", "alpha<sub>cw</sub>", f"{_fmt(lk['alpha_cw'], 3)}"]]
        self._table(rows, [55 * mm, 25 * mm, 70 * mm])
        self._fig(viz.truss_figure(lk["theta_deg"], lk["z"], links["legs"],
                                   links["dia"], links["s"]), 130, 80)
        self._formula(
            "V<sub>Rd,s</sub> = (A<sub>sw</sub>/s) z f<sub>ywd</sub> cot theta",
            ref="EN 1992-1-1 (6.8)",
            subst=f"{_fmt(links['asw_over_s'], 4)} &#183; {_fmt(lk['z'], 1)} &#183; "
                  f"{_fmt(lk['fywd'], 1)} &#183; {_fmt(lk['cot'], 3)} / 1000",
            result=f"V<sub>Rd,s</sub> = {_fmt(lk['vrd_s'], 3)} kN")
        self._formula(
            "V<sub>Rd,max</sub> = alpha<sub>cw</sub> b<sub>w</sub> z nu<sub>1</sub> "
            "f<sub>cd</sub> / (cot theta + tan theta)",
            ref="EN 1992-1-1 (6.9)",
            subst=f"{_fmt(lk['alpha_cw'], 3)} &#183; {_fmt(sh['bw'], 1)} &#183; "
                  f"{_fmt(lk['z'], 1)} &#183; {_fmt(lk['nu1'], 3)} &#183; "
                  f"{_fmt(lk['fcd'], 2)} / ({_fmt(lk['cot'], 3)} + "
                  f"{_fmt(1.0 / lk['cot'], 3)}) / 1000",
            result=f"V<sub>Rd,max</sub> = {_fmt(lk['vrd_max'], 3)} kN")
        self._formula(
            "V<sub>Rd</sub> = min(V<sub>Rd,s</sub>, V<sub>Rd,max</sub>)",
            result=f"V<sub>Rd</sub> = {_fmt(lk['vrd'], 3)} kN "
                   f"(governed by {lk['governs']})")
        util = links["util"]
        util_txt = _pct(util)
        verdict = _code_verdict(
            viz.util_ok(util), links.get("code_applicable", True)
        )
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd</sub>",
                      subst=f"{_fmt(sh['v_ed'], 3)} / {_fmt(lk['vrd'], 3)}",
                      result=f"{util_txt}  ({verdict})")
        if links.get("theta_mode") == "utilisation":
            angle_note = ("The strut angle is the ONE member angle (shared with "
                          "torsion when enabled, EN 1992-1-1 6.3.2(2)), selected "
                          "within the bounds to MINIMISE THE GOVERNING UTILISATION: a "
                          "flatter strut relaxes the stirrups but raises the crushing "
                          "demand and the longitudinal chord tension, so the angle "
                          "depends on V<sub>Ed</sub>, M<sub>Ed</sub> and N<sub>Ed</sub>.")
        else:
            angle_note = ("The strut angle is auto-optimised within the bounds to "
                          "maximise V<sub>Rd</sub>.")
        self._small(angle_note + " The shear adds a longitudinal tension "
                    "&#916;F<sub>td</sub> = 0.5 V<sub>Ed</sub> cot theta = "
                    f"{_fmt(links['delta_ftd'], 1)} kN (6.18) that the tension "
                    "reinforcement must also carry.")
        # Longitudinal chord under M + V (+ T), at the member strut angle -- the
        # same check the combined section shows; printed here so a shear + bending
        # run without torsion still documents it.
        ch = links.get("chord")
        if ch is not None and ch.get("valid"):
            self._h2("Longitudinal chord: bending + shear"
                     + (" + torsion" if ch.get("has_torsion") else "") + " tension")
            vv = _code_verdict(ch["ok"], ch.get("code_applicable", True))
            face = viz.tension_face_label(
                ch.get("tension_low", True), ch.get("axis")
            )
            self._formula(
                "M<sub>Ed,total</sub> = M<sub>Ed</sub> + &#916;F<sub>td</sub>"
                "&#183;z + F<sub>td,T</sub>&#183;z/2",
                ref="EN 1992-1-1 6.2.3(7) + 6.3.2",
                subst=f"{_fmt(ch['m_ed'], 1)} + {_fmt(ch['mv'], 1)} + "
                      f"{_fmt(ch['mt'], 1)} kNm  (z = {_fmt(ch['z'], 3)} m)",
                result=f"M<sub>Ed,total</sub> = {_fmt(ch['m_total'], 1)} kNm")
            fell_back = ch.get("biaxial") and not ch.get("conditional", True)
            self._formula(
                "M<sub>Ed,total</sub> / M<sub>Rd</sub>",
                subst=f"{_fmt(ch['m_total'], 1)} / {_fmt(ch['m_rd'], 1)}",
                result=(f"utilisation = {_pct(ch['util'])}"
                        + ("  (pure-axis fallback -- see note)" if fell_back
                           else f"  ({vv})")))
            face_desc = (f"the shear tension face ({face})" if ch.get("gets_shift", True)
                         else f"the shear compression face ({face}) -- the torsion "
                         "tension governs there, with no shear shift and the bending "
                         "relieving rather than adding")
            note = (f"Tension chord = {face_desc}; M<sub>Rd</sub> "
                    + viz.chord_mrd_label(ch["axis"], ch.get("m_off", 0.0),
                                          ch.get("conditional", True)) + ".")
            if ch.get("theta_mode") == "utilisation":
                note += (" This capped demand is part of the strut-angle objective, "
                         "so theta backs off the band edge when the chord would "
                         "otherwise govern.")
            if fell_back:
                note += (" Biaxial bending is acting but the conditional capacity "
                         "solve did not converge, so M<sub>Rd</sub> is the pure-axis "
                         "fallback and this check can be optimistic -- rely on the "
                         "combined sum(SEd/SRd).")
            elif ch.get("off_not_evaluated") == "subdivided":
                note += (" Compound (subdivided) section: the torsion longitudinal "
                         "steel is per sub-tube, so the off-axis chord's torsion "
                         "share is not evaluated here -- rely on the combined "
                         "sum(SEd/SRd).")
            elif ch.get("off_not_evaluated") == "not_solved":
                note += (" One or more chord faces carrying the torsion share could "
                         "not be evaluated (a conditional solve failed or a face has "
                         "no tension steel), so they are not checked and the governing "
                         "chord shown may not be the critical face -- rely on the "
                         "combined sum(SEd/SRd).")
            self._small(note)
            self._chord_off_block(links.get("chord_off"))

    def _combined(self):
        aggregate = self.out["combined"]
        directions = aggregate.get("directions") or {}
        if not aggregate.get("biaxial") or not directions:
            self._combined_direction(aggregate)
            return

        self._case_heading(
            "Combined bending + directional shear + torsion", "plastic"
        )
        self._status_block(
            f"{aggregate.get('status', 'REVIEW')} - Vx+T and Vy+T screens",
            aggregate.get("status", "REVIEW"),
        )
        self._small(
            "The simultaneous V<sub>x,Ed</sub> + V<sub>y,Ed</sub> + "
            "T<sub>Ed</sub> interaction is <b>NOT ASSESSED</b>. The following "
            "directional screens are independent; no three-component interaction "
            "expression is inferred."
        )
        rows = [["Screen", "r<sub>M</sub>", "r<sub>V</sub>",
                 "r<sub>T</sub>", "DK NA sum", "Status"]]
        for component in ("vx", "vy"):
            item = directions.get(component)
            if not item:
                continue
            rows.append([
                "Vx+T" if component == "vx" else "Vy+T",
                _pct(item.get("r_m")), _pct(item.get("r_v")),
                _pct(item.get("r_t")), _pct(item.get("dkna_sum")),
                item.get("status", (
                    "NOT ASSESSED" if not item.get("valid")
                    else "PASS" if item.get("dkna_ok") else "FAIL"
                )),
            ])
        self._table(rows, [27 * mm, 25 * mm, 25 * mm, 25 * mm, 32 * mm, 35 * mm])
        for component in ("vx", "vy"):
            if component in directions:
                label = "V<sub>x,Ed</sub> + T<sub>Ed</sub>" if component == "vx" \
                    else "V<sub>y,Ed</sub> + T<sub>Ed</sub>"
                self._h2(f"Directional screen: {label}")
                self._combined_direction(
                    directions[component], include_case_heading=False,
                    component=component,
                )

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
        self._p("The three checks tied together under the shared edition <b>"
                + str(c["method"]) + "</b>. The bending utilisation is the plastic "
                "M-M envelope at the applied N; the shear and torsion utilisations "
                "are the stand-alone checks.")
        rows = [["Action", "Utilisation"],
                ["Bending M", _pct(c["r_m"])],
                ["Shear V", _pct(c["r_v"])],
                ["Torsion T", _pct(c["r_t"])]]
        self._table(rows, [90 * mm, 60 * mm])
        self._h2("DK NA 6.3.2(6): sum(SEd/SRd) &#8804; 1")
        applicable = c.get("code_applicable", True)
        if not applicable:
            self._small("Warning: one or more active strut-angle bounds fall outside "
                        "the method's code range. The combined values are exploratory "
                        "and carry no compliance verdict.")
        verdict = _code_verdict(c["dkna_ok"], applicable)
        if c["m_v_independent"]:
            expr = "max(r<sub>M</sub> + r<sub>T</sub>, r<sub>V</sub> + r<sub>T</sub>)"
            note = ("M and V checked separately (shear longitudinal steel provided); "
                    "N is folded into the bending utilisation.")
        else:
            expr = "r<sub>M</sub> + r<sub>V</sub> + r<sub>T</sub>"
            note = "each action alone; N folded into the bending utilisation."
        self._formula(expr, subst=note,
                      result=f"sum(SEd/SRd) = {_pct(c['dkna_sum'])}  ({verdict})")
        cr = c.get("crushing")
        if cr is not None and cr.get("valid"):
            self._h2("Concrete crushing (6.29)")
            val = cr["value"]
            vv = _code_verdict(
                viz.util_ok(val), cr.get("code_applicable", applicable)
            )
            self._formula(
                "T<sub>Ed</sub>/T<sub>Rd,max</sub> + V<sub>Ed</sub>/V<sub>Rd,max</sub>",
                ref="EN 1992-1-1 (6.29)",
                subst=f"{_fmt(cr['t_ed'], 3)}/{_fmt(cr['trd_max'], 3)} + "
                      f"{_fmt(cr['v_ed'], 3)}/{_fmt(cr['vrd_max'], 3)}",
                result=f"{_pct(val)}  ({vv})")
            self._small(f"At a common strut cot theta = {_fmt(cr['cot'], 2)} "
                        f"({_fmt(cr['theta_deg'], 1)} deg).")
            self._fig(viz.vt_interaction_figure(cr["vrd_max"], cr["trd_max"],
                                                cr["v_ed"], cr["t_ed"],
                                                show_verdict=cr.get(
                                                    "code_applicable", applicable)),
                      120, 100)
        elif cr is not None and not cr.get("valid"):
            self._h2("Concrete crushing (6.29)")
            self._small("Not evaluated: the shear and torsion cot theta bands do not "
                        "overlap, so no single strut angle satisfies both.")
        tr = c.get("transverse")
        if tr is not None and not tr.get("valid"):
            self._h2("Shared stirrup (shear + torsion transverse steel)")
            self._small("Not evaluated: the shear and torsion cot theta bands do not "
                        "overlap, so no single strut angle satisfies both.")
        elif tr is not None:
            self._h2("Shared stirrup (shear + torsion transverse steel)")
            vv = _code_verdict(tr["ok"], applicable)
            if tr["shear_credited"]:
                note = (f"V<sub>Ed</sub> = {_fmt(tr['v_ed'], 1)} &#8804; V<sub>Rd,c</sub>"
                        f" = {_fmt(tr['vrd_c'], 1)} kN, so the concrete carries the "
                        "shear (6.2.1) and the whole closed stirrup serves torsion.")
            else:
                note = ("V<sub>Ed</sub> &gt; V<sub>Rd,c</sub>: shear and torsion "
                        "demands add on the shared closed stirrup.")
            self._formula(
                "shear share + torsion share (shared closed stirrup)",
                subst=f"{_pct(tr['shear_fraction'])} + {_pct(tr['torsion_fraction'])}",
                result=f"stirrup utilisation = {_pct(tr['u_stirrup'])}")
            self._formula(
                "crushing utilisation (both actions, one strut)",
                result=f"crushing utilisation = {_pct(tr['u_crush'])}")
            self._p(f"Governing ({tr['governs']}): {_pct(tr['governing'])}  ({vv})")
            self._small(note + f" At the member strut angle cot theta = "
                        f"{_fmt(tr['cot'], 2)} ({_fmt(tr['theta_deg'], 1)} deg) -- "
                        "the one angle shared by every shear and torsion check "
                        "(6.3.2(2)), selected to minimise the governing utilisation.")
        lg = c.get("longitudinal")
        if lg is not None and lg["valid"]:
            self._h2("Longitudinal reinforcement: combined M + V + T tension chord")
            vv = _code_verdict(lg["ok"], applicable)
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
                ref="EN 1992-1-1 6.2.3(7) + 6.3.2",
                subst=f"{_fmt(lg['m_ed'], 1)} + {_fmt(lg['mv'], 1)} + "
                      f"{_fmt(lg['mt'], 1)} kNm  (z = {_fmt(lg['z'], 3)} m, "
                      f"&#916;F<sub>td</sub> = {_fmt(lg['ftd_v'], 1)} kN, "
                      f"F<sub>td,T</sub> = {_fmt(lg['ftd_t'], 1)} kN)",
                result=f"M<sub>Ed,total</sub> = {_fmt(lg['m_total'], 1)} kNm")
            biaxial = lg.get("biaxial", False)
            fell_back = biaxial and not lg.get("conditional", True)
            self._formula(
                "M<sub>Ed,total</sub> / M<sub>Rd</sub>",
                subst=f"{_fmt(lg['m_total'], 1)} / {_fmt(lg['m_rd'], 1)}",
                result=(f"utilisation = {_pct(lg['util'])}"
                        + ("  (pure-axis fallback -- see note)" if fell_back
                           else f"  ({vv})")))
            if fell_back:
                self._p("Biaxial bending: a moment about the OTHER axis is acting ("
                        f"{_pct(lg.get('off_util', 0.0))} of that axis' capacity) but "
                        "the conditional capacity solve did not converge, so "
                        "M<sub>Rd</sub> is the pure-axis fallback and this chord check "
                        "can be optimistic -- rely on the sum(SEd/SRd) check above, "
                        "which uses the full biaxial bending utilisation.")
            note = viz.chord_angle_note(lg.get("theta_mode"))
            if lg.get("off_not_evaluated") == "subdivided":
                note += (" Compound (subdivided) section: the torsion longitudinal "
                         "steel is per sub-tube, so the off-axis chord's torsion "
                         "share is not evaluated; the sum(SEd/SRd) check covers the "
                         "interaction.")
            elif lg.get("off_not_evaluated") == "not_solved":
                note += (" One or more chord faces carrying the torsion share could "
                         "not be evaluated (a conditional solve failed or a face has "
                         "no tension steel), so they are NOT checked and the governing "
                         "chord shown may not be the critical face; the sum(SEd/SRd) "
                         "check above remains the combined verification.")
            elif biaxial and not lg.get("has_torsion"):
                note += (" The off-axis chord carries only its bending tension (no "
                         "torsion is acting), which the biaxial bending utilisation "
                         "in the sum(SEd/SRd) check already covers.")
            elif not biaxial:
                note += (" The sum(SEd/SRd) check above uses the full biaxial bending "
                         "utilisation and remains the primary combined check.")
            if lg["capped"]:
                note = ("The shear shift is capped so bending + shear does not exceed "
                        "M<sub>Rd</sub> (6.2.3(7): the added tension need not exceed "
                        "the peak-moment tension; a section tool uses M<sub>Rd</sub> as "
                        "that cap). ") + note
            self._small(note)
            self._chord_off_block(c.get("chord_off"))
        else:
            self._small(f"Additional longitudinal steel: torsion sum A<sub>sl</sub> = "
                        f"{_fmt(c['asl_torsion'], 0)} mm<sup>2</sup> round the perimeter "
                        f"(6.28); shear &#916;F<sub>td</sub> = {_fmt(c['delta_ftd'], 1)} "
                        "kN on the tension chord (6.18) -- both beyond the bending "
                        "steel. Enable shear links for the full utilisation check.")

    def _chord_off_block(self, och):
        """Off-axis chord check (bending + torsion share), shared by the shear and
        combined sections. Rendered when torsion is live on a single-tube section:
        the chord about the OTHER axis carries its bending tension plus its share
        of the distributed torsion longitudinal force, against the capacity
        conditional on the shear-axis moment."""
        if och is None or not och.get("valid"):
            return
        self._h2(f"Off-axis chord (about {och['axis']}, governing face): "
                 "bending + torsion tension")
        vv = _code_verdict(och["ok"], och.get("code_applicable", True))
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
            ref="EN 1992-1-1 6.3.2",
            subst=f"{_fmt(och['m_ed'], 1)} + {_fmt(och['mt'], 1)} kNm  "
                  f"(z = {_fmt(och['z'], 3)} m, "
                  f"F<sub>td,T</sub> = {_fmt(och['ftd_t'], 1)} kN)",
            result=f"M<sub>Ed,total</sub> = {_fmt(och['m_total'], 1)} kNm")
        self._formula(
            "M<sub>Ed,total</sub> / M<sub>Rd</sub>",
            subst=f"{_fmt(och['m_total'], 1)} / {_fmt(och['m_rd'], 1)}",
            result=f"utilisation = {_pct(och['util'])}  ({vv})")
        self._small(f"z = {_fmt(och['z'], 3)} m ({och.get('z_src') or '0.9 d'}). "
                    "Each chord's capacity is conditional on the OTHER axis' "
                    "bending moment only; the longitudinal steel the two chords "
                    "share also carries both their shear/torsion tensions, an "
                    "interaction the DK NA sum(SEd/SRd) check captures and which "
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
        verdict = _code_verdict(
            viz.util_ok(util), t.get("code_applicable", True)
        )
        g = t.get("governing_sub")
        gov = ("web" if g == 0 else f"part {g + 1}") if g is not None else "-"
        self._formula(
            "governing utilisation = max(T<sub>Ed,i</sub> / T<sub>Rd,i</sub>)",
            ref=f"worst sub-tube: {gov}", result=f"{util_txt}  ({verdict})")
        self._small("The applied torque is split by stiffness, not capacity, so a "
                    "sub-tube can be overstressed even while T<sub>Ed</sub> &#8804; sum "
                    "T<sub>Rd,i</sub> = " + f"{_fmt(t['trd'], 2)}" + " kN.m; the section "
                    "passes only when every sub-tube passes. Total longitudinal steel "
                    "sum A<sub>sl</sub> = " + f"{_fmt(t['asl_req'], 0)}" +
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
            self._small("Not evaluated: the shear and torsion cot theta bands do not "
                        "overlap, so no single strut angle satisfies both.")
            return
        val = inter["value"]
        val_txt = _pct(val)
        verdict_i = _code_verdict(
            viz.util_ok(val), inter.get("code_applicable", True)
        )
        self._formula(
            "T<sub>Ed</sub>/T<sub>Rd,max</sub> + V<sub>Ed</sub>/V<sub>Rd,max</sub>",
            ref="EN 1992-1-1 (6.29)",
            subst=f"{_fmt(inter['t_ed'], 3)}/{_fmt(inter['trd_max'], 3)} + "
                  f"{_fmt(inter['v_ed'], 3)}/{_fmt(inter['vrd_max'], 3)}",
            result=f"{val_txt}  ({verdict_i})")
        self._small("Evaluated at the common strut angle cot theta = "
                    f"{_fmt(inter['cot'], 2)} ({_fmt(inter['theta_deg'], 1)} deg); "
                    "T<sub>Rd,max</sub> and V<sub>Rd,max</sub> here are at that shared "
                    "angle.")
        self._fig(viz.vt_interaction_figure(inter["vrd_max"], inter["trd_max"],
                                            inter["v_ed"], inter["t_ed"],
                                            show_verdict=inter.get(
                                                "code_applicable", True)),
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
            self._status_block(
                "REVIEW - directional shear-torsion screens",
                "REVIEW",
            )
            self._small(
                "V<sub>x,Ed</sub> + V<sub>y,Ed</sub> + T<sub>Ed</sub> "
                "interaction is <b>NOT ASSESSED</b>. Standalone torsion is reported "
                "below; Vx+T and Vy+T are screened separately."
            )
            rows = [["Screen", "T<sub>Ed</sub>/T<sub>Rd</sub>",
                     "6.29 V+T", "Status"]]
            for component in ("vx", "vy"):
                item = directional.get(component)
                if not item:
                    continue
                interaction = item.get("interaction") or {}
                value = interaction.get("value")
                rows.append([
                    "Vx+T" if component == "vx" else "Vy+T",
                    _pct(item.get("util")), _pct(value),
                    item.get("directional_interaction_status") or (
                        presentation.interaction_assessment_status(
                            interaction,
                            applicable=item.get("code_applicable", True),
                        )
                    ),
                ])
            self._table(rows, [42 * mm, 42 * mm, 42 * mm, 42 * mm])
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
                            "resistance or compliance verdict is issued.")
            elif str(t.get("reason") or "").startswith(
                    "invalid sub-tube partition:"):
                detail = (t.get("subdivision_reason")
                          or str(t["reason"]).split(":", 1)[-1].strip())
                self._small(
                    "Torsion not evaluated: the positioned sub-rectangles do not "
                    f"form the concrete section ({detail}). Adjust each centre x/y "
                    "and b/h so their non-overlapping union equals the concrete net "
                    "area and does not enter a void. No torsion or dependent "
                    "interaction compliance verdict is issued."
                )
            else:
                self._small("Warning: the tube could not be formed (a degenerate or "
                            "too-thin section).")
            return
        if t["out_of_limits"]:
            self._small("Warning: the strut bounds cot theta in "
                        f"[{_fmt(t['cot_min'], 2)}, {_fmt(t['cot_max'], 2)}] fall "
                        "outside the code range 1..2.5 (6.7N / 6.7a NA). Values are "
                        "exploratory; no compliance verdict applies to torsion or "
                        "dependent interaction checks.")
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
                 f"{_fmt(t['theta_deg'], 1)} deg (cot theta = {_fmt(t['cot'], 3)})"],
                ["Strut factor", "nu", f"{_fmt(t['nu'], 3)}"],
                ["Chord factor", "alpha<sub>cw</sub>", f"{_fmt(t['alpha_cw'], 3)}"],
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
            ref="from EN 1992-1-1 (6.28)",
            subst=f"{_fmt(t['asw_over_s'], 4)} &#183; 2 &#183; {_fmt(tube['Ak'], 4)} "
                  f"&#183; {_fmt(t['fywd'], 1)} &#183; {_fmt(t['cot'], 3)}",
            result=f"T<sub>Rd,s</sub> = {_fmt(t['trd_s'], 3)} kN.m")
        self._formula(
            "T<sub>Rd,max</sub> = 2 nu alpha<sub>cw</sub> f<sub>cd</sub> "
            "A<sub>k</sub> t<sub>ef</sub> sin theta cos theta",
            ref="EN 1992-1-1 (6.30)",
            subst=f"2 &#183; {_fmt(t['nu'], 3)} &#183; {_fmt(t['alpha_cw'], 3)} &#183; "
                  f"{_fmt(t['fcd'], 2)} &#183; {_fmt(tube['Ak'], 4)} &#183; "
                  f"{_fmt(tube['tef'] / 1000.0, 4)} &#183; "
                  f"sincos({_fmt(t['cot'], 3)}) &#183; 1000",
            result=f"T<sub>Rd,max</sub> = {_fmt(t['trd_max'], 3)} kN.m")
        self._formula(
            "T<sub>Rd</sub> = min(T<sub>Rd,s</sub>, T<sub>Rd,max</sub>)",
            result=f"T<sub>Rd</sub> = {_fmt(t['trd'], 3)} kN.m "
                   f"(governed by {t['governs']})")
        self._formula(
            "T<sub>Rd,c</sub> = 2 A<sub>k</sub> t<sub>ef</sub> f<sub>ctd</sub>",
            ref="cracking (tau = f<sub>ctd</sub>)",
            subst=f"2 &#183; {_fmt(tube['Ak'], 4)} &#183; "
                  f"{_fmt(tube['tef'] / 1000.0, 4)} &#183; {_fmt(t['fctd'], 3)} "
                  "&#183; 1000",
            result=f"T<sub>Rd,c</sub> = {_fmt(t['trd_c'], 3)} kN.m")
        util = t["util"]
        util_txt = _pct(util)
        verdict = _code_verdict(
            viz.util_ok(util), t.get("code_applicable", True)
        )
        self._h2("Utilisation and longitudinal steel")
        self._formula("T<sub>Ed</sub> / T<sub>Rd</sub>",
                      subst=f"{_fmt(t['t_ed'], 3)} / {_fmt(t['trd'], 3)}",
                      result=f"{util_txt}  ({verdict})")
        self._formula(
            "sum A<sub>sl</sub> = T<sub>Ed</sub> u<sub>k</sub> cot theta / "
            "(2 A<sub>k</sub> f<sub>yd</sub>)",
            ref="EN 1992-1-1 (6.28)",
            subst=f"{_fmt(t['t_ed'], 3)} &#183; {_fmt(tube['uk'], 4)} &#183; "
                  f"{_fmt(t['cot'], 3)} / (2 &#183; {_fmt(tube['Ak'], 4)} &#183; "
                  f"{_fmt(t['fyd_long'], 1)}) &#183; 1000",
            result=f"sum A<sub>sl</sub> = {_fmt(t['asl_req'], 0)} mm<sup>2</sup> "
                   "(in addition to the bending steel)")
        self._small("Lengths shown in m and f in MPa; the &#183; 1000 converts "
                    "MN.m to kN.m (resistances) and m<sup>2</sup> to mm<sup>2</sup> "
                    "(A<sub>sl</sub>).")
        mr = t.get("min_reinf")
        if mr is not None and mr.get("applicable"):
            self._h2("Minimum-reinforcement screen (6.3.2(5), Eq 6.31)")
            vv = ("minimum reinforcement suffices" if mr["ok"]
                  else "designed reinforcement required")
            self._formula(
                "T<sub>Ed</sub>/T<sub>Rd,c</sub> + V<sub>Ed</sub>/V<sub>Rd,c</sub>",
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
            "Elastic section response and stress limits", "elastic"
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
        checks = el.get("stress_assessments") or {}
        if checks:
            self._h2("Stress-limit assessment")
            rows = [["Check", "Result", "Limit", "Utilisation", "Status"]]
            for label, key in (
                ("Concrete compression", "concrete"),
                ("Reinforcement tension", "reinforcement"),
                ("Tendon tension", "prestress"),
            ):
                item = checks.get(key)
                if not item or (key == "prestress" and not self.inp.get("tendons")):
                    continue
                limit = item.get("limit")
                rows.append([
                    label,
                    "-" if item.get("value") is None else
                    f"{_fmt(item.get('value'), 3)} MPa",
                    ("not supplied" if limit is None or limit <= 0.0 else
                     f"{_fmt(limit, 3)} MPa ({item.get('criterion', '-')})"),
                    "-" if item.get("util") is None else _pct(item.get("util")),
                    presentation.assessment_status_label(
                        item.get("status", "NOT ASSESSED")),
                ])
            self._table(rows, [42 * mm, 30 * mm, 47 * mm, 24 * mm, 27 * mm],
                        font=7.5)
            self._small(
                f"Criteria: {el.get('sls_limit_source', '-')}. "
                "Limits apply to the total elastic action."
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
                    show_labels=True, scale=_MM, unit="mm",
                    bar_ids=[item.get("id") for item in inp.get("bar_elements", [])],
                    tendon_ids=[item.get("id") for item in inp.get("tendon_elements", [])],
                    title="Elastic state (tension + / compression -)"), 150, 100)
                self._small(
                    "Blue/plain markers are tension (+); vermillion/x markers are "
                    "compression (-). Bar circles and tendon diamonds identify the "
                    "element type. Sign is not communicated by colour alone."
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
            )
            self._small("Coordinates in mm; area in mm<super>2</super>; strain in "
                        "permille; stresses in MPa.")
        else:
            # Backward-compatible report path for pre-PR6 result fixtures.
            total = el.get("total", [])
            rows = [["Element", "TOTAL", "LONG", "DIF", "RST1"]]
            for i in range(len(total)):
                rows.append([f"bar {i + 1}", _fmt(total[i], 3),
                             _fmt(el["long"][i], 3), _fmt(el["dif"][i], 3),
                             _fmt(el["rst1"][i], 3)])
            if len(total):
                w = 150 * mm / 5
                self._table(rows, [w] * 5, font=8, keep=False)
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
        assessment = el.get("crack_assessment") or {}
        status = assessment.get("status", "NOT ASSESSED")
        display_status = presentation.assessment_status_label(status)
        value = assessment.get("value")
        limit = assessment.get("limit")
        margin = assessment.get("margin")
        text = (
            f"{display_status} - Crack width | governing w<sub>k</sub> "
            f"{'-' if value is None else _fmt(value, 3) + ' mm'} | limit "
            f"{'not supplied' if limit is None or limit <= 0.0 else _fmt(limit, 3) + ' mm'} | "
            f"case {assessment.get('case') or '-'} | "
            f"element {assessment.get('governing') or '-'}"
        )
        if margin is not None:
            text += f" | margin {_fmt(margin, 3)} mm"
        self._status_block(text, status)
        self._small(f"Criteria: {el.get('sls_limit_source', '-')}.")
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
                ref="DS/EN 1992-1-1 &#167;7.3.4, Eq (7.14)",
                subst="bars not at close centres (spacing &gt; 5(c + phi/2))",
                result=f"s<sub>r,max</sub> = {_fmt(cw.get('sr_max',0), 3)} mm")
        else:
            self._formula(
                "s<sub>r,max</sub> = k<sub>3</sub>&#183;c + "
                "k<sub>1</sub>&#183;k<sub>2</sub>&#183;k<sub>4</sub>&#183;phi / rho<sub>p,eff</sub>",
                ref="DS/EN 1992-1-1 &#167;7.3.4, Eq (7.11)")
        self._formula(
            "eps<sub>sm</sub> - eps<sub>cm</sub> = [ sigma<sub>s</sub> - "
            "k<sub>t</sub>&#183;f<sub>ct,eff</sub>/rho<sub>p,eff</sub>&#183;"
            "(1 + alpha<sub>e</sub>&#183;rho<sub>p,eff</sub>) ] / E<sub>s</sub> "
            "&gt;= 0.6&#183;sigma<sub>s</sub>/E<sub>s</sub>",
            ref="Eq (7.9)")
        self._formula(
            ("w<sub>k</sub> = &#189;&#183;s<sub>r,max</sub> &#183; "
             "(eps<sub>sm</sub> - eps<sub>cm</sub>)" if coarse else
             "w<sub>k</sub> = s<sub>r,max</sub> &#183; "
             "(eps<sub>sm</sub> - eps<sub>cm</sub>)"),
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
                 "sigma<sub>s</sub>", "A<sub>c,eff</sub>", "delta eps",
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
        self._h2("Crack-width candidates - all checked cases")
        self._table(
            rows,
            _CRACK_CANDIDATE_COL_WIDTHS,
            font=5.4, keep=False,
        )
        self._small(
            "LT = long-term; ST = short-term. Coordinates, c, phi and "
            "s<sub>r</sub> in mm; sigma<sub>s</sub> in MPa; "
            "A<sub>c,eff</sub> in m<super>2</super>; delta eps "
            "dimensionless; w<sub>k</sub> in mm. G = governing; "
            "N = within 10% of governing."
        )

    def _crack_worked_2023(self, cw, code):
        """The EN 1992-1-1:2023 refined crack-width worked example (9.2.3)."""
        self._formula(
            "s<sub>r,m,cal</sub> = 1.5&#183;c + (k<sub>fl</sub>&#183;k<sub>b</sub>/7.2)"
            "&#183;phi/rho<sub>p,eff</sub> &lt;= (1.3/k<sub>w</sub>)&#183;(h-x)",
            ref="EN 1992-1-1:2023 &#167;9.2.3, Eq (9.15)",
            subst=f"k<sub>fl</sub> = {_fmt(cw.get('kfl',1),3)}; "
                  f"s<sub>r,m,cal</sub> = {_fmt(cw.get('sr_max',0), 3)} mm")
        self._formula(
            "eps<sub>sm</sub> - eps<sub>cm</sub> = [ sigma<sub>s</sub> - "
            "k<sub>t</sub>&#183;f<sub>ct,eff</sub>/rho<sub>p,eff</sub>&#183;"
            "(1 + alpha<sub>e</sub>&#183;rho<sub>p,eff</sub>) ] / E<sub>s</sub> "
            "&gt;= (1 - k<sub>t</sub>)&#183;sigma<sub>s</sub>/E<sub>s</sub>",
            ref="Eq (9.11)")
        self._formula(
            "w<sub>k,cal</sub> = k<sub>w</sub>&#183;k<sub>1/r</sub>&#183;"
            "s<sub>r,m,cal</sub>&#183;(eps<sub>sm</sub> - eps<sub>cm</sub>)",
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

    def _appendix(self):
        self.flow.append(PageBreak())
        self._h1("References and notes")
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
                "&#167;9.1-9.2 (stress limitations and cracking threshold)"
                if crack_2023 else
                "&#167;7.1-7.2 (stress limitations and cracking threshold)"
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
                "Stress and crack-width acceptance limits are the explicit "
                "user-entered project criteria printed with the result; Sector "
                "does not infer exposure class or action-combination applicability."
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


def build_report(meta, inp, out, version="", figures=True, progress=None) -> bytes:
    """Build the PDF report and return its bytes.

    ``progress`` is an optional ``callable(fraction, text)`` invoked as the report
    is assembled, so the UI can show a progress bar.
    """
    buffer = io.BytesIO()
    ReportBuilder(buffer, meta, inp, out, version=version, figures=figures,
                  progress=progress).build()
    buffer.seek(0)
    return buffer.getvalue()
