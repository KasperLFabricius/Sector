"""Independent worksheet arithmetic and numerical procedures for the manual.

These examples use explicit polygon sums and elementary material equations.
They do not call Sector's geometry, material or section solvers. Production
comparison belongs to the tests, so the published arithmetic is independently
checkable.
"""

from __future__ import annotations

from functools import lru_cache
import math

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _dot3(left, right):
    """Evaluate three terms in a fixed order, independent of BLAS dispatch."""
    return (float(left[0]) * float(right[0]) +
            float(left[1]) * float(right[1]) +
            float(left[2]) * float(right[2]))


def _solve3(matrix, target):
    """Solve three equations by scalar elimination with partial pivoting.

    Fixed-order Python float operations keep the published worksheet operands
    reproducible across CPU-specific BLAS kernels. No operands are rounded.
    """
    rows = [[float(value) for value in row] + [float(rhs)]
            for row, rhs in zip(matrix, target)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(rows[row][column]))
        if rows[pivot][column] == 0:
            raise ValueError("The manual worksheet matrix is singular.")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for row in range(column + 1, 3):
            factor = rows[row][column] / rows[column][column]
            rows[row][column] = 0.0
            for entry in range(column + 1, 4):
                rows[row][entry] -= factor * rows[column][entry]
    solution = [0.0] * 3
    for row in range(2, -1, -1):
        rhs = rows[row][3]
        for column in range(row + 1, 3):
            rhs -= rows[row][column] * solution[column]
        solution[row] = rhs / rows[row][row]
    return np.array(solution)


def clip_polygon(points, plane):
    """Keep q <= 0 with the edge intersection stated in the manual."""
    if not points:
        return []
    q0, gx, gy = map(float, plane)
    result = []
    for a, b in zip(points, points[1:] + points[:1]):
        da = q0 + gx * a[0] + gy * a[1]
        db = q0 + gx * b[0] + gy * b[1]
        if da <= 0:
            result.append(a)
        if (da <= 0) != (db <= 0):
            t = da / (da - db)
            result.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return result


def polygon_sums(points):
    """Signed A, Sx, Sy, Sxx, Syy and Sxy, using explicit edge sums."""
    values = [0.0] * 6
    if len(points) < 3:
        return np.array(values)
    for (x, y), (u, v) in zip(points, points[1:] + points[:1]):
        cross = x * v - u * y
        terms = [
            1 / 2, (x + u) / 6, (y + v) / 6,
            (x * x + x * u + u * u) / 12,
            (y * y + y * v + v * v) / 12,
            (2 * x * y + x * v + u * y + 2 * u * v) / 24,
        ]
        for index, term in enumerate(terms):
            values[index] += cross * term
    return np.array(values)


def worksheet_matrix(outer, holes, elements, plane, *, cracked):
    """Assemble the three equilibrium rows in the documented order."""
    region = clip_polygon(outer, plane) if cracked else outer
    moments = polygon_sums(region)
    clipped_holes = []
    for hole in holes:
        cut = clip_polygon(hole, plane) if cracked else hole
        clipped_holes.append(cut)
        moments = np.array([float(a) - float(b)
                            for a, b in zip(moments, polygon_sums(cut))])
    area, sx, sy, sxx, syy, sxy = map(float, moments)
    matrix = [[area, sx, sy], [sy, sxy, syy], [sx, sxx, sxy]]
    for x, y, area, ratio, _locked in elements:
        q = _dot3(plane, [1, x, y])
        weight = (ratio - int(not cracked or q < 0)) * area
        for row, row_factor in enumerate((1, y, x)):
            for column, column_factor in enumerate((1, x, y)):
                matrix[row][column] += weight * (row_factor * column_factor)
    return np.array(matrix), moments, region, clipped_holes


def worksheet_solve(outer, holes, elements, target):
    """Full-step Newton iteration with retained operands for publication."""
    initial, _, _, _ = worksheet_matrix(outer, holes, elements, np.zeros(3), cracked=False)
    plane = _solve3(initial, target)
    trace = []
    tolerance = 1e-9 * max(1, max(abs(target)))
    for iteration in range(1, 101):
        matrix, moments, region, voids = worksheet_matrix(outer, holes, elements, plane, cracked=True)
        internal = np.array([_dot3(row, plane) for row in matrix])
        residual = np.array([float(a) - float(b) for a, b in zip(internal, target)])
        accepted = max(abs(residual)) <= tolerance
        correction = np.zeros(3) if accepted else _solve3(matrix, -residual)
        trace.append(dict(iteration=iteration, plane=plane.copy(), matrix=matrix,
                          moments=moments, region=region, voids=voids,
                          internal=internal, residual=residual, correction=correction))
        if accepted:
            break
        plane = np.array([float(a) + float(b) for a, b in zip(plane, correction)])
    else:
        raise ValueError("The manual worksheet example did not converge.")
    passive = np.array([ratio * _dot3(plane, [1, x, y])
                        for x, y, _area, ratio, _locked in elements])
    return dict(initial=initial, trace=trace, plane=plane, passive=passive,
                tolerance=tolerance, target=np.array(target), elements=elements)


def element_resultants(stresses, elements):
    values = [0.0] * 3
    for stress, (x, y, area, _ratio, _locked) in zip(stresses, elements):
        force = float(stress) * area
        for index, factor in enumerate((1, y, x)):
            values[index] += force * factor
    return np.array(values)


