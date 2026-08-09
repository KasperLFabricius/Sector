"""Shared modelled-reinforcement direction and alias contract."""

from __future__ import annotations

import pytest

from app import modelled_direction
from sector import detailing


@pytest.mark.parametrize(
    ("cut", "expected"),
    [
        (detailing.CUT_TRANSVERSE, modelled_direction.LONGITUDINAL),
        (detailing.CUT_LONGITUDINAL, modelled_direction.TRANSVERSE),
        (None, modelled_direction.LONGITUDINAL),
    ],
)
def test_direction_from_cut_is_member_relative(cut, expected):
    assert modelled_direction.direction_from_cut(cut) == expected


def test_retained_result_direction_takes_precedence_over_live_cut():
    result = {"modelled_reinforcement_direction": " transverse "}

    assert modelled_direction.canonical_direction(
        result,
        cut_direction=detailing.CUT_TRANSVERSE,
    ) == modelled_direction.TRANSVERSE


@pytest.mark.parametrize(
    ("result", "cut"),
    [
        ({"modelled_reinforcement_direction": "diagonal"}, None),
        (None, "Diagonal cut"),
    ],
)
def test_unsupported_direction_never_reaches_presentation(result, cut):
    with pytest.raises(ValueError):
        modelled_direction.canonical_direction(result, cut_direction=cut)


def test_alias_is_optional_single_line_and_canonical_direction_stays_first():
    assert modelled_direction.normalise_alias(None) == ""
    assert modelled_direction.normalise_alias("  span   direction  ") == (
        "span direction"
    )
    assert modelled_direction.resolved_label(
        {"modelled_reinforcement_direction": "longitudinal"},
        cut_direction=detailing.CUT_LONGITUDINAL,
        alias="span direction",
    ) == "Longitudinal (project alias: span direction)"


def test_html_label_escapes_user_alias_without_hiding_canonical_direction():
    assert modelled_direction.resolved_html_label(
        {"modelled_reinforcement_direction": "longitudinal"},
        alias="<span & grid>",
    ) == (
        "Longitudinal (project alias: &lt;span &amp; grid&gt;)"
    )


def test_markdown_label_renders_directives_links_and_emphasis_as_literal_text():
    assert modelled_direction.resolved_markdown_label(
        {"modelled_reinforcement_direction": "longitudinal"},
        alias=":red[span] [deck](https://example.test) **critical**",
    ) == (
        "Longitudinal (project alias: "
        r"\:red\[span\] \[deck\]\(https\:\/\/example\.test\) "
        r"\*\*critical\*\*)"
    )


@pytest.mark.parametrize("value", ["span\ndirection", "span\u2028direction", 12])
def test_alias_rejects_multiline_or_nontext_values(value):
    with pytest.raises(ValueError):
        modelled_direction.normalise_alias(value)
