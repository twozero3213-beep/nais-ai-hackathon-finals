"""판정 이유 문장화와 화면 표시, 그리고 폐기 예정 Streamlit 인자 제거를 확인한다.

# [작성: 0 이영 · Claude] 2026-10-01 00:37 KST — 실제 브라우저 점검에서 (1) 이유가 영문 코드로만 보였고 (2) 서버 로그가 매 실행마다
# "use_container_width will be removed after 2025-12-31" 경고로 채워져 진짜 오류를 가리는 것을 확인했다.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

import pytest
from streamlit.testing.v1 import AppTest

FINALS = Path(__file__).resolve().parents[1]
ROOT = FINALS.parent
for path in (ROOT, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import finals_cases
import finals_explain as explain
import finals_provider


def test_known_codes_become_plain_korean_and_unknown_codes_are_kept_verbatim():
    assert "원문 지문이 달라" in explain.reason_text("ORIGINAL_SOURCE_UNAVAILABLE_OR_HASH_MISMATCH")
    # [수정: 0 이영 · Codex] 2026-10-01T03:02:04+09:00 — 기존 설명 회귀시험의 기대 문구를 조사 오류 수정에 맞춘다.
    assert explain.reason_text("CONDITION_MISMATCH_MISSING_POLICY") == "후보의 ‘결측 처리’ 항목이 등록된 조건과 다릅니다."
    assert "‘보고값’" in explain.reason_text("REGISTERED_FIELD_MISMATCH_REPORTED_VALUE")
    assert "(503)" in explain.reason_text("MODEL_HTTP_503")
    assert explain.reason_text("SOMETHING_NEW_AND_UNKNOWN") == "SOMETHING_NEW_AND_UNKNOWN"
    # [수정: 0 이영 · Codex] 2026-10-01T03:02:04+09:00 — 알 수 없는 필드 이름을 보존하는 기존 설명 시험의 문구를 맞춘다.
    assert explain.reason_text("CONDITION_MISMATCH_UNSEEN") == "후보의 ‘UNSEEN’ 항목이 등록된 조건과 다릅니다."


def test_reasons_are_deduplicated_in_order_across_report_sections():
    report = {"errors": ["SCHEMA_INVALID"], "validation": {"errors": ["CONDITION_MISMATCH_COLUMN", "SCHEMA_INVALID"]},
              "remaining_issues": ["CONDITION_MISMATCH_COLUMN", "사람의 원문·의미 연결 확인 대기"]}
    lines = explain.reasons(report)
    assert lines == [explain.reason_text("SCHEMA_INVALID"), explain.reason_text("CONDITION_MISMATCH_COLUMN"), "사람의 원문·의미 연결 확인 대기"]
    assert explain.reasons({}) == []


def test_calculation_summary_covers_match_conflict_and_denominator_mismatch():
    base = {"executed": True, "calculated_value": 344, "reported_value": 344, "delta": 0, "tolerance": 0,
            "within_tolerance": True, "selected_rows": 344, "expected_denominator": 344, "denominator_matches": True}
    assert explain.calculation_summary(base) == "계산값 344 · 보고값 344 · 차이 0(허용오차 0) — 허용오차 안에서 일치합니다. 선택한 344행이 선언한 분모와 같습니다."
    conflict = dict(base, calculated_value=343.0, delta=1.0, within_tolerance=False, selected_rows=343, denominator_matches=False)
    text = explain.calculation_summary(conflict)
    # [수정: 0 이영 · Codex] 2026-10-01T03:02:04+09:00 — 기존 분모 불일치 설명 시험의 기대 문구를 맞춘다.
    assert "계산값 343" in text and "허용오차를 벗어났습니다" in text and "분모(344)와 다릅니다" in text
    assert explain.calculation_summary({"executed": False}) is None
    assert explain.calculation_summary(None) is None
    assert explain.calculation_summary(dict(base, calculated_value="x")) is None


@pytest.fixture
def app_factory(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(finals_provider, "availability", lambda: {"available": False, "configured": False, "model": "gpt-4.1-mini", "live_allowed": False})

    def create(case_id):
        app = AppTest.from_file(str(FINALS / "app.py"), default_timeout=60).run()
        app.selectbox(key="fin_case_select").set_value(case_id).run()
        app.button(key="fin_manual_load").click().run()
        app.button(key="fin_compute").click().run()
        assert not app.exception
        return app

    return create


def _text(app):
    return " ".join(str(getattr(element, "value", "")) for element in list(app.markdown) + list(app.text))


def test_screen_explains_why_a_case_is_held(app_factory):
    app = app_factory("MISSING-PUBLISHER")
    assert "판정 이유" in _text(app)
    assert "원문 지문이 달라" in _text(app)


def test_screen_summarises_a_supported_case(app_factory):
    app = app_factory("NORMAL-PENG-ROWS")
    assert "허용오차 안에서 일치합니다" in _text(app)


def test_deprecated_container_width_argument_is_gone_from_shipped_ui_code():
    offenders = [str(p.relative_to(ROOT)) for p in list((ROOT / "finals").glob("*.py")) + list((ROOT / "core").glob("*_ui.py"))
                 if re.search(r"use_container_width", p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_change_summary_explains_what_changed_and_is_empty_without_a_change():
    # [수정: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:13:04+09:00 — 자료 변경 장면이 무엇이 바뀌었는지 문장으로 보여 주는지 확인한다.
    assert explain.change_summary(None) == [] and explain.change_summary({"changed_input": {"detected": False}}) == []
    report = {"changed_input": {"detected": True, "prior_input_sha256": "a" * 64, "current_input_sha256": "b" * 64, "removed_rows": 1},
              "formal_verification": {"calculated": 343}, "calculation": {"reported_value": 344},
              "human_approval": {"previous_approval": {"approved": True}}}
    lines = explain.change_summary(report)
    assert any("aaaaaaaaaaaa" in line and "bbbbbbbbbbbb" in line for line in lines)
    assert any("1행" in line and "원본 파일은 바뀌지 않았습니다" in line for line in lines)
    assert any("343" in line and "344" in line and "다릅니다" in line for line in lines)
    assert any("승인은 해제" in line for line in lines)
    report["human_approval"] = {"previous_approval": {}}
    assert any("해제할 이전 사람 승인은 없었습니다" in line for line in explain.change_summary(report))


def test_change_scene_replaces_the_contradictory_match_sentence_with_what_changed(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(finals_provider, "availability", lambda: {"available": False, "configured": False, "model": finals_provider.MODEL})
    app = AppTest.from_file(str(FINALS / "app.py"), default_timeout=60).run()
    normal = next(case for case in finals_cases.list_cases() if case["category"] == "normal")
    if app.selectbox(key="fin_case_select").value != normal["id"]:
        app.selectbox(key="fin_case_select").set_value(normal["id"]).run()
    app.button(key="fin_manual_load").click().run()
    app.button(key="fin_compute").click().run()
    before = " ".join(item.value for item in app.markdown)
    assert "무엇이 바뀌었나" not in before                                  # 변경 전에는 설명이 없다
    app.button(key="fin_change").click().run()
    assert not app.exception
    text = " ".join(item.value for item in app.markdown)
    assert "무엇이 바뀌었나" in text and "1행이 빠졌습니다" in text
    written = [item.value for item in app.markdown if "허용오차 안에서 일치합니다" in item.value]
    assert written == []                                                     # 차단 판정 옆에 '일치합니다'를 본문으로 쓰지 않는다
    assert any("변경 전 계산(참고용" in caption.value for caption in app.caption)

# [3 조지현 · 2026-10-01T02:13:04+09:00] 통합 후 추가 주석의 원작성 시각을 확인할 수 없어 미확인 표시; 실제 검토 시각과 원표기를 분리 기록한다.
