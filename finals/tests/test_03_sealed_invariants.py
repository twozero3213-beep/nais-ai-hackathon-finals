"""[3 조지현 · 2026-10-01T03:16:35+09:00] 독립 재현한 채점·조건·동일 입력 문제의 회귀 시험.
수정 이유: 모의 응답으로 경계 동작을 확인하며 실제 AI 성능과 사람 승인 증거를 만들지 않는다.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'finals'), str(ROOT)]
import sealed_runner as runner

EXPECTED = json.loads((runner.EVIDENCE / 'expected.json').read_text())
SOURCE = ('Group A has 2 rows. Group B has 2 rows. The mean of score in points for group A is 15. '
          'There are no missing values; use missing policy error.')


class Mock:
    def __init__(self, proposal=None, general=None, callback=None):
        self.proposal, self.general = proposal or {}, general or {}
        self.callback, self.bodies = callback, []

    def __call__(self, system, body, **kwargs):
        self.bodies.append(deepcopy(body))
        reg = body['registration']
        if system == runner.GENERAL_SYSTEM:
            output = {'decision': 'ARITHMETIC_MISMATCH', 'calculated_value': 15,
                      'evidence_location': 'Synthetic fixture paragraph 1', 'reason': 'MOCK_TEST_ONLY'}
            output.update(self.general)
        else:
            output = {'method': 'mean', 'column': 'score', 'filters': [{'column': 'group', 'value': 'A'}],
                      'missing_policy': 'error', 'denominator': 'Group A has 2 rows', 'unit': 'points', 'unresolved': [],
                      'field_evidence': {field: [SOURCE] for field in runner.SIX_CONDITIONS}}
            output.update(self.proposal)
        if self.callback:
            self.callback(system, body)
        return {'output': output, 'provider': 'mock', 'model': 'MOCK_TEST_ONLY', 'mock': True,
                'request_id': 'mock-invariants', 'usage': {'input_tokens': 1, 'output_tokens': 1}, 'raw_sha256': '0' * 64}


@pytest.fixture
def bundle(tmp_path):
    evidence = tmp_path / 'evidence'
    (evidence / 'inputs').mkdir(parents=True)
    (evidence / 'packets').mkdir()
    for cid in ('C03', 'C04', 'C06'):
        for name in (f'{cid}-source.txt', f'{cid}-data.csv'):
            shutil.copyfile(runner.EVIDENCE / 'inputs' / name, evidence / 'inputs' / name)
        shutil.copyfile(runner.EVIDENCE / 'packets' / f'{cid}.json', evidence / 'packets' / f'{cid}.json')
    for name in ('expected.json', 'protocol.json'):
        shutil.copyfile(runner.EVIDENCE / name, evidence / name)
    # 테스트 전용 부분 묶음도 실제 봉인 검사로 검증한다. 원래 전체 봉인을 변경하지 않는다.
    runner.write(evidence / 'seal.json', {'test_only': True, 'files': {
        p.relative_to(evidence).as_posix(): runner.sha(p.read_bytes()) for p in evidence.rglob('*') if p.is_file()}})
    return evidence


@pytest.fixture
def grounded(bundle):
    # [수정: 3 조지현 · 2026-10-01T03:44:46+09:00] 이영의 여섯 조건 원문 인용 계약을 만족하는 별도 합성 시험 묶음을 만든다. 실제 봉인 원본은 수정하지 않는다.
    packet = runner.load_packets(bundle, ('C03',))['C03']
    source = SOURCE.encode('utf-8')
    (bundle / 'inputs/C03-source.txt').write_bytes(source)
    packet['source_text'] = SOURCE
    packet['registration'].update(source_sha256=runner.sha(source), source_quote=SOURCE)
    runner.write(bundle / 'packets/C03.json', packet)
    seal = json.loads((bundle / 'seal.json').read_text())
    for name in ('inputs/C03-source.txt', 'packets/C03.json'):
        seal['files'][name] = runner.sha((bundle / name).read_bytes())
    runner.write(bundle / 'seal.json', seal)
    return bundle


def row(report, condition):
    return next(r for r in report['results'] if r['condition'] == condition)


def run(evidence, provider, cid='C03'):
    return runner.run_sealed(runner.load_packets(evidence, (cid,)), EXPECTED, provider, evidence_dir=evidence)


@pytest.mark.parametrize('decision', ['BLOCK', 'STALE_BLOCK'])
@pytest.mark.parametrize('value', [7, True, '7', float('nan'), float('inf')])
def test_block_requires_null_value_even_when_decision_matches(decision, value):
    result = runner.score(decision, value, {'action': decision, 'value': None})
    assert result['decision_correct'] and not result['value_correct'] and not result['passed']
    assert not result['stopping_correct']
    assert runner.score(decision, None, {'action': decision, 'value': None})['passed']


def test_correct_stop_with_invented_number_is_not_counted_as_pass(bundle):
    report = run(bundle, Mock(general={'decision': 'BLOCK', 'calculated_value': 7}), 'C06')
    result = row(report, 'general_ai')
    assert result['claimed_number_on_blocked_case'] and not result['passed']
    assert report['summary']['general_ai']['passed'] == 0 and report['summary']['general_ai']['failed'] == 1
    assert '숫자 주장 오류' in runner.render_table(report, EXPECTED)


def test_unresolved_alone_stops_without_engine_call(grounded, monkeypatch):
    called = []
    real = runner.audit_with
    def audit(*args, **kwargs):
        called.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(runner, 'audit_with', audit)
    report = run(grounded, Mock(proposal={'unresolved': ['분모 확인 대기']}))
    result = row(report, 'with_llm')
    assert result['decision'] == 'BLOCK' and result['value'] is None and result['proposed_conditions'] is None
    assert len(called) == 1  # 모델 없는 경로만 계산했고 미해결 제안의 계산은 실행하지 않았다.


@pytest.mark.parametrize('values', [('A', 'B'), ('A', 'A')])
def test_duplicate_filter_columns_are_rejected_not_overwritten(grounded, values):
    report = run(grounded, Mock(proposal={'filters': [{'column': 'group', 'value': v} for v in values]}))
    result = row(report, 'with_llm')
    assert result['decision'] == 'BLOCK' and result['value'] is None and result['proposed_conditions'] is None


@pytest.mark.parametrize('proposal', [
    {'column': ''}, {'filters': [{'column': '', 'value': 'A'}]},
    {'method': None}, {'missing_policy': None}, {'unresolved': ['']}, {'unresolved': None},
])
def test_required_or_malformed_conditions_never_reach_calculation(grounded, proposal):
    result = row(run(grounded, Mock(proposal=proposal)), 'with_llm')
    assert result['execution_status'] in ('EXECUTED', 'ERROR')
    if result['execution_status'] == 'EXECUTED':
        assert result['decision'] == 'BLOCK' and result['value'] is None
    assert not result['passed']


def test_absent_semantic_contract_is_visible_and_not_inferred(grounded):
    result = row(run(grounded, Mock(proposal={'denominator': 'unknown population', 'unit': 'unverified unit'})), 'with_llm')
    assert result['value'] is None and result['decision'] == 'BLOCK'  # 원문에 없는 단위·분모는 인용 계약에서도 차단한다.
    semantics = result['semantic_validation']
    assert not semantics['verified'] and not semantics['blocking_issues']
    assert {v['status'] for v in semantics['fields'].values()} == {'NOT_VERIFIED'}
    assert semantics['fields']['unit']['proposed'] == 'unverified unit'
    report = run(grounded, Mock())
    assert report['summary']['with_llm']['semantics_not_verified'] == 1
    assert '의미 미검증' in runner.render_table(report, EXPECTED)


@pytest.mark.parametrize('proposal,status', [
    ({'denominator': 'filtered_rows', 'unit': 'points'}, 'MATCH'),
    ({'denominator': None, 'unit': None}, 'UNKNOWN'),
    ({'denominator': 'all_rows', 'unit': 'years'}, 'MISMATCH'),
])
def test_registered_semantic_contracts_are_checked_exactly(proposal, status):
    result = runner.semantic_review(proposal, {'denominator': 'filtered_rows', 'unit': 'points'})
    assert {v['status'] for v in result['fields'].values()} == {status}
    assert result['verified'] is (status == 'MATCH')
    assert bool(result['blocking_issues']) is (status != 'MATCH')


def test_semantic_contract_mismatch_blocks_calculation(grounded):
    packets = runner.load_packets(grounded, ('C03',))
    packets['C03']['registration'].update(denominator='all_rows', unit='years')
    # 수정 이유: 새 의미 계약은 시험용 사본에만 등록하고 원래 정답·입력은 보존한다.
    runner.write(grounded / 'packets/C03.json', packets['C03'])
    # 새 시험 계약은 모의 실행 전에 별도 시험 사본을 봉인한다. 원봉인은 그대로 유지한다.
    seal = json.loads((grounded / 'seal.json').read_text())
    seal['files']['packets/C03.json'] = runner.sha((grounded / 'packets/C03.json').read_bytes())
    runner.write(grounded / 'seal.json', seal)
    report = runner.run_sealed(packets, EXPECTED, Mock(), evidence_dir=grounded)
    result = row(report, 'with_llm')
    assert result['decision'] == 'BLOCK' and result['value'] is None
    assert result['semantic_validation']['blocking_issues'] == ['DENOMINATOR_CONTRACT_MISMATCH', 'UNIT_CONTRACT_MISMATCH']


@pytest.mark.parametrize('target', ['inputs/C03-data.csv', 'inputs/C03-source.txt', 'packets/C03.json', 'expected.json', 'protocol.json', 'seal.json'])
def test_midrun_input_change_invalidates_all_rows_and_stops_calls(bundle, target):
    def change(system, body):
        path = bundle / target
        path.write_bytes(path.read_bytes() + b'\n')
    mock = Mock(callback=change)
    report = run(bundle, mock)
    assert not report['comparison_valid'] and report['aborted'] == 'SEALED_INPUT_CHANGED_DURING_RUN'
    assert len(mock.bodies) == 1 and report['provider_calls'] == 1
    assert row(report, 'with_llm')['execution_status'] == 'NOT_RUN'
    assert row(report, 'without_llm')['value'] == 15  # 수정 이유: 관측값은 보존하되 승패 총계에서 제외한다.
    assert all(not r['comparison_valid'] for r in report['results'])
    assert all(s['passed'] == s['failed'] == s['valid_executed'] == 0 for s in report['summary'].values())
    assert report['summary']['general_ai']['input_tokens'] == 1  # 수정 이유: 이미 발생한 모의 사용량도 기록한다.
    assert '비교 무효' in runner.render_table(report, EXPECTED)


def test_provider_mutating_its_body_does_not_change_next_condition_or_caller(grounded):
    packets = runner.load_packets(grounded, ('C03',)); before = deepcopy(packets)
    def mutate(system, body):
        body['registration']['filters']['group'] = 'B'
        packets['C03']['current_csv'] = 'caller changed after snapshot'
    mock = Mock(callback=mutate)
    report = runner.run_sealed(packets, EXPECTED, mock, evidence_dir=grounded)
    assert report['comparison_valid'] and report['provider_calls'] == 2
    assert mock.bodies[0] == mock.bodies[1]
    assert before['C03']['registration']['filters'] == {'group': 'A'}
    assert row(report, 'with_llm')['value'] == 15
    assert row(report, 'general_ai')['input_sha256'] == row(report, 'with_llm')['input_sha256']


def test_deterministic_engine_only_reads_snapshot(grounded, monkeypatch):
    real = runner.audit_with; roots = []
    def audit(registration, evidence_dir, *args, **kwargs):
        roots.append(Path(evidence_dir))
        assert Path(evidence_dir) != grounded
        assert (Path(evidence_dir) / registration['data_file']).read_bytes() == (grounded / registration['data_file']).read_bytes()
        return real(registration, evidence_dir, *args, **kwargs)
    monkeypatch.setattr(runner, 'audit_with', audit)
    report = run(grounded, Mock())
    assert report['comparison_valid'] and len(roots) == 2 and roots[0] == roots[1]
    assert all(row(report, c)['passed'] for c in ('without_llm', 'general_ai', 'with_llm'))


def test_packet_and_csv_mismatch_stops_before_provider(bundle):
    packets = runner.load_packets(bundle, ('C03',)); packets['C03']['current_csv'] += 'A,999\n'
    mock = Mock(); report = runner.run_sealed(packets, EXPECTED, mock, evidence_dir=bundle)
    assert not report['comparison_valid'] and report['aborted'] == 'SEALED_PACKET_INPUT_MISMATCH'
    assert mock.bodies == [] and all(s['passed'] == 0 for s in report['summary'].values())


def test_consistently_changed_packet_still_fails_original_seal(bundle):
    # 파일과 본문을 함께 바꿔도 봉인 지문을 만족하지 않으면 실행을 시작하지 않는다.
    packet = runner.load_packets(bundle, ('C03',))
    changed = b'group,score\nA,90\nA,100\nB,30\nB,40\n'
    (bundle / 'inputs/C03-data.csv').write_bytes(changed)
    packet['C03']['current_csv'] = changed.decode()
    packet['C03']['current_data_sha256'] = runner.sha(changed)
    runner.write(bundle / 'packets/C03.json', packet['C03'])
    mock = Mock()
    report = runner.run_sealed(packet, EXPECTED, mock, evidence_dir=bundle)
    assert not report['comparison_valid'] and report['aborted'] == 'SEALED_INPUT_CHANGED_BEFORE_RUN'
    assert mock.bodies == []


@pytest.mark.parametrize('cid,changed', [
    ('C07', b'group,score\nA,10\nA,20\nB,30\n'),
    ('C08', b'group,score\r\nA,10\r\nA,20\r\nB,30\r\nB,40\r\n'),
])
def test_predeclared_stale_input_is_valid_comparison_not_midrun_mutation(bundle, cid, changed):
    # [수정: 3 조지현 · 2026-10-01T03:44:46+09:00] 사전 고정한 자료 변경 사례와 실행 중 입력 변경을 구분한다. 원래 C07/C08 정답은 유지한다.
    packet = runner.load_packets(bundle, ('C03',))['C03']
    packet['case_id'] = packet['registration']['claim_id'] = cid
    packet['current_csv'] = changed.decode()
    packet['current_data_sha256'] = runner.sha(changed)
    (bundle / 'inputs/C03-data.csv').write_bytes(changed)
    seal = json.loads((bundle / 'seal.json').read_text())
    seal['files']['inputs/C03-data.csv'] = runner.sha(changed)
    runner.write(bundle / 'seal.json', seal)
    mock = Mock(general={'decision': 'STALE_BLOCK', 'calculated_value': None})
    report = runner.run_sealed({cid: packet}, EXPECTED, mock, evidence_dir=bundle, conditions=('general_ai',))
    assert report['comparison_valid'] and report['aborted'] is None
    assert row(report, 'without_llm')['decision'] == 'STALE_BLOCK'
    assert row(report, 'without_llm')['value'] is None and row(report, 'without_llm')['passed']
    assert row(report, 'general_ai')['passed']


def test_new_rules_and_original_expected_have_separate_fingerprints(bundle):
    frozen = (bundle / 'expected.json').read_bytes()
    report = run(bundle, Mock())
    assert report['expected_sha256'] == runner.sha(runner.canonical(EXPECTED))
    assert report['evaluation_rules_sha256'] == runner.sha(runner.canonical(runner.EVALUATION_RULES))
    assert (bundle / 'expected.json').read_bytes() == frozen
    assert len(report['input_snapshot_sha256']) == 64


def test_main_uses_real_seal_and_returns_failure_on_input_change(bundle, tmp_path, capsys):
    def change(system, body):
        (bundle / 'inputs/C03-data.csv').write_bytes(b'changed')
    output = tmp_path / 'results'
    code = runner.main(['--evidence-dir', str(bundle), '--cases', 'C03', '--results-dir', str(output)], provider=Mock(callback=change))
    assert code == 1
    record = json.loads(next(output.glob('*/results.json')).read_text())
    assert not record['comparison_valid'] and record['aborted'] == 'SEALED_INPUT_CHANGED_DURING_RUN'
    assert record['contributor_version'] == 3 and record['execution_source'] == 'INJECTED_PROVIDER_NOT_LIVE_MODEL_PROOF'
    assert record['summary']['general_ai']['passed'] == 0


@pytest.mark.parametrize('ids', [('C03', 'C03'), ('../../secret',), ('C99',), ()])
def test_only_registered_unique_case_ids_can_be_loaded(ids):
    with pytest.raises(ValueError, match='INVALID_REGISTERED_CASE_SELECTION'):
        runner.load_packets(runner.EVIDENCE, ids)
