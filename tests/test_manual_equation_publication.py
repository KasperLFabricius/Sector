"""Independent contract and surface tests for PR-11A3b manual publication."""

from __future__ import annotations

from dataclasses import replace
import io
import pathlib
import re
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import manual  # noqa: E402
import manual_equation_contract as contract  # noqa: E402
import manual_equation_location as location  # noqa: E402
import manual_equation_publication as publication  # noqa: E402


def _published():
    return publication.manual_publication_blocks(manual.manual_blocks())


def _equations():
    return tuple(
        block[1]
        for block in _published()
        if block[0] == publication.EQUATION_BLOCK
    )


def _part_c_non_display_text(blocks) -> str:
    part = ""
    retained = []
    for block in blocks:
        if block[0] == "part":
            part = block[1]
        if part != location.PART_C or block[0] != "md":
            continue
        fragments = block[1].split(location.DISPLAY_DELIMITER)
        retained.extend(fragments[::2])
    return "".join(retained)


def test_publication_spine_is_exact_complete_and_immutable():
    published = _published()
    equations = _equations()
    assert type(published) is tuple
    assert len(equations) == 32
    assert all(type(item) is contract.ContractedManualEquation for item in equations)
    assert tuple(item.contract.number for item in equations) == tuple(
        item.number for item in contract.MANUAL_EQUATION_CONTRACTS
    )
    assert tuple(item.contract.key for item in equations) == tuple(
        item.key for item in contract.MANUAL_EQUATION_CONTRACTS
    )
    assert equations == publication.bind_manual_publication_equations(
        manual.manual_blocks()
    )


def test_segmentation_preserves_all_non_display_part_c_text_exactly():
    raw = manual.manual_blocks()
    published = _published()
    assert _part_c_non_display_text(raw) == _part_c_non_display_text(published)

    part = ""
    for block in published:
        if block[0] == "part":
            part = block[1]
        if part == location.PART_C and block[0] == "md":
            assert location.DISPLAY_DELIMITER not in block[1]


def test_non_part_c_blocks_remain_byte_for_byte_and_in_order():
    def outside_part_c(blocks):
        part = ""
        retained = []
        for block in blocks:
            if block[0] == "part":
                part = block[1]
            if part != location.PART_C:
                retained.append(block)
        return tuple(retained)

    assert outside_part_c(_published()) == outside_part_c(manual.manual_blocks())


@pytest.mark.parametrize("mutation", ["missing", "extra", "changed", "reordered"])
def test_segmentation_fails_closed_for_hostile_display_streams(mutation):
    blocks = list(manual.manual_blocks())
    indices = [
        index
        for index, block in enumerate(blocks)
        if block[0] == "md" and "$$" in block[1]
    ]
    assert len(indices) >= 2
    first, second = indices[:2]
    if mutation == "missing":
        blocks[first] = ("md", blocks[first][1].replace("$$", "", 2))
    elif mutation == "extra":
        blocks[first] = ("md", blocks[first][1] + "\n\n$$x=1$$")
    elif mutation == "changed":
        blocks[first] = ("md", blocks[first][1].replace("f_{cd}", "f_{ck}", 1))
    else:
        blocks[first], blocks[second] = blocks[second], blocks[first]
    with pytest.raises(ValueError):
        publication.manual_publication_blocks(blocks)


def test_dependency_numbers_are_exact_and_reject_resealed_catalogues():
    equations = _equations()
    number_by_key = {
        item.key: item.number for item in contract.MANUAL_EQUATION_CONTRACTS
    }
    expected_by_key = {
        item.key: tuple(number_by_key[key] for key in item.uses)
        for item in contract.MANUAL_EQUATION_CONTRACTS
    }
    for equation in equations:
        assert publication.dependency_numbers(equation) == expected_by_key[
            equation.contract.key
        ]

    changed = list(contract.MANUAL_EQUATION_CONTRACTS)
    changed[0] = replace(changed[0], dimensional_class="changed class")
    with pytest.raises(ValueError):
        publication.dependency_numbers(equations[0], tuple(changed))
    with pytest.raises(ValueError):
        publication.dependency_numbers("C3-1")


