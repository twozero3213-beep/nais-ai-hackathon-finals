"""Persistence, concurrency, privacy and approval boundaries without external calls."""
# [작성: 0 이영] 2026-10-01 03:30 KST — 단일 실행 단계 재개의 actor/지문/CAS/감사 원자성과 민감정보 차단을 검증한다.
import json
import sqlite3

import pytest

from core.research_integration_runs import IntegrationRunStore, STAGES, fingerprint
from core.research_tasks import TaskStore


@pytest.fixture
def store(tmp_path):
    value = IntegrationRunStore(TaskStore(tmp_path / 'tasks.db'))
    yield value
    value.close()


def start(store, key='start-1'):
    return store.start('researcher-0', {'query': 'public statistics', 'source_sha256': 'a' * 64}, idempotency_key=key)


def begin(store, run, stage='search', key='attempt-1', stage_sha=None):
    return store.begin_stage('researcher-0', run['run_id'], stage,
                             input_sha256=stage_sha or run['root_input_sha256'],
                             root_input_sha256=run['root_input_sha256'], expected_revision=run['revision'],
                             idempotency_key=key)


def finish(store, run, **changes):
    args = dict(attempt_id=run['attempt']['attempt_id'], input_sha256=run['attempt']['input_sha256'],
                root_input_sha256=run['root_input_sha256'], expected_revision=run['revision'],
                output_metadata={'count': 1, 'receipt_sha256': 'b' * 64})
    args.update(changes)
    return store.finish_stage('researcher-0', run['run_id'], **args)


def test_same_run_persists_all_stages_and_audit_without_approval(store):
    run = start(store)
    run_id = run['run_id']
    parent = None
    parent_output = None
    for stage in STAGES:
        active = begin(store, run, stage, 'stage-' + stage, fingerprint({'stage': stage}))
        assert active['attempt']['parent_attempt_id'] == parent
        assert active['attempt']['parent_output_sha256'] == parent_output
        parent = active['attempt']['attempt_id']
        output = {'approval_receipt_sha256': 'c' * 64} if stage == 'human_review' else {'count': 1}
        run = finish(store, active, output_metadata=output)
        parent_output = run['attempts'][-1]['output_sha256']
        assert run['run_id'] == run_id
        assert run['approved'] is False
    assert run['state'] == 'COMPLETE_METADATA'
    assert run['next_stage'] is None
    assert run['storage_limit'] == 'METADATA_ONLY_REACQUIRE_BYTES_AND_RECHECK_SHA256'
    task = store.tasks.get('researcher-0', run['task_id'])
    assert task['latest_run']['id'] == run_id and task['latest_run']['approved'] is False
    events = store.audit.for_claim('integration:' + run_id)
    assert len(events) == 15 and all(event['actor_id'] == 'researcher-0' for event in events)
    assert all(event['event'] != 'APPROVED' for event in events)
    assert store.audit.verify_audit_chain()
    reopened = IntegrationRunStore(TaskStore(store.tasks.path))
    try:
        assert reopened.get('researcher-0', run_id) == store.get('researcher-0', run_id)
    finally:
        reopened.close()


def test_actor_and_root_fingerprint_are_rechecked_before_resume(store):
    run = start(store)
    with pytest.raises(PermissionError, match='NOT_OWNED'):
        store.get('another-researcher', run['run_id'])
    with pytest.raises(ValueError, match='ROOT_INPUT_CHANGED'):
        store.resume('researcher-0', run['run_id'], root_input_sha256='d' * 64,
                     input_sha256=run['root_input_sha256'], expected_revision=0)
    active = begin(store, run, stage_sha='e' * 64)
    with pytest.raises(ValueError, match='STAGE_INPUT_CHANGED'):
        store.resume('researcher-0', run['run_id'], root_input_sha256=run['root_input_sha256'],
                     input_sha256='f' * 64, expected_revision=active['revision'])
    assert store.get('researcher-0', run['run_id'])['revision'] == active['revision']


