"""Contract tests for the planned Sector v0.93 development programme."""

from __future__ import annotations

import hashlib
import posixpath
import re
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "v093_decision_register.md"
PROGRAMME = ROOT / "docs" / "v093_pr_programme.md"
ACCEPTANCE = ROOT / "docs" / "pr01_v093_programme_acceptance.md"
WORKBOOK = ROOT / "docs" / "sector_v093_decision_register.xlsx"
WORKBOOK_BUILDER = ROOT / "tools" / "build_v093_decision_workbook.ps1"

BASELINE_REVISION = "decd1232abb0a082639de90726c125dc988e1078"
BASELINE_TREE = "f09bf8cb500f2ae02c2c30a8f085c67153fe619a"

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CORE_NS = (
    "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
)
_DC_NS = "http://purl.org/dc/elements/1.1/"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

_OFFICE_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
)
_EXPECTED_OOXML_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "docProps/app.xml",
    "docProps/core.xml",
    "xl/_rels/workbook.xml.rels",
    "xl/calcChain.xml",
    "xl/sharedStrings.xml",
    "xl/styles.xml",
    "xl/theme/theme1.xml",
    "xl/workbook.xml",
    *(f"xl/tables/table{number}.xml" for number in range(1, 6)),
    *(f"xl/worksheets/sheet{number}.xml" for number in range(1, 6)),
    *(
        f"xl/worksheets/_rels/sheet{number}.xml.rels"
        for number in range(1, 6)
    ),
}
_EXPECTED_RELATIONSHIPS = {
    "_rels/.rels": {
        (
            "http://schemas.openxmlformats.org/package/2006/relationships/"
            "metadata/core-properties",
            "docProps/core.xml",
        ),
        (_OFFICE_REL + "extended-properties", "docProps/app.xml"),
        (_OFFICE_REL + "officeDocument", "xl/workbook.xml"),
    },
    "xl/_rels/workbook.xml.rels": {
        *(
            (_OFFICE_REL + "worksheet", f"worksheets/sheet{number}.xml")
            for number in range(1, 6)
        ),
        (_OFFICE_REL + "calcChain", "calcChain.xml"),
        (_OFFICE_REL + "sharedStrings", "sharedStrings.xml"),
        (_OFFICE_REL + "styles", "styles.xml"),
        (_OFFICE_REL + "theme", "theme/theme1.xml"),
    },
    **{
        f"xl/worksheets/_rels/sheet{number}.xml.rels": {
            (_OFFICE_REL + "table", f"../tables/table{number}.xml")
        }
        for number in range(1, 6)
    },
}
_EXPECTED_CONTENT_TYPE_DEFAULTS = {
    "rels": "application/vnd.openxmlformats-package.relationships+xml",
    "xml": "application/xml",
}
_EXPECTED_CONTENT_TYPE_OVERRIDES = {
    "/xl/workbook.xml": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    ),
    "/xl/theme/theme1.xml": (
        "application/vnd.openxmlformats-officedocument.theme+xml"
    ),
    "/xl/styles.xml": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"
    ),
    "/xl/sharedStrings.xml": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
    ),
    "/xl/calcChain.xml": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.calcChain+xml"
    ),
    "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
    "/docProps/app.xml": (
        "application/vnd.openxmlformats-officedocument.extended-properties+xml"
    ),
    **{
        f"/xl/worksheets/sheet{number}.xml": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml."
            "worksheet+xml"
        )
        for number in range(1, 6)
    },
    **{
        f"/xl/tables/table{number}.xml": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"
        )
        for number in range(1, 6)
    },
}

_DECISION_HEADERS = [
    "Decision ID",
    "Frozen decision",
    "Reason and boundary",
    "Acceptance evidence",
    "Owning PR",
    "Status",
    "Disposition",
]
_PROGRAMME_HEADERS = ["Order", "Slice", "Depends on", "Status"]
_STANDARDS_HEADERS = [
    "Family",
    "Sector label and scope",
    "Status disclosure",
    "v0.93 boundary",
]
_PUBLICATION_HEADERS = [
    "Surface",
    "Current page",
    "Observed issue",
    "Required treatment",
]


