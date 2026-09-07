"""Real native member bundles used to qualify publication and report routes."""
from __future__ import annotations

import copy
import pickle

import pytest

from test_torsion import _fresh, _set, _set_and_click


@pytest.fixture(scope="module")
def native_formula_631_cases(tmp_path_factory):
    """Copy complete native screen bundles, cached by every varied input.

    This reuses producer results across profiles, not publication decisions.
    Every consumer still traverses the ordinary currentness and report gates.
    """
    import result_presentation as presentation
    from sector import codes
    from test_torsion import _apply_box_section, _subdivided

    destination = tmp_path_factory.mktemp("native-formula-631")
    applications = {}
    cases = {}
    with pytest.MonkeyPatch.context() as patch:
        def produce(
            *, scope_context="rectangle", n_ed=0.0, mx_ed=0.0, my_ed=0.0,
            condition_status="PASS", detailing_status="NOT RUN",
        ):
            assert scope_context in {
                "rectangle", "nonrectangular", "hollow", "subdivided",
                "unavailable-shear", "selected-2023", "selected-2023-no-shear",
            }
            assert condition_status in {"PASS", "FAIL"}
            assert detailing_status in {"PASS", "FAIL", "NOT RUN"}
            key = (scope_context, n_ed, mx_ed, my_ed,
                   condition_status, detailing_status)
            if key not in cases:
                patch.setenv("SECTOR_AUTOSAVE_DIR", str(destination / scope_context))
                if scope_context not in applications:
                    at = _fresh().run()
                    if scope_context == "nonrectangular":
                        at.session_state["_qs_open"] = True
                        at.run()
                        _set(at, ("selectbox", "shape", "Circular"))
                        _set_and_click(at, "qs_apply")
                    elif scope_context == "hollow":
                        _apply_box_section(at)
                    elif scope_context == "subdivided":
                        _subdivided(at, T=1.0)
                    _set(at, ("checkbox", "shear_on", True),
                         ("checkbox", "torsion_on", True),
                         ("checkbox", "shear_links", True))
                    # Fix the retained link inputs even for links-off cases;
                    # their bundle must not depend on which case ran first.
                    _set(at, ("number_input", "shear_link_dia", 16.0),
                         ("number_input", "shear_link_s", 100.0))
                    _set(
                        at,
                        ("selectbox", "shear_method", (
                            codes.EC2_2023.label
                            if scope_context.startswith("selected-2023")
                            else codes.EC2_2005_DKNA.label
                        )),
                        ("selectbox", "torsion_method", codes.EC2_2005_DKNA.label),
                    )
                    if scope_context == "subdivided":
                        _set(at,
                             ("selectbox", "shear_section_form", "Constant-width web"),
                             ("number_input", "shear_bw", 300.0))
                    applications[scope_context] = at
                at = applications[scope_context]
                shear_on = scope_context not in {
                    "unavailable-shear", "selected-2023-no-shear",
                }
                links_present = detailing_status == "PASS"
                _set(
                    at,
                    ("checkbox", "shear_on", shear_on),
                    ("checkbox", "combined_on", False),
                    ("checkbox", "transverse_detailing_on", detailing_status != "NOT RUN"),
                    ("checkbox", "shear_links", links_present),
                )
                changes = [
                    ("number_input", "pl_P", n_ed),
                    ("number_input", "pl_Mx", mx_ed),
                    ("number_input", "pl_My", my_ed),
                    ("number_input", "torsion_T", 1.0 if condition_status == "PASS" else 60.0),
                ]
                if shear_on:
                    changes.append(("number_input", "shear_V", 5.0 if condition_status == "PASS" else 200.0))
                if links_present:
                    changes.extend((
                        ("number_input", "shear_link_dia", 16.0),
                        ("number_input", "shear_link_s", 100.0),
                    ))
                _set_and_click(at, "calculate", *changes)
                assert not at.exception
                inp = copy.deepcopy(at.session_state["result_input_snapshot"])
                out = copy.deepcopy(at.session_state["results"])
                assert (inp["P_pl"], inp["Mx_pl"], inp["My_pl"]) == (n_ed, mx_ed, my_ed)
                assert inp["combined_on"] is False
                minimum = out["torsion"]["min_reinf"]
                assert (minimum["n_ed"], minimum["mx_ed"], minimum["my_ed"]) == (n_ed, mx_ed, my_ed)
                if scope_context == "rectangle" and not any((n_ed, mx_ed, my_ed)):
                    assert minimum["status"] == condition_status
                    assert minimum["detailing_status"] == detailing_status
                    assert minimum["value"] == pytest.approx(
                        minimum["t_ed"] / minimum["trd_c"]
                        + minimum["v_ed"] / minimum["vrd_c"]
                    )
                (destination / f"case-{len(cases):03d}.pickle").write_bytes(
                    pickle.dumps((key, inp, out))
                )
                cases[key] = inp, out
            inp, out = copy.deepcopy(cases[key])
            current, reason = presentation.torsion_publication_component_is_current(
                inp, out.get("shear"), out["torsion"],
            )
            assert current is True, reason
            return inp, out

        yield produce


