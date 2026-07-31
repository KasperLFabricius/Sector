from __future__ import annotations

import dataclasses

import pytest

from sector import codes, material_presets
from sector.materials import Concrete, MildSteel
from sector.section import Section
from sector.section_trace_blocks import section_trace_blocks


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
        values["curve"], **{key: value for key, value in values.items() if key != "curve"}
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


def test_blocks_are_immutable_exact_standard_inputs(block_input):
    blocks = section_trace_blocks(block_input)
    assert blocks.plastic_method_id == "ec2-2005"
    assert dict(blocks.plastic_actions.values) == {
        "P_pl": 0.0,
        "Mx_pl": 10.0,
        "My_pl": 20.0,
    }
    assert len(blocks.geometry.rings) == 1
    assert len(blocks.geometry.bars) == len(blocks.bars) == 2
    assert all(item.provenance.source.edition == codes.EC2_2005.label for item in blocks.bars)
    with pytest.raises(dataclasses.FrozenInstanceError):
        blocks.plastic_actions.values = ()
    for malformed in (True, "10"):
        with pytest.raises(ValueError, match="actions"):
            section_trace_blocks({**block_input, "P_pl": malformed})


def test_explicit_assignments_require_exact_catalog_vectors(block_input):
    standard = _preset_steel(codes.EC2_2023.label)
    custom = MildSteel(620.0, 430.0, futk=680.0, eut=0.032, curve=1, Es=205000.0)
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
    blocks = section_trace_blocks(assigned)
    assert blocks.plastic_method_id == "mixed-standard-project-material-section-solve"
    assert blocks.bars[0].provenance.source.edition == codes.EC2_2023.label
    assert blocks.bars[1].provenance.source.citation is None
    with pytest.raises(ValueError, match="does not match"):
        section_trace_blocks({**assigned, "bar_materials": [custom, standard]})
    with pytest.raises(ValueError, match="aligned catalog provenance"):
        section_trace_blocks({**block_input, "bar_materials": [standard, custom]})
    missing_ids = {
        **assigned,
        "bar_elements": [{"id": "B1"}, {"id": "B2", "material_id": "M2"}],
        "capacity_steel_material_id": "M1",
    }
    with pytest.raises(ValueError, match="aligned catalog provenance"):
        section_trace_blocks(missing_ids)


def test_edited_named_presets_are_project_laws_without_citations(block_input):
    forged = MildSteel(610.0, 590.0, futk=650.0, eut=0.04, curve=1)
    edited = {
        **block_input,
        "bar_materials": [forged, forged],
        "bar_elements": [
            {"id": "B1", "material_id": "M1"},
            {"id": "B2", "material_id": "M2"},
        ],
        "mild_material_catalog": {
            "items": [
                _catalog_item("M1", codes.EC2_2005.label, forged),
                _catalog_item("M2", codes.EC2_2005.label, forged),
            ]
        },
        "concrete": Concrete(35.0, 1.31, alpha_cc=0.91),
    }
    blocks = section_trace_blocks(edited)
    assert blocks.plastic_method_id == "user-defined-material-section-solve"
    assert all(item.provenance.source.citation is None for item in (blocks.concrete, *blocks.bars))


def test_builtin_tendon_catalog_ignores_inert_seed_fields():
    section = Section.from_polygon(
        [(0.0, 0.0), (0.3, 0.0), (0.3, 0.6), (0.0, 0.6)],
        [],
        tendons_xy_area_mm2=[(0.15, 0.08, 400.0)],
    )
    values = material_presets.PRESTRESS_PRESETS["Curve 1 (built-in)"]
    tendon = material_presets.build_prestress(
        values["curve"], **{key: value for key, value in values.items() if key != "curve"}
    )
    item = _catalog_item("P1", "Curve 1 (built-in)", tendon)
    item.update({"fytk": 1600.0, "futk": 1860.0, "eut": 35.0, "k": 1.0})
    blocks = section_trace_blocks(
        {
            "section": section,
            "concrete": codes.EC2_2005.concrete(35.0),
            "steel": codes.EC2_2005.steel(500.0),
            "prestress": tendon,
            "concrete_preset": codes.EC2_2005.label,
            "mild_preset": codes.EC2_2005.label,
            "prestress_preset": "Curve 1 (built-in)",
            "tendon_materials": [tendon],
            "tendon_elements": [{"id": "T1", "material_id": "P1"}],
            "prestress_material_catalog": {"items": [item]},
            "P_pl": 0.0,
            "Mx_pl": 0.0,
            "My_pl": 0.0,
        }
    )
    assert len(blocks.tendons) == 1
    assert dict(blocks.tendons[0].values)["curve"] == 1.0
