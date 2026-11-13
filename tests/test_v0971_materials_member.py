"""0.97.1 I4: material cards, the Member settings group and the input rerun cost.

Expected design values come from the standard text, not from Sector:
EN 1992-1-1:2004 3.1.6(1)P Formula (3.15), Table 3.1, 3.2.7(2) and Figure
3.8, 3.3.6(6) and (7); DS/EN 1992-1-1 DK NA:2024 Table 2.1Na NA and 3.2.7(2);
DS/EN 1992-1-1:2023 5.1.6(1) Formulae (5.3) and (5.4), 5.2.4(1) Formula (5.11).
"""

from __future__ import annotations

import ast
import json
import math
import pathlib
import sys
import tomllib

import pytest

from app import input_issues, material_cards
from sector import capacity, codes, material_presets as mp

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = str(ROOT / "app" / "sector_app.py")
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))  # `import sector_app` works alone
DK_NA = "DS/EN 1992-1-1:2005 + DK NA:2024"
EN_2004 = "EN 1992-1-1:2005"
EN_2023 = "DS/EN 1992-1-1:2023"
PERMILLE = chr(0x2030)
DEGREE = chr(0x00B0)
NBSP = chr(0x00A0)


def _rows(card):
    return {row.quantity: row for row in card.rows}


def _concrete(fck, gamma_c, alpha_cc, preset):
    return mp.build_concrete(curve=2, fck=fck, gamma_c=gamma_c,
                             alpha_cc=alpha_cc, eps_c2=2.0, eps_cu2=3.5, n=2.0,
                             k_tc=None, pivot_c=mp.pivot_c_default(preset))


# --- Material cards -------------------------------------------------------


def _v(number, unit):
    """Card value text: the number, a non-breaking space and the unit."""
    return f"{number}{NBSP}{unit}"


def test_dk_na_concrete_card_gives_the_standard_values():
    # C35/45. DK NA Table 2.1Na NA: gamma_c = 1.45 (gamma_0 = gamma_3 = 1.0).
    # DK NA 3.1.6(1)P keeps alpha_cc = 1.0. Formula (3.15):
    # fcd = 1.0 x 35 / 1.45 = 24.14 MPa. Table 3.1: fctm = 0.30 x 35^(2/3)
    # = 3.21 MPa, Ecm = 22 (43/10)^0.3 = 34.1 GPa, eps_c2 = 2.0, eps_cu2 = 3.5.
    card = material_cards.concrete_card(
        _concrete(35.0, 1.45, 1.0, DK_NA), fctm_mpa=2.9, ec_gpa=30.0,
        preset=DK_NA,
    )
    rows = _rows(card)
    fcd = rows[r"$f_{cd}$"]
    assert fcd.value == _v(f"{35.0 / 1.45:.2f}", "MPa") == _v("24.14", "MPa")
    assert fcd.basis == (r"$\alpha_{cc}f_{ck}/\gamma_c$; 3.1.6(1)P, (3.15); "
                         r"$\gamma_c$: DK NA Table 2.1Na NA")
    # The entered values of the calculation, with the Table 3.1 reference.
    fctm = rows[r"$f_{ctm}$"]
    assert fctm.value == _v("2.90", "MPa")
    assert fctm.basis == "Entered; Table 3.1: " + _v(
        f"{0.30 * 35.0 ** (2.0 / 3.0):.2f}", "MPa")
    ec = rows[r"$E_c$"]
    assert ec.value == _v("30.0", "GPa")
    assert ec.basis == "Entered; Table 3.1, $E_{cm}$: " + _v(
        f"{22.0 * (43.0 / 10.0) ** 0.3:.1f}", "GPa")
    assert rows[r"$\varepsilon_{c2}$"].value == _v("2.00", PERMILLE)
    assert rows[r"$\varepsilon_{cu2}$"].value == _v("3.50", PERMILLE)
    assert rows[r"$\varepsilon_{cu2}$"].basis == "Table 3.1, 3.1.7(1)"
    assert card.edition == DK_NA
    assert card.condition == (
        f"20 {DEGREE}C, concrete age 28 days, persistent design situation"
    )
    caption = material_cards.card_caption(card)
    assert caption.startswith(f"Edition: {DK_NA}. Condition: 20 {DEGREE}C")
    assert "torsion cracking resistance" in caption


