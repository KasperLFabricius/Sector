"""Tests for the in-app user manual (content blocks, worked examples, figures).

The manual authors its content as typed blocks rendered both in the app and (in
a later step) to a PDF, so the block list and the worked-example models are
tested directly. The examples are also run through the engine, so a manual
figure or worked number can never reference a section the solver cannot handle.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
from sector.codes import fctm  # noqa: E402
from sector.plastic import plastic_capacity_at_angle  # noqa: E402
from sector.section import Section  # noqa: E402
from sector.serviceability import analyse_cracking  # noqa: E402

APP = str(ROOT / "app" / "sector_app.py")


def _section(ex):
    return Section.from_polygon(corners=ex["outer"], holes=ex["holes"],
                                bars_xy_area_mm2=ex["bars"],
                                tendons_xy_area_mm2=ex["tendons"])


@pytest.mark.parametrize("builder", [manual.example_beam, manual.example_circular],
                         ids=["beam", "circular"])
def test_worked_example_is_analysable(builder):
    # Every worked example the manual leans on must build a valid section and run
    # through both solvers, so a figure or derivation can't reference a section the
    # engine rejects (e.g. a void that disconnects the concrete).
    ex = builder()
    sec = _section(ex)
    r = plastic_capacity_at_angle(sec, ex["concrete"], ex["steel"], ex["P"], 90.0,
                                  prestress=ex["prestress"])
    assert r.converged
    assert r.Mx > 0.0
    cr = analyse_cracking(sec, ex["P"], ex["Mx"], ex["My"], 6.0,
                          fctm=fctm(ex["concrete"].fck), bar_diameter=20.0)
    assert cr.lambda_cr > 0.0


def test_beam_is_mild_only_and_circular_has_void_and_prestress():
    beam = manual.example_beam()
    assert beam["prestress"] is None and not beam["tendons"] and not beam["holes"]
    circ = manual.example_circular()
    assert circ["prestress"] is not None
    assert len(circ["holes"]) == 1 and len(circ["tendons"]) > 0 and len(circ["bars"]) > 0


@pytest.mark.parametrize("fig", [manual.fig_beam_section, manual.fig_circular_section],
                         ids=["beam", "circular"])
def test_section_figures_build(fig):
    f = fig()
    assert f is not None
    assert len(f.data) > 0                      # the drawing has traces


def test_manual_blocks_are_wellformed():
    blocks = manual.manual_blocks()
    assert len(blocks) > 10
    kinds = {b[0] for b in blocks}
    assert {"part", "h1", "md"} <= kinds        # the spine is present
    for b in blocks:
        if b[0] == "callout":
            assert b[1] in manual._CALLOUT      # a known callout kind
            assert isinstance(b[2], str) and b[2]
        elif b[0] == "figure":
            assert callable(b[1])               # figure is a live callable
            assert isinstance(b[2], str)
        elif b[0] == "table":
            headers, rows = b[1], b[2]
            assert all(len(row) == len(headers) for row in rows)  # rectangular


def test_manual_covers_both_examples_and_all_crack_editions():
    # The reference part documents every crack edition equally; the get-started part
    # introduces both worked examples.
    text = "\n".join(b[1] for b in manual.manual_blocks() if b[0] == "md")
    text += "\n".join(str(b) for b in manual.manual_blocks() if b[0] == "table")
    for edition in ("2005", "DK NA", "2023"):
        assert edition in text
    assert "mild steel" in text.lower() and "prestress" in text.lower()


def test_manual_has_the_expected_parts_in_order():
    parts = [b[1] for b in manual.manual_blocks() if b[0] == "part"]
    assert parts == ["Part A - Get started", "Part B - Features & options",
                     "Part C - Theory & methodology", "Part D - Reference"]


def test_every_figure_block_builds():
    # Every figure referenced by the manual must build (the live curves, the
    # section drawings and the hand-drawn schematics), so no block renders as a
    # broken-figure placeholder.
    for b in manual.manual_blocks():
        if b[0] == "figure":
            assert b[1]() is not None, b[2]


def test_part_c_worked_numbers_match_the_engine():
    # The Part C derivations quote worked numbers for the beam example. Recompute
    # them so the prose cannot silently drift from the solver.
    ex = manual.example_beam()
    c, s = ex["concrete"], ex["steel"]
    assert c.fck / c.gamma_c * c.alpha_cc == pytest.approx(27.6, abs=0.1)   # fcd
    assert s.fytk / s.gamma_y == pytest.approx(458.0, abs=1.0)              # fyd
    # Curve 2 scales the elastic slope to Es/gamma_y, so the yield strain is
    # fytk/Es (not fyd/Es): 2.75 per mille for B550, as the manual now states.
    assert s.fytk / s.Es == pytest.approx(2.75e-3, abs=1e-5)
    sec = manual._section_of(ex)
    r = plastic_capacity_at_angle(sec, c, s, 0.0, 90.0)
    assert r.Mx == pytest.approx(346.0, abs=2.0)                            # capacity
    # eps_steel is a percentage: -1.89% = 18.9 per mille, past yield (2.75) but
    # below rupture (50) -- the worked point is tension-controlled, as stated.
    eps_frac = abs(r.eps_steel) / 100.0
    assert s.fytk / s.Es < eps_frac < s.eut
    fc = fctm(c.fck)
    editions = {
        "2005": (dict(), 0.188, 236.0),
        "fine": (dict(k3_cover_dependent=True), 0.164, 206.0),
        "coarse": (dict(k3_cover_dependent=True, coarse=True), 0.077, 184.0),
        "2023": (dict(edition="2023"), 0.186, 134.0),
    }
    for _name, (kw, wk, sr) in editions.items():
        cr = analyse_cracking(sec, 0.0, manual._BEAM_SLS_MX, 0.0, 6.0, fctm=fc,
                              bar_diameter=25.0, cover=37.5, beta=0.5, kt=0.4, **kw)
        assert cr.lambda_cr == pytest.approx(0.49, abs=0.02)
        assert cr.crack.wk == pytest.approx(wk, abs=0.005)
        assert cr.crack.sr_max == pytest.approx(sr, abs=1.5)


def test_part_b_documents_the_panels_and_options():
    # Part B is the feature/option reference: it must name the analysis modes, the
    # Quick Section shapes and the result views so it tracks the actual UI.
    text = "\n".join(str(b) for b in manual.manual_blocks())
    for token in ("Quick Section", "T-section", "Box girder", "Circular",
                  "Plastic", "Elastic", "Crack width", "Active in compression"):
        assert token in text, token


def test_latex_to_rl_converts_the_subset():
    # The PDF converter turns the LaTeX subset into ReportLab markup: Greek and
    # operators to entities, sub/superscripts to tags, fractions to a/b, and it
    # leaves no raw LaTeX punctuation behind.
    out = manual._latex_to_rl(
        r"\varphi = \min\!\left(\frac{\varepsilon_{cu2}}{c},\; "
        r"\frac{\varepsilon_{ud}}{s_{na}-s_{bar,min}}\right)^{2}")
    assert "&#966;" in out and "&#949;" in out            # phi, eps -> entities
    assert "<sub>cu2</sub>" in out and "<super>2</super>" in out
    assert "(s<sub>na</sub>-s<sub>bar,min</sub>)" in out  # compound denom parenthesised
    assert "min(" in out
    assert "\\" not in out and "{" not in out and "}" not in out  # nothing left over

    # A nested fraction (the EC2 7.9 mean strain has a tfrac inside the frac
    # numerator) must flatten fully -- no leftover 'frac' or backslash.
    nested = manual._latex_to_rl(
        r"\frac{\sigma_s - k_t\,\tfrac{f_{ct,eff}}{\rho_{p,eff}}(1+\alpha_e"
        r"\rho_{p,eff})}{E_s}")
    assert "frac" not in nested and "\\" not in nested
    assert nested.endswith("/E<sub>s</sub>")             # outer division survived

    # \text{...} labels (e.g. the prestress total strain) keep their content.
    txt = manual._latex_to_rl(r"\varepsilon_c(\text{tendon})")
    assert "(tendon)" in txt and "texttendon" not in txt and "\\" not in txt


def test_manual_pdf_builds_tables_only():
    # Build without the Plotly-to-PNG export (no kaleido/browser needed): a valid,
    # non-trivial PDF over all the content blocks.
    pdf = manual.build_manual_pdf_bytes(figures=False)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 8000


def test_manual_opens_from_the_sidebar_button():
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    assert not at.exception
    at.button(key="open_manual").click().run()
    assert not at.exception
    assert at.session_state["_manual_open"] is True
    assert any("Sector user manual" in m.value for m in at.markdown)
