"""Tests for the prestressed-steel material presets."""

from __future__ import annotations

import pytest

from sector import codes, material_presets as mp
from sector.materials import Prestress


def test_presets_cover_curves_and_eurocodes():
    labels = list(mp.PRESTRESS_PRESETS)
    for i in range(1, 8):
        assert any(("Curve %d" % i) in lab for lab in labels)
    for code_label in codes.CODES:
        assert code_label in labels


def test_every_preset_builds_a_tension_only_tendon():
    for p in mp.PRESTRESS_PRESETS.values():
        t = mp.build_prestress(**p)
        assert isinstance(t, Prestress)
        assert t.stress(-0.01, design=True) == 0.0      # no compression
        assert t.stress(0.01, design=True) > 0.0        # carries tension


def test_fields_metadata_is_consistent():
    for fields in mp.PRESTRESS_FIELDS_BY_CURVE.values():
        for f in fields:
            assert f in mp.PRESTRESS_FIELD_META


def test_eurocode_presets_apply_a_partial_factor():
    for label in codes.CODES:
        p = mp.PRESTRESS_PRESETS[label]
        assert p["gamma_y"] >= 1.15


def test_diagram_markers_label_the_ultimate_point():
    t = mp.build_prestress(**mp.PRESTRESS_PRESETS["Curve 6 (bilinear)"])
    keys = [sk for (_a, _b, _ek, sk) in t.diagram_markers(design=True)]
    assert "fpud" in keys
