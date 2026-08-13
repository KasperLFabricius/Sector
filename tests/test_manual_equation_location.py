"""Independent contract and adversarial tests for Part C equation locations."""

from __future__ import annotations

import ast
from collections import Counter, UserList
from collections.abc import Set
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
    "manual.crack.dk-na-heightened",
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
    "C5-4", "C5-5", "C5-6", "C5-7", "C7-1", "C7-2", "C7-5",
    "C7-3", "C7-4", "C8-1", "C8-2", "C8-3", "C8-4", "C8-5", "C8-6",
    "C8-7", "C8-8", "C9-1", "C9-2", "C9-3", "C9-4", "C9-5",
    "C10-1", "C10-2", "C11-1", "C11-2",
)

EXPECTED_CATALOGUE_SEAL = (
    "1fc22df5ac99229f6cffde7829c5d644127b54a68ac49850162c7c075ce6fede"
)


class _CustomSet(Set):
    """Small non-builtin set used to exercise the abstract container boundary."""

    def __init__(self, values):
        self._values = tuple(values)

    def __contains__(self, value):
        return value in self._values

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


def _blocks():
    return list(manual.manual_blocks())


def _registered(blocks=None):
    return location.register_manual_equation_locations(
        manual.manual_blocks() if blocks is None else blocks
    )


def _part_span(blocks, name):
    start = next(
        index for index, block in enumerate(blocks)
        if block[:2] == ("part", name)
    )
    end = next(
        (
            index for index in range(start + 1, len(blocks))
            if blocks[index][0] == "part"
        ),
        len(blocks),
    )
    return start, end


def _first_part_c_display(blocks):
    start, end = _part_span(blocks, location.PART_C)
    return next(
        index for index in range(start + 1, end)
        if blocks[index][0] == "md"
        and location.DISPLAY_DELIMITER in blocks[index][1]
    )


def test_live_manual_registers_exact_catalogue_in_authored_order():
    registered = _registered()
    assert len(registered) == 33
    assert tuple(item.location.ordinal for item in registered) == tuple(range(1, 34))
    assert tuple(item.location.key for item in registered) == EXPECTED_KEYS
    assert tuple(item.location.number for item in registered) == EXPECTED_NUMBERS
    assert all(item.location.part == location.PART_C for item in registered)
    assert all(item.expression and item.expression.isascii() for item in registered)


def test_complete_catalogue_has_exact_seal():
    assert location.location_catalogue_sha256() == EXPECTED_CATALOGUE_SEAL


@pytest.mark.parametrize(
    "part_name",
    ["Part A - Get started", "Part B - Features & options", "Part D - Reference"],
)
@pytest.mark.parametrize("shape", ["markdown", "heading", "excluded"])
def test_display_content_outside_part_c_is_inert(part_name, shape):
    blocks = _blocks()
    start, end = _part_span(blocks, part_name)
    if shape == "markdown":
        index = next(
            i for i in range(start + 1, end) if blocks[i][0] == "md"
        )
        blocks[index] = ("md", blocks[index][1] + "\n\n$$outside=value.$$")
    elif shape == "heading":
        blocks.insert(start + 1, ("h2", "Outside $$x=y.$$"))
    else:
        blocks.insert(start + 1, ("candidate", {"nested": ["$$x=y.$$"]}))
    assert tuple(item.location.key for item in _registered(blocks)) == EXPECTED_KEYS


def test_extra_part_c_markdown_display_is_rejected():
    blocks = _blocks()
    start, _ = _part_span(blocks, location.PART_C)
    blocks.insert(start + 1, ("md", "$$x=y.$$"))
    with pytest.raises(ValueError, match="cardinality changed"):
        _registered(blocks)


@pytest.mark.parametrize("mutation", ["changed", "missing", "duplicate"])
def test_every_live_expression_is_bound_to_its_exact_digest(mutation):
    blocks = _blocks()
    index = _first_part_c_display(blocks)
    text = blocks[index][1]
    match = re.search(r"\$\$(.+?)\$\$", text, re.DOTALL)
    display = match.group(0)
    if mutation == "changed":
        changed = display.replace(r"\sigma_c", r"\sigma_x", 1)
        blocks[index] = ("md", text.replace(display, changed, 1))
    elif mutation == "missing":
        blocks[index] = ("md", text.replace(display, "", 1))
    else:
        blocks[index] = ("md", text.replace(display, display + display, 1))
    with pytest.raises(ValueError, match="cardinality changed|expression changed"):
        _registered(blocks)


def test_equation_moved_to_another_heading_is_rejected():
    blocks = _blocks()
    index = next(
        i for i, block in enumerate(blocks)
        if block[:2] == ("h2", "Concrete (parabola-rectangle)")
    )
    blocks[index] = ("h2", "Mild steel")
    with pytest.raises(ValueError, match="moved"):
        _registered(blocks)


@pytest.mark.parametrize("kind", ["part", "h1", "h2"])
def test_structural_primary_payload_in_part_c_cannot_hide_display(kind):
    blocks = _blocks()
    _, end = _part_span(blocks, location.PART_C)
    blocks.insert(end, (kind, "Hidden $$x=y.$$"))
    with pytest.raises(ValueError, match="structural fields"):
        _registered(blocks)


