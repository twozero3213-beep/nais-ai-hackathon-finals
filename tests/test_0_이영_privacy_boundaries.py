"""Synthetic-only privacy checks at model and persistent logging boundaries."""
# [작성: 0 이영] 2026-10-01 02:53 KST — 공급자별 개인정보 우회·모델 응답 재전송·실제 로그 저장을 재현하고 정상 검산 수치와 원입력 불변을 함께 검증한다.
from copy import deepcopy
import base64
import hashlib
import json

import pytest

from core import research_agent as agent, team_workspace as team
from core.input_security import sensitive_content_kinds
from core.logging_utils import get_logger
from core.structured_logging import _redact, event, get_event_logger
from finals import finals_provider as provider


KEY = 'Synthetic-Only-Model-Credential'
EVIDENCE = [{'id': 'mock-e1', 'text': 'Synthetic public evidence supports the draft.',
             'doi': '10.0000/synthetic', 'locator': 'synthetic p.1'}]
DRAFT = {'answer': 'Synthetic supported draft.', 'citations': ['mock-e1'], 'limitations': []}
CRITIC = {'supported': True, 'issues': []}
SENSITIVE = [
    pytest.param('reviewer@example.invalid', id='EMAIL'),
    pytest.param('010-1234-5678', id='KR_PHONE'),
    pytest.param('990101-1234567', id='KR_RRN'),
    pytest.param('AIza' + 'A' * 35, id='GOOGLE_KEY'),
    # [수정: 3 조지현 · 2026-10-01T03:44:46+09:00] 합성 헤더의 런타임 값은 보존하고, 정적 비밀값 검사에 실제 키 본문처럼 걸리는 표기를 분리한다.
    pytest.param('-----BEGIN ' + 'PRIVATE KEY-----\nSYNTHETIC_TEST_BODY\n-----END PRIVATE KEY-----', id='PRIVATE_KEY'),
    pytest.param('password=synthetic-fixture-only', id='NAMED_PASSWORD'),
    pytest.param('access_token="synthetic-fixture-only"', id='NAMED_TOKEN'),
]


@pytest.fixture(autouse=True)
def forbid_network_and_isolate_knowledge(monkeypatch):
    monkeypatch.setattr(agent, 'load_knowledge', lambda: ({}, 'synthetic-knowledge-sha'))
    monkeypatch.setattr(agent, 'forbidden_claims', lambda: [])
    monkeypatch.setattr(agent, 'known_error_cases', lambda _: [])
    monkeypatch.setattr(agent.http.client, 'HTTPSConnection',
                        lambda *a, **k: pytest.fail('Synthetic tests must never connect'))


def model_transport(monkeypatch, selected, outputs):
    calls = []
    values = iter(outputs)

    def anthropic(payload, *, api_key):
        calls.append(payload)
        return {'stop_reason': 'end_turn',
                'content': [{'type': 'text', 'text': json.dumps(next(values))}],
                'usage': {'input_tokens': 3, 'output_tokens': 2}}

    def openai(system, payload, **kwargs):
        calls.append(payload)
        return {'output': next(values), 'usage': {'input_tokens': 3, 'output_tokens': 2},
                'provider': 'openai', 'model': provider.MODEL}

    monkeypatch.setattr(agent, '_post_messages', anthropic)
    monkeypatch.setattr(provider, 'complete_json', openai)
    model = provider.MODEL if selected == 'openai' else 'claude-synthetic'
    return calls, model


@pytest.mark.parametrize('selected', ['anthropic', 'openai'])
@pytest.mark.parametrize('location', ['question', 'text', 'doi', 'locator', 'id'])
@pytest.mark.parametrize('sensitive', SENSITIVE)
def test_sensitive_input_blocks_all_providers_before_transport(selected, location, sensitive, monkeypatch):
    calls, model = model_transport(monkeypatch, selected, [])
    evidence = deepcopy(EVIDENCE)
    question = 'Synthetic question'
    if location == 'question':
        question = sensitive
    else:
        evidence[0][location] = sensitive
    original = deepcopy(evidence)
    result = agent.run_research_agent(question, evidence, api_key=KEY, model=model, provider=selected)
    assert result['status'] == 'BLOCKED'
    assert result['limitations'] == ['SENSITIVE_DATA_IN_INPUT']
    assert result['usage']['calls'] == 0 and not calls
    assert result['input_snapshot_sha256'] is None
    assert result['approved'] is False and result['executed'] is False
    assert sensitive not in json.dumps(result, ensure_ascii=False)
    assert evidence == original


