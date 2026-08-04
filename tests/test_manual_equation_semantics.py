"""Independent contract and hostile tests for Part C equation semantics."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
import hashlib
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import manual_equation_location as location  # noqa: E402
import manual_equation_semantics as semantics  # noqa: E402
import manual_equation_source as source  # noqa: E402


EXPECTED_SEMANTIC_SEAL = (
    "4c240e40d2a9feb5b241ef5e55d1d803ad65f5a99f008f2051491a46a33c96b5"
)
EXPECTED_MARK_UNIT_SEAL = (
    "6064b3152bf511a145599de3b7fc01e0221a177b96df0a1e79c5952a739edfae"
)
EXPECTED_MEANING_SEAL = (
    "9c123107aa74d66deeea58323c4b0bde60ec847a4b1b1498d9fdcd2692a38ac9"
)
EXPECTED_DIMENSION_SEAL = (
    "9c01b16493937a96e591c4fbe980ae67e2064d72ba2dd6200d3f46fad72d2801"
)

EXPECTED_UNITS = {
    "dimensionless",
    "actions",
    "cycles",
    "days",
    "degrees",
    "MPa",
    "MPa^(1/2)",
    "MPa^(2/3)",
    "mm",
    "mm2",
    "m",
    "m2",
    "1/m",
    "kN",
    "kNm",
}

EXPECTED_SYMBOL_COUNTS = (
    ("C3-1", 6),
    ("C3-2", 7),
    ("C3-3", 11),
    ("C4-1", 9),
    ("C5-1", 6),
    ("C5-2", 3),
    ("C5-3", 4),
    ("C5-4", 3),
    ("C5-5", 8),
    ("C5-6", 3),
    ("C5-7", 5),
    ("C7-1", 10),
    ("C7-2", 10),
    ("C7-3", 9),
    ("C7-4", 9),
    ("C8-1", 5),
    ("C8-2", 3),
    ("C8-3", 5),
    ("C8-4", 3),
    ("C8-5", 7),
    ("C8-6", 7),
    ("C8-7", 4),
    ("C8-8", 2),
    ("C9-1", 9),
    ("C9-2", 6),
    ("C9-3", 6),
    ("C9-4", 11),
    ("C9-5", 8),
    ("C10-1", 11),
    ("C10-2", 4),
    ("C11-1", 4),
    ("C11-2", 2),
)

EXPECTED_PUBLIC_DEPENDENCIES = (
    ("C5-7", "C5-5"),
    ("C7-1", "C7-2"),
    ("C7-3", "C7-4"),
    ("C8-3", "C8-2"),
    ("C8-3", "C8-1"),
    ("C8-4", "C8-3"),
    ("C9-5", "C5-5"),
    ("C10-2", "C10-1"),
    ("C10-2", "C9-4"),
    ("C11-1", "C10-2"),
)


class _EqualitySpoof:
    """Foreign provenance value that impersonates every equality comparison."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False


def _located():
    return location.register_manual_equation_locations(manual.manual_blocks())


def _sourced():
    return source.bind_manual_equation_sources(_located())


def _bound(equations=None, catalogue=semantics.MANUAL_EQUATION_SEMANTICS):
    return semantics.bind_manual_equation_semantics(
        _sourced() if equations is None else equations,
        catalogue,
    )


def _inventory_seals(records):
    mark_units = hashlib.sha256(
        "\x1e".join(
            "\x1f".join(
                (record.number,)
                + tuple(
                    "\x1d".join((symbol.markup, symbol.unit))
                    for symbol in record.symbols
                )
            )
            for record in records
        ).encode("ascii")
    ).hexdigest()
    meanings = hashlib.sha256(
        "\x1e".join(
            "\x1f".join(
                (record.number,)
                + tuple(symbol.meaning for symbol in record.symbols)
            )
            for record in records
        ).encode("ascii")
    ).hexdigest()
    dimensions = hashlib.sha256(
        "\x1e".join(
            "\x1f".join((record.number, record.dimensional_note))
            for record in records
        ).encode("ascii")
    ).hexdigest()
    return mark_units, meanings, dimensions


