"""[3 조지현] 화면 경로의 자료·원문·분석 조건 승인 및 재열기 결속 경계.
자동화 합성 승인 시험이며 실제 사람 승인·모델 비교가 아니다.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
from streamlit.testing.v1 import AppTest
FINALS=Path(__file__).resolve().parents[1]
for p in (FINALS.parent,FINALS):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
import finals_pipeline as pipeline


def test_approval_records_all_three_current_bindings():
    report=pipeline.run_case_manual('NORMAL-BAT-MEAN')
    expected={'data_sha256':report['input_sha256'],'source_sha256':report['source_sha256'],'proposal_sha256':report['proposal_sha256']}
    assert report['input_bindings']==expected
    approved=pipeline.approve_report(report,'AUTOMATED_TEST_ONLY: 등록 합성 검토 확인',confirmed=True)
    assert approved['human_approval']['input_bindings']==expected
    reopened=pipeline.reopen_report(pipeline.export_report(approved))
    assert reopened['human_approval']['active'] is False


@pytest.mark.parametrize('field',['input_sha256','source_sha256','proposal_sha256'])
def test_missing_or_changed_record_binding_blocks_approval(field):
    original=pipeline.run_case_manual('NORMAL-BAT-MEAN')
    for value in (None,'0'*64):
        report=deepcopy(original)
        if value is None:report.pop(field)
        else:report[field]=value
        with pytest.raises(ValueError,match='APPROVAL_INPUT_CHANGED'):
            pipeline.approve_report(report,'AUTOMATED_TEST_ONLY: 입력 확인',confirmed=True)


def test_source_change_blocks_approval_and_reopen_with_same_csv(monkeypatch):
    report=pipeline.run_case_manual('NORMAL-BAT-MEAN');case=pipeline.load_case('NORMAL-BAT-MEAN')
    changed=deepcopy(case);changed['source_sha256']='0'*64
    monkeypatch.setattr(pipeline,'load_case',lambda _:changed)
    with pytest.raises(ValueError,match='APPROVAL_INPUT_CHANGED'):
        pipeline.approve_report(report,'AUTOMATED_TEST_ONLY: 변경 전 기록',confirmed=True)
    reopened=pipeline.reopen_report(pipeline.export_report(report))
    assert reopened['state']=='BLOCKED_CHANGED_INPUT'
    assert not reopened['human_approval']['active']


def test_tampered_binding_map_never_approves_even_with_valid_scalar_fields():
    report=pipeline.run_case_manual('NORMAL-BAT-MEAN')
    report['input_bindings']={'data_sha256':report['input_sha256'],'source_sha256':'0'*64,'proposal_sha256':report['proposal_sha256']}
    with pytest.raises(ValueError,match='APPROVAL_INPUT_CHANGED'):
        pipeline.approve_report(report,'AUTOMATED_TEST_ONLY: 위조된 대응',confirmed=True)
    assert pipeline.reopen_report(pipeline.export_report(report))['state']=='BLOCKED_CHANGED_INPUT'


def test_legacy_report_without_new_map_remains_review_only():
    report=pipeline.run_case_manual('NORMAL-BAT-MEAN');report.pop('input_bindings',None)
    reopened=pipeline.reopen_report(pipeline.export_report(report))
    assert reopened['state']=='IMPORTED_REVIEW'
    assert not reopened['human_approval']['active'] and not reopened['can_approve']


def test_screen_displays_all_three_bindings_after_real_bat_calculation(monkeypatch):
    monkeypatch.chdir(FINALS.parent)
    app=AppTest.from_file(str(FINALS/'app.py'),default_timeout=60).run()
    app.selectbox(key='fin_case_select').set_value('NORMAL-BAT-MEAN').run()
    # [수정: 0 이영 · Codex] 2026-10-01 03:29 KST — 3 조지현의 세 지문 검증을 실제 네 단계 사용자 경로에 맞추고 계산 전 확인을 우회하지 않는다.
    app.button(key='fin_source_next').click().run()
    app.button(key='fin_manual_load').click().run()
    app.button(key='fin_conditions_next').click().run()
    app.button(key='fin_compute').click().run()
    assert not app.exception
    report=app.session_state['fin_report']
    assert set(report['input_bindings'])=={'data_sha256','source_sha256','proposal_sha256'}
    assert any('승인에 연결된 자료·원문·분석 조건' in x.label for x in app.expander)
    assert not report['human_approval']['approved']


def test_notice_document_references_resolve_to_tracked_evidence():
    # [3 조지현] 사용자 안내가 미게시 내부 문서를 가리키는 회귀를 막는다.
    import re
    import finals_notice
    paths=re.findall(r'docs/[^\s·]+\.md',finals_notice.DOCUMENT_REFERENCE)
    assert paths
    for path in paths:
        assert (FINALS.parent/path).is_file(),path


@pytest.mark.parametrize('calculated,reported',[(1.00000000001,1.0),(49.320000000001,49.32)])
def test_changed_values_not_declared_equal_due_to_display_rounding(calculated,reported):
    # [3 조지현] 표시용 반올림이 수치 일치 판단으로 쓰여 실제 차이를 숨기는 경계를 확인한다.
    from finals_explain import change_summary
    report={'changed_input':{'detected':True},'formal_verification':{'calculated':calculated},'calculation':{'reported_value':reported}}
    assert any('다릅니다' in line for line in change_summary(report))
