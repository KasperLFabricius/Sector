"""Focused identity, scope and provenance tests for Part C manual equations."""

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
import manual_equation_identity as identity  # noqa: E402


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

EXPECTED_SEALS = {
    "identity": "e8a56fdb1a699aa314ece500cecdfef59b853cce51188f327cd5c74ae3e7a740",
    "sources": "a00f5070e95623c54d5d4d8d843fe65344615223af746d32bd59fccda64b4496",
}


def _registered(blocks=None):
    return identity.register_manual_equation_identities(
        manual.manual_blocks() if blocks is None else blocks
    )


def _by_key(key):
    return next(
        item for item in identity.MANUAL_EQUATION_IDENTITIES if item.key == key
    )


def _alter_source_block(mutation):
    blocks = list(manual.manual_blocks())
    index = next(
        i for i, block in enumerate(blocks)
        if block[0] == "md" and "$$" in block[1]
    )
    block = blocks[index]
    display = re.search(r"\$\$(.+?)\$\$", block[1], re.DOTALL).group(0)
    if mutation == "changed":
        text = block[1].replace(r"\sigma_c", r"\sigma_x", 1)
    elif mutation == "missing":
        text = block[1].replace(display, "", 1)
    else:
        text = block[1].replace(display, display + "\n\n" + display, 1)
    blocks[index] = ("md", text)
    return blocks


def _add_display_to_part(part_name):
    blocks = list(manual.manual_blocks())
    inside = False
    for index, block in enumerate(blocks):
        if block[0] == "part":
            inside = block[1] == part_name
        elif inside and block[0] == "md":
            blocks[index] = ("md", block[1] + "\n\n$$x=y.$$")
            return blocks
    raise AssertionError(f"No Markdown block found in {part_name}")


def test_exact_part_c_catalogue_registers_in_authored_order():
    registered = _registered()
    assert len(registered) == 32
    assert tuple(item.identity.ordinal for item in registered) == tuple(range(1, 33))
    assert tuple(item.identity.key for item in registered) == EXPECTED_KEYS
    assert tuple(item.identity.number for item in registered) == EXPECTED_NUMBERS
    assert all(item.identity.part == identity.PART_C for item in registered)
    assert all(item.expression.isascii() for item in registered)
    assert Counter(item.identity.source_kind for item in registered) == {
        "standard": 28, "mixed": 2, "project": 2,
    }


def test_identity_and_source_catalogues_have_frozen_seals():
    assert {
        field: identity.catalogue_sha256(field) for field in EXPECTED_SEALS
    } == EXPECTED_SEALS
    with pytest.raises(ValueError, match="Unknown manual equation catalogue"):
        identity.catalogue_sha256("symbols")


@pytest.mark.parametrize(
    "part_name",
    ["Part A - Get started", "Part B - Features & options", "Part D - Reference"],
)
def test_display_equations_outside_part_c_are_inert(part_name):
    registered = _registered(_add_display_to_part(part_name))
    assert tuple(item.identity.key for item in registered) == EXPECTED_KEYS


def test_an_extra_part_c_display_equation_is_rejected():
    with pytest.raises(ValueError, match="Part C equation cardinality changed"):
        _registered(_add_display_to_part(identity.PART_C))


@pytest.mark.parametrize("mutation", ["changed", "missing", "duplicate"])
def test_part_c_expression_mutations_are_rejected(mutation):
    with pytest.raises(ValueError, match="cardinality changed|expression changed"):
        _registered(_alter_source_block(mutation))


def test_moved_part_c_equation_is_rejected():
    blocks = list(manual.manual_blocks())
    index = next(
        i for i, block in enumerate(blocks)
        if block[:2] == ("h2", "Concrete (parabola-rectangle)")
    )
    blocks[index] = ("h2", "Mild steel")
    with pytest.raises(ValueError, match="moved"):
        _registered(blocks)


def test_c9_3_provenance_matches_retained_solver_and_report():
    action = _by_key("manual.shear.action-factor-2023")
    assert "Formulas (8.30) and (8.31)" in action.source
    assert "(8.27)" not in action.source
    shear_source = (ROOT / "sector" / "shear.py").read_text(encoding="utf-8")
    report_source = (ROOT / "app" / "sector_report.py").read_text(encoding="utf-8")
    assert "a_cs = max(abs(MEd/VEd), d)`` (8.30)" in shear_source
    assert "``k_vp = max" in shear_source and ")`` (8.31)" in shear_source
    assert 'ref="EN 1992-1-1:2023 Formula (8.30)"' in report_source
    assert 'Formula (8.31)"' in report_source


