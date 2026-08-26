"""Independent checks for longitudinal detailing and bar clear spacing."""

import math
from types import SimpleNamespace

import pytest

from sector import detailing
from sector.materials import Concrete, MildSteel
from sector.section import Section


def _steel(fyk=500.0):
    return MildSteel(fytk=fyk, fyck=fyk, eut=1.0, curve=2)


def _rectangle():
    bars = [
        (-0.12, -0.25, 491.0),
        (0.12, -0.25, 491.0),
        (-0.12, 0.25, 491.0),
        (0.12, 0.25, 491.0),
    ]
    section = Section.from_polygon(
        [(-0.15, -0.30), (0.15, -0.30), (0.15, 0.30), (-0.15, 0.30)],
        bars,
    )
    elements = [
        {
            "id": f"R{index + 1}",
            "kind": "bar",
            "x_mm": x * 1000.0,
            "y_mm": y * 1000.0,
            "diameter_mm": 25.0,
            "material_id": "M1",
        }
        for index, (x, y, _area) in enumerate(bars)
    ]
    return section, elements, [_steel()] * len(bars)


def _core_m02_review_fixture():
    """Return the immutable asymmetric-section numerical review fixture."""

    outer = [
        (-0.50, -0.45),
        (0.55, -0.45),
        (0.55, -0.10),
        (0.18, -0.10),
        (0.18, 0.55),
        (-0.08, 0.55),
        (-0.08, 0.20),
        (-0.50, 0.20),
    ]
    hole = [
        (-0.02, -0.02),
        (0.10, -0.02),
        (0.10, 0.10),
        (-0.02, 0.10),
    ]
    bars = [
        (-0.42, -0.38, 804.0),
        (0.45, -0.38, 804.0),
        (0.10, 0.47, 491.0),
        (-0.02, 0.47, 491.0),
        (-0.42, 0.13, 314.0),
        (0.48, -0.03, 314.0),
    ]
    section = Section.from_polygon(outer, bars, holes=[hole])
    elements = [
        {
            "id": f"R{index}",
            "kind": "bar",
            "x_mm": x * 1000.0,
            "y_mm": y * 1000.0,
            "diameter_mm": math.sqrt(4.0 * area / math.pi),
            "material_id": "M1",
        }
        for index, (x, y, area) in enumerate(bars, start=1)
    ]
    steel = MildSteel(
        fytk=500.0,
        fyck=500.0,
        futk=575.0,
        eut=0.05,
        curve=3,
        k=0.9,
        ey0t=0.002,
        ey0c=0.002,
        gamma_y=1.15,
        gamma_u=1.15,
        gamma_E=1.0,
        Es=200000.0,
        active_in_compression=True,
    )
    concrete = Concrete(
        fck=70.0,
        gamma_c=1.5,
        alpha_cc=0.85,
        curve=2,
        eps_c2=0.0024,
        eps_cu2=0.0027,
        n=1.45,
    )
    return section, elements, [steel] * len(bars), concrete


def _core_m02_full_sweep_reference(
    section, concrete, materials, mx_cr_knm, my_cr_knm, increment_deg
):
    """Independently rate one complete neutral-axis sweep at fixed resolution."""

    centred = detailing._recentred_without_tendons(section)
    characteristic = [
        detailing._characteristic_plateau(material) for material in materials
    ]
    endpoint = 360.0 - increment_deg
    # Permit the historical represented 0.1-degree gaps without asking the
    # maximum-increment guard to compensate for binary64 subtraction noise.
    maximum_increment = increment_deg * (1.0 + 1.0e-12)
    points = detailing.solve_plastic(
        centred,
        concrete,
        characteristic[0],
        0.0,
        0.0,
        endpoint,
        maximum_increment,
        bar_materials=characteristic,
    )
    radial = detailing._module("combined").radial_util_result(
        [point.Mx for point in points],
        [point.My for point in points],
        mx_cr_knm,
        my_cr_knm,
    )
    return points, radial


@pytest.mark.parametrize(
    ("active_in_compression", "fyck", "expected_active"),
    (
        (True, 500.0, True),
        (True, 0.0, False),
        (False, 500.0, False),
    ),
)
def test_characteristic_plateau_preserves_effective_compression_applicability(
    active_in_compression,
    fyck,
    expected_active,
):
    source = MildSteel(
        fytk=500.0,
        fyck=fyck,
        eut=0.05,
        gamma_y=1.15,
        curve=2,
        active_in_compression=active_in_compression,
    )

    plateau = detailing._characteristic_plateau(source)

    assert plateau.active_in_compression is expected_active
    assert plateau.fyck == pytest.approx(500.0 if expected_active else 0.0)
    assert plateau.stress(-0.01, design=False) == pytest.approx(
        -500.0 if expected_active else 0.0
    )


def test_tension_zone_mean_width_uses_net_clipped_concrete():
    section, _elements, _materials = _rectangle()
    assert detailing.tension_zone_mean_width(section, "x", True) == pytest.approx(
        (300.0, 300.0)
    )

    # T-section with the flange in compression.  Its centroid lies in the web;
    # the complete bottom tension half is therefore exactly 300 mm wide.
    t_section = Section.from_polygon(
        [
            (-0.60, 0.20),
            (0.60, 0.20),
            (0.60, 0.40),
            (0.15, 0.40),
            (0.15, 1.00),
            (-0.15, 1.00),
            (-0.15, 0.40),
            (-0.60, 0.40),
        ]
    )
    bt, _depth = detailing.tension_zone_mean_width(t_section, "x", False)
    assert bt == pytest.approx(300.0)


def test_2005_formula_reports_face_inputs_and_area_ratio():
    section, elements, materials = _rectangle()
    result = detailing.minimum_reinforcement_2005(
        section,
        elements,
        materials,
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=100.0,
        my_ed_knm=0.0,
    )
    row = result["checks"][0]
    expected = max(0.26 * 2.9 / 500.0, 0.0013) * 300.0 * 550.0
    assert result["status"] == "PASS"
    assert row["face"] == "bottom"
    assert row["bar_ids"] == ["R1", "R2"]
    assert row["as_min_mm2"] == pytest.approx(expected)
    assert row["utilisation"] == pytest.approx(expected / 982.0)
    assert row["strength_coefficient"] == pytest.approx(0.26 * 2.9 / 500.0)
    assert row["floor_coefficient"] == pytest.approx(0.0013)
    assert row["selected_coefficient"] == pytest.approx(0.26 * 2.9 / 500.0)
    assert row["governing_coefficient"] == "0.26 fctm / fyk"
    assert row["tension_zone_area_mm2"] == pytest.approx(300.0 * 300.0)
    assert row["bt_mm"] == pytest.approx(
        row["tension_zone_area_mm2"] / row["tension_zone_depth_mm"]
    )
    assert row["d_mm"] == pytest.approx(
        (row["bar_level_m"] - row["compression_extreme_m"]) * 1000.0
    )


def test_origin_moment_transfer_uses_tension_positive_axial_sign():
    bars = [
        (0.0, 0.05, 100.0),
        (0.0, 0.55, 500.0),
    ]
    section = Section.from_polygon(
        [(-0.10, 0.0), (0.10, 0.0), (0.10, 0.60), (-0.10, 0.60)],
        bars,
    )
    elements = [
        {
            "id": f"R{index + 1}",
            "kind": "bar",
            "x_mm": x * 1000.0,
            "y_mm": y * 1000.0,
            "diameter_mm": 16.0,
            "material_id": "M1",
        }
        for index, (x, y, _area) in enumerate(bars)
    ]

    result = detailing.minimum_reinforcement_2005(
        section,
        elements,
        [_steel(), _steel()],
        fctm_mpa=2.9,
        n_ed_tension_kn=100.0,
        mx_ed_knm=0.0,
        my_ed_knm=0.0,
    )

    check = result["checks"][0]
    expected = max(0.26 * 2.9 / 500.0, 0.0013) * 200.0 * 550.0
    assert result["mx_ed_centroid_knm"] == pytest.approx(30.0)
    assert check["face"] == "bottom"
    assert check["bar_ids"] == ["R1"]
    assert check["as_min_mm2"] == pytest.approx(expected)
    assert check["status"] == "FAIL"


def test_2005_biaxial_check_uses_resultant_tension_zone_not_axis_halves():
    bars = [
        (0.25, -0.25, 1000.0),
        (-0.25, 0.25, 1000.0),
    ]
    section = Section.from_polygon(
        [(-0.30, -0.30), (0.30, -0.30), (0.30, 0.30), (-0.30, 0.30)],
        bars,
    )
    elements = [
        {
            "id": f"R{index + 1}",
            "kind": "bar",
            "x_mm": x * 1000.0,
            "y_mm": y * 1000.0,
            "diameter_mm": 36.0,
            "material_id": "M1",
        }
        for index, (x, y, _area) in enumerate(bars)
    ]

    result = detailing.minimum_reinforcement_2005(
        section,
        elements,
        [_steel(), _steel()],
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=100.0,
        my_ed_knm=100.0,
    )

    check = result["checks"][0]
    assert result["status"] == "FAIL"
    assert check["type"] == "minimum area"
    assert check["axis"] == "xy"
    assert check["face"] == "resultant tension zone"
    assert check["bar_ids"] == []
    assert check["as_min_mm2"] is None
    assert check["tension_direction"] == pytest.approx(
        [-math.sqrt(0.5), -math.sqrt(0.5)]
    )


