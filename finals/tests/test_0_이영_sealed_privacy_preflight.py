"""[0 이영 · Codex] 2026-10-01 05:04 KST — 봉인 비교의 인증정보 전송 전 차단 회귀.

수정 이유: 임시 합성 봉인과 모의 공급자로 공통 탐지기의 실제 전송·dry-run 경계를
검증한다. 원봉인·기대값을 보존하며 실제 모델·네트워크 호출은 하지 않는다.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "finals"), str(ROOT)]
import sealed_runner as runner

CANARY = "SYNTHETIC_CREDENTIAL_CANARY_ONLY"


class MockProvider:
    def __init__(self):
        self.calls = 0

    def __call__(self, system, body, **kwargs):
        self.calls += 1
        assert system == runner.GENERAL_SYSTEM
        return {
            "output": {"decision": "ARITHMETIC_MISMATCH", "calculated_value": 15,
                       "evidence_location": "Synthetic fixture paragraph 1", "reason": "MOCK_TEST_ONLY"},
            "provider": "mock", "model": "MOCK_TEST_ONLY", "mock": True,
            "request_id": "mock-privacy-preflight", "raw_sha256": "0" * 64,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }


@pytest.fixture(autouse=True)
def original_evidence_unchanged():
    # 원자료 보존도 각 회귀의 사후조건이다. 공개 합성 사례와 봉인 메타데이터만 읽는다.
    names = ("seal.json", "expected.json", "protocol.json", "packets/C03.json",
             "inputs/C03-source.txt", "inputs/C03-data.csv")
    before = {name: runner.sha((runner.EVIDENCE / name).read_bytes()) for name in names}
    yield
    assert before == {name: runner.sha((runner.EVIDENCE / name).read_bytes()) for name in names}


def make_bundle(tmp_path, *, field=None, text=""):
    evidence = tmp_path / "evidence"
    (evidence / "inputs").mkdir(parents=True)
    (evidence / "packets").mkdir()
    for name in ("C03-source.txt", "C03-data.csv"):
        shutil.copyfile(runner.EVIDENCE / "inputs" / name, evidence / "inputs" / name)
    for name in ("expected.json", "protocol.json"):
        shutil.copyfile(runner.EVIDENCE / name, evidence / name)
    packet = runner.load_packets(runner.EVIDENCE, ("C03",))["C03"]
    if field:
        packet[field] += " " + text
        if field == "source_text":
            raw = packet[field].encode("utf-8")
            (evidence / "inputs/C03-source.txt").write_bytes(raw)
            packet["registration"]["source_sha256"] = runner.sha(raw)
    runner.write(evidence / "packets/C03.json", packet)
    # 합성 변형을 시험 시작 전에 임시 폴더에만 봉인한다. 원프로토콜·기대값은 그대로 복사한다.
    runner.write(evidence / "seal.json", {"test_only": True, "files": {
        path.relative_to(evidence).as_posix(): runner.sha(path.read_bytes())
        for path in evidence.rglob("*") if path.is_file()
    }})
    expected = json.loads((evidence / "expected.json").read_text(encoding="utf-8"))
    return evidence, runner.load_packets(evidence, ("C03",)), expected


@pytest.mark.parametrize("label", ["password=", "access_token:", "secret="])
@pytest.mark.parametrize("field", ["question", "source_text"])
def test_credentials_stop_both_ai_paths_before_provider_call(tmp_path, field, label):
    evidence, packets, expected = make_bundle(tmp_path, field=field, text=label + CANARY)
    before = {p.relative_to(evidence).as_posix(): runner.sha(p.read_bytes())
              for p in evidence.rglob("*") if p.is_file()}
    provider = MockProvider()
    report = runner.run_sealed(packets, expected, provider, evidence_dir=evidence)
    assert provider.calls == report["provider_calls"] == 0
    assert report["comparison_valid"] and report["aborted"] is None
    ai_rows = [row for row in report["results"] if row["condition"] in runner.AI_CONDITIONS]
    assert len(ai_rows) == 2
    assert all(row["execution_status"] == "NOT_RUN"
               and row["blocker"] == "PERSONAL_DATA_IN_OUTBOUND_PAYLOAD" for row in ai_rows)
    assert CANARY not in json.dumps(report, ensure_ascii=False)
    assert CANARY not in runner.render_table(report, expected)
    assert before == {p.relative_to(evidence).as_posix(): runner.sha(p.read_bytes())
                      for p in evidence.rglob("*") if p.is_file()}


def test_dry_run_uses_fixed_kinds_without_reflecting_values_or_mutating_packets():
    packets = runner.load_packets(runner.EVIDENCE, ("C03",))
    packets["C03"]["question"] += " password=" + CANARY + " mock" + chr(64) + "example.invalid"
    before = deepcopy(packets)
    report = runner.dry_run(packets)
    assert report["cases"][0]["blocked_by_privacy"] == ["EMAIL", "CREDENTIAL_ASSIGNMENT"]
    rendered = json.dumps(report, ensure_ascii=False)
    assert CANARY not in rendered and "example.invalid" not in rendered
    assert packets == before


def test_public_input_is_allowed_and_calls_only_injected_mock(tmp_path):
    evidence, packets, expected = make_bundle(tmp_path)
    provider = MockProvider()
    assert runner.dry_run(packets)["cases"][0]["blocked_by_privacy"] == []
    report = runner.run_sealed(packets, expected, provider, evidence_dir=evidence, conditions=("general_ai",))
    assert provider.calls == report["provider_calls"] == 1 and report["comparison_valid"]
    result = next(row for row in report["results"] if row["condition"] == "general_ai")
    assert result["execution_status"] == "EXECUTED" and result["value"] == 15 and result["passed"]
    assert result["receipt"]["mock"] is True