def test_renderer_helpers_reject_coherently_changed_payload_chains():
    original = _equations()[0]
    sourced = original.equation
    located = sourced.equation
    changed_payloads = (
        replace(
            original,
            contract=replace(original.contract, dimensional_class="changed class"),
        ),
        replace(
            original,
            equation=replace(
                sourced,
                source=replace(sourced.source, source_text="changed source"),
            ),
        ),
        replace(
            original,
            equation=replace(
                sourced,
                equation=replace(
                    located,
                    location=replace(located.location, key="manual.changed"),
                ),
            ),
        ),
        replace(
            original,
            equation=replace(
                sourced,
                equation=replace(located, expression=located.expression + "+0"),
            ),
        ),
    )
    for payload in changed_payloads:
        with pytest.raises(ValueError):
            publication.dependency_numbers(payload)
        with pytest.raises(ValueError):
            publication.source_kind_label(payload)


def test_every_advertised_semantic_field_reaches_streamlit_markup():
    for equation in _equations():
        result_markup = manual._manual_equation_results_markdown(equation)
        symbol_markup = manual._manual_equation_symbols_markdown(equation)
        dependency_markup = manual._manual_equation_dependencies_markdown(equation)
        for result in equation.contract.results:
            assert result.markup in result_markup
            assert result.meaning in result_markup
            assert result.unit in result_markup
        for symbol in equation.contract.symbols:
            assert symbol.markup in symbol_markup
            assert symbol.meaning in symbol_markup
            assert symbol.unit in symbol_markup
        for number in publication.dependency_numbers(equation):
            assert f"Equation {number}" in dependency_markup
            assert f"#equation-{number.casefold()}" in dependency_markup


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _StreamlitRecorder:
    def __init__(self):
        self.markdowns = []
        self.captions = []
        self.expanders = []

    def markdown(self, value, **_kwargs):
        self.markdowns.append(value)

    def caption(self, value, **_kwargs):
        self.captions.append(value)

    def expander(self, label, *, expanded):
        self.expanders.append((label, expanded))
        return _Context()


def test_streamlit_equation_detail_is_complete_but_collapsed_on_demand(monkeypatch):
    recorder = _StreamlitRecorder()
    monkeypatch.setattr(manual, "st", recorder)
    for equation in _equations():
        manual._render_manual_equation_streamlit(equation)

    visible = "\n".join(recorder.markdowns)
    captions = "\n".join(recorder.captions)
    assert len(recorder.expanders) == 32
    assert all(expanded is False for _label, expanded in recorder.expanders)
    for equation in _equations():
        number = equation.contract.number
        assert f"##### Equation {number}" in visible
        assert equation.equation.equation.expression in visible
        assert f"Dimensional class: {equation.contract.dimensional_class}" in captions
        assert equation.equation.source.source_text in captions
        assert publication.source_kind_label(equation) in captions
        assert any(number in label for label, _expanded in recorder.expanders)


def test_pdf_publishes_every_number_source_meaning_and_dependency():
    import pypdf

    pdf = manual.build_manual_pdf_bytes(figures=False)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = re.sub(
        r"\s+",
        " ",
        "\n".join(page.extract_text() or "" for page in reader.pages),
    )
    assert pdf[:4] == b"%PDF"
    assert "$" not in text
    destination_links = [
        annotation.get_object()
        for page in reader.pages
        for annotation in (page.get("/Annots") or [])
        if annotation.get_object().get("/Subtype") == "/Link"
        and annotation.get_object().get("/Dest")
    ]
    assert len(destination_links) >= 21 + len(manual._PART_SUMMARIES)
    for equation in _equations():
        assert f"Equation {equation.contract.number}" in text
        assert equation.contract.dimensional_class in text
        assert equation.equation.source.source_text in text
        for term in equation.contract.symbols + equation.contract.results:
            assert term.meaning in text
        for number in publication.dependency_numbers(equation):
            assert f"Equation {number}" in text


def test_source_labels_are_complete_and_unknown_types_fail_closed():
    labels = {publication.source_kind_label(item) for item in _equations()}
    assert labels == {
        "Standard source",
        "Mixed source",
        "Project-defined method",
    }
    with pytest.raises(ValueError):
        publication.source_kind_label(object())