def test_2005_formula_uses_conservative_face_fyk_and_flags_missing_face():
    section, elements, materials = _rectangle()
    materials = [_steel(400.0), _steel(500.0), *materials[2:]]
    result = detailing.minimum_reinforcement_2005(
        section,
        elements,
        materials,
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=100.0,
        my_ed_knm=0.0,
    )
    assert result["checks"][0]["fyk_mpa"] == 400.0

    no_bottom = Section.from_polygon(
        section.concrete[0],
        [(bar.x, bar.y, bar.area * 1.0e6) for bar in section.bars[2:]],
    )
    missing = detailing.minimum_reinforcement_2005(
        no_bottom,
        elements[2:],
        materials[2:],
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=100.0,
        my_ed_knm=0.0,
    )
    assert missing["status"] == "FAIL"
    assert missing["checks"][0]["as_min_mm2"] is None


def test_2023_rectangle_cracking_moment_is_independently_reproduced():
    section, elements, materials = _rectangle()
    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=100.0,
        my_ed_knm=0.0,
    )
    # Mcr = fctm * b*h^2/6 = 52.2 kNm.
    assert result["status"] == "PASS"
    assert result["checks"][0]["m_cr_knm"] == pytest.approx(52.2)
    assert result["checks"][0]["mr_nom_knm"] > 52.2
    check = result["checks"][0]
    assert check["cracking_branch"] == (
        "scaled bending reaches the concrete tensile strength"
    )
    assert check["cracking_factor"] == pytest.approx(
        (
            check["cracking_fctm_mpa"]
            - check["cracking_governing_axial_stress_mpa"]
        )
        / check["cracking_governing_bending_stress_mpa"]
    )
    solution = check["nominal_solution"]
    assert solution["method"] == "plastic nominal axial-moment envelope"
    assert solution["angle_start_deg"] == 0.0
    assert solution["angle_end_deg"] == 345.0
    assert solution["angle_increment_deg"] == 15.0
    assert solution["accepted_point_count"] > 24
    assert solution["resolution_state"] == "RESOLVED"
    assert [
        stage["target_increment_deg"]
        for stage in solution["refinement_history"]
    ] == [15.0, 1.0, 0.1]
    assert all(
        stage["resolution_achieved"]
        and stage["governing_interval_deg"]
        <= stage["target_increment_deg"] + 1.0e-12
        for stage in solution["refinement_history"]
    )
    assert solution["governing_target_increment_deg"] == pytest.approx(0.1)
    assert solution["governing_interval_deg"] == pytest.approx(
        solution["refinement_history"][-1]["governing_interval_deg"]
    )
    selected = solution["governing_point"]
    assert selected["neutral_axis_angle_deg"] == pytest.approx(90.0)
    assert selected["converged"] is True
    assert selected["achieved_axial_kn"] == pytest.approx(0.0, abs=1.0e-4)
    assert selected["axial_residual_kn"] == pytest.approx(
        selected["achieved_axial_kn"] - selected["requested_axial_kn"]
    )
    assert selected["search_depth_range_m"] is not None


@pytest.mark.parametrize(
    (
        "phi_deg",
        "fctm_mpa",
        "expected_status",
        "expected_cracking",
        "fixed_references",
    ),
    [
        pytest.param(
            309.0,
            8.9,
            "PASS",
            (
                649.4598830005184,
                408.71834754106794,
                -504.72512520216964,
            ),
            (
                (15.0, 647.5044122669113, 1.0030200114417152, 135.0),
                (1.0, 664.8594002351513, 0.9768379341118042, 142.0),
                (0.1, 664.8630715346253, 0.9768325401220532, 141.9),
            ),
            id="309-degree-false-fail",
        ),
        pytest.param(
            357.0,
            7.258066978469918,
            "FAIL",
            (
                800.7222093632556,
                799.6248474040824,
                -41.90656251198909,
            ),
            (
                (15.0, 801.1924436984497, 0.9994130819144731, 105.0),
                (1.0, 800.2580078750917, 1.000580064783602, 113.0),
                (0.1, 800.249288886036, 1.0005909664448163, 112.8),
            ),
            id="357-degree-false-pass",
        ),
    ],
)
def test_2023_review_cases_are_stable_against_independent_full_sweeps(
    phi_deg,
    fctm_mpa,
    expected_status,
    expected_cracking,
    fixed_references,
):
    section, elements, materials, concrete = _core_m02_review_fixture()
    phi = math.radians(phi_deg)

    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        concrete,
        fctm_mpa=fctm_mpa,
        n_ed_tension_kn=0.0,
        mx_ed_knm=math.cos(phi),
        my_ed_knm=math.sin(phi),
    )

    check = result["checks"][0]
    expected_mcr, expected_mxcr, expected_mycr = expected_cracking
    assert result["status"] == expected_status
    assert check["m_cr_knm"] == pytest.approx(expected_mcr, rel=1.0e-11)
    assert check["mx_cr_knm"] == pytest.approx(expected_mxcr, rel=1.0e-11)
    assert check["my_cr_knm"] == pytest.approx(expected_mycr, rel=1.0e-11)
    assert math.degrees(
        math.atan2(check["my_cr_knm"], check["mx_cr_knm"])
    ) % 360.0 == pytest.approx(phi_deg)

    independent = []
    for increment, expected_mr, expected_util, expected_edge_start in fixed_references:
        points, radial = _core_m02_full_sweep_reference(
            section,
            concrete,
            materials,
            check["mx_cr_knm"],
            check["my_cr_knm"],
            increment,
        )
        assert len(points) == round(360.0 / increment)
        assert all(point.converged for point in points)
        assert radial.valid is True
        assert radial.resistance == pytest.approx(expected_mr, rel=1.0e-10)
        assert radial.utilisation == pytest.approx(expected_util, rel=1.0e-10)
        assert points[radial.governing_index].V == pytest.approx(
            expected_edge_start
        )
        independent.append(radial)

    solution = check["nominal_solution"]
    history = solution["refinement_history"]
    assert solution["resolution_state"] == "RESOLVED"
    assert solution["verdict_resolved"] is True
    assert solution["error_control_factor"] == 2.0
    assert solution["minimum_utilisation_error"] == pytest.approx(1.0e-6)
    assert solution["governing_increment_deg"] == pytest.approx(0.1)
    assert solution["governing_target_increment_deg"] == pytest.approx(0.1)
    assert solution["governing_interval_deg"] <= 0.1 + 1.0e-12
    assert [stage["target_increment_deg"] for stage in history] == [
        15.0,
        1.0,
        0.1,
    ]
    assert all(stage["resolution_achieved"] for stage in history)
    assert all(
        stage["governing_interval_deg"]
        <= stage["target_increment_deg"] + 1.0e-12
        for stage in history
    )
    assert history[0]["utilisation"] == pytest.approx(
        independent[0].utilisation
    )
    assert history[1]["utilisation"] == pytest.approx(
        independent[1].utilisation
    )
    assert check["utilisation"] == pytest.approx(
        independent[2].utilisation, rel=2.0e-6
    )
    if expected_status == "PASS":
        assert solution["utilisation_upper_bound"] < 1.0
    else:
        assert solution["utilisation_lower_bound"] > 1.0
    # phi is the applied-moment direction; V remains separate solver evidence.
    assert history[-1]["governing_angle_deg"] != pytest.approx(phi_deg)


@pytest.mark.parametrize(
    ("mx_centroid_knm", "my_centroid_knm", "expected_mx_cr", "expected_my_cr"),
    [
        (1.0e-12, 0.0, 52.2, 0.0),
        (1.0e-13, 0.0, 52.2, 0.0),
        (-1.0e-12, 0.0, -52.2, 0.0),
        (0.0, 1.0e-12, 0.0, 26.1),
        (0.0, -1.0e-12, 0.0, -26.1),
    ],
)
def test_2023_cracking_action_is_scale_independent_for_tiny_moment(
    mx_centroid_knm, my_centroid_knm, expected_mx_cr, expected_my_cr
):
    section, _elements, _materials = _rectangle()

    result = detailing._cracking_action(
        section,
        n_ed_tension_kn=0.0,
        mx_centroid_knm=mx_centroid_knm,
        my_centroid_knm=my_centroid_knm,
        fctm_mpa=2.9,
    )

    expected_mcr = math.hypot(expected_mx_cr, expected_my_cr)
    assert result["valid"] is True
    assert result["branch"] == "scaled bending reaches the concrete tensile strength"
    assert result["mx_cr_knm"] == pytest.approx(expected_mx_cr, rel=1.0e-10)
    assert result["my_cr_knm"] == pytest.approx(expected_my_cr, rel=1.0e-10)
    assert result["m_cr_knm"] == pytest.approx(expected_mcr, rel=1.0e-10)
    entered_moment = math.hypot(mx_centroid_knm, my_centroid_knm)
    assert result["factor"] == pytest.approx(
        expected_mcr / entered_moment, rel=1.0e-10
    )
    assert result["governing_bending_stress_mpa"] > 0.0