@lru_cache(maxsize=1)
def biaxial_example():
    outer = [(-0.2, -0.3), (0.2, -0.3), (0.2, 0.15), (0.05, 0.3), (-0.2, 0.3)]
    holes = [[(-0.07, -0.02), (0.03, -0.02), (0.03, 0.08), (-0.07, 0.08)]]
    bar_area = math.pi * 0.025**2 / 4
    elements = [(x, y, bar_area, 6.0, 0.0)
                for x, y in [(-0.15, -0.25), (0.15, -0.25), (0.15, 0.1), (-0.15, 0.25)]]
    elements.append((0.05, -0.18, 150e-6, 5.85, 195000e3 * 0.005))
    locked = np.array([row[4] for row in elements])
    prestress = element_resultants(locked, elements)
    applied = np.array([-200.0, -100.0, -40.0])
    result = worksheet_solve(outer, holes, elements, applied - prestress)
    long_elements = [(x, y, area, ratio * 3, lock) for x, y, area, ratio, lock in elements]
    long = worksheet_solve(outer, holes, long_elements, np.array([-200., -70., -30.]) - prestress)
    retained = long["passive"] * (2 / 3)
    neutralising = element_resultants(retained, elements)
    instant = worksheet_solve(outer, holes, elements, applied - prestress - neutralising)
    total = retained + instant["passive"] + locked
    long_total = long["passive"] + locked
    return dict(outer=outer, holes=holes, elements=elements, locked=locked,
                prestress=prestress, applied=applied, elastic=result, long=long,
                retained=retained, neutralising=neutralising, instant=instant,
                total=total, long_total=long_total, difference=total-long_total)


def rectangular_plastic_trial(depth):
    """Independent 80-band rectangle, bilinear bars and first strain limit."""
    s_na = 0.3 - depth
    bars = [(-0.25, math.pi * 0.025**2 / 4)] * 3 + [(0.25, math.pi * 0.016**2 / 4)] * 2
    candidates = [(0.0035 / depth, "Concrete")]
    candidates += [(0.05 * (1 - 1e-9) / abs(y - s_na), f"Bar {index}")
                   for index, (y, _area) in enumerate(bars, 1) if y != s_na]
    curvature, governing = min(candidates, key=lambda row: row[0])
    s_peak = s_na + 0.002 / curvature
    high = min(0.3, s_peak)
    delta = (high - s_na) / 80
    fcd = 40 / 1.45
    regions = []
    for index in range(80):
        lower = s_na + index * delta
        upper = s_na + (index + 1) * delta
        midpoint = (lower + upper) / 2
        strain = curvature * (midpoint - s_na)
        stress = fcd * (1 - (1 - strain / 0.002)**2)
        actual_lower, actual_upper = max(lower, -0.3), min(upper, 0.3)
        area = 0.3 * max(0, actual_upper - actual_lower)
        sy = area * (actual_lower + actual_upper) / 2
        force, moment = stress * area * 1000, stress * sy * 1000
        regions.append((lower, upper, midpoint, strain, stress, area, sy, force, moment))
    plateau_low = max(s_peak, -0.3)
    plateau_area = 0.3 * max(0, 0.3 - plateau_low)
    plateau_sy = plateau_area * (plateau_low + 0.3) / 2
    plateau = (plateau_low, 0.3, fcd, plateau_area, plateau_sy,
               fcd * plateau_area * 1000, fcd * plateau_sy * 1000)
    reinforcement = []
    for y, area in bars:
        strain = curvature * (y - s_na)
        stress = max(-550 / 1.2, min(550 / 1.2, 200000 * strain))
        force = stress * area * 1000
        reinforcement.append((y, area, strain, stress, force, force * y))
    axial = sum(row[7] for row in regions) + plateau[5] + sum(row[4] for row in reinforcement)
    moment = sum(row[8] for row in regions) + plateau[6] + sum(row[5] for row in reinforcement)
    return dict(depth=depth, s_na=s_na, s_peak=s_peak, curvature=curvature,
                governing=governing, bands=regions, plateau=plateau, bars=reinforcement,
                axial=axial, moment=moment)


@lru_cache(maxsize=1)
def plastic_search_example():
    lo, hi = 1e-9 * 0.6, 0.6
    trace = []
    for iteration in range(1, 101):
        mid = (lo + hi) / 2
        trial = rectangular_plastic_trial(mid)
        trace.append((iteration, lo, hi, trial))
        if trial["axial"] < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12 * 0.6:
            break
    return dict(trace=trace, accepted=rectangular_plastic_trial((lo+hi)/2))


def fig_elastic_iteration():
    """First and accepted compression polygons on equal section coordinates."""
    case = biaxial_example()
    trace = case["elastic"]["trace"]
    figure = make_subplots(rows=1, cols=2, subplot_titles=("First cracked evaluation", "Accepted equilibrium"))
    for col, state in enumerate((trace[0], trace[-1]), 1):
        for ring, fill, color in [(case["outer"], None, "#667786"),
                                  (state["region"], "toself", "#F4DBCF")]:
            if ring:
                closed = ring + ring[:1]
                figure.add_trace(go.Scatter(x=[p[0]*1000 for p in closed], y=[p[1]*1000 for p in closed],
                    mode="lines", fill=fill, fillcolor=color if fill else None,
                    line=dict(color="#AD492F" if fill else color, width=2)), row=1, col=col)
        for hole in case["holes"]:
            closed = hole + hole[:1]
            figure.add_trace(go.Scatter(x=[p[0]*1000 for p in closed], y=[p[1]*1000 for p in closed],
                mode="lines", fill="toself", fillcolor="white", line=dict(color="#667786", width=2)), row=1, col=col)
        elements = case["elements"]
        figure.add_trace(go.Scatter(x=[p[0]*1000 for p in elements], y=[p[1]*1000 for p in elements],
            mode="markers", marker=dict(size=[9]*4+[11], symbol=["circle"]*4+["diamond"], color="#AD492F")), row=1, col=col)
        q0, gx, gy = state["plane"]
        figure.add_trace(go.Scatter(x=[-210, 210], y=[-(q0+gx*x)/gy*1000 for x in [-.21, .21]],
            mode="lines", line=dict(color="#263541", dash="dash", width=2)), row=1, col=col)
        figure.update_xaxes(title_text="x (mm)", range=[-225, 225], row=1, col=col)
        figure.update_yaxes(title_text="y (mm)", range=[-325, 325], scaleanchor="x" if col == 1 else "x2", scaleratio=1, row=1, col=col)
    figure.update_layout(template="plotly_white", width=920, height=540, showlegend=False,
        font=dict(family="Arial", size=15, color="#263541"), margin=dict(l=60,r=30,t=60,b=55))
    return figure


