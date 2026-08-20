"""Generate a QA-able PDF report of a Sector cross-section analysis.

Modelled on the BriCoS report: a sectioned reportlab document with a numbered
footer, every case summarised and governing calculations reported in detail, and
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

from collections.abc import Mapping
import datetime
import decimal
import html as html_lib
import io
import math
import os
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (CondPageBreak, Flowable, Image, KeepTogether,
                                NotAtTopPageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

import case_analysis
import fatigue_inputs
import fatigue_presentation
import material_catalog
from app import modelled_direction
from app import publication_equation_layout as publication_equations
from app import report_profiles
from app import table_field_definitions as table_fields
import publication_image_export
from publication_items import PublicationCounter
from publication_notation import normalize_trusted_markup, shield_literal_markup
import publication_theme
import report_equation_contract
import viz
import result_presentation as presentation
from sector import codes as ec2_codes
from sector import detailing
from sector import fatigue as fatigue_core
from sector import __licensee__ as SECTOR_LICENSEE
from sector.build_info import short_revision
from sector.design_standards import DesignBasisKey, get_design_basis

_MM = 1000.0                       # metres -> millimetres for display
_KN = 1.0                          # forces already in kN
_BLUE = colors.HexColor(publication_theme.PALETTE.primary)
_GREY = colors.HexColor(publication_theme.PALETTE.muted)
_LINE = colors.HexColor(publication_theme.PALETTE.rule)
_HEAD_BG = colors.HexColor(publication_theme.PALETTE.report_header)
_A4_CONTENT_WIDTH = A4[0] - 40 * mm
_REPORT_FRAME_PADDING = 6.0
_A4_FRAME_USABLE_HEIGHT = A4[1] - 45 * mm - 2 * _REPORT_FRAME_PADDING
_MIN_REPORT_TABLE_FONT = 7.2
_REPORT_TABLE_HORIZONTAL_PADDING = 3.0
_REPORT_TABLE_SCRIPT_PADDING = 2.0
_REPORT_TABLE_SUBSCRIPT_RISE_FACTOR = 0.15
_REPORT_TABLE_SUPERSCRIPT_RISE_FACTOR = 0.25
_REPORT_TABLE_SCRIPT_TAG = re.compile(r"<(?:sub|sup|super)>", re.IGNORECASE)
_ASSESSMENT_PALETTE = publication_theme.ASSESSMENT_COLORS
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
_INPUT_TABLE_SUBSCRIPT_RE = re.compile(r"_\{([A-Za-z0-9,]+)\}")
_INPUT_TABLE_SIMPLE_SUBSCRIPT_RE = re.compile(r"_([A-Za-z0-9]+)")
_INPUT_TABLE_RAW_TEX_RE = re.compile(r"[\\{}$^]")
_DERIVED_EQUATION_SOURCE = (
    "Derived relation; no separate normative source assigned."
)
_LITERAL_REPORT_RESULT_IDENTITIES = frozenset({
    ("elastic.long.stress-plane", None),
    ("elastic.instantaneous.stress-plane", None),
})
_EQUATION_DECIMAL_PLACES = 3
_EQUATION_DECIMAL_QUANTUM = decimal.Decimal(1).scaleb(
    -_EQUATION_DECIMAL_PLACES
)
_EQUATION_MAX_RELATIVE_ROUNDING = decimal.Decimal("0.005")
_EQUATION_DECIMAL_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_#])"
    r"((?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)"
    r"(?![0-9_])"
)
_EQUATION_NEGATIVE_ZERO_RE = re.compile(
    r"(^|[=(:,;+*/\[\]{}|<>^])(?P<space>\s*)-0(?=$|[\s),;%\]}|])"
)


def _table_script_markup(markup, font_size):
    """Apply compact, measured script rises inside trusted table markup.

    ReportLab's default half-em rise pushes subscripts through a table's bottom
    rule.  These table-only rises remain visibly sub/superscripted while keeping
    the glyph ink inside a compact row with explicit rule clearance.
    """

    subscript_rise = font_size * _REPORT_TABLE_SUBSCRIPT_RISE_FACTOR
    superscript_rise = font_size * _REPORT_TABLE_SUPERSCRIPT_RISE_FACTOR
    markup = re.sub(
        r"<sub>",
        f'<sub rise="{subscript_rise:.3f}">',
        markup,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"<(?:sup|super)>",
        f'<super rise="{superscript_rise:.3f}">',
        markup,
        flags=re.IGNORECASE,
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


def _report_basis_summary(inp):
    """Return ordered, user-facing selected bases and methods for the dashboard."""

    values = []
    for key in ("sls_code", "fatigue_edition"):
        value = inp.get(key)
        if value in (None, ""):
            continue
        try:
            label = get_design_basis(value).label
        except (TypeError, ValueError):
            label = str(value)
        values.append(label)
    for key in (
        "detailing_edition",
        "shear_method",
        "torsion_method",
        "combined_method",
    ):
        value = inp.get(key)
        if value not in (None, ""):
            values.append(str(value))
    return "; ".join(dict.fromkeys(values)) or "Not declared"


def _catalogue_presets_for_ids(catalogue, material_ids):
    """Return presets for assigned catalogue IDs, preserving catalogue order."""

    if not isinstance(catalogue, Mapping):
        return ()
    items = catalogue.get("items") or ()
    if isinstance(items, Mapping):
        items = (items,)
    wanted = {str(value) for value in material_ids if value not in (None, "")}
    return tuple(
        str(item.get("preset"))
        for item in items
        if isinstance(item, Mapping)
        and str(item.get("id")) in wanted
        and item.get("preset") not in (None, "")
    )


def _used_material_presets(inp):
    """Return material presets that participate in the current calculation."""

    presets = []
    concrete_preset = inp.get("concrete_preset")
    if concrete_preset not in (None, ""):
        presets.append(str(concrete_preset))

    mild_ids = [
        item.get("material_id")
        for item in (inp.get("bar_elements") or ())
        if isinstance(item, Mapping)
    ]
    if inp.get("shear_on") or inp.get("torsion_on"):
        mild_ids.append(inp.get("capacity_steel_material_id"))
    mild_presets = _catalogue_presets_for_ids(
        inp.get("mild_material_catalog"), mild_ids
    )
    if mild_presets:
        presets.extend(mild_presets)
    elif inp.get("bars") or mild_ids:
        mild_preset = inp.get("mild_preset")
        if mild_preset not in (None, ""):
            presets.append(str(mild_preset))

    prestress_ids = [
        item.get("material_id")
        for item in (inp.get("tendon_elements") or ())
        if isinstance(item, Mapping)
    ]
    prestress_presets = _catalogue_presets_for_ids(
        inp.get("prestress_material_catalog"), prestress_ids
    )
    if prestress_presets:
        presets.extend(prestress_presets)
    elif inp.get("tendons") or prestress_ids:
        prestress_preset = inp.get("prestress_preset")
        if prestress_preset not in (None, ""):
            presets.append(str(prestress_preset))

    return tuple(dict.fromkeys(presets))


def _report_adoption_warning(inp):
    """Return explicit adoption/applicability warnings for the dashboard."""

    basis = _report_basis_summary(inp)
    warnings = []
    if "2023" in basis or any(
        "2023" in preset for preset in _used_material_presets(inp)
    ):
        warnings.append(
            "The 2023 reference option requires project adoption; no Danish "
            "National Annex is applied."
        )
    if inp.get("sls_heightened_on"):
        warnings.append(
            "The DK heightened crack-control applicability is user-selected; "
            "Sector does not infer it."
        )
    return " ".join(warnings)


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


def _modelled_direction_report_label(
    result=None, *, cut_direction=None, alias=None
):
    """Return canonical direction plus literal-safe project terminology."""

    canonical = modelled_direction.canonical_direction(
        result, cut_direction=cut_direction
    ).capitalize()
    project_alias = modelled_direction.normalise_alias(alias)
    if not project_alias:
        return canonical
    return f"{canonical} (project alias: {_html_escape(project_alias)})"


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


def _input_table_symbol(table_key, field_key):
    """Return one registered input symbol as trusted ReportLab markup.

    Editable-table symbols use a deliberately small LaTeX subset. Convert that
    subset here rather than duplicating the symbols in the report, and fail
    closed if a future registry entry introduces unsupported TeX.
    """

    definition = table_fields.field_definition(table_key, field_key)
    symbol = definition.math_symbol.strip()
    if symbol == "-":
        return _html_escape(definition.label)
    symbol = symbol.replace(r"\Delta", "&#916;").replace(r"\phi", "&#966;")
    symbol = _INPUT_TABLE_SUBSCRIPT_RE.sub(r"<sub>\1</sub>", symbol)
    symbol = _INPUT_TABLE_SIMPLE_SUBSCRIPT_RE.sub(r"<sub>\1</sub>", symbol)
    if _INPUT_TABLE_RAW_TEX_RE.search(symbol):
        raise ValueError(
            f"unsupported input-table mathematics for {table_key}.{field_key}"
        )
    return normalize_trusted_markup(symbol)


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

        # Never leave a repeated caption/header fragment without one complete
        # data row. If that minimum group fits an ordinary page but not the
        # current remainder, ask ReportLab to move the table to the next page.
        minimum_fragment_height = (
            sum(self._rowHeights[: repeat_count + 1])
            if data_count > 0
            else 0.0
        )
        if (
            data_count > 0
            and minimum_fragment_height <= _A4_FRAME_USABLE_HEIGHT + 1e-7
            and availHeight + 1e-7 < minimum_fragment_height
        ):
            return []

        row_split_range = None
        # Prefer three complete data rows at both edges.  If a tall-row table
        # cannot fit three trailing rows on an ordinary page, retain two rather
        # than falling back to an orphan one-row continuation.
        for edge_rows in (3, 2):
            if data_count < 2 * edge_rows:
                continue
            repeated_height = sum(self._rowHeights[:repeat_count])
            leading_height = sum(
                self._rowHeights[: repeat_count + edge_rows]
            )
            trailing_height = repeated_height + sum(
                self._rowHeights[-edge_rows:]
            )
            if (
                leading_height <= _A4_FRAME_USABLE_HEIGHT + 1e-7
                and trailing_height <= _A4_FRAME_USABLE_HEIGHT + 1e-7
            ):
                row_split_range = (
                    repeat_count + edge_rows,
                    -edge_rows,
                )
                break

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
            "_sector_force_page_break_between_fragments",
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
        if (
            getattr(self, "_sector_force_page_break_between_fragments", False)
            and len(fragments) > 1
        ):
            separated = []
            for index, fragment in enumerate(fragments):
                if index:
                    separated.append(NotAtTopPageBreak())
                separated.append(fragment)
            return separated
        return fragments


def ensure_image_server(timeout=None):
    """Start the shared exporter or fail the requested report explicitly."""

    selected_timeout = _FIG_EXPORT_TIMEOUT_S if timeout is None else timeout
    try:
        publication_image_export.ensure_ready(timeout=selected_timeout)
    except publication_image_export.KaleidoExportError as exc:
        raise ReportFigureError(
            "Engineering-figure exporter could not start; report not created."
        ) from exc


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

    def themed(name, parent, role):
        return ParagraphStyle(
            name,
            parent=parent,
            **publication_theme.reportlab_style_values(
                publication_theme.REPORT_TEXT[role],
                _FONT,
                _FONT_BOLD,
                colors.HexColor,
            ),
        )

    out["title"] = themed("t", ss["Title"], "title")
    out["subtitle"] = themed("st", ss["Normal"], "subtitle")
    out["h1"] = themed("h1", ss["Heading1"], "h1")
    out["h2"] = themed("h2", ss["Heading2"], "h2")
    out["body"] = themed("b", ss["Normal"], "body")
    out["small"] = themed("s", ss["Normal"], "small")
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
    out["publication_ref"] = themed(
        "pr", ss["Normal"], "publication_ref"
    )
    out["publication_caption"] = themed(
        "pc", ss["Normal"], "publication_caption"
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


class _EquationAnchor(Flowable):
    """Zero-height named destination kept under report ownership."""

    def __init__(self, anchor):
        super().__init__()
        self._sector_equation_anchor = str(anchor)
        self._sector_equation_role = "identity"

    def wrap(self, availWidth, availHeight):
        del availWidth, availHeight
        self.width = 0.0
        self.height = 0.0
        return 0.0, 0.0

    def draw(self):
        self.canv.bookmarkHorizontal(self._sector_equation_anchor, 0.0, 0.0)

    @staticmethod
    def getPlainText():
        return ""


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
        self._sector_equation_publication_role = contract.publication_role
        self._sector_equation_applicability_note_required = (
            contract.applicability_note_required
        )
        self._sector_equation_anchor = anchor
        self._sector_equation_number = number
        self._sector_equation_section = section
        self._sector_equation_subsection = subsection
        roles = []
        for child in content:
            child_roles = getattr(child, "_sector_equation_roles", None)
            if child_roles is not None:
                roles.extend(child_roles)
                continue
            roles.append(child._sector_equation_role)
        self._sector_equation_roles = tuple(roles)

    def getSpaceBefore(self, content=None):
        """Measure the first visible row rather than the zero-height anchor."""
        rows = self._content if content is None else content
        for child in rows:
            if isinstance(child, _EquationAnchor):
                continue
            if not hasattr(child, "frameAction"):
                return child.getSpaceBefore()
        return 0

    def wrap(self, available_width, available_height):
        """Include visible leading space in ReportLab's keep decision."""
        width, height = super().wrap(available_width, available_height)
        # KeepTogether excludes the first non-zero child's spaceBefore from
        # its internal height.  Our zero-height bookmark anchor is released
        # ahead of the visible math, so that space is consumed when ReportLab
        # lays out the children individually.  Retaining it here prevents a
        # near-boundary fit from orphaning the final source row.
        leading_space = self.getSpaceBefore()
        frame = getattr(self, "_frame", None)
        if frame is None:
            unmeasured_space = leading_space
        elif getattr(frame, "_atTop", False):
            unmeasured_space = 0.0
        else:
            externally_applied = leading_space
            if getattr(frame, "_oASpace", False):
                externally_applied = max(
                    leading_space - getattr(frame, "_prevASpace", 0.0),
                    0.0,
                )
            unmeasured_space = max(
                leading_space - externally_applied,
                0.0,
            )
        self._H += unmeasured_space
        return width, height

    def getPlainText(self):
        parts = []
        for child in self._content:
            if not hasattr(child, "getPlainText"):
                continue
            text = getattr(child, "_sector_report_plain_text", None)
            if text is None:
                text = child.getPlainText()
            if text:
                parts.append(text)
        return " ".join(parts)


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
    """Export through the serialized process coordinator.

    The tuple contract is retained for the report builder: a timeout is distinct
    from another export failure, while either condition permanently poisons the
    shared coordinator and makes later calls fail without starting more workers.
    """

    def _work():
        with publication_theme.without_kaleido_server_kopts_noise():
            return fig.to_image(
                format="png", width=w_px, height=h_px, scale=2
            )

    try:
        png = publication_image_export.export_png(
            _work,
            timeout=timeout,
            description="report figure export",
        )
    except publication_image_export.KaleidoExportTimeout:
        return None, True
    except publication_image_export.KaleidoExportError:
        return None, False
    return png, False


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


def _compact_equation_numbers(source):
    """Round display-only equation values without hiding tiny nonzero terms."""

    if not isinstance(source, str):
        raise TypeError("equation display source must be text")

    def compact(match):
        raw = match.group(1)
        value = decimal.Decimal(raw)
        if value.is_zero():
            return "0"

        with decimal.localcontext() as context:
            context.prec = max(
                28,
                len(value.as_tuple().digits) + abs(value.adjusted()) + 8,
            )
            rounded = value.quantize(
                _EQUATION_DECIMAL_QUANTUM,
                rounding=decimal.ROUND_HALF_UP,
            )
            relative_rounding = abs(rounded - value) / abs(value)
            if (
                "e" in raw.lower()
                or rounded.is_zero()
                or relative_rounding > _EQUATION_MAX_RELATIVE_ROUNDING
            ):
                exponent = abs(value).adjusted()
                mantissa = value.scaleb(-exponent).quantize(
                    _EQUATION_DECIMAL_QUANTUM,
                    rounding=decimal.ROUND_HALF_UP,
                )
                if abs(mantissa) >= decimal.Decimal("10"):
                    mantissa = mantissa / decimal.Decimal("10")
                    exponent += 1
                text = format(mantissa, "f").rstrip("0").rstrip(".")
                return f"{text}e{exponent:+d}"

            return format(rounded, "f").rstrip("0").rstrip(".")

    compacted = _EQUATION_DECIMAL_TOKEN_RE.sub(compact, source)

    def remove_negative_zero(match):
        return f"{match.group(1)}{match.group('space')}0"

    return _EQUATION_NEGATIVE_ZERO_RE.sub(remove_negative_zero, compacted)


