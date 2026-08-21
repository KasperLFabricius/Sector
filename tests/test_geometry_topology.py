"""Independent and boundary-level regression evidence for QA finding F-001."""

from __future__ import annotations

from fractions import Fraction
import hashlib
import itertools
import json
import math
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

from sector import capacity, detailing, fatigue, geometry, serviceability, shear, torsion
from sector.elastic import (
    solve_elastic,
    solve_elastic_combined,
    solve_elastic_uncracked,
    transformed_properties,
)
from sector.materials import Concrete, MildSteel
from sector.plastic import (
    conditional_capacity,
    plastic_capacity_at_angle,
    solve_interaction,
    solve_plastic,
)
from sector.section import Section


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
FIXTURE = ROOT / "tests" / "fixtures" / "geometry_topology_f001.json"


# ---------------------------------------------------------------------------
# Independent exact-rational oracle (test-only; no production helper reuse)
# ---------------------------------------------------------------------------

def _qpoint(point):
    return tuple(Fraction(str(value)) for value in point)


def _qring(ring):
    return tuple(_qpoint(point) for point in ring)


def _qcross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _qarea2(ring):
    return sum(
        ring[index][0] * ring[(index + 1) % len(ring)][1]
        - ring[(index + 1) % len(ring)][0] * ring[index][1]
        for index in range(len(ring))
    )


def _qon_segment(point, start, end):
    return (
        _qcross(start, end, point) == 0
        and min(start[0], end[0]) <= point[0] <= max(start[0], end[0])
        and min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
    )


def _qsegments_intersect(a0, a1, b0, b1):
    directions = (
        _qcross(a0, a1, b0),
        _qcross(a0, a1, b1),
        _qcross(b0, b1, a0),
        _qcross(b0, b1, a1),
    )
    if (
        directions[0] * directions[1] < 0
        and directions[2] * directions[3] < 0
    ):
        return True
    return any((
        directions[0] == 0 and _qon_segment(b0, a0, a1),
        directions[1] == 0 and _qon_segment(b1, a0, a1),
        directions[2] == 0 and _qon_segment(a0, b0, b1),
        directions[3] == 0 and _qon_segment(a1, b0, b1),
    ))


def _qring_simple(ring):
    count = len(ring)
    if count < 3 or len(set(ring)) != count or _qarea2(ring) == 0:
        return False
    for vertex in range(count):
        incoming = (
            ring[vertex][0] - ring[vertex - 1][0],
            ring[vertex][1] - ring[vertex - 1][1],
        )
        outgoing = (
            ring[(vertex + 1) % count][0] - ring[vertex][0],
            ring[(vertex + 1) % count][1] - ring[vertex][1],
        )
        if (
            incoming[0] * outgoing[1] - incoming[1] * outgoing[0] == 0
            and incoming[0] * outgoing[0] + incoming[1] * outgoing[1] < 0
        ):
            return False
    for first in range(count):
        for second in range(first + 1, count):
            if second == first + 1 or (first == 0 and second == count - 1):
                continue
            if _qsegments_intersect(
                ring[first],
                ring[(first + 1) % count],
                ring[second],
                ring[(second + 1) % count],
            ):
                return False
    return True