@pytest.fixture(scope="module")
def native_member_report_cases(tmp_path_factory):
    destination = tmp_path_factory.mktemp("native-member-reports")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SECTOR_AUTOSAVE_DIR", str(destination / "autosave"))
        at = _fresh().run()
        _set(
            at,
            ("checkbox", "shear_on", True),
            ("checkbox", "torsion_on", True),
            ("checkbox", "shear_links", True),
            ("checkbox", "combined_on", True),
        )
        cases = {}
        for name, mx, my, shear_force, torque in (
            # A definite current failure lets the legacy-origin test demonstrate
            # suppression of an assessed Combined cell on both physical faces.
            ("two-face", 0.0, 0.0, 30.0, 180.0),
            # Orthogonal bending makes the shifted x-face non-governing, so its
            # preserved pure-axis substitute cannot hide behind the selected face.
            ("biaxial", 40.0, 100.0, 150.0, 40.0),
        ):
            _set_and_click(
                at, "calculate",
                ("number_input", "pl_Mx", mx),
                ("number_input", "pl_My", my),
                ("number_input", "shear_Vy", shear_force),
                ("number_input", "torsion_T", torque),
            )
            assert not at.exception
            inp = copy.deepcopy(at.session_state["result_input_snapshot"])
            out = copy.deepcopy(at.session_state["results"])
            assert out["plastic"]["util_valid"] is True
            assert out["torsion"]["valid"] is True
            assert out["shear"]["links"]["res"]["valid"] is True
            (destination / (name + ".pickle")).write_bytes(pickle.dumps((inp,out)))
            cases[name] = (inp,out)
        yield cases


@pytest.fixture(scope="module")
def native_base_en_report_case(tmp_path_factory):
    """Return a complete single-direction Base-EN native publication bundle."""
    from sector import codes

    destination = tmp_path_factory.mktemp("native-base-en-report")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SECTOR_AUTOSAVE_DIR", str(destination / "autosave"))
        at = _fresh().run()
        _set(
            at,
            ("checkbox", "shear_on", True),
            ("checkbox", "torsion_on", True),
            ("checkbox", "shear_links", True),
            ("checkbox", "combined_on", True),
        )
        _set(at, ("checkbox", "combined_mv_independent", True))
        _set(at, ("selectbox", "combined_method", codes.EC2_2005.label))
        _set_and_click(
            at, "calculate",
            ("number_input", "pl_P", 0.0),
            ("number_input", "pl_Mx", 100.0),
            ("number_input", "pl_My", 0.0),
            ("number_input", "shear_Vx", 0.0),
            ("number_input", "shear_Vy", 150.0),
            ("number_input", "torsion_T", 40.0),
        )
        assert not at.exception
        inp = copy.deepcopy(at.session_state["result_input_snapshot"])
        out = copy.deepcopy(at.session_state["results"])
        (destination / "base-en.pickle").write_bytes(pickle.dumps((inp, out)))
        assert inp["combined_method"] == codes.EC2_2005.label
        assert inp["combined_mv_independent"] is True
        assert (inp["P_pl"], inp["Mx_pl"], inp["My_pl"]) == (0.0, 100.0, 0.0)
        for family in ("shear", "torsion", "combined"):
            assert out[family]["method"] == codes.EC2_2005.label
        return inp, out


@pytest.fixture(scope="module")
def native_subdivided_report_case(tmp_path_factory):
    from test_torsion import _subdivided

    destination = tmp_path_factory.mktemp("native-subdivided-report")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SECTOR_AUTOSAVE_DIR", str(destination / "autosave"))
        at = _fresh().run()
        _set(at, ("checkbox", "shear_on", True),
             ("checkbox", "shear_links", True),
             ("number_input", "shear_V", 150.0))
        # A definite overload is eligible for a worked example while per-tube
        # longitudinal reserve/allocation remains unverified.
        _subdivided(at, T=180.0)
        _set(at, ("selectbox", "shear_section_form", "Constant-width web"),
             ("number_input", "shear_bw", 300.0))
        _set_and_click(at, "calculate", ("checkbox", "combined_on", True),
                       ("number_input", "pl_Mx", 100.0))
        assert not at.exception
        inp = copy.deepcopy(at.session_state["result_input_snapshot"])
        out = copy.deepcopy(at.session_state["results"])
        assert out["plastic"]["util_valid"] is True
        assert out["torsion"]["valid"] is True and out["torsion"]["subdivided"] is True
        (destination / "subdivided.pickle").write_bytes(pickle.dumps((inp, out)))
        assert out["torsion"]["assessment_status"] == "FAIL"
        longitudinal = out["torsion"]["longitudinal_assessment"]
        assert longitudinal["status"] == "FAIL"
        assert longitudinal["ok"] is False
        assert longitudinal["reason"] == "longitudinal_torsion_reinforcement_insufficient"
        assert longitudinal["area_sufficient"] is False
        assert longitudinal["required_design_force_kn"] > longitudinal["provided_design_force_kn"]
        assert all(longitudinal[key] is False for key in (
            "distribution_verified", "all_perimeter_sides_verified", "bending_reserve_verified",
            "anchorage_verified", "tube_allocation_verified",
        ))
        assert len(out["torsion"]["subtubes"]) == 2
        assert out["shear"]["res"]["valid"] is True
        return inp, out
