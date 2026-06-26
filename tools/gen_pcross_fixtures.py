"""Generate tests/pcross_fixtures.py from the legacy PCROSS .pcr output PDFs.

Reads each example PDF, reconstructs the section + materials, samples a few
expected result rows, runs the solver, and writes the cleanly-matching cases as
pure-ASCII Python literals so the committed regression test needs no PDFs.

Usage:
    python tools/gen_pcross_fixtures.py [PDF_DIR]

PDF_DIR defaults to $PCROSS_DIR or the project's local examples folder. Requires
``pypdf`` (a dev dependency). Only prints ASCII status lines; raw PDF text is
never echoed.
"""
import glob
import os
import pathlib
import re
import sys

# Make the project importable when run as a script from a fresh checkout
# (python tools/gen_pcross_fixtures.py puts tools/ -- not the repo root -- on
# sys.path), so no PYTHONPATH or install step is needed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pypdf import PdfReader  # noqa: E402

from sector.materials import Concrete, MildSteel, Prestress  # noqa: E402
from sector.plastic import plastic_capacity_at_angle  # noqa: E402
from sector.section import Section  # noqa: E402

DEFAULT_DIR = (
    r"C:\Users\DK1J4Z\OneDrive - Sweco AB\Documents\Claude"
    r"\Secant\Pcross & Ecross\Pcross output examples"
)


def ascii_text(path):
    reader = PdfReader(path)
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    return "".join(ch if ord(ch) < 128 else " " for ch in text)


def nums(line):
    return [float(x.replace("D", "E"))
            for x in re.findall(r"[-+]?\d*\.?\d+(?:[DE][-+]?\d+)?", line)]


def parse(path):
    blob = ascii_text(path)
    lines = blob.splitlines()
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
    conc = v[7]
    i = 8
    steel = v[i] if has_steel else 0.0
    if has_steel:
        i += 1
    cable = v[i] if has_cable else None
    if has_cable:
        i += 1
    return conc, steel, cable, v[i]


def main():
    pdf_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PCROSS_DIR", DEFAULT_DIR)
    cases = []
    for f in sorted(glob.glob(os.path.join(pdf_dir, "*.pdf"))):
        name = "".join(c if ord(c) < 128 else "_" for c in os.path.basename(f))
        name = name.replace(".pcr.pdf", "").replace(".pdf", "").replace(" ", "_").replace("-", "_")
        try:
            parsed = parse(f)
        except Exception:
            continue
        if parsed is None:
            continue
        section, concrete, steel, prestress, lines = parsed
        has_steel = len(section.bars) > 0
        rows = list(result_rows(lines, prestress is not None))
        if len(rows) > 4:
            rows = rows[:: len(rows) // 4 + 1]
        exp, good = [], bool(rows)
        for cur_P, has_cable, v in rows:
            Mx, My, V = v[2], v[3], v[4]
            try:
                r = plastic_capacity_at_angle(section, concrete, steel, cur_P, V,
                                              prestress=prestress, n_bands=40)
            except Exception:
                good = False
                break
            if max(abs(r.Mx - Mx), abs(r.My - My)) / max(abs(Mx), abs(My), 1.0) > 0.025:
                good = False
                break
            c, s, cab, curv = strain_cols(has_steel, has_cable, v)
            exp.append((round(cur_P, 2), round(V, 1), round(Mx, 1), round(My, 1),
                        round(c, 2), round(s, 2),
                        None if cab is None else round(cab, 2), round(curv, 6)))
        if good and exp:
            cases.append((name, section, concrete, steel, prestress, exp))

    out = os.path.join("tests", "pcross_fixtures.py")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('"""Auto-generated fixtures from the legacy PCROSS example outputs.\n\n')
        fh.write("Each case is a real section reconstructed from a .pcr output with sampled\n")
        fh.write("expected rows (P, V, Mx, My, eps_concrete, eps_steel, eps_cable, curvature).\n")
        fh.write('Regenerate with tools/gen_pcross_fixtures.py; do not edit by hand.\n"""\n\n')
        fh.write("CASES = [\n")
        for name, sec, c, s, p, exp in cases:
            corners = [(round(x, 4), round(y, 4)) for x, y in sec.concrete[0].tolist()]
            bars = [(round(b.x, 4), round(b.y, 4), round(b.area * 1e6, 2)) for b in sec.bars]
            tend = [(round(b.x, 4), round(b.y, 4), round(b.area * 1e6, 2)) for b in sec.tendons]
            cd = dict(fck=c.fck, gamma_c=c.gamma_c, curve=c.curve)
            sd = dict(fytk=s.fytk, fyck=s.fyck, eut=round(s.eut, 4), futk=s.futk,
                      gamma_y=s.gamma_y, gamma_u=s.gamma_u, gamma_E=s.gamma_E, curve=s.curve)
            pd = None if p is None else dict(curve=p.curve, IS=round(p.IS, 5),
                                             gamma_y=p.gamma_y, gamma_u=p.gamma_u,
                                             gamma_E=p.gamma_E, fytk=p.fytk, futk=p.futk,
                                             eut=round(p.eut, 4))
            fh.write("    {\n")
            fh.write(f"        \"name\": {name!r},\n")
            fh.write(f"        \"corners\": {corners!r},\n")
            fh.write(f"        \"bars\": {bars!r},\n")
            fh.write(f"        \"tendons\": {tend!r},\n")
            fh.write(f"        \"concrete\": {cd!r},\n")
            fh.write(f"        \"mild\": {sd!r},\n")
            fh.write(f"        \"prestress\": {pd!r},\n")
            fh.write(f"        \"rows\": {exp!r},\n")
            fh.write("    },\n")
        fh.write("]\n")
    print("EMITTED", len(cases), "cases:", ", ".join(c[0] for c in cases))


if __name__ == "__main__":
    main()
