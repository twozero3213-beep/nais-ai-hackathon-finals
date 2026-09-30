"""Synthetic receipt tracing; no real HTTP/model/human action or artifact storage."""
# [작성: 0 이영] 2026-10-01 04:17 KST — 관측/현재기록/미수행을 구분하고 명시 저장·재개·변경 차단을 검증한다.
from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest

from core import research_integration_intake as intake
from core import research_integration_trace_ui as trace_ui
from core.research_integration_runs import IntegrationRunStore
from core.research_tasks import TaskStore
from evidence_gate.spec import empty_spec

RAW = b'id,x\na,1\nb,3\n'
ORIGINAL_TIME = '2026-10-01T02:10:00+09:00'


@pytest.fixture
def store(tmp_path):
    value = IntegrationRunStore(TaskStore(tmp_path / 'trace.db'))
    yield value
    value.close()


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setattr(intake, 'source_revision', lambda: 'c' * 64)
    monkeypatch.setattr(intake, '_get_bytes', lambda host, path, **kwargs: (RAW, {
        'http_status': 200, 'source_url': 'https://' + host + path,
        'retrieved_at_kst': ORIGINAL_TIME, 'content_type': 'text/csv'}))
    record = {'id': '23', 'doi': '10.5281/zenodo.23', 'concept_doi': '10.5281/zenodo.22',
              'version': None, 'detail_status': 'RETRIEVED', 'official_url': 'https://zenodo.org/records/23',
              'license': {'id': 'cc0-1.0', 'reuse_authorization': 'NOT_CONFIRMED'},
              'access': {'metadata': 'public', 'files': 'open'}, 'custom_terms_present': False,
              'provenance': {'response_sha256': 'a' * 64, 'source_url': 'https://zenodo.org/api/records/23'},
              'files': [{'id': 'synthetic-file', 'name': 'synthetic.csv', 'size': len(RAW), 'restricted': False,
                         'checksum': {'algorithm': 'md5', 'value': hashlib.md5(RAW).hexdigest(),
                                      'origin': 'repository_computed', 'verified_against_download': False}, 'supplied_checksum': None}]}
    acquisition = intake.acquisition('zenodo', record, 'synthetic-file')
    assert acquisition['success']
    spec = empty_spec('SYNTHETIC-TRACE')
    spec.update(method='row_count', reported_value=2, filters=[], missing_policy='not_applicable', missing_tokens=[],
                denominator='all two rows', unit='observations', data_fingerprint=hashlib.sha256(RAW).hexdigest(), tolerance=0,
                source_location={'source_id': 'synthetic', 'locator': 'Table 1', 'quote': 'Two observations.'})
    return {'download': acquisition, 'spec': spec, 'paper_context': {'paper_doi': '10.0000/synthetic',
            'paper_version': 'synthetic-1', 'source_url': 'https://example.org/synthetic', 'source_sha256': 'b' * 64},
            'source_location': deepcopy(spec['source_location']), 'conditions_confirmed': True, 'record': record}


def calculated(state):
    state['report'] = intake.verify_download(state['download']['raw_bytes'], state['download']['receipt'], state['spec'],
                                            paper_context=state['paper_context'], conditions_confirmed=True, current_record=state['record'])
    assert state['report']['success']
    return state


def test_snapshot_is_read_only_and_does_not_execute_network_model_engine_or_approval(state, monkeypatch):
    forbidden = Mock(side_effect=AssertionError('must not execute'))
    monkeypatch.setattr(intake, '_get_bytes', forbidden)
    monkeypatch.setattr(intake.gate, 'evaluate', forbidden)
    monkeypatch.setattr(intake, 'approve_download', forbidden)
    monkeypatch.setattr(trace_ui, 'IntegrationRunStore', forbidden)
    result = trace_ui.snapshot(state, 'synthetic-member')
    assert result['success'] and not result['tool_executed'] and not result['approved']
    forbidden.assert_not_called()
    assert 'raw_bytes' not in json.dumps(result)
    assert 'Two observations.' not in json.dumps(result)