def _number(value):
    text = f"{value:.9g}"
    if "e" in text:
        mantissa, exponent = text.split("e")
        return f"${mantissa}\\times10^{{{int(exponent)}}}$"
    return text


def material_evaluation_blocks():
    """Piecewise arithmetic corresponding to the supported material curves."""
    b = [("h1", "Evaluate the plastic material laws")]
    md = lambda text: b.append(("md", text))
    h2 = lambda text: b.append(("h2", text))
    table = lambda headers, rows: b.append(("table", headers, rows))
    md('Use tension-positive strain and stress for each material law in this chapter. Use MPa for stress and modulus. Convert entered strain from \u2030 to a fraction before calculation.')
    h2("Concrete curves")
    md('Use the compression magnitude:\n\n$a=-\\varepsilon_c$.\n\nThe concrete law has these conditions:\n\n- For $a\\le0$, concrete stress is zero.\n- For $a>\\varepsilon_{cu2}$, the material is crushed and its stress is zero.\n- Between peak and ultimate strain, the characteristic compression magnitude is $f_{ck}$.')
    md('For strain smaller than the peak strain, Curve 2 uses:\n\n$f_{ck}[1-(1-a/\\varepsilon_{c2})^n]$.\n\nCurve 1 uses the polynomial in the table. Calculate its strain variable in percent:\n\n$e=100a$.\n\nCalculate its modulus parameter:\n\n$E_0=51f_{ck}/(13+f_{ck})$.')
    table(["Curve 1 contribution", "Compression stress magnitude (MPa)"], [
        ["Linear term", "$10E_0e$"],
        ["Quadratic term", "$100(0.75f_{ck}-E_0)e^2$"],
        ["Cubic term", "$250(E_0-f_{ck})e^3$"],
    ])
    md('1. For Curve 1, add the three terms.\n2. Multiply the characteristic stress magnitude by the effective strength coefficient divided by $\\gamma_c$.\n3. Apply a negative sign to get tension-positive concrete stress.\n\nUse the effective coefficient for the selected edition:\n\n- 2005 family: $\\alpha_{cc}$.\n- 2023: $\\eta_{cc}k_{tc}$.')
    h2("Linear interpolation between material points")
    md('For a straight branch between $(e_a,f_a)$ and $(e_b,f_b)$, interpolate with:\n\n$f=f_a+(e-e_a)(f_b-f_a)/(e_b-e_a)$.\n\nUse the endpoint value at an endpoint. A coincident pair defines one corner. For that pair, continue with the next branch without division by zero.')
    h2("General reinforcing-steel law")
    md('The current steel editor uses general Curve 3. Calculate these design parameters:\n\n- Modulus: $E_d=E_s/\\gamma_E$.\n- Tensile yield strength: $f_t=f_{ytk}/\\gamma_y$.\n- Compressive yield strength: $f_c=f_{yck}/\\gamma_y$.\n- Ultimate tensile strength: $f_u=f_{utk}/\\gamma_u$.\n\nFor the characteristic curve, use the same procedure with the three partial factors equal to 1.')
    table(["Tension point", "Strain", "Stress"], [
        ["Origin", "0", "0"],
        ["First yield", "$e_1=kf_t/E_d$", "$kf_t$"],
        ["Second yield", "$e_2=\\varepsilon_{0t}+f_t/E_d$", "$f_t$"],
        ["Ultimate", "$e_u=\\varepsilon_{ut}$", "$f_u$"],
    ])
    md('For tension, interpolate through the listed points.\n\nFor compression:\n\n1. Use strain magnitude $a=-\\varepsilon_s$.\n2. Replace $f_t$ with $f_c$.\n3. Replace $\\varepsilon_{0t}$ with $\\varepsilon_{0c}$.\n4. Interpolate through the resulting points.\n5. Apply a negative sign to the stress.\n\nFor $|\\varepsilon_s|>\\varepsilon_{ut}$, stress is zero.')
    md('When compression response is off, negative steel strain gives zero plastic stress. A zero compression yield strength also gives zero compression stress. The elastic section solver uses the assigned linear modulus in tension and compression.')
    md('**Generic elastic-perfectly-plastic preset**\n\nThis preset uses Curve 3 with:\n\n- $k=1$.\n- The two offsets equal to zero.\n- Equal factored yield and ultimate strengths.\n\n**Legacy curves**\n\nLegacy Curve 1 has a linear tensile branch, then a hardening branch. Its compression plateau is constant.\n\nLegacy Curve 2 has slope $E_s/\\gamma_y$ and constant yield plateaus. The two legacy curves keep the entered rupture limit.')
    h2("User-defined tendon curves")
    md('First calculate the total tendon strain:\n\n$\\varepsilon_p=\\varepsilon_{section}+\\varepsilon_{p,IS}$.\n\nPlastic tendon stress is zero under these conditions:\n\n- $\\varepsilon_p\\le0$.\n- Strain is greater than the applicable rupture limit.')
    md('For Curve 6, calculate the design modulus:\n\n$E_d=E_p/\\gamma_E$.\n\nThe first branch joins the origin to this strain-stress point:\n\n$(f_{p0.1k}/(\\gamma_yE_d),f_{p0.1k}/\\gamma_y)$.\n\nThe second branch joins that point to:\n\n$(\\varepsilon_{pu},f_{pk}/\\gamma_u)$.')
    md('Curve 7 uses the three tensile branches in the steel table. Use these tendon inputs in place of the steel inputs:\n\n- $E_p$ for $E_s$.\n- $f_{p0.1k}$ for $f_{ytk}$.\n- $f_{pk}$ for $f_{utk}$.\n- $\\varepsilon_{pu}$ for $\\varepsilon_{ut}$.\n\nThe second yield point includes the entered tensile plastic offset.')
    h2("Fixed tendon curves 1 to 5")
    md('Set $e=100\\varepsilon_p$, the total tendon strain in percent. These expressions give characteristic stress in MPa. Divide by $\\gamma_y$ for design stress. Each fixed curve has rupture strain 0.035, equivalent to 35 \u2030.')
    table(["Curve", "Strain interval (%)", "Characteristic stress (MPa)"], [
        ["1", "$0<e<0.6$", "$2000e$"],
        ["1", "$0.6\\le e<1.0$", "$-2500e^2+5000e-900$"],
        ["1", "$1.0\\le e<1.75$", "$60e+1540$"],
        ["1", "$1.75\\le e\\le3.5$", "1645"],
        ["2", "$0<e<0.7$", "$1850e$"],
        ["2", "$0.7\\le e<1.0$", "$2743e^3-9932e^2+11724e-2986$"],
        ["2", "$1.0\\le e\\le3.5$", "$1462+86e$"],
        ["3", "$0<e<0.7$", "$1850e$"],
        ["3", "$0.7\\le e<1.0$", "$2037e^3-8137e^2+10247e-2590$"],
        ["3", "$1.0\\le e\\le3.5$", "$1473+85e$"],
        ["4", "$0<e<0.6$", "$1950e$"],
        ["4", "$0.6\\le e<1.0$", "$2286e^3-7783e^2+8825e-1816$"],
        ["4", "$1.0\\le e\\le3.5$", "$1403+105e$"],
        ["5", "$0<e<0.6$", "$1950e$"],
        ["5", "$0.6\\le e<1.0$", "$2378e^3-8014e^2+8998e-1857$"],
        ["5", "$1.0\\le e\\le3.5$", "$1399+106e$"],
    ])
    md("For example, Curve 4 at total strain 0.008 uses $e=0.8$. "
       "The polynomial gives 1433.312 MPa characteristic stress. With $\\gamma_y=1.15$, design stress is 1246.358261 MPa.")
    return b


