"""Independent contract and hostile tests for manual equation semantics."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import manual_equation_contract as contract  # noqa: E402
import manual_equation_location as location  # noqa: E402
import manual_equation_source as source  # noqa: E402


EXPECTED_CONTRACT_SEAL = (
    "bf761eb9014419e5c42e6f04e0a0c05628bb21549d5f8abe0c76d9f4e433613b"
)

EXPECTED_ROWS = (
    ("C3-1", 6, (r"\sigma_c",), ("MPa",), "stress law", ()),
    (
        "C3-2", 7, (r"\sigma_s", r"f_{yd}", r"\varepsilon_{yd}"),
        ("MPa", "MPa", "1"), "stress and strain law", (),
    ),
    (
        "C3-3", 11, (r"\varepsilon_{p,j}", r"\sigma_p", r"f_{pd}"),
        ("1", "MPa", "MPa"), "strain and stress law", (),
    ),
    (
        "C4-1", 11, (r"\kappa",), ("1/mm",), "curvature selection",
        (
            "manual.material.concrete-law",
            "manual.material.steel-law",
            "manual.material.prestress-law",
        ),
    ),
    ("C5-1", 6, (r"A_{s,min}",), ("mm^2",), "area check", ()),
    ("C5-2", 3, (r"M_{R,nom}",), ("N mm",), "moment check", ()),
    (
        "C5-3", 5, (r"\sum_i A_{s,i}f_{yk,i}",), ("N",),
        "force check", (),
    ),
    ("C5-4", 3, (r"c_{clear}",), ("mm",), "length check", ()),
    (
        "C5-5", 8, (r"\rho_w", r"\rho_{w,min}"), ("1", "1"),
        "dimensionless ratio check", (),
    ),
    (
        "C5-6", 3, (r"s_l", r"s_t"), ("mm", "mm"),
        "length checks", (),
    ),
    (
        "C5-7", 5, (r"\rho_{w,T}",), ("1",),
        "dimensionless ratio check",
        ("manual.detailing.links.minimum-ratio",),
    ),
    (
        "C7-1", 10, (r"w_k", r"\varepsilon_{sm}-\varepsilon_{cm}"),
        ("mm", "1"), "crack-width relation", ("manual.crack.2005.spacing",),
    ),
    (
        "C7-2", 10, (r"s_{r,max}",), ("mm",), "length relation", (),
    ),
    (
        "C7-3", 10, (r"w_k", r"\frac{k_1}{r}"), ("mm", "1"),
        "crack-width relation", ("manual.crack.2023.spacing",),
    ),
    (
        "C7-4", 9, (r"s_{r,m,cal}",), ("mm",), "length relation", (),
    ),
    (
        "C8-1", 6, (r"\Delta\sigma_{Ed,i}",), ("MPa",),
        "stress-range relation", (),
    ),
    (
        "C8-2", 3, (r"\Delta\sigma_{Rd}",), ("MPa",),
        "stress relation", (),
    ),
    (
        "C8-3", 6, (r"N_{R,i}",), ("cycles",), "cycle-life relation",
        (
            "manual.fatigue.stress-range",
            "manual.fatigue.reinforcement.design-range",
        ),
    ),
    (
        "C8-4", 4, (r"D",), ("1",), "dimensionless damage check",
        ("manual.fatigue.reinforcement.life",),
    ),
    (
        "C8-5", 7, (r"f_{cd,fat}",), ("MPa",), "stress relation", (),
    ),
    (
        "C8-6", 7, (r"\eta_{cc}", r"\eta_{cc,fat}", r"f_{cd,fat}"),
        ("1", "1", "MPa"), "dimensionless factors and stress relation", (),
    ),
    (
        "C8-7", 4, (r"N_R",), ("cycles",), "cycle-life relation",
        (
            "manual.fatigue.concrete.strength-2005",
            "manual.fatigue.concrete.strength-2023",
        ),
    ),
    (
        "C8-8", 2,
        (r"E_{max}+0.43\sqrt{1-E_{min}/E_{max}}",), ("1",),
        "dimensionless fatigue check",
        (
            "manual.fatigue.concrete.strength-2005",
            "manual.fatigue.concrete.strength-2023",
        ),
    ),
    (
        "C9-1", 9, (r"V_{Rd,c}",), ("N",), "force relation", (),
    ),
    (
        "C9-2", 6, (r"V_{Rd,c}",), ("N",), "force relation", (),
    ),
    (
        "C9-3", 6, (r"a_{cs}", r"k_{vp}"), ("mm", "1"),
        "length and dimensionless factor", (),
    ),
    (
        "C9-4", 11, (r"V_{Rd,s}", r"V_{Rd,max}"), ("N", "N"),
        "force relations", (),
    ),
    (
        "C9-5", 8, (r"\tau_{Rd,sy}", r"\sigma_{cd}"), ("MPa", "MPa"),
        "stress relations", ("manual.detailing.links.minimum-ratio",),
    ),
    (
        "C10-1", 11, (r"T_{Rd,s}", r"T_{Rd,max}"), ("N mm", "N mm"),
        "moment relations", (),
    ),
    (
        "C10-2", 4,
        (r"T_{Ed}/T_{Rd,max}+V_{Ed}/V_{Rd,max}",), ("1",),
        "dimensionless interaction check",
        ("manual.shear.links-2005", "manual.torsion.resistance"),
    ),
    (
        "C11-1", 4,
        (r"T_{Ed}/T_{Rd,max}+V_{Ed}/V_{Rd,max}",), ("1",),
        "dimensionless interaction check",
        ("manual.shear.links-2005", "manual.torsion.resistance"),
    ),
    (
        "C11-2", 2, (r"\sum(S_{Ed}/S_{Rd})",), ("1",),
        "dimensionless interaction check",
        (
            "manual.shear.links-2005",
            "manual.shear.links-2023",
            "manual.torsion.resistance",
        ),
    ),
)


def _sourced():
    located = location.register_manual_equation_locations(manual.manual_blocks())
    return source.bind_manual_equation_sources(located)


def _bound(equations=None, catalogue=contract.MANUAL_EQUATION_CONTRACTS):
    return contract.bind_manual_equation_contracts(
        _sourced() if equations is None else equations,
        catalogue,
    )


def _row(item):
    return (
        item.number,
        len(item.symbols),
        tuple(result.markup for result in item.results),
        tuple(result.unit for result in item.results),
        item.dimensional_class,
        item.uses,
    )


def test_live_manual_binds_exact_independent_semantic_inventory():
    bound = _bound()
    assert len(bound) == 32
    assert tuple(_row(item.contract) for item in bound) == EXPECTED_ROWS
    assert tuple(item.contract.ordinal for item in bound) == tuple(range(1, 33))
    assert tuple(item.contract.key for item in bound) == tuple(
        item.key for item in location.MANUAL_EQUATION_LOCATIONS
    )
    assert sum(len(item.contract.symbols) for item in bound) == 207
    assert sum(len(item.contract.results) for item in bound) == 46
    assert sum(len(item.contract.uses) for item in bound) == 21


def test_complete_contract_catalogue_has_exact_seal():
    assert contract.contract_catalogue_sha256() == EXPECTED_CONTRACT_SEAL


def test_concrete_units_are_dimensionally_consistent_for_every_term():
    allowed = {
        "1", "1/mm", "MPa", "N", "N mm", "case action", "cycles",
        "days", "matching action", "mm", "mm^2", "rad",
    }
    for item in contract.MANUAL_EQUATION_CONTRACTS:
        assert item.dimensional_class
        for term in (*item.symbols, *item.results):
            assert term.unit in allowed
            assert term.markup
            assert term.meaning


def test_tendon_and_action_sign_identities_are_explicit():
    by_number = {
        item.number: item for item in contract.MANUAL_EQUATION_CONTRACTS
    }
    tendon = {term.markup: term for term in by_number["C3-3"].symbols}
    assert tendon[r"s_{p,j}"].meaning == (
        "tendon-j coordinate normal to the neutral axis"
    )
    assert tendon[r"\varepsilon_{p,IS,j}"].meaning == (
        "locked-in strain of tendon j"
    )
    shear = {term.markup: term for term in by_number["C9-3"].symbols}
    assert shear[r"N_{Ed}"].meaning.endswith("tension positive")
    assert shear[r"M_{Ed}"].unit == "N mm"
    assert shear[r"V_{Ed}"].unit == "N"


def test_forward_reuse_and_duplicate_expression_identities_are_not_collapsed():
    by_number = {
        item.number: item for item in contract.MANUAL_EQUATION_CONTRACTS
    }
    assert by_number["C7-1"].uses == ("manual.crack.2005.spacing",)
    assert by_number["C7-3"].uses == ("manual.crack.2023.spacing",)
    assert by_number["C10-2"] != by_number["C11-1"]
    assert by_number["C10-2"].results == by_number["C11-1"].results
    assert by_number["C10-2"].uses == by_number["C11-1"].uses
    assert by_number["C10-2"].key != by_number["C11-1"].key


def test_edition_alternative_dependencies_are_complete_and_ordered():
    by_number = {
        item.number: item for item in contract.MANUAL_EQUATION_CONTRACTS
    }
    expected = (
        "manual.fatigue.concrete.strength-2005",
        "manual.fatigue.concrete.strength-2023",
    )
    assert by_number["C8-7"].uses == expected
    assert by_number["C8-8"].uses == expected


@pytest.mark.parametrize("index", range(32))
@pytest.mark.parametrize(
    "field",
    (
        "ordinal",
        "key",
        "number",
        "symbols",
        "results",
        "dimensional_class",
        "uses",
    ),
)
def test_every_contract_field_rejects_valid_looking_coherent_mutation(
    index, field
):
    candidate = list(contract.MANUAL_EQUATION_CONTRACTS)
    original = candidate[index]
    alternate_dependency = next(
        item.key
        for item in contract.MANUAL_EQUATION_CONTRACTS
        if item.key != original.key and item.key not in original.uses
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
        "results": (
            replace(
                original.results[0],
                meaning=original.results[0].meaning + " altered",
            ),
            *original.results[1:],
        ),
        "dimensional_class": original.dimensional_class + " altered",
        "uses": (
            original.uses[:-1]
            if original.uses
            else (alternate_dependency,)
        ),
    }
    candidate[index] = replace(original, **{field: values[field]})
    with pytest.raises(ValueError, match="contract catalogue changed"):
        _bound(catalogue=tuple(candidate))


@pytest.mark.parametrize("collection", ("symbols", "results"))
@pytest.mark.parametrize("term_field", ("markup", "meaning", "unit"))
def test_every_nested_term_field_is_sealed(collection, term_field):
    for contract_index, original in enumerate(contract.MANUAL_EQUATION_CONTRACTS):
        terms = getattr(original, collection)
        for term_index, term in enumerate(terms):
            if term_field == "unit":
                value = "MPa" if term.unit != "MPa" else "1"
            else:
                value = getattr(term, term_field) + " altered"
            changed_terms = list(terms)
            changed_terms[term_index] = replace(term, **{term_field: value})
            candidate = list(contract.MANUAL_EQUATION_CONTRACTS)
            candidate[contract_index] = replace(
                original,
                **{collection: tuple(changed_terms)},
            )
            with pytest.raises(ValueError, match="contract catalogue changed"):
                _bound(catalogue=tuple(candidate))


def test_missing_duplicate_reordered_unknown_and_shape_shifted_catalogues_fail():
    canonical = contract.MANUAL_EQUATION_CONTRACTS
    variants = (
        canonical[:-1],
        (*canonical[:-1], canonical[-2]),
        (canonical[1], canonical[0], *canonical[2:]),
        (*canonical, canonical[-1]),
        list(canonical),
        (
            replace(canonical[0], symbols=list(canonical[0].symbols)),
            *canonical[1:],
        ),
        (
            replace(canonical[0], results=list(canonical[0].results)),
            *canonical[1:],
        ),
        (
            replace(canonical[0], uses=list(canonical[0].uses)),
            *canonical[1:],
        ),
    )
    for candidate in variants:
        with pytest.raises(ValueError, match="contract catalogue changed"):
            _bound(catalogue=candidate)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing", "cardinality"),
        ("duplicate", "location"),
        ("reordered", "location"),
        ("expression", "expression"),
        ("location", "location"),
        ("source", "provenance"),
        ("located-type", "Located manual equation type"),
        ("location-type", "location type"),
        ("source-type", "source type"),
        ("type", "type"),
        ("container", "tuple"),
    ),
)
def test_candidate_selected_sourced_chain_cannot_gain_semantics(mutation, message):
    equations = _sourced()
    if mutation == "missing":
        candidate = equations[:-1]
    elif mutation == "duplicate":
        candidate = (*equations[:-1], equations[-2])
    elif mutation == "reordered":
        candidate = (equations[1], equations[0], *equations[2:])
    elif mutation == "expression":
        first = equations[0]
        located = replace(
            first.equation,
            expression=first.equation.expression + "x",
        )
        candidate = (replace(first, equation=located), *equations[1:])
    elif mutation == "location":
        first = equations[0]
        altered_location = replace(
            first.equation.location,
            section="Altered section",
        )
        candidate = (
            replace(first, equation=replace(first.equation, location=altered_location)),
            *equations[1:],
        )
    elif mutation == "source":
        first = equations[0]
        candidate = (
            replace(
                first,
                source=replace(
                    first.source,
                    source_text=first.source.source_text + " Altered.",
                ),
            ),
            *equations[1:],
        )
    elif mutation == "located-type":
        first = equations[0]
        candidate = (replace(first, equation=object()), *equations[1:])
    elif mutation == "location-type":
        first = equations[0]
        candidate = (
            replace(first, equation=replace(first.equation, location=object())),
            *equations[1:],
        )
    elif mutation == "source-type":
        first = equations[0]
        candidate = (replace(first, source=object()), *equations[1:])
    elif mutation == "type":
        candidate = (object(), *equations[1:])
    else:
        candidate = list(equations)
    with pytest.raises(ValueError, match=message):
        _bound(candidate)


def test_contract_records_bindings_and_nested_terms_are_immutable_exact_types():
    assert {field.name for field in fields(contract.ManualEquationTerm)} == {
        "markup", "meaning", "unit",
    }
    assert {field.name for field in fields(contract.ManualEquationContract)} == {
        "ordinal", "key", "number", "symbols", "results",
        "dimensional_class", "uses",
    }
    assert {
        field.name for field in fields(contract.ContractedManualEquation)
    } == {"equation", "contract"}
    item = _bound()[0]
    with pytest.raises(FrozenInstanceError):
        item.contract.number = "candidate"
    with pytest.raises(FrozenInstanceError):
        item.contract.symbols[0].unit = "candidate"
    with pytest.raises(FrozenInstanceError):
        item.equation = object()


def test_dependency_graph_is_complete_known_unique_and_acyclic():
    contracts = contract.MANUAL_EQUATION_CONTRACTS
    by_key = {item.key: item for item in contracts}
    assert len(by_key) == 32
    visiting = set()
    visited = set()

    def visit(key):
        assert key not in visiting
        if key in visited:
            return
        visiting.add(key)
        for dependency in by_key[key].uses:
            assert dependency in by_key
            assert dependency != key
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in by_key:
        visit(key)
    assert len(visited) == 32


def test_contract_module_has_only_predecessors_and_standard_library_imports():
    path = ROOT / "app" / "manual_equation_contract.py"
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
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "manual_equation_location",
        "manual_equation_source",
    }
    assert not imported.intersection(
        {
            "manual",
            "streamlit",
            "reportlab",
            "sector_report",
            "sector",
            "report_equation_contract",
        }
    )