def test_start_and_stage_idempotency_prevent_duplicate_calls(store):
    run = start(store)
    duplicate = start(store)
    assert duplicate['run_id'] == run['run_id'] and duplicate['reused'] is True
    with pytest.raises(ValueError, match='ROOT_INPUT_CHANGED'):
        store.start('researcher-0', {'query': 'different'}, idempotency_key='start-1')
    active = begin(store, run)
    duplicate = begin(store, run)  # stale revision is acceptable only for identical idempotent readback.
    assert duplicate['execute'] is False
    assert duplicate['attempt']['attempt_id'] == active['attempt']['attempt_id']
    result = finish(store, active)
    assert finish(store, active)['reused'] is True
    with pytest.raises(ValueError, match='IDEMPOTENCY_INPUT_CONFLICT'):
        begin(store, result, key='attempt-1', stage_sha='c' * 64)
    assert len(store.audit.for_claim('integration:' + run['run_id'])) == 3


def test_explicit_resume_revokes_late_worker_and_retains_attempt_history(store):
    run = start(store)
    old = begin(store, run)
    resumed = store.resume('researcher-0', run['run_id'], root_input_sha256=run['root_input_sha256'],
                           input_sha256=old['attempt']['input_sha256'], expected_revision=old['revision'])
    new = begin(store, resumed, key='attempt-2')
    with pytest.raises(ValueError, match='STALE_CHECKPOINT'):
        finish(store, old)
    with pytest.raises(ValueError, match='NO_LONGER_ACTIVE'):
        finish(store, old, expected_revision=new['revision'])
    finished = finish(store, new)
    assert [a['status'] for a in finished['attempts']] == ['INTERRUPTED', 'SUCCEEDED']
    assert finished['attempts'][1]['attempt'] == 2


def test_two_sessions_cannot_begin_or_finish_with_stale_revision(store):
    run = start(store)
    other = IntegrationRunStore(TaskStore(store.tasks.path))
    try:
        active = begin(store, run)
        with pytest.raises(ValueError, match='STALE_CHECKPOINT'):
            begin(other, run, key='competing-attempt')
        finish(store, active)
        with pytest.raises(ValueError, match='STALE_CHECKPOINT'):
            finish(other, active, output_metadata={'count': 99})
    finally:
        other.close()


def test_failure_retry_preserves_error_and_only_counts_actual_started_attempts(store):
    active = begin(store, start(store))
    failed = finish(store, active, output_metadata=None, error_code='PUBLIC_PROVIDER_UNAVAILABLE', next_action='RETRY')
    assert failed['state'] == 'NEEDS_ATTENTION'
    with pytest.raises(ValueError, match='STAGE_INPUT_CHANGED'):
        begin(store, failed, key='changed-retry', stage_sha='d' * 64)
    retry = begin(store, failed, key='retry-2')
    completed = finish(store, retry)
    assert completed['attempts'][0]['error_code'] == 'PUBLIC_PROVIDER_UNAVAILABLE'
    assert completed['attempts'][0]['output_sha256'] is None
    assert completed['attempts'][1]['output_sha256'] == fingerprint(completed['attempts'][1]['output_metadata'])


@pytest.mark.parametrize('payload', [
    {'api_key': 'unprinted-placeholder'}, {'notes': 'someone@example.invalid'},
    {'data': b'csv bytes'}, {'question': 'a' * 1001}, {'body': ['a'] * 33},
    {'local_path': 'C:/Users/synthetic-test/input.csv'},  # hygiene: allow-local-path — 개인 파일 없이 합성 경로를 차단하는 시험.
    {'password': 'unprinted-placeholder'},
])
def test_sensitive_large_or_binary_inputs_never_enter_tasks_or_audit(store, payload):
    with pytest.raises(ValueError):
        store.start('researcher-0', payload, idempotency_key='unsafe')
    assert store.con.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    assert store.con.execute('SELECT count(*) FROM lifecycle').fetchone()[0] == 0


