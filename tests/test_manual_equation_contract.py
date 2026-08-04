"""Independent contract and adversarial checks for Part C manual equations."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import FrozenInstanceError, replace
import pathlib
import re
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import manual_equation_contract as contract  # noqa: E402


EXPECTED_KEYS = (
    "manual.material.concrete-law",
    "manual.material.steel-law",
    "manual.material.prestress-law",
    "manual.plastic.governing-curvature",
    "manual.detailing.minimum-2005",
    "manual.detailing.minimum-2023-bending",
    "manual.detailing.minimum-2023-axial",
    "manual.detailing.clear-spacing",
    "manual.detailing.links.minimum-ratio",
    "manual.detailing.links.spacing",
    "manual.detailing.torsion.minimum-ratio",
    "manual.crack.2005.width",
    "manual.crack.2005.spacing",
    "manual.crack.2023.width",
    "manual.crack.2023.spacing",
    "manual.fatigue.stress-range",
    "manual.fatigue.reinforcement.design-range",
    "manual.fatigue.reinforcement.life",
    "manual.fatigue.reinforcement.miner",
    "manual.fatigue.concrete.strength-2005",
    "manual.fatigue.concrete.strength-2023",
    "manual.fatigue.concrete.life",
    "manual.fatigue.concrete.equivalent",
    "manual.shear.no-links.variable",
    "manual.shear.no-links.minimum",
    "manual.shear.action-factor-2023",
    "manual.shear.links-2005",
    "manual.shear.links-2023",
    "manual.torsion.resistance",
    "manual.torsion.strut-interaction",
    "manual.combined.strut-interaction",
    "manual.combined.utilisation",
)

EXPECTED_NUMBERS = (
    "C3-1", "C3-2", "C3-3", "C4-1", "C5-1", "C5-2", "C5-3",
    "C5-4", "C5-5", "C5-6", "C5-7", "C7-1", "C7-2", "C7-3",
    "C7-4", "C8-1", "C8-2", "C8-3", "C8-4", "C8-5", "C8-6",
    "C8-7", "C8-8", "C9-1", "C9-2", "C9-3", "C9-4", "C9-5",
    "C10-1", "C10-2", "C11-1", "C11-2",
)

EXPECTED_DEPENDENCIES = {
    "manual.detailing.torsion.minimum-ratio": (
        "manual.detailing.links.minimum-ratio",
    ),
    "manual.crack.2005.width": ("manual.crack.2005.spacing",),
    "manual.crack.2023.width": ("manual.crack.2023.spacing",),
    "manual.fatigue.reinforcement.life": (
        "manual.fatigue.reinforcement.design-range",
    ),
    "manual.fatigue.reinforcement.miner": (
        "manual.fatigue.reinforcement.life",
    ),
    "manual.shear.links-2023": (
        "manual.detailing.links.minimum-ratio",
    ),
    "manual.torsion.strut-interaction": (
        "manual.torsion.resistance", "manual.shear.links-2005",
    ),
    "manual.combined.strut-interaction": (
        "manual.torsion.strut-interaction",
    ),
}

EXPECTED_SEALS = {
    "identity": "f225373dafbe17de1b14d9451ce5aa954e9a2db273edf78c43b81c5090d7e5e8",
    "sources": "b5f89bef1fff29aee683cef9313f453a6d057649c16c61cc220aeba7450be9c1",
    "symbols": "e23f42d7f5805311a4f3ac9205f2670c42e4f6c04bf8388fe9e2fb3c5b556ce1",
    "dimensions": "3c4cf16f8cfa2f89c0af952b495eae9b0949dd7fdbc939c8ff9ad664ca2b4887",
    "dependencies": "566c401f3b6aa3e5fb3f53ef85ebcfa00081bf547fa7a94410e47e919de1fc4c",
}


def _registered():
    return contract.register_manual_equations(manual.manual_blocks())


def _spec(key):
    return next(spec for spec in contract.MANUAL_EQUATION_SPECS if spec.key == key)


def _symbol(spec, latex):
    return next(symbol for symbol in spec.symbols if symbol.latex == latex)


def _replace_spec(index, replacement):
    specs = list(contract.MANUAL_EQUATION_SPECS)
    specs[index] = replacement
    return tuple(specs)


def _first_equation_block():
    blocks = list(manual.manual_blocks())
    index = next(
        index for index, block in enumerate(blocks)
        if block[0] == "md" and "$$" in block[1]
    )
    return blocks, index


def test_exact_source_catalogue_registers_in_frozen_order():
    registered = _registered()
    assert len(registered) == 32
    assert tuple(item.spec.key for item in registered) == EXPECTED_KEYS
    assert tuple(item.spec.number for item in registered) == EXPECTED_NUMBERS
    assert all(item.spec.part == "Part C - Theory & methodology" for item in registered)
    assert all(item.expression.isascii() for item in registered)
    assert sum(len(item.spec.symbols) for item in registered) == 201
    assert Counter(item.spec.source_kind for item in registered) == {
        "standard": 28, "mixed": 2, "project": 2,
    }


def test_complete_advertised_inventories_have_frozen_seals():
    assert {
        field: contract.inventory_sha256(field) for field in EXPECTED_SEALS
    } == EXPECTED_SEALS
    with pytest.raises(ValueError, match="Unknown manual equation inventory"):
        contract.inventory_sha256("results")


def test_formula_tokens_exactly_equal_each_local_symbol_inventory():
    for item in _registered():
        assert contract.equation_symbol_tokens(item.expression) == tuple(
            symbol.latex for symbol in item.spec.symbols
        ), item.spec.key


def test_dependency_graph_contains_only_nine_genuine_links():
    actual = {
        spec.key: spec.uses for spec in contract.MANUAL_EQUATION_SPECS if spec.uses
    }
    assert actual == EXPECTED_DEPENDENCIES
    assert sum(len(targets) for targets in actual.values()) == 9


def test_duplicate_expression_is_semantically_disambiguated():
    torsion = _spec("manual.torsion.strut-interaction")
    combined = _spec("manual.combined.strut-interaction")
    assert torsion.expression_sha256 == combined.expression_sha256
    assert torsion.key != combined.key
    assert torsion.number == "C10-2"
    assert combined.number == "C11-1"
    assert torsion.section != combined.section


def test_empirical_coefficients_publish_their_fractional_mpa_units():
    links = _spec("manual.detailing.links.minimum-ratio")
    shear = _spec("manual.shear.no-links.variable")
    assert _symbol(links, "c").unit == "MPa^(1/2)"
    assert "c sqrt(f_ck)/f_ywk" in links.dimensional_note
    assert _symbol(shear, r"C_{Rd,c}").unit == "MPa^(2/3)"
    assert "f_ck^(1/3)" in shear.dimensional_note


def test_solver_aligned_coordinate_and_torsion_units_are_pinned():
    prestress = _spec("manual.material.prestress-law")
    curvature = _spec("manual.plastic.governing-curvature")
    action = _spec("manual.shear.action-factor-2023")
    torsion = _spec("manual.torsion.resistance")
    assert _symbol(prestress, r"\kappa").unit == "1/m"
    assert _symbol(prestress, r"s_{p,j}").unit == "m"
    assert _symbol(curvature, "c").unit == "m"
    assert _symbol(action, r"a_{cs}").unit == "m"
    assert _symbol(action, "d").unit == "m"
    assert _symbol(action, r"M_{Ed}").unit == "kNm"
    assert _symbol(action, r"V_{Ed}").unit == "kN"
    assert _symbol(torsion, r"A_{k}").unit == "m2"
    assert _symbol(torsion, r"t_{ef}").unit == "m"
    assert _symbol(torsion, r"A_{sw}").unit == "mm2"
    assert _symbol(torsion, "s").unit == "mm"


def test_fatigue_literal_and_generic_action_identity_is_explicit():
    life = _spec("manual.fatigue.reinforcement.life")
    strength_2005 = _spec("manual.fatigue.concrete.strength-2005")
    strength_2023 = _spec("manual.fatigue.concrete.strength-2023")
    generic = _spec("manual.combined.utilisation")
    assert _symbol(life, r"N^*").unit == "cycles"
    assert "250 carries MPa" in strength_2005.dimensional_note
    assert "40 carries MPa" in strength_2023.dimensional_note
    assert {_symbol(generic, name).unit for name in (r"S_{Ed}", r"S_{Rd}")} == {
        "actions"
    }


def test_project_defined_methods_remain_uncited():
    project = [
        spec for spec in contract.MANUAL_EQUATION_SPECS
        if spec.source_kind == "project"
    ]
    assert {spec.key for spec in project} == {
        "manual.material.steel-law", "manual.plastic.governing-curvature",
    }
    assert all("DS/EN" not in spec.source for spec in project)
    assert all("no normative" in spec.source.lower() or "no separate" in spec.source.lower()
               for spec in project)


@pytest.mark.parametrize("mutation", ["changed", "missing", "duplicate"])
def test_source_expression_mutations_are_rejected(mutation):
    blocks, index = _first_equation_block()
    block = blocks[index]
    expression = re.search(r"\$\$(.+?)\$\$", block[1], re.DOTALL).group(0)
    if mutation == "changed":
        text = block[1].replace(r"\sigma_c", r"\sigma_x", 1)
    elif mutation == "missing":
        text = block[1].replace(expression, "", 1)
    else:
        text = block[1].replace(expression, expression + "\n\n" + expression, 1)
    blocks[index] = ("md", text)
    with pytest.raises(ValueError, match="cardinality changed|expression changed"):
        contract.register_manual_equations(blocks)


def test_moved_source_expression_is_rejected():
    blocks = list(manual.manual_blocks())
    index = next(
        index for index, block in enumerate(blocks)
        if block[0] == "h2" and block[1] == "Concrete (parabola-rectangle)"
    )
    blocks[index] = ("h2", "Mild steel")
    with pytest.raises(ValueError, match="moved from its frozen location"):
        contract.register_manual_equations(blocks)


@pytest.mark.parametrize("mutation", ["missing", "reordered", "duplicate"])
def test_registry_cardinality_order_and_duplicate_identity_are_rejected(mutation):
    specs = list(contract.MANUAL_EQUATION_SPECS)
    if mutation == "missing":
        specs.pop()
    elif mutation == "reordered":
        specs[0], specs[1] = specs[1], specs[0]
    else:
        specs[-1] = specs[-2]
    with pytest.raises(ValueError):
        contract.register_manual_equations(manual.manual_blocks(), specs)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("key", "not-canonical", "keys must be unique"),
        ("number", "Equation 1", "numbers must be unique"),
        ("source_kind", "candidate", "source identity"),
        ("source", " ", "source identity"),
        ("dimensional_note", " ", "dimensional contract"),
        ("uses", ("manual.unknown",), "unknown equation"),
    ],
)
def test_mutated_advertised_spec_fields_are_rejected(field, value, match):
    first = contract.MANUAL_EQUATION_SPECS[0]
    altered = replace(first, **{field: value})
    with pytest.raises(ValueError, match=match):
        contract.register_manual_equations(
            manual.manual_blocks(), _replace_spec(0, altered)
        )


@pytest.mark.parametrize("mutation", ["missing", "reordered", "unknown", "duplicate"])
def test_mutated_local_symbol_inventories_are_rejected(mutation):
    first = contract.MANUAL_EQUATION_SPECS[0]
    symbols = list(first.symbols)
    if mutation == "missing":
        symbols.pop()
    elif mutation == "reordered":
        symbols[0], symbols[1] = symbols[1], symbols[0]
    elif mutation == "unknown":
        symbols[0] = replace(symbols[0], latex="x")
    else:
        symbols[-1] = symbols[0]
    altered = replace(first, symbols=tuple(symbols))
    with pytest.raises(
        ValueError, match="symbol.*inventory changed|duplicate local symbols"
    ):
        contract.register_manual_equations(
            manual.manual_blocks(), _replace_spec(0, altered)
        )


@pytest.mark.parametrize(
    ("field", "value"), [("meaning", " "), ("unit", "MPa/sqrt(mm)")]
)
def test_invalid_symbol_meaning_or_unit_is_rejected(field, value):
    first = contract.MANUAL_EQUATION_SPECS[0]
    symbols = list(first.symbols)
    symbols[0] = replace(symbols[0], **{field: value})
    altered = replace(first, symbols=tuple(symbols))
    with pytest.raises(ValueError, match="invalid symbol definition"):
        contract.register_manual_equations(
            manual.manual_blocks(), _replace_spec(0, altered)
        )


@pytest.mark.parametrize(
    ("mutation", "inventory"),
    [
        ("key", "identity"),
        ("number", "identity"),
        ("digest", "identity"),
        ("source-kind", "sources"),
        ("source", "sources"),
        ("meaning", "symbols"),
        ("unit", "symbols"),
        ("dimension", "dimensions"),
        ("dependency", "dependencies"),
    ],
)
def test_valid_looking_coherently_resealed_fields_are_rejected(mutation, inventory):
    index = 0
    spec = contract.MANUAL_EQUATION_SPECS[index]
    if mutation == "key":
        altered = replace(spec, key="manual.material.concrete-law-altered")
    elif mutation == "number":
        altered = replace(spec, number="C3-4")
    elif mutation == "digest":
        altered = replace(spec, expression_sha256="0" * 64)
    elif mutation == "source-kind":
        altered = replace(spec, source_kind="mixed")
    elif mutation == "source":
        altered = replace(spec, source=spec.source + " Candidate addendum.")
    elif mutation in {"meaning", "unit"}:
        symbols = list(spec.symbols)
        change = {mutation: "candidate meaning" if mutation == "meaning" else "1"}
        symbols[0] = replace(symbols[0], **change)
        altered = replace(spec, symbols=tuple(symbols))
    elif mutation == "dimension":
        altered = replace(spec, dimensional_note="Candidate dimensional closure.")
    else:
        index = next(
            i for i, value in enumerate(contract.MANUAL_EQUATION_SPECS)
            if value.key == "manual.detailing.torsion.minimum-ratio"
        )
        spec = contract.MANUAL_EQUATION_SPECS[index]
        altered = replace(spec, uses=("manual.material.concrete-law",))
    with pytest.raises(
        ValueError, match=f"frozen manual equation {inventory} inventory changed"
    ):
        contract.register_manual_equations(
            manual.manual_blocks(), _replace_spec(index, altered)
        )


def test_contract_records_are_immutable():
    item = _registered()[0]
    with pytest.raises(FrozenInstanceError):
        item.expression = "candidate"
    with pytest.raises(FrozenInstanceError):
        item.spec.symbols[0].unit = "1"


def test_contract_module_has_no_renderer_or_manual_dependency():
    path = ROOT / "app" / "manual_equation_contract.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in tree.body if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module for node in tree.body if isinstance(node, ast.ImportFrom)
        and node.module is not None
    )
    assert not imported.intersection({
        "manual", "streamlit", "reportlab", "sector_report",
    })
