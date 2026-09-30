"""Real UI stage transitions; no implicit provider calls or inferred approval."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 사용자 단계·공백 근거·실패·수신/승인 구분을 실제 AppTest로 검증한다.
from pathlib import Path
from unittest.mock import Mock
import json

import pytest
from streamlit.testing.v1 import AppTest
from core import research_integration_router as router
from core import research_integration_intake as intake
from core import research_integration_feeds as feeds

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app(monkeypatch):
    monkeypatch.chdir(ROOT)
    for module, name in ((router, "search"), (router, "publication"), (router, "repository"),
                         (intake, "acquisition"), (intake, "acquisition_registered"), (feeds, "get_integration_feed")):
        monkeypatch.setattr(module, name, Mock(side_effect=AssertionError("implicit network")))
    return AppTest.from_file(str(ROOT / "0_이영_연구연동.py"), default_timeout=60).run()


def text(app):
    return "\n".join(str(e.value) for kind in ("markdown", "caption", "info", "warning", "error") for e in app.get(kind))


def test_initial_source_step_no_implicit_network(app):
    assert not app.exception
    assert app.session_state["ri_step"] == 1
    assert app.button(key="ri_source_next").disabled
    assert all(label in text(app) for label in ("근거 연결", "조건 확인", "지원 계산", "검토 기록"))
    router.search.assert_not_called()
    intake.acquisition.assert_not_called()
    feeds.get_integration_feed.assert_not_called()


def test_whitespace_source_never_opens_next_stage(app):
    app.text_input(key="ri_locator").set_value("   ").run()
    assert not app.exception
    assert app.session_state["ri_step"] == 1
    assert app.button(key="ri_source_next").disabled


def test_metadata_retrieval_is_not_download_or_approval(app, monkeypatch):
    monkeypatch.setattr(router, "repository", Mock(return_value={"ok": True, "items": [{"id": "7", "title": "Public metadata", "doi": "10.5281/zenodo.7", "version": "1", "files": [], "license": None}], "approved": False}))
    app.text_input(key="ri_identifier").set_value("7").run()
    app.button(key="ri_record_load").click().run()
    assert not app.exception
    assert app.button(key="ri_source_next").disabled
    assert "download" not in app.session_state["ri_state"]


def test_registered_acquisition_failure_stays_at_source(app, monkeypatch):
    monkeypatch.setattr(intake, "acquisition_registered", Mock(return_value={"success": False, "error": "CHECKSUM_MISMATCH", "receipt": {"approved": False}}))
    app.button(key="ri_registered_acquire").click().run()
    assert not app.exception
    assert app.session_state["ri_step"] == 1
    assert "CHECKSUM_MISMATCH" in text(app)
    assert not app.session_state["ri_state"].get("report")


def test_invalid_import_does_not_create_active_approval(app):
    app.text_area(key="ri_import_text").set_value(json.dumps({"approved": True})).run()
    app.button(key="ri_import").click().run()
    assert not app.exception
    assert "reopened" not in app.session_state["ri_state"]
