"""Adversarial closure tests for CT-010a reinforcement fatigue traces."""

from __future__ import annotations

import dataclasses
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
from test_fatigue_analysis import _base  # noqa: E402
from sector.calculation_trace import (  # noqa: E402
    RESULT_FAILED,
    TraceValidationError,
    bundle_from_json,
    bundle_to_json,
    seal_bundle,
)
from sector.fatigue_trace import (  # noqa: E402
    _damage_from_log,
    build_fatigue_trace_family,
    validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (  # noqa: E402
    DOC_2023,
    expected_registry,
    trace_shape,
)
from sector.fatigue_trace_reader import read_fatigue_evidence  # noqa: E402
from sector.trace_registry import audit_trace_registry  # noqa: E402


INPUT_HASH = "1" * 64
RESULT_HASH = "2" * 64


def _reinforcement_output(inp):
    """Use the retained adapter while keeping CT-010b's search out of this test."""

    def engine(section, spectra, nl, ns, **kwargs):
        kwargs["concrete"] = None
        kwargs["check_concrete"] = False
        return fatigue_analysis.analyse_grouped_spectra(
            section, spectra, nl, ns, **kwargs
        )

    return fatigue_analysis.run_analysis(inp, engine=engine)


def _build(inp=None, out=None):
    inp = _base() if inp is None else inp
    out = _reinforcement_output(inp) if out is None else out
    bundle = build_fatigue_trace_family(
        inp,
        out,
        input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH,
        context={"case": "FAT-ULS", "row": 3},
    )
    return inp, out, bundle


@pytest.fixture(scope="module")
def baseline():
    return _build()


def _steps(calculation):
    return {step.step_id: step for step in calculation.steps}


def _reaches(calculation, dependency_id):
    steps = _steps(calculation)
    reachable = {calculation.final_step_id}
    pending = [calculation.final_step_id]
    while pending:
        current = pending.pop()
        for dependency in steps[current].dependencies:
            if dependency.step_id not in reachable:
                reachable.add(dependency.step_id)
                pending.append(dependency.step_id)
    return dependency_id in reachable


def test_build_validate_and_json_round_trip(baseline):
    inp, out, bundle = baseline
    loaded = bundle_from_json(bundle_to_json(bundle))
    assert validate_fatigue_trace_family(
        loaded,
        inp,
        out,
        input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH,
        context={"case": "FAT-ULS", "row": 3},
    ) == bundle


def test_registry_is_exact_for_every_dynamic_member(baseline):
    inp, out, bundle = baseline
    shape = trace_shape(read_fatigue_evidence(
        inp, out, {"case": "FAT-ULS", "row": 3}
    ))
    assert audit_trace_registry(bundle, expected_registry(shape)) == bundle
    assert len(bundle.calculations) == 3


def test_geometry_material_and_gamma_c_reach_every_final(baseline):
    _inp, _out, bundle = baseline
    for calculation in bundle.calculations:
        assert _reaches(calculation, "geometry-material-spectrum-vector")
        assert _reaches(calculation, "input-gamma-c")


def test_bin_description_changes_the_sealed_trace():
    first = _base()
    _inp, _out, first_bundle = _build(first)
    second = _base()
    table = second[fatigue_inputs.SPECTRUM_TABLE_KEY].copy()
    table.loc[0, fatigue_inputs.DESCRIPTION] = "Changed published description"
    second[fatigue_inputs.SPECTRUM_TABLE_KEY] = table
    _inp, _out, second_bundle = _build(second)
    assert first_bundle.content_sha256 != second_bundle.content_sha256


def test_same_law_different_mild_material_id_changes_identity():
    first = _base(concrete_material_id="C1")
    _inp, _out, first_bundle = _build(first)
    second = _base(concrete_material_id="C1")
    catalog = second["mild_material_catalog"]
    catalog["items"][0]["id"] = "M2"
    catalog["next_id"] = 3
    second["bar_elements"][0]["material_id"] = "M2"
    _inp, _out, second_bundle = _build(second)
    assert first_bundle.content_sha256 != second_bundle.content_sha256
    assert any("u4d32" in step.step_id for calculation in second_bundle.calculations
               for step in calculation.steps)


def test_same_law_different_concrete_id_changes_identity():
    _inp, _out, first = _build(_base(concrete_material_id="C1"))
    _inp, _out, second = _build(_base(concrete_material_id="C2"))
    assert first.content_sha256 != second.content_sha256


@pytest.mark.parametrize("key", ["concrete_method", "concrete_parameters"])
def test_excluded_concrete_sibling_rejects_incompatible_list(key, baseline):
    inp, out, _bundle = baseline
    damaged = dict(out)
    damaged[key] = []
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp,
            damaged,
            input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH,
        )