def _ascii(path: Path) -> str:
    return path.read_text(encoding="ascii")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _lf_normalized_bytes(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _canonical_markdown_sha256(path: Path) -> str:
    return hashlib.sha256(_lf_normalized_bytes(path.read_bytes())).hexdigest().upper()


def _clean_markdown_cell(value: str) -> str:
    clean = value.strip().replace("`", "").replace("**", "")
    clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)
    return re.sub(r"\s+", " ", clean)


def _markdown_rows(
    text: str,
    first_cell_pattern: str,
    expected_columns: int,
) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if not re.match(first_cell_pattern, line):
            continue
        cells = [_clean_markdown_cell(cell) for cell in line.split("|")[1:-1]]
        assert len(cells) == expected_columns
        rows.append(cells)
    return rows


def _markdown_table_after(
    text: str,
    heading: str,
    first_header: str,
    expected_columns: int,
) -> list[list[str]]:
    _, separator, tail = text.partition(heading)
    assert separator, f"missing Markdown heading: {heading}"
    lines = tail.splitlines()
    header_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith(f"| {first_header} |")
    )
    rows = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = [_clean_markdown_cell(cell) for cell in line.split("|")[1:-1]]
        assert len(cells) == expected_columns
        rows.append(cells)
    return rows


def _expected_workbook_rows() -> dict[str, list[list[str]]]:
    decisions_text = _ascii(DECISIONS)
    programme_text = _ascii(PROGRAMME)
    decisions = _markdown_rows(decisions_text, r"^\| D093-\d{3} \|", 5)
    decision_rows = [
        [
            *row,
            "Frozen",
            "Deferred" if row[0] == "D093-013" else "Implement",
        ]
        for row in decisions
    ]
    programme_rows = _markdown_rows(
        programme_text,
        r"^\| \d+ \| PR-",
        4,
    )
    standards_rows = _markdown_table_after(
        decisions_text,
        "## Standards status frozen for implementation",
        "Family",
        4,
    )
    manual_rows = _markdown_table_after(
        programme_text,
        "### 2.8 Manual review and target information architecture",
        "Current page",
        3,
    )
    report_rows = _markdown_table_after(
        programme_text,
        "### 2.9 Report review and target profiles",
        "Current page",
        3,
    )
    publication_rows = [
        *[["Manual", *row] for row in manual_rows],
        *[["Report", *row] for row in report_rows],
    ]
    return {
        "Decisions": [_DECISION_HEADERS, *decision_rows],
        "PR Programme": [_PROGRAMME_HEADERS, *programme_rows],
        "Standards": [_STANDARDS_HEADERS, *standards_rows],
        "Publication QA": [_PUBLICATION_HEADERS, *publication_rows],
    }