@pytest.mark.parametrize('output', [
    {'raw_bytes': b'file'}, {'doi': 'someone@example.invalid'},
    {'url': 'https://example.org/data?authorization=placeholder'}, {'url': 'file:///private/file'},
    {'url': 'https://name:placeholder@example.org/data'}, {'status': 'a' * 301}, {'sha256': 'short'},
    {'url': 1}, {'count': True}, {'count': -1}, {'conditions_confirmed': 1},
])
def test_unsafe_outputs_are_rejected_without_advancing_checkpoint(store, output):
    active = begin(store, start(store))
    with pytest.raises(ValueError):
        finish(store, active, output_metadata=output)
    assert store.get('researcher-0', active['run_id'])['revision'] == active['revision']
    assert len(store.audit.for_claim('integration:' + active['run_id'])) == 2


def test_only_error_codes_are_recorded_not_exception_text(store):
    active = begin(store, start(store))
    with pytest.raises(ValueError, match='ERROR_CODE_ONLY'):
        finish(store, active, output_metadata=None, error_code='Request failed: private details')
    assert store.get('researcher-0', active['run_id'])['revision'] == active['revision']


def test_stage_order_and_human_review_receipt_fail_closed(store):
    run = start(store)
    with pytest.raises(ValueError, match='STAGE_NOT_READY'):
        begin(store, run, stage='calculation')
    for stage in STAGES[:-1]:
        run = finish(store, begin(store, run, stage=stage, key=stage))
    active = begin(store, run, stage='human_review', key='review')
    with pytest.raises(ValueError, match='HUMAN_REVIEW_RECEIPT_REQUIRED'):
        finish(store, active)
    assert store.get('researcher-0', run['run_id'])['approved'] is False


def test_checkpoint_and_audit_event_rollback_together(store, monkeypatch):
    run = start(store)
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic audit failure')
    monkeypatch.setattr(store.audit, 'append', broken)
    with pytest.raises(sqlite3.OperationalError):
        begin(store, run)
    assert store.get('researcher-0', run['run_id'])['revision'] == 0
    assert store.tasks.get('researcher-0', run['task_id'])['status'] == 'CHECKED_PARTIAL'


def test_report_rehashed_after_tampering_still_fails_audit_binding(store):
    run = start(store)
    row = store.con.execute('SELECT report_json FROM runs WHERE id=?', (run['run_id'],)).fetchone()
    report = json.loads(row[0])
    report['integration']['next_stage'] = 'calculation'
    from core.research_tasks import _json
    raw, digest = _json(report)
    with store.con:
        store.con.execute('UPDATE runs SET report_json=?,report_sha256=? WHERE id=?', (raw, digest, run['run_id']))
    with pytest.raises(ValueError, match='CHECKPOINT_AUDIT_MISMATCH'):
        store.get('researcher-0', run['run_id'])


def test_superseding_generic_task_run_blocks_old_integration_writes(store):
    run = start(store)
    assert store.tasks._claim('researcher-0', run['task_id']) is not None
    with pytest.raises(ValueError, match='RUN_SUPERSEDED'):
        store.get('researcher-0', run['run_id'])


def test_atomic_start_rolls_back_task_and_run_if_audit_write_fails(store, monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic audit failure')
    monkeypatch.setattr(store.audit, 'append', broken)
    with pytest.raises(sqlite3.OperationalError):
        start(store)
    assert store.con.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    assert store.con.execute('SELECT count(*) FROM runs').fetchone()[0] == 0


def test_same_store_parallel_claims_have_one_winner(store):
    from concurrent.futures import ThreadPoolExecutor
    run = start(store)
    def try_begin(key):
        try:
            return begin(store, run, key=key)['execute']
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_begin, ['worker-a', 'worker-b']))
    assert sorted(str(value) for value in results) == ['STALE_CHECKPOINT', 'True']
    assert len(store.get('researcher-0', run['run_id'])['attempts']) == 1


