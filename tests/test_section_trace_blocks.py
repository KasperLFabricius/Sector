from __future__ import annotations

import copy
import dataclasses

import pytest

from sector import codes, material_presets
from sector.calculation_trace import SOURCE_PROJECT, trace_identity_token
from sector.materials import Concrete, MildSteel
from sector.section import Section
from sector.section_trace_blocks import (
    CROSS_EDITION_METHOD,
    MIXED_PROJECT_METHOD,
    PROJECT_METHOD,
    context_axes,
    context_id,
    section_trace_blocks,
)


def _catalog_item(material_id, preset, law):
    item = {"id": material_id, "preset": preset}
    for field in dataclasses.fields(law):
        value = getattr(law, field.name)
        if field.name in {"IS", "eut", "ey0t", "ey0c"}:
            value *= 1000.0
        elif field.name == "Es":
            value /= 1000.0
        item[field.name] = value
    return item


def _preset_steel(preset):
    values = material_presets.MILD_PRESETS[preset]
    return material_presets.build_mild(
        values["curve"],
        **{key: value for key, value in values.items() if key != "curve"},
    )


@pytest.fixture
def block_input():
    section = Section.from_polygon(
        [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        [(0.06, 0.05, 500.0), (0.24, 0.55, 500.0)],
    )
    return {
        "section": section,
        "concrete": codes.EC2_2005.concrete(35.0),
        "steel": codes.EC2_2005.steel(500.0),
        "concrete_preset": codes.EC2_2005.label,
        "mild_preset": codes.EC2_2005.label,
        "P_pl": 0.0,
        "Mx_pl": 10.0,
        "My_pl": 20.0,
    }


def _assigned_bars(block_input):
    standard = _preset_steel(codes.EC2_2023.label)
    custom = MildSteel(
        620.0,
        430.0,
        futk=680.0,
        eut=0.032,
        curve=1,
        Es=205000.0,
    )
    assigned = {
        **block_input,
        "bar_materials": [standard, custom],
        "bar_elements": [
            {"id": "B1", "material_id": "M1"},
            {"id": "B2", "material_id": "M2"},
        ],
        "mild_material_catalog": {
            "items": [
                _catalog_item("M1", codes.EC2_2023.label, standard),
                _catalog_item("M2", "Custom / imported", custom),
            ]
        },
    }
    return assigned, standard, custom


def test_context_identity_is_injective_and_preserves_family_axes():
    first = {"case": "A/B", "stage": 2}
    second = {"stage": 2, "case": "A/B"}

    assert context_id({}) == "section"
    assert context_axes({}) == ()
    assert context_id(first) == context_id(second)
    assert context_axes(first, axis="x") == context_axes(second, axis="x")
    assert context_axes({}, axis="x")[0].name == "axis"
    assert context_axes(first, axis="x") != context_axes(first, axis="y")
    assert context_id({"case/id": "A"}) != context_id({"case-id": "A"})
    assert context_axes({"case/id": "A"}) != context_axes({"case-id": "A"})

    with pytest.raises(ValueError, match="replace"):
        context_axes({"axis": "context"}, axis="family")
    encoded = trace_identity_token("case")
    with pytest.raises(ValueError, match="replace"):
        context_axes({"case": "A"}, **{encoded: "family"})


def test_blocks_are_immutable_and_keep_every_solver_material(block_input):
    blocks = section_trace_blocks(block_input)

    assert blocks.plastic_method_id == "ec2-2005"
    assert dict(blocks.plastic_actions.values) == {
        "P_pl": 0.0,
        "Mx_pl": 10.0,
        "My_pl": 20.0,
    }
    assert len(blocks.geometry.rings) == 1
    assert len(blocks.geometry.bars) == len(blocks.bars) == 2
    assert blocks.concrete.element_id == "concrete"
    assert [item.element_id for item in blocks.bars] == [
        "bar-001",
        "bar-002",
    ]
    assert all(
        item.provenance.source.edition == codes.EC2_2005.label
        for item in (blocks.concrete, *blocks.bars)
    )
    assert dict(blocks.bars[0].values) == {
        field.name: float(
            int(getattr(block_input["steel"], field.name))
            if type(getattr(block_input["steel"], field.name)) is bool
            else getattr(block_input["steel"], field.name)
        )
        for field in dataclasses.fields(block_input["steel"])
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        blocks.plastic_actions.values = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        blocks.bars[0].material_id = "changed"


@pytest.mark.parametrize("malformed", [True, "10", float("inf"), float("nan")])
def test_actions_reject_non_numeric_boolean_and_nonfinite_values(
    block_input,
    malformed,
):
    with pytest.raises(ValueError, match="actions"):
        section_trace_blocks({**block_input, "P_pl": malformed})


def test_explicit_assignments_require_exact_complete_catalog_vectors(
    block_input,
):
    assigned, standard, custom = _assigned_bars(block_input)

    blocks = section_trace_blocks(assigned)
    assert blocks.plastic_method_id == MIXED_PROJECT_METHOD
    assert [(item.element_id, item.material_id) for item in blocks.bars] == [
        ("B1", "M1"),
        ("B2", "M2"),
    ]
    assert blocks.bars[0].provenance.source.edition == codes.EC2_2023.label
    assert blocks.bars[1].provenance.source.kind == SOURCE_PROJECT
    assert blocks.bars[1].provenance.source.citation is None

    with pytest.raises(ValueError, match="does not match"):
        section_trace_blocks(
            {**assigned, "bar_materials": [custom, standard]}
        )

    tampered = copy.deepcopy(assigned)
    tampered["mild_material_catalog"]["items"][0]["Es"] += 1.0
    with pytest.raises(ValueError, match="does not match"):
        section_trace_blocks(tampered)

    with pytest.raises(ValueError, match="aligned catalog"):
        section_trace_blocks(
            {
                **block_input,
                "bar_materials": [standard, custom],
                "bar_elements": assigned["bar_elements"],
            }
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["bar_elements"][0].pop("material_id"),
            "non-blank material IDs",
        ),
        (
            lambda value: value["bar_elements"][0].update(material_id=""),
            "non-blank material IDs",
        ),
        (
            lambda value: value["bar_elements"][1].update(id="B1"),
            "duplicate bar element ID",
        ),
        (
            lambda value: value["bar_elements"].append(
                {"id": "B3", "material_id": "M1"}
            ),
            "aligned bar element",
        ),
    ],
)
def test_explicit_assignments_reject_missing_or_duplicate_identities(
    block_input,
    mutation,
    message,
):
    assigned, _, _ = _assigned_bars(block_input)
    mutation(assigned)
    with pytest.raises(ValueError, match=message):
        section_trace_blocks(assigned)


