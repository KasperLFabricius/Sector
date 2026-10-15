"""Presentation navigation must retain canonical shear/torsion inputs."""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from input_stage_host import InputStage

from app import mvt_workspace as mvt


class Host:
    def __init__(self, state):
        self.state = state
        self.calls = []

    def radio(self, label, options, **kwargs):
        self.calls.append(("radio", label))
        return self.state[kwargs["key"]]

    def caption(self, text):
        self.calls.append(("caption", text))

    def markdown(self, text):
        self.calls.append(("markdown", text))

    def number_input(self, label, **kwargs):
        self.calls.append(("number_input", label))
        return kwargs.get("value")


@pytest.mark.parametrize("selected", mvt.PAGES)
def test_only_selected_page_mounts_controls(selected):
    state = {mvt.PAGE_KEY: selected}
    host = Host(state)
    pages = mvt.stages(host, state=state)
    assert [page.open for page in pages] == [name == selected for name in mvt.PAGES]
    for index, page in enumerate(pages):
        page.number_input(str(index), value=3.0, key=f"input_{index}")
    assert [label for kind, label in host.calls if kind == "number_input"] == [str(mvt.PAGES.index(selected))]


@pytest.mark.parametrize("selected", mvt.PAGES)
def test_closed_parent_keeps_all_pages_closed(selected):
    state = {mvt.PAGE_KEY: selected, "shear_link_dia": 12.0}
    host = Host(state)
    parent = InputStage(host, active=False, state=state)
    pages = mvt.stages(parent, state=state)
    assert not any(page.open for page in pages)
    assert pages[1].number_input("Diameter", key="shear_link_dia", value=10.0) == 12.0
    assert host.calls == []


def test_page_change_preserves_values_and_refreshes_navigation_mirrors():
    state = {"shear_on": False, "torsion_on": False, "shear_links": False,
             "shear_link_dia": 12.0, "_durable_input_scalars": {}}
    events = []

    def snapshot():
        events.append(dict(state))
        state["_pending_input_events"] = {mvt.PAGE_KEY: mvt.PAGES[0]}

    mvt.select_page(state, mvt.PAGES[1], on_change=snapshot)
    assert len(events) == 1
    assert state[mvt.PAGE_KEY] == mvt.PAGES[1]
    assert state["_pending_input_events"][mvt.PAGE_KEY] == mvt.PAGES[1]
    assert state["_durable_input_scalars"][mvt.PAGE_KEY] == mvt.PAGES[1]
    assert not any(state[key] for key in ("shear_on", "torsion_on", "shear_links"))
    assert state["shear_link_dia"] == 12.0


@pytest.mark.parametrize("key, expected", [
    ("combined_on", 0), ("shear_method", 0), ("torsion_method", 0),
    ("shear_links", 1), ("capacity_steel_material_id", 1),
    ("strut_cot_min", 1), ("shear_vx_transverse_leg_spacing", 1),
    ("shear_gamma_v", 2), ("shear_duct_case", 2),
    ("torsion_gamma_ct", 3), ("torsion_sub_x3", 3),
    ("_torsion_case_design_basis::0::Case 1", 3),
    ("_torsion_case_member_scope::0::Case 1", 3),
    ("combined_mv_independent", 4),
])
def test_issue_field_routes_to_its_owner(key, expected):
    assert mvt.field_page(key) == mvt.PAGES[expected]


def test_unrelated_key_has_no_mvt_route():
    assert mvt.field_page("fck") is None


def test_invalid_request_does_not_modify_state():
    state = {"shear_on": False}
    with pytest.raises(ValueError):
        mvt.select_page(state, "Unsupported")
    assert state == {"shear_on": False}


def test_inactive_page_retains_pending_invalid_number():
    state = {mvt.PAGE_KEY: mvt.PAGES[0],
             "_pending_input_events": {"torsion_gamma_ct": None},
             "_durable_input_scalars": {"torsion_gamma_ct": 1.8}}
    pages = mvt.stages(Host(state), state=state)
    value = pages[3].number_input("Tensile factor", key="torsion_gamma_ct", value=1.5)
    assert value is None


def test_prerequisite_links_are_navigation_only_and_group_duplicate_requirements():
    class LinkHost:
        def __init__(self):
            self.buttons = []
            self.status = []

        def button(self, label, **kwargs):
            self.buttons.append((label, kwargs))

        def caption(self, label):
            self.status.append(label)

    state = {"mode": "Elastic", "check_util": False, "shear_on": False,
             "torsion_on": False, "shear_links": False,
             "_pending_input_events": {}, "_durable_input_scalars": {}}
    original = {key: state[key] for key in ("mode", "check_util", "shear_on", "torsion_on", "shear_links")}
    requirements = [(False, label) for label in (
        "Plastic / Both bending analysis", "Check utilisation against applied moment",
        "Shear check enabled", "Torsion check enabled",
        "Shared links / closed torsion stirrups present",
    )]
    host = LinkHost()
    mvt.requirement_links(host, requirements, state=state, key_prefix="test", show_status=True)
    assert len(host.status) == 5
    assert [label for label, _ in host.buttons] == [
        "Open General settings", "Open Checks and methods", "Open Shared reinforcement"]
    for _, kwargs in host.buttons:
        kwargs["on_click"](*kwargs["args"], **kwargs["kwargs"])
        assert {key: state[key] for key in original} == original
    assert state["_analysis_group"] == "Shear / torsion / M-V-T"
    assert state[mvt.PAGE_KEY] == "Shared reinforcement"


def test_prerequisite_navigation_snapshots_before_changing_destinations():
    state = {"_analysis_group": "Shear / torsion / M-V-T", "mode": "Elastic"}
    seen = []
    mvt.open_settings(state, "General", on_change=lambda: seen.append(dict(state)))
    assert seen == [{"_analysis_group": "Shear / torsion / M-V-T", "mode": "Elastic"}]
    assert state == {"_analysis_group": "General", "mode": "Elastic"}