def test_2023_concrete_card_uses_the_2023_formula_and_clauses():
    # DS/EN 1992-1-1:2023 5.1.6(1), (5.3) and (5.4): eta_cc = (40/50)^(1/3),
    # k_tc = 0.85, gamma_C = 1.5: fcd = 0.9283 x 0.85 x 50 / 1.5 = 26.30 MPa.
    eta_cc = (40.0 / 50.0) ** (1.0 / 3.0)
    alpha = mp.strength_dependent_alpha_cc(EN_2023, 50.0, 0.85)
    card = material_cards.concrete_card(
        _concrete(50.0, 1.5, alpha, EN_2023), fctm_mpa=4.07, ec_gpa=37.3,
        preset=EN_2023,
    )
    rows = _rows(card)
    fcd = rows[r"$f_{cd}$"]
    assert fcd.value == _v(f"{eta_cc * 0.85 * 50.0 / 1.5:.2f}", "MPa") == _v(
        "26.30", "MPa")
    assert fcd.basis == r"$\eta_{cc}k_{tc}f_{ck}/\gamma_C$; 5.1.6(1), (5.3), (5.4)"
    assert rows[r"$\varepsilon_{cu2}$"].basis == "8.1.2(1), (8.4)"
    # The Auto buttons use EN 1992-1-1:2004 Table 3.1; the card names it.
    assert rows[r"$f_{ctm}$"].basis.startswith(
        "Entered; EN 1992-1-1:2004 Table 3.1: "
    )


def test_concrete_card_reads_the_law_of_the_calculation():
    # A curve preset has no standard clause; the values come from the law.
    concrete = mp.build_concrete(curve=1, fck=30.0, gamma_c=1.2, alpha_cc=0.85,
                                 eps_c2=2.2, eps_cu2=3.0)
    card = material_cards.concrete_card(
        concrete, fctm_mpa=2.9, ec_gpa=33.0, preset="Curve 1 (cubic)"
    )
    rows = _rows(card)
    # Formula (3.15) with the entered operands: 0.85 x 30 / 1.2 = 21.25 MPa.
    assert rows[r"$f_{cd}$"].value == _v("21.25", "MPa")
    assert rows[r"$f_{cd}$"].basis == r"$\alpha_{cc}f_{ck}/\gamma_c$"
    assert rows[r"$\varepsilon_{cu2}$"].value == _v("3.00", PERMILLE)
    assert rows[r"$\varepsilon_{cu2}$"].basis == "-"
    assert "Sector curve law, no standard clause" in card.edition
    assert material_cards.edition_key("Curve 1 (cubic)") is None
    assert material_cards.edition_key(DK_NA) == codes.EC2_2005_DKNA.key


def test_dk_na_reinforcing_steel_card():
    # DK NA Table 2.1Na NA: gamma_s = 1.20. Figure 3.8: fyd = 550 / 1.20 =
    # 458.33 MPa. The preset rupture strain is 50 permille. DK NA 3.2.7(2)
    # selects the horizontal branch b) without a strain limit.
    steel = mp.build_mild(**mp.MILD_PRESETS[DK_NA])
    card = material_cards.reinforcing_steel_card(steel, preset=DK_NA, title="M1")
    rows = _rows(card)
    fyd = rows[r"$f_{yd}$"]
    assert fyd.value == _v(f"{550.0 / 1.20:.2f}", "MPa") == _v("458.33", "MPa")
    assert fyd.basis.startswith(r"$f_{ytk}/\gamma_y$; 3.2.7(2), Figure 3.8")
    eud = rows[r"$\varepsilon_{ud}$"]
    assert eud.value == _v("50.00", PERMILLE)
    assert eud.basis == (r"Entered $\varepsilon_{ut}$; 3.2.7(2) a); DK NA "
                         "3.2.7(2): b), no strain limit")
    assert rows["Compression"].value == "active"
    assert card.condition == f"20 {DEGREE}C, persistent design situation"
    tension_only = mp.build_mild(**mp.MILD_PRESETS[DK_NA] | {
        "active_in_compression": False})
    assert _rows(material_cards.reinforcing_steel_card(
        tension_only, preset=DK_NA))["Compression"].value == "tension only"


