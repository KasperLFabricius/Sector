"""STATE-H02 deterministic whole-project replacement evidence."""

from __future__ import annotations

import os
import pathlib
import sys

import pytest
from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

APP = str(ROOT / "app" / "sector_app.py")

import material_catalog  # noqa: E402
import project_io  # noqa: E402


_SPARSE_PROJECT = project_io.dump_project(
    {},
    {"rep_proj_no": "STATE-H02 sparse project"},
).encode("utf-8")

_EXPLICIT_FIELDS_WITHOUT_PRESETS_PROJECT = project_io.dump_project(
    {},
    {
        "rep_proj_no": "STATE-H02 explicit fields without presets",
        "conc_fck": 41.0,
        "mild_fytk": 615.0,
        "mild_futk": 650.0,
        "pre_fytk": 1711.0,
        "pre_futk": 1800.0,
    },
).encode("utf-8")

_OLD_ARTIFACT_KEYS = (
    "results",
    "result_sig",
    "result_plastic_sig",
    "result_elastic_sig",
    "result_fatigue_sig",
    "result_capacity_contract_sig",
    "result_input_snapshot",
    "calculation_record",
    "report_buffer",
    "report_bytes",
    "report_signature",
    "report_filename",
    "report_generated_on",
    "report_generation_record",
    "_report_msg",
)


@pytest.fixture(scope="module", autouse=True)
def _isolated_autosave(tmp_path_factory):
    """Keep native AppTest sessions independent of any engineer autosave."""

    key = "SECTOR_AUTOSAVE_DIR"
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path_factory.mktemp("state-h02-autosave"))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _fresh() -> AppTest:
    return AppTest.from_file(APP, default_timeout=90).run()


def _goto_page(at: AppTest, page: str) -> AppTest:
    current = at.session_state["_main_page"]
    if current != page:
        at.segmented_control(key="_main_page").set_value(page).run()
    return at


def _goto_input_tab(at: AppTest, name: str) -> AppTest:
    _goto_page(at, "Inputs")
    dot = chr(0x00B7)
    labels = {
        "Analysis settings": f"1 {dot} Analysis settings",
        "Section": f"2 {dot} Section",
        "Material parameters": f"3 {dot} Material parameters",
        "Project": "Project",
    }
    if at.session_state["_input_tab"] != labels[name]:
        at.session_state["_input_tab"] = labels[name]
        at.run()
    return at


def _goto_material_tab(at: AppTest, name: str) -> AppTest:
    _goto_input_tab(at, "Material parameters")
    current = at.session_state["_material_tab"]
    if current != name:
        at.session_state["_material_tab"] = name
        at.session_state["_material_tab_preference"] = name
        at.run()
    return at


def _goto_project(at: AppTest) -> AppTest:
    return _goto_input_tab(at, "Project")


def _upload_project(
    at: AppTest,
    content: bytes,
    *,
    filename: str = "state-h02.json",
) -> AppTest:
    _goto_project(at)
    assert len(at.file_uploader) == 1
    at.file_uploader[0].set_value(
        (filename, content, "application/json")
    ).run()
    assert not at.exception
    assert any("Project loaded" in str(item.value) for item in at.success)
    return at


def _upload_sparse_project(at: AppTest) -> AppTest:
    return _upload_project(at, _SPARSE_PROJECT)


def _build_history(name: str) -> AppTest:
    at = _fresh()
    if name == "clean":
        return at
    if name == "altered-concrete":
        _goto_material_tab(at, "Concrete")
        at.number_input(key="conc_fck").set_value(70.0).run()
        assert at.session_state["conc_fck"] == pytest.approx(70.0)
        return at
    if name == "altered-material":
        _goto_material_tab(at, "Mild steel")
        at.number_input(key="mild_fytk").set_value(777.0).run()
        assert at.session_state["mild_fytk"] == pytest.approx(777.0)
        return at
    if name == "fatigue-enabled":
        _goto_input_tab(at, "Analysis settings")
        at.toggle(key="fatigue_on").set_value(True).run()
        assert at.session_state["fatigue_on"] is True
        return at
    if name == "torsion-enabled":
        _goto_input_tab(at, "Analysis settings")
        at.checkbox(key="torsion_on").set_value(True).run()
        assert at.session_state["torsion_on"] is True
        return at
    if name == "altered-section-labels":
        _goto_input_tab(at, "Section")
        at.number_input(key="label_scale").set_value(2.5).run()
        at.number_input(key="label_min_gap").set_value(0.25).run()
        assert at.number_input(key="label_scale").value == pytest.approx(2.5)
        assert at.number_input(key="label_min_gap").value == pytest.approx(0.25)
        assert at.session_state["_workspace_label_scale"] == pytest.approx(2.5)
        assert at.session_state["_workspace_label_min_gap"] == pytest.approx(0.25)
        return at
    if name == "quick-section":
        at.session_state["_qs_open"] = True
        at.session_state["_main_page"] = "Analysis"
        at.run()
        at.number_input(key="b_mm").set_value(1234.0).run()
        assert at.session_state["qsv_b_mm"] == pytest.approx(1234.0)
        at.session_state["_qs_open"] = False
        at.session_state["_main_page"] = "Inputs"
        at.session_state["_input_tab"] = "Project"
        at.run()
        return at
    raise AssertionError(f"unknown history {name}")