def test_edited_named_presets_are_project_laws_without_citations(block_input):
    assigned, _, _ = _assigned_bars(block_input)
    forged = MildSteel(
        610.0,
        590.0,
        futk=650.0,
        eut=0.04,
        curve=1,
    )
    assigned.update(
        concrete=Concrete(35.0, 1.31, alpha_cc=0.91),
        bar_materials=[forged, forged],
        mild_material_catalog={
            "items": [
                _catalog_item("M1", codes.EC2_2005.label, forged),
                _catalog_item("M2", codes.EC2_2005.label, forged),
            ]
        },
    )

    blocks = section_trace_blocks(assigned)
    assert blocks.plastic_method_id == PROJECT_METHOD
    assert all(
        item.provenance.source.kind == SOURCE_PROJECT
        and item.provenance.source.citation is None
        for item in (blocks.concrete, *blocks.bars)
    )


def test_common_cross_edition_mixed_and_project_methods_are_exact(block_input):
    assigned, standard, _ = _assigned_bars(block_input)
    assert section_trace_blocks(block_input).plastic_method_id == "ec2-2005"
    assert section_trace_blocks(assigned).plastic_method_id == MIXED_PROJECT_METHOD

    cross_edition = copy.deepcopy(assigned)
    cross_edition["bar_materials"] = [standard, standard]
    cross_edition["mild_material_catalog"]["items"] = [
        _catalog_item("M1", codes.EC2_2023.label, standard),
        _catalog_item("M2", codes.EC2_2023.label, standard),
    ]
    assert (
        section_trace_blocks(cross_edition).plastic_method_id
        == CROSS_EDITION_METHOD
    )

    common_2023 = {
        **cross_edition,
        "concrete": codes.EC2_2023.concrete(35.0),
        "concrete_preset": codes.EC2_2023.label,
    }
    assert section_trace_blocks(common_2023).plastic_method_id == "ec2-2023"


