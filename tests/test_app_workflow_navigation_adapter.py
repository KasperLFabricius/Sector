"""Pure checks for test navigation adapters; no AppTest or calculation."""
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import pytest
from app_workflow_navigation import goto_input_stage, goto_page, goto_widget_owner


class State(dict):
    @property
    def filtered_state(self):
        return self


class FakeApp:
    def __init__(self):
        self.session_state = State(_workflow_page="section", mode="Both", shear_on=False,
                                   _durable_input_scalars={"shear_on": False},
                                   _pending_input_events={"shear_vy_bw": 300.0})
        self.runs = 0

    def run(self):
        self.runs += 1
        page = self.session_state.pop("_next_workflow_page", None)
        if page:
            self.session_state["_workflow_page"] = page
        return self


@pytest.mark.parametrize("stage,route", [("Section", "section"), ("Material parameters", "materials"),
                                           ("Loads", "actions"), ("Analysis settings", "settings"),
                                           ("Project", "project")])
def test_stage_routes(stage, route):
    at = FakeApp()
    goto_input_stage(at, stage)
    assert at.session_state["_workflow_page"] == route


@pytest.mark.parametrize("key,group,page", [
    ("mode", "General", None), ("shear_on", "Shear / torsion / M-V-T", "Checks and methods"),
    ("shear_link_dia", "Shear / torsion / M-V-T", "Shared reinforcement"),
    ("shear_vy_bw", "Shear / torsion / M-V-T", "Shear"),
    ("torsion_method", "Shear / torsion / M-V-T", "Checks and methods"),
    ("torsion_tef", "Shear / torsion / M-V-T", "Torsion"),
    ("combined_mv_independent", "Shear / torsion / M-V-T", "Combined M-V-T"),
    ("sls_code", "Crack width", None), ("transverse_detailing_on", "Detailing", None),
    ("fatigue_on", "Fatigue", None),
])
def test_hidden_settings_navigation_preserves_engineering_values(key, group, page):
    at = FakeApp()
    before = deepcopy(at.session_state)
    goto_widget_owner(at, key)
    assert at.session_state["_workflow_page"] == "settings"
    assert at.session_state["_analysis_group"] == group
    if page:
        assert at.session_state["_mvt_page"] == page
    assert at.session_state["mode"] == before["mode"]
    assert at.session_state["shear_on"] is False
    assert at.session_state["_durable_input_scalars"]["shear_on"] is False
    assert at.session_state["_pending_input_events"]["shear_vy_bw"] == 300.0
    runs = at.runs
    goto_widget_owner(at, key)
    assert at.runs == runs


def test_unknown_page_fails_closed_and_input_navigation_retains_stage():
    at = FakeApp()
    with pytest.raises(KeyError):
        goto_page(at, "Unknown")
    at.session_state["_input_tab"] = f"4 {chr(0x00B7)} Loads"
    goto_page(at, "Inputs")
    assert at.session_state["_workflow_page"] == "actions"


def test_elastic_creep_owner_selects_existing_elastic_case_controls():
    at = FakeApp()
    goto_widget_owner(at, "el_phi")
    assert at.session_state["_workflow_page"] == "actions"
    assert at.session_state["_actions_family"] == "Elastic"


@pytest.mark.parametrize("key,family", [("conc_fck", "Concrete"), ("mild_fytk", "Reinforcing steel"),
                                       ("pre_fytk", "Prestressing steel"), ("fatiguecat_id", "Fatigue details")])
def test_exact_native_material_family_labels(key, family):
    at = FakeApp()
    goto_widget_owner(at, key)
    assert at.session_state["_workflow_page"] == "materials"
    assert at.session_state["_material_tab"] == family
    assert at.session_state["_material_tab_preference"] == family


def test_action_family_switch_preserves_both_tables_and_only_routes_once():
    from app_workflow_navigation import goto_action_family
    at = FakeApp()
    at.session_state['plastic_cases_base'] = [{'name': 'A', 'n_ed_kn': 11}]
    at.session_state['elastic_cases_base'] = [{'name': 'E', 'n_long_ed_kn': 17}]
    before = deepcopy(at.session_state)
    goto_action_family(at, 'Elastic')
    assert at.session_state['_workflow_page'] == 'actions'
    assert at.session_state['_actions_family'] == 'Elastic'
    assert at.session_state['plastic_cases_base'] == before['plastic_cases_base']
    assert at.session_state['elastic_cases_base'] == before['elastic_cases_base']
    runs = at.runs
    goto_action_family(at, 'Elastic')
    assert at.runs == runs
    with pytest.raises(ValueError):
        goto_action_family(at, 'Unknown')


def test_fatigue_actions_owner_preserves_all_tables_and_does_not_revisit():
    from app_workflow_navigation import goto_action_family
    at = FakeApp()
    tables = {"plastic_cases_base": [{"name": "A", "n_ed_kn": 11}],
              "elastic_cases_base": [{"name": "E", "n_long_ed_kn": 17}],
              "fatigue_spectrum_base": [{"name": "F", "cycles": 12345}]}
    at.session_state.update(deepcopy(tables))
    goto_widget_owner(at, "fatigue_spectrum_editor")
    assert at.session_state["_workflow_page"] == "actions"
    assert at.session_state["_actions_family"] == "Fatigue"
    assert {key: at.session_state[key] for key in tables} == tables
    runs = at.runs
    goto_action_family(at, "Fatigue")
    assert at.runs == runs
    assert {key: at.session_state[key] for key in tables} == tables
