"""Native navigation protocol and unchanged portable startup semantic guards."""
from dataclasses import replace
import json

import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from tools import verify_portable_startup as startup


def navigation_message():
    message = ForwardMsg()
    for index, (path, label) in enumerate(startup._PUBLIC_PAGES.items()):
        page = message.navigation.app_pages.add()
        page.page_script_hash = f'{index + 1:032x}'
        page.page_name = label
        page.url_pathname = path
        page.is_default = path == ''
    message.navigation.page_script_hash = message.navigation.app_pages[0].page_script_hash
    return message


def surface(navigation):
    return startup._PageSurfaceEvidence({}, (), {}, navigation=navigation)


def test_native_navigation_matches_installed_protocol_and_exact_public_routes():
    message = navigation_message()
    actual = startup._page_navigation(message.SerializeToString())
    assert actual is not None
    assert len(actual.pages) == 8
    assert {page.path: page.label for page in actual.pages} == startup._PUBLIC_PAGES
    assert startup._required_navigation(surface(actual), '') == actual
    assert startup._page_navigation(ForwardMsg(script_finished=0).SerializeToString()) is None


@pytest.mark.parametrize('path', ['', 'materials', 'actions', 'settings', 'results', 'report', 'project', 'help'])
def test_requests_use_each_actual_emitted_page_hash_and_preserve_widget_payload(path):
    actual = startup._page_navigation(navigation_message().SerializeToString())
    page_hash = next(page.page_hash for page in actual.pages if page.path == path)
    original = startup._trigger_widget_rerun_backmsg('trigger-id', string_arrays=(('profile-id', 'Standard'),))
    output = BackMsg(); output.ParseFromString(startup._with_page_hash(original, page_hash))
    before = BackMsg(); before.ParseFromString(original)
    assert output.rerun_script.page_script_hash == page_hash
    assert output.rerun_script.widget_states == before.rerun_script.widget_states
    assert sum(widget.trigger_value for widget in output.rerun_script.widget_states.widgets) == 1


@pytest.mark.parametrize('mutation', ['empty', 'duplicate-path', 'duplicate-hash', 'duplicate-label', 'missing-current', 'unknown-current', 'bad-hash', 'two-defaults', 'no-default', 'hidden', 'external'])
def test_malformed_navigation_is_rejected(mutation):
    message = navigation_message(); nav = message.navigation
    if mutation == 'empty': nav.ClearField('app_pages')
    elif mutation == 'duplicate-path': nav.app_pages[1].url_pathname = ''
    elif mutation == 'duplicate-hash': nav.app_pages[1].page_script_hash = nav.app_pages[0].page_script_hash
    elif mutation == 'duplicate-label': nav.app_pages[1].page_name = nav.app_pages[0].page_name
    elif mutation == 'missing-current': nav.ClearField('page_script_hash')
    elif mutation == 'unknown-current': nav.page_script_hash = 'f' * 32
    elif mutation == 'bad-hash': nav.app_pages[1].page_script_hash = '../arbitrary'
    elif mutation == 'two-defaults': nav.app_pages[1].is_default = True
    elif mutation == 'no-default': nav.app_pages[0].is_default = False
    elif mutation == 'hidden': nav.app_pages[1].is_hidden = True
    elif mutation == 'external': nav.app_pages[1].external_url = 'https://example.invalid/'
    with pytest.raises(startup.PortableStartupError):
        startup._page_navigation(message.SerializeToString())


def test_required_navigation_rejects_missing_route_wrong_destination_and_changed_identity():
    actual = startup._page_navigation(navigation_message().SerializeToString())
    with pytest.raises(startup.PortableStartupError): startup._required_navigation(surface(None), '')
    with pytest.raises(startup.PortableStartupError): startup._required_navigation(surface(actual), 'report')
    missing = replace(actual, pages=actual.pages[:-1])
    with pytest.raises(startup.PortableStartupError): startup._required_navigation(surface(missing), '')
    changed = replace(actual, pages=(replace(actual.pages[0], page_hash='f' * 32), *actual.pages[1:]), current_page_hash='f' * 32)
    with pytest.raises(startup.PortableStartupError): startup._required_navigation(surface(changed), '', actual)


def test_native_route_does_not_depend_on_an_unrelated_nested_tab_count():
    actual = startup._page_navigation(navigation_message().SerializeToString())
    for tabs in ({}, {'material-tabs': 0}, {'material-tabs': 0, 'mvt-tabs': 2}):
        assert startup._required_navigation(replace(surface(actual), tab_containers=tabs), '') == actual


def test_duplicate_native_request_identity_and_malformed_hash_fail_closed():
    with pytest.raises(startup.PortableStartupError): startup._with_page_hash(startup._PAGE_RERUN_BACKMSG, 'not-a-page')
    request = startup._with_page_hash(startup._PAGE_RERUN_BACKMSG, '1' * 32)
    with pytest.raises(startup.PortableStartupError): startup._with_page_hash(request, '2' * 32)


def test_page_protocol_diagnostics_preserve_completed_surface_and_error(tmp_path):
    path = tmp_path / 'protocol.jsonl'
    token = startup._PAGE_DIAGNOSTICS.set(path)
    try:
        actual = startup._page_navigation(navigation_message().SerializeToString())
        startup._write_page_diagnostic('completed-surface', {'navigation': {'current_page_hash': actual.current_page_hash}})
        startup._write_page_diagnostic('failure', {'type': 'PortableStartupError', 'message': 'retained guard'})
    finally:
        startup._PAGE_DIAGNOSTICS.reset(token)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row['stage'] for row in rows] == ['completed-surface', 'failure']
    assert rows[0]['data']['navigation']['current_page_hash'] == actual.current_page_hash
    assert rows[1]['data']['message'] == 'retained guard'