def test_standard_code_keys_resolve_to_canonical_bar_and_tendon_presets():
    section = Section.from_polygon(
        [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        [(0.06, 0.05, 500.0)],
        tendons_xy_area_mm2=[(0.15, 0.08, 400.0)],
    )
    bar = _preset_steel(codes.EC2_2023.label)
    tendon_values = material_presets.PRESTRESS_PRESETS[codes.EC2_2023.label]
    tendon = material_presets.build_prestress(
        tendon_values["curve"],
        **{
            key: value
            for key, value in tendon_values.items()
            if key != "curve"
        },
    )
    blocks = section_trace_blocks(
        {
            "section": section,
            "concrete": codes.EC2_2023.concrete(35.0),
            "concrete_preset": codes.EC2_2023.key,
            "bar_materials": [bar],
            "bar_elements": [{"id": "B1", "material_id": "M1"}],
            "mild_material_catalog": {
                "items": [
                    _catalog_item("M1", codes.EC2_2023.key, bar),
                ]
            },
            "tendon_materials": [tendon],
            "tendon_elements": [{"id": "T1", "material_id": "P1"}],
            "prestress_material_catalog": {
                "items": [
                    _catalog_item("P1", codes.EC2_2023.key, tendon),
                ]
            },
        }
    )

    assert blocks.plastic_method_id == "ec2-2023"
    assert all(
        item.provenance.source.edition == codes.EC2_2023.label
        for item in (blocks.concrete, *blocks.bars, *blocks.tendons)
    )


def test_builtin_tendon_catalog_reconstructs_only_curve_specific_fields():
    section = Section.from_polygon(
        [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        [],
        tendons_xy_area_mm2=[(0.15, 0.08, 400.0)],
    )
    values = material_presets.PRESTRESS_PRESETS["Curve 1 (built-in)"]
    tendon = material_presets.build_prestress(
        values["curve"],
        **{key: value for key, value in values.items() if key != "curve"},
    )
    item = _catalog_item("P1", "Curve 1 (built-in)", tendon)
    item.update(
        {
            "fytk": 1600.0,
            "futk": 1860.0,
            "eut": 35.0,
            "k": 0.8,
            "ey0t": 3.0,
        }
    )
    inp = {
        "section": section,
        "concrete": codes.EC2_2005.concrete(35.0),
        "concrete_preset": codes.EC2_2005.label,
        "tendon_materials": [tendon],
        "tendon_elements": [{"id": "T1", "material_id": "P1"}],
        "prestress_material_catalog": {"items": [item]},
    }

    blocks = section_trace_blocks(inp)
    assert len(blocks.tendons) == 1
    assert blocks.tendons[0].element_id == "T1"
    assert blocks.tendons[0].material_id == "P1"
    assert dict(blocks.tendons[0].values)["curve"] == 1.0

    tampered = copy.deepcopy(inp)
    tampered["prestress_material_catalog"]["items"][0]["IS"] += 0.1
    with pytest.raises(ValueError, match="does not match"):
        section_trace_blocks(tampered)