def _replacement_snapshot(at: AppTest) -> tuple[str, str]:
    input_durable = dict(at.session_state["_durable_input_scalars"])
    report_durable = dict(at.session_state["_durable_report_scalars"])
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {}
    for key in (*project_io.SCALAR_KEYS, *project_io.PRESENTATION_SCALAR_KEYS):
        owner = (
            report_durable
            if key in {
                "rep_proj_no",
                "rep_proj_name",
                "rep_section",
                "rep_rev",
                "rep_author",
                "rep_comments",
                project_io.REPORT_PROFILE_KEY,
            }
            else input_durable
        )
        if key in at.session_state:
            scalars[key] = at.session_state[key]
        elif key in owner:
            scalars[key] = owner[key]
    persistence = project_io.persistence_sha256(tables, scalars)
    calculation = project_io.result_sha256(
        at.session_state["_latest_inputs"]["signature"]
    )
    return persistence, calculation


@pytest.fixture(scope="module")
def clean_replacement_snapshot() -> tuple[str, str]:
    return _replacement_snapshot(_upload_sparse_project(_build_history("clean")))


@pytest.fixture(scope="module")
def clean_explicit_fields_snapshot() -> tuple[str, str]:
    at = _upload_project(
        _build_history("clean"),
        _EXPLICIT_FIELDS_WITHOUT_PRESETS_PROJECT,
        filename="explicit-fields.json",
    )
    return _replacement_snapshot(at)


@pytest.mark.parametrize(
    "history",
    (
        "clean",
        "altered-concrete",
        "altered-material",
        "fatigue-enabled",
        "torsion-enabled",
        "altered-section-labels",
        "quick-section",
    ),
)
def test_same_sparse_project_reconstructs_identically_from_every_history(
    history: str,
    clean_replacement_snapshot: tuple[str, str],
) -> None:
    at = _upload_sparse_project(_build_history(history))

    assert _replacement_snapshot(at) == clean_replacement_snapshot
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(35.0)
    assert at.session_state["_latest_inputs"]["fatigue_on"] is False
    assert at.session_state["_latest_inputs"]["torsion_on"] is False
    assert at.session_state["_durable_report_scalars"]["rep_proj_no"] == (
        "STATE-H02 sparse project"
    )
    assert "_pending_input_events" not in at.session_state
    assert "_pending_report_events" not in at.session_state

    # Exercise the previously altered family's real widgets after replacement.
    if history == "altered-concrete":
        _goto_material_tab(at, "Concrete")
        assert at.number_input(key="conc_fck").value == pytest.approx(35.0)
    elif history == "altered-material":
        _goto_material_tab(at, "Mild steel")
        expected = material_catalog.default_entry("mild")["fytk"]
        assert at.number_input(key="mild_fytk").value == pytest.approx(expected)
    elif history == "fatigue-enabled":
        _goto_input_tab(at, "Analysis settings")
        assert at.toggle(key="fatigue_on").value is False
    elif history == "torsion-enabled":
        _goto_input_tab(at, "Analysis settings")
        assert at.checkbox(key="torsion_on").value is False
    elif history == "altered-section-labels":
        defaults = {
            "label_scale": 1.0,
            "label_min_gap": 0.04,
        }

        def assert_section_defaults() -> None:
            for key, expected in defaults.items():
                mirror = f"_workspace_{key}"
                assert at.number_input(key=key).value == pytest.approx(expected)
                assert at.session_state[key] == pytest.approx(expected)
                assert at.session_state[mirror] == pytest.approx(expected)
                assert at.session_state["_durable_input_scalars"][key] == (
                    pytest.approx(expected)
                )
                assert at.session_state["_latest_inputs"][key] == pytest.approx(
                    expected
                )

        # Mount the real controls, then leave and remount their owner stage. The
        # canonical defaults must remain authoritative in every mirror and in the
        # completed calculation payload throughout that lifecycle.
        _goto_input_tab(at, "Section")
        assert_section_defaults()
        _goto_project(at)
        _goto_input_tab(at, "Section")
        assert_section_defaults()
        assert _replacement_snapshot(at) == clean_replacement_snapshot
    elif history == "quick-section":
        at.session_state["_qs_open"] = True
        at.session_state["_main_page"] = "Analysis"
        at.run()
        assert at.selectbox(key="shape").value == "Rectangle"
        assert at.number_input(key="b_mm").value == pytest.approx(400.0)