@pytest.mark.parametrize(
    "mx_centroid_knm",
    [
        pytest.param(math.ulp(0.0), id="minimum-subnormal"),
        pytest.param(float.fromhex("0x1.fffffffffffffp+1023"), id="maximum-finite"),
    ],
)
def test_2023_extreme_finite_cracking_action_fails_closed(mx_centroid_knm):
    section, _elements, _materials = _rectangle()

    result = detailing._cracking_action(
        section,
        n_ed_tension_kn=0.0,
        mx_centroid_knm=mx_centroid_knm,
        my_centroid_knm=0.0,
        fctm_mpa=2.9,
    )

    assert result["valid"] is False
    assert (
        "finite" in result["reason"].casefold()
        or "representable" in result["reason"].casefold()
    )


def test_2023_finite_cracking_intermediates_cannot_publish_overflowed_action():
    section = Section.from_polygon(
        [(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)]
    )

    result = detailing._cracking_action(
        section,
        n_ed_tension_kn=0.0,
        mx_centroid_knm=1.0e100,
        my_centroid_knm=0.0,
        fctm_mpa=1.0e305,
    )

    assert result == {
        "valid": False,
        "reason": "cracking action is not representable with finite values",
    }


def test_2023_axial_stress_at_fctm_owns_zero_cracking_factor():
    section, _elements, _materials = _rectangle()

    result = detailing._cracking_action(
        section,
        n_ed_tension_kn=522.0,
        mx_centroid_knm=1.0,
        my_centroid_knm=0.0,
        fctm_mpa=2.9,
    )

    assert result["valid"] is True
    assert result["branch"] == "axial action reaches the concrete tensile strength"
    assert result["factor"] == 0.0
    assert result["mx_cr_knm"] == 0.0
    assert result["my_cr_knm"] == 0.0
    assert result["m_cr_knm"] == 0.0


@pytest.mark.parametrize(
    ("mx_centroid_knm", "fctm_mpa", "reason"),
    [
        (math.inf, 2.9, "cracking action inputs must be finite"),
        (math.nan, 2.9, "cracking action inputs must be finite"),
        (1.0, math.inf, "fctm must be finite and positive"),
        (1.0, 0.0, "fctm must be finite and positive"),
    ],
)
def test_2023_nonfinite_or_nonpositive_cracking_inputs_fail_closed(
    mx_centroid_knm, fctm_mpa, reason
):
    section, _elements, _materials = _rectangle()

    result = detailing._cracking_action(
        section,
        n_ed_tension_kn=0.0,
        mx_centroid_knm=mx_centroid_knm,
        my_centroid_knm=0.0,
        fctm_mpa=fctm_mpa,
    )

    assert result == {"valid": False, "reason": reason}


def test_2023_tiny_real_moment_reaches_nominal_envelope():
    section, elements, materials = _rectangle()

    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=1.0e-12,
        my_ed_knm=0.0,
    )

    check = result["checks"][0]
    assert result["status"] == "PASS"
    assert result["clause"] == "12.2(2)(a), Formula (12.1)"
    assert check["type"] == "bending with axial force"
    assert check["m_cr_knm"] == pytest.approx(52.2, rel=1.0e-10)
    assert check["mx_cr_knm"] == pytest.approx(52.2, rel=1.0e-10)
    assert check["my_cr_knm"] == 0.0
    assert check["cracking_factor"] == pytest.approx(52.2e12, rel=1.0e-10)
    assert check["model"] == "uniaxial x; refined nominal envelope"
    assert check["radial_demand_knm"] == pytest.approx(52.2, rel=1.0e-10)
    assert check["radial_resistance_knm"] == pytest.approx(
        252.72029622280888, rel=1.0e-10
    )
    assert check["utilisation"] == pytest.approx(
        0.2065524644446375, rel=1.0e-10
    )
    assert check["nominal_solution"]["accepted_point_count"] > 24
    assert check["nominal_solution"]["all_points_converged"] is True


def test_2023_pure_tension_uses_formula_12_2_force_equilibrium():
    section, elements, materials = _rectangle()
    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=100.0,
        mx_ed_knm=0.0,
        my_ed_knm=0.0,
    )
    check = result["checks"][0]
    assert result["clause"] == "12.2(2)(b), Formula (12.2)"
    assert check["demand_kn"] == pytest.approx(0.18 * 2.9 * 1000.0)
    assert check["resistance_kn"] == pytest.approx(1964.0 * 500.0 / 1000.0)
    assert result["concrete_area_m2"] == pytest.approx(0.18)
    assert result["compression_limit_kn"] == pytest.approx(
        0.5 * result["concrete_area_m2"] * result["fcd_mpa"] * 1000.0
    )
    assert [term["bar_id"] for term in check["reinforcement_terms"]] == [
        "R1", "R2", "R3", "R4"
    ]
    assert sum(
        term["resistance_kn"] for term in check["reinforcement_terms"]
    ) == pytest.approx(check["resistance_kn"])


def test_2023_high_compression_is_outside_formula_12_1_scope():
    section, elements, materials = _rectangle()
    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=-1800.0,
        mx_ed_knm=100.0,
        my_ed_knm=0.0,
    )
    assert result["status"] == "NOT APPLICABLE"
    assert result["compression_limit_kn"] == pytest.approx(1800.0)


def test_2023_axial_tension_that_already_cracks_cannot_bypass_axial_capacity():
    section, elements, materials = _rectangle()
    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        # Ac*fctm = 522 kN, while sum(As*fyk) = 982 kN. This axial action
        # therefore causes cracking before bending and exceeds the nominal bar
        # resistance. A zero calculated Mcr must not turn that into a false pass.
        n_ed_tension_kn=1000.0,
        mx_ed_knm=50.0,
        my_ed_knm=0.0,
    )

    check = result["checks"][0]
    assert result["status"] == "FAIL"
    assert check["m_cr_knm"] == pytest.approx(0.0)
    assert check["axial_feasible"] is False
    assert check["nominal_axial_resistance_kn"] == pytest.approx(982.0)
    assert "below NEd,min" in check["reason"]


def test_2023_zero_cracking_moment_checks_nominal_axial_moment_envelope():
    section, elements, materials = _rectangle()
    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=600.0,
        mx_ed_knm=50.0,
        my_ed_knm=0.0,
    )

    check = result["checks"][0]
    assert check["m_cr_knm"] == pytest.approx(0.0)
    assert check["axial_feasible"] is True
    assert result["status"] == "PASS"


def _remote_origin_envelope():
    return [
        SimpleNamespace(Mx=9.0, My=-1.0, converged=True),
        SimpleNamespace(Mx=11.0, My=-1.0, converged=True),
        SimpleNamespace(Mx=11.0, My=1.0, converged=True),
        SimpleNamespace(Mx=9.0, My=1.0, converged=True),
    ]


def _nominal_point(mx, my, *, angle=0.0, converged=True):
    return SimpleNamespace(
        Mx=mx,
        My=my,
        V=angle,
        axial=0.0,
        curvature=0.0,
        converged=converged,
    )


def _centred_nominal_envelope(scale=1.0):
    return [
        _nominal_point(-scale, -scale, angle=0.0),
        _nominal_point(scale, -scale, angle=90.0),
        _nominal_point(scale, scale, angle=180.0),
        _nominal_point(-scale, scale, angle=270.0),
    ]


def _accept_synthetic_four_point_resolution(monkeypatch):
    """Keep four-point radial-isolation fixtures outside angular-resolution QA."""

    monkeypatch.setattr(
        detailing,
        "_nominal_interval_achieved",
        lambda *_args, **_kwargs: True,
    )


@pytest.mark.parametrize(
    ("utilisations", "expected_state", "expected_final_status"),
    [
        ((1.02, 0.99, 0.98), "RESOLVED", "PASS"),
        ((0.98, 1.02, 1.03), "RESOLVED", "FAIL"),
        ((0.99, 1.0005, 1.0001, 1.00005), "UNRESOLVED", None),
        ((0.99, 1.0, 1.0, 1.0), "UNRESOLVED", None),
    ],
)
def test_2023_nominal_refinement_resolves_reversals_and_withholds_near_limit(
    monkeypatch, utilisations, expected_state, expected_final_status
):
    section, _elements, materials = _rectangle()
    scripted = iter(utilisations)

    def fake_solve(*args, **_kwargs):
        angles = detailing._module("plastic").plastic_sweep_angles(*args[4:7])
        return [
            _nominal_point(
                math.cos(math.radians(angle)),
                math.sin(math.radians(angle)),
                angle=angle,
            )
            for angle in angles
        ]

    def fake_radial(*_args, **_kwargs):
        utilisation = next(scripted)
        return SimpleNamespace(
            demand=1.0,
            resistance=1.0 / utilisation,
            utilisation=utilisation,
            governing_index=0,
            valid=True,
            reason=None,
            origin_inside_or_on=True,
        )

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)
    monkeypatch.setattr(
        detailing._module("combined"), "radial_util_result", fake_radial
    )

    points, radial, resolution = detailing._nominal_refined_envelope(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials[0],
        materials,
        p_comp=0.0,
        mx=1.0,
        my=0.0,
    )

    assert points
    assert resolution["resolution_state"] == expected_state
    assert resolution["verdict_resolved"] is (expected_state == "RESOLVED")
    assert [
        stage["target_increment_deg"]
        for stage in resolution["refinement_history"]
    ] == (
        [15.0, 1.0, 0.1]
        if expected_state == "RESOLVED"
        else [15.0, 1.0, 0.1, 0.01]
    )
    if expected_final_status is None:
        assert resolution["utilisation_lower_bound"] < 1.0
        assert resolution["utilisation_upper_bound"] > 1.0
        assert "stable assessment" in resolution["reason"]
    else:
        final_status = "PASS" if radial.utilisation <= 1.0 else "FAIL"
        assert final_status == expected_final_status