@pytest.mark.parametrize("kind", ["part", "h1", "h2"])
def test_structural_extra_field_in_part_c_cannot_hide_display(kind):
    blocks = _blocks()
    start, end = _part_span(blocks, location.PART_C)
    index = next(
        i for i in range(start, end) if blocks[i][0] == kind
    )
    blocks[index] = (*blocks[index], {"nested": ["Hidden $$x=y.$$"]})
    with pytest.raises(ValueError, match="structural fields"):
        _registered(blocks)


def test_markdown_extra_field_cannot_hide_display():
    blocks = _blocks()
    index = _first_part_c_display(blocks)
    blocks[index] = (*blocks[index], {"extra": ["Hidden $$x=y.$$"]})
    with pytest.raises(ValueError, match="Markdown payloads"):
        _registered(blocks)


@pytest.mark.parametrize(
    "hidden_block",
    [
        ("call", "concept", "Callout text with $$x=y.$$"),
        ("table", ["Column"], [["Nested cell with $$x=y.$$"]]),
        ("candidate", {"Key $$x=y.$$": "value"}),
        ("candidate", {"outer": ({"inner": ["$$x=y.$$"]},)}),
        ("candidate", {"set": frozenset(("$$x=y.$$,",))}),
        ("candidate", UserList(["$$x=y.$$"])),
        ("candidate", _CustomSet(("$$x=y.$$",))),
    ],
)
def test_every_text_leaf_of_excluded_part_c_block_is_scanned(hidden_block):
    blocks = _blocks()
    start, _ = _part_span(blocks, location.PART_C)
    blocks.insert(start + 1, hidden_block)
    with pytest.raises(ValueError, match="Markdown payloads"):
        _registered(blocks)


def test_cyclic_excluded_container_is_safe_and_still_scanned():
    cycle = []
    cycle.append(cycle)
    cycle.append("Hidden $$x=y.$$")
    blocks = _blocks()
    start, _ = _part_span(blocks, location.PART_C)
    blocks.insert(start + 1, ("candidate", cycle))
    with pytest.raises(ValueError, match="Markdown payloads"):
        _registered(blocks)


def test_display_cannot_move_from_markdown_to_excluded_block():
    blocks = _blocks()
    index = _first_part_c_display(blocks)
    blocks[index] = ("call", "concept", blocks[index][1])
    with pytest.raises(ValueError, match="Markdown payloads"):
        _registered(blocks)


def test_unknown_block_kind_text_cannot_hide_display():
    blocks = _blocks()
    start, _ = _part_span(blocks, location.PART_C)
    blocks.insert(start + 1, ("candidate-$$x=y.$$", "ordinary payload"))
    with pytest.raises(ValueError, match="Markdown payloads"):
        _registered(blocks)


@pytest.mark.parametrize(
    ("suffix", "error"),
    [
        ("$$unclosed", "unpaired"),
        ("$$$$", "must not be empty"),
        ("$$   $$", "must not be empty"),
        ("$$x=" + chr(945) + "$$", "ASCII"),
    ],
)
def test_malformed_part_c_display_delimiters_fail_closed(suffix, error):
    blocks = _blocks()
    index = _first_part_c_display(blocks)
    blocks[index] = ("md", blocks[index][1] + suffix)
    with pytest.raises(ValueError, match=error):
        _registered(blocks)


def test_adjacent_nonempty_displays_are_counted_not_ignored():
    blocks = _blocks()
    index = _first_part_c_display(blocks)
    blocks[index] = ("md", blocks[index][1] + "$$x=y.$$$$y=z.$$")
    with pytest.raises(ValueError, match="got 35"):
        _registered(blocks)


@pytest.mark.parametrize(
    "bad_block",
    [
        ["md", "text"],
        ("md",),
        (1, "text"),
        ("part", 1),
        ("h1", None),
        ("h2", []),
        ("md", object()),
    ],
)
def test_block_and_structural_payload_types_fail_closed(bad_block):
    blocks = _blocks()
    blocks.insert(0, bad_block)
    with pytest.raises(ValueError, match="tuple|kind|payload"):
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
def test_valid_looking_coherently_resealed_catalogue_is_rejected(field, value):
    candidate = list(location.MANUAL_EQUATION_LOCATIONS)
    candidate[0] = replace(candidate[0], **{field: value})
    with pytest.raises(ValueError, match="Canonical.*catalogue changed"):
        location.register_manual_equation_locations(manual.manual_blocks(), candidate)


def test_missing_duplicate_and_reordered_catalogues_are_rejected():
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


def test_h1_level_equations_deliberately_retain_empty_subsection():
    assert tuple(
        item.number for item in location.MANUAL_EQUATION_LOCATIONS
        if item.subsection == ""
    ) == ("C9-1", "C9-2", "C9-3", "C10-1", "C10-2", "C11-1", "C11-2")


def test_formula_6_29_keeps_two_distinct_semantic_identities():
    by_number = {item.number: item for item in location.MANUAL_EQUATION_LOCATIONS}
    torsion = by_number["C10-2"]
    combined = by_number["C11-1"]
    assert torsion.expression_sha256 == combined.expression_sha256
    assert (torsion.key, torsion.section) != (combined.key, combined.section)


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
            record.key,
            record.number,
            record.part,
            record.section,
            record.subsection,
            record.expression_sha256,
        )
    )


def test_location_slice_advertises_no_successor_contract_fields():
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


def test_module_has_no_manual_renderer_solver_or_source_import():
    path = ROOT / "app" / "manual_equation_location.py"
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
    assert not imported.intersection(
        {
            "manual", "streamlit", "reportlab", "sector_report", "sector",
            "report_equation_contract", "manual_equation_source",
        }
    )
