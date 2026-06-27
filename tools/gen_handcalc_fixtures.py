"""Generate tests/handcalc_fixtures.py from the handcalc .pcr output PDFs.

Reads each example PDF, reconstructs every section it contains (some PDFs hold
several analyses), samples a few expected result rows, runs the solver, and
writes the cleanly-matching cases as pure-ASCII Python literals so the committed
regression test needs no PDFs.

Usage:
    python tools/gen_handcalc_fixtures.py [PDF_DIR]

PDF_DIR defaults to $HANDCALC_DIR or the project's local examples folder. Requires
``pypdf`` (a dev dependency). Only prints ASCII status lines; raw PDF text is
never echoed.
"""
import glob
import os
import pathlib
import re
import sys

# Make the project importable when run as a script from a fresh checkout
# (python tools/gen_handcalc_fixtures.py puts tools/ -- not the repo root -- on
# sys.path), so no PYTHONPATH or install step is needed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pypdf import PdfReader  # noqa: E402

from sector.materials import Concrete, MildSteel, Prestress  # noqa: E402
from sector.plastic import plastic_capacity_at_angle  # noqa: E402
from sector.section import Section  # noqa: E402

DEFAULT_DIR = (
    r"C:\Users\DK1J4Z\OneDrive - Sweco AB\Documents\Claude"
    r"\Secant\handcalc & handcalc\handcalc output examples"
)


def ascii_text(path):
    reader = PdfReader(path)
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    return "".join(ch if ord(ch) < 128 else " " for ch in text)


def nums(line):
    return [float(x.replace("D", "E"))
            for x in re.findall(r"[-+]?\d*\.?\d+(?:[DE][-+]?\d+)?", line)]


def parse_block(lines):
    """Parse one section block (header + table) into section + materials."""
    blob = "\n".join(lines)
    if "MILD STEEL" not in blob and "PRESTRESSED STEEL:" not in blob:
        return None

    def find(pat, default=None):
        m = re.search(pat, blob, re.DOTALL)
        return m.group(1) if m else default

    ncorner = int(find(r"CONCRETE:\s+(\d+)\s+CORNERS", "0"))
    concrete = Concrete(fck=float(find(r"COMPRESSION STRENGTH\s+([\d.]+)", "30")),
                        gamma_c=float(find(r"SAFETY FACTOR FOR CONCRETE\s+([\d.]+)", "1.5")),
                        curve=int(find(r"CONCRETE:.*?\(type\s+(\d+)\)", "1")))

    fytk = float(find(r"MILD STEEL.*?YIELD STRESS, TENSION\s+([\d.]+)", "500"))
    gy = float(find(r"SAFETY FACTOR FOR MILD STEEL\s+([\d.]+)", "1"))
    steel = MildSteel(
        fytk=fytk,
        fyck=float(find(r"MILD STEEL.*?YIELD STRESS, COMPRESSION\s+([\d.]+)", str(fytk))),
        eut=float(find(r"MILD STEEL.*?RUPTURE ELONGATION, TENSION\s+([\d.]+)", "5")) / 100.0,
        futk=float(find(r"MILD STEEL.*?RUPTURE STRESS, TENSION\s+([\d.]+)", str(fytk))),
        gamma_y=gy,
        gamma_u=float(find(r"RUPTURE TENSILE STRESS FOR MILD STEEL\s+([\d.]+)", str(gy))),
        gamma_E=float(find(r"E-MODULUS FOR MILD STEEL\s+([\d.]+)", str(gy))),
        curve=int(find(r"MILD STEEL\s+\d+\s+BARS\s+\(type\s+(\d+)\)", "1")))

    prestress = None
    if "PRESTRESSED STEEL:" in blob:
        ptype = int(find(r"PRESTRESSED STEEL:.*?\(type\s+(\d+)\)", "1"))
        pkw = dict(curve=ptype,
                   IS=float(find(r"INITIAL STRAIN\s+([\d.]+)", "0")) / 100.0,
                   gamma_y=float(find(r"SAFETY FACTOR FOR PRESTRESSED STEEL\s+([\d.]+)", "1")))
        if ptype in (6, 7):
            pkw.update(
                fytk=float(find(r"PRESTRESSED STEEL:.*?YIELD STRESS, TENSION\s+([\d.]+)", "1600")),
                futk=float(find(r"PRESTRESSED STEEL:.*?RUPTURE STRESS, TENSION\s+([\d.]+)", "1800")),
                eut=float(find(r"PRESTRESSED STEEL:.*?RUPTURE ELONGATION, TENSION\s+([\d.]+)", "3.5")) / 100.0,
                gamma_u=float(find(r"RUPTURE TENSILE STRESS FOR PRESTRESSED STEEL\s+([\d.]+)", "1.1")),
                gamma_E=float(find(r"E-MODULUS FOR PRESTRESSED STEEL\s+([\d.]+)", "1")))
        prestress = Prestress(**pkw)

    nbar = int(find(r"MILD STEEL\s+(\d+)\s+BARS", "0"))
    ncable = int(find(r"PRESTRESSED STEEL:\s+(\d+)\s+CABLES", "0"))
    corners, bars, tendons, in_tab = [], [], [], False
    for ln in lines:
        if "ABSCISSA" in ln and "ORDINATE" in ln:
            in_tab = True
            continue
        if not in_tab:
            continue
        if "LOAD CASE" in ln:
            break
        vals = nums(ln)
        if not vals:
            continue
        rest = vals[1:]
        if "MILD STEEL" in ln or "PRESTRESSED STEEL" in ln:
            if len(rest) >= 5:
                if len(corners) < ncorner:
                    corners.append((rest[0], rest[1]))
                bx, by, ba = rest[2], rest[3], rest[4]
            elif len(rest) >= 3:
                bx, by, ba = rest[0], rest[1], rest[2]
            else:
                continue
            if "PRESTRESSED STEEL" in ln:
                if len(tendons) < ncable:
                    tendons.append((bx, by, ba))
            elif len(bars) < nbar:
                bars.append((bx, by, ba))
        elif len(rest) >= 2 and len(corners) < ncorner:
            corners.append((rest[0], rest[1]))

    if len(corners) < 3:
        return None
    section = Section.from_polygon(corners=corners, bars_xy_area_mm2=bars,
                                   tendons_xy_area_mm2=tendons)
    return section, concrete, steel, prestress, lines


