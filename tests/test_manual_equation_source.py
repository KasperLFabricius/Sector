"""Independent contract and hostile tests for manual equation provenance."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import FrozenInstanceError, fields, replace
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import manual_equation_location as location  # noqa: E402
import manual_equation_source as source  # noqa: E402


EXPECTED_ROWS = (
    (
        "C3-1", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 3.1.7, Formula (3.17), "
        "and Table 3.1; DS/EN 1992-1-1:2023 8.1.2(1), Formula (8.4).",
    ),
    (
        "C3-2", "project",
        "Project-defined / uncited general Curve 3 mild-steel law; "
        "edition-named presets show their material references separately.",
    ),
    (
        "C3-3", "mixed",
        "Project-defined / uncited plane-section total-strain composition with "
        "the selected prestressing-law reference from DS/EN 1992-1-1:2004 + "
        "A1:2014 + AC:2010 3.3.6 or DS/EN 1992-1-1:2023 5.3.3 when the "
        "corresponding edition preset is selected.",
    ),
    (
        "C4-1", "project",
        "Project-defined / uncited first-material-limit capacity search; selected "
        "material limits keep their stated references.",
    ),
    (
        "C5-1", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 9.2.1.1(1), Formula "
        "(9.1N), with DS/EN 1992-1-1 DK NA:2024 where selected.",
    ),
    (
        "C5-2", "standard",
        "DS/EN 1992-1-1:2023 12.2(2)(a), Formula (12.1).",
    ),
    (
        "C5-3", "standard",
        "DS/EN 1992-1-1:2023 12.2(2)(b), Formula (12.2).",
    ),
    (
        "C5-4", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 8.2(2); "
        "DS/EN 1992-1-1:2023 11.2(2).",
    ),
    (
        "C5-5", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 9.2.2(5), Formulas "
        "(9.4) and (9.5N); DS/EN 1992-1-1 DK NA:2024 9.2.2(5), Formula "
        "(9.5N NA), where selected; DS/EN 1992-1-1:2023 12.2(4), Formula "
        "(12.4).",
    ),
    (
        "C5-6", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 9.2.2(6),(8), Formulas "
        "(9.6N) and (9.8N), plus 9.3.2(2),(4)-(5) for the slab provisions; "
        "DS/EN 1992-1-1:2023 Table 12.1 items 5 and 7, plus Table 12.2 items "
        "8 and 10 and 12.4.2 for the slab provisions.",
    ),
    (
        "C5-7", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 9.2.3(2), referring to "
        "9.2.2(5), Formulas (9.4) and (9.5N); DS/EN 1992-1-1 DK NA:2024 "
        "9.2.2(5), Formula (9.5N NA), where selected; DS/EN 1992-1-1:2023 "
        "12.2(4), Formula (12.4), and Table 12.1 item 2.",
    ),
    (
        "C7-1", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 7.3.4, Formulas (7.8) "
        "and (7.9).",
    ),
    (
        "C7-2", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 7.3.4, Formulas "
        "(7.11) and (7.14).",
    ),
    (
        "C7-5", "standard",
        "DS/EN 1992-1-1 DK NA:2024 7.3.2(1)P, Formula (7.100 NA).",
    ),
    (
        "C7-3", "standard",
        "DS/EN 1992-1-1:2023 9.2.3, Formulas (9.8) and (9.9).",
    ),
    (
        "C7-4", "standard",
        "DS/EN 1992-1-1:2023 9.2.3, Formulas (9.15)-(9.18).",
    ),
    (
        "C8-1", "mixed",
        "Project-defined / uncited Elastic stress calculation with "
        "a selected fatigue action factor; DS/EN 1992-1-1:2004 + A1:2014 + "
        "AC:2010 2.4.2.3 and 6.8.4(1), or DS/EN 1992-1-1:2023 10.2 and "
        "Annex E, defines how that factor applies for the selected edition.",
    ),
    (
        "C8-2", "mixed",
        "Project-defined / uncited characteristic range for Custom / imported "
        "fatigue details; DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.8.4 "
        "and Tables 6.3N-6.4N, or DS/EN 1992-1-1:2023 Annex E.5 and Tables "
        "E.1-E.2, for the corresponding edition preset.",
    ),
    (
        "C8-3", "mixed",
        "Project-defined / uncited S-N relationship for Custom / imported "
        "fatigue details; DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.8.4 "
        "and Tables 6.3N-6.4N, or DS/EN 1992-1-1:2023 Annex E.5 and Tables "
        "E.1-E.2, for the corresponding edition preset.",
    ),
    (
        "C8-4", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.8.4, Palmgren-Miner "
        "summation; DS/EN 1992-1-1:2023 Annex E.5, Palmgren-Miner summation.",
    ),
    (
        "C8-5", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 3.1.6 and 6.8.7, "
        "Formula (6.76).",
    ),
    (
        "C8-6", "standard",
        "DS/EN 1992-1-1:2023 5.1.6(1), Formula (5.3), and 10.5, "
        "Formula (10.5).",
    ),
    (
        "C8-7", "mixed",
        "Project-defined / uncited concrete Miner S-N relation when the "
        "user-defined method is selected; DS/EN 1992-2:2005 + AC:2008 "
        "corrected 6.106, or DS/EN 1992-1-1:2023 E.5.3, Formulas "
        "(E.7)-(E.8), for the corresponding standard Miner method.",
    ),
    (
        "C8-8", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.8.7, Formula "
        "(6.72); DS/EN 1992-1-1:2023 E.4.3, Formula (E.2).",
    ),
    (
        "C9-1", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.2.2(1), Formula "
        "(6.2a), with DS/EN 1992-1-1 DK NA:2024 where selected.",
    ),
    (
        "C9-2", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.2.2(1), Formula "
        "(6.2b), with DS/EN 1992-1-1 DK NA:2024 where selected.",
    ),
    (
        "C9-3", "standard",
        "DS/EN 1992-1-1:2023 8.2.2(3)-(4), Formulas (8.30) and (8.31).",
    ),
    (
        "C9-4", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.2.3(3), Formulas "
        "(6.8) and (6.9), with DS/EN 1992-1-1 DK NA:2024 6.2.3(2)-(3) "
        "where selected.",
    ),
    (
        "C9-5", "standard",
        "DS/EN 1992-1-1:2023 8.2.3(5), Formulas (8.42) and (8.44).",
    ),
    (
        "C10-1", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.3.2(1), Formula "
        "(6.27), 6.2.3(3), Formula (6.8), and 6.3.2(4), Formula (6.30), "
        "with DS/EN 1992-1-1 DK NA:2024 where selected.",
    ),
    (
        "C10-2", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.3.2(4), Formula "
        "(6.29).",
    ),
    (
        "C11-1", "standard",
        "DS/EN 1992-1-1:2004 + A1:2014 + AC:2010 6.3.2(4), Formula "
        "(6.29).",
    ),
    (
        "C11-2", "standard",
        "DS/EN 1992-1-1 DK NA:2024 6.3.2(6).",
    ),
)

EXPECTED_SOURCE_SEAL = (
    "aeab11addf8fc0d983b5275b5fba943f5963805c58ade050cde5bd0586ceca1d"
)


def _located():
    return location.register_manual_equation_locations(manual.manual_blocks())


def _bound(equations=None, catalogue=source.MANUAL_EQUATION_SOURCES):
    return source.bind_manual_equation_sources(
        _located() if equations is None else equations,
        catalogue,
    )


def test_live_manual_binds_exact_independent_source_matrix():
    bound = _bound()
    assert len(bound) == 33
    assert tuple(
        (
            item.source.number,
            item.source.source_kind,
            item.source.source_text,
        )
        for item in bound
    ) == EXPECTED_ROWS
    assert tuple(item.source.ordinal for item in bound) == tuple(range(1, 34))
    assert tuple(item.source.key for item in bound) == tuple(
        item.key for item in location.MANUAL_EQUATION_LOCATIONS
    )


def test_complete_source_catalogue_has_exact_seal():
    assert source.source_catalogue_sha256() == EXPECTED_SOURCE_SEAL


def test_source_classification_is_exact_and_project_sources_are_uncited():
    records = source.MANUAL_EQUATION_SOURCES
    assert Counter(item.source_kind for item in records) == {
        "standard": 26,
        "mixed": 5,
        "project": 2,
    }
    project = tuple(item for item in records if item.source_kind == "project")
    mixed = tuple(item for item in records if item.source_kind == "mixed")
    assert tuple(item.number for item in project) == ("C3-2", "C4-1")
    assert tuple(item.number for item in mixed) == (
        "C3-3", "C8-1", "C8-2", "C8-3", "C8-7",
    )
    for item in project:
        assert item.source_text.startswith("Project-defined / uncited")
        assert not any(document in item.source_text for document in source.DOCUMENTS)
    for item in mixed:
        assert item.source_text.startswith("Project-defined / uncited")
        assert any(document in item.source_text for document in source.DOCUMENTS)
    for item in records:
        if item.source_kind == "standard":
            assert any(document in item.source_text for document in source.DOCUMENTS)
            assert "Project-defined / uncited" not in item.source_text


def test_selectable_custom_fatigue_laws_retain_project_provenance():
    records = {item.number: item for item in source.MANUAL_EQUATION_SOURCES}
    expected = {
        "C8-2": "Custom / imported",
        "C8-3": "Custom / imported",
        "C8-7": "user-defined method",
    }
    for number, branch_label in expected.items():
        record = records[number]
        assert record.source_kind == source.SOURCE_MIXED
        assert record.source_text.startswith("Project-defined / uncited")
        assert branch_label in record.source_text
        assert any(
            document in record.source_text for document in source.DOCUMENTS
        )


@pytest.mark.parametrize("index", range(33))
@pytest.mark.parametrize(
    "field",
    ("ordinal", "key", "number", "source_kind", "source_text"),
)
def test_every_source_field_rejects_valid_looking_coherent_mutation(index, field):
    candidate = list(source.MANUAL_EQUATION_SOURCES)
    original = candidate[index]
    values = {
        "ordinal": original.ordinal + 100,
        "key": original.key + "-altered",
        "number": "C99-99",
        "source_kind": (
            "mixed" if original.source_kind != "mixed" else "standard"
        ),
        "source_text": original.source_text + " Altered source.",
    }
    candidate[index] = replace(original, **{field: values[field]})
    with pytest.raises(ValueError, match="source catalogue changed"):
        _bound(catalogue=tuple(candidate))


def test_missing_duplicate_reordered_unknown_and_shape_shifted_catalogues_fail():
    canonical = source.MANUAL_EQUATION_SOURCES
    variants = (
        canonical[:-1],
        (*canonical[:-1], canonical[-2]),
        (canonical[1], canonical[0], *canonical[2:]),
        (*canonical, canonical[-1]),
        list(canonical),
    )
    for candidate in variants:
        with pytest.raises(ValueError, match="source catalogue changed"):
            _bound(catalogue=candidate)


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "reordered"))
def test_located_equation_cardinality_and_order_are_revalidated(mutation):
    equations = _located()
    if mutation == "missing":
        candidate = equations[:-1]
    elif mutation == "duplicate":
        candidate = (*equations[:-1], equations[-2])
    else:
        candidate = (equations[1], equations[0], *equations[2:])
    with pytest.raises(ValueError, match="cardinality|identity"):
        _bound(candidate)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("expression", "expression"),
        ("non-ascii", "expression"),
        ("location", "identity"),
        ("type", "type"),
        ("container", "tuple"),
    ),
)
def test_candidate_selected_location_expression_and_shape_cannot_gain_source(
    mutation, message
):
    equations = list(_located())
    if mutation == "expression":
        equations[0] = replace(equations[0], expression=equations[0].expression + "x")
        candidate = tuple(equations)
    elif mutation == "non-ascii":
        equations[0] = replace(
            equations[0], expression=equations[0].expression + chr(945)
        )
        candidate = tuple(equations)
    elif mutation == "location":
        equations[0] = replace(
            equations[0],
            location=replace(equations[0].location, section="Altered section"),
        )
        candidate = tuple(equations)
    elif mutation == "type":
        equations[0] = object()
        candidate = tuple(equations)
    else:
        candidate = equations
    with pytest.raises(ValueError, match=message):
        _bound(candidate)


def test_source_records_and_bindings_are_exact_immutable_ascii_types():
    source_fields = {field.name for field in fields(source.ManualEquationSource)}
    assert source_fields == {
        "ordinal", "key", "number", "source_kind", "source_text",
    }
    binding_fields = {field.name for field in fields(source.SourcedManualEquation)}
    assert binding_fields == {"equation", "source"}
    item = _bound()[0]
    with pytest.raises(FrozenInstanceError):
        item.source.source_text = "candidate"
    with pytest.raises(FrozenInstanceError):
        item.equation = object()
    assert all(
        type(record.ordinal) is int
        and all(
            type(value) is str and value.isascii()
            for value in (
                record.key,
                record.number,
                record.source_kind,
                record.source_text,
            )
        )
        for record in source.MANUAL_EQUATION_SOURCES
    )


def test_source_module_has_only_location_and_standard_library_imports():
    path = ROOT / "app" / "manual_equation_source.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in tree.body if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module
        for node in tree.body if isinstance(node, ast.ImportFrom)
        and node.module is not None
    )
    assert imported == {
        "__future__", "dataclasses", "hashlib", "manual_equation_location",
    }
    assert not imported.intersection(
        {
            "manual", "streamlit", "reportlab", "sector_report", "sector",
            "report_equation_contract",
        }
    )
    assert all(
        "trace" not in imported_name and "solver" not in imported_name
        for imported_name in imported
    )