@pytest.mark.parametrize('selected', ['anthropic', 'openai'])
@pytest.mark.parametrize('location', ['answer', 'limitations', 'critic_issues'])
@pytest.mark.parametrize('sensitive', SENSITIVE)
def test_sensitive_model_output_is_not_retransmitted_or_returned(selected, location, sensitive, monkeypatch):
    draft, critic = deepcopy(DRAFT), deepcopy(CRITIC)
    if location == 'answer':
        draft['answer'] = sensitive
    elif location == 'limitations':
        draft['limitations'] = [sensitive]
    else:
        critic['issues'] = [sensitive]
    calls, model = model_transport(monkeypatch, selected, [draft, critic])
    result = agent.run_research_agent('Synthetic question', deepcopy(EVIDENCE),
                                      api_key=KEY, model=model, provider=selected)
    expected_attempts = 2 if location == 'critic_issues' else 1
    assert result['status'] == 'BLOCKED' and result['answer'] == ''
    assert result['limitations'] == ['SENSITIVE_DATA_IN_MODEL_OUTPUT']
    assert result['usage']['calls'] == expected_attempts and len(calls) == expected_attempts
    assert sensitive not in json.dumps(result, ensure_ascii=False)
    assert all(sensitive not in json.dumps(payload, ensure_ascii=False) for payload in calls)
    assert result['approved'] is False and result['executed'] is False


@pytest.mark.parametrize('selected', ['anthropic', 'openai'])
def test_public_input_and_model_output_keep_two_role_behavior(selected, monkeypatch):
    calls, model = model_transport(monkeypatch, selected, [deepcopy(DRAFT), deepcopy(CRITIC)])
    result = agent.run_research_agent('Synthetic question', deepcopy(EVIDENCE),
                                      api_key=KEY, model=model, provider=selected)
    assert result['status'] == 'READY' and result['answer'] == DRAFT['answer']
    assert result['usage'] == {'calls': 2, 'input_tokens': 6, 'output_tokens': 4}
    assert len(calls) == 2 and result['input_snapshot_sha256']
    assert result['approved'] is False and result['executed'] is False


@pytest.mark.parametrize('sensitive', SENSITIVE)
def test_real_log_files_do_not_retain_sensitive_strings(sensitive, tmp_path):
    runtime_path, event_path = tmp_path / 'runtime.log', tmp_path / 'events.jsonl'
    runtime, audit = get_logger(str(runtime_path)), get_event_logger(str(event_path))
    runtime.info('Synthetic privacy probe: %s', sensitive)
    event(audit, 'SYNTHETIC_PRIVACY_PROBE', {'detail': sensitive, 'statistic': 2.75},
          claim_id='synthetic-claim', rows_used=20, state='BLOCKED')
    for logger in (runtime, audit):
        for handler in logger.handlers:
            handler.flush()
    runtime_text, audit_text = runtime_path.read_text('utf-8'), event_path.read_text('utf-8')
    assert sensitive not in runtime_text and sensitive not in audit_text
    assert 'SYNTHETIC_TEST_BODY' not in runtime_text + audit_text
    assert 'REDACTED' in runtime_text and 'REDACTED' in audit_text
    saved = json.loads(audit_text)
    message = json.loads(saved['message'])
    assert message['statistic'] == 2.75 and saved['rows_used'] == 20
    assert saved['event'] == 'SYNTHETIC_PRIVACY_PROBE' and saved['claim_id'] == 'synthetic-claim'
    assert saved['state'] == 'BLOCKED'


def test_structured_logging_redacts_nested_keys_and_values_without_mutating_source():
    email = 'reviewer@example.invalid'
    source = {'statistic': 2.75, 'details': [{email: 'synthetic role'}, {'contact': email}],
              'timestamp': 'synthetic activity clock', 'source_date': '2001-01-01'}
    original = deepcopy(source)
    cleaned = json.loads(_redact(source))
    assert email not in json.dumps(cleaned)
    assert cleaned['statistic'] == 2.75 and cleaned['source_date'] == '2001-01-01'
    assert 'timestamp' not in cleaned and source == original


def test_normal_logging_keeps_safe_context_and_numeric_values(tmp_path):
    path = tmp_path / 'normal.jsonl'
    logger = get_event_logger(str(path))
    event(logger, 'VERIFICATION_COMPLETE', {'t': 2.75, 'p': 0.04, 'n': 20, 'doi': '10.0000/synthetic'},
          claim_id='synthetic-claim', rows_used=20, state='PASS')
    for handler in logger.handlers:
        handler.flush()
    saved = json.loads(path.read_text('utf-8'))
    assert json.loads(saved['message']) == {'t': 2.75, 'p': 0.04, 'n': 20, 'doi': '10.0000/synthetic'}
    assert saved['rows_used'] == 20 and saved['state'] == 'PASS'


# [수정: 0 이영] 2026-10-01 03:11 KST — 같은 인증 라벨 탐지기를 입력/응답/로그/저장 모두에 적용하고 정제 표시·공개 수치·빈 설정의 정상 동작도 검증한다.
@pytest.mark.parametrize('value', ['password=""', "secret=''", 'api_key=[REDACTED]',
                                 {'password': '[REDACTED]', 'token': None},
                                 {'access_token': '', 'value': 2.75},
                                 {'n': 20, 't': 2.75, 'doi': '10.0000/synthetic'}])