def test_concrete_fatigue_sources_match_retained_method_dispatch():
    assert _by_key("manual.fatigue.concrete.strength-2005").source == (
        "DS/EN 1992-1-1:2005+A1:2014 6.8.7, Formula (6.76)."
    )
    assert _by_key("manual.fatigue.concrete.strength-2023").source == (
        "DS/EN 1992-1-1:2023 10.5, Formula (10.5)."
    )
    assert _by_key("manual.fatigue.concrete.equivalent").source == (
        "DS/EN 1992-1-1:2005+A1:2014 6.8.7, Formula (6.72); "
        "DS/EN 1992-1-1:2023 E.4.3, Formula (E.2)."
    )

    dispatch = (ROOT / "sector" / "fatigue_trace_contract.py").read_text(
        encoding="utf-8"
    )
    mechanics = (ROOT / "sector" / "fatigue.py").read_text(encoding="utf-8")
    assert '"Formula (10.5)" if current else "Formula (6.76)"' in dispatch
    assert "Formula (6.72) and EN 1992-1-1:2023" in mechanics
    assert "Formula (E.2). Compression" in mechanics


def test_selected_high_risk_source_identities_are_exact():
    assert "Formula (12.1)" in _by_key(
        "manual.detailing.minimum-2023-bending"
    ).source
    assert "Formula (12.2)" in _by_key(
        "manual.detailing.minimum-2023-axial"
    ).source
    torsion = _by_key("manual.torsion.resistance").source
    for formula in ("Formula (6.27)", "Formula (6.8)", "Formula (6.30)"):
        assert formula in torsion
    assert "Formulas (8.42) and (8.44)" in _by_key(
        "manual.shear.links-2023"
    ).source


def test_project_methods_are_explicitly_uncited():
    project = [
        item for item in identity.MANUAL_EQUATION_IDENTITIES
        if item.source_kind == "project"
    ]
    assert {item.key for item in project} == {
        "manual.material.steel-law", "manual.plastic.governing-curvature",
    }
    assert all("DS/EN" not in item.source for item in project)
    assert all("no normative" in item.source.lower() for item in project)


def test_identity_slice_advertises_no_later_contract_fields():
    assert {field.name for field in fields(identity.ManualEquationIdentity)} == {
        "ordinal", "key", "number", "part", "section", "subsection",
        "expression_sha256", "source_kind", "source",
    }
    item = identity.MANUAL_EQUATION_IDENTITIES[0]
    for excluded in ("symbols", "units", "dimensional_note", "uses", "result"):
        assert not hasattr(item, excluded)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ordinal", 2),
        ("key", "manual.material.concrete-law-altered"),
        ("number", "C3-4"),
        ("section", "Altered section"),
        ("subsection", "Altered subsection"),
        ("expression_sha256", "0" * 64),
        ("source_kind", "mixed"),
        ("source", "Candidate source."),
    ],
)
def test_valid_looking_coherently_altered_catalogue_is_rejected(field, value):
    values = list(identity.MANUAL_EQUATION_IDENTITIES)
    values[0] = replace(values[0], **{field: value})
    with pytest.raises(ValueError, match="canonical.*catalogue changed"):
        identity.register_manual_equation_identities(manual.manual_blocks(), values)


def test_missing_duplicate_and_reordered_catalogue_are_rejected():
    canonical = list(identity.MANUAL_EQUATION_IDENTITIES)
    variants = (
        canonical[:-1],
        canonical[:-1] + [canonical[-2]],
        [canonical[1], canonical[0], *canonical[2:]],
    )
    for variant in variants:
        with pytest.raises(ValueError, match="canonical.*catalogue changed"):
            identity.register_manual_equation_identities(
                manual.manual_blocks(), variant
            )


def test_identical_formula_6_29_expressions_keep_distinct_identity():
    torsion = _by_key("manual.torsion.strut-interaction")
    combined = _by_key("manual.combined.strut-interaction")
    assert torsion.expression_sha256 == combined.expression_sha256
    assert (torsion.key, torsion.number, torsion.section) != (
        combined.key, combined.number, combined.section
    )


def test_identity_records_are_immutable_and_ascii():
    item = _registered()[0]
    with pytest.raises(FrozenInstanceError):
        item.expression = "candidate"
    with pytest.raises(FrozenInstanceError):
        item.identity.source = "candidate"
    assert all(
        value.isascii()
        for record in identity.MANUAL_EQUATION_IDENTITIES
        for value in (
            record.key, record.number, record.part, record.section,
            record.subsection, record.source_kind, record.source,
        )
    )


def test_identity_module_has_no_manual_renderer_or_solver_import():
    path = ROOT / "app" / "manual_equation_identity.py"
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
    })
