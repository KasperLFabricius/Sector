"""Native editor commits retain frozen seeds across navigation callbacks."""
import ast
import copy
from pathlib import Path
from types import CodeType, FunctionType, SimpleNamespace

import pandas as pd
import pytest

import fatigue_inputs
import load_cases
import project_widget_state as recovery


TABLES = tuple(recovery.EDITOR_TABLES.values())


def fixture(table, kind):
    fatigue = table == fatigue_inputs.SPECTRUM_TABLE_KEY
    numeric = 'cycles' if fatigue else load_cases.NUMERIC_COLUMNS[table][0]
    rows = [{'name': 'first', numeric: 123456.78901234567},
            {'name': 'second', numeric: 7.123456789012345}]
    if fatigue:
        for row in rows:
            row['spectrum'] = 'Traffic'
    normalize = fatigue_inputs.normalise_spectrum_table if fatigue else lambda data: load_cases.normalise_table(data, table)
    project = fatigue_inputs.editor_spectrum_table if fatigue else lambda data: load_cases.editor_table(data, table)
    seed = normalize(rows)
    patch = {'edited_rows': {}, 'deleted_rows': [], 'added_rows': []}
    if kind in ('precise', 'invalid'):
        patch['edited_rows'] = {'0': {numeric: '0.10000000000000003' if kind == 'precise' else 'invalid-action'}}
    elif kind == 'added':
        patch['added_rows'] = [{'name': 'added', numeric: '12.000000000000002', **({'spectrum': 'Traffic'} if fatigue else {})}]
    else:
        patch['deleted_rows'] = [0]
    # Independent finite-row oracle uses the existing canonical parser only.
    expected_rows = project(seed).to_dict('records')
    for position, cells in patch['edited_rows'].items():
        expected_rows[int(position)].update(cells)
    expected_rows = [row for index, row in enumerate(expected_rows) if index not in patch['deleted_rows']]
    expected_rows.extend({column: row.get(column) for column in seed.columns} for row in patch['added_rows'])
    return seed, patch, normalize(expected_rows)


def state_for(table, kind):
    seed, patch, expected = fixture(table, kind)
    editor = next(key for key, value in recovery.EDITOR_TABLES.items() if value == table)
    state = {table: seed.copy(deep=True), f'_{table}_editor_seed': seed, editor: patch,
             'results': {'N': 123.45678901234567}, 'report_buffer': b'approved',
             '_torsion_case_authorities': {'first': {'scope': True}}}
    return state, editor, expected


@pytest.mark.parametrize('table', TABLES)
@pytest.mark.parametrize('kind', ['precise', 'invalid', 'added', 'deleted'])
@pytest.mark.parametrize('order', ['editor-first', 'navigation-first', 'interrupted'])
def test_callbacks_preserve_exact_edits_and_seed_for_all_action_families(table, kind, order):
    state, editor, expected = state_for(table, kind)
    originals = dict(state)
    seed_before = copy.deepcopy(state[f'_{table}_editor_seed'])
    if order == 'navigation-first':
        recovery.commit_editor_values(state)
    recovery.commit_editor_values(state, (editor,))
    # A snapshot or recovered rerun can see the cumulative patch again.
    recovery.commit_editor_values(state)
    recovery.commit_editor_values(state, (editor,))
    pd.testing.assert_frame_equal(state[table], expected, check_exact=True)
    assert state[table].attrs == expected.attrs
    for key, value in originals.items():
        if key != table:
            assert state[key] is value
    pd.testing.assert_frame_equal(state[f'_{table}_editor_seed'], seed_before, check_exact=True)
    # Widget cleanup then remount creates a fresh seed from the committed base.
    state.pop(editor)
    recovery.commit_editor_values(state)
    state[f'_{table}_editor_seed'] = state[table].copy(deep=True)
    state[editor] = {'edited_rows': {}, 'deleted_rows': [], 'added_rows': []}
    recovery.commit_editor_values(state)
    pd.testing.assert_frame_equal(state[table], expected, check_exact=True)
    assert state[table].attrs == expected.attrs


def functions(state):
    path = Path(__file__).resolve().parents[1] / 'app/sector_app.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    scope = {'copy': copy, 'st': SimpleNamespace(session_state=state),
             'project_io': SimpleNamespace(REPORT_PROFILE_KEY='report_profile'),
             '_INPUT_STATE_KEY': '_durable_input_scalars',
             '_PENDING_INPUT_EVENTS_KEY': '_pending_input_events',
             '_NON_REPLAYABLE_INPUT_EVENT_KEYS': frozenset(recovery.EDITOR_TABLES),
             '_DURABLE_INPUT_SCALARS': (), '_PROJECT_TABLES': (),
             '_LAST_WORKSPACE_KEY': '_last_completed_workspace',
             '_INPUT_BUILD_KEY': '_inputs_build_in_progress'}
    for name in ('_record_input_event', '_snapshot_input_state', '_snapshot_completed_input_state'):
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        compiled = compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec')
        code = next(value for value in compiled.co_consts if isinstance(value, CodeType))
        scope[name] = FunctionType(code, scope, argdefs=tuple(ast.literal_eval(value) for value in node.args.defaults))
    return scope


@pytest.mark.parametrize('table', TABLES)
@pytest.mark.parametrize('order', ['editor-first', 'navigation-first', 'interrupted'])
def test_actual_callback_functions_commit_before_journal_cleanup(table, order):
    state, editor, expected = state_for(table, 'added')
    state.update(_main_page='Inputs', _last_completed_workspace='Inputs',
                 _inputs_build_in_progress=(order == 'interrupted'))
    scope = functions(state)
    if order == 'navigation-first':
        scope['_snapshot_completed_input_state']()
    scope['_record_input_event'](editor)
    scope['_snapshot_completed_input_state']()
    pd.testing.assert_frame_equal(state[table], expected, check_exact=True)
    state['_inputs_build_in_progress'] = False
    scope['_snapshot_completed_input_state']()
    assert '_pending_input_events' not in state
    pd.testing.assert_frame_equal(state[table], expected, check_exact=True)


@pytest.mark.parametrize('bad', [None, {'edited_rows': []}, {'deleted_rows': [100]}, {'unknown': [1]}])
def test_invalid_second_editor_prevents_any_canonical_write(bad):
    state, _, _ = state_for(TABLES[0], 'added')
    other, editor, _ = state_for(TABLES[1], 'added')
    state.update(other)
    state[editor] = bad
    original = dict(state)
    with pytest.raises(ValueError):
        recovery.commit_editor_values(state)
    assert all(state[key] is value for key, value in original.items())


def test_removed_widget_cannot_replay_old_seed_over_canonical_table():
    state, editor, expected = state_for(TABLES[0], 'added')
    recovery.commit_editor_values(state)
    state.pop(editor)
    recovery.commit_editor_values(state)
    pd.testing.assert_frame_equal(state[TABLES[0]], expected, check_exact=True)
