"""Focused publication and trace checks for transverse torsion provenance."""

from pathlib import Path

from sector.torsion_trace_contract import LONGITUDINAL_SOURCE, TRANSVERSE_SOURCE


ROOT = Path(__file__).resolve().parents[1]


def test_transverse_and_longitudinal_torsion_sources_are_distinct():
    transverse = TRANSVERSE_SOURCE.citation
    longitudinal = LONGITUDINAL_SOURCE.citation

    assert transverse is not None
    assert transverse.clause == "6.3.2(1) and 6.2.3(3)"
    assert transverse.locator == "Formulae (6.27) and (6.8)"
    assert longitudinal is not None
    assert longitudinal.clause == "6.3.2(3)"
    assert longitudinal.locator == "Formula (6.28)"
    assert TRANSVERSE_SOURCE != LONGITUDINAL_SOURCE


def test_transverse_provenance_reaches_every_publication_surface():
    expected = {
        "app/sector_app.py": ("torsional wall shear flow (6.27)",
                              "transverse equilibrium (6.8)"),
        "app/sector_report.py": ("wall shear flow (6.27)",
                                 "transverse equilibrium (6.8)"),
        "app/manual.py": ("torsional wall shear ", "flow (6.27)",
                          "transverse equilibrium (6.8)"),
        "sector/torsion.py": ("6.27 + 6.8", "Formula 6.28 separately defines"),
    }

    for relative, fragments in expected.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for fragment in fragments:
            assert fragment in text, (relative, fragment)


def test_transverse_surfaces_do_not_attribute_resistance_to_formula_628():
    forbidden = (
        "T_{Rd,s} = (A_{sw}/s)\\,2 A_k f_{ywd}\\cot\\theta$ (6.28)",
        "ref=\"from EN 1992-1-1 (6.28)\"",
        "Closed stirrups   ``TRd,s   = (Asw/s) * 2*Ak * fywd * "
        "cot(theta)``      (from 6.28)",
    )
    combined = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in ("app/sector_app.py", "app/sector_report.py", "sector/torsion.py")
    )
    for fragment in forbidden:
        assert fragment not in combined