def _qpoint_inside(point, ring):
    if any(
        _qon_segment(point, ring[index], ring[(index + 1) % len(ring)])
        for index in range(len(ring))
    ):
        return False
    inside = False
    x, y = point
    for index, start in enumerate(ring):
        end = ring[(index + 1) % len(ring)]
        if (start[1] > y) == (end[1] > y):
            continue
        crossing_x = (
            start[0]
            + (y - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
        )
        if x < crossing_x:
            inside = not inside
    return inside


def _qboundaries_intersect(first, second):
    return any(
        _qsegments_intersect(
            first[i],
            first[(i + 1) % len(first)],
            second[j],
            second[(j + 1) % len(second)],
        )
        for i in range(len(first))
        for j in range(len(second))
    )


def _exact_oracle_valid(outer, holes):
    outer_q = _qring(outer)
    holes_q = tuple(_qring(hole) for hole in holes)
    if not _qring_simple(outer_q) or any(not _qring_simple(hole) for hole in holes_q):
        return False
    for hole in holes_q:
        if _qboundaries_intersect(outer_q, hole) or not _qpoint_inside(hole[0], outer_q):
            return False
    for first, second in itertools.combinations(holes_q, 2):
        if (
            _qboundaries_intersect(first, second)
            or _qpoint_inside(first[0], second)
            or _qpoint_inside(second[0], first)
        ):
            return False
    return True


def _fixture_cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize(
    "case", _fixture_cases(), ids=lambda case: case["benchmark_id"]
)
def test_frozen_f001_cases_match_independent_exact_oracle_and_production(case):
    assert _exact_oracle_valid(case["outer"], case["holes"]) is case["valid"]
    result = geometry.validate_section_topology(case["outer"], case["holes"])
    assert result.valid is case["valid"]
    if case["expected_code"] is not None:
        assert result.issues[0].code == case["expected_code"]
        assert result.issues[0].ring in result.message


def test_bow_tie_diagnostic_names_both_defective_edges():
    result = geometry.validate_section_topology(
        [(0, 0), (4, 4), (0, 4), (4, 0)]
    )
    assert result.issues[0].code == "self-intersection"
    assert "outer ring" in result.message
    assert "edge 1" in result.message
    assert "edge 3" in result.message
    assert "clearance" in result.message
    assert "tolerance" in result.message


@pytest.mark.parametrize(
    ("outer", "holes", "code", "message_parts"),
    [
        (
            [(0, 0), (1, 0), (1, 1), (0, 1), (1, 0)],
            [],
            "repeated-point",
            ("outer ring", "points 2 and 5"),
        ),
        (
            [(0, 0), (1, 0), (0.5, 0), (0, 1)],
            [],
            "backtracking-edge",
            ("outer ring", "point 2"),
        ),
        (
            [(0, 0), (1, 0), (1, 1), (0, 1)],
            [[(0, 0.2), (0.2, 0.2), (0.2, 0.4), (0, 0.4)]],
            "hole-boundary-contact",
            ("hole 1", "outer ring", "edge"),
        ),
        (
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [
                [(2, 2), (8, 2), (8, 8), (2, 8)],
                [(3, 3), (4, 3), (4, 4), (3, 4)],
            ],
            "nested-hole",
            ("hole 2", "hole 1"),
        ),
    ],
)
def test_topology_diagnostics_identify_ring_point_and_edges(
    outer, holes, code, message_parts
):
    result = geometry.validate_section_topology(outer, holes)
    assert result.issues[0].code == code
    for part in message_parts:
        assert part in result.message


def test_nonfinite_ring_coordinate_is_blocked_at_the_causal_point():
    result = geometry.validate_section_topology(
        [(0.0, 0.0), (1.0, 0.0), (1.0, np.inf), (0.0, 1.0)]
    )
    assert result.issues[0].code == "non-finite-point"
    assert "outer ring point 3" in result.message


def test_section_api_routes_malformed_coordinates_through_canonical_diagnostic():
    with pytest.raises(geometry.GeometryTopologyError) as caught:
        Section.from_polygon([(0, 0), (1, 0), ("not-a-number", 1)])
    assert caught.value.validation.issues[0].code == "malformed-ring"
    assert "outer ring" in str(caught.value)


def test_exact_terminal_closure_marker_is_compatible_but_near_closure_is_not():
    closed = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    assert geometry.validate_section_topology(closed).valid
    section = Section.from_polygon(closed)
    assert np.array_equal(section.concrete[0], np.asarray(closed, dtype=float))

    near_closed = closed[:-1] + [(0.5e-9, 0)]
    result = geometry.validate_section_topology(near_closed)
    assert result.issues[0].code == "repeated-point"
    assert "edge 5" in result.message


def _u_outline(gap):
    return [
        (0.0, 0.0),
        (2.0, 0.0),
        (2.0, 2.0),
        (1.0 + gap, 2.0),
        (1.0 + gap, 0.5),
        (1.0, 0.5),
        (1.0, 2.0),
        (0.0, 2.0),
    ]


def test_tolerance_brackets_for_edges_area_and_intersections():
    policy = geometry.DEFAULT_TOPOLOGY_TOLERANCE
    length_tol = policy.resolved_length(1.0)

    repeated_below = [(0, 0), (0.5 * length_tol, 0), (1, 0), (1, 1), (0, 1)]
    repeated_above = [(0, 0), (2.0 * length_tol, 0), (1, 0), (1, 1), (0, 1)]
    assert not geometry.validate_section_topology(repeated_below).valid
    assert geometry.validate_section_topology(repeated_above).valid

    skinny_below = [(0, 0), (1, 0), (1, 0.5 * length_tol), (0, 0.5 * length_tol)]
    skinny_above = [(0, 0), (1, 0), (1, 2.0 * length_tol), (0, 2.0 * length_tol)]
    assert not geometry.validate_section_topology(skinny_below).valid
    assert geometry.validate_section_topology(skinny_above).valid

    u_tol = policy.resolved_length(2.0)
    assert not geometry.validate_section_topology(_u_outline(0.5 * u_tol)).valid
    assert geometry.validate_section_topology(_u_outline(2.0 * u_tol)).valid


def test_tolerance_brackets_for_outer_and_hole_clearance():
    outer = [(0, 0), (1, 0), (1, 1), (0, 1)]
    length_tol = geometry.DEFAULT_TOPOLOGY_TOLERANCE.resolved_length(1.0)

    def hole_at(clearance):
        return [(clearance, 0.2), (0.2, 0.2), (0.2, 0.4), (clearance, 0.4)]

    assert not geometry.validate_section_topology(
        outer, [hole_at(0.5 * length_tol)]
    ).valid
    assert geometry.validate_section_topology(
        outer, [hole_at(2.0 * length_tol)]
    ).valid

    first = [(0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)]

    def second_at(clearance):
        left = 0.4 + clearance
        return [(left, 0.2), (0.6, 0.2), (0.6, 0.4), (left, 0.4)]

    assert not geometry.validate_section_topology(
        outer, [first, second_at(0.5 * length_tol)]
    ).valid
    assert geometry.validate_section_topology(
        outer, [first, second_at(2.0 * length_tol)]
    ).valid


@pytest.mark.parametrize("scale", [1.0e-3, 1.0, 1.0e3])
@pytest.mark.parametrize("translation", [(0.0, 0.0), (1.0e6, -2.0e6)])
def test_validation_is_translation_invariant_at_representative_section_scales(
    scale, translation
):
    outer = [(0, 0), (4, 0), (4, 3), (0, 3)]
    holes = [[(1, 1), (2, 1), (2, 2), (1, 2)]]

    def moved(ring):
        return [
            (translation[0] + scale * x, translation[1] + scale * y)
            for x, y in ring
        ]

    result = geometry.validate_section_topology(moved(outer), [moved(holes[0])])
    assert result.valid, result.message
    coordinate_magnitude = max(
        abs(coordinate)
        for ring in (moved(outer), moved(holes[0]))
        for point in ring
        for coordinate in point
    )
    floating_point_tolerance = (
        geometry.DEFAULT_TOPOLOGY_TOLERANCE.coordinate_ulp_multiplier
        * math.ulp(coordinate_magnitude)
    )
    assert result.length_tolerance == pytest.approx(
        max(1.0e-12, 4.0 * scale * 1.0e-9, floating_point_tolerance)
    )
    assert result.floating_point_tolerance == pytest.approx(
        floating_point_tolerance
    )


def _translated_contact_geometry(scale=1.0, translation=(500000.0, 500000.0)):
    outer = [(0.0, 0.0), (0.08, 0.0), (0.0, 0.08)]
    # The first point lies exactly on the outer diagonal x + y = 0.08.
    hole = [(0.04, 0.04), (0.02, 0.04), (0.04, 0.02)]

    def moved(ring):
        return [
            (
                translation[0] + scale * x,
                translation[1] + scale * y,
            )
            for x, y in ring
        ]

    return moved(outer), moved(hole)


def test_qa_translated_contact_reproducer_blocks_all_winding_and_closure_forms():
    outer, hole = _translated_contact_geometry()
    nominal_scale_tolerance = 0.08 * 1.0e-9

    for reverse_outer, reverse_hole, close_outer, close_hole in itertools.product(
        (False, True), repeat=4
    ):
        raw_outer = list(reversed(outer)) if reverse_outer else list(outer)
        raw_hole = list(reversed(hole)) if reverse_hole else list(hole)
        if close_outer:
            raw_outer.append(raw_outer[0])
        if close_hole:
            raw_hole.append(raw_hole[0])
        result = geometry.validate_section_topology(raw_outer, [raw_hole])
        assert not result.valid
        assert result.issues[0].code == "hole-boundary-contact"
        assert result.length_tolerance > nominal_scale_tolerance
        assert result.floating_point_tolerance > nominal_scale_tolerance


@pytest.mark.parametrize(
    "base",
    [
        [(0, 2), (1, 1), (1, 2), (2, 2), (2, 0)],
        [(0, 2), (1, 1), (2, 2), (2, 1), (2, 0)],
        [(0, 2), (1, 2), (1, 1), (2, 2), (2, 1), (2, 0)],
    ],
    ids=("qa-backtrack-contact-1", "qa-backtrack-contact-2", "qa-contact-3"),
)
def test_qa_oracle_translated_contact_and_backtracking_corpus_is_blocked(base):
    ring = [
        (1.0e6 + 1.0e-3 * x, -1.0e6 + 1.0e-3 * y)
        for x, y in base
    ]
    reversed_ring = list(reversed(ring))
    variants = (
        ring,
        reversed_ring,
        [*ring, ring[0]],
        [*reversed_ring, reversed_ring[0]],
    )

    for variant in variants:
        result = geometry.validate_section_topology(variant)
        assert not result.valid
        assert result.issues[0].code in {
            "backtracking-edge",
            "self-intersection",
        }


@pytest.mark.parametrize("scale", [1.0e-3, 1.0, 1.0e3])
@pytest.mark.parametrize("translation", [(0.0, 0.0), (500000.0, 500000.0)])
def test_invalid_contact_and_backtracking_are_translation_safe_across_scales(
    scale, translation
):
    outer, hole = _translated_contact_geometry(scale, translation)
    contact = geometry.validate_section_topology(outer, [hole])
    assert not contact.valid
    assert contact.issues[0].code == "hole-boundary-contact"

    backtracking_base = [
        (0.0, 0.0),
        (1.0, 0.0),
        (0.5, 0.0),
        (0.0, 1.0),
    ]
    backtracking = [
        (
            translation[0] + scale * x,
            translation[1] + scale * y,
        )
        for x, y in backtracking_base
    ]
    result = geometry.validate_section_topology(backtracking)
    assert not result.valid
    assert result.issues[0].code == "backtracking-edge"


def test_ulp_aware_translated_boundary_clearance_is_bracketed():
    origin = 500000.0
    outer = [
        (origin, origin),
        (origin + 0.08, origin),
        (origin + 0.08, origin + 0.08),
        (origin, origin + 0.08),
    ]

    def hole_at(clearance):
        return [
            (origin + clearance, origin + 0.02),
            (origin + 0.04, origin + 0.02),
            (origin + 0.04, origin + 0.04),
            (origin + clearance, origin + 0.04),
        ]

    probe = geometry.validate_section_topology(outer, [hole_at(0.01)])
    assert probe.valid
    assert probe.floating_point_tolerance > 0.08 * 1.0e-9
    assert not geometry.validate_section_topology(
        outer,
        [hole_at(0.5 * probe.length_tolerance)],
    ).valid
    assert geometry.validate_section_topology(
        outer,
        [hole_at(4.0 * probe.length_tolerance)],
    ).valid


def test_translated_contact_is_blocked_at_api_project_and_solver_gates():
    import project_io

    outer, hole = _translated_contact_geometry()
    with pytest.raises(geometry.GeometryTopologyError) as api_error:
        Section.from_polygon(outer, holes=[hole])
    assert api_error.value.validation.issues[0].code == "hole-boundary-contact"

    payload = _project_payload(outer, [hole])
    with pytest.raises(ValueError, match="invalid project section geometry"):
        project_io.parse_project(json.dumps(payload))

    tables = {
        "corners_base": pd.DataFrame(
            [[1000.0 * x, 1000.0 * y] for x, y in outer],
            columns=["x (mm)", "y (mm)"],
        ),
        "hole_base": pd.DataFrame(
            [[1000.0 * x, 1000.0 * y] for x, y in hole],
            columns=["x (mm)", "y (mm)"],
        ),
    }
    with pytest.raises(ValueError, match="invalid project section geometry"):
        project_io.dump_project(tables, {})

    valid_hole = [
        (500000.039, 500000.039),
        hole[1],
        hole[2],
    ]
    section = Section.from_polygon(outer, holes=[valid_hole])
    section.concrete[1] = np.asarray(hole, dtype=float)
    with pytest.raises(geometry.GeometryTopologyError) as solver_error:
        solve_elastic_uncracked(section, 0.0, 1.0, 0.0, 6.0)
    assert solver_error.value.validation.issues[0].code == "hole-boundary-contact"


def test_all_winding_permutations_keep_point_order_and_analysis_results():
    outer = [(0, 0), (5, 0), (5, 4), (0, 4)]
    holes = [
        [(1, 1), (2, 1), (2, 2), (1, 2)],
        [(3, 1), (4, 1), (4, 3), (3, 3)],
    ]
    reference = None
    for reverse_outer, reverse_first, reverse_second in itertools.product(
        (False, True), repeat=3
    ):
        raw_outer = list(reversed(outer)) if reverse_outer else outer
        raw_holes = [
            list(reversed(holes[0])) if reverse_first else holes[0],
            list(reversed(holes[1])) if reverse_second else holes[1],
        ]
        section = Section.from_polygon(raw_outer, holes=raw_holes)
        assert np.array_equal(section.concrete_vertices()[:4], raw_outer)
        rings = section.integration_rings()
        assert geometry.signed_area(rings[0]) > 0.0
        assert all(geometry.signed_area(ring) < 0.0 for ring in rings[1:])
        moments = geometry.area_moments_rings(rings)
        result = solve_elastic_uncracked(section, 100.0, 20.0, -10.0, 6.0)
        values = (
            moments.area,
            moments.sx,
            moments.sy,
            moments.sxx,
            moments.syy,
            moments.sxy,
            result.max_concrete_compression,
            result.max_concrete_tension,
        )
        if reference is None:
            reference = values
        else:
            assert values == pytest.approx(reference, rel=1.0e-12, abs=1.0e-12)


def _mutated_bow_tie_section():
    section = Section.from_polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    section.concrete[0] = np.asarray([(0, 0), (1, 1), (0, 1), (1, 0)], dtype=float)
    return section


@pytest.mark.parametrize(
    "solver",
    [
        lambda section: solve_elastic(section, 0.0, 1.0, 0.0, 6.0),
        lambda section: solve_elastic_uncracked(section, 0.0, 1.0, 0.0, 6.0),
        lambda section: transformed_properties(section, 6.0),
        lambda section: solve_elastic_combined(
            section, 0.0, 1.0, 0.0, 6.0, 0.0, 0.0, 0.0, 6.0
        ),
        lambda section: plastic_capacity_at_angle(
            section, Concrete(30.0), MildSteel(500.0, 500.0), 0.0, 90.0
        ),
        lambda section: solve_plastic(
            section, Concrete(30.0), MildSteel(500.0, 500.0),
            0.0, 0.0, 90.0, 90.0
        ),
        lambda section: solve_interaction(
            section, Concrete(30.0), MildSteel(500.0, 500.0),
            90.0, n_points=4
        ),
        lambda section: conditional_capacity(
            section, Concrete(30.0), MildSteel(500.0, 500.0),
            0.0, "x", True, 0.0
        ),
        lambda section: serviceability.analyse_cracking(
            section, 0.0, 1.0, 0.0, 6.0, fctm=2.9
        ),
        lambda section: serviceability.combined_cracking(
            section, 0.0, 1.0, 0.0, 6.0, 0.0, 0.0, 0.0, 6.0, fctm=2.9
        ),
        lambda section: serviceability.crack_width(
            section, None, 6.0, fctm=2.9
        ),
        lambda section: detailing.tension_zone_mean_width(section, "x", True),
        lambda section: detailing.minimum_reinforcement(
            section,
            [],
            [],
            Concrete(30.0),
            edition=detailing.EC2_2005,
            fctm_mpa=2.9,
            n_ed_tension_kn=0.0,
            mx_ed_knm=0.0,
            my_ed_knm=0.0,
        ),
        lambda section: fatigue.solve_fatigue_bin(section, None, 6.0, 6.0),
    ],
)
def test_every_section_solver_family_revalidates_mutable_api_input(solver):
    with pytest.raises(geometry.GeometryTopologyError) as caught:
        solver(_mutated_bow_tie_section())
    assert caught.value.validation.issues[0].code == "self-intersection"


def test_raw_shear_torsion_and_capacity_entries_share_the_canonical_gate():
    bow_tie = [(0, 0), (1, 1), (0, 1), (1, 0)]
    with pytest.raises(geometry.GeometryTopologyError):
        shear.min_web_width(bow_tie, [], "x")
    with pytest.raises(geometry.GeometryTopologyError):
        shear.effective_depth(bow_tie, "x", True, 0.5)
    with pytest.raises(geometry.GeometryTopologyError):
        torsion.tube_properties(bow_tie, [])
    with pytest.raises(geometry.GeometryTopologyError):
        capacity.gross_area_centroid(bow_tie, [])


@pytest.mark.parametrize(
    "entry",
    [
        lambda inp: capacity.shear_lever_arm(inp, "x", True, 500.0),
        lambda inp: capacity.shear_face_mrd(inp, "x", True),
        lambda inp: capacity.build_directional_shear_contexts(inp, 0.0, 0.0),
        lambda inp: capacity.build_shear_context(inp, 0.0, 0.0),
        lambda inp: capacity.build_torsion_context(inp, 0.0),
    ],
)
def test_capacity_orchestrator_entries_do_not_swallow_topology_errors(entry):
    section = _mutated_bow_tie_section()
    inp = {
        "section": section,
        "outer": section.concrete[0],
        "holes": [],
        "shear_on": True,
        "shear_links": True,
        "shear_method": capacity.codes.EC2_2005_DKNA.label,
        "torsion_on": True,
        "torsion_nu_v": False,
        "torsion_method": capacity.codes.EC2_2005_DKNA.label,
    }
    with pytest.raises(geometry.GeometryTopologyError):
        entry(inp)


def test_empty_mutated_ring_container_keeps_canonical_solver_and_ui_diagnostic():
    import fatigue_analysis

    section = Section.from_polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    section.concrete.clear()
    with pytest.raises(geometry.GeometryTopologyError) as caught:
        solve_elastic_uncracked(section, 0.0, 1.0, 0.0, 6.0)
    assert caught.value.validation.issues[0].ring == "outer ring"

    errors = fatigue_analysis.validation_errors({
        "fatigue_on": True,
        "section": section,
    })
    assert any("Invalid section geometry" in error for error in errors)


def _project_payload(outer, holes):
    import project_io

    hole_rows = []
    for index, hole in enumerate(holes):
        if index:
            hole_rows.append([None, None])
        hole_rows.extend([[1000.0 * x, 1000.0 * y] for x, y in hole])
    payload = json.loads(
        project_io.dump_project({}, {}, app_version="0.91", revision="test")
    )
    payload["tables"]["corners_base"] = {
        "columns": ["x (mm)", "y (mm)"],
        "rows": [[1000.0 * x, 1000.0 * y] for x, y in outer],
    }
    payload["tables"]["hole_base"] = {
        "columns": ["x (mm)", "y (mm)"],
        "rows": hole_rows,
    }
    content = {
        "tables": payload["tables"],
        "scalars": payload["scalars"],
    }
    canonical = json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    payload["provenance"]["input_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return payload


@pytest.mark.parametrize(
    "case",
    [case for case in _fixture_cases() if not case["valid"]],
    ids=lambda case: case["benchmark_id"],
)
def test_project_load_blocks_all_frozen_invalid_topologies(case):
    import project_io

    with pytest.raises(ValueError, match="invalid project section geometry"):
        project_io.parse_project(json.dumps(_project_payload(case["outer"], case["holes"])))


def test_current_schema_mixed_winding_project_remains_round_trip_compatible():
    import project_io

    outer_cw = [(0, 0), (0, 4), (5, 4), (5, 0)]
    hole_ccw = [(1, 1), (2, 1), (2, 2), (1, 2)]
    tables, scalars = project_io.parse_project(
        json.dumps(_project_payload(outer_cw, [hole_ccw]))
    )
    round_trip = project_io.dump_project(tables, scalars)
    restored, _ = project_io.parse_project(round_trip)
    assert restored["corners_base"].values.tolist() == [
        [1000.0 * x, 1000.0 * y] for x, y in outer_cw
    ]


def test_project_save_rejects_invalid_geometry_before_serialisation():
    import project_io

    tables = {
        "corners_base": pd.DataFrame(
            {
                "x (mm)": [0.0, 1000.0, 0.0, 1000.0],
                "y (mm)": [0.0, 1000.0, 1000.0, 0.0],
            }
        )
    }
    with pytest.raises(ValueError, match="outer ring.*edge"):
        project_io.dump_project(tables, {})


def test_project_save_and_load_reject_orphan_holes_without_an_outer_ring():
    import project_io

    hole = {
        "x (mm)": [100.0, 200.0, 200.0, 100.0],
        "y (mm)": [100.0, 100.0, 200.0, 200.0],
    }
    with pytest.raises(ValueError, match="requires a non-empty outer ring"):
        project_io.dump_project({"hole_base": pd.DataFrame(hole)}, {})

    payload = _project_payload(
        [],
        [[
            (x / 1000.0, y / 1000.0)
            for x, y in zip(hole["x (mm)"], hole["y (mm)"])
        ]],
    )
    with pytest.raises(ValueError, match="requires a non-empty outer ring"):
        project_io.parse_project(json.dumps(payload))
