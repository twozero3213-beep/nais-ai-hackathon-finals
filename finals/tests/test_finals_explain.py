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
    assert explain.reason_text("CONDITION_MISMATCH_MISSING_POLICY") == "후보의 ‘결측 처리’이(가) 등록된 조건과 다릅니다."
    assert "‘보고값’" in explain.reason_text("REGISTERED_FIELD_MISMATCH_REPORTED_VALUE")
    assert "(503)" in explain.reason_text("MODEL_HTTP_503")
    assert explain.reason_text("SOMETHING_NEW_AND_UNKNOWN") == "SOMETHING_NEW_AND_UNKNOWN"
    assert explain.reason_text("CONDITION_MISMATCH_UNSEEN") == "후보의 ‘UNSEEN’이(가) 등록된 조건과 다릅니다."


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
    assert "계산값 343" in text and "허용오차를 벗어났습니다" in text and "분모 344와 다릅니다" in text
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
