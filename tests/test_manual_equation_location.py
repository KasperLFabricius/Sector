"""Focused identity, location and scope tests for Part C manual equations."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import FrozenInstanceError, fields, replace
import pathlib
import re
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import manual_equation_location as location  # noqa: E402


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

EXPECTED_LOCATION_SEAL = (
    "68a50835e369abfde610085c040a7b934a87634d6a0271fa596f63088ab45579"
)


def _registered(blocks=None):
    return location.register_manual_equation_locations(
        manual.manual_blocks() if blocks is None else blocks
    )


def _alter_first_part_c_display(mutation):
    blocks = list(manual.manual_blocks())
    inside = False
    for index, block in enumerate(blocks):
        if block[0] == "part":
            inside = block[1] == location.PART_C
        elif inside and block[0] == "md" and "$$" in block[1]:
            display = re.search(r"\$\$(.+?)\$\$", block[1], re.DOTALL).group(0)
            if mutation == "changed":
                text = block[1].replace(r"\sigma_c", r"\sigma_x", 1)
            elif mutation == "missing":
                text = block[1].replace(display, "", 1)
            else:
                text = block[1].replace(display, display + "\n\n" + display, 1)
            blocks[index] = ("md", text)
            return blocks
    raise AssertionError("No Part C display equation found.")


def _add_display_to_part(part_name):
    blocks = list(manual.manual_blocks())
    inside = False
    for index, block in enumerate(blocks):
        if block[0] == "part":
            inside = block[1] == part_name
        elif inside and block[0] == "md":
            blocks[index] = ("md", block[1] + "\n\n$$x=y.$$")
            return blocks
    raise AssertionError(f"No Markdown block found in {part_name}.")


def test_exact_part_c_catalogue_registers_in_authored_order():
    registered = _registered()
    assert len(registered) == 32
    assert tuple(item.location.ordinal for item in registered) == tuple(range(1, 33))
    assert tuple(item.location.key for item in registered) == EXPECTED_KEYS
    assert tuple(item.location.number for item in registered) == EXPECTED_NUMBERS
    assert all(item.location.part == location.PART_C for item in registered)
    assert all(item.expression.isascii() for item in registered)


def test_complete_location_catalogue_has_frozen_seal():
    assert location.location_catalogue_sha256() == EXPECTED_LOCATION_SEAL


@pytest.mark.parametrize(
    "part_name",
    ["Part A - Get started", "Part B - Features & options", "Part D - Reference"],
)
def test_display_equations_outside_part_c_are_inert(part_name):
    registered = _registered(_add_display_to_part(part_name))
    assert tuple(item.location.key for item in registered) == EXPECTED_KEYS


def test_an_extra_part_c_display_equation_is_rejected():
    with pytest.raises(ValueError, match="Part C equation cardinality changed"):
        _registered(_add_display_to_part(location.PART_C))


@pytest.mark.parametrize("mutation", ["changed", "missing", "duplicate"])
def test_part_c_expression_mutations_are_rejected(mutation):
    with pytest.raises(ValueError, match="cardinality changed|expression changed"):
        _registered(_alter_first_part_c_display(mutation))


def test_moved_part_c_equation_is_rejected():
    blocks = list(manual.manual_blocks())
    index = next(
        i for i, block in enumerate(blocks)
        if block[:2] == ("h2", "Concrete (parabola-rectangle)")
    )
    blocks[index] = ("h2", "Mild steel")
    with pytest.raises(ValueError, match="moved"):
        _registered(blocks)


def test_part_c_display_cannot_move_to_an_excluded_block_kind():
    blocks = list(manual.manual_blocks())
    inside = False
    for index, block in enumerate(blocks):
        if block[0] == "part":
            inside = block[1] == location.PART_C
        elif inside and block[0] == "md" and "$$" in block[1]:
            blocks[index] = ("call", block[1])
            break
    else:
        raise AssertionError("No Part C display equation found.")
    with pytest.raises(ValueError, match="must remain in Markdown content"):
        _registered(blocks)


@pytest.mark.parametrize(
    "hidden_block",
    [
        ("call", "concept", "Callout text with $$x=y.$$"),
        ("table", ["Column"], [["Nested cell with $$x=y.$$"]]),
        ("candidate", {"nested": ["Deep text with $$x=y.$$"]}),
    ],
)
def test_part_c_display_cannot_hide_in_excluded_text_fields(hidden_block):
    blocks = list(manual.manual_blocks())
    part_index = next(
        i for i, block in enumerate(blocks)
        if block[:2] == ("part", location.PART_C)
    )
    blocks.insert(part_index + 1, hidden_block)
    with pytest.raises(ValueError, match="must remain in Markdown content"):
        _registered(blocks)


@pytest.mark.parametrize("kind", ["part", "h1", "h2"])
def test_part_c_display_cannot_hide_in_structural_extra_field(kind):
    blocks = list(manual.manual_blocks())
    inside = False
    for index, block in enumerate(blocks):
        if block[0] == "part":
            inside = block[1] == location.PART_C
        if inside and block[0] == kind:
            blocks[index] = (*block, "Hidden $$x=y.$$")
            break
    else:
        raise AssertionError(f"No Part C {kind} block found.")
    with pytest.raises(ValueError, match="must remain in Markdown content"):
        _registered(blocks)


def test_unpaired_part_c_display_delimiter_fails_closed():
    blocks = list(manual.manual_blocks())
    inside = False
    for index, block in enumerate(blocks):
        if block[0] == "part":
            inside = block[1] == location.PART_C
        elif inside and block[0] == "md":
            blocks[index] = ("md", block[1] + "\n\n$$unclosed")
            break
    with pytest.raises(ValueError, match="Malformed.*delimiter"):
        _registered(blocks)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ordinal", 2),
        ("key", "manual.material.concrete-law-altered"),
        ("number", "C3-4"),
        ("part", "Part B - Features & options"),
        ("section", "Altered section"),
        ("subsection", "Altered subsection"),
        ("expression_sha256", "0" * 64),
    ],
)
def test_valid_looking_coherently_altered_catalogue_is_rejected(field, value):
    values = list(location.MANUAL_EQUATION_LOCATIONS)
    values[0] = replace(values[0], **{field: value})
    with pytest.raises(ValueError, match="Canonical.*catalogue changed"):
        location.register_manual_equation_locations(manual.manual_blocks(), values)


def test_missing_duplicate_and_reordered_catalogue_are_rejected():
    canonical = list(location.MANUAL_EQUATION_LOCATIONS)
    variants = (
        canonical[:-1],
        canonical[:-1] + [canonical[-2]],
        [canonical[1], canonical[0], *canonical[2:]],
    )
    for variant in variants:
        with pytest.raises(ValueError, match="Canonical.*catalogue changed"):
            location.register_manual_equation_locations(
                manual.manual_blocks(), variant
            )


def test_empty_subsections_are_retained_only_at_authored_h1_level():
    empty = [
        item for item in location.MANUAL_EQUATION_LOCATIONS
        if item.subsection == ""
    ]
    assert tuple(item.number for item in empty) == (
        "C9-1", "C9-2", "C9-3", "C10-1", "C10-2", "C11-1", "C11-2",
    )


def test_identical_formula_6_29_expressions_keep_distinct_identity():
    by_number = {
        item.number: item for item in location.MANUAL_EQUATION_LOCATIONS
    }
    torsion = by_number["C10-2"]
    combined = by_number["C11-1"]
    assert torsion.expression_sha256 == combined.expression_sha256
    assert (torsion.key, torsion.number, torsion.section) != (
        combined.key, combined.number, combined.section
    )


def test_location_records_are_immutable_unique_and_ascii():
    item = _registered()[0]
    with pytest.raises(FrozenInstanceError):
        item.expression = "candidate"
    with pytest.raises(FrozenInstanceError):
        item.location.section = "candidate"
    assert Counter(
        record.key for record in location.MANUAL_EQUATION_LOCATIONS
    ).most_common(1)[0][1] == 1
    assert all(
        value.isascii()
        for record in location.MANUAL_EQUATION_LOCATIONS
        for value in (
            record.key, record.number, record.part, record.section,
            record.subsection, record.expression_sha256,
        )
    )


def test_location_slice_advertises_no_later_contract_fields():
    assert {field.name for field in fields(location.ManualEquationLocation)} == {
        "ordinal", "key", "number", "part", "section", "subsection",
        "expression_sha256",
    }
    item = location.MANUAL_EQUATION_LOCATIONS[0]
    for excluded in (
        "source", "source_kind", "symbols", "units", "dimensional_note",
        "uses", "result",
    ):
        assert not hasattr(item, excluded)


@pytest.mark.parametrize(
    "bad_block",
    [("part", 1), ("h1", None), ("h2", []), ("md", object())],
)
def test_retained_structural_block_types_fail_closed(bad_block):
    blocks = list(manual.manual_blocks())
    blocks.insert(0, bad_block)
    with pytest.raises(ValueError, match="must retain string content"):
        _registered(blocks)


def test_malformed_manual_block_fails_closed():
    blocks = list(manual.manual_blocks())
    blocks.insert(0, ("md",))
    with pytest.raises(ValueError, match="Malformed manual block"):
        _registered(blocks)


def test_non_string_manual_block_kind_fails_closed():
    blocks = list(manual.manual_blocks())
    blocks.insert(0, (1, "candidate"))
    with pytest.raises(ValueError, match="kind must retain string identity"):
        _registered(blocks)


def test_location_module_has_no_manual_renderer_solver_or_source_import():
    path = ROOT / "app" / "manual_equation_location.py"
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
        "manual", "streamlit", "reportlab", "sector_report", "sector",
        "report_equation_contract", "manual_equation_source",
    })
