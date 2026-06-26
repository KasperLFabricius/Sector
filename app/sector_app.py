"""Sector - reinforced-concrete cross-section analysis (Streamlit interface).

Define a section by its shape and reinforcement, choose elastic and/or plastic
analysis, then press Calculate to review the stresses and the ultimate capacity.
"""

from __future__ import annotations

import pathlib
import sys

# Make both the repo root (for ``sector``) and this app folder (for ``viz``)
# importable when run as a script or via Streamlit's AppTest.
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

import numpy as np  # noqa: E402
import streamlit as st  # noqa: E402

import viz  # noqa: E402
from sector import codes, kernels, templates  # noqa: E402
from sector.elastic import solve_elastic  # noqa: E402
from sector.materials import Concrete, MildSteel  # noqa: E402
from sector.plastic import solve_plastic  # noqa: E402
from sector.section import Section  # noqa: E402

APP_VERSION = "0.1.0"
ROOT = pathlib.Path(__file__).resolve().parent.parent

st.set_page_config(layout="wide", page_title=f"Sector v{APP_VERSION}")


@st.cache_resource(show_spinner="Preparing the solver...")
def _warm_solver():
    """Compile the solver kernels once per server, so the cost is paid at
    startup rather than on the first Calculate."""
    return kernels.warmup()


_warm_solver()

_logo = ROOT / "assets" / "logo.png"
if _logo.exists():
    st.sidebar.image(str(_logo), use_container_width=True)

st.title(f"Sector v{APP_VERSION}")
st.caption("Reinforced-concrete cross-section analysis - elastic stresses and plastic capacity")


# ---------------------------------------------------------------------------
# Build the section + materials from the sidebar inputs
# ---------------------------------------------------------------------------