def test_manual_source_records_skipped_lookups_without_claiming_original_acquisition(state, store):
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    assert result['success'] and result['status'] == 'WAITING_FOR_CALCULATION'
    steps = result['run']['attempts']
    assert [a['stage'] for a in steps] == ['search', 'relations', 'original', 'file', 'conditions']
    for lookup in steps[:2]:
        assert lookup['output_metadata']['status'] == 'NOT_REQUESTED_USER_SUPPLIED_SOURCE'
        assert lookup['output_metadata']['observation_kind'] == 'NOT_REQUESTED'
        assert lookup['output_metadata']['observed_at_kst'] is None
    assert steps[2]['output_metadata']['status'] == 'USER_DECLARED_SOURCE_NOT_ACQUIRED'
    assert result['approved'] is False and result['verified'] is False


def test_original_receipt_time_is_preserved_when_persisted_later(state, store):
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    file_step = next(a for a in result['run']['attempts'] if a['stage'] == 'file')
    assert file_step['output_metadata']['observed_at_kst'] == ORIGINAL_TIME
    assert file_step['output_metadata']['http_status'] == 200
    assert file_step['finished_at'] != ORIGINAL_TIME
    assert file_step['output_metadata']['usage_unknown'] is True


def test_repeated_explicit_persist_is_idempotent_without_duplicate_events(state, store):
    first = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    before = len(store.audit.for_claim('integration:' + first['run_id']))
    again = trace_ui.persist_snapshot(state, 'synthetic-member', store=store, trace=first)
    assert again['run_id'] == first['run_id'] and again['revision'] == first['revision']
    assert len(store.audit.for_claim('integration:' + first['run_id'])) == before


@pytest.mark.parametrize('field', ['paper', 'spec', 'engine', 'source_location', 'actor'])
def test_actor_and_current_bindings_are_rechecked_before_resume(state, store, monkeypatch, field):
    first = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    actor = 'synthetic-member'
    if field == 'paper': state['paper_context']['source_sha256'] = 'd' * 64
    if field == 'spec': state['spec']['unit'] = 'changed declared unit'
    if field == 'engine': monkeypatch.setattr(intake, 'source_revision', lambda: 'e' * 64)
    if field == 'source_location': state['source_location']['quote'] += ' changed'
    if field == 'actor': actor = 'synthetic-other'
    result = trace_ui.resume_snapshot(state, actor, store=store, trace=first)
    assert not result['success']
    assert result['error'] in {'TRACE_ROOT_CHANGED_START_NEW_RUN', 'TRACE_ACTOR_CHANGED'}
    assert store.get('synthetic-member', first['run_id'])['revision'] == first['revision']


def test_changed_bytes_block_before_any_new_audit_record(state, store):
    first = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    state['download']['raw_bytes'] += b'\n'
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store, trace=first)
    assert result['error'] == 'STALE_DATA'
    assert store.get('synthetic-member', first['run_id'])['revision'] == first['revision']


def test_observed_calculation_is_separate_from_unobserved_human_review(state, store):
    calculated(state)
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    assert result['status'] == 'WAITING_FOR_HUMAN_REVIEW'
    last = result['run']['attempts'][-1]
    assert last['stage'] == 'calculation' and last['output_metadata']['code'] == 'ARITHMETIC_SCOPE_ONLY'
    assert result['run']['next_stage'] == 'human_review'
    assert not result['approved'] and not result['verified']


def test_imported_approval_does_not_complete_trace_human_review(state, store):
    calculated(state)
    approved = intake.approve_download(state['report'], raw_bytes=RAW, receipt=state['download']['receipt'], spec=state['spec'],
                                       paper_context=state['paper_context'], actor='synthetic-approver', actor_role='APPROVER',
                                       confirmed=True, reason='Synthetic fixture; no real human event')
    state['report'] = intake.reopen_report(intake.export_report(approved))
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    assert result['status'] == 'WAITING_FOR_HUMAN_REVIEW'
    assert not result['approved'] and result['run']['next_stage'] == 'human_review'


