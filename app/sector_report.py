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

from app import report_summary_notation as report_notation

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
from reportlab.platypus.tableofcontents import TableOfContents

import case_analysis
import fatigue_inputs
import fatigue_presentation
import material_catalog
from app import modelled_direction
from app import elastic_display
from app import publication_equation_layout as publication_equations
from app import report_profiles, report_sources, publication_branding
from app import table_field_definitions as table_fields
import publication_image_export
from publication_items import PublicationCounter
from publication_notation import normalize_trusted_markup, shield_literal_markup
import publication_theme
import report_equation_contract
import report_diagrams
import viz
import result_presentation as presentation
import section_fields
from app import engineer_messages
from sector import capacity
from sector import codes as ec2_codes
from sector import detailing
from sector import shear_inputs
from sector import fatigue as fatigue_core
from sector import __licensee__ as SECTOR_LICENSEE
from sector.design_standards import (
    DesignBasisKey,
    InputGuidanceKey,
    get_design_basis,
    input_guidance,
)
from sector.engineer_message import EngineerMessage

_MM = 1000.0                       # metres -> millimetres for display
_KN = 1.0                          # forces already in kN
_BLUE = colors.HexColor(publication_theme.PALETTE.primary)
_GREY = colors.HexColor(publication_theme.PALETTE.muted)
_LINE = colors.HexColor(publication_theme.PALETTE.rule)
_HEAD_BG = colors.HexColor(publication_theme.PALETTE.report_header)
_A4_CONTENT_WIDTH = A4[0] - 40 * mm
_REPORT_FRAME_PADDING = 6.0
_A4_FRAME_USABLE_HEIGHT = A4[1] - 45 * mm - 2 * _REPORT_FRAME_PADDING
_MIN_REPORT_TABLE_FONT = 9.0
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
    ("torsion.utilisation", None),
    ("torsion.subtube.governing-utilisation", None),
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
_REPORT_RESULT_WARNING = EngineerMessage(
    "REPORT-RESULT-WARNING",
    "Review the calculation warnings in Sector before using this report",
)
_REPORT_RESULT_ERROR = EngineerMessage(
    "REPORT-RESULT-ERROR",
    "Review the calculation inputs and recalculate before using this report",
)



def _fatigue_report_label(value, family, *, kind=None):
    """Describe exact retained fatigue enums at the report boundary."""
    labels = {
        "kind": {
            "mild": "Reinforcing steel",
            "prestress": "Prestressing steel",
        },
        "stress_model": {
            "fixed": "Fixed characteristic stress range",
            "ec2_2023_bar_diameter": "EC2:2023 bar-diameter-dependent stress range",
            "ec2_2023_welded_diameter": "EC2:2023 welded-bar-diameter-dependent stress range",
        },
        "range_basis": {
            "characteristic": "Characteristic stress range",
            "design": "Design stress range",
        },
        "sn_branch": {
            "zero stress range": "Zero stress range",
            "k1 (at or above knee)": "Exponent k<sub>1</sub>: stress range at or above the S-N curve knee",
            "k2 (below knee)": "Exponent k<sub>2</sub>: stress range below the S-N curve knee",
        },
    }
    if family == "yield_branch":
        strengths = {
            ("mild", "tension fytk"): "Tensile yield strength f<sub>ytk</sub>",
            ("mild", "compression fyck"): "Compressive yield strength f<sub>yck</sub>",
            ("mild", "compression fytk fallback"): (
                "Tensile yield strength f<sub>ytk</sub> is used for compression "
                "because a compressive yield strength is unavailable."
            ),
            ("prestress", "tension fytk"): "Tensile 0.1% proof strength f<sub>p0.1k</sub>",
            ("prestress", "compression fytk fallback"): (
                "Tensile 0.1% proof strength f<sub>p0.1k</sub> is used for compression "
                "because a compressive proof strength is unavailable."
            ),
        }
        return strengths.get((kind, value), _html_escape(value))
    return labels.get(family, {}).get(value, _html_escape(value))


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
        return (
            "DS/EN 1992-1-1:2023, 5.2.4(1)-(3), Formula (5.11) "
            "and Figure 5.2"
        )
    return f"{code.label}, 3.2.7"


def _prestress_standard_reference(preset):
    """Return the exact design-law source for a recognised tendon preset."""

    code = ec2_codes.CODES.get(str(preset))
    if code is None:
        return None
    if code.key == "EC2-2023":
        return (
            "DS/EN 1992-1-1:2023, 5.3.3(1)-(3), Formula (5.12) "
            "and Figure 5.3"
        )
    return f"{code.label}, 3.3.6"


def _concrete_ultimate_reference(preset):
    """Return the selected concrete-law source without inferring a preset."""

    code = ec2_codes.CODES.get(str(preset))
    if code is None:
        return None
    if code.key == "EC2-2023":
        return (
            "DS/EN 1992-1-1:2023, 8.1.1(2)-(3) and 8.1.2(1), "
            "Formula (8.4)"
        )
    return (
        f"{code.label}, 3.1.7, Formula (3.17), and Table 3.1"
    )


_INPUT_REFERENCE_BASIS_BY_EDITION = {
    ec2_codes.EC2_2005.label: DesignBasisKey.FIRST_GEN_BASE,
    ec2_codes.EC2_2005_DKNA.label: DesignBasisKey.FIRST_GEN_DK_NA_2024,
    ec2_codes.EC2_2023.label: DesignBasisKey.PUBLISHED_2023,
}


def _input_reference_source(edition, key, *, project_defined=False):
    """Return one registry-owned input source for report publication."""

    basis_key = _INPUT_REFERENCE_BASIS_BY_EDITION.get(edition)
    if basis_key is None:
        if project_defined:
            return "Project-defined input; no Eurocode source inferred."
        return "Selected edition has no registered input source."
    return input_guidance(basis_key, key).source


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

    if isinstance(value, report_notation.ReportText):
        return _LiteralReportText(report_notation.render(
            value, lambda part: _html_escape(part, quote=quote)))
    escaped = shield_literal_markup(value, quote=quote)
    return _LiteralReportText(_GREEK_RE.sub(
        lambda match: "".join(
            f"&#{ord(character)};" for character in match.group(1)
        ),
        escaped,
    ))