def test_shared_detector_accepts_empty_redacted_and_public_values(value):
    assert sensitive_content_kinds(value) == ()


@pytest.mark.parametrize('sensitive', SENSITIVE)
@pytest.mark.parametrize('encoding', ['utf-8-sig', 'utf-16', 'utf-32'])
def test_text_upload_blocks_sensitive_content_across_supported_encodings(sensitive, encoding):
    original = sensitive.encode(encoding)
    with pytest.raises(ValueError) as failure:
        team.validate_upload('synthetic-note.txt', original)
    assert sensitive not in str(failure.value)
    assert original == sensitive.encode(encoding)


def test_upload_blocks_sensitive_filename_and_invalid_text_encoding():
    with pytest.raises(ValueError):
        team.validate_upload('reviewer@example.invalid.txt', b'synthetic')
    with pytest.raises(ValueError, match='UTF-8'):
        team.validate_upload('synthetic-note.txt', b'\xffinvalid-utf8')


@pytest.mark.parametrize('sensitive', SENSITIVE)
@pytest.mark.parametrize('location', ['title', 'note', 'snapshot', 'attachment'])
@pytest.mark.parametrize('remote', [False, True])
def test_workspace_blocks_sensitive_payload_before_any_write(sensitive, location, remote, monkeypatch, tmp_path):
    monkeypatch.setattr(team, 'member_role', lambda _: 'REVIEWER')
    calls = []
    monkeypatch.setattr(team.Workspace, '_request', lambda *a, **k: calls.append((a, k)))
    workspace = team.Workspace(tmp_path / 'workspace', repo='synthetic/repo' if remote else '',
                               token='Synthetic-Not-A-Usable-Token' if remote else '')
    values = {'title': 'Synthetic public task', 'note': 'Synthetic public note',
              'snapshot': {'n': 20, 't': 2.75}, 'files': ()}
    if location == 'attachment':
        values['files'] = [('synthetic-note.txt', sensitive.encode('utf-8'))]
    elif location == 'snapshot':
        values['snapshot'] = {'nested': [{'value': sensitive}], 'n': 20, 't': 2.75}
    else:
        values[location] = sensitive
    original = deepcopy(values)
    with pytest.raises(ValueError) as failure:
        workspace.save('이영', status='진행 중', **values)
    assert sensitive not in str(failure.value) and not calls
    assert values == original
    if not remote:
        with workspace._local_connection() as connection:
            assert connection.execute('SELECT COUNT(*) FROM updates').fetchone()[0] == 0


@pytest.mark.parametrize('remote', [False, True])
def test_workspace_public_task_preserves_snapshot_and_attachment(remote, monkeypatch, tmp_path):
    monkeypatch.setattr(team, 'member_role', lambda _: 'REVIEWER')
    calls = []
    monkeypatch.setattr(team.Workspace, '_request', lambda *a, **k: calls.append((a, k)))
    workspace = team.Workspace(tmp_path / 'workspace', repo='synthetic/repo' if remote else '',
                               token='Synthetic-Not-A-Usable-Token' if remote else '')
    snapshot = {'n': 20, 't': 2.75, 'p': 0.04, 'doi': '10.0000/synthetic'}
    attachment = b'value\n2.75\n'
    item_id = workspace.save('이영', 'Synthetic public task', '진행 중', note='Synthetic public note',
                             snapshot=snapshot, files=[('synthetic.csv', attachment)])
    assert len(item_id) == 32
    if remote:
        assert len(calls) == 1 and calls[0][0][1] == 'PUT'
    else:
        record = workspace.get(item_id)
        assert record['snapshot'] == snapshot
        assert record['files'][0]['size'] == len(attachment)
    assert snapshot == {'n': 20, 't': 2.75, 'p': 0.04, 'doi': '10.0000/synthetic'}


def test_legacy_sensitive_attachment_cannot_be_inherited_and_original_row_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(team, 'member_role', lambda _: 'REVIEWER')
    workspace = team.Workspace(tmp_path / 'workspace')
    item_id = 'a' * 32
    content = b'reviewer@example.invalid'
    legacy = {'id': item_id, 'at': '2001-01-01T00:00:00+00:00', 'title': 'Synthetic legacy',
              'status': '완료', 'note': 'Synthetic old note', 'verified_by': '이영',
              'snapshot': None, 'version': 1, 'supersedes': None,
              'files': [{'name': 'synthetic-note.txt', 'size': len(content),
                         'sha256': hashlib.sha256(content).hexdigest(),
                         'data': base64.b64encode(content).decode()}]}
    payload = json.dumps(legacy, ensure_ascii=False)
    with workspace._local_connection() as connection:
        connection.execute('INSERT INTO updates VALUES(?,?)', (item_id, payload))
    with pytest.raises(ValueError):
        workspace.save('이영', 'Synthetic new task', '진행 중', supersedes=item_id)
    with workspace._local_connection() as connection:
        rows = connection.execute('SELECT id,payload FROM updates').fetchall()
    assert rows == [(item_id, payload)]
