"""[01 이채우][작업번호 1] 승인 차단을 단계 기록과 한국어 판정 이유에 연결한다. 실제 모델 시험이 아니다."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest

for path in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import finals_cases as cases
import finals_pipeline as pipeline
import finals_explain as explain

@pytest.mark.parametrize('ready,issues,expected_codes', [
    (False, [], ['CRITIQUE_EVIDENCE_NOT_READY']),
    (True, ['Unresolved source mapping'], ['CRITIQUE_UNRESOLVED_ISSUES']),
    (True, [], []),
])
def test_critique_decision_is_visible_without_changing_approval(ready, issues, expected_codes):
    outputs = [cases.load_case('NORMAL-PENG-ROWS')['manual_proposal'], {'evidence_ready': ready, 'issues': issues}]
    calls = []
    def provider(*args, **kwargs):
        output = deepcopy(outputs[len(calls)])
        calls.append(1)
        return {'output': output, 'provider': 'mock', 'model': 'MOCK_TEST_ONLY', 'mock': True,
                'usage': {'input_tokens': 1, 'output_tokens': 1}, 'elapsed_ms': 0,
                'request_id': 'mock-test', 'raw_sha256': '0' * 64}
    report = pipeline.run_case_ai('NORMAL-PENG-ROWS', provider=provider)
    assert report['calculation']['within_tolerance']
    assert report['can_approve'] is (not expected_codes)
    assert not report['human_approval']['approved'] and not report['actual_model_output']
    stage = next(step for step in report['steps'] if step['step'] == 'critique')
    assert stage['status'] == ('BLOCKED' if expected_codes else 'PASS')
    for code in expected_codes:
        assert code in report['remaining_issues']
        assert explain.reason_text(code) != code
        assert explain.reason_text(code) in explain.reasons(report)
