"""[1 이채우] 공개 BAT 논문의 두 기술통계를 검산한다. 모델 호출·사람 승인 없음.

원자료를 수정하지 않는다. 출력은 새 디렉터리에만 기록한다.
이 실행은 등록 조건 대조이며 AI 성능 비교나 논문 전체 재현이 아니다.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evidence_gate.gate import evaluate
from evidence_gate.spec import empty_spec
from finals.finals_cases import load_case
from finals.finals_pipeline import run_case_manual, export_report, reopen_report

KST = timezone(timedelta(hours=9))
PROTOCOL = {
    "contributor": "1 이채우",
    "paper_doi": "10.1371/journal.pone.0149458",
    "paper_url": "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0149458",
    "author_revision": "b02a0e302e36717b095abf9b1586a7398704f014",
    "source_location": "Results / Identification of BAT positive patients",
    "data_sha256": "a3771cdaaecb24adedb61df55537c4c0d670456182b8e0f286e56182e3349c28",
    "filter": {"Readout.bat": "1"}, "column": "Age.y",
    "expected_n": 53, "reported_mean": "49.32", "tolerance": "0.005",
    "missing_policy": "error", "unit": "years",
    "scope": "Registered conditions, two descriptive statistics; not a blinded evaluation",
    "controlled_checks": ["registered filter change blocks", "saved report tampering blocks"],
    "model_calls": 0, "human_approval": "NOT_PERFORMED",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(KST).isoformat(timespec="seconds")
    # [1 이채우] 실제 계산 전에 보고값·허용오차·입력 지문을 파일로 고정한다.
    write_json(output / "1_protocol.json", PROTOCOL)
    protocol_hash = sha((output / "1_protocol.json").read_bytes())
    started = perf_counter()
    case = load_case("NORMAL-BAT-MEAN")
    raw = case["data_bytes"]
    if sha(raw) != PROTOCOL["data_sha256"]:
        raise ValueError("REGISTERED_DATA_HASH_MISMATCH")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    selected = [r for r in rows if r["Readout.bat"] == "1"]
    missing = sum(not r["Age.y"].strip() for r in selected)
    if missing:
        raise ValueError("AGE_MISSING")
    total_age = sum((Decimal(r["Age.y"]) for r in selected), Decimal(0))
    mean = total_age / len(selected)
    duplicate_ids = len(selected) - len({r["Study.ID"] for r in selected})
    claims = []
    for claim_id, method, reported, tolerance in (
        ("BAT-POSITIVE-N", "row_count", 53, 0),
        ("BAT-POSITIVE-MEAN-AGE", "mean", 49.32, 0.005),
    ):
        report = run_case_manual(claim_id)
        spec = empty_spec(claim_id)
        spec.update(method=method, reported_value=reported,
                    variable="Age.y" if method == "mean" else None,
                    filters=[{"column": "Readout.bat", "operator": "eq", "value": "1"}],
                    missing_policy="error" if method == "mean" else "not_applicable",
                    missing_tokens=["", "NA"], denominator="BAT positive records; n=53",
                    unit="years" if method == "mean" else "records",
                    data_fingerprint=sha(raw), tolerance=tolerance,
                    source_location={"source_id": PROTOCOL["paper_doi"],
                                     "locator": PROTOCOL["source_location"],
                                     "quote": report["proposal"]["source_quote"]})
        gate = evaluate(spec, raw)
        exported = export_report(report)
        reopened = reopen_report(exported)
        tampered = json.loads(exported)
        tampered["proposal"]["reported_value"] += 1
        tamper_error = None
        try:
            reopen_report(json.dumps(tampered))
        except ValueError as exc:
            tamper_error = str(exc)
        claims.append({"claim_id": claim_id, "reported_value": reported,
                       "pipeline_state": report["state"], "pipeline_calculation": report["calculation"],
                       "gate_result": gate, "validation_valid": report["validation"].get("valid"),
                       "source_valid": report["validation"].get("source_valid"),
                       "human_approval": report["human_approval"],
                       "llm_executed": report["llm_executed"],
                       "export_sha256": sha(exported.encode("utf-8")),
                       "reopen_state": reopened["state"],
                       "reopen_approval_active": reopened["human_approval"]["active"],
                       "tamper_error": tamper_error})
    changed = run_case_manual("CHANGED-BAT-CONTRACT")
    checks = {
        "positive_records_53": len(selected) == 53,
        "positive_subject_ids_unique": duplicate_ids == 0,
        "no_selected_age_missing": missing == 0,
        "mean_matches_paper_rounding": abs(mean - Decimal(PROTOCOL["reported_mean"])) <= Decimal(PROTOCOL["tolerance"]),
        "both_engines_match": all(c["pipeline_state"] == "SUPPORTED_PREVIEW" and c["gate_result"]["verdict"] == "MATCH" for c in claims),
        "source_and_conditions_valid": all(c["validation_valid"] and c["source_valid"] for c in claims),
        "denominators_match": all(c["pipeline_calculation"]["denominator_matches"] for c in claims),
        "no_human_approval_created": all(not c["human_approval"]["approved"] for c in claims),
        "reopen_requires_review": all(c["reopen_state"] == "IMPORTED_REVIEW" and not c["reopen_approval_active"] for c in claims),
        "tampered_report_blocked": all(c["tamper_error"] == "REPORT_INTEGRITY_MISMATCH" for c in claims),
        "changed_filter_blocked": changed["state"] == "BLOCKED_CHANGED_INPUT" and not changed["can_approve"],
    }
    code_paths = ["tools/1_verify_bat_paper.py", "finals/finals_cases.py", "finals/finals_pipeline.py",
                  "core/statistics.py", "evidence_gate/gate.py", "evidence_gate/spec.py", "evidence_gate/compute.py"]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True,
                                capture_output=True, text=True, timeout=5).stdout.strip())
    result = {"contributor": "1 이채우", "started_at_kst": started_at,
              "finished_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
              "base_commit": commit, "local_changes_present": dirty,
              "python": platform.python_version(), "platform": platform.system(),
              "protocol_sha256": protocol_hash, "data_sha256": sha(raw),
              "source_sha256": case["source_sha256"], "paper_url": PROTOCOL["paper_url"],
              "code_sha256": {p: sha((ROOT/p).read_bytes()) for p in code_paths},
              "independent_calculation": {"total_rows": len(rows), "selected_rows": len(selected),
                  "age_missing": missing, "duplicate_positive_ids": duplicate_ids,
                  "age_sum": str(total_age), "mean_age": str(mean)},
              "claims": claims, "controlled_changed_filter": {"state": changed["state"], "can_approve": changed["can_approve"]},
              "checks": checks, "elapsed_seconds": round(perf_counter() - started, 4),
              "success": all(checks.values()), "model_calls": 0,
              "limitations": ["No general AI comparison", "No actual human approval", "No whole-paper or clinical validation", "Conditions were registered by people, not inferred by a model", "Changed filter and report tampering are controlled tests, not errors in the paper"]}
    write_json(output / "1_result.json", result)
    print(json.dumps({"success": result["success"], "checks_passed": sum(checks.values()),
                      "checks_total": len(checks), "mean_age": str(mean), "selected_rows": len(selected),
                      "output": str(output)}, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="존재하지 않는 새 실행 폴더")
    raise SystemExit(run(parser.parse_args().output.resolve()))