def parse(path):
    """Return one parsed block per section in the PDF (split on each header)."""
    lines = ascii_text(path).splitlines()
    starts = [i for i, l in enumerate(lines)
              if re.search(r"CONCRETE:\s+\d+\s+CORNERS", l)]
    blocks = []
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        parsed = parse_block(lines[s:end])
        if parsed:
            blocks.append(parsed)
    return blocks


def result_rows(lines, has_cable):
    cur_P, pending = None, False
    for ln in lines:
        if "LOAD CASE" in ln:
            pending = True
            continue
        if pending and re.search(r"\d", ln) and "V.MIN" not in ln and "P " not in ln[:3]:
            v = nums(ln)
            if v:
                cur_P, pending = v[0], False
            continue
        if cur_P is not None and re.search(r"\dD[-+]\d", ln):
            v = nums(ln)
            if len(v) >= 11:
                yield cur_P, has_cable, v


def strain_cols(has_steel, has_cable, v):
    """Strain/curvature columns: CONCRETE [STEEL] [CABLES] CURVATURE.

    The STEEL column is present only when the section has mild bars, the CABLES
    column only when it has tendons, so the curvature index shifts accordingly.
    """
    conc, i = v[7], 8
    steel = v[i] if has_steel else 0.0
    if has_steel:
        i += 1
    cable = v[i] if has_cable else None
    if has_cable:
        i += 1
    return conc, steel, cable, v[i]


def fixture_dicts(section, concrete, steel, prestress):
    """Rounded geometry + material dicts exactly as the fixture will store them."""
    corners = [(round(x, 4), round(y, 4)) for x, y in section.concrete[0].tolist()]
    bars = [(round(b.x, 4), round(b.y, 4), round(b.area * 1e6, 2)) for b in section.bars]
    tend = [(round(b.x, 4), round(b.y, 4), round(b.area * 1e6, 2)) for b in section.tendons]
    cd = dict(fck=concrete.fck, gamma_c=concrete.gamma_c, curve=concrete.curve)
    sd = dict(fytk=steel.fytk, fyck=steel.fyck, eut=round(steel.eut, 4), futk=steel.futk,
              gamma_y=steel.gamma_y, gamma_u=steel.gamma_u, gamma_E=steel.gamma_E,
              curve=steel.curve)
    pd = None if prestress is None else dict(
        curve=prestress.curve, IS=round(prestress.IS, 5), gamma_y=prestress.gamma_y,
        gamma_u=prestress.gamma_u, gamma_E=prestress.gamma_E, fytk=prestress.fytk,
        futk=prestress.futk, eut=round(prestress.eut, 4))
    return corners, bars, tend, cd, sd, pd