def test_live_manual_binds_complete_semantics_in_exact_location_order():
    bound = _bound()
    assert len(bound) == 32
    assert tuple(item.semantics.ordinal for item in bound) == tuple(range(1, 33))
    assert tuple(item.semantics.key for item in bound) == tuple(
        item.key for item in location.MANUAL_EQUATION_LOCATIONS
    )
    assert tuple(item.semantics.number for item in bound) == tuple(
        item.number for item in location.MANUAL_EQUATION_LOCATIONS
    )
    assert tuple(
        (item.semantics.number, len(item.semantics.symbols))
        for item in bound
    ) == EXPECTED_SYMBOL_COUNTS
    assert sum(len(item.semantics.symbols) for item in bound) == 200


def test_complete_catalogue_and_independent_inventories_have_exact_seals():
    records = semantics.MANUAL_EQUATION_SEMANTICS
    assert semantics.semantic_catalogue_sha256() == EXPECTED_SEMANTIC_SEAL
    assert _inventory_seals(records) == (
        EXPECTED_MARK_UNIT_SEAL,
        EXPECTED_MEANING_SEAL,
        EXPECTED_DIMENSION_SEAL,
    )


def test_unit_vocabulary_is_exact_and_every_unit_is_used():
    assert semantics.UNITS == EXPECTED_UNITS
    used = {
        symbol.unit
        for record in semantics.MANUAL_EQUATION_SEMANTICS
        for symbol in record.symbols
    }
    assert used == EXPECTED_UNITS


def test_direct_dependency_graph_is_exact_ordered_and_acyclic():
    records = semantics.MANUAL_EQUATION_SEMANTICS
    number_by_key = {record.key: record.number for record in records}
    public_edges = tuple(
        (record.number, number_by_key[dependency])
        for record in records
        for dependency in record.direct_uses
    )
    assert public_edges == EXPECTED_PUBLIC_DEPENDENCIES
    assert len(public_edges) == 10

    uses = {record.key: record.direct_uses for record in records}
    for origin in uses:
        pending = [origin]
        visited = set()
        while pending:
            current = pending.pop()
            assert current not in visited
            visited.add(current)
            pending.extend(
                dependency
                for dependency in uses[current]
                if dependency not in visited
            )

    assert next(record for record in records if record.number == "C11-2").direct_uses == ()
    assert tuple(
        number_by_key[key]
        for key in next(
            record for record in records if record.number == "C8-3"
        ).direct_uses
    ) == ("C8-2", "C8-1")


def test_high_risk_units_and_conversion_notes_are_exact():
    by_number = {
        record.number: {
            symbol.markup: symbol.unit for symbol in record.symbols
        }
        for record in semantics.MANUAL_EQUATION_SEMANTICS
    }
    notes = {
        record.number: record.dimensional_note
        for record in semantics.MANUAL_EQUATION_SEMANTICS
    }

    assert by_number["C5-5"][r"c"] == "MPa^(1/2)"
    assert by_number["C9-1"][r"C_{Rd,c}"] == "MPa^(2/3)"
    assert by_number["C9-3"][r"a_{cs}"] == "m"
    assert by_number["C9-3"][r"d"] == "m"
    assert by_number["C9-3"][r"M_{Ed}"] == "kNm"
    assert by_number["C9-3"][r"V_{Ed}"] == "kN"
    assert by_number["C10-1"][r"A_k"] == "m2"
    assert by_number["C10-1"][r"t_{ef}"] == "m"
    assert by_number["C10-1"][r"A_{sw}"] == "mm2"
    assert by_number["C10-1"][r"s"] == "mm"
    assert "literal 250 has unit MPa" in notes["C8-5"]
    assert "literal 40 has unit MPa" in notes["C8-6"]
    assert "converts A_sw/s from mm2/mm" in notes["C10-1"]
    assert "N_R/(1 cycle)" in notes["C8-7"]


