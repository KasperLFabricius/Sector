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



@pytest.fixture(scope="module")
def native_axial_compression_report_cases(tmp_path_factory):
    """Native 2023 linked-shear cases with unavailable compression web force."""
    from sector import capacity, codes
    import result_presentation as presentation

    destination = tmp_path_factory.mktemp("native-shear-compression")
    cases = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SECTOR_AUTOSAVE_DIR", str(destination / "autosave"))
        at = _fresh().run()
        _set(
            at, ("checkbox", "shear_on", True),
            ("selectbox", "shear_method", codes.EC2_2023.label),
            ("checkbox", "shear_links", True),
        )

        def produce(*, biaxial):
            if biaxial not in cases:
                _set_and_click(
                    at, "calculate",
                    ("checkbox", "torsion_on", False),
                    ("checkbox", "combined_on", False),
                    ("number_input", "pl_P", -800.0),
                    ("number_input", "pl_Mx", 0.0),
                    ("number_input", "pl_My", 0.0),
                    ("number_input", "shear_Vy", 50.0),
                    ("number_input", "shear_Vx", 25.0 if biaxial else 0.0),
                )
                assert not at.exception
                inp = copy.deepcopy(at.session_state["result_input_snapshot"])
                out = copy.deepcopy(at.session_state["results"])
                assert inp["P_pl"] == -800.0
                assert inp["shear_method"] == codes.EC2_2023.label
                assert inp["shear_links"] is True
                aggregate = out["shear"]
                assert presentation.shear_publication_input_is_current(
                    inp, aggregate, plastic_result=out.get("plastic"),
                )[0] is True
                children = aggregate["directions"] if biaxial else {"vy": aggregate}
                for component, child in children.items():
                    assert child["n_ed_comp"] == 800.0
                    assert capacity.validated_signed_shear_demand(child) == (50.0 if component == "vy" else 25.0)
                    assert child["links"]["res"]["valid"] is False
                    assert child["links"]["res"]["calculation_state"] == "NOT ASSESSED"
                    assert child["links"]["res"]["vrd"] is None
                    assert child["links"]["util"] is None
                (destination / ("biaxial.pickle" if biaxial else "single.pickle")).write_bytes(
                    pickle.dumps((inp, out))
                )
                cases[biaxial] = inp, out
            return copy.deepcopy(cases[biaxial])
        yield produce



@pytest.fixture(scope="module")
def native_scheduler_report_cases(native_base_en_report_case, tmp_path_factory):
    """Recalculate canonical named-case matrices through the actual producer."""
    import case_analysis
    import result_presentation as presentation
    import sector_app
    from sector import capacity, codes

    destination = tmp_path_factory.mktemp("native-scheduler-report")
    seed, seed_out = copy.deepcopy(native_base_en_report_case)
    original_seed = pickle.dumps((seed, seed_out))
    cache = {}

    def record(name, mx, my, vx, vy, torque):
        return {
            "name": name, "description": name, "n_ed_kn": 0.0,
            "mx_ed_knm": mx, "my_ed_knm": my,
            "vx_ed_kn": vx, "vy_ed_kn": vy,
            "vx_face": "auto", "vy_face": "auto", "t_ed_knm": torque,
            "check_minimum_reinforcement": False,
        }

    matrices = {
        "base-en": (codes.EC2_2005.label, [
            record("PL-LOW", 80, 0, 0, 20, 120),
            record("PL-GOV", 80, 0, 0, 80, 180),
            record("PL-INCOMPLETE", 80, 0, 30, 25, 15),
        ]),
        "dkna": (codes.EC2_2005_DKNA.label, [
            record("PL-LOW", 40, 0, 20, 30, 120),
            record("PL-GOV", 100, 30, 45, 80, 180),
        ]),
        "authority": (codes.EC2_2005_DKNA.label, [
            record("PL-BLOCKED", 0, 0, 0, 30, -180),
            record("PL-APPLICABLE", 0, 0, 0, 30, 180),
        ]),
        "independent-subchecks": (codes.EC2_2005_DKNA.label, [
            record("PL-A", 0, 0, 0, 80, 180),
            record("PL-B", 400, 0, 0, 20, 180),
        ]),
        "authority-labels": (codes.EC2_2005_DKNA.label, [
            record("EQ-01", 0, 0, 0, 30, 40),
            record("COMP-01", 0, 0, 0, 30, -40),
        ]),
    }

    def produce(group):
        assert group in matrices
        if group not in cache:
            method, records = matrices[group]
            inp = copy.deepcopy(seed)
            inp.update(
                mode="Plastic", plastic_cases=copy.deepcopy(records), elastic_cases=[],
                combined_on=True, shear_on=True, torsion_on=True, shear_links=True,
                combined_method=method, shear_method=method, torsion_method=method,
                combined_mv_independent=False,
            )
            inp[capacity.TORSION_CASE_AUTHORITIES_KEY] = {
                row["name"]: {
                    capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                        capacity.TORSION_DESIGN_COMPATIBILITY_MEMBER
                        if row["name"] in {"PL-BLOCKED", "COMP-01"}
                        else capacity.TORSION_DESIGN_EQUILIBRIUM
                    ),
                    capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
                } for row in records
            }
            before_input = pickle.dumps(inp)
            out = case_analysis.run_case_tables(inp, sector_app._run_single_analysis)
            assert pickle.dumps(inp) == before_input
            out["worked_example_selection"] = presentation.worked_example_selection(inp, out)
            with presentation.publication_calculation_scope():
                contexts = presentation._worked_case_contexts(inp, out, "combined")
                assert [item[0] for item in contexts] == [row["name"] for row in records]
                for case_id, case_inp, case_out, current in contexts:
                    assert current is True, case_id
                    sh, torsion = case_out["shear"], case_out["torsion"]
                    assert presentation.shear_publication_input_is_current(
                        case_inp, sh, plastic_result=case_out["plastic"], torsion_result=torsion,
                    ) == (True, None)
                    torsion_current = presentation.torsion_publication_component_is_current(
                        case_inp, sh, torsion,
                    )
                    if case_id in {"PL-BLOCKED", "COMP-01"}:
                        # Canonical row identity is current, while compatibility
                        # torsion intentionally has no sectional result authority.
                        assert group in {"authority", "authority-labels"}
                        assert torsion_current == (False, "torsion result evidence is unavailable")
                        assert presentation.torsion_applicability_publication_status(torsion) == "NOT ASSESSED"
                        assert presentation._transverse_metric(
                            "torsion", torsion, input_payload=case_inp, shear_result=sh,
                        ) is None
                        assert "Compatibility torsion requires a separate member or system assessment" in presentation.combined_bending_assessment_blocker(case_out, case_inp)
                    else:
                        assert torsion_current == (True, None)
                    assert presentation.combined_publication_evidence_is_current(
                        case_inp, case_out,
                    ) == (True, None)
            (destination / (group + ".pickle")).write_bytes(pickle.dumps((inp, out)))
            cache[group] = inp, out
        assert pickle.dumps((seed, seed_out)) == original_seed
        return copy.deepcopy(cache[group])
    return produce
