"""Contract tests for the planned Sector v0.93 development programme."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "v093_decision_register.md"
PROGRAMME = ROOT / "docs" / "v093_pr_programme.md"


def _ascii(path: Path) -> str:
    return path.read_text(encoding="ascii")


def test_v093_programme_documents_are_ascii_and_linked_from_readme():
    decisions = _ascii(DECISIONS)
    programme = _ascii(PROGRAMME)
    readme = _ascii(ROOT / "README.md")

    assert "[v0.93 decision register](docs/v093_decision_register.md)" in readme
    assert "[v0.93 pull-request programme](docs/v093_pr_programme.md)" in readme
    assert "[Sector product identity](product_identity.md)" in decisions
    assert "[v0.93 decision register](v093_decision_register.md)" in programme


def test_decision_register_has_one_complete_stable_id_sequence():
    decisions = _ascii(DECISIONS)
    ids = re.findall(r"^\| (D093-\d{3}) \|", decisions, flags=re.MULTILINE)

    assert ids == [f"D093-{number:03d}" for number in range(1, 28)]
    assert len(ids) == len(set(ids))


def test_owner_scope_decisions_are_explicit_and_noncontradictory():
    decisions = _ascii(DECISIONS)

    for required in (
        "Ordinary crack-width acceptance is optional.",
        "The first-generation DK/NA heightened crack-control check is separately selectable and its permitted crack width is mandatory.",
        "Confinement is deferred beyond 0.93.",
        "Remove bridge-specific checks that require semantic component mapping.",
        "Formula typography is checked explicitly in both manuals and reports.",
        "Every complete calculation is presented as a student-readable worked example, including numerical substitution for every meaningful live step.",
        "Reports offer Brief, Standard and Audit profiles.",
        "A double-clicked BAT in the extracted official source ZIP builds a complete portable Windows distribution without a separate PowerShell command.",
        "The distributable Windows application is an unsigned portable application, not a signed Windows production release.",
        "Sector never issues a global code-compliance conclusion.",
    ):
        assert required in decisions

    assert "no fictitious `EN 1992-2:2023` option is created" in decisions
    assert "No Danish National Annex for that edition is applied" not in decisions
    assert "no Danish NA applied" in decisions
    assert "OCR is not an implementation authority" in decisions
    assert "docs/sector_v093_decision_register.xlsx" in decisions


def test_programme_slice_order_and_initial_status_are_frozen():
    programme = _ascii(PROGRAMME)
    rows = re.findall(
        r"^\| (\d+) \| (PR-[^|]+?) \| ([^|]+?) \| (In progress|Planned) \|$",
        programme,
        flags=re.MULTILINE,
    )

    assert [int(row[0]) for row in rows] == list(range(1, 11))
    assert [row[1].split(" - ", 1)[0] for row in rows] == [
        "PR-01",
        "PR-02",
        "PR-03",
        "PR-04",
        "PR-05",
        "PR-06",
        "PR-07A",
        "PR-07B",
        "PR-08",
        "PR-09",
    ]
    assert rows[0][3] == "In progress"
    assert all(row[3] == "Planned" for row in rows[1:])


def test_complete_calculation_not_only_crack_spacing_is_textbook_readable():
    programme = _ascii(PROGRAMME)
    collapsed = " ".join(programme.split())

    assert "Crack spacing is the example that exposed the defect, not the scope boundary." in collapsed
    for family in (
        "geometry properties",
        "elastic and cracked section response",
        "plastic resistance/envelopes",
        "shear",
        "torsion",
        "interaction",
        "detailing",
        "fatigue",
        "ordinary crack width",
        "heightened crack control",
    ):
        assert family in collapsed
    for step in (
        "**Question.**",
        "**Given data.**",
        "**Preparation.**",
        "**Equation.**",
        "**Substitution.**",
        "**Interim result.**",
        "**Numerical solution evidence.**",
        "**Final result and criterion.**",
        "**Interpretation and scope.**",
    ):
        assert step in programme
    assert "Standard and Audit must both be independently followable" in collapsed


def test_pr01_is_planning_only_and_current_release_remains_0_92():
    programme = _ascii(PROGRAMME)
    readme = _ascii(ROOT / "README.md")

    pr01 = programme.split("### PR-01", 1)[1].split("### PR-02", 1)[0]
    assert "no runtime, solver, schema, version or packaging behaviour changes" in pr01
    assert "Current release: **Sector 0.92**" in readme
    assert "no Windows executable is published" in " ".join(readme.split())


def test_programme_preserves_product_and_release_boundaries():
    combined = " ".join((_ascii(DECISIONS) + "\n" + _ascii(PROGRAMME)).split())

    for required in (
        "not engineering certification",
        "does not make Sector a complete Eurocode",
        "never issues a global code-compliance conclusion",
        "unsigned portable",
        "does not install or require administrator privileges",
        "never claims a digital signature",
        "Current torsion and combined M-V-T solvers remain first-generation only",
        "two independent human readings of the licensed visual formula",
    ):
        assert required.casefold() in combined.casefold()

    assert "EN 1992-2:2023" in combined
    assert combined.count("fictitious `EN 1992-2:2023`") == 1
