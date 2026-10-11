"""Numerical and asset checks for the reproducible manual walkthroughs."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import manual
import manual_assets
from manual_walkthroughs import beam_example


def test_rectangular_hand_calculation_reproduces_native_elastic_state():
    values = beam_example()
    hand, result = values["hand"], values["elastic"]
    assert result.converged
    assert hand["x"] == pytest.approx(149.25054281121734, abs=1e-9)
    assert 300 - result.na_y_intercept * 1000 == pytest.approx(hand["x"], abs=1e-8)
    assert result.bar_stress[0] / 1000 == pytest.approx(hand["bottom_stress"], abs=1e-8)
    assert result.bar_stress[-1] / 1000 == pytest.approx(hand["top_stress"], abs=1e-8)
    assert result.max_concrete_compression / 1000 == pytest.approx(
        hand["concrete_stress"], abs=1e-8
    )


def test_individual_midpoint_bands_reproduce_native_force_and_moment():
    values = beam_example()
    result = values["plastic"]
    concrete = values["bands"] + (values["plateau"],)
    assert result.converged
    assert len(values["bands"]) == 80
    assert sum(row[3] for row in concrete) == pytest.approx(
        result.concrete_force, abs=1e-7
    )
    assert sum(row[4] for row in concrete) == pytest.approx(
        result.concrete_mx, abs=1e-7
    )
    force = sum(row[3] for row in concrete) + sum(s.force for s in result.bar_states)
    moment = sum(row[4] for row in concrete) + sum(s.mx for s in result.bar_states)
    assert abs(force) < 1e-6
    assert moment == pytest.approx(345.97660151589446, abs=1e-6)


def test_duration_example_preserves_component_identities():
    result = beam_example()["combined"]
    assert result.converged
    assert result.long_term_reduction_factor == pytest.approx(2 / 3)
    assert np.allclose(
        result.bar_stress_total, result.bar_stress_reduced_long + result.bar_stress_rst1
    )
    assert np.allclose(
        result.bar_stress_dif, result.bar_stress_total - result.bar_stress_long
    )
    assert result.bar_stress_total[0] > result.bar_stress_long[0] > 0


def test_band_refinement_is_explicit_and_convergent_for_the_named_beam():
    values = beam_example()["refinement"]
    assert tuple(n for n, _ in values) == (20, 40, 80, 160)
    differences = np.abs(np.diff([m for _, m in values]))
    assert np.all(differences[1:] < differences[:-1])
    assert differences[-1] < 0.001


def test_offline_figures_match_the_live_factories_and_png_checksums():
    manifest = json.loads((manual_assets.ASSET_ROOT / "manifest.json").read_text())
    assert manifest["version"] == manual.APP_VERSION
    factories = {
        b[1].__name__: b[1] for b in manual.manual_blocks() if b[0] == "figure"
    }
    assert set(factories) == set(manifest["figures"])
    for name, factory in factories.items():
        digest = hashlib.sha256(factory().to_json().encode("utf-8")).hexdigest()
        assert digest == manifest["figures"][name]["figure_sha256"], name
        assert manual_assets.figure_data_uri(factory).startswith(
            "data:image/png;base64,"
        )


def test_native_cracked_figure_publication_precision_is_bounded_and_stable(monkeypatch):
    import copy

    native_section_figure = manual.viz.section_figure
    unrounded = []
    perturb = False

    def capture_native_geometry(*args, **kwargs):
        figure = native_section_figure(*args, **kwargs)
        unrounded.append(copy.deepcopy(figure))
        if perturb:
            for trace in figure.data:
                for axis in ("x", "y"):
                    values = getattr(trace, axis, None)
                    if values is not None:
                        trace.update({axis: [float(np.nextafter(value, -np.inf))
                                             if value is not None else None for value in values]})
        return figure

    monkeypatch.setattr(manual.viz, "section_figure", capture_native_geometry)
    published = manual.fig_beam_cracked()
    perturb = True
    assert manual.fig_beam_cracked().to_json() == published.to_json()
    # Compare every plotted coordinate with its unrounded native counterpart.
    for actual, native in zip(published.data, unrounded[0].data, strict=True):
        for axis in ("x", "y"):
            coordinates = getattr(actual, axis, None)
            if coordinates is not None:
                for value, raw in zip(coordinates, getattr(native, axis), strict=True):
                    if raw is None:
                        assert value is None
                    else:
                        assert abs(value - raw) <= 5e-10
                        if value == 0:
                            assert not np.signbit(value)


def test_damaged_offline_image_cannot_be_published(tmp_path, monkeypatch):
    name = "fig_beam_section"
    (tmp_path / (name + ".png")).write_bytes(b"\x89PNG\r\n\x1a\nchanged")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"figures": {name: {"png_sha256": "0" * 64}}})
    )
    monkeypatch.setattr(manual_assets, "ASSET_ROOT", tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        manual_assets.figure_data_uri(manual.fig_beam_section)
