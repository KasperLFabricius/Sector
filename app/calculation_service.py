"""Sector calculation service: the calculation orchestration without Streamlit.

``run_analysis`` runs every named action case and enabled calculation of one
calculation input document (the ``inp`` mapping that the input pages build).
The functions moved here from ``app/sector_app.py`` in 0.97.1 (AR-07),
unchanged except the cache decorator of ``_warm_solver`` (``functools.cache``
in place of ``st.cache_resource``) and one comment about the member-angle
scan; ``sector_app`` imports them again for one release.

``calculate_project`` is the headless entry. With the repository root on
``sys.path``::

    from app import calculation_service
    result_set = calculation_service.calculate_project(project_text)

The import puts the ``app`` folder first on ``sys.path`` when it is not there,
the same as ``sector_app`` does. Until the app modules become a package in
0.97.3 (AR-03, AR-09), the names of the app modules (for example ``viz``,
``manual``, ``project_io``) are thus reserved in the process: a caller module
with one of these names is not found after the import. The module is one object
under both names, ``app.calculation_service`` and ``calculation_service``.

The command line calculates one project file and prints a short summary::

    python app/calculation_service.py project.json
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
import functools
import math
import os
import pathlib
import sys
import tempfile
import time

# The flat app modules import each other by their bare names (for example
# ``deferred_import``), so the ``app`` folder must be on ``sys.path``.
# ``sector_app`` adds it for the application; this guard adds it for a caller
# that has only the repository root on ``sys.path`` (until AR-03).
_APP_FOLDER = str(pathlib.Path(__file__).resolve().parent)
if _APP_FOLDER not in sys.path:
    sys.path.insert(0, _APP_FOLDER)
if __name__ == "__main__":  # command line: make ``app`` and ``sector`` importable
    _ROOT_FOLDER = str(pathlib.Path(__file__).resolve().parent.parent)
    if _ROOT_FOLDER not in sys.path:
        sys.path.insert(0, _ROOT_FOLDER)

import numpy as np  # noqa: E402

from app import engineer_messages  # noqa: E402
from deferred_import import deferred_module  # noqa: E402
from sector import codes, design_standards, shear_inputs  # noqa: E402
from sector.engineer_message import EngineerMessage  # noqa: E402
from sector.materials import ES as STEEL_REFERENCE_MODULUS  # noqa: E402
from sector.sls_identity import (  # noqa: E402
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
    LONG_TERM_PERMITTED_CRACK_WIDTH_KEY,
    SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY,
)

# The flat layout lets the module load as ``app.calculation_service`` and as
# ``calculation_service``. Register this module object under both names, so
# that the second import gives the same globals and the same caches.
if __name__ in {"app.calculation_service", "calculation_service"}:
    _THIS_MODULE = sys.modules[__name__]
    for _module_name in ("app.calculation_service", "calculation_service"):
        sys.modules.setdefault(_module_name, _THIS_MODULE)
    if getattr(sys.modules.get("app"), "calculation_service", None) is None:
        setattr(sys.modules["app"], "calculation_service", _THIS_MODULE)

# The same deferred module names as in sector_app: a module that the first
# render does not need stays unloaded until a calculation reaches it.
case_analysis = deferred_module("case_analysis")
fatigue_analysis = deferred_module("fatigue_analysis")
project_io = deferred_module("project_io")
rebar_table = deferred_module("reinforcement_table")
presentation = deferred_module("result_presentation")
heightened_adapter = deferred_module("heightened_crack_adapter")
section_fields = deferred_module("section_fields")

capacity = deferred_module("sector.capacity")
combined = deferred_module("sector.combined")
detailing = deferred_module("sector.detailing")
elastic_core = deferred_module("sector.elastic")
geometry = deferred_module("sector.geometry")
kernels = deferred_module("sector.kernels")
plastic_core = deferred_module("sector.plastic")
section_core = deferred_module("sector.section")
serviceability_core = deferred_module("sector.serviceability")
heightened_crack_control_core = deferred_module(
    "sector.heightened_crack_control"
)
shear = deferred_module("sector.shear")
sls_core = deferred_module("sector.sls")
torsion = deferred_module("sector.torsion")

_MM = 1000.0   # millimetres per metre (the same factor as in sector_app)


def solve_elastic_combined(*args, **kwargs):
    return elastic_core.solve_elastic_combined(*args, **kwargs)


def transformed_properties(*args, **kwargs):
    return elastic_core.transformed_properties(*args, **kwargs)


def solve_interaction(*args, **kwargs):
    return plastic_core.solve_interaction(*args, **kwargs)


def solve_plastic(*args, **kwargs):
    return plastic_core.solve_plastic(*args, **kwargs)


def analyse_cracking(*args, **kwargs):
    return serviceability_core.analyse_cracking(*args, **kwargs)


def combined_cracking(*args, **kwargs):
    return serviceability_core.combined_cracking(*args, **kwargs)


def crack_width(*args, **kwargs):
    return serviceability_core.crack_width(*args, **kwargs)


def evaluate_crack_width(*args, **kwargs):
    return serviceability_core.evaluate_crack_width(*args, **kwargs)


# One warm-up for each process, as st.cache_resource gave in sector_app.
@functools.cache
def _warm_solver():
    """Compile the plastic kernels once, immediately before their first use.

    Starting this work at module import competed with Streamlit's first render and
    could leave a background compiler active while the engineer navigated.  The
    cached synchronous call keeps startup responsive and makes Calculate own the
    one-time warm-up it actually needs.
    """
    kernels.warmup()
    return True


_SLAB_DENSITY_GUIDANCE = (
    "The slab-spacing layout no longer matches the current point tables. "
    "Reapply the slab layout, or define explicit bars, before relying on "
    "crack-width or clear-spacing results."
)
_SLAB_TENDON_FACE_GUIDANCE = (
    "Move every tendon far enough inside the physical top and bottom slab "
    "faces to provide non-negative clear cover before relying on crack-width "
    "results."
)


def _slab_face_clear_cover_mm(y_m, diameter_mm, bottom_face_m, top_face_m):
    """Clear cover to the nearest real horizontal slab face."""

    values = (y_m, diameter_mm, bottom_face_m, top_face_m)
    if any(isinstance(value, (bool, np.bool_)) for value in values):
        raise ValueError("slab face cover inputs must be numeric")
    y_m = float(y_m)
    diameter_mm = float(diameter_mm)
    bottom_face_m = float(bottom_face_m)
    top_face_m = float(top_face_m)
    if (
        any(not math.isfinite(value) for value in (
            y_m, diameter_mm, bottom_face_m, top_face_m
        ))
        or diameter_mm <= 0.0
        or bottom_face_m >= top_face_m
    ):
        raise ValueError("slab face cover inputs must be finite")
    clear_cover_mm = (
        min(y_m - bottom_face_m, top_face_m - y_m) * _MM
        - diameter_mm / 2.0
    )
    if clear_cover_mm < -1.0e-9:
        raise ValueError("reinforcement envelope is outside a physical slab face")
    return max(clear_cover_mm, 0.0)


def _slab_tendon_face_clear_cover_mm(y_m, diameter_mm, outer):
    """Clear tendon cover to a real slab face, ignoring unit-strip side cuts."""

    face_coordinates = [float(point[1]) for point in outer]
    if not face_coordinates:
        raise ValueError("slab face cover inputs must be finite")
    return _slab_face_clear_cover_mm(
        y_m,
        diameter_mm,
        min(face_coordinates),
        max(face_coordinates),
    )


def _sweep(v_min, v_max, v_inc):
    """Use the core inclusive-endpoint/max-increment sweep contract."""

    return plastic_core.plastic_sweep_angles(v_min, v_max, v_inc)


def _props_dict(p):
    """Flatten SectionProperties to a plain dict for the results payload."""
    return dict(area=p.area, cx=p.cx, cy=p.cy, Ix=p.Ix, Iy=p.Iy, Ixy=p.Ixy)


def _plastic_point_result(point, inp):
    """Flatten one accepted plastic state without evaluating a material law."""

    corner_rows = []
    for point_no, state in enumerate(point.concrete_corner_states or (), start=1):
        corner_rows.append(dict(
            point_no=point_no,
            ring=("Outer" if state.ring_index == 0
                  else f"Hole {state.ring_index}"),
            ring_point_no=state.point_index + 1,
            x_mm=state.x * _MM,
            y_mm=state.y * _MM,
            section_strain_permille=state.section_strain * _MM,
            strain_permille=state.material_strain * _MM,
            stress_mpa=state.material_stress,
        ))

    mild_names = {
        item.get("id"): item.get("name")
        for item in (inp.get("mild_material_catalog") or {}).get("items", [])
    }
    prestress_names = {
        item.get("id"): item.get("name")
        for item in (inp.get("prestress_material_catalog") or {}).get("items", [])
    }

    reinforcement_rows = []

    def append_states(states, family, elements, names):
        for state in states or ():
            metadata = (
                elements[state.element_index]
                if state.element_index < len(elements) else {}
            )
            element_no = state.element_index + 1
            element_id = str(metadata.get("id") or f"{family.lower()} {element_no}")
            material_id = metadata.get("material_id")
            strain = state.material_strain
            reinforcement_rows.append(dict(
                element_type=family,
                element_no=element_no,
                element_id=element_id,
                material_id=material_id,
                material_name=names.get(material_id),
                state=("Tension" if strain > 1.0e-12 else
                       "Compression" if strain < -1.0e-12 else "Neutral"),
                x_mm=state.x * _MM,
                y_mm=state.y * _MM,
                area_mm2=state.area * 1.0e6,
                section_strain_permille=state.section_strain * _MM,
                initial_strain_permille=state.initial_strain * _MM,
                strain_permille=strain * _MM,
                stress_mpa=state.material_stress,
                force_kn=-state.force,
                internal_force_kn=state.force,
                internal_mx_knm=state.mx,
                internal_my_knm=state.my,
            ))

    bar_elements = list(inp.get("bar_elements") or [])
    tendon_elements = list(inp.get("tendon_elements") or [])
    append_states(point.bar_states, "Bar", bar_elements, mild_names)
    append_states(point.tendon_states, "Tendon", tendon_elements, prestress_names)

    candidate_rows = []
    selection = point.curvature_selection
    if selection is not None:
        for candidate in selection.candidates:
            if candidate.mode.startswith("bar_") and candidate.element_index is not None:
                metadata = (bar_elements[candidate.element_index]
                            if candidate.element_index < len(bar_elements) else {})
                element_id = str(
                    metadata.get("id") or f"bar {candidate.element_index + 1}"
                )
            elif (candidate.mode.startswith("tendon_")
                  and candidate.element_index is not None):
                metadata = (tendon_elements[candidate.element_index]
                            if candidate.element_index < len(tendon_elements) else {})
                element_id = str(
                    metadata.get("id") or f"tendon {candidate.element_index + 1}"
                )
            else:
                element_id = None
            candidate_rows.append(dict(
                mode=candidate.mode,
                element_index=candidate.element_index,
                element_id=element_id,
                strain_limit=candidate.strain_limit,
                distance_from_na_m=candidate.distance_from_na,
                curvature_per_m=candidate.curvature,
                selected=(
                    candidate.mode == selection.selected_mode
                    and candidate.element_index == selection.selected_element_index
                ),
            ))

    return dict(
        V=point.V,
        field_context=section_fields.context_signature(inp, "Plastic"),
        Mx=point.Mx,
        My=point.My,
        na_x=point.na_x_intercept,
        na_y=point.na_y_intercept,
        eps_c=-point.eps_concrete,
        eps_s=-point.eps_steel,
        eps_s_comp=-point.eps_steel_comp,
        eps_cable=-point.eps_cable,
        kappa=point.curvature,
        comp_force=point.compression_force,
        lever=point.lever_arm,
        dx=point.dx,
        dy=point.dy,
        converged=point.converged,
        axial_requested=point.axial_requested,
        axial_achieved=point.axial,
        axial_residual=point.axial_residual,
        axial_tolerance=point.axial_tolerance,
        axial_reachable=point.axial_reachable,
        compression_depth=point.compression_depth,
        neutral_axis_offset=point.neutral_axis_offset,
        strain_gradient_x=point.strain_gradient_x,
        strain_gradient_y=point.strain_gradient_y,
        strain_offset=point.strain_offset,
        search_lower_depth=point.search_lower_depth,
        search_upper_depth=point.search_upper_depth,
        search_lower_axial=point.search_lower_axial,
        search_upper_axial=point.search_upper_axial,
        search_iterations=point.search_iterations,
        concrete_force=point.concrete_force,
        concrete_mx=point.concrete_mx,
        concrete_my=point.concrete_my,
        bar_force=point.bar_force,
        bar_mx=point.bar_mx,
        bar_my=point.bar_my,
        tendon_force=point.tendon_force,
        tendon_mx=point.tendon_mx,
        tendon_my=point.tendon_my,
        compression_mx=point.compression_mx,
        compression_my=point.compression_my,
        tension_force=point.tension_force,
        tension_mx=point.tension_mx,
        tension_my=point.tension_my,
        concrete_corner_states=corner_rows,
        reinforcement_states=reinforcement_rows,
        curvature_candidates=candidate_rows,
        curvature_selection=(
            dict(
                mode=selection.selected_mode,
                element_index=selection.selected_element_index,
                curvature_per_m=selection.selected_curvature,
            ) if selection is not None else None
        ),
    )


def _elastic_resultant_result(value):
    """Flatten one named elastic resultant with heterogeneous physical units."""

    return dict(
        n=value.axial_force,
        mx=value.moment_x,
        my=value.moment_y,
    )


def _elastic_state_result(value):
    """Flatten one accepted Ec=1 elastic state for publication."""

    sigma0, gradient_x, gradient_y = value.raw_stress_plane
    equilibrium = value.equilibrium
    return dict(
        raw_stress_plane=dict(
            sigma0_kpa=sigma0,
            gradient_x_kpa_per_m=gradient_x,
            gradient_y_kpa_per_m=gradient_y,
        ),
        iterations=value.iterations,
        converged=value.converged,
        equilibrium=dict(
            matrix=[list(row) for row in equilibrium.equilibrium_matrix],
            target=_elastic_resultant_result(equilibrium.target),
            internal=_elastic_resultant_result(equilibrium.internal),
            residual=_elastic_resultant_result(equilibrium.residual),
            residual_scale=equilibrium.residual_scale,
            normalised_residual=equilibrium.normalised_residual,
            relative_tolerance=equilibrium.relative_tolerance,
        ),
    )


def _area_moments_dict(value):
    """Flatten one authoritative polygon-moment result for publication."""

    return dict(
        area_m2=value.area,
        first_x_m3=value.sx,
        first_y_m3=value.sy,
        second_xx_m4=value.sxx,
        second_yy_m4=value.syy,
        product_xy_m4=value.sxy,
    )


def _section_and_material_results(inp):
    """Prepare shared existing calculations once for human-readable output.

    These are compact final-state breakdowns, not a trace or a second solver.
    Every numerical value comes from an existing family kernel/property and is
    shared by all named action cases in the current run.
    """

    # Use the section's established integration orientation: outer positive,
    # voids negative, independent of the user's vertex-entry direction.
    rings = inp["section"].integration_rings()
    moments = geometry.area_moment_breakdown(rings)
    section_properties = dict(
        rings=[
            dict(
                ring_id=("outer" if index == 0 else f"void {index}"),
                role=("gross outline" if index == 0 else "void deduction"),
                **_area_moments_dict(value),
            )
            for index, value in enumerate(moments.ring_moments)
        ],
        net_concrete=dict(
            **_area_moments_dict(moments.total),
            centroid_x_m=moments.centroid[0],
            centroid_y_m=moments.centroid[1],
            ix_centroid_m4=moments.centroidal_syy,
            iy_centroid_m4=moments.centroidal_sxx,
            ixy_centroid_m4=moments.centroidal_sxy,
        ),
    )

    concrete = inp["concrete"]
    mild_ids = list(dict.fromkeys(
        [item.get("material_id") for item in inp.get("bar_elements", [])]
        + ([inp.get("capacity_steel_material_id")]
           if inp.get("shear_on") or inp.get("torsion_on") else [])
    ))
    mild_ids = [value for value in mild_ids if value]
    mild_laws = inp.get("mild_materials") or {}
    if not mild_ids and (inp.get("bars") or inp.get("shear_on")
                         or inp.get("torsion_on")):
        mild_ids = ["-"]
        mild_laws = {"-": inp["steel"]}
    mild = []
    for material_id in mild_ids:
        material = mild_laws.get(material_id)
        if material is None:
            continue
        mild.append(dict(
            material_id=material_id,
            characteristic_yield_mpa=material.fytk,
            yield_factor=material.gamma_y,
            design_yield_mpa=capacity.design_yield(material),
        ))

    prestress_ids = list(dict.fromkeys(
        item.get("material_id") for item in inp.get("tendon_elements", [])
    ))
    prestress_ids = [value for value in prestress_ids if value]
    prestress_laws = inp.get("prestress_materials") or {}
    if not prestress_ids and inp.get("tendons") and inp.get("prestress") is not None:
        prestress_ids = ["-"]
        prestress_laws = {"-": inp["prestress"]}
    prestress_materials = []
    for material_id in prestress_ids:
        material = prestress_laws.get(material_id)
        if material is None:
            continue
        prestress_materials.append(dict(
            material_id=material_id,
            curve=material.curve,
            rupture_strain=material.rupture_strain,
            characteristic_stress_at_rupture_mpa=(
                material.stress(material.rupture_strain, design=False)
                if material.curve in (1, 2, 3, 4, 5) else None
            ),
        ))
    material_properties = dict(
        concrete=dict(
            variant=("2023" if "2023" in str(inp.get("concrete_preset", ""))
                     else "2005"),
            characteristic_strength_mpa=concrete.fck,
            strength_factor=concrete.alpha_cc,
            partial_factor=concrete.gamma_c,
            eta_cc=inp.get("concrete_eta_cc"),
            k_tc=inp.get("concrete_k_tc"),
            design_strength_mpa=concrete.fcd,
        ),
        mild=mild,
        prestress=prestress_materials,
    )

    prestress = capacity.locked_in_prestress_result(inp)
    tendon_elements = list(inp.get("tendon_elements") or [])
    prestress_rows = []
    for value in prestress.tendons:
        row = dataclasses.asdict(value)
        row["material_id"] = (
            tendon_elements[value.tendon_index].get("material_id")
            if value.tendon_index < len(tendon_elements) else None
        )
        prestress_rows.append(row)
    # Bond strain difference per tendon (see _apply_bonded_prestrain): elastic and
    # fatigue models at nl, plastic model at Es/Ecm.
    bond_strain = []
    effective = inp.get("tendon_effective_prestrain")
    sls_laws = list(inp.get("tendon_materials") or [])
    uls_laws = list(capacity.plastic_tendon_materials(inp) or [])
    elastic_unavailable = bool(inp.get("tendon_bond_elastic_unavailable"))
    if (
        effective is not None
        and len(effective) == len(sls_laws) == len(uls_laws)
        and inp.get("tendon_materials_uls") is not None
    ):
        for index, (value, sls, uls) in enumerate(
            zip(effective, sls_laws, uls_laws)
        ):
            bond_strain.append(dict(
                element_id=(
                    prestress_rows[index]["element_id"]
                    if index < len(prestress_rows) else str(index + 1)
                ),
                effective_strain=float(value),
                bond_strain_elastic=(
                    None if elastic_unavailable else float(sls.IS)
                ),
                bond_stress_elastic_mpa=(
                    None if elastic_unavailable
                    else float(sls.Es) * float(sls.IS)
                ),
                bond_strain_plastic=float(uls.IS),
            ))
    prestress_initial = dict(
        elements=prestress_rows,
        bond_strain=bond_strain,
        internal_resultant_origin=dict(
            n_kn=prestress.total_n_kn,
            mx_knm=prestress.total_mx_knm,
            my_knm=prestress.total_my_knm,
        ),
        equivalent_action_origin=dict(
            n_kn=-prestress.total_n_kn,
            mx_knm=prestress.total_mx_knm,
            my_knm=prestress.total_my_knm,
        ),
    )

    descriptors = []
    seen = set()
    for family, elements, materials in (
        ("mild", inp.get("bar_elements", []), inp.get("bar_materials", [])),
        ("prestress", inp.get("tendon_elements", []),
         inp.get("tendon_materials", [])),
    ):
        for element, material in zip(elements, materials):
            material_id = str(element.get("material_id") or "-")
            identity = (family, material_id)
            if identity in seen:
                continue
            seen.add(identity)
            descriptors.append((material_id, family, material.Es))
    if not descriptors:
        if inp.get("bars") and inp.get("steel") is not None:
            descriptors.append(("M1", "mild", inp["steel"].Es))
        if inp.get("tendons") and inp.get("prestress") is not None:
            descriptors.append(("P1", "prestress", inp["prestress"].Es))
    ratios = elastic_core.calculate_modular_ratios(
        float(inp["conc_Ec"]) * 1000.0,
        float(inp.get("el_phi") or 0.0),
        descriptors,
    )
    elastic_shared = dict(
        concrete_modulus_mpa=ratios.concrete_modulus_mpa,
        effective_concrete_modulus_mpa=ratios.effective_concrete_modulus_mpa,
        creep_coefficient=ratios.creep_coefficient,
        materials=[dataclasses.asdict(value) for value in ratios.materials],
    )
    return dict(
        section_properties=section_properties,
        material_properties=material_properties,
        prestress_initial=prestress_initial,
        elastic_shared=elastic_shared,
    )


def _elastic_solver_inputs(inp, shared_results):
    """Prepare existing per-element elastic inputs once for every named case."""

    all_laws = list(inp.get("bar_materials") or
                    [inp["steel"]] * len(inp.get("bars", [])))
    all_laws.extend(inp.get("tendon_materials") or [])
    n_mult = (
        np.asarray(
            [material.Es / STEEL_REFERENCE_MODULUS for material in all_laws],
            dtype=float,
        )
        if all_laws else None
    )
    tendon_laws = list(inp.get("tendon_materials") or [])
    prestress_stress = None
    if inp.get("tendons") and tendon_laws:
        # The bonded locked-in stress Ep*eps_p(0); under prestress alone the
        # solved tendon stress is the effective Ep*IS (see _apply_bonded_prestrain).
        prestress_stress = np.asarray(
            [0.0] * len(inp.get("bars", []))
            + [material.Es * material.IS * 1000.0 for material in tendon_laws],
            dtype=float,
        )
    return n_mult, prestress_stress


def _crack_dict(cw, bar_ids=None, tendon_ids=None):
    """Flatten a CrackWidthResult (or None) for the results payload."""
    if cw is None:
        return None

    bar_ids = list(bar_ids or [])
    tendon_ids = list(tendon_ids or [])
    n_bars = len(bar_ids)

    def retained_record(value):
        """Serialize one family-owned retained record without deriving values."""

        if value is None:
            return None
        row = dataclasses.asdict(value)
        row["record_kind"] = type(value).__name__
        return row

    def element(index):
        if index < n_bars:
            number = index + 1
            element_id = bar_ids[index] if index < len(bar_ids) else f"bar {number}"
            return "Bar", number, element_id
        number = index - n_bars + 1
        tendon_index = index - n_bars
        element_id = (tendon_ids[tendon_index]
                      if tendon_index < len(tendon_ids) else f"tendon {number}")
        return "Tendon", number, element_id

    def candidate(c):
        kind, number, element_id = element(c.bar_index)
        return dict(
            element_type=kind, element_no=number,
            element_id=element_id,
            x_mm=c.x * _MM, y_mm=c.y * _MM, area_mm2=c.area,
            wk=c.wk, sr_max=c.sr_max, esm_ecm=c.esm_ecm,
            sigma_s=c.sigma_s, rho_p_eff=c.rho_p_eff, ac_eff=c.ac_eff,
            hc_ef=c.hc_ef, phi=c.phi, cover=c.cover, coarse=c.coarse,
            edition=c.edition, kw=c.kw, k1_r=c.k1_r, kfl=c.kfl,
            sr_max_geometric=c.sr_max_geometric,
            as_eff=c.as_eff, ap_eff=c.ap_eff,
            ap_eff_weighted=c.ap_eff_weighted, xi1=c.xi1,
            reinforcement_type=c.reinforcement_type, bc_ef=c.bc_ef,
            direct_tension=c.direct_tension, scope=c.scope,
            direction_deg=c.direction_deg,
            equivalent_diameter=c.equivalent_diameter,
            diameter_source=c.diameter_source,
            cover_source=c.cover_source,
            bond_coefficient=c.bond_coefficient,
            modular_ratio=c.modular_ratio,
            mean_strain_operands=retained_record(c.mean_strain_operands),
            spacing_operands=retained_record(c.spacing_operands),
        )

    kind, number, element_id = element(cw.gov_bar)
    governing_candidate = (
        candidate(cw.candidates[0]) if cw.candidates else None
    )
    effective_reinforcement = retained_record(
        cw.effective_reinforcement_2023
    )
    if effective_reinforcement is not None:
        for row in effective_reinforcement.get("elements", []):
            element_kind, element_number, retained_id = element(
                int(row["element_index"])
            )
            row.update(
                element_type=element_kind,
                element_no=element_number,
                element_id=retained_id,
            )
    effective_elements = []
    for retained in cw.effective_reinforcement:
        row = dataclasses.asdict(retained)
        element_kind, element_number, retained_id = element(
            int(row["element_index"])
        )
        row.update(
            element_type=element_kind,
            element_no=element_number,
            element_id=retained_id,
        )
        effective_elements.append(row)
    return dict(
        wk=cw.wk, sr_max=cw.sr_max, esm_ecm=cw.esm_ecm,
        sigma_s=cw.sigma_s, rho_p_eff=cw.rho_p_eff, ac_eff=cw.ac_eff,
        hc_ef=cw.hc_ef, phi=cw.phi, cover=cw.cover,
        gov_bar=cw.gov_bar + 1, element_type=kind, element_no=number,
        element_id=element_id, coarse=cw.coarse,
        edition=cw.edition, kw=cw.kw, k1_r=cw.k1_r, kfl=cw.kfl,
        sr_max_geometric=cw.sr_max_geometric,
        as_eff=cw.as_eff, ap_eff=cw.ap_eff,
        ap_eff_weighted=cw.ap_eff_weighted,
        xi1_min=cw.xi1_min, xi1_max=cw.xi1_max,
        bc_ef=cw.bc_ef, direct_tension=cw.direct_tension,
        scope=cw.scope, direction_deg=cw.direction_deg,
        effective_area_operands=retained_record(cw.effective_area_operands),
        effective_reinforcement_2023=effective_reinforcement,
        effective_reinforcement=effective_elements,
        governing_rule=cw.governing_rule,
        governing_candidate=governing_candidate,
        candidates=[candidate(c) for c in cw.candidates],
    )


def _outline_bbox(outer):
    """Bounding box ``(xmin, ymin, xmax, ymax)`` of the outline, or ``None``.

    Used to clip the drawn neutral-axis segment to the section (viz.na_line_at):
    unclipped it spans +/- extent about the origin-closest point, which overshoots
    badly for a section drawn away from the origin.
    """
    outer = [] if outer is None else list(outer)
    if len(outer) < 3:
        return None
    xs = [p[0] for p in outer]
    ys = [p[1] for p in outer]
    return (min(xs), min(ys), max(xs), max(ys))


def _shear_lever_arm(*args, **kwargs):
    return capacity.shear_lever_arm(*args, **kwargs)


def _shear_face_mrd(*args, **kwargs):
    return capacity.shear_face_mrd(*args, **kwargs)


def _tube_torsion(*args, **kwargs):
    return capacity.tube_torsion(*args, **kwargs)


def _run_single_analysis(
    inp,
    *,
    reuse_plastic=None,
    reuse_elastic=None,
    elastic_solver_inputs=None,
    shared_results=None,
):
    """Run one Plastic/Elastic action pair and return the results payload.

    ``reuse_plastic`` / ``reuse_elastic`` let the caller pass a previously computed
    plastic / elastic sub-result whose inputs are unchanged (its split signature
    matches); that analysis is then skipped and the cached result reused, so a Both
    run that only touched the elastic (or only the plastic) inputs recomputes just
    the affected half.
    """
    out = {}
    if (inp["section"] is None or inp.get("geometry_error")
            or inp.get("void_error")
            or inp.get("steel_error") or inp.get("material_error")):
        return out                          # invalid section -> nothing to run
    if shared_results is None:
        shared_results = _section_and_material_results(inp)
    if elastic_solver_inputs is None:
        elastic_solver_inputs = _elastic_solver_inputs(inp, shared_results)
    if inp["mode"] in ("Plastic", "Both") and reuse_plastic is not None:
        out["plastic"] = reuse_plastic
    elif inp["mode"] in ("Plastic", "Both"):
        _warm_solver()
        sweep_angles = _sweep(inp["v_min"], inp["v_max"], inp["v_inc"])
        vlo, vhi = sweep_angles[0], sweep_angles[-1]
        # A full 360 deg turn returns to the start, so the last angle (v_max) repeats
        # the first (v_min) exactly. Sweep only up to the angle before it -- the
        # envelope closes itself -- so that duplicate point is neither computed nor
        # reported. The closed-envelope flag still reflects the full turn.
        closed = plastic_core.plastic_sweep_is_full_turn(vlo, vhi)
        sweep_hi = sweep_angles[-2] if closed else vhi
        # Prestress enters the analysis only when the section actually has tendons.
        pre = inp["prestress"] if inp["tendons"] else None
        # The user enters N tension-positive; the solver is compression-positive, so
        # negate at the boundary (the engine and its verification are unchanged).
        pts = solve_plastic(inp["section"], inp["concrete"], inp["steel"],
                            -inp["P_pl"], vlo, sweep_hi, inp["v_inc"], prestress=pre,
                            bar_materials=inp.get("bar_materials"),
                            tendon_materials=capacity.plastic_tendon_materials(inp))
        mx = [p.Mx for p in pts]
        my = [p.My for p in pts]
        # Utilisation is a closed-envelope check (a partial arc has no wrap-around), and
        # only reported when the user asks to check it; otherwise this is a capacity-only
        # run (the applied moments are ignored and locked).
        check_util = inp.get("check_util", True)
        if closed and check_util:
            radial = combined.radial_util_result(
                mx, my, inp["Mx_pl"], inp["My_pl"]
            )
            util = radial.utilisation if radial.valid else None
            util_gov = radial.governing_index if radial.valid else None
            util_demand = radial.demand
            util_resistance = radial.resistance
            util_valid = radial.valid
            util_reason = radial.reason
            util_origin_inside_or_on = radial.origin_inside_or_on
        else:
            util, util_gov = None, None
            util_demand, util_resistance = None, None
            util_valid, util_reason = None, None
            util_origin_inside_or_on = None
        out["plastic"] = dict(
            mx=mx, my=my,
            max_mx=max(mx), max_my=max(my), min_mx=min(mx), min_my=min(my),
            util=util, util_gov=util_gov, closed=closed, check_util=check_util,
            util_demand=util_demand, util_resistance=util_resistance,
            util_valid=util_valid, util_reason=util_reason,
            util_origin_inside_or_on=util_origin_inside_or_on,
            applied=((inp["Mx_pl"], inp["My_pl"]) if check_util else None),
            converged=all(p.converged for p in pts),
            # The adapter publishes the accepted state already evaluated by the
            # plastic family. It performs unit/sign conversion and identity
            # decoration only; no material law or capacity calculation is repeated.
            points=[_plastic_point_result(point, inp) for point in pts],
            effective_depths=capacity.plastic_effective_depths(inp),
        )
        worked_index = (
            util_gov
            if util_gov is not None and 0 <= util_gov < len(pts)
            else max(range(len(pts)), key=lambda index: math.hypot(
                pts[index].Mx, pts[index].My
            ))
        )
        out["plastic"].update(
            worked_point_index=worked_index,
            worked_point_basis=(
                "utilisation direction" if util_gov is not None
                else "peak resultant moment"
            ),
        )
        # Opt-in N-M interaction diagrams, one about each bending axis. For each axis
        # trace the +M branch (NA angle stored as V) and the -M branch (V+180) from
        # pure tension to the squash load, then join them into one closed capacity
        # boundary. About x uses a horizontal neutral axis (V = 90/270, Mx varies);
        # about y a vertical one (V = 0/180, My varies).
        # Each diagram holds the companion moment at the case value (review item
        # TA-08): a fixed neutral-axis angle overstated the uniaxial capacity of
        # sections that are not symmetric about the bending axis. Without the
        # utilisation check the case moments are not used, so the companion
        # moment is zero (uniaxial diagrams).
        if inp.get("interaction"):
            nm_with_case = inp.get("check_util", True)
            mx_companion = float(inp["Mx_pl"]) if nm_with_case else 0.0
            my_companion = float(inp["My_pl"]) if nm_with_case else 0.0

            def diagram(axis, m_off):
                return plastic_core.uniaxial_interaction_loop(
                    inp["section"], inp["concrete"], inp["steel"], axis,
                    m_off=m_off, prestress=pre,
                    bar_materials=inp.get("bar_materials"),
                    tendon_materials=capacity.plastic_tendon_materials(inp),
                )

            nm_x = diagram("x", my_companion)
            nm_y = diagram("y", mx_companion)
            loop_x = nm_x.upper + list(reversed(nm_x.lower))
            loop_y = nm_y.upper + list(reversed(nm_y.lower))
            # The solver reports the axial compression-positive; negate it so the
            # diagram and the applied point are both tension-positive (matching N).
            # The limits are (squash load, tension limit) of the two fixed-angle
            # traces of each diagram.
            out["plastic"]["interaction"] = dict(
                x=dict(N=[-q.axial for q in loop_x], M=[q.Mx for q in loop_x],
                       applied=(inp["P_pl"], inp["Mx_pl"]),
                       converged=all(q.converged for q in loop_x),
                       companion=my_companion, limits=(-nm_x.n_c, -nm_x.n_t)),
                y=dict(N=[-q.axial for q in loop_y], M=[q.My for q in loop_y],
                       applied=(inp["P_pl"], inp["My_pl"]),
                       converged=all(q.converged for q in loop_y),
                       companion=mx_companion, limits=(-nm_y.n_c, -nm_y.n_t)),
            )
    if inp["mode"] in ("Elastic", "Both") and reuse_elastic is not None:
        out["elastic"] = reuse_elastic
    elif inp["mode"] in ("Elastic", "Both"):
        # The user enters N tension-positive; the elastic solver takes it
        # compression-positive, so negate it once here and pass the compression form
        # to every elastic call (main solve and the two cracking checks).
        p_el_l, p_el_s = -inp["P_el_l"], -inp["P_el_s"]
        # Tendons are folded into the bar set for the elastic run. Each tendon uses
        # its own modular ratio (Ep/Ec, via the multiplier Ep/Es) and carries the
        # locked-in prestress Ep*eps_p(0), applied as a force so the user's N is the
        # external normal force only -- matching the plastic solver.
        sec = inp["section"]
        bar_laws = list(inp.get("bar_materials") or
                        [inp["steel"]] * len(inp["bars"]))
        tendon_laws = list(inp.get("tendon_materials") or [])
        all_laws = bar_laws + tendon_laws
        n_mult, prestress_stress = elastic_solver_inputs
        pre_resultant = None
        if inp["tendons"]:
            sec = section_core.Section.from_polygon(
                corners=inp["outer"],
                bars_xy_area_mm2=list(inp["bars"]) + list(inp["tendons"]),
                holes=inp["holes"],
            )
            internal = shared_results["prestress_initial"][
                "internal_resultant_origin"
            ]
            pre_resultant = (
                internal["n_kn"], internal["mx_knm"], internal["my_knm"]
            )
        r = solve_elastic_combined(sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"],
                                   inp["nl"], p_el_s, inp["Mx_el_s"],
                                   inp["My_el_s"], inp["ns"],
                                   n_mult=n_mult, prestress_stress=prestress_stress)
        mpa = lambda arr: [s / 1000.0 for s in arr]  # kN/m2 -> MPa
        total = mpa(r.bar_stress_total)
        bar_ids = [item["id"] for item in inp.get("bar_elements", [])]
        tendon_ids = [item["id"] for item in inp.get("tendon_elements", [])]
        mild_names = {
            item["id"]: item["name"]
            for item in inp["mild_material_catalog"]["items"]
        }
        prestress_names = {
            item["id"]: item["name"]
            for item in inp["prestress_material_catalog"]["items"]
        }
        elements = sls_core.element_rows(
            inp["bars"], inp["tendons"],
            total=total, long=mpa(r.bar_stress_long),
            dif=mpa(r.bar_stress_dif), rst1=mpa(r.bar_stress_rst1),
            es_mpa=[material.Es for material in bar_laws],
            ep_mpa=([material.Es for material in tendon_laws]
                    if tendon_laws else None),
            bar_ids=bar_ids, tendon_ids=tendon_ids,
            bar_material_ids=[item["material_id"]
                              for item in inp.get("bar_elements", [])],
            tendon_material_ids=[item["material_id"]
                                 for item in inp.get("tendon_elements", [])],
            bar_material_names=[mild_names.get(element["material_id"], "")
                                for element in inp.get("bar_elements", [])],
            tendon_material_names=[
                prestress_names.get(element["material_id"], "")
                for element in inp.get("tendon_elements", [])
            ],
        )
        long_passive = mpa(r.bar_stress_long_passive)
        reduced_long = mpa(r.bar_stress_reduced_long)
        locked_in = mpa(r.bar_stress_locked_in)
        for index, row in enumerate(elements):
            row.update(
                long_passive_mpa=long_passive[index],
                reduced_long_mpa=reduced_long[index],
                locked_in_mpa=locked_in[index],
            )
        corners = sls_core.concrete_corner_rows(
            inp["outer"], inp["holes"],
            stress_plane=(r.short_term.eps0, r.short_term.kx, r.short_term.ky),
            ec_mpa=inp["conc_Ec"] * 1000.0,
        )
        governing_element = (
            max(elements, key=lambda row: row["total_mpa"]) if elements else None
        )
        if governing_element is not None and governing_element["total_mpa"] <= 0.0:
            governing_element = None
        stress_outputs = sls_core.stress_outputs(
            total,
            n_bars=len(inp["bars"]),
            max_concrete_compression=r.max_concrete_compression / 1000.0,
            valid=r.converged,
            bar_ids=bar_ids, tendon_ids=tendon_ids,
        )
        out["elastic"] = dict(
            field_context=section_fields.context_signature(inp, "Elastic"),
            total=total, long=mpa(r.bar_stress_long), dif=mpa(r.bar_stress_dif),
            rst1=mpa(r.bar_stress_rst1),
            max_conc=r.max_concrete_compression / 1000.0,
            max_conc_xy=tuple(r.short_term.max_concrete_xy),
            # Public point identifiers are one-based everywhere; the engine keeps
            # zero-based arrays internally.
            max_conc_point=int(r.max_concrete_point) + 1,
            na_x=r.na_x_intercept, na_y=r.na_y_intercept,
            max_steel=(governing_element["total_mpa"] if governing_element else 0.0),
            # Compatibility field: global one-based position in the solver's
            # bars-then-tendons array. New presentation uses max_steel_element so
            # a tendon is never labelled as a reinforcing bar.
            max_steel_bar=(int(np.argmax(total)) + 1
                           if governing_element is not None else 0),
            max_steel_type=(governing_element["element_type"]
                            if governing_element else None),
            max_steel_element=(governing_element["element_id"]
                               if governing_element else None),
            prestress=pre_resultant,
            converged=r.converged,
            stress_plane=(r.short_term.eps0, r.short_term.kx, r.short_term.ky),
            accepted_states=dict(
                long_term=_elastic_state_result(r.long),
                instantaneous_combined=_elastic_state_result(r.short_term),
            ),
            superposition=dict(
                long_term_modular_ratio=r.long_term_modular_ratio,
                short_term_modular_ratio=r.short_term_modular_ratio,
                long_term_reduction_factor=r.long_term_reduction_factor,
                prestress_resultant=_elastic_resultant_result(
                    r.prestress_resultant
                ),
                combined_target_before_neutralisation=_elastic_resultant_result(
                    r.combined_target_before_neutralisation
                ),
                neutralising_resultant=_elastic_resultant_result(
                    r.neutralising_resultant
                ),
            ),
            elements=elements,
            concrete_corners=corners,
            stress_outputs=stress_outputs,
        )

        # Extended serviceability checks. Explicit bars take clear cover from the
        # geometry; a verified slab-density layout supplies its physical face cover
        # and entered spacing instead of treating integration points as bar axes.
        # The user-defined long-term
        # state at nl (beta/kt = 0.5/0.4) drives the cracking threshold, the
        # section properties and tension stiffening; the short-term (instantaneous)
        # state -- the total long+short load at ns (beta/kt = 1.0/0.6) -- gives the
        # short-term crack width. Crack width is reported for both loads.
        if inp["sls_phi"] > 0.0:
            phi = inp["sls_phi"]
        else:
            phi = [
                (
                    item["diameter_mm"]
                    if item.get("size_mode")
                    in {
                        rebar_table.DIAMETER_MODE,
                        rebar_table.INDEPENDENT_MODE,
                    }
                    else 0.0
                )
                for item in (inp.get("bar_elements", [])
                             + inp.get("tendon_elements", []))
            ]
        # k1 per bar: the mild reinforcement uses the selected bond value; any
        # prestressing tendons (folded into the bar set after the bars) always
        # use 1.6. Order matches sec.bar_arrays() (bars first, then tendons).
        k1_bars = [inp["sls_k1"]] * len(inp["bars"]) + [1.6] * len(inp["tendons"])
        density = inp.get("slab_density")
        physical_geometry_available = not (
            density is not None and density.get("status") == "UNVERIFIED"
        )
        physical_geometry_reason = (
            density.get("reason")
            if density is not None and not physical_geometry_available
            else None
        )
        crack_cover = None
        crack_spacing = None
        physical_spacing_points = None
        physical_spacing_groups = None
        if density is not None and density.get("status") == "VERIFIED":
            metadata = list(density.get("analysis_metadata") or [])
            if len(metadata) != len(inp["bars"]):
                physical_geometry_available = False
                physical_geometry_reason = _SLAB_DENSITY_GUIDANCE
            else:
                crack_cover = [float(item["cover_mm"]) for item in metadata]
                crack_spacing = [
                    float(item["nominal_spacing_mm"]) for item in metadata
                ]
                physical_spacing_groups = [
                    item.get("spacing_group") for item in metadata
                ]
                if inp["tendons"]:
                    rings = list(sec.integration_rings())
                    tendon_elements = list(inp.get("tendon_elements", []))
                    try:
                        tendon_cover = [
                            _slab_tendon_face_clear_cover_mm(
                                item["y"], item["diameter_mm"], rings[0]
                            )
                            for item in tendon_elements
                        ]
                    except (IndexError, KeyError, TypeError, ValueError, OverflowError):
                        physical_geometry_available = False
                        physical_geometry_reason = _SLAB_TENDON_FACE_GUIDANCE
                        tendon_cover = [0.0] * len(tendon_elements)
                    crack_cover.extend(tendon_cover)
                    crack_spacing.extend(
                        math.nan for _item in tendon_elements
                    )
                    physical_spacing_groups.extend(
                        None for _item in tendon_elements
                    )
                physical_spacing_points = [
                    (
                        float(item["x_mm"]) / _MM,
                        float(item["y_mm"]) / _MM,
                        None,
                        item.get("spacing_group"),
                    )
                    for item in density.get("physical_elements", ())
                ]
                physical_spacing_points.extend(
                    (
                        float(item["x"]),
                        float(item["y"]),
                        len(inp["bars"]) + index,
                    )
                    for index, item in enumerate(
                        inp.get("tendon_elements", [])
                    )
                )
        # Dispatch only through the immutable capability binding. Persisted labels
        # and label substrings never select an engineering route.
        ordinary_binding = design_standards.capability_binding(
            inp["sls_code"],
            design_standards.Capability.ORDINARY_CRACK_WIDTH,
        )
        ordinary_route = ordinary_binding.ordinary_crack_width_route
        if ordinary_route is None:
            raise ValueError("The selected basis has no ordinary crack-width route")
        dk_na = ordinary_route.k3_cover_dependent
        slabs_or_prestressed = (
            inp["sls_member"] == "Slab" or bool(inp["tendons"])
        )
        include_hx = (
            ordinary_route.include_hx_term_for_slabs_or_prestressed
            if slabs_or_prestressed
            else ordinary_route.include_hx_term_for_ordinary_beams
        )
        report_coarse = ordinary_route.report_coarse_system
        crack_basis = design_standards.get_design_basis(inp["sls_code"])
        # Cracking is irreversible and is triggered by the maximum load the section
        # ever sees, so the section is cracked if EITHER the sustained (long-term) or
        # the peak (total) action exceeds the cracking stress. The peak check uses
        # the combined creep state (long @ nl superposed with short @ ns), matching
        # the reported Total/RST1 stresses; a short-term action that counteracts the
        # sustained one can leave the peak uncracked while the long-term already
        # cracked, and vice versa. Report the governing (smallest lambda_cr) of the
        # two.
        # cr_l provides the long-term cracked state and the sustained cracking
        # factor; its own crack width is unused (the crack widths are computed
        # below per system), so the coarse flag here is immaterial.
        # The Stage I solves use the locked-in stress of the uncracked section
        # (_apply_bonded_prestrain), so that prestress alone gives Ep*IS also in
        # Stage I. An input without that state keeps the Stage II stress.
        stage_one = inp.get("tendon_stage_one_stress")
        stage_one_stress = (
            None if prestress_stress is None or stage_one is None
            else np.asarray([0.0] * len(inp["bars"]) + list(stage_one), dtype=float)
        )
        cr_l = analyse_cracking(
            sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            fctm=inp["sls_fctm"], Es=[material.Es for material in all_laws],
            beta=0.5, kt=0.4,
            cover=crack_cover, bar_diameter=phi,
            nominal_spacing=crack_spacing,
            physical_spacing_points=physical_spacing_points,
            physical_spacing_groups=physical_spacing_groups,
            k1=k1_bars,
            physical_geometry_available=physical_geometry_available,
            physical_geometry_reason=physical_geometry_reason,
            k3_cover_dependent=dk_na, include_hx_term=include_hx,
            edition=ordinary_route.edition,
            n_mult=n_mult, prestress_stress=prestress_stress,
            stage_one_prestress_stress=stage_one_stress)
        sls_converged = (
            r.converged
            and cr_l.uncracked.converged
            and cr_l.cracked_state.converged
        )
        out["elastic"]["converged"] = sls_converged
        if not sls_converged:
            for output in out["elastic"]["stress_outputs"].values():
                output.update(value=None, calculation_state="INVALID")
        crk_t, lam_t, sig_t = combined_cracking(
            sec, p_el_l, inp["Mx_el_l"], inp["My_el_l"], inp["nl"],
            p_el_s, inp["Mx_el_s"], inp["My_el_s"], inp["ns"],
            fctm=inp["sls_fctm"], n_mult=n_mult, prestress_stress=prestress_stress,
            stage_one_prestress_stress=stage_one_stress)
        # Governing case. Its cracked state (for the reported cracked properties) is
        # the combined creep total state (r.short_term) when the peak strictly
        # governs, or the long-term cracked state when the sustained action governs.
        # Ties (e.g. no short-term load, where the peak reduces to the sustained
        # check) go to the sustained state, so a long-term-only run keeps its nl
        # cracked properties rather than the instantaneous combined state.
        if lam_t < cr_l.lambda_cr:
            cracked, lambda_cr, sigma_ct, gov_state = crk_t, lam_t, sig_t, r.short_term
        else:
            cracked, lambda_cr, sigma_ct = (cr_l.cracked, cr_l.lambda_cr,
                                            cr_l.sigma_ct)
            gov_state = cr_l.cracked_state
        # Each material uses its own modular ratio; deduct the concrete occupied
        # by reinforcement wherever concrete remains active.
        props_un = transformed_properties(sec, inp["nl"], cracked=False, n_mult=n_mult)
        props_cr = (transformed_properties(
            sec, inp["nl"], eps0=gov_state.eps0, kx=gov_state.kx, ky=gov_state.ky,
            cracked=True, n_mult=n_mult) if cracked else None)
        out["elastic"].update(
            cracked=cracked, lambda_cr=lambda_cr, sigma_ct=sigma_ct,
            fctm=inp["sls_fctm"], show_cw=inp["sls_cw"],
            props_un=_props_dict(props_un),
            props_cr=(_props_dict(props_cr) if props_cr is not None else None),
            crack=None, crack_short=None,
            crack_basis_key=crack_basis.key.value,
            crack_code=crack_basis.label,
            crack_edition=ordinary_route.edition,
            crack_member=(inp["sls_member"] if report_coarse else None),
        )
        # Crack width is its own opt-in, reported for both load cases once the
        # section has cracked. The short-term state reuses the combined creep solve
        # `r`: its instantaneous neutral axis with the displayed total steel stress
        # (s2 + RST1), so the crack-width sigma_s matches the Total column rather
        # than a raw (long+short)-at-ns solve. Cover follows the physical source
        # selected above.
        crack_evaluations = {}
        if inp["sls_cw"] and cracked:
            # Crack width uses the load-induced steel stress, so strip the locked-in
            # tendon prestress back out of the reported total (mild bars unaffected).
            cw_stress = np.asarray(r.bar_stress_total, dtype=float)
            if prestress_stress is not None:
                cw_stress = cw_stress - prestress_stress
            short_state = dataclasses.replace(r.short_term, bar_stress=cw_stress)

            reinforcement_types = (
                ["mild"] * len(inp["bars"])
                + ["prestress"] * len(inp["tendons"])
            )
            tendon_xi = (
                None
                if not inp["tendons"] or inp.get("sls_tendon_xi", 0.0) <= 0.0
                else [1.0] * len(inp["bars"])
                + [float(inp["sls_tendon_xi"])] * len(inp["tendons"])
            )

            def _cw(state, n, kt, coarse):
                # n sets the cracked state; Formula (7.9) and 2023 (9.11) use
                # alpha_e = Es/Ecm (7.3.4(2)) for both durations.
                return evaluate_crack_width(
                    sec,
                    state,
                    n,
                    alpha_e_ratio=inp["ns"],
                    fctm=inp["sls_fctm"],
                    Es=[material.Es for material in all_laws],
                    kt=kt,
                    cover=crack_cover,
                    bar_diameter=phi,
                    nominal_spacing=crack_spacing,
                    physical_spacing_points=physical_spacing_points,
                    physical_spacing_groups=physical_spacing_groups,
                    physical_geometry_available=physical_geometry_available,
                    physical_geometry_reason=physical_geometry_reason,
                    k1=k1_bars,
                    k3_cover_dependent=dk_na,
                    include_hx_term=include_hx,
                    coarse=coarse,
                    edition=ordinary_route.edition,
                    n_mult=n_mult,
                    reinforcement_types=reinforcement_types,
                    bond_ratio_xi=tendon_xi,
                )

            # Long-term crack width is on the cracked section under the user-entered
            # sustained action (kt = 0.4), computed directly from that state so it
            # is reported even when the long-term load alone would not cross the
            # cracking threshold. The short-term is the instantaneous total (kt = 0.6).
            long_evaluation = _cw(
                cr_l.cracked_state, inp["nl"], 0.4, False
            )
            short_evaluation = _cw(short_state, inp["ns"], 0.6, False)
            long_crack = _crack_dict(
                long_evaluation.result, bar_ids, tendon_ids
            )
            short_crack = _crack_dict(
                short_evaluation.result, bar_ids, tendon_ids
            )
            crack_evaluations.update(
                {
                    "Long-term": {
                        "status": long_evaluation.status,
                        "reason": long_evaluation.reason,
                        "result": long_crack,
                    },
                    "Short-term": {
                        "status": short_evaluation.status,
                        "reason": short_evaluation.reason,
                        "result": short_crack,
                    },
                }
            )
            out["elastic"].update(
                crack=long_crack,
                crack_short=short_crack,
            )
            # The DK NA reports the coarse crack system alongside the fine one, for
            # both load cases (four crack widths in total).
            if report_coarse:
                long_coarse_evaluation = _cw(
                    cr_l.cracked_state, inp["nl"], 0.4, True
                )
                short_coarse_evaluation = _cw(
                    short_state, inp["ns"], 0.6, True
                )
                long_coarse_crack = _crack_dict(
                    long_coarse_evaluation.result, bar_ids, tendon_ids
                )
                short_coarse_crack = _crack_dict(
                    short_coarse_evaluation.result, bar_ids, tendon_ids
                )
                crack_evaluations = {
                    "Long-term (fine)": crack_evaluations["Long-term"],
                    "Short-term (fine)": crack_evaluations["Short-term"],
                    "Long-term (coarse)": {
                        "status": long_coarse_evaluation.status,
                        "reason": long_coarse_evaluation.reason,
                        "result": long_coarse_crack,
                    },
                    "Short-term (coarse)": {
                        "status": short_coarse_evaluation.status,
                        "reason": short_coarse_evaluation.reason,
                        "result": short_coarse_crack,
                    },
                }
                out["elastic"].update(
                    crack_coarse=long_coarse_crack,
                    crack_short_coarse=short_coarse_crack,
                )
        eout = out["elastic"]
        if report_coarse:
            long_term_crack_cases = {
                name: crack_evaluations.get(name)
                for name in (
                    "Long-term (fine)",
                    "Long-term (coarse)",
                )
            }
            short_term_crack_cases = {
                name: crack_evaluations.get(name)
                for name in (
                    "Short-term (fine)",
                    "Short-term (coarse)",
                )
            }
        else:
            long_term_crack_cases = {
                name: crack_evaluations.get(name)
                for name in ("Long-term",)
            }
            short_term_crack_cases = {
                name: crack_evaluations.get(name)
                for name in ("Short-term",)
            }
        eout["crack_output"] = sls_core.crack_outputs(
            long_term_crack_cases,
            short_term_crack_cases,
            valid=eout["converged"],
            requested=bool(inp["sls_cw"]),
            long_term_criterion_mm=inp.get(
                LONG_TERM_PERMITTED_CRACK_WIDTH_KEY, 0.0
            ),
            short_term_criterion_mm=inp.get(
                SHORT_TERM_PERMITTED_CRACK_WIDTH_KEY, 0.0
            ),
            long_term_criterion_source=inp.get(
                "sls_long_term_permitted_crack_width_source"
            ),
            short_term_criterion_source=inp.get(
                "sls_short_term_permitted_crack_width_source"
            ),
        )
    if inp.get("minimum_reinforcement_on"):
        if inp.get("detailing_edition") == detailing.EC2_2023:
            _warm_solver()
        out["minimum_reinforcement"] = detailing.minimum_reinforcement(
            inp["section"],
            inp.get("bar_elements") or [],
            inp.get("bar_materials") or [],
            inp["concrete"],
            edition=inp["detailing_edition"],
            fctm_mpa=inp["sls_fctm"],
            n_ed_tension_kn=inp["P_pl"],
            mx_ed_knm=inp["Mx_pl"],
            my_ed_knm=inp["My_pl"],
            member_type=inp.get(
                "detailing_member_type", detailing.MEMBER_BEAM
            ),
            cut_direction=inp.get(
                "detailing_cut_direction", detailing.CUT_TRANSVERSE
            ),
        )
    _run_capacity_checks(inp, out)
    if inp.get("transverse_detailing_on"):
        out["transverse_reinforcement"] = _transverse_detailing_result(inp, out)
    _attach_formula_631_detailing_state(inp, out)
    return out


def _run_fatigue_or_invalid(inp):
    """Run fatigue when valid; otherwise return immutable INVALID evidence.

    Fatigue is independent of the requested plastic/elastic/capacity checks.
    Invalid fatigue input therefore cannot suppress otherwise valid results.
    """

    errors = fatigue_analysis.validation_errors(inp)
    return (
        fatigue_analysis.invalid_result(inp, errors)
        if errors
        else fatigue_analysis.run_analysis(inp)
    )


_HEIGHTENED_POSITIVE_INPUTS = (
    (
        "sls_heightened_effective_tensile_strength_mpa",
        "Effective tensile strength",
    ),
    (
        HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY,
        "Heightened permitted crack width",
    ),
    (
        "sls_heightened_fine_effective_tension_area_mm2",
        "Fine-system effective tension area",
    ),
    (
        "sls_heightened_coarse_effective_tension_area_mm2",
        "Coarse-system effective tension area",
    ),
)
_HEIGHTENED_BOOLEAN = EngineerMessage(
    "HEIGHTENED-ENABLED",
    "Choose whether heightened crack control is enabled",
)
_HEIGHTENED_ELASTIC_MODE = EngineerMessage(
    "HEIGHTENED-ELASTIC-MODE",
    "Enable Elastic analysis before checking heightened crack control",
)
_HEIGHTENED_DESIGN_BASIS = EngineerMessage(
    "HEIGHTENED-DESIGN-BASIS",
    "Select the first-generation DK NA:2024 design basis for heightened crack control",
)
_HEIGHTENED_SURFACE = EngineerMessage(
    "HEIGHTENED-SURFACE",
    "Select ribbed or smooth reinforcement for heightened crack control",
)
_HEIGHTENED_POSITIVE_MESSAGES = {
    "sls_heightened_effective_tensile_strength_mpa": EngineerMessage(
        "HEIGHTENED-TENSILE-STRENGTH",
        "Enter a positive finite effective tensile strength",
    ),
    HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY: EngineerMessage(
        "HEIGHTENED-CRACK-LIMIT",
        "Enter a positive finite heightened crack-width limit",
    ),
    "sls_heightened_fine_effective_tension_area_mm2": EngineerMessage(
        "HEIGHTENED-FINE-AREA",
        "Enter a positive finite fine-system effective tension area",
    ),
    "sls_heightened_coarse_effective_tension_area_mm2": EngineerMessage(
        "HEIGHTENED-COARSE-AREA",
        "Enter a positive finite coarse-system effective tension area",
    ),
}
_HEIGHTENED_REFERENCE_REQUIRED = EngineerMessage(
    "HEIGHTENED-REFERENCE-REQUIRED",
    "Enable crack-width calculation for at least one Elastic case",
)
_HEIGHTENED_REFERENCE_SELECT = EngineerMessage(
    "HEIGHTENED-REFERENCE-SELECT",
    "Select one crack-enabled Elastic case as the heightened reference",
)
_HEIGHTENED_REFERENCE_DISPLAY = EngineerMessage(
    "HEIGHTENED-REFERENCE-CASE",
    "Review the Elastic reference case for heightened crack control",
)


def _heightened_crack_control_validation_errors(inp):
    """Validate the separate DK calculation without evaluating its formula."""

    enabled = inp.get("sls_heightened_on", False)
    if type(enabled) is not bool:
        return [_HEIGHTENED_BOOLEAN]
    if not enabled:
        return []

    errors = []
    if inp.get("mode") not in {"Elastic", "Both"}:
        errors.append(_HEIGHTENED_ELASTIC_MODE)
    try:
        design_standards.capability_binding(
            inp.get("sls_code"),
            design_standards.Capability.HEIGHTENED_CRACK_CONTROL,
        )
    except ValueError:
        errors.append(_HEIGHTENED_DESIGN_BASIS)
    if inp.get("sls_heightened_reinforcement_surface") not in {
        "ribbed",
        "smooth",
    }:
        errors.append(_HEIGHTENED_SURFACE)
    for key, _label in _HEIGHTENED_POSITIVE_INPUTS:
        value = inp.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = math.nan
        if (
            isinstance(value, bool)
            or type(value).__name__ == "bool_"
            or not math.isfinite(number)
            or number <= 0.0
        ):
            errors.append(_HEIGHTENED_POSITIVE_MESSAGES[key])
    try:
        records = case_analysis.case_records(inp, "elastic")
        names = heightened_adapter.crack_enabled_case_names(records)
    except Exception as exc:
        errors.append(engineer_messages.resolve(
            exc,
            fallback=_HEIGHTENED_REFERENCE_DISPLAY,
            context="heightened crack-control reference case",
        ))
    else:
        selected = inp.get("sls_heightened_reference_case")
        if not names:
            errors.append(_HEIGHTENED_REFERENCE_REQUIRED)
        elif len(names) > 1 and (
            not isinstance(selected, str) or selected not in names
        ):
            errors.append(_HEIGHTENED_REFERENCE_SELECT)
    return errors


def _heightened_crack_control_payload(inp, analysis_result):
    """Bind, derive and evaluate the dual family from retained case evidence."""

    reference_name = heightened_adapter.resolve_reference_case_name(
        case_analysis.case_records(inp, "elastic"),
        inp.get("sls_heightened_reference_case"),
    )
    reference = next(
        (
            entry
            for entry in analysis_result.get("elastic_cases", [])
            if entry.get("name") == reference_name
        ),
        None,
    )
    if not isinstance(reference, dict):
        raise ValueError(
            "The selected heightened reference case has no current calculated result"
        )
    derived = heightened_adapter.derive_heightened_reinforcement(
        reference,
        bar_diameter_override_mm=inp.get("sls_phi", 0.0),
    )
    result = heightened_crack_control_core.calculate_dual_heightened_crack_control(
        basis=inp["sls_code"],
        reinforcement_surface=inp["sls_heightened_reinforcement_surface"],
        bar_diameter_mm=derived.bar_diameter_mm,
        effective_tensile_strength_mpa=inp[
            "sls_heightened_effective_tensile_strength_mpa"
        ],
        reinforcement_modulus_mpa=derived.reinforcement_modulus_mpa,
        permitted_crack_width_mm=inp[HEIGHTENED_PERMITTED_CRACK_WIDTH_KEY],
        fine_effective_tension_area_mm2=inp[
            "sls_heightened_fine_effective_tension_area_mm2"
        ],
        coarse_effective_tension_area_mm2=inp[
            "sls_heightened_coarse_effective_tension_area_mm2"
        ],
        provided_reinforcement_area_mm2=(
            derived.provided_reinforcement_area_mm2
        ),
    )
    branch_payloads = {}
    for branch_name in ("fine", "coarse"):
        branch = getattr(result, branch_name)
        branch_payload = dataclasses.asdict(branch)
        branch_payload.update(
            basis_key=branch.basis_key.value,
            crack_system=branch.crack_system.value,
            reinforcement_surface=branch.reinforcement_surface.value,
            status=branch.status.value,
        )
        branch_payloads[branch_name] = branch_payload
    governing = branch_payloads[result.governing_crack_system.value]
    payload = {
        **governing,
        "fine": branch_payloads["fine"],
        "coarse": branch_payloads["coarse"],
        "governing_crack_system": result.governing_crack_system.value,
        "governing_required_reinforcement_area_mm2": (
            result.governing_required_reinforcement_area_mm2
        ),
        "governing_comparison_ratio": result.governing_comparison_ratio,
        "governing_status": result.governing_status.value,
        "reference_case_id": derived.reference_case_id,
        "ordinary_crack_branch": derived.ordinary_crack_branch,
        "diameter_source": derived.diameter_source,
        "diameter_governing_element_ids": list(
            derived.diameter_governing_element_ids
        ),
        "modulus_governing_material_ids": list(
            derived.modulus_governing_material_ids
        ),
        "contributions": [
            dataclasses.asdict(item) for item in derived.contributions
        ],
    }
    return payload


def _attach_heightened_crack_control(inp, result):
    """Attach exactly one section-level heightened result when requested."""

    if inp.get("sls_heightened_on"):
        result["heightened_crack_control"] = (
            _heightened_crack_control_payload(inp, result)
        )


def _clear_spacing_result(inp):
    """Use nominal slab axes, never density-analysis points, for detailing."""

    density = inp.get("slab_density")
    if density is not None and density.get("status") == "UNVERIFIED":
        return {
            "status": "NOT ASSESSED",
            "edition": inp["detailing_edition"],
            "clause": (
                "11.2(2)"
                if inp["detailing_edition"] == detailing.EC2_2023
                else "8.2(2)"
            ),
            "d_upper_mm": float(inp["detailing_d_upper"]),
            "include_tendons": bool(
                inp.get("detailing_include_tendons", False)
            ),
            "pairs": [],
            "governing": None,
            "reason": density.get("reason") or _SLAB_DENSITY_GUIDANCE,
            "limitations": [
                "Reapply the slab layout or define explicit bars before "
                "assessing clear spacing."
            ],
        }
    elements = list(inp.get("bar_elements") or [])
    if density is not None and density.get("status") == "VERIFIED":
        elements = list(density.get("physical_elements") or [])
    elements.extend(list(inp.get("tendon_elements") or []))
    return detailing.clear_spacing(
        elements,
        d_upper_mm=inp["detailing_d_upper"],
        edition=inp["detailing_edition"],
        include_tendons=inp.get("detailing_include_tendons", False),
    )


def run_analysis(
    inp,
    *,
    reuse_plastic=None,
    reuse_elastic=None,
    reuse_plastic_cases=None,
    reuse_plastic_bending_cases=None,
    reuse_elastic_cases=None,
    reuse_fatigue=None,
):
    """Run every current named action and enabled calculation."""
    sweep_error = case_analysis.plastic_sweep_error(inp)
    if sweep_error is not None:
        raise engineer_messages.EngineerValidationError(sweep_error)
    heightened_errors = _heightened_crack_control_validation_errors(inp)
    if heightened_errors:
        raise engineer_messages.EngineerValidationError(heightened_errors[0])
    if (inp["section"] is None or inp.get("geometry_error")
            or inp.get("void_error")
            or inp.get("steel_error") or inp.get("material_error")):
        return {}
    shared_results = _section_and_material_results(inp)
    elastic_solver_inputs = _elastic_solver_inputs(inp, shared_results)
    if "plastic_cases" not in inp and "elastic_cases" not in inp:
        result = _run_single_analysis(
            inp,
            reuse_plastic=reuse_plastic,
            reuse_elastic=reuse_elastic,
            elastic_solver_inputs=elastic_solver_inputs,
            shared_results=shared_results,
        )
        if inp.get("clear_spacing_on"):
            result["clear_spacing"] = _clear_spacing_result(inp)
        if inp.get("fatigue_on"):
            result["fatigue"] = (
                reuse_fatigue
                if reuse_fatigue is not None
                else _run_fatigue_or_invalid(inp)
            )
        result.update(shared_results)
        _attach_heightened_crack_control(inp, result)
        result["worked_example_selection"] = (
            presentation.worked_example_selection(inp, result)
        )
        return result

    def _runner(case_inp, *, reuse_plastic=None):
        return _run_single_analysis(
            case_inp,
            reuse_plastic=reuse_plastic,
            elastic_solver_inputs=elastic_solver_inputs,
            shared_results=shared_results,
        )

    result = case_analysis.run_case_tables(
        inp,
        _runner,
        reuse_plastic=reuse_plastic_cases,
        reuse_plastic_bending=reuse_plastic_bending_cases,
        reuse_elastic=reuse_elastic_cases,
    )
    if inp.get("clear_spacing_on"):
        result["clear_spacing"] = _clear_spacing_result(inp)
    if inp.get("fatigue_on"):
        result["fatigue"] = (
            reuse_fatigue
            if reuse_fatigue is not None
            else _run_fatigue_or_invalid(inp)
        )
    result.update(shared_results)
    _attach_heightened_crack_control(inp, result)
    result["worked_example_selection"] = (
        presentation.worked_example_selection(inp, result)
    )
    return result


def _run_uniaxial_capacity_checks(inp, out):
    """Shear, torsion and the combined M-V-T checks for ``inp``; mutates ``out``.

    Runs after the independent plastic and elastic analyses. Reads ``inp`` and the
    already-built ``out["plastic"/"shear"/"torsion"]``; writes ``out["shear"]``,
    ``out["torsion"]`` and ``out["combined"]``. One member strut angle serves shear
    AND torsion (EN 1992-1-1 6.3.2(2)), chosen to minimise the governing utilisation
    -- the sizeable strut-angle pass that used to sit inline in run_analysis.
    """
    # Build the angle-independent contexts in sector.capacity. This function
    # keeps the shared member-angle scan; result_presentation keeps the
    # presentation.
    n_prestress = capacity.prestress_axial(inp)
    n_ed_comp = -inp["P_pl"] + n_prestress
    shear_payload, link_ctx = capacity.build_shear_context(
        inp, n_prestress, n_ed_comp
    )
    if shear_payload is not None:
        out["shear"] = shear_payload
    tors_ctx = capacity.build_torsion_context(inp, n_ed_comp)
    if (
        tors_ctx is not None
        and tors_ctx.get("applicability_blocked") is True
    ):
        out["torsion"] = capacity.unassessed_torsion_applicability(tors_ctx)
        tors_ctx = None

    # ---- Member strut angle (EN 1992-1-1 6.3.2(2)) ----------------------------
    # One strut angle serves shear AND torsion (the same web struts carry both).
    # It is chosen to MINIMISE THE GOVERNING UTILISATION over every reported check
    # that depends on it: the stirrup checks relax with a flatter strut while the
    # crushing checks and the longitudinal-chord demand (MEd + 0.5*VEd*cot*z
    # [+ Ftd,T*z/2] vs MRd) grow, so the optimum is load-dependent -- unlike the
    # old per-action angle, which maximised each resistance alone and therefore sat
    # at the band edge regardless of VEd/MEd/NEd. The chord enters the objective as
    # the SAME capped utilisation the app reports (6.2.3(7)), so the chosen angle
    # can never fail a reported check that another admissible angle would pass.
    # Only LIVE checks constrain the angle -- valid AND loaded: an invalid tube
    # (util = inf at every angle) or a companion with zero load must not drag the
    # angle of a valid check. With no live checks (capacity-only runs) the legacy
    # resistance-maximising angles are kept.
    if link_ctx is not None or tors_ctx is not None:
        v_ed_s = link_ctx["v_ed"] if link_ctx is not None else 0.0
        t_ed_s = tors_ctx["t_ed"] if tors_ctx is not None else 0.0
        retained_vrd_c = (
            link_ctx.get("vrd_c") if link_ctx is not None else None
        )
        concrete_route_applicable = bool(
            retained_vrd_c is not None
            and math.isfinite(float(retained_vrd_c))
            and float(retained_vrd_c) > 0.0
            and v_ed_s <= float(retained_vrd_c)
        )
        torsion_geometry_valid = bool(
            tors_ctx is not None
            and all(tb["valid"] for tb in tors_ctx["subtubes"])
        )
        link_ctx, tors_ctx = capacity.shared_member_angle_contexts(
            inp, link_ctx, tors_ctx
        )
        # Validity probes: a broken links result (no stirrup area / degenerate web)
        # or an invalid tube gives infinite utilisations at EVERY angle, which would
        # otherwise tie the scan and pin the angle at the band edge.
        lk_probe = (link_ctx["build"](link_ctx["cot_min"], link_ctx["cot_min"])
                    if link_ctx is not None else None)
        links_valid = bool(
            lk_probe is not None
            and lk_probe["valid"]
            and (lk_probe.get("vrd_s") or 0.0) > 0.0
            and (lk_probe.get("vrd_max") or 0.0) > 0.0
        )
        tors_valid = bool(
            tors_ctx is not None
            and tors_ctx["closed_links_present"]
            and tors_ctx["asw_over_s_t"] > 0.0
            and torsion_geometry_valid
            and tors_ctx["angle_applicability"]["applicable"] is True
        )
        tors_live = tors_valid and abs(t_ed_s) > 0.0
        shear_live = (
            links_valid
            and v_ed_s > 0.0
            and (
                not concrete_route_applicable
                or tors_live
            )
        )

        # Longitudinal-chord parameters: the shear tension face's applied moment and
        # pure-axis capacity (the B1 machinery), available when the plastic
        # utilisation was computed and the links provide a lever arm.
        pl = out.get("plastic")
        chord_faces = []           # shear-axis chord faces (see below)
        chord_off_faces = []       # off-axis chord faces (both), built when torsion is live
        off_axis_geometry_reason = None
        if links_valid and pl is not None and pl.get("util") is not None:
            l_axis, tlow = link_ctx["axis"], link_ctx["tension_low"]
            model_2023 = bool(link_ctx.get("model_2023"))
            m_origin_signed = (
                inp["Mx_pl"] if l_axis == "x" else inp["My_pl"]
            )
            m_signed = (
                link_ctx["m_ed_2023"]
                if model_2023
                else m_origin_signed
            )
            moment_reference_shift = (
                link_ctx["moment_reference_shift"]
                if model_2023
                else 0.0
            )
            off_signed = inp["My_pl"] if l_axis == "x" else inp["Mx_pl"]
            off_max = pl["max_my"] if l_axis == "x" else pl["max_mx"]
            off_min = pl.get("min_my" if l_axis == "x" else "min_mx", -off_max)
            off_cap = off_max if off_signed >= 0.0 else abs(off_min)
            off_util = (abs(off_signed) / off_cap if off_cap > 0.0
                        else (math.inf if off_signed else 0.0))
            _, scx, scy = capacity.gross_area_centroid(
                inp["outer"], inp["holes"]
            )
            s_centroid = scy if l_axis == "x" else scx
            # Shear-axis chord: MRd is CONDITIONAL on the coexisting off-axis moment
            # (the M-M envelope point carrying off_signed) -- the pure-axis capacity
            # overstates what the chord can lean on under biaxial bending. The
            # flexural shear-TENSION face carries the shear shift dFtd; when torsion
            # is live the OPPOSITE (compression) face also carries the torsion
            # longitudinal share (no shear shift, tensile round the whole tube), so
            # it is built too and the GOVERNING face reported (it can govern on a
            # section with asymmetric steel). The tension face keeps the legacy
            # fallback (pure-axis then sweep extremum) so a failed conditional solve
            # still reports; the torsion-only face is only used on an honest solve.
            if model_2023:
                # Formulae (8.51) and (8.52) require both physical flexural
                # chords. The applied moment sign establishes which face is the
                # flexural tension chord; at zero moment the already selected
                # shear face supplies the otherwise indeterminate designation.
                flexural_tension_low = (
                    True if m_signed > 0.0
                    else False if m_signed < 0.0
                    else tlow
                )
                shear_faces = [
                    (flexural_tension_low, True),
                    (not flexural_tension_low, True),
                ]
            else:
                flexural_tension_low = tlow
                shear_faces = [(tlow, True)]
                if tors_live:
                    shear_faces.append((not tlow, False))
            for f_tlow, gets_shift in shear_faces:
                m_ed_f = combined.chord_applied_moment(m_signed, f_tlow)
                m_rd_f, cond_f = _shear_face_mrd(
                    inp,
                    l_axis,
                    f_tlow,
                    m_off=off_signed,
                    moment_reference_shift=moment_reference_shift,
                )
                if model_2023:
                    # Both 2023 chord equations require the honest face-specific
                    # conditional resistance. A pure-axis substitute cannot close
                    # the required opposite-face check.
                    if not cond_f:
                        continue
                    fitted_section_z = (link_ctx.get("shear_geometry") or {}).get(
                        "fitted_z_mm"
                    )
                    if fitted_section_z is not None:
                        z_f_mm = float(fitted_section_z)
                        z_f_src = "circular_fitted_section"
                    elif f_tlow is tlow:
                        z_f_mm, z_f_src = link_ctx["z_mm"], link_ctx["z_src"]
                    else:
                        _, s_cg = shear.tension_reinforcement(
                            inp["bars"], l_axis, f_tlow, s_centroid
                        )
                        d_f = shear.effective_depth(
                            inp["outer"], l_axis, f_tlow, s_cg
                        )
                        z_f_mm, z_f_src = _shear_lever_arm(
                            inp, l_axis, f_tlow, d_f
                        )
                    if z_f_mm is None or z_f_mm <= 0.0:
                        continue
                elif gets_shift:
                    if not cond_f and m_rd_f <= 0.0:
                        max_m = pl["max_mx"] if l_axis == "x" else pl["max_my"]
                        min_m = pl.get("min_mx" if l_axis == "x" else "min_my", -max_m)
                        m_rd_f = max_m if f_tlow else abs(min_m)
                    if not (m_rd_f > 0.0 or cond_f):
                        continue
                    z_f_mm, z_f_src = link_ctx["z_mm"], link_ctx["z_src"]
                else:
                    if not cond_f:
                        continue
                    _, s_cg = shear.tension_reinforcement(inp["bars"], l_axis,
                                                          f_tlow, s_centroid)
                    d_f = shear.effective_depth(inp["outer"], l_axis, f_tlow, s_cg)
                    z_f_mm, z_f_src = _shear_lever_arm(inp, l_axis, f_tlow, d_f)
                    if z_f_mm is None or z_f_mm <= 0.0:
                        continue
                chord_faces.append(
                    dict(m_ed=m_ed_f, m_rd=m_rd_f, z_m=z_f_mm / 1000.0,
                         z_src=z_f_src, axis=l_axis, tension_low=f_tlow,
                         off_util=off_util, m_off=off_signed, conditional=cond_f,
                         gets_shift=gets_shift,
                         m_ed_signed=m_signed,
                         m_ed_origin_signed=m_origin_signed,
                         moment_reference_shift=moment_reference_shift,
                         flexural_tension_low=flexural_tension_low))
            # Off-axis chord(s): with torsion live, the OTHER axis' tension chords
            # carry their bending tension plus a share of the distributed torsion
            # longitudinal force. The torsion force is tensile round the whole tube
            # perimeter, so it tensions BOTH off-axis faces -- both are built and the
            # governing one reported (on a section with asymmetric steel the face the
            # bending does not tension can still govern under the torsion share).
            # Each face's capacity is conditional on the shear-axis moment, and only
            # the honest conditional capacity is used (a failed solve leaves no
            # defensible MRd, so that face is simply not checked). Single-tube
            # sections only: on a compound section the torsion steel is per sub-tube,
            # so no single tube bounds the off-axis face.
            if (chord_faces and tors_live
                    and not tors_ctx.get("subdivide", False)):
                o_axis = "y" if l_axis == "x" else "x"
                other_component = "vy" if o_axis == "x" else "vx"
                circular_off_axis_geometry = None
                if inp.get("shear_section_form") == shear_inputs.SHEAR_SECTION_CIRCULAR:
                    circular_off_axis_geometry = (
                        shear.resolve_circular_shear_geometry(
                            bw_mm=inp.get(f"shear_{other_component}_bw"),
                            hoop_diameter_mm=inp.get("shear_hoop_diameter"),
                            fitted_z_mm=inp.get(
                                f"shear_{other_component}_fitted_z"
                            ),
                        )
                    )
                    if not circular_off_axis_geometry["valid"]:
                        off_axis_geometry_reason = circular_off_axis_geometry[
                            "reason"
                        ]
                _, ocx, ocy = capacity.gross_area_centroid(
                    inp["outer"], inp["holes"]
                )
                o_centroid = ocy if o_axis == "x" else ocx
                for o_tlow in (True, False):
                    if (
                        circular_off_axis_geometry is not None
                        and not circular_off_axis_geometry["valid"]
                    ):
                        continue
                    m_ed_o = combined.chord_applied_moment(off_signed, o_tlow)
                    m_rd_o, o_cond = _shear_face_mrd(inp, o_axis, o_tlow,
                                                     m_off=m_origin_signed)
                    if not o_cond:
                        continue
                    # Lever arm about the off axis: the exact face-aligned Plastic
                    # internal lever arm, like the reinforced-shear z.
                    if circular_off_axis_geometry is not None:
                        z_o_mm = circular_off_axis_geometry["fitted_z_mm"]
                        z_o_src = "circular_fitted_section"
                    else:
                        _, o_cg = shear.tension_reinforcement(
                            inp["bars"], o_axis, o_tlow, o_centroid
                        )
                        d_o = shear.effective_depth(
                            inp["outer"], o_axis, o_tlow, o_cg
                        )
                        z_o_mm, z_o_src = _shear_lever_arm(
                            inp, o_axis, o_tlow, d_o
                        )
                    if z_o_mm is None or z_o_mm <= 0.0:
                        continue
                    chord_off_faces.append(
                        dict(m_ed=m_ed_o, m_rd=m_rd_o, z_m=z_o_mm / 1000.0,
                             z_src=z_o_src, axis=o_axis, tension_low=o_tlow,
                             m_off=m_origin_signed, conditional=True))

        # The scan band comes from the one physical compression-strut input. A
        # companion that is invalid or carries no load does not join the objective,
        # but shear and torsion no longer have separate ranges to reconcile.
        band = None
        if shear_live and tors_live:
            band = (link_ctx["cot_min"], link_ctx["cot_max"])
        elif shear_live:
            band = (link_ctx["cot_min"], link_ctx["cot_max"])
        elif tors_live:
            band = (tors_ctx["tcot_min"], tors_ctx["tcot_max"])

        @functools.lru_cache(maxsize=4096)
        def _snap(cot):
            """Every strut-angle-dependent resistance at one cot."""
            s = {}
            if link_ctx is not None:
                s["lk"] = link_ctx["build"](cot, cot)
            if tors_ctx is not None and torsion_geometry_valid:
                tk = dict(tors_ctx["_tk"], cot_min=cot, cot_max=cot)
                s["subs"] = tuple(_tube_torsion(tb, te, **tk)
                                  for tb, te in zip(tors_ctx["subtubes"],
                                                    tors_ctx["ted_parts"]))
            return s

        def _ftd_t_at(cot):
            """Torsion longitudinal force on the web chord (kN) at one cot."""
            if not tors_live:
                return 0.0
            web = _snap(cot)["subs"][0]
            return web["asl_req"] * tors_ctx["fyd_long"] / 1000.0

        links_model_2023 = bool(
            link_ctx is not None and link_ctx.get("model_2023")
        )

        def _ftd_v_at(cot):
            """Additional longitudinal shear force on the tension chord (kN)."""
            if not shear_live or concrete_route_applicable:
                return 0.0
            factor = 1.0 if links_model_2023 else 0.5
            return factor * v_ed_s * cot

        utils = []
        objective_labels = []

        def _add_angle_objective(label, evaluator):
            objective_labels.append(label)
            utils.append(evaluator)

        if shear_live:
            _add_angle_objective(
                "shear link yielding",
                lambda c: combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_s"]),
            )
            _add_angle_objective(
                "shear strut crushing",
                lambda c: combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_max"]),
            )
        if tors_live:
            for i in range(len(tors_ctx["subtubes"])):
                _add_angle_objective(
                    f"torsion sub-tube {i + 1}",
                    lambda c, i=i: _snap(c)["subs"][i]["util"],
                )
        if links_valid and tors_live and tors_ctx["asw_over_s_t"] > 0.0:
            # The one closed stirrup carries shear AND the web's torsion share (the
            # transverse check); the web struts crush under both (6.29).
            def _shared_stirrup(c):
                sf = (0.0 if v_ed_s <= link_ctx["vrd_c"]
                      else combined.ratio(v_ed_s, _snap(c)["lk"]["vrd_s"]))
                tf = combined.ratio(_snap(c)["subs"][0]["t_ed"],
                                    _snap(c)["subs"][0]["trd_s"])
                return sf + tf

            def _crush_629(c):
                snap = _snap(c)
                return combined.crushing_interaction(
                    snap["subs"][0]["t_ed"], snap["subs"][0]["trd_max"],
                    v_ed_s, snap["lk"]["vrd_max"])
            _add_angle_objective("shared closed stirrup", _shared_stirrup)
            _add_angle_objective("shared shear-torsion strut", _crush_629)
        for _cf in chord_faces:
            # The objective sees exactly the reported chord utilisation. The 2005
            # shear shift is capped per 6.2.3(7) only by an engineer-entered
            # MEd,max; the 2023 NVd force from (8.50) is not capped because Sector
            # does not establish the support/load-specific condition in (8.53).
            if _cf["m_rd"] > 0.0 and (shear_live or tors_live):
                face = "negative" if _cf["tension_low"] else "positive"
                if links_model_2023:
                    evaluator = lambda c, f=_cf: combined.longitudinal_chord_check_2023(
                        f["m_ed_signed"], f["m_rd"], _ftd_v_at(c),
                        _ftd_t_at(c), f["z_m"],
                        tension_low=f["tension_low"],
                        flexural_tension_low=f["flexural_tension_low"],
                        n_ed=inp["P_pl"],
                    )["util"]
                else:
                    evaluator = lambda c, f=_cf: combined.longitudinal_check(
                        f["m_ed"], f["m_rd"],
                        _ftd_v_at(c) if f["gets_shift"] else 0.0,
                        _ftd_t_at(c), f["z_m"],
                        m_ed_max=capacity.chord_med_max(
                            inp, f["axis"], f["tension_low"]
                        ),
                    )["util"]
                _add_angle_objective(
                    f"{_cf['axis']}-axis {face} longitudinal chord",
                    evaluator,
                )
        for _ocf in chord_off_faces:
            # Each off-axis face depends on the angle only through Ftd,T; both join
            # the objective (m_rd > 0) so the optimiser and the reported governing
            # verdict agree. A zero-capacity face is kept out (util = inf at every
            # angle would tie the scan).
            if _ocf["m_rd"] > 0.0 and tors_live:
                face = "negative" if _ocf["tension_low"] else "positive"
                _add_angle_objective(
                    f"{_ocf['axis']}-axis {face} off-axis chord",
                    lambda c, f=_ocf: combined.longitudinal_check(
                        f["m_ed"], f["m_rd"], 0.0, _ftd_t_at(c), f["z_m"]
                    )["util"],
                )
        # The a_l = d tension chord of the concrete shear route (6.2.2(5) and
        # 9.2.1.3(2)) also carries Ftd,T z/2 when torsion is live (6.3.2(3)), so
        # it depends on the angle. It joins the objective with the same operands,
        # lever arm and MEd,max limit as capacity.concrete_route_chord (TB-02).
        # Without the plastic result the chord is NOT ASSESSED, so it stays out.
        if (
            concrete_route_applicable and tors_live and links_valid
            and capacity.concrete_route_chord_plastic_available(pl)
        ):
            concrete_chord = capacity.concrete_route_chord_operands(
                inp, out.get("shear")
            )
            concrete_mrd, concrete_exact = (
                capacity.concrete_route_chord_face_mrd(inp, concrete_chord)
                if concrete_chord is not None
                else (0.0, False)
            )
            if concrete_exact and concrete_mrd > 0.0:
                _add_angle_objective(
                    "concrete-route a_l = d tension chord",
                    lambda c, f=concrete_chord, m_rd=concrete_mrd,
                    z=link_ctx["z_mm"] / 1000.0: (
                        capacity.concrete_route_chord_demand(
                            f, m_rd, ftd_t=_ftd_t_at(c), z=z
                        )["util"]
                    ),
                )
        cot_star = None
        member_angle_selection = None
        if band is not None and utils:
            angle_result = combined.governing_strut_result(
                utils, band[0], band[1]
            )
            cot_star = angle_result.cot
            member_angle_selection = dataclasses.asdict(angle_result)
            member_angle_selection["objective_labels"] = tuple(objective_labels)
            member_angle_selection["governing_objectives"] = tuple(
                objective_labels[index]
                for index in angle_result.governing_component_indices
            )
        # One label for how the member angle was chosen, reused by every payload:
        #   utilisation -> a live load drove the minimax choice (cot_star found);
        #   resistance  -> no live transverse load, so the capacity result uses its
        #                  resistance-optimum angle (nothing to optimise).
        theta_mode_str = (
            "utilisation" if cot_star is not None else "resistance"
        )

        # ---- torsion payload at the member angle (or the shared band when no load
        # drives the choice) ----
        if tors_ctx is not None:
            t_ed = tors_ctx["t_ed"]
            subdivide = tors_ctx["subdivide"]
            tk = tors_ctx["_tk"]
            # Pin to the member angle only when torsion is a LIVE participant. A dead
            # companion (TEd = 0) does not join the shared-angle objective and remains
            # at its resistance optimum within the same user-entered range.
            if cot_star is not None and tors_live:
                tk = dict(tk, cot_min=cot_star, cot_max=cot_star)
            if torsion_geometry_valid:
                sub_res = [
                    _tube_torsion(tb, te, **tk)
                    for tb, te in zip(
                        tors_ctx["subtubes"], tors_ctx["ted_parts"]
                    )
                ]
            else:
                sub_res = [
                    capacity.unassessed_tube_torsion(
                        tb,
                        te,
                        closed_links_present=tors_ctx["closed_links_present"],
                    )
                    for tb, te in zip(
                        tors_ctx["subtubes"], tors_ctx["ted_parts"]
                    )
                ]
            governing_sub = None
            if subdivide:
                for r, c, dims in zip(sub_res, tors_ctx["consts"],
                                      tors_ctx["sub_dims"]):
                    r["stiffness"] = c
                    (r["x_mm"], r["y_mm"],
                     r["b_mm"], r["h_mm"]) = dims
                tube_valid = all(r["tube_valid"] for r in sub_res)
                transverse_resistance_assessed = all(
                    r["transverse_resistance_assessed"] for r in sub_res
                )
                valid = bool(tube_valid and transverse_resistance_assessed)
                trd = sum(r["trd"] for r in sub_res) if valid else None
                asl_req = (
                    sum(r["asl_req"] for r in sub_res)
                    if (
                        tube_valid
                        and tors_ctx["angle_applicability"]["applicable"] is True
                    )
                    else None
                )
                primary = sub_res[0]
                if not tube_valid:
                    primary = next(
                        result for result in sub_res if not result["tube_valid"]
                    )
                tube_main = primary["tube"]
                # Governing = the WORST sub-tube (each carries its stiffness share).
                if valid:
                    governing_sub = max(
                        range(len(sub_res)),
                        key=lambda i: sub_res[i]["util"],
                    )
                    util_t = sub_res[governing_sub]["util"]
                else:
                    governing_sub = None
                    util_t = None
            else:
                primary = sub_res[0]
                sub_res = None
                trd, asl_req = primary["trd"], primary["asl_req"]
                tube_main = tors_ctx["tube"]
                tube_valid = primary["tube_valid"]
                transverse_resistance_assessed = primary[
                    "transverse_resistance_assessed"
                ]
                valid = bool(tube_valid and transverse_resistance_assessed)
                util_t = primary["util"] if valid else None
            assessment_reason = (
                None
                if transverse_resistance_assessed
                else primary["assessment_reason"]
            )
            reason = (
                tube_main.get("reason")
                if not tube_valid
                else assessment_reason
            )
            required_by_tube = (
                tuple(item["asl_req"] for item in (sub_res or [primary]))
                if (
                    tube_valid
                    and tors_ctx["angle_applicability"]["applicable"] is True
                )
                else ()
            )
            longitudinal_assessment = (
                capacity.torsion_longitudinal_assessment(
                    inp,
                    required_by_tube,
                    resistance_assessed=valid,
                )
            )
            resistance_status = (
                "NOT ASSESSED"
                if not valid or util_t is None
                else "PASS"
                if math.isfinite(util_t) and util_t <= 1.0
                else "FAIL"
            )
            overall_status = capacity.aggregate_assessment_status((
                resistance_status,
                longitudinal_assessment["status"],
            ))
            overall_ok = (
                True
                if overall_status == "PASS"
                else False
                if overall_status == "FAIL"
                else None
            )
            overall_reason = (
                reason
                if not valid
                else capacity.TORSION_RESISTANCE_EXCEEDED
                if resistance_status == "FAIL"
                else longitudinal_assessment["reason"]
            )
            tcode = tors_ctx["tcode"]
            tcot_min, tcot_max = tors_ctx["tcot_min"], tors_ctx["tcot_max"]
            angle_limits = tors_ctx["angle_limits"]
            angle_applicability = tors_ctx["angle_applicability"]
            lo_t = angle_limits["minimum"]
            hi_t = angle_limits["maximum"]
            torsion_out_of_limits = bool(
                angle_applicability.get("active", True)
                and angle_applicability["applicable"] is False
            )
            out["torsion"] = dict(
                tube=tube_main, trd_s=primary["trd_s"], trd_max=primary["trd_max"],
                trd=trd, trd_c=primary["trd_c"], cot=primary["cot"],
                theta_deg=primary["theta_deg"], util=util_t, asl_req=asl_req,
                t_ed=t_ed, t_ed_signed=tors_ctx["t_ed_signed"],
                applicability=tors_ctx["applicability"],
                applicability_blocked=False,
                fcd=tors_ctx["fcd"], fywd=tors_ctx["fywd_t"],
                fyd_long=tors_ctx["fyd_long"], nu=primary["nu"],
                alpha_cw=tors_ctx["alpha_cw"], fctd=tors_ctx["fctd"],
                fctk_005=tors_ctx["fctk_005"],
                gamma_c=tors_ctx["gamma_c"], gamma_ct=tors_ctx["gamma_ct"],
                gamma_s=tors_ctx["gamma_s"],
                nu_v_detailing=tors_ctx["nu_detail_applied"],
                sigma_cp=tors_ctx["sigma_cp"], n_prestress=n_prestress,
                asw_t=tors_ctx["asw_t"], asw_over_s=tors_ctx["asw_over_s_t"],
                dia=inp["shear_link_dia"], s=inp["shear_link_s"], cot_min=tcot_min,
                cot_max=tcot_max, method=inp["torsion_method"],
                governs=primary["governs"], valid=valid,
                tube_valid=tube_valid,
                closed_links_present=tors_ctx["closed_links_present"],
                transverse_resistance_assessed=(
                    transverse_resistance_assessed
                ),
                # Compatibility alias for retained schema-27 result consumers.
                full_resistance_assessed=transverse_resistance_assessed,
                assessment_reason=assessment_reason,
                resistance_status=resistance_status,
                longitudinal_assessment=longitudinal_assessment,
                assessment_status=overall_status,
                assessment_ok=overall_ok,
                overall_reason=overall_reason,
                resistance_selection=primary["resistance_selection"],
                reason=reason, cot_limit_lo=lo_t, cot_limit_hi=hi_t,
                out_of_limits=torsion_out_of_limits,
                angle_limits=angle_limits,
                angle_applicability=angle_applicability,
                subdivided=subdivide, subtubes=sub_res, primary=primary,
                governing_sub=governing_sub,
                compound_detected=tors_ctx["compound_detected"],
                subdivision_requested=tors_ctx["subdivision_requested"],
                subdivision_valid=tors_ctx["subdivision_valid"],
                subdivision_reason=tors_ctx["subdivision_reason"],
                theta_mode=(
                    theta_mode_str
                    if transverse_resistance_assessed and tors_live
                    else (
                        "resistance"
                        if transverse_resistance_assessed
                        else "transparency"
                    )
                ),
                torque_distribution=tors_ctx["torque_distribution"],
                member_angle_selection=member_angle_selection)

        # ---- links payload at the member angle ----
        if link_ctx is not None:
            v_ed = link_ctx["v_ed"]
            # Pin to the member angle only when shear is a LIVE participant. A dead
            # companion (VEd = 0) remains at its resistance optimum within the same
            # user-entered range.
            if cot_star is not None and shear_live:
                lk = link_ctx["build"](cot_star, cot_star)
            else:
                lk = link_ctx["build"](link_ctx["cot_min"], link_ctx["cot_max"])
            util_l = (
                v_ed / lk["vrd"]
                if lk.get("valid") and (lk.get("vrd") or 0.0) > 0.0
                else None
            )
            concrete_route_selected = bool(
                link_ctx.get("vrd_c") is not None
                and v_ed <= float(link_ctx["vrd_c"])
            )
            # Extra longitudinal force from shear: 2005 delta_Ftd = 0.5 VEd cot
            # theta; 2023 NVd = |VEd| cot theta (8.50).
            longitudinal_shear_force = (
                (1.0 if link_ctx.get("model_2023") else 0.5)
                * v_ed * lk["cot"]
                if lk["valid"] and shear_live and not concrete_route_selected
                else 0.0
                if lk["valid"]
                else None
            )
            delta_ftd = (
                None if link_ctx.get("model_2023") or not lk["valid"]
                else longitudinal_shear_force
            )
            angle_limits = link_ctx["angle_limits"]
            lo, hi = angle_limits["minimum"], angle_limits["maximum"]
            links_out_of_limits = bool(
                link_ctx["angle_applicability"].get("active", True)
                and link_ctx["angle_applicability"]["applicable"] is False
            )
            # The reported longitudinal-chord check (capped per 6.2.3(7)), on the
            # shear tension face; the torsion term is the web tube's share (zero
            # without torsion). Shown in the Shear view and reused by the combined
            # view, so both present the same numbers.
            lchk = None
            ochk = None
            lchecks = []
            ochecks = []
            off_not_evaluated = None
            if chord_faces and lk["valid"]:
                # The torsion term comes from the BUILT torsion payload (the web
                # tube's Asl at its final angle).
                p_web = out.get("torsion", {}).get("primary")
                ftd_t_star = (p_web["asl_req"] * tors_ctx["fyd_long"] / 1000.0
                              if (p_web is not None and tors_live) else 0.0)
                # Why no off-axis chord check accompanies this one (so the views and
                # report can disclose it rather than silently drop the torsion share
                # on the off-axis face, as the pre-v0.78 warning always did):
                #   subdivided -> a compound section's torsion steel is per sub-tube;
                #   not_solved -> single tube, but at least one chord face that
                #                 carries the torsion share could not be built (its
                #                 conditional solve failed or it has no tension steel).
                # Under torsion the torsion tensions all four faces (both shear faces
                # and both off-axis faces), so ALL four are required; if fewer were
                # built the coverage is incomplete and a partly-checked governing
                # chord must not read as a clean OK -- disclose it.
                if tors_live and tors_ctx.get("subdivide", False):
                    off_not_evaluated = "subdivided"
                elif tors_live and off_axis_geometry_reason is not None:
                    off_not_evaluated = "circular_geometry"
                elif tors_live and len(chord_faces) + len(chord_off_faces) < 4:
                    off_not_evaluated = "not_solved"
                else:
                    off_not_evaluated = None
                # Report the GOVERNING shear-axis face. The 2023 route retains both
                # flexural chords under Formulae (8.51) and (8.52); the 2005-family
                # route retains its existing tension-face shear shift.
                for _cf in chord_faces:
                    if links_model_2023:
                        fchk = combined.longitudinal_chord_check_2023(
                            _cf["m_ed_signed"], _cf["m_rd"],
                            longitudinal_shear_force, ftd_t_star, _cf["z_m"],
                            tension_low=_cf["tension_low"],
                            flexural_tension_low=_cf["flexural_tension_low"],
                            n_ed=inp["P_pl"],
                        )
                    else:
                        fchk = combined.longitudinal_check(
                            _cf["m_ed"], _cf["m_rd"],
                            longitudinal_shear_force if _cf["gets_shift"] else 0.0,
                            ftd_t_star, _cf["z_m"],
                            m_ed_max=capacity.chord_med_max(
                                inp, _cf["axis"], _cf["tension_low"]
                            ),
                        )
                    fchk.update(valid=True, role="shear_axis",
                                axis=_cf["axis"],
                                tension_low=_cf["tension_low"],
                                off_util=_cf["off_util"],
                                biaxial=bool(_cf["off_util"] > 0.05),
                                m_off=_cf["m_off"],
                                conditional=_cf["conditional"],
                                has_torsion=tors_live,
                                gets_shift=_cf["gets_shift"],
                                m_ed_origin_signed=_cf[
                                    "m_ed_origin_signed"
                                ],
                                moment_reference_shift=_cf[
                                    "moment_reference_shift"
                                ],
                                off_not_evaluated=off_not_evaluated,
                                theta_mode=theta_mode_str,
                                z_src=_cf.get("z_src"))
                    lchecks.append(fchk)
                    if lchk is None or fchk["util"] > lchk["util"]:
                        lchk = fchk
                # The off-axis chord: bending tension about the OTHER axis plus its
                # share of the torsion longitudinal force (no shear shift -- the
                # shear acts in the shear plane), against the capacity conditional on
                # the shear-axis moment. Both off-axis faces carry the torsion share;
                # report the GOVERNING (highest utilisation) at the member angle.
                for _ocf in chord_off_faces:
                    fchk = combined.longitudinal_check(
                        _ocf["m_ed"], _ocf["m_rd"], 0.0, ftd_t_star, _ocf["z_m"])
                    fchk.update(valid=True, role="off_axis",
                                axis=_ocf["axis"],
                                tension_low=_ocf["tension_low"],
                                m_off=_ocf["m_off"],
                                conditional=_ocf["conditional"],
                                z_src=_ocf.get("z_src"),
                                theta_mode=theta_mode_str)
                    ochecks.append(fchk)
                    if ochk is None or fchk["util"] > ochk["util"]:
                        ochk = fchk
            required_chords = lchecks + ochecks
            governing_longitudinal = (
                max(required_chords, key=lambda item: item["util"])
                if required_chords else None
            )
            longitudinal_fallback = next(
                (
                    item for item in required_chords
                    if not item.get("conditional", True)
                ),
                None,
            )
            try:
                z_input_basis = capacity.shear_link_arm_publication_basis(
                    inp,
                    link_ctx["axis"],
                    link_ctx["tension_low"],
                    link_ctx["z_mm"],
                )
            except (capacity.CapacityInputError, TypeError, ValueError, OverflowError):
                z_input_basis = None
            links_payload = dict(
                res=lk, util=util_l, asw=link_ctx["asw"],
                asw_over_s=link_ctx["asw_over_s"],
                effective_asw_over_s=link_ctx["effective_asw_over_s"],
                asw_factor=link_ctx["asw_factor"],
                shear_geometry=link_ctx["shear_geometry"],
                legs=link_ctx["link_legs"], dia=inp["shear_link_dia"],
                s=inp["shear_link_s"], fywk=inp["shear_fywk"],
                cot_min=link_ctx["cot_min"], cot_max=link_ctx["cot_max"],
                delta_ftd=delta_ftd,
                longitudinal_shear_force=longitudinal_shear_force,
                longitudinal_shear_symbol=(
                    "NVd" if link_ctx.get("model_2023") else "delta_Ftd"
                ),
                longitudinal_shear_clause=(
                    "8.2.3(8), Formula (8.50)"
                    if link_ctx.get("model_2023")
                    else "6.2.3(7), Formula (6.18)"
                ),
                cot_limit_lo=lo, cot_limit_hi=hi,
                angle_limits=angle_limits,
                angle_applicability=link_ctx["angle_applicability"],
                model_2023=link_ctx.get("model_2023", False),
                m_ed_2023=link_ctx.get("m_ed_2023"),
                moment_reference_shift=link_ctx.get(
                    "moment_reference_shift",
                    0.0,
                ),
                z_source=link_ctx["z_src"],
                z_component=link_ctx["z_component"],
                z_source_angle_deg=link_ctx["z_source_angle_deg"],
                z_source_case=link_ctx["z_source_case"],
                z_source_axial_kn=link_ctx["z_source_axial_kn"],
                z_input_basis=z_input_basis,
                assessment_reason=(
                    link_ctx["z_src"]
                    if link_ctx.get("z_mm") is None
                    else lk.get("reason")
                ),
                out_of_limits=links_out_of_limits,
                required=(
                    bool(v_ed > link_ctx["vrd_c"])
                    if link_ctx.get("vrd_c") is not None
                    else None
                ),
                chord=lchk,
                chord_off=ochk,
                chord_candidates=required_chords,
                governing_longitudinal=governing_longitudinal,
                longitudinal_fallback=longitudinal_fallback,
                longitudinal_all_conditional=(
                    bool(required_chords) and longitudinal_fallback is None
                ),
                theta_mode=(theta_mode_str if shear_live else "resistance"),
                member_angle_selection=member_angle_selection,
            )
            longitudinal_assessment = capacity.longitudinal_chord_assessment(
                links_payload,
                shear_axis=link_ctx["axis"],
                shear_tension_low=link_ctx["tension_low"],
                shear_live=shear_live,
                torsion_live=tors_live,
                torsion_subdivided=bool(
                    tors_ctx is not None and tors_ctx.get("subdivide", False)
                ),
            )
            if (
                off_axis_geometry_reason is not None
                and longitudinal_assessment["status"] == "NOT ASSESSED"
            ):
                longitudinal_assessment = dict(
                    longitudinal_assessment,
                    reason=off_axis_geometry_reason,
                )
            if (
                longitudinal_assessment["status"] == "NOT APPLICABLE"
                and longitudinal_assessment.get("reason")
                == "no_longitudinal_chord_action"
            ):
                links_payload.update(
                    chord=None,
                    chord_off=None,
                    chord_candidates=[],
                    governing_longitudinal=None,
                    longitudinal_fallback=None,
                    longitudinal_all_conditional=False,
                )
            links_payload["longitudinal_assessment"] = longitudinal_assessment
            out["shear"].update(links=links_payload)

        # ---- checks that pair shear and torsion, at the member angle ----
        if tors_ctx is not None:
            t_ed = tors_ctx["t_ed"]
            primary = out["torsion"]["primary"]
            # Minimum-reinforcement screen (EN 1992-1-1 6.3.2(5), Eq 6.31).
            # Applicability is decided here and retained with the operands so no
            # presentation surface can infer a favourable verdict from geometry
            # alone.
            sh_ms = out.get("shear")
            out["torsion"]["min_reinf"] = (
                capacity.minimum_reinforcement_screen_from_context(
                    inp,
                    sh_ms,
                    tors_ctx,
                    primary,
                )
            )
            # Combined shear+torsion concrete crushing (6.29) at the member angle,
            # pairing the shear with the PRIMARY (web) tube's torsion share.
            sh_links = out.get("shear", {}).get("links")
            if (
                sh_links is not None
                and sh_links["res"]["valid"]
                and primary["tube"]["valid"]
                and primary["transverse_resistance_assessed"]
            ):
                # The member angle when a load drives it; otherwise the
                # least-conservative angle (cot = 1 clamped to the shared band).
                pl_lo, pl_hi = link_ctx["cot_min"], link_ctx["cot_max"]
                cot_c = (
                    cot_star
                    if cot_star is not None
                    else min(max(1.0, pl_lo), pl_hi)
                )
                interaction = capacity.shear_torsion_crushing_from_context(
                    sh_ms,
                    link_ctx,
                    tors_ctx,
                    cot_c,
                )
                if interaction is not None:
                    out["torsion"]["interaction"] = interaction

    shear_result = out.get("shear")
    if shear_result is not None:
        nominal = capacity.select_nominal_shear_resistance(
            shear_result,
            links_selected=inp.get("shear_links") is True,
        )
        nominal_payload = dataclasses.asdict(nominal)
        assessment_status = nominal.status
        links_payload = shear_result.get("links") or {}
        chord_assessment = links_payload.get("longitudinal_assessment")
        if isinstance(chord_assessment, dict):
            chord_status = str(
                chord_assessment.get("status") or "NOT ASSESSED"
            ).upper()
            if chord_status != "NOT APPLICABLE":
                assessment_status = capacity.aggregate_assessment_status((
                    nominal.status,
                    chord_status,
                ))
        concrete_chord = capacity.concrete_route_chord(
            inp, out.get("plastic"), shear_result, nominal,
            torsion_result=out.get("torsion"),
        )
        shear_result["concrete_chord"] = concrete_chord
        if concrete_chord is not None:
            assessment_status = capacity.aggregate_assessment_status((
                assessment_status,
                concrete_chord["status"],
            ))
        shear_result.update(
            nominal_resistance=nominal_payload,
            resistance_status=nominal.status,
            assessment_status=assessment_status,
            assessment_ok=(
                True
                if assessment_status == "PASS"
                else False
                if assessment_status == "FAIL"
                else None
            ),
        )
    capacity.finalize_combined(inp, out)


def _directional_shear_status(inp, shear_out):
    """Acceptance state for one directional shear calculation."""
    nominal = (shear_out or {}).get("nominal_resistance")
    if not isinstance(nominal, dict):
        nominal = dataclasses.asdict(capacity.select_nominal_shear_resistance(
            shear_out,
            links_selected=inp.get("shear_links") is True,
        ))
    status = str(nominal.get("status") or "INVALID").upper()
    if nominal.get("valid") is not True:
        return status if status in {"NOT ASSESSED", "INVALID"} else "INVALID"
    util = nominal.get("utilisation")
    if util is None or not math.isfinite(float(util)):
        return "INVALID"
    retained_status = str(shear_out.get("assessment_status") or "").upper()
    if retained_status in {"PASS", "FAIL", "NOT ASSESSED"}:
        return retained_status
    return status


def _shear_candidate_assessment(inp, candidate_out):
    """Return the status and shear-only metric for one candidate face."""
    shear_out = candidate_out.get("shear") or {}
    status = _directional_shear_status(inp, shear_out)
    nominal = shear_out.get("nominal_resistance")
    if not isinstance(nominal, dict):
        nominal = dataclasses.asdict(capacity.select_nominal_shear_resistance(
            shear_out,
            links_selected=inp.get("shear_links") is True,
        ))
    metric = float(nominal.get("utilisation") or 0.0)
    return status, (math.inf if status == "INVALID" else metric)


def _minimum_reinf_assessment(torsion_out):
    """Return an ordering state for the face-specific Eq. 6.31 screen."""
    if torsion_out is None:
        return "NOT RUN", 0.0
    check = (torsion_out or {}).get("min_reinf") or {}
    if not check.get("applicable"):
        return presentation.minimum_reinforcement_screen_status(check), 0.0
    value = check.get("value")
    if value is None or not math.isfinite(float(value)):
        return "INVALID", math.inf
    return ("PASS" if check.get("ok") else "FAIL"), float(value)


def _candidate_domain_cot(candidate, domain):
    """Strut cot(theta) for one candidate/domain, where the domain has an angle."""
    results = candidate.get("results") or {}
    if domain == "shear":
        return (((results.get("shear") or {}).get("links") or {}).get("res") or {}).get(
            "cot"
        )
    if domain == "vt":
        return ((results.get("torsion") or {}).get("interaction") or {}).get("cot")
    if domain == "combined":
        combined_out = results.get("combined") or {}
        transverse = combined_out.get("transverse") or {}
        if transverse.get("valid") and transverse.get("cot") is not None:
            return transverse.get("cot")
        return (combined_out.get("crushing") or {}).get("cot")
    return None


def _governing_domain(candidate, status, metric, domain):
    """Auditable face/angle/status record for an independently governed domain."""
    return {
        "face": "negative" if candidate["tension_low"] else "positive",
        "cot": _candidate_domain_cot(candidate, domain),
        "status": status,
        "util": metric,
    }


def _torsion_interaction_assessment(torsion_out):
    """Return the result state of one face-specific V+T crushing screen."""
    if torsion_out is None:
        return "NOT RUN", 0.0
    torsion_out = torsion_out or {}
    interaction = torsion_out.get("interaction") or {}
    value = interaction.get("value")
    status = presentation.interaction_assessment_status(interaction)
    metric = float(value or 0.0)
    if not math.isfinite(metric):
        metric = math.inf
    return status, metric


def _combined_direction_assessment(inp, candidate_out):
    """Return the conservative status and utilisation for one V+T screen.

    Reuse the same result rows as the application summary so the directional
    results view and report cannot disagree about an invalid or failed sub-check.
    """
    # These are raw face results on the translated magnitude/axis contract.
    # Signed component authority belongs to the parent assembled afterwards.
    publication_input = dict(inp)
    for key in ("shear_Vx", "shear_Vy", "shear_components"):
        publication_input.pop(key, None)
    rows = [
        row for row in presentation.result_summary_rows(publication_input, candidate_out)
        if row.get("view") == "M-V-T Combined"
    ]
    status = presentation.overall_summary_status(rows)
    utilisations = [
        float(row["util"])
        for row in rows
        if row.get("util") is not None
    ]
    return status, max(utilisations, default=0.0)


def _direction_input(inp, component, tension_low, spec=None):
    """Translate one v7 component/face onto the verified uniaxial v6 contract."""
    spec = spec or capacity.shear_direction_specs(inp)[component]
    translated = dict(inp)
    translated.update(
        shear_axis=spec["axis"],
        shear_tension=bool(tension_low),
        shear_V=spec["v_ed"],
        shear_bw=spec["bw"],
        shear_link_legs=spec["legs"],
    )
    return translated


def _run_capacity_checks(inp, out):
    """Run directional Vx/Vy checks without claiming a biaxial interaction law.

    Each direction is passed independently through the existing verified shear and
    shear-torsion implementation. If both components are present, both directional
    results are retained with no aggregate cross-direction verdict.
    """
    prepared_inp = inp
    directional_contract = (
        "shear_Vx" in prepared_inp
        or "shear_Vy" in prepared_inp
        or "shear_components" in prepared_inp
    )
    if not directional_contract:
        _run_uniaxial_capacity_checks(prepared_inp, out)
        return

    specs = capacity.shear_direction_specs(prepared_inp)
    active = [component for component in ("vx", "vy")
              if prepared_inp.get("shear_on") and specs[component]["v_ed"] > 0.0]
    if not active:
        base = dict(prepared_inp, shear_on=False, combined_on=False)
        _run_uniaxial_capacity_checks(base, out)
        return

    directions = {}
    retained_nm_action_alone = None
    for component in active:
        spec = specs[component]
        face_key = "shear_face_x" if component == "vx" else "shear_face_y"
        faces = capacity.shear_face_candidates(spec["face"], spec["moment"])
        candidates = []
        for tension_low in faces:
            candidate_inp = _direction_input(
                prepared_inp, component, tension_low, spec
            )
            if retained_nm_action_alone is not None:
                candidate_inp["_dkna_nm_action_alone"] = (
                    retained_nm_action_alone
                )
            candidate_out = {
                key: value for key, value in out.items()
                if key in {"plastic", "elastic"}
            }
            _run_uniaxial_capacity_checks(candidate_inp, candidate_out)
            action_alone = (
                (candidate_out.get("combined") or {}).get("action_alone")
                or {}
            )
            if (
                retained_nm_action_alone is None
                and isinstance(action_alone.get("n"), dict)
                and isinstance(action_alone.get("m"), dict)
            ):
                retained_nm_action_alone = {
                    "n": action_alone["n"],
                    "m": action_alone["m"],
                }
            shear_status, shear_metric = _shear_candidate_assessment(
                candidate_inp, candidate_out
            )
            torsion_status, torsion_metric = _torsion_interaction_assessment(
                candidate_out.get("torsion")
            )
            min_reinf_status, min_reinf_metric = _minimum_reinf_assessment(
                candidate_out.get("torsion")
            )
            if candidate_out.get("combined") is not None:
                combined_status, combined_metric = _combined_direction_assessment(
                    candidate_inp, candidate_out
                )
            else:
                combined_status, combined_metric = "NOT RUN", 0.0
            candidates.append({
                "tension_low": bool(tension_low),
                "input": candidate_inp,
                "results": candidate_out,
                "shear_status": shear_status,
                "shear_metric": shear_metric,
                "torsion_status": torsion_status,
                "torsion_metric": torsion_metric,
                "min_reinf_status": min_reinf_status,
                "min_reinf_metric": min_reinf_metric,
                "combined_status": combined_status,
                "combined_metric": combined_metric,
            })
        shear_governing = max(
            candidates,
            key=lambda candidate: capacity.assessment_key(
                candidate["shear_status"], candidate["shear_metric"]
            ),
        )
        torsion_governing = max(
            candidates,
            key=lambda candidate: capacity.assessment_key(
                candidate["torsion_status"], candidate["torsion_metric"]
            ),
        )
        min_reinf_governing = max(
            candidates,
            key=lambda candidate: capacity.assessment_key(
                candidate["min_reinf_status"], candidate["min_reinf_metric"]
            ),
        )
        combined_governing = max(
            candidates,
            key=lambda candidate: capacity.assessment_key(
                candidate["combined_status"], candidate["combined_metric"]
            ),
        )
        shear_out = dict(shear_governing["results"]["shear"])
        shear_status = capacity.aggregate_assessment_status(
            candidate["shear_status"] for candidate in candidates
        )
        torsion_status = capacity.aggregate_assessment_status(
            candidate["torsion_status"] for candidate in candidates
        )
        min_reinf_status = capacity.aggregate_assessment_status(
            candidate["min_reinf_status"] for candidate in candidates
        )
        combined_status = capacity.aggregate_assessment_status(
            candidate["combined_status"] for candidate in candidates
        )
        governing_domains = {
            "shear": _governing_domain(
                shear_governing,
                shear_status,
                shear_governing["shear_metric"],
                "shear",
            )
        }
        if any(
            ((candidate["results"].get("torsion") or {}).get("interaction"))
            is not None
            for candidate in candidates
        ):
            governing_domains["vt"] = _governing_domain(
                torsion_governing,
                torsion_status,
                torsion_governing["torsion_metric"],
                "vt",
            )
        if any(
            ((candidate["results"].get("torsion") or {}).get("min_reinf"))
            is not None
            for candidate in candidates
        ):
            governing_domains["minimum_reinforcement"] = _governing_domain(
                min_reinf_governing,
                min_reinf_status,
                min_reinf_governing["min_reinf_metric"],
                "minimum_reinforcement",
            )
        if any(candidate["results"].get("combined") is not None
               for candidate in candidates):
            governing_domains["combined"] = _governing_domain(
                combined_governing,
                combined_status,
                combined_governing["combined_metric"],
                "combined",
            )
        shear_out.update(
            face_mode=str(inp.get(face_key, "auto")),
            both_faces_evaluated=len(candidates) == 2,
            governing_face=(
                "negative" if shear_governing["tension_low"] else "positive"
            ),
            associated_moment=spec["moment"],
            associated_moment_origin=spec["moment_origin"],
            signed_v_ed=spec["signed_v_ed"],
            status=shear_status,
            governing_domains=governing_domains,
            face_candidates=[{
                "tension_low": candidate["tension_low"],
                "shear_status": candidate["shear_status"],
                "shear_metric": candidate["shear_metric"],
                "torsion_status": candidate["torsion_status"],
                "torsion_metric": candidate["torsion_metric"],
                "min_reinf_status": candidate["min_reinf_status"],
                "min_reinf_metric": candidate["min_reinf_metric"],
                "combined_status": candidate["combined_status"],
                "combined_metric": candidate["combined_metric"],
                "shear": candidate["results"].get("shear"),
                "torsion": candidate["results"].get("torsion"),
                "combined": candidate["results"].get("combined"),
            } for candidate in candidates],
        )
        combined_out = combined_governing["results"].get("combined")
        if combined_out is not None:
            combined_out = dict(
                combined_out,
                component=component,
                governing_face=(
                    "negative" if combined_governing["tension_low"] else "positive"
                ),
                governing_cot=_candidate_domain_cot(
                    combined_governing, "combined"
                ),
            )
        torsion_out = torsion_governing["results"].get("torsion")
        if torsion_out is not None:
            vt_domain = governing_domains.get("vt") or {}
            torsion_out = dict(
                torsion_out,
                directional_interaction_status=capacity.aggregate_assessment_status(
                    candidate["torsion_status"] for candidate in candidates
                ),
                directional_governing_face=vt_domain.get("face"),
                directional_governing_cot=vt_domain.get("cot"),
            )
            selected_min_reinf = (
                (min_reinf_governing["results"].get("torsion") or {}).get(
                    "min_reinf"
                )
            )
            if selected_min_reinf is not None:
                torsion_out["min_reinf"] = dict(
                    selected_min_reinf,
                    directional_status=min_reinf_status,
                    governing_face=(
                        "negative"
                        if min_reinf_governing["tension_low"]
                        else "positive"
                    ),
                )
                torsion_out["directional_min_reinf_status"] = min_reinf_status
                torsion_out["directional_min_reinf_governing_face"] = (
                    "negative"
                    if min_reinf_governing["tension_low"]
                    else "positive"
                )
        directions[component] = {
            "component": component,
            "shear": shear_out,
            "torsion": torsion_out,
            "combined": combined_out,
            "status": shear_out["status"],
            "metric": shear_governing["shear_metric"],
        }

    if len(active) == 1:
        chosen = directions[active[0]]
        out["shear"] = chosen["shear"]
        if chosen["torsion"] is not None:
            out["torsion"] = chosen["torsion"]
        if chosen["combined"] is not None:
            out["combined"] = chosen["combined"]
        return

    out["shear"] = {
        "directions": {
            key: value["shear"] for key, value in directions.items()
        },
        "active_directions": active,
        "biaxial": True,
        "note": (
            "Vx and Vy are calculated independently. Generic cross-direction "
            "interaction is not calculated."
        ),
    }

    # Torsion on its own remains fully assessable.  The directional V+T screens
    # above are retained separately; no Vx+Vy+T interaction is inferred.
    if inp.get("torsion_on"):
        torsion_only_inp = dict(inp, shear_on=False, combined_on=False)
        torsion_only_out = {key: value for key, value in out.items()
                            if key in {"plastic", "elastic"}}
        _run_uniaxial_capacity_checks(torsion_only_inp, torsion_only_out)
        if torsion_only_out.get("torsion") is not None:
            out["torsion"] = dict(
                torsion_only_out["torsion"],
                directional_interactions={
                    key: value["torsion"] for key, value in directions.items()
                },
            )
    if inp.get("combined_on"):
        directional_combined = {
            key: value["combined"] for key, value in directions.items()
        }
        dkna_basis = inp.get("combined_method") == codes.EC2_2005_DKNA.label
        independent_mv = bool(
            dkna_basis and inp.get("combined_mv_independent") is True
        )
        separation_condition = next((
            direction.get("m_v_separation_condition")
            for direction in directional_combined.values()
            if isinstance(direction, dict)
            and direction.get("m_v_independent") is independent_mv
            and isinstance(direction.get("m_v_separation_condition"), dict)
        ), None)
        aggregate = dict(
            directions=directional_combined,
            biaxial=True,
            method=inp.get("combined_method"),
            note=(
                "Independent Vx+T and Vy+T calculations are reported. Generic "
                "Vx+Vy+T interaction is not calculated."
            ),
        )
        if dkna_basis:
            aggregate.update(
                m_v_independent=independent_mv,
                m_v_separation_condition=separation_condition,
            )
        out["combined"] = aggregate


def _direction_detailing_depth(direction):
    """Smallest required-face depth retained in one directional shear result."""
    depths = []
    for candidate in direction.get("face_candidates") or []:
        value = (candidate.get("shear") or {}).get("d")
        if value is not None and math.isfinite(float(value)) and float(value) > 0.0:
            depths.append(float(value))
    value = direction.get("d")
    if value is not None and math.isfinite(float(value)) and float(value) > 0.0:
        depths.append(float(value))
    return min(depths, default=0.0)


def _transverse_detailing_result(inp, out):
    """Translate verified shear/torsion geometry into pure detailing checks."""
    shear_specs = []
    shear_out = out.get("shear") or {}
    if inp.get("shear_on") and shear_out:
        directions = shear_out.get("directions")
        if directions:
            items = list(directions.items())
        else:
            component = str(shear_out.get("component") or (
                "vy" if shear_out.get("axis") == "x" else "vx"
            ))
            items = [(component, shear_out)]
        for component, direction in items:
            links = direction.get("links") or {}
            resistance = direction.get("res") or {}
            resistance_valid = bool(resistance.get("valid"))
            vrd_c = resistance.get("vrd_c")
            v_ed = direction.get("v_ed")
            if (
                resistance_valid
                and vrd_c is not None
                and v_ed is not None
                and math.isfinite(float(vrd_c))
                and math.isfinite(float(v_ed))
            ):
                links_required = float(v_ed) > float(vrd_c)
            else:
                links_required = None
            shear_specs.append({
                "component": component,
                "links_present": inp.get("shear_links") is True,
                "links_required": links_required,
                "requirement_clause": (
                    "8.2.2"
                    if bool(direction.get("model_2023"))
                    else "6.2.2"
                ),
                "bw_mm": direction.get("bw", 0.0),
                "d_mm": _direction_detailing_depth(direction),
                "legs": links.get(
                    "legs",
                    inp.get(
                        "shear_vx_link_legs"
                        if component == "vx"
                        else "shear_vy_link_legs",
                        0.0,
                    ),
                ),
                "transverse_leg_spacing_mm": inp.get(
                    "shear_vx_transverse_leg_spacing"
                    if component == "vx"
                    else "shear_vy_transverse_leg_spacing",
                    0.0,
                ),
                "measurement_axis": "y" if component == "vx" else "x",
            })

    torsion_specs = []
    torsion_out = out.get("torsion") or {}
    if inp.get("torsion_on") and torsion_out:
        subresults = torsion_out.get("subtubes") or []
        if subresults:
            for index, subresult in enumerate(subresults, start=1):
                tube = subresult.get("tube") or {}
                geometry_valid = (
                    subresult.get("tube_valid")
                    if "tube_valid" in subresult
                    else subresult.get("valid")
                )
                torsion_specs.append({
                    "label": f"Tube {index}",
                    "valid": (
                        geometry_valid is True
                        and tube.get("valid") is True
                    ),
                    "reason": tube.get("reason"),
                    "tef_mm": tube.get("tef", 0.0),
                    "uk_mm": float(tube.get("uk", 0.0)) * 1000.0,
                    "minimum_dimension_mm": tube.get(
                        "minimum_dimension_mm", 0.0
                    ),
                })
        else:
            tube = torsion_out.get("tube") or {}
            geometry_valid = (
                torsion_out.get("tube_valid")
                if "tube_valid" in torsion_out
                else torsion_out.get("valid")
            )
            torsion_specs.append({
                "label": "Tube",
                "valid": (
                    geometry_valid is True
                    and tube.get("valid") is True
                ),
                "reason": torsion_out.get("reason") or tube.get("reason"),
                "tef_mm": tube.get("tef", 0.0),
                "uk_mm": float(tube.get("uk", 0.0)) * 1000.0,
                "minimum_dimension_mm": tube.get(
                    "minimum_dimension_mm", 0.0
                ),
            })

    return detailing.transverse_reinforcement(
        edition=inp["detailing_edition"],
        fck_mpa=inp["concrete"].fck,
        fywk_mpa=inp["shear_fywk"],
        diameter_mm=inp["shear_link_dia"],
        spacing_mm=inp["shear_link_s"],
        shear_directions=shear_specs,
        torsion_tubes=torsion_specs,
        ductility_class=inp.get("transverse_ductility_class", "B"),
        apply_ductility_reduction=inp.get(
            "transverse_apply_ductility_reduction", False
        ),
        member_type=inp.get(
            "detailing_member_type", detailing.MEMBER_BEAM
        ),
    )


def _formula_631_detailing_state(inp, out):
    """Return the separate retained link-detailing assessment state."""

    if not inp.get("transverse_detailing_on"):
        return "NOT RUN", "separate_detailing_not_run"
    transverse = out.get("transverse_reinforcement")
    if not isinstance(transverse, dict):
        return "NOT RUN", "separate_detailing_not_run"
    status = str(transverse.get("status") or "").upper()
    if status == "PASS":
        return "PASS", "separate_detailing_passed"
    if status == "FAIL":
        return "FAIL", "separate_detailing_failed"
    return "NOT ASSESSED", "separate_detailing_incomplete"


def _attach_formula_631_detailing_state(inp, out):
    """Attach one independent detailing state to every retained 6.31 screen."""

    status, scope_key = _formula_631_detailing_state(inp, out)

    def attach(minimum):
        if isinstance(minimum, dict):
            minimum["detailing_status"] = status
            minimum["detailing_scope_key"] = scope_key

    torsion = out.get("torsion") or {}
    attach(torsion.get("min_reinf"))
    for item in (torsion.get("directional_interactions") or {}).values():
        if isinstance(item, dict):
            attach(item.get("min_reinf"))

    shear = out.get("shear") or {}
    directions = list((shear.get("directions") or {}).values())
    if not directions:
        directions = [shear]
    for direction in directions:
        if not isinstance(direction, dict):
            continue
        minimum_domain = (direction.get("governing_domains") or {}).get(
            "minimum_reinforcement"
        )
        attach(minimum_domain)
        for candidate in direction.get("face_candidates") or ():
            candidate_torsion = (candidate or {}).get("torsion") or {}
            attach(candidate_torsion.get("min_reinf"))


# ---------------------------------------------------------------------------
# Headless entry: calculate_project and the command line
# ---------------------------------------------------------------------------

_APP_SCRIPT = pathlib.Path(__file__).resolve().with_name("sector_app.py")


def _is_input_document(item) -> bool:
    return isinstance(item, Mapping) and "section" in item


def project_inputs(project, *, timeout: float = 180.0) -> dict:
    """Return the calculation input document of one project.

    ``project`` is the text of a project file or a ``(tables, scalars)`` pair
    from ``project_io.parse_project``. The input build (``build_inputs``) is
    still part of the Streamlit script. This function therefore runs that
    script one time in an isolated headless session (``streamlit.testing``)
    with a temporary autosave folder, and returns the inputs that Calculate
    would use. It does not read or change the state of a running application,
    so do not call it from the application.
    """

    if (
        isinstance(project, tuple)
        and len(project) == 2
        and all(
            isinstance(part, Mapping) and not _is_input_document(part)
            for part in project
        )
    ):
        text = project_io.dump_project(*project)
    elif isinstance(project, str):
        text = project
    else:
        raise TypeError(
            "project must be project file text or a (tables, scalars) pair"
        )
    from streamlit.testing.v1 import AppTest

    previous = os.environ.get("SECTOR_AUTOSAVE_DIR")
    with tempfile.TemporaryDirectory(prefix="sector-service-") as folder:
        os.environ["SECTOR_AUTOSAVE_DIR"] = str(pathlib.Path(folder) / "autosave")
        try:
            session = AppTest.from_file(str(_APP_SCRIPT), default_timeout=timeout)
            session.session_state["_pending_project"] = text
            session.run()
        finally:
            if previous is None:
                os.environ.pop("SECTOR_AUTOSAVE_DIR", None)
            else:
                os.environ["SECTOR_AUTOSAVE_DIR"] = previous
    if session.exception:
        raise RuntimeError(
            "The project input build stopped: "
            + "; ".join(str(item.value) for item in session.exception)
        )
    state = session.session_state
    # A file that Sector does not apply keeps the default session; only a
    # confirmed load gives the inputs of this project.
    message = state["_project_msg"] if "_project_msg" in state else None
    if not message or message[0] != "success":
        raise ValueError(
            str(message[1]) if message else "Sector did not confirm the project load"
        )
    errors = [str(item.value) for item in session.error]
    if errors:
        raise ValueError("Correct the project inputs: " + "; ".join(errors))
    if "_latest_inputs" not in state:
        raise RuntimeError("The project input build gave no inputs")
    return state["_latest_inputs"]


def _calculate_one(item) -> dict:
    inp = item if _is_input_document(item) else project_inputs(item)
    results = run_analysis(inp)
    return {
        "inputs": inp,
        "results": results,
        "result_sha256": project_io.result_sha256(results),
    }


def calculate_project(project_or_list):
    """Calculate one project, or each project of a list, without Streamlit state.

    An item is a calculation input document (the ``inp`` mapping that the
    input pages build) or a project (project file text, or a
    ``(tables, scalars)`` pair from ``project_io.parse_project``). A project
    gets its inputs from ``project_inputs`` first. The calculation is
    ``run_analysis``, the same call as Calculate, without result reuse.

    Returns one result set for one item, and a list of result sets in the same
    order for a list. A result set is a dictionary with ``inputs``,
    ``results`` and ``result_sha256`` (``project_io.result_sha256`` of the
    results, the value of the calculation record).
    """

    if isinstance(project_or_list, list):
        return [_calculate_one(item) for item in project_or_list]
    return _calculate_one(project_or_list)


def _summary_lines(
    name: str, result_set: dict, input_seconds: float, calculation_seconds: float
) -> list[str]:
    inp, results = result_set["inputs"], result_set["results"]
    lines = [f"Project: {name}"]
    if not results:
        lines.append(
            "No results. Correct the section, reinforcement or material inputs."
        )
        return lines
    rows = presentation.multi_case_summary_rows(inp, results)
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "-")
        counts[status] = counts.get(status, 0) + 1
    cases = {str(row.get("case") or "-") for row in rows}
    lines.append(f"Result rows: {len(rows)} in {len(cases)} cases")
    lines.extend(
        f"  {status}: {count}" for status, count in sorted(counts.items())
    )
    lines.append(f"Result SHA-256: {result_set['result_sha256']}")
    lines.append(f"Input build time: {input_seconds:.1f} s")
    lines.append(f"Calculation time: {calculation_seconds:.1f} s")
    return lines


def main(argv=None) -> int:
    """Command line: calculate one project file and print a short summary."""

    import argparse
    import logging

    parser = argparse.ArgumentParser(
        prog="python app/calculation_service.py",
        description="Calculate one Sector project file and print a summary.",
    )
    parser.add_argument("project", help="Sector project file (JSON)")
    args = parser.parse_args(argv)
    path = pathlib.Path(args.project)
    start = time.perf_counter()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        print(
            f"Sector: The file {path} does not exist. Make sure that the path "
            "is correct.",
            file=sys.stderr,
        )
        return 1
    except (OSError, UnicodeDecodeError):
        print(
            f"Sector: Cannot read the project file: {path}. Make sure that it "
            "is a Sector project file that you can open.",
            file=sys.stderr,
        )
        return 1
    # The headless session, the calculation and the summary write internal log
    # lines: the "missing ScriptRunContext" warning of Streamlit and the note of
    # the message filter about a suppressed diagnostic. The command line shows
    # only the summary or one Sector line, so stop log output below ERROR while
    # it runs, and set the earlier state again after it.
    previous_disable = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        try:
            inp = project_inputs(text)
            built = time.perf_counter()
            result_set = calculate_project(inp)
        except (ValueError, RuntimeError) as error:
            engineer_message = getattr(error, "engineer_message", None)
            detail = engineer_message.text if engineer_message is not None else error
            print(f"Sector: {detail}", file=sys.stderr)
            return 1
        done = time.perf_counter()
        lines = _summary_lines(path.name, result_set, built - start, done - built)
    finally:
        logging.disable(previous_disable)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    # Run the canonical module, so that this file does not load two times as
    # two different modules in one process.
    from app import calculation_service

    raise SystemExit(calculation_service.main())