def build_inputs():
    s = st.sidebar
    s.header("Section")
    shape = s.selectbox("Shape", ["Rectangle", "Slab strip", "T-section",
                                  "Box girder", "Circular"], key="shape")

    holes = []
    if shape == "Rectangle":
        b = s.number_input("Width b (m)", 0.05, 10.0, 0.40, 0.05, key="b")
        h = s.number_input("Height h (m)", 0.05, 10.0, 0.60, 0.05, key="h")
        outer = templates.rectangle(b, h)
        width_b = b
    elif shape == "Slab strip":
        h = s.number_input("Thickness h (m)", 0.05, 3.0, 0.30, 0.01, key="h")
        b = 1.0
        outer = templates.slab_strip(h)
        width_b = b
    elif shape == "T-section":
        bf = s.number_input("Flange width bf (m)", 0.1, 12.0, 1.20, 0.05, key="bf")
        hf = s.number_input("Flange thickness hf (m)", 0.05, 2.0, 0.20, 0.01, key="hf")
        bw = s.number_input("Web width bw (m)", 0.05, 4.0, 0.30, 0.05, key="bw")
        hw = s.number_input("Web depth hw (m)", 0.1, 6.0, 0.60, 0.05, key="hw")
        outer = templates.t_section(bf, hf, bw, hw)
        b, h, width_b = bw, hf + hw, bf
    elif shape == "Box girder":
        b = s.number_input("Width b (m)", 0.2, 12.0, 0.80, 0.05, key="b")
        h = s.number_input("Height h (m)", 0.2, 12.0, 1.00, 0.05, key="h")
        # Cap the wall so the cavity stays positive (2*wall < b and < h).
        max_wall = round(min(b, h) / 2 - 0.01, 3)
        wall = s.number_input("Wall thickness (m)", 0.02, max_wall,
                              min(0.20, max_wall), 0.01, key="wall")
        outer, holes = templates.box(b, h, wall)
        width_b = b
    else:  # Circular
        dia = s.number_input("Diameter (m)", 0.1, 6.0, 0.60, 0.05, key="dia")
        outer = templates.circular(dia)
        b = h = dia
        width_b = dia

    s.header("Reinforcement")
    if shape == "Circular":
        nb = s.number_input("Perimeter bars", 0, 200, 8, 1, key="ring_n")
        rd = s.selectbox("Bar diameter (mm)", templates.BAR_DIAMETERS, index=4, key="ring_d")
        cov = s.number_input("Cover (m)", 0.0, 0.5, 0.05, 0.005, key="ring_c")
        bars = templates.bar_ring(0.0, 0.0, dia / 2 - cov, int(nb), rd)
    else:
        c1, c2 = s.columns(2)
        with c1:
            st.markdown("**Bottom**")
            nb_bot = st.number_input("n##bot", 0, 100, 6, 1, key="bot_n", label_visibility="collapsed")
            rd_bot = st.selectbox("dia##bot", templates.BAR_DIAMETERS, index=4, key="bot_d", label_visibility="collapsed")
        with c2:
            st.markdown("**Top**")
            nb_top = st.number_input("n##top", 0, 100, 2, 1, key="top_n", label_visibility="collapsed")
            rd_top = st.selectbox("dia##top", templates.BAR_DIAMETERS, index=4, key="top_d", label_visibility="collapsed")
        cov = s.number_input("Cover (m)", 0.0, 0.5, 0.05, 0.005, key="cover")
        bw_eff = width_b if shape == "T-section" else b
        bars = templates.merge_bars(
            templates.bar_row(-h / 2 + cov, -(b if shape != "T-section" else bw_eff) / 2 + cov,
                              (b if shape != "T-section" else bw_eff) / 2 - cov, int(nb_bot), rd_bot)
            if shape != "T-section" else
            templates.bar_row(-(hf + hw) / 2 + cov, -bw / 2 + cov, bw / 2 - cov, int(nb_bot), rd_bot),
            templates.bar_row(h / 2 - cov, -width_b / 2 + cov, width_b / 2 - cov, int(nb_top), rd_top),
        )

    s.header("Materials")
    basis = s.selectbox("Design basis", ["Manual"] + list(codes.CODES), key="basis")
    if basis == "Manual":
        fck = s.number_input("Concrete fck (MPa)", 10.0, 100.0, 35.0, 1.0, key="fck")
        gc = s.number_input("Concrete gamma_c", 1.0, 2.0, 1.5, 0.01, key="gc")
        fyk = s.number_input("Steel fyk (MPa)", 200.0, 700.0, 500.0, 10.0, key="fyk")
        gs = s.number_input("Steel gamma_s", 1.0, 1.5, 1.15, 0.01, key="gs")
        concrete = Concrete(fck=fck, gamma_c=gc, curve=2)
        steel = MildSteel(fytk=fyk, fyck=fyk, eut=0.05, gamma_y=gs, curve=2)
    else:
        code = codes.CODES[basis]
        cclass = s.selectbox("Concrete class", list(codes.CONCRETE_CLASSES),
                             index=4, key="cclass")
        grade = s.selectbox("Reinforcement grade", list(codes.STEEL_GRADES),
                            key="grade")
        concrete = code.concrete(codes.CONCRETE_CLASSES[cclass])
        steel = code.steel(codes.STEEL_GRADES[grade])
        s.caption(
            f"gamma_c = {code.gamma_c:g}, gamma_s = {code.gamma_s:g}, "
            f"alpha_cc = {code.alpha_cc:g}, eps_ud = {code.eps_ud:.3f}"
        )

    s.header("Loads")
    P = s.number_input("Axial force P (kN, + = compression)", -50000.0, 50000.0, 0.0, 50.0, key="P")
    mode = s.radio("Analysis", ["Plastic", "Elastic", "Both"], key="mode")
    if mode in ("Elastic", "Both"):
        Mx = s.number_input("Applied Mx (kNm)", -100000.0, 100000.0, 200.0, 10.0, key="Mx")
        My = s.number_input("Applied My (kNm)", -100000.0, 100000.0, 0.0, 10.0, key="My")
        ratio = s.number_input("Modular ratio n = Es/Ec", 5.0, 30.0, 15.0, 0.5, key="ratio")
    else:
        Mx = s.number_input("Applied Mx (kNm)", -100000.0, 100000.0, 200.0, 10.0, key="Mx")
        My = s.number_input("Applied My (kNm)", -100000.0, 100000.0, 0.0, 10.0, key="My")
        ratio = 15.0

    section = Section.from_polygon(corners=outer, bars_xy_area_mm2=bars, holes=holes)
    extent = max(abs(b), abs(h)) * 0.75
    sig = (st.session_state.get(k) for k in
           ("shape", "b", "h", "bf", "hf", "bw", "hw", "wall", "dia",
            "bot_n", "bot_d", "top_n", "top_d", "ring_n", "ring_d", "ring_c",
            "cover", "basis", "cclass", "grade", "fck", "gc", "fyk", "gs",
            "P", "Mx", "My", "ratio", "mode"))
    return dict(section=section, concrete=concrete, steel=steel, ratio=ratio,
                bars=bars, outer=outer, holes=holes, P=P, Mx=Mx, My=My, mode=mode,
                extent=extent, signature=tuple(sig))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def run_analysis(inp):
    out = {}
    if inp["mode"] in ("Plastic", "Both"):
        pts = solve_plastic(inp["section"], inp["concrete"], inp["steel"],
                            inp["P"], 0.0, 360.0, 15.0)
        mx = [p.Mx for p in pts]
        my = [p.My for p in pts]
        out["plastic"] = dict(
            mx=mx, my=my,
            max_mx=max(mx), max_my=max(my),
            util=_radial_util(mx, my, inp["Mx"], inp["My"]),
            converged=all(p.converged for p in pts),
        )
    if inp["mode"] in ("Elastic", "Both"):
        r = solve_elastic(inp["section"], inp["P"], inp["Mx"], inp["My"], inp["ratio"])
        out["elastic"] = dict(
            bar_stress=[s / 1000.0 for s in r.bar_stress],  # kN/m2 -> MPa
            max_conc=r.max_concrete_compression / 1000.0,
            na_x=r.na_x_intercept, na_y=r.na_y_intercept,
            converged=r.converged,
        )
    return out


