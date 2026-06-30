"""Generate a QA-able PDF report of a Sector cross-section analysis.

Modelled on the BriCoS report: a sectioned reportlab document with a numbered
footer, the governing case worked in full and the remainder summarised in tables,
and every computed quantity tied to its formula and a ``DS/EN 1992-1-1`` reference.

The builder is fed the same two objects the result views use -- the collected
inputs ``inp`` and the analysis payload ``out = run_analysis(inp)`` -- plus the
report ``meta`` (project / author fields), so the report cannot drift from what
the app computes. Figures are the on-screen Plotly figures exported to PNG.

Engineering symbols are written in ASCII (``eps_cu2``, ``sigma_s``, ``w_k``) with
``<sub>`` markup: the source stays ASCII (the repo enforces it) and the PDF does
not depend on a Greek-capable font.
"""

from __future__ import annotations

import contextlib
import datetime
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
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

import viz

_MM = 1000.0                       # metres -> millimetres for display
_KN = 1.0                          # forces already in kN
_BLUE = colors.HexColor("#1F3B66")
_GREY = colors.HexColor("#5A5A5A")
_LINE = colors.HexColor("#9AA5B1")
_HEAD_BG = colors.HexColor("#E8ECF2")

# A Unicode (Greek-capable) font for the report. DejaVuSans is free and shipped
# with the app; Helvetica is the fallback (Greek glyphs then render as boxes, but
# the report still generates). BriCoS uses Helvetica -- DejaVuSans keeps the same
# clean sans-serif look while adding the Greek the engineering notation needs.
_FONT, _FONT_BOLD = "Helvetica", "Helvetica-Bold"


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
          "permille": "&#8240;"}
_GREEK_RE = re.compile(r"\b(" + "|".join(_GREEK) + r")\b")


def _greek(s):
    """Replace the ASCII engineering tokens in display text with Greek glyphs."""
    s = _GREEK_RE.sub(lambda m: _GREEK[m.group(1)], s)
    return s.replace("&lt;=", "&#8804;").replace("&gt;=", "&#8805;")


@contextlib.contextmanager
def _persistent_image_export():
    """Keep one kaleido export process alive for all figures in the report.

    With kaleido 1.x each ``to_image`` otherwise spawns and tears down a headless
    browser; starting the sync server once makes every export just the render
    time. Falls back silently (one browser per image) when the server or a
    browser is unavailable, so report generation still works.
    """
    start = stop = None
    try:
        import kaleido
        start = getattr(kaleido, "start_sync_server", None)
        stop = getattr(kaleido, "stop_sync_server", None)
    except Exception:
        start = stop = None
    if start is None or stop is None:
        yield
        return
    try:
        start(silence_warnings=True)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            stop(silence_warnings=True)
        except Exception:
            pass


class _NumberedCanvas(canvas.Canvas):
    """Adds a 'Page x of y' footer with the tool version once the count is known."""

    def __init__(self, *args, footer="", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []
        self._footer = footer

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._draw_footer(n)
            super().showPage()
        super().save()

    def _draw_footer(self, total):
        self.setFont(_FONT, 8)
        self.setFillColor(_GREY)
        self.drawString(20 * mm, 12 * mm, self._footer)
        self.drawRightString(190 * mm, 12 * mm,
                             "Page %d of %d" % (self._pageNumber, total))
        self.setStrokeColor(_LINE)
        self.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)


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


def _fig_png(fig, w_px, h_px):
    """Export a Plotly figure to PNG bytes, or ``None`` if export is unavailable."""
    try:
        return fig.to_image(format="png", width=w_px, height=h_px, scale=2)
    except Exception:
        return None


def _fmt(v, nd=2):
    if v is None:
        return "-"
    if isinstance(v, float) and not math.isfinite(v):
        return "inf"
    return f"{v:.{nd}f}"


