"""Adversarial Brief composition and governing-figure contracts for v0.96."""

from __future__ import annotations

import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import result_presentation as presentation
import sector_report

from tools import report_render_fixture


def _brief_builder(*, figures: bool):
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    out["worked_example_selection"] = presentation.worked_example_selection(
        inp, out
    )
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, inp, out, figures=figures, profile="Brief"
    )


def test_brief_requests_only_selected_plastic_and_elastic_key_figures(monkeypatch):
    builder = _brief_builder(figures=True)
    built = []
    published = []

    monkeypatch.setattr(
        sector_report.viz,
        "interaction_figure",
        lambda *args, **kwargs: built.append(("plastic", args, kwargs)) or "PL-FIG",
    )
    monkeypatch.setattr(
        sector_report.viz,
        "elastic_strain_figure",
        lambda *args, **kwargs: built.append(("elastic", args, kwargs)) or "EL-FIG",
    )
    monkeypatch.setattr(
        builder,
        "_fig",
        lambda figure, *args, **kwargs: published.append((figure, args, kwargs)),
    )

    builder._brief_key_figures()

    assert [kind for kind, _args, _kwargs in built] == ["plastic", "elastic"]
    assert [item[0] for item in published] == ["PL-FIG", "EL-FIG"]
    captions = [item[2]["caption"] for item in published]
    assert captions[0].startswith("Governing Plastic result - ")
    assert captions[1].startswith("Governing Elastic result - ")


def test_brief_key_figures_are_disabled_or_fail_closed_without_selection(monkeypatch):
    calls = []
    for figures in (False, True):
        builder = _brief_builder(figures=figures)
        if figures:
            builder._selected_families = {}
        monkeypatch.setattr(
            builder,
            "_fig",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        builder._brief_key_figures()

    assert calls == []


def test_brief_key_figures_do_not_request_secondary_or_input_plots(monkeypatch):
    builder = _brief_builder(figures=True)
    forbidden = (
        "section_figure",
        "concrete_curve_figure",
        "steel_curve_figure",
        "prestress_curve_figure",
        "interaction_nm_figure",
        "detailing_geometry_figure",
        "shear_geometry_figure",
        "biaxial_shear_overview_figure",
        "vt_interaction_figure",
        "tube_figure",
        "subtube_figure",
        "truss_figure",
        "fatigue_utilisation_map_figure",
        "fatigue_sn_figure",
        "fatigue_damage_figure",
    )

    def unexpected(name):
        def fail(*_args, **_kwargs):
            raise AssertionError(f"Brief requested forbidden figure builder {name}")

        return fail

    for name in forbidden:
        monkeypatch.setattr(sector_report.viz, name, unexpected(name))
    monkeypatch.setattr(sector_report.viz, "interaction_figure", lambda *a, **k: "P")
    monkeypatch.setattr(
        sector_report.viz, "elastic_strain_figure", lambda *a, **k: "E"
    )
    monkeypatch.setattr(builder, "_fig", lambda *_args, **_kwargs: None)

    builder._brief_key_figures()
