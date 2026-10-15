"""Pending Plastic and Elastic edits survive native tab and page transitions."""
import json

import pandas as pd
import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetState

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import load_cases
from app_workflow_navigation import goto_page
from test_actions_tabs_native import (
    EDITORS, _assert_active_only, _fresh, _payload, _select, _send,
    _tab_container, _tables, _widget_id,
)


@pytest.mark.parametrize('family', ['Plastic', 'Elastic'])
@pytest.mark.parametrize('kind', ['precise', 'invalid', 'added', 'deleted'])
def test_pending_case_editor_event_survives_tab_page_switch(family, kind):
    app = _fresh()
    table = family.lower() + '_cases_base'
    numeric = load_cases.NUMERIC_COLUMNS[table][0]
    seed = load_cases.normalise_table([
        {'name': 'first', numeric: 123456.78901234567},
        {'name': 'second', numeric: 7.123456789012345},
    ], table)
    app.session_state[table] = seed
    for key in (EDITORS[family], f'_{table}_editor_seed'):
        if key in app.session_state:
            del app.session_state[key]
    app.run()
    assert not app.exception
    _select(app, family)
    before = _tables(app)
    patch = {'edited_rows': {}, 'added_rows': [], 'deleted_rows': []}
    if kind in ('precise', 'invalid'):
        patch['edited_rows'] = {'0': {numeric: '0.10000000000000003' if kind == 'precise' else 'invalid-action'}}
    elif kind == 'added':
        patch['added_rows'] = [{'name': 'added', numeric: '12.000000000000002'}]
    else:
        patch['deleted_rows'] = [0]
    rows = load_cases.editor_table(app.session_state[f'_{table}_editor_seed'], table).to_dict('records')
    for index, cells in patch['edited_rows'].items():
        rows[int(index)].update(cells)
    rows = [row for index, row in enumerate(rows) if index not in patch['deleted_rows']]
    rows.extend({column: row.get(column) for column in seed.columns} for row in patch['added_rows'])
    expected = load_cases.normalise_table(rows, table)
    _send(app,
          WidgetState(id=_tab_container(app).proto.tab_container.id, string_value='Fatigue'),
          WidgetState(id=_widget_id(app, EDITORS[family]), string_value=json.dumps(patch)))
    _assert_active_only(app, 'Fatigue', True)
    pd.testing.assert_frame_equal(app.session_state[table], expected, check_exact=True)
    goto_page(app, 'materials')
    goto_page(app, 'actions')
    _select(app, family)
    pd.testing.assert_frame_equal(app.session_state[table], expected, check_exact=True)
    assert app.session_state[table].attrs == expected.attrs
    for other, frame in before.items():
        if other != table:
            pd.testing.assert_frame_equal(app.session_state[other], frame, check_exact=True)
            assert app.session_state[other].attrs == frame.attrs
    payload_table = app.session_state['_latest_inputs'][family.lower() + '_cases']
    pd.testing.assert_frame_equal(payload_table, expected, check_exact=True)
    assert payload_table.attrs == expected.attrs
    payload = _payload(app)
    _select(app, 'Fatigue')
    _select(app, family)
    pd.testing.assert_frame_equal(app.session_state[table], expected, check_exact=True)
    assert app.session_state[table].attrs == expected.attrs
    assert _payload(app) == payload
