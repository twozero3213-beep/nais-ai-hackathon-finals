"""[0 이영] 수정 이유: 실제 등록 자료로 수동 검산·직접 승인·변경 차단·재열기 UI 동선을 검사한다."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from streamlit.testing.v1 import AppTest

FINALS = Path(__file__).resolve().parents[1]
ROOT = FINALS.parent
for path in (ROOT, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import finals_cases
import finals_provider


@pytest.fixture
def app_factory(monkeypatch):
    # 수정 이유: UI 검산에는 실제 자료·파이프라인을 쓰고 모델 외부 호출은 이 시험에서 발생시키지 않는다.
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(finals_provider, "availability", lambda: {"available":False,"configured":False,"model":"gpt-4.1-mini"})

    def create(category="normal"):
        app = AppTest.from_file(str(FINALS / "app.py"), default_timeout=60).run()
        assert not app.exception
        item = next(case for case in finals_cases.list_cases() if case["category"] == category)
        if app.selectbox(key="fin_case_select").value != item["id"]:
            app.selectbox(key="fin_case_select").set_value(item["id"]).run()
        assert not app.exception
        return app

    return create


def compute(app):
    app.button(key="fin_manual_load").click().run()
    assert not app.exception
    assert app.text_area(key="fin_candidate_text").value.strip()
    app.button(key="fin_compute").click().run()
    assert not app.exception
    return app.session_state["fin_report"]


def approve(app):
    assert app.button(key="fin_approve").disabled
    app.checkbox(key="fin_human_confirm").set_value(True).run()
    assert app.button(key="fin_approve").disabled
    app.text_area(key="fin_reason").set_value("공개 원문과 여섯 분석 조건을 대조하고 검산값을 직접 확인했습니다.").run()
    assert not app.button(key="fin_approve").disabled
    app.button(key="fin_approve").click().run()
    assert not app.exception
    return app.session_state["fin_report"]


def test_registered_cases_visible_and_unavailable_ai_keeps_manual_path(app_factory):
    app = app_factory()
    assert len(finals_cases.list_cases()) == 8
    # [수정: 0 이영] 2026-09-30 23:54 KST — 참고 UI를 적용한 실제 검산 화면 제목·조건 안내를 확인한다.
    assert "다시 계산해 볼까요" in app.title[0].value
    assert any("분석 조건" in item.value for item in app.caption)
    assert not app.button(key="fin_manual_load").disabled
    assert app.button(key="fin_compute").disabled
    app.radio(key="fin_mode").set_value("실시간 AI").run()
    assert not app.exception
    assert app.button(key="fin_live_generate").disabled
    assert any("수동" in item.value for item in app.info)
    app.radio(key="fin_mode").set_value("수동 작성").run()
    assert not app.button(key="fin_manual_load").disabled


def test_normal_manual_calculation_requires_direct_confirmation_and_reason(app_factory):
    app = app_factory()
    report = compute(app)
    assert report["can_approve"] is True
    assert report["human_approval"]["status"] == "PENDING"
    assert report.get("calculation")
    approved = approve(app)
    assert approved["human_approval"]["status"] == "APPROVED"
    assert any("직접 승인 완료" in item.value for item in app.markdown)
    assert any(item.label == "검산 보고서 JSON 내려받기" for item in app.get("download_button"))


@pytest.mark.parametrize("category", ["mismatch", "evidence_missing", "data_changed"])
def test_blocked_conditions_never_enable_approval(app_factory, category):
    app = app_factory(category)
    report = compute(app)
    assert report["can_approve"] is False
    assert report["human_approval"]["status"] != "APPROVED"
    app.checkbox(key="fin_human_confirm").set_value(True).run()
    app.text_area(key="fin_reason").set_value("확인 사유를 적어도 불일치나 근거 부족을 승인으로 바꾸지 않습니다.").run()
    assert app.button(key="fin_approve").disabled
    assert not app.exception


def test_editing_candidate_invalidates_calculation_and_approval(app_factory):
    app = app_factory()
    compute(app)
    approve(app)
    candidate = json.loads(app.text_area(key="fin_candidate_text").value)
    candidate["unit"] = "확인되지 않은 변경 단위"
    app.text_area(key="fin_candidate_text").set_value(json.dumps(candidate,ensure_ascii=False)).run()
    assert not app.exception
    assert "fin_report" not in app.session_state
    assert app.session_state["fin_human_confirm"] is False
    assert not any(item.label == "검산 보고서 JSON 내려받기" for item in app.get("download_button"))


def test_changed_input_blocks_reuse_after_approval(app_factory):
    app = app_factory()
    compute(app)
    approve(app)
    app.button(key="fin_change").click().run()
    assert not app.exception
    report = app.session_state["fin_report"]
    assert report["can_approve"] is False
    assert report["human_approval"]["status"] != "APPROVED"
    assert app.checkbox(key="fin_human_confirm").value is False
    assert app.button(key="fin_approve").disabled


def test_report_reopens_as_record_without_new_approval(app_factory):
    app = app_factory()
    compute(app)
    original = approve(app)
    exported = app.session_state["fin_exported_report"]
    assert json.loads(exported)["export_integrity_sha256"]
    app.text_area(key="fin_reopen_text").set_value(exported).run()
    app.button(key="fin_reopen").click().run()
    assert not app.exception
    reopened = app.session_state["fin_reopened"]
    assert reopened["human_approval"]["approved"] is False
    assert reopened["human_approval"]["active"] is False
    assert any("새로운 사람 승인" in item.value for item in app.caption)
    app.text_area(key="fin_reopen_text").set_value(json.dumps(original,ensure_ascii=False)).run()
    app.button(key="fin_reopen").click().run()
    assert not app.exception
    assert app.session_state["fin_reopened"]["can_approve"] is False
    assert app.session_state["fin_reopened"]["human_approval"]["active"] is False
    tampered = json.loads(exported)
    tampered["contributor_version"] = 99
    app.text_area(key="fin_reopen_text").set_value(json.dumps(tampered,ensure_ascii=False)).run()
    app.button(key="fin_reopen").click().run()
    assert not app.exception
    assert any("보고서 검증 지문이 맞지 않습니다" in item.value for item in app.error)
    assert app.session_state["fin_reopened"]["human_approval"]["active"] is False


def test_replay_requires_saved_actual_response(app_factory, monkeypatch):
    import finals_pipeline
    monkeypatch.setattr(finals_pipeline, "list_replays", lambda: [])
    app = app_factory()
    app.radio(key="fin_mode").set_value("저장 응답 재생").run()
    assert not app.exception
    assert app.button(key="fin_replay_run").disabled
    assert any("저장된 실제 AI 응답이 없습니다" in item.value for item in app.info)
