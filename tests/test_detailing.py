"""Independent checks for longitudinal detailing and bar clear spacing."""

import math

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
    assert checks["longitudinal_spacing"]["limit"] == pytest.approx(412.5)
    assert checks["transverse_leg_spacing"]["provided"] == pytest.approx(300.0)
    assert checks["transverse_leg_spacing"]["spacing_source"] == "conservative auto"


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
    assert transverse["spacing_source"] == "conservative auto"


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