def test_generic_stale_recovery_cannot_reauthorize_old_attempt(store, monkeypatch):
    from datetime import timedelta
    import core.research_tasks as tasks_module
    active = begin(store, start(store))
    future = tasks_module.utc_now() + timedelta(minutes=16)
    monkeypatch.setattr(tasks_module, 'utc_now', lambda: future)
    store.tasks.recover_stale('researcher-0', active['task_id'])
    with pytest.raises(ValueError, match='NO_LONGER_ACTIVE'):
        finish(store, active)
    resumed = store.resume('researcher-0', active['run_id'],
                           root_input_sha256=active['root_input_sha256'],
                           input_sha256=active['attempt']['input_sha256'], expected_revision=active['revision'])
    assert resumed['attempts'][0]['status'] == 'INTERRUPTED'
    assert resumed['run_id'] == active['run_id']


@pytest.mark.parametrize('revision', [True, 0.0, -1, '0'])
def test_revision_contract_does_not_coerce_bool_float_or_string(store, revision):
    run = start(store)
    with pytest.raises(ValueError, match='INVALID_REVISION'):
        store.begin_stage('researcher-0', run['run_id'], 'search',
                          input_sha256=run['root_input_sha256'], root_input_sha256=run['root_input_sha256'],
                          expected_revision=revision, idempotency_key='strict')


@pytest.mark.parametrize('field', ['source_sha256', 'data_sha256', 'spec_sha256', 'engine_source_revision'])
def test_original_data_spec_or_engine_change_requires_new_run(store, field):
    inputs = {key: 'a' * 64 for key in ('source_sha256', 'data_sha256', 'spec_sha256', 'engine_source_revision')}
    run = store.start('researcher-0', inputs, idempotency_key='bound-run')
    inputs[field] = 'b' * 64
    with pytest.raises(ValueError, match='ROOT_INPUT_CHANGED'):
        store.resume('researcher-0', run['run_id'], root_input_sha256=fingerprint(inputs),
                     input_sha256=run['root_input_sha256'], expected_revision=run['revision'])
    assert store.get('researcher-0', run['run_id'])['revision'] == run['revision']


# [수정: 0 이영] 2026-10-01 04:15 KST — 관측 trace 5필드의 엄격 타입·KST 시각과 원시값 비노출을 검증한다.
@pytest.mark.parametrize('metadata', [
    {'http_status': True}, {'http_status': 99}, {'http_status': 600}, {'http_status': '200'},
    {'elapsed_ms': -1}, {'elapsed_ms': True}, {'elapsed_ms': 1.5}, {'usage_unknown': 1},
    {'usage_unknown': None}, {'observed_at_kst': '2026-10-01T04:15:00'},
    {'observed_at_kst': '2026-10-01T04:15:00+00:00'}, {'observed_at_kst': 'invented time'},
    {'observation_kind': ''}, {'observation_kind': None},
])
def test_observation_fields_reject_wrong_types_and_unknown_timezone(store, metadata):
    active = begin(store, start(store))
    with pytest.raises(ValueError):
        finish(store, active, output_metadata=metadata)
    assert store.get('researcher-0', active['run_id'])['revision'] == active['revision']


def test_original_observation_time_is_distinct_from_recording_time(store):
    active = begin(store, start(store))
    result = finish(store, active, output_metadata={'observed_at_kst': '2026-10-01T02:00:00+09:00',
                    'observation_kind': 'OBSERVED_RECEIPT', 'http_status': 200, 'elapsed_ms': 0, 'usage_unknown': True})
    saved = result['attempts'][-1]
    assert saved['output_metadata']['observed_at_kst'] == '2026-10-01T02:00:00+09:00'
    assert saved['finished_at'] != saved['output_metadata']['observed_at_kst']


def test_public_https_is_not_mistaken_for_a_local_windows_drive(store):
    active = begin(store, start(store))
    result = finish(store, active, output_metadata={'url': 'https://example.org/public/data.csv'})
    assert result['attempts'][-1]['output_metadata']['url'] == 'https://example.org/public/data.csv'