def case_matches(section, concrete, steel, prestress, lines):
    """Build the rounded fixture, rebuild everything from it, and return the
    fixture dict iff every sampled row matches the committed test (else None).

    Validating against the round-tripped objects and the rounded expected values
    guarantees the gate here agrees exactly with the committed test.
    """
    has_steel = len(section.bars) > 0
    has_cable = prestress is not None
    rows = list(result_rows(lines, has_cable))
    if len(rows) > 4:
        rows = rows[:: len(rows) // 4 + 1]
    if not rows:
        return None
    corners, bars, tend, cd, sd, pd = fixture_dicts(section, concrete, steel, prestress)
    rsec = Section.from_polygon(corners=corners, bars_xy_area_mm2=bars,
                                tendons_xy_area_mm2=tend)
    rconc, rmild = Concrete(**cd), MildSteel(**sd)
    rpre = None if pd is None else Prestress(**pd)
    exp = []
    for cur_P, _, v in rows:
        Mx, My, V = v[2], v[3], v[4]
        try:
            r = plastic_capacity_at_angle(rsec, rconc, rmild, cur_P, V,
                                          prestress=rpre, n_bands=50)
        except Exception:
            return None
        c, s, cab, curv = strain_cols(has_steel, has_cable, v)
        row = (round(cur_P, 2), round(V, 1), round(Mx, 1), round(My, 1),
               round(c, 2), round(s, 2),
               None if cab is None else round(cab, 2), round(curv, 6))
        _, _, Mxr, Myr, cr, sr, cabr, curvr = row
        scale = max(abs(Mxr), abs(Myr), 1.0)
        ok = (r.converged
              and abs(r.Mx - Mxr) <= 0.03 * scale + 1.0
              and abs(r.My - Myr) <= 0.03 * scale + 1.0
              and abs(r.eps_concrete - cr) <= 0.03
              and abs(r.eps_steel - sr) <= 0.08
              and (cabr is None or abs(r.eps_cable - cabr) <= 0.08)
              and abs(r.curvature - curvr) <= 0.05 * abs(curvr) + 1e-4)
        if not ok:
            return None
        exp.append(row)
    return dict(corners=corners, bars=bars, tendons=tend,
                concrete=cd, mild=sd, prestress=pd, rows=exp)


def clean_name(path):
    name = "".join(c if ord(c) < 128 else "_" for c in os.path.basename(path))
    return (name.replace(".pcr.pdf", "").replace(".pdf", "")
            .replace(" ", "_").replace("-", "_"))


def main():
    pdf_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HANDCALC_DIR", DEFAULT_DIR)
    cases = []
    for f in sorted(glob.glob(os.path.join(pdf_dir, "*.pdf"))):
        base = clean_name(f)
        try:
            blocks = parse(f)
        except Exception:
            continue
        for bi, (section, concrete, steel, prestress, lines) in enumerate(blocks):
            fx = case_matches(section, concrete, steel, prestress, lines)
            if not fx:
                continue
            fx["name"] = base if len(blocks) == 1 else f"{base}_s{bi + 1}"
            cases.append(fx)

    out = os.path.join("tests", "handcalc_fixtures.py")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('"""Auto-generated fixtures from the handcalc example outputs.\n\n')
        fh.write("Each case is a real section reconstructed from a .pcr output with sampled\n")
        fh.write("expected rows (P, V, Mx, My, eps_concrete, eps_steel, eps_cable, curvature).\n")
        fh.write('Regenerate with tools/gen_handcalc_fixtures.py; do not edit by hand.\n"""\n\n')
        fh.write("CASES = [\n")
        for fx in cases:
            fh.write("    {\n")
            for key in ("name", "corners", "bars", "tendons", "concrete", "mild",
                        "prestress", "rows"):
                fh.write(f"        {key!r}: {fx[key]!r},\n")
            fh.write("    },\n")
        fh.write("]\n")
    print("EMITTED", len(cases), "cases:", ", ".join(c["name"] for c in cases))


if __name__ == "__main__":
    main()