def test_2023_nominal_refinement_follows_moved_window_across_wrap_before_verdict(
    monkeypatch,
):
    section, _elements, materials = _rectangle()
    scripted = iter([
        (0.0, 0.99),
        (180.0, 0.99),
        (180.0, 0.99),
        (90.0, 0.99),
        (90.0, 1.01),
        (0.0, 1.01),
        (0.0, 1.011),
    ])
    solved_windows = []

    def fake_solve(*args, **_kwargs):
        start, end, increment = (float(value) for value in args[4:7])
        solved_windows.append((start, end, increment))
        angles = detailing._module("plastic").plastic_sweep_angles(
            start, end, increment
        )
        return [
            _nominal_point(angle, 0.0, angle=angle)
            for angle in angles
        ]

    def fake_radial(mx_values, _my_values, *_args, **_kwargs):
        target_angle, utilisation = next(scripted)
        governing_index = min(
            range(len(mx_values)),
            key=lambda index: abs(float(mx_values[index]) - target_angle),
        )
        return SimpleNamespace(
            demand=1.0,
            resistance=1.0 / utilisation,
            utilisation=utilisation,
            governing_index=governing_index,
            valid=True,
            reason=None,
            origin_inside_or_on=True,
        )

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)
    monkeypatch.setattr(
        detailing._module("combined"), "radial_util_result", fake_radial
    )

    _points, radial, resolution = detailing._nominal_refined_envelope(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials[0],
        materials,
        p_comp=0.0,
        mx=1.0,
        my=0.0,
    )

    history = resolution["refinement_history"]
    assert resolution["resolution_state"] == "RESOLVED"
    assert radial.utilisation == pytest.approx(1.011)
    assert [stage["target_increment_deg"] for stage in history] == [
        15.0,
        1.0,
        0.1,
        0.01,
    ]
    assert [stage.get("refinement_window_count", 0) for stage in history] == [
        0,
        2,
        2,
        2,
    ]
    assert all(stage["resolution_achieved"] for stage in history)
    assert all(
        stage["governing_interval_deg"]
        <= stage["target_increment_deg"] + 1.0e-12
        for stage in history
    )
    assert resolution["governing_target_increment_deg"] == pytest.approx(0.01)
    assert resolution["governing_interval_deg"] <= 0.01 + 1.0e-12
    assert any(
        start < 0.0 < end and increment == pytest.approx(0.01)
        for start, end, increment in solved_windows
    )


def test_2023_nominal_refinement_fails_closed_when_window_cannot_progress(
    monkeypatch,
):
    section, _elements, materials = _rectangle()
    scripted = iter(((0, 0.99), (12, 0.99)))

    def fake_solve(*args, **_kwargs):
        angles = detailing._module("plastic").plastic_sweep_angles(*args[4:7])
        return [
            _nominal_point(
                math.cos(math.radians(angle)),
                math.sin(math.radians(angle)),
                angle=angle,
            )
            for angle in angles
        ]

    def fake_radial(mx_values, _my_values, *_args, **_kwargs):
        governing_index, utilisation = next(scripted)
        assert governing_index < len(mx_values)
        return SimpleNamespace(
            demand=1.0,
            resistance=1.0 / utilisation,
            utilisation=utilisation,
            governing_index=governing_index,
            valid=True,
            reason=None,
            origin_inside_or_on=True,
        )

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)
    monkeypatch.setattr(
        detailing,
        "_refine_nominal_governing_window",
        lambda *_args, **_kwargs: list(_args[5]),
    )
    monkeypatch.setattr(
        detailing._module("combined"), "radial_util_result", fake_radial
    )

    _points, _radial, resolution = detailing._nominal_refined_envelope(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials[0],
        materials,
        p_comp=0.0,
        mx=1.0,
        my=0.0,
    )

    assert resolution["resolution_state"] == "UNRESOLVED"
    assert resolution["verdict_resolved"] is False
    assert resolution["reason"] == (
        "nominal governing interval could not be refined consistently"
    )
    assert resolution["governing_target_increment_deg"] == pytest.approx(1.0)
    assert resolution["governing_interval_deg"] == pytest.approx(15.0)
    assert resolution["utilisation_lower_bound"] is None
    assert resolution["utilisation_upper_bound"] is None
    assert resolution["refinement_history"][-1]["resolution_achieved"] is False


def test_2023_nominal_refinement_bounds_moved_windows_before_radial_work(
    monkeypatch,
):
    section, elements, materials = _rectangle()
    scripted = iter([
        (0.0, 0.99),
        (0.0, 0.99),
        (0.0, 1.0),
        (180.0, 1.0),
        (90.0, 1.0),
        (90.0, 1.0),
    ])
    radial_point_counts = []
    solved_windows = []

    def fake_solve(*args, **_kwargs):
        solved_windows.append(tuple(float(value) for value in args[4:7]))
        angles = detailing._module("plastic").plastic_sweep_angles(*args[4:7])
        return [
            _nominal_point(angle, 0.0, angle=angle)
            for angle in angles
        ]

    def fake_radial(mx_values, _my_values, *_args, **_kwargs):
        radial_point_counts.append(len(mx_values))
        target_angle, utilisation = next(scripted)
        governing_index = min(
            range(len(mx_values)),
            key=lambda index: abs(float(mx_values[index]) - target_angle),
        )
        return SimpleNamespace(
            demand=1.0,
            resistance=1.0 / utilisation,
            utilisation=utilisation,
            governing_index=governing_index,
            valid=True,
            reason=None,
            origin_inside_or_on=True,
        )

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)
    monkeypatch.setattr(
        detailing._module("combined"), "radial_util_result", fake_radial
    )
    monkeypatch.setattr(
        detailing,
        "_cracking_action",
        lambda *_args, **_kwargs: {
            "valid": True,
            "m_cr_knm": 1.0,
            "mx_cr_knm": 1.0,
            "my_cr_knm": 0.0,
            "factor": 1.0,
            "branch": "retained-angle boundary test",
            "fctm_mpa": 2.9,
            "governing_vertex_index": 0,
            "governing_vertex_x_m": 0.0,
            "governing_vertex_y_m": 0.0,
            "governing_axial_stress_mpa": 0.0,
            "governing_bending_stress_mpa": 2.9,
            "axial_peak_tension_mpa": 0.0,
        },
    )

    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=1.0,
        my_ed_knm=0.0,
    )

    point_limit = detailing._module("plastic").PLASTIC_SWEEP_MAX_POINTS
    solution = result["checks"][0]["nominal_solution"]
    history = solution["refinement_history"]
    assert radial_point_counts == [24, 52, 72, 80, 3080]
    expected_windows = [
        (0.0, 345.0, 15.0),
        (-15.0, 15.0, 1.0),
        (-1.0, 1.0, 0.1),
        (-1.0 / 21.0, 1.0 / 21.0, 0.01),
        (165.0, 195.0, 0.01),
    ]
    assert len(solved_windows) == len(expected_windows)
    for actual, expected in zip(solved_windows, expected_windows):
        assert actual == pytest.approx(expected)
    assert not any(
        start == pytest.approx(75.0)
        and end == pytest.approx(105.0)
        and increment == pytest.approx(0.01)
        for start, end, increment in solved_windows
    )
    assert max(radial_point_counts) <= point_limit
    assert solution["accepted_point_count"] == 3080
    assert solution["accepted_point_count"] <= point_limit
    assert history[-1]["accepted_point_count"] == 3080
    assert history[-1]["resolution_achieved"] is False
    assert solution["resolution_state"] == "UNRESOLVED"
    assert solution["governing_target_increment_deg"] == pytest.approx(0.01)
    assert solution["governing_interval_deg"] == pytest.approx(15.0)
    assert result["status"] == "NOT ASSESSED"
    assert result["reason"] == (
        "nominal governing interval could not be refined consistently"
    )


