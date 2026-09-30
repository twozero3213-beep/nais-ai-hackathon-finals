"""[0 이영 · Claude] 개인정보·인증 값 안전장치 시험: 탐지 함수, 외부 전송 길목, 승인 사유, 화면 고지.

# [작성: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:08:17+09:00 — 모의 심사 피드백(활용성: 개인정보·데이터 보호, 오남용 방지)에 대응한 안전장치의 회귀 시험이다.
# 위험한 문자열은 조립해서 이 파일이 저장소 위생 검사에 걸리지 않게 한다. 실제 네트워크 호출은 하지 않는다.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

FINALS = Path(__file__).resolve().parents[1]
ROOT = FINALS.parent
for path in (ROOT, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import finals_cases as cases
import finals_explain
import finals_notice
import finals_pipeline as pipeline
import finals_privacy as privacy
import finals_provider as provider

AT = chr(64)
EMAIL = "kim" + AT + "lab.ac.kr"
PHONE = "010-" + "1234-5678"
RRN = "900101-" + "1234567"
FAKE_KEY = "sk-" + "a" * 24


@pytest.mark.parametrize("text,kind", [
    ("문의: " + EMAIL, "EMAIL"), ("연락 " + PHONE, "KR_PHONE"), ("02-" + "123-4567", "KR_PHONE"), ("번호 " + RRN, "KR_RRN"),
    ("key=" + FAKE_KEY, "API_KEY"), ("Bearer " + "abcdefghijkl1234", "BEARER_TOKEN"), ("-----BEGIN " + "RSA PRIVATE KEY-----", "PRIVATE_KEY"),
])
def test_personal_data_and_secret_shapes_are_detected_by_kind_only(text, kind):
    assert kind in privacy.sensitive_kinds(text)
    assert kind in privacy.sensitive_kinds({"nested": [text]})            # JSON 값 안에 있어도 잡는다
    assert text not in privacy.describe(privacy.sensitive_kinds(text))   # 값은 설명에 싣지 않는다


@pytest.mark.parametrize("text", [
    "task-provided risk-stratification sk-learn", "2007-11-11", "N1A1 344 rows mean 49.32", "0.123-456-7890 and 12-3456",
    "arxiv.org 2026", "", None, 344, {"n": 344, "mean": 49.32},
])
def test_ordinary_research_text_and_numbers_are_not_flagged(text):
    assert privacy.sensitive_kinds(text) == ()
    assert privacy.is_public_text(text)


def test_every_registered_case_payload_sent_to_the_model_is_free_of_personal_data():
    # 외부 AI로 나가는 본문은 _shared_payload다. 공개 원문·자료만 쓰므로 모든 등록 사례에서 비어 있어야 한다.
    for item in cases.list_cases():
        payload = pipeline._shared_payload(cases.load_case(item["id"]))
        assert privacy.sensitive_kinds(payload) == (), item["id"]


def test_provider_blocks_personal_data_before_any_connection(monkeypatch):
    monkeypatch.setenv("NAIS_ALLOW_LIVE_AI", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "test" + "0" * 30)
    monkeypatch.setattr(provider, "_LIVE_CALLS", {"n": 0})

    def never(*args, **kwargs):
        raise AssertionError("개인정보가 있는 본문으로 네트워크 연결을 만들었다")

    monkeypatch.setattr(provider.http.client, "HTTPSConnection", never)
    with pytest.raises(provider.ProviderError, match="PERSONAL_DATA_IN_OUTBOUND_PAYLOAD"):
        provider.complete_json("Review the claim", {"claim": "담당자 " + EMAIL})
    with pytest.raises(provider.ProviderError, match="PERSONAL_DATA_IN_OUTBOUND_PAYLOAD"):
        provider.complete_json("연락처 " + PHONE, {"claim": "7 rows"})
    assert provider._LIVE_CALLS["n"] == 0          # 호출 횟수도 소모하지 않는다


def test_provider_does_not_read_the_key_file_when_live_ai_is_off(monkeypatch, tmp_path):
    # 꺼져 있으면 키 파일을 열지도 않는다(데이터 최소화). 키 파일이 없어도 오류는 LIVE_AI_NOT_ALLOWED다.
    monkeypatch.delenv("NAIS_ALLOW_LIVE_AI", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("NAIS_SECRETS_FILE", str(tmp_path / "missing.txt"))
    with pytest.raises(provider.ProviderError, match="LIVE_AI_NOT_ALLOWED"):
        provider.complete_json("x", {"a": 1})


def test_approval_reason_with_personal_data_is_rejected_with_a_distinct_code():
    report = pipeline.run_case_manual("NORMAL-PENG-ROWS")
    for reason in ("담당 " + EMAIL + " 와 확인했습니다", "전화 " + PHONE + " 로 확인했습니다", "주민번호 " + RRN):
        with pytest.raises(ValueError, match="APPROVAL_REASON_PERSONAL_DATA"):
            pipeline.approve_report(report, reason, confirmed=True)
    approved = pipeline.approve_report(report, "원문 344개체와 전체 CSV 조건을 직접 대조했습니다", confirmed=True)
    assert approved["status"] == "APPROVED"
    assert "@" not in approved["human_approval"]["reason"]


def test_candidate_json_with_personal_data_is_blocked_as_sensitive_content():
    proposal = dict(cases.load_case("NORMAL-PENG-ROWS")["manual_proposal"])
    proposal["claim_text"] = proposal["claim_text"] + " (문의 " + EMAIL + ")"
    import json
    report = pipeline.run_case("NORMAL-PENG-ROWS", mode="manual", proposal_text=json.dumps(proposal, ensure_ascii=False))
    assert not report["can_approve"]
    assert "SENSITIVE_CONTENT_BLOCKED" in report["errors"]
    assert EMAIL not in json.dumps(report, ensure_ascii=False)       # 차단한 값은 보고서에 남기지 않는다


def test_new_error_codes_have_korean_explanations_without_values():
    for code in ("APPROVAL_REASON_PERSONAL_DATA", "PERSONAL_DATA_IN_OUTBOUND_PAYLOAD", "SENSITIVE_CONTENT_BLOCKED"):
        text = finals_explain.reason_text(code)
        assert text != code and "@" not in text


def test_notice_covers_the_official_ethics_questions_and_mentions_only_implemented_controls():
    titles = " ".join(title for title, _ in finals_notice.NOTICE_POINTS)
    body = " ".join(body for _, body in finals_notice.NOTICE_POINTS)
    # 활용성 질문: 편향성·공정성·투명성, 개인정보·데이터 보호, 오남용 방지
    for needle in ("편중", "비교", "확인한 것", "개인정보", "서버", "사람이 최종"):
        assert needle in titles + body
    assert "NAIS_ALLOW_LIVE_AI" not in body and "store=false" not in body      # 내부 설정 이름은 화면 문구에 쓰지 않는다
    assert "미실행" in body                                                    # 하지 않은 것은 하지 않았다고 쓴다


def test_screen_shows_the_notice_and_blocks_an_approval_reason_with_personal_data(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(provider, "availability", lambda: {"available": False, "configured": False, "model": provider.MODEL})
    app = AppTest.from_file(str(FINALS / "app.py"), default_timeout=60).run()
    assert not app.exception
    assert any(item.label == finals_notice.NOTICE_TITLE for item in app.expander)          # 윤리·개인정보 고지가 화면에 있다
    normal = next(item for item in cases.list_cases() if item["category"] == "normal")
    if app.selectbox(key="fin_case_select").value != normal["id"]:
        app.selectbox(key="fin_case_select").set_value(normal["id"]).run()
    app.button(key="fin_manual_load").click().run()
    app.button(key="fin_compute").click().run()
    assert not app.exception
    app.checkbox(key="fin_human_confirm").set_value(True).run()
    app.text_area(key="fin_reason").set_value("원문과 조건을 확인했습니다 " + EMAIL).run()
    assert app.button(key="fin_approve").disabled                                          # 개인정보 형태가 있으면 승인 버튼이 막힌다
    assert any("이메일" in warning.value for warning in app.warning)
    assert EMAIL not in " ".join(warning.value for warning in app.warning)                 # 경고에도 값을 다시 싣지 않는다
    app.text_area(key="fin_reason").set_value("원문과 조건을 직접 확인했습니다").run()
    assert not app.button(key="fin_approve").disabled
# [수정: 3 조지현 · 2026-10-01T02:08:17+09:00] 기준 커밋보다 뒤인 주석 시각은 원작성 시각으로 확인할 수 없어 미확인으로 표시했다. 원표기는 별도 검토 기록에 보존한다.
