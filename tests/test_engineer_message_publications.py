"""Independent publication oracle for the AR-07 closure boundary."""

from __future__ import annotations

import functools
import html.parser
import io
import re

import pypdf

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
        r"\beq[-_]+[a-z0-9][a-z0-9._-]*\b",
        text,
        flags=re.IGNORECASE,
    ):
        hits.append("non-public equation identifier")
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


def test_every_report_profile_hides_hostile_result_messages(caplog):
    for profile in ("Brief", "Standard", "Audit"):
        inp = report_render_fixture._inputs()
        out = report_render_fixture._results(inp)
        out["fatigue"] = {
            **out["fatigue"],
            "warnings": (HOSTILE_SENTINEL,),
            "errors": (HOSTILE_SENTINEL,),
        }
        out["heightened_crack_control"] = {
            **out["heightened_crack_control"],
            "warnings": (HOSTILE_SENTINEL,),
        }

        pdf = report_render_fixture.sector_report.build_report(
            {},
            inp,
            out,
            figures=False,
            profile=profile,
        )
        text = _pdf_text(pdf)

        assert "RAW-BOUNDARY-9Z" not in text
        assert _independent_oracle_hits(text) == ()
        assert "Review the calculation inputs and recalculate" in text

    assert "Suppressed untrusted diagnostic" in caplog.text