@pytest.mark.parametrize(("preset", "fyd", "fyd_clause", "eud_clause"), [
    # EN 1992-1-1:2004 Table 2.1N gamma_s = 1.15: 500 / 1.15 = 434.78 MPa.
    (EN_2004, 500.0 / 1.15, "; 3.2.7(2), Figure 3.8", "; 3.2.7(2) a)"),
    # DS/EN 1992-1-1:2023 5.2.4(1), (5.11): 500 / 1.15 = 434.78 MPa.
    (EN_2023, 500.0 / 1.15, "; 5.2.4(1), (5.11)", "; 5.2.4(2) a)"),
    ("Curve 2 (elastic-perfectly-plastic)", 500.0, "", ""),
])
def test_reinforcing_steel_card_clause_follows_the_edition(
    preset, fyd, fyd_clause, eud_clause
):
    steel = mp.build_mild(**mp.MILD_PRESETS[preset])
    rows = _rows(material_cards.reinforcing_steel_card(steel, preset=preset))
    assert rows[r"$f_{yd}$"].value == _v(f"{fyd:.2f}", "MPa")
    assert rows[r"$f_{yd}$"].basis == r"$f_{ytk}/\gamma_y$" + fyd_clause
    assert rows[r"$\varepsilon_{ud}$"].basis == (
        r"Entered $\varepsilon_{ut}$" + eud_clause)


def test_steel_card_value_is_the_engine_design_yield():
    # The card reads the same function as the shear and torsion checks.
    steel = mp.build_mild(**mp.MILD_PRESETS[DK_NA] | {"gamma_y": 1.32})
    card = material_cards.reinforcing_steel_card(steel, preset=DK_NA)
    assert _rows(card)[r"$f_{yd}$"].value == _v(
        f"{capacity.design_yield(steel):.2f}", "MPa"
    ) == _v(f"{550.0 / 1.32:.2f}", "MPa")


def test_prestressing_steel_cards():
    # 3.3.6(6): fpd = fp0,1k / gamma_s = 1640 / 1.20 = 1366.67 MPa (DK NA).
    tendon = mp.build_prestress(**mp.PRESTRESS_PRESETS[DK_NA])
    rows = _rows(material_cards.prestressing_steel_card(tendon, preset=DK_NA))
    assert rows[r"$f_{pd}$"].value == _v("1366.67", "MPa")
    assert rows[r"$f_{pd}$"].basis.startswith(r"$f_{p0.1k}/\gamma_y$; 3.3.6(6)")
    assert rows[r"$\varepsilon_{ud}$"].value == _v("35.00", PERMILLE)
    assert rows[r"$\varepsilon_{ud}$"].basis == "Total tendon strain; 3.3.6(7)"
    # 2023 5.3.3(1), (5.12): 1640 / 1.15 = 1426.09 MPa.
    tendon = mp.build_prestress(**mp.PRESTRESS_PRESETS[EN_2023])
    rows = _rows(material_cards.prestressing_steel_card(tendon, preset=EN_2023))
    assert rows[r"$f_{pd}$"].value == _v(f"{1640.0 / 1.15:.2f}", "MPa")
    assert rows[r"$f_{pd}$"].basis == r"$f_{p0.1k}/\gamma_y$; 5.3.3(1), (5.12)"
    assert rows[r"$\varepsilon_{ud}$"].basis == "Total tendon strain; 5.3.3(2) a)"
    # A built-in curve is a fixed law with the fixed 3.5 % rupture strain.
    builtin = mp.build_prestress(**mp.PRESTRESS_PRESETS["Curve 1 (built-in)"])
    rows = _rows(material_cards.prestressing_steel_card(
        builtin, preset="Curve 1 (built-in)"))
    assert rows[r"$f_{pd}$"].value == "-"
    assert rows[r"$f_{pd}$"].basis == "Built-in curve 1: fixed law"
    assert rows[r"$\varepsilon_{ud}$"].value == _v("35.00", PERMILLE)
    assert rows[r"$\varepsilon_{ud}$"].basis == "Total tendon strain"


