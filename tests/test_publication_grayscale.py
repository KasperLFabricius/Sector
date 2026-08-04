"""Independent F-041 grayscale-publication contract."""

from __future__ import annotations

import base64
import io
import pathlib
import sys

import plotly.graph_objects as go
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual
import sector_report
import viz


PUBLIC_FACTORIES = (
    "elastic_strain_figure",
    "concrete_curve_figure",
    "prestress_curve_figure",
    "steel_curve_figure",
    "section_figure",
    "fatigue_utilisation_map_figure",
    "fatigue_sn_figure",
    "fatigue_damage_figure",
    "detailing_geometry_figure",
    "shear_geometry_figure",
    "biaxial_shear_overview_figure",
    "interaction_figure",
    "interaction_nm_figure",
    "vt_interaction_figure",
    "tube_figure",
    "subtube_figure",
    "truss_figure",
)


def _line_adversary():
    figure = go.Figure()
    figure.add_scatter(
        x=[0, 1], y=[0, 1], mode="lines", name="default one",
        line=dict(color="#111111"),
    )
    figure.add_scatter(
        x=[0, 1], y=[1, 2], mode="lines", name="default two",
        line=dict(color="#222222"),
    )
    figure.add_scatter(
        x=[0, 1], y=[2, 3], mode="lines", name="authored dot",
        line=dict(color="#333333", dash="dot"),
    )
    figure.add_scatter(
        x=[0, 1], y=[3, 4], mode="lines", name="authored dash",
        line=dict(color="#444444", dash="dash"),
    )
    return figure


def _cue_map(figure):
    return dict(viz.grayscale_distinction_cues(figure))


def test_defaults_never_consume_later_authored_line_cues():
    figure = _line_adversary()
    before = [
        (tuple(trace.x), tuple(trace.y), trace.name, trace.line.color)
        for trace in figure.data
    ]

    viz.apply_grayscale_safe_distinctions(figure)
    cues = _cue_map(figure)

    assert figure.data[2].line.dash == "dot"
    assert figure.data[3].line.dash == "dash"
    assert figure.data[1].line.dash not in {"dot", "dash"}
    assert len(cues.values()) == len(set(cues.values()))
    assert [
        (tuple(trace.x), tuple(trace.y), trace.name, trace.line.color)
        for trace in figure.data
    ] == before
    first_pass = viz.grayscale_distinction_cues(figure)
    viz.apply_grayscale_safe_distinctions(figure)
    assert viz.grayscale_distinction_cues(figure) == first_pass


def test_marker_and_bar_fallbacks_reserve_authored_symbols_and_patterns():
    figure = go.Figure()
    figure.add_scatter(x=[0], y=[0], mode="markers", name="marker one")
    figure.add_scatter(x=[1], y=[1], mode="markers", name="marker two")
    figure.add_scatter(
        x=[2], y=[2], mode="markers", name="authored diamond",
        marker=dict(symbol="diamond"),
    )
    figure.add_bar(x=["a"], y=[1], name="bar one")
    figure.add_bar(x=["a"], y=[2], name="bar two")
    figure.add_bar(
        x=["a"], y=[3], name="authored slash",
        marker=dict(pattern=dict(shape="/")),
    )

    viz.apply_grayscale_safe_distinctions(figure)
    cues = [cue for _name, cue in viz.grayscale_distinction_cues(figure)]

    assert figure.data[2].marker.symbol == "diamond"
    assert figure.data[1].marker.symbol != "diamond"
    assert figure.data[5].marker.pattern.shape == "/"
    assert figure.data[4].marker.pattern.shape != "/"
    assert len(cues) == len(set(cues))


def test_duplicated_authored_primary_cue_is_retained_with_secondary_channel():
    figure = go.Figure()
    for name in ("first semantic", "second semantic"):
        figure.add_scatter(
            x=[0, 1], y=[0, 1], mode="lines", name=name,
            line=dict(dash="dot"),
        )

    viz.apply_grayscale_safe_distinctions(figure)

    assert [trace.line.dash for trace in figure.data] == ["dot", "dot"]
    assert figure.data[1].mode == "lines+markers"
    cues = [cue for _name, cue in viz.grayscale_distinction_cues(figure)]
    assert len(cues) == len(set(cues))