@pytest.mark.parametrize("index", range(32))
@pytest.mark.parametrize(
    "field",
    ("ordinal", "key", "number", "symbols", "dimensional_note", "direct_uses"),
)
def test_every_semantic_field_rejects_valid_looking_coherent_mutation(
    index, field
):
    canonical = semantics.MANUAL_EQUATION_SEMANTICS
    candidate = list(canonical)
    original = candidate[index]
    dependency = (
        "manual.material.steel-law"
        if original.key == "manual.material.concrete-law"
        else "manual.material.concrete-law"
    )
    values = {
        "ordinal": original.ordinal + 100,
        "key": original.key + "-altered",
        "number": "C99-99",
        "symbols": (
            replace(
                original.symbols[0],
                meaning=original.symbols[0].meaning + " altered",
            ),
            *original.symbols[1:],
        ),
        "dimensional_note": original.dimensional_note + " Altered.",
        "direct_uses": (dependency,),
    }
    candidate[index] = replace(original, **{field: values[field]})
    with pytest.raises(ValueError, match="semantic catalogue changed"):
        _bound(catalogue=tuple(candidate))


SYMBOL_CASES = tuple(
    (record_index, symbol_index, field)
    for record_index, record in enumerate(semantics.MANUAL_EQUATION_SEMANTICS)
    for symbol_index in range(len(record.symbols))
    for field in ("markup", "meaning", "unit")
)


@pytest.mark.parametrize(("record_index", "symbol_index", "field"), SYMBOL_CASES)
def test_every_nested_symbol_field_rejects_coherent_mutation(
    record_index, symbol_index, field
):
    canonical = semantics.MANUAL_EQUATION_SEMANTICS
    candidate = list(canonical)
    record = candidate[record_index]
    symbols = list(record.symbols)
    symbol = symbols[symbol_index]
    values = {
        "markup": symbol.markup + "_x",
        "meaning": symbol.meaning + " altered",
        "unit": (
            semantics.MPA
            if symbol.unit != semantics.MPA
            else semantics.DIMENSIONLESS
        ),
    }
    symbols[symbol_index] = replace(symbol, **{field: values[field]})
    candidate[record_index] = replace(record, symbols=tuple(symbols))
    with pytest.raises(ValueError, match="semantic catalogue changed"):
        _bound(catalogue=tuple(candidate))


def test_symbol_mutation_matrix_has_exact_complete_cardinality():
    assert len(SYMBOL_CASES) == 200 * 3
    assert len(set(SYMBOL_CASES)) == len(SYMBOL_CASES)


def test_missing_duplicate_reordered_unknown_and_shape_shifted_catalogues_fail():
    canonical = semantics.MANUAL_EQUATION_SEMANTICS
    variants = (
        canonical[:-1],
        (*canonical[:-1], canonical[-2]),
        (canonical[1], canonical[0], *canonical[2:]),
        (*canonical, canonical[-1]),
        list(canonical),
    )
    for candidate in variants:
        with pytest.raises(ValueError, match="semantic catalogue changed"):
            _bound(catalogue=candidate)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing", "cardinality"),
        ("duplicate", "identity"),
        ("reordered", "identity"),
        ("expression", "expression"),
        ("location", "identity"),
        ("source", "identity"),
        ("type", "type"),
        ("container", "tuple"),
    ),
)
def test_untrusted_sourced_equations_are_revalidated_before_semantics(
    mutation, message
):
    equations = list(_sourced())
    if mutation == "missing":
        candidate = tuple(equations[:-1])
    elif mutation == "duplicate":
        candidate = tuple((*equations[:-1], equations[-2]))
    elif mutation == "reordered":
        candidate = tuple((equations[1], equations[0], *equations[2:]))
    elif mutation == "expression":
        located = replace(
            equations[0].equation,
            expression=equations[0].equation.expression + "x",
        )
        equations[0] = replace(equations[0], equation=located)
        candidate = tuple(equations)
    elif mutation == "location":
        located = replace(
            equations[0].equation,
            location=replace(
                equations[0].equation.location,
                section="Altered section",
            ),
        )
        equations[0] = replace(equations[0], equation=located)
        candidate = tuple(equations)
    elif mutation == "source":
        equations[0] = replace(
            equations[0],
            source=replace(
                equations[0].source,
                source_text=equations[0].source.source_text + " Altered.",
            ),
        )
        candidate = tuple(equations)
    elif mutation == "type":
        equations[0] = object()
        candidate = tuple(equations)
    else:
        candidate = equations
    with pytest.raises(ValueError, match=message):
        _bound(candidate)