@pytest.mark.parametrize(
    ("point_angles", "expected_count", "work_expected"),
    (
        ((0.0, 120.0, 240.0), 4097, True),
        ((0.0, 120.0, 180.0, 240.0), 4098, False),
    ),
)
def test_2023_nominal_refinement_preflights_exact_inclusive_point_limit(
    monkeypatch,
    point_angles,
    expected_count,
    work_expected,
):
    section, _elements, materials = _rectangle()
    points = [
        _nominal_point(angle, 0.0, angle=angle)
        for angle in point_angles
    ]
    increment = (240.0 / 4095.0) * (1.0 + 1.0e-12)
    window = detailing._nominal_refinement_window(points, 0)
    assert window == pytest.approx((-120.0, 120.0))
    sweep_angles = detailing._module("plastic").plastic_sweep_angles(
        *window, increment
    )
    refined = [
        _nominal_point(angle, 0.0, angle=angle)
        for angle in sweep_angles
    ]
    actually_merged = detailing._merge_nominal_points(points, refined)
    prospective_count = detailing._nominal_refined_point_count(
        points, 0, increment
    )

    assert prospective_count == expected_count
    assert len(actually_merged) == expected_count
    assert len({
        round(detailing._nominal_angle(point), 12)
        for point in actually_merged
    }) == expected_count

    solve_calls = []
    radial_point_counts = []

    def fake_solve(*args, **_kwargs):
        solve_calls.append(tuple(float(value) for value in args[4:7]))
        angles = detailing._module("plastic").plastic_sweep_angles(*args[4:7])
        return [
            _nominal_point(angle, 0.0, angle=angle)
            for angle in angles
        ]

    def fake_radial(mx_values, _my_values, *_args, **_kwargs):
        radial_point_counts.append(len(mx_values))
        return SimpleNamespace(
            demand=1.0,
            resistance=1.0,
            utilisation=1.0,
            governing_index=1,
            valid=True,
            reason=None,
            origin_inside_or_on=True,
        )

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)
    monkeypatch.setattr(
        detailing._module("combined"), "radial_util_result", fake_radial
    )
    prior_radial = SimpleNamespace(
        demand=1.0,
        resistance=1.0 / 0.99,
        utilisation=0.99,
        governing_index=0,
        valid=True,
        reason=None,
        origin_inside_or_on=True,
    )

    returned_points, returned_radial, stage, failure_state, reason = (
        detailing._resolve_nominal_refinement_stage(
            section,
            Concrete(30.0, gamma_c=1.5),
            materials[0],
            materials,
            0.0,
            points,
            prior_radial,
            1.0,
            0.0,
            increment,
        )
    )

    point_limit = detailing._module("plastic").PLASTIC_SWEEP_MAX_POINTS
    assert point_limit == 4097
    if work_expected:
        assert len(solve_calls) == 1
        assert radial_point_counts == [point_limit]
        assert len(returned_points) == point_limit
        assert returned_radial is not prior_radial
        assert stage["accepted_point_count"] == point_limit
        assert stage["resolution_achieved"] is True
        assert failure_state is None
        assert reason is None
    else:
        assert solve_calls == []
        assert radial_point_counts == []
        assert returned_points is points
        assert returned_radial is prior_radial
        assert stage["accepted_point_count"] == len(points)
        assert stage["utilisation"] == pytest.approx(prior_radial.utilisation)
        assert stage["resistance_knm"] == pytest.approx(prior_radial.resistance)
        assert stage["governing_angle_deg"] == pytest.approx(0.0)
        assert stage["governing_interval_deg"] == pytest.approx(120.0)
        assert stage["resolution_achieved"] is False
        assert failure_state == "UNRESOLVED"
        assert reason == (
            "nominal governing interval could not be refined consistently"
        )


def test_2023_nominal_refinement_rejects_coarse_initial_solver_evidence(
    monkeypatch,
):
    section, _elements, materials = _rectangle()
    monkeypatch.setattr(
        detailing,
        "solve_plastic",
        lambda *_args, **_kwargs: _centred_nominal_envelope(),
    )

    _points, _radial, resolution = detailing._nominal_refined_envelope(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials[0],
        materials,
        p_comp=0.0,
        mx=1.0,
        my=0.0,
    )

    assert resolution["resolution_state"] == "UNRESOLVED"
    assert resolution["verdict_resolved"] is False
    assert resolution["governing_target_increment_deg"] == pytest.approx(15.0)
    assert resolution["governing_interval_deg"] == pytest.approx(90.0)
    assert resolution["refinement_history"][0]["resolution_achieved"] is False


def test_2023_nominal_refinement_retains_later_nonconvergence(monkeypatch):
    section, _elements, materials = _rectangle()
    solve_count = 0

    def fake_solve(*args, **_kwargs):
        nonlocal solve_count
        solve_count += 1
        angles = detailing._module("plastic").plastic_sweep_angles(*args[4:7])
        return [
            _nominal_point(
                math.cos(math.radians(angle)),
                math.sin(math.radians(angle)),
                angle=angle,
                converged=solve_count == 1,
            )
            for angle in angles
        ]

    def fake_radial(*_args, **_kwargs):
        return SimpleNamespace(
            demand=1.0,
            resistance=2.0,
            utilisation=0.5,
            governing_index=0,
            valid=True,
            reason=None,
            origin_inside_or_on=True,
        )

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)
    monkeypatch.setattr(
        detailing._module("combined"), "radial_util_result", fake_radial
    )

    _points, _radial, resolution = detailing._nominal_refined_envelope(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials[0],
        materials,
        p_comp=0.0,
        mx=1.0,
        my=0.0,
    )

    assert resolution["resolution_state"] == "INVALID"
    assert resolution["verdict_resolved"] is False
    assert resolution["reason"] == "nominal axial-moment envelope did not converge"
    assert [
        stage["target_increment_deg"]
        for stage in resolution["refinement_history"]
    ] == [15.0, 1.0]
    assert resolution["refinement_history"][0]["all_points_converged"] is True
    assert resolution["refinement_history"][1]["all_points_converged"] is False


def test_2023_unresolved_nominal_refinement_is_not_assessed(monkeypatch):
    section, elements, materials = _rectangle()
    reason = (
        "nominal resistance is too close to the cracking demand for a stable "
        "assessment at the available angular resolution"
    )
    monkeypatch.setattr(
        detailing,
        "_cracking_action",
        lambda *_args, **_kwargs: {
            "valid": True,
            "m_cr_knm": 1.0,
            "mx_cr_knm": 1.0,
            "my_cr_knm": 0.0,
            "factor": 1.0,
            "branch": "near-limit resolution test",
            "fctm_mpa": 2.9,
            "governing_vertex_index": 0,
            "governing_vertex_x_m": 0.0,
            "governing_vertex_y_m": 0.0,
            "governing_axial_stress_mpa": 0.0,
            "governing_bending_stress_mpa": 2.9,
            "axial_peak_tension_mpa": 0.0,
        },
    )
    monkeypatch.setattr(
        detailing,
        "_nominal_capacity_utilisation",
        lambda *_args, **_kwargs: {
            "valid": True,
            "assessment_resolved": False,
            "utilisation": None,
            "mr_nom_knm": None,
            "model": "uniaxial x; refined nominal envelope",
            "nominal_axial_resistance_kn": 1000.0,
            "nominal_reinforcement_terms": [],
            "nominal_solution": {
                "resolution_state": "UNRESOLVED",
                "verdict_resolved": False,
                "estimated_utilisation_error": 0.0001,
                "utilisation_lower_bound": 0.99995,
                "utilisation_upper_bound": 1.00015,
                "governing_increment_deg": 0.01,
                "refinement_history": [],
            },
            "radial_demand_knm": 1.0,
            "radial_resistance_knm": None,
            "reason": reason,
        },
    )

    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=1.0,
        my_ed_knm=0.0,
    )

    assert result["status"] == "NOT ASSESSED"
    assert result["reason"] == reason
    assert result["checks"][0]["status"] == "NOT ASSESSED"
    assert result["checks"][0]["utilisation"] is None
    assert result["checks"][0]["mr_nom_knm"] is None


def test_2023_zero_cracking_remote_nominal_envelope_cannot_pass(monkeypatch):
    section, elements, materials = _rectangle()
    monkeypatch.setattr(
        detailing,
        "_cracking_action",
        lambda *_args, **_kwargs: {
            "valid": True,
            "m_cr_knm": 0.0,
            "mx_cr_knm": 0.0,
            "my_cr_knm": 0.0,
            "factor": 0.0,
            "branch": "zero cracking action test",
            "fctm_mpa": 2.9,
            "governing_vertex_index": 0,
            "governing_vertex_x_m": 0.0,
            "governing_vertex_y_m": 0.0,
            "governing_axial_stress_mpa": 0.0,
            "governing_bending_stress_mpa": 0.0,
            "axial_peak_tension_mpa": 0.0,
        },
    )
    monkeypatch.setattr(
        detailing,
        "solve_plastic",
        lambda *_args, **_kwargs: _remote_origin_envelope(),
    )

    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=50.0,
        my_ed_knm=0.0,
    )

    check = result["checks"][0]
    assert result["status"] == "FAIL"
    assert check["status"] == "FAIL"
    assert check["axial_feasible"] is False
    assert check["utilisation"] is None
    assert "outside the nominal envelope" in check["reason"]


def test_2023_biaxial_nominal_envelope_propagates_origin_invalid(monkeypatch):
    section, _elements, materials = _rectangle()
    monkeypatch.setattr(
        detailing,
        "solve_plastic",
        lambda *_args, **_kwargs: _remote_origin_envelope(),
    )

    result = detailing._nominal_capacity_utilisation(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials,
        n_ed_tension_kn=0.0,
        mx_cr_knm=1.0,
        my_cr_knm=1.0,
    )

    assert result["valid"] is False
    assert result["utilisation"] is None
    assert result["mr_nom_knm"] is None
    assert result["radial_resistance_knm"] is None
    assert "origin" in result["reason"].casefold()


