"""STATE-H01 project-upload identity and all-state transaction evidence."""

from __future__ import annotations

import inspect
import pathlib
import sys

import pytest
from streamlit.proto.Common_pb2 import FileURLs
from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec
from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

APP = str(ROOT / "app" / "sector_app.py")

import fatigue_inputs  # noqa: E402
import project_io  # noqa: E402

_RESULT_KEYS = (
    "results",
    "result_sig",
    "result_plastic_sig",
    "result_elastic_sig",
    "result_fatigue_sig",
    "result_plastic_case_context_sig",
    "result_elastic_case_context_sig",
    "result_plastic_bending_context_sig",
    "result_input_snapshot",
    "calculation_record",
    "_case_error",
    "pl_state",
    "report_buffer",
    "report_bytes",
    "report_signature",
    "report_filename",
    "report_generated_on",
    "report_generation_record",
    "_report_msg",
)


def _project_bytes(fck: float, *, fatigue: bool = False) -> bytes:
    tables = {}
    scalars = {"conc_fck": fck}
    if fatigue:
        tables[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
            fatigue_inputs.normalise_spectrum_table(
                [
                    {
                        "spectrum": "Traffic",
                        "name": "FAT-01",
                        "cycles": 2e6,
                        "n_long_ed_kn": -500.0,
                        "mx_short_ed_knm": 80.0,
                    }
                ]
            )
        )
        scalars["fatigue_on"] = True
    return project_io.dump_project(tables, scalars).encode("utf-8")


def _uploaded(content: bytes, *, file_id: str = "same-file") -> UploadedFile:
    return UploadedFile(
        UploadedFileRec(
            file_id,
            "sector_section.json",
            "application/json",
            content,
        ),
        FileURLs(),
    )


def _upload_widget_key(at: AppTest) -> str:
    generation = (
        at.session_state["_project_upload_widget_generation"]
        if "_project_upload_widget_generation" in at.session_state
        else 0
    )
    return "project_upload" if generation == 0 else f"project_upload_{generation}"


def _fresh_with_upload(content: bytes) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["_input_tab"] = "Project"
    at.session_state["project_upload"] = _uploaded(content)
    return at.run()


def _fresh() -> AppTest:
    return AppTest.from_file(APP, default_timeout=90).run()


def _upload(at: AppTest, content: bytes) -> AppTest:
    at.session_state[_upload_widget_key(at)] = _uploaded(content)
    return at.run()


def _goto_page(at: AppTest, page: str) -> AppTest:
    current = (
        at.session_state["_main_page"]
        if "_main_page" in at.session_state
        else None
    )
    if current != page:
        at.segmented_control(key="_main_page").set_value(page).run()
    return at


def _goto_project(at: AppTest) -> AppTest:
    _goto_page(at, "Inputs")
    if at.session_state["_input_tab"] != "Project":
        at.session_state["_input_tab"] = "Project"
        at.run()
    return at


def _calculate(at: AppTest) -> AppTest:
    _goto_page(at, "Analysis")
    if not any(button.key == "calculate" for button in at.button):
        _goto_page(at, "Inputs")
        _goto_page(at, "Analysis")
    at.button(key="calculate").click().run()
    assert "results" in at.session_state, [item.value for item in at.error]
    return at


def _project_signature(at: AppTest) -> str:
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {
        key: at.session_state[key]
        for key in project_io.SCALAR_KEYS
        if key in at.session_state
    }
    return project_io.persistence_sha256(tables, scalars)


def _replacement_bytes(
    at: AppTest,
    fck: float,
    *,
    fatigue: bool = False,
) -> bytes:
    tables = {
        key: at.session_state[key]
        for key in project_io.PROJECT_TABLE_KEYS
        if key in at.session_state
    }
    scalars = {
        key: at.session_state[key]
        for key in project_io.SCALAR_KEYS
        if key in at.session_state
    }
    scalars["conc_fck"] = fck
    if fatigue:
        tables[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
            fatigue_inputs.normalise_spectrum_table(
                [
                    {
                        "spectrum": "Traffic",
                        "name": "FAT-01",
                        "cycles": 2e6,
                        "n_long_ed_kn": -500.0,
                        "mx_short_ed_knm": 80.0,
                    }
                ]
            )
        )
        scalars["fatigue_on"] = True
    return project_io.dump_project(tables, scalars).encode("utf-8")


def _completed_result_evidence(at: AppTest) -> tuple[tuple[str, ...], str]:
    _calculate(at)
    _goto_project(at)
    dependent_evidence = {
        "_case_error": "last-valid-A calculation diagnostic",
        "pl_state": {"source": "last-valid-A"},
        "report_buffer": b"last-valid-report",
        "report_bytes": b"last-valid-report",
        "report_signature": ("A", "report"),
        "report_filename": "last-valid-A.pdf",
        "report_generated_on": "2026-08-25T00:00:00Z",
        "report_generation_record": {"source": "last-valid-A"},
        "_report_msg": ("success", "last-valid-A report"),
    }
    for key, value in dependent_evidence.items():
        at.session_state[key] = value
    present = tuple(key for key in _RESULT_KEYS if key in at.session_state)
    assert "results" in present
    return present, project_io.result_sha256(
        {key: at.session_state[key] for key in present}
    )


def _assert_result_evidence(
    at: AppTest,
    expected: tuple[tuple[str, ...], str],
) -> None:
    present, digest = expected
    assert tuple(key for key in _RESULT_KEYS if key in at.session_state) == present
    assert project_io.result_sha256(
        {key: at.session_state[key] for key in present}
    ) == digest