def _radial_util(mx, my, ax, ay):
    a_rad = float(np.hypot(ax, ay))
    if a_rad < 1e-9:
        return 0.0
    angs = np.arctan2(my, mx)
    rad = np.hypot(mx, my)
    order = np.argsort(angs)
    angs_s, rad_s = angs[order], rad[order]
    ext_a = np.concatenate([angs_s - 2 * np.pi, angs_s, angs_s + 2 * np.pi])
    ext_r = np.concatenate([rad_s, rad_s, rad_s])
    cap = float(np.interp(np.arctan2(ay, ax), ext_a, ext_r))
    return a_rad / cap if cap > 0 else float("inf")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

inp = build_inputs()
calc = st.sidebar.button("Calculate", type="primary", key="calculate")

if calc:
    st.session_state["results"] = run_analysis(inp)
    st.session_state["result_sig"] = inp["signature"]

results = st.session_state.get("results")
stale = results is not None and st.session_state.get("result_sig") != inp["signature"]

left, right = st.columns(2)
with left:
    bar_xy = [(b[0], b[1]) for b in inp["bars"]]
    na_line = None
    if results and "elastic" in results:
        na_line = viz.na_endpoints(results["elastic"]["na_x"],
                                   results["elastic"]["na_y"], inp["extent"])
    st.plotly_chart(viz.section_figure(inp["outer"], inp["holes"], bar_xy,
                                       na_line=na_line, title="Section"),
                    use_container_width=True)

with right:
    if results is None:
        st.info("Define the section, then press Calculate.")
    else:
        if stale:
            st.warning("Inputs changed since the last calculation - press Calculate to update.")
        if "plastic" in results:
            p = results["plastic"]
            st.subheader("Plastic capacity")
            m1, m2, m3 = st.columns(3)
            m1.metric("Max Mx", f"{p['max_mx']:.0f} kNm")
            m2.metric("Max My", f"{p['max_my']:.0f} kNm")
            u = p["util"]
            m3.metric("Utilisation", f"{u:.2f}", help="applied / capacity in the load direction")
            st.plotly_chart(
                viz.interaction_figure(p["mx"], p["my"], applied=(inp["Mx"], inp["My"])),
                use_container_width=True)
        if "elastic" in results:
            e = results["elastic"]
            st.subheader("Elastic stresses")
            st.metric("Max concrete compression", f"{e['max_conc']:.1f} MPa")
            st.dataframe(
                {"Bar": list(range(1, len(e["bar_stress"]) + 1)),
                 "Stress (MPa)": [round(s, 1) for s in e["bar_stress"]]},
                hide_index=True, use_container_width=True)