def _torsion_case_authority_rows(inp):
    """Return report-table rows for each Plastic case's torsion authority."""

    if inp.get("plastic_cases") is not None:
        rows = []
        authorities = inp.get(capacity.TORSION_CASE_AUTHORITIES_KEY)
        for record in case_analysis.case_records(inp, "plastic"):
            case_name = record.get("name") or "Unnamed case"
            authority = capacity.torsion_case_authority(
                authorities,
                record.get("name"),
            )
            rows.extend([
                [
                    "Torsion design basis - " + _html_escape(case_name),
                    _html_escape(
                        authority[capacity.TORSION_CASE_DESIGN_BASIS_KEY]
                    ),
                ],
                [
                    "Torsion member scope - " + _html_escape(case_name),
                    _html_escape(
                        authority[capacity.TORSION_CASE_MEMBER_SCOPE_KEY]
                    ),
                ],
            ])
        return rows
    direct_case = inp.get("plastic_case")
    case_name = (
        str(direct_case.get("id") or "Current action")
        if isinstance(direct_case, Mapping)
        else "Current action"
    )
    return [
        [
            "Torsion design basis - " + _html_escape(case_name),
            _html_escape(
                inp.get("torsion_design_basis")
                or capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
        ],
        [
            "Torsion member scope - " + _html_escape(case_name),
            _html_escape(
                inp.get("torsion_member_scope")
                or capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
            ),
        ],
    ]


def _report_resistance_governing_label(value):
    """Format exact native resistance labels and escape all other text."""
    labels = {
        "stirrups (VRd,s)": "stirrups (V<sub>Rd,s</sub>)",
        "crushing (VRd,max)": "crushing (V<sub>Rd,max</sub>)",
        "links (tau_Rd,sy)": "links (&#964;<sub>Rd,sy</sub>)",
        "compression field (sigma_cd)": "compression field (&#963;<sub>cd</sub>)",
        "stirrups (TRd,s)": "stirrups (T<sub>Rd,s</sub>)",
        "crushing (TRd,max)": "crushing (T<sub>Rd,max</sub>)",
    }
    return labels.get(str(value), _html_escape(str(value)))


def _report_fatigue_utilization_map(outer, holes, bars, tendons, spectrum, *, title):
    """Set report-owned labels on a fresh native fatigue map."""
    figure = viz.fatigue_utilisation_map_figure(
        outer, holes, bars, tendons, spectrum, title=title,
    )
    figure.layout.coloraxis.colorbar.title.text = "Utilization"
    for trace in figure.data:
        if trace.name == "concrete fibres":
            trace.name = "concrete fibers"
    for annotation in figure.layout.annotations or ():
        if annotation.text == "utilisation limit = 1.00":
            annotation.text = "utilization limit = 1.00"
    return figure


def _report_chord_mrd_label(axis, m_off, conditional):
    """Explain a chord resistance using report notation and literal-safe axes."""
    axis_text = _html_escape(axis)
    off = "M<sub>y</sub>" if axis == "x" else "M<sub>x</sub>"
    if conditional and abs(m_off) > 1e-9:
        return (
            f"(capacity about {axis_text} at the applied N, with coexisting "
            f"{off} = {m_off:.1f} kNm). The M-M envelope point carries both moments"
        )
    if conditional:
        return f"(bending about {axis_text} at the applied N)"
    return (
        f"(pure-axis bending about {axis_text} at the applied N). The conditional "
        "biaxial solve did not converge. This capacity can overstate the chord resistance"
    )


def _result_reason(value, family, context):
    """Resolve one retained diagnostic before placing it in report markup."""

    return presentation.result_reason(value, family, context=context)


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
            "_sector_results_overview",
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


class _ResultsOverviewTable(_PaginatedReportTable):
    """Keep the governing note with the final overview-table fragment."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sector_trailing_note = None
        self._sector_trailing_note_gap = 2.0
        self._sector_trailing_note_height = 0.0

    def _measure_trailing_note(self, availWidth, availHeight):
        note = self._sector_trailing_note
        if note is None:
            self._sector_trailing_note_height = 0.0
            return 0.0, 0.0
        width, height = note.wrap(availWidth, availHeight)
        self._sector_trailing_note_height = height
        return width, height

    def wrap(self, availWidth, availHeight):
        table_width, table_height = super().wrap(availWidth, availHeight)
        note_width, note_height = self._measure_trailing_note(
            availWidth, availHeight
        )
        if self._sector_trailing_note is None:
            return table_width, table_height
        return (
            max(table_width, note_width),
            table_height + self._sector_trailing_note_gap + note_height,
        )

    def split(self, availWidth, availHeight):
        note = self._sector_trailing_note
        if note is None:
            return super().split(availWidth, availHeight)

        fragments = super().split(availWidth, availHeight)
        if len(fragments) <= 1:
            _note_width, note_height = self._measure_trailing_note(
                availWidth, availHeight
            )
            reserved_height = self._sector_trailing_note_gap + note_height
            fragments = super().split(
                availWidth,
                max(0.0, availHeight - reserved_height),
            )
        if len(fragments) <= 1:
            return []

        for fragment in fragments:
            fragment._sector_trailing_note = None
        fragments[-1]._sector_trailing_note = note
        fragments[-1]._sector_trailing_note_gap = (
            self._sector_trailing_note_gap
        )
        return fragments

    def draw(self):
        note = self._sector_trailing_note
        if note is None:
            return super().draw()
        note_height = self._sector_trailing_note_height
        self.canv.saveState()
        try:
            self.canv.translate(
                0, note_height + self._sector_trailing_note_gap
            )
            super().draw()
        finally:
            self.canv.restoreState()
        note.drawOn(self.canv, 0, 0)


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
            self.drawString(
                20 * mm,
                286 * mm,
                self._fit(self._header, 136 * mm, _FONT, 7.5),
            )
            if self._revision is not None:
                revision = self._fit(
                    f"Rev: {self._revision or '-'}",
                    30 * mm,
                    _FONT,
                    7.5,
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
    """Register report destinations for the outline and visible contents."""

    def afterFlowable(self, flowable):
        key = getattr(flowable, "_sector_bookmark", None)
        if key:
            level = int(getattr(flowable, "_sector_outline_level", 0))
            title = getattr(flowable, "_sector_outline", key)
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(
                title,
                key,
                level=level,
                closed=False,
            )
            if getattr(flowable, "_sector_toc_entry", False):
                # Outline titles are plain PDF strings, while TableOfContents
                # reparses its title as Paragraph markup. Keep the decoded plain
                # title for bookmarks and escape the separate visible-contents
                # payload so a user identifier can never become active markup.
                self.notify(
                    "TOCEntry",
                    (level, _html_escape(str(title)), self.page, key),
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
    for role in ("body", "small"):
        out[role].allowWidows = 0
        out[role].allowOrphans = 0
    out["formula"] = ParagraphStyle(
        "f", parent=ss["Normal"], fontSize=9.5, leading=14,
        leftIndent=12, rightIndent=6, spaceBefore=2, spaceAfter=3,
        fontName=_FONT, wordWrap="LTR", splitLongWords=True,
    )
    out["formula_id"] = ParagraphStyle(
        "fi", parent=ss["Normal"], fontSize=9.5, fontName=_FONT_BOLD,
        leading=12, leftIndent=12, rightIndent=6, textColor=_BLUE,
        spaceBefore=2, spaceAfter=1,
    )
    out["ref"] = ParagraphStyle("r", parent=ss["Normal"], fontSize=9.5,
                               fontName=_FONT, leading=12, leftIndent=12,
                               rightIndent=6, textColor=_GREY, spaceAfter=6)
    out["publication_ref"] = themed(
        "pr", ss["Normal"], "publication_ref"
    )
    out["publication_caption"] = themed(
        "pc", ss["Normal"], "publication_caption"
    )
    out["toc_h1"] = ParagraphStyle(
        "toc-h1", parent=out["body"], fontSize=9.5, leading=12,
        leftIndent=0, firstLineIndent=0, spaceBefore=1, spaceAfter=1,
    )
    out["toc_h2"] = ParagraphStyle(
        "toc-h2", parent=out["small"], fontSize=9.5, leading=12,
        leftIndent=14, firstLineIndent=0, spaceBefore=0, spaceAfter=0,
    )
    out["formula_symbol"] = ParagraphStyle(
        "fs", parent=ss["Normal"], fontSize=9.5, leading=12.5,
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
    from another export failure. Either condition terminates the owned worker;
    a later independent publication attempt can start a clean process.
    """

    try:
        png = publication_image_export.export_png(
            fig,
            width=w_px,
            height=h_px,
            scale=2,
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


_GAMMA_V_REPORT_DECIMALS = 3


def _fmt_gamma_v(value):
    """Use one precision for the selected factor on every report surface."""

    return _fmt(value, _GAMMA_V_REPORT_DECIMALS)


def _fmt_sig(v, sig=6):
    """Format small engineering values without rounding nonzero evidence to zero."""
    if v is None:
        return "-"
    if isinstance(v, float) and not math.isfinite(v):
        return "-inf" if math.isinf(v) and v < 0.0 else "inf"
    return f"{v:.{sig}g}"


def _fmt_crack_ratio(value):
    """Retain eight decimals unless their relative rounding exceeds one ppm."""
    text = _fmt(value, 8)
    if value and abs(float(text) - float(value)) / abs(float(value)) > 1e-6:
        return _fmt_sig(value, 9)
    return text


def _compact_equation_numbers(source, *, decimal_places=_EQUATION_DECIMAL_PLACES):
    """Round display-only equation values without hiding tiny nonzero terms."""

    if not isinstance(source, str):
        raise TypeError("equation display source must be text")

    quantum = decimal.Decimal(1).scaleb(-decimal_places)

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
                quantum,
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
                    quantum,
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


def _scientific_equation_markup(text):
    """Keep each expanded scientific number as one mathematical operand."""
    def expand(match):
        mantissa = match.group(1)
        if mantissa.startswith("."):
            mantissa = "0" + mantissa
        if mantissa.endswith("."):
            mantissa += "0"
        return (
            "(" + mantissa + " &#215; 10<super>"
            + str(int(match.group(2))) + "</super>)"
        )

    return re.sub(
        r"(?<![A-Za-z0-9_.])([0-9]+(?:\.[0-9]*)?|\.[0-9]+)[eE]([+-]?[0-9]+)(?![A-Za-z0-9_.])",
        expand,
        text,
    )


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
        self._source_register = report_sources.validate(
            self.meta.get("source_register", [])
        )
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
            presentation.validated_worked_example_selection(
                self._base_inp,
                self._base_out,
            )
            if (
                isinstance(selection, Mapping)
                and type(selection.get("schema")) is int
                and selection.get("schema") == 1
            )
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
            try:
                current_records = case_analysis.case_records(self._base_inp, family)
            except (KeyError, TypeError, ValueError, OverflowError):
                current_records = []
            authority = presentation._worked_case_contexts(
                self._base_inp,
                self._base_out,
                family,
            )
            for index, (name, case_inp, case_results, current) in enumerate(
                authority
            ):
                entry = entries[index] if index < len(entries) else {}
                actions = entry.get("actions") or {}
                if not isinstance(case_inp, Mapping) and not current:
                    # Removed or renamed retained rows are not current report cases.
                    continue
                if not isinstance(case_inp, Mapping):
                    try:
                        case_inp = (
                            case_analysis.plastic_case_input(
                                self._base_inp, actions
                            )
                            if family == "plastic"
                            else case_analysis.elastic_case_input(
                                self._base_inp, actions
                            )
                        )
                    except (KeyError, TypeError, ValueError, OverflowError):
                        case_inp = dict(self._base_inp)
                else:
                    case_inp = dict(case_inp)
                matching_actions = [
                    record for record in current_records if record.get("name") == name
                ]
                case_inp["_report_case_actions"] = (
                    dict(matching_actions[0])
                    if current and len(matching_actions) == 1
                    else {"name": name}
                )
                case_inp["_report_case_current"] = bool(current)
                contexts.append((case_inp, case_results))
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

    def _plastic_publication_authority(self):
        """Return the current table-level plastic evidence for named cases."""

        return presentation.plastic_publication_authority(
            self.inp, self.out, self._base_out,
        )

    def _shear_publication_authority(self):
        """Use the selected case's shear; an absent zero-shear result is intentional."""

        shear = self.out.get("shear")
        return shear if isinstance(shear, Mapping) else None

    def _current_case_inputs(self, family):
        """Return the canonical current input register for one case family."""

        table_key = f"{family}_cases"
        if table_key in self._base_inp:
            try:
                records = case_analysis.case_records(self._base_inp, family)
                return [
                    (
                        case_analysis.plastic_case_input(self._base_inp, record)
                        if family == "plastic"
                        else case_analysis.elastic_case_input(
                            self._base_inp,
                            record,
                        )
                    )
                    for record in records
                ]
            except (KeyError, TypeError, ValueError, OverflowError):
                return []
        return [self._base_inp] if self._case_contexts(family) else []

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
            (case_inp, case_out)
            for case_inp, case_out in self._case_contexts("plastic")
            if self._case_id(case_inp, "plastic") == selected.get("case_id")
        ]
        return (
            len(matches) == 1
            and matches[0][1].get("combined") is not None
            and presentation.combined_bending_assessment_blocker(
                matches[0][1],
                matches[0][0],
            ) is None
        )

    def _result_values(self, key):
        family = "elastic" if key == "elastic" else "plastic"
        return [
            result[key]
            for case_inp, result in self._case_contexts(family)
            if case_inp.get("_report_case_current") is not False
            and key in result
        ]

    def _case_register(self, family):
        """Escaped case register for cover-page document control."""
        contexts = self._current_case_inputs(family)
        if self.profile.key == "Brief":
            return _LiteralReportText(", ".join(
                presentation.action_set(case_inp, family)["id"] or "ID NOT SET"
                for case_inp in contexts
            ))
        return _LiteralReportText("; ".join(
            _report_action_set_text(case_inp, family)
            for case_inp in contexts
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
        heading._sector_outline_level = 0
        heading._sector_toc_entry = True
        heading.keepWithNext = 1
        if reserve:
            self.flow.append(CondPageBreak(reserve))
        self.flow.append(heading)

    def _h2(self, text, *, reserve=170):
        self._subsection += 1
        self._table_subsection_context = _greek(f"Subsection: {text}")
        self._publication_subsection_title = Paragraph(
            _greek(str(text)), self.s["small"]
        ).getPlainText().strip()
        heading_text = (
            f"{self._chapter}.{self._subsection} {text}"
            if self.profile.key == "Audit" and self._chapter
            else text
        )
        # ``keepWithNext`` can be defeated when the following object is a
        # nested indivisible equation/table wrapper. Reserve enough space before
        # placing the heading for at least one substantive following row.
        # Reserve enough room for the heading and the first indivisible
        # equation/table block.  A smaller guard still allowed a heading plus
        # its tiny identity row to fit while the actual calculation moved to
        # the next page.
        previous = self.flow[-1] if self.flow else None
        follows_chapter_heading = (
            isinstance(previous, Paragraph)
            and getattr(previous, "_sector_outline_level", None) == 0
        )
        if reserve and not follows_chapter_heading:
            self.flow.append(CondPageBreak(reserve))
        heading = Paragraph(_greek(heading_text), self.s["h2"])
        heading.keepWithNext = 1
        if self._chapter:
            heading._sector_bookmark = (
                f"sector-section-{self._chapter}-{self._subsection}"
            )
            heading._sector_outline = heading.getPlainText()
            heading._sector_outline_level = 1
            heading._sector_toc_entry = self.profile.key == "Audit"
        self.flow.append(heading)

    def _p(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["body"]))

    def _small(self, text, *, keep_with_next=False):
        paragraph = Paragraph(_greek(text), self.s["small"])
        if keep_with_next:
            paragraph.keepWithNext = 1
            paragraph._sector_table_lead = True
        self.flow.append(paragraph)

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
        self.flow.append(table)

    def _case_line(self, family, title=""):
        case_name = presentation.action_set(self.inp, family)["id"]
        self._small("<b>Case:</b> " + _report_action_set_text(self.inp, family)
                    + self._project_source_link(family.title(), case_name))
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
                caption='Concurrent section actions',
            )
            if title.startswith(("Shear", "Combined", "Torsion")):
                self._small(
                    "<b>Shear tension faces:</b> V<sub>x,Ed</sub> = "
                    f"{_html_escape(report_diagrams.shear_face_text('vx', actions.get('vx_face', 'auto')))}; "
                    "V<sub>y,Ed</sub> = "
                    f"{_html_escape(report_diagrams.shear_face_text('vy', actions.get('vy_face', 'auto')))}."
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
        self._h1(
            f"{title} - {_html_escape(case_id)}",
            reserve=180,
        )
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
        retained_rows = presentation.multi_case_summary_rows(
            self._base_inp, self._base_out
        )
        selected = presentation.governing_summary_rows(retained_rows)
        rows = presentation.governing_result_rows(selected)
        information_rows = presentation.governing_information_rows(selected)
        self._h2("Results overview")
        self._small(
            "The table shows the governing result for each check type. Each "
            "comparison has its own status; quantities without a limit are "
            "labeled CALCULATED."
        )
        # Keep the explanatory lead-in with the table's first page.  This still
        # lets genuinely oversized project overviews use the native row splitter.
        self.flow[-1].keepWithNext = 1
        data = [[
            "Check", "Action set", "Status", "Result", "Criterion", "Source / note"
        ]]
        def _overview_group(row):
            status = str(row["status"]).upper()
            if status == "CALCULATED" or row["criterion"] == "Output only":
                return "Calculated outputs"
            return "Checks and comparisons"

        def _overview_note_parts(row):
            source = str(row.get("source") or "").strip()
            case_type = str(row.get("case_type") or "").strip()
            note = report_notation.row_field(row, "note") or ""
            note = note.strip()
            parts = []
            if source not in {"", "-"}:
                parts.append("Source: " + source)
            elif case_type not in {"", "-"}:
                parts.append(case_type)
            if note:
                parts.extend(report_notation.note_parts(note))
            return tuple(parts) or ("-",)

        group_rows = []
        status_rows = []
        result_notes = []
        previous_group = None
        for row in rows:
            group_label = _overview_group(row)
            if group_label != previous_group:
                group_rows.append((len(data), group_label))
                data.append([group_label, "", "", "", "", ""])
                previous_group = group_label
            status_rows.append((len(data), row["status"]))
            note_id = len(result_notes) + 1
            result_notes.append((note_id, row, _overview_note_parts(row)))
            data.append([
                _html_escape(row["check"]), _html_escape(row["case"]),
                row["status"],
                _html_escape(report_notation.row_field(row, "result")),
                _html_escape(report_notation.row_field(row, "criterion")),
                f'<link href="#result-note-{note_id}">Note {note_id}</link>',
            ])
        summary_font = 9.5
        body = ParagraphStyle(
            "summary-cell", parent=self.s["body"], fontSize=summary_font,
            fontName=_FONT, leading=summary_font + 1.6,
            embeddedHyphenation=2,
        )
        head = ParagraphStyle(
            "summary-head", parent=body, fontName=_FONT_BOLD,
        )
        status_body = ParagraphStyle(
            "summary-status", parent=body, embeddedHyphenation=0,
        )
        formatted = []
        for index, row in enumerate(data):
            style = head if index == 0 or any(
                index == group_index for group_index, _label in group_rows
            ) else body
            formatted.append([
                Paragraph(
                    _table_script_markup(_greek(str(cell)), summary_font),
                    status_body if column == 2 and style is body else style,
                )
                for column, cell in enumerate(row)
            ])
        table_item = self._publication_counter.issue(
            "Table", "Results overview across calculated checks"
        )
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
        table = _ResultsOverviewTable(
            formatted,
            colWidths=[
                36 * mm, 23 * mm, 34 * mm,
                29 * mm, 29 * mm, 19 * mm,
            ],
            repeatRows=1 + context_count + 1,
            hAlign="LEFT",
            splitByRow=1,
            splitInRow=1,
        )
        vertical_padding = 3
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
                ("NOSPLIT", (0, table_index), (-1, table_index + 1)),
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
            "CONDITIONAL": colors.HexColor("#FFF4D6"),
            "NOT ASSESSED": colors.HexColor("#FFF4D6"),
            "NOT RUN": colors.HexColor("#EEF2F6"),
            "NOT CALCULATED": colors.HexColor("#EEF2F6"),
            "NOT APPLICABLE": colors.HexColor("#EEF2F6"),
            "NOT REQUESTED": colors.HexColor("#EEF2F6"),
            "STALE": colors.HexColor("#FFF4D6"),
            "EXCEEDS USER-SPECIFIED LIMIT": colors.HexColor("#FFF4D6"),
            "PROVIDED AREA BELOW CALCULATED REQUIREMENT": colors.HexColor("#FFF4D6"),
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
        table.keepWithNext = 0
        if self.profile.key == "Brief":
            governing_note = (
                "The table shows one governing row per engineering check type."
            )
        else:
            governing_note = (
                "The table shows one governing row for each engineering check type."
            )
        table._sector_trailing_note = Paragraph(
            _greek(governing_note), self.s["small"]
        )
        self.flow.append(table)
        self._h2("Governing result notes", reserve=100)
        self._p(
            "Read each result with its numbered note. The notes identify the "
            "source, governing condition and limits of the assessment."
        )
        for note_id, row, parts in result_notes:
            self._p(
                f'<a name="result-note-{note_id}"/><b>Note {note_id}. '
                f"{_html_escape(row['check'])}: {_html_escape(row['case'])}.</b>"
            )
            self.flow[-1].keepWithNext = 1
            for index, part in enumerate(parts):
                self._p(_html_escape(part))
                if index + 1 < len(parts):
                    self.flow[-1].keepWithNext = 1
        if information_rows:
            self._small("<b>Scope and calculation state</b>", keep_with_next=True)
            for row in information_rows:
                self._small(
                    f"{_html_escape(row['check'])} | "
                    f"{_html_escape(row['case'])} | "
                    f"{_html_escape(row['status'])} | "
                    f"{_html_escape(report_notation.row_field(row, 'result'))}"
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

    def _preceding_headings(self, start):
        """Attach immediately preceding headings to their first content block."""
        while start and isinstance(self.flow[start - 1], Paragraph) and self.flow[start - 1].getKeepWithNext():
            start -= 1
        return start

    def _keep_from(self, start):
        """Keep the flowables added since ``start`` together when they fit a page."""
        start = self._preceding_headings(start)
        block = []
        equations = []
        for item in self.flow[start:]:
            equations.extend(getattr(item, "_sector_equations", ()))
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
        group = KeepTogether(block)
        if equations:
            group._sector_equations = tuple(equations)
        self.flow[start:] = [group]

    def _keep_measured_calculation_from(self, start):
        """Keep a bounded table/equation calculation together using real heights.

        ``_EquationFlowable`` is itself a ``KeepTogether`` and therefore reports
        ReportLab's deliberately artificial height when nested.  Flatten its
        visible rows for this outer layout group, while retaining the sealed
        equation objects as publication metadata on the group.
        """
        start = self._preceding_headings(start)
        block = []
        equations = []
        for item in self.flow[start:]:
            if isinstance(item, _EquationFlowable):
                equations.append(item)
                block.extend(item._content)
            elif isinstance(item, KeepTogether):
                equations.extend(getattr(item, "_sector_equations", ()))
                block.extend(item._content)
            else:
                block.append(item)
        group = KeepTogether(block)
        group._sector_equations = tuple(equations)
        self.flow[start:] = [group]

    def _standard_result_projection(self, anchor, symbol, result, source, note, expr):
        """Group adjacent final outputs with a source retained for every row."""
        scope = (self._chapter, self._subsection,
                 self._table_section_context, self._table_subsection_context,
                 self._table_assessment_context)
        group = getattr(self, "_standard_projection_group", None)
        if group is None or group["scope"] != scope or group["end"] != len(self.flow) or any(
                old is not new for old, new in zip(group["tail"], self.flow[group["start"]:])):
            start = self._preceding_headings(len(self.flow))
            group = {"scope": scope, "start": start, "rows": [], "item": None,
                     "headings": tuple(self.flow[start:])}
        else:
            del self.flow[group["start"]:]
            self.flow.extend(group["headings"])
        condition = note or ""
        if symbol is None or source == _DERIVED_EQUATION_SOURCE:
            condition += ("<br/>" if condition else "") + "Method: " + _equation_math(expr)
        group["rows"].append([
            f'<a name="{anchor}"/>' + (symbol or "Method relation"),
            result, ((condition + "<br/>") if condition else "")
            + "<b>Source:</b> " + source,
        ])
        group["item"] = self._table(
            [["Quantity", "Result", "Method, condition and source"], *group["rows"]],
            [35 * mm, 65 * mm, 65 * mm], font=9,
            caption="Final results and used design parameters",
            publication_item=group["item"],
        )
        group["end"] = len(self.flow)
        group["tail"] = tuple(self.flow[group["start"]:])
        self._standard_projection_group = group

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

        # Retain the ratio precision needed to reproduce crack-spacing arithmetic.
        equation_decimals = (8 if equation_key in {
            "crack.effective-reinforcement.ratio", "crack.2005.spacing",
            "crack.2023.spacing",
        } else _EQUATION_DECIMAL_PLACES)

        def display_numbers(value):
            return _compact_equation_numbers(value, decimal_places=equation_decimals)

        source = ref if ref is not None else _DERIVED_EQUATION_SOURCE
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"Equation {equation_key} requires source text.")

        if self.profile.key == "Standard":
            # Validate the complete retained calculation above before projecting
            # its result and provenance. Audit owns the numerical worked chain.
            anchor = (
                f"sector-method-{self._chapter}-{self._subsection}-"
                + _equation_anchor_key(equation_key)
            )
            self._equations[scope] = {
                "key": equation_key, "anchor": anchor, "number": None,
            }
            if not report_profiles.standard_retains_equation_result(equation_key):
                return
            self._standard_result_projection(
                anchor, contract.result_symbol,
                display_numbers(result) if result else
                "Method relation; result reported in the assessment table.",
                source, note, expr,
            )
            return

        display_substitution = (
            display_numbers(subst) if subst else None
        )
        display_result = display_numbers(result) if result else None

        compiled_expression = publication_equations.compile_report_math(expr)
        compiled_substitution = (
            publication_equations.compile_report_fragment(_scientific_equation_markup(display_substitution))
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
                    _scientific_equation_markup(display_result)
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

        # The internal key remains attached to the flowable and registry for
        # validation and cross-references. Published reports identify equations
        # only by their report number; an engineer does not need the software's
        # internal key to review or reproduce the calculation.
        identity = (
            f"Equation ({number})" if number is not None else "Method relation"
        )
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
            result_label = "Result:"
            quantity_text = f"{visible_result_symbol} [{visible_result_unit}]"
            lines.append(publication_equations.EquationLine(
                "result-quantity",
                publication_equations.compile_report_fragment(
                    f"{contract.result_symbol} [{normalize_trusted_markup(display_unit)}]"
                ),
                "Result quantity:",
                "Result quantity: " + quantity_text,
            ))
            result_plain_text = Paragraph(
                "<b>Result: "
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
                f"{_equation_math(symbol.markup)}: "
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
                    if target["number"] else "Prior method relation"
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
        source_row = _equation_paragraph(
            source_markup,
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
        start = len(self.flow)
        self.flow.append(equation)
        if self._preceding_headings(start) < start:
            self._keep_measured_calculation_from(start)

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
                # Preserve ordinary body words even in a narrow authored column.
                # Long unbroken identities can still wrap; their floor is bounded
                # at one third of the page, while numbers retain their full atom.
                required = max(
                    required,
                    (paragraph.minWidth() if header and row_index == 0
                     else min(paragraph.minWidth(),
                              max(authored_width, _A4_CONTENT_WIDTH / 3))),
                    # Table layout may round an exact string-width boundary
                    # down; retain a negligible guard against splitting a digit.
                    numeric_width + 1e-6 if numeric_width else 0.0,
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
        publication_item=None,
    ):
        table_start = len(self.flow)
        if not data or not data[0]:
            raise ValueError("A report table requires at least one cell.")
        column_count = len(data[0])
        if any(len(row) != column_count for row in data):
            raise ValueError("Every report table row must retain the same columns.")
        if len(widths) != column_count:
            raise ValueError("Report table widths must match the column count.")
        table_leads = []
        while self.flow and getattr(self.flow[-1], "_sector_table_lead", False):
            table_leads.insert(0, self.flow.pop().text)
        table_start = len(self.flow)
        table_lead_markup = "<br/>".join(table_leads)
        if table_lead_markup:
            table_lead_markup += "<br/>"
        profile_floor = 9.5
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
                # Prose remains left-aligned. Numeric cells use a shared edge;
                # multiline explanations must not become centered paragraphs.
                st = ParagraphStyle("x", parent=st, alignment=TA_LEFT)
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
            caption = subject
            if first_header.lower() not in subject.lower():
                caption += f": {first_header}"
        table_item = publication_item or self._publication_counter.issue("Table", str(caption))
        # A long table (the sweep / per-bar tables) may split across pages; a short
        # one is kept whole so it never strands a row on an otherwise empty page.
        # The first caption row owns the destination, so it cannot be separated
        # from its object by a separate self-reference paragraph.
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
            panel_lead = ""
            if len(panels) > 1:
                labels = (
                    [rows[0][index].getPlainText() for index in columns]
                    if header else [f"Column {index + 1}" for index in columns]
                )
                panel_lead = (
                    f"<b>Column panel {panel_number} of {len(panels)}:</b> "
                    + ", ".join(_html_escape(label) for label in labels)
                    + "<br/>"
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
                (table_lead_markup if panel_number == 1 else "")
                + panel_lead + f"{anchor}<b>{visible_label}.</b> "
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
            # The first fragment of each horizontal panel retains its lead.
            # Its caption already says "continued" when appropriate.
            table._sector_is_continuation = False
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
            if table_lead_markup or panel_lead:
                # A separate trailing spacer can create an empty final page.
                # Table splitting carries spaceAfter on the last fragment only.
                table.spaceAfter = 4
            self.flow.append(KeepTogether(table) if keep else table)
            if not (table_lead_markup or panel_lead):
                self._gap(4)
        if self._preceding_headings(table_start) < table_start:
            self._keep_from(table_start)
        return table_item

    def _fig(self, fig, w_mm=150, h_mm=95, caption=None, *, export_size=None):
        if not self.figures:
            return
        # Once an export has wedged the browser (a full-timeout hang), stop trying:
        # every further _fig_png would block for the whole timeout again.
        if self._export_hung:
            raise ReportFigureError(
                "Engineering-figure export previously timed out; report not created."
            )
        export_width, export_height = export_size or (int(w_mm * 3.78), int(h_mm * 3.78))
        png, timed_out = _fig_png(fig, export_width, export_height)
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
        caption_flowable = Paragraph(
            f'<a name="{figure_item.anchor}"/><b>{figure_item.label}.</b> '
            f"{_greek(_html_escape(figure_item.caption))}",
            self.s["publication_caption"],
        )
        figure_table = Table(
            [
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

    def _contents(self):
        """Add profile-appropriate linked contents without a page-count target."""

        contents = TableOfContents(
            levelStyles=[self.s["toc_h1"], self.s["toc_h2"]],
            dotsMinLevel=0,
            rightColumnWidth=12 * mm,
        )
        contents._sector_visible_contents = True
        self.flow.extend([
            Paragraph("Contents", self.s["h1"]),
            Paragraph(
                (
                    "Select a section or page number to open it. Audit also "
                    "lists calculation subsections."
                    if self.profile.key == "Audit"
                    else "Select a section or page number to open it."
                ),
                self.s["small"],
            ),
            contents,
        ])
        self._page_break()

    # -- build -------------------------------------------------------------
    def build(self):
        # Reuse the one process-wide kaleido server (started on the first report and
        # left running) rather than starting and stopping one per report. A
        # tables-only report renders no figures, so it never starts a browser.
        if self.figures:
            ensure_image_server()
        self._tick(0.05, "Cover and conventions...")
        self._cover()
        self._contents()
        if self.profile.key == "Brief":
            self._brief_governing_register()
            self._brief_fatigue_screen_results()
            self._brief_warning_summary()
            self._brief_key_figures()
            self._brief_input_summary()
            self._write_pdf()
            return
        self._results_dashboard()
        self._conventions()
        self._tick(0.2, "Section and materials...")
        self._inputs()
        if self.profile.key == "Audit":
            self._theory()
        if self._base_out.get("clear_spacing") is not None:
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
                    case_inp.get("_report_case_current") is False
                    and key != "torsion"
                ):
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
                        key,
                        case_out[key],
                        case_inp=case_inp,
                        case_out=case_out,
                    )
                    and not (
                        key == "combined"
                        and presentation.combined_bending_assessment_blocker(
                            case_out,
                            case_inp,
                        ) is not None
                    )
                ):
                    if key == "plastic" and self.figures:
                        jobs.append((case_inp, case_out,
                                     f"Plastic section maps - {case_id}...",
                                     "_plastic_field_chapter", True))
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
                if (
                    presentation.torsion_applicability_publication_status(
                        case_out.get("torsion") or {}
                    )
                    != "APPLICABLE"
                ):
                    continue
                if presentation.torsion_publication_component_is_current(
                    case_inp,
                    case_out.get("shear"),
                    case_out.get("torsion"),
                    component=selection.get("component"),
                )[0] is not True:
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
            if case_inp.get("_report_case_current") is False:
                continue
            case_id = presentation.action_set(case_inp, "elastic")["id"] or "-"
            if (
                "elastic" in case_out
                and (
                    self._selected_family("elastic", case_inp) is not None
                    or self._needs_diagnostic_chapter(
                        "elastic",
                        case_out["elastic"],
                        case_inp=case_inp,
                    )
                )
            ):
                jobs.append((
                    case_inp, case_out,
                    f"Elastic stresses - {case_id}...", "_elastic", True,
                ))
            elif "elastic" in case_out and self.figures:
                jobs.append((case_inp, case_out,
                             f"Elastic section maps - {case_id}...",
                             "_elastic_field_chapter", True))
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

        family_order = {
            "_minimum_reinforcement": 0, "_transverse_reinforcement": 1,
            "_plastic": 2, "_plastic_field_chapter": 2,
            "_shear": 3, "_torsion": 4,
            "_torsion_interaction_example": 4,
            "_torsion_minimum_reinforcement_example": 4,
            "_combined": 5, "_elastic": 6, "_elastic_field_chapter": 6,
            "_cracking": 7,
        }
        jobs.sort(key=lambda job: family_order[job[3]])
        try:
            for index, (case_inp, case_out, label, method, _new_page) in enumerate(jobs):
                self.inp, self.out = case_inp, case_out
                fraction = 0.42 + 0.5 * (index / max(len(jobs), 1))
                self._tick(fraction, label)
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
            self._heightened_crack_control()
        if self._base_out.get("fatigue") is not None:
            self._tick(0.88, "Grouped fatigue...")
            self._fatigue()
        if self.qa_appendix:
            self._appendix()

        self._write_pdf()

    def _write_pdf(self):
        """Write the already assembled presentation flow without recalculation."""
        if getattr(self, "_project_sources_linked", False):
            self._project_source_register()

        self._tick(0.92, "Writing PDF...")
        footer = f"Sector {self.version}  -  {SECTOR_LICENSEE}".strip()
        project = str(self.meta.get("proj_no", "")).strip() or "-"
        section = str(self.meta.get("section", "")).strip() or "-"
        revision = str(self.meta.get("rev", "")).strip()
        active_families = [
            family
            for family in ("plastic", "elastic")
            if self._current_case_inputs(family)
        ]
        cases = [
            presentation.action_set(case_inp, family)["id"]
            for family in active_families
            for case_inp in self._current_case_inputs(family)
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
                    f"{family.title()} {len(self._current_case_inputs(family))}"
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
                                 title=title, lang="en")
        # ReportLab suppresses canvas.save() on indexing passes and writes once
        # after every TableOfContents is satisfied. The shared BytesIO therefore
        # receives one final PDF container, not one container per pass.
        doc.multiBuild(
            self.flow,
            canvasmaker=lambda *a, **k: _NumberedCanvas(
                *a,
                footer=footer,
                header=header,
                revision=revision,
                **k,
            ),
        )
        self._tick(1.0, "Done")

    # -- sections ----------------------------------------------------------
    def _family_inputs_requested(self, family):
        inp = self._base_inp
        if self._result_values(family):
            return True
        key = family + "_cases"
        if key in inp:
            return bool(case_analysis.case_records(inp, family))
        if inp.get("mode") in {family.title(), "Both"}:
            return True
        return family == "plastic" and any(inp.get(key) for key in (
            "shear_on", "torsion_on", "combined_on", "minimum_reinforcement_on",
            "transverse_detailing_on"))

    def _shear_geometry_input_rows(self):
        inp = self._base_inp
        if not inp.get("shear_on"):
            return []
        rows = [
            ["Shear section form", _html_escape(str(inp.get("shear_section_form", shear_inputs.SHEAR_SECTION_AUTO)))],
            ["Web duct condition", _html_escape(str(inp.get("shear_duct_case", shear_inputs.SHEAR_DUCT_NONE)))],
            ["Circular hoop diameter", _fmt(inp.get("shear_hoop_diameter", 0.0), 3) + " mm"],
        ]
        for component in ("vx", "vy"):
            prefix = "shear_" + component + "_"
            label = "V<sub>" + component[1] + "</sub> "
            rows.append([label + "web inclination", _fmt(inp.get(prefix + "web_inclination_deg", inp.get("shear_web_inclination_deg", 0.0)), 3) + "&#176;"])
            rows.append([label + "fitted lever arm", _fmt(inp.get(prefix + "fitted_z", inp.get("shear_fitted_z", 0.0)), 3) + " mm"])
            for suffix, name in (("duct_sum", "sum of duct diameters"), ("duct_largest", "largest duct diameter")):
                rows.append([label + name, _fmt(inp.get(prefix + suffix, inp.get("shear_" + suffix, 0.0)), 3) + " mm"])
        return rows

    def _slab_density_input_tables(self):
        density = self._base_inp.get("slab_density")
        if not isinstance(density, Mapping):
            return
        self._h2("Slab-density reinforcement basis")
        self._small("Slab-density reinforcement defines an area per metre of strip width. The schedules distinguish reinforcement series and physical bar positions.")
        self._small("Layout verification: " + _html_escape(str(density.get("status") or "Not stated")))
        if density.get("status") != "VERIFIED":
            known_reason = EngineerMessage(
                "REPORT-SLAB-LAYOUT",
                "The slab-spacing layout no longer matches the current point tables. "
                "Reapply the slab layout, or define explicit bars, before relying on "
                "crack-width or clear-spacing results."
            )
            reason = engineer_messages.resolve_state(
                density.get("reason"),
                authored={known_reason.text: known_reason},
                fallback=EngineerMessage("REPORT-SLAB-UNVERIFIED", "Verify the slab-density layout before relying on its physical spacing or cover."),
                context="report slab-density layout reason",
            ).text
            self._small(_html_escape(reason))
            return
        for key in ("series", "analysis_metadata", "physical_elements"):
            records = density.get(key, ())
            if not isinstance(records, (list, tuple)) or any(not isinstance(row, Mapping) for row in records):
                self._small("The slab-density schedule is incomplete. Reapply the slab layout to restore its physical input records.")
                return
        series = density.get("series") or []
        if series:
            rows = [["Face", "Series", "Diameter (mm)", "Spacing (mm)", "Layers", "Bar equivalents per layer per m", "Area per layer (mm<super>2</super>/m)", "Total area (mm<super>2</super>/m)"]]
            rows.extend([_html_escape(str(r.get("face", "-"))), _html_escape(str(r.get("role", "-"))),
                         _fmt(r.get("diameter_mm"), 3), _fmt(r.get("spacing_mm"), 3), r.get("layers", "-"),
                         _fmt(r.get("equivalents_per_layer"), 6), _fmt(r.get("area_per_layer_mm2_per_m"), 3),
                         _fmt(r.get("total_area_mm2_per_m"), 3)] for r in series)
            self._table(rows, [24*mm, 28*mm, 26*mm, 26*mm, 20*mm, 35*mm, 40*mm, 40*mm], keep=False, repeat_cols=2,
                        caption="Slab-density series definitions")
        metadata = density.get("analysis_metadata") or []
        unique = []
        for row in metadata:
            values = tuple(row.get(k) for k in ("face", "role", "layer", "spacing_group", "cover_mm", "nominal_spacing_mm"))
            if values not in unique:
                unique.append(values)
        if unique:
            self._table([["Face", "Series", "Layer", "Spacing group", "Clear cover (mm)", "Nearest nominal spacing (mm)"]]
                        + [[_html_escape(str(a)), _html_escape(str(b)), c, group, _fmt(d,3), _fmt(e,3)] for a,b,c,group,d,e in unique],
                        [25*mm, 28*mm, 20*mm, 27*mm, 40*mm, 50*mm], keep=False, repeat_cols=2,
                        caption="Physical cover and spacing by layer")
        physical = density.get("physical_elements") or []
        if physical:
            self._small("The area at each nominal axis is its tributary reinforcement area. Axes at strip cuts can have partial area weights.")
            self._table([["Physical element", "Spacing group", "x (mm)", "y (mm)", "Diameter (mm)", "Tributary area (mm<super>2</super>)"]]
                        + [[_html_escape(str(r.get("id", "-"))), r.get("spacing_group", "-"), _fmt(r.get("x_mm"),3), _fmt(r.get("y_mm"),3),
                            _fmt(r.get("diameter_mm"),3), _fmt(r.get("area_mm2"),3)] for r in physical],
                        [62*mm, 27*mm, 25*mm, 25*mm, 27*mm, 38*mm], keep=False,
                        caption="Nominal physical bar positions for the slab strip")

    def _brief_input_summary(self):
        """Publish a compact summary of every active report input."""

        self._h1("Analysis input summary")
        self._small('This input summary records the geometry, assigned materials, actions and active analysis settings used for the reported results.')
        self._small('Standard adds complete result tables, criteria and method references. Audit includes the calculation steps and substitutions.')
        self._brief_geometry_summary()
        self._brief_material_summary()
        self._brief_actions_summary()
        self._method_register()
        self._brief_settings_summary()

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
        self._slab_density_input_tables()

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
            concrete_reference = _concrete_ultimate_reference(concrete_source)
            concrete_source_text = str(concrete_source or "User-defined")
            concrete_source_text += (
                "; source: " + concrete_reference
                if concrete_reference
                else "; project-defined; no Eurocode source inferred"
            )
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
                    f"{_fmt(concrete.eps_cu2 * 1000, 3)} &#8240;"
                ),
            ])
            if concrete.curve == 2:
                concrete_properties.append(f"n = {_fmt(concrete.n, 3)}")
            rows.append([
                "Concrete",
                "Concrete rings",
                _html_escape(concrete_source_text),
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
            source_reference = _steel_standard_reference(record.get("preset"))
            source_text += (
                "; source: " + source_reference
                if source_reference
                else "; project-defined; no Eurocode source inferred"
            )
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
                    f"eps<sub>ut</sub> = {_fmt(law.eut * 1000, 3)} &#8240;",
                    factors,
                ]
                if curve == 3:
                    law_parts.extend([
                        f"k = {_fmt(law.k, 3)}",
                        (
                            f"eps<sub>0t</sub> / eps<sub>0c</sub> = "
                            f"{_fmt(law.ey0t * 1000, 3)} / "
                            f"{_fmt(law.ey0c * 1000, 3)} &#8240;"
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
            source_reference = _prestress_standard_reference(
                record.get("preset")
            )
            source_text += (
                "; source: " + source_reference
                if source_reference
                else "; project-defined; no Eurocode source inferred"
            )
            properties = "Material definition unavailable"
            if law is not None:
                if law.curve in (1, 2, 3, 4, 5):
                    properties = (
                        f"built-in fixed curve {law.curve}; E<sub>p</sub> = "
                        f"{_fmt(law.Es / 1000, 1)} GPa; "
                        f"eps<sub>p,0</sub> / eps<sub>ut</sub> = "
                        f"{_fmt(law.IS * 1000, 3)} / "
                        f"{_fmt(law.rupture_strain * 1000, 3)} &#8240;; "
                        f"gamma<sub>y</sub> = {_fmt(law.gamma_y, 3)}"
                    )
                    if reinforcement_fatigue and record.get("fytk") is not None:
                        properties += (
                            "; fatigue proof-stress input "
                            "f<sub>p0.1k</sub> = "
                            f"{_fmt(record.get('fytk'), 3)} MPa "
                            "(fatigue yield/proof check input, not a "
                            "fixed-curve plastic-law field)"
                        )
                else:
                    law_parts = [
                        f"curve {law.curve}; f<sub>p0.1k</sub> / "
                        f"f<sub>pk</sub> = {_fmt(law.fytk, 3)} / "
                        f"{_fmt(law.futk, 3)} MPa; E<sub>p</sub> = "
                        f"{_fmt(law.Es / 1000, 1)} GPa; "
                        f"eps<sub>p,0</sub> = "
                        f"{_fmt(law.IS * 1000, 3)} &#8240;",
                        f"eps<sub>ut</sub> = {_fmt(law.eut * 1000, 3)} &#8240;",
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
                                f"{_fmt(law.ey0t * 1000, 3)} &#8240;"
                            ),
                        ])
                    properties = "; ".join(law_parts)
            rows.append([
                _html_escape(f"Prestress / {material_id}"),
                _html_escape("Tendons " + ", ".join(assignments)),
                _html_escape(source_text),
                properties,
            ])
        for family, assignment, source, properties in rows[1:]:
            self._table(
                [["Material", "Assignment", "Name, preset and source"],
                 [family, assignment, source]],
                [32 * mm, 52 * mm, 86 * mm],
                keep=False,
                caption="Assigned material definition",
            )
            self._table(
                [["Property", "Value"], *self._material_property_rows(properties)],
                [85 * mm, 85 * mm],
                keep=False,
                caption=f"Material properties: {family}",
            )

    @staticmethod
    def _material_property_rows(markup):
        """Expand authored material summaries without splitting HTML entities."""

        entities = []

        def protect(match):
            entities.append(match.group())
            return f"__entity_{len(entities) - 1}__"

        protected = re.sub(r"&(?:#[0-9]+|#x[0-9a-fA-F]+|[A-Za-z]+);", protect, markup)
        rows = []
        for item in protected.split("; "):
            for index, entity in enumerate(entities):
                item = item.replace(f"__entity_{index}__", entity)
            label, separator, value = item.partition(" = ")
            if not separator:
                rows.append(["Definition", item])
                continue
            labels = label.split(" / ")
            values = value.split(" / ")
            if len(labels) == len(values) and len(labels) > 1:
                unit_match = re.search(r" (MPa|GPa|&#8240;)$", values[-1])
                unit = unit_match.group() if unit_match else ""
                for index, (name, number) in enumerate(zip(labels, values)):
                    rows.append([name, number + (unit if index < len(values) - 1 else "")])
            else:
                rows.append([label, value])
        return rows

    def _brief_actions_summary(self):
        """Reuse the canonical action-table publication without derivations."""

        self._h2("Actions", reserve=85)
        self._loads_block()
        self._project_source_register()

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

        if self.profile.key != "Brief":
            self._table(rows, [85 * mm, 85 * mm], keep=False, caption=caption)
            return
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

    def _torsion_geometry_input_rows(self):
        """Retain entered wall and partition inputs independently of assessment."""
        inp = self.inp
        rows = [
            ["Torsion wall thickness t<sub>ef</sub>",
             self._brief_auto_dimension(inp.get("torsion_tef"))],
            ["Subdivide torsion tube", self._brief_switch(inp.get("torsion_subdivide"))],
        ]
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
                rows.append([
                    f"Torsion sub-tube {index}",
                    (
                        f"x / y / b / h = {_fmt(x, 1)} / "
                        f"{_fmt(y, 1)} / {_fmt(width, 1)} / "
                        f"{_fmt(height, 1)} mm"
                    ),
                ])
        return rows

    def _brief_settings_summary(self):
        """Publish active numerical, crack, resistance and fatigue settings."""

        inp = dict(self._base_inp)
        for family in ("shear", "torsion", "combined", "fatigue"):
            flag = family + "_on"
            if flag not in inp:
                retained = (
                    self._base_out.get("fatigue")
                    if family == "fatigue" else self._result_values(family)
                )
                if retained:
                    inp[flag] = True
        plastic_results = self._result_values("plastic")
        elastic_results = self._result_values("elastic")
        plastic_requested = self._family_inputs_requested("plastic")
        elastic_requested = self._family_inputs_requested("elastic")
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
        if plastic_requested:
            check_util = inp.get(
                "check_util", plastic_results[0].get("check_util", True) if plastic_results else True
            )
            rows.extend([
                ["Neutral-axis sweep start", f"{_fmt(inp.get('v_min'), 3)}&#176;"],
                ["Neutral-axis sweep end", f"{_fmt(inp.get('v_max'), 3)}&#176;"],
                ["Neutral-axis maximum increment", f"{_fmt(inp.get('v_inc'), 3)}&#176;"],
                ["Applied-moment utilization", self._brief_switch(check_util)],
                ["N-M interaction diagrams", self._brief_switch(inp.get("interaction"))],
            ])
        if elastic_requested or inp.get("fatigue_on"):
            concrete_preset = (
                inp.get("concrete_preset") or inp.get("conc_preset")
            )
            rows.extend([
                ["Elastic area model", "Concrete occupied by reinforcement is deducted"],
                ["Concrete elastic modulus E<sub>c</sub>", f"{_fmt(inp.get('conc_Ec'), 3)} GPa"],
                ["Creep coefficient phi", _fmt(inp.get("el_phi"), 3)],
                [
                    "Creep coefficient source",
                    _html_escape(_input_reference_source(
                        concrete_preset,
                        InputGuidanceKey.CREEP_COEFFICIENT,
                        project_defined=True,
                    )),
                ],
            ])
        if elastic_requested:
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

        crack_requested = any(record.get("calculate_crack_width") for record in case_analysis.case_records(inp, "elastic")) if "elastic_cases" in inp else bool(inp.get("sls_cw"))
        crack_requested = crack_requested or any(
            result.get("show_cw") for result in elastic_results
        )
        if crack_requested or inp.get("sls_heightened_on"):
            self._h2("Crack-control settings", reserve=75)
            crack_rows = [["Setting", "Value"]]
            long_term_limit = inp.get(
                "sls_long_term_permitted_crack_width_mm", 0.0
            )
            short_term_limit = inp.get(
                "sls_short_term_permitted_crack_width_mm", 0.0
            )
            crack_rows.extend([
                ["Ordinary crack-width design basis", _html_escape(str(basis))],
                [
                    "Long-term user limit w<sub>k,long</sub>",
                    (
                        "0.000 mm - no comparison"
                        if not long_term_limit
                        else f"{_fmt(long_term_limit, 3)} mm"
                    ),
                ],
                ["Long-term user-limit source",
                 _html_escape(str(inp.get("sls_long_term_permitted_crack_width_source") or "not supplied"))],
                [
                    "Short-term user limit w<sub>k,short</sub>",
                    (
                        "0.000 mm - no comparison"
                        if not short_term_limit
                        else f"{_fmt(short_term_limit, 3)} mm"
                    ),
                ],
                ["Short-term user-limit source",
                 _html_escape(str(inp.get("sls_short_term_permitted_crack_width_source") or "not supplied"))],
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
                        {
                            "Ribbed / high bond (k1 = 0.8)": "Ribbed / high bond (k<sub>1</sub> = 0.8)",
                            "Plain round (k1 = 1.6)": "Plain round (k<sub>1</sub> = 1.6)",
                        }.get(str(inp.get("sls_bond") or "not retained"),
                              _html_escape(str(inp.get("sls_bond") or "not retained"))),
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
                inp.get("sls_member", "Beam"),
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
                    "Bonded-tendon bond-strength ratio &#958;",
                    (
                        _fmt(tendon_xi, 3)
                        if math.isfinite(tendon_xi) and tendon_xi > 0.0
                        else "not set"
                    ),
                ])
            if inp.get("sls_heightened_on"):
                crack_rows.extend([
                    ["DK heightened crack control", "fine and coarse calculated together"],
                    [
                        "Formula 7.100 NA permitted width",
                        f"{_fmt(inp.get('sls_heightened_permitted_crack_width_mm'), 3)} mm",
                    ],
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
                ])
                if (
                    inp.get("combined_method")
                    == ec2_codes.EC2_2005_DKNA.label
                ):
                    resistance_rows.append([
                        "Separate M/V route selected as a design assumption",
                        self._brief_switch(inp.get("combined_mv_independent")),
                    ])
            if shear_active:
                resistance_rows.extend(self._shear_geometry_input_rows())
                resistance_rows.extend([
                    ["Shear method", _html_escape(str(effective_shear_method or "-"))],
                    ["V<sub>x</sub> web width", self._brief_auto_dimension(inp.get("shear_vx_bw"))],
                    ["V<sub>y</sub> web width", self._brief_auto_dimension(inp.get("shear_vy_bw"))],
                ])
                if shear_2023:
                    resistance_rows.append([
                        "Shear aggregate D<sub>lower</sub>",
                        self._brief_auto_dimension(
                            inp.get("shear_dlower")
                        ),
                    ])
                    resistance_rows.append([
                        "Shear partial factor gamma<sub>V</sub>",
                        _fmt_gamma_v(inp.get("shear_gamma_v")),
                    ])
            if inp.get("torsion_on"):
                resistance_rows.extend([
                    ["Torsion method", _html_escape(str(inp.get("torsion_method") or "-"))],
                    *_torsion_case_authority_rows(inp),
                    ["Concrete tensile factor gamma<sub>ct</sub>", _fmt(inp.get("torsion_gamma_ct"), 3)],
                    [
                        "Requested nu<sub>t</sub> = nu<sub>v</sub> detailing allowance",
                        self._brief_switch(inp.get("torsion_nu_v") is True),
                    ],
                    *self._torsion_geometry_input_rows(),
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
            detailing_edition = inp.get("detailing_edition")
            if minimum_active:
                resistance_rows.append([
                    "Minimum reinforcement source",
                    _html_escape(_input_reference_source(
                        detailing_edition,
                        InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
                    )),
                ])
            if transverse_active:
                resistance_rows.append([
                    "Link-detailing source",
                    _html_escape(_input_reference_source(
                        detailing_edition,
                        InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
                    )),
                ])
            if clear_active:
                resistance_rows.append([
                    "Clear-spacing source",
                    _html_escape(_input_reference_source(
                        detailing_edition,
                        InputGuidanceKey.DETAILING_CLEAR_SPACING,
                    )),
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
        if inp.get("fatigue_on"):
            self._h2("Grouped fatigue settings", reserve=75)
            fatigue = fatigue or {}
            checks = fatigue.get("checks") or {}
            factors = fatigue.get("partial_factors") or {}
            concrete = fatigue.get("concrete_parameters") or {}
            basis = fatigue.get("basis") or inp.get(fatigue_inputs.BASIS_KEY) or {}
            fatigue_rows = [["Setting", "Value"]]
            edition = fatigue.get("edition") or inp.get("fatigue_edition") or "-"
            try:
                edition = get_design_basis(edition).label
            except (TypeError, ValueError):
                pass
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
                ["Method reference", _html_escape(str(fatigue.get("method_reference") or "not calculated"))],
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
            unique_details = []
            for detail in detail_basis:
                if detail not in unique_details:
                    unique_details.append(detail)
            self._brief_settings_table(
                fatigue_rows, caption="Grouped fatigue calculation settings",
            )
            self._fatigue_detail_input_tables(
                unique_details, mixed_reinforcement=mixed_reinforcement,
            )

    def _fatigue_detail_input_tables(self, details, *, mixed_reinforcement):
        """Publish each assigned fatigue definition as readable property rows."""
        unique = []
        for detail in details:
            if detail not in unique:
                unique.append(detail)
        if not unique:
            return
        self._h2("Assigned fatigue details", reserve=100)
        for detail in unique:
            detail_id = _html_escape(str(detail.get("id") or "-"))
            rows = [
                ["Property", "Value"],
                ["Detail ID", detail_id],
                ["Name", _html_escape(str(detail.get("name") or detail.get("preset") or "-"))],
                ["Preset", _html_escape(str(detail.get("preset") or "-"))],
                ["Source", _html_escape(str(detail.get("source") or "not stated"))],
                ["Material kind", _fatigue_report_label(str(detail.get("kind") or "-"), "kind")],
                ["Stress model", _fatigue_report_label(str(detail.get("stress_model") or "-"), "stress_model")],
                ["Reference stress range &#916;&#963;<sub>Rsk</sub>",
                 f"{_fmt(detail.get('delta_sigma_rsk_mpa'), 3)} MPa"],
                ["Reference cycle count N<super>*</super>", _fmt(detail.get("n_star"), 3)],
                ["Upper-branch exponent k<sub>1</sub>", _fmt(detail.get("k1"), 3)],
                ["Lower-branch exponent k<sub>2</sub>", _fmt(detail.get("k2"), 3)],
                ["Bend reduction", self._brief_switch(detail.get("bend_reduction"))],
            ]
            if detail.get("bend_reduction"):
                rows.append(["Mandrel diameter", f"{_fmt(detail.get('mandrel_diameter_mm'), 3)} mm"])
            if str(detail.get("kind") or "").strip().lower() == fatigue_inputs.PRESTRESS and mixed_reinforcement:
                rows.extend([
                    ["Bond-strength ratio &#958;", _fmt(detail.get("bond_ratio_xi"), 3)],
                    ["Bond-equivalent diameter", f"{_fmt(detail.get('bond_equivalent_diameter_mm'), 3)} mm"],
                ])
            self._table(rows, [70 * mm, 100 * mm], keep=False,
                        caption="Fatigue detail " + detail_id + ": input properties")

    def _brief_fatigue_screen_results(self):
        """Publish fatigue outcomes as rows, with explicit local source notes."""
        fatigue = self._base_out.get("fatigue") or {}
        checks = fatigue.get("checks") or {}
        if not checks.get("reinforcement", self._base_inp.get("fatigue_check_steel")):
            return
        for spectrum in fatigue_presentation.items(fatigue, "spectra"):
            records = fatigue_presentation.reinforcement_rows(spectrum)
            if not records:
                continue
            name = str(fatigue_presentation.value(spectrum, "spectrum_name", "-"))
            self._h2("Fatigue stress-range results: " + _html_escape(name), reserve=120)
            rows = [["Element", "Screen status", "Range (MPa)", "Limit (MPa)", "Utilization", "Governing bin"]]
            for row in records:
                rows.append([
                    _html_escape(row["element_id"]), _html_escape(row["screen_status"]),
                    _fmt(row["screen_range_mpa"], 3), _fmt(row["screen_threshold_mpa"], 3),
                    _pct(row["screen_utilisation"]), _html_escape(row["screen_governing_bin"]),
                ])
            self._table(rows, [25 * mm, 29 * mm, 25 * mm, 25 * mm, 29 * mm, 37 * mm],
                        keep=False, caption="Fatigue stress-range screen outcomes")
            detail_rows = [["Element", "Detail class", "Range basis", "Miner damage D", "Yield / proof utilization", "Note"]]
            sources = []
            for index, row in enumerate(records, 1):
                source = str(row["screen_source"] or "Source not retained")
                if source not in sources:
                    sources.append(source)
                detail_rows.append([
                    _html_escape(row["element_id"]), _html_escape(row["screen_detail_class"]),
                    _fatigue_report_label(row["screen_range_basis"], "range_basis"), _fmt_sig(row["damage"], 6),
                    _pct(row["yield_utilisation"]), str(index),
                ])
            self._table(detail_rows, [24 * mm, 30 * mm, 34 * mm, 29 * mm, 35 * mm, 18 * mm],
                        keep=False, caption="Fatigue detail, damage and independent yield or proof check")
            for index, row in enumerate(records, 1):
                reason = _result_reason(row["screen_reason"], "fatigue", "brief report fatigue-screen reason") if row["screen_reason"] else "No additional assessment note."
                source_index = sources.index(str(row["screen_source"] or "Source not retained")) + 1
                self._small(f"<b>Note {index}: {_html_escape(row['element_id'])}.</b> "
                            + _html_escape(reason) + f" Source {source_index}.")
            for index, source in enumerate(sources, 1):
                self._small(f"<b>Source {index}:</b> " + _html_escape(source))

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
                    fallback = (
                        _REPORT_RESULT_WARNING
                        if key == "warnings"
                        else _REPORT_RESULT_ERROR
                    )
                    warnings.append((label, engineer_messages.error_detail(
                        message,
                        fallback=fallback,
                        context=f"Brief report {label.casefold()} {key}",
                    )))
        if not warnings:
            return
        self._h2("Calculation warnings", reserve=90)
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
        """Lead with the canonical governing values, criteria, statuses and limits."""

        self._h1("Governing results and limitations", reserve=110)
        self._results_overview()
        self._page_break()

    def _selected_brief_result_context(self, result_key, family):
        """Return one exact retained selected context without report-side ranking."""

        selected = self._selected_families.get(result_key)
        if not isinstance(selected, Mapping):
            return None
        matches = [
            (case_inp, case_out[result_key])
            for case_inp, case_out in self._case_contexts(family)
            if self._case_id(case_inp, family) == selected.get("case_id")
            and isinstance(case_out.get(result_key), Mapping)
        ]
        return matches[0] if len(matches) == 1 else None

    def _brief_key_figures(self):
        """Publish only retained governing Plastic and Elastic result figures."""

        if not self.figures:
            return

        def has_items(value):
            try:
                return value is not None and len(value) > 0
            except TypeError:
                return False

        figures = []
        plastic = self._selected_brief_result_context("plastic", "plastic")
        if plastic is not None:
            case_inp, result = plastic
            mx = result.get("mx")
            my = result.get("my")
            points = result.get("points")
            has_envelope = (
                has_items(mx)
                and has_items(my)
                and len(mx) == len(my)
            )
            if has_envelope:
                assessment = presentation.plastic_action_assessment(result)
                case_id = presentation.action_set(case_inp, "plastic")["id"] or "-"
                angles = (
                    [point["V"] for point in points]
                    if has_items(points)
                    and len(points) == len(mx)
                    and all(
                        isinstance(point, Mapping) and "V" in point
                        for point in points
                    )
                    else None
                )
                figures.append((
                    viz.interaction_figure(
                        mx,
                        my,
                        applied=result.get("applied"),
                        title=f"Governing Plastic result - {case_id}",
                        angles=angles,
                        util=assessment.get("util"),
                        closed=result.get("closed", True),
                    ),
                    f"Governing Plastic result - {case_id}",
                    130,
                    100,
                ))

        elastic = self._selected_brief_result_context("elastic", "elastic")
        if elastic is not None:
            case_inp, result = elastic
            corners = result.get("concrete_corners")
            elements = result.get("elements")
            stress_plane = result.get("stress_plane")
            try:
                ec_mpa = float(case_inp.get("conc_Ec") or 0.0) * 1000.0
            except (TypeError, ValueError):
                ec_mpa = 0.0
            if has_items(corners) and has_items(stress_plane) and ec_mpa > 0.0:
                case_id = presentation.action_set(case_inp, "elastic")["id"] or "-"
                figures.append((
                    viz.elastic_strain_figure(
                        corners,
                        elements,
                        stress_plane,
                        ec_mpa=ec_mpa,
                        title=f"Governing Elastic result - {case_id}",
                    ),
                    f"Governing Elastic result - {case_id}",
                    130,
                    90,
                ))

        if not figures:
            return
        self._h1("Key governing figures", reserve=150)
        for figure, caption, width, height in figures:
            self._fig(
                figure,
                width,
                height,
                caption=caption,
            )

    def _non_governing_status_register(self):
        """Publish every retained row excluded from the governing overview."""

        retained_rows = presentation.multi_case_summary_rows(
            self._base_inp, self._base_out
        )
        non_governing = presentation.non_governing_summary_rows(retained_rows)
        non_governing.extend(
            presentation.non_governing_fatigue_spectrum_rows(
                self._base_inp, self._base_out
            )
        )
        if non_governing:
            self._h2("Other case results and calculation states", reserve=90)
            availability = []
            data = [["Check", "Action set", "Status", "Result"]]
            for row in non_governing:
                result = _html_escape(report_notation.row_field(row, "result"))
                if row["status"] not in {"PASS", "FAIL", "CALCULATED"}:
                    number = len(availability) + 1
                    availability.append((number, row))
                    result += (
                        f'<br/><link href="#availability-note-{number}">'
                        f'Assessment note {number}</link>'
                    )
                data.append([
                    _html_escape(row["check"]), _html_escape(row["case"]),
                    _html_escape(row["status"]), result,
                ])
            self._table(
                data, [49 * mm, 30 * mm, 41 * mm, 45 * mm],
                font=7.2, keep=False,
                caption="Compact non-governing requested results",
            )
            notes_start = len(self.flow)
            for number, row in availability:
                self._p(
                    f'<a name="availability-note-{number}"/><b>Assessment note '
                    f'{number}. {_html_escape(row["check"])}: '
                    f'{_html_escape(row["case"])}.</b>'
                )
                self.flow[-1].keepWithNext = 1
                note = report_notation.row_field(row, "note")
                if note:
                    self._p(_html_escape(note))
                else:
                    self._p("Review this case's calculation state and requested inputs.")
                source = str(row.get("source") or "").strip()
                if source and source != "-":
                    self.flow[-1].keepWithNext = 1
                    self._p("Source: " + _html_escape(source))
            if availability:
                self._keep_from(notes_start)

    def _cover(self):
        m = self.meta
        self.flow.append(publication_branding.logo_flowable(45 * mm))
        self.flow.append(Spacer(1, 4 * mm))
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
                *[[label, _html_escape(m[key])]
                  for key, label in (("checker", "Checker"), ("approver", "Approver"))
                  if str(m.get(key) or "").strip()],
                ["Date", _html_escape(date)],
                ["Tool version", self.version or "-"],
                [
                    "Calculation state",
                    _html_escape(m.get("calculation_state", "Not supplied")),
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
        if self._current_case_inputs("plastic"):
            rows.append([
                "Plastic analysis cases",
                self._case_register("plastic"),
            ])
        if self._current_case_inputs("elastic"):
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
            ("minimum_reinforcement", "modeled-direction minimum reinforcement"),
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
        self.flow.append(NotAtTopPageBreak())

    def _results_dashboard(self):
        """Publish the report-wide result dashboard before detailed sections."""

        self._h1("Results summary", reserve=130)
        self._results_overview()
        if self.profile.non_governing_scope == "complete":
            self._non_governing_status_register()
        self._page_break()

    def _conventions(self):
        self._h1("Conventions and units")
        self._p('Coordinates are entered in the section plane. The origin is the entered origin. The x-axis is horizontal, and the y-axis is vertical.')
        self._p('<b>M<sub>x</sub></b> acts about the x-axis, so stress varies with y. The interaction diagram shows M<sub>x</sub> on its vertical axis.')
        self._p('<b>M<sub>y</sub></b> acts about the y-axis.')
        self._p('Axial force <b>N</b>, stress and strain are positive in tension and negative in compression. Thus, the concrete strain at crushing is negative.')
        self._p('Plastic and cracked elastic calculations use compression-only concrete. The uncracked Stage I calculation includes concrete in tension. Plane sections remain plane (Bernoulli assumption).')
        rows = [["Quantity", "Unit"],
                ["Coordinates, neutral-axis intercepts, lever arm", "mm"],
                ["Axial force N", "kN"],
                ["Moments M<sub>x</sub>, M<sub>y</sub>", "kNm"],
                ["Stresses", "MPa"],
                ["Strains", "&#8240; / percent as noted"],
                ["Curvature kappa", "1/m"],
                ["Areas / second moments", "m<super>2</super> / m<super>4</super>"]]
        self._table(rows, [120 * mm, 45 * mm])
        self._method_register()

    def _method_register(self):
        """Identify each selected family without implying a common code basis."""
        inp = self._base_inp
        rows = [["Check family", "Selected basis or method", "Application"]]
        for label, key, family, purpose in (
            ("Elastic and ordinary crack width", "sls_code", "elastic",
             "Serviceability material assumptions and ordinary crack-width method"),
            ("Minimum reinforcement", "detailing_edition", "minimum_reinforcement",
             "Modeled-direction minimum area and detailing checks"),
            ("Shear", "shear_method", "shear",
             "Concrete, link and longitudinal chord resistance"),
            ("Torsion", "torsion_method", "torsion",
             "The retained applicability assessment governs use of the tube model"),
            ("Combined actions", "combined_method", "combined",
             "Concurrent bending, one shear direction and torsion"),
            ("Fatigue", "fatigue_edition", "fatigue",
             "Selected reinforcement and concrete fatigue methods"),
        ):
            requested = (self._family_inputs_requested(family) if family == "elastic"
                         else bool(inp.get(family + "_on")))
            if not requested and not self._result_values(family) and not self._base_out.get(family):
                continue
            value = inp.get(key)
            try:
                basis = get_design_basis(value).label if value else "Not declared"
            except (TypeError, ValueError):
                basis = str(value)
            rows.append([label, _html_escape(basis), purpose])
        presets = _used_material_presets(inp)
        if presets:
            rows.append(["Material laws", _html_escape("; ".join(presets)),
                         "Assigned presets; entered properties are in the material schedules"])
        if len(rows) == 1:
            return
        self._h2("Selected methods by check family", reserve=95)
        self._small("Each result chapter gives its applicable clauses, input conditions and assessment limits. Check project adoption of the selected editions before issue.")
        self._table(rows, [38 * mm, 70 * mm, 62 * mm], keep=False,
                    caption="Selected methods and their application")

    def _inputs(self):
        self._h1("Section and materials", reserve=240)
        inp = self.inp
        # Geometry drawing.
        self._h2("Geometry")
        if self.figures:
            inset = "Concurrent-action inset unavailable.<br>Read the complete action schedules."
            action_caption = "Read the complete action schedules for the requested cases."
            for family in ("plastic", "elastic"):
                selected = self._selected_brief_result_context(family, family)
                if selected is None or selected[0].get("_report_case_current") is False:
                    continue
                case_inp, result = selected
                try:
                    inset = report_diagrams.action_inset_text(
                        case_inp, family.title(), presentation.action_set(case_inp, family)["id"] or "-",
                        capacity_only=family == "plastic" and result.get("check_util") is False,
                    )
                except report_diagrams.DiagramUnavailable:
                    continue
                action_caption = ("Concurrent " + family.title() + " actions: "
                                  + str(presentation.action_set(case_inp, family)["id"] or "-") + ".")
                break
            fig = report_diagrams.section_axes_figure(inp, action_inset=inset)
            self._fig(fig, 170, 140,
                      caption="Input coordinates and element IDs. " + action_caption
                      + " Dimensions are in millimeters. Marker sizes identify elements; the schedule gives their areas.")
        self._geometry_tables()
        self._slab_density_input_tables()
        self._concrete_section_properties_block()
        # Materials are reported only when the section actually uses them: mild
        # steel when there are bars, prestress when there are tendons.
        self._h2("Concrete", reserve=320)
        self._concrete_block()
        if inp.get("bars") or inp.get("shear_on") or inp.get("torsion_on"):
            self._h2("Reinforcement")
            self._steel_block()
        if inp.get("tendons") and inp.get("prestress") is not None:
            start = len(self.flow)
            self._h2("Prestressing steel")
            self._prestress_block()
            self._keep_from(start)
            self._prestress_initial_block()
        # Start the load schedules together; let settings follow the source
        # register with the normal heading keep rather than an empty page tail.
        self._page_break()
        self._h2("Loads")
        self._loads_block()
        self._project_source_register()
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
        self._small(
            "A is in m<super>2</super>. S<sub>x</sub> and S<sub>y</sub> are in "
            "m<super>3</super>. S<sub>xx</sub>, S<sub>yy</sub> and S<sub>xy</sub> "
            "are in m<super>4</super>."
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
            ref="Centroid definition using the signed polygon moments.",
            subst=(f"= {_fmt(net['first_x_m3'], 6)} / "
                   f"{_fmt(net['area_m2'], 6)}"),
            result=f"= {_fmt(net['centroid_x_m'], 6)} m",
            references=("geometry.concrete.net-area",),
        )
        self._formula(
            "y<sub>c</sub> = S<sub>y</sub> / A<sub>c</sub>",
            equation_key="geometry.concrete.centroid-y",
            ref="Centroid definition using the signed polygon moments.",
            subst=(f"= {_fmt(net['first_y_m3'], 6)} / "
                   f"{_fmt(net['area_m2'], 6)}"),
            result=f"= {_fmt(net['centroid_y_m'], 6)} m",
            references=("geometry.concrete.net-area",),
        )
        self._formula(
            "I<sub>x,c</sub> = S<sub>yy</sub> - A<sub>c</sub> "
            "y<sub>c</sub><super>2</super>",
            equation_key="geometry.concrete.centroidal-ix",
            ref="Parallel-axis transfer of the calculated origin moment.",
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
            ref="Parallel-axis transfer of the calculated origin moment.",
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
            ref="Parallel-axis transfer of the calculated origin product moment.",
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
                 ["Peak strain", "eps<sub>c2</sub>", f"{_fmt(c.eps_c2*1000, 3)} &#8240;"],
                 ["Ultimate strain", "eps<sub>cu2</sub>", f"{_fmt(c.eps_cu2*1000, 3)} &#8240;"],
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
        definition_start = self._preceding_headings(len(self.flow))
        self._table(rows, [60 * mm, 35 * mm, 50 * mm])
        applicability_note = None
        if is_2023 and fcd is not None:
            self._formula(
                "f<sub>cd</sub> = eta<sub>cc</sub> &#183; k<sub>tc</sub> &#183; "
                "f<sub>ck</sub> / gamma<sub>c</sub>",
                equation_key="materials.concrete.fcd",
                equation_variant="2023",
                ref=(
                    "DS/EN 1992-1-1:2023, 5.1.6(1), Formulae "
                    "(5.3)-(5.4)"
                ),
                subst=f"= {_fmt(self.inp.get('concrete_eta_cc'),6)} &#183; "
                      f"{_fmt(self.inp.get('concrete_k_tc'),2)} &#183; "
                      f"{_fmt(c.fck, 3)} / {_fmt(c.gamma_c, 3)}",
                result=f"= {_fmt(fcd, 3)} MPa")
            if math.isclose(float(self.inp.get("concrete_k_tc") or 0.0), 1.0):
                applicability_note = (
                    "<b>Applicability assumption:</b> k<sub>tc</sub> = 1.00 was selected under the following conditions (5.1.6(1)).",
                    "For CR/CN, t<sub>ref</sub> &#8804; 28 days. For CS, t<sub>ref</sub> &#8804; 56 days.",
                    "Design loading is expected at least 3 months after casting. The governing National Annex can specify different conditions.",
                )
            else:
                applicability_note = (
                    "k<sub>tc</sub> = 0.85 is the general / other-case value stated "
                    "in DS/EN 1992-1-1:2023, 5.1.6(1)."
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
            for paragraph in (applicability_note if isinstance(applicability_note, tuple) else (applicability_note,)):
                self._small(paragraph)
        if c.curve == 2:
            curve_source = (
                _concrete_ultimate_reference(preset)
                or "Project-defined concrete law; no Eurocode source inferred."
            )
            self._small("The material-law equation uses compression-positive stress and strain magnitudes. "
                        "The material graph uses tension-positive signed values.")
            self._formula(
                "sigma<sub>c</sub> = f<sub>cd</sub> &#183; [1 - (1 - eps<sub>c</sub>/"
                "eps<sub>c2</sub>)<super>n</super>],  for eps<sub>c</sub> &lt;= eps<sub>c2</sub>; "
                "then f<sub>cd</sub> up to eps<sub>cu2</sub>",
                equation_key="materials.concrete.curve-2",
                ref=curve_source,
            )
            if self.profile.key == "Standard":
                self._small("Concrete law source: " + _html_escape(curve_source))
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
        self._small("The printed partial factors are the final project inputs and "
                    "are used directly in the calculation.")
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
                    ["Selected preset", "-", _html_escape(
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
                     f"{_fmt(st.eut*1000, 3)} &#8240;"],
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
            self._keep_measured_calculation_from(block_start)

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
                     f"{_fmt(p.IS*1000, 3)} &#8240;"],
                    [
                        "Design-law source",
                        "-",
                        _prestress_standard_reference(item.get("preset"))
                        or (
                            "Project-defined or built-in law; no Eurocode "
                            "source inferred"
                        ),
                    ]]
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
                     f"{_fmt(p.rupture_strain*1000, 3)} &#8240;"],
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
                     f"{_fmt(p.rupture_strain*1000, 3)} &#8240;"],
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
        block_start = len(self.flow)
        self._h2("Initial prestress action")
        state_rows = [[
            "Tendon", "Material", "E<sub>p</sub> (MPa)", "eps<sub>p,0</sub> (-)",
            "sigma<sub>p,0</sub> (MPa)", "A<sub>p</sub> (mm<super>2</super>)", "F<sub>p,0</sub> (kN)",
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
        if self.profile.key == "Standard":
            # Keep the retained tendon schedules with their resultant summary
            # when this complete calculation fits within one page.
            self._keep_from(block_start)

    def _project_source_link(self, scope, case_name):
        self._project_sources_linked = True
        for index, entry in enumerate(self._source_register, start=1):
            if (entry["scope"], entry["case_name"]) == (scope, case_name):
                return (' | User reference: <link href="#sector-project-sources">'
                        f'R{index}</link>')
        return ""

    def _project_source_register(self):
        if getattr(self, "_project_sources_emitted", False):
            return
        self._project_sources_emitted = True
        self._h2("User-supplied project and action references", reserve=70)
        self._p('<a name="sector-project-sources"/>Project references concern project assumptions. Action references apply only to their named case or spectrum.')
        self._p('The user supplies these references. They are separate from the calculation-method sources.')
        current = report_sources.available_assignments(self._base_inp)
        if not self._source_register:
            self._p("References incomplete: no user-supplied document or record "
                    "and section/page locator has been provided.")
            return
        rows = [["Ref. / scope", "Document / section or page", "Reference status"]]
        assigned = set()
        for index, entry in enumerate(self._source_register, start=1):
            identity = entry["scope"], entry["case_name"]
            assigned.add(identity)
            scope = entry["scope"] + (" / " + entry["case_name"]
                                      if entry["case_name"] else " assumptions")
            status = report_sources.reference_status(entry)
            if identity not in current:
                status += "; unmatched current case or spectrum"
            rows.append([
                f"R{index}: " + _html_escape(scope),
                _html_escape(entry["document"] or "Document not supplied")
                + "<br/>" + _html_escape(entry["locator"] or "Section/page not supplied"),
                _html_escape(status),
            ])
        self._table(rows, [47 * mm, 77 * mm, 46 * mm], font=9, keep=False,
                    caption="User-supplied references and their exact scopes")
        missing = [scope + (" / " + name if name else " assumptions")
                   for scope, name in current if (scope, name) not in assigned]
        if missing:
            self._p("References incomplete for: " + _html_escape("; ".join(missing)) + ".")

    def _fatigue_loads_block(self):
        inp = self._base_inp
        fatigue_rows = (
            fatigue_inputs.spectrum_records(
                inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
            )
            if inp.get("fatigue_on") else []
        )
        if fatigue_rows:
            self._small("<b>Grouped fatigue spectra</b>", keep_with_next=True)
            rows = [["Spectrum", "Bin", "Description", "Cycles"]]
            rows.extend([
                [_html_escape(row[fatigue_inputs.SPECTRUM]),
                 _html_escape(row[fatigue_inputs.NAME]),
                 _html_escape(row[fatigue_inputs.DESCRIPTION]),
                 _fmt(row[fatigue_inputs.CYCLES], 3)]
                for row in fatigue_rows
            ])
            self._table(rows, [35 * mm, 35 * mm, 65 * mm, 35 * mm],
                        keep=False, repeat_cols=2,
                        caption="Fatigue spectrum records and cycle counts")
            action_rows = [["Spectrum", "Bin", "Part", "N<sub>Ed</sub>",
                            "M<sub>x,Ed</sub>", "M<sub>y,Ed</sub>"]]
            for row in fatigue_rows:
                for part, label in (("long", "Long"), ("short", "Short")):
                    action_rows.append([
                        _html_escape(row[fatigue_inputs.SPECTRUM]),
                        _html_escape(row[fatigue_inputs.NAME]), label,
                        _fmt(row[f"n_{part}_ed_kn"], 3),
                        _fmt(row[f"mx_{part}_ed_knm"], 3),
                        _fmt(row[f"my_{part}_ed_knm"], 3),
                    ])
            self._table(action_rows,
                        [35 * mm, 35 * mm, 19 * mm, 27 * mm, 27 * mm, 27 * mm],
                        keep=False, repeat_cols=3,
                        caption="Fatigue action components")
            self._small('N is in kN, and M is in kN&#183;m. N is positive in tension.')
            self._small('Long is the sustained state. Short is the cyclic increment.')
        return fatigue_rows

    def _loads_block(self):
        inp = self._base_inp
        out = self._base_out
        if "plastic_cases" in inp or "elastic_cases" in inp:
            plastic = (
                case_analysis.case_records(inp, "plastic")
                if inp.get("plastic_cases") is not None else []
            )
            if plastic:
                self._small("<b>Plastic / capacity cases</b>", keep_with_next=True)
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
                self._small('N, V<sub>x</sub> and V<sub>y</sub> are in kN. M and T are in kN&#183;m.')
                self._small('A zero shear component or zero torsion is not evaluated for that case.')

            elastic = (
                case_analysis.case_records(inp, "elastic")
                if inp.get("elastic_cases") is not None else []
            )
            if elastic:
                self._small("<b>Elastic cases</b>", keep_with_next=True)
                rows = [[
                    "Case", "Description", "Part", "N<sub>Ed</sub>",
                    "M<sub>x,Ed</sub>", "M<sub>y,Ed</sub>",
                    "Stress", "Crack width",
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
                self._small('N is in kN, and M is in kN&#183;m. Stress results are always reported. Crack-width calculation is optional for each case.')
                self._small('The user can enter separate permitted crack widths for the long-term and short-term states. No stress limit is applied.')
            fatigue_rows = self._fatigue_loads_block()
            if not plastic and not elastic and not fatigue_rows:
                self._small("No active load cases.")
            return

        rows = [["Load case", "N (kN)", "M<sub>x</sub> (kNm)", "M<sub>y</sub> (kNm)"]]
        if "plastic" in out or inp.get("mode") in {"Plastic", "Both"}:
            # Capacity-only Plastic defines the axial-force envelope. Active
            # member checks also receive the separate input-moment row below.
            cap_only = not out.get("plastic", {}).get("check_util", inp.get("check_util", True))
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
        if any(inp.get(key) for key in ("shear_on", "torsion_on", "combined_on")) and (
            "plastic" not in out or not out["plastic"].get("check_util", True)
        ):
            case = _html_escape(
                presentation.action_set(inp, "plastic")["id"] or "-"
            )
            rows.append([
                _LiteralReportText(f"{case} - member inputs"),
                _fmt(inp.get("P_pl"), 3), _fmt(inp.get("Mx_pl"), 3),
                _fmt(inp.get("My_pl"), 3),
            ])
        if "elastic" in out or inp.get("mode") in {"Elastic", "Both"}:
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

        # Direct callers have no declared case table to disclose the transverse
        # actions. Read the same current input fields as the member producer.
        transverse = [["Action set", "Action", "Value"]]
        case = _LiteralReportText(_html_escape(
            presentation.action_set(inp, "plastic")["id"] or "-"
        ))
        if inp.get("shear_on"):
            if any(key in inp for key in (
                "shear_Vx", "shear_Vy", "shear_components",
            )):
                components = inp.get("shear_components") or {}
                actions = [
                    (axis, (components.get("v" + axis) or {}).get(
                        "signed_v_ed", inp.get("shear_V" + axis, 0.0)
                    ))
                    for axis in ("x", "y")
                ]
            else:
                component = {"x": "y", "y": "x"}.get(inp.get("shear_axis"), "?")
                actions = [(component, inp.get("shear_V"))]
            transverse.extend([
                [case, f"Shear V<sub>{axis},Ed</sub>", f"{_fmt(value, 3)} kN"]
                for axis, value in actions
            ])
        if inp.get("torsion_on"):
            torque = presentation._publication_metric(inp.get("torsion_T"))
            sense = presentation._publication_metric(
                inp.get("torsion_T_signed", inp.get("torsion_T")),
            )
            torque = (
                math.copysign(abs(torque), sense)
                if torque is not None and sense is not None else None
            )
            transverse.append([
                case, "Torsion T<sub>Ed</sub>",
                f"{_fmt(torque, 3)} kNm",
            ])
        if len(transverse) > 1:
            self._table(transverse, [55 * mm, 73 * mm, 38 * mm])
        self._fatigue_loads_block()

    def _settings_block(self):
        """Publish requested inputs, then separately publish retained derivations."""
        self._brief_settings_summary()
        elastic_results = self._result_values("elastic")
        elastic_shared = self._base_out.get("elastic_shared") or {}
        if elastic_results and elastic_shared:
            start = len(self.flow)
            self._elastic_shared_calculation_block(elastic_shared)
            self._keep_from(start)
        fatigue = self._base_out.get("fatigue") or {}
        concrete = fatigue.get("concrete_parameters") or {}
        if fatigue and self._base_inp.get("fatigue_on", True):
            rows = [["Retained quantity", "Value"]]
            if (fatigue.get("checks") or {}).get("concrete"):
                rows.extend([
                    ["Concrete fatigue f<sub>ck</sub>", f"{_fmt(concrete.get('fck_mpa'), 2)} MPa"],
                    ["Concrete fatigue alpha<sub>cc</sub>", _fmt(concrete.get("alpha_cc"), 3)],
                ])
            rows.append([
                "Fatigue n<sub>l</sub> / n<sub>s</sub>",
                f"{_fmt(self.inp.get('nl'), 3)} / {_fmt(self.inp.get('ns'), 3)}",
            ])
            self._h2("Retained fatigue material parameters")
            self._table(rows, [85 * mm, 85 * mm], keep=False)

    def _elastic_shared_calculation_block(self, payload):
        """Publish effective modulus and per-material modular ratios."""

        materials = payload.get("materials") or []
        ec = payload["concrete_modulus_mpa"]
        phi = payload["creep_coefficient"]
        self._h2("Elastic material transformation")
        creep_source = _input_reference_source(
            self.inp.get("concrete_preset") or self.inp.get("conc_preset"),
            InputGuidanceKey.CREEP_COEFFICIENT,
            project_defined=True,
        )
        self._small(
            "<b>Creep coefficient source:</b> "
            + _html_escape(creep_source)
        )
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

    def _needs_diagnostic_chapter(
        self,
        family,
        result,
        *,
        case_inp=None,
        case_out=None,
    ):
        """Keep an unrankable/invalid result's reason without a worked chain."""

        if not isinstance(result, Mapping):
            return False
        if (
            isinstance(case_inp, Mapping)
            and case_inp.get("_report_case_current") is False
        ):
            return True
        if family in {"plastic", "elastic"}:
            return result.get("converged") is False
        if family == "torsion":
            shear = (
                case_out.get("shear")
                if isinstance(case_out, Mapping)
                else self._shear_publication_authority()
            )
            if (
                isinstance(case_inp, Mapping)
                and presentation.torsion_publication_evidence_is_current(
                    case_inp,
                    shear,
                    result,
                )[0]
                is not True
            ):
                return True
            return (
                result.get("valid") is False
                or presentation.torsion_applicability_publication_status(result)
                == "NOT ASSESSED"
                or presentation.torsion_assessment_status(
                    result, input_payload=case_inp,
                )
                not in {"PASS", "FAIL"}
            )
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
            if (
                isinstance(case_inp, Mapping)
                and presentation.shear_publication_input_is_current(
                    case_inp,
                    result,
                    plastic_result=self._plastic_publication_authority(),
                    torsion_result=(case_out or {}).get("torsion"),
                )[0]
                is not True
            ):
                return True
            directions = result.get("directions") or {}
            items = tuple(directions.values()) or (result,)
            if isinstance(case_inp, Mapping) and case_inp.get("shear_links") is True:
                torsion = (case_out or {}).get("torsion")
                if any(
                    presentation.provided_link_publication_assessment(
                        case_inp, item, torsion_result=torsion,
                    ).valid is not True
                    for item in items
                ):
                    return True
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
        if family == "combined":
            if not presentation.combined_uses_dkna(result):
                if result.get("biaxial") is True:
                    retained = presentation.base_en_combined_direction_items(
                        result
                    )
                    if retained is None:
                        return True
                    items = tuple(item for _, item in retained)
                else:
                    items = (result,)
                return not all(
                    item.get("valid") is True
                    and all(
                        component["status"] in {"PASS", "FAIL"}
                        and self._retained_utilisation_available(
                            component["util"]
                        )
                        for component in presentation.combined_physical_components(
                            item
                        )
                    )
                    for item in items
                )
            directions = result.get("directions") or {}
            items = tuple(directions.values()) or (result,)
            return not any(
                item.get("valid") is True
                and item.get("dkna_valid", item.get("valid")) is True
                and self._retained_utilisation_available(item.get("dkna_sum"))
                and presentation.combined_dkna_status(item)
                in {"PASS", "FAIL", "CONDITIONAL"}
                for item in items
            )
        return False

    @staticmethod
    def _retained_utilisation_available(value):
        """Whether a stored assessment utilisation can be published."""
        return (
            viz.utilisation_value(value, allow_positive_infinity=True)
            is not None
        )

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
            self._p('<b>2023 basis limitation.</b> DS/EN 1992-1-1:2023 is reported as a published project-adoption basis. The engineer is responsible for project adoption.')
            self._p('No Danish National Annex is applied. The 2023 confinement enhancement is not included or assessed.')
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
                "DS/EN 1992-1-1:2023 &#167;8.1.1-8.1.2 and &#167;5.1.6"
                if material_2023 else
                "DS/EN 1992-1-1 &#167;6.1 and &#167;3.1.7"
            )
            steel_ref = _steel_theory_reference(steel_presets)
            self._p('<b>Plastic section capacity.</b> Plane sections remain plane. Concrete in compression follows the design curve in the material section. Reinforcement follows its design stress-strain law.')
            self._p('For each trial neutral axis, the strain plane is scaled to the governing curvature. This curvature is the first material limit reached:')
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
            self._p('<b>Cracked-section elastic stresses.</b> The transformed section weights reinforcement by its modular ratio. Cracked concrete carries no tension. Steel carries tension and compression.')
            self._p('Each bar or tendon uses its assigned elastic modulus. Its modular ratio is calculated from the material moduli:')
            self._p('n<sub>i</sub> = E<sub>i</sub>/E<sub>c</sub>.')
            self._p('Long-term and short-term actions use their respective modular ratios. For the long-term state, creep reduces the concrete modulus:')
            self._p('E<sub>c,eff</sub> = E<sub>c</sub>/(1+&#966;).')
            self._p('The long-term modular ratio is E<sub>i</sub>/E<sub>c,eff</sub>.')
            self._p('Concrete occupied by reinforcement is deducted. The added transformed area in the compression zone is:')
            self._p('(n<sub>i</sub>-1)A<sub>i</sub>.')
            self._p('In the cracked tension zone, the added transformed area is:')
            self._p('n<sub>i</sub>A<sub>i</sub>.')
            self._p("<b>Cracking threshold.</b> The Stage-I extreme tensile stress "
                    "is compared with f<sub>ct,eff</sub>. The uncracked section "
                    "deducts concrete occupied by reinforcement in both tension "
                    "and compression.")
            if any(result.get("show_cw") for result in elastic_results):
                self._p('<b>Crack width.</b> The requested calculation uses the selected code method. The crack-width section gives the worked calculation.')
        if fatigue is not None and not fatigue_errors:
            references = fatigue.get("calculation_references") or {}
            self._p(
                "<b>Grouped fatigue.</b> Each named spectrum is checked "
                "independently with the cracked Elastic analysis. For each bin, "
                "the long action is the sustained state and the short action is "
                "the cyclic increment."
            )
            self._formula(
                "&#916; sigma<sub>i</sub> = | sigma(long + "
                "gamma<sub>Ff</sub> &#183; short)<sub>i</sub> - "
                "sigma(long)<sub>i</sub> |",
                equation_key="basis.fatigue.stress-range",
                ref=(
                    "gamma<sub>Ff</sub> is applied to the cyclic section "
                    "actions before solving; stresses are not scaled afterwards."
                ),
            )
            if (fatigue.get("checks") or {}).get("reinforcement"):
                self._p('<b>Reinforcement fatigue.</b> A supported named detail is first compared with its simplified stress-range limit.')
                self._p('If this shortcut passes, the detailed range check is unnecessary. Otherwise, the assigned two-slope S-N curve gives N<sub>R,i</sub> for each design stress range.')
                self._p('Both results are reported. Each bin also has an independent yield or proof-stress check.')
                self._formula(
                    "D = &#8721;(n<sub>i</sub> / N<sub>R,i</sub>) &#8804; 1.00",
                    equation_key="basis.fatigue.reinforcement-miner",
                    ref=_html_escape(
                        references.get("reinforcement") or "-"
                    ),
                )
            if (fatigue.get("checks") or {}).get("concrete"):
                self._p('<b>Concrete fatigue.</b> Compression minima and maxima are evaluated at the same fiber for every bin.')
                self._p('Miner damage and the maximum compressive-stress ratio are checked. An adaptive section search reports an upper bound for damage.')
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
            minimum_source = _input_reference_source(
                edition,
                InputGuidanceKey.DETAILING_MINIMUM_REINFORCEMENT,
            )
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
                    "Reference: " + _html_escape(minimum_source)
                    + ". Prestressing tendons are not credited."
                )
            else:
                self._p(f"<b>Minimum reinforcement - {direction_label}.</b> The resultant gross-concrete tension zone is checked with:")
                self._p("A<sub>s,min</sub> = max(0.26 f<sub>ctm</sub>/f<sub>yk</sub>, 0.0013) b<sub>t</sub>d.")
                self._small(
                    "Reference: " + _html_escape(minimum_source)
                    + ". Prestressing tendons are not credited."
                )
        if transverse_results:
            edition = str(self.inp.get("detailing_edition") or "")
            transverse_source = _input_reference_source(
                edition,
                InputGuidanceKey.DETAILING_TRANSVERSE_LINKS,
            )
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
                ref=_html_escape(transverse_source),
            )
            self._small('The model uses vertical stirrups for shear reinforcement and closed stirrups for torsion reinforcement.')
            self._small('Anchorage is assumed. Reduce f<sub>ywk</sub> when full anchorage is unavailable.')
            self._small('Transverse leg spacing is the distance between adjacent parallel legs in the section plane. It is measured along y for V<sub>x</sub> and along x for V<sub>y</sub>.')
            self._small('A zero input uses the gross web breadth as an upper bound. If this bound passes the spacing check, the result is PASS.')
            self._small('Enter the actual spacing when the bound exceeds the limit.')
        if self._base_out.get("clear_spacing") is not None:
            spacing_source = _input_reference_source(
                self.inp.get("detailing_edition"),
                InputGuidanceKey.DETAILING_CLEAR_SPACING,
            )
            self._p('<b>Clear spacing.</b> The edge-to-edge distance for each pair is compared with:')
            self._p('max(phi, D<sub>upper</sub> + 5 mm, 20 mm).')
            self._small(
                "Reference: " + _html_escape(spacing_source) + ". "
                "Review laps and bundles separately in member detailing."
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
            self.profile.substitution_scope != "none"
            and
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
            f"governing utilization {_pct(max(utilisations))}"
            if utilisations
            else _result_reason(
                result.get("reason"),
                "minimum_reinforcement",
                "report minimum-reinforcement summary reason",
            )
        )
        self._status_block(f"{status} - {summary}", status)
        self._small(
            f"<b>Modeled direction:</b> {direction_label}; "
            f"<b>Method:</b> {_html_escape(result.get('member_type', '-'))}; "
            f"{_html_escape(result.get('cut_direction', '-'))} | "
            f"{_html_escape(result.get('edition', '-'))} | "
            f"{_html_escape(result.get('clause', '-'))}."
        )

        for limitation in result.get("limitations") or []:
            self._small("<b>Scope:</b> " + _html_escape(report_notation.native_scope(limitation)))

        highlight_ids = sorted({
            str(element_id)
            for check in checks
            for element_id in check.get("bar_ids") or []
        })
        if self.figures:
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
            self._small(
                "Areas in mm<super>2</super>; b<sub>t</sub> and d in mm; "
                "strengths in MPa."
            )
            self.flow[-1].keepWithNext = 1
            self._table(
                rows,
                [14 * mm, 22 * mm, 17 * mm, 17 * mm, 14 * mm,
                 14 * mm, 14 * mm, 13 * mm, 13 * mm, 18 * mm, 14 * mm],
                font=5.9,
                keep=False,
                repeat_cols=2,
            )
            for check in checks:
                if check.get("reason"):
                    self._small(
                        "<b>Outcome:</b> " + _html_escape(_result_reason(
                            check["reason"],
                            "minimum_reinforcement",
                            "report minimum-reinforcement check reason",
                        ))
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
                    ref="DS/EN 1992-1-1:2023 &#167;12.2(2)(b), Formula (12.2)",
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
                "R<sub>cr</sub> (kN)", "R<sub>nom</sub> (kN)", "Utilization",
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
                    ref="Sector vertex evaluation of DS/EN 1992-1-1:2023 Formula (12.1)",
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
            ref="Final nominal-section axial equilibrium.",
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
                    ref="DS/EN 1992-1-1:2023 &#167;12.2(2)(a), Formula (12.1)",
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
                "Utilization", "N<sub>nom,t</sub> (kN)", "Axial eq.",
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
                solution = check.get("nominal_solution") or {}
                history = solution.get("refinement_history") or []
                if history:
                    target = solution.get("governing_target_increment_deg")
                    if "governing_target_increment_deg" not in solution:
                        target = solution.get("governing_increment_deg")
                    achieved = solution.get("governing_interval_deg")
                    retained = solution.get("accepted_point_count")
                    resolution = str(
                        solution.get("resolution_state") or ""
                    ).upper()
                    outcome = (
                        "assessment resolved"
                        if resolution == "RESOLVED"
                        else "separate assessment required"
                    )
                    convergence = (
                        "all retained angles converged"
                        if solution.get("all_points_converged")
                        else "one or more retained angles did not converge"
                    )
                    if achieved is not None:
                        self._small("<b>Angular resolution:</b> the initial envelope uses 15&#176; intervals.")
                        self._small(f"Achieved governing interval: {_fmt(achieved, 3)}&#176;."
                                    + (f" Target: {_fmt(target, 3)}&#176;." if target is not None else ""))
                        self._small(f"Retained angles: {retained}. {convergence.capitalize()}; {outcome}.")
                    lower = solution.get("utilisation_lower_bound")
                    upper = solution.get("utilisation_upper_bound")
                    if lower is not None and upper is not None:
                        self._small(
                            "<b>Refinement estimate:</b> utilisation interval "
                            f"{_fmt(100.0 * float(lower), 4)} to "
                            f"{_fmt(100.0 * float(upper), 4)} %."
                        )
        elif result.get("reason"):
            self._small(_html_escape(_result_reason(
                result["reason"],
                "minimum_reinforcement",
                "report minimum-reinforcement result reason",
            )))

        if checks and not publish_worked:
            self._small(
                "The complete minimum-reinforcement worked example is published in Audit "
                "only for the governing utilization across all plastic cases."
            )


    def _transverse_reinforcement(self):
        result = self.out["transverse_reinforcement"]
        publish_worked = (
            self.profile.substitution_scope != "none"
            and
            self._selected_family("transverse_reinforcement", self.inp) is not None
        )
        self._case_heading("Shear/torsion link detailing", "plastic")
        status = str(result.get("status") or "NOT ASSESSED").upper()
        governing = result.get("governing") or {}
        utilisation = governing.get("utilisation")
        incomplete_reason = next((
            _result_reason(
                check["reason"],
                "transverse_reinforcement",
                "report transverse-reinforcement check reason",
            )
            for check in result.get("checks") or []
            if check.get("status") == "NOT ASSESSED" and check.get("reason")
        ), None)
        summary = (
            incomplete_reason
            if status == "NOT ASSESSED" and incomplete_reason
            else str(governing.get("scope") or "not evaluated")
        )
        if not governing and result.get("reason"):
            summary = _result_reason(
                result["reason"],
                "transverse_reinforcement",
                "report transverse-reinforcement summary reason",
            )
        if (
            status != "NOT ASSESSED"
            and utilisation is not None
            and math.isfinite(float(utilisation))
        ):
            summary += f"; utilization {_pct(utilisation)}"
        self._status_block(f"{status} - {summary}", status)

        for limitation in result.get("limitations") or []:
            self._small("<b>Scope:</b> " + _html_escape(report_notation.native_scope(limitation)))

        minimum = result.get("minimum_ratio") or {}
        self._small(f"<b>Method:</b> {_html_escape(result.get('member_type', '-'))}; {_html_escape(result.get('edition', '-'))}.")
        self._small(f"Stirrup diameter &#966; = {_fmt(result.get('diameter_mm'), 1)} mm.")
        self._small(f"Stirrup spacing s = {_fmt(result.get('spacing_mm'), 1)} mm.")
        self._small(f"f<sub>ywk</sub> = {_fmt(result.get('fywk_mpa'), 1)} MPa.")
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
                "The complete link-detailing worked example is published in Audit only "
                "for the governing utilization across all plastic cases."
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
                    report_notation.concat("governing limit: ",
                        str(check["governing_limit"])
                        if str(check["governing_limit"]) != "u_k/8"
                        else report_notation.authored("u_k/8"))
                )
            if check.get("reason"):
                details.append(_result_reason(
                    check["reason"],
                    "transverse_reinforcement",
                    "report transverse-reinforcement detail reason",
                ))
            if details:
                self._small(
                    f"<b>{_html_escape(check.get('scope') or 'Check')}:</b> "
                    + _html_escape(report_notation.join("; ", details))
                )

    def _clear_spacing(self):
        result = self.out["clear_spacing"]
        self._h1("Reinforcement clear spacing")
        status = str(result.get("status") or "NOT ASSESSED").upper()
        governing = result.get("governing") or {}
        summary = (
            f"{_fmt(governing.get('clear_mm'), 1)} mm clear; "
            f"{_fmt(governing.get('required_mm'), 1)} mm required"
            if governing
            else _result_reason(
                result.get("reason"),
                "generic",
                "report clear-spacing reason",
            )
        )
        self._status_block(f"{status} - {summary}", status)
        self._small(
            f"<b>Method:</b> {_html_escape(result.get('edition', '-'))} | "
            f"{_html_escape(result.get('clause', '-'))}; "
            f"D<sub>upper</sub> = {_fmt(result.get('d_upper_mm'), 1)} mm."
        )
        if self.figures:
            self._fig(viz.detailing_geometry_figure(
                self.inp.get("outer") or [],
                self.inp.get("holes") or [],
                self.inp.get("bars") or [],
                self.inp.get("tendons") or [],
                bar_elements=self.inp.get("bar_elements") or [],
                tendon_elements=self.inp.get("tendon_elements") or [],
                spacing_pair=governing,
                slab_density=self.inp.get("slab_density"),
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
        published_pairs = (
            pairs
            if self.profile.key == "Audit"
            else ([governing] if governing else [])
        )
        if published_pairs:
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
                for pair in published_pairs
            ])
            self._table(
                rows,
                [38 * mm, 30 * mm, 26 * mm, 30 * mm, 26 * mm, 20 * mm],
                font=6.4,
                keep=False,
                repeat_cols=2,
            )
        for limitation in result.get("limitations") or []:
            self._small("<b>Scope:</b> " + _html_escape(report_notation.native_scope(limitation)))

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
        if self.figures:
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
                "Utilization",
                "INVALID - " + _html_escape(assessment.get("detail") or ""),
            ])
        elif not pl.get("check_util", True):
            rows.append(["Utilization", "not checked (capacity only)"])
        elif not assessment.get("assessed"):
            rows.append([
                "Utilization",
                "not assessed - " + _html_escape(assessment.get("detail") or ""),
            ])
        elif assessment.get("util") is not None:
            if applied is not None:
                rows.append(["Applied M<sub>x</sub>, M<sub>y</sub>",
                             f"{_fmt(applied[0], 3)}, {_fmt(applied[1], 3)} kNm"])
            rows.append(["Utilization (applied direction)",
                         f"{_fmt(assessment['util']*100, 3)} %"])
        else:
            rows.append([
                "Utilization",
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
                diagram_start = len(self.flow)
                if self.figures:
                    self._fig(viz.interaction_nm_figure(
                        d["N"], d["M"], axis=axis,
                        applied=d.get("applied") if pl.get("check_util", True) else None,
                        title=f"N-{mtag} interaction"), 130, 95)
                self._small(f"The capacity boundary about the {axis}-axis extends from pure tension to the squash load.")
                self._small("Concrete carries compression only. Reinforcement therefore controls the tension end.")
                if pl.get("check_util", True) and d.get("applied") is not None:
                    self._small("The marked point is the applied plastic action.")
                self._keep_from(diagram_start)
            if self.profile.key == "Audit":
                self._plastic_nm_boundary(nm)
        if self.profile.key == "Audit":
            self._plastic_sweep_population(pl)
        # Each case has its own retained capacity point. Map publication is
        # independent of the report's cross-case worked-calculation selection.
        self._section_field_maps(pl, family="Plastic", point_index=pl.get("worked_point_index"))
        if self._selected_family("plastic", self.inp) is not None:
            self._plastic_worked(pl)
        else:
            self._small(
                "Audit gives the complete plastic worked example for the governing "
                "utilization across all plastic cases. When utilization is not "
                "assessed, it uses the capacity extremum."
            )

    def _plastic_field_chapter(self):
        case_id = self._case_id(self.inp, "plastic")
        self._h1(f"Plastic section maps - {case_id}")
        result = self.out["plastic"]
        self._section_field_maps(result, family="Plastic", point_index=result.get("worked_point_index"))

    def _elastic_field_chapter(self):
        case_id = self._case_id(self.inp, "elastic")
        self._h1(f"Elastic section maps - {case_id}")
        self._section_field_maps(self.out["elastic"], family="Elastic")

    def _section_field_maps(self, result, *, family, point_index=None):
        if not self.figures:
            return
        try:
            field, figures = section_fields.field_pair(
                self.inp, result, family=family, point_index=point_index)
        except section_fields.FieldUnavailable as exc:
            self._h2("Section stress and strain maps", reserve=0)
            self._small("Section maps unavailable. " + _html_escape(str(exc)))
            return
        case = self.inp.get("plastic_case" if family == "Plastic" else "elastic_case") or {}
        case_label = str(case.get("id") or "Unnamed action")
        definition_start = len(self.flow)
        follows_heading = self._preceding_headings(definition_start) < definition_start
        definitions = [
            "For the section maps, color limits stay fixed across valid states of this action. Other actions can have different limits.",
            "Display bands show values from the accepted field. Marker sizes identify elements; the element schedule gives their areas.",
        ]
        if field.density:
            definitions.append("Slab-density markers identify retained integration points or nominal axes with tabulated tributary areas.")
        # Preserve the existing opening paragraphs after a dedicated chapter.
        # Other introductions can accompany a map instead of forming a notes page.
        for paragraph in definitions if follows_heading else [" ".join(definitions)]:
            self._small(paragraph)
        for index, (quantity, figure) in enumerate(figures):
            # Definitions can flow in the preceding space. The map heading and
            # selected state stay with the first figure and its extrema.
            block_start = len(self.flow)
            if index == 0:
                self._h2("Section stress and strain maps", reserve=0)
                self._p(_html_escape(field.state + ". " + field.caption))
            heading_content = list(self.flow[block_start:])
            canvas_width, canvas_height = float(figure.layout.width), float(figure.layout.height)
            if not (math.isfinite(canvas_width) and math.isfinite(canvas_height)
                    and canvas_width > 0.0 and canvas_height > 0.0):
                raise ReportFigureError("Section map dimensions are invalid.")
            scale = min(170.0 / canvas_width, 160.0 / canvas_height)
            self._fig(figure, canvas_width * scale, canvas_height * scale,
                      caption=f"{case_label}: {family.lower()} {quantity}. {field.state}.",
                      export_size=(int(canvas_width), int(canvas_height)))
            unit = "&#8240;" if quantity == "strain" else "MPa"
            rows = [["Extremum", f"Value ({unit})", "x (mm)", "y (mm)"]]
            rows.extend([_html_escape(label), _fmt(value, 5), _fmt(x * _MM, 2), _fmt(y * _MM, 2)]
                        for label, value, x, y in section_fields.extrema(field, quantity))
            self._table(rows, [80 * mm, 35 * mm, 25 * mm, 25 * mm], font=8)
            self._small("Tension is positive. Compression is negative. " + (
                "Concrete and reinforcement use separate stress scales."
                if quantity == "stress" else "Strain values are in &#8240;."))
            self._keep_from(block_start)
            if heading_content:
                group = self.flow[-1]
                measure_canvas = canvas.Canvas(io.BytesIO())
                group.wrapOn(measure_canvas, _A4_CONTENT_WIDTH - 2 * _REPORT_FRAME_PADDING,
                             _A4_FRAME_USABLE_HEIGHT)
                if group._H + group.getSpaceBefore() > _A4_FRAME_USABLE_HEIGHT:
                    # Preserve the complete map block when a long identity or
                    # extra extrema leave no room for its preceding heading.
                    count = len(heading_content)
                    assert all(a is b for a, b in zip(group._content[:count], heading_content))
                    self.flow[-1:] = [*heading_content, KeepTogether(group._content[count:])]
            if index == 0 and not follows_heading:
                # Measure before replacing flow, without consuming a preceding
                # chapter heading. Definitions may accompany either map.
                definitions_content = list(self.flow[definition_start:block_start])
                first_content = []
                for item in self.flow[block_start:]:
                    first_content.extend(item._content if isinstance(item, KeepTogether) else [item])
                complete = KeepTogether([*definitions_content, *first_content])
                complete.wrapOn(canvas.Canvas(io.BytesIO()),
                                _A4_CONTENT_WIDTH - 2 * _REPORT_FRAME_PADDING,
                                _A4_FRAME_USABLE_HEIGHT)
                if complete._H + complete.getSpaceBefore() <= _A4_FRAME_USABLE_HEIGHT:
                    self.flow[definition_start:] = [complete]
                    definitions_content = []
                elif len(figures) > 1:
                    del self.flow[definition_start:block_start]
            elif index == 1 and not follows_heading and definitions_content:
                second_map = self.flow[-1]
                defined_map = KeepTogether([*definitions_content, *second_map._content])
                defined_map.wrapOn(canvas.Canvas(io.BytesIO()),
                                   _A4_CONTENT_WIDTH - 2 * _REPORT_FRAME_PADDING,
                                   _A4_FRAME_USABLE_HEIGHT)
                if defined_map._H + defined_map.getSpaceBefore() <= _A4_FRAME_USABLE_HEIGHT:
                    self.flow[-1] = defined_map
                else:
                    # An oversized map retains the prior flowing introduction.
                    self.flow[definition_start:definition_start] = definitions_content

    def _plastic_nm_boundary(self, nm):
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
        self._small('The point sequence is the plotted boundary sequence. N is in kN and is positive in tension. M is in kN&#183;m.')
        self._small('The two traces can use different numerical points. Each trace therefore has its own N column.')

    def _plastic_sweep_population(self, pl):
        # Audit retains the complete per-angle population in exact solver order.
        # Split it into readable groups with the NA angle repeated as the row key;
        # a single wide table forces values to wrap digit by digit.
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
                       + ["kappa", "F<sub>comp</sub>", "lever z",
                          "z<sub>x</sub>", "z<sub>y</sub>"])
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
        self._small("<b>Capacity and neutral axis</b>", keep_with_next=True)
        self._table(
            capacity_rows,
            [18 * mm, 38 * mm, 38 * mm, 38 * mm, 38 * mm],
            font=7.5,
            keep=False,
        )
        self._small("<b>Strain and equilibrium detail</b>", keep_with_next=True)
        detail_cols = len(detail_head)
        self._table(
            detail_rows,
            [170 * mm / detail_cols] * detail_cols,
            font=7.2,
            keep=False,
        )
        self._small('Neutral-axis angle is in &#176;. Moments are in kN&#183;m, and F<sub>comp</sub> is in kN.')
        self._small('Neutral-axis x/y coordinates and lever arms z, z<sub>x</sub> and z<sub>y</sub> are in mm.')
        self._small('Strain is in %. Curvature kappa is in 1/m.')

    def _plastic_worked(self, pl):
        pts = pl["points"]
        worked_index = pl.get("worked_point_index")
        assessment = presentation.plastic_action_assessment(pl)
        retained_basis = str(
            pl.get("worked_point_basis") or "selected capacity point"
        )
        if retained_basis == "utilisation direction" and not assessment.get(
            "assessed"
        ):
            self._h2("Worked plastic calculation unavailable")
            self._small(
                "The selected worked point is unavailable: "
                + _html_escape(assessment.get("detail") or "recalculate")
                + ". Recalculate before issuing the report."
            )
            return
        if not isinstance(worked_index, int) or not 0 <= worked_index < len(pts):
            self._h2("Worked plastic calculation unavailable")
            self._small(
                "The selected governing capacity point is unavailable. "
                "Recalculate before issuing the report."
            )
            return
        gov = pts[worked_index]
        basis = retained_basis
        heading = (
            f"Governing plastic state ({basis})"
            if self.profile.key == "Standard"
            else f"Worked plastic calculation ({basis})"
        )
        state_rows = presentation.plastic_state_rows(gov)
        start = len(self.flow)
        self._h2(heading)
        self._p("Source: " + _html_escape(presentation.action_set_text(self.inp, "plastic", include_source=False)) + ".")
        self._p(f"N<sub>Ed</sub> = {_fmt(self.inp.get('P_pl', 0.0), 3)} kN.")
        self._p(f"Selected sweep point: {worked_index + 1} of {len(pts)}. Neutral-axis angle = {_fmt(gov['V'], 0)}&#176;.")
        self._p("Plastic equilibrium uses internal axial forces that are positive in compression. The entered N<sub>Ed</sub> is positive in tension. Its sign is converted for the equilibrium calculation.")
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
        compression_depth_mm = presentation.plastic_compression_depth_mm(gov)
        rows = [["Quantity", "Symbol", "Value"],
                ["NA intercepts", "x<sub>na</sub>, y<sub>na</sub>",
                 f"{_fmt(gov['na_x']*_MM, 3)}, {_fmt(gov['na_y']*_MM, 3)} mm"],
                ["Extreme concrete strain", "eps<sub>c</sub>", f"{_fmt(gov['eps_c'], 3)} %"],
                *steel_rows,
                ["Curvature", "kappa", f"{_fmt(gov['kappa'],4)} 1/m"],
                ["Compression resultant", "F<sub>comp</sub>",
                 f"{_fmt(gov['comp_force'], 3)} kN"],
                ["Compression-zone depth", "c", (
                    "-" if compression_depth_mm is None
                    else f"{_fmt(compression_depth_mm, 3)} mm"
                )],
                ["Internal lever arm", "z", f"{_fmt(gov['lever']*_MM, 3)} mm"],
                *[[f"Effective depth ({face})", "d",
                   "Unavailable" if depth is None else f"{depth:.3f} mm"]
                  for face, depth in presentation.plastic_face_depth_summary(pl)],
                ["Lever components", "z<sub>x</sub>, z<sub>y</sub>",
                 f"{_fmt(gov['dx']*_MM, 3)}, {_fmt(gov['dy']*_MM, 3)} mm"],
                ["Capacity", "M<sub>x</sub>, M<sub>y</sub>",
                 f"{_fmt(gov['Mx'], 3)}, {_fmt(gov['My'], 3)} kNm"]]
        self._table(rows, [70 * mm, 30 * mm, 60 * mm])
        self._keep_from(start)
        if self.profile.key == "Standard":
            governing_candidate = next(
                (item for item in gov.get("curvature_candidates") or ()
                 if item.get("selected")),
                None,
            )
            if governing_candidate is not None:
                mode_labels = {
                    "concrete_crushing": "Concrete crushing",
                    "bar_tension_rupture": "Bar tension rupture",
                    "bar_compression_rupture": "Bar compression rupture",
                    "tendon_tension_rupture": "Tendon tension rupture",
                }
                mode = governing_candidate.get("mode")
                element = governing_candidate.get("element_id")
                self._small(
                    "<b>Governing strain limit:</b> "
                    + _html_escape(mode_labels.get(mode, str(mode or "-")))
                    + "; "
                    + ("element " + _html_escape(str(element))
                       if element else "extreme concrete fiber")
                )
                self._small(
                    "Sector governing-curvature minimum; the governing material "
                    "candidate is stated with the result."
                )
            self._small(
                "Method: plane-section strain compatibility and force equilibrium "
                "at the retained governing capacity point. The calculation sequence "
                "and element equilibrium contributions are in Audit."
            )
            return
        if self.profile.key == "Audit":
            self._h2("Face-specific effective depth")
            effective_depths = pl.get("effective_depths") or ()
            if not effective_depths:
                self._small(
                    "This result does not include face-specific effective depth. "
                    "Recalculate to show it."
                )
                effective_depths = ()
            depth_rows = [[
                "Bending axis", "Tension face", "d", "Tension bars",
                "A<sub>sl</sub>", "A<sub>sl</sub> centroid", "Arm component",
            ]]
            for item in effective_depths:
                ids = ", ".join(str(value) for value in item["asl_bar_ids"])
                cg = item["asl_cg_m"]
                component = (
                    "z<sub>y</sub>"
                    if item["arm_component"] == "z_y"
                    else "z<sub>x</sub>"
                )
                depth_rows.append([
                    item["axis"],
                    viz.tension_face_label(
                        item["tension_low"], item["axis"]
                    ),
                    (
                        f"{_fmt(item['d_mm'], 3)} mm"
                        if item["d_mm"] > 0.0
                        else "-"
                    ),
                    ids or "none",
                    f"{_fmt(item['asl_mm2'], 3)} mm<super>2</super>",
                    (
                        f"{item['coordinate']} = {_fmt(cg * _MM, 3)} mm"
                        if cg is not None
                        else "-"
                    ),
                    component,
                ])
            if effective_depths:
                self._table(
                    depth_rows,
                    [16 * mm, 30 * mm, 22 * mm, 24 * mm, 22 * mm,
                     34 * mm, 22 * mm],
                    font=7.2,
                    keep=False,
                )
                self._small(
                    "Each d is measured from the opposite extreme concrete fiber "
                    "to the centroid of the listed ordinary reinforcing bars. Four face-aligned "
                    "values cover either bending direction, including off-axis "
                    "states."
                )
        plane_values = (
            gov.get("strain_offset"), gov.get("strain_gradient_x"),
            gov.get("strain_gradient_y"),
        )
        reference_rows = state_rows["concrete"] or state_rows["elements"]
        if all(value is not None for value in plane_values) and reference_rows:
            reference = reference_rows[0]
            self._h2("Converged strain plane")
            self._formula(
                "eps<sub>sec</sub>(x,y) = eps<sub>0</sub> + "
                "g<sub>x</sub>x + g<sub>y</sub>y",
                equation_key="plastic.worked.strain-plane",
                ref="Sector plane-section kinematics at the selected capacity point.",
                subst=(
                    f"= {_fmt(plane_values[0], 8)} + "
                    f"{_fmt(plane_values[1], 8)} &#183; "
                    f"{_fmt(reference['x_mm'] / _MM, 6)} + "
                    f"{_fmt(plane_values[2], 8)} &#183; "
                    f"{_fmt(reference['y_mm'] / _MM, 6)}"
                ),
                result=(
                    f"eps<sub>sec</sub> = "
                    f"{_fmt(reference['section_strain_permille'], 6)} &#8240; "
                    "(compression positive)"
                ),
            )

        candidates = gov.get("curvature_candidates") or []
        selected = gov.get("curvature_selection") or {}
        if candidates:
            mode_labels = {
                "concrete_crushing": "Concrete crushing",
                "bar_tension_rupture": "Bar tension rupture",
                "bar_compression_rupture": "Bar compression rupture",
                "tendon_tension_rupture": "Tendon tension rupture",
            }
            governing_candidate = next(
                (candidate for candidate in candidates if candidate.get("selected")),
                None,
            )
            if self.profile.key == "Audit":
                self._h2("Ultimate-curvature candidates")
                candidate_rows = [[
                    "Candidate", "Element", "Strain limit (&#8240;)", "Distance to NA (mm)",
                    "Curvature (1/m)", "Selected",
                ]]
                for candidate in candidates:
                    candidate_rows.append([
                        mode_labels.get(candidate["mode"], candidate["mode"]),
                        candidate.get("element_id") or "extreme concrete fiber",
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
            if selected and governing_candidate is not None:
                if self.profile.key != "Audit":
                    self._h2("Governing ultimate curvature")
                    selected_element = governing_candidate.get("element_id")
                    self._small(
                        "<b>Selected candidate:</b> "
                        + _html_escape(mode_labels.get(
                            governing_candidate["mode"],
                            governing_candidate["mode"],
                        ))
                        + "; "
                        + (
                            "element " + _html_escape(str(selected_element))
                            if selected_element
                            else "extreme concrete fiber"
                        )
                        + "."
                    )
                self._formula(
                    "kappa<sub>i</sub> = eps<sub>lim,i</sub> / d<sub>i</sub>",
                    equation_key="plastic.worked.curvature-candidate",
                    ref="Material strain-limit candidate at the solved depth.",
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
                    ref=(
                        "Sector governing-curvature minimum; the governing material "
                        "candidate is stated with the result."
                    ),
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
        if (
            compression_depth_mm is not None
            and all(gov.get(key) is not None for key in search_keys)
        ):
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
                "Solved compression depth",
                f"{_fmt(compression_depth_mm, 6)} mm",
            ], [
                "Requested / achieved internal N",
                f"{_fmt(gov['axial_requested'], 6)} / "
                f"{_fmt(gov['axial_achieved'], 6)} kN",
            ], [
                "Residual / tolerance",
                f"{_fmt(gov['axial_residual'], 9)} / "
                f"{_fmt(gov['axial_tolerance'], 9)} kN",
            ], [
                "Converged state",
                "yes" if gov.get("axial_reachable") and gov.get("converged") else "no",
            ]]
            self._table(search_rows, [75 * mm, 85 * mm], keep=False)
            self._small(
                "Only the initial bracket, converged state and final residual are "
                "shown; the internal bisection sequence and integration bands are "
                "not published."
            )
        else:
            self._h2("Compression-depth solution unavailable")
            self._small(
                "The converged bracket, depth and residual summary are "
                "unavailable. Recalculate before issuing the report."
            )

        resultant_keys = (
            "concrete_force", "bar_force", "tendon_force",
            "concrete_mx", "bar_mx", "tendon_mx",
            "concrete_my", "bar_my", "tendon_my",
            "axial_achieved", "axial_requested", "axial_residual", "Mx", "My",
        )
        if all(gov.get(key) is not None for key in resultant_keys):
            self._h2("Section resultants at convergence")
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
            self._h2("Section resultants at convergence unavailable")
            self._small(
                "One or more concrete, mild-steel or tendon resultants are "
                "unavailable. Recalculate before issuing the report."
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
                "Coordinates in mm; strain in &#8240;; design stress in MPa. "
                "Strain and stress are tension-positive."
            )
        element_rows = state_rows["elements"]
        if element_rows:
            self._h2("Governing reinforcement and tendon response")
            worked_element = element_rows[0]
            self._formula(
                "F<sub>i</sub> = sigma<sub>i</sub>A<sub>i</sub>/1000",
                equation_key="plastic.worked.element-force",
                ref="Calculated material response and entered element area.",
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
            self._small('Coordinates are in mm, and area is in mm<super>2</super>. Strain is in &#8240;, design stress is in MPa, and force is in kN.')
            self._small('Signs are positive in tension. Force equals stress multiplied by the entered area, with the applicable unit conversion.')
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
            self._small('Blue markers without crosses show tension (+). Vermillion markers with crosses show compression (-). Circles identify bars, and diamonds identify tendons.')
            self._small('The element table gives the element IDs and coordinates.')

    def _shear_2023(self, sh, res):
        """The DS/EN 1992-1-1:2023 strain-based tau_Rd,c body (sec. 8.2.2)."""
        bw_src = "user input" if sh["bw_user"] else "derived (minimum solid width)"
        calculation_bw = float(res.get("bw", sh["bw"]))
        if not math.isclose(
            calculation_bw, float(sh["bw"]), rel_tol=0.0, abs_tol=1e-9
        ):
            bw_src = f"nominal after duct allowance; physical bw = {_fmt(sh['bw'], 1)} mm"
        fck = sh["fck"]
        rows = [["Quantity", "Symbol", "Value"],
                ["Effective depth", "d", f"{_fmt(sh['d'], 1)} mm"],
                ["Web width", "b<sub>w</sub>",
                 f"{_fmt(calculation_bw, 1)} mm ({bw_src})"],
                ["Standard-defined concrete-shear arm", "z",
                 f"{_fmt(res['z'], 1)} mm (0.9 d; 8.2.1(3))"],
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
                ["Shear partial factor (4.3.3; Table 4.3 NDP)",
                 "gamma<sub>V</sub>",
                 _fmt_gamma_v(res["gamma_v"])]]
        self._table(rows, [55 * mm, 25 * mm, 70 * mm])
        self._h2("Resistance")
        if res.get("a_cs", 0.0) > 0.0:
            self._formula(
                "a<sub>cs</sub> = max(|M<sub>Ed</sub>/V<sub>Ed</sub>|, d)",
                equation_key="shear.2023.effective-span",
                ref="DS/EN 1992-1-1:2023 Formula (8.30)",
                subst=f"max(|{_fmt(sh.get('m_ed_2023'), 3)}| / "
                      f"{_fmt(sh.get('v_ed'), 3)} &#183; 1000, {_fmt(sh['d'], 1)})",
                result=f"a<sub>cs</sub> = {_fmt(res.get('a_cs'), 1)} mm")
            self._formula(
                "k<sub>vp</sub> = max(1 + N<sub>Ed</sub>/|V<sub>Ed</sub>| &#183; "
                "d/(3a<sub>cs</sub>), 0.1)",
                equation_key="shear.2023.axial-factor",
                ref="DS/EN 1992-1-1:2023 &#167;8.2.2(4), Formula (8.31)",
                subst=f"N<sub>Ed</sub> = {_fmt(res.get('n_ed_tension'), 3)} kN; "
                      f"k<sub>vp</sub> = {_fmt(res.get('k_vp'), 4)}",
                result=f"k<sub>vp</sub>d = {_fmt(res.get('d_kvp'), 1)} mm")
        self._formula(
            "tau<sub>Rd,c</sub> = (0.66/gamma<sub>v</sub>)(100 rho<sub>l</sub> "
            "f<sub>ck</sub> d<sub>dg</sub>/(k<sub>vp</sub>d))<sup>1/3</sup>",
            equation_key="shear.2023.tau-basic",
            ref="DS/EN 1992-1-1:2023 &#167;8.2.2, Formula (8.27)",
            subst=f"(0.66/{_fmt_gamma_v(res['gamma_v'])})(100 &#183; "
                  f"{_fmt(res['rho_l'], 4)} &#183; {_fmt(fck, 0)} &#183; "
                  f"{_fmt(res['ddg'], 1)}/{_fmt(res.get('d_kvp'), 1)})"
                  "<sup>1/3</sup>",
            result=f"tau = {_fmt(res['tau_basic'], 3)} MPa")
        self._formula(
            "tau<sub>Rd,c,min</sub> = (11/gamma<sub>v</sub>) "
            "&#8730;(f<sub>ck</sub>/f<sub>yd</sub> &#183; d<sub>dg</sub>/d)",
            equation_key="shear.2023.tau-minimum",
            ref="DS/EN 1992-1-1:2023 &#167;8.2.2, Formula (8.20)",
            subst=f"(11/{_fmt_gamma_v(res['gamma_v'])}) &#8730;({_fmt(fck, 0)}/"
                  f"{_fmt(res['fyd'], 1)} &#183; {_fmt(res['ddg'], 1)}/"
                  f"{_fmt(sh['d'], 1)})",
            result=f"tau<sub>min</sub> = {_fmt(res['tau_min'], 3)} MPa")
        self._formula(
            "V<sub>Rd,c</sub> = max(tau<sub>Rd,c</sub>, tau<sub>Rd,c,min</sub>) "
            "b<sub>w</sub> z",
            equation_key="shear.2023.vrdc",
            references=("shear.2023.tau-basic", "shear.2023.tau-minimum"),
            subst=f"max({_fmt(res['tau_rdc'], 3)}, {_fmt(res['tau_min'], 3)}) &#183; "
                  f"{_fmt(calculation_bw, 1)} &#183; {_fmt(res['z'], 1)} / 1000",
            result=f"V<sub>Rd,c</sub> = {_fmt(res['vrd_c'], 3)} kN")
        util = sh["util"]
        util_txt = _pct(util)
        nominal = presentation.nominal_shear_resistance(
            sh,
            links_selected=self.inp.get("shear_links") is True,
            input_payload=self.inp,
            torsion_result=self.out.get("torsion"),
        )
        concrete_route_selected = bool(
            nominal.get("valid") is True and nominal.get("route") == "concrete"
        )
        self._h2("Utilization")
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd,c</sub>",
                      equation_key="shear.2023.utilisation",
                      subst=f"{_fmt(sh['v_ed'], 3)} / {_fmt(res['vrd_c'], 3)}",
                      result=(
                          f"{util_txt} (non-governing concrete-only context)"
                          if not concrete_route_selected
                          else f"{util_txt}  "
                               f"({'OK' if viz.util_ok(util) else 'EXCEEDED'})"
                      ))
        self._small(
            "The selected gamma<sub>V</sub> is defined in DS/EN "
            "1992-1-1:2023, 4.3.3 and Table 4.3 (NDP), and applied in "
            "8.2.2."
        )
        self._small('The 2023 tau<sub>Rd,c</sub> calculation uses the flexural design yield and the axial-force modification in Formula (8.31). Its aggregate-size parameter is:')
        self._small('d<sub>dg</sub> = 16 + D<sub>lower</sub>.')
        self._small('N<sub>Ed</sub> and M<sub>Ed</sub> include the locked-in tendon prestress effects in accordance with 8.2.1(8).')
        self._small('Tendons are assumed parallel to the member axis: cos beta = 1.')
        if sh.get("links") is not None:
            self._shear_links(sh)

    def _shear_directional_summary(self, aggregate, directions):
        rows = [["Direction", "V<sub>Ed</sub>", "V<sub>Rd</sub>",
                 "Component utilization", "Component status", "Overall shear status", "Tension face"]]
        for component in ("vx", "vy"):
            if component not in directions:
                continue
            item = directions[component]
            links = item.get("links") or {}
            selected_resistance = presentation.nominal_shear_resistance(
                item,
                links_selected=self.inp.get("shear_links") is True,
                input_payload=self.inp,
                torsion_result=self.out.get("torsion"),
            )
            resistance = selected_resistance.get("resistance")
            utilisation = selected_resistance.get("utilisation")
            selected_unavailable = (
                selected_resistance.get("valid") is not True
                or capacity.validated_signed_shear_demand(item) is None
            )
            applied_demand = presentation.shear_publication_signed_demand(
                self.inp, item,
            )
            retained_status = str(
                item.get("status")
                or item.get("assessment_status")
                or selected_resistance.get("status")
                or "NOT ASSESSED"
            ).upper()
            rows.append([
                "V<sub>x,Ed</sub>" if component == "vx" else "V<sub>y,Ed</sub>",
                (
                    "-" if applied_demand is None
                    else f"{_fmt(applied_demand, 3)} kN"
                ),
                (
                    "-" if selected_unavailable
                    else f"{_fmt(resistance, 3)} kN"
                ),
                "-" if selected_unavailable else _pct(utilisation),
                "NOT ASSESSED" if selected_unavailable else str(
                    selected_resistance.get("status") or "NOT ASSESSED"
                ).upper(),
                (
                    "NOT ASSESSED" if selected_unavailable
                    else retained_status
                ),
                viz.tension_face_label(item.get("tension_low", True), item.get("axis")),
            ])
        self._table(rows, [22 * mm, 25 * mm, 25 * mm, 25 * mm, 24 * mm, 25 * mm, 26 * mm])
        if aggregate.get("biaxial"):
            self._small(
                "V<sub>x</sub> and V<sub>y</sub> are calculated independently. "
                "Generic cross-direction interaction is not calculated and no "
                "aggregate shear verdict is issued."
            )

    def _shear(self):
        aggregate = self.out["shear"]
        aggregate_current, aggregate_reason = (
            presentation.shear_publication_input_is_current(
                self.inp,
                aggregate,
                plastic_result=self._plastic_publication_authority(),
                validate_directions=False,
                torsion_result=self.out.get("torsion"),
            )
        )
        if aggregate_current is not True:
            guidance = _result_reason(
                aggregate_reason,
                "shear",
                "report shear family authority",
            )
            self._case_heading("Shear resistance", "plastic")
            self._h2("Assessment")
            self._small(
                "NOT ASSESSED: "
                + _html_escape(guidance)
                + ". Recalculate the shear check before relying on resistance, "
                  "utilization or worked calculation values. No resistance, "
                  "utilization or PASS/FAIL verdict is published."
            )
            return
        directions = aggregate.get("directions") or {}
        selected = self._selected_family("shear", self.inp)
        critical = selected is not None

        def selected_failure_reason(item):
            if capacity.validated_signed_shear_demand(item) is None:
                return _result_reason(
                    "retained shear action evidence is unavailable",
                    "shear",
                    "report signed shear action",
                )
            selected_resistance = presentation.nominal_shear_resistance(
                item,
                links_selected=self.inp.get("shear_links") is True,
                input_payload=self.inp,
                torsion_result=self.out.get("torsion"),
            )
            if selected_resistance.get("valid") is not True:
                return _result_reason(
                    selected_resistance.get("reason"),
                    "shear",
                    "report nominal shear-resistance reason",
                )
            result = item.get("res") or {}
            if result.get("calculation_state") == "NOT ASSESSED":
                return _result_reason(
                    result.get("reason"),
                    "shear",
                    "report shear-geometry result reason",
                )
            return None

        if not directions:
            self._case_heading("Shear resistance", "plastic")
            links = aggregate.get("links") or {}
            selected_resistance = presentation.nominal_shear_resistance(
                aggregate,
                links_selected=self.inp.get("shear_links") is True,
                input_payload=self.inp,
                torsion_result=self.out.get("torsion"),
            )
            resistance = selected_resistance.get("resistance")
            utilisation = selected_resistance.get("utilisation")
            selected_unavailable = (
                selected_resistance.get("valid") is not True
                or capacity.validated_signed_shear_demand(aggregate) is None
            )
            applied_demand = presentation.shear_publication_signed_demand(
                self.inp, aggregate,
            )
            retained_status = str(
                aggregate.get("assessment_status")
                or selected_resistance.get("status")
                or "NOT ASSESSED"
            ).upper()
            component = aggregate.get("component") or (
                "vy" if aggregate.get("axis") == "x" else "vx"
            )
            action = "V<sub>y,Ed</sub>" if component == "vy" else "V<sub>x,Ed</sub>"
            self._table(
                [
                    ["Direction", "V<sub>Ed</sub>", "V<sub>Rd</sub>",
                     "Nominal utilization", "Overall shear status", "Tension face"],
                    [
                        action,
                        (
                            "-" if applied_demand is None
                            else f"{_fmt(applied_demand, 3)} kN"
                        ),
                        (
                            "-" if selected_unavailable
                            else f"{_fmt(resistance, 3)} kN"
                        ),
                        "-" if selected_unavailable else _pct(utilisation),
                        (
                            "NOT ASSESSED" if selected_unavailable
                            else retained_status
                        ),
                        viz.tension_face_label(
                            aggregate.get("tension_low", True),
                            aggregate.get("axis"),
                        ),
                    ],
                ],
                [25 * mm, 27 * mm, 27 * mm, 27 * mm, 28 * mm, 38 * mm],
            )
            self._small(
                "Nominal utilization compares the applied shear with its nominal resistance. "
                "The overall shear status also includes the applicable longitudinal-chord "
                "and detailing assessments."
            )
            if links.get("out_of_limits") or aggregate.get("out_of_limits"):
                self._small(
                    "The entered compression-strut range is outside the selected "
                    "method's permitted range. Angle-dependent design checks are "
                    "NOT ASSESSED; a separately applicable concrete-only shear "
                    "route remains identified where relevant."
                )
            if (reason := selected_failure_reason(aggregate)) is not None:
                self._small(
                    "NOT ASSESSED: "
                    + _html_escape(reason)
                    + ". No resistance, utilization or PASS/FAIL "
                      "verdict is published for this result."
                )
            if not critical:
                self._small(
                    "The complete shear worked example is published in Audit only for the "
                    "governing utilization across all plastic cases."
                )
                return
            self._small(
                "All calculated shear cases remain in the results overview. The "
                "complete shear worked example is published in Audit only for the governing "
                "utilization across all plastic cases."
            )
            self._h2(f"Governing direction: {action}" if self.profile.key == "Standard" else f"Governing worked example: {action}")
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
        self._shear_directional_summary(aggregate, directions)
        if any(
            (item.get("links") or {}).get("out_of_limits")
            or item.get("out_of_limits")
            for item in directions.values()
        ):
            self._small(
                "One or more entered directional compression-strut ranges are "
                "outside the selected method's permitted range. Their angle-"
                "dependent design checks are NOT ASSESSED."
            )
        for component in ("vx", "vy"):
            item = directions.get(component)
            if item is None:
                continue
            reason = selected_failure_reason(item)
            if reason is not None:
                label = "Vx,Ed" if component == "vx" else "Vy,Ed"
                self._small(
                    f"{label} NOT ASSESSED: "
                    + _html_escape(reason)
                    + ". No resistance, utilization or PASS/FAIL "
                      "verdict is published for this result."
                )
        if not critical:
            self._small(
                "The complete shear worked example is published in Audit only for the "
                "governing utilization across all plastic cases."
            )
            return
        self._small(
            "All calculated shear cases and directions remain in the results "
            "overview. The complete shear worked example is published in Audit only for "
            "the governing utilization across all plastic cases."
        )
        component = selected.get("component")
        if not isinstance(component, str) or component not in directions:
            self._h2("Worked shear calculation unavailable")
            self._small(
                "The selected governing shear direction is unavailable. "
                "Recalculate before issuing the report."
            )
            return
        label = "V<sub>x,Ed</sub>" if component == "vx" else "V<sub>y,Ed</sub>"
        self._h2(f"Governing direction: {label}" if self.profile.key == "Standard" else f"Governing worked example: {label}")
        self._shear_direction(
            directions[component], include_case_heading=False,
            component=component,
        )

    def _shear_face_tables(self, sh, component, combined_blocked, combined_blocker):
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
                           "Value / util.", "Status / outcome",
                           "Separate detailing"]]
        for key in ("shear", "vt", "minimum_reinforcement", "combined"):
            domain = governing_domains.get(key)
            if not domain:
                continue
            if key == "combined" and combined_blocked:
                governing_rows.append([
                    labels[key], "-", "-", "-", "NOT ASSESSED", "-",
                ])
                continue
            status = domain.get("status")
            if key == "minimum_reinforcement":
                status = presentation.minimum_reinforcement_screen_outcome(
                    domain
                )
            governing_rows.append([
                labels[key],
                viz.directional_face_label(component, domain.get("face")),
                _fmt(domain.get("cot"), 3),
                _pct(domain.get("util")),
                status,
                (
                    presentation.minimum_reinforcement_detailing_status(
                        domain
                    )
                    if key == "minimum_reinforcement" else "-"
                ),
            ])
        self._h2("Independent governing selections")
        self._table(
            governing_rows,
            [29 * mm, 30 * mm, 20 * mm, 25 * mm, 43 * mm, 33 * mm],
            font=6.5,
        )
        if combined_blocked:
            self._small(combined_blocker)

    def _shear_direction_introduction(self, sh, component, signed_action):
        component = component or sh.get("component") or (
            "vy" if sh["axis"] == "x" else "vx"
        )
        axis = ("Vy along y, paired with Mx" if component == "vy"
                else "Vx along x, paired with My")
        action = "V<sub>y,Ed</sub>" if component == "vy" else "V<sub>x,Ed</sub>"
        face = viz.tension_face_label(sh["tension_low"], sh["axis"])
        clause = "8.2.2" if sh.get("model_2023") else "6.2.2(1)"
        self._p(f"Design shear resistance V<sub>Rd,c</sub> applies to a member that does not require shear reinforcement (EN 1992-1-1 sec. {clause}).")
        self._p(f"Method: <b>{sh['method']}</b>. {axis}, with tension reinforcement on the {face} face.")
        self._small(f"Entered action: {action} = {_fmt(signed_action, 3)} kN.")
        self._small(f"Resistance and utilization use the action magnitude: |{action}| = {_fmt(abs(signed_action), 3)} kN.")
        if sh.get("face_mode") == "auto":
            self._small(
                "Automatic face selection uses the associated moment at the "
                "concrete centroid: "
                f"{_fmt(sh.get('associated_moment'), 3)} kNm."
            )
        return component, action, face

    def _shear_direction(self, sh, *, include_case_heading=True, component=None):
        res = sh["res"]
        combined_blocker = presentation.combined_bending_assessment_blocker(
            self.out,
            self.inp,
        )
        combined_blocked = combined_blocker is not None
        if include_case_heading:
            self._case_heading("Shear resistance", "plastic")
        signed_action = capacity.validated_signed_shear_demand(sh)
        if signed_action is None:
            self._h2("Assessment")
            self._small(
                "NOT ASSESSED: Recalculate the applied shear action and "
                "resistance before relying on this result. No resistance, "
                "utilization or PASS/FAIL verdict is published."
            )
            return
        input_current, input_reason = (
            presentation.shear_direction_publication_input_is_current(
                self.inp,
                sh,
                plastic_result=self._plastic_publication_authority(),
                torsion_result=self.out.get("torsion"),
            )
        )
        if input_current is not True:
            guidance = _result_reason(
                input_reason,
                "shear",
                "report shear current-input authority",
            )
            self._h2("Assessment")
            self._small(
                "NOT ASSESSED: "
                + _html_escape(guidance)
                + ". Recalculate the shear check before relying on resistance, "
                  "utilization or worked calculation values. No resistance, "
                  "utilization or PASS/FAIL verdict is published."
            )
            return
        component, action, face = self._shear_direction_introduction(
            sh, component, signed_action,
        )
        if res.get("calculation_state") == "NOT ASSESSED":
            reason = _result_reason(
                res.get("reason"),
                "shear",
                "report shear section-geometry reason",
            )
            geometry_record = sh.get("shear_geometry") or {}
            self._h2("Assessment")
            self._small(
                "NOT ASSESSED: "
                + _html_escape(reason)
                + ". No resistance, utilization or PASS/FAIL verdict is "
                  "published for this result."
            )
            self._table(
                [
                    ["Input", "Value"],
                    [
                        "Section form",
                        _html_escape(
                            str(geometry_record.get("section_form") or "-")
                        ),
                    ],
                    [
                        "Governing web width",
                        (
                            f"{_fmt(geometry_record.get('bw_mm'), 1)} mm"
                            if geometry_record.get("bw_mm") is not None
                            else "-"
                        ),
                    ],
                    [
                        "Web duct condition",
                        _html_escape(str(geometry_record.get("duct_case") or "-")),
                    ],
                    [
                        "Duct diameter sum",
                        (
                            f"{_fmt(geometry_record.get('duct_sum_mm'), 1)} mm"
                            if geometry_record.get("duct_sum_mm") is not None
                            else "-"
                        ),
                    ],
                ],
                [65 * mm, 85 * mm],
            )
            return
        if not res["valid"]:
            self._small("Warning: V<sub>Rd,c</sub> is zero -- no tension "
                        "reinforcement on the chosen face, or a zero effective depth "
                        "/ web width.")
        face_evidence_current, _face_evidence_reason = (
            presentation.directional_shear_publication_evidence_is_current(
                self.inp,
                sh,
                plastic_result=self._plastic_publication_authority(),
            )
        )
        if sh.get("both_faces_evaluated") and face_evidence_current:
            self._shear_face_tables(sh, component, combined_blocked, combined_blocker)
        elif sh.get("both_faces_evaluated"):
            self._h2("Face-specific shear comparison")
            self._small(
                "NOT ASSESSED: Recalculate before relying on either mandatory "
                "face or its governing selection. No face-specific resistance, "
                "utilization or PASS/FAIL verdict is published."
            )
        geometry_basis = presentation.shear_geometry_basis(
            self.inp, sh, torsion_result=self.out.get("torsion"),
        )
        z_geometry = geometry_basis["z_mm"]
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
                    # Full depth and lever-arm provenance follows the figure.
                    # Keep its dimension callouts short at the printed size.
                    d_note=None,
                    z_note=None,
                    title=f"{action} geometry - {face} tension",
                ),
                170,
                120,
            )
            self._small(
                "Star markers are the bars included in A<sub>sl</sub>; the dotted "
                "line is the gross-section centroid used as the selection boundary."
            )
        self._small(_html_escape(geometry_basis["statement"]))
        shear_geometry = sh.get("shear_geometry") or {}
        self._small(
            "Shear section form: "
            + _html_escape(
                str(
                    shear_geometry.get("resolved_form")
                    or shear_geometry.get("section_form")
                    or "-"
                )
            )
            + ". Web duct condition: "
            + _html_escape(str(shear_geometry.get("duct_case") or "-"))
            + "."
        )
        if float(shear_geometry.get("duct_factor_concrete") or 0.0) > 0.0:
            self._small(
                "The no-links check uses the retained nominal web width after "
                f"the duct allowance k<sub>duct</sub> = "
                f"{_fmt(shear_geometry.get('duct_factor_concrete'), 2)}."
            )
        if sh.get("model_2023"):
            self._shear_2023(sh, res)
            return
        self._shear_2005(sh, res)

    def _shear_2005(self, sh, res):
        bw_src = "user input" if sh["bw_user"] else "derived (minimum solid width)"
        calculation_bw = float(res.get("bw", sh["bw"]))
        if not math.isclose(
            calculation_bw, float(sh["bw"]), rel_tol=0.0, abs_tol=1e-9
        ):
            bw_src = f"nominal after duct allowance; physical bw = {_fmt(sh['bw'], 1)} mm"
        fck = sh["fck"]
        k1 = res["k1"]
        rows = [["Quantity", "Symbol", "Value"],
                ["Effective depth", "d", f"{_fmt(sh['d'], 1)} mm"],
                ["Web width", "b<sub>w</sub>",
                 f"{_fmt(calculation_bw, 1)} mm ({bw_src})"],
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
                  f"{_fmt(calculation_bw, 1)} &#183; {_fmt(sh['d'], 1)} / 1000",
            result=f"V<sub>Rd,c</sub> = {_fmt(res['vrd_c'], 3)} kN")
        nominal = presentation.nominal_shear_resistance(
            sh,
            links_selected=self.inp.get("shear_links") is True,
            input_payload=self.inp,
            torsion_result=self.out.get("torsion"),
        )
        self._shear_2005_utilisation(sh, res, nominal)
        self._small('A<sub>sl</sub> is the tension reinforcement on the selected face. Full anchorage is assumed for a distance of at least l<sub>bd</sub> + d beyond the section.')
        self._small('sigma<sub>cp</sub> uses the plastic axial force plus tendon precompression, where present.')
        self._small('If V<sub>Ed</sub> &gt; V<sub>Rd,c</sub>, the section requires designed shear reinforcement.')
        if sh.get("links") is not None:
            self._shear_links(sh)

    def _shear_2005_utilisation(self, sh, res, nominal):
        util = sh["util"]
        util_txt = _pct(util)
        concrete_route_selected = bool(
            nominal.get("valid") is True and nominal.get("route") == "concrete"
        )
        self._h2("Utilization")
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd,c</sub>",
                      equation_key="shear.2005.utilisation",
                      subst=f"{_fmt(sh['v_ed'], 3)} / {_fmt(res['vrd_c'], 3)}",
                      result=(
                          f"{util_txt} (non-governing concrete-only context)"
                          if not concrete_route_selected
                          else f"{util_txt}  "
                               f"({'OK' if viz.util_ok(util) else 'EXCEEDED'})"
                      ))

    def _shear_link_terms_available(self, lk):
        retained_angle_fields = {
            "cot", "tan", "theta_deg", "cot_min", "cot_max",
            "cot_unconstrained", "angle_selection",
        }
        if not retained_angle_fields.issubset(lk):
            self._small(
                "Worked shear calculation unavailable: the selected strut-angle "
                "terms are missing. Recalculate before issuing the report."
            )
            return False
        return True

    def _shear_links(self, sh):
        links = sh["links"]
        link_mapping = links if isinstance(links, dict) else {}
        lk = link_mapping.get("res")
        self._h2("Shear reinforcement (links)")
        model_2023 = bool(link_mapping.get("model_2023"))
        clause = "8.2.3" if model_2023 else "6.2.3"
        nominal = presentation.nominal_shear_resistance(
            sh,
            links_selected=self.inp.get("shear_links") is True,
            input_payload=self.inp,
            torsion_result=self.out.get("torsion"),
        )
        links_are_nominal = bool(
            nominal.get("valid") is True and nominal.get("route") == "links"
        )
        transverse = self.out.get("transverse_reinforcement")
        if not self.inp.get("transverse_detailing_on"):
            detailing_status = "NOT RUN"
        elif isinstance(transverse, dict):
            detailing_status = str(
                transverse.get("status") or "NOT ASSESSED"
            ).upper()
        else:
            detailing_status = "NOT ASSESSED"
        self._small(
            "Separate link detailing assessment: "
            + _html_escape(detailing_status)
            + "."
        )
        if not isinstance(lk, dict) or lk.get("valid") is not True:
            reason = _result_reason(
                link_mapping.get("assessment_reason")
                or (lk or {}).get("reason")
                or "invalid reinforced-shear input",
                "shear",
                "report reinforced-shear reason",
            )
            self._small(
                "NOT ASSESSED: "
                + _html_escape(reason)
                + ". No link lever arm, resistance, utilization or PASS/FAIL "
                  "verdict is published for this result."
            )
            angle_applicability = (lk or {}).get(
                "angle_applicability"
            ) or link_mapping.get(
                "angle_applicability"
            )
            public_angle = (
                presentation.strut_angle_applicability_publication(
                    angle_applicability
                )
            )
            if public_angle is not None:
                self._small(f"Requested cot theta: {_fmt(public_angle['requested_min'], 3)} to {_fmt(public_angle['requested_max'], 3)}.")
                self._small("Method: " + _html_escape(public_angle["method"]) + ".")
                self._small(f"Permitted cot theta: {_fmt(public_angle['permitted_min'], 3)} to {_fmt(public_angle['permitted_max'], 3)}.")
            return
        provided_link = presentation.provided_link_publication_assessment(
            self.inp,
            sh,
            torsion_result=self.out.get("torsion"),
        )
        if provided_link.valid is not True:
            reason = _result_reason(
                provided_link.reason,
                "shear",
                "report provided-link resistance assessment",
            )
            self._small(
                "NOT ASSESSED: "
                + _html_escape(reason)
                + ". No link resistance, utilization or PASS/FAIL verdict is "
                  "published until the reinforced-shear result is recalculated."
            )
            return
        req = ("required (V<sub>Ed</sub> &gt; V<sub>Rd,c</sub>)" if nominal.get("links_required") is True
               else "not strictly required (V<sub>Ed</sub> &#8804; V<sub>Rd,c</sub>); "
                    "minimum reinforcement rules still apply")
        if links_are_nominal:
            self._p(f"The selected nominal resistance uses the compression-field model (EN 1992-1-1 sec. {clause}):")
            self._p("V<sub>Rd</sub> = min(V<sub>Rd,s</sub>, V<sub>Rd,max</sub>).")
            self._p(f"For this V<sub>Ed</sub>, links are {req}.")
        else:
            self._p('The provided-link resistance is an independent resistance check. It does not govern the selected nominal resistance for this case.')
            self._p('The concrete route supplies the selected nominal resistance because:')
            self._p('|V<sub>Ed</sub>| &#8804; V<sub>Rd,c</sub>.')
            self._p('Minimum reinforcement and link detailing are assessed separately.')
        if not self._shear_link_terms_available(lk):
            return
        shear_geometry = links.get("shear_geometry") or {}
        effective_asw_over_s = links.get(
            "effective_asw_over_s", links.get("asw_over_s")
        )
        links_bw = lk.get("bw", sh.get("bw"))
        rows = [["Quantity", "Symbol", "Value"],
                ["Links", "n x phi / s",
                 f"{_fmt(links['legs'], 0)} x {_fmt(links['dia'], 0)} / "
                 f"{_fmt(links['s'], 0)} mm"],
                ["Gross link area / spacing", "A<sub>sw</sub>/s",
                 f"{_fmt(links['asw_over_s'], 5)} mm<sup>2</sup>/mm"],
                ["Effective link area / spacing", "A<sub>sw,eff</sub>/s",
                 f"{_fmt(effective_asw_over_s, 5)} mm<sup>2</sup>/mm"],
                ["Link-area factor", "A<sub>sw,eff</sub>/A<sub>sw</sub>",
                 _fmt(links.get("asw_factor"), 5)],
                ["Physical web width", "b<sub>w</sub>",
                 f"{_fmt(shear_geometry.get('bw_mm'), 1)} mm"],
                ["Compression-field web width", "b<sub>w,nom</sub>",
                 f"{_fmt(links_bw, 1)} mm"],
                ["Section form", "-",
                 _html_escape(str(shear_geometry.get("resolved_form") or "-"))],
                ["Web duct condition", "-",
                 _html_escape(str(shear_geometry.get("duct_case") or "-"))],
                ["Duct diameter sum", "sum phi<sub>duct</sub>",
                 f"{_fmt(shear_geometry.get('duct_sum_mm'), 1)} mm"],
                ["Duct allowance factor", "k<sub>duct</sub>",
                 _fmt(shear_geometry.get("duct_factor_links"), 2)],
                ["Design link yield", "f<sub>ywd</sub>", f"{_fmt(lk['fywd'], 1)} MPa"],
                ["Calculated links arm", "z",
                 f"{_fmt(lk['z'], 1)} mm "
                 f"({presentation.shear_link_arm_source_label(links.get('z_source'))})"],
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
        if not math.isclose(
            float(links.get("asw_factor", 1.0)),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            self._small(
                "The selected section-form factor is applied to A<sub>sw</sub> "
                "before the links resistance is calculated."
            )
        if float(shear_geometry.get("duct_factor_links") or 0.0) > 0.0:
            self._small(
                "The compression-field check uses the retained nominal web width "
                "after the selected duct allowance."
            )
        shared_angle = links.get("member_angle_selection") or {}
        if shared_angle:
            labels = tuple(shared_angle.get("objective_labels") or ())
            governing = tuple(shared_angle.get("governing_objectives") or ())
            self._small(f"Selected common member angle: cot theta = {_fmt(shared_angle.get('cot'), 4)}.")
            self._small(f"Selection interval: [{_fmt(shared_angle.get('cot_min'), 3)}, {_fmt(shared_angle.get('cot_max'), 3)}].")
            self._small(f"Governing checks: {_html_escape(', '.join(governing) or 'not identified')}.")
            self._small(f"Checks considered: {_html_escape(', '.join(labels) or 'the active checks')}.")
        else:
            self._small(f"Unconstrained resistance angle: cot theta = {_fmt(lk['cot_unconstrained'], 4)}.")
            self._small(f"Entered interval: [{_fmt(lk['cot_min'], 3)}, {_fmt(lk['cot_max'], 3)}].")
            self._small(f"Selected angle: cot theta = {_fmt(lk['cot'], 4)} ({_html_escape(lk['angle_selection'])}).")
        if self.figures:
            self._fig(viz.truss_figure(lk["theta_deg"], lk["z"], links["legs"],
                                       links["dia"], links["s"]), 130, 80)
        if model_2023:
            self._formula(
                "tau<sub>Rd,sy</sub> = rho<sub>w</sub> f<sub>ywd</sub> cot theta",
                equation_key="shear.links.tau-yield",
                ref="DS/EN 1992-1-1:2023 Formula (8.42)",
                subst=f"{_fmt(lk['rho_w'], 5)} &#183; {_fmt(lk['fywd'], 1)} "
                      f"&#183; {_fmt(lk['cot'], 3)}",
                result=f"tau<sub>Rd,sy</sub> = {_fmt(lk['tau_rd_sy'], 3)} MPa")
            self._formula(
                "sigma<sub>cd</sub> = tau<sub>Ed</sub>"
                "(cot theta + tan theta) &#8804; nu f<sub>cd</sub>",
                equation_key="shear.links.sigma-field",
                ref="DS/EN 1992-1-1:2023 Formula (8.44)",
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
                subst=f"{_fmt(lk['tau_rd_sy'], 3)} &#183; {_fmt(links_bw, 1)} "
                      f"&#183; {_fmt(lk['z'], 1)} / 1000",
                result=f"V<sub>Rd,s</sub> = {_fmt(lk['vrd_s'], 3)} kN")
            self._formula(
                "V<sub>Rd,max</sub> = nu f<sub>cd</sub> b<sub>w</sub> z / "
                "(cot theta + tan theta)",
                equation_key="shear.links.vrdmax",
                equation_variant="2023",
                references=("shear.links.sigma-field",),
                subst=f"{_fmt(lk['nu_fcd'], 3)} &#183; {_fmt(links_bw, 1)} "
                      f"&#183; {_fmt(lk['z'], 1)} / "
                      f"({_fmt(lk['cot'], 3)} + {_fmt(lk['tan'], 3)}) / 1000",
                result=f"V<sub>Rd,max</sub> = {_fmt(lk['vrd_max'], 3)} kN")
        else:
            self._formula(
                "V<sub>Rd,s</sub> = (A<sub>sw</sub>/s) z f<sub>ywd</sub> cot theta",
                equation_key="shear.links.vrds",
                equation_variant="2005",
                ref="EN 1992-1-1 (6.8)",
                subst=f"{_fmt(effective_asw_over_s, 4)} &#183; {_fmt(lk['z'], 1)} "
                      f"&#183; {_fmt(lk['fywd'], 1)} &#183; {_fmt(lk['cot'], 3)} / 1000",
                result=f"V<sub>Rd,s</sub> = {_fmt(lk['vrd_s'], 3)} kN")
            self._formula(
                "V<sub>Rd,max</sub> = alpha<sub>cw</sub> b<sub>w</sub> z "
                "nu<sub>1</sub> f<sub>cd</sub> / (cot theta + tan theta)",
                equation_key="shear.links.vrdmax",
                equation_variant="2005",
                ref="EN 1992-1-1 (6.9)",
                subst=f"{_fmt(lk['alpha_cw'], 3)} &#183; {_fmt(links_bw, 1)} &#183; "
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
                   f"(governed by {_report_resistance_governing_label(lk['governs'])})")
        util = provided_link.utilisation
        util_txt = _pct(util)
        verdict = provided_link.status
        self._formula("|V<sub>Ed</sub>| / V<sub>Rd</sub>",
                      equation_key="shear.links.utilisation",
                      references=("shear.links.vrd",),
                      subst=f"{_fmt(sh['v_ed'], 3)} / {_fmt(lk['vrd'], 3)}",
                      result=(
                          f"{util_txt}  ({verdict})"
                          if links_are_nominal
                          else f"{util_txt} ({verdict}; non-governing comparison)"
                      ))
        if links.get("theta_mode") == "utilisation":
            shared_note = (
                "shared with torsion when enabled"
                if model_2023
                else "shared with torsion when enabled under 6.3.2(2)"
            )
            angle_note = (f"The member strut angle is {shared_note}. "
                          "The angle is selected within the limits to minimize the governing utilization. "
                          "A flatter strut reduces the stirrup demand but increases the crushing demand and longitudinal chord tension. "
                          "Thus, the selected angle depends on the applied actions.")
        else:
            angle_note = ("The strut angle is auto-optimised within the bounds to "
                          "maximise V<sub>Rd</sub>.")
        chord_publication = (
            presentation.provided_link_longitudinal_publication_assessment(
                self.inp,
                sh,
                torsion_result=self.out.get("torsion"),
            )
        )
        chord_assessment = chord_publication.get("assessment") or {
            "status": "NOT ASSESSED",
            "ok": None,
            "util": None,
            "reason": "longitudinal chord evidence is unavailable",
            "coverage_complete": False,
            "governing": None,
        }
        if chord_publication.get("valid") is not True:
            self._h2("Longitudinal chord assessment")
            self._small(
                "NOT ASSESSED: Recalculate the shear and longitudinal chord "
                "checks before using their worked evidence."
            )
        if not links_are_nominal:
            self._small(angle_note)
            self._small("The provided links do not replace the applicable concrete resistance route. Thus, no longitudinal shear force is applied in the nominal check.")
            chord_status = str(
                chord_assessment.get("status") or "NOT APPLICABLE"
            ).upper()
            if chord_status not in {"PASS", "FAIL", "NOT ASSESSED"}:
                return
        elif model_2023:
            self._small(angle_note)
            self._small("The additional longitudinal force is (8.50):")
            self._small("N<sub>Vd</sub> = |V<sub>Ed</sub>| cot theta = "
                        f"{_fmt(links['longitudinal_shear_force'], 1)} kN.")
            self._small("This force is applied to both flexural chords with Formulae (8.51) and (8.52). The support/load-specific relief in (8.53) is not credited.")
        else:
            self._small(angle_note)
            self._small("The shear adds longitudinal tension (6.18):")
            self._small("&#916;F<sub>td</sub> = 0.5 V<sub>Ed</sub> cot theta = "
                        f"{_fmt(links['longitudinal_shear_force'], 1)} kN.")
        # Longitudinal chord under M + V (+ T), at the member strut angle -- the
        # same check the combined section shows; printed here so a shear + bending
        # run without torsion still documents it.
        ch = chord_publication.get("governing")
        if chord_assessment.get("status") == "NOT APPLICABLE":
            ch = None
        if ch is not None and ch.get("valid"):
            self._h2("Longitudinal chord: bending + shear"
                     + (" + torsion" if ch.get("has_torsion") else "") + " tension")
            candidates = chord_publication.get("candidates") or ()
            if (self.figures and chord_publication.get("valid") is True
                    and chord_assessment.get("coverage_complete") is True and candidates):
                try:
                    figure = report_diagrams.chord_comparison_figure(candidates)
                except report_diagrams.DiagramUnavailable as error:
                    self._small("Chord comparison diagram unavailable. " + _html_escape(str(error)))
                else:
                    self._fig(figure, 170, 95, caption=(
                        "Concurrent longitudinal chord demand and conditional bending capacity at each retained physical face. "
                        "The capacity includes the applied axial force and the moment about the other axis."
                    ))
            vv = _demand_resistance_verdict(ch["ok"])
            coverage = ch.get("off_not_evaluated")
            face = viz.tension_face_label(
                ch.get("tension_low", True), ch.get("axis")
            )
            if model_2023:
                chord_formula = (
                    "M<sub>Ed,total</sub> = max(M<sub>face</sub> + "
                    "N<sub>Vd</sub>&#183;z, 0) + "
                    "F<sub>td,T</sub>&#183;z/2"
                )
                chord_ref = "DS/EN 1992-1-1:2023, 8.2.3(8), Formulae (8.50)-(8.52)"
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
                subst=(
                    f"max({_fmt(ch.get('face_m_ed_signed', ch['m_ed']), 1)} + "
                    f"{_fmt(ch['mv'], 1)}, 0) + {_fmt(ch['mt'], 1)} kNm "
                    f" (z = {_fmt(ch['z'], 3)} m)"
                    if model_2023
                    else f"{_fmt(ch['m_ed'], 1)} + {_fmt(ch['mv'], 1)} + "
                         f"{_fmt(ch['mt'], 1)} kNm  (z = {_fmt(ch['z'], 3)} m)"
                ),
                result=f"M<sub>Ed,total</sub> = {_fmt(ch['m_total'], 1)} kNm")
            fallback = chord_publication.get("fallback")
            fell_back = fallback is not None
            chord_status = str(
                chord_assessment.get("status") or "NOT ASSESSED"
            ).upper()
            assessment_complete = chord_status in {"PASS", "FAIL"}
            if not assessment_complete:
                verdict_suffix = (
                    "  (NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE)"
                )
            else:
                verdict_suffix = f"  ({vv})"
            self._formula(
                "M<sub>Ed,total</sub> / M<sub>Rd</sub>",
                equation_key="shear.chord.utilisation",
                references=("shear.chord.demand",),
                subst=f"{_fmt(ch['m_total'], 1)} / {_fmt(ch['m_rd'], 1)}",
                result=f"utilisation = {_pct(ch['util'])}{verdict_suffix}")
            if model_2023:
                face_desc = (
                    f"the flexural tension chord ({face}), Formula (8.51)"
                    if ch.get("chord_role") == "flexural_tension"
                    else f"the flexural compression chord ({face}), Formula "
                         "(8.52), after bending-compression relief"
                )
            else:
                face_desc = (
                    f"the shear tension face ({face})"
                    if ch.get("gets_shift", True)
                    else f"the shear compression face ({face}), with torsion "
                         "tension and bending relief"
                )
            notes = [f"Tension chord: {face_desc}. M<sub>Rd</sub> "
                     + _report_chord_mrd_label(ch["axis"], ch.get("m_off", 0.0), ch.get("conditional", True)) + "."]
            if ch.get("theta_mode") == "utilisation":
                demand_word = "uncapped" if model_2023 else "capped"
                notes.append(f"This {demand_word} demand is part of the strut-angle objective. The selected angle moves away from the interval boundary when the chord would otherwise govern.")
            if model_2023:
                notes.append("The acting axial force is already included in the conditional bending resistance for each face.")
            if fell_back:
                fallback_axis = fallback.get("axis", "?")
                fallback_face = "negative" if fallback.get("tension_low", True) else "positive"
                notes.append(f"The required {fallback_axis}-axis {fallback_face} face uses a pure-axis substitute because its conditional capacity solve did not converge.")
                notes.append("The complete chord check can be optimistic. Use the combined &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check.")
            if coverage == "subdivided":
                notes.append("For this compound section, the torsion longitudinal steel is calculated for each sub-tube. The torsion share of the off-axis chord is not evaluated here.")
                notes.append("Use the combined &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check.")
            elif coverage == "circular_geometry":
                notes.append("The fitted-section lever arm for the circular off-axis chord is not established.")
                notes.append("Before you use the longitudinal shear assessment, enter the following values for both directions.")
                notes.append("Enter the governing web width, hoop diameter and fitted-section lever arm.")
            elif coverage == "not_solved":
                notes.append("At least one chord face that carries the torsion share could not be evaluated. A conditional solve failed, or a face has no tension steel.")
                notes.append("These faces are not checked. The reported governing chord can therefore be less critical than an unchecked face.")
                notes.append("Use the combined &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check.")
            for note in notes:
                self._small(note)
            if model_2023:
                self._shear_2023_chord_faces(
                    chord_publication, chord_assessment, chord_status,
                )
            self._chord_off_block(
                chord_publication.get("chord_off"),
                assessment_complete=assessment_complete,
            )
        elif model_2023 and isinstance(chord_assessment, Mapping):
            self._shear_2023_missing_chords(chord_assessment)

    def _shear_2023_chord_faces(self, chord_publication, chord_assessment, chord_status):
        """Render the separate-shear face table after caller validation."""
        rows = [[
            "Face", "Chord", "Formula", "M<sub>face</sub>",
            "N<sub>Vd</sub>z", "M<sub>Ed,total</sub>",
            "M<sub>Rd</sub>", "Utilization", "Status",
        ]]
        for candidate in chord_publication.get("candidates") or ():
            if candidate.get("role") != "shear_axis":
                continue
            rows.append([
                viz.tension_face_label(
                    candidate.get("tension_low", True),
                    candidate.get("axis"),
                ),
                (
                    "Flexural tension"
                    if candidate.get("chord_role") == "flexural_tension"
                    else "Flexural compression"
                ),
                f"({candidate.get('chord_formula', '-')})",
                f"{_fmt(candidate.get('face_m_ed_signed'), 1)} kNm",
                f"{_fmt(candidate.get('mv'), 1)} kNm",
                f"{_fmt(candidate.get('m_total'), 1)} kNm",
                f"{_fmt(candidate.get('m_rd'), 1)} kNm",
                _pct(candidate.get("util")),
                str(candidate.get("status") or "NOT ASSESSED"),
            ])
        if len(rows) > 1:
            self._h2("Required 2023 longitudinal chord faces")
            self._table(
                rows,
                [16 * mm, 23 * mm, 17 * mm, 18 * mm, 18 * mm,
                 20 * mm, 18 * mm, 20 * mm, 16 * mm],
                font=6.7,
            )
        self._small(
            "Longitudinal chord assessment: "
            f"{chord_status}. "
            + presentation.result_reason(
                chord_assessment.get("reason"),
                "shear",
                context="report longitudinal chord assessment",
            )
        )

    def _shear_2023_missing_chords(self, chord_assessment):
        chord_status = str(
            chord_assessment.get("status") or "NOT ASSESSED"
        ).upper()
        self._h2("Required 2023 longitudinal chord faces")
        self._small(
            "Longitudinal chord assessment: "
            f"{chord_status}. "
            + presentation.result_reason(
                chord_assessment.get("reason"),
                "shear",
                context="report longitudinal chord assessment",
            )
        )


    def _combined_chord_diagram(self, c, longitudinal):
        """Publish only complete, current chord evidence owned by this case."""
        if not self.figures or self.inp.get("_report_case_current") is False:
            return
        aggregate = self.out.get("combined")
        directions = aggregate.get("directions") if isinstance(aggregate, Mapping) else None
        owned = c is aggregate or (
            isinstance(directions, Mapping)
            and type(c.get("component")) is str
            and directions.get(c["component"]) is c
        )
        assessment = longitudinal.get("assessment") or {}
        if not (owned and longitudinal.get("chord_status") in {"PASS", "FAIL"}
                and assessment.get("chord_coverage_complete") is True
                and presentation.combined_publication_evidence_is_current(
                    self.inp, self.out)[0]):
            return
        candidates = c.get("longitudinal_candidates")
        try:
            figure = report_diagrams.chord_comparison_figure(candidates)
        except report_diagrams.DiagramUnavailable as error:
            self._small("Chord comparison diagram unavailable. " + _html_escape(str(error)))
            return
        concrete = next(item for item in presentation.combined_physical_components(c)
                        if item["key"] == "concrete")
        case_id = presentation.action_set(self.inp, "plastic")["id"] or "ID NOT SET"
        context = "Case " + str(case_id)
        component = c.get("component")
        component_label = {"vx": "Vx", "vy": "Vy", "x": "x", "y": "y",
                           "Vx": "Vx", "Vy": "Vy"}.get(component)
        if component_label:
            context += "; shear component " + component_label
        if concrete.get("angle_valid") is True:
            context += "; member strut angle " + _fmt(concrete.get("theta_deg"), 2) + " degrees"
        self._fig(figure, 170, 95, caption=(
            context + ". Concurrent chord demand and conditional bending capacity at each retained physical face. "
            "The capacity includes the applied axial force and the moment about the other axis."
        ))
        self._small("Each demand represents longitudinal tension at the named physical face, expressed as an equivalent moment. "
                    "A zero demand indicates no net tension demand for that chord comparison.")

    def _combined_base_en_direction(self, c):
        """Publish Base-EN physical interactions without a DK aggregate."""

        c = c if isinstance(c, Mapping) else {}
        if not c.get("valid"):
            missing = [
                label
                for key, label in (
                    ("have_m", "bending"),
                    ("have_v", "shear"),
                    ("have_t", "torsion"),
                )
                if key in c and not c.get(key)
            ]
            reason = (
                _html_escape(_result_reason(
                    c["reason"],
                    "combined",
                    "Base EN combined prerequisite reason",
                ))
                if c.get("reason")
                else "Complete the required component checks and recalculate"
            )
            self._small(
                "Base-EN combined components are NOT ASSESSED"
                + (": missing " + ", ".join(missing) if missing else "")
                + ". "
                + reason
                + "."
            )
            return
        self._p(
            "The shared edition is <b>EN 1992-1-1:2005</b>. Sector reports "
            "the supported V+T concrete, closed-stirrup and longitudinal-"
            "reinforcement checks separately. No additional aggregate "
            "interaction verdict is published for this route."
        )
        physical_components = presentation.combined_physical_components(c)
        physical_by_key = {
            component["key"]: component for component in physical_components
        }
        component_rows = [["Component", "Utilization", "Status", "Engineering note"]]
        component_rows.extend([
            [
                component["label"],
                _pct(component["util"]),
                component["status"],
                component["note"],
            ]
            for component in physical_components
        ])
        self._h2("Supported Base-EN physical interactions")
        self._table(
            component_rows,
            [48 * mm, 28 * mm, 29 * mm, 65 * mm],
            font=7.5,
        )
        self._small(
            "These are independent physical checks; no additional Base-EN "
            "aggregate interaction verdict is published."
        )
        cr = c.get("crushing")
        concrete = physical_by_key["concrete"]
        cr_status = concrete["status"]
        if isinstance(cr, Mapping) and cr_status in {"PASS", "FAIL"}:
            self._h2("Concrete compression strut (6.29)")
            self._formula(
                "T<sub>Ed</sub>/T<sub>Rd,max</sub> + "
                "V<sub>Ed</sub>/V<sub>Rd,max</sub>",
                equation_key="combined.crushing.interaction",
                ref="EN 1992-1-1 (6.29)",
                subst=(
                    f"{_fmt(cr['t_ed'], 3)}/{_fmt(cr['trd_max'], 3)} + "
                    f"{_fmt(cr['v_ed'], 3)}/{_fmt(cr['vrd_max'], 3)}"
                ),
                result=(
                    f"{_pct(concrete['util'])}  "
                    f"({_demand_resistance_verdict(cr_status == 'PASS')})"
                ),
            )
            self._small(
                f"Common member angle cot theta = {_fmt(cr.get('cot'), 3)}."
            )
        elif isinstance(cr, Mapping):
            self._h2("Concrete compression strut (6.29)")
            self._small(
                "NOT ASSESSED: " + _html_escape(concrete["note"]) + "."
            )
        tr = c.get("transverse")
        stirrup = physical_by_key["stirrup"]
        if (
            isinstance(tr, Mapping)
            and stirrup["status"] in {"PASS", "FAIL"}
        ):
            self._h2("Shared closed stirrup: shear + torsion")
            self._table(
                [
                    ["Shear share", "Torsion share", "Utilization", "Status"],
                    [
                        _pct(tr.get("shear_fraction")),
                        _pct(tr.get("torsion_fraction")),
                        _pct(tr.get("u_stirrup")),
                        (
                            stirrup["status"]
                        ),
                    ],
                ],
                [40 * mm, 40 * mm, 40 * mm, 40 * mm],
            )
        elif isinstance(tr, Mapping):
            self._h2("Shared closed stirrup: shear + torsion")
            self._small(
                "NOT ASSESSED: complete the shared closed-stirrup calculation "
                "and recalculate."
            )
        longitudinal = next(
            component
            for component in physical_components
            if component["key"] == "longitudinal"
        )
        lg = longitudinal.get("governing")
        self._h2("Longitudinal reinforcement: combined M + V + T tension chord")
        if isinstance(lg, Mapping) and lg.get("valid"):
            self._combined_chord_diagram(c, longitudinal)
            self._table(
                [
                    [
                        "M<sub>Ed</sub>", "Shear shift", "Torsion share", "M<sub>Ed,total</sub>",
                        "M<sub>Rd</sub>", "Chord utilization",
                    ],
                    [
                        f"{_fmt(lg.get('m_ed'), 3)} kNm",
                        f"{_fmt(lg.get('mv'), 3)} kNm",
                        f"{_fmt(lg.get('mt'), 3)} kNm",
                        f"{_fmt(lg.get('m_total'), 3)} kNm",
                        f"{_fmt(lg.get('m_rd'), 3)} kNm",
                        f"{_pct(longitudinal['chord_util'])} "
                        f"{longitudinal['chord_status']}",
                    ],
                ],
                [27 * mm, 27 * mm, 27 * mm, 29 * mm, 27 * mm, 23 * mm],
                font=7.2,
                caption='Longitudinal chord demand and conditional resistance',
            )
            self._small(viz.chord_angle_note(
                lg.get("theta_mode"),
                angle_valid=concrete.get("angle_valid") is True,
            ))
            self._small(
                "Overall longitudinal reinforcement assessment: "
                f"{_pct(longitudinal['util'])} {longitudinal['status']}. "
                "Governing check: "
                f"{_html_escape(str(longitudinal.get('governing_mechanism') or '-'))}."
            )
        else:
            self._small(
                "Longitudinal chord assessment: "
                f"{longitudinal['status']}. "
                f"{_html_escape(longitudinal['note'])}."
            )

    def _combined_base_en(self, aggregate):
        """Publish Base-EN uniaxial/directional component evidence."""

        self._case_heading(
            "Combined bending + shear + torsion (M-V-T)", "plastic"
        )
        blocker = presentation.combined_bending_assessment_blocker(
            self.out,
            self.inp,
        )
        if blocker is not None:
            self._small("Combined Base-EN components: NOT ASSESSED. " + blocker)
            return
        self._combined_base_en_components(aggregate)

    def _combined_base_en_components(self, aggregate):
        if aggregate.get("biaxial") is True:
            retained = presentation.base_en_combined_direction_items(aggregate)
            if retained is None:
                self._small(
                    "Base-EN directional combined components are NOT ASSESSED. "
                    "Complete both Vx+T and Vy+T calculations, then recalculate."
                )
                return
            directions = dict(retained)
            self._small(
                "V<sub>x,Ed</sub> + T<sub>Ed</sub> and V<sub>y,Ed</sub> + "
                "T<sub>Ed</sub> are reported independently. No simultaneous "
                "V<sub>x</sub> + V<sub>y</sub> + T verdict is inferred."
            )
            rows = [[
                "Direction", "Concrete strut", "Closed stirrup",
                "Longitudinal", "Governing face", "cot theta",
            ]]
            for component in ("vx", "vy"):
                item = directions[component]
                physical = {
                    value["key"]: value
                    for value in presentation.combined_physical_components(item)
                }
                rows.append([
                    "Vx+T" if component == "vx" else "Vy+T",
                    physical["concrete"]["status"],
                    physical["stirrup"]["status"],
                    physical["longitudinal"]["status"],
                    viz.directional_face_label(
                        component, item.get("governing_face")
                    ),
                    _fmt(item.get("governing_cot"), 3),
                ])
            self._table(
                rows,
                [24 * mm, 27 * mm, 27 * mm, 27 * mm, 36 * mm, 22 * mm],
                font=6.8,
            )
            selected = self._selected_family("combined", self.inp)
            selected_component = (
                selected.get("component") if isinstance(selected, Mapping) else None
            )
            if selected_component not in directions:
                selected_component = next(
                    (
                        component
                        for component, item in directions.items()
                        if item.get("valid") is not True
                        or any(
                            physical["status"] not in {"PASS", "FAIL"}
                            or not self._retained_utilisation_available(
                                physical["util"]
                            )
                            for physical in (
                                presentation.combined_physical_components(item)
                            )
                        )
                    ),
                    next(iter(directions)),
                )
            label = "Vx+T" if selected_component == "vx" else "Vy+T"
            self._h2(f"Base-EN directional result: {label}" if self.profile.key == "Standard" else f"Representative Base-EN directional calculation: {label}")
            self._combined_base_en_direction(directions[selected_component])
            return
        self._combined_base_en_direction(aggregate)

    def _combined_directional_summary(self, directions):
        self._case_heading(
            "Combined bending + directional shear + torsion", "plastic"
        )
        self._small(
            "V<sub>x,Ed</sub> + T<sub>Ed</sub> and V<sub>y,Ed</sub> + "
            "T<sub>Ed</sub> are assessed separately. A simultaneous "
            "V<sub>x</sub> + V<sub>y</sub> + T check is not included and requires "
            "a separate member check."
        )
        rows = [["Screen", "r<sub>N</sub>", "r<sub>M</sub>", "r<sub>V</sub>",
                 "r<sub>T</sub>", "DK NA sum", "Governing face",
                 "cot theta", "DK NA sum status"]]
        for component in ("vx", "vy"):
            item = directions.get(component)
            if not item:
                continue
            rows.append([
                "Vx+T" if component == "vx" else "Vy+T",
                _pct(item.get("r_n")), _pct(item.get("r_m")),
                _pct(item.get("r_v")),
                _pct(item.get("r_t")), _pct(item.get("dkna_sum")),
                viz.directional_face_label(
                    component, item.get("governing_face")
                ),
                _fmt(item.get("governing_cot"), 3),
                presentation.combined_dkna_status(item),
            ])
        self._table(
            rows,
            [16 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 21 * mm,
             27 * mm, 17 * mm, 30 * mm],
            font=5.8,
        )
        governing_notes = {
            presentation.combined_governing_assessment_note(item)
            for item in directions.values()
            if presentation.combined_governing_assessment_note(item)
        }
        for note in sorted(governing_notes):
            self._small(_html_escape(note))
        if any(
            item.get("outside_default_range")
            for item in directions.values()
        ):
            self._small(
                "One or more entered shared compression-strut ranges are outside "
                "the permitted method range. Dependent combined checks are NOT "
                "ASSESSED."
            )

    def _combined(self):
        aggregate = self.out["combined"]
        if not presentation.combined_uses_dkna(aggregate):
            self._combined_base_en(aggregate)
            return
        screen_label = presentation.combined_dkna_screen_label(aggregate)
        combined_blocker = presentation.combined_bending_assessment_blocker(
            self.out,
            self.inp,
        )
        if combined_blocker is not None:
            self._case_heading(
                "Combined bending + shear + torsion (M-V-T)", "plastic"
            )
            self._table(
                [
                    ["Screen", "r<sub>N</sub>", "r<sub>M</sub>", "r<sub>V</sub>",
                     "r<sub>T</sub>", "DK NA sum", "Status"],
                    [screen_label, "-", "-", "-", "-", "-", "NOT ASSESSED"],
                ],
                [27 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 28 * mm, 35 * mm],
            )
            self._small(combined_blocker)
            return
        if aggregate.get("outside_default_range"):
            self._case_heading(
                "Combined bending + shear + torsion (M-V-T)", "plastic"
            )
            self._h2("Compression-strut range: NOT ASSESSED")
            self._small('The selected compression-strut range is outside the range permitted for the selected methods.')
            self._small('Restore the entered limits to the permitted interval. Then recalculate.')
            self._small('No combined resistance, utilization or PASS/FAIL verdict is published.')
            return
        directions = aggregate.get("directions") or {}
        selected = self._selected_family("combined", self.inp)
        critical = selected is not None
        if not aggregate.get("biaxial") or not directions:
            self._case_heading(
                "Combined bending + shear + torsion (M-V-T)", "plastic"
            )
            status = presentation.combined_dkna_status(aggregate)
            self._table(
                [
                    ["Screen", "r<sub>N</sub>", "r<sub>M</sub>", "r<sub>V</sub>",
                     "r<sub>T</sub>", "DK NA sum", "Status"],
                    [
                        screen_label,
                        _pct(aggregate.get("r_n")),
                        _pct(aggregate.get("r_m")),
                        _pct(aggregate.get("r_v")),
                        _pct(aggregate.get("r_t")),
                        _pct(aggregate.get("dkna_sum")),
                        status,
                    ],
                ],
                [27 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 28 * mm, 35 * mm],
            )
            governing_note = presentation.combined_governing_assessment_note(
                aggregate
            )
            if governing_note:
                self._small(_html_escape(governing_note))
            if not critical:
                if aggregate.get("valid") and not aggregate.get("dkna_valid"):
                    self._h2("DK NA action-alone resistance assessment")
                    self._combined_direction(
                        aggregate, include_case_heading=False
                    )
                    return
                self._small(
                    "The complete combined M-V-T worked example is published only "
                    "for the governing utilization across all plastic cases."
                )
                return
            self._small('The results overview includes all calculated combined-action cases.')
            self._small('Audit gives the complete combined M-V-T worked example for the case with the governing utilization across all plastic cases.')
            self._h2("Governing combined result" if self.profile.key == "Standard" else "Governing combined worked example")
            self._combined_direction(aggregate, include_case_heading=False)
            return

        self._combined_directional_summary(directions)
        if not critical:
            self._small(
                "The complete combined M-V-T worked example is published in Audit only for "
                "the governing utilization across all plastic cases."
            )
            return
        self._small('The results overview includes all calculated combined-action cases and directions.')
        self._small('Audit gives the complete combined M-V-T worked example for the governing utilization across all plastic cases.')
        component = selected.get("component")
        if not isinstance(component, str) or component not in directions:
            self._h2("Worked combined calculation unavailable")
            self._small(
                "The selected governing interaction direction is unavailable. "
                "Recalculate before issuing the report."
            )
            return
        block_start = len(self.flow)
        label = "V<sub>x,Ed</sub> + T<sub>Ed</sub>" if component == "vx" \
            else "V<sub>y,Ed</sub> + T<sub>Ed</sub>"
        self._h2(f"Governing directional result: {label}" if self.profile.key == "Standard" else f"Governing directional worked example: {label}")
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
        scope_note = presentation.combined_publication_scope_note(c)
        if scope_note is not None:
            self._small(_html_escape(scope_note))
            return
        if not c.get("valid"):
            missing = []
            if not c.get("have_m", True):
                missing.append("bending")
            if not c.get("have_v", True):
                missing.append("shear")
            if not c.get("have_t", True):
                missing.append("torsion")
            detail = ", ".join(missing) or "one or more component checks"
            reason = (
                " " + _html_escape(_result_reason(
                    c["reason"],
                    "combined",
                    "report combined result reason",
                )) + "."
                if c.get("reason")
                else ""
            )
            self._small(
                f"Directional combined check not evaluated: {detail} missing "
                f"or invalid.{reason}"
            )
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
        self._p("The sectional actions use the shared edition <b>" + str(c["method"]) + "</b>.")
        self._p("Each denominator in the DK NA interaction is the resistance to that action acting alone. The other external sectional actions are set to zero.")
        governing_assessment_note = (
            presentation.combined_governing_assessment_note(c)
        )
        if governing_assessment_note:
            self._small(
                "<b>Overall M-V-T:</b> "
                + _html_escape(governing_assessment_note)
            )
        action_records = c.get("action_alone") or {}
        rows = [["Action", "S<sub>Ed</sub>", "S<sub>Rd</sub>", "Ratio"]]
        for key, label, unit in (
            ("n", "Axial N", "kN"),
            ("m", "Bending M", "kNm"),
            ("v", "Shear V", "kN"),
            ("t", "Torsion T", "kNm"),
        ):
            record = action_records.get(key) or {}
            demand = record.get("demand")
            resistance = record.get("resistance")
            rows.append([
                label,
                "-" if demand is None else f"{_fmt(demand, 3)} {unit}",
                "-" if resistance is None else f"{_fmt(resistance, 3)} {unit}",
                _pct(c.get(f"r_{key}")),
            ])
        self._table(rows, [43 * mm, 43 * mm, 43 * mm, 31 * mm])
        self._small(
            "N retains the entered tension/compression sign. The bending resistance "
            "is selected on the entered biaxial moment direction. Source: "
            "DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)."
        )
        self._small(
            "Scope: cross-section resistance. Complete the applicable Annex F "
            "member and detailing assessment separately."
        )
        self._h2(
            "DK NA 6.3.2(6): "
            "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) &#8804; 1"
        )
        selection = c.get("dkna_selection")
        if not isinstance(selection, dict):
            self._h2("Worked combined calculation unavailable")
            self._small(
                "The required DK NA component sums are unavailable. Recalculate "
                "before issuing the report."
            )
            return
        if not c.get("dkna_valid") or not selection.get("valid"):
            self._h2("DK NA interaction: NOT ASSESSED")
            self._small(
                "One or more matching action-alone resistances could not be "
                "determined. Check the section, materials and complete Plastic "
                "bending sweep, then recalculate. No PASS or FAIL verdict is given."
            )
        else:
            verdict = presentation.combined_dkna_status(c)
            if c["m_v_independent"]:
                expr = (
                    "max(r<sub>N</sub> + r<sub>M</sub> + r<sub>T</sub>, "
                    "r<sub>N</sub> + r<sub>V</sub> + r<sub>T</sub>)"
                )
                note = presentation.combined_dkna_assumption_note(c)
                note += " N and T remain in both independent checks."
                subst = (
                    f"max({_fmt(selection['n_m_plus_t'], 4)}, "
                    f"{_fmt(selection['n_v_plus_t'], 4)})"
                )
            else:
                expr = (
                    "r<sub>N</sub> + r<sub>M</sub> + r<sub>V</sub> + "
                    "r<sub>T</sub>"
                )
                note = "N, M, V and T each use their action-alone resistance."
                subst = (
                    f"{_fmt(selection['r_n'], 4)} + "
                    f"{_fmt(selection['r_m'], 4)} + "
                    f"{_fmt(selection['r_v'], 4)} + "
                    f"{_fmt(selection['r_t'], 4)}"
                )
            self._formula(
                expr,
                equation_key="combined.dk-na.sum",
                ref="DS/EN 1992-1-1 DK NA:2024, 6.3.2(6)",
                subst=subst,
                note=(f"{note} Applied inclusion rule: "
                      f"{_html_escape(selection['inclusion_rule'])}; governing "
                      f"branch: {_html_escape(selection['governing_chord'])}."),
                result=(
                    "&#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) = "
                    + (
                        f"{_pct(selection['utilisation'])}  "
                        "(numerical component only)"
                        if (
                            governing_assessment_note
                            and presentation.combined_dkna_limit_satisfied(c)
                            is not False
                        )
                        else f"{_pct(selection['utilisation'])}  ({verdict})"
                    )
                ),
            )
        self._h2("Physical resistance components")
        components_start = len(self.flow) - 1
        physical_components = presentation.combined_physical_components(c)
        physical_by_key = {
            component["key"]: component for component in physical_components
        }
        concrete = physical_by_key["concrete"]
        component_rows = [["Component", "Utilization", "Status", "Assessment note"]]
        component_rows.extend([
            [
                component["label"],
                _pct(component["util"]),
                component["status"],
                component["note"],
            ]
            for component in physical_components
        ])
        self._table(
            component_rows,
            [48 * mm, 28 * mm, 29 * mm, 65 * mm],
            font=7.5,
        )
        self._keep_from(components_start)
        self._small(
            "Concrete strut, closed stirrup and longitudinal reinforcement are "
            "independent physical checks. The worst value may govern the case, but "
            "it is not reported as a combined transverse-reinforcement utilization."
        )
        cr = c.get("crushing")
        if cr is not None and cr.get("valid"):
            self._h2("Concrete compression strut (6.29)")
            cr_status = concrete["status"]
            val = concrete["util"]
            if cr_status in {"PASS", "FAIL"}:
                vv = _demand_resistance_verdict(cr_status == "PASS")
                self._formula(
                    "T<sub>Ed</sub>/T<sub>Rd,max</sub> + "
                    "V<sub>Ed</sub>/V<sub>Rd,max</sub>",
                    equation_key="combined.crushing.interaction",
                    ref="EN 1992-1-1 (6.29)",
                    subst=f"{_fmt(cr['t_ed'], 3)}/{_fmt(cr['trd_max'], 3)} + "
                          f"{_fmt(cr['v_ed'], 3)}/{_fmt(cr['vrd_max'], 3)}",
                    result=f"{_pct(val)}  ({vv})")
                self._small(
                    "At a common strut cot theta = "
                    f"{_fmt(concrete['cot'], 2)} "
                    f"(theta = {_fmt(concrete['theta_deg'], 1)}&#176;)."
                )
                if self.figures:
                    self._fig(viz.vt_interaction_figure(
                        cr["vrd_max"], cr["trd_max"], cr["v_ed"], cr["t_ed"],
                        show_verdict=True,
                    ), 120, 100)
            else:
                self._small(
                    "NOT ASSESSED: recalculate the shared compression-strut "
                    "check before using this result."
                )
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
            stirrup = physical_by_key["stirrup"]
            if stirrup["status"] not in {"PASS", "FAIL"}:
                self._small(
                    "NOT ASSESSED: recalculate the shared closed-stirrup check "
                    "before using this result."
                )
            elif tr["shear_credited"]:
                note = (f"V<sub>Ed</sub> = {_fmt(tr['v_ed'], 1)} &#8804; V<sub>Rd,c</sub>"
                        f" = {_fmt(tr['vrd_c'], 1)} kN, so the concrete carries the "
                        "shear (6.2.1) and the whole closed stirrup serves torsion.")
            else:
                note = ("V<sub>Ed</sub> &gt; V<sub>Rd,c</sub>: shear and torsion "
                        "demands add on the shared closed stirrup.")
            if stirrup["status"] in {"PASS", "FAIL"}:
                vv = _demand_resistance_verdict(stirrup["status"] == "PASS")
                self._formula(
                    "shear share + torsion share (shared closed stirrup)",
                    equation_key="combined.stirrup.utilisation",
                    subst=(f"{_pct(tr['shear_fraction'])} + "
                           f"{_pct(tr['torsion_fraction'])}"),
                    result=(
                        "closed-stirrup utilisation = "
                        f"{_pct(stirrup['util'])}  ({vv})"
                    ))
                self._small(note)
                self._small(f"Member strut angle: cot theta = {_fmt(concrete['cot'], 2)} (theta = {_fmt(concrete['theta_deg'], 1)}&#176;).")
                self._small("Every participating shear and torsion check uses this angle (6.3.2(2)). The angle is selected to minimize the governing utilization.")
                self._keep_measured_calculation_from(stirrup_start)
        longitudinal = physical_by_key["longitudinal"]
        lg = longitudinal.get("governing")
        diagnostic_only = False
        if lg is None and presentation.required_chord_fallback(c) is not None:
            case_combined = self.out.get("combined")
            directions = case_combined.get("directions") if isinstance(case_combined, Mapping) else None
            owned_component = c.get("component")
            component_matches = component is None or (
                type(component) is str and component == owned_component
            )
            owned = component_matches and (
                c is case_combined or (
                    isinstance(directions, Mapping) and type(owned_component) is str
                    and directions.get(owned_component) is c
                )
            )
            diagnostic_current = owned and presentation.combined_publication_evidence_is_current(
                self.inp, self.out,
            )[0]
            if diagnostic_current:
                lg = capacity._combined_longitudinal_candidate(c.get("governing_longitudinal"))
                diagnostic_only = lg is not None
        if isinstance(lg, Mapping) and lg.get("valid"):
            self._h2("Longitudinal reinforcement: combined M + V + T tension chord")
            if not diagnostic_only:
                self._combined_chord_diagram(c, longitudinal)
            chord_status = longitudinal["chord_status"]
            chord_util = longitudinal["chord_util"]
            coverage = lg.get("off_not_evaluated")
            ax = lg["axis"]
            face = viz.tension_face_label(
                lg.get("tension_low", True), lg.get("axis")
            )
            face_desc = (
                f"the off-axis face ({face})"
                if lg.get("role") == "off_axis"
                else
                f"the shear tension face ({face})"
                if lg.get("gets_shift") is True
                else f"the shear compression face ({face}), with torsion "
                     "tension and bending relief"
            )
            if diagnostic_only:
                self._p(
                    "Required face coverage is incomplete. The largest available "
                    "conditional face is shown for inspection; these operands do "
                    "not establish a complete governing chord check."
                )
            self._p(("The retained conditional chord is " if diagnostic_only else "The governing tension chord is ")
                    + f"{face_desc} about the {ax}-axis. M<sub>Ed</sub> and M<sub>Rd</sub> refer to that face.")
            self._p("The chord carries bending tension, the shear shift and its share of the torsion longitudinal force.")
            self._p("The shear shift is (6.18):")
            self._p("&#916;F<sub>td</sub> = 0.5&#183;V<sub>Ed</sub>&#183;cot theta.")
            self._p("The shift acts only on the flexural tension face. It is zero on an off-axis face.")
            self._p("The torsion longitudinal force is (6.28):")
            self._p("F<sub>td,T</sub> = T<sub>Ed</sub>&#183;u<sub>k</sub>&#183;cot theta/(2A<sub>k</sub>).")
            self._p("This force is distributed around the perimeter. Half acts on this chord.")
            self._p("Each contribution is converted to an equivalent moment with lever arm z. It is checked against M<sub>Rd</sub> "
                    + _report_chord_mrd_label(ax, lg.get("m_off", 0.0), lg.get("conditional", True)) + ".")
            self._formula(
                "M<sub>Ed,total</sub> = M<sub>Ed</sub> + "
                "&#916;F<sub>td</sub>&#183;z + F<sub>td,T</sub>&#183;z/2",
                equation_key="combined.chord.demand",
                ref="EN 1992-1-1 6.2.3(7) + 6.3.2",
                subst=f"{_fmt(lg['m_ed'], 1)} + {_fmt(lg['mv'], 1)} + "
                      f"{_fmt(lg['mt'], 1)} kNm  (z = {_fmt(lg['z'], 3)} m, "
                      f"&#916;F<sub>td</sub> = {_fmt(lg['ftd_v'], 1)} kN, "
                      f"F<sub>td,T</sub> = {_fmt(lg['ftd_t'], 1)} kN)",
                result=(
                    f"M<sub>Ed,total</sub> = {_fmt(lg['m_total'], 1)} kNm"
                ),
            )
            biaxial = lg.get("biaxial", False)
            fallback = presentation.required_chord_fallback(c)
            fell_back = fallback is not None
            assessment_complete = chord_status in {"PASS", "FAIL"}
            if not assessment_complete:
                verdict_suffix = (
                    "  (NOT ASSESSED - CHORD ASSESSMENT INCOMPLETE)"
                )
            else:
                vv = _demand_resistance_verdict(chord_status == "PASS")
                verdict_suffix = f"  ({vv})"
            self._formula(
                "M<sub>Ed,total</sub> / M<sub>Rd</sub>",
                equation_key="combined.chord.utilisation",
                references=("combined.chord.demand",),
                subst=f"{_fmt(lg['m_total'], 1)} / {_fmt(lg['m_rd'], 1)}",
                result=f"utilisation = {_pct(chord_util)}{verdict_suffix}")
            self._small(
                "Overall longitudinal reinforcement assessment: "
                f"{_pct(longitudinal['util'])} {longitudinal['status']}. "
                "Governing check: "
                f"{_html_escape(str(longitudinal.get('governing_mechanism') or '-'))}. "
                "The chord comparison and the independent Formula (6.28) "
                "reinforcement evidence remain separately identified."
            )
            if fell_back:
                fallback_axis = fallback.get("axis", "?")
                fallback_face = (
                    "negative" if fallback.get("tension_low", True)
                    else "positive"
                )
                self._p(f"The required {fallback_axis}-axis {fallback_face} face uses a pure-axis substitute because its conditional capacity solve did not converge.")
                self._p("The complete chord check can be optimistic. Use the combined &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check, which includes the full biaxial bending utilization.")
            notes = [viz.chord_angle_note(lg.get("theta_mode"), angle_valid=concrete.get("angle_valid") is True)]
            if coverage == "subdivided":
                notes.append("For this compound section, the torsion longitudinal steel is calculated for each sub-tube. The torsion share of the off-axis chord is not evaluated.")
                notes.append("The &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check includes the interaction.")
            elif coverage == "not_solved":
                notes.append("At least one chord face that carries the torsion share could not be evaluated. A conditional solve failed, or a face has no tension steel.")
                notes.append("These faces are NOT checked. The reported governing chord can therefore be less critical than an unchecked face.")
                notes.append("The &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check remains the combined verification.")
            elif biaxial and not lg.get("has_torsion"):
                notes.append("No torsion acts on the off-axis chord. Its bending tension is already included in the biaxial bending utilization of the &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check.")
            elif not biaxial:
                notes.append("The &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check uses the full biaxial bending utilization. It remains the primary combined check.")
            if lg["capped"]:
                notes[0:0] = [
                    "The shear shift is limited so that bending plus shear does not exceed M<sub>Rd</sub>.",
                    "Clause 6.2.3(7) permits the added tension to be limited by the tension at peak moment. This section calculation uses M<sub>Rd</sub> as that limit.",
                ]
            for note in notes:
                self._small(note)
            self._chord_off_block(
                c.get("chord_off"),
                assessment_complete=assessment_complete,
            )
        else:
            chord_guidance = (
                "Complete current longitudinal chord evidence is required for the full utilization check."
                if c.get("links") else
                "Enable shear links for the full utilization check."
            )
            self._small("Additional longitudinal steel for torsion (6.28): "
                        f"&#8721;A<sub>sl</sub> = {_fmt(c['asl_torsion'], 0)} mm<sup>2</sup> around the perimeter.")
            self._small("Additional longitudinal shear force on the tension chord (6.18): "
                        f"&#916;F<sub>td</sub> = {_fmt(c['delta_ftd'], 1)} kN.")
            self._small("Both requirements are additional to the bending reinforcement.")
            self._small(chord_guidance)

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
        self._p(f"The governing tension chord is the {face} face about the {och['axis']}-axis. Shear does not act on this axis.")
        self._p("Torsion applies tension to both faces. The more critical face is reported. No shear shift acts on this chord.")
        self._p("The equivalent moment from the torsion share is F<sub>td,T</sub>&#183;z/2.")
        self._p("The capacity is checked against M<sub>Rd</sub> "
                + _report_chord_mrd_label(och["axis"], och.get("m_off", 0.0), True) + ".")
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
        off_axis_arm_source = presentation.shear_link_arm_source_label(
            och.get("z_src")
        )
        self._small(f"z = {_fmt(och['z'], 3)} m ({off_axis_arm_source}).")
        self._small("Each chord capacity is calculated at the applied axial force N and the bending moment about the other axis.")
        self._small("The shared longitudinal steel also carries the shear and torsion tensions from both chords. The DK NA &#8721;(S<sub>Ed</sub>/S<sub>Rd</sub>) check includes this interaction and governs the combined check.")

    def _subtube_evidence_tables(self, t):
        """Publish retained component geometry and torque allocation."""
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
                "One or more stiffness-proportional sub-tube torque shares are "
                "unavailable. Recalculate before issuing the report."
            )
            return
        wall_selection_rows = [[
            "Sub-tube", "Base A/u", "Selected t<sub>ef</sub>", "Source"
        ]]
        wall_detail_rows = [[
            "Sub-tube", "Wall", "Bar positions", "a", "Lower bound 2a",
            "Real wall",
        ]]
        for index, sub in enumerate(subs):
            role = "web" if index == 0 else f"part {index + 1}"
            tube = sub.get("tube") or {}
            evidence = tube.get("wall_evidence") or {}
            wall_rows = evidence.get("walls") or ()
            if not evidence.get("complete") or not wall_rows:
                self._h2("Sub-tube wall selection unavailable")
                self._small(
                    "The reinforcement-center evidence required for one or more "
                    "sub-tube walls is unavailable. Recalculate before issuing "
                    "the report."
                )
                return
            wall_selection_rows.append([
                role,
                f"{_fmt(evidence.get('a_over_u_mm'), 1)} mm",
                f"{_fmt(evidence.get('selected_tef_mm'), 1)} mm",
                _html_escape(evidence.get("selection") or "wall limits"),
            ])
            wall_detail_rows.extend([
                [
                    role,
                    f"Wall {row['wall']}",
                    ", ".join(str(value) for value in row["bar_indices"]),
                    f"{_fmt(row.get('a_mm'), 1)} mm",
                    f"{_fmt(row.get('lower_bound_mm'), 1)} mm",
                    (
                        "-"
                        if row.get("real_wall_mm") is None
                        else f"{_fmt(row.get('real_wall_mm'), 1)} mm"
                    ),
                ]
                for row in wall_rows
            ])
        self._p('The compound section is represented by component rectangles. Each rectangle forms an equivalent thin-walled tube.')
        self._p('The T<sub>Rd</sub> component is the sum of the sub-tube resistance components (6.3.1(3)). Applied torque T<sub>Ed</sub> is distributed by uncracked torsional stiffness (6.3.1(4)):')
        self._p('C = beta h b<sup>3</sup>.')
        self._p('The first rectangle is the web. It carries the shear in the combined V+T checks.')
        self._p('The union of the positioned rectangles was checked against the concrete outline and voids before these results were issued.')
        self._h2("Equivalent-tube wall selection")
        self._table(
            wall_selection_rows,
            [30 * mm, 30 * mm, 35 * mm, 85 * mm],
            font=7.0,
        )
        self._table(
            wall_detail_rows,
            [22 * mm, 20 * mm, 30 * mm, 24 * mm, 38 * mm, 30 * mm],
            font=6.5,
        )
        rows = [["Sub-tube", "center x, y<br/>b x h (mm)", "t<sub>ef</sub> (mm)",
                 "A<sub>k</sub> (mm2)", "share", "T<sub>Ed,i</sub> (kNm)",
                 "T<sub>Rd,i</sub> (kNm)", "util", "A<sub>sl,req</sub> (mm<super>2</super>)",
                 "governs"]]
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
                         _fmt(s["trd"], 2), ut, _fmt(s.get("asl_req"), 0),
                         _report_resistance_governing_label(s["governs"])])
        self._table(rows, [15 * mm, 23 * mm, 13 * mm, 17 * mm, 12 * mm, 15 * mm,
                           15 * mm, 11 * mm, 15 * mm, 24 * mm], font=6.4)
        return True

    def _subtube_section(self, t):
        """Torsion of a subdivided compound section (EN 1992-1-1 6.3.1(3)-(4))."""
        subs = t["subtubes"]
        distribution = t.get("torque_distribution") or {}
        shares = distribution.get("shares") or ()
        if self._subtube_evidence_tables(t) is not True:
            return
        # The torque is split by STIFFNESS, not capacity, so the governing check is the
        # WORST sub-tube (max util), not TEd / sum(TRd_i).
        util = t["util"]
        util_txt = _pct(util)
        component_verdict = _demand_resistance_verdict(viz.util_ok(util))
        g = t.get("governing_sub")
        gov = ("web" if g == 0 else f"part {g + 1}") if g is not None else "-"
        if not isinstance(g, int) or not 0 <= g < len(subs):
            self._h2("Governing sub-tube calculation unavailable")
            self._small(
                "The governing sub-tube is unavailable. Recalculate before "
                "issuing the report."
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
                "Terms from the governing sub-tube resistance are unavailable. "
                "Recalculate before issuing the report."
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
                   f"(governed by {_report_resistance_governing_label(resistance['governs'])})",
        )
        self._formula(
            "governing utilisation = max(T<sub>Ed,i</sub> / T<sub>Rd,i</sub>)",
            equation_key="torsion.subtube.governing-utilisation",
            references=("torsion.subtube.torque-share",
                        "torsion.resistance.governing"),
            ref=f"worst sub-tube: {gov}",
            subst=(f"{_fmt(governing['t_ed'], 3)} / "
                   f"{_fmt(governing['trd'], 3)}"),
            result=(f"{util_txt}  (transverse/strut component "
                    f"{component_verdict})"))
        self._small("The largest T<sub>Ed,i</sub>/T<sub>Rd,i</sub> governs the resistance component. Every sub-tube resistance component must pass.")
        self._small("Applied torque is distributed by uncracked torsional stiffness.")
        self._small(f"Resistance-component sum: &#8721;T<sub>Rd,i</sub> = {_fmt(t['trd'], 2)} kN&#183;m. This sum is not the verdict denominator.")
        self._small(f"Total required longitudinal steel: &#8721;A<sub>sl</sub> = {_fmt(t['asl_req'], 0)} mm<sup>2</sup> across all sub-tubes.")
        self._small("Its allocation around each sub-tube, reserve beyond bending and member anchorage are not verified.")
        self._small("The combined V+T crushing check pairs shear with the web sub-tube.")
        if self.figures:
            self._fig(viz.subtube_figure(subs), 150, 90)

    def _selected_torsion_subcheck(self, key):
        selection = self._selected_torsion_subchecks.get(key)
        if (
            not isinstance(selection, Mapping)
            or selection.get("case_id") != self._case_id(self.inp, "plastic")
        ):
            return None, None
        torsion_result = self.out.get("torsion") or {}
        if (
            presentation.torsion_applicability_publication_status(
                torsion_result
            )
            != "APPLICABLE"
        ):
            return None, None
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
                "<b>Worked calculation unavailable.</b> Required Formula 6.29 "
                "terms are missing. Recalculate before issuing the report."
            )
            return
        direction = (
            ""
            if component is None
            else " for " + ("Vx + T" if component == "vx" else "Vy + T")
        )
        self._small(
            "All calculated V+T screens remain in the results overview. This is "
            "the single largest calculated Formula 6.29 utilisation across "
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
                "<b>Worked calculation unavailable.</b> Required Formula 6.31 "
                "terms are missing. Recalculate before issuing the report."
            )
            return
        direction = (
            ""
            if component is None
            else " for " + ("Vx + T" if component == "vx" else "Vy + T")
        )
        self._small(
            "All calculated Formula 6.31 screens remain in the results overview. "
            "This is the single largest calculated screen value across all "
            f"plastic cases and directions{direction}."
        )
        self._h2("Minimum-reinforcement screen (6.3.2(5), Eq 6.31)")
        condition_status = (
            presentation.minimum_reinforcement_screen_status(minimum)
        )
        detailing_status = (
            presentation.minimum_reinforcement_detailing_status(minimum)
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
            result=(
                f"{_fmt(minimum['value'], 3)}  (low-action {condition_status}; "
                f"link detailing {detailing_status})"
            ),
        )

    def _torsion_minimum_reinforcement_summary(self, minimum):
        """Publish one retained Formula (6.31) scope and verdict."""

        if not isinstance(minimum, dict):
            return
        status = presentation.minimum_reinforcement_screen_status(minimum)
        outcome = presentation.minimum_reinforcement_screen_outcome(minimum)
        detailing_status = (
            presentation.minimum_reinforcement_detailing_status(minimum)
        )
        self._h2("Minimum-reinforcement screen (Formula 6.31)")
        self._table(
            [
                ["Condition status", "6.31 sum", "Low-action outcome",
                 "Separate detailing"],
                [
                    status,
                    (
                        _fmt(minimum.get("value"), 3)
                        if minimum.get("applicable")
                        else "-"
                    ),
                    outcome,
                    detailing_status,
                ],
            ],
            [32 * mm, 28 * mm, 72 * mm, 48 * mm],
        )
        self._small(
            _html_escape(
                presentation.minimum_reinforcement_screen_note(minimum)
            )
            + ". The complete shear-and-torsion resistance checks remain "
            "separate."
        )
        self._small(
            "<b>Separate link detailing - " + detailing_status + ":</b> "
            + _html_escape(
                presentation.minimum_reinforcement_detailing_note(minimum)
            )
            + "."
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
        self._small(f"Common strut angle: cot theta = {_fmt(inter['cot'], 2)} (theta = {_fmt(inter['theta_deg'], 1)}&#176;).")
        self._small("T<sub>Rd,max</sub> and V<sub>Rd,max</sub> are evaluated at this shared angle.")
        if self.figures:
            self._fig(viz.vt_interaction_figure(inter["vrd_max"], inter["trd_max"],
                                                inter["v_ed"], inter["t_ed"],
                                                show_verdict=True),
                      120, 100)

    def _torsion_applicability_block(self, t):
        """Render applicability; the caller must first establish current evidence."""
        applicability = t.get("applicability")
        if not isinstance(applicability, Mapping):
            applicability = {}
        design_basis = applicability.get("design_basis")
        if design_basis not in capacity.TORSION_DESIGN_BASES:
            design_basis = capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
        member_scope = applicability.get("member_scope")
        if member_scope not in capacity.TORSION_MEMBER_SCOPES:
            member_scope = capacity.TORSION_APPLICABILITY_NOT_ESTABLISHED
        applicability_status = (
            presentation.torsion_applicability_publication_status(t)
        )
        self._h2("Torsion applicability and member scope")
        self._table(
            [
                ["Design basis", "Member scope", "Applicability"],
                [design_basis, member_scope, applicability_status],
            ],
            [70 * mm, 70 * mm, 40 * mm],
            font=6.5,
        )
        clauses = applicability.get("clauses") or ()
        applicability_note = _html_escape(
            presentation.torsion_applicability_note(t)
        )
        if clauses:
            applicability_note += ". Clauses: " + "; ".join(
                _html_escape(str(clause)) for clause in clauses
            )
        self._small(applicability_note + ".")
        limitation = applicability.get("limitation")
        if (
            design_basis == capacity.TORSION_DESIGN_COMPATIBILITY_RESIDUAL
            and isinstance(limitation, str)
        ):
            self._small(_html_escape(report_notation.native_scope(limitation)))
        if applicability_status != "APPLICABLE":
            t_ed = presentation.torsion_publication_t_ed(t)
            self._p(
                f"<b>{applicability_status}:</b> "
                + _html_escape(presentation.torsion_applicability_note(t))
                + ". Resistance, utilization, governing angle, longitudinal "
                "demand and dependent interaction verdicts are withheld."
            )
            self._table(
                [
                    [
                        "T<sub>Ed</sub>",
                        "T<sub>Rd</sub>",
                        "Utilization",
                        "Overall status",
                    ],
                    [
                        "-" if t_ed is None else f"{_fmt(t_ed, 3)} kN&#183;m",
                        "-",
                        "-",
                        applicability_status,
                    ],
                ],
                [45 * mm, 45 * mm, 45 * mm, 45 * mm],
                caption='Torsion resistance and overall status',
            )
            return False
        return True

    def _torsion_longitudinal_block(self, t):
        retained_longitudinal_assessment = t.get("longitudinal_assessment")
        longitudinal_assessment = (
            presentation.torsion_longitudinal_assessment(t, input_payload=self.inp)
        )
        if isinstance(retained_longitudinal_assessment, Mapping):
            self._h2("Longitudinal torsion reinforcement (Formula 6.28)")
            self._table(
                [
                    ["Quantity", "Value", "Assessment"],
                    [
                        "Required longitudinal area",
                        f"{_fmt(longitudinal_assessment.get('required_asl_mm2'), 0)} mm<sup>2</sup>",
                        "Formula (6.28)",
                    ],
                    [
                        "All modeled passive bars - gross area",
                        f"{_fmt(longitudinal_assessment.get('provided_gross_area_mm2'), 0)} mm<sup>2</sup>",
                        "Upper bound before bending demand",
                    ],
                    [
                        "All modeled passive bars - equivalent area at selected f<sub>yd</sub>",
                        f"{_fmt(longitudinal_assessment.get('provided_equivalent_area_mm2'), 0)} mm<sup>2</sup>",
                        str(longitudinal_assessment.get("status") or "NOT ASSESSED"),
                    ],
                ],
                [75 * mm, 45 * mm, 60 * mm],
                font=7.0,
            )
            self._small(_html_escape(presentation.torsion_assessment_note(t, input_payload=self.inp)) + ".")
            self._small("The modeled passive-bar total can be credited as usable torsion reinforcement only after its reserve beyond bending is established.")
            self._small("Distribution around every torsion-tube side and anchorage along the member must also be established.")

    def _torsion(self):
        t = self.out["torsion"]
        critical = self._selected_family("torsion", self.inp) is not None
        self._case_heading("Torsion (thin-walled tube)", "plastic")
        if self.inp.get("_report_case_current") is False:
            self._h2("Torsion result")
            self._status_block(
                "NOT ASSESSED - Recalculate this action set before relying on "
                "the torsion result.",
                "NOT ASSESSED",
            )
            return
        current, current_reason = presentation.torsion_publication_component_is_current(
            self.inp,
            self._shear_publication_authority(),
            t,
        )
        if current is not True:
            guidance = _result_reason(
                current_reason,
                "torsion",
                "report torsion current-evidence reason",
            )
            self._h2("Torsion result")
            self._status_block(
                "NOT ASSESSED - " + guidance + ". Recalculate the torsion check.",
                "NOT ASSESSED",
            )
            return
        if self._torsion_applicability_block(t) is not True:
            return
        self._torsion_components(t, critical)

    def _torsion_angle_diagnostic(self, t, angle_applicability):
        reason = _result_reason(
            t.get("assessment_reason") or t.get("reason"),
            "torsion",
            "report torsion strut-angle applicability reason",
        )
        self._small(
            "Torsion NOT ASSESSED: " + _html_escape(reason) + ". "
            "No torsion resistance, utilization, longitudinal demand or "
            "dependent interaction verdict is published."
        )
        self._table(
            [
                ["Quantity", "Value", "Publication state"],
                [
                    "T<sub>Ed</sub>",
                    f"{_fmt(t.get('t_ed'), 3)} kN&#183;m",
                    "Applied action",
                ],
                [
                    "T<sub>Rd,c</sub>",
                    f"{_fmt(t.get('trd_c'), 3)} kN&#183;m",
                    "Angle-independent cracking context",
                ],
            ],
            [55 * mm, 45 * mm, 80 * mm],
        )
        self._small(f"Requested cot theta: {_fmt(angle_applicability.get('requested_min'), 3)} to {_fmt(angle_applicability.get('requested_max'), 3)}.")
        self._small("Method: " + _html_escape(str(angle_applicability.get("method") or "-"))
                    + " (" + _html_escape(str(angle_applicability.get("clause") or "-")) + ").")
        self._small(f"Permitted cot theta: {_fmt(angle_applicability.get('permitted_min'), 3)} to {_fmt(angle_applicability.get('permitted_max'), 3)}.")

    def _single_tube_evidence_tables(self, t):
        """Publish retained single-tube geometry and wall evidence."""
        tube = t["tube"]
        self._h2("Equivalent-tube wall selection")
        tef_src = str(tube.get("tef_selection") or "wall limits")
        rows = [["Quantity", "Symbol", "Value"],
                ["Gross area (incl. hollow)", "A", f"{_fmt(tube['A'] * 1e6, 0)} mm<sup>2</sup>"],
                ["Outer perimeter", "u", f"{_fmt(tube['u'] * 1e3, 0)} mm"],
                ["Base thickness", "A/u", f"{_fmt(tube['tef_auto'], 1)} mm"],
                ["Wall thickness", "t<sub>ef</sub>",
                 f"{_fmt(tube['tef'], 1)} mm ({tef_src})"],
                ["Enclosed area", "A<sub>k</sub>", f"{_fmt(tube['Ak'] * 1e6, 0)} mm<sup>2</sup>"],
                ["Center-line perimeter", "u<sub>k</sub>", f"{_fmt(tube['uk'] * 1e3, 0)} mm"],
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
        wall_rows = (tube.get("wall_evidence") or {}).get("walls") or ()
        if wall_rows:
            self._small(
                "Wall-specific reinforcement-center lower bounds and hollow-wall "
                "limits used for the selected equivalent-tube thickness:"
            )
            self.flow[-1].keepWithNext = 1
            self._table(
                [
                    ["Wall", "Bar(s)", "a", "Lower bound 2a", "Real wall"],
                    *[
                        [
                            f"Wall {row['wall']}",
                            ", ".join(str(value) for value in row["bar_indices"]),
                            f"{_fmt(row.get('a_mm'), 1)} mm",
                            f"{_fmt(row.get('lower_bound_mm'), 1)} mm",
                            (
                                "-"
                                if row.get("real_wall_mm") is None
                                else f"{_fmt(row.get('real_wall_mm'), 1)} mm"
                            ),
                        ]
                        for row in wall_rows
                    ],
                ],
                [25 * mm, 25 * mm, 30 * mm, 40 * mm, 35 * mm],
                font=6.8,
            )

    def _torsion_components(self, t, critical):
        tube = t["tube"]
        tube_valid = (
            t.get("tube_valid") is True
            if "tube_valid" in t
            else t.get("valid") is True
        )
        transverse_resistance_assessed = (
            t.get("transverse_resistance_assessed") is True
            if "transverse_resistance_assessed" in t
            else t.get("full_resistance_assessed") is True
            if "full_resistance_assessed" in t
            else t.get("valid") is True
        )
        transverse_resistance_available = bool(
            tube_valid
            and transverse_resistance_assessed
            and (
                t.get("closed_links_present") is True
                if "closed_links_present" in t
                else t.get("valid") is True
            )
            and t.get("valid") is True
        )
        if transverse_resistance_available:
            self._p(
                "The transverse-steel and concrete-strut resistance components "
                "are calculated with the EN 1992-1-1 section 6.3 closed-tube "
                "model, method <b>"
                + str(t["method"])
                + "</b>. "
                + presentation.torsion_angle_selection_note(t)
            )
        elif tube_valid and not transverse_resistance_assessed:
            angle_applicability = t.get("angle_applicability")
            if (
                isinstance(angle_applicability, dict)
                and angle_applicability.get("applicable") is False
            ):
                self._p(
                    "<b>NOT ASSESSED:</b> the entered compression-strut range is "
                    "outside the permitted range for method <b>"
                    + str(t["method"])
                    + "</b>. Angle-dependent resistance, utilization and "
                    "reinforcement demand are withheld."
                )
            else:
                self._p(
                    "<b>NOT ASSESSED:</b> the torsion transverse/strut resistance "
                    "under method <b>"
                    + str(t["method"])
                    + "</b> requires current shared links / closed stirrups. "
                    "Concrete resistance and reinforcement demand remain as "
                    "context."
                )
        else:
            self._p(
                "<b>NOT ASSESSED:</b> the thin-walled tube geometry is invalid. "
                "Review the reason below."
            )
        status = presentation.torsion_assessment_status(t, input_payload=self.inp)
        reported_trd = t.get("trd") if transverse_resistance_available else None
        reported_util = t.get("util") if transverse_resistance_available else None
        reported_governing = (
            t.get("governs") if transverse_resistance_available else None
        )
        self._table(
            [
                ["T<sub>Ed</sub>", "T<sub>Rd</sub> component",
                 "Component utilization", "Governing component",
                 "Overall status"],
                [
                    f"{_fmt(t.get('t_ed'), 3)} kN&#183;m",
                    (
                        f"{_fmt(reported_trd, 3)} kN&#183;m"
                        if reported_trd is not None
                        else "-"
                    ),
                    _pct(reported_util),
                    _report_resistance_governing_label(reported_governing) if reported_governing else "-",
                    status,
                ],
            ],
            [31 * mm, 31 * mm, 31 * mm, 46 * mm, 31 * mm],
            caption='Torsion resistance and overall status',
        )
        if transverse_resistance_available:
            self._small(
                "<b>Overall "
                + status
                + ":</b> "
                + _html_escape(presentation.torsion_assessment_note(t, input_payload=self.inp))
                + "."
            )
        directional = t.get("directional_interactions") or {}
        if not directional and isinstance(t.get("min_reinf"), dict):
            self._torsion_minimum_reinforcement_summary(t["min_reinf"])
        if directional:
            rows = [["Screen", "T<sub>Ed</sub>/T<sub>Rd</sub>",
                     "6.29 V+T", "Governing face", "cot theta", "Status"]]
            min_reinf_rows = [[
                "Screen", "6.31 sum", "Governing face", "Condition status",
                "Low-action outcome", "Separate detailing"
            ]]
            min_reinf_notes = []
            for component in ("vx", "vy"):
                item = directional.get(component)
                if presentation.torsion_publication_component_is_current(
                    self.inp, self._shear_publication_authority(), t, component=component,
                )[0] is not True:
                    label = "Vx+T" if component == "vx" else "Vy+T"
                    rows.append([label, "-", "-", "-", "-", "NOT ASSESSED"])
                    min_reinf_rows.append([
                        label, "-", "-", "NOT ASSESSED",
                        "Recalculate this directional torsion check", "NOT ASSESSED",
                    ])
                    continue
                if not item:
                    continue
                if transverse_resistance_available:
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
                    min_reinf_status = (
                        presentation.minimum_reinforcement_screen_status(
                            min_reinf
                        )
                    )
                    outcome = (
                        presentation.minimum_reinforcement_screen_outcome(
                            min_reinf
                        )
                    )
                    detailing_status = (
                        presentation.minimum_reinforcement_detailing_status(
                            min_reinf
                        )
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
                        min_reinf_status,
                        outcome,
                        detailing_status,
                    ])
                    min_reinf_notes.append((
                        min_reinf_status,
                        presentation.minimum_reinforcement_screen_note(
                            min_reinf
                        ),
                        detailing_status,
                        presentation.minimum_reinforcement_detailing_note(
                            min_reinf
                        ),
                    ))
            if len(rows) > 1:
                self._small('Standalone torsion, V<sub>x</sub>+T and V<sub>y</sub>+T are reported separately.')
                self._small('Simultaneous V<sub>x</sub>+V<sub>y</sub>+T requires a separate member check. This report does not include that check.')
                self._table(
                    rows,
                    [27 * mm, 28 * mm, 25 * mm, 38 * mm, 20 * mm, 32 * mm],
                    font=6.5,
                )
            if len(min_reinf_rows) > 1:
                self._h2("Directional minimum-reinforcement screens (Eq. 6.31)")
                self._table(
                    min_reinf_rows,
                    [20 * mm, 19 * mm, 25 * mm, 25 * mm, 50 * mm, 41 * mm],
                    font=6.5,
                )
                self._small(
                    "Within its stated scope, Formula 6.31 indicates whether "
                    "designed shear-and-torsion reinforcement beyond the required "
                    "minimum is needed. The complete resistance and detailing "
                    "checks remain separate."
                )
                for (
                    min_reinf_status,
                    note,
                    detailing_status,
                    detailing_note,
                ) in dict.fromkeys(min_reinf_notes):
                    self._small(
                        "<b>" + min_reinf_status + ":</b> "
                        + _html_escape(note) + "."
                    )
                    self._small(
                        "<b>Separate link detailing - "
                        + detailing_status
                        + ":</b> "
                        + _html_escape(detailing_note)
                        + "."
                    )
        if tube_valid and not transverse_resistance_assessed:
            angle_applicability = t.get("angle_applicability")
            if (
                isinstance(angle_applicability, dict)
                and angle_applicability.get("applicable") is False
            ):
                self._torsion_angle_diagnostic(t, angle_applicability)
                return
            reason = _result_reason(
                t.get("assessment_reason")
                or t.get("reason")
                or "full torsion resistance not assessed",
                "torsion",
                "report torsion assessment reason",
            )
            self._small(
                "Reason: " + _html_escape(reason) + ". "
                "T<sub>Rd,max</sub> is the concrete-strut cap and "
                "T<sub>Rd,c</sub> the cracking resistance. The transverse/strut "
                "resistance component and its utilization require current closed "
                "links."
            )
            self._table(
                [
                    ["Quantity", "Value", "Publication state"],
                    ["T<sub>Ed</sub>", f"{_fmt(t.get('t_ed'), 3)} kN&#183;m", "Applied action"],
                    ["T<sub>Rd,max</sub>", f"{_fmt(t.get('trd_max'), 3)} kN&#183;m", "Concrete cap only"],
                    ["T<sub>Rd,c</sub>", f"{_fmt(t.get('trd_c'), 3)} kN&#183;m", "Cracking transparency"],
                    ["Required longitudinal steel", f"{_fmt(t.get('asl_req'), 0)} mm<sup>2</sup>", "Formula (6.28) demand"],
                ],
                [55 * mm, 45 * mm, 80 * mm],
            )
            self._small(
                "Displayed cap angle: theta = "
                f"{_fmt(t.get('theta_deg'), 1)}&#176;, cot theta = "
                f"{_fmt(t.get('cot'), 3)}. This supports the concrete cap and "
                "reinforcement demand; the transverse resistance component is "
                "not assessed."
            )
            return
        if not t["valid"]:
            if t.get("reason") == "multi-cell (2+ voids)":
                self._small("Torsion not evaluated: a multi-cell section (two or "
                            "more voids) needs sub-division into separate tubes "
                            "(6.3.2(1)); the single-tube idealisation is not applied.")
            elif t.get("reason") == "compound outline requires subdivision":
                self._small('Torsion is not evaluated. The re-entrant or compound outline, such as T, L or I, requires component sub-sections under EN 1992-1-1 6.3.1(3).')
                self._small('Enable sub-tubes and define rectangles that partition the section. A resistance result can then be calculated.')
            elif str(t.get("reason") or "").startswith(
                    "invalid sub-tube partition:"):
                _result_reason(
                    t.get("subdivision_reason") or t.get("reason"),
                    "torsion",
                    "report torsion sub-tube partition reason",
                )
                self._small('Torsion is not assessed because the sub-tubes do not partition the concrete section.')
                self._small('Adjust their centers and dimensions to cover the net area without gaps, overlaps or boundary crossings.')
                self._small('Torsion resistance and dependent interaction checks are not calculated.')
            elif (
                str(t.get("reason") or "").startswith("torsion wall")
                or str(t.get("reason") or "").startswith(
                    "torsion sub-tube reinforcement"
                )
            ):
                reason = _result_reason(
                    t.get("reason"),
                    "torsion",
                    "report torsion wall-thickness applicability reason",
                )
                self._small(
                    "Torsion NOT ASSESSED: " + _html_escape(reason) + ". "
                    "No torsion resistance, utilization or dependent interaction "
                    "verdict is published."
                )
                wall_evidence = (t.get("tube") or {}).get("wall_evidence") or {}
                evidence_rows = [
                    ["Quantity", "Value"],
                    [
                        "Base thickness A/u",
                        f"{_fmt(wall_evidence.get('a_over_u_mm'), 1)} mm",
                    ],
                    [
                        "Entered override",
                        (
                            "automatic"
                            if not wall_evidence.get("override_mm")
                            else f"{_fmt(wall_evidence.get('override_mm'), 1)} mm"
                        ),
                    ],
                ]
                self._table(evidence_rows, [75 * mm, 75 * mm])
                wall_rows = wall_evidence.get("walls") or ()
                if wall_rows:
                    self._table(
                        [
                            ["Wall", "a", "Lower bound 2a", "Real wall"],
                            *[
                                [
                                    f"Wall {row['wall']}",
                                    f"{_fmt(row.get('a_mm'), 1)} mm",
                                    f"{_fmt(row.get('lower_bound_mm'), 1)} mm",
                                    (
                                        "-"
                                        if row.get("real_wall_mm") is None
                                        else f"{_fmt(row.get('real_wall_mm'), 1)} mm"
                                    ),
                                ]
                                for row in wall_rows
                            ],
                        ],
                        [30 * mm, 35 * mm, 45 * mm, 40 * mm],
                        font=7.0,
                    )
            else:
                self._small("Warning: the tube could not be formed (a degenerate or "
                            "too-thin section).")
            return
        self._torsion_longitudinal_block(t)
        if not critical:
            if self.profile.key == "Audit" and transverse_resistance_available:
                overall = presentation.torsion_assessment_status(t, input_payload=self.inp)
                self._h2("Retained torsion component evidence")
                self._status_block("Overall torsion status: " + _html_escape(overall), overall)
                self._small(
                    "The tables document the calculated tube geometry, "
                    "wall bounds and component quantities. The longitudinal "
                    "reinforcement assessment and its stated requirements remain applicable."
                )
                if t.get("subdivided"):
                    self._subtube_evidence_tables(t)
                elif (tube.get("wall_evidence") or {}).get("complete") is True:
                    self._single_tube_evidence_tables(t)
                else:
                    self._small("Complete retained wall evidence is unavailable. Recalculate this case.")
            self._small(
                "The complete torsion worked example is published in Audit only for the "
                "governing utilization across all plastic cases."
            )
            return
        self._small(
            "All calculated torsion cases remain in the results overview. The "
            "complete torsion worked example is published in Audit only for the governing "
            "utilization across all plastic cases."
        )
        self._small(f"Torsional cracking uses the entered gamma<sub>ct</sub> = {_fmt(t.get('gamma_ct'), 3)}.")
        self._small("f<sub>ctd</sub> = f<sub>ctk,0.05</sub>/gamma<sub>ct</sub> = "
                    f"{_fmt(t.get('fctd'), 3)} MPa.")
        if t.get("subdivided"):
            self._h2("Sub-tubes (compound section, 6.3.1(3))")
            self._subtube_section(t)
            return
        primary = t.get("primary")
        retained = {
            name: primary.get(name) if isinstance(primary, Mapping) else None
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
                "One or more selected torsion terms are unavailable. Recalculate "
                "before issuing the report."
            )
            return
        angle = retained["angle_selection"]
        steel = retained["steel_resistance"]
        strut = retained["strut_resistance"]
        resistance = retained["resistance_selection"]
        cracking = retained["cracking_resistance"]
        longitudinal = retained["longitudinal_reinforcement"]
        self._single_tube_evidence_tables(t)
        shared_angle = t.get("member_angle_selection") or {}
        if shared_angle:
            self._small(f"Selected common member angle: cot theta = {_fmt(shared_angle.get('cot'), 4)}.")
            self._small(f"Selection interval: [{_fmt(shared_angle.get('cot_min'), 3)}, {_fmt(shared_angle.get('cot_max'), 3)}].")
            self._small("Governing checks: " + _html_escape(', '.join(shared_angle.get('governing_objectives') or ()) or 'not identified') + ".")
        else:
            self._small(f"Unconstrained torsion-resistance angle: cot theta = {_fmt(angle.get('cot_unconstrained'), 4)}.")
            self._small(f"Entered interval: [{_fmt(angle.get('cot_min'), 3)}, {_fmt(angle.get('cot_max'), 3)}].")
            self._small(f"Selected angle: cot theta = {_fmt(angle.get('cot'), 4)} ({_html_escape(angle.get('selection'))}).")
        if self.figures:
            self._fig(viz.tube_figure(self.inp["outer"], self.inp.get("holes"),
                                      tube["tef"], ak_m2=tube["Ak"], report_labels=True), 120, 100)
        if t.get("n_prestress"):
            self._small(f"alpha<sub>cw</sub> uses sigma<sub>cp</sub> = {_fmt(t['sigma_cp'], 3)} MPa.")
            self._small(f"This stress includes axial N and tendon precompression of {_fmt(t['n_prestress'], 3)} kN. The tendon precompression comes from the prestress initial strain.")
        if t.get("nu_v_detailing"):
            self._small('The selected detailing condition raises the strut factor from nu<sub>t</sub> to nu<sub>v</sub>:')
            self._small('nu = nu<sub>v</sub>.')
            self._small('DK NA Figur 5.100 NA requires closed stirrups around the periphery and distributed longitudinal steel on both faces.')
            self._small('The overall longitudinal verification also applies to this selected detailing condition.')
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
                   f"(governed by {_report_resistance_governing_label(resistance['governs'])})")
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
        component_verdict = _demand_resistance_verdict(viz.util_ok(util))
        self._h2("Resistance-component utilization and longitudinal steel")
        self._formula("T<sub>Ed</sub> / T<sub>Rd</sub>",
                      equation_key="torsion.utilisation",
                      subst=f"{_fmt(t['t_ed'], 3)} / {_fmt(t['trd'], 3)}",
                      result=(f"{util_txt}  (transverse/strut component "
                              f"{component_verdict})"))
        self._formula(
            "&#8721;A<sub>sl</sub> = T<sub>Ed</sub> u<sub>k</sub> cot theta / "
            "(2 A<sub>k</sub> f<sub>yd</sub>)",
            equation_key="torsion.longitudinal-steel",
            ref="EN 1992-1-1 (6.28)",
            subst=f"{_fmt(longitudinal['numerator'], 6)} / "
                  f"{_fmt(longitudinal['denominator'], 6)} &#183; 1000",
            result=f"&#8721;A<sub>sl</sub> = "
                   f"{_fmt(longitudinal['asl_required_mm2'], 0)} mm<sup>2</sup> "
                   "(required beyond bending demand)")
        self._small(
            "Overall torsion status: <b>"
            + presentation.torsion_assessment_status(t, input_payload=self.inp)
            + "</b>. "
            + _html_escape(presentation.torsion_assessment_note(t, input_payload=self.inp))
            + "."
        )
        self._small("The concrete-strut and cracking-resistance substitutions use thickness in m and strength in MPa. Their factor of 1000 converts MN&#183;m to kN&#183;m.")
        self._small("The stirrup-resistance substitution uses A<sub>sw</sub>/s in mm<super>2</super>/mm, A<sub>k</sub> in m<super>2</super> and f<sub>ywd</sub> in MPa. This combination gives kN&#183;m directly.")
        self._small('The A<sub>sl</sub> substitution uses torque in kN&#183;m, lengths in m and strength in MPa. Its factor of 1000 gives area in mm<sup>2</sup>.')
        self._small('For area alone, 1 m<sup>2</sup> = 10<super>6</super> mm<sup>2</sup>.')

    def _elastic_state_tables(self, title, state):
        """Publish one retained Ec=1 state without repeating the elastic solve."""

        self._h2(title)
        plane = state["raw_stress_plane"]
        self._table(
            [["Coefficient", "Value", "Unit"],
             ["sigma<sub>0</sub>", _fmt(plane["sigma0_kpa"], 9), "kN/m<super>2</super>"],
             ["d sigma / dx", _fmt(plane["gradient_x_kpa_per_m"], 9), "kN/m<super>3</super>"],
             ["d sigma / dy", _fmt(plane["gradient_y_kpa_per_m"], 9), "kN/m<super>3</super>"]],
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
        matrix_start = len(self.flow)
        self._small('Final transformed equilibrium matrix J:', keep_with_next=True)
        self._table(
            matrix_rows,
            [31 * mm, 43 * mm, 43 * mm, 43 * mm],
            font=7.0,
            keep=False,
        )
        self._small('The N row has column units m<super>2</super>, m<super>3</super> and m<super>3</super>.')
        self._small('The M<sub>x</sub> and M<sub>y</sub> rows have column units m<super>3</super>, m<super>4</super> and m<super>4</super>.')
        self._small('The reference-stress plane has coefficient units kN/m<super>2</super> and kN/m<super>3</super>. Matrix multiplication gives N in kN and moments in kN&#183;m.')
        self._keep_from(matrix_start)
        self._table(
            [["Resultant", "Target", "Internal", "Residual", "Unit"],
             ["N", _fmt(equilibrium["target"]["n"], 9),
              _fmt(equilibrium["internal"]["n"], 9),
              _fmt_sig(equilibrium["residual"]["n"], 9), "kN"],
             ["Mx", _fmt(equilibrium["target"]["mx"], 9),
              _fmt(equilibrium["internal"]["mx"], 9),
              _fmt_sig(equilibrium["residual"]["mx"], 9), "kNm"],
             ["My", _fmt(equilibrium["target"]["my"], 9),
              _fmt(equilibrium["internal"]["my"], 9),
              _fmt_sig(equilibrium["residual"]["my"], 9), "kNm"]],
            [29 * mm, 37 * mm, 37 * mm, 37 * mm, 20 * mm],
            font=7.0,
            keep=False,
        )
        tolerance = equilibrium.get("relative_tolerance")
        self._small(f"Converged after {state.get('iterations', 0)} Newton iterations.")
        self._small(f"Normalized residual = {_fmt_sig(equilibrium['normalised_residual'], 9)}."
                    + (f" Tolerance = {_fmt_sig(tolerance, 9)}." if tolerance is not None
                       else " Direct uncracked linear solution. No Newton tolerance applies."))
        self._small("The normalized residual uses the maximum of the numerical [kN, kN&#183;m, kN&#183;m] components. It is not a norm with consistent physical units.")
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
                "The converged elastic states are unavailable. Recalculate before "
                "issuing the report."
            )
            return

        if self.profile.key == "Standard":
            self._small(
                "Method: cracked-section elastic equilibrium with long-term and "
                "instantaneous response, including retained prestress neutralization. "
                "Concrete occupied by reinforcement is deducted. "
                "The state-by-state calculation is in Audit."
            )
            return

        self._p("The elastic solves use an E<sub>c</sub> = 1 reference-stress plane. The tables give stress-plane coefficients, not physical strain or curvature.")
        self._p("Convert the reference stress and concrete modulus to consistent units before calculating strain.")
        self._p("Instantaneous strain uses the entered concrete modulus E<sub>c</sub>. LONG strain uses the effective modulus E<sub>c,eff</sub> = E<sub>c</sub>/(1 + phi).")
        self._p("TOTAL compatible strain includes the instantaneous strain and the retained long-term deformation. At each point, it equals:")
        self._p("(sigma<sub>ref,inst</sub> + phi sigma<sub>ref,long</sub>)/E<sub>c</sub>.")
        self._p("Here, sigma<sub>ref,inst</sub> and sigma<sub>ref,long</sub> are the reference stresses at that point in the instantaneous and long-term states.")

        long_plane, long_eq, long_matrix = self._elastic_state_tables(
            "Step 1 - converged long-term state", states["long_term"]
        )
        self._formula(
            "sigma<sub>ref</sub>(x,y) = sigma<sub>0</sub> + g<sub>x</sub>x + "
            "g<sub>y</sub>y",
            equation_key="elastic.long.stress-plane",
            ref="Sector cracked-section reference-stress formulation with E<sub>c</sub> = 1.",
            subst=(f"= {_fmt(long_plane['sigma0_kpa'], 9)} + "
                   f"{_fmt(long_plane['gradient_x_kpa_per_m'], 9)}x + "
                   f"{_fmt(long_plane['gradient_y_kpa_per_m'], 9)}y"),
            result="Long-term reference-stress plane (x and y in m).",
        )
        self._formula(
            "N<sub>int</sub> = J<sub>N</sub> q",
            equation_key="elastic.long.equilibrium-n",
            ref="Final transformed-section equilibrium row.",
            subst="= " + self._matrix_substitution(long_matrix[0], long_plane),
            result=(f"N<sub>int</sub> = {_fmt(long_eq['internal']['n'], 9)} kN; "
                    f"target = {_fmt(long_eq['target']['n'], 9)} kN; "
                    f"residual = {_fmt(long_eq['residual']['n'], 9)} kN"),
        )
        self._formula(
            "M<sub>x,int</sub> = J<sub>Mx</sub> q",
            equation_key="elastic.long.equilibrium-mx",
            ref="Final transformed-section equilibrium row.",
            subst="= " + self._matrix_substitution(long_matrix[1], long_plane),
            result=(f"M<sub>x,int</sub> = {_fmt(long_eq['internal']['mx'], 9)} kNm; "
                    f"target = {_fmt(long_eq['target']['mx'], 9)} kNm; "
                    f"residual = {_fmt(long_eq['residual']['mx'], 9)} kNm"),
        )
        self._formula(
            "M<sub>y,int</sub> = J<sub>My</sub> q",
            equation_key="elastic.long.equilibrium-my",
            ref="Final transformed-section equilibrium row.",
            subst="= " + self._matrix_substitution(long_matrix[2], long_plane),
            result=(f"M<sub>y,int</sub> = {_fmt(long_eq['internal']['my'], 9)} kNm; "
                    f"target = {_fmt(long_eq['target']['my'], 9)} kNm; "
                    f"residual = {_fmt(long_eq['residual']['my'], 9)} kNm"),
        )

        nl = superposition["long_term_modular_ratio"]
        ns = superposition["short_term_modular_ratio"]
        factor = superposition["long_term_reduction_factor"]
        self._h2("Step 2 - neutralize the long-term concrete stress")
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
            "Step 3 - converged instantaneous combined state",
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
            ref="Sector cracked-section reference-stress formulation with E<sub>c</sub> = 1.",
            subst=(f"= {_fmt(instant_plane['sigma0_kpa'], 9)} + "
                   f"{_fmt(instant_plane['gradient_x_kpa_per_m'], 9)}x + "
                   f"{_fmt(instant_plane['gradient_y_kpa_per_m'], 9)}y"),
            result="Instantaneous combined reference-stress plane (x and y in m).",
        )
        self._formula(
            "N<sub>int</sub> = J<sub>N</sub> q",
            equation_key="elastic.instantaneous.equilibrium-n",
            ref="Final transformed-section equilibrium row.",
            subst="= " + self._matrix_substitution(instant_matrix[0], instant_plane),
            result=(f"N<sub>int</sub> = {_fmt(instant_eq['internal']['n'], 9)} kN; "
                    f"target = {_fmt(instant_eq['target']['n'], 9)} kN; "
                    f"residual = {_fmt(instant_eq['residual']['n'], 9)} kN"),
        )
        self._formula(
            "M<sub>x,int</sub> = J<sub>Mx</sub> q",
            equation_key="elastic.instantaneous.equilibrium-mx",
            ref="Final transformed-section equilibrium row.",
            subst="= " + self._matrix_substitution(instant_matrix[1], instant_plane),
            result=(f"M<sub>x,int</sub> = {_fmt(instant_eq['internal']['mx'], 9)} kNm; "
                    f"target = {_fmt(instant_eq['target']['mx'], 9)} kNm; "
                    f"residual = {_fmt(instant_eq['residual']['mx'], 9)} kNm"),
        )
        self._formula(
            "M<sub>y,int</sub> = J<sub>My</sub> q",
            equation_key="elastic.instantaneous.equilibrium-my",
            ref="Final transformed-section equilibrium row.",
            subst="= " + self._matrix_substitution(instant_matrix[2], instant_plane),
            result=(f"M<sub>y,int</sub> = {_fmt(instant_eq['internal']['my'], 9)} kNm; "
                    f"target = {_fmt(instant_eq['target']['my'], 9)} kNm; "
                    f"residual = {_fmt(instant_eq['residual']['my'], 9)} kNm"),
        )

        if elements:
            element = elements[0]
            self._h2("Step 4 - combine the element stress components")
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
            self._p(f"The section is <b>{state}</b>. This classification is the governing result from the long-term and total actions.")
            self._p(f"Neutral-axis intercepts: x<sub>na</sub> = {_fmt(el['na_x']*_MM, 3)} mm; y<sub>na</sub> = {_fmt(el['na_y']*_MM, 3)} mm.")
        else:
            self._p("There is no verified cracking classification or cracked/uncracked state.")
            self._p(f"Diagnostic neutral-axis intercepts: x<sub>na</sub> = {_fmt(el['na_x']*_MM, 3)} mm; y<sub>na</sub> = {_fmt(el['na_y']*_MM, 3)} mm.")
        ps = (
            (self._base_out.get("prestress_initial") or {}).get(
                "equivalent_action_origin"
            )
        )
        if ps is not None and self.inp.get("tendons"):
            self._p("Tendon prestress is applied through its initial strain. The entered N is the external force only.")
            self._p("Equivalent prestress actions, with N positive in tension:")
            self._p(f"N = {_fmt(ps['n_kn'], 3)} kN.")
            self._p(f"M<sub>x</sub> = {_fmt(ps['mx_knm'], 3)} kN&#183;m.")
            self._p(f"M<sub>y</sub> = {_fmt(ps['my_knm'], 3)} kN&#183;m.")
            self._p("Section and materials gives the prestress-action calculation.")
        if self._selected_family("elastic", self.inp) is not None:
            self._elastic_worked(el)
        else:
            self._small(
                "The complete elastic worked example is published in Audit only for the "
                "governing stress extremum across all elastic cases."
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
                    f"{_fmt(item.get('value'), 3)} MPa; "
                    + _html_escape(elastic_display.output_comparison(
                        self.inp, el, key, item
                    )),
                    _html_escape(item.get("governing") or "-"),
                    item.get("calculation_state") or "NOT CALCULATED",
                ])
            self._table(rows, [55 * mm, 35 * mm, 45 * mm, 35 * mm],
                        font=7.5)
            self._small(
                "Numerical outputs for the actual named Elastic action. No "
                "stress-limit criterion is applied. Percentages compare the displayed "
                "stress with the stated characteristic strength."
            )
        self._section_field_maps(el, family="Elastic")
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
            self._small("Concrete profile: instantaneous stress-plane strain. Markers: TOTAL material strain, including retained long-term deformation and tendon initial strain.")
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
        self._table(
            rows, [55 * mm, 45 * mm] + ([45 * mm] if pc else []),
            caption="Transformed section properties with long-term modular ratios",
        )
        self._small("Transformed (n<sub>l</sub>-weighted) about the centroid; the "
                    "cracked column drops the concrete in tension.")
        # Complete, explicitly typed bar/tendon evidence.
        self._h2("Reinforcement and tendon response")
        self._small('Total is the response to the long and short actions together. Long-term is the response to the long-term actions alone.')
        self._small('Increment (Incr.) = Total - Long-term.')
        self._small('Instantaneous (RST1) is the response after the long-term concrete stress has been neutralized. Tension is positive.')
        element_rows = el.get("elements") or []
        if element_rows:
            rows = [["Element", "Material", "x", "y", "Area", "Strain", "Total",
                     "Long-<br/>term", "Incr.", "Instant."]]
            for row in element_rows:
                rows.append([
                    _html_escape(row["element_id"]),
                    _html_escape(row.get("material_id") or "-"),
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
                        "&#8240;; stresses in MPa.")
        if element_rows:
            self._h2("Stress as percentage of characteristic strength")
            self._small('The percentage is the absolute stress divided by the stated characteristic strength. Actual stress values keep their signs.')
            self._small('Unavailable means that the reference strength or element assignment is missing or invalid. These percentages do not assess compliance.')
            percent_rows = [["Element", "Material", "Reference", "Total",
                             "Long-term", "Increment", "Instant."]]
            for item in elastic_display.element_comparison_rows(self.inp, element_rows):
                percent_rows.append([
                    _html_escape(item["Element"]), _html_escape(item["Material"]),
                    _html_escape(report_notation.symbol(item["Reference"])),
                    *["Unavailable" if item[label] is None else f"{item[label]:.1f}%"
                      for _, label in elastic_display.COMPONENTS],
                ])
            self._table(percent_rows, [22*mm, 20*mm, 25*mm, 25*mm,
                                       26*mm, 26*mm, 26*mm], keep=False)
        corner_rows = el.get("concrete_corners") or []
        if corner_rows:
            self._h2("Concrete corner stress and strain")
            rows = [["Point", "Ring", "Ring point", "x", "y",
                     "Instantaneous<br/>strain", "Concrete stress / f<sub>ck</sub>"]]
            for row in corner_rows:
                rows.append([
                    row["point_no"], row["ring"], row["ring_point_no"],
                    _fmt(row["x_mm"], 1), _fmt(row["y_mm"], 1),
                    _fmt(row["strain_permille"], 5),
                    _fmt(row["stress_mpa"], 3) + " MPa; "
                    + _html_escape(elastic_display.comparison_text(
                        row["stress_mpa"],
                        {"f_ck": getattr(self.inp.get("concrete"), "fck", None)},
                    )),
                ])
            self._table(
                rows,
                [16 * mm, 29 * mm, 20 * mm, 19 * mm, 19 * mm,
                 28 * mm, 29 * mm],
                font=7, keep=False,
                repeat_cols=3,
            )
            self._small('Coordinates are in mm, strain is in &#8240;, and stress is in MPa. Compression is negative.')
            self._small('Cracked concrete carries compression only. Compatible tensile strains remain in the strain plane while tensile stress is zero.')
        rows = [["Quantity", "Value"],
                ["Max concrete compression", f"{_fmt(el.get('max_conc'), 3)} MPa "
                 f"(point {el.get('max_conc_point', '-')})"],
                ["Max steel-element tension", f"{_fmt(el.get('max_steel'), 3)} MPa "
                 f"({_html_escape(el.get('max_steel_element') or 'not in tension')})"]]
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
        comparison_duration = (
            self._selected_crack_comparison.get("duration")
            if publish_comparison
            else None
        )
        if publish_threshold and publish_crack_width:
            heading = "Cracking threshold and governing crack width"
        elif publish_crack_width:
            heading = "Governing crack width"
        elif publish_comparison:
            heading = "Governing crack-width comparison"
        else:
            heading = "Cracking threshold"
        # Leave the chapter's conditional page break outside the measured block.
        threshold_start = len(self.flow) + 1
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
                    "(DS/EN 1992-1-1:2023 &#167;9.2.1)"
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
                    None if prestressed else
                    f"lambda<sub>cr</sub> = {_fmt(lam,3)}"
                ),
                note=(
                    None if prestressed else
                    (
                        f"The section is {verdict}. Strictly below 1 means "
                        "cracked. A value of 1 or above means uncracked."
                        if valid else
                        "INVALID; no verified cracking classification"
                    )
                ),
            )
            if not publish_crack_width:
                self._keep_measured_calculation_from(threshold_start)
            if prestressed:
                self._small('Locked-in prestress stays fixed. If a prestress-only fiber stress exceeds f<sub>ct,eff</sub>, lambda<sub>cr</sub> = 0.')
                self._small('Otherwise, only the external N and M are scaled. The smallest positive fiber solution governs.')
                self._small('The result is infinity if no fiber gains tension.')
                self._small(f"Calculated sigma<sub>ct,I</sub> = {_fmt(el.get('sigma_ct'), 3)} MPa.")
                self._small(f"Calculated lambda<sub>cr</sub> = {_fmt(lam,3)}.")
                self._small(f"The section is {verdict}. Below 1 means cracked. A value of 1 or above means uncracked." if valid else "INVALID.")
            self._small('This is the critical threshold across the current, converged elastic cases.')
            self._small('Within each case, the smaller cracking factor from the sustained and total states governs. Cracking in either state is retained in the assessment.')
        if not publish_crack_width:
            assessments = el.get("crack_output") or {}
            if not isinstance(assessments, Mapping):
                assessments = {}
            for duration in ("long_term", "short_term"):
                assessment = assessments.get(duration)
                if isinstance(assessment, Mapping):
                    self._ordinary_crack_assessment(
                        assessment,
                        publish_comparison=(comparison_duration == duration),
                    )
            if (
                el.get("crack") is None
                and el.get("crack_short") is None
                and el.get("crack_coarse") is None
                and el.get("crack_short_coarse") is None
                and not any(
                    str(item.get("reason") or "").strip()
                    for item in assessments.values()
                    if isinstance(item, Mapping)
                )
            ):
                self._small(
                    "The crack-width calculation returned no value. Review the "
                    "calculation state and inputs."
                )
            return
        cl, cs = el.get("crack"), el.get("crack_short")
        clc, csc = el.get("crack_coarse"), el.get("crack_short_coarse")
        no_results = cl is None and cs is None and clc is None and csc is None
        assessments = el.get("crack_output") or {}
        if not isinstance(assessments, Mapping):
            assessments = {}
        for duration, label in (
            ("long_term", "Long-term"),
            ("short_term", "Short-term"),
        ):
            assessment = assessments.get(duration)
            if not isinstance(assessment, Mapping):
                continue
            value = assessment.get("value")
            text = (
                f"{label} crack-width output | w<sub>k</sub> "
                f"{'-' if value is None else _fmt(value, 3) + ' mm'} | "
                f"crack calculation {assessment.get('case') or '-'} | "
                f"element {assessment.get('governing') or '-'}"
            )
            self._p(text)
            self._ordinary_crack_assessment(
                assessment,
                publish_comparison=(comparison_duration == duration),
            )
        if no_results:
            if not any(
                str(item.get("reason") or "").strip()
                for item in assessments.values()
                if isinstance(item, Mapping)
            ):
                self._small(
                    "The crack-width calculation returned no value. Review the "
                    "calculation state and inputs."
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
                    "<b>Worked calculation unavailable.</b> The selected crack-width "
                    "method is missing or unsupported. Recalculate before issuing "
                    "the report."
                )
        self._crack_candidates(selected_cases)
        for crack, label in selected_worked:
            self._crack_worked(crack, label)

    def _ordinary_crack_assessment(self, assessment, *, publish_comparison):
        """Publish one retained user comparison without inferring a code limit."""
        status = str(assessment.get("calculation_state") or "NOT ASSESSED")
        criterion = assessment.get("criterion_mm")
        duration = str(assessment.get("duration") or "").replace("_", "-")
        duration_label = duration.capitalize() if duration else "Duration"
        source = str(assessment.get("criterion_source") or "").strip()
        raw_reason = assessment.get("reason")
        reason = (
            _result_reason(
                raw_reason,
                "crack",
                "report ordinary crack-width reason",
            )
            if raw_reason
            else ""
        )
        if criterion is None:
            self._small(f"Calculation state: {status}. No user-specified crack-width criterion was supplied.")
            self._small("Exposure, durability, prestress category and owner limits are not inferred.")
            if reason:
                self._small(_html_escape(reason))
            return

        if criterion == 0.0:
            self._small(f"{_html_escape(duration_label)} calculation state: {_html_escape(status)}.")
            self._small("The user criterion is 0.000 mm. The calculated width is reported without a limit comparison.")
            if reason:
                self._small(_html_escape(reason))
            return

        self._small(f"{_html_escape(duration_label)} calculation state: {_html_escape(status)}.")
        self._small(f"User-specified criterion = {_fmt(criterion, 3)} mm. Source: {_html_escape(source or 'NOT RETAINED')}.")
        self._small("The comparison uses the user-specified crack-width limit. Exposure and project requirements require separate confirmation.")
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
                "<b>Worked comparison unavailable.</b> The critical "
                "ordinary crack-width comparison is incomplete (missing: "
                + ", ".join(missing)
                + "). Recalculate to restore it."
            )
            return
        self._h2(
            "User-specified crack-width comparison - critical "
            + _html_escape(duration_label.lower())
            + " case"
        )
        self._formula(
            "u<sub>w</sub> = w<sub>k</sub> / w<sub>k,criterion</sub>",
            equation_key="crack.user-limit.comparison",
            ref="User-specified crack-width criterion",
            note=(
                "The largest calculated ordinary crack width is selected; a "
                "smaller width with a tighter criterion cannot govern the "
                "governing comparison."
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
                 ("Mean strain eps<sub>sm</sub>-eps<sub>cm</sub> (&#8240;)", "esm_ecm", 4, 1000.0),
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
        if self.profile.key == "Audit":
            self._h2(f"Crack width worked - governing case ({which})" if which
                     else "Crack width worked (governing element)")
        missing = self._crack_worked_missing_operands(cw)
        if missing:
            self._small(
                "<b>Worked calculation unavailable.</b> The selected crack-width "
                "calculation is incomplete (missing: "
                + _html_escape(", ".join(missing))
                + "). Recalculate before issuing the report."
            )
            return
        self._crack_area_diagram(cw, which)
        if self.profile.key == "Standard":
            self._crack_ratio_basis(cw)
            self._small("Governing crack-width method: "
                        + _html_escape(str(self.out["elastic"].get("crack_code") or "source unavailable")) + ".")
            self._small("The result tables give the retained element result and criterion. Audit gives the numerical worked calculation.")
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
            self._small(f"Crack-width code: {code}.")
            if cw.get("edition") == "2023":
                self._small("Refined control of cracking (&#167;9.2.3) converts the mean crack width to the calculated value with:")
                self._small("k<sub>w</sub> = 1.7.")
                if spacing.get("flexural_factor_method") == "formula-9.20-direct-tension":
                    self._small("For direct tension, the curvature factor is:")
                    self._small(f"k<sub>1/r</sub> = {_fmt(cw['k1_r'], 3)}.")
                else:
                    self._small("The curvature factor is:")
                    self._small("k<sub>1/r</sub> = (h-x)/(h-a<sub>y</sub>-x).")
                self._small("The lower bound for the mean strain is:")
                self._small("(1 - k<sub>t</sub>)&#183;sigma<sub>s</sub>/E<sub>s</sub>.")
            elif "DK NA" in code:
                self._small("The cover-dependent coefficient is (&#167;7.3.4(3)):")
                self._small("k<sub>3</sub> = 3.4&#183;(25/c)<super>2/3</super>.")
                if coarse:
                    self._small("For the coarse crack system (&#167;7.3.4(1)), A<sub>c,eff</sub> is a band at the tension face.")
                    self._small("Its centroid matches the tension reinforcement (figure 7.100 NA). The calculated w<sub>k</sub> is halved.")
                else:
                    self._small("The (h-x)/3 term in h<sub>c,ef</sub> applies only to slabs and prestressed members.")
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
                    "bars not at close centers: selected because nearest spacing "
                    f"{_fmt(spacing.get('nearest_neighbour_spacing'), 3)} mm "
                    "exceeds 5(c + phi/2) = "
                    f"{_fmt(spacing.get('close_spacing_limit'), 3)} mm"
                ),
                subst=(
                    "= 1.3 &#183; "
                    f"{_fmt(float(spacing.get('tension_zone_depth', 0.0)) * _MM, 8)} mm"
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
                    "bars at close centers: nearest spacing "
                    f"{_fmt(spacing.get('nearest_neighbour_spacing'), 3)} mm "
                    "; close-center threshold 5(c + phi/2) = "
                    f"{_fmt(spacing.get('close_spacing_limit'), 3)} mm; "
                    "Formula (7.11) selected"
                ),
                subst=(
                    f"= {_fmt(spacing.get('k3_used'), 8)} &#183; "
                    f"{_fmt(spacing.get('cover'), 8)} + "
                    f"{_fmt(spacing.get('k1'), 8)} &#183; "
                    f"{_fmt(spacing.get('k2'), 8)} &#183; "
                    f"{_fmt(spacing.get('k4'), 8)} &#183; "
                    f"{_fmt(spacing.get('diameter'), 8)} / "
                    f"{_fmt_crack_ratio(spacing.get('rho_p_eff'))}"
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
                    f"{_fmt(cw.get('esm_ecm',0)*1000,4)} &#8240;",
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
            ))
            direct_area = area.get("record_kind") == "CrackEffectiveArea2023Direct"
            direct_method = spacing.get("flexural_factor_method") == "formula-9.20-direct-tension"
            if direct_area or direct_method:
                if not (direct_area and direct_method
                        and spacing.get("selected_candidate") == "formula-9.15"):
                    missing.append("spacing.direct-tension-branch")
                # Native uniform tension retains explicit None for the infinite cap.
                for key in ("cap_tension_depth", "cap_spacing"):
                    if key not in spacing or spacing[key] is not None:
                        missing.append("spacing." + key + "-direct-tension")
            else:
                require(spacing, "spacing.", ("cap_tension_depth", "cap_spacing"))
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

    def _crack_ratio_basis(self, cw):
        """Identify the retained reinforcement numerator beside the area diagram."""
        modern = cw.get("edition") == "2023"
        basis = (cw.get("effective_reinforcement_2023") if modern
                 else cw.get("governing_candidate")) or {}
        tendon_key = "ap_eff_weighted" if modern else "ap_eff"
        try:
            steel, tendon, area, ratio = (report_diagrams._finite(basis.get(key))
                                         for key in ("as_eff", tendon_key, "ac_eff", "rho_p_eff"))
            if min(steel, tendon, ratio) < 0 or area <= 0:
                raise report_diagrams.DiagramUnavailable("The effective reinforcement basis is invalid.")
            if not math.isclose((steel + tendon) / area, ratio, rel_tol=1e-8, abs_tol=1e-10):
                raise report_diagrams.DiagramUnavailable("The retained reinforcement ratio and its areas disagree.")
            if not (math.isclose(area, report_diagrams._finite(cw.get("ac_eff")), rel_tol=1e-8, abs_tol=1e-10)
                    and math.isclose(ratio, report_diagrams._finite(cw.get("rho_p_eff")), rel_tol=1e-8, abs_tol=1e-10)):
                raise report_diagrams.DiagramUnavailable("The reinforcement basis and selected crack result disagree.")
        except report_diagrams.DiagramUnavailable as error:
            self._small("Effective reinforcement basis unavailable. " + _html_escape(str(error)))
            return
        self._h2("Effective reinforcement ratio basis")
        self._table([
            ["Retained quantity", "Value"],
            ["Effective bar area A<sub>s,eff</sub>", _fmt(steel * 1e6, 3) + " mm<super>2</super>"],
            [("Bond-weighted tendon area" if modern else "Effective tendon area A<sub>p,eff</sub>"),
             _fmt(tendon * 1e6, 3) + " mm<super>2</super>"],
            ["Effective concrete area A<sub>c,eff</sub>", _fmt(area * 1e6, 3) + " mm<super>2</super>"],
            ["Effective reinforcement ratio rho<sub>p,eff</sub>", _fmt_crack_ratio(ratio)],
        ], [110 * mm, 60 * mm])
        self._small("The ratio is the sum of the two effective reinforcement areas divided by the effective concrete area.")
        if modern:
            self._small("The tendon contribution includes the retained bond weighting for each tendon, from Formula (9.12).")

    def _crack_area_diagram(self, cw, which):
        """Keep the retained effective area and its interpretation together."""
        if not self.figures:
            return
        elastic = self.out.get("elastic") or {}
        state_key = "instantaneous_combined" if "short-term" in which.lower() else "long_term"
        try:
            if elastic.get("field_context") != section_fields.context_signature(self.inp, "Elastic"):
                raise report_diagrams.DiagramUnavailable("The elastic geometry and action identity require recalculation.")
            figure = report_diagrams.crack_effective_area_figure(
                self.inp, cw, (elastic.get("accepted_states") or {}).get(state_key),
                title=f"Effective crack-control area: {which or 'governing state'}",
            )
        except report_diagrams.DiagramUnavailable as error:
            self._small("Effective-area diagram unavailable. " + _html_escape(str(error)))
            return
        start = len(self.flow)
        self._fig(figure, 170, 125, caption=(
            "Effective concrete area and reinforcement included in the crack-width calculation. "
            "The governing element has the largest calculated crack width."
        ))
        self._small("Circles identify bars. Diamonds identify tendons. Filled markers are inside the effective area; open markers identify other reinforcement.")
        self._small("Marker size does not represent area. The element schedule gives the IDs and areas.")
        self._keep_from(start)

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
                ref="DS/EN 1992-1-1:2023 Figure 9.3",
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
                ref="DS/EN 1992-1-1:2023 Figure 9.3",
                subst=(
                    f"= {_fmt(area.get('width'), 6)} &#183; {_fmt(area.get('height'), 6)} - "
                    f"{_fmt(area.get('inner_width'), 6)} &#183; {_fmt(area.get('inner_height'), 6)}"
                ),
                result=f"A<sub>c,eff</sub> = {_fmt(area.get('ac_eff'), 6)} m<super>2</super>",
            )
        else:
            self._small(
                "<b>Effective-area calculation unavailable.</b> Required "
                "effective-area terms are missing. Recalculate before issuing "
                "the report."
            )

        if cw.get("edition") == "2023":
            reinforcement = cw.get("effective_reinforcement_2023") or {}
            if not reinforcement:
                self._small(
                    "<b>Effective reinforcement ratio unavailable.</b> The "
                    "required Formula (9.12) terms are missing."
                )
                return
            self._formula(
                "rho<sub>p,eff</sub> = (A<sub>s,eff</sub> + "
                "sum xi<sub>1,j</sub>A<sub>p,j</sub>) / A<sub>c,eff</sub>",
                equation_key="crack.effective-reinforcement.ratio",
                equation_variant="2023",
                ref="DS/EN 1992-1-1:2023 Formula (9.12)",
                subst=(
                    f"= ({_fmt(reinforcement.get('as_eff'), 8)} + "
                    f"{_fmt(reinforcement.get('ap_eff_weighted'), 8)}) / "
                    f"{_fmt(reinforcement.get('ac_eff'), 8)}"
                ),
                result=f"rho<sub>p,eff</sub> = {_fmt_crack_ratio(reinforcement.get('rho_p_eff'))}",
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
                result=f"rho<sub>p,eff</sub> = {_fmt_crack_ratio(candidate.get('rho_p_eff'))}",
            )

    def _crack_mean_strain_worked(self, mean, *, edition):
        lower_label = "0.6" if edition == "2005" else "(1 - k<sub>t</sub>)"
        symbolic = (
            "eps<sub>sm</sub> - eps<sub>cm</sub> = max{[sigma<sub>s</sub> - "
            "(k<sub>t</sub>f<sub>ct,eff</sub>/rho<sub>p,eff</sub>) &#183; "
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
                ref="DS/EN 1992-1-1:2023 Formula (9.11)",
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
        """The DS/EN 1992-1-1:2023 refined crack-width worked example (9.2.3)."""
        spacing = candidate["spacing_operands"]
        mean = candidate["mean_strain_operands"]
        cap = spacing.get("cap_spacing")
        direct_tension = (
            spacing.get("flexural_factor_method") == "formula-9.20-direct-tension"
        )
        expression = (
            "s<sub>r,m,cal</sub> = 1.5&#183;c + (k<sub>fl</sub>&#183;k<sub>b</sub>/7.2)"
            "&#183;phi/rho<sub>p,eff</sub>"
        )
        if not direct_tension:
            expression += " &lt;= (1.3/k<sub>w</sub>)&#183;(h-x)"
        self._formula(
            expression,
            equation_key="crack.2023.spacing",
            ref="DS/EN 1992-1-1:2023 &#167;9.2.3, Eq (9.15)",
            note=(
                f"k<sub>fl</sub> method: {spacing.get('flexural_factor_method', '-')}; "
                f"selected: {spacing.get('selected_candidate', '-')}"
                + (
                    "; no finite tension-zone cap; h-x applies to the bending cap"
                    if direct_tension else ""
                )
            ),
            subst=(
                f"formula = {_fmt(spacing.get('cover_coefficient'), 8)} &#183; "
                f"{_fmt(spacing.get('cover'), 8)} + "
                f"({_fmt(spacing.get('flexural_factor'), 8)} &#183; "
                f"{_fmt(spacing.get('bond_factor_kb'), 8)} / "
                f"{_fmt(spacing.get('diameter_ratio_divisor'), 8)}) &#183; "
                f"{_fmt(spacing.get('diameter'), 8)} / "
                f"{_fmt_crack_ratio(spacing.get('rho_p_eff'))} = "
                f"{_fmt(spacing.get('formula_spacing'), 3)} mm"
                + (
                    f"; cap = (1.3 / {_fmt(cw.get('kw'), 3)}) &#183; "
                    f"{_fmt(float(spacing['cap_tension_depth']) * _MM, 8)} = "
                    f"{_fmt(cap, 3)} mm"
                    if cap is not None else ""
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
                  f"{_fmt(cw.get('esm_ecm',0)*1000,4)} &#8240;",
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
                "<b>Worked calculation unavailable.</b> The Formula "
                "7.100 NA result is incomplete (missing: "
                + ", ".join(missing)
                + "). Recalculate to restore it."
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
        self._small('Project inputs define applicability, permitted width, reinforcement surface, tensile strength and both effective tension areas.')
        self._small('The selected ordinary crack-width result supplies the reinforcement terms for the heightened check.')
        self._small('Record restraint, watertightness, exposure and owner criteria in the project basis.')
        rows = [
            ["Input", "Value"],
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
                "Effective tensile strength f<sub>ct,eff</sub>",
                f"{_fmt(result['effective_tensile_strength_mpa'], 3)} MPa",
            ],
            [
                "Auto-derived reinforcement modulus E<sub>sk</sub>",
                f"{_fmt(result['reinforcement_modulus_mpa'], 1)} MPa; "
                "governing materials "
                + _html_escape(", ".join(
                    str(value)
                    for value in result["modulus_governing_material_ids"]
                )),
            ],
            [
                "Permitted crack width w<sub>k</sub>",
                f"{_fmt(result['permitted_crack_width_mm'], 3)} mm",
            ],
            [
                "Auto-derived provided reinforcement area A<sub>s,prov</sub>",
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
                    "A<sub>c,eff</sub> (mm<super>2</super>)",
                    "rho<sub>s,min</sub>",
                    "A<sub>s,req</sub> (mm<super>2</super>)",
                    "A<sub>s,req</sub> / A<sub>s,prov</sub>",
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
        self._h2("Reinforcement source details")
        self._table(
            [
                ["Element", "Material", "Area (mm<super>2</super>)", "phi (mm)", "E<sub>s</sub> (MPa)"],
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
                "m<sub>s</sub> = 1 for ribbed reinforcement. For smooth "
                "reinforcement, m<sub>s</sub> = &#8730;2."
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
                "Comparison with the ordinary crack-width reinforcing-bar area; this "
                "covers only the selected section reinforcement."
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
                    f"{status} - {_html_escape(governing_name)} | utilization "
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
            visible_warning = engineer_messages.error_detail(
                warning,
                fallback=_REPORT_RESULT_WARNING,
                context="fatigue report warning",
            )
            self._small("<b>Review:</b> " + _html_escape(visible_warning))
        if errors:
            self._p(
                "Fatigue input was incomplete or invalid at calculation time. "
                "No fatigue resistance verdict has been issued."
            )
            for error in errors:
                visible_error = engineer_messages.error_detail(
                    error,
                    fallback=_REPORT_RESULT_ERROR,
                    context="fatigue report error",
                )
                self._small("<b>Input error:</b> " + _html_escape(visible_error))
            return

        self._h2("Basis and references")
        basis = payload.get("basis") or {}
        factors = payload.get("partial_factors") or {}
        concrete_parameters = payload.get("concrete_parameters") or {}
        basis_rows = [
            ["Item", "Value"],
            ["Design basis", _html_escape(str(
                payload.get("basis_label") or payload.get("edition") or "-"
            ))],
            ["Method scope", _html_escape(str(
                payload.get("basis_disclosure") or "-"
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
                "Check", "Calculation", "Source", "Scope disclosure",
            ]]
            for key in evidence_keys:
                binding = bindings.get(key)
                if isinstance(binding, Mapping):
                    capability = fatigue_presentation.capability_display_label(
                        binding.get("capability")
                    )
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
        summary_rows = fatigue_presentation.spectrum_rows(payload)
        self._h2("Spectrum summary")
        rows = [[
            "Spectrum", "Status", "Governing",
            "Max Miner D", "Max yield / proof", "Governing util.",
            "Search upper D",
        ]]
        rows.extend([
            [
                _html_escape(row["spectrum"]),
                row["status"],
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
            [25 * mm, 18 * mm, 34 * mm, 21 * mm, 25 * mm, 25 * mm, 22 * mm],
            font=9,
            keep=False,
            caption="Spectrum results",
        )
        self._small(
            "Each spectrum has its own Miner sum. Governing utilization is the "
            "maximum applicable simplified screen, Miner range, yield/proof "
            "stress or concrete result."
        )
        self._table(
            [["Spectrum", "Bins", "Steel elements", "Concrete fibers"],
             *[[_html_escape(row["spectrum"]), row["bins"],
                row["reinforcement_elements"], row["concrete_fibres"]]
               for row in summary_rows]],
            [60 * mm, 30 * mm, 40 * mm, 40 * mm],
            font=9,
            keep=False,
            caption="Spectrum calculation counts",
        )

        spectra = fatigue_presentation.items(payload, "spectra")
        reinforcement_example = payload.get("governing_reinforcement_example")
        concrete_example = payload.get("governing_concrete_example")
        retained_screen_rows = [
            (str(fatigue_presentation.value(spectrum, "spectrum_name", "-")), row)
            for spectrum in spectra
            for row in fatigue_presentation.reinforcement_rows(spectrum)
        ]
        if self.profile.key != "Audit":
            if isinstance(reinforcement_example, Mapping):
                retained_screen_rows = [
                    (spectrum_name, row)
                    for spectrum_name, row in retained_screen_rows
                    if spectrum_name == reinforcement_example.get("spectrum_name")
                    and row["element_id"] == reinforcement_example.get("element_id")
                ]
            else:
                # A missing converged governing example must not erase retained
                # diagnostics. Publish every invalid screen without promoting one
                # of them to a governing result or manufacturing a verdict.
                retained_screen_rows = [
                    (spectrum_name, row)
                    for spectrum_name, row in retained_screen_rows
                    if row["screen_status"] == "INVALID"
                ]
        if checks.get("reinforcement") and retained_screen_rows:
            self._h2("Simplified reinforcement stress-range screens")
            rows = [[
                "Spectrum", "Element", "Status", "Detail class", "Basis",
                "Range / limit", "Util.", "Governing bin",
            ]]
            rows.extend([
                [
                    _html_escape(spectrum_name),
                    _html_escape(row["element_id"]),
                    _html_escape(row["screen_status"]),
                    _html_escape(row["screen_detail_class"]),
                    _fatigue_report_label(row["screen_range_basis"], "range_basis"),
                    (
                        _fmt(row["screen_range_mpa"], 3)
                        + " / "
                        + _fmt(row["screen_threshold_mpa"], 3)
                        + " MPa"
                    ),
                    _pct(row["screen_utilisation"]),
                    _html_escape(row["screen_governing_bin"]),
                ]
                for spectrum_name, row in retained_screen_rows
            ])
            self._table(
                rows,
                [20 * mm, 17 * mm, 22 * mm, 28 * mm, 24 * mm,
                 21 * mm, 12 * mm, 21 * mm],
                font=5.2,
                keep=False,
                repeat_cols=2,
            )
            for spectrum_name, row in retained_screen_rows:
                self._small(
                    "<b>"
                    + _html_escape(spectrum_name)
                    + " / "
                    + _html_escape(row["element_id"])
                    + ":</b> "
                    + _html_escape(
                        _result_reason(
                            row["screen_reason"],
                            "fatigue",
                            "report fatigue-screen summary reason",
                        )
                        if row["screen_reason"]
                        else "-"
                    )
                    + (
                        " <b>Reference:</b> "
                        + _html_escape(row["screen_source"])
                        if row["screen_source"]
                        else ""
                    )
                )

        input_records = fatigue_inputs.spectrum_records(
            self._base_inp.get(fatigue_inputs.SPECTRUM_TABLE_KEY)
        )
        selected_spectrum_names = {
            str(selection.get("spectrum_name"))
            for selection in (reinforcement_example, concrete_example)
            if isinstance(selection, Mapping) and selection.get("spectrum_name")
        }
        if checks.get("reinforcement") and not reinforcement_example:
            self._small(
                "<b>Worked example unavailable:</b> no converged governing "
                "reinforcement fatigue result is available."
            )
        if checks.get("concrete") and not concrete_example:
            self._small(
                "<b>Worked example unavailable:</b> no converged governing "
                "concrete fatigue result is available."
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
            spectrum_status = fatigue_presentation.result_status(spectrum)
            self._h2("Spectrum - " + _html_escape(spectrum_name))
            source_link = self._project_source_link("Fatigue", spectrum_name)
            if source_link:
                self._p(source_link.removeprefix(" | "))
            self._status_block(
                f"Overall spectrum: {spectrum_status} - governing utilization "
                f"{_pct(fatigue_presentation.evidence_number(
                    fatigue_presentation.value(spectrum, 'utilisation')
                ))} | {_html_escape(
                    fatigue_presentation.criterion_breakdown(spectrum)
                )}",
                spectrum_status,
            )
            # The following tables publish their own local outcomes. Repeating
            # the overall reinforcement result above concrete values obscures
            # their distinct assessment scope.
            self._table_assessment_context = None

            if self.figures:
                self._fig(
                    _report_fatigue_utilization_map(
                        self._base_inp.get("outer", []),
                        self._base_inp.get("holes", []),
                        self._base_inp.get("bar_elements", []),
                        self._base_inp.get("tendon_elements", []),
                        spectrum,
                        title=f"Fatigue utilization - {spectrum_name}",
                    ),
                    150,
                    105,
                    caption=(
                        f"Fatigue utilization - {spectrum_name}"
                        + (
                            ". Stars identify adaptive concrete search points."
                            if fatigue_presentation.value(
                                spectrum, "concrete_search"
                            ) is not None else ""
                        )
                    ),
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
                    _input_table_symbol(table_key, "n_long_ed_kn").replace(
                        ",long</sub>", ",<br/>long</sub>"
                    ),
                    _input_table_symbol(table_key, "mx_long_ed_knm").replace(
                        ",long</sub>", ",<br/>long</sub>"
                    ),
                    _input_table_symbol(table_key, "my_long_ed_knm").replace(
                        ",long</sub>", ",<br/>long</sub>"
                    ),
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
                self._h2("Elastic states used in the fatigue calculation")
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
                governing_id = reinforcement_example.get("element_id")
                published_reinforcement_rows = (
                    reinforcement_rows
                    if audit_detail
                    else [
                        row for row in reinforcement_rows
                        if row["element_id"] == governing_id
                    ]
                )
                self._h2("Reinforcement fatigue")
                rows = [[
                    "Element", "Type", "Detail", "phi", "Shortcut",
                    "Miner D", "Yield / proof util.", "Governing", "Util.",
                    "Status",
                ]]
                rows.extend([
                    [
                        _html_escape(row["element_id"]),
                        _fatigue_report_label(row["kind"], "kind"),
                        _html_escape(row["detail_id"]),
                        f"{_fmt(row['diameter_mm'], 1)} mm",
                        (
                            _html_escape(row["screen_status"])
                            + (
                                "<br/>u = " + _pct(row["screen_utilisation"])
                                if row["screen_utilisation"] is not None
                                else ""
                            )
                        ),
                        _fmt_sig(row["damage"], 6),
                        _pct(row["yield_utilisation"]),
                        _html_escape(row["governing"]),
                        _pct(row["utilisation"]),
                        row["status"],
                    ]
                    for row in published_reinforcement_rows
                ])
                self._table(
                    rows,
                    [20 * mm, 12 * mm, 14 * mm, 13 * mm, 29 * mm,
                     15 * mm, 18 * mm, 25 * mm, 16 * mm, 14 * mm],
                    font=5.2,
                    keep=False,
                    repeat_cols=3,
                )
                result = fatigue_presentation.result_by_element(
                    spectrum, governing_id
                )
                properties = fatigue_presentation.reinforcement_property(
                    payload, governing_id
                )
                if result is not None and properties is not None:
                    screen = (
                        fatigue_presentation.simplified_reinforcement_screen(
                            result
                        )
                    )
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
                    self._h2("Simplified stress-range screen")
                    self._table(
                        [[
                            "Status", "Detail class", "Range basis",
                            "Governing range", "Limit", "Util.",
                            "Governing bin", "Total cycles",
                        ], [
                            _html_escape(screen["status"]),
                            _html_escape(screen["detail_class"]),
                            _fatigue_report_label(screen["range_basis"], "range_basis"),
                            (
                                "-" if screen["governing_range_mpa"] is None
                                else f"{_fmt(screen['governing_range_mpa'], 3)} MPa"
                            ),
                            (
                                "-" if screen["threshold_mpa"] is None
                                else f"{_fmt(screen['threshold_mpa'], 3)} MPa"
                            ),
                            _pct(screen["utilisation"]),
                            _html_escape(screen["governing_bin"]),
                            _fmt_sig(screen["total_cycles"], 8),
                        ]],
                        [25 * mm, 34 * mm, 29 * mm, 23 * mm,
                         19 * mm, 17 * mm, 21 * mm, 22 * mm],
                        font=5.5,
                        keep=False,
                    )
                    self._small(
                        _html_escape(
                            _result_reason(
                                screen["reason"],
                                "fatigue",
                                "report simplified fatigue-screen reason",
                            )
                            if screen["reason"]
                            else "-"
                        )
                        + (
                            "<br/><b>Reference:</b> "
                            + _html_escape(screen["source"])
                            if screen["source"]
                            else ""
                        )
                    )
                    self._small('A passing shortcut governs the stress-range criterion. The complete S-N/Miner result is also reported for review.')
                    self._small('Yield or proof stress has an independent check.')
                    if self.figures:
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
                    if self.figures:
                        self._fig(
                            viz.fatigue_damage_figure(
                                result,
                                title=f"Miner damage - {governing_id}",
                            ),
                            150,
                            82,
                        )
                    all_bin_rows = fatigue_presentation.reinforcement_bin_rows(
                        result
                    )
                    published_bin_rows = all_bin_rows
                    if not audit_detail:
                        selected_bin_name = str(
                            reinforcement_example.get("bin_name") or ""
                        )
                        published_bin_rows = [
                            row for row in all_bin_rows
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
                        for row in published_bin_rows
                    ])
                    self._table(
                        rows,
                        [18 * mm, 18 * mm, 16 * mm, 18 * mm, 18 * mm,
                         19 * mm, 20 * mm, 21 * mm, 20 * mm],
                        font=5.2,
                        keep=False,
                    )
                    self._small('All stresses are in MPa. Fatigue total includes the bond transformation.')
                    self._small('Design elastic &#916;sigma is the action-factored Elastic stress range before the bond correction.')
                    self._small('Design values include the action-level factor gamma<sub>Ff</sub>.')
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
                        for row in published_bin_rows
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
                        all_bin_rows,
                        reinforcement_example,
                        references.get("reinforcement"),
                    )

            concrete_rows = fatigue_presentation.concrete_rows(spectrum)
            if concrete_rows and publish_concrete:
                governing_fibre = concrete_example.get("fibre_index")
                published_concrete_rows = (
                    concrete_rows
                    if audit_detail
                    else [
                        row for row in concrete_rows
                        if row["fibre_index"] == governing_fibre
                    ]
                )
                equivalent_method = (
                    str(fatigue_presentation.value(
                        spectrum, "concrete_method", ""
                    )) == fatigue_core.CONCRETE_EQUIVALENT
                )
                self._h2("Concrete fatigue")
                rows = [[
                    "Fiber", "Source", "x", "y", "f<sub>cd,fat</sub>",
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
                    for row in published_concrete_rows
                ])
                self._table(
                    rows,
                    [14 * mm, 18 * mm, 12 * mm, 12 * mm, 17 * mm,
                     16 * mm, 18 * mm, 26 * mm, 13 * mm, 14 * mm],
                    font=5.4,
                    keep=False,
                    repeat_cols=2,
                )
                self._small(
                    "Coordinates in mm; f<sub>cd,fat</sub> in MPa. The selected "
                    "criterion and stress are evaluated at the same fixed fiber."
                )
                result = fatigue_presentation.result_by_fibre(
                    spectrum, governing_fibre
                )
                if result is None:
                    self._small(
                        "<b>Worked example unavailable:</b> the selected concrete "
                        "fiber is absent from this spectrum."
                    )
                    continue
                all_bin_rows = fatigue_presentation.concrete_bin_rows(result)
                if self.profile.key == "Standard":
                    self._fatigue_concrete_formulas(
                        spectrum,
                        result,
                        all_bin_rows,
                        concrete_example,
                        references.get("concrete"),
                    )
                self._h2(
                    "Governing concrete fiber - "
                    + _html_escape(str(governing_fibre))
                )
                if self.figures:
                    self._fig(
                        viz.fatigue_damage_figure(
                            result,
                            title=(
                                "Damage-equivalent criterion"
                                if equivalent_method
                                else "Miner damage"
                            ) + f" - concrete fiber {governing_fibre}",
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
                    self._h2("Bounded governing-fiber search")
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
                        [22 * mm, 16 * mm, 16 * mm, 16 * mm, 16 * mm,
                         16 * mm, 16 * mm, 22 * mm, 18 * mm, 18 * mm],
                        font=5.3,
                    )
                self._h2(
                    "Governing concrete fiber bin results - "
                    + _html_escape(str(governing_fibre))
                )
                published_bin_rows = all_bin_rows
                if not audit_detail:
                    selected_bin_name = str(
                        concrete_example.get("bin_name") or ""
                    )
                    published_bin_rows = [
                        row for row in all_bin_rows
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
                    for row in published_bin_rows
                ])
                self._table(
                    rows,
                    [17 * mm, 17 * mm, 15 * mm, 18 * mm, 18 * mm,
                     18 * mm, 18 * mm, 14 * mm, 15 * mm, 15 * mm],
                    font=5.2,
                    keep=False,
                    caption=(
                        "Concrete stress history at governing fiber "
                        + str(governing_fibre)
                    ),
                )
                self._small(
                    "Compression values in MPa; E<sub>cd</sub> is the "
                    "normalized design compression level."
                )
                rows = [[
                    "Bin",
                    (
                        "Equivalent utilization"
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
                    "Stress utilization",
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
                    for row in published_bin_rows
                ])
                self._table(
                    rows,
                    [28 * mm, 35 * mm, 35 * mm, 32 * mm, 35 * mm],
                    font=6.5,
                    keep=False,
                    caption=(
                        "Concrete fatigue results at governing fiber "
                        + str(governing_fibre)
                    ),
                )
                if self.profile.key != "Standard":
                    self._fatigue_concrete_formulas(
                        spectrum,
                        result,
                        all_bin_rows,
                        concrete_example,
                        references.get("concrete"),
                    )
                if equivalent_method:
                    self._small('Concrete criterion:')
                    self._small('E<sub>cd,max</sub> + 0.43 &#8730;(1 - E<sub>cd,min</sub>/E<sub>cd,max</sub>) &#8804; 1.')
                    self._small('Each action pair is supplied as a damage-equivalent amplitude for 10<super>6</super> cycles. The entered cycle count is not used for concrete.')

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
                "bin lacks one or more required numerical terms. Recalculate to "
                "restore it."
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
        screen = fatigue_presentation.simplified_reinforcement_screen(result)
        screen_passed = screen["passed"] is True
        range_utilisation = (
            screen["utilisation"] if screen_passed else damage_total
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
                range_utilisation,
            )
            or any(value is None for value in damages)
        ):
            self._small(
                "<b>Worked example unavailable:</b> the governing reinforcement "
                "result lacks part of its criterion or reference. Recalculate to "
                "restore it."
            )
            return
        source = _html_escape(str(reference))
        if self.profile.key == "Standard":
            self._small(f"<b>Governing fatigue method:</b> {source}")
            return
        self._h2("Worked calculation - governing reinforcement fatigue")
        calculation_start = len(self.flow) - 1
        self._p('The globally governing reinforcement element and bin demonstrate the S-N, Miner and yield/proof checks once.')
        self._p('The compact summaries include all other elements and spectra.')
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
                f"({_fmt(selected_bin['delta_sigma_rsk_mpa'], 6)} / "
                f"{_fmt(material_factor, 6)}) MPa"
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
                note=_fatigue_report_label(selected_bin.get("sn_branch") or "", "sn_branch"),
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
                note=_fatigue_report_label(selected_bin.get("sn_branch") or "", "sn_branch"),
            )
        else:
            self._small(
                "<b>Worked example unavailable:</b> the governing S-N result lacks "
                "its reference ratio. Recalculate to restore it."
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
                f"({_fmt(characteristic, 6)} / {_fmt(material_factor, 6)}) MPa"
            ),
            result=f"sigma<sub>Rd</sub> = {_fmt(design_limit, 6)} MPa",
            note=_fatigue_report_label(
                fatigue_presentation.value(yield_check, "branch", ""),
                "yield_branch", kind=fatigue_presentation.value(result, "kind"),
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
            "u = max(u<sub>range</sub>, u<sub>yield</sub>)",
            equation_key="fatigue.reinforcement.utilisation",
            ref=(
                _html_escape(screen["source"])
                if screen_passed and screen["source"]
                else source
            ),
            subst=(
                (
                    "u<sub>range</sub> = u<sub>screen</sub> = "
                    if screen_passed
                    else "u<sub>range</sub> = D = "
                )
                + f"{_fmt_sig(range_utilisation, 8)}; max("
                f"{_fmt_sig(range_utilisation, 8)}, "
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
                "strength or bin name is missing."
            )
            return
        if reference is None:
            self._small(
                "<b>Worked example unavailable:</b> the governing concrete "
                "calculation source is absent."
            )
            return
        source = _html_escape(str(reference))
        self._h2(
            "Governing concrete fatigue result"
            if self.profile.key == "Standard"
            else "Worked calculation - governing concrete fatigue"
        )
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
                    "f<sub>cd,fat</sub> = (k<sub>1</sub> beta<sub>cc</sub> "
                    "alpha<sub>cc</sub> f<sub>ck</sub> / gamma<sub>c</sub>) &#183; "
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
                "lacks one or more normalized-stress terms. Recalculate to "
                "restore it."
            )
            return
        fcd_fat = fatigue_presentation.evidence_number(
            fatigue_presentation.value(result, "fcd_fat_mpa")
        )
        if fcd_fat is None:
            self._small(
                "<b>Worked example unavailable:</b> the governing concrete "
                "fatigue strength is absent from the selected fiber result."
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
                    "fatigue method is not recognised."
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
        appendix_start = len(self.flow)
        self._h1("QA appendix - references and notes")
        lines = []
        plastic_results = self._result_values("plastic")
        elastic_results = self._result_values("elastic")
        shear_results = self._result_values("shear")
        torsion_results = self._result_values("torsion")
        combined_results = [
            case_out["combined"]
            for case_inp, case_out in self._case_contexts("plastic")
            if case_inp.get("_report_case_current") is not False
            and case_out.get("combined") is not None
            and presentation.combined_bending_assessment_blocker(
                case_out,
                case_inp,
            ) is None
        ]
        if plastic_results:
            if "2023" in str(self.inp.get("concrete_preset", "")):
                lines.append(
                    "Selected concrete material - DS/EN 1992-1-1:2023: &#167;5.1.6 "
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
            edition = "DS/EN 1992-1-1:2023" if crack_2023 else "DS/EN 1992-1-1"
            lines.append(f"{edition} (Eurocode 2): {clauses}.")
            lines.append(
                "Stresses and crack widths are numerical outputs for the named "
                "user-defined actions. Apply any project exposure, durability, "
                "decompression or action-combination criteria separately."
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
                    "DS/EN 1992-1-1:2023 &#167;8.2.1-8.2.2: Formulae (8.18), "
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
        # Native biaxial aggregates deliberately have no aggregate verdict.
        # Use the same eligible directional evidence as worked-case selection,
        # after the current-case, scope and prerequisite checks above.
        if any(
            presentation._transverse_metric("combined", result) is not None
            for result in combined_results
        ):
            lines.append(
                "The combined M-V-T chapter states the selected edition, the common "
                "strut-angle basis and the applicable interaction expressions."
            )
        fatigue = self._base_out.get("fatigue")
        fatigue_errors = tuple((fatigue or {}).get("errors") or ())
        if fatigue is not None and not fatigue_errors:
            references = fatigue.get("calculation_references") or {}
            lines.extend([
                "Grouped fatigue spectra are assessed independently with the cracked Elastic analysis.",
                "gamma<sub>Ff</sub> is applied to the cyclic actions before the stress calculation.",
                "gamma<sub>s</sub> is applied to the reinforcement S-N resistance.",
            ])
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
                "The grouped fatigue calculation covers normal force and bending; "
                "shear and torsion fatigue remain separate checks."
            )
        elif fatigue_errors:
            lines.append(
                "Fatigue was requested but not assessed because the input "
                "preflight was invalid. No fatigue methodology or resistance "
                "verdict was applied."
            )
        lines.append(
            "The printed gamma<sub>c</sub>, gamma<sub>s</sub> and reinforcement "
            "factors are the final project inputs and are used directly in the "
            "calculation."
        )
        lines.append(
            "All results follow from the documented inputs and cited formulas; "
            "intermediate values are shown for the governing cases."
        )
        for line in lines:
            self._p("- " + line)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self._small(f"Generated {ts} by Sector {self.version}.")
        self._keep_from(appendix_start)


@presentation.publication_calculation_scope()
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
