# [수정: 0 이영 · Codex] 2026-10-01T03:51:17+09:00 — 동기화 폴더에서 AppTest 초기읽기3초 초과를 실제 확인해 UI시험 대기만60초로 통일; 인증 assertion은 유지한다. 공개 경로명 표현 정리: 2026-10-01T05:47:00+09:00.
"""Test-only fixtures: setup safety and real Streamlit authentication boundary."""
# [작성: 0 이영] 2026-09-30 22:52 KST — 모의 비밀값으로 누락설정·오입력·네 팀원 로그인·로그아웃·권한 경계를 검증합니다.
import importlib.util
from pathlib import Path
import tomllib

import pytest
from streamlit.testing.v1 import AppTest
from core import team_workspace as team
from core.rbac import can

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("team_setup_for_tests", ROOT / "tools/0_이영_팀접속설정.py")
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)

# 실제 접속용 비밀번호가 아닌 시험 전용 입력입니다. 생성 도구의 기본값으로 사용하지 않습니다.
MOCK_VALUES = {member: f"FixtureOnly-{index}-Input!" for index, member in enumerate(team.MEMBERS)}
# [수정: 0 이영] 2026-09-30 22:55 KST — Windows AppTest 임시 파일의 기본 인코딩 문제를 피하도록 시험 앱 문자열만 ASCII로 작성합니다. 실제 한국어 로그인 UI는 그대로 검증합니다.
_LOGIN_APP = """
import streamlit as st
from core.team_workspace import require_member, member_role
who = require_member()
st.write('authenticated: ' + who)
st.write('role: ' + member_role(who))
"""


@pytest.fixture(autouse=True)
def no_local_auth_bypass(monkeypatch):
    monkeypatch.delenv("EVIDENCE_GATE_LOCAL_MODE", raising=False)
    monkeypatch.delenv("EVIDENCE_GATE_LOCAL_ROLE", raising=False)


@pytest.fixture(scope="module")
def hashes():
    return {member: team.password_hash(value) for member, value in MOCK_VALUES.items()}


@pytest.fixture
def auth_config(monkeypatch, hashes):
    value = {"password_hashes": hashes, "roles": setup.ROLES}
    monkeypatch.setattr(team, "settings", lambda: value)
    return value


def _button(app, label):
    return next(button for button in app.button if button.label == label)


@pytest.mark.parametrize("invalid", ["", "   ", "short!1A", "abcdefghijklmnop", "Aaaaaaaaaaaaaaa", "StrongInput1!\n"])
def test_rejects_empty_weak_or_control_password(invalid):
    with pytest.raises(ValueError):
        setup.validate_password(invalid)


def test_generated_secrets_have_only_individual_hashes_and_expected_roles(tmp_path, capsys):
    values = iter(value for member in team.MEMBERS for value in (MOCK_VALUES[member], MOCK_VALUES[member]))
    target = tmp_path / ".streamlit/secrets.toml"
    setup.create_secrets(target, reader=lambda _: next(values))
    text = target.read_text(encoding="utf-8")
    config = tomllib.loads(text)["team"]
    assert set(config["password_hashes"]) == set(team.MEMBERS)
    assert config["roles"] == setup.ROLES
    for member, value in MOCK_VALUES.items():
        assert value not in text
        assert team.verify_password(value, config["password_hashes"][member])
    assert can(config["roles"]["이영"], "approve")
    assert all(not can(config["roles"][member], "approve") for member in team.MEMBERS if member != "이영")
    assert "EVIDENCE_GATE_LOCAL_MODE" not in text
    captured = capsys.readouterr()
    assert all(value not in captured.out + captured.err for value in MOCK_VALUES.values())


def test_existing_secret_file_is_preserved_before_prompt(tmp_path):
    target = tmp_path / "secrets.toml"
    target.write_bytes(b"preserve-existing-file")
    def forbidden_reader(_):
        raise AssertionError("Existing files must be rejected before asking for input")
    with pytest.raises(FileExistsError):
        setup.create_secrets(target, reader=forbidden_reader)
    assert target.read_bytes() == b"preserve-existing-file"


