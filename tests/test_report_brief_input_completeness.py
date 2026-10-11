"""Independent engineering-input completeness checks for Brief reports."""
from __future__ import annotations

import html
import ast
import math
import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import sector_report
from report_profiles import BRIEF_PROFILE, STANDARD_PROFILE, AUDIT_PROFILE
from tools.report_render_fixture import _inputs
from sector import templates
from sector.materials import Prestress
from sector.engineer_message import EngineerMessage
import fatigue_inputs
from sector.shear_inputs import SHEAR_SECTION_VARIABLE, SHEAR_SECTION_CIRCULAR, SHEAR_DUCT_GROUTED_STEEL


def _capture(inp, *, result_values=None, profile=BRIEF_PROFILE):
    builder = object.__new__(sector_report.ReportBuilder)
    builder.inp = builder._base_inp = inp
    builder.out = builder._base_out = {}
    builder.profile = profile
    builder.flow = []
    captured = []
    builder._captured_tables = []
    def text(value, **kwargs):
        captured.append(str(value))
        builder.flow.append(SimpleNamespace(keepWithNext=0))
    def table(rows, *args, **kwargs):
        builder._captured_tables.append((kwargs.get("caption", ""), rows))
        captured.extend(str(cell) for row in rows for cell in row)
        captured.append(str(kwargs.get("caption", "")))
    builder._h1 = builder._h2 = builder._small = text
    builder._table = table
    builder._result_values = lambda key: (result_values or {}).get(key, [])
    builder._project_source_register = lambda: None
    return builder, lambda: html.unescape(re.sub(r"<[^>]*>", "", "\n".join(captured)))


@pytest.mark.parametrize("key,value", [
    ("shear_vx_web_inclination_deg", 17.3), ("shear_vy_web_inclination_deg", 23.7),
    ("shear_hoop_diameter", 617.3), ("shear_vx_fitted_z", 413.7),
    ("shear_vy_fitted_z", 327.9), ("shear_vx_duct_sum", 117.3),
    ("shear_vy_duct_sum", 123.7), ("shear_vx_duct_largest", 67.3),
    ("shear_vy_duct_largest", 63.7)])