def numerical_blocks():
    """Reader-facing numerical appendix; all values use the independent sums."""
    from manual_additional_figures import fig_plastic_bisection
    from manual_numerical_figures import fig_polygon_clipping, fig_duration_sequence

    case = biaxial_example()
    elastic = case["elastic"]
    first = elastic["trace"][0]
    plastic = plastic_search_example()
    accepted = plastic["accepted"]
    b = []
    md = lambda text: b.append(("md", text))
    h1 = lambda text: b.append(("h1", text))
    h2 = lambda text: b.append(("h2", text))
    table = lambda headers, rows: b.append(("table", headers, rows))
    b.append(("part", "Part D - Numerical procedures"))
    h1("Calculation conventions")
    md('This appendix describes the arithmetic that Sector executes for section equilibrium. Use the tables as worksheet rows. Keep full precision during calculation. Round only the reported values.')
    md('The numerical examples use meters, kN and kNm. Stress thus has units of $\\text{kN}/\\text{m}^{2}$. Divide that stress by 1000 to get MPa. Use dimensionless strain in material equations.')
    table(["Quantity", "Application entry", "Numerical value"], [
        ["Coordinate", "100 mm", "0.1 m"],
        ["Area", "$150\\,\\text{mm}^{2}$", "$0.00015\\,\\text{m}^{2}$"],
        ["Modulus", "200 GPa", "$200000000\\,\\text{kN}/\\text{m}^{2}$"],
        ["Initial tendon strain", "5 \u2030", "0.005"],
        ["Compression action", "$N=-200$ kN", "$P=200$ kN"],
    ])
    md('Entered $N$ is tension-positive. Plastic internal axial force is compression-positive. Its target is:\n\n$P=-N$.\n\nFor elastic integration, the tension-positive resultant vector is:\n\n$(N,-M_x,-M_y)$.\n\nIts second row integrates stress times $y$. Its third row integrates stress times $x$.')
    b.extend(material_evaluation_blocks())
    h1("Polygon clipping and area integrals")
    h2("Keep the compressed part of each ring")
    md('Use the trial elastic plane:\n\n$q(x,y)=q_0+g_xx+g_yy$.\n\nConcrete contributes where $q\\le0$. For each polygon edge, calculate $q_a$ and $q_b$ at its endpoints. Keep an endpoint when it belongs to the compressed side.')
    md('When an edge crosses the boundary, calculate the intersection fraction:\n\n$t=q_a/(q_a-q_b)$.\n\nCalculate the intersection coordinates:\n\n$(x_a+t(x_b-x_a),y_a+t(y_b-y_a))$.\n\nProcess each edge and the closing edge. Apply the same operation to each void.')
    md('For a plastic band, first clip at the lower projected depth. Then clip at the upper depth. Use $s=x\\cos V+y\\sin V$ to evaluate those boundaries. This operation supplies the area and moment arms inside that band.')
    b.append(("figure", fig_polygon_clipping, 'Polygon clipping example. Coordinates are in millimeters. The plane is $q=0.24+0.0002x-0.001y$ MPa. Retain $q\\le0$. Subtract the clipped void. Edge a-b intersects the boundary at c.', 'The left panel shows the retained outer polygon and the clipped void. The right panel gives $q_a=0.32$ MPa and $q_b=-0.28$ MPa. The crossing fraction is $8/15$, and point c is at (400, 320) mm.'))
    h2("Calculate six signed sums")
    md('For each edge from $(x_i,y_i)$ to $(x_j,y_j)$, define $D_i=x_i y_j-x_j y_i$. Sum the contributions in the table around the ring. The last edge returns to the first vertex.')
    table(["Integral", "Contribution from each edge", "Unit"], [
        ["$A$", "$D_i/2$", "$\\text{m}^{2}$"],
        ["$S_x=\\int x\\,dA$", "$(x_i+x_j)D_i/6$", "$\\text{m}^{3}$"],
        ["$S_y=\\int y\\,dA$", "$(y_i+y_j)D_i/6$", "$\\text{m}^{3}$"],
        ["$S_{xx}=\\int x^2\\,dA$", "$(x_i^2+x_ix_j+x_j^2)D_i/12$", "$\\text{m}^{4}$"],
        ["$S_{yy}=\\int y^2\\,dA$", "$(y_i^2+y_iy_j+y_j^2)D_i/12$", "$\\text{m}^{4}$"],
        ["$S_{xy}=\\int xy\\,dA$", "$(2x_iy_i+x_iy_j+x_jy_i+2x_jy_j)D_i/24$", "$\\text{m}^{4}$"],
    ])
    md('Counter-clockwise rings give positive area. This worksheet lists all rings counter-clockwise and subtracts the void sums. Sector accepts clockwise or counter-clockwise input, then orients the outer ring and voids internally so their signed sums give the same net integrals. A clipped ring with fewer than three vertices contributes zero.')
    h1("Elastic equilibrium procedure")
    h2("Assemble the equilibrium matrix")
    md('Use the unknown vector:\n\n$u=(q_0,g_x,g_y)$.\n\nThe reference value $q_0$ has stress units. The gradients have stress units per meter. The table gives the three concrete matrix rows. Their product with $u$ gives the axial and two moment integrals.')
    table(["Row", "$q_0$ coefficient", "$g_x$ coefficient", "$g_y$ coefficient"], [
        ["Axial force", "$A$", "$S_x$", "$S_y$"],
        ["Moment using $y$", "$S_y$", "$S_{xy}$", "$S_{yy}$"],
        ["Moment using $x$", "$S_x$", "$S_{xx}$", "$S_{xy}$"],
    ])
    md('For reinforcement element $i$, calculate its modulus ratio $n_i=E_i/E_c$ and trial reference stress $q_i$.\n\nUse the applicable transformed area:\n\n- Where concrete is compressed: $w_i=(n_i-1)A_i$.\n- In the cracked tension region: $w_i=n_iA_i$.\n\nThe subtraction accounts for displaced concrete. Actual reinforcement stress uses the full ratio $n_i$.')
    md('For each bar and tendon, use its assigned modulus and add these row contributions:\n\n- Axial row: $w_i(1,x_i,y_i)$.\n- Second row: $w_i y_i(1,x_i,y_i)$.\n- Third row: $w_i x_i(1,x_i,y_i)$.')
    h2("Solve and update the plane")
    md('1. Assemble the initial matrix with the full concrete section and weight $(n_i-1)A_i$ for each element.\n2. Subtract locked-prestress resultants from $(N,-M_x,-M_y)$ to get the target vector $T$.\n3. Solve the initial three equations $J_0u=T$.\n4. Clip concrete and voids to the current compressed region.\n5. Reassemble $J$. Calculate $R=Ju$. Form the residual $r=R-T$.\n6. If the stopping condition is satisfied, keep this plane.\n7. If the stopping condition is not satisfied, solve $J\\Delta u=-r$. Replace $u$ with $u+\\Delta u$.\n8. Do steps 4 to 7 again.')
    md('Sector accepts the state when the largest absolute residual component is no greater than:\n\n$10^{-9}\\max(1,|T_1|,|T_2|,|T_3|)$.\n\nApply this numerical test in kN and kNm. Convert worksheet residuals to those units before comparison. The default maximum is 100 evaluations.')
    md('A singular initial matrix gives a zero initial plane in Sector. A singular correction matrix ends the iteration. Sector reports the convergence status and residuals. At the iteration limit, Sector evaluates the last updated plane for diagnostics. Sector accepts the result only if the convergence flag is true.')
    h1("Biaxial section with a void and tendon")
    md('This example includes an asymmetric outline, a void, four bars and one tendon.\n\n**Elastic moduli**\n\n- $E_c=33.333333333$ GPa.\n- $E_s=200$ GPa.\n- $E_p=195$ GPa.\n\n**External actions**\n\n- $N=-200$ kN.\n- $M_x=100$ kNm.\n- $M_y=40$ kNm.\n\nFirst use zero creep.')
    table(["Ring", "Ordered coordinates (mm)"], [
        ["Concrete outline", "(-200,-300), (200,-300), (200,150), (50,300), (-200,300)"],
        ["Void", "(-70,-20), (30,-20), (30,80), (-70,80)"],
    ])
    table(["Element", "$x$ (mm)", "$y$ (mm)", "Area or diameter", "Modulus / initial strain"], [
        *[[f"Bar {i}", _number(x*1000), _number(y*1000), "Diameter 25 mm", "200 GPa / 0"]
          for i, (x,y,_a,_n,_l) in enumerate(case["elements"][:4], 1)],
        ["Tendon 1", "50", "-180", "$150\\,\\text{mm}^{2}$", "195 GPa / 5 \u2030"],
    ])
    md('Use one assigned mild-steel material for all four bars and one prestress material for the tendon. The elastic calculation uses their moduli.\n\nThe tendon initial stress is:\n\n$E_p\\varepsilon_{p,IS}=975$ MPa.\n\nIts locked resultants are:\n\n- Axial force: 146.25 kN.\n- Moment using $y$: -26.325 kNm.\n- Moment using $x$: 7.3125 kNm.')
    md('After you subtract those locked resultants, the elastic target is:\n\n$(T_1,T_2,T_3)=(-346.25,-73.675,-47.3125)$.\n\nThe first component is in kN. The two moment components are in kNm.')
    h2("Initialization and first correction")
    table(["Initial matrix row", "$q_0$ coefficient", "$g_x$ coefficient", "$g_y$ coefficient"], [
        [str(i+1), *[_number(v) for v in row]]
        for i,row in enumerate(elastic["initial"])
    ])
    table(["First clipped matrix row", "$q_0$ coefficient", "$g_x$ coefficient", "$g_y$ coefficient"], [
        [str(i+1), *[_number(v) for v in row]]
        for i,row in enumerate(first["matrix"])
    ])
    md('Use the row and column units from the equilibrium matrix above. Matrix coefficients combine areas, first moments and second moments, so their units are different.')
    table(["First evaluation", "Component 1", "Component 2", "Component 3"], [
        ["Plane: stress, stress/m, stress/m", *[_number(v) for v in first["plane"]]],
        ["Internal resultants: kN, kNm, kNm", *[_number(v) for v in first["internal"]]],
        ["Residual: kN, kNm, kNm", *[_number(v) for v in first["residual"]]],
        ["Plane correction", *[_number(v) for v in first["correction"]]],
        ["Updated plane", *[_number(v) for v in first["plane"]+first["correction"]]],
    ])
    table(["Clipped ring at first evaluation", "Ordered coordinates (m)"], [
        ["Outer", "; ".join(f"({_number(x)}, {_number(y)})" for x,y in first["region"])],
        ["Void", "; ".join(f"({_number(x)}, {_number(y)})" for x,y in first["voids"][0])],
    ])
    table(["Net concrete integral", "First evaluation value"], [
        [name, _number(value)] for name,value in zip(
            ["$A$ ($\\text{m}^{2}$)", "$S_x$ ($\\text{m}^{3}$)", "$S_y$ ($\\text{m}^{3}$)",
             "$S_{xx}$ ($\\text{m}^{4}$)", "$S_{yy}$ ($\\text{m}^{4}$)", "$S_{xy}$ ($\\text{m}^{4}$)"], first["moments"])
    ])
    h2("Iteration trace and accepted stresses")
    table(["Evaluation", "$q_0$", "$g_x$", "$g_y$"], [
        [str(row["iteration"]), *[_number(v) for v in row["plane"]]]
        for row in elastic["trace"]
    ])
    table(["Evaluation", "$r_N$ (kN)", "$r_y$ (kNm)", "$r_x$ (kNm)"], [
        [str(row["iteration"]), *[_number(v) for v in row["residual"]]]
        for row in elastic["trace"]
    ])
    md(f"The acceptance threshold is {_number(elastic['tolerance'])} in the component's kN or kNm units. "
       "Each correction changes the plane and thus the compressed polygon. The figure shows the first and accepted regions.")
    b.append(("figure", fig_elastic_iteration,
              'Elastic iteration for the biaxial example. Shading shows compressed concrete. The dashed line is the neutral axis. Circles identify bars. The diamond identifies the tendon.',
              "Equal-scale section views show the first and accepted compression zones around the void. Circles identify bars and a diamond identifies the tendon."))
    table(["Element", "Passive stress (MPa)", "Locked stress (MPa)", "Reported stress (MPa)"], [
        [f"Bar {i+1}" if i<4 else "Tendon 1", _number(passive/1000), _number(lock/1000), _number((passive+lock)/1000)]
        for i,(passive,lock) in enumerate(zip(elastic["passive"], case["locked"]))
    ])
    md('Concrete stress equals $q$ in the compressed region. Reinforcement passive stress equals $n_iq_i$. Add the locked stress to get the reported tendon stress. For zero creep, physical section strain is $q/E_c$. The tendon total strain also includes its initial strain.')
    h1("Plastic depth search and force integration")
    md("Use the rectangular tutorial section and material values. Select the 90-degree orientation and axial action $N=0$. "
       "The local depth coordinate is then $s=y$, and the extreme concrete coordinate is $s_{max}=0.3$ m.")
    h2("Evaluate a trial depth")
    md('1. Choose compression depth $c$ and calculate $s_{na}=s_{max}-c$.\n2. Calculate the concrete curvature candidate $\\varepsilon_{cu}/c$.\n3. Calculate each eligible reinforcement curvature candidate from its distance to the neutral axis.\n4. Select the smallest candidate and calculate the compatible strain field.\n5. Integrate concrete bands and plateau, then add each reinforcement force and moment.\n6. Compare the compression-positive axial sum with $P=-N$.')
    md('**Bar curvature candidate**\n\nFor an eligible bar, use:\n\n$(1-10^{-9})\\varepsilon_u/|s_i-s_{na}|$.\n\nCompression-side bars participate when their plastic compression response is active and their compression yield strength is positive.\n\n**Tendon curvature candidate**\n\nFor a tension-side tendon, the remaining strain margin must be positive:\n\n$\\varepsilon_{pu}-\\varepsilon_{p,IS}>0$.\n\nIts candidate is:\n\n$(1-10^{-9})(\\varepsilon_{pu}-\\varepsilon_{p,IS})/(s_{na}-s_i)$.\n\nThe small reduction keeps the evaluated material strain no greater in magnitude than its rupture limit.')
    md('A candidate is valid only with a positive distance and, for a tendon, a positive remaining strain margin. Sector keeps the first candidate when values are equal. It evaluates each element with its own material law and limits.')
    h2("Bracket and bisect the axial target")
    md('The lower depth is $10^{-9}$ times the projected section depth. The initial upper depth is the full projected depth. If its axial force is smaller than the target, double the upper depth and evaluate again. At most 80 doublings are permitted.')
    md('Compare the target with the two endpoint forces. A target outside that interval is unreachable and keeps the related endpoint as a diagnostic result. For a reachable target, evaluate the midpoint depth. If the force is smaller than the target, replace the lower bound. If the force is equal to or larger than the target, replace the upper bound.')
    md('Continue for at most 100 bisections. Stop when the interval width is smaller than $10^{-12}$ times the projected section depth. Evaluate the last interval midpoint again.\n\nAcceptance requires a reachable target and this axial residual limit:\n\n$|\\sum F-P|\\le10^{-6}\\max(1,|P|)$.\n\nUse forces in kN.')
    selected = plastic["trace"][:6] + plastic["trace"][-3:]
    table(["Step", "Lower $c$ (mm)", "Upper $c$ (mm)", "Trial $c$ (mm)"], [
        [str(i), f"{lo*1000:.8f}", f"{hi*1000:.8f}", f"{trial['depth']*1000:.8f}"]
        for i,lo,hi,trial in selected
    ])
    table(["Step", "Limit", "$\\kappa$ (1/m)", "Axial residual (kN)"], [
        [str(i), trial["governing"],
         _number(trial["curvature"]), _number(trial["axial"])] for i,lo,hi,trial in selected
    ])
    md("The table shows the first six and last three trials. Intermediate steps use the same midpoint rule. "
       f"The accepted depth is ${accepted['depth']*1000:.9f}$ mm and curvature is ${accepted['curvature']:.12f}$ 1/m.")
    b.append(("figure", fig_plastic_bisection, 'Plastic depth search for the rectangular example at zero axial force. Diamonds mark the first six evaluated midpoints. Each interval contains the accepted depth $c=83.799$ mm. The axial sum uses the compression-positive calculation convention.', 'Two aligned plots show axial residual against compression depth and the depth interval before each of the first six bisection trials. The accepted root is 83.799 mm. The trial depths are 300, 150, 75, 112.5, 93.75 and 84.375 mm.'))
    md('If the residual is negative, replace the lower bound with the trial depth. Otherwise, replace the upper bound with the trial depth. The next diamond is the midpoint of the retained interval.')
    h2("Calculate individual concrete contributions")
    md('The plateau starts at:\n\n$s_{peak}=s_{na}+\\varepsilon_{c2}/\\kappa$.\n\nDivide the rising region into 80 equal bands. Its endpoints are $s_{na}$ and $\\min(s_{peak},s_{max})$.\n\nFor each band, evaluate strain and stress at its depth midpoint. Clip the geometry to get its signed area and first moments.')
    md("Calculate each band's force and moments:\n\n- $F_i=\\sigma_i A_i$.\n- $M_{x,i}=\\sigma_i S_{y,i}$.\n- $M_{y,i}=\\sigma_i S_{x,i}$.\n\nThe table uses MPa and meter-based integrals. Thus, multiply each product by 1000 to get kN or kNm.\n\nFor the plateau, use constant $f_{cd}$ and integrate its full polygon.")
    for index in (0, 39, 79):
        row = accepted["bands"][index]
        table([f"Band {index+1} operand", "Value"], [
            ["Lower / upper depth (m)", f"{_number(row[0])} / {_number(row[1])}"],
            ["Midpoint (m)", _number(row[2])], ["Compression strain", _number(row[3])],
            ["Stress (MPa)", _number(row[4])], ["Area ($\\text{m}^{2}$)", _number(row[5])],
            ["$S_y$ ($\\text{m}^{3}$)", _number(row[6])], ["Force (kN)", _number(row[7])],
            ["$M_x$ (kNm)", _number(row[8])],
        ])
    plateau = accepted["plateau"]
    table(["Plateau operand", "Value"], [
        ["Lower / upper depth (m)", f"{_number(plateau[0])} / {_number(plateau[1])}"],
        ["Stress (MPa)", _number(plateau[2])], ["Area ($\\text{m}^{2}$)", _number(plateau[3])],
        ["$S_y$ ($\\text{m}^{3}$)", _number(plateau[4])], ["Force (kN)", _number(plateau[5])],
        ["$M_x$ (kNm)", _number(plateau[6])],
    ])
    h2('Recover reinforcement and examine equilibrium')
    table(["Bar", 'Strain (compression +)', "Stress (MPa)", "Force (kN)", "$M_x$ (kNm)"], [
        [str(i), *[_number(v) for v in row[2:]]] for i,row in enumerate(accepted["bars"], 1)
    ])
    md(f"The summed axial force is {_number(accepted['axial'])} kN. The moment is ${accepted['moment']:.9f}$ kNm. "
       "The calculation integrates the net concrete polygon and adds reinforcement forces. "
       "The plastic procedure uses gross concrete in that polygon. The elastic transformed-section procedure deducts displaced concrete.")
    md('A depth larger than the full projected section depth places the neutral axis outside the section. The same clipping and force equations then evaluate whole-section compression. Equilibrium tolerance defines the permitted force imbalance. Band refinement measures integration accuracy, and angle refinement measures envelope resolution.')
    h1("Sustained actions and locked prestress")
    md('Return to the biaxial section. Use creep coefficient 2.\n\n**Sustained actions**\n\n- $N=-200$ kN.\n- $M_x=70$ kNm.\n- $M_y=30$ kNm.\n\n**Additional actions**\n\n- $N=0$ kN.\n- $M_x=30$ kNm.\n- $M_y=10$ kNm.')
    md('**Modulus ratios**\n\nThe instantaneous ratios are:\n\n- Bars: 6.\n- Tendon: 5.85.\n\nThe sustained ratios are three times those values because:\n\n$E_{c,eff}=E_c/(1+\\varphi)$.\n\n**Sustained solve**\n\n1. Subtract locked prestress from the sustained target.\n2. Solve the adjusted target.\n3. Keep the passive reinforcement stresses from that solve.')
    md('**Retained component**\n\nFor this example, the retained fraction is:\n\n$1-n_s/n_l=2/3$.\n\n1. Multiply each passive sustained stress by this fraction to get its retained component.\n2. Sum the retained element forces and raw moments.\n3. Subtract that resultant vector and locked prestress from the total external target.\n4. Solve the adjusted target with the instantaneous ratios to get RST1.')
    b.append(("figure", fig_duration_sequence, 'Duration calculation sequence for a reinforced or prestressed section. C includes the sustained actions and additional actions. Element stress is tension-positive. Each solve uses the net transformed section.', 'Four steps show sustained equilibrium and the adjusted instantaneous solve. A branch from sustained equilibrium gives LONG. The instantaneous solve supplies TOTAL. LONG and TOTAL connect to DIF.'))
    table(["Element", "Passive LONG (MPa)", "Retained (MPa)"], [
        [f"Bar {i+1}" if i<4 else "Tendon 1", _number(case["long"]["passive"][i]/1000),
         _number(case["retained"][i]/1000)]
        for i,row in enumerate(case["elements"])
    ])
    table(["Element", "Retained force (kN)", "Moment using $y$ (kNm)", "Moment using $x$ (kNm)"], [
        [f"Bar {i+1}" if i<4 else "Tendon 1",
         *[_number(v) for v in element_resultants([case["retained"][i]], [row])]]
        for i,row in enumerate(case["elements"])
    ])
    table(["Target or resultant", "Axial (kN)", "Moment using y (kNm)", "Moment using x (kNm)"], [
        ["Locked prestress", *[_number(v) for v in case["prestress"]]],
        ["Sustained target after locked prestress", *[_number(v) for v in case["long"]["target"]]],
        ["Retained reinforcement", *[_number(v) for v in case["neutralising"]]],
        ['Instantaneous target after the two subtractions', *[_number(v) for v in case["instant"]["target"]]],
    ])
    md('The reported reinforcement stresses are:\n\n- **LONG:** passive LONG plus locked stress.\n- **TOTAL:** retained stress plus RST1 plus locked stress.\n- **DIF:** TOTAL minus LONG. The same locked stress cancels.\n\nThe concrete total state comes from the adjusted instantaneous solve.')
    table(["Element", "LONG (MPa)", "RST1 (MPa)", "Locked (MPa)", "TOTAL (MPa)", "DIF (MPa)"], [
        [f"Bar {i+1}" if i<4 else "Tendon 1", *[_number(v/1000) for v in (
            case["long_total"][i], case["instant"]["passive"][i], case["locked"][i], case["total"][i], case["difference"][i])]]
        for i in range(len(case["elements"]))
    ])
    table(["Solve", "$q_0$", "$g_x$", "$g_y$", "Neutral-axis equation"], [
        [label, *[_number(v) for v in result["plane"]], "$q_0+g_xx+g_yy=0$"]
        for label,result in [("Sustained", case["long"]), ("Adjusted instantaneous", case["instant"])]
    ])
    md('Use the stated planes to recover concrete stress at each compressed vertex. The sustained plane uses the effective concrete modulus. The adjusted instantaneous plane uses the instantaneous modulus. The retained reinforcement component must accompany that second plane when you reconstruct total equilibrium.')
    h1("Construct capacity diagrams")
    h2("Sample the fixed-axial-force envelope")
    md('The angular span is:\n\n$L=V_{max}-V_{min}$.\n\nFor maximum increment $\\Delta V$, start with this number of intervals:\n\n$m=\\lceil L/\\Delta V\\rceil$.\n\nUse these angles and keep the two exact endpoints:\n\n$V_i=V_{min}+iL/m$.\n\nSector can add an interval if numerical rounding makes a represented gap larger than the maximum increment.')
    md('A zero span requests one orientation. A full 360-degree sweep closes the envelope. At each orientation, run the plastic depth search at the same axial target. Connect accepted moment pairs in sweep order to get the capacity polygon.')
    h2("Intersect the demand ray with each segment")
    md('Use the applied moment vector:\n\n$d=(M_{x,Ed},M_{y,Ed})$.\n\nFor capacity segment endpoints $p$ and $p+v$, solve:\n\n$\\lambda d=p+tv$.\n\nUse this two-dimensional determinant:\n\n$[a,b]=a_xb_y-a_yb_x$.')
    table(["Quantity", "Calculation", "Acceptance"], [
        ["Ray factor", "$\\lambda=[p,v]/[d,v]$", "$\\lambda>0$"],
        ["Segment position", "$t=[p,d]/[d,v]$", "$0\\le t\\le1$"],
        ["Utilization", "$u=1/\\lambda$", "Use the first verified inside-to-outside crossing"],
    ])
    md('Skip a parallel segment where $[d,v]=0$. Group duplicate intersections at a shared vertex. The origin must be inside or on the accepted simple polygon. For a nonconvex polygon, check the intervals between intersections to identify the first exit.')
    md('A zero demand has utilization zero when the origin condition is satisfied. For an envelope collapsed to a line through the origin, Sector uses the farthest positive capacity point in the demand direction. For a malformed, self-intersecting or inadmissible envelope, Sector reports an invalid result and its cause.')
    md("The selected per-angle state is the segment endpoint nearest the intersection. "
       "Its strains belong to that solved endpoint. The radial resistance lies on the straight segment between the two solved points.")
    h2("Vary axial force for an N-M diagram")
    md('For each fixed orientation, Sector first estimates axial tension and compression bounds from concrete area and assigned reinforcement laws. It probes beyond those estimates and keeps the attainable endpoint forces from the depth solver.')
    md("Let $A_c$ be the net concrete area in square meters. "
       "For each bar, evaluate the design stresses at $+0.99\\varepsilon_u$ and $-0.99\\varepsilon_u$. "
       "Multiply the larger absolute stress by that bar's area. "
       "For each tendon, multiply its design stress at $0.99\\varepsilon_{pu}$ by its area.")
    md('Use MPa and square meters in these products. Multiply their sum by 1000 to get reinforcement-force bound $R$ in kN. The compression estimate is $C=1000f_{cd}A_c+R$. The tension estimate is $R$.')
    table(["Endpoint probe", "Compression-positive target (kN)", "Endpoint kept"], [
        ["Compression", "$1.5C+1$", "Axial force returned by the depth solver"],
        ["Tension", "$-1.5R-1$", "Axial force returned by the depth solver"],
    ])
    md("These probes deliberately request forces beyond the estimated range. "
       "The depth solver keeps the attainable boundary state when a target is unreachable. "
       "Use its returned axial force as the endpoint for the subsequent sweep.")
    md('Use $P_t$ and $P_c$ for the compression-positive endpoints. Calculate:\n\n$P_i=P_t+(P_c-P_t)i/32$.\n\nUse $i=0$ to 32 and keep the exact endpoint values. Each sample runs the full plastic depth search.\n\nConvert the reported axial coordinate:\n\n$N_i=-P_i$.')
    md('The application combines the 90-degree and 270-degree branches for $N$-$M_x$. It combines the 0-degree and 180-degree branches for $N$-$M_y$. An asymmetric section can also give an orthogonal moment on these fixed-orientation branches.')
    return b
