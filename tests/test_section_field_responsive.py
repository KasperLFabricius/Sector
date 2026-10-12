"""Fixed-margin figure scales remain visible when the UI stretches the canvas."""
import pytest
from app import section_fields as fields
from test_section_fields import native_case


@pytest.mark.parametrize("quantity", ["stress", "strain"])
def test_scales_and_legend_use_width_independent_placement(quantity):
    inp, result, _, _ = native_case()
    field = fields.build_field(inp, result, family="Elastic")
    figure = fields.section_field_figure(field, quantity)
    for axis, offset in ((figure.layout.coloraxis, 10), (figure.layout.coloraxis2, 115)):
        assert axis.colorbar.x == 1.0
        assert axis.colorbar.xanchor == "left"
        assert axis.colorbar.xpad == offset
        assert axis.colorbar.thickness == 14
    assert figure.layout.legend.orientation == "v"
    assert figure.layout.legend.xanchor == "left"
    assert figure.layout.legend.yanchor == "top"
    assert figure.layout.legend.x == 1.0
    assert figure.layout.legend.y == .12
    assert figure.layout.margin.r == 225
    assert figure.layout.yaxis.scaleanchor == "x"
    assert figure.layout.yaxis.scaleratio == 1


@pytest.mark.parametrize("width", [600, 760, 1110, 1600])
def test_fixed_pixel_scales_fit_reserved_margin_at_supported_widths(width):
    inp, result, _, _ = native_case()
    field = fields.build_field(inp, result, family="Elastic")
    figure = fields.section_field_figure(field, "stress")
    figure.update_layout(width=width)
    # The quantitative bar starts at the paper right edge plus its pixel pad.
    paper_right = width - figure.layout.margin.r
    left = paper_right + figure.layout.coloraxis.colorbar.xpad
    right = paper_right + figure.layout.coloraxis2.colorbar.xpad
    assert right - left == 105
    assert right + 14 + 80 <= width  # bar and the longest reviewed label/tick extent
    assert paper_right + 210 <= width  # complete reviewed legend label width