def _curvature_selection_substitution(candidates, selected):
    """Summarise the retained candidate population without repeating its table."""

    selected_ordinal = next(
        index
        for index, candidate in enumerate(candidates, start=1)
        if candidate.get("selected")
    )
    candidate_count = len(candidates)
    population = (
        "kappa<sub>1</sub>"
        if candidate_count == 1
        else f"kappa<sub>i=1:{candidate_count}</sub>"
    )
    return (
        f"= min({population}) = kappa<sub>{selected_ordinal}</sub> = "
        f"{_fmt(selected.get('curvature_per_m'), 9)} 1/m"
    )


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
        qa_appendix=None,
        profile=None,
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
        self.profile = report_profiles.resolve_profile(
            profile,
            qa_appendix=qa_appendix,
        )
        # Preserve the historical attribute for bounded downstream compatibility.
        # The immutable profile policy is now the authority.
        self.qa_appendix = self.profile.include_qa_appendix
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
        selection = self._base_out.get("worked_example_selection")
        self._worked_example_selection = (
            selection
            if isinstance(selection, Mapping) and selection.get("schema") == 1
            else {}
        )
        families = self._worked_example_selection.get("families")
        self._selected_families = families if isinstance(families, Mapping) else {}
        crack_examples = self._worked_example_selection.get("crack_examples")
        self._selected_crack_examples = tuple(
            item for item in crack_examples
            if isinstance(item, Mapping)
        ) if isinstance(crack_examples, (list, tuple)) else ()
        crack_comparison = self._worked_example_selection.get("crack_comparison")
        self._selected_crack_comparison = (
            crack_comparison if isinstance(crack_comparison, Mapping) else None
        )
        threshold = self._worked_example_selection.get("cracking_threshold")
        self._selected_cracking_threshold = (
            threshold if isinstance(threshold, Mapping) else None
        )
        torsion_subchecks = self._worked_example_selection.get("torsion_subchecks")
        self._selected_torsion_subchecks = (
            torsion_subchecks if isinstance(torsion_subchecks, Mapping) else {}
        )
        heightened = self._worked_example_selection.get(
            "heightened_crack_control"
        )
        self._selected_heightened_crack_control = (
            heightened if isinstance(heightened, Mapping) else None
        )

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

    @staticmethod
    def _case_id(case_inp, family):
        """Return the stable identity used by the retained selection contract."""
        if "_report_case_actions" not in case_inp:
            return "__single__"
        return presentation.action_set(case_inp, family)["id"]

    def _selected_family(self, family, case_inp):
        selected = self._selected_families.get(family)
        if not isinstance(selected, Mapping):
            return None
        return selected if selected.get("case_id") == self._case_id(
            case_inp, "elastic" if family == "elastic" else "plastic"
        ) else None

    def _combined_selection_is_authoritative(self, selected):
        """Return whether a retained combined selection has trusted bending."""

        if not isinstance(selected, Mapping):
            return False
        matches = [
            case_out
            for case_inp, case_out in self._case_contexts("plastic")
            if self._case_id(case_inp, "plastic") == selected.get("case_id")
        ]
        return (
            len(matches) == 1
            and matches[0].get("combined") is not None
            and presentation.combined_bending_assessment_blocker(matches[0]) is None
        )

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
        if self.profile.key == "Brief":
            return _LiteralReportText(", ".join(
                presentation.action_set(case_inp, family)["id"] or "ID NOT SET"
                for case_inp, _ in contexts
            ))
        return _LiteralReportText("; ".join(
            _report_action_set_text(case_inp, family)
            for case_inp, _ in contexts
        ))

    def _tick(self, frac, text):
        if self._progress is not None:
            self._progress(frac, text)

    # -- flowable helpers --------------------------------------------------
    def _h1(self, text, *, reserve=0):
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
        if reserve:
            self.flow.append(CondPageBreak(reserve))
        self.flow.append(heading)

    def _h2(self, text, *, reserve=170):
        self._subsection += 1
        self._table_subsection_context = _greek(f"Subsection: {text}")
        self._publication_subsection_title = Paragraph(
            _greek(str(text)), self.s["small"]
        ).getPlainText().strip()
        # ``keepWithNext`` can be defeated when the following object is a
        # nested indivisible equation/table wrapper. Reserve enough space before
        # placing the heading for at least one substantive following row.
        # Reserve enough room for the heading and the first indivisible
        # equation/table block.  A smaller guard still allowed a heading plus
        # its tiny identity row to fit while the actual calculation moved to
        # the next page.
        self.flow.append(CondPageBreak(reserve))
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
        # Standard and Audit continuations must remain independently reviewable.
        # Brief retains compact assessment-only context so its new input inventory
        # can remain readable without duplicating section context on every split.
        include_full_context = self.profile.key != "Brief"
        if include_full_context and self._table_section_context is not None:
            entries.append((
                "section", self._table_section_context, _HEAD_BG, _BLUE,
            ))
        if include_full_context and self._table_subsection_context is not None:
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
        # Keep the explanatory lead-in with the table's first page.  This still
        # lets genuinely oversized project overviews use the native row splitter.
        self.flow[-1].keepWithNext = 1
        data = [[
            "Check", "Action set", "Status", "Result", "Criterion", "Gov."
        ]]
        scope_states = {"NOT REQUESTED", "NOT APPLICABLE", "NOT RUN"}
        attention_states = {"FAIL", "INVALID", "REVIEW", "NOT ASSESSED"}

        def _overview_group(row):
            status = str(row["status"]).upper()
            if status in scope_states:
                return "Scope and not-run states"
            if status == "CALCULATED" or row["criterion"] == "Output only":
                return "Calculated outputs"
            return "Acceptance checks"

        grouped = {
            "Acceptance checks": [],
            "Calculated outputs": [],
            "Scope and not-run states": [],
        }
        for original_index, (row, is_governing) in enumerate(zip(rows, governing)):
            grouped[_overview_group(row)].append((original_index, row, is_governing))
        grouped["Acceptance checks"].sort(key=lambda item: (
            str(item[1]["status"]).upper() not in attention_states,
            item[0],
        ))

        group_rows = []
        status_rows = []
        for group_label, entries in grouped.items():
            if not entries:
                continue
            group_rows.append((len(data), group_label))
            data.append([group_label, "", "", "", "", ""])
            for _original_index, row, is_governing in entries:
                status_rows.append((len(data), row["status"]))
                data.append([
                    _html_escape(row["check"]), _html_escape(row["case"]),
                    row["status"], row["result"], row["criterion"],
                    "YES" if is_governing else "-",
                ])
        summary_font = 8.5 if self.profile.key == "Standard" else 7.2
        body = ParagraphStyle(
            "summary-cell", parent=self.s["body"], fontSize=summary_font,
            fontName=_FONT, leading=summary_font + 1.6,
        )
        head = ParagraphStyle(
            "summary-head", parent=body, fontName=_FONT_BOLD,
        )
        formatted = []
        for index, row in enumerate(data):
            style = head if index == 0 or any(
                index == group_index for group_index, _label in group_rows
            ) else body
            formatted.append([
                Paragraph(_greek(str(cell)), style) for cell in row
            ])
        table_item = self._publication_counter.issue(
            "Table", "Results overview across calculated checks"
        )
        caption_markup = (
            f'<font color="{publication_theme.PALETTE.publication_reference}">'
            f'See <link href="#{table_item.anchor}">'
            f'{table_item.label}</link>.</font><br/>'
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
            colWidths=[
                41 * mm, 24 * mm, 27 * mm,
                33 * mm, 35 * mm, 10 * mm,
            ],
            repeatRows=1 + context_count + 1,
            hAlign="LEFT",
            splitByRow=1,
            splitInRow=1,
        )
        vertical_padding = 0.45 if self.profile.key == "Brief" else 0.7
        style = [
            ("SPAN", (0, 0), (-1, 0)),
            ("GRID", (0, 1), (-1, -1), 0.4, _LINE),
            ("BACKGROUND", (0, header_row), (-1, header_row), _HEAD_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), vertical_padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), vertical_padding),
        ]
        style.extend(context_style)
        group_padding = 1.2 if self.profile.key == "Brief" else 3
        for data_index, _group_label in group_rows:
            table_index = header_row + data_index
            style.extend([
                ("SPAN", (0, table_index), (-1, table_index)),
                ("BACKGROUND", (0, table_index), (-1, table_index),
                 colors.HexColor("#F1F4F8")),
                ("TEXTCOLOR", (0, table_index), (-1, table_index), _BLUE),
                (
                    "TOPPADDING", (0, table_index), (-1, table_index),
                    group_padding,
                ),
                (
                    "BOTTOMPADDING", (0, table_index), (-1, table_index),
                    group_padding,
                ),
            ])
        fills = {
            "PASS": colors.HexColor("#E8F5E9"),
            "FAIL": colors.HexColor("#FDECEC"),
            "INVALID": colors.HexColor("#FDECEC"),
            "REVIEW": colors.HexColor("#FFF4D6"),
            "NOT ASSESSED": colors.HexColor("#FFF4D6"),
            "NOT RUN": colors.HexColor("#EEF2F6"),
            "NOT APPLICABLE": colors.HexColor("#EEF2F6"),
        }
        for data_index, status in status_rows:
            row_index = header_row + data_index
            fill = fills.get(status)
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
        table._sector_overview_groups = tuple(
            label for _index, label in group_rows
        )
        table.keepWithNext = 1
        self.flow.append(table)
        if self.profile.key == "Brief":
            governing_note = (
                "Gov. marks the highest PASS/FAIL utilisation per check; ties "
                "remain marked. NOT APPLICABLE means zero action."
            )
        else:
            governing_note = (
                "Gov. marks the highest PASS/FAIL utilisation for each check; "
                "ties remain marked. NOT APPLICABLE means the row action is zero."
            )
        self._small(governing_note)
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

    def _keep_measured_calculation_from(self, start):
        """Keep a bounded table/equation calculation together using real heights.

        ``_EquationFlowable`` is itself a ``KeepTogether`` and therefore reports
        ReportLab's deliberately artificial height when nested.  Flatten its
        visible rows for this outer layout group, while retaining the sealed
        equation objects as publication metadata on the group.
        """
        block = []
        equations = []
        for item in self.flow[start:]:
            if isinstance(item, _EquationFlowable):
                equations.append(item)
                block.extend(item._content)
            elif isinstance(item, KeepTogether):
                block.extend(item._content)
            else:
                block.append(item)
        group = KeepTogether(block)
        group._sector_equations = tuple(equations)
        self.flow[start:] = [group]

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

        display_substitution = (
            _compact_equation_numbers(subst) if subst else None
        )
        display_result = _compact_equation_numbers(result) if result else None

        compiled_expression = publication_equations.compile_report_math(expr)
        compiled_substitution = (
            publication_equations.compile_report_fragment(display_substitution)
            if display_substitution else None
        )
        compiled_result = None
        if display_result:
            result_identity = (equation_key, equation_variant)
            if result_identity in _LITERAL_REPORT_RESULT_IDENTITIES:
                compiled_result = publication_equations.compile_report_literal(
                    display_result
                )
            else:
                compiled_result = publication_equations.compile_report_fragment(
                    display_result
                )

        next_equation_number = self._equation_number + 1 if numbered else None
        number = (
            f"{self._chapter}.{next_equation_number}"
            if next_equation_number is not None else None
        )
        anchor = (
            f"sector-equation-{self._chapter}-{self._subsection}-"
            + _equation_anchor_key(equation_key)
        )
        record = {
            "key": equation_key,
            "anchor": anchor,
            "number": number,
        }

        public = f"EQ-{equation_key.upper()}"
        if self.profile.key == "Audit":
            identity = (
                f"Equation ({number}) | {public}"
                if number is not None else public
            )
        else:
            # Internal contract keys remain sealed on the equation flowable and
            # registry. Ordinary readers receive the user-facing publication
            # number only; the Audit profile exposes the internal key inventory.
            identity = f"Equation ({number})" if number is not None else "Method relation"
        symbolic_plain_text = Paragraph(
            f"<b>Symbolic expression:</b> {_equation_math(expr)}",
            self.s["formula"],
        ).getPlainText()
        lines = [publication_equations.EquationLine(
            "symbolic-expression",
            compiled_expression,
            "Symbolic expression:",
            symbolic_plain_text,
        )]
        legacy_math_text = [
            identity,
            symbolic_plain_text,
        ]
        if compiled_substitution is not None:
            substitution_plain_text = Paragraph(
                "<b>Numerical substitution:</b> "
                f"{_equation_math(display_substitution)}",
                self.s["formula"],
            ).getPlainText()
            lines.append(publication_equations.EquationLine(
                "numerical-substitution",
                compiled_substitution,
                "Numerical substitution:",
                substitution_plain_text,
            ))
            legacy_math_text.append(substitution_plain_text)
        if display_result:
            display_unit = _equation_result_unit(
                contract.result_unit, display_result
            )
            visible_result_symbol = Paragraph(
                _equation_math(contract.result_symbol),
                self.s["formula"],
            ).getPlainText()
            visible_result_unit = Paragraph(
                _greek(display_unit),
                self.s["formula"],
            ).getPlainText()
            result_label = (
                f"Result {chr(0x2014)} {visible_result_symbol} "
                f"[{visible_result_unit}]:"
            )
            result_plain_text = Paragraph(
                "<b>Result &#8212; "
                f"{_equation_math(contract.result_symbol)} "
                f"[{_greek(display_unit)}]:</b> "
                f"{_equation_math(display_result)}",
                self.s["formula"],
            ).getPlainText()
            lines.append(publication_equations.EquationLine(
                "result",
                compiled_result,
                result_label,
                result_plain_text,
            ))
            legacy_math_text.append(result_plain_text)

        math_flowable = publication_equations.EquationFlowable(
            publication_equations.EquationBlock(tuple(lines), identity=identity)
        )
        math_flowable._sector_equation_role = "aligned-math"
        math_flowable._sector_equation_roles = tuple(
            line.role for line in lines
        )
        math_flowable._sector_report_plain_text = " ".join(legacy_math_text)
        math_flowable.spaceBefore = 2
        math_flowable.spaceAfter = 3
        content = [_EquationAnchor(anchor), math_flowable]
        if note:
            content.append(_equation_paragraph(
                f"<b>Applicability / method note:</b> {_greek(note)}",
                self.s["formula"],
                "applicability-note",
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
        source_markup = _greek(f"<b>Source / method note:</b> {source}")
        source_end_marker = f"SECTOR-SOURCE-END[{anchor}]"
        source_row = _equation_paragraph(
            source_markup
            + f'<font color="#FFFFFF" size="0.1">{source_end_marker}</font>',
            self.s["ref"],
            "source",
        )
        source_row._sector_report_plain_text = Paragraph(
            source_markup,
            self.s["ref"],
        ).getPlainText()
        content.append(source_row)
        equation = _EquationFlowable(
            content,
            key=equation_key,
            variant=equation_variant,
            contract=contract,
            anchor=anchor,
            number=number,
            section=self._chapter,
            subsection=self._subsection,
        )
        if next_equation_number is not None:
            self._equation_number = next_equation_number
        self._equations[scope] = record
        self.flow.append(equation)

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
        profile_floor = 8.5 if self.profile.key == "Standard" else 0.0
        font = max(float(font), _MIN_REPORT_TABLE_FONT, profile_floor)
        body = ParagraphStyle("c", parent=self.s["body"], fontSize=font,
                              fontName=_FONT, leading=font + 2)
        head = ParagraphStyle("ch", parent=body, fontName=_FONT_BOLD)
        rows = []
        markups = []
        literals = []
        numeric_sources = []
        script_rows = []
        for r, row in enumerate(data):
            cells = []
            rendered_row = []
            literal_row = []
            numeric_source_row = []
            row_markups = [_greek(str(cell)) for cell in row]
            has_scripts = any(
                _REPORT_TABLE_SCRIPT_TAG.search(markup) is not None
                for markup in row_markups
            )
            if has_scripts:
                script_rows.append(r)
            for ci, cell in enumerate(row):
                st = head if (header and r == 0) else body
                st = ParagraphStyle("x", parent=st,
                                    alignment=TA_LEFT if ci == 0 else TA_CENTER)
                markup = row_markups[ci]
                if has_scripts:
                    markup = _table_script_markup(markup, font)
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
        # A long table (the sweep / per-bar tables) may split across pages; a short
        # one is kept whole so it never strands a row on an otherwise empty page.
        # The first caption row owns the reference as well as the destination, so
        # no page-position guard can separate ``See Table ...`` from its object.
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
            reference_markup = (
                f'<font color="{publication_theme.PALETTE.publication_reference}">See '
                f'<link href="#{table_item.anchor}">{table_item.label}</link>.'
                f"</font><br/>"
                if not continued else ""
            )
            visible_label = (
                f"{table_item.label} (continued)"
                if continued
                else table_item.label
            )
            anchor = f'<a name="{table_item.anchor}"/>' if not continued else ""
            caption_markup = (
                f"{reference_markup}{anchor}<b>{visible_label}.</b> "
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
            table._sector_script_source_rows = tuple(script_rows)
            table._sector_script_table_rows = tuple(
                1 + context_count + row_index for row_index in script_rows
            )
            table._sector_script_leading = font + 2
            table._sector_script_top_padding = _REPORT_TABLE_SCRIPT_PADDING
            table._sector_script_bottom_padding = _REPORT_TABLE_SCRIPT_PADDING
            table._sector_subscript_rise = (
                font * _REPORT_TABLE_SUBSCRIPT_RISE_FACTOR
            )
            table._sector_superscript_rise = (
                font * _REPORT_TABLE_SUPERSCRIPT_RISE_FACTOR
            )
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
            for source_row in script_rows:
                table_row = 1 + context_count + source_row
                table_style.extend([
                    (
                        "TOPPADDING",
                        (0, table_row),
                        (-1, table_row),
                        _REPORT_TABLE_SCRIPT_PADDING,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, table_row),
                        (-1, table_row),
                        _REPORT_TABLE_SCRIPT_PADDING,
                    ),
                ])
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
        if self.profile.key == "Brief":
            self._brief_input_summary()
            self._brief_governing_register()
            self._write_pdf()
            return
        self._conventions()
        if self.profile.key == "Audit":
            self._theory()
        self._tick(0.2, "Section and materials...")
        self._inputs()
        if self._base_out.get("clear_spacing") is not None:
            if self.profile.key == "Audit":
                self.flow.append(NotAtTopPageBreak())
            self.inp, self.out = self._base_inp, self._base_out
            self._clear_spacing()
        jobs = []
        plastic_contexts = self._case_contexts("plastic")
        for case_inp, case_out in plastic_contexts:
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
                if (
                    self._selected_family(key, case_inp) is None
                    and not self._needs_diagnostic_chapter(
                        key, case_out[key]
                    )
                    and not (
                        key == "combined"
                        and presentation.combined_bending_assessment_blocker(
                            case_out
                        ) is not None
                    )
                ):
                    continue
                jobs.append((
                    case_inp, case_out, f"{label} - {case_id}...", method, True
                ))
        for key, label, method in (
            (
                "interaction",
                "Governing shear-torsion concrete-strut interaction",
                "_torsion_interaction_example",
            ),
            (
                "minimum_reinforcement",
                "Governing shear-torsion minimum-reinforcement screen",
                "_torsion_minimum_reinforcement_example",
            ),
        ):
            if self.profile.key != "Audit":
                continue
            selection = self._selected_torsion_subchecks.get(key)
            if not isinstance(selection, Mapping):
                continue
            for case_inp, case_out in plastic_contexts:
                if self._case_id(case_inp, "plastic") != selection.get("case_id"):
                    continue
                case_id = presentation.action_set(case_inp, "plastic")["id"] or "-"
                jobs.append((
                    case_inp,
                    case_out,
                    f"{label} - {case_id}...",
                    method,
                    True,
                ))
                break
        for case_inp, case_out in self._case_contexts("elastic"):
            case_id = presentation.action_set(case_inp, "elastic")["id"] or "-"
            if (
                "elastic" in case_out
                and (
                    self._selected_family("elastic", case_inp) is not None
                    or self._needs_diagnostic_chapter(
                        "elastic", case_out["elastic"]
                    )
                )
            ):
                jobs.append((
                    case_inp, case_out,
                    f"Elastic stresses - {case_id}...", "_elastic", True,
                ))
            if (
                any(
                    item.get("case_id") == self._case_id(case_inp, "elastic")
                    for item in self._selected_crack_examples
                )
                or (
                    isinstance(self._selected_cracking_threshold, Mapping)
                    and self._selected_cracking_threshold.get("case_id")
                    == self._case_id(case_inp, "elastic")
                )
                or (
                    isinstance(self._selected_crack_comparison, Mapping)
                    and self._selected_crack_comparison.get("case_id")
                    == self._case_id(case_inp, "elastic")
                )
            ):
                jobs.append((
                    case_inp, case_out,
                    f"Cracking - {case_id}...", "_cracking", False,
                ))

        try:
            for index, (case_inp, case_out, label, method, new_page) in enumerate(jobs):
                self.inp, self.out = case_inp, case_out
                fraction = 0.42 + 0.5 * (index / max(len(jobs), 1))
                self._tick(fraction, label)
                if new_page and self.profile.key == "Audit":
                    self.flow.append(NotAtTopPageBreak())
                getattr(self, method)()
        finally:
            self.inp, self.out = self._base_inp, self._base_out
        if (
            isinstance(self._selected_heightened_crack_control, Mapping)
            and self._selected_heightened_crack_control.get("result_key")
            == "heightened_crack_control"
            and isinstance(
                self._base_out.get("heightened_crack_control"), Mapping
            )
        ):
            if self.profile.key == "Audit":
                self.flow.append(NotAtTopPageBreak())
            self._heightened_crack_control()
        if self._base_out.get("fatigue") is not None:
            self._tick(0.88, "Grouped fatigue...")
            if self.profile.key == "Audit":
                self.flow.append(NotAtTopPageBreak())
            self._fatigue()
        if self.qa_appendix:
            self._appendix()

        self._write_pdf()

    def _write_pdf(self):
        """Write the already assembled presentation flow without recalculation."""

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
        if pdfmetrics.stringWidth(header, _FONT, 7.5) > 136 * mm:
            summary = []
            for family in active_families:
                summary.append(
                    f"{family.title()} {len(self._case_contexts(family))}"
                )
            fatigue_count = len(fatigue_presentation.items(
                self._base_out.get("fatigue"), "spectra"
            ))
            if fatigue_count:
                summary.append(f"Fatigue {fatigue_count}")
            header = (
                f"Project: {project}  |  Section: {section}  |  Cases: "
                + "; ".join(summary)
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
    def _brief_input_summary(self):
        """Publish a compact, auditable inventory of every active report input."""

        self._h1("Analysis input summary")
        self._small(
            "This compact inventory records the geometry, assigned materials, "
            "actions and active analysis settings used for the reported results. "
            "Generate Standard or Audit for calculation derivations and expanded "
            "provenance."
        )
        self._brief_geometry_summary()
        self._brief_material_summary()
        self._brief_actions_summary()
        self._brief_settings_summary()
        self._brief_warning_summary()

    def _brief_geometry_summary(self):
        """Publish every concrete-ring and reinforcement input row compactly."""

        inp = self._base_inp
        self._h2("Geometry and reinforcement", reserve=80)
        ring_rows = [["Ring", "Point", "x (mm)", "y (mm)"]]
        rings = [("Outer", inp.get("outer") or [])]
        rings.extend(
            (f"Void {index}", ring)
            for index, ring in enumerate(inp.get("holes") or [], 1)
        )
        for ring_label, ring in rings:
            for point_index, point in enumerate(ring, 1):
                ring_rows.append([
                    ring_label,
                    point_index,
                    _fmt(point[0] * _MM, 3),
                    _fmt(point[1] * _MM, 3),
                ])
        if len(ring_rows) == 1:
            ring_rows.append(["Concrete", "-", "Not supplied", "Not supplied"])
        self._table(
            ring_rows,
            [45 * mm, 25 * mm, 45 * mm, 45 * mm],
            keep=False,
            repeat_cols=2,
            caption="Concrete outline and void coordinates",
        )

        element_rows = [[
            "Element", "x (mm)", "y (mm)", "Area (mm<super>2</super>)",
            "Diameter / size basis", "Material", "Fatigue detail",
        ]]

        def append_elements(kind, points, records, prefix):
            retained = list(records or [])
            if len(retained) != len(points):
                retained = [
                    {
                        "id": f"{prefix}{index}",
                        "x_mm": point[0] * _MM,
                        "y_mm": point[1] * _MM,
                        "area_mm2": point[2],
                        "diameter_mm": None,
                        "size_mode": "Area (diameter not retained)",
                        "material_id": "-",
                        "fatigue_detail_id": "",
                    }
                    for index, point in enumerate(points, 1)
                ]
            for record in retained:
                diameter = record.get("diameter_mm")
                diameter_text = (
                    "not retained"
                    if diameter is None
                    else f"{_fmt(diameter, 3)} mm"
                )
                size_mode = str(record.get("size_mode") or "-")
                element_rows.append([
                    _html_escape(
                        f"{kind} {record.get('id') or '-'}"
                    ),
                    _fmt(record.get("x_mm"), 3),
                    _fmt(record.get("y_mm"), 3),
                    _fmt(record.get("area_mm2"), 3),
                    _LiteralReportText(f"{diameter_text}; {size_mode}"),
                    _html_escape(str(record.get("material_id") or "-")),
                    _html_escape(str(record.get("fatigue_detail_id") or "-")),
                ])

        append_elements(
            "Bar", inp.get("bars") or [], inp.get("bar_elements"), "R"
        )
        append_elements(
            "Tendon", inp.get("tendons") or [], inp.get("tendon_elements"), "P"
        )
        if len(element_rows) == 1:
            element_rows.append(["None", "-", "-", "-", "-", "-", "-"])
        self._table(
            element_rows,
            [24 * mm, 22 * mm, 22 * mm, 28 * mm, 35 * mm, 20 * mm, 19 * mm],
            font=7.2,
            keep=False,
            repeat_cols=1,
            caption="Reinforcement and tendon layout with assignments",
        )

    def _brief_material_summary(self):
        """Publish assigned material identities and their key entered properties."""

        inp = self._base_inp
        fatigue = self._base_out.get("fatigue") or {}
        fatigue_checks = fatigue.get("checks") or {}
        reinforcement_fatigue = bool(
            (inp.get("fatigue_on") or self._base_out.get("fatigue") is not None)
            and fatigue_checks.get(
                "reinforcement", inp.get("fatigue_check_steel")
            )
        )
        self._h2("Assigned materials and key properties", reserve=80)
        rows = [["Family / ID", "Assignment", "Name / preset / source", "Key properties"]]
        concrete = inp.get("concrete")
        if concrete is not None:
            concrete_source = inp.get("concrete_preset") or inp.get("conc_preset")
            concrete_2023 = "2023" in str(concrete_source or "")
            concrete_properties = [
                f"f<sub>ck</sub> = {_fmt(concrete.fck, 3)} MPa",
                f"gamma<sub>c</sub> = {_fmt(concrete.gamma_c, 3)}",
            ]
            if concrete_2023:
                concrete_properties.extend([
                    "eta<sub>cc</sub> = "
                    + _fmt(inp.get("concrete_eta_cc"), 6),
                    "k<sub>tc</sub> = "
                    + _fmt(inp.get("concrete_k_tc"), 2),
                    (
                        "alpha<sub>cc</sub> = eta<sub>cc</sub> "
                        "k<sub>tc</sub> = "
                        + _fmt(concrete.alpha_cc, 6)
                    ),
                ])
            else:
                concrete_properties.append(
                    f"alpha<sub>cc</sub> = {_fmt(concrete.alpha_cc, 3)}"
                )
            concrete_properties.extend([
                f"curve {concrete.curve}",
                (
                    f"eps<sub>c2</sub> / eps<sub>cu2</sub> = "
                    f"{_fmt(concrete.eps_c2 * 1000, 3)} / "
                    f"{_fmt(concrete.eps_cu2 * 1000, 3)} permille"
                ),
            ])
            if concrete.curve == 2:
                concrete_properties.append(f"n = {_fmt(concrete.n, 3)}")
            rows.append([
                "Concrete",
                "Concrete rings",
                _html_escape(str(concrete_source or "User-defined")),
                "; ".join(concrete_properties),
            ])

        def catalogue_items(catalogue):
            items = (catalogue or {}).get("items", [])
            if isinstance(items, Mapping):
                return [items]
            return [item for item in items if isinstance(item, Mapping)]

        bar_elements = list(inp.get("bar_elements") or [])
        mild_ids = list(dict.fromkeys(
            str(item.get("material_id"))
            for item in bar_elements
            if item.get("material_id") not in (None, "")
        ))
        if inp.get("shear_on") or inp.get("torsion_on"):
            capacity_id = inp.get("capacity_steel_material_id")
            if capacity_id not in (None, "") and str(capacity_id) not in mild_ids:
                mild_ids.append(str(capacity_id))
        mild_records = {
            str(item.get("id")): item
            for item in catalogue_items(inp.get("mild_material_catalog"))
        }
        mild_laws = inp.get("mild_materials") or {}
        if not mild_ids and (inp.get("bars") or inp.get("shear_on") or inp.get("torsion_on")):
            mild_ids = ["-"]
            mild_records["-"] = {
                "id": "-", "name": "Reinforcement",
                "preset": inp.get("mild_preset") or "User-defined",
                "description": "",
            }
            mild_laws = {"-": inp.get("steel")}
        for material_id in mild_ids:
            record = mild_records.get(material_id, {})
            law = mild_laws.get(material_id)
            if law is None and len(mild_ids) == 1:
                law = inp.get("steel")
            assignments = [
                str(item.get("id") or "-")
                for item in bar_elements
                if str(item.get("material_id")) == material_id
            ]
            assignment_text = (
                "Bars " + ", ".join(assignments) if assignments else "No bar row"
            )
            if str(inp.get("capacity_steel_material_id")) == material_id:
                assignment_text += "; member-check reference"
            source_parts = [
                str(record.get(key) or "").strip()
                for key in ("name", "preset", "description")
            ]
            source_text = "; ".join(part for part in source_parts if part) or "User-defined"
            properties = "Material definition unavailable"
            if law is not None:
                curve = int(law.curve)
                strengths = (
                    f"f<sub>ytk</sub> / f<sub>yck</sub> = "
                    f"{_fmt(law.fytk, 3)} / {_fmt(law.fyck, 3)} MPa"
                )
                factors = f"gamma<sub>y</sub> = {_fmt(law.gamma_y, 3)}"
                if curve in (1, 3):
                    strengths = (
                        f"f<sub>ytk</sub> / f<sub>yck</sub> / "
                        f"f<sub>utk</sub> = {_fmt(law.fytk, 3)} / "
                        f"{_fmt(law.fyck, 3)} / {_fmt(law.futk, 3)} MPa"
                    )
                    factors = (
                        f"gamma<sub>y</sub> / gamma<sub>u</sub> / "
                        f"gamma<sub>E</sub> = {_fmt(law.gamma_y, 3)} / "
                        f"{_fmt(law.gamma_u, 3)} / {_fmt(law.gamma_E, 3)}"
                    )
                law_parts = [
                    f"curve {curve}",
                    strengths,
                    f"E<sub>s</sub> = {_fmt(law.Es / 1000, 1)} GPa",
                    f"eps<sub>ut</sub> = {_fmt(law.eut * 1000, 3)} permille",
                    factors,
                ]
                if curve == 3:
                    law_parts.extend([
                        f"k = {_fmt(law.k, 3)}",
                        (
                            f"eps<sub>0t</sub> / eps<sub>0c</sub> = "
                            f"{_fmt(law.ey0t * 1000, 3)} / "
                            f"{_fmt(law.ey0c * 1000, 3)} permille"
                        ),
                    ])
                law_parts.append(
                    "compression branch active = "
                    + self._brief_switch(law.active_in_compression)
                )
                properties = "; ".join(law_parts)
            rows.append([
                _html_escape(f"Mild / {material_id}"),
                _html_escape(assignment_text),
                _html_escape(source_text),
                properties,
            ])

        tendon_elements = list(inp.get("tendon_elements") or [])
        prestress_ids = list(dict.fromkeys(
            str(item.get("material_id"))
            for item in tendon_elements
            if item.get("material_id") not in (None, "")
        ))
        prestress_records = {
            str(item.get("id")): item
            for item in catalogue_items(inp.get("prestress_material_catalog"))
        }
        prestress_laws = inp.get("prestress_materials") or {}
        if not prestress_ids and inp.get("tendons"):
            prestress_ids = ["-"]
            prestress_records["-"] = {
                "id": "-", "name": "Prestressing steel",
                "preset": inp.get("prestress_preset") or "User-defined",
                "description": "",
            }
            prestress_laws = {"-": inp.get("prestress")}
        for material_id in prestress_ids:
            record = prestress_records.get(material_id, {})
            law = prestress_laws.get(material_id)
            if law is None and len(prestress_ids) == 1:
                law = inp.get("prestress")
            assignments = [
                str(item.get("id") or "-")
                for item in tendon_elements
                if str(item.get("material_id")) == material_id
            ]
            source_parts = [
                str(record.get(key) or "").strip()
                for key in ("name", "preset", "description")
            ]
            source_text = "; ".join(part for part in source_parts if part) or "User-defined"
            properties = "Material definition unavailable"
            if law is not None:
                if law.curve in (1, 2, 3, 4, 5):
                    properties = (
                        f"built-in fixed curve {law.curve}; E<sub>p</sub> = "
                        f"{_fmt(law.Es / 1000, 1)} GPa; "
                        f"eps<sub>p,0</sub> / eps<sub>ut</sub> = "
                        f"{_fmt(law.IS * 1000, 3)} / "
                        f"{_fmt(law.rupture_strain * 1000, 3)} permille; "
                        f"gamma<sub>y</sub> = {_fmt(law.gamma_y, 3)}"
                    )
                    if reinforcement_fatigue and record.get("fytk") is not None:
                        properties += (
                            "; fatigue proof-stress input "
                            "f<sub>p0.1k</sub> = "
                            f"{_fmt(record.get('fytk'), 3)} MPa "
                            "(fatigue yield/proof check input; not a "
                            "fixed-curve plastic-law field)"
                        )
                else:
                    law_parts = [
                        f"curve {law.curve}; f<sub>p0.1k</sub> / "
                        f"f<sub>pk</sub> = {_fmt(law.fytk, 3)} / "
                        f"{_fmt(law.futk, 3)} MPa; E<sub>p</sub> = "
                        f"{_fmt(law.Es / 1000, 1)} GPa; "
                        f"eps<sub>p,0</sub> = "
                        f"{_fmt(law.IS * 1000, 3)} permille",
                        f"eps<sub>ut</sub> = {_fmt(law.eut * 1000, 3)} permille",
                        f"gamma<sub>y</sub> / gamma<sub>u</sub> / "
                        f"gamma<sub>E</sub> = {_fmt(law.gamma_y, 3)} / "
                        f"{_fmt(law.gamma_u, 3)} / "
                        f"{_fmt(law.gamma_E, 3)}",
                    ]
                    if law.curve == 7:
                        law_parts.extend([
                            f"k = {_fmt(law.k, 3)}",
                            (
                                f"eps<sub>0t</sub> = "
                                f"{_fmt(law.ey0t * 1000, 3)} permille"
                            ),
                        ])
                    properties = "; ".join(law_parts)
            rows.append([
                _html_escape(f"Prestress / {material_id}"),
                _html_escape("Tendons " + ", ".join(assignments)),
                _html_escape(source_text),
                properties,
            ])
        self._table(
            rows,
            [29 * mm, 38 * mm, 48 * mm, 55 * mm],
            font=7.2,
            keep=False,
            repeat_cols=1,
            caption="Assigned material definitions and governing properties",
        )

    def _brief_actions_summary(self):
        """Reuse the canonical action-table publication without derivations."""

        self._h2("Actions", reserve=85)
        self._loads_block()

    @staticmethod
    def _brief_switch(value):
        return "yes" if bool(value) else "no"

    @staticmethod
    def _brief_auto_dimension(value, *, decimals=1, unit="mm"):
        if value in (None, ""):
            return "auto / derived"
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return _html_escape(str(value))
        if math.isclose(number, 0.0, rel_tol=0.0, abs_tol=0.0):
            return "auto / derived"
        return f"{_fmt(number, decimals)} {unit}".strip()

    @staticmethod
    def _brief_transverse_leg_spacing(value):
        """Format an explicit leg-spacing screen without treating zero as auto."""

        if value in (None, ""):
            return "gross-web upper-bound screen"
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return _html_escape(str(value))
        if math.isclose(number, 0.0, rel_tol=0.0, abs_tol=0.0):
            return "gross-web upper-bound screen"
        return f"{_fmt(number, 1)} mm"

    def _brief_settings_table(self, rows, *, caption):
        """Publish setting/value rows in two compact, deterministic columns."""

        body = list(rows[1:])
        paired = [["Setting", "Value", "Setting", "Value"]]
        for index in range(0, len(body), 2):
            left = body[index]
            right = body[index + 1] if index + 1 < len(body) else ["", ""]
            paired.append([*left, *right])
        self._table(
            paired,
            [42 * mm, 43 * mm, 42 * mm, 43 * mm],
            font=7.2,
            keep=False,
            repeat_cols=0,
            caption=caption,
        )

    def _brief_settings_summary(self):
        """Publish active numerical, crack, resistance and fatigue settings."""

        inp = self._base_inp
        plastic_results = self._result_values("plastic")
        elastic_results = self._result_values("elastic")
        basis_key = inp.get("sls_code")
        basis_2023 = False
        basis_dk_coarse = False
        try:
            resolved_basis = get_design_basis(basis_key)
            basis = resolved_basis.label
            basis_2023 = resolved_basis.key is DesignBasisKey.PUBLISHED_2023
            basis_dk_coarse = (
                resolved_basis.key is DesignBasisKey.FIRST_GEN_DK_NA_2024
            )
        except (TypeError, ValueError):
            basis = basis_key or "-"
        self._h2("Analysis settings", reserve=75)
        rows = [["Setting", "Value"]]
        rows.append(["Analysis mode", _html_escape(str(inp.get("mode") or "-"))])
        if plastic_results:
            check_util = inp.get(
                "check_util", plastic_results[0].get("check_util", True)
            )
            rows.extend([
                ["Neutral-axis sweep start", f"{_fmt(inp.get('v_min'), 0)}&#176;"],
                ["Neutral-axis sweep end", f"{_fmt(inp.get('v_max'), 0)}&#176;"],
                ["Neutral-axis maximum increment", f"{_fmt(inp.get('v_inc'), 0)}&#176;"],
                ["Applied-moment utilisation", self._brief_switch(check_util)],
                ["N-M interaction diagrams", self._brief_switch(inp.get("interaction"))],
            ])
        if elastic_results or inp.get("fatigue_on"):
            rows.extend([
                ["Concrete elastic modulus E<sub>c</sub>", f"{_fmt(inp.get('conc_Ec'), 3)} GPa"],
                ["Creep coefficient phi", _fmt(inp.get("el_phi"), 3)],
            ])
        if elastic_results:
            rows.extend([
                ["Ordinary SLS design basis", _html_escape(str(basis))],
                [
                    "Mean tensile strength f<sub>ctm</sub>",
                    f"{_fmt(inp.get('sls_fctm'), 3)} MPa",
                ],
            ])
        elif inp.get("minimum_reinforcement_on"):
            rows.append([
                "Mean tensile strength f<sub>ctm</sub>",
                f"{_fmt(inp.get('sls_fctm'), 3)} MPa",
            ])
        self._brief_settings_table(
            rows, caption="General numerical analysis settings",
        )

        crack_requested = bool(inp.get("sls_cw")) or any(
            result.get("show_cw") for result in elastic_results
        )
        if crack_requested or inp.get("sls_heightened_on"):
            self._h2("Crack-control settings", reserve=75)
            crack_rows = [["Setting", "Value"]]
            permitted = inp.get("sls_permitted_crack_width_mm")
            crack_rows.extend([
                ["Ordinary crack-width design basis", _html_escape(str(basis))],
                [
                    "Permitted crack width w<sub>k</sub>",
                    "not specified" if permitted is None else f"{_fmt(permitted, 3)} mm",
                ],
                [
                    "Crack-width diameter",
                    "per-element values" if not inp.get("sls_phi")
                    else f"{_fmt(inp.get('sls_phi'), 3)} mm global override",
                ],
            ])
            if crack_requested and inp.get("bars"):
                crack_rows.extend([
                    [
                        "Mild-steel bond selection",
                        _html_escape(
                            str(inp.get("sls_bond") or "not retained")
                        ),
                    ],
                    [
                        "Mild-steel bond coefficient k<sub>1</sub>",
                        _fmt(inp.get("sls_k1"), 3),
                    ],
                ])
            crack_member = next(
                (
                    result.get("crack_member")
                    for result in elastic_results
                    if result.get("show_cw") and result.get("crack_member")
                ),
                None,
            )
            if basis_dk_coarse and crack_member:
                crack_rows.append([
                    "Member type", _html_escape(str(crack_member)),
                ])
            if inp.get("tendons") and basis_2023:
                tendon_xi = inp.get("sls_tendon_xi")
                try:
                    tendon_xi = float(tendon_xi)
                except (TypeError, ValueError, OverflowError):
                    tendon_xi = 0.0
                crack_rows.append([
                    "Bonded-tendon bond-strength ratio xi",
                    (
                        _fmt(tendon_xi, 3)
                        if math.isfinite(tendon_xi) and tendon_xi > 0.0
                        else "not set"
                    ),
                ])
            if inp.get("sls_heightened_on"):
                crack_rows.extend([
                    ["DK heightened crack control", "fine and coarse calculated together"],
                    ["Heightened reference case", _html_escape(str(inp.get("sls_heightened_reference_case") or "-"))],
                    ["Reinforcement surface", _html_escape(str(inp.get("sls_heightened_reinforcement_surface") or "-"))],
                    ["Effective tensile strength f<sub>ct,eff</sub>", f"{_fmt(inp.get('sls_heightened_effective_tensile_strength_mpa'), 3)} MPa"],
                    ["Fine effective tension area A<sub>c,eff</sub>", f"{_fmt(inp.get('sls_heightened_fine_effective_tension_area_mm2'), 3)} mm<super>2</super>"],
                    ["Coarse effective tension area A<sub>c,eff</sub>", f"{_fmt(inp.get('sls_heightened_coarse_effective_tension_area_mm2'), 3)} mm<super>2</super>"],
                ])
                heightened = self._base_out.get("heightened_crack_control") or {}
                if isinstance(heightened, Mapping) and heightened:
                    crack_rows.extend([
                        ["Derived bar diameter", f"{_fmt(heightened.get('bar_diameter_mm'), 3)} mm; {_html_escape(str(heightened.get('diameter_source') or '-'))}"],
                        ["Derived reinforcement modulus", f"{_fmt(heightened.get('reinforcement_modulus_mpa'), 1)} MPa"],
                        ["Derived provided reinforcement area", f"{_fmt(heightened.get('provided_reinforcement_area_mm2'), 3)} mm<super>2</super>"],
                    ])
            self._brief_settings_table(
                crack_rows,
                caption="Ordinary and heightened crack-control settings",
            )

        resistance_active = any(inp.get(key) for key in (
            "shear_on", "torsion_on", "combined_on",
            "minimum_reinforcement_on", "transverse_detailing_on",
            "clear_spacing_on",
        ))
        if resistance_active:
            self._h2("Shear, torsion and detailing settings", reserve=75)
            resistance_rows = [["Setting", "Value"]]
            shear_active = bool(inp.get("shear_on"))
            shear_links_active = bool(
                shear_active and inp.get("shear_links") is True
            )
            minimum_active = bool(inp.get("minimum_reinforcement_on"))
            transverse_active = bool(inp.get("transverse_detailing_on"))
            clear_active = bool(inp.get("clear_spacing_on"))
            effective_shear_method = (
                inp.get("combined_method")
                if inp.get("combined_on")
                else inp.get("shear_method")
            )
            shear_2023 = bool(
                shear_active and "2023" in str(effective_shear_method or "")
            )
            shear_2023_links = bool(shear_2023 and shear_links_active)
            detailing_2023 = bool(
                transverse_active
                and inp.get("detailing_edition") == detailing.EC2_2023
            )
            if inp.get("combined_on"):
                resistance_rows.extend([
                    ["Combined M-V-T", "yes"],
                    ["Combined shared method", _html_escape(str(inp.get("combined_method") or "-"))],
                    ["Independent M and V longitudinal steel", self._brief_switch(inp.get("combined_mv_independent"))],
                ])
            if shear_active:
                resistance_rows.extend([
                    ["Shear method", _html_escape(str(effective_shear_method or "-"))],
                    ["V<sub>x</sub> web width", self._brief_auto_dimension(inp.get("shear_vx_bw"))],
                    ["V<sub>y</sub> web width", self._brief_auto_dimension(inp.get("shear_vy_bw"))],
                ])
                if shear_2023:
                    resistance_rows.append([
                        "Shear aggregate D<sub>lower</sub>",
                        self._brief_auto_dimension(inp.get("shear_dlower")),
                    ])
            if inp.get("torsion_on"):
                resistance_rows.extend([
                    ["Torsion method", _html_escape(str(inp.get("torsion_method") or "-"))],
                    ["Torsion wall thickness t<sub>ef</sub>", self._brief_auto_dimension(inp.get("torsion_tef"))],
                    ["Concrete tensile factor gamma<sub>ct</sub>", _fmt(inp.get("torsion_gamma_ct"), 3)],
                    [
                        "Requested nu<sub>t</sub> = nu<sub>v</sub> detailing allowance",
                        self._brief_switch(inp.get("torsion_nu_v") is True),
                    ],
                    ["Subdivide torsion tube", self._brief_switch(inp.get("torsion_subdivide"))],
                ])
                if inp.get("torsion_subdivide"):
                    subrects = list(inp.get("torsion_subrects") or [])
                    if not subrects:
                        count = int(inp.get("torsion_nsub") or 0)
                        subrects = [
                            (
                                inp.get(f"torsion_sub_x{index}"),
                                inp.get(f"torsion_sub_y{index}"),
                                inp.get(f"torsion_sub_b{index}"),
                                inp.get(f"torsion_sub_h{index}"),
                            )
                            for index in range(count)
                        ]
                    for index, (x, y, width, height) in enumerate(subrects, 1):
                        resistance_rows.append([
                            f"Torsion sub-tube {index}",
                            (
                                f"x / y / b / h = {_fmt(x, 1)} / "
                                f"{_fmt(y, 1)} / {_fmt(width, 1)} / "
                                f"{_fmt(height, 1)} mm"
                            ),
                        ])
            member_transverse_active = bool(
                shear_active or inp.get("torsion_on")
            )
            shared_links = inp.get("shear_links") is True
            if member_transverse_active:
                resistance_rows.extend([
                    ["Shared links / closed torsion stirrup present", self._brief_switch(shared_links)],
                    ["Member-check reinforcing material", _html_escape(str(inp.get("capacity_steel_material_id") or "-"))],
                    ["Compression-strut cot theta range", f"{_fmt(inp.get('strut_cot_min'), 2)} to {_fmt(inp.get('strut_cot_max'), 2)}"],
                ])
            if member_transverse_active and shared_links:
                resistance_rows.extend([
                    ["Closed-link diameter", self._brief_auto_dimension(inp.get("shear_link_dia"))],
                    ["Closed-link longitudinal spacing", self._brief_auto_dimension(inp.get("shear_link_s"))],
                    ["Closed-link characteristic yield", self._brief_auto_dimension(inp.get("shear_fywk"), decimals=1, unit="MPa")],
                ])
                if shear_links_active:
                    resistance_rows.append([
                        "Effective V<sub>x</sub> / V<sub>y</sub> link legs",
                        f"{_fmt(inp.get('shear_vx_link_legs'), 1)} / "
                        f"{_fmt(inp.get('shear_vy_link_legs'), 1)}",
                    ])
            if minimum_active or transverse_active:
                resistance_rows.extend([
                    ["Minimum reinforcement", self._brief_switch(minimum_active)],
                    ["Shear/torsion link detailing", self._brief_switch(transverse_active)],
                ])
            if minimum_active or transverse_active or clear_active:
                resistance_rows.append([
                    "Detailing edition",
                    _html_escape(str(inp.get("detailing_edition") or "-")),
                ])
            if minimum_active or transverse_active:
                resistance_rows.append([
                    "Detailing member type",
                    _html_escape(str(inp.get("detailing_member_type") or "-")),
                ])
            if minimum_active:
                resistance_rows.extend([
                    ["Section cut direction", _html_escape(str(inp.get("detailing_cut_direction") or "-"))],
                    ["Modelled reinforcement direction", _modelled_direction_report_label(cut_direction=inp.get("detailing_cut_direction"), alias=inp.get(modelled_direction.ALIAS_KEY))],
                ])
            if detailing_2023 or shear_2023_links:
                resistance_rows.append([
                    "Link reinforcement ductility class",
                    _html_escape(str(inp.get("transverse_ductility_class") or "-")),
                ])
            if detailing_2023:
                resistance_rows.append([
                    "2023 minimum-ratio ductility reduction",
                    self._brief_switch(
                        inp.get("transverse_apply_ductility_reduction")
                    ),
                ])
            if transverse_active and shear_links_active:
                resistance_rows.extend([
                    ["Maximum V<sub>x</sub>-leg spacing along y", self._brief_transverse_leg_spacing(inp.get("shear_vx_transverse_leg_spacing"))],
                    ["Maximum V<sub>y</sub>-leg spacing along x", self._brief_transverse_leg_spacing(inp.get("shear_vy_transverse_leg_spacing"))],
                ])
            if clear_active:
                resistance_rows.extend([
                    ["Clear-spacing check", "section-wide"],
                    [
                        "Upper aggregate size D<sub>upper</sub>",
                        f"{_fmt(inp.get('detailing_d_upper'), 1)} mm",
                    ],
                    ["Tendons included in spacing", self._brief_switch(inp.get("detailing_include_tendons"))],
                ])
            self._brief_settings_table(
                resistance_rows,
                caption="Active shear, torsion and detailing settings",
            )

        fatigue = self._base_out.get("fatigue")
        if inp.get("fatigue_on") or fatigue is not None:
            self._h2("Grouped fatigue settings", reserve=75)
            fatigue = fatigue or {}
            checks = fatigue.get("checks") or {}
            factors = fatigue.get("partial_factors") or {}
            concrete = fatigue.get("concrete_parameters") or {}
            basis = fatigue.get("basis") or inp.get(fatigue_inputs.BASIS_KEY) or {}
            fatigue_rows = [["Setting", "Value"]]
            edition = fatigue.get("edition") or inp.get("fatigue_edition") or "-"
            reinforcement_fatigue = bool(
                checks.get("reinforcement", inp.get("fatigue_check_steel"))
            )
            concrete_fatigue = bool(
                checks.get("concrete", inp.get("fatigue_check_concrete"))
            )
            concrete_method = (
                fatigue.get("concrete_method")
                or inp.get("fatigue_concrete_method")
                or fatigue_core.CONCRETE_MINER
            )
            solver_edition = str(fatigue.get("solver_edition") or "")
            if not solver_edition:
                try:
                    solver_edition = get_design_basis(
                        fatigue.get("basis_key") or inp.get("fatigue_edition")
                    ).label
                except (TypeError, ValueError):
                    solver_edition = str(edition)
            concrete_2023 = "2023" in solver_edition
            fatigue_rows.extend([
                ["Fatigue edition", _html_escape(str(edition))],
                ["Reinforcement fatigue", self._brief_switch(reinforcement_fatigue)],
                ["Concrete fatigue", self._brief_switch(concrete_fatigue)],
                ["Action factor gamma<sub>Ff</sub>", _fmt(factors.get("gamma_ff", inp.get("fatigue_gamma_ff")), 3)],
            ])
            if reinforcement_fatigue:
                fatigue_rows.append([
                    "Reinforcement factor gamma<sub>s</sub>",
                    _fmt(factors.get("gamma_s", inp.get("fatigue_gamma_s")), 3),
                ])
            if concrete_fatigue:
                fatigue_rows.extend([
                    [
                        "Concrete factor gamma<sub>c,fat</sub>",
                        _fmt(
                            factors.get("gamma_c", inp.get("fatigue_gamma_c")),
                            3,
                        ),
                    ],
                    [
                        "Concrete fatigue method",
                        _html_escape(str(concrete_method)),
                    ],
                    [
                        "Concrete age t<sub>0</sub>",
                        f"{_fmt(fatigue.get('t0_days', inp.get('fatigue_t0_days')), 2)} days",
                    ],
                    [
                        "beta<sub>cc</sub>(t<sub>0</sub>)",
                        _fmt(
                            concrete.get(
                                "beta_cc_t0", inp.get("fatigue_beta_cc_t0")
                            ),
                            4,
                        ),
                    ],
                ])
                if not concrete_2023:
                    fatigue_rows.append([
                        "Concrete fatigue k<sub>1</sub>",
                        _fmt(
                            concrete.get(
                                "k1", inp.get("fatigue_concrete_k1")
                            ),
                            3,
                        ),
                    ])
                if concrete_method in fatigue_core.CONCRETE_MINER_METHODS:
                    fatigue_rows.append([
                        "Concrete fatigue C",
                        _fmt(
                            concrete.get(
                                "c", inp.get("fatigue_concrete_c")
                            ),
                            3,
                        ),
                    ])
            fatigue_rows.extend([
                ["Spectrum method", _html_escape(str(basis.get("method") or "-"))],
                ["Spectrum basis notes", _html_escape(str(basis.get("notes") or "-"))],
            ])
            mixed_reinforcement = bool(inp.get("bar_elements")) and bool(
                inp.get("tendon_elements")
            )
            detail_basis = (
                tuple(fatigue.get("fatigue_detail_basis") or ())
                if reinforcement_fatigue
                else ()
            )
            if reinforcement_fatigue and not detail_basis:
                assigned_ids = [
                    str(record.get("fatigue_detail_id") or "").strip()
                    for record in (
                        list(inp.get("bar_elements") or [])
                        + list(inp.get("tendon_elements") or [])
                    )
                    if isinstance(record, Mapping)
                ]
                assigned_ids = [detail_id for detail_id in assigned_ids if detail_id]
                try:
                    source_catalog = fatigue_inputs.normalise_catalog(
                        inp.get(fatigue_inputs.DETAIL_CATALOG_KEY),
                        assigned_ids=assigned_ids,
                    )
                    source_details = fatigue_inputs.entry_map(source_catalog)
                except (TypeError, ValueError):
                    source_details = {}
                seen_detail_ids = set()
                ordered_details = []
                for detail_id in assigned_ids:
                    if (
                        detail_id not in source_details
                        or detail_id in seen_detail_ids
                    ):
                        continue
                    seen_detail_ids.add(detail_id)
                    ordered_details.append(source_details[detail_id])
                detail_basis = tuple(ordered_details)
            for detail in detail_basis:
                bend_reduction = bool(detail.get("bend_reduction"))
                modifiers = [
                    "kind = "
                    + _html_escape(str(detail.get("kind") or "-")),
                    "stress model = "
                    + _html_escape(str(detail.get("stress_model") or "-")),
                    "bend reduction = " + self._brief_switch(bend_reduction),
                ]
                if bend_reduction:
                    modifiers.append(
                        "mandrel diameter = "
                        f"{_fmt(detail.get('mandrel_diameter_mm'), 3)} mm"
                    )
                if (
                    str(detail.get("kind") or "").strip().lower()
                    == fatigue_inputs.PRESTRESS
                    and mixed_reinforcement
                ):
                    modifiers.extend([
                        "bond ratio xi = "
                        + _fmt(detail.get("bond_ratio_xi"), 3),
                        (
                            "bond-equivalent diameter = "
                            f"{_fmt(detail.get('bond_equivalent_diameter_mm'), 3)} mm"
                        ),
                    ])
                fatigue_rows.append([
                    "Fatigue detail " + _html_escape(str(detail.get("id") or "-")),
                    (
                        _html_escape(str(detail.get("name") or detail.get("preset") or "-"))
                        + "; preset = "
                        + _html_escape(str(detail.get("preset") or "-"))
                        + "; source = "
                        + _html_escape(str(detail.get("source") or "not stated"))
                        + f"; Delta sigma<sub>Rsk</sub> = {_fmt(detail.get('delta_sigma_rsk_mpa'), 3)} MPa; "
                        + f"N* = {_fmt(detail.get('n_star'), 3)}; "
                        + f"k<sub>1</sub> / k<sub>2</sub> = {_fmt(detail.get('k1'), 3)} / {_fmt(detail.get('k2'), 3)}; "
                        + "; ".join(modifiers)
                    ),
                ])
            self._brief_settings_table(
                fatigue_rows,
                caption=(
                    "Grouped fatigue calculation settings and detail definitions"
                ),
            )

    def _brief_warning_summary(self):
        """Retain active calculation warnings without expanding derivations."""

        warnings = []
        for label, payload in (
            ("Fatigue", self._base_out.get("fatigue")),
            ("DK heightened crack control", self._base_out.get("heightened_crack_control")),
        ):
            if not isinstance(payload, Mapping):
                continue
            for key in ("warnings", "errors"):
                for message in payload.get(key) or ():
                    warnings.append((label, str(message)))
        if not warnings:
            return
        self._h2("Warnings retained with the calculation", reserve=90)
        self._table(
            [["Source", "Warning"], *[
                [_html_escape(label), _html_escape(message)]
                for label, message in warnings
            ]],
            [45 * mm, 120 * mm],
            keep=False,
            caption="Warnings relevant to the reported calculation",
        )

    def _brief_governing_register(self):
        """Publish retained critical-example identities after the input inventory."""

        self._h1("Governing calculation register", reserve=130)
        self._p(
            "This rapid-review profile retains every requested result and status "
            "in the overview. The register below identifies the precomputed "
            "globally critical worked examples; no report-side ranking or "
            "calculation is performed. Generate Standard or Audit for the full "
            "numerical derivations."
        )
        rows = [["Calculation", "Selected case / branch"]]
        labels = {
            "plastic": "Plastic capacity",
            "minimum_reinforcement": "Minimum reinforcement",
            "transverse_reinforcement": "Link detailing",
            "shear": "Shear resistance",
            "torsion": "Torsion resistance",
            "combined": "Combined M-V-T",
            "elastic": "Elastic response",
        }
        for family in (
            "plastic",
            "minimum_reinforcement",
            "transverse_reinforcement",
            "shear",
            "torsion",
            "combined",
            "elastic",
        ):
            selected = self._selected_families.get(family)
            if not isinstance(selected, Mapping):
                continue
            if (
                family == "combined"
                and not self._combined_selection_is_authoritative(selected)
            ):
                continue
            identity = str(selected.get("case_id") or "-")
            component = selected.get("component")
            if component is not None:
                identity += " / " + str(component)
            rows.append([labels[family], _html_escape(identity)])
        for selected in self._selected_crack_examples:
            rows.append([
                "Crack width",
                _html_escape(
                    f"{selected.get('case_id') or '-'} / "
                    f"{selected.get('label') or selected.get('branch') or '-'}"
                ),
            ])
        if isinstance(self._selected_crack_comparison, Mapping):
            rows.append([
                "Global permitted crack width",
                "Analysis settings",
            ])
        if isinstance(self._selected_cracking_threshold, Mapping):
            rows.append([
                "Cracking threshold",
                _html_escape(str(
                    self._selected_cracking_threshold.get("case_id") or "-"
                )),
            ])
        if isinstance(self._selected_heightened_crack_control, Mapping):
            rows.append(["DK heightened crack control", "Global result"])
        if self._base_out.get("fatigue") is not None:
            rows.append([
                "Grouped fatigue",
                "Governing reinforcement and concrete results in overview",
            ])
        if len(rows) == 1:
            rows.append(["Worked example selection", "Not available"])
        self._table(rows, [70 * mm, 95 * mm], font=8.5, keep=False)
        self._small(
            "Brief omits complete non-governing derivations, full method theory, "
            "branch inventories, hashes and exhaustive provenance. Figures are a "
            "separate export choice. Audit is evidence depth, not approval, "
            "compliance or certification."
        )

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
                    "Calculation state",
                    _html_escape(m.get("calculation_state", "Not supplied")),
                ],
                [
                    "Input SHA-256",
                    _html_escape(m.get("input_sha256", "Not supplied")),
                ],
                ["Selected basis / methods", _report_basis_summary(self.inp)],
                [
                    "Report profile",
                    self.profile.label,
                ]]
        adoption_warning = _report_adoption_warning(self.inp)
        if adoption_warning:
            rows.append(["Adoption / applicability warning", adoption_warning])
        rows.append(["Profile scope", self.profile.description])
        rows.append(["Detail omitted", self.profile.omitted_detail])
        direction_alias = modelled_direction.normalise_alias(
            self.inp.get(modelled_direction.ALIAS_KEY)
        )
        if direction_alias:
            rows.append([
                "Modelled reinforcement direction",
                _modelled_direction_report_label(
                    cut_direction=self.inp.get("detailing_cut_direction"),
                    alias=direction_alias,
                ),
            ])
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
            self._p(_html_escape(m["comments"]))
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
        self._h1("Section and materials", reserve=240)
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
        self._concrete_section_properties_block()
        # Materials are reported only when the section actually uses them: mild
        # steel when there are bars, prestress when there are tendons.
        self._h2("Concrete", reserve=320)
        self._concrete_block()
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
            self._prestress_initial_block()
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
                        # Legacy tuple-only inputs do not retain the entered bar
                        # diameter.  The report must not reconstruct one from
                        # area and present it as calculation evidence.
                        "diameter_mm": None,
                        "size_mode": "Area (diameter not retained)",
                        "material_id": "-",
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

    def _concrete_section_properties_block(self):
        """Publish exact signed-ring section properties from retained results."""

        properties = self._base_out.get("section_properties") or {}
        rings = properties.get("rings") or []
        net = properties.get("net_concrete") or {}
        if not rings or not net:
            return
        self._h2("Concrete section properties")
        self._small(
            "The outer ring is positive and each clockwise void ring is negative. "
            "The signed ring contributions therefore sum directly to the net "
            "concrete section."
        )
        rows = [[
            "Ring", "Role", "A", "S<sub>x</sub>", "S<sub>y</sub>",
            "S<sub>xx</sub>", "S<sub>yy</sub>", "S<sub>xy</sub>",
        ]]
        for ring in rings:
            rows.append([
                ring["ring_id"], ring["role"], _fmt(ring["area_m2"], 6),
                _fmt(ring["first_x_m3"], 6), _fmt(ring["first_y_m3"], 6),
                _fmt(ring["second_xx_m4"], 6),
                _fmt(ring["second_yy_m4"], 6),
                _fmt(ring["product_xy_m4"], 6),
            ])
        rows.append([
            "Net", "signed sum", _fmt(net["area_m2"], 6),
            _fmt(net["first_x_m3"], 6), _fmt(net["first_y_m3"], 6),
            _fmt(net["second_xx_m4"], 6),
            _fmt(net["second_yy_m4"], 6),
            _fmt(net["product_xy_m4"], 6),
        ])
        self._table(
            rows,
            [17 * mm, 26 * mm, 18 * mm, 20 * mm, 20 * mm,
             22 * mm, 22 * mm, 22 * mm],
            font=6.3,
            keep=False,
            repeat_cols=2,
        )
        area_terms = " + ".join(_fmt(row["area_m2"], 6) for row in rings)
        self._formula(
            "A<sub>c</sub> = &#931; A<sub>j</sub>",
            equation_key="geometry.concrete.net-area",
            ref="Sector exact signed polygon integration by Green's theorem.",
            subst=f"= {area_terms}",
            result=f"= {_fmt(net['area_m2'], 6)} m<super>2</super>",
        )
        self._formula(
            "x<sub>c</sub> = S<sub>x</sub> / A<sub>c</sub>",
            equation_key="geometry.concrete.centroid-x",
            ref="Centroid definition for the retained signed polygon moments.",
            subst=(f"= {_fmt(net['first_x_m3'], 6)} / "
                   f"{_fmt(net['area_m2'], 6)}"),
            result=f"= {_fmt(net['centroid_x_m'], 6)} m",
            references=("geometry.concrete.net-area",),
        )
        self._formula(
            "y<sub>c</sub> = S<sub>y</sub> / A<sub>c</sub>",
            equation_key="geometry.concrete.centroid-y",
            ref="Centroid definition for the retained signed polygon moments.",
            subst=(f"= {_fmt(net['first_y_m3'], 6)} / "
                   f"{_fmt(net['area_m2'], 6)}"),
            result=f"= {_fmt(net['centroid_y_m'], 6)} m",
            references=("geometry.concrete.net-area",),
        )
        self._formula(
            "I<sub>x,c</sub> = S<sub>yy</sub> - A<sub>c</sub> "
            "y<sub>c</sub><super>2</super>",
            equation_key="geometry.concrete.centroidal-ix",
            ref="Parallel-axis transfer of the retained origin moment.",
            subst=(f"= {_fmt(net['second_yy_m4'], 6)} - "
                   f"{_fmt(net['area_m2'], 6)} &#183; "
                   f"{_fmt(net['centroid_y_m'], 6)}<super>2</super>"),
            result=f"= {_fmt(net['ix_centroid_m4'], 6)} m<super>4</super>",
            references=("geometry.concrete.net-area",
                        "geometry.concrete.centroid-y"),
        )
        self._formula(
            "I<sub>y,c</sub> = S<sub>xx</sub> - A<sub>c</sub> "
            "x<sub>c</sub><super>2</super>",
            equation_key="geometry.concrete.centroidal-iy",
            ref="Parallel-axis transfer of the retained origin moment.",
            subst=(f"= {_fmt(net['second_xx_m4'], 6)} - "
                   f"{_fmt(net['area_m2'], 6)} &#183; "
                   f"{_fmt(net['centroid_x_m'], 6)}<super>2</super>"),
            result=f"= {_fmt(net['iy_centroid_m4'], 6)} m<super>4</super>",
            references=("geometry.concrete.net-area",
                        "geometry.concrete.centroid-x"),
        )
        self._formula(
            "I<sub>xy,c</sub> = S<sub>xy</sub> - A<sub>c</sub> "
            "x<sub>c</sub> y<sub>c</sub>",
            equation_key="geometry.concrete.centroidal-ixy",
            ref="Parallel-axis transfer of the retained origin product moment.",
            subst=(f"= {_fmt(net['product_xy_m4'], 6)} - "
                   f"{_fmt(net['area_m2'], 6)} &#183; "
                   f"{_fmt(net['centroid_x_m'], 6)} &#183; "
                   f"{_fmt(net['centroid_y_m'], 6)}"),
            result=f"= {_fmt(net['ixy_centroid_m4'], 6)} m<super>4</super>",
            references=("geometry.concrete.net-area",
                        "geometry.concrete.centroid-x",
                        "geometry.concrete.centroid-y"),
        )

    def _concrete_block(self):
        c = self.inp["concrete"]
        prepared = (
            (self._base_out.get("material_properties") or {}).get("concrete")
        )
        fcd = (
            prepared["design_strength_mpa"]
            if prepared is not None else None
        )
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
        ])
        if fcd is not None:
            rows.append(
                ["Design strength", "f<sub>cd</sub>", f"{_fmt(fcd, 3)} MPa"]
            )
        # Keep the material table with its numerical design-strength equation,
        # while allowing the longer constitutive-law/figure material below to
        # paginate independently.  Wrapping the complete Concrete subsection can
        # exceed a page and lets ReportLab split the table from this equation.
        definition_start = len(self.flow)
        self._table(rows, [60 * mm, 35 * mm, 50 * mm])
        applicability_note = None
        if is_2023 and fcd is not None:
            self._formula(
                "f<sub>cd</sub> = eta<sub>cc</sub> &#183; k<sub>tc</sub> &#183; "
                "f<sub>ck</sub> / gamma<sub>c</sub>",
                equation_key="materials.concrete.fcd",
                equation_variant="2023",
                ref="EN 1992-1-1:2023 &#167;5.1.6(1), Formulae (5.3) and (5.4)",
                subst=f"= {_fmt(self.inp.get('concrete_eta_cc'),6)} &#183; "
                      f"{_fmt(self.inp.get('concrete_k_tc'),2)} &#183; "
                      f"{_fmt(c.fck, 3)} / {_fmt(c.gamma_c, 3)}",
                result=f"= {_fmt(fcd, 3)} MPa")
            if math.isclose(float(self.inp.get("concrete_k_tc") or 0.0), 1.0):
                applicability_note = (
                    "<b>Applicability assumption:</b> k<sub>tc</sub> = 1.00 was "
                    "selected assuming t<sub>ref</sub> &#8804; 28 days for CR/CN "
                    "or &#8804; 56 days for CS and that design loading is not "
                    "expected until at least 3 months after casting, unless the "
                    "governing National Annex states otherwise (5.1.6(1))."
                )
            else:
                applicability_note = (
                    "k<sub>tc</sub> = 0.85 is the general / other-case value stated "
                    "in EN 1992-1-1:2023 5.1.6(1)."
                )
        elif fcd is not None:
            self._formula(
                "f<sub>cd</sub> = alpha<sub>cc</sub> &#183; f<sub>ck</sub> / "
                "gamma<sub>c</sub>",
                equation_key="materials.concrete.fcd",
                equation_variant="2005",
                ref="DS/EN 1992-1-1 &#167;3.1.6, Eq (3.15)",
                subst=f"= {_fmt(c.alpha_cc,3)} &#183; {_fmt(c.fck, 3)} / "
                      f"{_fmt(c.gamma_c, 3)}",
                result=f"= {_fmt(fcd, 3)} MPa")
        if fcd is not None:
            self._keep_measured_calculation_from(definition_start)
        if applicability_note is not None:
            self._small(applicability_note)
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
        prepared = {
            str(item.get("material_id")): item
            for item in (
                (self._base_out.get("material_properties") or {}).get("mild")
                or []
            )
        }
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
            retained = prepared.get(str(material_id))
            fyd = (
                retained["design_yield_mpa"]
                if retained is not None else None
            )
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
                     "yes" if st.active_in_compression else "no"]]
            if fyd is not None:
                rows.append(
                    ["Design yield", "f<sub>yd</sub>", f"{_fmt(fyd, 3)} MPa"]
                )
            self._table(rows, [60 * mm, 35 * mm, 50 * mm])
            source_ref = _steel_standard_reference(item.get("preset"))
            if fyd is not None:
                self._formula(
                    "f<sub>yd</sub> = f<sub>ytk</sub> / gamma<sub>y</sub>",
                    equation_key=f"materials.steel.fyd-{material_index + 1}",
                    ref=(source_ref or
                         "User-defined or generic constitutive law; no "
                         "normative curve source assigned."),
                    subst=f"= {_fmt(st.fytk, 3)} / {_fmt(st.gamma_y, 3)}",
                    result=f"= {_fmt(fyd, 3)} MPa",
                )
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
        prepared = {
            str(item.get("material_id")): item
            for item in (
                (self._base_out.get("material_properties") or {}).get("prestress")
                or []
            )
        }
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
                characteristic_at_rupture = (
                    prepared.get(str(material_id), {}).get(
                        "characteristic_stress_at_rupture_mpa"
                    )
                )
                rows.extend([
                    ["Curve definition", "-", f"Built-in fixed curve {p.curve}"],
                    ["Curve source", "-", "Sector fixed polynomial; normative "
                     "source not assigned"],
                    ["Elastic-analysis modulus", "E<sub>p</sub>",
                     f"{_fmt(p.Es/1000, 1)} GPa"],
                    ["Fixed rupture strain", "eps<sub>ut</sub>",
                     f"{_fmt(p.rupture_strain*1000, 3)} permille"],
                    ["Design factor on fixed workline", "gamma<sub>y</sub>",
                     _fmt(p.gamma_y, 3)],
                ])
                if characteristic_at_rupture is not None:
                    rows.insert(
                        3,
                        ["Characteristic stress at rupture strain",
                         "sigma<sub>p</sub>(eps<sub>ut</sub>)",
                         f"{_fmt(characteristic_at_rupture, 3)} MPa"],
                    )
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

    def _prestress_initial_block(self):
        """Publish the retained strain-to-resultant prestress calculation."""

        payload = self._base_out.get("prestress_initial") or {}
        elements = payload.get("elements") or []
        if not elements:
            return
        self._h2("Initial prestress action")
        state_rows = [[
            "Tendon", "Material", "E<sub>p</sub>", "eps<sub>p,0</sub>",
            "sigma<sub>p,0</sub>", "A<sub>p</sub>", "F<sub>p,0</sub>",
        ]]
        moment_rows = [[
            "Tendon", "x (m)", "y (m)",
            "M<sub>p,x,0</sub> (kNm)", "M<sub>p,y,0</sub> (kNm)",
        ]]
        for row in elements:
            state_rows.append([
                row["element_id"], row.get("material_id") or "-",
                _fmt(row["modulus_mpa"], 1),
                _fmt(row["initial_strain"], 6),
                _fmt(row["locked_in_stress_mpa"], 3),
                _fmt(row["area_mm2"], 1), _fmt(row["force_kn"], 3),
            ])
            moment_rows.append([
                row["element_id"],
                _fmt(row["x_m"], 4), _fmt(row["y_m"], 4),
                _fmt(row["mx_knm"], 3), _fmt(row["my_knm"], 3),
            ])
        self._table(
            state_rows,
            [20 * mm, 22 * mm, 23 * mm, 24 * mm, 27 * mm, 22 * mm,
             27 * mm],
            font=6.8,
            keep=False,
            repeat_cols=2,
        )
        self._table(
            moment_rows,
            [25 * mm, 28 * mm, 28 * mm, 42 * mm, 42 * mm],
            font=7.0,
            keep=False,
            repeat_cols=1,
        )

        def labelled(values, formatter):
            return "; ".join(
                f"{row['element_id']}: {formatter(row)}" for row in values
            )

        self._formula(
            "sigma<sub>p,0,i</sub> = E<sub>p,i</sub> "
            "eps<sub>p,0,i</sub>",
            equation_key="prestress.initial-stress",
            ref="Sector locked-in prestress initialisation from entered tendon strain.",
            subst=labelled(
                elements,
                lambda row: (f"{_fmt(row['modulus_mpa'], 1)} &#183; "
                             f"{_fmt(row['initial_strain'], 6)}"),
            ),
            result=("= " + labelled(
                elements,
                lambda row: _fmt(row["locked_in_stress_mpa"], 3),
            ) + " MPa"),
        )
        self._formula(
            "F<sub>p,0,i</sub> = sigma<sub>p,0,i</sub> "
            "A<sub>p,i</sub> / 1000",
            equation_key="prestress.element-force",
            ref="Stress in MPa times area in mm2, converted to kN.",
            subst=labelled(
                elements,
                lambda row: (f"{_fmt(row['locked_in_stress_mpa'], 3)} &#183; "
                             f"{_fmt(row['area_mm2'], 1)} / 1000"),
            ),
            result=("= " + labelled(
                elements, lambda row: _fmt(row["force_kn"], 3)
            ) + " kN"),
            references=("prestress.initial-stress",),
        )
        internal = payload["internal_resultant_origin"]
        force_terms = " + ".join(_fmt(row["force_kn"], 3) for row in elements)
        mx_terms = " + ".join(
            f"{_fmt(row['force_kn'], 3)} &#183; {_fmt(row['y_m'], 4)}"
            for row in elements
        )
        my_terms = " + ".join(
            f"{_fmt(row['force_kn'], 3)} &#183; {_fmt(row['x_m'], 4)}"
            for row in elements
        )
        self._formula(
            "N<sub>p,0</sub> = &#931; F<sub>p,0,i</sub>",
            equation_key="prestress.resultant-n",
            ref="Tendon internal tensile-force resultant about the section origin.",
            subst=f"= {force_terms}",
            result=f"= {_fmt(internal['n_kn'], 3)} kN",
            references=("prestress.element-force",),
        )
        self._formula(
            "M<sub>p,x,0</sub> = &#931; F<sub>p,0,i</sub> y<sub>i</sub>",
            equation_key="prestress.resultant-mx",
            ref="Tendon internal moment resultant about the section x-axis.",
            subst=f"= {mx_terms}",
            result=f"= {_fmt(internal['mx_knm'], 3)} kNm",
            references=("prestress.element-force",),
        )
        self._formula(
            "M<sub>p,y,0</sub> = &#931; F<sub>p,0,i</sub> x<sub>i</sub>",
            equation_key="prestress.resultant-my",
            ref="Tendon internal moment resultant about the section y-axis.",
            subst=f"= {my_terms}",
            result=f"= {_fmt(internal['my_knm'], 3)} kNm",
            references=("prestress.element-force",),
        )

    def _loads_block(self):
        inp = self._base_inp
        out = self._base_out
        self._small(
            "Load-table input accepts a dot or comma as the decimal separator; "
            "blank action cells canonicalize to zero; calculations retain the "
            "parsed numeric precision."
        )
        if "plastic_cases" in inp or "elastic_cases" in inp:
            plastic = (
                case_analysis.case_records(inp, "plastic")
                if self._case_contexts("plastic") else []
            )
            if plastic:
                self._small("<b>Plastic / capacity cases</b>")
                if self.profile.key == "Brief":
                    self.flow[-1].keepWithNext = 1
                table_key = table_fields.PLASTIC_CASES_TABLE_KEY
                rows = [[
                    "Case", "Description",
                    _input_table_symbol(table_key, "n_ed_kn"),
                    _input_table_symbol(table_key, "mx_ed_knm"),
                    _input_table_symbol(table_key, "my_ed_knm"),
                    _input_table_symbol(table_key, "vx_ed_kn"),
                    _input_table_symbol(table_key, "vy_ed_kn"),
                    _input_table_symbol(table_key, "t_ed_knm"),
                    "Faces", "Min. reinf.",
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
                if self.profile.key == "Brief":
                    self.flow[-1].keepWithNext = 1
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
                    "crack-width calculation is optional per case. The optional "
                    "permitted crack width is shared from Analysis settings; no "
                    "stress limit is applied."
                )
            fatigue_rows = (
                fatigue_inputs.spectrum_records(
                    inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
                )
                if inp.get("fatigue_on") else []
            )
            if fatigue_rows:
                self._small("<b>Grouped fatigue spectra</b>")
                if self.profile.key == "Brief":
                    self.flow[-1].keepWithNext = 1
                table_key = table_fields.FATIGUE_SPECTRUM_TABLE_KEY
                rows = [[
                    "Spectrum", "Bin", "Description", "Cycles",
                    _input_table_symbol(table_key, "n_long_ed_kn"),
                    _input_table_symbol(table_key, "mx_long_ed_knm"),
                    _input_table_symbol(table_key, "my_long_ed_knm"),
                    _input_table_symbol(table_key, "n_short_ed_kn"),
                    _input_table_symbol(table_key, "mx_short_ed_knm"),
                    _input_table_symbol(table_key, "my_short_ed_knm"),
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
                    "Shared links / closed torsion stirrup present",
                    self._brief_switch(inp.get("shear_links") is True),
                ],
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
                [
                    "Requested nu<sub>t</sub> = nu<sub>v</sub> detailing allowance",
                    self._brief_switch(inp.get("torsion_nu_v") is True),
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
            direction_label = _modelled_direction_report_label(
                cut_direction=inp.get("detailing_cut_direction"),
                alias=inp.get(modelled_direction.ALIAS_KEY),
            )
            rows.extend([
                ["Minimum reinforcement", "selected per capacity case"],
                ["Detailing edition", str(inp.get("detailing_edition") or "-")],
                ["Member type", str(inp.get("detailing_member_type") or "Beam")],
                [
                    "Section cut direction",
                    str(inp.get("detailing_cut_direction") or "Transverse cut"),
                ],
                ["Modelled reinforcement direction", direction_label],
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
            inp.get("shear_links") is True
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
        elastic_shared = self._base_out.get("elastic_shared") or {}
        if elastic_results:
            # Modular ratios are derived from the elastic moduli and creep, not entered;
            # document the inputs (Ec, phi) and the derived mild + prestress ratios.
            if elastic_shared:
                rows.append(["Concrete elastic modulus E<sub>c</sub>",
                             f"{_fmt(elastic_shared.get('concrete_modulus_mpa'), 1)} MPa"])
                rows.append(["Effective long-term modulus E<sub>c,eff</sub>",
                             f"{_fmt(elastic_shared.get('effective_concrete_modulus_mpa'), 1)} MPa"])
                rows.append(["Creep coefficient &#966; (long-term)",
                             _fmt(elastic_shared.get("creep_coefficient"), 3)])
            for material in elastic_shared.get("materials") or []:
                rows.append([
                    f"{material.get('material_id')} modular ratios "
                    "n<sub>s</sub> / n<sub>l</sub>",
                    f"{_fmt(material.get('short_term'), 3)} / "
                    f"{_fmt(material.get('long_term'), 3)}",
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
                permitted_width = inp.get("sls_permitted_crack_width_mm")
                rows.append([
                    "Crack-width treatment",
                    (
                        "Calculated without acceptance assessment"
                        if permitted_width is None
                        else "Compared with the shared Analysis criterion"
                    ),
                ])
                rows.append([
                    "Permitted crack width w<sub>k</sub>",
                    (
                        "not specified"
                        if permitted_width is None
                        else f"{_fmt(permitted_width, 3)} mm"
                    ),
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
        if elastic_results and elastic_shared:
            start = len(self.flow)
            self._elastic_shared_calculation_block(elastic_shared)
            self._keep_from(start)
        if fatigue_rows:
            self.flow.append(NotAtTopPageBreak())
            self._h2("Grouped fatigue settings")
            self._table(fatigue_rows, [110 * mm, 55 * mm], keep=False)

    def _elastic_shared_calculation_block(self, payload):
        """Publish effective modulus and per-material modular ratios."""

        materials = payload.get("materials") or []
        ec = payload["concrete_modulus_mpa"]
        phi = payload["creep_coefficient"]
        self._h2("Elastic material transformation")
        self._formula(
            "E<sub>c,eff</sub> = E<sub>c</sub> / (1 + phi)",
            equation_key="elastic.concrete.effective-modulus",
            ref="Sector transformed-section long-term modulus relation.",
            subst=f"= {_fmt(ec, 1)} / (1 + {_fmt(phi, 3)})",
            result=(f"= {_fmt(payload['effective_concrete_modulus_mpa'], 1)} "
                    "MPa"),
        )
        if not materials:
            return

        def rows_text(formatter):
            return "; ".join(
                f"{row['material_id']}: {formatter(row)}" for row in materials
            )

        self._formula(
            "n<sub>s,i</sub> = E<sub>i</sub> / E<sub>c</sub>",
            equation_key="elastic.modular-ratio.short",
            ref="Sector transformed-section short-term modular ratio.",
            subst=rows_text(
                lambda row: f"{_fmt(row['modulus_mpa'], 1)} / {_fmt(ec, 1)}"
            ),
            result=("= " + rows_text(
                lambda row: _fmt(row["short_term"], 4)
            )),
        )
        self._formula(
            "n<sub>l,i</sub> = n<sub>s,i</sub> (1 + phi)",
            equation_key="elastic.modular-ratio.long",
            ref="Sector transformed-section long-term modular ratio.",
            subst=rows_text(
                lambda row: (f"{_fmt(row['short_term'], 4)} &#183; "
                             f"(1 + {_fmt(phi, 3)})")
            ),
            result=("= " + rows_text(
                lambda row: _fmt(row["long_term"], 4)
            )),
            references=("elastic.modular-ratio.short",),
        )

    def _needs_diagnostic_chapter(self, family, result):
        """Keep an unrankable/invalid result's reason without a worked chain."""

        if not isinstance(result, Mapping):
            return False
        if family in {"plastic", "elastic"}:
            return result.get("converged") is False
        if family == "torsion":
            return result.get("valid") is False
        if family in {"minimum_reinforcement", "transverse_reinforcement"}:
            checks = tuple(result.get("checks") or ())
            if not checks:
                return bool(result.get("reason"))
            return not any(
                check.get("status") in {"PASS", "FAIL"}
                and self._retained_utilisation_available(check.get("utilisation"))
                for check in checks
            )
        if family == "shear":
            directions = result.get("directions") or {}
            items = tuple(directions.values()) or (result,)
            return not any(
                (
                    (item.get("links") or {}).get("res") or {}
                ).get("valid")
                and self._retained_utilisation_available(
                    (item.get("links") or {}).get("util")
                )
                or (
                    not item.get("links")
                    and (item.get("res") or {}).get("valid")
                    and self._retained_utilisation_available(item.get("util"))
                )
                for item in items
            )
        return False

    @staticmethod
    def _retained_utilisation_available(value):
        """Whether a stored assessment utilisation can be published."""
        try:
            metric = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(metric) or metric == math.inf

    def _theory(self):
        self._h1("Basis of analysis")
        plastic_results = self._result_values("plastic")
        elastic_results = self._result_values("elastic")
        minimum_results = self._result_values("minimum_reinforcement")
        transverse_results = self._result_values("transverse_reinforcement")
        fatigue = self._base_out.get("fatigue")
        fatigue_errors = tuple((fatigue or {}).get("errors") or ())
        basis_values = [
            self.inp.get(key)
            for key in (
                "design_basis_key",
                "concrete_preset",
                "mild_preset",
                "prestress_preset",
                "pre_preset",
                "sls_code",
                "fatigue_edition",
                "detailing_edition",
                "shear_method",
                "torsion_method",
                "combined_method",
            )
        ]

        for catalogue_key in (
            "mild_material_catalog",
            "prestress_material_catalog",
        ):
            basis_values.extend(
                item.get("preset")
                for item in (self.inp.get(catalogue_key) or {}).get("items", [])
            )
        if fatigue is not None:
            basis_values.extend((
                fatigue.get("basis_key"),
                fatigue.get("basis_label"),
                fatigue.get("edition"),
            ))
        if any("2023" in str(value) for value in basis_values if value is not None):
            self._p(
                "<b>2023 basis limitation.</b> DS/EN 1992-1-1:2023 is "
                "reported as a published project-adoption basis. Project "
                "adoption remains the engineer's responsibility; no Danish "
                "National Annex is applied. The 2023 confinement enhancement "
                "is not included or assessed."
            )
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
            direction_label = _modelled_direction_report_label(
                minimum_results[0],
                cut_direction=self.inp.get("detailing_cut_direction"),
                alias=self.inp.get(modelled_direction.ALIAS_KEY),
            )
            if edition == detailing.EC2_2023:
                self._p(
                    f"<b>Minimum reinforcement - {direction_label}.</b> The nominal section "
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
                    f"<b>Minimum reinforcement - {direction_label}.</b> The resultant "
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
        publish_worked = (
            self._selected_family("minimum_reinforcement", self.inp) is not None
        )
        direction_label = _modelled_direction_report_label(
            result,
            cut_direction=self.inp.get("detailing_cut_direction"),
            alias=self.inp.get(modelled_direction.ALIAS_KEY),
        )
        self._case_heading(
            f"{direction_label} minimum reinforcement", "plastic"
        )
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
            f"<b>Modelled direction:</b> {direction_label}; "
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
            worked_check = max(
                checks,
                key=lambda item: (
                    -math.inf if item.get("utilisation") is None
                    else float(item["utilisation"])
                ),
            )
            if publish_worked:
                self._formula(
                    "A<sub>s,min</sub> = max(0.26 f<sub>ctm</sub> / "
                    "f<sub>yk</sub>, 0.0013) b<sub>t</sub>d",
                    equation_key="detailing.minimum.area-2005",
                    ref=(f"{_html_escape(result.get('edition', '-'))} "
                         "&#167;9.2.1.1(1), Formula (9.1N)"),
                    subst=(
                        "coefficient = max("
                        f"{_fmt(worked_check.get('strength_coefficient'), 7)}, "
                        f"{_fmt(worked_check.get('floor_coefficient'), 7)}) = "
                        f"{_fmt(worked_check.get('selected_coefficient'), 7)}; "
                        f"A<sub>s,min</sub> = {_fmt(worked_check.get('selected_coefficient'), 7)} "
                        f"&#183; {_fmt(worked_check.get('bt_mm'), 3)} &#183; "
                        f"{_fmt(worked_check.get('d_mm'), 3)}"
                    ),
                    result=(
                        f"A<sub>s,min</sub> = {_fmt(worked_check.get('as_min_mm2'), 3)} "
                        f"mm<super>2</super> ({worked_check.get('governing_coefficient', '-')})"
                    ),
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
            worked_check = max(
                checks,
                key=lambda item: (
                    -math.inf if item.get("utilisation") is None
                    else float(item["utilisation"])
                ),
            )
            if publish_worked:
                terms = worked_check.get("reinforcement_terms") or []
                self._formula(
                    "R<sub>nom</sub> = &#8721;(A<sub>s,i</sub> f<sub>yk,i</sub>) "
                    "&#8805; R<sub>cr</sub> = A<sub>c</sub> f<sub>ctm</sub>",
                    equation_key="detailing.minimum.tension-2023",
                    ref="EN 1992-1-1:2023 &#167;12.2(2)(b), Formula (12.2)",
                    subst=(
                        "R<sub>cr</sub> = "
                        f"{_fmt(worked_check.get('concrete_area_m2'), 6)} &#183; "
                        f"{_fmt(worked_check.get('fctm_mpa'), 3)} &#183; 1000 = "
                        f"{_fmt(worked_check.get('demand_kn'), 3)} kN; "
                        "R<sub>nom</sub> terms = "
                        + "; ".join(
                            f"{_html_escape(str(term.get('bar_id', '-')))}: "
                            f"{_fmt(term.get('area_mm2'), 3)} &#183; "
                            f"{_fmt(term.get('fyk_mpa'), 3)} / 1000 = "
                            f"{_fmt(term.get('resistance_kn'), 3)} kN"
                            for term in terms
                        )
                    ),
                    result=(
                        f"R<sub>nom</sub> = {_fmt(worked_check.get('resistance_kn'), 3)} kN; "
                        f"R<sub>cr</sub>/R<sub>nom</sub> = "
                        f"{_fmt(worked_check.get('utilisation'), 5)}"
                    ),
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
            worked_check = max(
                checks,
                key=lambda item: (
                    -math.inf if item.get("utilisation") is None
                    else float(item["utilisation"])
                ),
            )
            if publish_worked:
                self._formula(
                    "lambda<sub>cr</sub> = (f<sub>ctm</sub> - "
                    "sigma<sub>N,v</sub>) / sigma<sub>M,v</sub>",
                    equation_key="detailing.minimum.cracking-factor-2023",
                    ref="Sector vertex evaluation of EN 1992-1-1:2023 Formula (12.1)",
                    subst=(
                        f"= ({_fmt(worked_check.get('cracking_fctm_mpa'), 6)} - "
                        f"{_fmt(worked_check.get('cracking_governing_axial_stress_mpa'), 6)}) / "
                        f"{_fmt(worked_check.get('cracking_governing_bending_stress_mpa'), 6)}"
                    ),
                    result=(
                        f"lambda<sub>cr</sub> = {_fmt(worked_check.get('cracking_factor'), 8)}; "
                        f"M<sub>cr</sub> = {_fmt(worked_check.get('m_cr_knm'), 6)} kNm"
                    ),
                )
                solution = worked_check.get("nominal_solution") or {}
                selected_solution = solution.get("governing_point") or solution
                if selected_solution.get("axial_residual_kn") is not None:
                    self._formula(
                        "Delta N = N<sub>int</sub> - N<sub>target</sub>",
                        equation_key="detailing.minimum.nominal-equilibrium-2023",
                        ref="Final retained nominal-section axial equilibrium.",
                        subst=(
                            f"= {_fmt(selected_solution.get('achieved_axial_kn'), 8)} - "
                            f"{_fmt(selected_solution.get('requested_axial_kn'), 8)} kN"
                        ),
                        result=(
                            f"Delta N = {_fmt(selected_solution.get('axial_residual_kn'), 9)} kN; "
                            f"tolerance = {_fmt(selected_solution.get('axial_tolerance_kn'), 9)} kN; "
                            f"iterations = {selected_solution.get('iterations', '-')}"
                        ),
                    )
                self._formula(
                    "M<sub>R,nom</sub>(N<sub>Ed</sub>) &#8805; "
                    "M<sub>cr</sub>(N<sub>Ed</sub>)",
                    equation_key="detailing.minimum.bending-2023",
                    ref="EN 1992-1-1:2023 &#167;12.2(2)(a), Formula (12.1)",
                    subst=(
                        f"{_fmt(worked_check.get('mr_nom_knm'), 6)} kNm "
                        f"&#8805; {_fmt(worked_check.get('m_cr_knm'), 6)} kNm"
                    ),
                    result=(
                        "M<sub>cr</sub>/M<sub>R,nom</sub> = "
                        f"{_fmt(worked_check.get('utilisation'), 6)}"
                    ),
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

        if checks and not publish_worked:
            self._small(
                "The complete minimum-reinforcement worked example is published "
                "only for the governing stored utilisation across all plastic cases."
            )

        for limitation in result.get("limitations") or []:
            self._small("<b>Scope:</b> " + _html_escape(limitation))

    def _transverse_reinforcement(self):
        result = self.out["transverse_reinforcement"]
        publish_worked = (
            self._selected_family("transverse_reinforcement", self.inp) is not None
        )
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
        minimum_operands_complete = all(
            minimum.get(key) is not None
            for key in (
                "coefficient", "fck_mpa", "fywk_mpa", "base_ratio", "ratio"
            )
        )
        if minimum and publish_worked and minimum_operands_complete:
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
                subst=(
                    f"base = {_fmt(minimum.get('coefficient'), 4)} &#183; "
                    f"&#8730;({_fmt(minimum.get('fck_mpa'), 3)}) / "
                    f"{_fmt(minimum.get('fywk_mpa'), 3)} = "
                    f"{_fmt(minimum.get('base_ratio'), 7)}"
                    + (
                        f"; selected = {_fmt(minimum.get('base_ratio'), 7)} &#183; "
                        f"{_fmt(minimum.get('ductility_factor'), 3)}"
                        if minimum.get("ductility_reduction_applied") else ""
                    )
                ),
                result=(
                    "rho<sub>w,min</sub> = "
                    f"{_fmt(minimum.get('ratio'), 7)}"
                ),
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
        if publish_worked and governing:
            kind = governing.get("kind")
            if kind == "minimum_ratio" and governing.get("bw_mm") is not None:
                self._formula(
                    "rho<sub>w</sub> = n<sub>leg</sub>A<sub>leg</sub> / "
                    "(s b<sub>w</sub>)",
                    equation_key="detailing.links.provided-ratio",
                    equation_variant="shear",
                    ref=_html_escape(governing.get("clause") or "-"),
                    subst=(
                        f"= {governing.get('legs', '-')} &#183; "
                        f"{_fmt(governing.get('leg_area_mm2'), 5)} / "
                        f"({_fmt(governing.get('link_spacing_mm'), 3)} &#183; "
                        f"{_fmt(governing.get('bw_mm'), 3)})"
                    ),
                    result=(
                        f"rho<sub>w</sub> = {_fmt(governing.get('provided'), 7)}; "
                        f"rho<sub>w,min</sub>/rho<sub>w</sub> = "
                        f"{_fmt(governing.get('utilisation'), 6)}"
                    ),
                )
            elif kind == "minimum_ratio" and governing.get("tef_mm") is not None:
                self._formula(
                    "rho<sub>w,T</sub> = A<sub>leg</sub> / "
                    "(s t<sub>ef</sub>)",
                    equation_key="detailing.links.provided-ratio",
                    equation_variant="torsion",
                    ref=_html_escape(governing.get("clause") or "-"),
                    subst=(
                        f"= {_fmt(governing.get('leg_area_mm2'), 5)} / "
                        f"({_fmt(governing.get('link_spacing_mm'), 3)} &#183; "
                        f"{_fmt(governing.get('tef_mm'), 3)})"
                    ),
                    result=(
                        f"rho<sub>w,T</sub> = {_fmt(governing.get('provided'), 7)}; "
                        f"rho<sub>w,min</sub>/rho<sub>w,T</sub> = "
                        f"{_fmt(governing.get('utilisation'), 6)}"
                    ),
                )
            elif kind == "longitudinal_spacing":
                self._formula(
                    "s<sub>l,max</sub> = 0.75d",
                    equation_key="detailing.links.spacing-limit",
                    equation_variant="longitudinal",
                    ref=_html_escape(governing.get("clause") or "-"),
                    subst=(
                        f"= {_fmt(governing.get('spacing_factor'), 3)} &#183; "
                        f"{_fmt(governing.get('d_mm'), 3)} mm"
                    ),
                    result=(
                        f"s<sub>l,max</sub> = {_fmt(governing.get('limit'), 3)} mm; "
                        f"s<sub>l</sub>/s<sub>l,max</sub> = "
                        f"{_fmt(governing.get('utilisation'), 6)}"
                    ),
                )
            elif kind == "transverse_leg_spacing":
                limits = governing.get("spacing_limits_mm") or {}
                self._formula(
                    "s<sub>t,max</sub> = min(0.75d, 600 mm)",
                    equation_key="detailing.links.spacing-limit",
                    equation_variant="transverse",
                    ref=_html_escape(governing.get("clause") or "-"),
                    subst="; ".join(
                        f"{_html_escape(str(label))} = {_fmt(value, 3)} mm"
                        for label, value in limits.items()
                    ),
                    result=(
                        f"s<sub>t,max</sub> = {_fmt(governing.get('limit'), 3)} mm "
                        f"({governing.get('governing_limit', '-')}); "
                        f"s<sub>t</sub>/s<sub>t,max</sub> = "
                        f"{_fmt(governing.get('utilisation'), 6)}"
                    ),
                )
            elif kind == "torsion_spacing":
                limits = governing.get("spacing_limits_mm") or {}
                self._formula(
                    "s<sub>max</sub> = min(u<sub>k</sub>/8, "
                    "section minimum dimension)",
                    equation_key="detailing.links.spacing-limit",
                    equation_variant="torsion",
                    ref=_html_escape(governing.get("clause") or "-"),
                    subst="; ".join(
                        f"{_html_escape(str(label))} = {_fmt(value, 3)} mm"
                        for label, value in limits.items()
                    ),
                    result=(
                        f"s<sub>max</sub> = {_fmt(governing.get('limit'), 3)} mm "
                        f"({governing.get('governing_limit', '-')}); "
                        f"s/s<sub>max</sub> = {_fmt(governing.get('utilisation'), 6)}"
                    ),
                )
        elif result.get("checks"):
            self._small(
                "The complete link-detailing worked example is published only "
                "for the governing stored utilisation across all plastic cases."
            )
        for check in result.get("checks") or []:
            details = []
            if check.get("spacing_source"):
                details.append(
                    "spacing source: " + str(check["spacing_source"])
                )
                if check.get("spacing_source") == "gross-web upper-bound screen":
                    details.append(
                        "this upper-bound screen can prove PASS but cannot prove FAIL"
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
        if governing:
            candidates = governing.get("required_candidates_mm") or {}
            self._formula(
                "r<sub>12</sub> = sqrt(Delta x<super>2</super> + "
                "Delta y<super>2</super>);   c<sub>12</sub> = r<sub>12</sub> "
                "- (phi<sub>1</sub> + phi<sub>2</sub>)/2",
                equation_key="detailing.clear-spacing.distance",
                ref="Sector section-plane pair geometry.",
                subst=(
                    f"r<sub>12</sub> = sqrt({_fmt(governing.get('dx_mm'), 3)}<super>2</super> + "
                    f"{_fmt(governing.get('dy_mm'), 3)}<super>2</super>) = "
                    f"{_fmt(governing.get('centre_distance_mm'), 3)} mm; "
                    f"c<sub>12</sub> = {_fmt(governing.get('centre_distance_mm'), 3)} - "
                    f"({_fmt(governing.get('phi_first_mm'), 3)} + "
                    f"{_fmt(governing.get('phi_second_mm'), 3)})/2"
                ),
                result=f"c<sub>12</sub> = {_fmt(governing.get('clear_mm'), 3)} mm",
            )
            self._formula(
                "c<sub>req</sub> = max(phi<sub>max</sub>, "
                "D<sub>upper</sub> + 5 mm, 20 mm)",
                equation_key="detailing.clear-spacing.requirement",
                ref=(f"{_html_escape(result.get('edition', '-'))} "
                     f"&#167;{_html_escape(result.get('clause', '-'))}"),
                subst=(
                    "= max("
                    f"{_fmt(candidates.get('larger element diameter'), 3)}, "
                    f"{_fmt(candidates.get('aggregate allowance'), 3)}, "
                    f"{_fmt(candidates.get('absolute minimum'), 3)}) mm"
                ),
                result=(
                    f"c<sub>req</sub> = {_fmt(governing.get('required_mm'), 3)} mm "
                    f"({governing.get('governing_requirement', '-')})"
                ),
            )
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
            angles=[pt["V"] for pt in pl["points"]],
            util=assessment.get("util"),
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
        if assessment.get("status") == "INVALID":
            if applied is not None:
                rows.append(["Applied M<sub>x</sub>, M<sub>y</sub>",
                             f"{_fmt(applied[0], 3)}, {_fmt(applied[1], 3)} kNm"])
            rows.append([
                "Utilisation",
                "INVALID - " + _html_escape(assessment.get("detail") or ""),
            ])
        elif not pl.get("check_util", True):
            rows.append(["Utilisation", "not checked (capacity only)"])
        elif not assessment.get("assessed"):
            rows.append([
                "Utilisation",
                "not assessed - " + _html_escape(assessment.get("detail") or ""),
            ])
        elif assessment.get("util") is not None:
            if applied is not None:
                rows.append(["Applied M<sub>x</sub>, M<sub>y</sub>",
                             f"{_fmt(applied[0], 3)}, {_fmt(applied[1], 3)} kNm"])
            rows.append(["Utilisation (applied direction)",
                         f"{_fmt(assessment['util']*100, 3)} %"])
        else:
            rows.append([
                "Utilisation",
                "not assessed - " + _html_escape(assessment.get("detail") or ""),
            ])
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
        if self._selected_family("plastic", self.inp) is not None:
            self._plastic_worked(pl)
        else:
            self._small(
                "The complete plastic worked example is published only for the "
                "governing utilisation (or capacity extremum when no utilisation "
                "is assessed) across all plastic cases."
            )

    def _plastic_worked(self, pl):
        pts = pl["points"]
        worked_index = pl.get("worked_point_index")
        assessment = presentation.plastic_action_assessment(pl)
        retained_basis = str(
            pl.get("worked_point_basis") or "accepted solver state"
        )
        if retained_basis == "utilisation direction" and not assessment.get(
            "assessed"
        ):
            self._h2("Worked plastic calculation unavailable")
            self._small(
                "The retained utilisation-based worked point is not authoritative: "
                + _html_escape(assessment.get("detail") or "recalculate")
                + "."
            )
            return
        if not isinstance(worked_index, int) or not 0 <= worked_index < len(pts):
            self._h2("Worked plastic calculation unavailable")
            self._small(
                "The completed payload does not retain the selected worked-point "
                "identity. Sector does not select or recalculate one in the report."
            )
            return
        gov = pts[worked_index]
        basis = retained_basis
        heading = f"Worked plastic calculation ({basis})"
        state_rows = presentation.plastic_state_rows(gov)
        start = len(self.flow)
        self._h2(heading)
        self._p(
            f"Selected sweep point {worked_index + 1} of {len(pts)}: neutral-axis "
            f"angle = {_fmt(gov['V'], 0)}&#176;. Internal axial forces use the "
            "plastic solver's compression-positive convention; the entered "
            "N<sub>Ed</sub> is tension-positive and is negated at the solver boundary."
        )
        comp = any(
            row.get("element_type") == "Bar" and row.get("state") == "Compression"
            for row in state_rows["elements"]
        )
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
                ["Compression resultant", "F<sub>comp</sub>",
                 f"{_fmt(gov['comp_force'], 3)} kN"],
                ["Internal lever arm", "L", f"{_fmt(gov['lever']*_MM, 3)} mm"],
                ["Lever components", "d<sub>x</sub>, d<sub>y</sub>",
                 f"{_fmt(gov['dx']*_MM, 3)}, {_fmt(gov['dy']*_MM, 3)} mm"],
                ["Capacity", "M<sub>x</sub>, M<sub>y</sub>",
                 f"{_fmt(gov['Mx'], 3)}, {_fmt(gov['My'], 3)} kNm"]]
        self._table(rows, [70 * mm, 30 * mm, 60 * mm])
        self._keep_from(start)
        plane_values = (
            gov.get("strain_offset"), gov.get("strain_gradient_x"),
            gov.get("strain_gradient_y"),
        )
        reference_rows = state_rows["concrete"] or state_rows["elements"]
        if all(value is not None for value in plane_values) and reference_rows:
            reference = reference_rows[0]
            self._h2("Accepted strain plane")
            self._formula(
                "eps<sub>sec</sub>(x,y) = eps<sub>0</sub> + "
                "g<sub>x</sub>x + g<sub>y</sub>y",
                equation_key="plastic.worked.strain-plane",
                ref="Sector plane-section kinematics at the retained accepted state.",
                subst=(
                    f"= {_fmt(plane_values[0], 8)} + "
                    f"{_fmt(plane_values[1], 8)} &#183; "
                    f"{_fmt(reference['x_mm'] / _MM, 6)} + "
                    f"{_fmt(plane_values[2], 8)} &#183; "
                    f"{_fmt(reference['y_mm'] / _MM, 6)}"
                ),
                result=(
                    f"eps<sub>sec</sub> = "
                    f"{_fmt(reference['section_strain_permille'], 6)} permille "
                    "(compression positive)"
                ),
            )

        candidates = gov.get("curvature_candidates") or []
        selected = gov.get("curvature_selection") or {}
        if candidates and selected:
            self._h2("Ultimate-curvature candidates")
            mode_labels = {
                "concrete_crushing": "Concrete crushing",
                "bar_tension_rupture": "Bar tension rupture",
                "bar_compression_rupture": "Bar compression rupture",
                "tendon_tension_rupture": "Tendon tension rupture",
            }
            candidate_rows = [[
                "Candidate", "Element", "Strain limit", "Distance to NA",
                "Curvature", "Selected",
            ]]
            for candidate in candidates:
                candidate_rows.append([
                    mode_labels.get(candidate["mode"], candidate["mode"]),
                    candidate.get("element_id") or "extreme concrete fibre",
                    _fmt(candidate["strain_limit"] * 1000.0, 6),
                    _fmt(candidate["distance_from_na_m"] * _MM, 4),
                    _fmt(candidate["curvature_per_m"], 8),
                    "yes" if candidate.get("selected") else "",
                ])
            self._table(
                candidate_rows,
                [37 * mm, 31 * mm, 27 * mm, 28 * mm, 28 * mm, 17 * mm],
                font=6.7,
                keep=False,
            )
            governing_candidate = next(
                (candidate for candidate in candidates if candidate.get("selected")),
                None,
            )
            if governing_candidate is not None:
                self._formula(
                    "kappa<sub>i</sub> = eps<sub>lim,i</sub> / d<sub>i</sub>",
                    equation_key="plastic.worked.curvature-candidate",
                    ref="Sector retained ultimate-strain candidate at the accepted depth.",
                    subst=(
                        f"= {_fmt(governing_candidate['strain_limit'], 9)} / "
                        f"{_fmt(governing_candidate['distance_from_na_m'], 9)} m"
                    ),
                    result=(
                        f"kappa<sub>i</sub> = "
                        f"{_fmt(governing_candidate['curvature_per_m'], 9)} 1/m"
                    ),
                )
                self._formula(
                    "kappa<sub>u</sub> = min(kappa<sub>c</sub>, "
                    "kappa<sub>s,i</sub>, kappa<sub>p,j</sub>)",
                    equation_key="plastic.worked.curvature-selection",
                    ref="Sector governing-curvature minimum; exact candidate operands above.",
                    subst=_curvature_selection_substitution(candidates, selected),
                    result=(
                        f"kappa<sub>u</sub> = "
                        f"{_fmt(selected.get('curvature_per_m'), 9)} 1/m; "
                        f"{mode_labels.get(selected.get('mode'), selected.get('mode'))}"
                    ),
                    references=("plastic.worked.curvature-candidate",),
                )

        search_keys = (
            "search_lower_depth",
            "search_upper_depth",
            "search_lower_axial",
            "search_upper_axial",
            "search_iterations",
            "compression_depth",
            "axial_requested",
            "axial_achieved",
            "axial_residual",
            "axial_tolerance",
        )
        if all(gov.get(key) is not None for key in search_keys):
            self._h2("Compression-depth solution")
            search_rows = [["Quantity", "Value"], [
                "Initial depth bracket",
                f"{_fmt(gov['search_lower_depth'] * _MM, 6)} to "
                f"{_fmt(gov['search_upper_depth'] * _MM, 6)} mm",
            ], [
                "Axial resultants at initial bracket",
                f"{_fmt(gov['search_lower_axial'], 6)} to "
                f"{_fmt(gov['search_upper_axial'], 6)} kN (compression +)",
            ], [
                "Bisection iterations", str(gov["search_iterations"]),
            ], [
                "Accepted compression depth",
                f"{_fmt(gov['compression_depth'] * _MM, 6)} mm",
            ], [
                "Requested / achieved internal N",
                f"{_fmt(gov['axial_requested'], 6)} / "
                f"{_fmt(gov['axial_achieved'], 6)} kN",
            ], [
                "Residual / tolerance",
                f"{_fmt(gov['axial_residual'], 9)} / "
                f"{_fmt(gov['axial_tolerance'], 9)} kN",
            ], [
                "Accepted state",
                "yes" if gov.get("axial_reachable") and gov.get("converged") else "no",
            ]]
            self._table(search_rows, [75 * mm, 85 * mm], keep=False)
            self._small(
                "Only the initial bracket, accepted state and final residual are "
                "shown; the internal bisection sequence and integration bands are "
                "not published."
            )
        else:
            self._h2("Compression-depth solution unavailable")
            self._small(
                "The completed payload does not contain the full accepted bracket, "
                "depth and residual summary. Sector does not reconstruct those "
                "solver values in the report."
            )

        resultant_keys = (
            "concrete_force", "bar_force", "tendon_force",
            "concrete_mx", "bar_mx", "tendon_mx",
            "concrete_my", "bar_my", "tendon_my",
            "axial_achieved", "axial_requested", "axial_residual", "Mx", "My",
        )
        if all(gov.get(key) is not None for key in resultant_keys):
            self._h2("Accepted section resultants")
            self._formula(
                "N<sub>int</sub> = F<sub>c</sub> + F<sub>s</sub> + F<sub>p</sub>",
                equation_key="plastic.worked.axial-equilibrium",
                subst=(f"= {_fmt(gov['concrete_force'], 6)} + "
                       f"{_fmt(gov['bar_force'], 6)} + "
                       f"{_fmt(gov['tendon_force'], 6)} kN"),
                result=(f"N<sub>int</sub> = {_fmt(gov['axial_achieved'], 6)} kN; "
                        f"target = {_fmt(gov['axial_requested'], 6)} kN; "
                        f"residual = {_fmt(gov['axial_residual'], 9)} kN"),
            )
            self._formula(
                "M<sub>x</sub> = M<sub>c,x</sub> + M<sub>s,x</sub> + M<sub>p,x</sub>",
                equation_key="plastic.worked.moment-x",
                subst=(f"= {_fmt(gov['concrete_mx'], 6)} + "
                       f"{_fmt(gov['bar_mx'], 6)} + "
                       f"{_fmt(gov['tendon_mx'], 6)} kNm"),
                result=f"M<sub>x</sub> = {_fmt(gov['Mx'], 6)} kNm",
            )
            self._formula(
                "M<sub>y</sub> = M<sub>c,y</sub> + M<sub>s,y</sub> + M<sub>p,y</sub>",
                equation_key="plastic.worked.moment-y",
                subst=(f"= {_fmt(gov['concrete_my'], 6)} + "
                       f"{_fmt(gov['bar_my'], 6)} + "
                       f"{_fmt(gov['tendon_my'], 6)} kNm"),
                result=f"M<sub>y</sub> = {_fmt(gov['My'], 6)} kNm",
            )
        else:
            self._h2("Accepted section resultants unavailable")
            self._small(
                "The completed payload does not retain every concrete, mild-steel "
                "and tendon resultant. Sector does not reconstruct material or "
                "section response in the report."
            )

        concrete_rows = state_rows["concrete"]
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
        element_rows = state_rows["elements"]
        if element_rows:
            self._h2("Governing reinforcement and tendon response")
            worked_element = element_rows[0]
            self._formula(
                "F<sub>i</sub> = sigma<sub>i</sub>A<sub>i</sub>/1000",
                equation_key="plastic.worked.element-force",
                ref="Retained accepted material response and entered element area.",
                subst=(
                    f"= {_fmt(worked_element['stress_mpa'], 6)} MPa &#183; "
                    f"{_fmt(worked_element['area_mm2'], 6)} mm<super>2</super> / 1000"
                ),
                result=(f"F<sub>{_html_escape(worked_element['element_id'])}</sub> = "
                        f"{_fmt(worked_element['force_kn'], 6)} kN "
                        "(tension positive)"),
            )
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
            hp = state_rows["halfplane"]
            na = viz.na_line_at(hp[0], hp[1], hp[2], inp.get("extent", 1.0))
            zones = viz.compression_zones(inp.get("outer", []), hp)
            bars = inp.get("bars", [])
            tendons = inp.get("tendons", [])
            bar_states = [
                row for row in element_rows if row.get("element_type") == "Bar"
            ]
            tendon_states = [
                row for row in element_rows if row.get("element_type") == "Tendon"
            ]
            state_colour = lambda row: (
                viz.BAR_TENSION
                if row.get("strain_permille", 0.0) >= 0.0
                else viz.BAR_COMPRESSION
            )
            bar_colors = (
                [state_colour(row) for row in bar_states]
                if len(bar_states) == len(bars) else None
            )
            tendon_colors = (
                [state_colour(row) for row in tendon_states]
                if len(tendon_states) == len(tendons) else None
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
        selected = self._selected_family("shear", self.inp)
        critical = selected is not None
        if not directions:
            self._case_heading("Shear resistance", "plastic")
            links = aggregate.get("links") or {}
            resistance = (
                (links.get("res") or {}).get("vrd")
                if links else (aggregate.get("res") or {}).get("vrd_c")
            )
            utilisation = links.get("util") if links else aggregate.get("util")
            component = aggregate.get("component") or (
                "vy" if aggregate.get("axis") == "x" else "vx"
            )
            action = "V<sub>y,Ed</sub>" if component == "vy" else "V<sub>x,Ed</sub>"
            self._table(
                [
                    ["Direction", "V<sub>Ed</sub>", "V<sub>Rd</sub>",
                     "Utilisation", "Status", "Tension face"],
                    [
                        action,
                        f"{_fmt(aggregate.get('signed_v_ed', aggregate.get('v_ed')), 3)} kN",
                        f"{_fmt(resistance, 3)} kN",
                        _pct(utilisation),
                        aggregate.get("status", "NOT ASSESSED"),
                        viz.tension_face_label(
                            aggregate.get("tension_low", True),
                            aggregate.get("axis"),
                        ),
                    ],
                ],
                [25 * mm, 27 * mm, 27 * mm, 27 * mm, 28 * mm, 38 * mm],
            )
            if links.get("out_of_limits") or aggregate.get("out_of_limits"):
                self._small(
                    "Warning: the retained compression-strut bounds are outside "
                    "the selected method's default range. The actual entered "
                    "bounds remain in the completed result."
                )
            if not critical:
                self._small(
                    "The complete shear worked example is published only for the "
                    "governing retained utilisation across all plastic cases."
                )
                return
            self._small(
                "All calculated shear cases remain in the results overview. The "
                "complete shear worked example is published only for the governing "
                "retained utilisation across all plastic cases."
            )
            self._h2(f"Governing worked example: {action}")
            self._shear_direction(
                aggregate, include_case_heading=False, component=component
            )
            return

        self._case_heading("Shear resistance", "plastic")
        if critical and aggregate.get("biaxial") and self.figures:
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
                if self.inp.get("shear_links") is True
                else (item.get("res") or {}).get("vrd_c")
            )
            utilisation = (
                links.get("util")
                if self.inp.get("shear_links") is True
                else item.get("util")
            )
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
        if any(
            (item.get("links") or {}).get("out_of_limits")
            or item.get("out_of_limits")
            for item in directions.values()
        ):
            self._small(
                "Warning: one or more directional compression-strut bands are "
                "outside the selected method's default range. The actual entered "
                "bounds remain in the completed results."
            )
        if not critical:
            self._small(
                "The complete shear worked example is published only for the "
                "governing retained utilisation across all plastic cases."
            )
            return
        self._small(
            "All calculated shear cases and directions remain in the results "
            "overview. The complete shear worked example is published only for "
            "the governing retained utilisation across all plastic cases."
        )
        component = selected.get("component")
        if not isinstance(component, str) or component not in directions:
            self._h2("Worked shear calculation unavailable")
            self._small(
                "The completed payload does not retain the selected directional "
                "result required by the governing worked-example contract."
            )
            return
        label = "V<sub>x,Ed</sub>" if component == "vx" else "V<sub>y,Ed</sub>"
        self._h2(f"Governing worked example: {label}")
        self._shear_direction(
            directions[component], include_case_heading=False,
            component=component,
        )

    def _shear_direction(self, sh, *, include_case_heading=True, component=None):
        res = sh["res"]
        combined_blocker = presentation.combined_bending_assessment_blocker(
            self.out
        )
        combined_blocked = combined_blocker is not None
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
                    (
                        "NOT ASSESSED"
                        if combined_blocked
                        else candidate.get("combined_status", "NOT RUN")
                    ),
                ])
            domain_subject = (
                "Shear and V+T"
                if combined_blocked
                else "Shear, V+T and combined"
            )
            self._small(
                "The associated bending moment is effectively zero; both faces are "
                f"mandatory. {domain_subject} checks may govern on different faces."
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
                if key == "combined" and combined_blocked:
                    governing_rows.append([
                        labels[key], "-", "-", "-", "NOT ASSESSED",
                    ])
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
            if combined_blocked:
                self._small(combined_blocker)
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
        retained_angle_fields = {
            "cot", "tan", "theta_deg", "cot_min", "cot_max",
            "cot_unconstrained", "angle_selection",
        }
        if not retained_angle_fields.issubset(lk):
            self._small(
                "Worked shear calculation unavailable: the completed payload does "
                "not retain the accepted strut-angle operands. Sector does not "
                "reconstruct them in the report."
            )
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
        shared_angle = links.get("member_angle_selection") or {}
        if shared_angle:
            labels = tuple(shared_angle.get("objective_labels") or ())
            governing = tuple(shared_angle.get("governing_objectives") or ())
            self._small(
                "Accepted common member-angle selection: cot theta = "
                f"{_fmt(shared_angle.get('cot'), 4)} within "
                f"[{_fmt(shared_angle.get('cot_min'), 3)}, "
                f"{_fmt(shared_angle.get('cot_max'), 3)}], selected point "
                f"{int(shared_angle.get('selected_index', 0)) + 1} of "
                f"{int(shared_angle.get('samples', 0))}. "
                "Governing retained objective(s): "
                f"{_html_escape(', '.join(governing) or 'not identified')}. "
                "The compact certificate covers "
                f"{_html_escape(', '.join(labels) or 'the active checks')} and "
                "does not contain an iteration history."
            )
        else:
            self._small(
                "Accepted resistance-angle selection: unconstrained cot theta = "
                f"{_fmt(lk['cot_unconstrained'], 4)}, entered band "
                f"[{_fmt(lk['cot_min'], 3)}, {_fmt(lk['cot_max'], 3)}], "
                f"selected cot theta = {_fmt(lk['cot'], 4)} "
                f"({_html_escape(lk['angle_selection'])})."
            )
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
                      f"({_fmt(lk['cot'], 3)} + {_fmt(lk['tan'], 3)}) "
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
                      f"({_fmt(lk['cot'], 3)} + {_fmt(lk['tan'], 3)}) / 1000",
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
                      f"{_fmt(lk['tan'], 3)}) / 1000",
                result=f"V<sub>Rd,max</sub> = {_fmt(lk['vrd_max'], 3)} kN")
        self._formula(
            "V<sub>Rd</sub> = min(V<sub>Rd,s</sub>, V<sub>Rd,max</sub>)",
            equation_key="shear.links.vrd",
            references=("shear.links.vrds", "shear.links.vrdmax"),
            subst=f"min({_fmt(lk['vrd_s'], 3)}, {_fmt(lk['vrd_max'], 3)})",
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
        combined_blocker = presentation.combined_bending_assessment_blocker(
            self.out
        )
        if combined_blocker is not None:
            self._case_heading(
                "Combined bending + shear + torsion (M-V-T)", "plastic"
            )
            self._table(
                [
                    ["Screen", "r<sub>M</sub>", "r<sub>V</sub>",
                     "r<sub>T</sub>", "DK NA sum", "Status"],
                    ["M+V+T", "-", "-", "-", "-", "NOT ASSESSED"],
                ],
                [30 * mm, 25 * mm, 25 * mm, 25 * mm, 30 * mm, 35 * mm],
            )
            self._small(combined_blocker)
            return
        directions = aggregate.get("directions") or {}
        selected = self._selected_family("combined", self.inp)
        critical = selected is not None
        if not aggregate.get("biaxial") or not directions:
            self._case_heading(
                "Combined bending + shear + torsion (M-V-T)", "plastic"
            )
            status = (
                "NOT ASSESSED" if not aggregate.get("valid")
                else "PASS" if aggregate.get("dkna_ok") else "FAIL"
            )
            self._table(
                [
                    ["Screen", "r<sub>M</sub>", "r<sub>V</sub>",
                     "r<sub>T</sub>", "DK NA sum", "Status"],
                    [
                        "M+V+T",
                        _pct(aggregate.get("r_m")),
                        _pct(aggregate.get("r_v")),
                        _pct(aggregate.get("r_t")),
                        _pct(aggregate.get("dkna_sum")),
                        status,
                    ],
                ],
                [30 * mm, 25 * mm, 25 * mm, 25 * mm, 30 * mm, 35 * mm],
            )
            if aggregate.get("outside_default_range"):
                self._small(
                    "Warning: the retained shared compression-strut bounds are "
                    "outside the selected method's default range."
                )
            if not critical:
                self._small(
                    "The complete combined M-V-T worked example is published only "
                    "for the governing retained utilisation across all plastic cases."
                )
                return
            self._small(
                "All calculated combined-action cases remain in the results "
                "overview. The complete combined M-V-T worked example is published "
                "only for the governing retained utilisation across all plastic "
                "cases."
            )
            self._h2("Governing combined worked example")
            self._combined_direction(aggregate, include_case_heading=False)
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
        if any(
            item.get("outside_default_range")
            for item in directions.values()
        ):
            self._small(
                "Warning: one or more retained shared compression-strut bands are "
                "outside the selected method's default range."
            )
        if not critical:
            self._small(
                "The complete combined M-V-T worked example is published only for "
                "the governing retained utilisation across all plastic cases."
            )
            return
        self._small(
            "All calculated combined-action cases and directions remain in the "
            "results overview. The complete combined M-V-T worked example is "
            "published only for the governing retained utilisation across all "
            "plastic cases."
        )
        component = selected.get("component")
        if not isinstance(component, str) or component not in directions:
            self._h2("Worked combined calculation unavailable")
            self._small(
                "The completed payload does not retain the selected directional "
                "result required by the governing worked-example contract."
            )
            return
        block_start = len(self.flow)
        label = "V<sub>x,Ed</sub> + T<sub>Ed</sub>" if component == "vx" \
            else "V<sub>y,Ed</sub> + T<sub>Ed</sub>"
        self._h2(f"Governing directional worked example: {label}")
        self._combined_direction(
            directions[component], include_case_heading=False,
            component=component,
        )
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
        selection = c.get("dkna_selection")
        if not isinstance(selection, dict):
            self._h2("Worked combined calculation unavailable")
            self._small(
                "The completed payload does not retain the DK NA inclusion branch "
                "and component sums. Sector does not reconstruct them in the report."
            )
            return
        verdict = _demand_resistance_verdict(c["dkna_ok"])
        if c["m_v_independent"]:
            expr = "max(r<sub>M</sub> + r<sub>T</sub>, r<sub>V</sub> + r<sub>T</sub>)"
            note = ("M and V checked separately (shear longitudinal steel provided); "
                    "N is folded into the bending utilisation.")
            subst = (
                f"max({_fmt(selection['m_plus_t'], 4)}, "
                f"{_fmt(selection['v_plus_t'], 4)})"
            )
        else:
            expr = "r<sub>M</sub> + r<sub>V</sub> + r<sub>T</sub>"
            note = "each action alone; N folded into the bending utilisation."
            subst = (
                f"{_fmt(selection['r_m'], 4)} + "
                f"{_fmt(selection['r_v'], 4)} + "
                f"{_fmt(selection['r_t'], 4)}"
            )
        self._formula(
            expr,
            equation_key="combined.dk-na.sum",
            subst=subst,
            note=(f"{note} Retained inclusion rule: "
                  f"{_html_escape(selection['inclusion_rule'])}; governing chord: "
                  f"{_html_escape(selection['governing_chord'])}."),
            result=(
                "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) = "
                f"{_pct(selection['utilisation'])}  ({verdict})"
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
            stirrup_start = len(self.flow)
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
            self._keep_measured_calculation_from(stirrup_start)
        lg = c.get("longitudinal")
        if lg is not None and lg["valid"]:
            if (
                self.profile.key == "Audit"
                and (cr is not None or tr is not None)
            ):
                # Keep the complete governing chord derivation together. Without
                # this semantic break, its final utilisation equation is commonly
                # orphaned by the preceding strut/stirrup blocks.
                self._page_break()
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
        distribution = t.get("torque_distribution") or {}
        shares = distribution.get("shares") or ()
        if (
            not isinstance(distribution, dict)
            or len(shares) != len(subs)
            or any(not isinstance(share, dict) for share in shares)
        ):
            self._h2("Worked sub-tube calculation unavailable")
            self._small(
                "The completed payload does not retain the stiffness-proportional "
                "torque shares for every sub-tube. Sector does not recreate that "
                "distribution in the report."
            )
            return
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
            share = shares[i]
            role = "web" if i == 0 else f"part {i + 1}"
            ut = ("inf" if not math.isfinite(s["util"])
                  else f"{_fmt(s['util'] * 100, 0)}%")
            rows.append([role,
                         f"({_fmt(s['x_mm'], 0)}, {_fmt(s['y_mm'], 0)})<br/>"
                         f"{_fmt(s['b_mm'], 0)}x{_fmt(s['h_mm'], 0)}",
                         _fmt(s["tube"]["tef"], 1), _fmt(s["tube"]["Ak"] * 1e6, 0),
                         _pct(share.get("fraction")),
                         _fmt(share.get("torque"), 2),
                         _fmt(s["trd"], 2), ut, s["governs"]])
        self._table(rows, [16 * mm, 24 * mm, 14 * mm, 18 * mm, 13 * mm, 16 * mm,
                           16 * mm, 12 * mm, 25 * mm])
        # The torque is split by STIFFNESS, not capacity, so the governing check is the
        # WORST sub-tube (max util), not TEd / sum(TRd_i).
        util = t["util"]
        util_txt = _pct(util)
        verdict = _demand_resistance_verdict(viz.util_ok(util))
        g = t.get("governing_sub")
        gov = ("web" if g == 0 else f"part {g + 1}") if g is not None else "-"
        if not isinstance(g, int) or not 0 <= g < len(subs):
            self._h2("Governing sub-tube calculation unavailable")
            self._small(
                "The completed payload does not retain the governing sub-tube "
                "identity. Sector does not select one in the report."
            )
            return
        governing = subs[g]
        governing_share = shares[g]
        steel = governing.get("steel_resistance") or {}
        strut = governing.get("strut_resistance") or {}
        resistance = governing.get("resistance_selection") or {}
        required = (
            "asw_over_s", "two_ak_m2", "fywd_mpa", "cot", "trd_s"
        )
        strut_required = (
            "nu", "alpha_cw", "fcd_mpa", "ak_m2", "tef_mm",
            "sin_cos", "trd_max",
        )
        if (
            any(name not in steel for name in required)
            or any(name not in strut for name in strut_required)
            or any(name not in resistance for name in ("trd_s", "trd_max",
                                                        "resistance", "governs"))
        ):
            self._h2("Governing sub-tube calculation unavailable")
            self._small(
                "The completed payload does not retain the governing sub-tube's "
                "resistance operands. Sector does not recreate them in the report."
            )
            return
        self._formula(
            "lambda<sub>i</sub> = C<sub>i</sub> / &#8721; C<sub>j</sub>",
            equation_key="torsion.subtube.stiffness-share",
            ref="EN 1992-1-1 6.3.1(4), uncracked torsional-stiffness distribution.",
            subst=(f"{_fmt(governing_share['stiffness'], 6)} / "
                   f"{_fmt(distribution['positive_stiffness_sum'], 6)}"),
            result=f"lambda<sub>{g + 1}</sub> = {_fmt(governing_share['fraction'], 6)}",
        )
        self._formula(
            "T<sub>Ed,i</sub> = lambda<sub>i</sub> T<sub>Ed</sub>",
            equation_key="torsion.subtube.torque-share",
            references=("torsion.subtube.stiffness-share",),
            subst=(f"{_fmt(governing_share['fraction'], 6)} &#183; "
                   f"{_fmt(distribution['applied_torque'], 3)}"),
            result=f"T<sub>Ed,{g + 1}</sub> = {_fmt(governing_share['torque'], 3)} kN&#183;m",
        )
        self._formula(
            "T<sub>Rd,s</sub> = (A<sub>sw</sub>/s) 2 A<sub>k</sub> "
            "f<sub>ywd</sub> cot theta",
            equation_key="torsion.resistance.steel",
            ref="EN 1992-1-1 wall shear flow (6.27) and transverse equilibrium (6.8)",
            subst=f"{_fmt(steel['asw_over_s'], 4)} &#183; "
                  f"{_fmt(steel['two_ak_m2'], 4)} &#183; "
                  f"{_fmt(steel['fywd_mpa'], 1)} &#183; {_fmt(steel['cot'], 3)}",
            result=f"T<sub>Rd,s</sub> = {_fmt(steel['trd_s'], 3)} kN&#183;m",
        )
        self._formula(
            "T<sub>Rd,max</sub> = 2 nu alpha<sub>cw</sub> f<sub>cd</sub> "
            "A<sub>k</sub> t<sub>ef</sub> sin theta cos theta",
            equation_key="torsion.resistance.crushing",
            ref="EN 1992-1-1 (6.30)",
            subst=f"2 &#183; {_fmt(strut['nu'], 3)} &#183; "
                  f"{_fmt(strut['alpha_cw'], 3)} &#183; "
                  f"{_fmt(strut['fcd_mpa'], 2)} &#183; {_fmt(strut['ak_m2'], 4)} "
                  f"&#183; ({_fmt(strut['tef_mm'], 3)} / 1000) &#183; "
                  f"{_fmt(strut['sin_cos'], 4)} &#183; 1000",
            result=f"T<sub>Rd,max</sub> = {_fmt(strut['trd_max'], 3)} kN&#183;m",
        )
        self._formula(
            "T<sub>Rd</sub> = min(T<sub>Rd,s</sub>, T<sub>Rd,max</sub>)",
            equation_key="torsion.resistance.governing",
            references=("torsion.resistance.steel", "torsion.resistance.crushing"),
            subst=f"min({_fmt(resistance['trd_s'], 3)}, "
                  f"{_fmt(resistance['trd_max'], 3)})",
            result=f"T<sub>Rd</sub> = {_fmt(resistance['resistance'], 3)} kN&#183;m "
                   f"(governed by {resistance['governs']})",
        )
        self._formula(
            "governing utilisation = max(T<sub>Ed,i</sub> / T<sub>Rd,i</sub>)",
            equation_key="torsion.subtube.governing-utilisation",
            references=("torsion.subtube.torque-share",
                        "torsion.resistance.governing"),
            ref=f"worst sub-tube: {gov}",
            subst=(f"{_fmt(governing['t_ed'], 3)} / "
                   f"{_fmt(governing['trd'], 3)}"),
            result=f"{util_txt}  ({verdict})")
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

    def _selected_torsion_subcheck(self, key):
        selection = self._selected_torsion_subchecks.get(key)
        if (
            not isinstance(selection, Mapping)
            or selection.get("case_id") != self._case_id(self.inp, "plastic")
        ):
            return None, None
        torsion_result = self.out.get("torsion") or {}
        component = selection.get("component")
        if component is None:
            item = torsion_result
        elif isinstance(component, str):
            item = (
                torsion_result.get("directional_interactions") or {}
            ).get(component) or {}
        else:
            return None, None
        payload_key = (
            "interaction" if key == "interaction" else "min_reinf"
        )
        return component, item.get(payload_key)

    def _torsion_interaction_example(self):
        component, interaction = self._selected_torsion_subcheck("interaction")
        self._case_heading(
            "Governing shear + torsion concrete-strut interaction", "plastic"
        )
        required = (
            "valid", "value", "t_ed", "trd_max", "v_ed", "vrd_max",
            "cot", "theta_deg",
        )
        if (
            not isinstance(interaction, dict)
            or not interaction.get("valid")
            or any(key not in interaction or interaction[key] is None for key in required)
        ):
            self._small(
                "<b>Worked calculation unavailable.</b> The retained governing "
                "Formula 6.29 payload is incomplete; the report does not "
                "reconstruct its operands."
            )
            return
        direction = (
            ""
            if component is None
            else " for " + ("Vx + T" if component == "vx" else "Vy + T")
        )
        self._small(
            "All calculated V+T screens remain in the results overview. This is "
            "the single largest retained Formula 6.29 utilisation across "
            f"all plastic cases and directions{direction}."
        )
        self._crushing_interaction({"interaction": interaction})

    def _torsion_minimum_reinforcement_example(self):
        component, minimum = self._selected_torsion_subcheck(
            "minimum_reinforcement"
        )
        self._case_heading(
            "Governing shear + torsion minimum-reinforcement screen", "plastic"
        )
        required = (
            "applicable", "value", "ok", "t_ed", "trd_c", "v_ed",
            "vrd_c", "solid",
        )
        if (
            not isinstance(minimum, dict)
            or not minimum.get("applicable")
            or any(key not in minimum or minimum[key] is None for key in required)
        ):
            self._small(
                "<b>Worked calculation unavailable.</b> The retained governing "
                "Formula 6.31 payload is incomplete; the report does not "
                "reconstruct its operands."
            )
            return
        direction = (
            ""
            if component is None
            else " for " + ("Vx + T" if component == "vx" else "Vy + T")
        )
        self._small(
            "All calculated Formula 6.31 screens remain in the results overview. "
            "This is the single largest retained screen value across all "
            f"plastic cases and directions{direction}."
        )
        self._h2("Minimum-reinforcement screen (6.3.2(5), Eq 6.31)")
        outcome = (
            "minimum reinforcement suffices"
            if minimum["ok"] else "designed reinforcement required"
        )
        self._formula(
            "T<sub>Ed</sub>/T<sub>Rd,c</sub> + "
            "V<sub>Ed</sub>/V<sub>Rd,c</sub>",
            equation_key="torsion.minimum-reinforcement.screen",
            ref="EN 1992-1-1 (6.31)",
            subst=(
                f"{_fmt(minimum['t_ed'], 3)}/{_fmt(minimum['trd_c'], 3)} + "
                f"{_fmt(minimum['v_ed'], 3)}/{_fmt(minimum['vrd_c'], 3)}"
            ),
            result=f"{_fmt(minimum['value'], 3)}  ({outcome})",
        )
        solid_note = (
            "Assumes an approximately solid rectangular section."
            if minimum["solid"]
            else "This section has a void: 6.31 is for solid sections, so it "
            "does not strictly apply."
        )
        self._small(
            "If &#8804; 1, only minimum shear + torsion reinforcement is required "
            "(no designed stirrups for these actions). " + solid_note
        )

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
        critical = self._selected_family("torsion", self.inp) is not None
        tube_valid = (
            t.get("tube_valid") is True
            if "tube_valid" in t
            else t.get("valid") is True
        )
        full_resistance_assessed = (
            t.get("full_resistance_assessed") is True
            if "full_resistance_assessed" in t
            else t.get("valid") is True
        )
        full_resistance_available = bool(
            tube_valid
            and full_resistance_assessed
            and (
                t.get("closed_links_present") is True
                if "closed_links_present" in t
                else t.get("valid") is True
            )
            and t.get("valid") is True
        )
        self._case_heading("Torsion (thin-walled tube)", "plastic")
        if full_resistance_available:
            self._p("Torsion resistance from the thin-walled closed-tube "
                    "idealisation (EN 1992-1-1 sec. 6.3), method <b>"
                    + str(t["method"]) + "</b>. The tube is derived from the "
                    "outline; the current closed stirrups and concrete struts "
                    "give the resistance at the member strut angle "
                    + ("(one angle shared with the shear check, 6.3.2(2), "
                       "selected to minimise the governing utilisation)."
                       if t.get("theta_mode") == "utilisation"
                       else "(auto-optimised for the torsion resistance)."))
        elif tube_valid and not full_resistance_assessed:
            self._p(
                "Full torsion resistance is <b>NOT ASSESSED</b> under the "
                "thin-walled closed-tube model, method <b>"
                + str(t["method"])
                + "</b>. Current shared links / closed torsion stirrups are "
                "required before the transverse and concrete components can "
                "form one full resistance."
            )
        else:
            self._p(
                "Full torsion resistance is <b>NOT ASSESSED</b> because the "
                "thin-walled tube or retained tube evidence is invalid. "
                "No resistance or verdict is published from this state."
            )
        status = (
            "NOT ASSESSED"
            if not full_resistance_available
            else _demand_resistance_verdict(viz.util_ok(t.get("util")))
        )
        reported_trd = t.get("trd") if full_resistance_available else None
        reported_util = t.get("util") if full_resistance_available else None
        reported_governing = (
            t.get("governs") if full_resistance_available else None
        )
        self._table(
            [
                ["T<sub>Ed</sub>", "T<sub>Rd</sub>", "Utilisation",
                 "Governing resistance", "Status"],
                [
                    f"{_fmt(t.get('t_ed'), 3)} kN&#183;m",
                    (
                        f"{_fmt(reported_trd, 3)} kN&#183;m"
                        if reported_trd is not None
                        else "-"
                    ),
                    _pct(reported_util),
                    reported_governing or "-",
                    status,
                ],
            ],
            [31 * mm, 31 * mm, 31 * mm, 46 * mm, 31 * mm],
        )
        directional = t.get("directional_interactions") or {}
        if directional and full_resistance_available:
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
        if tube_valid and not full_resistance_assessed:
            reason = str(
                t.get("assessment_reason")
                or t.get("reason")
                or "full torsion resistance not assessed"
            )
            self._small(
                "Reason: " + _html_escape(reason.replace("_", " ")) + ". "
                "T<sub>Rd,max</sub> is retained only as the concrete-strut cap "
                "and T<sub>Rd,c</sub> as cracking transparency. Neither is "
                "promoted to T<sub>Rd</sub>; no utilisation, governing "
                "resistance or PASS/FAIL verdict is issued."
            )
            self._table(
                [
                    ["Quantity", "Value", "Publication state"],
                    ["T<sub>Ed</sub>", f"{_fmt(t.get('t_ed'), 3)} kN&#183;m", "Applied action"],
                    ["T<sub>Rd,max</sub>", f"{_fmt(t.get('trd_max'), 3)} kN&#183;m", "Concrete cap only"],
                    ["T<sub>Rd,c</sub>", f"{_fmt(t.get('trd_c'), 3)} kN&#183;m", "Cracking transparency"],
                    ["Required longitudinal steel", f"{_fmt(t.get('asl_req'), 0)} mm<sup>2</sup>", "Informational requirement"],
                ],
                [55 * mm, 45 * mm, 80 * mm],
            )
            self._small(
                "Displayed cap angle: theta = "
                f"{_fmt(t.get('theta_deg'), 1)}&#176;, cot theta = "
                f"{_fmt(t.get('cot'), 3)}. This is not an accepted resistance "
                "angle while full resistance is not assessed."
            )
            return
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
        if not critical:
            self._small(
                "The complete torsion worked example is published only for the "
                "governing retained utilisation across all plastic cases."
            )
            return
        self._small(
            "All calculated torsion cases remain in the results overview. The "
            "complete torsion worked example is published only for the governing "
            "retained utilisation across all plastic cases."
        )
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
        retained = {
            name: t.get(name)
            for name in (
                "angle_selection",
                "steel_resistance",
                "strut_resistance",
                "resistance_selection",
                "cracking_resistance",
                "longitudinal_reinforcement",
            )
        }
        if any(not isinstance(value, dict) for value in retained.values()):
            self._h2("Worked torsion calculation unavailable")
            self._small(
                "The completed payload does not retain every accepted torsion "
                "formula operand and governing selection. Sector does not recreate "
                "them in the report."
            )
            return
        angle = retained["angle_selection"]
        steel = retained["steel_resistance"]
        strut = retained["strut_resistance"]
        resistance = retained["resistance_selection"]
        cracking = retained["cracking_resistance"]
        longitudinal = retained["longitudinal_reinforcement"]
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
        shared_angle = t.get("member_angle_selection") or {}
        if shared_angle:
            self._small(
                "Accepted common member-angle selection: cot theta = "
                f"{_fmt(shared_angle.get('cot'), 4)} within "
                f"[{_fmt(shared_angle.get('cot_min'), 3)}, "
                f"{_fmt(shared_angle.get('cot_max'), 3)}], selected point "
                f"{int(shared_angle.get('selected_index', 0)) + 1} of "
                f"{int(shared_angle.get('samples', 0))}; governing retained "
                "objective(s): "
                f"{_html_escape(', '.join(shared_angle.get('governing_objectives') or ()) or 'not identified')}."
            )
        else:
            self._small(
                "Accepted torsion-resistance angle: unconstrained cot theta = "
                f"{_fmt(angle.get('cot_unconstrained'), 4)}, entered band "
                f"[{_fmt(angle.get('cot_min'), 3)}, {_fmt(angle.get('cot_max'), 3)}], "
                f"selected cot theta = {_fmt(angle.get('cot'), 4)} "
                f"({_html_escape(angle.get('selection'))})."
            )
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
        self._h2("Resistances", reserve=240)
        self._formula(
            "T<sub>Rd,s</sub> = (A<sub>sw</sub>/s) 2 A<sub>k</sub> f<sub>ywd</sub> "
            "cot theta",
            equation_key="torsion.resistance.steel",
            ref="EN 1992-1-1 wall shear flow (6.27) and transverse equilibrium (6.8)",
            subst=f"{_fmt(steel['asw_over_s'], 4)} &#183; "
                  f"{_fmt(steel['two_ak_m2'], 4)} &#183; "
                  f"{_fmt(steel['fywd_mpa'], 1)} &#183; {_fmt(steel['cot'], 3)}",
            result=f"T<sub>Rd,s</sub> = {_fmt(steel['trd_s'], 3)} kN&#183;m")
        self._formula(
            "T<sub>Rd,max</sub> = 2 nu alpha<sub>cw</sub> f<sub>cd</sub> "
            "A<sub>k</sub> t<sub>ef</sub> sin theta cos theta",
            equation_key="torsion.resistance.crushing",
            ref="EN 1992-1-1 (6.30)",
            subst=f"2 &#183; {_fmt(strut['nu'], 3)} &#183; "
                  f"{_fmt(strut['alpha_cw'], 3)} &#183; "
                  f"{_fmt(strut['fcd_mpa'], 2)} &#183; {_fmt(strut['ak_m2'], 4)} "
                  f"&#183; ({_fmt(strut['tef_mm'], 3)} / 1000) &#183; "
                  f"{_fmt(strut['sin_cos'], 4)} &#183; 1000",
            result=f"T<sub>Rd,max</sub> = {_fmt(strut['trd_max'], 3)} kN&#183;m")
        self._formula(
            "T<sub>Rd</sub> = min(T<sub>Rd,s</sub>, T<sub>Rd,max</sub>)",
            equation_key="torsion.resistance.governing",
            references=("torsion.resistance.steel", "torsion.resistance.crushing"),
            subst=f"min({_fmt(resistance['trd_s'], 3)}, "
                  f"{_fmt(resistance['trd_max'], 3)})",
            result=f"T<sub>Rd</sub> = {_fmt(resistance['resistance'], 3)} kN&#183;m "
                   f"(governed by {resistance['governs']})")
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
            subst=f"2 &#183; {_fmt(cracking['ak_m2'], 4)} &#183; "
                  f"({_fmt(cracking['tef_mm'], 3)} / 1000) &#183; "
                  f"{_fmt(cracking['fctd_mpa'], 3)} "
                  "&#183; 1000",
            result=f"T<sub>Rd,c</sub> = {_fmt(cracking['trd_c'], 3)} kN&#183;m")
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
            subst=f"{_fmt(longitudinal['numerator'], 6)} / "
                  f"{_fmt(longitudinal['denominator'], 6)} &#183; 1000",
            result=f"&#8721;A<sub>sl</sub> = "
                   f"{_fmt(longitudinal['asl_required_mm2'], 0)} mm<sup>2</sup> "
                   "(in addition to the bending steel)")
        self._small("Lengths shown in m and f in MPa; the &#183; 1000 converts "
                    "MN&#183;m to kN&#183;m (resistances) and m<sup>2</sup> "
                    "to mm<sup>2</sup> "
                    "(A<sub>sl</sub>).")

    def _elastic_state_tables(self, title, state):
        """Publish one retained Ec=1 state without repeating the elastic solve."""

        self._h2(title)
        plane = state["raw_stress_plane"]
        self._table(
            [["Coefficient", "Value", "Unit"],
             ["sigma<sub>0</sub>", _fmt(plane["sigma0_kpa"], 9), "kN/m2"],
             ["d sigma / dx", _fmt(plane["gradient_x_kpa_per_m"], 9), "kN/m3"],
             ["d sigma / dy", _fmt(plane["gradient_y_kpa_per_m"], 9), "kN/m3"]],
            [55 * mm, 60 * mm, 45 * mm],
        )
        equilibrium = state["equilibrium"]
        matrix = equilibrium["matrix"]
        matrix_rows = [[
            "Resultant row", "sigma<sub>0</sub> coefficient",
            "d sigma/dx coefficient", "d sigma/dy coefficient",
        ]]
        for label, row in zip(("N", "Mx", "My"), matrix):
            matrix_rows.append([label, *[_fmt(value, 9) for value in row]])
        self._table(
            matrix_rows,
            [31 * mm, 43 * mm, 43 * mm, 43 * mm],
            font=7.0,
            keep=False,
        )
        self._small(
            "Final transformed equilibrium matrix J. For the N row the columns "
            "have units m2, m3, m3; for the Mx/My rows they have units m3, m4, "
            "m4. The raw plane uses kN/m2 and kN/m3, giving N in kN and moments "
            "in kNm."
        )
        self._table(
            [["Resultant", "Target", "Internal", "Residual", "Unit"],
             ["N", _fmt(equilibrium["target"]["n"], 9),
              _fmt(equilibrium["internal"]["n"], 9),
              _fmt(equilibrium["residual"]["n"], 9), "kN"],
             ["Mx", _fmt(equilibrium["target"]["mx"], 9),
              _fmt(equilibrium["internal"]["mx"], 9),
              _fmt(equilibrium["residual"]["mx"], 9), "kNm"],
             ["My", _fmt(equilibrium["target"]["my"], 9),
              _fmt(equilibrium["internal"]["my"], 9),
              _fmt(equilibrium["residual"]["my"], 9), "kNm"]],
            [29 * mm, 37 * mm, 37 * mm, 37 * mm, 20 * mm],
            font=7.0,
            keep=False,
        )
        tolerance = equilibrium.get("relative_tolerance")
        self._small(
            f"Accepted after {state.get('iterations', 0)} Newton iteration(s); "
            f"normalised residual = {_fmt(equilibrium['normalised_residual'], 9)}"
            + (f", tolerance = {_fmt(tolerance, 9)}." if tolerance is not None
               else ". Direct uncracked linear solution; no Newton tolerance applies.")
            + " The normalisation exactly preserves the solver's fixed numeric "
              "[kN, kNm, kNm] maximum convention; it is not a physical-unit norm."
        )
        return plane, equilibrium, matrix

    @staticmethod
    def _matrix_substitution(row, plane):
        return (
            f"{_fmt(row[0], 9)} &#183; {_fmt(plane['sigma0_kpa'], 9)} + "
            f"{_fmt(row[1], 9)} &#183; {_fmt(plane['gradient_x_kpa_per_m'], 9)} + "
            f"{_fmt(row[2], 9)} &#183; {_fmt(plane['gradient_y_kpa_per_m'], 9)}"
        )

    def _elastic_worked(self, el):
        """Publish the existing combined elastic calculation as a worked chain."""

        states = el.get("accepted_states") or {}
        superposition = el.get("superposition") or {}
        if not states or not superposition:
            self._h2("Worked elastic calculation unavailable")
            self._small(
                "The completed payload does not retain the accepted elastic states. "
                "Sector does not repeat the solver in the report."
            )
            return

        self._p(
            "The elastic solver uses a raw reference-stress plane with E<sub>c</sub> "
            "normalised to 1. Physical concrete strain is the retained reference "
            "stress divided by the entered E<sub>c</sub>; eps0/kx/ky are therefore "
            "not published as physical strain or curvature."
        )

        long_plane, long_eq, long_matrix = self._elastic_state_tables(
            "Step 1 - accepted long-term state", states["long_term"]
        )
        self._formula(
            "sigma<sub>ref</sub>(x,y) = sigma<sub>0</sub> + g<sub>x</sub>x + "
            "g<sub>y</sub>y",
            equation_key="elastic.long.stress-plane",
            ref="Sector Ec=1 cracked-section stress-plane formulation.",
            subst=(f"= {_fmt(long_plane['sigma0_kpa'], 9)} + "
                   f"{_fmt(long_plane['gradient_x_kpa_per_m'], 9)}x + "
                   f"{_fmt(long_plane['gradient_y_kpa_per_m'], 9)}y"),
            result="Retained long-term reference-stress plane (x and y in m).",
        )
        self._formula(
            "N<sub>int</sub> = J<sub>N</sub> q",
            equation_key="elastic.long.equilibrium-n",
            ref="Final retained transformed equilibrium row.",
            subst="= " + self._matrix_substitution(long_matrix[0], long_plane),
            result=(f"N<sub>int</sub> = {_fmt(long_eq['internal']['n'], 9)} kN; "
                    f"target = {_fmt(long_eq['target']['n'], 9)} kN; "
                    f"residual = {_fmt(long_eq['residual']['n'], 9)} kN"),
        )
        self._formula(
            "M<sub>x,int</sub> = J<sub>Mx</sub> q",
            equation_key="elastic.long.equilibrium-mx",
            ref="Final retained transformed equilibrium row.",
            subst="= " + self._matrix_substitution(long_matrix[1], long_plane),
            result=(f"M<sub>x,int</sub> = {_fmt(long_eq['internal']['mx'], 9)} kNm; "
                    f"target = {_fmt(long_eq['target']['mx'], 9)} kNm; "
                    f"residual = {_fmt(long_eq['residual']['mx'], 9)} kNm"),
        )
        self._formula(
            "M<sub>y,int</sub> = J<sub>My</sub> q",
            equation_key="elastic.long.equilibrium-my",
            ref="Final retained transformed equilibrium row.",
            subst="= " + self._matrix_substitution(long_matrix[2], long_plane),
            result=(f"M<sub>y,int</sub> = {_fmt(long_eq['internal']['my'], 9)} kNm; "
                    f"target = {_fmt(long_eq['target']['my'], 9)} kNm; "
                    f"residual = {_fmt(long_eq['residual']['my'], 9)} kNm"),
        )

        nl = superposition["long_term_modular_ratio"]
        ns = superposition["short_term_modular_ratio"]
        factor = superposition["long_term_reduction_factor"]
        self._h2("Step 2 - neutralise the long-term concrete stress")
        self._formula(
            "r = 1 - n<sub>s</sub>/n<sub>l</sub>",
            equation_key="elastic.combined.reduction-factor",
            subst=f"= 1 - {_fmt(ns, 9)} / {_fmt(nl, 9)}",
            result=f"r = {_fmt(factor, 9)}",
        )
        elements = el.get("elements") or []
        if elements:
            element = elements[0]
            self._formula(
                "sigma<sub>s2,i</sub> = r sigma<sub>s1,passive,i</sub>",
                equation_key="elastic.combined.reduced-long-stress",
                references=("elastic.combined.reduction-factor",),
                subst=(f"= {_fmt(factor, 9)} &#183; "
                       f"{_fmt(element['long_passive_mpa'], 9)} MPa"),
                result=(f"sigma<sub>s2,{_html_escape(element['element_id'])}</sub> = "
                        f"{_fmt(element['reduced_long_mpa'], 9)} MPa"),
            )
        neutralising = superposition["neutralising_resultant"]
        terms_n = " + ".join(
            f"{_fmt(row['reduced_long_mpa'], 6)}&#183;{_fmt(row['area_mm2'], 3)}/1000"
            for row in elements
        ) or "0"
        terms_mx = " + ".join(
            f"{_fmt(row['reduced_long_mpa'], 6)}&#183;{_fmt(row['area_mm2'], 3)}"
            f"&#183;{_fmt(row['y_mm'], 3)}/1000000"
            for row in elements
        ) or "0"
        terms_my = " + ".join(
            f"{_fmt(row['reduced_long_mpa'], 6)}&#183;{_fmt(row['area_mm2'], 3)}"
            f"&#183;{_fmt(row['x_mm'], 3)}/1000000"
            for row in elements
        ) or "0"
        self._formula(
            "N<sub>neu</sub> = sum(sigma<sub>s2,i</sub>A<sub>i</sub>)",
            equation_key="elastic.combined.neutralising-n",
            subst="= " + terms_n,
            result=f"N<sub>neu</sub> = {_fmt(neutralising['n'], 9)} kN",
        )
        self._formula(
            "M<sub>neu,x</sub> = sum(sigma<sub>s2,i</sub>A<sub>i</sub>y<sub>i</sub>)",
            equation_key="elastic.combined.neutralising-mx",
            subst="= " + terms_mx,
            result=f"M<sub>neu,x</sub> = {_fmt(neutralising['mx'], 9)} kNm",
        )
        self._formula(
            "M<sub>neu,y</sub> = sum(sigma<sub>s2,i</sub>A<sub>i</sub>x<sub>i</sub>)",
            equation_key="elastic.combined.neutralising-my",
            subst="= " + terms_my,
            result=f"M<sub>neu,y</sub> = {_fmt(neutralising['my'], 9)} kNm",
        )

        instant_plane, instant_eq, instant_matrix = self._elastic_state_tables(
            "Step 3 - accepted instantaneous combined state",
            states["instantaneous_combined"],
        )
        combined_target = superposition["combined_target_before_neutralisation"]
        self._formula(
            "N<sub>target</sub> = N<sub>comb</sub> - N<sub>neu</sub>",
            equation_key="elastic.combined.target-n",
            subst=(f"= {_fmt(combined_target['n'], 9)} - "
                   f"{_fmt(neutralising['n'], 9)} kN"),
            result=f"N<sub>target</sub> = {_fmt(instant_eq['target']['n'], 9)} kN",
        )
        self._formula(
            "M<sub>x,target</sub> = M<sub>x,comb</sub> - M<sub>x,neu</sub>",
            equation_key="elastic.combined.target-mx",
            subst=(f"= {_fmt(combined_target['mx'], 9)} - "
                   f"{_fmt(neutralising['mx'], 9)} kNm"),
            result=(f"M<sub>x,target</sub> = "
                    f"{_fmt(instant_eq['target']['mx'], 9)} kNm"),
        )
        self._formula(
            "M<sub>y,target</sub> = M<sub>y,comb</sub> - M<sub>y,neu</sub>",
            equation_key="elastic.combined.target-my",
            subst=(f"= {_fmt(combined_target['my'], 9)} - "
                   f"{_fmt(neutralising['my'], 9)} kNm"),
            result=(f"M<sub>y,target</sub> = "
                    f"{_fmt(instant_eq['target']['my'], 9)} kNm"),
        )
        self._formula(
            "sigma<sub>ref</sub>(x,y) = sigma<sub>0</sub> + g<sub>x</sub>x + "
            "g<sub>y</sub>y",
            equation_key="elastic.instantaneous.stress-plane",
            ref="Sector Ec=1 cracked-section stress-plane formulation.",
            subst=(f"= {_fmt(instant_plane['sigma0_kpa'], 9)} + "
                   f"{_fmt(instant_plane['gradient_x_kpa_per_m'], 9)}x + "
                   f"{_fmt(instant_plane['gradient_y_kpa_per_m'], 9)}y"),
            result="Retained instantaneous combined reference-stress plane (x and y in m).",
        )
        self._formula(
            "N<sub>int</sub> = J<sub>N</sub> q",
            equation_key="elastic.instantaneous.equilibrium-n",
            ref="Final retained transformed equilibrium row.",
            subst="= " + self._matrix_substitution(instant_matrix[0], instant_plane),
            result=(f"N<sub>int</sub> = {_fmt(instant_eq['internal']['n'], 9)} kN; "
                    f"target = {_fmt(instant_eq['target']['n'], 9)} kN; "
                    f"residual = {_fmt(instant_eq['residual']['n'], 9)} kN"),
        )
        self._formula(
            "M<sub>x,int</sub> = J<sub>Mx</sub> q",
            equation_key="elastic.instantaneous.equilibrium-mx",
            ref="Final retained transformed equilibrium row.",
            subst="= " + self._matrix_substitution(instant_matrix[1], instant_plane),
            result=(f"M<sub>x,int</sub> = {_fmt(instant_eq['internal']['mx'], 9)} kNm; "
                    f"target = {_fmt(instant_eq['target']['mx'], 9)} kNm; "
                    f"residual = {_fmt(instant_eq['residual']['mx'], 9)} kNm"),
        )
        self._formula(
            "M<sub>y,int</sub> = J<sub>My</sub> q",
            equation_key="elastic.instantaneous.equilibrium-my",
            ref="Final retained transformed equilibrium row.",
            subst="= " + self._matrix_substitution(instant_matrix[2], instant_plane),
            result=(f"M<sub>y,int</sub> = {_fmt(instant_eq['internal']['my'], 9)} kNm; "
                    f"target = {_fmt(instant_eq['target']['my'], 9)} kNm; "
                    f"residual = {_fmt(instant_eq['residual']['my'], 9)} kNm"),
        )

        if elements:
            element = elements[0]
            self._h2("Step 4 - combine the retained element stresses")
            self._formula(
                "sigma<sub>total,i</sub> = sigma<sub>s2,i</sub> + "
                "sigma<sub>RST1,i</sub> + sigma<sub>p0,i</sub>",
                equation_key="elastic.combined.total-stress",
                subst=(f"= {_fmt(element['reduced_long_mpa'], 9)} + "
                       f"{_fmt(element['rst1_mpa'], 9)} + "
                       f"{_fmt(element['locked_in_mpa'], 9)} MPa"),
                result=(f"sigma<sub>total,{_html_escape(element['element_id'])}</sub> = "
                        f"{_fmt(element['total_mpa'], 9)} MPa"),
            )
            self._formula(
                "sigma<sub>DIF,i</sub> = sigma<sub>total,i</sub> - "
                "sigma<sub>long,i</sub>",
                equation_key="elastic.combined.difference-stress",
                subst=(f"= {_fmt(element['total_mpa'], 9)} - "
                       f"{_fmt(element['long_mpa'], 9)} MPa"),
                result=(f"sigma<sub>DIF,{_html_escape(element['element_id'])}</sub> = "
                        f"{_fmt(element['dif_mpa'], 9)} MPa"),
            )

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
                "There is no verified cracking classification or "
                "cracked/uncracked state. "
                "Diagnostic neutral-axis intercepts: "
                f"x<sub>na</sub> = {_fmt(el['na_x']*_MM, 3)} mm, "
                f"y<sub>na</sub> = {_fmt(el['na_y']*_MM, 3)} mm."
            )
        ps = (
            (self._base_out.get("prestress_initial") or {}).get(
                "equivalent_action_origin"
            )
        )
        if ps is not None and self.inp.get("tendons"):
            self._p(f"The tendon prestress is applied from its initial strain (so N "
                    f"is the external force only): equivalent prestress action "
                    f"N = {_fmt(ps['n_kn'], 3)} kN, "
                    f"M<sub>x</sub> = {_fmt(ps['mx_knm'], 3)} kNm, "
                    f"M<sub>y</sub> = {_fmt(ps['my_knm'], 3)} kNm "
                    "(N tension-positive; calculation shown in Section and "
                    "materials).")
        if self._selected_family("elastic", self.inp) is not None:
            self._elastic_worked(el)
        else:
            self._small(
                "The complete elastic worked example is published only for the "
                "governing retained stress extremum across all elastic cases."
            )
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
        case_id = self._case_id(self.inp, "elastic")
        publish_threshold = (
            isinstance(self._selected_cracking_threshold, Mapping)
            and self._selected_cracking_threshold.get("case_id") == case_id
        )
        examples = [
            item for item in self._selected_crack_examples
            if item.get("case_id") == case_id
        ]
        publish_crack_width = bool(examples)
        publish_comparison = (
            isinstance(self._selected_crack_comparison, Mapping)
            and self._selected_crack_comparison.get("case_id") == case_id
        )
        if publish_threshold and publish_crack_width:
            heading = "Cracking threshold and governing crack width"
        elif publish_crack_width:
            heading = "Governing crack width"
        elif publish_comparison:
            heading = "Governing crack-width comparison"
        else:
            heading = "Cracking threshold"
        self._case_heading(
            heading,
            "elastic",
        )
        valid = el.get("converged", True)
        crack_2023 = (
            el.get("crack_edition") == "2023"
            or "2023" in str(el.get("crack_code", ""))
        )
        if publish_threshold:
            if publish_crack_width:
                self._h2("Governing cracking threshold")
            lam = el.get("lambda_cr")
            verdict = "cracked" if el.get("cracked") else "uncracked"
            prestressed = bool(self.inp.get("tendons"))
            threshold_equation = (
                "sigma<sub>pre,i</sub> + lambda<sub>cr</sub> "
                "sigma<sub>ext,i</sub> = f<sub>ct,eff</sub>"
                if prestressed else
                "lambda<sub>cr</sub> = f<sub>ct,eff</sub> / "
                "sigma<sub>ct,I</sub>"
            )
            self._formula(
                threshold_equation,
                equation_key="cracking.threshold",
                equation_variant=(
                    "prestress" if prestressed else "ordinary"
                ),
                ref=(
                    "Stage-I extreme tensile stress reaches f<sub>ct,eff</sub> "
                    "(EN 1992-1-1:2023 &#167;9.2.1)"
                    if crack_2023 else
                    "Stage-I extreme tensile stress reaches f<sub>ct,eff</sub> "
                    "(DS/EN 1992-1-1 &#167;7.1)"
                ),
                subst=(
                    None
                    if prestressed else
                    f"f<sub>ct,eff</sub> = {_fmt(el.get('fctm'), 3)} MPa,  "
                    f"sigma<sub>ct,I</sub> = {_fmt(el.get('sigma_ct'), 3)} MPa"
                ),
                result=(
                    None
                    if prestressed else
                    (
                        f"lambda<sub>cr</sub> = {_fmt(lam,3)}  ->  section is "
                        f"{verdict} (strictly below 1: cracked; "
                        "1 or above: uncracked)"
                        if valid else
                        f"lambda<sub>cr</sub> = {_fmt(lam,3)}  ->  INVALID; "
                        "no verified cracking classification"
                    )
                ),
            )
            if prestressed:
                self._small(
                    "Locked-in prestress remains fixed. If any prestress-only "
                    "concrete fibre is above fct,eff, Sector assigns lambda_cr = 0 "
                    "directly and does not apply the equality. Otherwise it scales "
                    "only the external N/M actions and takes the minimum equality "
                    "solution over fibres with a strictly positive external tensile "
                    "increment; if there is no such fibre, the factor is infinite. "
                    + (
                        "Calculated output: sigma_ct,I = "
                        f"{_fmt(el.get('sigma_ct'), 3)} MPa; lambda_cr = "
                        f"{_fmt(lam,3)}; section is "
                        f"{verdict} (strictly below 1: cracked; 1 or above: "
                        "uncracked)."
                        if valid else
                        "Calculated output: sigma_ct,I = "
                        f"{_fmt(el.get('sigma_ct'), 3)} MPa; lambda_cr = "
                        f"{_fmt(lam,3)}; INVALID; "
                        "no verified cracking classification."
                    )
                )
            self._small(
                "Globally critical threshold across the elastic cases. "
                "Cracking is triggered by the peak tension the section sees and "
                "is irreversible."
            )
        if not publish_crack_width:
            assessment = el.get("crack_output") or {}
            self._ordinary_crack_assessment(
                assessment,
                publish_comparison=publish_comparison,
            )
            if (
                el.get("crack") is None
                and el.get("crack_short") is None
                and el.get("crack_coarse") is None
                and el.get("crack_short_coarse") is None
                and not str(assessment.get("reason") or "").strip()
            ):
                self._small(
                    "No calculated crack-width value is available; the report "
                    "does not infer a physical reason."
                )
            return
        cl, cs = el.get("crack"), el.get("crack_short")
        clc, csc = el.get("crack_coarse"), el.get("crack_short_coarse")
        no_results = cl is None and cs is None and clc is None and csc is None
        assessment = el.get("crack_output") or {}
        value = assessment.get("value")
        text = (
            f"Crack-width output | governing w<sub>k</sub> "
            f"{'-' if value is None else _fmt(value, 3) + ' mm'} | "
            f"case {assessment.get('case') or '-'} | "
            f"element {assessment.get('governing') or '-'}"
        )
        self._p(text)
        self._ordinary_crack_assessment(
            assessment,
            publish_comparison=publish_comparison,
        )
        if no_results:
            if not str(assessment.get("reason") or "").strip():
                self._small(
                    "No calculated crack-width value is available; the report "
                    "does not infer a physical reason."
                )
            return
        self._crack_table(cl, cs, clc, csc)
        selected_cases = []
        selected_worked = []
        allowed_branches = {
            "crack", "crack_short", "crack_coarse", "crack_short_coarse",
        }
        for item in examples:
            branch = item.get("branch")
            crack = (
                el.get(branch)
                if isinstance(branch, str) and branch in allowed_branches
                else None
            )
            if isinstance(crack, Mapping):
                selected = (crack, str(item.get("label") or ""))
                selected_cases.append(selected)
                selected_worked.append(selected)
            else:
                self._small(
                    "<b>Worked calculation unavailable.</b> The retained "
                    "worked-example selection references a missing or unsupported "
                    "crack branch; no alternative branch is selected in the report."
                )
        self._crack_candidates(selected_cases)
        for crack, label in selected_worked:
            self._crack_worked(crack, label)

    def _ordinary_crack_assessment(self, assessment, *, publish_comparison):
        """Publish one retained user comparison without inferring a code limit."""
        status = str(assessment.get("calculation_state") or "NOT ASSESSED")
        criterion = assessment.get("criterion_mm")
        source = str(assessment.get("criterion_source") or "").strip()
        reason = str(assessment.get("reason") or "").strip()
        if criterion is None:
            self._small(
                f"Calculation state: {status}. No user-specified crack-width "
                "criterion was supplied; exposure, durability, prestress "
                "category and owner limits are not inferred."
            )
            if reason:
                self._small(_html_escape(reason))
            return

        self._small(
            f"Calculation state: {_html_escape(status)}. User-specified "
            f"criterion = {_fmt(criterion, 3)} mm; source: "
            f"{_html_escape(source or 'NOT RETAINED')}. This is a bounded "
            "comparison only; no exposure or owner criterion is inferred."
        )
        if reason:
            self._small(_html_escape(reason))
        if not publish_comparison:
            return
        required = (
            "value", "criterion_mm", "ratio", "criterion_source",
            "comparison_equation", "calculation_state",
        )
        missing = [
            key for key in required
            if assessment.get(key) is None
            or (key == "criterion_source" and not source)
        ]
        if missing:
            self._small(
                "<b>Worked comparison unavailable.</b> The retained critical "
                "ordinary crack-width comparison is incomplete (missing: "
                + ", ".join(missing)
                + "). The report does not reconstruct it."
            )
            return
        self._h2("User-specified crack-width comparison - critical case")
        self._formula(
            "u<sub>w</sub> = w<sub>k</sub> / w<sub>k,criterion</sub>",
            equation_key="crack.user-limit.comparison",
            ref="User-specified crack-width criterion",
            note=(
                "The largest calculated ordinary crack width is selected; a "
                "smaller width with a tighter criterion cannot govern the "
                "worked example."
            ),
            subst=(
                f"= {_fmt(assessment.get('value'), 3)} mm / "
                f"{_fmt(assessment.get('criterion_mm'), 3)} mm"
            ),
            result=(
                f"u<sub>w</sub> = {_fmt(assessment.get('ratio'), 3)}; "
                f"{_html_escape(status)}"
            ),
        )

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
        missing = self._crack_worked_missing_operands(cw)
        if missing:
            self._small(
                "<b>Worked calculation unavailable.</b> The selected retained "
                "crack branch is incomplete (missing: "
                + _html_escape(", ".join(missing))
                + "). Sector does not substitute defaults or reconstruct "
                "engineering operands in the report."
            )
            return
        self._small(f"Governing element (largest w<sub>k</sub>): "
                    f"{cw.get('element_id', 'element ' + str(cw.get('gov_bar','-')))}; "
                    f"clear cover c = {_fmt(cw.get('cover',0), 3)} mm.")
        candidate = cw.get("governing_candidate") or {}
        mean = candidate.get("mean_strain_operands") or {}
        spacing = candidate.get("spacing_operands") or {}
        code = self.out["elastic"].get("crack_code")
        coarse = bool(cw.get("coarse"))
        if code:
            if cw.get("edition") == "2023":
                note = (
                    f"Crack-width code: {code}. Refined control of cracking "
                    "(&#167;9.2.3): k<sub>w</sub> = 1.7 converts the mean crack "
                    "width to the calculated value, k<sub>1/r</sub> = (h-x)/"
                    "(h-a<sub>y</sub>-x) accounts for curvature, and the mean "
                    "strain lower bound is (1 - k<sub>t</sub>)&#183;sigma<sub>s</sub>"
                    "/E<sub>s</sub>."
                )
            else:
                note = f"Crack-width code: {code}. "
                if "DK NA" in code:
                    note += (
                        "k<sub>3</sub> = 3.4&#183;(25/c)<super>2/3</super> "
                        "(&#167;7.3.4(3)). "
                    )
                    if coarse:
                        note += (
                            "Coarse crack system (&#167;7.3.4(1)): "
                            "A<sub>c,eff</sub> is the tension-face band whose "
                            "centroid matches the tension reinforcement "
                            "(figure 7.100 NA), and w<sub>k</sub> is halved."
                        )
                    else:
                        note += (
                            "The (h-x)/3 term in h<sub>c,ef</sub> applies to "
                            "slabs and prestressed members only."
                        )
            self._small(note)
        self._crack_effective_area_worked(cw, candidate)
        if cw.get("edition") == "2023":
            self._crack_worked_2023(cw, candidate)
            return
        if spacing.get("selected_candidate") == "formula-7.14":
            # Wide/isolated bars (spacing > 5(c+phi/2)): EC2 assigns the geometric
            # spacing 1.3(h-x) directly (Eq 7.14), so the (7.11) formula would not
            # reproduce the reported value.
            self._formula(
                "s<sub>r,max</sub> = 1.3&#183;(h - x)",
                equation_key="crack.2005.spacing",
                equation_variant="geometric",
                ref="DS/EN 1992-1-1 &#167;7.3.4, Eq (7.14)",
                note=(
                    "bars not at close centres: selected because nearest spacing "
                    f"{_fmt(spacing.get('nearest_neighbour_spacing'), 3)} mm "
                    "exceeds 5(c + phi/2) = "
                    f"{_fmt(spacing.get('close_spacing_limit'), 3)} mm"
                ),
                subst=(
                    "= 1.3 &#183; "
                    f"{_fmt(float(spacing.get('tension_zone_depth', 0.0)) * _MM, 3)} mm"
                ),
                result=(
                    "s<sub>r,max</sub> = "
                    f"{_fmt(spacing.get('selected_spacing'), 3)} mm"
                ))
        else:
            self._formula(
                "s<sub>r,max</sub> = k<sub>3</sub>&#183;c + "
                "k<sub>1</sub>&#183;k<sub>2</sub>&#183;k<sub>4</sub>&#183;phi / rho<sub>p,eff</sub>",
                equation_key="crack.2005.spacing",
                equation_variant="reinforcement",
                ref="DS/EN 1992-1-1 &#167;7.3.4, Eq (7.11)",
                note=(
                    "bars at close centres: nearest spacing "
                    f"{_fmt(spacing.get('nearest_neighbour_spacing'), 3)} mm "
                    "; close-centre threshold 5(c + phi/2) = "
                    f"{_fmt(spacing.get('close_spacing_limit'), 3)} mm; "
                    "Formula (7.11) selected"
                ),
                subst=(
                    f"= {_fmt(spacing.get('k3_used'), 4)} &#183; "
                    f"{_fmt(spacing.get('cover'), 3)} + "
                    f"{_fmt(spacing.get('k1'), 3)} &#183; "
                    f"{_fmt(spacing.get('k2'), 3)} &#183; "
                    f"{_fmt(spacing.get('k4'), 3)} &#183; "
                    f"{_fmt(spacing.get('diameter'), 3)} / "
                    f"{_fmt(spacing.get('rho_p_eff'), 6)}"
                ),
                result=(
                    "s<sub>r,max</sub> = "
                    f"{_fmt(spacing.get('selected_spacing'), 3)} mm"
                ))
        self._crack_mean_strain_worked(mean, edition="2005")
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

    @staticmethod
    def _crack_worked_missing_operands(cw):
        """Validate every operand required by the selected crack formula branch."""
        missing = []

        def require(mapping, prefix, keys):
            if not isinstance(mapping, Mapping):
                missing.append(prefix.rstrip("."))
                return
            missing.extend(
                prefix + key for key in keys
                if key not in mapping or mapping[key] is None
            )

        require(cw, "crack.", (
            "cover", "sr_max", "esm_ecm", "wk", "governing_candidate",
            "effective_area_operands", "edition",
        ))
        candidate = cw.get("governing_candidate") or {}
        require(candidate, "candidate.", (
            "as_eff", "ap_eff", "ac_eff", "rho_p_eff",
            "mean_strain_operands", "spacing_operands",
        ))
        mean = candidate.get("mean_strain_operands") or {}
        require(mean, "mean_strain.", (
            "sigma_s", "concrete_tension_reduction", "es",
            "formula_candidate", "lower_bound_factor",
            "lower_bound_candidate", "selected_esm_ecm", "selected_candidate",
        ))
        spacing = candidate.get("spacing_operands") or {}
        require(spacing, "spacing.", ("selected_candidate", "selected_spacing"))
        area = cw.get("effective_area_operands") or {}
        require(area, "effective_area.", ("record_kind", "ac_eff"))
        edition = cw.get("edition")
        if edition not in {"2004", "2005", "2023"}:
            missing.append("crack.edition-supported")
        if edition == "2023":
            require(cw, "crack.", ("kw", "k1_r", "effective_reinforcement_2023"))
            require(spacing, "spacing.", (
                "flexural_factor_method", "cover_coefficient", "cover",
                "flexural_factor", "bond_factor_kb", "diameter_ratio_divisor",
                "diameter", "rho_p_eff", "formula_spacing",
                "cap_tension_depth", "cap_spacing",
            ))
            if spacing.get("selected_candidate") not in {
                "formula-9.15", "tension-zone-cap",
            }:
                missing.append("spacing.selected_candidate-supported")
            reinforcement = cw.get("effective_reinforcement_2023") or {}
            require(reinforcement, "effective_reinforcement.", (
                "as_eff", "ap_eff_weighted", "ac_eff", "rho_p_eff",
            ))
        elif edition in {"2004", "2005"}:
            require(spacing, "spacing.", (
                "nearest_neighbour_spacing", "close_spacing_limit",
            ))
            spacing_candidate = spacing.get("selected_candidate")
            if spacing_candidate == "formula-7.14":
                require(spacing, "spacing.", ("tension_zone_depth",))
            elif spacing_candidate == "formula-7.11":
                require(spacing, "spacing.", (
                    "k3_used", "cover", "k1", "k2", "k4", "diameter",
                    "rho_p_eff",
                ))
            else:
                missing.append("spacing.selected_candidate-supported")

        area_keys = {
            "CrackEffectiveArea2005Fine": (
                "candidate_2_5_h_minus_d", "candidate_h_over_2",
                "selected_hc_eff", "selected_candidate",
            ),
            "CrackEffectiveArea2005Coarse": (
                "band_centroid_axis", "reinforcement_centroid_axis",
                "centroid_gap", "selected_hc_eff",
            ),
            "CrackEffectiveArea2023Bending": (
                "candidate_ay_plus_5phi", "candidate_10phi",
                "candidate_3_5ay", "layer_spread", "candidate_h_minus_x",
                "candidate_h_over_2", "selected_hc_eff",
                "final_selected_candidate",
            ),
            "CrackEffectiveArea2023Direct": (
                "width", "height", "inner_width", "inner_height",
            ),
        }
        record_kind = area.get("record_kind")
        if record_kind not in area_keys:
            missing.append("effective_area.record_kind")
        else:
            require(area, "effective_area.", area_keys[record_kind])
            if edition == "2023" and record_kind not in {
                "CrackEffectiveArea2023Bending",
                "CrackEffectiveArea2023Direct",
            }:
                missing.append("effective_area.record_kind-for-edition")
            if edition in {"2004", "2005"}:
                expected_kind = (
                    "CrackEffectiveArea2005Coarse"
                    if cw.get("coarse") else "CrackEffectiveArea2005Fine"
                )
                if record_kind != expected_kind:
                    missing.append("effective_area.record_kind-for-system")
        return tuple(dict.fromkeys(missing))

    def _crack_effective_area_worked(self, cw, candidate):
        """Publish retained effective-area and reinforcement-ratio operands."""

        area = cw.get("effective_area_operands") or {}
        kind = area.get("record_kind")
        if kind == "CrackEffectiveArea2005Fine":
            hx = area.get("candidate_h_minus_x_over_3")
            candidates = (
                f"2.5(h-d) = {_fmt(area.get('candidate_2_5_h_minus_d', 0) * _MM, 3)} mm; "
                + (
                    f"(h-x)/3 = {_fmt(hx * _MM, 3)} mm; "
                    if hx is not None else "(h-x)/3 not applicable; "
                )
                + f"h/2 = {_fmt(area.get('candidate_h_over_2', 0) * _MM, 3)} mm"
            )
            self._formula(
                "h<sub>c,eff</sub> = min[2.5(h-d), (h-x)/3, h/2]",
                equation_key="crack.effective-area.2005",
                equation_variant="fine",
                ref="DS/EN 1992-1-1 &#167;7.3.2(3)",
                subst=candidates,
                result=(
                    f"h<sub>c,eff</sub> = {_fmt(area.get('selected_hc_eff', 0) * _MM, 3)} mm "
                    f"({area.get('selected_candidate', '-')}); "
                    f"A<sub>c,eff</sub> = {_fmt(area.get('ac_eff'), 6)} m<super>2</super>"
                ),
            )
        elif kind == "CrackEffectiveArea2005Coarse":
            self._formula(
                "s&#772;<sub>c,eff</sub> = s&#772;<sub>s,t</sub>",
                equation_key="crack.effective-area.2005",
                equation_variant="coarse",
                ref="DS/EN 1992-1-1 DK NA Figure 7.100 NA",
                subst=(
                    f"s&#772;<sub>c,eff</sub> = {_fmt(area.get('band_centroid_axis'), 6)} m; "
                    f"s&#772;<sub>s,t</sub> = {_fmt(area.get('reinforcement_centroid_axis'), 6)} m"
                ),
                result=(
                    f"centroid gap = {_fmt(area.get('centroid_gap', 0) * _MM, 6)} mm; "
                    f"h<sub>c,eff</sub> = {_fmt(area.get('selected_hc_eff', 0) * _MM, 3)} mm; "
                    f"A<sub>c,eff</sub> = {_fmt(area.get('ac_eff'), 6)} m<super>2</super>"
                ),
            )
        elif kind == "CrackEffectiveArea2023Bending":
            self._formula(
                "h<sub>c,eff</sub> = min[max(min(a<sub>y</sub>+5phi, 10phi, "
                "3.5a<sub>y</sub>), Delta a<sub>y</sub>), h-x, h/2]",
                equation_key="crack.effective-area.2023",
                equation_variant="bending",
                ref="EN 1992-1-1:2023 Figure 9.3",
                subst=(
                    f"a<sub>y</sub>+5phi = {_fmt(area.get('candidate_ay_plus_5phi', 0) * _MM, 3)} mm; "
                    f"10phi = {_fmt(area.get('candidate_10phi', 0) * _MM, 3)} mm; "
                    f"3.5a<sub>y</sub> = {_fmt(area.get('candidate_3_5ay', 0) * _MM, 3)} mm; "
                    f"layer spread = {_fmt(area.get('layer_spread', 0) * _MM, 3)} mm; "
                    f"h-x = {_fmt(area.get('candidate_h_minus_x', 0) * _MM, 3)} mm; "
                    f"h/2 = {_fmt(area.get('candidate_h_over_2', 0) * _MM, 3)} mm"
                ),
                result=(
                    f"h<sub>c,eff</sub> = {_fmt(area.get('selected_hc_eff', 0) * _MM, 3)} mm "
                    f"({area.get('final_selected_candidate', '-')}); "
                    f"A<sub>c,eff</sub> = {_fmt(area.get('ac_eff'), 6)} m<super>2</super>"
                ),
            )
        elif kind == "CrackEffectiveArea2023Direct":
            self._formula(
                "A<sub>c,eff</sub> = bh - (b-c<sub>l</sub>-c<sub>r</sub>)"
                "(h-c<sub>b</sub>-c<sub>t</sub>)",
                equation_key="crack.effective-area.2023",
                equation_variant="direct-tension",
                ref="EN 1992-1-1:2023 Figure 9.3",
                subst=(
                    f"= {_fmt(area.get('width'), 6)} &#183; {_fmt(area.get('height'), 6)} - "
                    f"{_fmt(area.get('inner_width'), 6)} &#183; {_fmt(area.get('inner_height'), 6)}"
                ),
                result=f"A<sub>c,eff</sub> = {_fmt(area.get('ac_eff'), 6)} m<super>2</super>",
            )
        else:
            self._small(
                "<b>Effective-area calculation unavailable.</b> No retained "
                "effective-area operands were supplied; the report does not "
                "reconstruct the section geometry."
            )

        if cw.get("edition") == "2023":
            reinforcement = cw.get("effective_reinforcement_2023") or {}
            if not reinforcement:
                self._small(
                    "<b>Effective reinforcement ratio unavailable.</b> The "
                    "retained Formula (9.12) operands are missing."
                )
                return
            self._formula(
                "rho<sub>p,eff</sub> = (A<sub>s,eff</sub> + "
                "sum xi<sub>1,j</sub>A<sub>p,j</sub>) / A<sub>c,eff</sub>",
                equation_key="crack.effective-reinforcement.ratio",
                equation_variant="2023",
                ref="EN 1992-1-1:2023 Formula (9.12)",
                subst=(
                    f"= ({_fmt(reinforcement.get('as_eff'), 8)} + "
                    f"{_fmt(reinforcement.get('ap_eff_weighted'), 8)}) / "
                    f"{_fmt(reinforcement.get('ac_eff'), 8)}"
                ),
                result=f"rho<sub>p,eff</sub> = {_fmt(reinforcement.get('rho_p_eff'), 6)}",
            )
        else:
            self._formula(
                "rho<sub>p,eff</sub> = (A<sub>s,eff</sub> + "
                "A<sub>p,eff</sub>) / A<sub>c,eff</sub>",
                equation_key="crack.effective-reinforcement.ratio",
                equation_variant="2005",
                ref="DS/EN 1992-1-1 &#167;7.3.2",
                subst=(
                    f"= ({_fmt(candidate.get('as_eff'), 8)} + "
                    f"{_fmt(candidate.get('ap_eff'), 8)}) / "
                    f"{_fmt(candidate.get('ac_eff'), 8)}"
                ),
                result=f"rho<sub>p,eff</sub> = {_fmt(candidate.get('rho_p_eff'), 6)}",
            )

    def _crack_mean_strain_worked(self, mean, *, edition):
        lower_label = "0.6" if edition == "2005" else "1 - k<sub>t</sub>"
        symbolic = (
            "eps<sub>sm</sub> - eps<sub>cm</sub> = max{[sigma<sub>s</sub> - "
            "k<sub>t</sub>f<sub>ct,eff</sub>/rho<sub>p,eff</sub> "
            "(1 + alpha<sub>e</sub>rho<sub>p,eff</sub>)]/E<sub>s</sub>, "
            f"{lower_label} sigma<sub>s</sub>/E<sub>s</sub>}}"
        )
        subst = (
            f"first candidate = ({_fmt(mean.get('sigma_s'), 3)} - "
            f"{_fmt(mean.get('concrete_tension_reduction'), 3)}) / "
            f"{_fmt(mean.get('es'), 1)} = "
            f"{_fmt(mean.get('formula_candidate'), 8)}; "
            f"lower bound = {_fmt(mean.get('lower_bound_factor'), 3)} &#183; "
            f"{_fmt(mean.get('sigma_s'), 3)} / {_fmt(mean.get('es'), 1)} = "
            f"{_fmt(mean.get('lower_bound_candidate'), 8)}"
        )
        result = (
            "eps<sub>sm</sub> - eps<sub>cm</sub> = "
            f"{_fmt(mean.get('selected_esm_ecm'), 8)} "
            f"({mean.get('selected_candidate', '-')})"
        )
        if edition == "2005":
            self._formula(
                symbolic,
                equation_key="crack.2005.mean-strain",
                ref="DS/EN 1992-1-1 Formula (7.9)",
                subst=subst,
                result=result,
            )
        else:
            self._formula(
                symbolic,
                equation_key="crack.2023.mean-strain",
                ref="EN 1992-1-1:2023 Formula (9.11)",
                subst=subst,
                result=result,
            )

    def _crack_candidates(self, cases):
        """Append the complete sorted per-element crack-width audit table."""
        if self.profile.key != "Audit":
            return
        rows = [["Case<br/>(LT/ST)", "#<br/>(G/N)", "Element",
                 "x<br/>(mm)", "y<br/>(mm)", "c<br/>(mm)",
                 "phi<br/>(mm)", "sigma<sub>s</sub><br/>(MPa)",
                 "A<sub>c,eff</sub><br/>(m<super>2</super>)", "&#916;eps",
                 "s<sub>r</sub><br/>(mm)", "w<sub>k</sub><br/>(mm)"]]
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
        # KeepWithNext on the heading keeps it with the table.  Do not wrap the
        # whole heading/table/legend block in KeepTogether: after a full worked
        # derivation that can push this compact summary onto an otherwise empty
        # continuation page.
        self._h2("Candidate summary for governing crack example")
        self._table(
            rows,
            _CRACK_CANDIDATE_COL_WIDTHS,
            font=5.4, keep=False, repeat_cols=3,
        )

    def _crack_worked_2023(self, cw, candidate):
        """The EN 1992-1-1:2023 refined crack-width worked example (9.2.3)."""
        spacing = candidate["spacing_operands"]
        mean = candidate["mean_strain_operands"]
        cap = spacing.get("cap_spacing")
        self._formula(
            "s<sub>r,m,cal</sub> = 1.5&#183;c + (k<sub>fl</sub>&#183;k<sub>b</sub>/7.2)"
            "&#183;phi/rho<sub>p,eff</sub> &lt;= (1.3/k<sub>w</sub>)&#183;(h-x)",
            equation_key="crack.2023.spacing",
            ref="EN 1992-1-1:2023 &#167;9.2.3, Eq (9.15)",
            note=(
                f"k<sub>fl</sub> method: {spacing.get('flexural_factor_method', '-')}; "
                f"selected: {spacing.get('selected_candidate', '-')}"
            ),
            subst=(
                f"formula = {_fmt(spacing.get('cover_coefficient'), 3)} &#183; "
                f"{_fmt(spacing.get('cover'), 3)} + "
                f"({_fmt(spacing.get('flexural_factor'), 4)} &#183; "
                f"{_fmt(spacing.get('bond_factor_kb'), 3)} / "
                f"{_fmt(spacing.get('diameter_ratio_divisor'), 3)}) &#183; "
                f"{_fmt(spacing.get('diameter'), 3)} / "
                f"{_fmt(spacing.get('rho_p_eff'), 6)} = "
                f"{_fmt(spacing.get('formula_spacing'), 3)} mm"
                + (
                    f"; cap = (1.3 / {_fmt(cw.get('kw'), 3)}) &#183; "
                    f"{_fmt(float(spacing['cap_tension_depth']) * _MM, 3)} = "
                    f"{_fmt(cap, 3)} mm"
                    if cap is not None else "; no finite tension-zone cap"
                )
            ),
            result=(
                "s<sub>r,m,cal</sub> = "
                f"{_fmt(spacing.get('selected_spacing'), 3)} mm"
            ))
        self._crack_mean_strain_worked(mean, edition="2023")
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

    def _heightened_crack_control(self):
        """Publish both retained DK Formula 7.100 NA calculations."""
        result = self._base_out.get("heightened_crack_control") or {}
        required = (
            "basis_key",
            "reinforcement_surface",
            "bar_diameter_mm",
            "diameter_source",
            "effective_tensile_strength_mpa",
            "reinforcement_modulus_mpa",
            "permitted_crack_width_mm",
            "provided_reinforcement_area_mm2",
            "source",
            "disclosure",
            "formula_identity",
            "reference_case_id",
            "ordinary_crack_branch",
            "diameter_governing_element_ids",
            "modulus_governing_material_ids",
            "contributions",
            "fine",
            "coarse",
            "governing_crack_system",
            "governing_status",
        )
        missing = [
            key for key in required
            if key not in result or result[key] is None
            or (key in {"source", "disclosure"} and not str(result[key]).strip())
        ]
        branch_required = (
            "crack_system",
            "crack_system_factor",
            "reinforcement_surface_multiplier",
            "effective_tension_area_mm2",
            "base_reinforcement_ratio",
            "required_reinforcement_ratio",
            "required_reinforcement_area_mm2",
            "comparison_ratio",
            "status",
        )
        for branch_name in ("fine", "coarse"):
            branch = result.get(branch_name)
            if not isinstance(branch, Mapping):
                missing.append(branch_name)
                continue
            missing.extend(
                f"{branch_name}.{key}"
                for key in branch_required
                if branch.get(key) is None
            )
        for key in (
            "diameter_governing_element_ids",
            "modulus_governing_material_ids",
            "contributions",
        ):
            value = result.get(key)
            if not isinstance(value, (list, tuple)) or not value:
                missing.append(key)
        contribution_required = (
            "element_id",
            "material_id",
            "area_mm2",
            "diameter_mm",
            "diameter_source",
            "reinforcement_modulus_mpa",
        )
        contributions = result.get("contributions") or []
        for index, contribution in enumerate(contributions, start=1):
            if not isinstance(contribution, Mapping):
                missing.append(f"contributions[{index}]")
                continue
            missing.extend(
                f"contributions[{index}].{key}"
                for key in contribution_required
                if contribution.get(key) in (None, "")
            )
        self._h1("DK heightened crack-control minimum - fine and coarse")
        if missing:
            self._small(
                "<b>Worked calculation unavailable.</b> The retained Formula "
                "7.100 NA result is incomplete (missing: "
                + ", ".join(missing)
                + "). The report does not reconstruct it."
            )
            return

        self._p(
            "<b>Calculation state:</b> "
            + _html_escape(str(result["governing_status"]))
            + "; governing system: "
            + _html_escape(str(result["governing_crack_system"]))
        )
        self._small(
            "<b>Source:</b> " + _html_escape(str(result["source"]))
            + ". <b>Scope:</b> " + _html_escape(str(result["disclosure"]))
        )
        self._small(
            "The user declared applicability, permitted width, reinforcement "
            "surface, effective tensile strength and the two effective tension "
            "areas. Sector derives the shared reinforcement operands from the "
            "retained ordinary crack result and does not infer restraint, "
            "watertightness, exposure class or owner requirements."
        )
        rows = [
            ["Retained input", "Value"],
            [
                "Reference Elastic case / ordinary branch",
                _html_escape(
                    f"{result['reference_case_id']} / "
                    f"{result['ordinary_crack_branch']}"
                ),
            ],
            [
                "Reinforcement surface",
                _html_escape(str(result["reinforcement_surface"])),
            ],
            [
                "Auto-derived bar diameter phi",
                f"{_fmt(result['bar_diameter_mm'], 3)} mm; "
                + _html_escape(str(result["diameter_source"]))
                + "; governing elements "
                + _html_escape(", ".join(
                    str(value)
                    for value in result["diameter_governing_element_ids"]
                )),
            ],
            [
                "Effective tensile strength fct,eff",
                f"{_fmt(result['effective_tensile_strength_mpa'], 3)} MPa",
            ],
            [
                "Auto-derived reinforcement modulus Esk",
                f"{_fmt(result['reinforcement_modulus_mpa'], 1)} MPa; "
                "governing materials "
                + _html_escape(", ".join(
                    str(value)
                    for value in result["modulus_governing_material_ids"]
                )),
            ],
            [
                "Permitted crack width wk",
                f"{_fmt(result['permitted_crack_width_mm'], 3)} mm",
            ],
            [
                "Auto-derived provided reinforcement area As,prov",
                f"{_fmt(result['provided_reinforcement_area_mm2'], 1)} mm2",
            ],
        ]
        self._table(rows, [82 * mm, 78 * mm])
        systems = [result["fine"], result["coarse"]]
        self._table(
            [
                [
                    "System",
                    "k",
                    "Ac,eff (mm2)",
                    "rho s,min",
                    "As,req (mm2)",
                    "As,req / As,prov",
                    "State",
                ],
                *[
                    [
                        _html_escape(str(branch["crack_system"])),
                        _fmt(branch["crack_system_factor"], 3),
                        _fmt(branch["effective_tension_area_mm2"], 1),
                        _fmt(branch["required_reinforcement_ratio"], 6),
                        _fmt(branch["required_reinforcement_area_mm2"], 1),
                        _fmt(branch["comparison_ratio"], 3),
                        _html_escape(str(branch["status"])),
                    ]
                    for branch in systems
                ],
            ],
            [18 * mm, 10 * mm, 25 * mm, 23 * mm, 25 * mm, 25 * mm, 34 * mm],
            font=7.0,
        )
        self._h2("Auto-derived reinforcement provenance")
        self._table(
            [
                ["Element", "Material", "Area (mm2)", "phi (mm)", "Es (MPa)"],
                *[
                    [
                        _html_escape(str(row.get("element_id") or "-")),
                        _html_escape(str(row.get("material_id") or "-")),
                        _fmt(row.get("area_mm2"), 1),
                        _fmt(row.get("diameter_mm"), 3),
                        _fmt(row.get("reinforcement_modulus_mpa"), 1),
                    ]
                    for row in contributions
                ],
            ],
            [30 * mm, 30 * mm, 30 * mm, 30 * mm, 35 * mm],
            font=7.5,
        )
        self._formula(
            "rho<sub>s,min,base</sub> = sqrt[phi f<sub>ct,eff</sub> / "
            "(4 E<sub>sk</sub> k w<sub>k</sub>)]",
            equation_key="crack.heightened.base-ratio",
            ref=_html_escape(str(result["source"])),
            note=(
                "k = 1 for the fine crack system and k = 2 for the coarse "
                "crack system."
            ),
            subst=(
                "; ".join(
                    f"{branch['crack_system']}: sqrt["
                    f"({_fmt(result['bar_diameter_mm'], 3)})"
                    f"({_fmt(result['effective_tensile_strength_mpa'], 3)}) / "
                    f"(4({_fmt(result['reinforcement_modulus_mpa'], 1)})"
                    f"({_fmt(branch['crack_system_factor'], 3)})"
                    f"({_fmt(result['permitted_crack_width_mm'], 3)}))]"
                    for branch in systems
                )
            ),
            result=(
                "; ".join(
                    f"{branch['crack_system']}: rho<sub>s,min,base</sub> = "
                    f"{_fmt(branch['base_reinforcement_ratio'], 6)}"
                    for branch in systems
                )
            ),
        )
        self._formula(
            "rho<sub>s,min</sub> = m<sub>s</sub> "
            "rho<sub>s,min,base</sub>",
            equation_key="crack.heightened.required-ratio",
            references=("crack.heightened.base-ratio",),
            ref="DS/EN 1992-1-1 DK NA:2024 Formula 7.100 NA",
            note=(
                "m_s = 1 for ribbed reinforcement and sqrt(2) for smooth "
                "reinforcement."
            ),
            subst=(
                "; ".join(
                    f"{branch['crack_system']}: "
                    f"{_fmt(branch['reinforcement_surface_multiplier'], 6)} "
                    f"&#183; {_fmt(branch['base_reinforcement_ratio'], 6)}"
                    for branch in systems
                )
            ),
            result=(
                "; ".join(
                    f"{branch['crack_system']}: rho<sub>s,min</sub> = "
                    f"{_fmt(branch['required_reinforcement_ratio'], 6)}"
                    for branch in systems
                )
            ),
        )
        self._formula(
            "A<sub>s,req</sub> = rho<sub>s,min</sub> A<sub>c,eff</sub>",
            equation_key="crack.heightened.required-area",
            references=("crack.heightened.required-ratio",),
            ref="User-supplied fine and coarse effective tension areas",
            subst=(
                "; ".join(
                    f"{branch['crack_system']}: "
                    f"{_fmt(branch['required_reinforcement_ratio'], 6)} &#183; "
                    f"{_fmt(branch['effective_tension_area_mm2'], 1)} "
                    "mm<super>2</super>"
                    for branch in systems
                )
            ),
            result=(
                "; ".join(
                    f"{branch['crack_system']}: A<sub>s,req</sub> = "
                    f"{_fmt(branch['required_reinforcement_area_mm2'], 1)} "
                    "mm<super>2</super>"
                    for branch in systems
                )
            ),
        )
        self._formula(
            "u<sub>A</sub> = A<sub>s,req</sub> / A<sub>s,prov</sub>",
            equation_key="crack.heightened.area-comparison",
            references=("crack.heightened.required-area",),
            ref="Auto-derived provided reinforcement area comparison",
            note=(
                "Bounded comparison with the retained ordinary-crack mild-bar "
                "area; this "
                "is not a global project-compliance verdict."
            ),
            subst=(
                "; ".join(
                    f"{branch['crack_system']}: "
                    f"{_fmt(branch['required_reinforcement_area_mm2'], 1)} / "
                    f"{_fmt(result['provided_reinforcement_area_mm2'], 1)}"
                    for branch in systems
                )
            ),
            result=(
                "; ".join(
                    f"{branch['crack_system']}: u<sub>A</sub> = "
                    f"{_fmt(branch['comparison_ratio'], 3)}; "
                    + _html_escape(str(branch["status"]))
                    for branch in systems
                )
            ),
        )

    def _fatigue(self):
        payload = self._base_out["fatigue"]
        audit_detail = self.profile.key == "Audit"
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
            "<b>Design basis:</b> "
            f"{_html_escape(str(payload.get('basis_label') or payload.get('edition') or '-'))}; "
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
            ["Design-basis key",
             _html_escape(str(payload.get("basis_key") or "-"))],
            ["Design basis", _html_escape(str(
                payload.get("basis_label") or payload.get("edition") or "-"
            ))],
            ["Basis disclosure", _html_escape(str(
                payload.get("basis_disclosure") or "-"
            ))],
            ["Solver edition", _html_escape(str(
                payload.get("solver_edition") or "-"
            ))],
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
        bindings = payload.get("capability_bindings") or {}
        if references or bindings:
            self._h2("Calculation sources and capability scope")
            evidence_keys = tuple(dict.fromkeys((*references, *bindings)))
            evidence_rows = [[
                "Check", "Registered capability", "Source", "Scope disclosure",
            ]]
            for key in evidence_keys:
                binding = bindings.get(key)
                if isinstance(binding, Mapping):
                    capability = str(binding.get("capability") or "-")
                    source = str(
                        binding.get("source") or references.get(key) or "-"
                    )
                    disclosure = str(binding.get("disclosure") or "-")
                else:
                    capability = "Project-defined / uncited"
                    source = "Project-defined / uncited"
                    method_note = str(references.get(key) or "").strip()
                    disclosure = (
                        "No registered standard capability is claimed for this "
                        "project-defined relation."
                        + (f" Method note: {method_note}." if method_note else "")
                    )
                evidence_rows.append([
                    str(key).capitalize(),
                    _html_escape(capability),
                    _html_escape(source),
                    _html_escape(disclosure),
                ])
            self._table(
                evidence_rows,
                [21 * mm, 42 * mm, 47 * mm, 55 * mm],
                font=6.3,
                keep=False,
            )
        details = payload.get("fatigue_detail_basis") or ()
        if details and audit_detail:
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
            "Max Miner D", "Max yield / proof", "Governing util.",
            "Search upper D",
        ]]
        rows.extend([
            [
                _html_escape(row["spectrum"]),
                row["status"],
                row["bins"],
                row["reinforcement_elements"],
                row["concrete_fibres"],
                _html_escape(row["governing"]),
                _fmt_sig(row["miner_damage"], 6),
                _pct(row["yield_utilisation"]),
                _pct(row["utilisation"]),
                _fmt_sig(row["search_upper_damage"], 6),
            ]
            for row in summary_rows
        ])
        self._table(
            rows,
            [18 * mm, 14 * mm, 8 * mm, 9 * mm, 10 * mm,
             28 * mm, 16 * mm, 19 * mm, 18 * mm, 18 * mm],
            font=5.5,
            keep=False,
        )
        self._small(
            "Miner sums are accumulated within each spectrum; different "
            "spectrum names are not combined. Governing utilisation is the "
            "maximum of the applicable Miner, yield/proof and concrete criteria."
        )

        input_records = fatigue_inputs.spectrum_records(
            self._base_inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
        )
        spectra = fatigue_presentation.items(payload, "spectra")
        reinforcement_example = payload.get("governing_reinforcement_example")
        concrete_example = payload.get("governing_concrete_example")
        selected_spectrum_names = {
            str(selection.get("spectrum_name"))
            for selection in (reinforcement_example, concrete_example)
            if isinstance(selection, Mapping) and selection.get("spectrum_name")
        }
        if checks.get("reinforcement") and not reinforcement_example:
            self._small(
                "<b>Worked example unavailable:</b> no converged governing "
                "reinforcement fatigue result was retained."
            )
        if checks.get("concrete") and not concrete_example:
            self._small(
                "<b>Worked example unavailable:</b> no converged governing "
                "concrete fatigue result was retained."
            )
        for spectrum in spectra:
            spectrum_name = str(
                fatigue_presentation.value(spectrum, "spectrum_name", "-")
            )
            if spectrum_name not in selected_spectrum_names:
                continue
            publish_reinforcement = bool(
                isinstance(reinforcement_example, Mapping)
                and reinforcement_example.get("spectrum_name") == spectrum_name
            )
            publish_concrete = bool(
                isinstance(concrete_example, Mapping)
                and concrete_example.get("spectrum_name") == spectrum_name
            )
            # Only spectra containing a globally governing family example become
            # detailed report units. Every other spectrum remains in the summary.
            if self.profile.key == "Audit":
                self.flow.append(NotAtTopPageBreak())
            spectrum_status = fatigue_presentation.result_status(spectrum)
            self._h2("Spectrum - " + _html_escape(spectrum_name))
            self._status_block(
                f"{spectrum_status} - governing utilisation "
                f"{_pct(fatigue_presentation.evidence_number(
                    fatigue_presentation.value(spectrum, 'utilisation')
                ))} | {_html_escape(
                    fatigue_presentation.criterion_breakdown(spectrum)
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
                table_key = table_fields.FATIGUE_SPECTRUM_TABLE_KEY
                rows = [[
                    "Bin", "Description", "Cycles",
                    _input_table_symbol(table_key, "n_long_ed_kn"),
                    _input_table_symbol(table_key, "mx_long_ed_knm"),
                    _input_table_symbol(table_key, "my_long_ed_knm"),
                    _input_table_symbol(table_key, "n_short_ed_kn"),
                    _input_table_symbol(table_key, "mx_short_ed_knm"),
                    _input_table_symbol(table_key, "my_short_ed_knm"),
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
            if state_rows and audit_detail:
                self._h2("Elastic solver states")
                rows = [[
                    "Bin", "Description", "Cycles", "Status",
                    "Cyclic action", "gamma<sub>Ff</sub>", "Bond method",
                ]]
                rows.extend([
                    [
                        _html_escape(row["bin"]),
                        _html_escape(row["description"]),
                        _fmt_sig(row["cycles"], 8),
                        row["status"],
                        row["cyclic_action"],
                        _fmt(row["gamma_ff"], 3),
                        _html_escape(row["bond_method"]),
                    ]
                    for row in state_rows
                ])
                self._table(
                    rows,
                    [18 * mm, 35 * mm, 18 * mm, 16 * mm, 28 * mm,
                     18 * mm, 32 * mm],
                    font=5.9,
                    keep=False,
                )

            reinforcement_rows = fatigue_presentation.reinforcement_rows(
                spectrum
            )
            if reinforcement_rows and publish_reinforcement:
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
                governing_id = reinforcement_example.get("element_id")
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
                    if not audit_detail:
                        selected_bin_name = str(
                            reinforcement_example.get("bin_name") or ""
                        )
                        bin_rows = [
                            row for row in bin_rows
                            if row["bin"] == selected_bin_name
                        ]
                    rows = [[
                        "Bin", "Cycles", "Status / range", "Long stress",
                        "Fatigue total", "Design total", "Design elastic &#916;sigma",
                        "Design &#916;sigma", "Bond factor / method",
                    ]]
                    rows.extend([
                        [
                            _html_escape(row["bin"]),
                            _fmt(row["cycles"], 3),
                            row["status"] + "<br/>" + row["range_state"],
                            _fmt(row["stress_long_mpa"], 3),
                            _fmt(row["stress_total_mpa"], 3),
                            _fmt(row["stress_total_design_mpa"], 3),
                            _fmt(row["design_stress_range_elastic_mpa"], 3),
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
                        "transformation; design elastic &#916;sigma is the raw "
                        "action-factored solver range before the bond correction; "
                        "design values include action-level "
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
                    self._fatigue_reinforcement_formulas(
                        result,
                        bin_rows,
                        reinforcement_example,
                        references.get("reinforcement"),
                    )

            concrete_rows = fatigue_presentation.concrete_rows(spectrum)
            if concrete_rows and publish_concrete:
                equivalent_method = (
                    str(fatigue_presentation.value(
                        spectrum, "concrete_method", ""
                    )) == fatigue_core.CONCRETE_EQUIVALENT
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
                governing_fibre = concrete_example.get("fibre_index")
                result = fatigue_presentation.result_by_fibre(
                    spectrum, governing_fibre
                )
                if result is None:
                    self._small(
                        "<b>Worked example unavailable:</b> the retained global "
                        "concrete-fibre identity is absent from this spectrum."
                    )
                    continue
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
                if not audit_detail:
                    selected_bin_name = str(
                        concrete_example.get("bin_name") or ""
                    )
                    bin_rows = [
                        row for row in bin_rows
                        if row["bin"] == selected_bin_name
                    ]
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
                self._fatigue_concrete_formulas(
                    spectrum,
                    result,
                    bin_rows,
                    concrete_example,
                    references.get("concrete"),
                )
                if equivalent_method:
                    self._small(
                        "Concrete criterion: E<sub>cd,max</sub> + 0.43 "
                        "&#8730;(1 - E<sub>cd,min</sub>/E<sub>cd,max</sub>) "
                        "&#8804; 1. Each action pair is user-supplied as a "
                        "damage-equivalent amplitude for 10<super>6</super> "
                        "cycles; the entered cycle count is not used for concrete."
                    )

    def _fatigue_reinforcement_formulas(
        self, result, bin_rows, selection, reference
    ):
        """Publish one solver-retained governing reinforcement fatigue chain."""

        selected_bin = next(
            (
                row for row in bin_rows
                if row["bin"] == str(selection.get("bin_name") or "")
            ),
            None,
        )
        required = (
            "stress_long_mpa",
            "stress_total_design_mpa",
            "stress_total_design_elastic_mpa",
            "design_stress_range_elastic_mpa",
            "bond_adjustment",
            "design_stress_range_mpa",
            "delta_sigma_rsk_mpa",
            "delta_sigma_rd_mpa",
            "sn_reference_cycles",
            "sn_exponent",
            "cycles_to_failure",
            "cycles",
            "damage",
            "material_factor",
        )
        if selected_bin is None or any(
            selected_bin.get(key) is None for key in required
        ):
            self._small(
                "<b>Worked example unavailable:</b> the governing reinforcement "
                "bin does not retain every required numerical operand."
            )
            return
        yield_check = selected_bin.get("governing_yield_check")
        characteristic = fatigue_presentation.evidence_number(
            fatigue_presentation.value(
                yield_check, "characteristic_strength_mpa"
            )
        )
        design_limit = fatigue_presentation.evidence_number(
            fatigue_presentation.value(yield_check, "design_limit_mpa")
        )
        yield_stress = fatigue_presentation.evidence_number(
            fatigue_presentation.value(yield_check, "stress_mpa")
        )
        yield_util = fatigue_presentation.evidence_number(
            fatigue_presentation.value(yield_check, "utilisation")
        )
        damage_total = fatigue_presentation.evidence_number(
            fatigue_presentation.value(result, "damage")
        )
        yield_total = fatigue_presentation.evidence_number(
            fatigue_presentation.value(result, "yield_utilisation")
        )
        utilisation = fatigue_presentation.evidence_number(
            fatigue_presentation.value(result, "utilisation")
        )
        damages = [row.get("damage") for row in bin_rows]
        if (
            reference is None
            or yield_check is None
            or None in (
                characteristic,
                design_limit,
                yield_stress,
                yield_util,
                damage_total,
                yield_total,
                utilisation,
            )
            or any(value is None for value in damages)
        ):
            self._small(
                "<b>Worked example unavailable:</b> the governing reinforcement "
                "result does not retain the complete criterion or source chain."
            )
            return
        source = _html_escape(str(reference))
        self._h2("Textbook calculation - governing reinforcement fatigue")
        calculation_start = len(self.flow) - 1
        self._p(
            "The globally governing reinforcement element and bin are used once "
            "to demonstrate the S-N, Miner and yield/proof checks. All other "
            "elements and spectra remain in the compact summaries above."
        )
        self._formula(
            "Delta sigma<sub>Ed,el,i</sub> = "
            "|sigma<sub>total,Ed,el,i</sub> - sigma<sub>long,i</sub>|; "
            "Delta sigma<sub>Ed,i</sub> = eta<sub>b</sub> "
            "Delta sigma<sub>Ed,el,i</sub>",
            equation_key="fatigue.reinforcement.design-stress-range",
            ref=source,
            subst=(
                f"|{_fmt(selected_bin['stress_total_design_elastic_mpa'], 6)} - "
                f"{_fmt(selected_bin['stress_long_mpa'], 6)}| = "
                f"{_fmt(selected_bin['design_stress_range_elastic_mpa'], 6)} MPa; "
                f"{_fmt(selected_bin['bond_adjustment'], 6)} &#183; "
                f"{_fmt(selected_bin['design_stress_range_elastic_mpa'], 6)} MPa"
            ),
            result=(
                "Delta sigma<sub>Ed,i</sub> = "
                f"{_fmt(selected_bin['design_stress_range_mpa'], 6)} MPa"
            ),
            note=_html_escape(selected_bin.get("bond_method") or ""),
        )
        # Keep only the subsection heading, its lead-in and the first measured
        # equation together.  The remaining worked chain must stay independently
        # pageable; wrapping every equation would create a near-page-height block.
        self._keep_measured_calculation_from(calculation_start)
        material_factor = selected_bin["material_factor"]
        self._formula(
            "Delta sigma<sub>Rd</sub> = Delta sigma<sub>Rsk</sub> / "
            "gamma<sub>s</sub>",
            equation_key="fatigue.reinforcement.design-resistance-range",
            ref=source,
            subst=(
                f"{_fmt(selected_bin['delta_sigma_rsk_mpa'], 6)} / "
                f"{_fmt(material_factor, 6)} MPa"
            ),
            result=(
                "Delta sigma<sub>Rd</sub> = "
                f"{_fmt(selected_bin['delta_sigma_rd_mpa'], 6)} MPa"
            ),
        )
        if (
            selected_bin.get("sn_reference_ratio") is None
            and selected_bin["design_stress_range_mpa"] == 0.0
        ):
            self._formula(
                "Delta sigma<sub>Ed,i</sub> = 0 "
                "implies N<sub>R,i</sub> = +infinity",
                equation_key="fatigue.reinforcement.sn-life",
                equation_variant="zero-range",
                ref=source,
                subst=(
                    "Delta sigma<sub>Ed,i</sub> = "
                    f"{_fmt(selected_bin['design_stress_range_mpa'], 6)} MPa"
                ),
                result=(
                    "N<sub>R,i</sub> = "
                    f"{_fmt_sig(selected_bin['cycles_to_failure'], 8)} cycles"
                ),
                note=_html_escape(selected_bin.get("sn_branch") or ""),
            )
        elif selected_bin.get("sn_reference_ratio") is not None:
            self._formula(
                "N<sub>R,i</sub> = N<super>*</super> "
                "(Delta sigma<sub>Rd</sub> / Delta sigma<sub>Ed,i</sub>)"
                "<super>k</super>",
                equation_key="fatigue.reinforcement.sn-life",
                equation_variant="power-law",
                ref=source,
                subst=(
                    f"{_fmt_sig(selected_bin['sn_reference_cycles'], 8)} &#183; "
                    f"({_fmt(selected_bin['sn_reference_ratio'], 8)})"
                    f"<super>{_fmt(selected_bin['sn_exponent'], 3)}</super>"
                ),
                result=(
                    "N<sub>R,i</sub> = "
                    f"{_fmt_sig(selected_bin['cycles_to_failure'], 8)} cycles"
                ),
                note=_html_escape(selected_bin.get("sn_branch") or ""),
            )
        else:
            self._small(
                "<b>Worked example unavailable:</b> the governing S-N branch "
                "does not retain its reference ratio."
            )
            return
        self._formula(
            "D<sub>i</sub> = n<sub>i</sub> / N<sub>R,i</sub>",
            equation_key="fatigue.reinforcement.bin-damage",
            ref=source,
            subst=(
                f"{_fmt_sig(selected_bin['cycles'], 8)} / "
                f"{_fmt_sig(selected_bin['cycles_to_failure'], 8)}"
            ),
            result=f"D<sub>i</sub> = {_fmt_sig(selected_bin['damage'], 8)}",
        )
        self._formula(
            "D = sum D<sub>i</sub>",
            equation_key="fatigue.reinforcement.miner-sum",
            ref=source,
            subst=" + ".join(_fmt_sig(value, 8) for value in damages),
            result=f"D = {_fmt_sig(damage_total, 8)}",
        )
        self._formula(
            "sigma<sub>Rd</sub> = f<sub>yk/proof</sub> / gamma<sub>s</sub>",
            equation_key="fatigue.reinforcement.yield-limit",
            ref=source,
            subst=(
                f"{_fmt(characteristic, 6)} / {_fmt(material_factor, 6)} MPa"
            ),
            result=f"sigma<sub>Rd</sub> = {_fmt(design_limit, 6)} MPa",
            note=_html_escape(
                fatigue_presentation.value(yield_check, "branch", "")
            ),
        )
        self._formula(
            "u<sub>yield</sub> = |sigma<sub>Ed</sub>| / "
            "sigma<sub>Rd</sub>",
            equation_key="fatigue.reinforcement.yield-utilisation",
            ref=source,
            subst=(
                f"|{_fmt(yield_stress, 6)}| / {_fmt(design_limit, 6)}"
            ),
            result=f"u<sub>yield</sub> = {_fmt(yield_util, 8)}",
        )
        self._formula(
            "u = max(D, u<sub>yield</sub>)",
            equation_key="fatigue.reinforcement.utilisation",
            ref=source,
            subst=(
                f"max({_fmt_sig(damage_total, 8)}, "
                f"{_fmt(yield_total, 8)})"
            ),
            result=(
                "u = "
                f"{_fmt(utilisation, 8)}"
            ),
            note=_html_escape(
                fatigue_presentation.value(result, "governing_criterion", "")
            ),
        )

    def _fatigue_concrete_formulas(
        self, spectrum, result, bin_rows, selection, reference
    ):
        """Publish one solver-retained governing concrete fatigue chain."""

        strength = fatigue_presentation.value(spectrum, "concrete_strength")
        selected_bin = next(
            (
                row for row in bin_rows
                if row["bin"] == str(selection.get("bin_name") or "")
            ),
            None,
        )
        if strength is None or selected_bin is None:
            self._small(
                "<b>Worked example unavailable:</b> the governing concrete "
                "strength or bin identity is absent."
            )
            return
        if reference is None:
            self._small(
                "<b>Worked example unavailable:</b> the governing concrete "
                "calculation source is absent."
            )
            return
        source = _html_escape(str(reference))
        self._h2("Textbook calculation - governing concrete fatigue")
        edition = str(fatigue_presentation.value(strength, "edition", ""))
        strength_published = False
        if edition == fatigue_core.EC2_2005:
            required = (
                "k1", "beta_cc_t0", "alpha_cc", "fck_mpa", "gamma_c",
                "high_strength_reduction", "fcd_fat_mpa",
            )
            values = {
                key: fatigue_presentation.evidence_number(
                    fatigue_presentation.value(strength, key)
                )
                for key in required
            }
            if all(value is not None for value in values.values()):
                self._formula(
                    "f<sub>cd,fat</sub> = k<sub>1</sub> beta<sub>cc</sub> "
                    "alpha<sub>cc</sub> f<sub>ck</sub> / gamma<sub>c</sub> "
                    "(1 - f<sub>ck</sub>/250)",
                    equation_key="fatigue.concrete.strength",
                    equation_variant="2005",
                    ref=source,
                    subst=(
                        f"{_fmt(values['k1'], 6)} &#183; "
                        f"{_fmt(values['beta_cc_t0'], 6)} &#183; "
                        f"{_fmt(values['alpha_cc'], 6)} &#183; "
                        f"{_fmt(values['fck_mpa'], 6)} / "
                        f"{_fmt(values['gamma_c'], 6)} &#183; "
                        f"(1 - {_fmt(values['fck_mpa'], 6)} / 250) = "
                        f"{_fmt(values['k1'], 6)} &#183; "
                        f"{_fmt(values['beta_cc_t0'], 6)} &#183; "
                        f"{_fmt(values['alpha_cc'], 6)} &#183; "
                        f"{_fmt(values['fck_mpa'], 6)} / "
                        f"{_fmt(values['gamma_c'], 6)} &#183; "
                        f"{_fmt(values['high_strength_reduction'], 6)} MPa"
                    ),
                    result=(
                        "f<sub>cd,fat</sub> = "
                        f"{_fmt(values['fcd_fat_mpa'], 6)} MPa"
                    ),
                )
                strength_published = True
        elif edition == fatigue_core.EC2_2023:
            beta = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "beta_cc_t0")
            )
            fck = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "fck_mpa")
            )
            gamma_c = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "gamma_c")
            )
            eta_raw = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "eta_cc_raw")
            )
            eta_cap = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "eta_cc_cap")
            )
            eta = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "eta_cc")
            )
            eta_fat_raw = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "eta_cc_fat_raw")
            )
            eta_fat_cap = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "eta_cc_fat_cap")
            )
            eta_fat = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "eta_cc_fat")
            )
            fcd_fat = fatigue_presentation.evidence_number(
                fatigue_presentation.value(strength, "fcd_fat_mpa")
            )
            if None not in (
                beta,
                fck,
                gamma_c,
                eta_raw,
                eta_cap,
                eta,
                eta_fat_raw,
                eta_fat_cap,
                eta_fat,
                fcd_fat,
            ):
                self._formula(
                    "eta<sub>cc</sub> = min((40/f<sub>ck</sub>)"
                    "<super>1/3</super>, 1.0)",
                    equation_key="fatigue.concrete.eta-cc",
                    ref=source,
                    subst=(
                        f"min((40 / {_fmt(fck, 6)})"
                        f"<super>1/3</super>, {_fmt(eta_cap, 8)}) = "
                        f"min({_fmt(eta_raw, 8)}, {_fmt(eta_cap, 8)})"
                    ),
                    result=f"eta<sub>cc</sub> = {_fmt(eta, 8)}",
                )
                self._formula(
                    "eta<sub>cc,fat</sub> = min(0.85 eta<sub>cc</sub>, 0.8)",
                    equation_key="fatigue.concrete.eta-cc-fat",
                    ref=source,
                    subst=(
                        f"min(0.85 &#183; {_fmt(eta, 8)}, "
                        f"{_fmt(eta_fat_cap, 8)}) = "
                        f"min({_fmt(eta_fat_raw, 8)}, "
                        f"{_fmt(eta_fat_cap, 8)})"
                    ),
                    result=f"eta<sub>cc,fat</sub> = {_fmt(eta_fat, 8)}",
                )
                self._formula(
                    "f<sub>cd,fat</sub> = beta<sub>cc</sub> "
                    "f<sub>ck</sub> eta<sub>cc,fat</sub> / gamma<sub>c</sub>",
                    equation_key="fatigue.concrete.strength",
                    equation_variant="2023",
                    ref=source,
                    subst=(
                        f"{_fmt(beta, 8)} &#183; {_fmt(fck, 6)} / "
                        f"{_fmt(gamma_c, 6)} &#183; {_fmt(eta_fat, 8)} MPa"
                    ),
                    result=f"f<sub>cd,fat</sub> = {_fmt(fcd_fat, 8)} MPa",
                )
                strength_published = True
        if not strength_published:
            self._small(
                "<b>Worked example unavailable:</b> the governing concrete "
                "strength record is incomplete or uses an unsupported edition."
            )
            return
        required = (
            "compression_min_design_mpa",
            "compression_max_design_mpa",
            "e_cd_min",
            "e_cd_max",
        )
        if any(selected_bin.get(key) is None for key in required):
            self._small(
                "<b>Worked example unavailable:</b> the governing concrete bin "
                "does not retain every normalized-stress operand."
            )
            return
        fcd_fat = fatigue_presentation.evidence_number(
            fatigue_presentation.value(result, "fcd_fat_mpa")
        )
        if fcd_fat is None:
            self._small(
                "<b>Worked example unavailable:</b> the governing concrete "
                "fatigue strength is absent from the selected fibre result."
            )
            return
        self._formula(
            "E<sub>cd,min/max</sub> = sigma<sub>c,min/max,Ed</sub> / "
            "f<sub>cd,fat</sub>",
            equation_key="fatigue.concrete.normalised-stress",
            ref=source,
            subst=(
                f"{_fmt(selected_bin['compression_min_design_mpa'], 6)} / "
                f"{_fmt(fcd_fat, 6)}; "
                f"{_fmt(selected_bin['compression_max_design_mpa'], 6)} / "
                f"{_fmt(fcd_fat, 6)}"
            ),
            result=(
                f"E<sub>cd,min</sub> = {_fmt(selected_bin['e_cd_min'], 8)}; "
                f"E<sub>cd,max</sub> = {_fmt(selected_bin['e_cd_max'], 8)}"
            ),
            note=(
                _html_escape(selected_bin.get("compression_min_state") or "")
                + " / "
                + _html_escape(selected_bin.get("compression_max_state") or "")
            ),
        )
        equivalent = selected_bin.get("equivalent_utilisation")
        if equivalent is not None:
            self._formula(
                "u<sub>eq</sub> = E<sub>cd,max</sub> + 0.43 "
                "sqrt(1 - E<sub>cd,min</sub>/E<sub>cd,max</sub>)",
                equation_key="fatigue.concrete.equivalent",
                ref=source,
                subst=(
                    f"{_fmt(selected_bin['e_cd_max'], 8)} + 0.43 sqrt(1 - "
                    f"{_fmt(selected_bin['e_cd_min'], 8)} / "
                    f"{_fmt(selected_bin['e_cd_max'], 8)})"
                ),
                result=f"u<sub>eq</sub> = {_fmt(equivalent, 8)}",
            )
        elif None not in (
            selected_bin.get("life_coefficient"),
            selected_bin.get("life_range_term"),
            selected_bin.get("cycles_to_failure"),
        ):
            life_branch = str(selected_bin.get("life_branch") or "")
            if life_branch == "variable compression":
                self._formula(
                    "log<sub>10</sub>N<sub>R,i</sub> = C "
                    "(1 - E<sub>cd,max</sub>) / "
                    "sqrt(1 - sigma<sub>c,min</sub>/sigma<sub>c,max</sub>)",
                    equation_key="fatigue.concrete.life",
                    equation_variant="variable-compression",
                    ref=source,
                    subst=(
                        f"{_fmt(selected_bin['life_coefficient'], 6)} &#183; "
                        f"(1 - {_fmt(selected_bin['e_cd_max'], 8)}) / "
                        f"sqrt(1 - "
                        f"{_fmt(selected_bin['compression_min_design_mpa'], 8)} / "
                        f"{_fmt(selected_bin['compression_max_design_mpa'], 8)}) = "
                        f"{_fmt(selected_bin['life_coefficient'], 6)} &#183; "
                        f"(1 - {_fmt(selected_bin['e_cd_max'], 8)}) / "
                        f"{_fmt(selected_bin['life_range_term'], 8)}"
                    ),
                    result=(
                        f"log<sub>10</sub>N<sub>R,i</sub> = "
                        f"{_fmt(selected_bin['log10_cycles_to_failure'], 8)}; "
                        f"N<sub>R,i</sub> = "
                        f"{_fmt_sig(selected_bin['cycles_to_failure'], 8)}"
                    ),
                    note=_html_escape(life_branch),
                )
            elif life_branch in {"zero compression", "constant compression"}:
                self._formula(
                    (
                        "sigma<sub>c,max</sub> = 0 implies "
                        "N<sub>R,i</sub> = +infinity"
                        if life_branch == "zero compression"
                        else "sigma<sub>c,min</sub> = sigma<sub>c,max</sub> "
                        "implies N<sub>R,i</sub> = +infinity"
                    ),
                    equation_key="fatigue.concrete.life",
                    equation_variant=(
                        "zero-compression"
                        if life_branch == "zero compression"
                        else "constant-compression"
                    ),
                    ref=source,
                    subst=(
                        f"sigma<sub>c,min</sub> = "
                        f"{_fmt(selected_bin['compression_min_design_mpa'], 8)} MPa; "
                        f"sigma<sub>c,max</sub> = "
                        f"{_fmt(selected_bin['compression_max_design_mpa'], 8)} MPa"
                    ),
                    result=(
                        "N<sub>R,i</sub> = "
                        f"{_fmt_sig(selected_bin['cycles_to_failure'], 8)}"
                    ),
                    note=_html_escape(life_branch),
                )
            else:
                self._small(
                    "<b>Worked example unavailable:</b> the governing concrete "
                    "life branch is not recognised."
                )
                return
            self._formula(
                "D<sub>i</sub> = n<sub>i</sub> / N<sub>R,i</sub>",
                equation_key="fatigue.concrete.bin-damage",
                ref=source,
                subst=(
                    f"{_fmt_sig(selected_bin['cycles'], 8)} / "
                    f"{_fmt_sig(selected_bin['cycles_to_failure'], 8)}"
                ),
                result=f"D<sub>i</sub> = {_fmt_sig(selected_bin['damage'], 8)}",
            )
            damages = [row.get("damage") for row in bin_rows]
            if all(value is not None for value in damages):
                self._formula(
                    "D = sum D<sub>i</sub>",
                    equation_key="fatigue.concrete.miner-sum",
                    ref=source,
                    subst=" + ".join(_fmt_sig(value, 8) for value in damages),
                    result=(
                        "D = "
                        f"{_fmt_sig(fatigue_presentation.value(result, 'damage'), 8)}"
                    ),
                )
        stress_bin_name = str(
            fatigue_presentation.value(result, "governing_stress_bin", "")
        )
        stress_bin = next(
            (row for row in bin_rows if row["bin"] == stress_bin_name),
            None,
        )
        if stress_bin is not None and stress_bin.get("e_cd_max") is not None:
            self._formula(
                "u<sub>sigma</sub> = E<sub>cd,max</sub>",
                equation_key="fatigue.concrete.stress-utilisation",
                ref=source,
                subst=_fmt(stress_bin["e_cd_max"], 8),
                result=(
                    "u<sub>sigma</sub> = "
                    f"{_fmt(fatigue_presentation.value(result, 'stress_utilisation'), 8)}"
                ),
            )
        candidates = [
            fatigue_presentation.evidence_number(
                fatigue_presentation.value(result, "damage_utilisation")
            ),
            fatigue_presentation.evidence_number(
                fatigue_presentation.value(result, "stress_utilisation")
            ),
            fatigue_presentation.evidence_number(
                fatigue_presentation.value(result, "equivalent_utilisation")
            ),
        ]
        search = fatigue_presentation.value(spectrum, "concrete_search")
        if search is not None and bool(
            fatigue_presentation.value(search, "converged", False)
        ):
            candidates.append(fatigue_presentation.evidence_number(
                fatigue_presentation.value(search, "upper_damage")
            ))
        candidates = [value for value in candidates if value is not None]
        if candidates:
            self._formula(
                "u = max(D, u<sub>sigma</sub>, u<sub>eq</sub>, "
                "u<sub>bound</sub>)",
                equation_key="fatigue.concrete.utilisation",
                ref=source,
                subst="max(" + ", ".join(
                    _fmt_sig(value, 8) for value in candidates
                ) + ")",
                result=f"u = {_fmt_sig(selection.get('utilisation'), 8)}",
                note=_html_escape(selection.get("criterion") or ""),
            )

    def _appendix(self):
        self.flow.append(NotAtTopPageBreak())
        self._h1("QA appendix - references and notes")
        lines = []
        plastic_results = self._result_values("plastic")
        elastic_results = self._result_values("elastic")
        shear_results = self._result_values("shear")
        torsion_results = self._result_values("torsion")
        combined_results = [
            case_out["combined"]
            for _, case_out in self._case_contexts("plastic")
            if case_out.get("combined") is not None
            and presentation.combined_bending_assessment_blocker(case_out) is None
        ]
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
    qa_appendix=None,
    profile=None,
) -> bytes:
    """Build the PDF report and return its bytes.

    ``progress`` is an optional ``callable(fraction, text)`` invoked as the report
    is assembled, so the UI can show a progress bar. ``profile`` selects the
    immutable presentation policy; figures remain a separate choice. The legacy
    ``qa_appendix`` flag maps ``False`` to Standard and ``True`` to Audit.
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
        profile=profile,
        qa_appendix=qa_appendix,
    ).build()
    buffer.seek(0)
    return buffer.getvalue()
