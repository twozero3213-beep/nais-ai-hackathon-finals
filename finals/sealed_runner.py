"""봉인된 C01~C08을 일반 AI와 'LLM 있는 경로'로 실행해 사전 봉인한 기대 판정과 대조한다. 결과가 나빠도 지우지 않는다.

# [작성: 0 이영 · Claude] 2026-10-01 03:00 KST — 모의 심사 1순위 피드백: 혁신성 "기존 방식 대비" 증거가 0건이다(AI 두 조건 16칸 미실행, 실행기 없음).
# 조건 (finals/evidence/protocol.json): general_ai(모델 단독, 도구·코드 실행 없음) / without_llm(등록 조건 그대로 결정적 계산) / with_llm(모델이 조건을 제안 →
# 같은 결정적 계산). 두 AI 조건은 같은 모델·같은 입력 패킷·같은 호출 상한을 받는다. 정답은 모델 입력에 없다.
#
# 사전 고정한 입력 변환(결과를 보기 전에 정했고 바꾸지 않는다): 봉인 패킷의 source_text는 출판 HTML 전체(최대 1.5MB)라 요청 상한(200KB)과 비용 때문에
# 그대로 보낼 수 없다. 두 AI 조건 모두 '등록 인용 주변 ±1,500자에서 태그를 지운 발췌'와 현재 CSV 전체를 받는다. 이 변환은 results.json에 기록한다.
# 전송 직전 개인정보 검사(finals_privacy)에 걸리면 그 칸은 '미실행'으로 남긴다.
#
# 사용(실호출은 비용이 든다): 먼저 python finals/sealed_runner.py --dry-run 으로 크기·추정 비용을 본다. 실행은 --confirm-spend와 NAIS_ALLOW_LIVE_AI=1이 모두 필요하다.
# 비공개 입력은 tools/restore_sealed_inputs.py로 임시 사본에 복원한 뒤 --evidence-dir로 가리킨다(저장소를 더럽히지 않는다).
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import statistics
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import uuid

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "finals"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from comparison import EVIDENCE, canonical, now, sha, verify_seal, write   # noqa: E402  finals/comparison.py
from finals_privacy import sensitive_kinds                                   # noqa: E402
from tools.case_registry import audit_registry                                # noqa: E402

CASE_IDS = tuple(f"C{n:02}" for n in range(1, 9))
DECISIONS = ("ARITHMETIC_MATCH", "ARITHMETIC_MISMATCH", "BLOCK", "STALE_BLOCK")
AI_CONDITIONS = ("general_ai", "with_llm")
EXCERPT_RADIUS = 1500
# 공식 단가(입력 100만 토큰 0.40달러, 출력 1.60달러) 기준의 추정이다. 영수증이 아니다.
PRICE_PER_MILLION = {"input": 0.40, "output": 1.60}

GENERAL_SYSTEM = (
    "You review one quantitative claim using only the JSON input. Do not use tools and do not execute code. "
    "Decide whether the registered result can be used now. Return exactly one JSON object. "
    "decision must be ARITHMETIC_MATCH if the value you compute from the current CSV under the registered conditions equals the registered reported_value within tolerance; "
    "ARITHMETIC_MISMATCH if it differs; BLOCK if required evidence or conditions are missing or cannot be verified; "
    "STALE_BLOCK if current_data_sha256 differs from registered_data_sha256, so the registered result must not be reused. "
    "calculated_value is the number you computed, or null if you did not compute one. Do not invent evidence. No human approval.")
CONDITIONS_SYSTEM = (
    "You propose the analysis conditions that reproduce the quoted claim from the current CSV, using only the JSON input. Do not use tools and do not execute code. "
    "Return exactly one JSON object. method is count_rows or mean (null if unsupported). column is the CSV column to average, or an empty string for count_rows. "
    "filters lists equality filters as {column, value} (an empty list only if the claim has no filter; null if unknown). missing_policy is error or drop (null if unknown). "
    "denominator and unit are short strings or null. List every condition the source does not support in unresolved. "
    "Never change the reported value, tolerance or fingerprints. No human approval.")

DECISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["decision", "calculated_value", "evidence_location", "reason"],
    "properties": {"decision": {"type": "string", "enum": list(DECISIONS)},
                   "calculated_value": {"type": ["number", "null"]},
                   "evidence_location": {"type": ["string", "null"]},
                   "reason": {"type": "string"}}}
CONDITIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["method", "column", "filters", "missing_policy", "denominator", "unit", "unresolved"],
    "properties": {"method": {"type": ["string", "null"], "enum": ["count_rows", "mean", None]},
                   "column": {"type": ["string", "null"]},
                   "filters": {"type": ["array", "null"], "items": {
                       "type": "object", "additionalProperties": False, "required": ["column", "value"],
                       "properties": {"column": {"type": "string"}, "value": {"type": "string"}}}},
                   "missing_policy": {"type": ["string", "null"], "enum": ["error", "drop", None]},
                   "denominator": {"type": ["string", "null"]},
                   "unit": {"type": ["string", "null"]},
                   "unresolved": {"type": "array", "items": {"type": "string"}}}}

_TAG = re.compile(r"<[^>]*>")


# ── 입력 ────────────────────────────────────────────────────────────────────────
def excerpt(source_text: str, quote: str, radius: int = EXCERPT_RADIUS) -> str:
    """등록 인용 주변 ±radius자를 잘라 태그를 지운다(짧은 원문은 그대로). 같은 입력이면 항상 같은 결과다."""
    if len(source_text) <= 2 * radius + len(quote):
        return source_text
    at = source_text.find(quote) if quote else -1
    window = source_text[max(0, at - radius): at + len(quote) + radius] if at >= 0 else source_text[: 2 * radius]
    return re.sub(r"\s+", " ", _TAG.sub(" ", window)).strip()


def model_input(packet: dict) -> dict:
    """봉인 패킷에서 모델에 보낼 본문을 만든다. 두 AI 조건이 같은 본문을 받는다. 정답·기대 판정은 패킷에 없다."""
    registration = packet["registration"]
    return {"question": packet["question"], "registration": registration,
            "source_excerpt": excerpt(packet["source_text"], registration.get("source_quote", "")),
            "current_csv": packet["current_csv"],
            "registered_data_sha256": packet["registered_data_sha256"], "current_data_sha256": packet["current_data_sha256"],
            "prior_result_reuse_requested": packet["prior_result_reuse_requested"], "prior_human_approval": packet["prior_human_approval"]}


def load_packets(evidence_dir: Path, ids=CASE_IDS) -> dict:
    return {cid: json.loads((Path(evidence_dir) / "packets" / f"{cid}.json").read_text(encoding="utf-8")) for cid in ids}


# ── 결정적 경로(모델 없음 / 모델이 제안한 조건으로) ────────────────────────────────
def audit_with(registration: dict, evidence_dir: Path, conditions: dict | None = None) -> dict:
    """등록 조건(또는 모델이 제안한 조건)으로 결정적 검산을 하고 comparison.run_local과 같은 규칙으로 STALE_BLOCK을 판정한다."""
    item = deepcopy(registration)
    item.update(conditions or {})
    with TemporaryDirectory() as directory:
        manifest = Path(directory) / "case.json"
        write(manifest, {"schema": 1, "cases": [item]})
        actual = audit_registry(manifest, root=Path(evidence_dir))["results"][0]
    changed = sha((Path(evidence_dir) / item["data_file"]).read_bytes()) != item["data_sha256"]
    decision = "STALE_BLOCK" if changed and actual["action"] == "BLOCK" else actual["action"]
    return {"decision": decision, "value": actual.get("value"), "reason": actual.get("reason")}


def conditions_from(proposal: dict) -> dict | None:
    """모델 제안을 등록 형식으로 바꾼다. 모르는 조건(null)이 있으면 실행하지 않는다(None)."""
    if proposal.get("method") not in ("count_rows", "mean") or proposal.get("column") is None or proposal.get("missing_policy") is None \
            or proposal.get("filters") is None:
        return None
    return {"method": proposal["method"], "column": proposal["column"], "missing_policy": proposal["missing_policy"],
            "filters": {item["column"]: item["value"] for item in proposal["filters"]}}


def differing_fields(registration: dict, conditions: dict | None) -> list[str]:
    """모델이 제안한 조건 중 등록 조건과 다른 필드(사람이 고쳐야 했을 필드). 제안이 없으면 전부."""
    fields = ("method", "column", "filters", "missing_policy")
    if conditions is None:
        return list(fields)
    return [field for field in fields if conditions[field] != registration.get(field, {} if field == "filters" else "")]


# ── 채점 ────────────────────────────────────────────────────────────────────────
def same_number(left, right) -> bool:
    return isinstance(left, (int, float)) and not isinstance(left, bool) and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def score(decision, value, gold: dict) -> dict:
    """정답표와 대조한다. 판정이 같고, 정답에 값이 있으면 값도 같아야 통과다. 정답에 값이 없는데 숫자를 내놓은 것은 따로 센다."""
    decision_ok = decision == gold["action"]
    value_ok = gold["value"] is None or same_number(value, gold["value"])
    return {"expected_action": gold["action"], "expected_value": gold["value"], "decision_correct": decision_ok,
            "value_correct": value_ok, "passed": decision_ok and value_ok,
            "claimed_number_on_blocked_case": gold["value"] is None and isinstance(value, (int, float)) and not isinstance(value, bool)}


def cell(case_id: str, condition: str, status: str, **fields) -> dict:
    return {"case_id": case_id, "condition": condition, "execution_status": status, **fields}


def not_run(case_id: str, condition: str, blocker: str) -> dict:
    return cell(case_id, condition, "NOT_RUN", blocker=blocker, decision=None, passed=None)


# ── 모델 호출 ───────────────────────────────────────────────────────────────────
def ask(provider, system: str, body: dict, schema: dict):
    """모델을 한 번 부르고 스키마를 검사한다. (출력, 영수증)을 돌려준다. 오류 문장은 입력을 반사할 수 있어 코드만 남긴다."""
    started = perf_counter()
    result = provider(system, body, schema=schema, timeout=45)
    output = result["output"]
    jsonschema.Draft202012Validator(schema).validate(output)
    receipt = {"usage": result.get("usage"), "request_id": result.get("request_id"), "raw_sha256": result.get("raw_sha256"),
               "provider": result.get("provider"), "model": result.get("model"), "elapsed_ms": round((perf_counter() - started) * 1000, 2)}
    return output, receipt


def error_code(exc: Exception) -> str:
    code = str(exc)
    return code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", code) else type(exc).__name__


# ── 실행 ────────────────────────────────────────────────────────────────────────
def run_sealed(packets: dict, expected: dict, provider, *, evidence_dir: Path = EVIDENCE, conditions=AI_CONDITIONS,
               max_calls: int = 16, stop_after_errors: int = 2) -> dict:
    results, calls, consecutive, aborted = [], 0, 0, None
    for case_id, packet in packets.items():
        gold, registration = expected[case_id], packet["registration"]
        body = model_input(packet)
        input_sha = sha(canonical(body))
        local = audit_with(registration, evidence_dir)
        results.append(cell(case_id, "without_llm", "EXECUTED", decision=local["decision"], value=local["value"], reason=local["reason"],
                            input_sha256=input_sha, new_model_calls=0, **score(local["decision"], local["value"], gold)))
        blocked_by_privacy = bool(sensitive_kinds(body))      # 전송 직전 검사: 같은 본문이라 사례마다 한 번만 본다
        for condition in conditions:
            if aborted or calls >= max_calls:
                results.append(not_run(case_id, condition, aborted or "CALL_BUDGET_EXHAUSTED"))
                continue
            if blocked_by_privacy:
                results.append(not_run(case_id, condition, "PERSONAL_DATA_IN_OUTBOUND_PAYLOAD"))
                continue
            calls += 1
            try:
                if condition == "general_ai":
                    output, receipt = ask(provider, GENERAL_SYSTEM, body, DECISION_SCHEMA)
                    decision, value, extra = output["decision"], output["calculated_value"], {"model_output": output}
                else:
                    output, receipt = ask(provider, CONDITIONS_SYSTEM, body, CONDITIONS_SCHEMA)
                    proposed = conditions_from(output)
                    if proposed is None:
                        audited = {"decision": "BLOCK", "value": None, "reason": "MODEL_PROPOSAL_UNRESOLVED"}
                    else:
                        audited = audit_with(registration, evidence_dir, proposed)
                    decision, value = audited["decision"], audited["value"]
                    extra = {"model_output": output, "proposed_conditions": proposed, "audit_reason": audited["reason"],
                             "fields_differing_from_registered": differing_fields(registration, proposed)}
                consecutive = 0
                results.append(cell(case_id, condition, "EXECUTED", decision=decision, value=value, input_sha256=input_sha,
                                    new_model_calls=1, receipt=receipt, **extra, **score(decision, value, gold)))
            except Exception as exc:  # noqa: BLE001 — 공급자·스키마 오류는 칸에 기록하고 계속한다(숨기지 않는다)
                consecutive += 1
                results.append(cell(case_id, condition, "ERROR", error=error_code(exc), decision=None, passed=False, new_model_calls=1,
                                    input_sha256=input_sha))
                if consecutive >= stop_after_errors:
                    aborted = "ABORTED_AFTER_CONSECUTIVE_ERRORS:" + error_code(exc)
    return {"results": results, "provider_calls": calls, "aborted": aborted, "summary": summarize(results)}


def summarize(results: list[dict]) -> dict:
    summary = {}
    for condition in ("without_llm", *AI_CONDITIONS):
        rows = [row for row in results if row["condition"] == condition]
        done = [row for row in rows if row["execution_status"] == "EXECUTED"]
        tokens = [(row.get("receipt") or {}).get("usage") or {} for row in done]
        times = [(row.get("receipt") or {}).get("elapsed_ms") for row in done if (row.get("receipt") or {}).get("elapsed_ms") is not None]
        summary[condition] = {
            "cells": len(rows), "executed": len(done), "passed": sum(1 for row in done if row["passed"]), "failed": sum(1 for row in done if not row["passed"]),
            "errors": sum(1 for row in rows if row["execution_status"] == "ERROR"), "not_run": sum(1 for row in rows if row["execution_status"] == "NOT_RUN"),
            "claimed_number_on_blocked_case": sum(1 for row in done if row.get("claimed_number_on_blocked_case")),
            "input_tokens": sum(usage.get("input_tokens", 0) for usage in tokens), "output_tokens": sum(usage.get("output_tokens", 0) for usage in tokens),
            "median_elapsed_ms": statistics.median(times) if times else None}
    return summary


def estimate_cost(summary: dict) -> float:
    return round(sum(summary[c]["input_tokens"] * PRICE_PER_MILLION["input"] + summary[c]["output_tokens"] * PRICE_PER_MILLION["output"]
                     for c in AI_CONDITIONS) / 1_000_000, 4)


# ── 표 ──────────────────────────────────────────────────────────────────────────
def label(row: dict | None) -> str:
    if row is None:
        return "—"
    if row["execution_status"] == "NOT_RUN":
        return f"미실행: {row['blocker']}"
    if row["execution_status"] == "ERROR":
        return f"오류: {row['error']}"
    mark = "통과" if row["passed"] else "**불일치**"
    value = "" if row.get("value") is None else f" {row['value']:g}" if isinstance(row["value"], (int, float)) else ""
    return f"{mark} · {row['decision']}{value}"


def render_table(report: dict, expected: dict) -> str:
    by = {(row["case_id"], row["condition"]): row for row in report["results"]}
    lines = ["| 사례 | 기대 판정 | LLM 없는 경로 | 일반 AI | LLM 있는 경로 |", "|---|---|---|---|---|"]
    for case_id in dict.fromkeys(row["case_id"] for row in report["results"]):
        gold = expected[case_id]
        lines.append(f"| {case_id} | {gold['action']}{'' if gold['value'] is None else ' ' + format(gold['value'], 'g')} | "
                     f"{label(by.get((case_id, 'without_llm')))} | {label(by.get((case_id, 'general_ai')))} | {label(by.get((case_id, 'with_llm')))} |")
    s = report["summary"]
    lines += ["", "| 조건 | 실행 | 통과 | 불일치 | 오류 | 미실행 | 정답 없는 칸에서 숫자 주장 | 입력 토큰 | 출력 토큰 |", "|---|---|---|---|---|---|---|---|---|"]
    for condition, name in (("without_llm", "LLM 없는 경로"), ("general_ai", "일반 AI"), ("with_llm", "LLM 있는 경로")):
        c = s[condition]
        lines.append(f"| {name} | {c['executed']} | {c['passed']} | {c['failed']} | {c['errors']} | {c['not_run']} | {c['claimed_number_on_blocked_case']} | {c['input_tokens']} | {c['output_tokens']} |")
    lines += ["", "이 표는 사전 봉인한 8개 등록 사례의 결과이며 일반적 우위나 모델 성능을 입증하지 않는다. 불일치·오류·미실행 칸을 지우거나 고치지 않았다.",
              f"비용은 공식 단가 기준 추정 약 {estimate_cost(s)}달러이며 영수증이 아니다."]
    return "\n".join(lines) + "\n"


# ── 실행 전 점검·명령행 ─────────────────────────────────────────────────────────
def dry_run(packets: dict) -> dict:
    """호출하지 않고 사례별 본문 크기·추정 토큰·전송 차단 여부·추정 비용 상한을 돌려준다."""
    rows, total_in = [], 0
    for case_id, packet in packets.items():
        body = model_input(packet)
        size = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        kinds = list(sensitive_kinds(body))
        tokens = size // 3            # 한글·CSV 혼합의 보수적 추정(글자 3바이트당 1토큰)
        rows.append({"case_id": case_id, "request_bytes": size, "estimated_input_tokens": tokens, "blocked_by_privacy": kinds})
        if not kinds:
            total_in += tokens * len(AI_CONDITIONS)
    upper = round((total_in * PRICE_PER_MILLION["input"] + len(rows) * len(AI_CONDITIONS) * 1800 * PRICE_PER_MILLION["output"]) / 1_000_000, 4)
    return {"cases": rows, "estimated_cost_usd_upper": upper, "note": "추정 상한이며 영수증이 아님. 요청 상한은 provider.MAX_REQUEST_BYTES."}


def main(argv=None, provider=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "finals/results")
    parser.add_argument("--cases", default=",".join(CASE_IDS))
    parser.add_argument("--conditions", default=",".join(AI_CONDITIONS))
    parser.add_argument("--max-calls", type=int, default=16)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-spend", action="store_true", help="실제 모델 호출(비용 발생)을 확인한다")
    args = parser.parse_args(argv)
    ids = tuple(item for item in args.cases.split(",") if item)
    conditions = tuple(item for item in args.conditions.split(",") if item in AI_CONDITIONS)
    verify_seal(args.evidence_dir)                                   # 봉인 입력이 바뀌었거나 비공개 입력이 복원되지 않았으면 여기서 멈춘다
    packets = load_packets(args.evidence_dir, ids)
    expected = json.loads((args.evidence_dir / "expected.json").read_text(encoding="utf-8"))
    if args.dry_run:
        print(json.dumps(dry_run(packets), ensure_ascii=False, indent=2))
        return 0
    if provider is None:
        if not args.confirm_spend:
            print(json.dumps({"status": "BLOCKED", "code": "CONFIRM_SPEND_REQUIRED"}, ensure_ascii=False))
            return 2
        from finals_provider import complete_json
        provider = complete_json
    started = now()
    report = run_sealed(packets, expected, provider, evidence_dir=args.evidence_dir, conditions=conditions, max_calls=args.max_calls)
    run_id = uuid.uuid4().hex
    folder = args.results_dir / run_id
    report.update(run_id=run_id, started_at_kst=started, finished_at_kst=now(), contributor_version=0,
                  seal_sha256=sha((args.evidence_dir / "seal.json").read_bytes()), runner_sha256=sha(Path(__file__).read_bytes()),
                  model={"provider": "openai", "id": "gpt-4.1-mini"}, excerpt_radius=EXCERPT_RADIUS, conditions=list(conditions),
                  estimated_cost_usd=estimate_cost(report["summary"]), cost_status="ESTIMATED_FROM_USAGE_NOT_A_RECEIPT")
    write(folder / "results.json", report)
    (folder / "presentation-table.md").write_text(render_table(report, expected), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "folder": str(folder), "summary": report["summary"], "aborted": report["aborted"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
