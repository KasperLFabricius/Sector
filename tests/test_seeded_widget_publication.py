"""Pure native registration tests for retained/live seeded widget values."""

import ast
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace
from typing import cast

import pytest
import streamlit
import streamlit.runtime.state.session_state_proxy as proxy_module
from streamlit.proto.WidgetStates_pb2 import WidgetState, WidgetStates
from streamlit.runtime.state.common import WidgetMetadata
from streamlit.runtime.state.safe_session_state import SafeSessionState
from streamlit.runtime.state.session_state import SessionState

SOURCE = Path(__file__).parents[1] / "app/sector_app.py"
if not SOURCE.exists():
    SOURCE = Path(__file__).with_name("sector_app.py")
CASES = [
    (
        "_number",
        "number_input",
        ("conc", "fck", {"fck": ("Value", 1, 120, 1)}, {"fck": "Preserved input help"}),
        2,
        7,
        1,
        "int_value",
    ),
    ("_seeded_number", "number_input", ("Value", 1, 120, 2, 1), 2, 7, 1, "int_value"),
    ("_seeded_checkbox", "checkbox", ("Value", True), True, False, False, "bool_value"),
    ("_seeded_toggle", "toggle", ("Value", True), True, False, False, "bool_value"),
    (
        "_seeded_selectbox",
        "selectbox",
        ("Value", ["First", "Saved"], "Saved"),
        "Saved",
        "First",
        "First",
        "string_value",
    ),
    (
        "_seeded_segmented_control",
        "segmented_control",
        ("Value", ["First", "Saved"], "Saved"),
        "Saved",
        "First",
        None,
        "string_value",
    ),
    (
        "_seeded_text",
        "text_input",
        ("Value", "Saved text"),
        "Saved text",
        "User text",
        "",
        "string_value",
    ),
    (
        "_seeded_text_area",
        "text_area",
        ("Value", "Saved text"),
        "Saved text",
        "User text",
        "",
        "string_value",
    ),
]


def function(source, name, namespace):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    node.decorator_list = []
    code = next(
        c
        for c in compile(
            ast.Module(body=[node], type_ignores=[]), str(source), "exec"
        ).co_consts
        if isinstance(c, CodeType)
    )
    return FunctionType(code, namespace)


@pytest.mark.parametrize("name,method,args,retained,edited,intrinsic,wire_type", CASES)
@pytest.mark.parametrize("seed_kind", ["default", "saved_custom"])
@pytest.mark.parametrize(
    "stage",
    [
        "absent_initial_state",
        "old_session_first_mount",
        "registered_remount",
        "explicit_user_event",
    ],
)
def test_seeded_value_reaches_native_registration_without_losing_live_event(
    monkeypatch,
    name,
    method,
    args,
    retained,
    edited,
    intrinsic,
    wire_type,
    stage,
    seed_kind,
):
    if seed_kind == "saved_custom":
        retained, edited = edited, retained
    native = SessionState()
    key = "conc_fck" if name == "_number" else "retained"
    identity = "$$ID-exact-" + key
    callbacks = []
    callback = lambda: callbacks.append("called")
    metadata = WidgetMetadata(
        identity,
        deserializer=lambda value: intrinsic if value is None else value,
        serializer=lambda value: value,
        value_type=wire_type,
        callback=callback,
    )
    if stage != "absent_initial_state":
        native[key] = retained
    if stage in {"registered_remount", "explicit_user_event"}:
        native.register_widget(metadata, key)
    native._compact_state()
    if stage == "explicit_user_event":
        widget = WidgetState(id=identity)
        setattr(widget, wire_type, edited)
        native.on_script_will_rerun(WidgetStates(widgets=[widget]))
        assert callbacks == ["called"]
    safe = SafeSessionState(native, lambda: None)
    monkeypatch.setattr(proxy_module, "get_session_state", lambda: safe)
    observations = []

    class Box:
        def __getattr__(self, called):
            assert called == method

            def invoke(*a, **kw):
                assert (
                    kw["on_change"] is callback and kw["help"] == "Preserved input help"
                )
                result = native.register_widget(metadata, key)
                observations.append(result)
                return result.value

            return invoke

    f = function(
        SOURCE,
        name,
        {
            "st": SimpleNamespace(session_state=proxy_module.SessionStateProxy()),
            "_input_widget_kwargs": lambda key, kw, **_host: dict(kw, on_change=callback),
        },
    )
    expected = edited if stage == "explicit_user_event" else retained
    if stage == "absent_initial_state":
        expected = (
            intrinsic
            if name == "_number"
            else next(c[3] for c in CASES if c[0] == name)
        )
    actual = (
        f(Box(), *args, disabled=False)
        if name == "_number"
        else f(Box(), *args, key, on_change=callback, help="Preserved input help")
    )
    assert actual == expected
    assert observations[0].value == expected
    if stage == "absent_initial_state" and name == "_number":
        assert observations[0].value_changed is False
    else:
        assert observations[0].value_changed is True
        assert_native_frontend_value(method, observations[0], expected)
    assert native[key] == expected
    assert callbacks == (["called"] if stage == "explicit_user_event" else [])