def test_confirmation_mismatch_and_duplicate_password_are_retried(monkeypatch, hashes, capsys):
    first, second, third, fourth = [MOCK_VALUES[member] for member in team.MEMBERS]
    values = iter(["", first, "different-confirmation", first, first,
                   first, first, second, second, third, third, fourth, fourth])
    reverse = {value: member for member, value in MOCK_VALUES.items()}
    monkeypatch.setattr(setup, "password_hash", lambda value: hashes[reverse[value]])
    assert setup.collect_password_hashes(lambda _: next(values)) == hashes
    errors = capsys.readouterr().err
    assert "비어" in errors and "일치" in errors and "서로 다른" in errors
    assert all(value not in errors for value in MOCK_VALUES.values())


def test_interrupted_setup_creates_no_secret_file(tmp_path):
    target = tmp_path / ".streamlit/secrets.toml"
    def cancelled(_):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        setup.create_secrets(target, reader=cancelled)
    assert not target.exists()


def test_example_is_safe_and_actual_secrets_are_ignored():
    example = tomllib.loads((ROOT / ".streamlit/secrets.toml.example").read_text(encoding="utf-8"))
    assert not example["team"]["password_hashes"]
    assert example["team"]["roles"] == setup.ROLES
    assert ".streamlit/secrets.toml" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("configured_members", [(), team.MEMBERS[:3]])
def test_login_stops_when_configuration_is_missing(monkeypatch, hashes, configured_members):
    monkeypatch.setattr(team, "settings", lambda: {"password_hashes": {member: hashes[member] for member in configured_members}})
    app = AppTest.from_string(_LOGIN_APP, default_timeout=60).run()
    assert not app.exception
    assert any("팀원 4명" in error.value for error in app.error)
    assert "authenticated_member" not in app.session_state
    assert not app.button


def test_wrong_password_cannot_authenticate(auth_config):
    app = AppTest.from_string(_LOGIN_APP, default_timeout=60).run()
    app.text_input[0].set_value("incorrect-test-input")
    _button(app, "로그인").click().run()
    assert not app.exception
    assert "authenticated_member" not in app.session_state
    assert any("비밀번호를 확인" in error.value for error in app.error)
    assert not any("authenticated:" in text.value for text in app.markdown)


@pytest.mark.parametrize("member", team.MEMBERS)
def test_member_can_login_and_logout_with_approval_role_preserved(auth_config, member):
    app = AppTest.from_string(_LOGIN_APP, default_timeout=60).run()
    assert not app.exception
    assert any("팀 로그인" in title.value for title in app.title)
    app.selectbox[0].select(member).run()
    app.text_input[0].set_value(MOCK_VALUES[member])
    _button(app, "로그인").click().run()
    assert not app.exception
    assert app.session_state["authenticated_member"] == member
    assert team.member_role(member) == setup.ROLES[member]
    assert can(team.member_role(member), "approve") == (member == "이영")
    _button(app, "로그아웃").click().run()
    assert not app.exception
    assert "authenticated_member" not in app.session_state
    assert any("팀 로그인" in title.value for title in app.title)


# [작성: 0 이영] 2026-09-30 22:55 KST — 숨김 입력 불가능한 환경과 입력 중 다른 설정 생성에도 비밀 파일을 덮어쓰지 않는지 확인합니다.
def test_noninteractive_terminal_refuses_password_collection(monkeypatch, tmp_path):
    from types import SimpleNamespace
    target = tmp_path / "secrets.toml"
    monkeypatch.setattr(setup, "DEFAULT_TARGET", target)
    monkeypatch.setattr(setup.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    def forbidden_getpass(_):
        raise AssertionError("Noninteractive input must be rejected")
    monkeypatch.setattr(setup.getpass, "getpass", forbidden_getpass)
    assert setup.main() == 2
    assert not target.exists()


def test_file_created_during_password_entry_is_not_overwritten(tmp_path, monkeypatch, hashes):
    target = tmp_path / "secrets.toml"
    values = iter(value for member in team.MEMBERS for value in (MOCK_VALUES[member], MOCK_VALUES[member]))
    reverse = {value: member for member, value in MOCK_VALUES.items()}
    monkeypatch.setattr(setup, "password_hash", lambda value: hashes[reverse[value]])
    def competing_reader(_):
        if not target.exists():
            target.write_bytes(b"created-by-another-session")
        return next(values)
    with pytest.raises(FileExistsError):
        setup.create_secrets(target, reader=competing_reader)
    assert target.read_bytes() == b"created-by-another-session"
