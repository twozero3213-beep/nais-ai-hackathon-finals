"""[3 조지현] 이채우 검토 묶음 취합 후 검토 보류·재생 범위 경계.
모의 AI 시험과 과거 저장 제안의 재검산이며 새 모델 호출/사람 승인은 아니다.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / 'finals'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import finals_cases as cases
import finals_pipeline as pipeline
import finals_explain as explain


def blocked_provider(*args, **kwargs):
    output = (cases.load_case('NORMAL-PENG-ROWS')['manual_proposal']
              if 'Propose' in args[0] else {'evidence_ready': False, 'issues': ['Source mapping requires review']})
    return {'output': deepcopy(output), 'provider': 'mock', 'model': 'MOCK_TEST_ONLY', 'mock': True,
            'usage': {'input_tokens': 1, 'output_tokens': 1}, 'request_id': 'mock', 'raw_sha256': '0' * 64}


def test_matching_arithmetic_with_unresolved_critique_has_review_blocked_state():
    report = pipeline.run_case_ai('NORMAL-PENG-ROWS', provider=blocked_provider)
    assert report['calculation']['within_tolerance']
    assert report['state'] == report['status'] == 'REVIEW_BLOCKED'
    assert not report['can_approve']
    assert any('검토 보류' in text for text in explain.review_summary(report))
    assert not report['human_approval']['approved']


def test_critique_is_rechecked_at_approval_even_when_display_flag_is_changed():
    report = pipeline.run_case_ai('NORMAL-PENG-ROWS', provider=blocked_provider)
    report['can_approve'] = True
    with pytest.raises(ValueError, match='APPROVAL_CRITIQUE_UNRESOLVED'):
        pipeline.approve_report(report, 'AUTOMATED_TEST_ONLY: review unresolved', confirmed=True)


def test_real_proposal_replay_does_not_claim_original_critique_is_replayed():
    replay = cases.list_replays()[0]
    report = pipeline.run_case('NORMAL-PENG-ROWS', mode='replay', replay_path=replay['path'])
    assert report['state'] == 'SUPPORTED_PREVIEW'
    assert report['replay_provenance']['scope'] == 'PROPOSAL_ONLY'
    assert report['replay_provenance']['original_critique_replayed'] is False
    assert report['replay_provenance']['input_bindings_verified'] is True
    assert not report['provider_calls'] and not report['llm_executed']
    assert not report['human_approval']['approved']
    assert any('원실행의 AI 검토' in text for text in explain.review_summary(report))


@pytest.mark.parametrize('field', ['case_id', 'input_sha256', 'source_sha256'])
def test_replay_for_other_or_unbound_inputs_is_rejected(monkeypatch, tmp_path, field):
    item = json.loads(Path(cases.list_replays()[0]['path']).read_text())
    item[field] = 'WRONG_CASE' if field == 'case_id' else '0' * 64
    path = tmp_path / 'test_replay.json'
    path.write_text(json.dumps(item))
    monkeypatch.setattr(pipeline, 'list_replays', lambda: [{'path': str(path)}])
    report = pipeline.run_case('NORMAL-PENG-ROWS', mode='replay', replay_path=str(path))
    assert report['errors'] == ['REPLAY_INPUT_MISMATCH']
    assert not report['calculation']['executed'] and not report['can_approve']


def test_replay_without_binding_is_rejected(monkeypatch, tmp_path):
    item = json.loads(Path(cases.list_replays()[0]['path']).read_text())
    item.pop('input_sha256')
    path = tmp_path / 'test_replay.json'; path.write_text(json.dumps(item))
    monkeypatch.setattr(pipeline, 'list_replays', lambda: [{'path': str(path)}])
    assert pipeline.run_case('NORMAL-PENG-ROWS', mode='replay', replay_path=str(path))['errors'] == ['REPLAY_INPUT_UNBOUND']


def test_screen_shows_review_hold_as_warning_without_green_preview(monkeypatch):
    monkeypatch.chdir(ROOT)
    app = AppTest.from_file(str(ROOT / 'finals/app.py'), default_timeout=60).run()
    app.session_state['fin_report'] = pipeline.run_case_ai('NORMAL-PENG-ROWS', provider=blocked_provider)
    app.run()
    assert not app.exception
    assert any('AI 검토 보류' in x.value for x in app.warning)
    assert not any('조건 검산 완료' in x.value for x in app.success)
    assert app.button(key='fin_approve').disabled