def test_brief_publishes_active_directional_shear_geometry_inputs(key, value):
    inp = _inputs()
    inp[key] = value
    inp["shear_section_form"] = (SHEAR_SECTION_CIRCULAR if key in {
        "shear_hoop_diameter", "shear_vx_fitted_z", "shear_vy_fitted_z"} else SHEAR_SECTION_VARIABLE)
    inp["shear_duct_case"] = SHEAR_DUCT_GROUTED_STEEL
    builder, text = _capture(inp)
    builder._brief_settings_summary()
    numbers = [float(item) for item in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", text())]
    assert value in numbers, f"Brief omits {key}={value}"


@pytest.mark.parametrize("key,value", [
    ("shear_section_form", "Circular section"),
    ("shear_duct_case", "Grouted steel ducts")])
def test_brief_publishes_selected_shear_geometry_method(key, value):
    inp = _inputs(); inp[key] = value
    builder, text = _capture(inp)
    builder._brief_settings_summary()
    assert value in text()


def test_brief_requested_unrun_cases_retain_numerical_and_elastic_inputs():
    inp = _inputs(); inp["fatigue_on"] = False
    builder, text = _capture(inp)
    builder._brief_settings_summary()
    for required in ("sweep", "Creep coefficient", "elastic modulus", "tensile strength"):
        assert required.lower() in text().lower(), required


def test_brief_requested_dk_member_input_is_retained_before_cracking_result():
    inp = _inputs(); inp.update(sls_member="Slab", sls_cw=True, fatigue_on=False)
    builder, text = _capture(inp)
    builder._brief_settings_summary()
    assert "Slab" in text()


def test_brief_nonfirst_unrun_case_cracking_request_retains_crack_settings():
    inp = _inputs(); inp.update(sls_cw=False, sls_heightened_on=False, fatigue_on=False)
    inp["elastic_cases"][0]["calculate_crack_width"] = False
    inp["elastic_cases"][1]["calculate_crack_width"] = True
    builder, text = _capture(inp, result_values={"elastic": [{"show_cw": False}]})
    builder._brief_settings_summary()
    assert "Crack-width diameter" in text()
    assert "Mild-steel bond" in text()


@pytest.mark.parametrize("profile", [BRIEF_PROFILE, STANDARD_PROFILE, AUDIT_PROFILE], ids=lambda p: p.key)
def test_direct_api_fatigue_spectrum_keeps_every_bin_and_action(profile):
    inp = _inputs()
    inp.pop("plastic_cases"); inp.pop("elastic_cases")
    builder, text = _capture(inp, profile=profile)
    builder._loads_block()
    for required in ("Road traffic", "FAT-QA-H", "FAT-QA-M", "100000", "1000000"):
        assert required in text(), required


def test_brief_named_nongoverning_and_unrun_actions_are_all_published():
    inp = _inputs()
    builder, text = _capture(inp)
    builder._brief_actions_summary()
    for required in ("PL-QA-1", "PL-QA-2", "EL-QA-1", "EL-QA-2", "FAT-QA-H", "FAT-QA-M"):
        assert required in text()
    for value in ("125.000", "90.000", "25.000", "100000.000", "1000000.000"):
        assert value in text()


def test_brief_assigned_mixed_materials_and_fatigue_detail_are_published_without_results():
    inp = _inputs()
    builder, text = _capture(inp)
    builder._brief_geometry_summary()
    builder._brief_material_summary()
    builder._brief_settings_summary()
    for required in ("M1", "M2", "235.000", "550.000", "F1", "Fatigue detail", "gamma", "bend reduction"):
        assert required.casefold() in text().casefold()


def test_brief_default_auto_dimensions_and_selected_member_options_remain_explicit():
    inp = _inputs()
    builder, text = _capture(inp)
    builder._brief_settings_summary()
    for required in ("auto / derived", "Compression-strut", "Minimum reinforcement", "Clear-spacing", "Detailing edition", "Torsion method"):
        assert required in text()


def _native_density_inputs():
    inp = _inputs()
    # Use the native pure layout producer, without starting Streamlit.
    source = ROOT / "app/sector_app.py"
    names = {"_slab_density_layout", "_slab_face_clear_cover_mm"}
    nodes = [node for node in ast.parse(source.read_text(encoding="utf-8")).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    import numpy as np
    namespace = {"math": math, "np": np, "templates": templates, "_MM": 1000.}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    layout = namespace["_slab_density_layout"](
        height_m=.3, cover_to_edge=True, bottom_diameter_mm=20., top_diameter_mm=20.,
        bottom_cover_m=.0373, top_cover_m=.05, bottom_spacing_m=.173,
        top_spacing_m=.187, bottom_layers=2, top_layers=1, layer_spacing_m=.05,
        bottom_interleave_diameter_mm=16.)
    inp["slab_density"] = dict(layout, status="VERIFIED", reason=None)
    inp["outer"] = templates.rectangle(1., .3)
    inp["bars"] = layout["bars"]
    inp["bar_elements"] = [dict(id=f"R{i+1}", x_mm=x*1000, y_mm=y*1000,
        area_mm2=area, diameter_mm=layout["diameters_mm"][i], size_mode="Independent",
        material_id="M1", fatigue_detail_id="F1") for i,(x,y,area) in enumerate(layout["bars"])]
    return inp


def test_brief_slab_density_physical_basis_is_published():
    inp = _native_density_inputs()
    builder, text = _capture(inp)
    builder._brief_geometry_summary()
    assert "density" in text().lower()
    for required in ("173", "37.3", "86.5", "Interleave"):
        assert required in text(), required


@pytest.mark.parametrize("profile", [BRIEF_PROFILE, STANDARD_PROFILE, AUDIT_PROFILE], ids=lambda p: p.key)
def test_density_group_identity_and_tributary_meaning_are_retained(profile):
    inp = _native_density_inputs()
    builder, text = _capture(inp, profile=profile)
    builder._slab_density_input_tables()
    tables = dict(builder._captured_tables)
    cover = tables["Physical cover and spacing by layer"]
    physical = tables["Nominal physical bar positions for the slab strip"]
    assert "Spacing group" in cover[0]
    assert "Spacing group" in physical[0]
    assert "Tributary area" in physical[0][-1]
    assert "Bar equivalents" in tables["Slab-density series definitions"][0][5]
    assert "strip cuts" in text() and "partial area weights" in text()
    expected_metadata = set()
    for row in inp["slab_density"]["analysis_metadata"]:
        expected_metadata.add((row["face"], row["role"], row["layer"], row["spacing_group"],
                               f'{row["cover_mm"]:.3f}', f'{row["nominal_spacing_mm"]:.3f}'))
    assert {tuple(row) for row in cover[1:]} == expected_metadata
    expected_physical = [(r["id"], r["spacing_group"], f'{r["x_mm"]:.3f}',
                          f'{r["y_mm"]:.3f}', f'{r["diameter_mm"]:.3f}', f'{r["area_mm2"]:.3f}')
                         for r in inp["slab_density"]["physical_elements"]]
    assert [tuple(row) for row in physical[1:]] == expected_physical


def test_brief_retains_fractional_sweep_inputs():
    inp = _inputs(); inp.update(v_min=12.5, v_max=327.5, v_inc=7.5)
    builder, text = _capture(inp, result_values={"plastic": [{"check_util": True}]})
    builder._brief_settings_summary()
    for value in ("12.5", "327.5", "7.5"):
        assert value in text(), value


@pytest.mark.parametrize("profile", [BRIEF_PROFILE, STANDARD_PROFILE, AUDIT_PROFILE], ids=lambda p: p.key)
def test_requested_unrun_direct_actions_are_retained(profile):
    inp = _inputs()
    inp.pop("plastic_cases"); inp.pop("elastic_cases")
    inp.update(shear_on=False, torsion_on=False, combined_on=False,
               P_pl=113.7, Mx_pl=67.9, My_pl=-43.1,
               P_el_l=27.3, Mx_el_l=31.7, My_el_l=-9.3,
               P_el_s=13.7, Mx_el_s=-17.9, My_el_s=6.7)
    builder, text = _capture(inp, profile=profile)
    builder._loads_block()
    for value in ("113.700", "67.900", "-43.100", "27.300", "31.700", "-9.300", "13.700", "-17.900", "6.700"):
        assert value in text(), value


def test_brief_requested_methods_remain_visible_without_results():
    inp = _inputs()
    builder, text = _capture(inp)
    builder._method_register()
    for label in ("Elastic and ordinary crack width", "Minimum reinforcement", "Shear", "Torsion", "Combined actions", "Fatigue"):
        assert label in text(), label


def test_brief_tendon_assignments_prestrain_and_fatigue_modifiers_are_complete():
    inp = _inputs()
    laws = {
        "P1": Prestress(curve=1, IS=.0037, Es=190000., gamma_y=1.13),
        "P2": Prestress(curve=7, IS=.0043, Es=195000., fytk=1437., futk=1749.,
                        eut=.04, gamma_y=1.17, gamma_u=1.19, gamma_E=1.03,
                        k=.85, ey0t=.0012)}
    inp.update(tendons=[(0., -.1, 143.), (0., .1, 177.)], prestress=laws["P1"],
               prestress_materials=laws, tendon_materials=list(laws.values()),
               prestress_material_catalog={"items": [
                   {"id": "P1", "name": "Fixed tendon law", "fytk": 1421.},
                   {"id": "P2", "name": "Project tendon law"}]},
               tendon_elements=[dict(id=f"T{i+1}", x_mm=0., y_mm=y*1000,
                   area_mm2=area, diameter_mm=15., size_mode="Area", material_id=f"P{i+1}",
                   fatigue_detail_id="F2") for i,(_,y,area) in enumerate([(0.,-.1,143.),(0.,.1,177.)])])
    detail = fatigue_inputs.default_entry(detail_id="F2", preset=fatigue_inputs.PRESET_2005_PLASTIC_STRAND)
    detail.update(bond_ratio_xi=.47, bond_equivalent_diameter_mm=11.3,
                  bend_reduction=True, mandrel_diameter_mm=213.)
    inp[fatigue_inputs.DETAIL_CATALOG_KEY]["items"].append(detail)
    builder, text = _capture(inp)
    builder._brief_geometry_summary(); builder._brief_material_summary(); builder._brief_settings_summary()
    for required in ("P1", "P2", "T1", "T2", "3.700", "4.300", "1421.000",
                     "1437.000", "1749.000", "1.170", "1.190", "1.030", "0.850",
                     "1.200", "0.470", "11.300", "213.000"):
        assert required in text(), required


def _native_slab_guidance():
    source = ROOT / "app/sector_app.py"
    assignments = [node for node in ast.parse(source.read_text(encoding="utf-8")).body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "_SLAB_DENSITY_GUIDANCE"
                           for target in node.targets)]
    assert len(assignments) == 1
    return ast.literal_eval(assignments[0].value)


@pytest.mark.parametrize("reason", [
    "native",
    EngineerMessage("SLAB-COVER-CHECK", "Check the bottom reinforcement cover before use."),
])
def test_unverified_density_publishes_trusted_guidance_and_suppresses_physical_schedule(reason):
    inp = _inputs()
    reason = _native_slab_guidance() if reason == "native" else reason
    inp["slab_density"] = {"status": "UNVERIFIED", "reason": reason,
                           "physical_elements": [{"id": "STALE-BAR-POSITION"}]}
    builder, text = _capture(inp)
    builder._slab_density_input_tables()
    assert "UNVERIFIED" in text()
    if isinstance(reason, EngineerMessage):
        assert reason.text in text()
    else:
        assert "Reapply the slab layout" in text()
        assert "explicit bars" in text()
    assert "STALE-BAR-POSITION" not in text()
    assert "Nominal physical bar positions" not in text()


@pytest.mark.parametrize("reason", [
    "Traceback: secret local path C:/private/schema.py", "Unexpected layout detail",
    {"text": "Untrusted structured reason"}, None,
])
def test_unverified_density_unknown_reason_has_authored_guidance(reason):
    inp = _inputs()
    inp["slab_density"] = {"status": "UNVERIFIED", "reason": reason,
                           "physical_elements": [{"id": "STALE-BAR-POSITION"}]}
    builder, text = _capture(inp)
    builder._slab_density_input_tables()
    if reason is not None:
        assert str(reason) not in text()
    assert "STALE-BAR-POSITION" not in text()
    assert any(word in text().lower() for word in ("verify", "check", "reapply"))


@pytest.mark.parametrize("key,bad_rows", [
    ("series", [None]), ("analysis_metadata", [None]),
    ("physical_elements", [None]), ("series", {"face": "Bottom"})])
def test_malformed_density_records_produce_explicit_diagnostic(key, bad_rows):
    inp = _inputs()
    inp["slab_density"] = {"status": "VERIFIED", key: bad_rows}
    builder, text = _capture(inp)
    builder._slab_density_input_tables()
    assert any(word in text().lower() for word in ("unavailable", "malformed", "incomplete", "invalid"))


def test_circular_required_dimensions_are_not_described_as_automatic():
    inp = _inputs()
    inp.update(shear_section_form=SHEAR_SECTION_CIRCULAR,
               shear_hoop_diameter=0., shear_vx_fitted_z=0., shear_vy_fitted_z=0.)
    builder, _ = _capture(inp)
    rows = builder._shear_geometry_input_rows()
    dimensions = [str(value) for label, value in rows
                  if "hoop diameter" in label or "fitted lever arm" in label]
    assert len(dimensions) == 3
    assert all("auto" not in value.lower() for value in dimensions)
    assert all("0.000" in value or any(word in value.lower() for word in ("required", "not established", "not set")) for value in dimensions)


@pytest.mark.parametrize("markup,expected", [
    ("f<sub>ytk</sub> / f<sub>yck</sub> / f<sub>utk</sub> = 551.125 / 537.375 / 613.625 MPa",
     [["f<sub>ytk</sub>", "551.125 MPa"], ["f<sub>yck</sub>", "537.375 MPa"], ["f<sub>utk</sub>", "613.625 MPa"]]),
    ("gamma<sub>y</sub> / gamma<sub>u</sub> / gamma<sub>E</sub> = 1.13 / 1.17 / 1.03",
     [["gamma<sub>y</sub>", "1.13"], ["gamma<sub>u</sub>", "1.17"], ["gamma<sub>E</sub>", "1.03"]]),
    ("eps<sub>c2</sub> / eps<sub>cu2</sub> = 2.15 / 3.65 &#8240;; n = 2.125",
     [["eps<sub>c2</sub>", "2.15 &#8240;"], ["eps<sub>cu2</sub>", "3.65 &#8240;"], ["n", "2.125"]]),
    ("curve 7; k = 0.85; eps<sub>0t</sub> / eps<sub>0c</sub> = 1.2 / 1.3 &#8240;; compression branch active = no",
     [["Definition", "curve 7"], ["k", "0.85"], ["eps<sub>0t</sub>", "1.2 &#8240;"], ["eps<sub>0c</sub>", "1.3 &#8240;"], ["compression branch active", "no"]]),
    ("alpha<sub>cc</sub> = eta<sub>cc</sub> k<sub>tc</sub> = 0.95; E<sub>s</sub> = 197.3 GPa",
     [["alpha<sub>cc</sub>", "eta<sub>cc</sub> k<sub>tc</sub> = 0.95"], ["E<sub>s</sub>", "197.3 GPa"]]),
])
def test_material_property_splitter_preserves_parameters_values_and_units(markup, expected):
    assert sector_report.ReportBuilder._material_property_rows(markup) == expected


@pytest.mark.parametrize("profile", [BRIEF_PROFILE, STANDARD_PROFILE, AUDIT_PROFILE], ids=lambda p: p.key)
def test_fatigue_detail_property_schedules_preserve_values_and_source(profile):
    inp = _inputs()
    inp["tendon_elements"] = [{"id": "T1", "fatigue_detail_id": "F2"}]
    details = [dict(id="F1", name="Bent bar <project>", preset="Custom & imported",
                    source="Project fatigue specification, Table 7", kind="mild",
                    stress_model="elastic", delta_sigma_rsk_mpa=137.125, n_star=1734567.125,
                    k1=4.125, k2=8.375, bend_reduction=True, mandrel_diameter_mm=213.625),
               dict(id="F2", name="Bonded tendon", preset="Tendon project law",
                    source="Project tendon specification, Clause 4.2", kind=fatigue_inputs.PRESTRESS,
                    stress_model="elastic", delta_sigma_rsk_mpa=147.875, n_star=2345678.625,
                    k1=5.125, k2=9.375, bend_reduction=False,
                    bond_ratio_xi=.437, bond_equivalent_diameter_mm=11.375)]
    builder, text = _capture(inp, profile=profile)
    builder.out = builder._base_out = {"fatigue": {
        "checks": {"reinforcement": True}, "fatigue_detail_basis": [details[0], details[1], dict(details[0])],
    }}
    if profile is BRIEF_PROFILE:
        builder._brief_settings_summary()
    else:
        builder._settings_block()
    schedules = [(caption, rows) for caption, rows in builder._captured_tables
                 if caption.startswith("Fatigue detail ")]
    assert len(schedules) == 2
    for detail, (caption, rows) in zip(details, schedules):
        assert detail["id"] in caption
        assert all(len(row) == 2 for row in rows)
        values = dict(rows[1:])
        for field, label in (("id", "Detail ID"), ("name", "Name"), ("preset", "Preset"),
                             ("source", "Source"), ("kind", "Material kind"), ("stress_model", "Stress model")):
            expected = detail[field]
            if field == "kind":
                expected = {
                    "mild": "Reinforcing steel",
                    "prestress": "Prestressing steel",
                }[expected]
            assert html.unescape(values[label]) == expected
        assert values["Reference stress range &#916;&#963;<sub>Rsk</sub>"] == f'{detail["delta_sigma_rsk_mpa"]:.3f} MPa'
        assert values["Reference cycle count N<super>*</super>"] == f'{detail["n_star"]:.3f}'
        assert values["Upper-branch exponent k<sub>1</sub>"] == f'{detail["k1"]:.3f}'
        assert values["Lower-branch exponent k<sub>2</sub>"] == f'{detail["k2"]:.3f}'
        assert values["Bend reduction"] == ("yes" if detail["bend_reduction"] else "no")
    mild = dict(schedules[0][1][1:]); tendon = dict(schedules[1][1][1:])
    assert mild["Mandrel diameter"] == "213.625 mm"
    assert tendon["Bond-strength ratio &#958;"] == "0.437"
    assert tendon["Bond-equivalent diameter"] == "11.375 mm"
    assert "Mandrel diameter" not in tendon
    assert "Bond-strength ratio &#958;" not in mild
    assert "Delta sigma" not in text() and "N* =" not in text()


def test_fatigue_detail_tendon_bond_controls_follow_mixed_reinforcement_scope():
    inp = _inputs()
    builder, _ = _capture(inp)
    detail = dict(id="F2", kind=fatigue_inputs.PRESTRESS, bond_ratio_xi=.437,
                  bond_equivalent_diameter_mm=11.375, bend_reduction=False)
    builder._fatigue_detail_input_tables([detail], mixed_reinforcement=False)
    values = dict(builder._captured_tables[0][1][1:])
    assert "Bond-strength ratio &#958;" not in values
    assert "Bond-equivalent diameter" not in values


@pytest.mark.parametrize("basis", list(sector_report.DesignBasisKey))
def test_requested_fatigue_basis_uses_its_public_label_before_results(basis):
    inp = _inputs(); inp["fatigue_edition"] = basis.value
    builder, text = _capture(inp)
    builder._brief_settings_summary()
    assert sector_report.get_design_basis(basis).label in text()
    assert basis.value not in text()


def test_unknown_project_fatigue_basis_is_preserved_as_literal_input():
    inp = _inputs(); inp["fatigue_edition"] = "Project fatigue specification <revision B>"
    builder, text = _capture(inp)
    builder._brief_settings_summary()
    assert inp["fatigue_edition"] in text()