def test_manual_probe_keeps_all_document_guards_on_project_page(monkeypatch):
    page_hash = 'a' * 32
    button = lambda key, label: startup._ButtonEvidence(key, label, False)
    download = lambda key, label: startup._DownloadEvidence(key, label, False, True)
    project = replace(surface(None), buttons={startup._USER_MANUAL_BUTTON_LABEL: button('open', startup._USER_MANUAL_BUTTON_LABEL)})
    opened = replace(surface(None), buttons={startup._MANUAL_GENERATE_BUTTON_LABEL: button('generate', startup._MANUAL_GENERATE_BUTTON_LABEL)})
    generated = replace(surface(None), buttons={startup._MANUAL_CLOSE_BUTTON_LABEL: button('close', startup._MANUAL_CLOSE_BUTTON_LABEL)}, downloads={
        startup._MANUAL_PDF_DOWNLOAD_LABEL: download('pdf', startup._MANUAL_PDF_DOWNLOAD_LABEL),
        startup._MANUAL_HTML_DOWNLOAD_LABEL: download('html', startup._MANUAL_HTML_DOWNLOAD_LABEL)})
    responses = iter([opened, generated, surface(None)])
    requests = []
    def execute(*args, **kwargs):
        requests.append(args[4]); return startup._PageExecutionEvidence(2, 'finished-successfully'), next(responses)
    monkeypatch.setattr(startup, '_execute_page_run', execute)
    assert startup._run_manual_document_probe(None, None, None, 1, page_hash, project) == 6
    actual = []
    for payload in requests:
        decoded = BackMsg(); decoded.ParseFromString(payload)
        assert decoded.rerun_script.page_script_hash == page_hash
        actual.append([(w.id, w.trigger_value) for w in decoded.rerun_script.widget_states.widgets])
    assert actual == [[('open', True)], [('generate', True)], [('close', True)]]


@pytest.mark.parametrize('missing', ['pdf', 'html'])
def test_manual_probe_rejects_either_missing_generated_format(monkeypatch, missing):
    button = lambda key, label: startup._ButtonEvidence(key, label, False)
    project = replace(surface(None), buttons={startup._USER_MANUAL_BUTTON_LABEL: button('open', startup._USER_MANUAL_BUTTON_LABEL)})
    opened = replace(surface(None), buttons={startup._MANUAL_GENERATE_BUTTON_LABEL: button('generate', startup._MANUAL_GENERATE_BUTTON_LABEL)})
    downloads = {label: startup._DownloadEvidence(key, label, False, True) for key,label in [('pdf',startup._MANUAL_PDF_DOWNLOAD_LABEL),('html',startup._MANUAL_HTML_DOWNLOAD_LABEL)] if key != missing}
    generated = replace(surface(None), downloads=downloads)
    responses = iter([opened, generated])
    monkeypatch.setattr(startup, '_execute_page_run', lambda *a,**k: (startup._PageExecutionEvidence(1,'finished-successfully'),next(responses)))
    with pytest.raises(startup.PortableStartupError, match='enabled download'):
        startup._run_manual_document_probe(None,None,None,1,'a'*32,project)


def test_report_probe_preserves_standard_profile_and_download_guard(monkeypatch):
    button = startup._ButtonEvidence('generate', startup._REPORT_GENERATE_BUTTON_LABEL, False)
    report = replace(surface(None), buttons={button.label: button})
    profile = startup._ButtonGroupEvidence('profile', 'Report profile', ('Brief','Standard','Audit'), ('Standard',))
    download = startup._DownloadEvidence('pdf', startup._REPORT_DOWNLOAD_LABEL, False, True)
    generated = replace(surface(None), downloads={download.label:download})
    requests=[]
    def execute(*args,**kwargs):
        requests.append(args[4]);return startup._PageExecutionEvidence(3,'finished-successfully'),generated
    monkeypatch.setattr(startup,'_execute_page_run',execute)
    assert startup._run_report_document_probe(None,None,None,1,'b'*32,profile,report)==3
    message=BackMsg();message.ParseFromString(requests[0])
    assert message.rerun_script.page_script_hash=='b'*32
    assert [(w.id,list(w.string_array_value.data),w.trigger_value) for w in message.rerun_script.widget_states.widgets]==[('profile',['Standard'],False),('generate',[],True)]
    generated=surface(None)
    with pytest.raises(startup.PortableStartupError,match='enabled download'):
        startup._run_report_document_probe(None,None,None,1,'b'*32,profile,report)


def test_navigation_rejects_wrong_wire_types_and_repeated_envelopes():
    def field(number, payload):
        return startup._encode_varint((number << 3) | 2) + startup._encode_varint(len(payload)) + payload
    valid = navigation_message().SerializeToString()
    for malformed in (startup._encode_varint(23 << 3) + b"\x01", valid + valid,
                      field(23, b"\x20\x01"),
                      field(23, field(4, b"a" * 32) + field(2, field(4, b"\x01")))):
        with pytest.raises(startup.PortableStartupError):
            startup._page_navigation(malformed)