def test_bound_synthetic_approval_record_is_observed_without_granting_approval(state, store):
    calculated(state)
    first = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    state['report'] = intake.approve_download(state['report'], raw_bytes=RAW, receipt=state['download']['receipt'], spec=state['spec'],
                                             paper_context=state['paper_context'], actor='synthetic-approver', actor_role='APPROVER',
                                             confirmed=True, reason='Synthetic fixture; no real human event')
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store, trace=first)
    assert result['success'] and result['run']['state'] == 'COMPLETE_METADATA'
    last = result['run']['attempts'][-1]
    assert last['stage'] == 'human_review' and last['output_metadata']['observation_kind'] == 'OBSERVED_APPROVAL_RECORD'
    assert last['output_metadata']['approval_receipt_sha256']
    assert not result['approved'] and not result['verified'] and not result['tool_executed']


def test_unconfirmed_conditions_stop_without_synthesizing_confirmation(state, store):
    state['conditions_confirmed'] = False
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    assert result['status'] == 'WAITING_FOR_CONDITIONS'
    assert [a['stage'] for a in result['run']['attempts']] == ['search', 'relations', 'original', 'file']


def test_missing_observation_date_remains_unknown_not_current_time(state):
    state['search'] = {'provider': 'crossref', 'status': 'SEARCHED', 'items': [], 'retrieved_at_kst': 'undated'}
    result = trace_ui.snapshot(state, 'synthetic-member')
    search = result['stages'][0]['output_metadata']
    assert search['observation_kind'] == 'OBSERVED_PROVIDER_RECEIPT'
    assert search['observed_at_kst'] is None


def test_stale_report_is_not_repackaged_as_a_current_calculation(state, store):
    calculated(state)
    state['spec']['unit'] = 'changed'
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    assert result['error'] == 'TRACE_STALE_REPORT'
    assert store.con.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_sensitive_actor_or_context_has_no_database_side_effect(state, store):
    state['paper_context']['note'] = 'someone@example.invalid'
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    assert not result['success']
    assert 'someone' not in json.dumps(result)
    assert store.con.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_interrupted_observation_requires_explicit_resume_then_same_run_retry(state, store):
    observed = trace_ui.snapshot(state, 'synthetic-member')
    started = store.start('synthetic-member', observed['bindings'], idempotency_key='interrupted-observation')
    active = store.begin_stage('synthetic-member', started['run_id'], 'search',
                               input_sha256=observed['stages'][0]['input_sha256'],
                               root_input_sha256=started['root_input_sha256'], expected_revision=started['revision'],
                               idempotency_key='observed-search-1-' + observed['stages'][0]['input_sha256'])
    prior = dict(run_id=started['run_id'], revision=active['revision'], actor_sha256=observed['actor_sha256'])
    waiting = trace_ui.persist_snapshot(state, 'synthetic-member', store=store, trace=prior)
    assert waiting['status'] == 'EXPLICIT_RESUME_REQUIRED'
    resumed = trace_ui.resume_snapshot(state, 'synthetic-member', store=store, trace=waiting)
    assert resumed['success'] and resumed['run_id'] == started['run_id']
    completed = trace_ui.persist_snapshot(state, 'synthetic-member', store=store, trace=resumed)
    assert completed['status'] == 'WAITING_FOR_CALCULATION'
    attempts = completed['run']['attempts']
    assert [a['status'] for a in attempts[:2]] == ['INTERRUPTED', 'SUCCEEDED']
    assert attempts[1]['attempt'] == 2


def test_first_ui_render_has_no_database_network_model_calculation_or_approval_side_effect(state, monkeypatch):
    from streamlit.testing.v1 import AppTest
    forbidden = Mock(side_effect=AssertionError('first render must not execute or persist'))
    monkeypatch.setattr(trace_ui, 'IntegrationRunStore', forbidden)
    monkeypatch.setattr(intake, '_get_bytes', forbidden)
    monkeypatch.setattr(intake.gate, 'evaluate', forbidden)
    monkeypatch.setattr(intake, 'approve_download', forbidden)
    code = "from core.research_integration_trace_ui import render_trace\nstate=" + repr(state) + "\nrender_trace(state, 'synthetic-member')\n"
    monkeypatch.setattr(intake, 'source_revision', forbidden)
    app = AppTest.from_string(code).run(timeout=15)
    assert len(app.exception) == 0
    # [수정: 0 이영] 2026-10-01 05:17 KST — 명시 지문 확인이 추가된 실제 네 버튼을 대조하며 첫 화면 실행 0 기대를 보존한다.
    assert {button.key for button in app.button} == {'ri_trace_check', 'ri_trace_persist', 'ri_trace_resume', 'ri_trace_new_run'}
    forbidden.assert_not_called()