def test_card_markdown_accepts_several_materials():
    first = material_cards.reinforcing_steel_card(
        mp.build_mild(**mp.MILD_PRESETS[DK_NA]), preset=DK_NA, title="M1 - B550")
    second = material_cards.reinforcing_steel_card(
        mp.build_mild(**mp.MILD_PRESETS[EN_2004]), preset=EN_2004, title="M2 - B500")
    text = material_cards.card_markdown([first, second])
    assert "**Design values: M1 - B550**" in text
    assert "**Design values: M2 - B500**" in text
    assert text.count("| Quantity | Value | Basis |") == 2
    assert material_cards.card_markdown(first) in text
    assert chr(0x2014) not in text


# --- Member settings group -------------------------------------------------


def test_member_inputs_route_to_the_member_group():
    assert input_issues.SETTINGS_GROUPS[1] == "Member"
    for key in (*capacity.MED_MAX_KEYS.values(), capacity.MED_MAX_ON_KEY,
                "shear_med_max_copy", "sls_member", "detailing_member_type",
                "detailing_cut_direction"):
        assert input_issues.settings_group(key, mvt_input=True) == "Member"
    assert input_issues.settings_group("sls_code") == "Crack width"
    assert input_issues.settings_group("fatigue_on") == "Fatigue"
    assert input_issues.settings_group("transverse_ductility_class") == "Detailing"
    assert input_issues.settings_group("modelled_direction_alias") == "Detailing"
    assert input_issues.settings_group("shear_links", mvt_input=True) == (
        "Shear / torsion / M-V-T"
    )
    assert input_issues.settings_group("mode") == "General"
    assert input_issues.settings_group(None) == "General"


