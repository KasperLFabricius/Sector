from app import workflow_navigation as nav


def test_all_input_pages_have_unique_routes_and_legacy_authorities():
    assert len({p.key for p in nav.PAGES}) == 8
    assert {p.stage for p in nav.PAGES if p.stage} == {
        "Section", "Material parameters", "Loads", "Analysis settings", "Project"
    }
    assert nav.legacy_destination("Analysis") == "results"
    assert nav.legacy_destination("Inputs", "Loads") == "actions"


def test_reading_context_preserves_inputs_and_result_identity():
    inp = {"signature": "a", "N": -123.456789}
    state = {"results": {"value": 0.0}, "result_sig": "a"}
    assert nav.context_status(inp, state, pending=False)[0] == "Results current"
    assert nav.context_status(inp, state, pending=True)[0] == "Input edit pending"
    assert nav.context_status(inp, state, pending=False, contract_current=False)[0] == "Recalculation required"
    assert inp == {"signature": "a", "N": -123.456789}
    assert state == {"results": {"value": 0.0}, "result_sig": "a"}


def test_calculate_is_explicit_one_shot_and_project_bound():
    for pending, generation, signature in [(True, 1, "a"), (False, 2, "a"), (False, 1, "b")]:
        state = {"_workflow_calculate_request": {"signature": "a", "generation": 1}}
        assert not nav.take_calculate_request(state, {"signature": signature}, pending=pending, generation=generation)
        assert "_workflow_calculate_request" not in state
    state = {"_workflow_calculate_request": {"signature": "a", "generation": 1}}
    assert nav.take_calculate_request(state, {"signature": "a"}, pending=False, generation=1)
    assert not nav.take_calculate_request(state, {"signature": "a"}, pending=False, generation=1)
