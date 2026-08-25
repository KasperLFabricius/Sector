"""Independent publication oracle for the AR-07 closure boundary."""

from __future__ import annotations

import functools
import html.parser
import io
import re
from copy import deepcopy

import pypdf
import pytest

from tools import report_render_fixture
from tools.manual_render_fixture import manual


# Deliberately independent of every production vocabulary list and detector.
HOSTILE_SENTINEL = (
    "RAW-BOUNDARY-9Z GitHub pull_request PR #907 git-commit source_control "
    "development-history development/process SHA-256 hash payload schema "
    "contract internal-ID private_identifier EQ-BOUNDARY-91"
)
_NORMALIZED_ORACLE_PHRASES = (
    "github",
    "pull request",
    "git commit",
    "source control",
    "development history",
    "development process",
    "sha",
    "sha 256",
    "sha256",
    "hash",
    "payload",
    "schema",
    "contract",
    "provenance",
)


class _VisibleHTML(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)


def _independent_oracle_hits(text: str) -> tuple[str, ...]:
    normalized = " ".join(
        re.sub(r"[^a-z0-9]+", " ", text.casefold()).split()
    )
    normalized_equation_copy = re.sub(r"\bu\s+eq\b", "ueq", normalized)
    padded = f" {normalized} "
    hits = [
        phrase
        for phrase in _NORMALIZED_ORACLE_PHRASES
        if f" {phrase} " in padded
    ]
    if re.search(r"\bpr\s+\d+\b", normalized):
        hits.append("numbered pull request")
    if re.search(
        r"\b(?:internal|private)\s+(?:id|ids|identifier|identifiers|key|keys)\b",
        normalized,
    ):
        hits.append("non-public identifier")
    if re.search(
        r"\beq\s+(?=[a-z])(?:[a-z0-9]+\s+)*\d+\b",
        normalized_equation_copy,
    ):
        hits.append("non-public equation identifier")
    if re.search(
        r"\b(?:fatigue|report|project|plastic|elastic|torsion|shear|capacity|"
        r"sls|heightened)(?:_[a-z0-9]+){2,}\b",
        text,
        flags=re.IGNORECASE,
    ):
        hits.append("private application identifier")
    return tuple(dict.fromkeys(hits))


def _pdf_text(pdf: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _html_text(document: bytes) -> str:
    parser = _VisibleHTML()
    parser.feed(document.decode("utf-8"))
    return " ".join(parser.parts)


@functools.lru_cache(maxsize=3)
def _profile_pdf(profile: str) -> bytes:
    return report_render_fixture.build_fixture_pdf(
        figures=False,
        profile=profile,
    )


def test_independent_oracle_detects_the_complete_hostile_sentinel():
    hits = _independent_oracle_hits(HOSTILE_SENTINEL)

    assert len(hits) >= 14


@pytest.mark.parametrize(
    "text",
    (
        "Eq.Plastic.07",
        "EQ/PLASTIC/07",
        "eq:plastic:07",
        "fatigue_gamma_s",
    ),
)
def test_independent_oracle_catches_separator_variants_and_private_keys(text):
    assert _independent_oracle_hits(text)


@pytest.mark.parametrize(
    "text",
    (
        "Eq. (6.31)",
        "u_eq",
        "u_eq and u_bound are dimensionless; max(1.0, u_eq) applies",
        "gamma_Ff gamma_s gamma_V gamma_c,fat",
    ),
)
def test_independent_oracle_preserves_engineering_notation(text):
    assert _independent_oracle_hits(text) == ()


def test_manual_html_and_every_report_profile_have_zero_oracle_hits():
    publications = {
        "manual PDF": _pdf_text(manual.build_manual_pdf_bytes(figures=False)),
        "manual HTML": _html_text(manual.build_manual_html_bytes()),
        **{
            f"{profile} report": _pdf_text(_profile_pdf(profile))
            for profile in ("Brief", "Standard", "Audit")
        },
    }

    offenders = {
        name: _independent_oracle_hits(text)
        for name, text in publications.items()
        if _independent_oracle_hits(text)
    }

    assert offenders == {}


def test_unmodified_report_fixture_has_zero_false_suppressions(caplog):
    for profile in ("Brief", "Standard", "Audit"):
        inp = report_render_fixture._inputs()
        out = report_render_fixture._results(inp)
        report_render_fixture.sector_report.build_report(
            {},
            inp,
            out,
            figures=False,
            profile=profile,
        )

    assert "Suppressed untrusted diagnostic" not in caplog.text


def _poison_retained_result_reasons(scope: dict) -> None:
    plastic = scope["plastic"]
    plastic.update(
        util=None,
        util_valid=False,
        util_reason=HOSTILE_SENTINEL,
        util_origin_inside_or_on=False,
        check_util=True,
        closed=True,
        converged=True,
    )
    transverse = scope.setdefault(
        "transverse_reinforcement",
        {
            "edition": "DS/EN 1992-1-1:2005 + DK NA:2024",
            "checks": [],
        },
    )
    transverse.update(
        status="NOT ASSESSED",
        checks=[],
        governing=None,
        governing_utilisation=None,
        reason=HOSTILE_SENTINEL,
    )


def _assert_hostile_report_diagnostics_are_hidden(pdf: bytes) -> None:
    text = _pdf_text(pdf)
    compact = " ".join(text.split())

    assert "RAW-BOUNDARY-9Z" not in text
    assert _independent_oracle_hits(text) == ()
    assert "Review the Plastic capacity envelope and applied actions" in compact
    assert (
        "Review the shear and torsion link-detailing inputs and result status"
        in compact
    )
    assert "Review the calculation inputs and recalculate" in compact


def test_every_report_profile_hides_top_level_and_per_case_result_reasons(caplog):
    for profile in ("Brief", "Standard", "Audit"):
        named_inp = report_render_fixture._inputs()
        named_out = report_render_fixture._results(named_inp)
        named_out["fatigue"] = {
            **named_out["fatigue"],
            "warnings": (HOSTILE_SENTINEL,),
            "errors": (HOSTILE_SENTINEL,),
        }
        named_out["heightened_crack_control"] = {
            **named_out["heightened_crack_control"],
            "warnings": (HOSTILE_SENTINEL,),
        }
        for entry in named_out["plastic_cases"]:
            _poison_retained_result_reasons(entry["results"])
        named_pdf = report_render_fixture.sector_report.build_report(
            {},
            named_inp,
            named_out,
            figures=False,
            profile=profile,
        )
        _assert_hostile_report_diagnostics_are_hidden(named_pdf)

        top_inp = deepcopy(named_inp)
        top_out = deepcopy(named_out)
        for key in ("plastic_cases", "elastic_cases"):
            top_inp.pop(key, None)
            top_out.pop(key, None)
        _poison_retained_result_reasons(top_out)
        top_pdf = report_render_fixture.sector_report.build_report(
            {},
            top_inp,
            top_out,
            figures=False,
            profile=profile,
        )
        _assert_hostile_report_diagnostics_are_hidden(top_pdf)

    assert HOSTILE_SENTINEL in caplog.text