def _fresh(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    return AppTest.from_file(APP, default_timeout=120)


def _keys(at):
    return {widget.key for kind in ("selectbox", "checkbox", "number_input")
            for widget in getattr(at, kind)}


def _group(at, group):
    from app_workflow_navigation import _navigation_values, goto_page

    changed = _navigation_values(at, {"_analysis_group": group})
    current = at.session_state.to_dict().get("_workflow_page")
    goto_page(at, "settings")
    if changed and current == "settings":
        at.run()
    assert not at.exception
    return _keys(at)


@pytest.fixture(scope="module")
def default_app(tmp_path_factory):
    import os

    from streamlit.testing.v1 import AppTest

    os.environ["SECTOR_AUTOSAVE_DIR"] = str(tmp_path_factory.mktemp("autosave"))
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    return at


def test_member_group_holds_the_member_context_inputs(default_app):
    at = default_app
    member_keys = {"sls_member", "detailing_member_type",
                   capacity.MED_MAX_ON_KEY, *capacity.MED_MAX_KEYS.values()}
    assert member_keys <= _group(at, "Member")
    captions = " ".join(item.value for item in at.caption)
    # Each input states when it has no effect (default: no check uses it).
    assert "Only the chord checks of shear and torsion use" in captions
    assert "Only the DK NA crack-width calculation uses this input" in captions
    assert "Only the detailing checks use these inputs" in captions
    assert not member_keys & _group(at, "Crack width")
    assert not member_keys & _group(at, "Detailing")
    assert "Member settings group" in " ".join(item.value for item in at.caption)
    at.session_state["_mvt_page"] = "Shared reinforcement"
    assert not member_keys & _group(at, "Shear / torsion / M-V-T")


def test_med_max_of_a_0970_file_survives_load_and_save(tmp_path, monkeypatch):
    # A schema-28 (0.97.0) project with MEd,max keeps the values after a load in
    # the app and a save. The widget keys and the project fields are unchanged.
    from app import project_io, reproducible_example

    tables = reproducible_example.project_tables()
    scalars = dict(reproducible_example.project_scalars())
    scalars[capacity.MED_MAX_ON_KEY] = True
    scalars["shear_med_max_mx_pos"] = 125.0
    scalars["shear_med_max_my_neg"] = 40.0
    from app import load_cases, section_ids
    from app import reinforcement_table as rebar

    # The form that 0.97.0 wrote: schema 28, without the schema-29 fields.
    payload = json.loads(project_io.dump_project(tables, scalars))
    payload["version"] = 28
    for key in project_io.SCHEMA29_SCALAR_KEYS:
        payload["scalars"].pop(key)
    schema29_columns = {
        **{key: {section_ids.ID} for key in section_ids.GEOMETRY_TABLE_KEYS},
        **{key: {rebar.GROUP_ID} for key in project_io.REINFORCEMENT_TABLE_KEYS},
        **{key: set(load_cases.ATTRIBUTE_COLUMNS)
           for key in load_cases.CASE_TABLE_KEYS},
    }
    for key, dropped in schema29_columns.items():
        table = payload["tables"][key]
        keep = [i for i, name in enumerate(table["columns"])
                if name not in dropped]
        table["columns"] = [table["columns"][i] for i in keep]
        table["rows"] = [[row[i] for i in keep] for row in table["rows"]]
    payload["provenance"]["input_sha256"] = project_io.recorded_input_sha256(
        payload)
    text = json.dumps(payload)
    assert project_io.parse_project_with_info(text)[2]["source_schema_version"] == 28

    at = _fresh(tmp_path, monkeypatch).run()
    at.session_state["_pending_project"] = text
    at.run()
    assert not at.exception
    assert {capacity.MED_MAX_ON_KEY, "shear_med_max_mx_pos"} <= _group(at, "Member")
    assert at.checkbox(key=capacity.MED_MAX_ON_KEY).value is True
    assert at.number_input(key="shear_med_max_mx_pos").value == 125.0
    assert at.number_input(key="shear_med_max_my_neg").value == 40.0

    # Save: the project download serialises this session state.
    import sector_app
    from types import SimpleNamespace

    monkeypatch.setattr(
        sector_app, "st", SimpleNamespace(session_state=at.session_state.to_dict())
    )
    saved = project_io.parse_project(sector_app._gather_project())[1]
    assert saved[capacity.MED_MAX_ON_KEY] is True
    assert saved["shear_med_max_mx_pos"] == 125.0
    assert saved["shear_med_max_my_neg"] == 40.0
    assert saved["shear_med_max_mx_neg"] == 0.0


# --- Input rerun cost (UI-31) ----------------------------------------------


def test_magic_is_off_and_the_main_script_has_no_magic_output():
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    assert config["runner"]["magicEnabled"] is False
    from streamlit.runtime.scriptrunner import magic

    tree = magic.add_magic(pathlib.Path(APP).read_text(encoding="utf-8"), APP)
    writes = [node for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr == "transparent_write"]
    assert writes == []


def test_ignore_keeps_the_field_out_of_the_rerun_and_the_journal():
    import sector_app

    ignored = sector_app._input_widget_kwargs(
        "k", {"on_change": "ignore", "help": "h"})
    assert ignored == {"on_change": "ignore", "help": "h"}
    callback = object()
    journaled = sector_app._input_widget_kwargs(
        "k", {"on_change": callback, "args": (1,)})
    assert journaled["on_change"] is sector_app._record_input_event
    assert journaled["args"] == ("k", callback, (1,), {})


def test_only_free_text_without_dependent_display_ignores_reruns(default_app):
    from app_workflow_navigation import goto_material

    at = default_app
    goto_material(at, "Reinforcing steel")
    assert not at.exception
    fields = {widget.key: widget.proto.ignore_rerun for widget in at.text_input}
    names = [key for key in fields if key.endswith("_name")]
    descriptions = [key for key in fields if key.endswith("_description")]
    assert names and descriptions
    assert all(fields[key] is False for key in names)
    assert all(fields[key] is True for key in descriptions)
    text = " ".join(item.value for item in at.markdown)
    # Figure 3.8 with DK NA Table 2.1Na NA: 550 / 1.20 = 458.33 MPa.
    assert "Design values: M1" in text and "458.33" + NBSP + "MPa" in text
    goto_material(at, "Concrete")
    text = " ".join(item.value for item in at.markdown)
    # Formula (3.15): 35 / 1.45 = 24.14 MPa (default C35, DK NA).
    assert "**Design values: Concrete**" in text and "24.14" + NBSP + "MPa" in text
    assert math.isclose(at.number_input(key="conc_fck").value, 35.0)