# [수정: 0 이영] 2026-10-01 04:35 KST — 후보/대조/원문 receipt까지 실행 루트 지문에 결속하고 별도 새 실행에서 이전 기록을 보존한다.
@pytest.mark.parametrize('field', ['source_receipt', 'candidate_set', 'source_agreement'])
def test_extended_observation_binding_changes_block_old_run_even_when_spec_is_same(state, store, field):
    state['source_receipt'] = {'schema': 'synthetic-receipt-metadata', 'version': 1}
    state['candidate_set'] = {'candidate_set_sha256': 'd' * 64, 'candidates': [{'candidate_id': 'synthetic-A'}]}
    state['source_agreement'] = {'agreement': 'EXACT', 'semantic_ready': False}
    first = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    unchanged_spec = deepcopy(state['spec'])
    state[field]['synthetic_revision'] = 2
    rejected = trace_ui.persist_snapshot(state, 'synthetic-member', store=store, trace=first)
    assert rejected['error'] == 'TRACE_ROOT_CHANGED_START_NEW_RUN'
    assert state['spec'] == unchanged_spec
    assert store.get('synthetic-member', first['run_id'])['revision'] == first['revision']
    fresh = trace_ui.persist_snapshot(state, 'synthetic-member', store=store, trace=None)
    assert fresh['success'] and fresh['run_id'] != first['run_id']
    assert store.get('synthetic-member', first['run_id'])['run_id'] == first['run_id']


def source_context(state, *, licensed=True):
    from core.research_integration_candidates import source_receipt_for_spans
    raw = b'<article><p>Two observations.</p></article>'
    version = 'synthetic-JATS-version-1'
    url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC23/fullTextXML'
    state['paper_context'] = dict(state['paper_context'], paper_version=version, source_url=url,
                                   source_sha256=hashlib.sha256(raw).hexdigest())
    state['source_bytes'] = raw
    state['source_receipt'] = source_receipt_for_spans(raw, source_url=url, paper_version=version,
                                                     spans=[{'locator': 'synthetic paragraph', 'start_byte': 9, 'end_byte': 33}],
                                                     source_kind='LICENSED_JATS_RECEIVED' if licensed else 'RECEIVED_SOURCE_BYTES')
    state['jats'] = {'ok': True, 'source_identity_checked': True, 'public_source_receipt': {
        'schema': 'research_public_source_receipt/1', 'type': 'JATS_XML', 'url': url,
        'doi': state['paper_context']['paper_doi'], 'pmcid': 'PMC23', 'license': 'https://creativecommons.org/licenses/by/4.0/',
        'sha256': hashlib.sha256(raw).hexdigest(), 'received_at': ORIGINAL_TIME}}
    return raw


def test_current_licensed_source_receipt_is_observed_without_returning_source_bytes(state, store):
    raw = source_context(state)
    observed = trace_ui.snapshot(state, 'synthetic-member')
    assert observed['success']
    original = observed['stages'][2]['output_metadata']
    assert original['observation_kind'] == 'OBSERVED_LICENSED_JATS_RECEIPT'
    assert original['observed_at_kst'] == ORIGINAL_TIME
    assert observed['bindings']['source_bytes_sha256'] == hashlib.sha256(raw).hexdigest()
    assert 'Two observations.' not in json.dumps(observed)
    assert '<article>' not in json.dumps(observed)
    persisted = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    assert persisted['success'] and persisted['approved'] is False
    assert b'<article>' not in store.tasks.path.read_bytes()
    for row in store.con.execute('SELECT report_json FROM runs'):
        assert '<article>' not in row[0] and 'Two observations.' not in row[0]


def test_changed_source_bytes_or_bad_spans_fail_before_database_mutation(state, store):
    source_context(state)
    state['source_bytes'] += b'\n'
    rejected = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    # 현재 선언 SHA도 실제 원문 바이트와 먼저 대조하므로, 바뀐 원문은 위치 검사 전에 거절된다.
    assert rejected['error'] == 'DECLARED_SOURCE_SHA256_MISMATCH'
    assert store.con.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_licensing_identity_or_public_receipt_mismatch_is_not_promoted_to_licensed_source(state):
    source_context(state)
    state['jats']['public_source_receipt']['license'] = 'license-unconfirmed'
    observed = trace_ui.snapshot(state, 'synthetic-member')
    assert observed['success']
    assert observed['stages'][2]['output_metadata']['observation_kind'] == 'OBSERVED_SOURCE_BYTES_RECEIPT'
    assert not observed['approved'] and not observed['verified']


