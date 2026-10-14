"""Keep Results navigation exits inside their instrumented owner."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"


def _functions():
    return {
        node.name: node
        for node in ast.parse(APP.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }


def _call(node, name):
    return isinstance(node, ast.Call) and ast.unparse(node.func) == name


def test_results_navigation_helpers_cannot_bypass_owner_exit():
    functions = _functions()
    pending = ["results_overview_view"]
    checked = set()
    while pending:
        name = pending.pop()
        if name in checked:
            continue
        checked.add(name)
        for node in ast.walk(functions[name]):
            assert not _call(node, "st.rerun"), (name, node.lineno)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in functions
            ):
                pending.append(node.func.id)
    assert "_review_overview_inputs" in checked


def test_both_results_navigation_actions_return_the_owner_request():
    overview = _functions()["results_overview_view"]
    actions = {}
    for node in ast.walk(overview):
        if not isinstance(node, ast.If) or not _call(node.test, "st.button"):
            continue
        keys = [keyword.value.value for keyword in node.test.keywords
                if keyword.arg == "key" and isinstance(keyword.value, ast.Constant)]
        if keys and keys[0] in {"overview_related_inputs", "overview_status_help"}:
            actions[keys[0]] = node
    assert set(actions) == {"overview_related_inputs", "overview_status_help"}
    for action in actions.values():
        assert isinstance(action.body[-1], ast.Return)
        assert isinstance(action.body[-1].value, ast.Constant)
        assert action.body[-1].value.value is True


def test_analysis_owner_closes_before_requested_navigation_rerun():
    owner = _functions()["_analysis_workspace"]
    routes = [node for node in ast.walk(owner)
              if isinstance(node, ast.If) and _call(node.test, "results_overview_view")]
    assert len(routes) == 1
    route = routes[0]
    assert len(route.body) == 2
    assert isinstance(route.body[0], ast.Expr)
    assert _call(route.body[0].value, "app_run_probe.close_fragment_run")
    assert isinstance(route.body[1], ast.Expr)
    assert _call(route.body[1].value, "st.rerun")
    assert [(keyword.arg, ast.literal_eval(keyword.value))
            for keyword in route.body[1].value.keywords] == [("scope", "app")]
