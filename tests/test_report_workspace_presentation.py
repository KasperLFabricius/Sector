"""Report UI preferences and preview preserve the original publication state."""

from __future__ import annotations

import base64
import copy

import pytest

from app import report_profiles
from app import report_workspace_presentation as ui


@pytest.mark.parametrize("profile", report_profiles.REPORT_PROFILE_KEYS)
def test_profile_outline_uses_each_existing_policy(profile):
    policy = report_profiles.resolve_profile(profile)
    rows = {row["Content"]: row["Coverage"] for row in ui.profile_outline(profile)}
    assert rows["Figures"] == "All applicable figures"
    assert "statuses, warnings, sources and limitations" in rows["Assessment"]
    assert (rows["QA appendix"] == "Included") is policy.include_qa_appendix
    assert (rows["Substitutions"] == "Available in Audit") is (policy.substitution_scope == "none")
    assert ("Full result tables" in rows["Results"]) is (policy.non_governing_scope == "complete")


@pytest.mark.parametrize("extra", [
    "rep_author", "rep_checker", "rep_approver", "rep_proj_no", "rep_comments",
    "source_register", "plastic_cases", "elastic_cases", "mode", "figures",
])
def test_preset_rejects_every_identity_engineering_and_coverage_extension(extra):
    with pytest.raises(ValueError, match="only its profile"):
        ui.read_preset({"profile": "Standard", extra: "value"})


@pytest.mark.parametrize("value", [None, "Standard", {}, {"profile": None}, {"profile": "Unknown"}])
def test_invalid_preset_fails_closed(value):
    with pytest.raises((ValueError, TypeError)):
        ui.read_preset(value)


def test_preset_preview_is_explicit_and_leaves_the_supplied_state_unchanged():
    state = {"profile": "Audit"}
    original = copy.deepcopy(state)
    preset = ui.read_preset(state)
    changes = ui.preset_changes("Standard", preset)
    assert changes == ({"Setting": "Report profile", "Current": "Standard", "Proposed": "Audit"},)
    assert ui.preset_changes("Audit", preset) == ()
    assert state == original


PDF = b"%PDF-1.7\nexact binary bytes \x00\xff\x01\n%%EOF"
SIGNATURE = ("input", ("metadata", "Standard"), ("0.96.9", "revision"), "contract")


def _preview(**changes):
    args = {
        "artifact_signature": SIGNATURE,
        "current_signature": SIGNATURE,
        "requested_signature": SIGNATURE,
        "pending_inputs": False,
    }
    args.update(changes)
    return ui.pdf_preview_url(PDF, **args)


def test_preview_contains_the_exact_original_pdf_bytes():
    url = _preview()
    assert url.startswith("data:application/pdf;base64,")
    assert base64.b64decode(url.split(",", 1)[1], validate=True) == PDF


@pytest.mark.parametrize("field", ["artifact_signature", "current_signature", "requested_signature"])
@pytest.mark.parametrize("value", [None, (), ("different",)])
def test_missing_mismatched_or_unrequested_signature_hides_preview(field, value):
    assert _preview(**{field: value}) is None


@pytest.mark.parametrize("value", [True, None, 0, "False"])
def test_pending_or_uncertain_inputs_hide_preview(value):
    assert _preview(pending_inputs=value) is None


@pytest.mark.parametrize("data", [None, b"", b"<html>not PDF</html>", bytearray(PDF), "%PDF-"])
def test_preview_accepts_only_generated_pdf_bytes(data):
    assert ui.pdf_preview_url(
        data, artifact_signature=SIGNATURE, current_signature=SIGNATURE,
        requested_signature=SIGNATURE, pending_inputs=False,
    ) is None


def test_meta_profile_revision_and_engineering_changes_each_expire_preview():
    for position in range(len(SIGNATURE)):
        changed = list(SIGNATURE)
        changed[position] = "changed"
        assert _preview(current_signature=tuple(changed)) is None


def test_outline_returns_fresh_read_only_content_descriptions():
    rows = ui.profile_outline("Standard")
    rows[0]["Coverage"] = "user modification"
    assert ui.profile_outline("Standard")[0]["Coverage"] == "Document identity and section description"


def test_declared_case_inventory_preserves_names_without_selecting_governing_rows():
    assignments = [("Project", ""), ("Plastic", "P2"), ("Plastic", "P1"),
                   ("Elastic", "E1"), ("Fatigue", "Spectrum A")]
    original = list(assignments)
    assert ui.declared_case_rows(assignments) == (
        {"Family": "Plastic", "Case or spectrum": "P2"},
        {"Family": "Plastic", "Case or spectrum": "P1"},
        {"Family": "Elastic", "Case or spectrum": "E1"},
        {"Family": "Fatigue", "Case or spectrum": "Spectrum A"},
    )
    assert assignments == original
