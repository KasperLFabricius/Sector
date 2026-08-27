"""Focused direct-publication checks for transverse torsion provenance."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_transverse_provenance_reaches_every_publication_surface():
    expected = {
        "app/sector_app.py": ("torsional wall shear flow (6.27)",
                              "transverse equilibrium (6.8)",
                              "f_{yd})$ (6.28) ",
                              "must remain available beyond bending demand"),
        "app/sector_report.py": ("wall shear flow (6.27)",
                                 "transverse equilibrium (6.8)",
                                 'ref="EN 1992-1-1 (6.28)"'),
        "app/manual.py": ("torsional wall shear ", "flow (6.27)",
                          "transverse equilibrium (6.8)",
                          "(6.28), **in addition**"),
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
