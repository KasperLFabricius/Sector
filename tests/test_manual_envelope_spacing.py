"""Preserve manual envelope data while reserving separate title/sign space."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import manual  # noqa: E402


def test_manual_envelope_separates_title_and_sign_notes_without_scaling_data():
    figure = manual.fig_beam_envelope()
    example = manual.example_beam()
    points = manual.solve_plastic(
        manual._section_of(example), example["concrete"], example["steel"],
        example["P"], 0.0, 360.0, 15.0,
    )
    native = manual.viz.interaction_figure(
        [point.Mx for point in points], [point.My for point in points],
        applied=(example["Mx"], example["My"]),
    )
    manual._manual_native_plot(native, height=610)
    assert [trace.to_plotly_json() for trace in figure.data] == [
        trace.to_plotly_json() for trace in native.data
    ]
    # Keep the original data-area height and supply room above both sign lines.
    assert figure.layout.height - figure.layout.margin.t - figure.layout.margin.b == 425
    assert figure.layout.margin.t >= 120
    assert figure.layout.title.y == 0.98
    assert figure.layout.title.yanchor == "top"
    assert len(figure.layout.annotations) == len(native.layout.annotations)
    for actual, expected in zip(figure.layout.annotations, native.layout.annotations):
        assert actual.text == expected.text.replace("+Mx", "+M<sub>x</sub>").replace(
            "+My", "+M<sub>y</sub>"
        )
        for field in ("x", "y", "xref", "yref", "xanchor", "yanchor"):
            assert getattr(actual, field) == getattr(expected, field)