@pytest.mark.parametrize(
    ("mx_cr_knm", "my_cr_knm"),
    [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)],
)
def test_2023_uniaxial_nominal_envelope_propagates_origin_invalid(
    monkeypatch, mx_cr_knm, my_cr_knm
):
    section, _elements, materials = _rectangle()
    monkeypatch.setattr(
        detailing,
        "solve_plastic",
        lambda *_args, **_kwargs: _remote_origin_envelope(),
    )
    result = detailing._nominal_capacity_utilisation(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials,
        n_ed_tension_kn=0.0,
        mx_cr_knm=mx_cr_knm,
        my_cr_knm=my_cr_knm,
    )

    assert result["valid"] is False
    assert result["utilisation"] is None
    assert result["mr_nom_knm"] is None
    assert result["radial_resistance_knm"] is None
    assert "origin" in result["reason"].casefold()


@pytest.mark.parametrize(
    ("mx_cr_knm", "my_cr_knm", "model"),
    [
        (5.0e-10, 0.0, "uniaxial x; refined nominal envelope"),
        (-5.0e-10, 0.0, "uniaxial x; refined nominal envelope"),
        (0.0, 5.0e-10, "uniaxial y; refined nominal envelope"),
        (0.0, -5.0e-10, "uniaxial y; refined nominal envelope"),
    ],
)
def test_2023_tiny_nonzero_cracking_moment_uses_radial_envelope(
    monkeypatch, mx_cr_knm, my_cr_knm, model
):
    section, _elements, materials = _rectangle()
    _accept_synthetic_four_point_resolution(monkeypatch)
    monkeypatch.setattr(
        detailing,
        "solve_plastic",
        lambda *_args, **_kwargs: _centred_nominal_envelope(1.0e-12),
    )

    result = detailing._nominal_capacity_utilisation(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials,
        n_ed_tension_kn=0.0,
        mx_cr_knm=mx_cr_knm,
        my_cr_knm=my_cr_knm,
    )

    assert result["valid"] is True
    assert result["utilisation"] == pytest.approx(500.0)
    assert result["mr_nom_knm"] == pytest.approx(
        1.0e-12, rel=1.0e-12, abs=0.0
    )
    assert result["radial_demand_knm"] == pytest.approx(
        5.0e-10, rel=1.0e-12, abs=0.0
    )
    assert result["radial_resistance_knm"] == pytest.approx(
        1.0e-12, rel=1.0e-12, abs=0.0
    )
    assert result["model"] == model


def test_2023_sub_tolerance_secondary_moment_remains_biaxial(monkeypatch):
    section, _elements, materials = _rectangle()
    monkeypatch.setattr(
        detailing,
        "solve_plastic",
        lambda *_args, **_kwargs: _centred_nominal_envelope(2.0),
    )

    result = detailing._nominal_capacity_utilisation(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials,
        n_ed_tension_kn=0.0,
        mx_cr_knm=1.0,
        my_cr_knm=5.0e-10,
    )

    assert result["valid"] is True
    assert result["model"] == "biaxial refined nominal envelope"
    assert result["radial_demand_knm"] == pytest.approx(
        math.hypot(1.0, 5.0e-10), rel=1.0e-12, abs=0.0
    )


def test_2023_exact_zero_cracking_moment_retains_zero_demand_path(monkeypatch):
    section, _elements, materials = _rectangle()
    calls = []

    def fake_solve(*args, **kwargs):
        calls.append((args, kwargs))
        return _centred_nominal_envelope(1.0e-12)

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)

    result = detailing._nominal_capacity_utilisation(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials,
        n_ed_tension_kn=0.0,
        mx_cr_knm=0.0,
        my_cr_knm=0.0,
    )

    assert len(calls) == 1
    assert result["valid"] is True
    assert result["utilisation"] == 0.0
    assert result["mr_nom_knm"] == 0.0
    assert result["axial_feasible"] is True
    assert result["model"] == "zero cracking moment; nominal axial-moment envelope"


def test_2023_uniaxial_capacity_refines_one_radial_envelope(monkeypatch):
    section, _elements, materials = _rectangle()
    _accept_synthetic_four_point_resolution(monkeypatch)
    points = [
        _nominal_point(4.0, 2.0, angle=0.0),
        _nominal_point(2.0, -2.0, angle=90.0),
        _nominal_point(-2.0, -2.0, angle=180.0),
        _nominal_point(-2.0, 2.0, angle=270.0),
    ]
    calls = []

    def fake_solve(*args, **kwargs):
        calls.append((args, kwargs))
        return points

    def reject_standalone_point(*_args, **_kwargs):
        raise AssertionError("standalone fixed-angle solve must not run")

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)
    monkeypatch.setattr(
        "sector.plastic.plastic_capacity_at_angle",
        reject_standalone_point,
    )

    result = detailing._nominal_capacity_utilisation(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials,
        n_ed_tension_kn=0.0,
        mx_cr_knm=1.5,
        my_cr_knm=0.0,
    )

    assert len(calls) == 3
    args, kwargs = calls[0]
    assert args[4:7] == (0.0, 345.0, 15.0)
    assert "bar_materials" in kwargs
    assert result["valid"] is True
    assert result["utilisation"] == pytest.approx(0.5)
    assert result["mr_nom_knm"] == pytest.approx(3.0)
    assert result["radial_resistance_knm"] == pytest.approx(3.0)
    assert result["governing"] == 0
    assert result["model"] == "uniaxial x; refined nominal envelope"
    cardinal = next(point for point in points if point.V == 90.0)
    assert abs(cardinal.Mx) == pytest.approx(2.0)
    assert result["mr_nom_knm"] != pytest.approx(abs(cardinal.Mx))
    solution = result["nominal_solution"]
    assert solution["method"] == "plastic nominal axial-moment envelope"
    assert solution["governing_point_index"] == 0
    assert solution["governing_point"]["capacity_mx_knm"] == pytest.approx(4.0)
    assert solution["governing_point"]["capacity_my_knm"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    (
        "mx_cr_knm",
        "my_cr_knm",
        "expected_resistance",
        "expected_governing",
        "expected_point",
        "model",
    ),
    [
        (1.0, 0.0, 13.0 / 4.0, 0, (4.0, 1.0), "uniaxial x; refined nominal envelope"),
        (-1.0, 0.0, 11.0 / 6.0, 2, (-2.0, -1.0), "uniaxial x; refined nominal envelope"),
        (0.0, 1.0, 21.0 / 5.0, 3, (-1.0, 5.0), "uniaxial y; refined nominal envelope"),
        (0.0, -1.0, 7.0 / 3.0, 1, (1.0, -3.0), "uniaxial y; refined nominal envelope"),
    ],
)
def test_2023_signed_uniaxial_axes_use_distinct_asymmetric_resistances(
    monkeypatch,
    mx_cr_knm,
    my_cr_knm,
    expected_resistance,
    expected_governing,
    expected_point,
    model,
):
    section, _elements, materials = _rectangle()
    _accept_synthetic_four_point_resolution(monkeypatch)
    points = [
        _nominal_point(4.0, 1.0, angle=0.0),
        _nominal_point(1.0, -3.0, angle=90.0),
        _nominal_point(-2.0, -1.0, angle=180.0),
        _nominal_point(-1.0, 5.0, angle=270.0),
    ]
    calls = []

    def fake_solve(*args, **kwargs):
        calls.append((args, kwargs))
        return points

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)

    result = detailing._nominal_capacity_utilisation(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials,
        n_ed_tension_kn=0.0,
        mx_cr_knm=mx_cr_knm,
        my_cr_knm=my_cr_knm,
    )

    assert len(calls) == 3
    assert result["valid"] is True
    assert result["model"] == model
    assert result["radial_demand_knm"] == 1.0
    assert result["radial_resistance_knm"] == pytest.approx(expected_resistance)
    assert result["mr_nom_knm"] == pytest.approx(expected_resistance)
    assert result["utilisation"] == pytest.approx(1.0 / expected_resistance)
    assert result["governing"] == expected_governing
    solution = result["nominal_solution"]
    assert solution["governing_point_index"] == expected_governing
    assert solution["governing_point"]["capacity_mx_knm"] == expected_point[0]
    assert solution["governing_point"]["capacity_my_knm"] == expected_point[1]


def test_2023_uniaxial_nonconverged_envelope_is_invalid(monkeypatch):
    section, _elements, materials = _rectangle()
    points = _centred_nominal_envelope()
    points[1].converged = False
    calls = []

    def fake_solve(*args, **kwargs):
        calls.append((args, kwargs))
        return points

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)

    result = detailing._nominal_capacity_utilisation(
        section,
        Concrete(30.0, gamma_c=1.5),
        materials,
        n_ed_tension_kn=0.0,
        mx_cr_knm=1.0,
        my_cr_knm=0.0,
    )

    assert len(calls) == 1
    assert result["valid"] is False
    assert result["utilisation"] is None
    assert result["mr_nom_knm"] is None
    assert result["model"] == "uniaxial x; refined nominal envelope"
    assert result["reason"] == "nominal axial-moment envelope did not converge"
    assert result["nominal_solution"]["all_points_converged"] is False


