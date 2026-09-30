"""Synthetic-only checks for the opt-in private credential generator."""
# [작성: 0 이영] 2026-10-01 00:57 KST — 실제 암호 생성/출력 없이 mock 입력의 강도·해시·경로·배타 저장·실패 정리를 검증한다.
import importlib.util
from pathlib import Path
import tomllib
import pytest
from core import team_workspace as team

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("private_team_generator_test", ROOT / "tools/0_이영_팀접속설정.py")
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)
VALUES = [f"MockOnly-Generation-{n}-Input!" for n in range(4)]


def test_bundle_hashes_roles_individual_instructions_and_no_output(tmp_path, capsys):
    values = iter(VALUES)
    result = setup.generate_access_bundle(tmp_path, generator=lambda: next(values))
    config_text = result["configuration"].read_text(encoding="utf-8")
    config = tomllib.loads(config_text)["team"]
    assert config["roles"] == setup.ROLES
    assert set(config["password_hashes"]) == set(team.MEMBERS)
    assert len(result["member_instructions"]) == 4
    for member, password, path in zip(team.MEMBERS, VALUES, result["member_instructions"]):
        assert team.verify_password(password, config["password_hashes"][member])
        assert password not in config_text
        text = path.read_text(encoding="utf-8")
        assert member in text and password in text
        assert all(other not in text for other in VALUES if other != password)
    assert not setup.DEFAULT_TARGET.exists()
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_generator_retries_weak_and_duplicate_inputs(tmp_path):
    values = iter(["weak", VALUES[0], VALUES[0], *VALUES[1:]])
    result = setup.generate_access_bundle(tmp_path, generator=lambda: next(values))
    assert len(result["member_instructions"]) == 4


def test_generation_exhaustion_creates_no_files(tmp_path):
    with pytest.raises(ValueError):
        setup.generate_access_bundle(tmp_path, generator=lambda: "weak")
    assert not list(tmp_path.iterdir())


def test_exclusive_write_preserves_existing_file(tmp_path):
    p = tmp_path / "existing.txt"
    p.write_bytes(b"preserved")
    with pytest.raises(FileExistsError):
        setup._write_private_file(p, "replacement")
    assert p.read_bytes() == b"preserved"


def test_private_output_rejects_product_checkout():
    with pytest.raises(ValueError):
        setup.generate_access_bundle(ROOT / "private", generator=lambda: pytest.fail("Must reject before generation"))


def test_generate_main_outputs_paths_only_and_never_getpass(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(setup, "PRIVATE_ROOT", tmp_path)
    values = iter(VALUES)
    monkeypatch.setattr(setup.secrets, "token_urlsafe", lambda _: next(values))
    monkeypatch.setattr(setup.getpass, "getpass", lambda _: pytest.fail("Generate must not ask for a password"))
    assert setup.main(["--generate"]) == 0
    output = capsys.readouterr()
    assert len(output.out.splitlines()) == 5 and not output.err
    assert all(value not in output.out for value in VALUES)
    assert all(Path(line).is_file() for line in output.out.splitlines())


def test_failure_cleans_only_new_bundle(monkeypatch, tmp_path):
    existing = tmp_path / "preserved.txt"
    existing.write_bytes(b"preserved")
    original = setup._write_private_file
    calls = []
    def fail_second(target, content):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("Simulated private write failure")
        original(target, content)
    monkeypatch.setattr(setup, "_write_private_file", fail_second)
    values = iter(VALUES)
    with pytest.raises(OSError):
        setup.generate_access_bundle(tmp_path, generator=lambda: next(values))
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_bytes() == b"preserved"