def test_array_markers_use_the_first_rendered_legend_glyph():
    figure = go.Figure()
    figure.add_scatter(
        x=[0], y=[0], mode="markers", name="array marker",
        marker=dict(symbol=["circle"], size=[9]),
    )
    figure.add_scatter(
        x=[1], y=[1], mode="markers", name="scalar marker",
        marker=dict(symbol="circle", size=9),
    )

    viz.apply_grayscale_safe_distinctions(figure)

    assert tuple(figure.data[0].marker.symbol) == ("circle",)
    assert tuple(figure.data[0].marker.size) == (9,)
    cues = [cue for _name, cue in viz.grayscale_distinction_cues(figure)]
    assert len(cues) == len(set(cues))


def test_omitted_scatter_mode_uses_plotly_point_count_default():
    figure = go.Figure()
    figure.add_scatter(x=[0, 1], y=[0, 1], name="implicit short")
    figure.add_scatter(
        x=[0, 1], y=[1, 2], mode="lines+markers", name="explicit short",
    )

    viz.apply_grayscale_safe_distinctions(figure)

    assert figure.data[0].mode is None
    assert figure.data[1].line.dash != "solid"
    cues = [cue for _name, cue in viz.grayscale_distinction_cues(figure)]
    assert len(cues) == len(set(cues))

    long_trace = go.Figure(
        [go.Scatter(x=list(range(20)), y=list(range(20)), name="implicit long")]
    )
    long_cue = viz.grayscale_distinction_cues(long_trace)[0][1]
    assert long_cue[1] is True
    assert long_cue[4] is False

    mismatched = go.Figure(
        [go.Scatter(x=[0, 1], y=list(range(20)), name="implicit clipped")]
    )
    mismatched_cue = viz.grayscale_distinction_cues(mismatched)[0][1]
    assert mismatched_cue[1] is True
    assert mismatched_cue[4] is True


def test_every_public_factory_is_finalized_and_non_plotly_values_are_inert():
    assert all(
        getattr(getattr(viz, name), "_sector_grayscale_safe", False)
        for name in PUBLIC_FACTORIES
    )
    sentinel = object()
    assert viz.apply_grayscale_safe_distinctions(sentinel) is sentinel


def test_unsupported_duplicate_legend_type_fails_instead_of_using_colour_only():
    figure = go.Figure()
    figure.add_pie(labels=["a"], values=[1], name="pie one")
    figure.add_pie(labels=["a"], values=[1], name="pie two")

    with pytest.raises(viz.GrayscalePublicationError, match="duplicate"):
        viz.apply_grayscale_safe_distinctions(figure)


def test_manual_export_boundary_finalizes_direct_manual_figure(monkeypatch):
    figure = _line_adversary()
    captured = {}

    def fake_write_image(self, target, **_kwargs):
        captured["cues"] = viz.grayscale_distinction_cues(self)
        target.write(b"png")

    monkeypatch.setattr(go.Figure, "write_image", fake_write_image)

    assert manual._fig_to_png(lambda: figure, timeout=5) == b"png"
    cues = [cue for _name, cue in captured["cues"]]
    assert len(cues) == len(set(cues))
    assert figure.data[2].line.dash == "dot"
    assert figure.data[3].line.dash == "dash"


def test_report_export_boundary_finalizes_direct_caller_figure(monkeypatch):
    figure = _line_adversary()
    captured = {}
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "/x8AAusB9Wl2nGQAAAAASUVORK5CYII="
    )

    def fake_export(value, *_args):
        captured["cues"] = viz.grayscale_distinction_cues(value)
        return png, False

    monkeypatch.setattr(sector_report, "_fig_png", fake_export)
    builder = sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=True, qa_appendix=False
    )
    builder._h1("Capacity")
    builder._fig(figure, 50, 40)

    cues = [cue for _name, cue in captured["cues"]]
    assert len(cues) == len(set(cues))
    assert figure.data[2].line.dash == "dot"
    assert figure.data[3].line.dash == "dash"