def _visible_upload_errors(at: AppTest) -> list[str]:
    return [str(item.value) for item in at.error]


def test_content_identity_and_validation_depend_only_on_raw_bytes() -> None:
    assert list(inspect.signature(project_io.prepare_project_upload).parameters) == [
        "content"
    ]
    a = _project_bytes(41.0)
    b = _project_bytes(42.0)
    assert len(a) == len(b)

    prepared_a = project_io.prepare_project_upload(a)
    prepared_b = project_io.prepare_project_upload(b)
    prepared_a_again = project_io.prepare_project_upload(a)
    assert prepared_a.content_identity != prepared_b.content_identity
    assert prepared_a_again == prepared_a

    invalid_utf8 = b"\xff" * len(a)
    for _retry in range(2):
        with pytest.raises(project_io.ProjectInputError) as exc_info:
            project_io.prepare_project_upload(invalid_utf8)
        assert project_io.engineer_error_message(exc_info.value) == (
            "the selected file is not a readable Sector project"
        )


def test_real_streamlit_upload_applies_same_name_same_size_a_b_a() -> None:
    a = _project_bytes(41.0)
    b = _project_bytes(42.0)
    assert len(a) == len(b)

    at = _fresh_with_upload(a)
    assert not at.exception
    assert at.session_state["conc_fck"] == pytest.approx(41.0)
    assert at.session_state["_project_upload_content_identity"] == (
        project_io.project_upload_identity(a)
    )

    _upload(at, b)
    assert not at.exception
    assert at.session_state["conc_fck"] == pytest.approx(42.0)
    assert at.session_state["_project_upload_content_identity"] == (
        project_io.project_upload_identity(b)
    )

    _upload(at, a)
    assert not at.exception
    assert at.session_state["conc_fck"] == pytest.approx(41.0)
    assert at.session_state["_project_upload_content_identity"] == (
        project_io.project_upload_identity(a)
    )


def test_invalid_retries_retain_results_then_corrected_same_size_applies() -> None:
    at = _fresh()
    a = _replacement_bytes(at, 41.0)
    _goto_project(at)
    _upload(at, a)
    assert at.session_state["_project_upload_content_identity"] == (
        project_io.project_upload_identity(a)
    )

    b = _replacement_bytes(at, 42.0)
    invalid_json = b"{" + (b" " * (len(b) - 1))
    invalid_utf8 = b"\xff" * len(b)
    assert len(invalid_utf8) == len(invalid_json) == len(b)

    before_results = _completed_result_evidence(at)
    before_project = _project_signature(at)
    before_identity = at.session_state["_project_upload_content_identity"]

    # Re-submit identical invalid bytes, then a different invalid encoding. No
    # failed identity is latched, and every attempt leaves the last valid state.
    for invalid in (invalid_utf8, invalid_utf8, invalid_json):
        _upload(at, invalid)

        assert not at.exception
        assert _project_signature(at) == before_project
        assert at.session_state["_project_upload_content_identity"] == (
            before_identity
        )
        _assert_result_evidence(at, before_results)
        errors = _visible_upload_errors(at)
        assert any("New file was not applied" in message for message in errors)
        assert any(
            "Select an intact, compatible Sector project file" in message
            for message in errors
        )
        assert all("UnicodeDecodeError" not in message for message in errors)
        assert all("JSONDecodeError" not in message for message in errors)

    _upload(at, b)

    assert not at.exception
    assert at.session_state["conc_fck"] == pytest.approx(42.0)
    assert at.session_state["_project_upload_content_identity"] == (
        project_io.project_upload_identity(b)
    )
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(
        42.0
    )
    for key in _RESULT_KEYS:
        assert key not in at.session_state


def test_late_application_failure_rolls_back_and_identical_bytes_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = _fresh()
    a = _replacement_bytes(at, 41.0)
    _goto_project(at)
    _upload(at, a)
    assert at.session_state["_project_upload_content_identity"] == (
        project_io.project_upload_identity(a)
    )

    b = _replacement_bytes(at, 42.0, fatigue=True)
    before_results = _completed_result_evidence(at)
    before_project = _project_signature(at)
    before_identity = at.session_state["_project_upload_content_identity"]

    original_normalise = fatigue_inputs.normalise_spectrum_table
    application_failures = 0

    def fail_during_application(value):
        nonlocal application_failures
        if sys._getframe(1).f_code.co_name == "_apply_project_text":
            application_failures += 1
            raise RuntimeError("private forced application diagnostic")
        return original_normalise(value)

    monkeypatch.setattr(
        fatigue_inputs,
        "normalise_spectrum_table",
        fail_during_application,
    )
    _upload(at, b)

    assert application_failures == 1
    assert not at.exception
    assert _project_signature(at) == before_project
    assert at.session_state["_project_upload_content_identity"] == before_identity
    _assert_result_evidence(at, before_results)
    errors = _visible_upload_errors(at)
    assert any("New file was not applied" in message for message in errors)
    assert all("private forced" not in message for message in errors)

    monkeypatch.setattr(
        fatigue_inputs,
        "normalise_spectrum_table",
        original_normalise,
    )
    _upload(at, b)

    assert not at.exception
    assert at.session_state["conc_fck"] == pytest.approx(42.0)
    assert at.session_state["_project_upload_content_identity"] == (
        project_io.project_upload_identity(b)
    )
    assert at.session_state["_latest_inputs"]["concrete"].fck == pytest.approx(
        42.0
    )
    for key in _RESULT_KEYS:
        assert key not in at.session_state