def _xlsx_sheet_paths(archive: zipfile.ZipFile) -> tuple[list[str], dict[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_targets = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    }
    sheets = workbook.find(f"{{{_MAIN_NS}}}sheets")
    assert sheets is not None
    sheet_names = [sheet.attrib["name"] for sheet in sheets]
    sheet_paths = {}
    for sheet in sheets:
        target = relationship_targets[sheet.attrib[f"{{{_REL_NS}}}id"]]
        sheet_paths[sheet.attrib["name"]] = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
    return sheet_names, sheet_paths


def _xlsx_sheet_cells(
    archive: zipfile.ZipFile,
    sheet_name: str,
) -> tuple[list[str], dict[str, tuple[str, str | None]]]:
    sheet_names, sheet_paths = _xlsx_sheet_paths(archive)
    sheet_path = sheet_paths[sheet_name]

    shared_strings: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in shared.findall(f"{{{_MAIN_NS}}}si"):
            shared_strings.append(
                "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
            )

    cells: dict[str, tuple[str, str | None]] = {}
    sheet_xml = ET.fromstring(archive.read(sheet_path))
    for cell in sheet_xml.iter(f"{{{_MAIN_NS}}}c"):
        address = cell.attrib["r"]
        formula_node = cell.find(f"{{{_MAIN_NS}}}f")
        formula = formula_node.text if formula_node is not None else None
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            value = "".join(
                node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t")
            )
        else:
            value_node = cell.find(f"{{{_MAIN_NS}}}v")
            value = "" if value_node is None else value_node.text or ""
            if cell_type == "s":
                value = shared_strings[int(value)]
        cells[address] = (value, formula)
    return sheet_names, cells


def _sheet_table_rows(
    cells: dict[str, tuple[str, str | None]],
    rows: int,
    columns: int,
) -> list[list[str]]:
    return [
        [cells[f"{chr(65 + column)}{row}"][0] for column in range(columns)]
        for row in range(4, 4 + rows)
    ]


def _relationships(
    archive: zipfile.ZipFile,
    part_name: str,
) -> set[tuple[str, str]]:
    root = ET.fromstring(archive.read(part_name))
    relationships = root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    assert all(item.attrib.get("TargetMode") is None for item in relationships)
    return {(item.attrib["Type"], item.attrib["Target"]) for item in relationships}


def test_v093_programme_documents_are_ascii_and_linked_from_readme():
    decisions = _ascii(DECISIONS)
    programme = _ascii(PROGRAMME)
    acceptance = _ascii(ACCEPTANCE)
    readme = _ascii(ROOT / "README.md")

    assert "[v0.93 decision register](docs/v093_decision_register.md)" in readme
    assert "[v0.93 pull-request programme](docs/v093_pr_programme.md)" in readme
    assert "[formatted Excel register](docs/sector_v093_decision_register.xlsx)" in readme
    assert "[programme acceptance](docs/pr01_v093_programme_acceptance.md)" in readme
    assert "[Sector product identity](product_identity.md)" in decisions
    assert "[v0.93 decision register](v093_decision_register.md)" in programme
    assert "[Sector product identity](product_identity.md)" in acceptance


def test_pr01_baseline_revision_and_tree_are_exact_everywhere():
    combined = "\n".join(
        (
            _ascii(DECISIONS),
            _ascii(PROGRAMME),
            _ascii(ACCEPTANCE),
            _ascii(WORKBOOK_BUILDER),
        )
    )

    assert combined.count(BASELINE_REVISION) == 4
    assert combined.count(BASELINE_TREE) == 4
    assert "f25a74a1a234b7b09ddc1be216fe31187333abbd" not in combined

    # Official source archives intentionally contain no .git directory. The
    # string contract remains testable there; CI and repository checkouts also
    # prove that the recorded revision resolves to the exact tree object.
    if not (ROOT / ".git").exists():
        return

    resolved_tree = subprocess.run(
        ["git", "rev-parse", "--verify", f"{BASELINE_REVISION}^{{tree}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert resolved_tree == BASELINE_TREE


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

    assert (
        "no fictitious `en 1992-2:2023` option is created"
        in decisions.casefold()
    )
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


def test_excel_decision_register_package_is_publication_safe():
    assert WORKBOOK.is_file()
    assert WORKBOOK_BUILDER.is_file()
    assert not (ROOT / "tools" / "build_v093_decision_workbook.mjs").exists()

    with zipfile.ZipFile(WORKBOOK) as archive:
        names = set(archive.namelist())
        assert names == _EXPECTED_OOXML_PARTS
        content_types = ET.fromstring(archive.read("[Content_Types].xml"))
        assert {
            node.attrib["Extension"]: node.attrib["ContentType"]
            for node in content_types.findall(f"{{{_CONTENT_TYPES_NS}}}Default")
        } == _EXPECTED_CONTENT_TYPE_DEFAULTS
        assert {
            node.attrib["PartName"]: node.attrib["ContentType"]
            for node in content_types.findall(f"{{{_CONTENT_TYPES_NS}}}Override")
        } == _EXPECTED_CONTENT_TYPE_OVERRIDES
        relationship_parts = {name for name in names if name.endswith(".rels")}
        assert relationship_parts == set(_EXPECTED_RELATIONSHIPS)
        for part_name, expected in _EXPECTED_RELATIONSHIPS.items():
            assert _relationships(archive, part_name) == expected

        package_text = "\n".join(
            archive.read(name).decode("utf-8")
            for name in sorted(names)
            if name.endswith((".xml", ".rels"))
        )
        folded = package_text.casefold()
        for forbidden in (
            "x15ac:abspath",
            "sharepoint.com",
            "onedrive",
            "msip_label_",
            "docprops/custom.xml",
            "/custom-properties",
            "file:",
            "/users/",
            "/home/",
        ):
            assert forbidden not in folded
        assert not re.search(
            r"(?<![a-z0-9])[a-z]:[\\/]",
            package_text,
            flags=re.IGNORECASE,
        )
        assert not re.search(
            r"(?<![\\])\\\\[^\\/\s<>]+[\\/]",
            package_text,
            flags=re.IGNORECASE,
        )

        core = ET.fromstring(archive.read("docProps/core.xml"))
        assert core.findtext(f"{{{_DC_NS}}}creator") == "Kasper Lindskov Fabricius"
        assert (
            core.findtext(f"{{{_CORE_NS}}}lastModifiedBy")
            == "Kasper Lindskov Fabricius"
        )


def test_excel_decision_register_matches_every_canonical_row_and_formula():
    expected_rows = _expected_workbook_rows()

    with zipfile.ZipFile(WORKBOOK) as archive:
        names = set(archive.namelist())

        sheet_names, read_me = _xlsx_sheet_cells(archive, "Read Me")
        assert sheet_names == [
            "Read Me",
            "Decisions",
            "PR Programme",
            "Standards",
            "Publication QA",
        ]
        assert read_me["B5"][0] == "Sector 0.93"
        assert read_me["B6"][0] == BASELINE_REVISION
        assert read_me["B7"][0] == BASELINE_TREE
        assert read_me["B8"][0] == "v0.92-source.1"
        assert read_me["B10"][0] == "docs/v093_decision_register.md"
        assert read_me["B11"][0] == _canonical_markdown_sha256(DECISIONS)
        assert read_me["B12"][0] == "docs/product_identity.md"

        expected_summary = {
            "E5": ("27", "COUNTA(Decisions!A5:A31)"),
            "E6": ("26", 'COUNTIF(Decisions!G5:G31,"Implement")'),
            "E7": ("1", 'COUNTIF(Decisions!G5:G31,"Deferred")'),
            "E8": ("9", 'COUNTIF(\'PR Programme\'!D5:D14,"Planned")'),
            "E9": ("1", 'COUNTIF(\'PR Programme\'!D5:D14,"In progress")'),
        }
        assert {cell: read_me[cell] for cell in expected_summary} == expected_summary

        all_formulas = {}
        for sheet_name in sheet_names:
            _, cells = _xlsx_sheet_cells(archive, sheet_name)
            all_formulas.update(
                {
                    (sheet_name, address): formula
                    for address, (_, formula) in cells.items()
                    if formula is not None
                }
            )
        assert all_formulas == {
            ("Read Me", address): formula
            for address, (_, formula) in expected_summary.items()
        }

        for sheet_name, rows in expected_rows.items():
            _, cells = _xlsx_sheet_cells(archive, sheet_name)
            assert _sheet_table_rows(cells, len(rows), len(rows[0])) == rows

        expected_tables = {
            "RegisterMetadata": ("A4:B12", ["Record", "Value"]),
            "V093Decisions": (
                f"A4:G{3 + len(expected_rows['Decisions'])}",
                _DECISION_HEADERS,
            ),
            "V093Programme": (
                f"A4:D{3 + len(expected_rows['PR Programme'])}",
                _PROGRAMME_HEADERS,
            ),
            "V093Standards": (
                f"A4:D{3 + len(expected_rows['Standards'])}",
                _STANDARDS_HEADERS,
            ),
            "V093PublicationQA": (
                f"A4:D{3 + len(expected_rows['Publication QA'])}",
                _PUBLICATION_HEADERS,
            ),
        }
        actual_tables = {}
        for name in names:
            if not name.startswith("xl/tables/table") or not name.endswith(".xml"):
                continue
            table = ET.fromstring(archive.read(name))
            auto_filter = table.find(f"{{{_MAIN_NS}}}autoFilter")
            columns = table.find(f"{{{_MAIN_NS}}}tableColumns")
            assert auto_filter is not None
            assert columns is not None
            table_ref = table.attrib["ref"]
            assert auto_filter.attrib["ref"] == table_ref
            actual_tables[table.attrib["name"]] = (
                table_ref,
                [column.attrib["name"] for column in columns],
            )
        assert actual_tables == expected_tables

        _, sheet_paths = _xlsx_sheet_paths(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        workbook_view = workbook.find(
            f"{{{_MAIN_NS}}}bookViews/{{{_MAIN_NS}}}workbookView"
        )
        assert workbook_view is not None
        assert workbook_view.attrib.get("activeTab", "0") == "0"
        for sheet_name, sheet_path in sheet_paths.items():
            sheet = ET.fromstring(archive.read(sheet_path))
            pane = sheet.find(
                f"{{{_MAIN_NS}}}sheetViews/"
                f"{{{_MAIN_NS}}}sheetView/"
                f"{{{_MAIN_NS}}}pane"
            )
            assert pane is not None, sheet_name
            assert pane.attrib == {
                "ySplit": "4",
                "topLeftCell": "A5",
                "activePane": "bottomLeft",
                "state": "frozenSplit",
            }


def test_pr01_acceptance_hash_pins_the_generated_workbook_and_markdown():
    acceptance = _ascii(ACCEPTANCE)
    collapsed = " ".join(acceptance.split())
    workbook_match = re.search(
        r"- Workbook SHA-256:\s+`([0-9A-F]{64})`",
        acceptance,
    )
    markdown_match = re.search(
        r"- LF-normalized canonical Markdown SHA-256 stored in the workbook:"
        r"\s+`([0-9A-F]{64})`",
        acceptance,
    )

    assert workbook_match is not None
    assert markdown_match is not None
    assert workbook_match.group(1) == _file_sha256(WORKBOOK)
    assert markdown_match.group(1) == _canonical_markdown_sha256(DECISIONS)
    decision_bytes = DECISIONS.read_bytes()
    crlf_bytes = _lf_normalized_bytes(decision_bytes).replace(b"\n", b"\r\n")
    assert hashlib.sha256(_lf_normalized_bytes(crlf_bytes)).hexdigest().upper() == (
        markdown_match.group(1)
    )
    assert "All eight resulting pages were rendered at" in collapsed
    assert "no runtime, solver, Streamlit, project-schema" in collapsed
    assert "Sector therefore remains version 0.92" in collapsed


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
    identity = _ascii(ROOT / "docs" / "product_identity.md")

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
    assert "PASS/FAIL is reserved for an implemented demand-versus-resistance equation" in identity
    assert "`WITHIN USER-SPECIFIED LIMIT`" in combined
    assert "`EXCEEDS USER-SPECIFIED LIMIT`" in combined
    assert "does not reuse demand/resistance `PASS`/`FAIL` terminology" in combined
    assert "DK NA:2015 remains project context in v0.93" in combined
    assert "standards context, not a Sector implementation claim" in combined
    assert "confinement enhancement is not included or assessed" in combined