def assert_native_frontend_value(method, result, expected):
    from streamlit.proto.ButtonGroup_pb2 import ButtonGroup
    from streamlit.proto.Checkbox_pb2 import Checkbox
    from streamlit.proto.NumberInput_pb2 import NumberInput
    from streamlit.proto.Selectbox_pb2 import Selectbox
    from streamlit.proto.TextArea_pb2 import TextArea
    from streamlit.proto.TextInput_pb2 import TextInput

    definitions = {
        "checkbox": ("checkbox.py", "checkbox_proto", Checkbox, "value"),
        "toggle": ("checkbox.py", "checkbox_proto", Checkbox, "value"),
        "number_input": ("number_input.py", "number_input_proto", NumberInput, "value"),
        "selectbox": ("selectbox.py", "selectbox_proto", Selectbox, "raw_value"),
        "segmented_control": ("button_group.py", "proto", ButtonGroup, "raw_values"),
        "text_input": ("text_widgets.py", "text_input_proto", TextInput, "value"),
        "text_area": ("text_widgets.py", "text_area_proto", TextArea, "value"),
    }
    filename, name, constructor, field = definitions[method]
    installed = Path(streamlit.__file__).parent / "elements/widgets" / filename
    tree = ast.parse(installed.read_text(encoding="utf-8"))
    branch = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.If)
        and "value_changed" in ast.unparse(n.test)
        and any(
            isinstance(x, ast.Attribute)
            and isinstance(x.ctx, ast.Store)
            and x.attr == "set_value"
            and isinstance(x.value, ast.Name)
            and x.value.id == name
            for x in ast.walk(n)
        )
    )
    f = ast.FunctionDef(
        name="emit",
        args=ast.arguments(
            posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]
        ),
        body=[branch],
        decorator_list=[],
    )
    tree = ast.fix_missing_locations(ast.Module(body=[f], type_ignores=[]))
    code = next(
        c
        for c in compile(tree, str(installed), "exec").co_consts
        if isinstance(c, CodeType)
    )
    proto = constructor()
    namespace = {
        name: proto,
        "checkbox_state": result,
        "widget_state": result,
        "current_value": expected,
        "value_needs_reset": False,
        "stale_fallback_used": False,
        "serde": SimpleNamespace(serialize=lambda value: value),
        "serializer": lambda value: [value],
        "cast": cast,
    }
    FunctionType(code, namespace)()
    assert proto.set_value is True
    assert (
        list(getattr(proto, field)) if field == "raw_values" else getattr(proto, field)
    ) == ([expected] if field == "raw_values" else expected)


@pytest.mark.parametrize(
    "owner,key,retained,edited",
    [
        (
            "_report_source_editor",
            "_report_source_assignment",
            ("Plastic", "P2"),
            ("Elastic", "E1"),
        ),
        ("_report_workspace", "_report_presentation_preset_choice", "Audit", "Brief"),
        ("_quick_section_geometry", "qs_rebar_mode", "By spacing", "By number"),
    ],
)
@pytest.mark.parametrize(
    "stage", ["old_session_first_mount", "registered_remount", "explicit_user_event"]
)
def test_adjacent_raw_control_publishes_retained_and_live_value(
    monkeypatch, owner, key, retained, edited, stage
):
    native = SessionState()
    identity = "$$ID-exact-" + key
    calls = []
    metadata = WidgetMetadata(
        identity,
        deserializer=lambda value: "intrinsic" if value is None else value,
        serializer=lambda value: value,
        value_type="string_value",
        callback=lambda: calls.append("edit"),
    )
    native[key] = retained
    if stage != "old_session_first_mount":
        native.register_widget(metadata, key)
    native._compact_state()
    if stage == "explicit_user_event":
        wire = WidgetState(id=identity, string_value=str(edited))
        # Real native string transport and callback handling; scope tuple selection is
        # represented by its serializer's string identity for this registration check.
        native.on_script_will_rerun(WidgetStates(widgets=[wire]))
    safe = SafeSessionState(native, lambda: None)
    monkeypatch.setattr(proxy_module, "get_session_state", lambda: safe)
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner_node = next(
        n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == owner
    )
    expected_key = "key" if owner == "_report_source_editor" else repr(key)
    matches = [
        n
        for n in ast.walk(owner_node)
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Subscript)
        and isinstance(n.value, ast.Subscript)
        and ast.dump(n.targets[0].slice) == ast.dump(n.value.slice)
        and ast.unparse(n.targets[0].slice) == expected_key
    ]
    assert len(matches) == 1
    wrapper = ast.FunctionDef(
        name="publish",
        args=ast.arguments(
            posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]
        ),
        body=matches,
        decorator_list=[],
    )
    code = next(
        c
        for c in compile(
            ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
            str(SOURCE),
            "exec",
        ).co_consts
        if isinstance(c, CodeType)
    )
    FunctionType(
        code,
        {
            "st": SimpleNamespace(session_state=proxy_module.SessionStateProxy()),
            "key": key,
        },
    )()
    result = native.register_widget(metadata, key)
    assert result.value == (str(edited) if stage == "explicit_user_event" else retained)
    assert result.value_changed is True
    assert calls == (["edit"] if stage == "explicit_user_event" else [])