def test_base_intake_report_stays_six_fields_while_candidate_trace_binding_is_added(state, store):
    calculated(state)
    state['candidate_set'] = {'candidate_set_sha256': 'd' * 64, 'semantic_ready': False}
    observed = trace_ui.snapshot(state, 'synthetic-member')
    assert observed['success']
    assert set(state['report']['bindings']) == set(trace_ui.BASE_BINDING_KEYS)
    assert 'candidate_set_sha256' in observed['bindings']
    result = trace_ui.persist_snapshot(state, 'synthetic-member', store=store)
    assert result['status'] == 'WAITING_FOR_HUMAN_REVIEW'


def test_extra_observation_bindings_do_not_replace_base_intake_binding_check(state):
    calculated(state)
    state['report']['bindings']['optional_observation_sha256'] = 'd' * 64
    state['report'] = intake._seal(state['report'])
    assert trace_ui.snapshot(state, 'synthetic-member')['success']
    state['report']['bindings']['data_sha256'] = 'e' * 64
    state['report'] = intake._seal(state['report'])
    assert trace_ui.snapshot(state, 'synthetic-member')['error'] == 'TRACE_STALE_REPORT'


def test_idle_ten_reruns_hash_nothing_and_explicit_check_still_revalidates(state, monkeypatch):
    # [수정: 0 이영] 2026-10-01 05:10 KST — 표시 10회에서 소스지문·DB·전송·계산 호출 0, 명시 확인 후 변경된 바이트 거절을 함께 측정한다. 서비스 성능 우위 시험이 아니다.
    import streamlit as st
    from contextlib import nullcontext
    selected = {'key': None}
    captions = []
    monkeypatch.setattr(st, 'expander', lambda *a, **kw: nullcontext())
    monkeypatch.setattr(st, 'button', lambda *a, key, **kw: key == selected['key'])
    monkeypatch.setattr(st, 'caption', lambda text: captions.append(text))
    monkeypatch.setattr(st, 'dataframe', lambda *a, **kw: None)
    monkeypatch.setattr(st, 'warning', lambda *a, **kw: None)
    engine = Mock(return_value='c' * 64)
    monkeypatch.setattr(intake, 'source_revision', engine)
    snapshot = Mock(wraps=trace_ui.snapshot)
    monkeypatch.setattr(trace_ui, 'snapshot', snapshot)
    forbidden = Mock(side_effect=AssertionError('Idle/check UI must not write or execute'))
    monkeypatch.setattr(trace_ui, 'IntegrationRunStore', forbidden)
    monkeypatch.setattr(intake, '_get_bytes', forbidden)
    monkeypatch.setattr(intake.gate, 'evaluate', forbidden)
    for _ in range(10):
        trace_ui.render_trace(state, 'synthetic-member')
    snapshot.assert_not_called()
    engine.assert_not_called()
    forbidden.assert_not_called()
    selected['key'] = 'ri_trace_check'
    trace_ui.render_trace(state, 'synthetic-member')
    snapshot.assert_called_once()
    assert engine.call_count > 0 and state['_integration_trace_summary']['rows']
    assert state['_integration_trace_summary']['approved'] is False
    snapshot.reset_mock(); engine.reset_mock()
    state['download']['raw_bytes'] = state['download']['raw_bytes'].replace(b'a,1', b'a,2')
    selected['key'] = None
    for _ in range(10):
        trace_ui.render_trace(state, 'synthetic-member')
    snapshot.assert_not_called(); engine.assert_not_called()
    assert any('마지막 확인 관측' in text for text in captions)
    selected['key'] = 'ri_trace_check'
    trace_ui.render_trace(state, 'synthetic-member')
    assert state['_integration_trace_summary']['error'] == 'STALE_DATA'
    assert '_integration_trace' not in state
    forbidden.assert_not_called()