@pytest.mark.parametrize(
    "history",
    ("clean", "altered-concrete", "altered-material"),
)
def test_explicit_preset_fields_survive_when_selectors_are_omitted(
    history: str,
    clean_explicit_fields_snapshot: tuple[str, str],
) -> None:
    _, scalars = project_io.parse_project(
        _EXPLICIT_FIELDS_WITHOUT_PRESETS_PROJECT.decode("utf-8")
    )
    assert all(
        key not in scalars
        for key in ("conc_preset", "mild_preset", "pre_preset")
    )

    at = _upload_project(
        _build_history(history),
        _EXPLICIT_FIELDS_WITHOUT_PRESETS_PROJECT,
        filename="explicit-fields.json",
    )
    assert _replacement_snapshot(at) == clean_explicit_fields_snapshot

    _goto_material_tab(at, "Concrete")
    assert at.selectbox(key="conc_preset").value == (
        "DS/EN 1992-1-1:2005 + DK NA:2024"
    )
    assert at.number_input(key="conc_fck").value == pytest.approx(41.0)

    _goto_material_tab(at, "Mild steel")
    assert at.selectbox(key="mild_preset").value == (
        "DS/EN 1992-1-1:2005 + DK NA:2024"
    )
    assert at.number_input(key="mild_fytk").value == pytest.approx(615.0)
    assert at.number_input(key="mild_futk").value == pytest.approx(650.0)

    _goto_material_tab(at, "Prestressing steel")
    assert at.selectbox(key="pre_preset").value == "EN 1992-1-1:2005"
    assert at.number_input(key="pre_fytk").value == pytest.approx(1711.0)
    assert at.number_input(key="pre_futk").value == pytest.approx(1800.0)

    assert at.session_state["_durable_input_scalars"]["conc_fck"] == (
        pytest.approx(41.0)
    )
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(
        41.0
    )
    assert at.session_state["_latest_inputs"]["mild_material_catalog"][
        "items"
    ][0]["fytk"] == pytest.approx(615.0)
    assert at.session_state["_latest_inputs"]["mild_material_catalog"][
        "items"
    ][0]["futk"] == pytest.approx(650.0)
    assert at.session_state["_latest_inputs"]["prestress_material_catalog"][
        "items"
    ][0]["fytk"] == pytest.approx(1711.0)
    assert at.session_state["_latest_inputs"]["prestress_material_catalog"][
        "items"
    ][0]["futk"] == pytest.approx(1800.0)
    assert not at.exception


def test_initial_replacement_preserves_explicit_fields_without_presets() -> None:
    """Exercise application before any prior-session preset marker can exist."""

    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["_input_tab"] = f"3 {chr(0x00B7)} Material parameters"
    at.session_state["_pending_project"] = (
        _EXPLICIT_FIELDS_WITHOUT_PRESETS_PROJECT.decode("utf-8")
    )
    at.run()

    assert not at.exception
    assert at.number_input(key="conc_fck").value == pytest.approx(41.0)
    assert at.session_state["conc_fck"] == pytest.approx(41.0)
    assert at.session_state["mild_fytk"] == pytest.approx(615.0)
    assert at.session_state["mild_futk"] == pytest.approx(650.0)
    assert at.session_state["pre_fytk"] == pytest.approx(1711.0)
    assert at.session_state["pre_futk"] == pytest.approx(1800.0)
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(
        41.0
    )
    assert at.session_state["_latest_inputs"]["mild_material_catalog"][
        "items"
    ][0]["fytk"] == pytest.approx(615.0)
    assert at.session_state["_latest_inputs"]["mild_material_catalog"][
        "items"
    ][0]["futk"] == pytest.approx(650.0)
    assert at.session_state["_latest_inputs"]["prestress_material_catalog"][
        "items"
    ][0]["fytk"] == pytest.approx(1711.0)
    assert at.session_state["_latest_inputs"]["prestress_material_catalog"][
        "items"
    ][0]["futk"] == pytest.approx(1800.0)


def test_successful_sparse_replacement_discards_old_results_events_and_reports() -> None:
    at = _build_history("altered-concrete")
    stale = {
        "results": {"source": "old project"},
        "result_sig": ("old", "result"),
        "result_plastic_sig": ("old", "plastic"),
        "result_elastic_sig": ("old", "elastic"),
        "result_fatigue_sig": ("old", "fatigue"),
        "result_capacity_contract_sig": ("old", "capacity"),
        "result_input_snapshot": {"source": "old project"},
        "calculation_record": {"source": "old project"},
        "report_buffer": b"old report",
        "report_bytes": b"old report",
        "report_signature": ("old", "report"),
        "report_filename": "old.pdf",
        "report_generated_on": "2026-08-25T00:00:00Z",
        "report_generation_record": {"source": "old project"},
        "_report_msg": ("success", "old report"),
        "_pending_input_events": {"conc_fck": 99.0},
        "_pending_report_events": {"rep_proj_no": "old project"},
    }
    for key, value in stale.items():
        at.session_state[key] = value

    _upload_sparse_project(at)

    for key in _OLD_ARTIFACT_KEYS:
        assert key not in at.session_state
    assert "_pending_input_events" not in at.session_state
    assert "_pending_report_events" not in at.session_state
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(35.0)