def test_2023_public_uniaxial_check_propagates_remote_origin_invalid(monkeypatch):
    section, elements, materials = _rectangle()
    monkeypatch.setattr(
        detailing,
        "_cracking_action",
        lambda *_args, **_kwargs: {
            "valid": True,
            "m_cr_knm": 1.0,
            "mx_cr_knm": 1.0,
            "my_cr_knm": 0.0,
            "factor": 1.0,
            "branch": "uniaxial origin prerequisite test",
            "fctm_mpa": 2.9,
            "governing_vertex_index": 0,
            "governing_vertex_x_m": 0.0,
            "governing_vertex_y_m": 0.0,
            "governing_axial_stress_mpa": 0.0,
            "governing_bending_stress_mpa": 2.9,
            "axial_peak_tension_mpa": 0.0,
        },
    )
    monkeypatch.setattr(
        detailing,
        "solve_plastic",
        lambda *_args, **_kwargs: _remote_origin_envelope(),
    )

    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=1.0,
        my_ed_knm=0.0,
    )

    check = result["checks"][0]
    assert result["status"] == "INVALID"
    assert check["status"] == "INVALID"
    assert check["utilisation"] is None
    assert check["mr_nom_knm"] is None
    assert "origin" in check["reason"].casefold()


def test_2023_public_tiny_nonzero_moment_cannot_bypass_bending(monkeypatch):
    section, elements, materials = _rectangle()
    _accept_synthetic_four_point_resolution(monkeypatch)
    cracking_calls = []
    envelope_calls = []

    def fake_cracking(*_args, **kwargs):
        cracking_calls.append(kwargs)
        return {
            "valid": True,
            "m_cr_knm": 5.0e-10,
            "mx_cr_knm": 5.0e-10,
            "my_cr_knm": 0.0,
            "factor": 1.0,
            "branch": "tiny nonzero moment test",
            "fctm_mpa": 2.9,
            "governing_vertex_index": 0,
            "governing_vertex_x_m": 0.0,
            "governing_vertex_y_m": 0.0,
            "governing_axial_stress_mpa": 0.0,
            "governing_bending_stress_mpa": 2.9,
            "axial_peak_tension_mpa": 0.0,
        }

    monkeypatch.setattr(detailing, "_cracking_action", fake_cracking)
    def fake_solve(*args, **kwargs):
        envelope_calls.append((args, kwargs))
        return _centred_nominal_envelope(1.0e-12)

    monkeypatch.setattr(detailing, "solve_plastic", fake_solve)

    result = detailing.minimum_reinforcement_2023(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=5.0e-10,
        my_ed_knm=0.0,
    )

    check = result["checks"][0]
    assert len(cracking_calls) == 1
    assert cracking_calls[0]["mx_centroid_knm"] == pytest.approx(
        5.0e-10, rel=1.0e-12, abs=0.0
    )
    assert cracking_calls[0]["my_centroid_knm"] == 0.0
    assert len(envelope_calls) == 3
    assert result["status"] == "FAIL"
    assert result["clause"] == "12.2(2)(a), Formula (12.1)"
    assert check["status"] == "FAIL"
    assert check["type"] == "bending with axial force"
    assert check["utilisation"] == pytest.approx(500.0)
    assert check["mr_nom_knm"] == pytest.approx(
        1.0e-12, rel=1.0e-12, abs=0.0
    )
    assert check["radial_demand_knm"] == pytest.approx(
        5.0e-10, rel=1.0e-12, abs=0.0
    )
    assert check["radial_resistance_knm"] == pytest.approx(
        1.0e-12, rel=1.0e-12, abs=0.0
    )


def _spacing_elements(clear_mm):
    phi = 20.0
    return [
        {
            "id": "R1",
            "kind": "bar",
            "x_mm": 0.0,
            "y_mm": 0.0,
            "diameter_mm": phi,
        },
        {
            "id": "R2",
            "kind": "bar",
            "x_mm": phi + clear_mm,
            "y_mm": 0.0,
            "diameter_mm": phi,
        },
    ]


def test_clear_spacing_uses_largest_code_term_and_pair_margin():
    result = detailing.clear_spacing(
        _spacing_elements(25.0),
        d_upper_mm=20.0,
        edition=detailing.EC2_2023,
    )
    pair = result["governing"]
    assert result["status"] == "PASS"
    assert pair["required_mm"] == 25.0
    assert pair["margin_mm"] == pytest.approx(0.0)
    assert pair["centre_distance_mm"] == pytest.approx(45.0)
    assert pair["dx_mm"] == pytest.approx(45.0)
    assert pair["dy_mm"] == pytest.approx(0.0)
    assert pair["required_candidates_mm"] == pytest.approx({
        "larger element diameter": 20.0,
        "aggregate allowance": 25.0,
        "absolute minimum": 20.0,
    })
    assert pair["governing_requirement"] == "aggregate allowance"


def test_clear_spacing_shortfall_fails_without_legacy_exception_fields():
    result = detailing.clear_spacing(
        _spacing_elements(10.0),
        d_upper_mm=16.0,
        edition=detailing.EC2_2005_DKNA,
    )
    assert result["status"] == "FAIL"
    assert result["governing"]["status"] == "FAIL"
    assert "declared_exception" not in result["governing"]
    assert "spacing_group_id" not in result["governing"]


def test_clear_spacing_excludes_tendons_unless_their_envelope_is_selected():
    elements = _spacing_elements(25.0)
    elements.append(
        {
            "id": "P1",
            "kind": "tendon",
            "x_mm": 5.0,
            "y_mm": 0.0,
            "diameter_mm": 10.0,
        }
    )
    bars_only = detailing.clear_spacing(
        elements, d_upper_mm=16.0, edition=detailing.EC2_2023
    )
    with_tendon = detailing.clear_spacing(
        elements,
        d_upper_mm=16.0,
        edition=detailing.EC2_2023,
        include_tendons=True,
    )
    assert bars_only["status"] == "PASS"
    assert with_tendon["status"] == "FAIL"
    assert math.isclose(with_tendon["governing"]["clear_mm"], -10.0)


def test_minimum_transverse_ratio_uses_dk_na_and_explicit_2023_reduction():
    dk = detailing.minimum_transverse_ratio(
        30.0,
        500.0,
        edition=detailing.EC2_2005_DKNA,
    )
    en = detailing.minimum_transverse_ratio(
        30.0,
        500.0,
        edition=detailing.EC2_2005,
    )
    class_c = detailing.minimum_transverse_ratio(
        30.0,
        500.0,
        edition=detailing.EC2_2023,
        ductility_class="C",
        apply_ductility_reduction=True,
    )
    assert dk["ratio"] == pytest.approx(0.063 * math.sqrt(30.0) / 500.0)
    assert en["ratio"] == pytest.approx(0.08 * math.sqrt(30.0) / 500.0)
    assert class_c["ratio"] == pytest.approx(en["ratio"] * 0.80)
    assert class_c["base_ratio"] == pytest.approx(
        class_c["coefficient"] * math.sqrt(class_c["fck_mpa"])
        / class_c["fywk_mpa"]
    )
    assert class_c["ductility_reduction_applied"] is True


def test_secondary_slab_cut_does_not_apply_primary_direction_minimum_formula():
    section, elements, materials = _rectangle()
    result = detailing.minimum_reinforcement(
        section,
        elements,
        materials,
        Concrete(30.0, gamma_c=1.5),
        edition=detailing.EC2_2005_DKNA,
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=100.0,
        my_ed_knm=0.0,
        member_type=detailing.MEMBER_SLAB,
        cut_direction=detailing.CUT_LONGITUDINAL,
    )
    assert result["status"] == "NOT ASSESSED"
    assert result["checks"] == []
    assert result["modelled_reinforcement_direction"] == "transverse"
    assert result["clause"] == "9.3.1.1(2)"
    assert "orthogonal primary reinforcement" in result["reason"]


def test_minimum_reinforcement_retains_the_modelled_direction_for_each_cut():
    section, elements, materials = _rectangle()
    common = dict(
        section=section,
        elements=elements,
        materials=materials,
        concrete=Concrete(30.0, gamma_c=1.5),
        edition=detailing.EC2_2005,
        fctm_mpa=2.9,
        n_ed_tension_kn=0.0,
        mx_ed_knm=100.0,
        my_ed_knm=0.0,
        member_type=detailing.MEMBER_BEAM,
    )
    transverse_cut = detailing.minimum_reinforcement(
        **common, cut_direction=detailing.CUT_TRANSVERSE
    )
    longitudinal_cut = detailing.minimum_reinforcement(
        **common, cut_direction=detailing.CUT_LONGITUDINAL
    )
    assert transverse_cut["modelled_reinforcement_direction"] == "longitudinal"
    assert longitudinal_cut["modelled_reinforcement_direction"] == "transverse"


def test_transverse_detailing_checks_shear_ratio_and_both_spacings():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005_DKNA,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
        shear_directions=[{
            "component": "vx",
            "bw_mm": 300.0,
            "d_mm": 550.0,
            "legs": 2.0,
            "transverse_leg_spacing_mm": 0.0,
        }],
    )
    checks = {check["kind"]: check for check in result["checks"]}
    assert result["status"] == "PASS"
    assert checks["minimum_ratio"]["provided"] == pytest.approx(
        2.0 * math.pi * 10.0 ** 2 / 4.0 / (150.0 * 300.0)
    )
    assert result["leg_area_mm2"] == pytest.approx(math.pi * 10.0 ** 2 / 4.0)
    assert checks["minimum_ratio"]["leg_area_mm2"] == pytest.approx(
        result["leg_area_mm2"]
    )
    assert checks["minimum_ratio"]["link_spacing_mm"] == pytest.approx(150.0)
    assert checks["longitudinal_spacing"]["limit"] == pytest.approx(412.5)
    assert checks["transverse_leg_spacing"]["provided"] == pytest.approx(300.0)
    assert checks["transverse_leg_spacing"]["spacing_limits_mm"] == pytest.approx(
        {"0.75 d": 412.5, "600 mm": 600.0}
    )
    assert checks["transverse_leg_spacing"]["governing_limit"] == "0.75 d"
    assert (
        checks["transverse_leg_spacing"]["spacing_source"]
        == "gross-web upper-bound screen"
    )


