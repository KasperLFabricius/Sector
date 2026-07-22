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
            "spacing_group_id": "",
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
            "spacing_group_id": "",
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
            "spacing_group_id": "",
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


def _spacing_elements(clear_mm, *, group=""):
    phi = 20.0
    return [
        {
            "id": "R1",
            "kind": "bar",
            "x_mm": 0.0,
            "y_mm": 0.0,
            "diameter_mm": phi,
            "spacing_group_id": group,
        },
        {
            "id": "R2",
            "kind": "bar",
            "x_mm": phi + clear_mm,
            "y_mm": 0.0,
            "diameter_mm": phi,
            "spacing_group_id": group,
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


def test_clear_spacing_distinguishes_failure_from_declared_exception():
    failed = detailing.clear_spacing(
        _spacing_elements(10.0),
        d_upper_mm=16.0,
        edition=detailing.EC2_2005_DKNA,
    )
    review = detailing.clear_spacing(
        _spacing_elements(10.0, group="L1"),
        d_upper_mm=16.0,
        edition=detailing.EC2_2005_DKNA,
    )
    assert failed["status"] == "FAIL"
    assert review["status"] == "REVIEW"
    assert review["governing"]["declared_exception"] is True


def test_clear_spacing_excludes_tendons_unless_their_envelope_is_selected():
    elements = _spacing_elements(25.0)
    elements.append(
        {
            "id": "P1",
            "kind": "tendon",
            "x_mm": 5.0,
            "y_mm": 0.0,
            "diameter_mm": 10.0,
            "spacing_group_id": "",
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
