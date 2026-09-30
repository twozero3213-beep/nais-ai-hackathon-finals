"""공개 연구 데스크의 호출 경계·6탭·세션 과제·비밀 비노출 회귀."""
# [작성: 0 이영 · Codex] 2026-09-30 KST — 공개 버튼 흐름과 오류의 비밀 비노출을 실제 AppTest로 확인한다.
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from core import paper_discovery, research_data_sources, research_news

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "0_이영_웹사이트.py"
PAPER_BUTTON = "FormSubmitter:desk_paper_search-논문 찾아볼게요"
DATA_BUTTON = "FormSubmitter:desk_data_search-이 출처에서 찾아볼게요"
TASK_BUTTON = "FormSubmitter:desk_task_form-과제로 저장할게요"
STAMP = "2026-09-30T13:55:00+00:00"


@pytest.fixture(autouse=True)
def no_implicit_network(monkeypatch):
    st.cache_data.clear()
    for module, name in [(paper_discovery, "search_papers"), (research_data_sources, "search_research_data"),
                         (research_news, "fetch_research_news")]:
        monkeypatch.setattr(module, name, Mock(side_effect=AssertionError("Unexpected network call")))


def app():
    result = AppTest.from_file(str(SITE)).run(timeout=45)
    assert not result.exception
    return result


def visible(result):
    return "\n".join(str(item.value) for kind in ["markdown", "caption", "text", "info", "warning", "error"]
                     for item in result.get(kind))


def test_all_six_tabs_render_without_implicit_search():
    result = app()
    assert [t.label for t in result.tabs] == ["논문 둘러보기", "공공·위성 데이터", "연구 과제", "대학 연구 소식", "연구 관심 순위", "다른 AI와 연결"]
    paper_discovery.search_papers.assert_not_called()
    research_data_sources.search_research_data.assert_not_called()
    research_news.fetch_research_news.assert_not_called()
    text = visible(result)
    assert "보관된 검색 스냅샷" in text and "실시간 갱신 아님" in text
    assert "최근 1년 인용 수나 연구 품질 점수" in text
    assert "8/8" not in text and "실행 대기 · 저장만 완료" not in text
    assert all(item.value != "None" for item in result.get("code"))


def test_paper_button_live_result_and_empty_are_distinct(monkeypatch):
    provider = Mock(return_value={"query": "bounded public query", "checked_at": STAMP, "items": []})
    monkeypatch.setattr(paper_discovery, "search_papers", provider)
    result = app()
    result.text_input(key="desk_query_AI_None").set_value("bounded public query")
    result.button(key=PAPER_BUTTON).click().run(timeout=45)
    assert not result.exception
    provider.assert_called_once_with("bounded public query", mode="latest", years=1, limit=8)
    assert "실시간 API 조회 결과" in visible(result) and "조건에 맞는 논문이 없어요" in visible(result)


def test_provider_exception_never_discloses_raw_secret(monkeypatch):
    private = "sk-testSensitiveExceptionValue123456"
    monkeypatch.setattr(paper_discovery, "search_papers", Mock(side_effect=RuntimeError(private)))
    result = app()
    result.button(key=PAPER_BUTTON).click().run(timeout=45)
    assert not result.exception and private not in visible(result)
    assert "보관된 검색 스냅샷" in visible(result)
    assert "논문을 불러오지 못했어요" in visible(result)


def test_private_search_not_sent_to_external_provider():
    result = app()
    result.text_input(key="desk_query_AI_None").set_value("private-contact@example.test")
    result.button(key=PAPER_BUTTON).click().run(timeout=45)
    assert not result.exception
    paper_discovery.search_papers.assert_not_called()


def test_data_button_empty_is_a_real_lookup(monkeypatch):
    provider = Mock(return_value={"status": "EMPTY", "checked_at": STAMP, "items": []})
    monkeypatch.setattr(research_data_sources, "search_research_data", provider)
    result = app()
    result.button(key=DATA_BUTTON).click().run(timeout=45)
    assert not result.exception
    provider.assert_called_once_with("world_bank", "", limit=5, mode="observations")
    assert "조회했지만 조건에 맞는 기록이 없었어요" in visible(result)


def test_news_button_uses_official_backend_and_empty_message(monkeypatch):
    provider = Mock(return_value={"as_of": STAMP, "articles": []})
    monkeypatch.setattr(research_news, "fetch_research_news", provider)
    result = app()
    result.button(key="desk_news_load").click().run(timeout=45)
    assert not result.exception
    provider.assert_called_once_with("mit")
    assert "실시간 RSS/API 조회 결과" in visible(result) and "표시할 소식이 없어요" in visible(result)


def test_task_is_session_saved_without_execution_and_private_task_rejected():
    result = app()
    result.text_area(key="desk_task_question").set_value("공개 펭귄 자료 행 수를 비교해 주세요.")
    result.text_input(key="desk_task_query").set_value("penguins")
    result.button(key=TASK_BUTTON).click().run(timeout=45)
    assert not result.exception
    tasks = result.session_state["desk_tasks"]
    assert len(tasks) == 1 and tasks[0]["status"] == "실행 대기 · 저장만 완료"
    assert "저장한 과제 내려받기" in [d.label for d in result.get("download_button")]
    private = "sk-testPrivateTaskValue123456"
    result.text_area(key="desk_task_question").set_value(private)
    result.button(key=TASK_BUTTON).click().run(timeout=45)
    assert len(result.session_state["desk_tasks"]) == 1
    assert private not in visible(result)


def test_exported_snapshot_contains_no_contact_or_credential_and_no_mock_case():
    spec = importlib.util.spec_from_file_location("desk_boundary", ROOT / "0_이영_연구데스크.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = module.SNAPSHOT.read_text(encoding="utf-8")
    email_found = bool(module.EMAIL.search(raw))
    credential_found = bool(module.SECRET_PATTERN.search(raw))
    assert email_found is False and credential_found is False
    assert '"actual"' not in raw and '"expected"' not in raw
    assert module._safe_url("https://example.org/?api_key=private") is None
    assert module._safe_url("https://example.org/a") == "https://example.org/a"