def test_transverse_detailing_requires_leg_distance_when_it_cannot_be_derived():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2023,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=32.0,
        spacing_mm=100.0,
        shear_directions=[{
            "component": "vy",
            "bw_mm": 200.0,
            "d_mm": 500.0,
            "legs": 1.0,
            "transverse_leg_spacing_mm": 0.0,
        }],
    )
    transverse = next(
        check for check in result["checks"]
        if check["kind"] == "transverse_leg_spacing"
    )
    assert result["status"] == "NOT ASSESSED"
    assert transverse["status"] == "NOT ASSESSED"
    assert "enter the maximum transverse distance" in transverse["reason"]


def test_three_or_more_legs_use_full_web_width_as_the_auto_upper_bound():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=16.0,
        spacing_mm=100.0,
        shear_directions=[{
            "component": "vy",
            "bw_mm": 600.0,
            "d_mm": 1000.0,
            "legs": 3.0,
            "transverse_leg_spacing_mm": 0.0,
        }],
    )
    transverse = next(
        check for check in result["checks"]
        if check["kind"] == "transverse_leg_spacing"
    )
    assert transverse["provided"] == pytest.approx(600.0)
    assert transverse["limit"] == pytest.approx(600.0)
    assert transverse["status"] == "PASS"
    assert transverse["spacing_source"] == "gross-web upper-bound screen"


def test_gross_web_upper_bound_cannot_create_a_definitive_spacing_failure():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005_DKNA,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
        shear_directions=[{
            "component": "vx",
            "bw_mm": 600.0,
            "d_mm": 305.0,
            "legs": 2.0,
            "transverse_leg_spacing_mm": 0.0,
            "measurement_axis": "y",
        }],
    )
    transverse = next(
        check for check in result["checks"]
        if check["kind"] == "transverse_leg_spacing"
    )
    assert result["status"] == "NOT ASSESSED"
    assert transverse["status"] == "NOT ASSESSED"
    assert transverse["provided"] == pytest.approx(600.0)
    assert transverse["limit"] == pytest.approx(0.75 * 305.0)
    assert transverse["utilisation"] is None
    assert transverse["measurement_axis"] == "y"
    assert "actual maximum centre-to-centre" in transverse["reason"]


def test_user_entered_transverse_spacing_can_create_a_definitive_failure():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005_DKNA,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
        shear_directions=[{
            "component": "vx",
            "bw_mm": 600.0,
            "d_mm": 305.0,
            "legs": 2.0,
            "transverse_leg_spacing_mm": 600.0,
            "measurement_axis": "y",
        }],
    )
    transverse = next(
        check for check in result["checks"]
        if check["kind"] == "transverse_leg_spacing"
    )
    assert result["status"] == "FAIL"
    assert transverse["status"] == "FAIL"
    assert transverse["spacing_source"] == "user"
    assert transverse["utilisation"] == pytest.approx(600.0 / (0.75 * 305.0))


def test_torsion_detailing_uses_one_closed_leg_and_perimeter_spacing():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
        torsion_tubes=[{
            "label": "Tube 1",
            "valid": True,
            "tef_mm": 100.0,
            "uk_mm": 2000.0,
            "minimum_dimension_mm": 300.0,
        }],
    )
    ratio, spacing = result["checks"]
    assert result["status"] == "PASS"
    assert ratio["provided"] == pytest.approx(
        math.pi * 10.0 ** 2 / 4.0 / (150.0 * 100.0)
    )
    assert spacing["limit"] == pytest.approx(250.0)
    assert spacing["governing_limit"] == "u_k/8"
    assert any(
        "350 mm" in note and "longitudinal torsion-bar" in note
        for note in result["limitations"]
    )


def test_torsion_spacing_is_not_restricted_by_shear_effective_depth():
    tube = {
        "valid": True,
        "tef_mm": 100.0,
        "uk_mm": 2000.0,
        "minimum_dimension_mm": 300.0,
    }
    common = dict(
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=16.0,
        spacing_mm=100.0,
        torsion_tubes=[tube],
    )
    old = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005,
        **common,
    )
    new = detailing.transverse_reinforcement(
        edition=detailing.EC2_2023,
        **common,
    )
    old_spacing = old["checks"][1]
    new_spacing = new["checks"][1]
    assert old_spacing["limit"] == pytest.approx(250.0)
    assert old_spacing["status"] == "PASS"
    assert new_spacing["limit"] == pytest.approx(250.0)
    assert new_spacing["status"] == "PASS"


def test_2005_torsion_spacing_needs_no_shear_effective_depth():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=16.0,
        spacing_mm=100.0,
        torsion_tubes=[{
            "valid": True,
            "tef_mm": 100.0,
            "uk_mm": 2000.0,
            "minimum_dimension_mm": 300.0,
        }],
    )
    spacing = result["checks"][1]
    assert result["status"] == "PASS"
    assert spacing["status"] == "PASS"
    assert spacing["limit"] == pytest.approx(250.0)


def test_slab_shear_uses_slab_transverse_leg_spacing_limit():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2023,
        member_type=detailing.MEMBER_SLAB,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=16.0,
        spacing_mm=100.0,
        shear_directions=[{
            "component": "vy",
            "bw_mm": 500.0,
            "d_mm": 200.0,
            "legs": 2.0,
            "transverse_leg_spacing_mm": 250.0,
        }],
    )
    checks = {check["kind"]: check for check in result["checks"]}
    assert result["member_type"] == detailing.MEMBER_SLAB
    assert checks["longitudinal_spacing"]["limit"] == pytest.approx(150.0)
    assert checks["transverse_leg_spacing"]["limit"] == pytest.approx(300.0)
    assert "Table 12.2" in checks["transverse_leg_spacing"]["clause"]


def test_slab_does_not_apply_beam_torsion_link_provisions():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005,
        member_type=detailing.MEMBER_SLAB,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=16.0,
        spacing_mm=100.0,
        torsion_tubes=[{
            "valid": True,
            "tef_mm": 100.0,
            "uk_mm": 2000.0,
            "minimum_dimension_mm": 300.0,
        }],
    )
    assert result["status"] == "NOT ASSESSED"
    assert all(check["status"] == "NOT ASSESSED" for check in result["checks"])
    assert all("beam torsion" in check["reason"] for check in result["checks"])


def test_missing_required_shear_links_is_a_visible_failure():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005_DKNA,
        member_type=detailing.MEMBER_SLAB,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
        shear_directions=[{
            "component": "vx",
            "links_present": False,
            "links_required": True,
            "requirement_clause": "6.2.2",
        }],
    )
    assert result["status"] == "FAIL"
    assert result["checks"][0]["kind"] == "required_links"
    assert result["checks"][0]["clause"] == "6.2.2"


def test_ordinary_beam_requires_minimum_links_for_any_active_shear():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005_DKNA,
        member_type=detailing.MEMBER_BEAM,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
        shear_directions=[{
            "component": "vx",
            "links_present": False,
            "links_required": False,
        }],
    )
    assert result["status"] == "FAIL"
    check = result["checks"][0]
    assert check["kind"] == "required_links"
    assert check["clause"] == "9.2.2(2), (5)"
    assert "minimum shear reinforcement" in check["reason"]


def test_2023_beam_no_link_applicability_respects_depth_and_system_scope():
    common = dict(
        edition=detailing.EC2_2023,
        member_type=detailing.MEMBER_BEAM,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
    )
    shallow = detailing.transverse_reinforcement(
        **common,
        shear_directions=[{
            "component": "vx",
            "links_present": False,
            "links_required": False,
            "d_mm": 500.0,
        }],
    )
    deep = detailing.transverse_reinforcement(
        **common,
        shear_directions=[{
            "component": "vx",
            "links_present": False,
            "links_required": False,
            "d_mm": 501.0,
        }],
    )
    assert shallow["status"] == "NOT APPLICABLE"
    assert shallow["checks"] == []
    assert deep["status"] == "NOT ASSESSED"
    check = deep["checks"][0]
    assert check["kind"] == "minimum_link_applicability"
    assert check["clause"] == "8.2.1(2), 12.2(4)"
    assert "statically determinate" in check["reason"]


def test_absent_unnecessary_shear_links_are_not_a_detailing_action():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005_DKNA,
        member_type=detailing.MEMBER_SLAB,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
        shear_directions=[{
            "component": "vx",
            "links_present": False,
            "links_required": False,
        }],
    )
    assert result["status"] == "NOT APPLICABLE"
    assert result["checks"] == []


def test_transverse_detailing_with_no_active_action_is_not_applicable():
    result = detailing.transverse_reinforcement(
        edition=detailing.EC2_2005_DKNA,
        fck_mpa=30.0,
        fywk_mpa=500.0,
        diameter_mm=10.0,
        spacing_mm=150.0,
    )
    assert result["status"] == "NOT APPLICABLE"
    assert result["checks"] == []