def test_excluded_concrete_values_remain_outside_ct010a(baseline):
    inp, out, _bundle = baseline
    changed = dict(out)
    changed["concrete_method"] = "future-ct010b-method"
    parameters = dict(changed["concrete_parameters"])
    parameters["c"] = parameters["c"] + 1.0
    changed["concrete_parameters"] = parameters
    build_fatigue_trace_family(
        inp,
        changed,
        input_sha256=INPUT_HASH,
        result_sha256=RESULT_HASH,
    )


def test_combined_convergence_tamper_is_rejected(baseline):
    inp, out, _bundle = baseline
    spectrum = out["spectra"][0]
    state = dataclasses.replace(spectrum.bins[0], converged=False)
    changed_spectrum = dataclasses.replace(
        spectrum, bins=(state, *spectrum.bins[1:])
    )
    changed = dict(out, spectra=(changed_spectrum, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="authoritative replay"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_equivalent_area_only_failure_is_retained(monkeypatch):
    inp = _base(fatigue_check_concrete=False)
    import sector.fatigue as fatigue

    original = fatigue.solve_fatigue_bin
    original_tendon_area = sum(item.area for item in inp["section"].tendons)

    def solve(section, *args, **kwargs):
        result = original(section, *args, **kwargs)
        area = sum(item.area for item in section.tendons)
        if area != pytest.approx(original_tendon_area):
            return dataclasses.replace(result, converged=False)
        return result

    monkeypatch.setattr(fatigue, "solve_fatigue_bin", solve)
    out = fatigue_analysis.run_analysis(inp)
    assert out["spectra"][0].bins[0].elastic_result.converged is True
    assert out["spectra"][0].bins[0].converged is False
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    assert all(
        next(step for step in calculation.steps
             if step.step_id == calculation.final_step_id).result.state
        == RESULT_FAILED
        for calculation in bundle.calculations
    )


def test_log_domain_damage_survives_life_underflow():
    damage = _damage_from_log(1.0e300, -300.0)
    assert damage == float("inf")
    assert _damage_from_log(1.0e-300, 300.0) == 0.0


def test_reinforcement_state_tuple_type_is_exact(baseline):
    inp, out, _bundle = baseline
    spectrum = out["spectra"][0]
    state = dataclasses.replace(
        spectrum.bins[0],
        bar_stress_long_mpa=list(spectrum.bins[0].bar_stress_long_mpa),
    )
    changed = dict(out, spectra=(
        dataclasses.replace(spectrum, bins=(state, *spectrum.bins[1:])),
        *out["spectra"][1:],
    ))
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_reinforcement_damage_tamper_is_rejected(baseline):
    inp, out, _bundle = baseline
    spectrum = out["spectra"][0]
    element = dataclasses.replace(
        spectrum.reinforcement[0],
        damage=spectrum.reinforcement[0].damage + 0.01,
    )
    changed_spectrum = dataclasses.replace(
        spectrum,
        reinforcement=(element, *spectrum.reinforcement[1:]),
    )
    changed = dict(out, spectra=(changed_spectrum, *out["spectra"][1:]))
    with pytest.raises(TraceValidationError, match="authoritative replay"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_noncanonical_catalog_inventory_is_rejected():
    inp = _base()
    catalog = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
    catalog["unexpected"] = "hidden"
    out = _reinforcement_output(inp)
    with pytest.raises(TraceValidationError, match="inventory/order"):
        build_fatigue_trace_family(
            inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_unused_catalog_entry_is_part_of_identity():
    first = _base()
    _inp, _out, first_bundle = _build(first)
    second = _base()
    catalog = second[fatigue_inputs.DETAIL_CATALOG_KEY]
    catalog, new_id = fatigue_inputs.add_entry(
        catalog, preset=fatigue_inputs.PRESET_2023_BARS
    )
    item = next(row for row in catalog["items"] if row["id"] == new_id)
    item["description"] = "Unused but retained detail identity"
    second[fatigue_inputs.DETAIL_CATALOG_KEY] = catalog
    _inp, _out, second_bundle = _build(second)
    assert first_bundle.content_sha256 != second_bundle.content_sha256


def test_candidate_step_value_tamper_fails_even_when_resealed(baseline):
    inp, out, bundle = baseline
    calculation = bundle.calculations[0]
    final_index = next(
        index for index, step in enumerate(calculation.steps)
        if step.step_id == calculation.final_step_id
    )
    final = calculation.steps[final_index]
    changed_final = dataclasses.replace(
        final,
        substituted_expression=final.substituted_expression + " tampered",
    )
    steps = list(calculation.steps)
    steps[final_index] = changed_final
    changed_calculation = dataclasses.replace(calculation, steps=tuple(steps))
    changed_bundle = seal_bundle(dataclasses.replace(
        bundle,
        calculations=(changed_calculation, *bundle.calculations[1:]),
        content_sha256="",
    ))
    with pytest.raises(TraceValidationError, match="independently reconstructed"):
        validate_fatigue_trace_family(
            changed_bundle,
            inp,
            out,
            input_sha256=INPUT_HASH,
            result_sha256=RESULT_HASH,
            context={"case": "FAT-ULS", "row": 3},
        )


def test_stale_hashes_are_rejected(baseline):
    inp, out, bundle = baseline
    with pytest.raises(TraceValidationError, match="input fingerprint"):
        validate_fatigue_trace_family(
            bundle,
            inp,
            out,
            input_sha256="3" * 64,
            result_sha256=RESULT_HASH,
        )


def test_standard_steps_use_2023_not_2005_citations(baseline):
    _inp, _out, bundle = baseline
    sources = {
        step.source
        for calculation in bundle.calculations
        for step in calculation.steps
    }
    standard_sources = [source for source in sources if source.edition]
    assert standard_sources
    assert all(source.edition == DOC_2023 for source in standard_sources)


def test_import_does_not_pull_crack_trace_modules():
    assert "sector.crack_trace" not in sys.modules
    assert "sector.crack_trace_contract" not in sys.modules


def test_invalid_branch_is_failure_only():
    inp = _base()
    inp["fatigue_gamma_s"] = "bad"
    out = fatigue_analysis.invalid_result(inp)
    bundle = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
    )
    assert len(bundle.calculations) == 1
    final = _steps(bundle.calculations[0])[bundle.calculations[0].final_step_id]
    assert final.result.state == RESULT_FAILED
    assert final.result.value is None


def test_missing_element_result_fails_closed(baseline):
    inp, out, _bundle = baseline
    spectrum = out["spectra"][0]
    changed = dict(out, spectra=(
        dataclasses.replace(spectrum, reinforcement=spectrum.reinforcement[:-1]),
        *out["spectra"][1:],
    ))
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_reordered_spectra_fail_closed(baseline):
    inp, out, _bundle = baseline
    changed = dict(out, spectra=tuple(reversed(out["spectra"])))
    with pytest.raises(TraceValidationError):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_exact_boolean_output_types_are_pinned(baseline):
    inp, out, _bundle = baseline
    changed = dict(out, passed=1)
    with pytest.raises(TraceValidationError, match="retained type"):
        build_fatigue_trace_family(
            inp, changed, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )


def test_numeric_boolean_input_is_not_laundered():
    inp = _base(fatigue_gamma_s=True)
    out = _reinforcement_output(inp)
    with pytest.raises(TraceValidationError, match="non-Boolean"):
        build_fatigue_trace_family(
            inp, out, input_sha256=INPUT_HASH, result_sha256=RESULT_HASH
        )
