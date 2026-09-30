"""New synthetic regression protocol; no model, network, or real human approval.

Numeric equality, old-approval reuse, and source semantics are separate assertions.
These tests are neither the C01–C08 sealed comparison nor a competitive benchmark.
"""
# [작성: 0 이영] 2026-10-01 03:52 KST — 공격 문서의 동등 숫자 반례와 정상 6대조를 별도 합성 회귀로 점검한다. 기존 봉인·제품은 수정하지 않는다.
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from core import research_integration_intake as intake
from core.research_integration_runs import IntegrationRunStore, fingerprint
from core.research_tasks import TaskStore
from evidence_gate.spec import empty_spec, spec_sha256


PROTOCOL_ID = 'SYNTHETIC-INTEGRATION-ADVERSARIAL-0-20261001'
PROTOCOL_SCOPE = {'synthetic': True, 'real_human_approvals': 0, 'model_calls': 0,
                  'scope': 'binding and arithmetic regression; source semantics not automatically verified'}
RAW = b'id,group,value\na,A,10\nb,A,20\nc,B,5\nd,B,25\n'
CHANGED_RAW_SAME_MEAN = b'id,group,value\na,A,5\nb,A,25\nc,B,10\nd,B,20\n'
SOURCE = 'Synthetic Methods: group A mean is 15 milligrams; two observations; no missing values.'
NORMAL_CONTROLS = (
    ('mean', 'A', 15), ('mean', 'B', 15), ('mean', None, 15),
    ('row_count', 'A', 2), ('row_count', 'B', 2), ('row_count', None, 4),
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def paper(source=SOURCE, version='synthetic-version-1'):
    return {'paper_doi': '10.0000/synthetic-adversarial', 'paper_version': version,
            'source_url': 'https://example.org/synthetic-methods', 'source_sha256': sha(source.encode('utf8'))}


def specification(raw=RAW, method='mean', group='A', reported=15):
    result = empty_spec('SYNTHETIC-ADVERSARIAL-CLAIM')
    result.update(method=method, variable='value' if method == 'mean' else None,
                  reported_value=reported, filters=[] if group is None else [{'column': 'group', 'operator': 'eq', 'value': group}],
                  missing_policy='error' if method == 'mean' else 'not_applicable', missing_tokens=[],
                  denominator='all input rows' if group is None else 'rows in group ' + group,
                  unit='milligrams' if method == 'mean' else 'observations', data_fingerprint=sha(raw),
                  tolerance=0.000001, source_location={'source_id': 'synthetic-methods', 'locator': 'Methods, synthetic paragraph 1', 'quote': SOURCE})
    return result


def acquired(monkeypatch, raw=RAW):
    record = {'id': '23', 'doi': '10.5281/zenodo.23', 'concept_doi': '10.5281/zenodo.22',
              'version': None, 'detail_status': 'RETRIEVED', 'official_url': 'https://zenodo.org/records/23',
              'license': {'id': 'cc0-1.0', 'reuse_authorization': 'NOT_CONFIRMED'},
              'access': {'metadata': 'public', 'files': 'open'}, 'custom_terms_present': False,
              'provenance': {'response_sha256': 'a' * 64, 'source_url': 'https://zenodo.org/api/records/23'},
              'files': [{'id': 'synthetic-file', 'name': 'synthetic.csv', 'size': len(raw), 'restricted': False,
                         'checksum': {'algorithm': 'md5', 'value': hashlib.md5(raw).hexdigest(),
                                      'origin': 'repository_computed', 'verified_against_download': False},
                         'supplied_checksum': None}]}
    monkeypatch.setattr(intake, '_get_bytes', lambda host, path, **kwargs: (raw, {
        'http_status': 200, 'source_url': 'https://' + host + path,
        'retrieved_at_kst': '2026-10-01T03:52:00+09:00', 'content_type': 'text/csv'}))
    result = intake.acquisition('zenodo', record, 'synthetic-file')
    assert result['success'], result.get('error')
    return result


@pytest.fixture(autouse=True)
def isolated_engine_and_network(monkeypatch):
    monkeypatch.setattr(intake, 'source_revision', lambda: 'synthetic-engine-source-1')
    # A missing per-test download mock must fail rather than perform a GET.
    monkeypatch.setattr(intake, '_get_bytes', Mock(side_effect=AssertionError('external HTTP is forbidden')))


def verify(acquisition, spec=None, *, context=None, **kwargs):
    return intake.verify_download(acquisition['raw_bytes'], acquisition['receipt'], spec or specification(acquisition['raw_bytes']),
                                  paper_context=context or paper(), conditions_confirmed=True, **kwargs)


def synthetic_approval(acquisition, report=None, spec=None):
    # This is a test fixture, not an authenticated real person's approval event.
    result = intake.approve_download(report or verify(acquisition, spec), raw_bytes=acquisition['raw_bytes'],
                                    receipt=acquisition['receipt'], spec=spec or specification(acquisition['raw_bytes']),
                                    paper_context=paper(), actor='synthetic-approver', actor_role='APPROVER',
                                    confirmed=True, reason='SYNTHETIC TEST ONLY; no real human review occurred')
    assert result['approved'] and result['verified'] is False
    assert result['state'] == 'APPROVED_ARITHMETIC_SCOPE'
    return result


@pytest.mark.parametrize('method,group,reported', NORMAL_CONTROLS)
def test_six_sufficient_supported_controls_reach_review_without_automatic_approval(monkeypatch, method, group, reported):
    acquisition = acquired(monkeypatch)
    result = verify(acquisition, specification(method=method, group=group, reported=reported))
    assert result['success'] and result['calculation']['verdict'] == 'MATCH'
    assert result['calculation']['computed'] == reported
    assert result['state'] == 'NEEDS_HUMAN_REVIEW' and result['can_approve']
    assert result['approved'] is False and result['verified'] is False
    assert result['human_approval'] is None
    assert result['paper_source_status']['status'] == 'NOT_ACQUIRED'


def test_sufficient_supported_mismatch_is_reported_rather_than_blanket_blocked(monkeypatch):
    result = verify(acquired(monkeypatch), specification(reported=16))
    assert result['success'] and result['state'] == 'NEEDS_HUMAN_REVIEW'
    assert result['calculation']['verdict'] == 'MISMATCH'
    assert result['calculation']['computed'] == 15
    assert not result['can_approve'] and not result['approved']


def test_same_mean_different_file_rejects_old_receipt_and_old_approval(monkeypatch):
    first = acquired(monkeypatch)
    approved = synthetic_approval(first)
    stale = deepcopy(first)
    stale['raw_bytes'] = CHANGED_RAW_SAME_MEAN
    assert verify(stale)['error'] == 'STALE_DATA'
    changed = acquired(monkeypatch, CHANGED_RAW_SAME_MEAN)
    fresh = verify(changed)
    assert fresh['calculation']['computed'] == approved['calculation']['computed'] == 15
    assert fresh['bindings']['data_sha256'] != approved['bindings']['data_sha256']
    blocked = verify(changed, prior_approval=approved['human_approval'])
    assert blocked['error'] == 'STALE_APPROVAL' and not blocked['approved']


def test_equal_mean_different_population_invalidates_review_without_claiming_semantic_truth(monkeypatch):
    acquisition = acquired(monkeypatch)
    approved = synthetic_approval(acquisition)
    other = specification(group='B')
    other['source_location']['quote'] = SOURCE  # Intentionally contradictory synthetic A-text/B-filter.
    fresh = verify(acquisition, other)
    assert fresh['calculation']['computed'] == approved['calculation']['computed'] == 15
    assert fresh['calculation']['verdict'] == 'MATCH'
    assert fresh['verified'] is False and fresh['paper_source_status']['actual_sha256'] is None
    assert 'PAPER_BYTES_NOT_ACQUIRED' in fresh['limitations']
    assert fresh['bindings']['spec_sha256'] != approved['bindings']['spec_sha256']
    blocked = verify(acquisition, other, prior_approval=approved['human_approval'])
    assert blocked['error'] == 'STALE_APPROVAL'
    # The generic intake checks arithmetic under declared conditions; it does not
    # independently reject the contradictory source meaning. Keep this limit visible.
    assert fresh['can_approve'] is True and fresh['approved'] is False


def test_equal_number_different_unit_invalidates_previous_review_not_unit_semantics(monkeypatch):
    acquisition = acquired(monkeypatch)
    approved = synthetic_approval(acquisition)
    other = specification()
    other['unit'] = 'micrograms'
    result = verify(acquisition, other, prior_approval=approved['human_approval'])
    assert result['error'] == 'STALE_APPROVAL'
    fresh = verify(acquisition, other)
    assert fresh['calculation']['computed'] == 15 and fresh['verified'] is False
    assert 'Arithmetic verification only' in fresh['limitations'][0]


@pytest.mark.parametrize('changed_source', [SOURCE + '\n', SOURCE.replace('group A', 'group B')])
def test_source_preprocessing_or_population_text_change_blocks_old_approval(monkeypatch, changed_source):
    acquisition = acquired(monkeypatch)
    approved = synthetic_approval(acquisition)
    result = verify(acquisition, context=paper(changed_source), prior_approval=approved['human_approval'])
    assert result['error'] == 'STALE_APPROVAL'
    fresh = verify(acquisition, context=paper(changed_source))
    assert fresh['calculation']['computed'] == 15
    assert fresh['paper_source_status']['status'] == 'NOT_ACQUIRED'


def test_engine_changes_during_calculation_fail_closed(monkeypatch):
    acquisition = acquired(monkeypatch)
    revisions = iter(['synthetic-engine-1', 'synthetic-engine-2'])
    monkeypatch.setattr(intake, 'source_revision', lambda: next(revisions))
    result = verify(acquisition)
    assert result['error'] == 'SOURCE_CHANGED_DURING_CALCULATION'
    assert result['approved'] is False and result['can_approve'] is False


def test_missing_conditions_do_not_execute_and_resolution_gets_new_spec_and_run(monkeypatch, tmp_path):
    acquisition = acquired(monkeypatch)
    missing = specification()
    missing['unit'] = None
    missing['unresolved'] = ['UNIT_NEEDS_SOURCE_CONFIRMATION']
    evaluator = Mock(wraps=intake.gate.evaluate)
    monkeypatch.setattr(intake.gate, 'evaluate', evaluator)
    report = verify(acquisition, missing)
    assert report['error'] == 'SPEC_NOT_READY'
    evaluator.assert_not_called()
    store = IntegrationRunStore(TaskStore(tmp_path / 'tasks.db'))
    try:
        old_inputs = {'spec_sha256': spec_sha256(missing), 'data_sha256': sha(RAW), 'source_sha256': paper()['source_sha256']}
        old = store.start('synthetic-researcher', old_inputs, idempotency_key='before-source-confirmation')
        resolved = specification()
        result = verify(acquisition, resolved)
        assert result['calculation']['verdict'] == 'MATCH' and result['approved'] is False
        new_inputs = dict(old_inputs, spec_sha256=spec_sha256(resolved))
        with pytest.raises(ValueError, match='ROOT_INPUT_CHANGED'):
            store.resume('synthetic-researcher', old['run_id'], root_input_sha256=fingerprint(new_inputs),
                         input_sha256=old['root_input_sha256'], expected_revision=old['revision'])
        new = store.start('synthetic-researcher', new_inputs, idempotency_key='after-source-confirmation')
        assert new['run_id'] != old['run_id'] and new['root_input_sha256'] != old['root_input_sha256']
        assert missing['unit'] is None and missing['unresolved']  # Prior candidate remains preserved.
    finally:
        store.close()


def test_ai_unresolved_and_truthy_confirmed_do_not_create_approval(monkeypatch):
    acquisition = acquired(monkeypatch)
    candidate = specification()
    candidate['unresolved'] = ['AI_PROPOSAL_REQUIRES_HUMAN_CONDITION_CONFIRMATION']
    assert verify(acquisition, candidate)['error'] == 'SPEC_NOT_READY'
    forged = intake.verify_download(RAW, acquisition['receipt'], specification(), paper_context=paper(), conditions_confirmed=1)
    assert forged['error'] == 'CONDITIONS_NOT_CONFIRMED'
    report = synthetic_approval(acquisition)
    reopened = intake.reopen_report(intake.export_report(report))
    assert not reopened['approved'] and not reopened['can_approve'] and not reopened['verified']
    assert reopened['human_approval']['active'] is False
    assert PROTOCOL_SCOPE['real_human_approvals'] == 0


def test_late_result_cannot_replace_resumed_stage_with_equal_numeric_metadata(tmp_path):
    store = IntegrationRunStore(TaskStore(tmp_path / 'tasks.db'))
    try:
        run = store.start('synthetic-researcher', {'data_sha256': sha(RAW)}, idempotency_key='synthetic-run')
        args = {'input_sha256': run['root_input_sha256'], 'root_input_sha256': run['root_input_sha256'], 'expected_revision': 0}
        old = store.begin_stage('synthetic-researcher', run['run_id'], 'search', idempotency_key='old-worker', **args)
        resumed = store.resume('synthetic-researcher', run['run_id'], **dict(args, expected_revision=old['revision']))
        new = store.begin_stage('synthetic-researcher', run['run_id'], 'search',
                                idempotency_key='new-worker', **dict(args, expected_revision=resumed['revision']))
        with pytest.raises(ValueError, match='ATTEMPT_NO_LONGER_ACTIVE'):
            store.finish_stage('synthetic-researcher', run['run_id'], attempt_id=old['attempt']['attempt_id'],
                               output_metadata={'count': 4}, **dict(args, expected_revision=new['revision']))
        finished = store.finish_stage('synthetic-researcher', run['run_id'], attempt_id=new['attempt']['attempt_id'],
                                      output_metadata={'count': 4}, **dict(args, expected_revision=new['revision']))
        assert [a['status'] for a in finished['attempts']] == ['INTERRUPTED', 'SUCCEEDED']
        assert finished['attempts'][0]['output_metadata'] is None
    finally:
        store.close()


def test_new_synthetic_protocol_preserves_existing_sealed_bytes(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    protected = [root / 'finals' / 'evidence' / name for name in ('seal.json', 'protocol.json', 'expected.json')]
    before = {p.name: sha(p.read_bytes()) for p in protected}
    assert PROTOCOL_ID.startswith('SYNTHETIC-') and len(NORMAL_CONTROLS) == 6
    assert PROTOCOL_SCOPE['synthetic'] and PROTOCOL_SCOPE['model_calls'] == 0
    assert PROTOCOL_ID not in json.loads(protected[1].read_text(encoding='utf8')).values()
    acquisition = acquired(monkeypatch)
    verify(acquisition)
    assert {p.name: sha(p.read_bytes()) for p in protected} == before