@pytest.mark.parametrize(
    ("layer", "field"),
    (
        ("location", "ordinal"),
        ("location", "key"),
        ("location", "number"),
        ("location", "part"),
        ("location", "section"),
        ("location", "subsection"),
        ("location", "expression_sha256"),
        ("source", "ordinal"),
        ("source", "key"),
        ("source", "number"),
        ("source", "source_kind"),
        ("source", "source_text"),
    ),
)
def test_nested_provenance_rejects_equality_spoof_fields(layer, field):
    equations = list(_sourced())
    if layer == "location":
        located = equations[0].equation
        spoofed = replace(located.location, **{field: _EqualitySpoof()})
        equations[0] = replace(
            equations[0], equation=replace(located, location=spoofed)
        )
    else:
        equations[0] = replace(
            equations[0],
            source=replace(equations[0].source, **{field: _EqualitySpoof()}),
        )
    with pytest.raises(ValueError, match="identity field type changed"):
        _bound(tuple(equations))


@pytest.mark.parametrize("layer", ("location", "source"))
def test_nested_provenance_rejects_equality_spoof_objects(layer):
    equations = list(_sourced())
    if layer == "location":
        located = equations[0].equation
        equations[0] = replace(
            equations[0],
            equation=replace(located, location=_EqualitySpoof()),
        )
    else:
        equations[0] = replace(equations[0], source=_EqualitySpoof())
    with pytest.raises(ValueError, match="identity type changed"):
        _bound(tuple(equations))


def test_records_bindings_and_nested_symbols_are_exact_immutable_ascii_types():
    semantic_fields = {
        field.name for field in fields(semantics.ManualEquationSemantics)
    }
    symbol_fields = {
        field.name for field in fields(semantics.ManualEquationSymbol)
    }
    binding_fields = {
        field.name for field in fields(semantics.SemanticManualEquation)
    }
    assert semantic_fields == {
        "ordinal",
        "key",
        "number",
        "symbols",
        "dimensional_note",
        "direct_uses",
    }
    assert symbol_fields == {"markup", "meaning", "unit"}
    assert binding_fields == {"equation", "semantics"}

    item = _bound()[0]
    with pytest.raises(FrozenInstanceError):
        item.semantics.dimensional_note = "changed"
    with pytest.raises(FrozenInstanceError):
        item.semantics.symbols[0].unit = "changed"
    with pytest.raises(FrozenInstanceError):
        item.equation = object()

    for record in semantics.MANUAL_EQUATION_SEMANTICS:
        assert type(record.ordinal) is int
        assert all(
            type(value) is str and value.isascii()
            for value in (
                record.key,
                record.number,
                record.dimensional_note,
                *record.direct_uses,
            )
        )
        assert type(record.symbols) is tuple
        for symbol in record.symbols:
            assert type(symbol) is semantics.ManualEquationSymbol
            assert all(
                type(value) is str and value.isascii()
                for value in (symbol.markup, symbol.meaning, symbol.unit)
            )


def test_semantics_module_import_boundary_is_exact():
    path = ROOT / "app" / "manual_equation_semantics.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert imported == {
        "__future__",
        "dataclasses",
        "hashlib",
        "manual_equation_source",
    }
    assert not imported.intersection(
        {
            "manual",
            "streamlit",
            "reportlab",
            "sector_report",
            "report_equation_contract",
            "sector",
        }
    )
    assert all(
        "trace" not in name and "solver" not in name for name in imported
    )


def test_semantic_slice_advertises_no_renderer_or_result_fields():
    record = semantics.MANUAL_EQUATION_SEMANTICS[0]
    for excluded in (
        "renderer",
        "style",
        "caption",
        "cross_reference",
        "substitution",
        "result",
        "verdict",
        "trace",
    ):
        assert not hasattr(record, excluded)
