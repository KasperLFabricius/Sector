"""End-to-end profile publication contracts on the frozen report fixture."""

from __future__ import annotations

import io

from pypdf import PdfReader

from tools import report_render_fixture


def _profile_pdf(profile: str) -> bytes:
    return report_render_fixture.build_fixture_pdf(
        figures=False,
        profile=profile,
    )


def _profile_text(profile: str) -> str:
    reader = PdfReader(io.BytesIO(_profile_pdf(profile)))
    return " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages
    )


def test_brief_frozen_fixture_obeys_the_three_page_hard_limit():
    reader = PdfReader(io.BytesIO(_profile_pdf("Brief")))
    assert len(reader.pages) <= 3
    assert len(reader.pages) == 3
    text = _profile_text("Brief")
    assert "Report profile Brief" in text
    assert "Results overview" in text
    assert "Governing calculation register" in text
    assert "no report-side ranking or calculation is performed" in text


def test_every_profile_retains_requested_statuses_and_engineering_values():
    expected = (
        "Plastic bending PL-QA-1 PASS 80.0 %",
        "Plastic bending PL-QA-2 FAIL 125.0 %",
        "Crack width EL-QA-1 EXCEEDS USER-SPECIFIED LIMIT 0.213 mm",
        "Crack width EL-QA-2 NOT REQUESTED",
        "Torsion PL-QA-1 FAIL 162.7 %",
        "Combined M-V-T - DK NA sum PL-QA-1 FAIL 266.2 %",
        "Fatigue Road traffic PASS 29.5 %",
    )
    for profile in ("Brief", "Standard", "Audit"):
        text = _profile_text(profile)
        for value in expected:
            assert value in text


def test_every_profile_begins_with_the_same_freshness_and_basis_dashboard():
    expected = (
        "Calculation state CURRENT - frozen QA fixture",
        f"Input SHA-256 {'f' * 64}",
        "Selected basis / methods",
        "Report profile",
        "DK heightened crack-control applicability is user-selected",
    )
    for profile in ("Brief", "Standard", "Audit"):
        reader = PdfReader(io.BytesIO(_profile_pdf(profile)))
        cover = " ".join((reader.pages[0].extract_text() or "").split())
        for value in expected:
            assert value in cover


def test_internal_equation_keys_are_audit_only_and_standard_is_default_depth():
    brief = _profile_text("Brief")
    standard = _profile_text("Standard")
    audit = _profile_text("Audit")
    assert "EQ-" not in brief
    assert "EQ-" not in standard
    assert "EQ-MATERIALS.CONCRETE.FCD" in audit
    assert "Report profile Standard" in standard
    assert "Report profile Audit" in audit
    assert "Audit does not mean approved, compliant or certified" in audit


def test_profile_depth_is_monotonic_without_changing_figures_policy():
    pages = {
        profile: len(PdfReader(io.BytesIO(_profile_pdf(profile))).pages)
        for profile in ("Brief", "Standard", "Audit")
    }
    assert pages["Brief"] < pages["Standard"] <= pages["Audit"]


def test_long_case_inventory_uses_a_complete_compact_running_header():
    reader = PdfReader(io.BytesIO(_profile_pdf("Standard")))
    header_fragments = []

    def collect(text, cm, tm, _font, size):
        value = " ".join(text.split())
        y = float(cm[5]) + float(tm[5])
        if value and y > 790 and float(size) == 7.5:
            header_fragments.append(value)

    reader.pages[0].extract_text(visitor_text=collect)
    header = " ".join(header_fragments)
    assert "Cases: Plastic 2; Elastic 2; Fatigue 1" in header
    assert "..." not in header


def test_calculation_subheadings_retain_first_table_or_equation_on_same_page():
    headings = (
        "Concrete",
        "Resistance",
        "Resistances",
        "Accepted strain plane",
        "Physical resistance components",
        "Accepted section resultants",
        "Governing reinforcement and tendon response",
        "Governing cracking threshold",
        "Step 2 - neutralise the long-term concrete stress",
        "Governing reinforcement element - R1",
        "Textbook calculation - governing reinforcement fatigue",
        "Textbook calculation - governing concrete fatigue",
    )
    for profile in ("Standard", "Audit"):
        reader = PdfReader(io.BytesIO(_profile_pdf(profile)))
        seen = set()
        for page in reader.pages:
            fragments = []

            def collect(text, cm, tm, _font, size):
                value = " ".join(text.split())
                if value:
                    fragments.append((
                        value,
                        float(size),
                        float(cm[5]) + float(tm[5]),
                    ))

            page.extract_text(visitor_text=collect)
            for heading in headings:
                matches = [
                    y for value, size, y in fragments
                    if value == heading and size == 11.5
                ]
                for heading_y in matches:
                    seen.add(heading)
                    assert any(
                        y < heading_y - 4
                        and (
                            value.startswith("SECTOR-MATH[")
                            or value.startswith("See Table")
                        )
                        for value, _size, y in fragments
                    ), (profile, heading)
        assert set(headings) <= seen