class ReportBuilder:
    """Builds the PDF into ``buffer`` from ``meta``, ``inp`` and ``out``."""

    def __init__(self, buffer, meta, inp, out, version="", figures=True,
                 progress=None):
        self.buffer = buffer
        self.meta = meta or {}
        self.inp = inp
        self.out = out or {}
        self.version = version
        self.figures = figures
        self._progress = progress
        self.s = _styles()
        self.flow = []
        self._chapter = 0

    def _tick(self, frac, text):
        if self._progress is not None:
            self._progress(frac, text)

    # -- flowable helpers --------------------------------------------------
    def _h1(self, text):
        self._chapter += 1
        self.flow.append(Paragraph(_greek(f"{self._chapter}. {text}"), self.s["h1"]))

    def _h2(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["h2"]))

    def _p(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["body"]))

    def _small(self, text):
        self.flow.append(Paragraph(_greek(text), self.s["small"]))

    def _gap(self, h=4):
        self.flow.append(Spacer(1, h))

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
        t = Table(rows, colWidths=widths, hAlign="LEFT", repeatRows=1 if not keep else 0)
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
        png = _fig_png(fig, int(w_mm * 3.78), int(h_mm * 3.78))
        if png is None:
            self._small("[figure unavailable: install kaleido and a browser to "
                        "embed plots]")
            return
        self.flow.append(Image(io.BytesIO(png), width=w_mm * mm, height=h_mm * mm))
        self._gap(4)

    # -- build -------------------------------------------------------------
    def build(self):
        with _persistent_image_export():
            self._tick(0.05, "Cover and conventions...")
            self._cover()
            self._conventions()
            self._tick(0.2, "Section and materials...")
            self._inputs()
            self._theory()
            if "plastic" in self.out:
                self._tick(0.45, "Plastic capacity...")
                self.flow.append(PageBreak())
                self._plastic()
            if "elastic" in self.out:
                self._tick(0.7, "Elastic stresses and crack width...")
                self.flow.append(PageBreak())
                self._elastic()
                self._cracking()
            self._appendix()
        self._tick(0.92, "Writing PDF...")
        footer = f"Sector {self.version}  -  Sweco".strip()
        doc = SimpleDocTemplate(self.buffer, pagesize=A4,
                                leftMargin=20 * mm, rightMargin=20 * mm,
                                topMargin=18 * mm, bottomMargin=20 * mm,
                                title="Sector cross-section report")
        doc.build(self.flow,
                  canvasmaker=lambda *a, **k: _NumberedCanvas(*a, footer=footer, **k))
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
                ["Tool version", self.version or "-"]]
        self._table(rows, [55 * mm, 110 * mm])
        if m.get("comments"):
            self._h2("Comments")
            self._p(str(m["comments"]))
        mode = self.inp.get("mode", "")
        ran = ", ".join(k for k in ("plastic", "elastic") if k in self.out) or "none"
        self._small(f"Analysis mode: {mode}. Result sections included: {ran}.")
        self.flow.append(PageBreak())

    def _conventions(self):
        self._h1("Conventions and units")
        self._p("Coordinates are entered in the section plane with the origin as "
                "input; the x-axis is horizontal and the y-axis vertical. "
                "<b>M<sub>x</sub></b> bends about the x-axis (stress varies with y) "
                "and is drawn on the vertical axis of the interaction diagram; "
                "<b>M<sub>y</sub></b> bends about the y-axis.")
        self._p("Axial force <b>N</b> is positive in compression. Concrete carries "
                "compression only (no tension). Strains are plane (Bernoulli).")
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
                                 scale=_MM, unit="mm", height=420)
        self._fig(fig, 150, 100)
        self._geometry_tables()
        # Materials are reported only when the section actually uses them: mild
        # steel when there are bars, prestress when there are tendons.
        self._h2("Concrete")
        self._concrete_block()
        if inp.get("bars"):
            self._h2("Reinforcement")
            self._steel_block()
        if inp.get("tendons") and inp.get("prestress") is not None:
            self._h2("Prestressing steel")
            self._prestress_block()
        # Loads & settings.
        self._h2("Loads")
        self._loads_block()
        self._h2("Analysis settings")
        self._settings_block()

    def _geometry_tables(self):
        inp = self.inp
        corners = inp.get("outer", [])
        if corners:
            rows = [["#", "x (mm)", "y (mm)"]]
            for i, p in enumerate(corners, 1):
                rows.append([i, _fmt(p[0] * _MM, 1), _fmt(p[1] * _MM, 1)])
            self._h2("Concrete corners")
            self._table(rows, [15 * mm, 40 * mm, 40 * mm])
        holes = inp.get("holes", [])
        for hi, ring in enumerate(holes, 1):
            rows = [["#", "x (mm)", "y (mm)"]]
            for i, p in enumerate(ring, 1):
                rows.append([i, _fmt(p[0] * _MM, 1), _fmt(p[1] * _MM, 1)])
            self._h2(f"Void {hi}")
            self._table(rows, [15 * mm, 40 * mm, 40 * mm])
        bars = inp.get("bars", [])
        if bars:
            rows = [["#", "x (mm)", "y (mm)", "Area (mm<super>2</super>)"]]
            for i, b in enumerate(bars, 1):
                rows.append([i, _fmt(b[0] * _MM, 1), _fmt(b[1] * _MM, 1),
                             _fmt(b[2] * 1e6, 0)])
            self._h2("Reinforcing bars")
            self._table(rows, [15 * mm, 35 * mm, 35 * mm, 40 * mm])
        tendons = inp.get("tendons", [])
        if tendons:
            rows = [["#", "x (mm)", "y (mm)", "Area (mm<super>2</super>)"]]
            for i, t in enumerate(tendons, 1):
                rows.append([i, _fmt(t[0] * _MM, 1), _fmt(t[1] * _MM, 1),
                             _fmt(t[2] * 1e6, 0)])
            self._h2("Tendons")
            self._table(rows, [15 * mm, 35 * mm, 35 * mm, 40 * mm])

    def _concrete_block(self):
        c = self.inp["concrete"]
        rows = [["Parameter", "Symbol", "Value"],
                ["Characteristic strength", "f<sub>ck</sub>", f"{_fmt(c.fck,1)} MPa"],
                ["Partial factor", "gamma<sub>c</sub>", _fmt(c.gamma_c, 2)],
                ["Design coefficient", "alpha<sub>cc</sub>", _fmt(c.alpha_cc, 3)],
                ["Curve", "-", "parabola-rectangle" if c.curve == 2 else "cubic"],
                ["Peak strain", "eps<sub>c2</sub>", f"{_fmt(c.eps_c2*1000,2)} permille"],
                ["Ultimate strain", "eps<sub>cu2</sub>", f"{_fmt(c.eps_cu2*1000,2)} permille"],
                ["Exponent", "n", _fmt(c.n, 2)],
                ["Design strength", "f<sub>cd</sub>", f"{_fmt(c.fcd,2)} MPa"]]
        self._table(rows, [60 * mm, 35 * mm, 50 * mm])
        self._formula(
            "f<sub>cd</sub> = alpha<sub>cc</sub> &#183; f<sub>ck</sub> / gamma<sub>c</sub>",
            ref="DS/EN 1992-1-1 &#167;3.1.6, Eq (3.15)",
            subst=f"= {_fmt(c.alpha_cc,3)} &#183; {_fmt(c.fck,1)} / {_fmt(c.gamma_c,2)}",
            result=f"= {_fmt(c.fcd,2)} MPa")
        if c.curve == 2:
            self._formula(
                "sigma<sub>c</sub> = f<sub>cd</sub> &#183; [1 - (1 - eps<sub>c</sub>/"
                "eps<sub>c2</sub>)<super>n</super>],  for eps<sub>c</sub> &lt;= eps<sub>c2</sub>; "
                "then f<sub>cd</sub> up to eps<sub>cu2</sub>",
                ref="DS/EN 1992-1-1 &#167;3.1.7, Eq (3.17); strains from Table 3.1")
        if self.figures:
            self._fig(viz.concrete_curve_figure(c), 130, 80)

    def _steel_block(self):
        st = self.inp["steel"]
        fyd = st.fytk / st.gamma_y if st.gamma_y else st.fytk
        rows = [["Parameter", "Symbol", "Value"],
                ["Yield strength", "f<sub>ytk</sub>", f"{_fmt(st.fytk,1)} MPa"],
                ["Compression yield", "f<sub>yck</sub>", f"{_fmt(st.fyck,1)} MPa"],
                ["Ultimate strength", "f<sub>utk</sub>", f"{_fmt(st.futk,1)} MPa"],
                ["Rupture strain", "eps<sub>ut</sub>", f"{_fmt(st.eut*1000,1)} permille"],
                ["Elastic modulus", "E<sub>s</sub>", f"{_fmt(st.Es/1000,0)} GPa"],
                ["Partial factor", "gamma<sub>s</sub>", _fmt(st.gamma_y, 2)],
                ["Active in compression", "-", "yes" if st.active_in_compression else "no"],
                ["Design yield", "f<sub>yd</sub>", f"{_fmt(fyd,1)} MPa"]]
        self._table(rows, [60 * mm, 35 * mm, 50 * mm])
        self._formula("f<sub>yd</sub> = f<sub>ytk</sub> / gamma<sub>s</sub>",
                      ref="DS/EN 1992-1-1 &#167;3.2.7",
                      subst=f"= {_fmt(st.fytk,1)} / {_fmt(st.gamma_y,2)}",
                      result=f"= {_fmt(fyd,1)} MPa")
        if self.figures:
            self._fig(viz.steel_curve_figure(st), 130, 80)

    def _prestress_block(self):
        p = self.inp["prestress"]
        rows = [["Parameter", "Value"],
                ["Initial prestrain IS", f"{_fmt(getattr(p,'IS',0.0)*1000,2)} permille"],
                ["Elastic modulus E<sub>p</sub>", f"{_fmt(getattr(p,'Es',0.0)/1000,0)} GPa"],
                ["Rupture strain", f"{_fmt(getattr(p,'rupture_strain',0.0)*1000,1)} permille"]]
        self._table(rows, [80 * mm, 60 * mm])
        if self.figures and p is not None:
            self._fig(viz.prestress_curve_figure(p), 130, 80)

    def _loads_block(self):
        inp = self.inp
        rows = [["Load case", "N (kN)", "M<sub>x</sub> (kNm)", "M<sub>y</sub> (kNm)"]]
        if "plastic" in self.out:
            # In a capacity-only run the applied moments are ignored, so only the
            # axial force (which defines the envelope) is listed.
            cap_only = not self.out["plastic"].get("check_util", True)
            label = "Plastic (axial, capacity only)" if cap_only else "Plastic (applied)"
            mx = "-" if cap_only else _fmt(inp.get("Mx_pl"), 1)
            my = "-" if cap_only else _fmt(inp.get("My_pl"), 1)
            rows.append([label, _fmt(inp.get("P_pl"), 1), mx, my])
        if "elastic" in self.out:
            rows.append(["Elastic long-term", _fmt(inp.get("P_el_l"), 1),
                         _fmt(inp.get("Mx_el_l"), 1), _fmt(inp.get("My_el_l"), 1)])
            rows.append(["Elastic short-term", _fmt(inp.get("P_el_s"), 1),
                         _fmt(inp.get("Mx_el_s"), 1), _fmt(inp.get("My_el_s"), 1)])
        self._table(rows, [55 * mm, 35 * mm, 38 * mm, 38 * mm])

    def _settings_block(self):
        # Every input that influences the reported results is documented here so the
        # report is self-contained and QA-able.
        inp = self.inp
        rows = [["Setting", "Value"]]
        rows.append(["Analysis mode", str(inp.get("mode", "-"))])
        if "plastic" in self.out:
            rows.append(["Sweep start V.min", f"{_fmt(inp.get('v_min'),0)} deg"])
            rows.append(["Sweep end V.max", f"{_fmt(inp.get('v_max'),0)} deg"])
            rows.append(["Sweep increment V.inc", f"max {_fmt(inp.get('v_inc'),0)} deg"])
            checked = self.out["plastic"].get("check_util", True)
            rows.append(["Utilisation check",
                         "applied moment checked" if checked else "capacity only"])
        if "elastic" in self.out:
            el = self.out["elastic"]
            rows.append(["Long-term modular ratio n<sub>l</sub> = E<sub>s</sub>/E<sub>c,eff</sub>",
                         _fmt(inp.get("nl"), 1)])
            rows.append(["Short-term modular ratio n<sub>s</sub> = E<sub>s</sub>/E<sub>c</sub>",
                         _fmt(inp.get("ns"), 1)])
            rows.append(["Mean tensile strength f<sub>ctm</sub>",
                         f"{_fmt(inp.get('sls_fctm'),2)} MPa"])
            rows.append(["Crack width checked", "yes" if inp.get("sls_cw") else "no"])
            if inp.get("sls_cw"):
                rows.append(["Crack-width code", str(el.get("crack_code", "-"))])
                if el.get("crack_member"):
                    rows.append(["Member type", str(el["crack_member"])])
                dia = inp.get("sls_phi") or 0.0
                rows.append(["Crack-width bar diameter",
                             "auto (from geometry)" if not dia else f"{_fmt(dia,1)} mm"])
                rows.append(["Mild-steel bond coefficient k<sub>1</sub>",
                             _fmt(inp.get("sls_k1"), 2)])
        self._table(rows, [110 * mm, 55 * mm])

    def _theory(self):
        self._h1("Basis of analysis")
        self._p("<b>Ultimate (plastic) capacity.</b> Plane sections; concrete in "
                "compression follows the design curve above, reinforcement the "
                "design stress-strain law. For a trial neutral axis the strain "
                "plane is scaled to the governing curvature - the first material "
                "limit reached:")
        self._formula("kappa<sub>u</sub> = min( eps<sub>cu2</sub>/c ,  "
                      "eps<sub>su</sub>/(s<sub>na</sub>-s<sub>bar</sub>) ,  "
                      "eps<sub>pu</sub>/... )",
                      ref="DS/EN 1992-1-1 &#167;6.1, &#167;3.1.7, &#167;3.2.7")
        self._p("The compression depth c is solved from axial equilibrium and the "
                "moments follow from the force resultants:")
        self._formula("F<sub>c</sub> + F<sub>s</sub> + F<sub>p</sub> = N ;   "
                      "M = sum( F<sub>i</sub> &#183; d<sub>i</sub> )")
        self._p("<b>Cracked-section elastic stresses.</b> Transformed section "
                "(reinforcement weighted by the modular ratio), concrete tension "
                "ignored once cracked; long-term and short-term actions are "
                "carried at their own modular ratios so creep is explicit.")
        self._p("<b>Serviceability.</b> The cracking threshold compares the Stage-I "
                "extreme tensile stress with f<sub>ct,eff</sub>; crack width follows "
                "&#167;7.3.4 (worked below).")

    def _plastic(self):
        pl = self.out["plastic"]
        inp = self.inp
        self._h1("Ultimate (plastic) capacity")
        if not pl.get("converged", True):
            self._small("Warning: not all sweep points converged.")
        applied = pl.get("applied")   # None for a capacity-only run
        self._fig(viz.interaction_figure(
            pl["mx"], pl["my"], applied=applied, title="M-M interaction"), 130, 100)
        rows = [["Quantity", "Value"],
                ["Max M<sub>x</sub> capacity", f"{_fmt(pl['max_mx'],1)} kNm"],
                ["Max M<sub>y</sub> capacity", f"{_fmt(pl['max_my'],1)} kNm"]]
        if not pl.get("check_util", True):
            rows.append(["Utilisation", "not checked (capacity only)"])
        elif pl.get("util") is not None:
            if applied is not None:
                rows.append(["Applied M<sub>x</sub>, M<sub>y</sub>",
                             f"{_fmt(applied[0],1)}, {_fmt(applied[1],1)} kNm"])
            rows.append(["Utilisation (applied direction)",
                         f"{_fmt(pl['util']*100,1)} %"])
        else:
            rows.append(["Utilisation", "open arc (no closed envelope)"])
        self._table(rows, [90 * mm, 60 * mm])
        # Per-angle results table -- the full column set, matching the result view.
        self._h2("Capacity over the neutral-axis sweep")
        cable = bool(self.inp.get("tendons"))
        head = ["V", "M<sub>x</sub>", "M<sub>y</sub>", "NA x", "NA y", "eps<sub>c</sub>",
                "eps<sub>s</sub>", "kappa", "Comp", "L", "D<sub>x</sub>", "D<sub>y</sub>"]
        if cable:
            head.append("eps<sub>p</sub>")
        rows = [head]
        for p in pl["points"]:
            row = [_fmt(p["V"], 0), _fmt(p["Mx"], 1), _fmt(p["My"], 1),
                   _fmt(p["na_x"] * _MM, 0), _fmt(p["na_y"] * _MM, 0),
                   _fmt(p["eps_c"], 2), _fmt(p["eps_s"], 2), _fmt(p["kappa"], 4),
                   _fmt(p["comp_force"], 0), _fmt(p["lever"] * _MM, 0),
                   _fmt(p["dx"] * _MM, 0), _fmt(p["dy"] * _MM, 0)]
            if cable:
                row.append(_fmt(p["eps_cable"], 2))
            rows.append(row)
        ncol = len(head)
        self._table(rows, [170 * mm / ncol] * ncol, font=6.5, keep=False)
        self._small("V deg; M kNm; NA x/y, L, D<sub>x</sub>, D<sub>y</sub> mm; "
                    "eps<sub>c</sub>/eps<sub>s</sub>/eps<sub>p</sub> %; kappa 1/m; Comp kN.")
        # Governing case worked.
        self._plastic_worked(pl)

    def _plastic_worked(self, pl):
        gov = max(pl["points"], key=lambda p: math.hypot(p["Mx"], p["My"]))
        P = self.inp.get("P_pl", 0.0) or 0.0
        Fc = gov["comp_force"]
        T = Fc - P
        self._h2("Governing case worked (peak resultant moment)")
        self._p(f"Neutral-axis angle V = {_fmt(gov['V'],0)} deg. The extreme "
                f"concrete fibre is at the ultimate strain; the curvature scales "
                f"the strain plane to that limit.")
        rows = [["Quantity", "Symbol", "Value"],
                ["NA intercepts", "x<sub>na</sub>, y<sub>na</sub>",
                 f"{_fmt(gov['na_x']*_MM,0)}, {_fmt(gov['na_y']*_MM,0)} mm"],
                ["Extreme concrete strain", "eps<sub>c</sub>", f"{_fmt(gov['eps_c'],2)} %"],
                ["Most-tensile bar strain", "eps<sub>s</sub>", f"{_fmt(gov['eps_s'],2)} %"],
                ["Curvature", "kappa", f"{_fmt(gov['kappa'],4)} 1/m"],
                ["Concrete compression resultant", "F<sub>c</sub>", f"{_fmt(Fc,1)} kN"],
                ["Internal lever arm", "L", f"{_fmt(gov['lever']*_MM,0)} mm"],
                ["Lever components", "d<sub>x</sub>, d<sub>y</sub>",
                 f"{_fmt(gov['dx']*_MM,0)}, {_fmt(gov['dy']*_MM,0)} mm"],
                ["Capacity", "M<sub>x</sub>, M<sub>y</sub>",
                 f"{_fmt(gov['Mx'],1)}, {_fmt(gov['My'],1)} kNm"]]
        self._table(rows, [70 * mm, 30 * mm, 60 * mm])
        self._h2("Axial equilibrium check")
        self._formula("F<sub>c</sub> - T = N",
                      subst=f"{_fmt(Fc,1)} - {_fmt(T,1)} = {_fmt(Fc-T,1)} kN",
                      result=f"applied N = {_fmt(P,1)} kN  (residual "
                             f"{_fmt(abs(Fc - T - P),3)} kN)")
        self._small("The tension resultant T = F<sub>c</sub> - N balances the "
                    "section; the moments above are the resultants about the origin.")
        # Section state at the governing angle (neutral axis + compression zone).
        if self.figures:
            inp = self.inp
            hp = viz.plastic_halfplane(gov["V"], gov["na_x"], gov["na_y"])
            na = viz.na_line_at(hp[0], hp[1], hp[2], inp.get("extent", 1.0))
            zones = viz.compression_zones(inp.get("outer", []), hp)
            bar_xy = [(b[0], b[1]) for b in inp.get("bars", [])]
            ten_xy = [(t[0], t[1]) for t in inp.get("tendons", [])]
            self._h2("Section state at the governing angle")
            self._fig(viz.section_figure(
                inp.get("outer", []), inp.get("holes", []), bar_xy, na_line=na,
                tendons=ten_xy, zones=zones, show_labels=True, scale=_MM, unit="mm",
                title=f"Compression zone at V = {_fmt(gov['V'],0)} deg"), 150, 100)

    def _elastic(self):
        el = self.out["elastic"]
        self._h1("Cracked-section elastic stresses")
        state = "cracked" if el.get("cracked") else "uncracked"
        self._p(f"Under the long-term (quasi-permanent) action the section is "
                f"<b>{state}</b>. Neutral-axis intercepts: "
                f"x<sub>na</sub> = {_fmt(el['na_x']*_MM,0)} mm, "
                f"y<sub>na</sub> = {_fmt(el['na_y']*_MM,0)} mm.")
        ps = el.get("prestress")
        if ps is not None:
            self._p(f"The tendon prestress is applied from its initial strain (so N "
                    f"is the external force only): equivalent prestress action "
                    f"N = {_fmt(ps[0],0)} kN, M<sub>x</sub> = {_fmt(ps[1],0)} kNm, "
                    f"M<sub>y</sub> = {_fmt(ps[2],0)} kNm (compression positive).")
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
                    [(b[0], b[1]) for b in inp.get("bars", [])],
                    bar_colors=[sgn(s) for s in total[:nb]],
                    tendons=[(t[0], t[1]) for t in inp.get("tendons", [])],
                    tendon_colors=[sgn(s) for s in total[nb:]], na_line=na, zones=zones,
                    show_labels=True, scale=_MM, unit="mm",
                    title="Elastic state (green tension, red compression)"), 150, 100)
        # Transformed properties: uncracked and (when cracked) cracked, n_l-weighted.
        self._h2("Transformed section properties (n<sub>l</sub>)")
        pu = el.get("props_un") or {}
        pc = el.get("props_cr")
        specs = [("Area A", "area", 4, "m<super>2</super>", 1.0),
                 ("Centroid x", "cx", 1, "mm", _MM),
                 ("Centroid y", "cy", 1, "mm", _MM),
                 ("I<sub>x</sub>", "Ix", 6, "m<super>4</super>", 1.0),
                 ("I<sub>y</sub>", "Iy", 6, "m<super>4</super>", 1.0)]
        head = ["Property", "Uncracked"] + (["Cracked"] if pc else [])
        rows = [head]
        for label, k, nd, unit, sc in specs:
            row = [f"{label} ({unit})", _fmt(pu.get(k, 0.0) * sc, nd)]
            if pc:
                row.append(_fmt(pc.get(k, 0.0) * sc, nd))
            rows.append(row)
        self._table(rows, [55 * mm, 45 * mm] + ([45 * mm] if pc else []))
        self._small("Transformed (n<sub>l</sub>-weighted) about the centroid; the "
                    "cracked column drops the concrete in tension.")
        # Per-bar stress table.
        self._h2("Reinforcement stresses (creep decomposition)")
        self._small("TOTAL = long + short at the section state; LONG = long-term "
                    "part; DIF = short-term difference; RST1 = restraint. "
                    "Compression positive.")
        total = el.get("total", [])
        rows = [["Bar", "TOTAL", "LONG", "DIF", "RST1"]]
        for i in range(len(total)):
            rows.append([i + 1, _fmt(total[i], 1), _fmt(el["long"][i], 1),
                         _fmt(el["dif"][i], 1), _fmt(el["rst1"][i], 1)])
        if len(total):
            w = 150 * mm / 5
            self._table(rows, [w] * 5, font=8, keep=False)
        rows = [["Quantity", "Value"],
                ["Max concrete compression", f"{_fmt(el.get('max_conc'),2)} MPa "
                 f"(point {el.get('max_conc_point','-')})"],
                ["Max reinforcement tension", f"{_fmt(el.get('max_steel'),1)} MPa "
                 f"(bar {el.get('max_steel_bar','-')})"]]
        self._table(rows, [70 * mm, 90 * mm])
        self._p("Stresses are the transformed-section result, sigma = "
                "n &#183; (N/A<sub>t</sub> + M&#183;z/I<sub>t</sub>), summed over "
                "the long- and short-term actions at their modular ratios.")

    def _cracking(self):
        el = self.out["elastic"]
        self._h1("Serviceability - cracking and crack width")
        # Threshold.
        self._h2("Cracking threshold")
        lam = el.get("lambda_cr")
        verdict = "cracked" if el.get("cracked") else "uncracked"
        self._formula("lambda<sub>cr</sub> = f<sub>ct,eff</sub> / sigma<sub>ct,I</sub>",
                      ref="Stage-I extreme tensile stress reaches f<sub>ct,eff</sub> "
                          "(DS/EN 1992-1-1 &#167;7.1)",
                      subst=f"f<sub>ct,eff</sub> = {_fmt(el.get('fctm'),2)} MPa,  "
                            f"sigma<sub>ct,I</sub> = {_fmt(el.get('sigma_ct'),2)} MPa",
                      result=f"lambda<sub>cr</sub> = {_fmt(lam,3)}  ->  section is "
                             f"{verdict} (cracks when lambda<sub>cr</sub> &lt;= 1)")
        if not el.get("show_cw"):
            self._small("Crack width was not requested for this run.")
            return
        cl, cs = el.get("crack"), el.get("crack_short")
        if cl is None and cs is None:
            self._small("No crack width: the section is uncracked, or no bar is in "
                        "tension, under either the long-term or the short-term load.")
            return
        self._crack_table(cl, cs)
        # Work the case that actually governs (the larger crack width).
        gov_case = max((c for c in (cl, cs) if c), key=lambda c: c.get("wk", 0.0))
        self._crack_worked(gov_case, "long-term" if gov_case is cl else "short-term")

    def _crack_table(self, cl, cs):
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
                 ("Bar diameter phi (mm)", "phi", 1, 1.0),
                 ("Governing bar", "gov_bar", 0, 1.0)]

        def col(c):
            return ["-"] * len(specs) if c is None else \
                [_fmt(c.get(k, 0.0) * sc, nd) for _, k, nd, sc in specs]
        lcol, scol = col(cl), col(cs)
        rows = [["Quantity", "Long-term", "Short-term"]]
        for i, spec in enumerate(specs):
            rows.append([spec[0], lcol[i], scol[i]])
        self._table(rows, [85 * mm, 38 * mm, 38 * mm])

    def _crack_worked(self, cw, which=""):
        if not cw:
            return
        self._h2(f"Crack width worked - governing case ({which})" if which
                 else "Crack width worked (governing bar)")
        self._small(f"Governing bar (largest w<sub>k</sub>): bar "
                    f"{cw.get('gov_bar','-')}; clear cover c = {_fmt(cw.get('cover',0),1)} mm.")
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
        coarse = bool(cw.get("coarse"))
        self._formula(
            ("w<sub>k</sub> = &#189;&#183;s<sub>r,max</sub> &#183; "
             "(eps<sub>sm</sub> - eps<sub>cm</sub>)" if coarse else
             "w<sub>k</sub> = s<sub>r,max</sub> &#183; "
             "(eps<sub>sm</sub> - eps<sub>cm</sub>)"),
            ref="DS/EN 1992-1-1 DK NA &#167;7.3.4(1), Eq (7.8)" if coarse else "Eq (7.8)",
            subst=("= &#189; &#183; " if coarse else "= ")
                  + f"{_fmt(cw.get('sr_max',0),1)} mm &#183; "
                    f"{_fmt(cw.get('esm_ecm',0)*1000,4)} permille",
            result=f"w<sub>k</sub> = {_fmt(cw.get('wk',0),3)} mm")
        code = self.out["elastic"].get("crack_code")
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

    def _appendix(self):
        self.flow.append(PageBreak())
        self._h1("References and notes")
        for line in (
            "DS/EN 1992-1-1 (Eurocode 2): &#167;3.1.6 (f<sub>cd</sub>), "
            "&#167;3.1.7 / Table 3.1 (concrete curve, strains), &#167;3.2.7 "
            "(reinforcement), &#167;6.1 (bending), &#167;7.1 (cracking), "
            "&#167;7.3.2-7.3.4 (crack width).",
            "The Danish National Annex modifies the crack-spacing coefficient "
            "k<sub>3</sub> and the effective-height term as noted.",
            "The capacity solver is verified against independent hand calculations.",
            "All results follow from the inputs in section 1 and the formulas cited; "
            "intermediate values are shown for the governing cases.",
        ):
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
