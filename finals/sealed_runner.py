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
from core.input_security import sensitive_content_kinds                      # noqa: E402
from tools.case_registry import audit_registry                                # noqa: E402

CASE_IDS = tuple(f"C{n:02}" for n in range(1, 9))
DECISIONS = ("ARITHMETIC_MATCH", "ARITHMETIC_MISMATCH", "BLOCK", "STALE_BLOCK")
AI_CONDITIONS = ("general_ai", "with_llm")
EXCERPT_RADIUS = 1500
# [수정: 0 이영 · Codex] 2026-10-01 02:58 KST — 봉인 원본을 바꾸지 않고 보강한 후보→실행 계약을 기존 4조건 실행 결과와 구분한다. 담당 버전 0과 별도다.
CONDITION_ADAPTER_VERSION = 2
SIX_CONDITIONS = ("method", "column", "filters", "denominator", "missing_policy", "unit")
# [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 정답 파일은 보존하고 강화한 채점·의미·입력 고정 규칙을 별도 지문으로 남긴다.
EVALUATION_RULES = json.loads((ROOT / "finals/sealed_evaluation_rules.json").read_text(encoding="utf-8"))
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
    "denominator and unit are short strings or null. field_evidence maps all six condition fields to arrays of exact quotes from source_excerpt, or null if unsupported. "
    "Use exact source wording for denominator and unit. List every condition the source does not support in unresolved. "
    "Missing conditions or evidence must remain unresolved; never infer a unit from CSV numbers. "
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
    "required": ["method", "column", "filters", "missing_policy", "denominator", "unit", "field_evidence", "unresolved"],
    "properties": {"method": {"type": ["string", "null"], "enum": ["count_rows", "mean", None]},
                   "column": {"type": ["string", "null"]},
                   "filters": {"type": ["array", "null"], "items": {
                       "type": "object", "additionalProperties": False, "required": ["column", "value"],
                       "properties": {"column": {"type": "string"}, "value": {"type": "string"}}}},
                   "missing_policy": {"type": ["string", "null"], "enum": ["error", "drop", None]},
                   "denominator": {"type": ["string", "null"]},
                   "unit": {"type": ["string", "null"]},
                   "field_evidence": {"type": "object", "additionalProperties": False,
                       "required": ["method", "column", "filters", "denominator", "missing_policy", "unit"],
                       "properties": {field: {"type": ["array", "null"], "items": {"type": "string"}}
                                      for field in SIX_CONDITIONS}},
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
    if not ids or len(set(ids)) != len(ids) or any(cid not in CASE_IDS for cid in ids):
        raise ValueError("INVALID_REGISTERED_CASE_SELECTION")
    return {cid: json.loads((Path(evidence_dir) / "packets" / f"{cid}.json").read_text(encoding="utf-8")) for cid in ids}


class InputChanged(ValueError):
    """실행 중 입력 변화는 모델의 오답과 구분하여 비교 전체를 무효로 만든다."""


def _input_path(root: Path, relative: str) -> Path:
    # [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 등록 상대경로만 사본으로 옮긴다. 절대경로·상위 탈출·외부 심볼릭 링크는 거절한다.
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("INVALID_REGISTERED_INPUT_PATH")
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("INVALID_REGISTERED_INPUT_PATH")
    return path


def _snapshot_inputs(packets: dict, expected: dict, evidence: Path, snapshot: Path) -> dict:
    """본문과 파일의 동일성을 확인한 바이트만 고정한다. 변경 사례의 '현재 지문'과 등록 지문은 구분한다."""
    fingerprints = {}
    for cid, packet in packets.items():
        reg = packet["registration"]
        if cid not in CASE_IDS or reg["claim_id"] != cid or packet.get("case_id", cid) != cid:
            raise ValueError("SEALED_PACKET_INPUT_MISMATCH")
        for field, text_field in (("source_file", "source_text"), ("data_file", "current_csv")):
            rel = reg[field]
            raw = _input_path(evidence, rel).read_bytes()
            digest = sha(raw)
            if raw.decode("utf-8-sig") != packet[text_field]:
                raise ValueError("SEALED_PACKET_INPUT_MISMATCH")
            if field == "source_file" and digest != reg["source_sha256"]:
                raise ValueError("SEALED_PACKET_INPUT_MISMATCH")
            if field == "data_file" and (digest != packet["current_data_sha256"] or reg["data_sha256"] != packet["registered_data_sha256"]):
                raise ValueError("SEALED_PACKET_INPUT_MISMATCH")
            fingerprints[rel] = digest
            target = snapshot / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        packet_rel = f"packets/{cid}.json"
        if (evidence / packet_rel).exists():
            raw = _input_path(evidence, packet_rel).read_bytes()
            if json.loads(raw) != packet:
                raise ValueError("SEALED_PACKET_INPUT_MISMATCH")
            fingerprints[packet_rel] = sha(raw)
    for rel in ("expected.json", "protocol.json", "seal.json"):
        if (evidence / rel).exists():
            raw = _input_path(evidence, rel).read_bytes()
            if rel == "expected.json":
                frozen = json.loads(raw)
                if any(frozen[cid] != expected[cid] for cid in packets):
                    raise ValueError("SEALED_EXPECTED_INPUT_MISMATCH")
            fingerprints[rel] = sha(raw)
    # [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 함수 직접 호출도 선택 입력의 기존 봉인과 대조한다. 미선택 비공개 파일을 대신 복원하지 않는다.
    if "seal.json" in fingerprints:
        sealed = json.loads((evidence / "seal.json").read_bytes())["files"]
        if any(sealed.get(rel) != digest for rel, digest in fingerprints.items() if rel != "seal.json"):
            raise ValueError("SEALED_INPUT_CHANGED_BEFORE_RUN")
    _assert_stable(evidence, fingerprints)
    return fingerprints


def _assert_stable(evidence: Path, fingerprints: dict) -> None:
    try:
        if any(sha(_input_path(evidence, rel).read_bytes()) != digest for rel, digest in fingerprints.items()):
            raise InputChanged("SEALED_INPUT_CHANGED_DURING_RUN")
    except (OSError, ValueError):
        raise InputChanged("SEALED_INPUT_CHANGED_DURING_RUN") from None


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


def conditions_from(proposal: dict, *, source_excerpt: str | None = None) -> dict | None:
    """여섯 조건과 원문 인용이 완성된 모델 후보만 산술 미리보기로 전달한다. 사람 승인은 생성하지 않는다."""
    # [수정: 0 이영 · Codex] 2026-10-01 02:58 KST — 분모·단위 null 또는 미해결 조건을 버리고 계산하던 우회를 막고, 여섯 조건의 인용이 실제 전송 원문에 있는지 확인한다.
    fields = SIX_CONDITIONS
    if not isinstance(proposal, dict) or proposal.get("unresolved") != []:
        return None
    if proposal.get("method") not in ("count_rows", "mean") or proposal.get("missing_policy") not in ("error", "drop"):
        return None
    if not isinstance(proposal.get("column"), str) or (proposal["method"] == "mean" and not proposal["column"].strip()):
        return None
    if any(not isinstance(proposal.get(field), str) or not proposal[field].strip() for field in ("denominator", "unit")):
        return None
    filters = proposal.get("filters")
    if not isinstance(filters, list) or any(not isinstance(item, dict) or set(item) != {"column", "value"}
            or not isinstance(item["column"], str) or not item["column"].strip() or not isinstance(item["value"], str) for item in filters):
        return None
    # 중복 열을 dict로 바꾸며 마지막 조건만 남기는 정규화도 허용하지 않는다.
    if len({item["column"] for item in filters}) != len(filters):
        return None
    evidence = proposal.get("field_evidence")
    if not isinstance(source_excerpt, str) or not isinstance(evidence, dict) or set(evidence) != set(fields):
        return None
    for field in fields:
        quotes = evidence[field]
        if not isinstance(quotes, list) or not quotes or any(not isinstance(quote, str) or not quote.strip()
                or quote not in source_excerpt for quote in quotes):
            return None
    if any(not any(proposal[field] in quote for quote in evidence[field]) for field in ("denominator", "unit")):
        return None
    # 인용 존재 확인은 의미 해석 승인과 다르다. 제안한 분모·단위·인용은 결과에도 보존한다.
    return {field: deepcopy(proposal[field]) for field in fields} | {"filters": {item["column"]: item["value"] for item in filters},
                                                                  "field_evidence": deepcopy(evidence)}


def semantic_review(proposal: dict | None, registration: dict) -> dict:
    """분모·단위의 등록 계약만 대조한다. 계약이 없으면 의미 검증을 주장하지 않는다."""
    # [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 숫자 일치로 단위/모집단의 정확성을 추정하지 않고, 미검증과 계약 불일치를 구분한다.
    fields, blocking = {}, []
    for name in ("denominator", "unit"):
        proposed = (proposal or {}).get(name)
        contract = registration.get(name)
        if not isinstance(contract, str) or not contract.strip():
            status = "NOT_VERIFIED"
        elif not isinstance(proposed, str) or not proposed.strip():
            status = "UNKNOWN"
            blocking.append("MISSING_" + name.upper() + "_CONTRACT_VALUE")
        elif proposed != contract:
            status = "MISMATCH"
            blocking.append(name.upper() + "_CONTRACT_MISMATCH")
        else:
            status = "MATCH"
        fields[name] = {"status": status, "proposed": proposed, "registered_contract": contract,
                        "basis": "REGISTERED_STRING_CONTRACT" if status != "NOT_VERIFIED" else "NO_SUPPORTED_REGISTERED_CONTRACT"}
    return {"fields": fields, "verified": all(value["status"] == "MATCH" for value in fields.values()),
            "blocking_issues": blocking, "scope": "registered_contract_comparison_not_independent_source_semantics"}


def differing_fields(registration: dict, conditions: dict | None) -> list[str]:
    """모델이 제안한 조건 중 등록 조건과 다른 필드(사람이 고쳐야 했을 필드). 제안이 없으면 전부."""
    fields = SIX_CONDITIONS
    if conditions is None:
        return list(fields)
    return [field for field in fields if conditions[field] != registration.get(field, {} if field == "filters" else "")]


# ── 채점 ────────────────────────────────────────────────────────────────────────
def same_number(left, right) -> bool:
    return all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (left, right)) \
        and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def score(decision, value, gold: dict) -> dict:
    """등록 판정과 수치/멈춤의 일관성을 함께 채점한다. 원래 정답표는 변경하지 않는다."""
    # [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 차단 판정만 맞히고 수치를 주장한 경우 통과 총계에 섞이지 않도록 한다.
    decision_ok = decision == gold["action"]
    # [수정: 0 이영 · Codex] 2026-10-01 03:02 KST — BLOCK 판정에 숫자를 붙인 모델 출력을 통과로 세던 채점 오류를 수정한다. 봉인 기대값은 그대로다.
    value_ok = value is None if gold["value"] is None else same_number(value, gold["value"])
    return {"expected_action": gold["action"], "expected_value": gold["value"], "decision_correct": decision_ok,
            "value_correct": value_ok, "passed": decision_ok and value_ok,
            "stopping_correct": decision in ("BLOCK", "STALE_BLOCK") and value is None if gold["value"] is None else None,
            "claimed_number_on_blocked_case": gold["value"] is None and isinstance(value, (int, float)) and not isinstance(value, bool)}


def cell(case_id: str, condition: str, status: str, **fields) -> dict:
    return {"case_id": case_id, "condition": condition, "execution_status": status, **fields}


def not_run(case_id: str, condition: str, blocker: str) -> dict:
    return cell(case_id, condition, "NOT_RUN", blocker=blocker, decision=None, passed=None)


# ── 모델 호출 ───────────────────────────────────────────────────────────────────
class ModelOutputRejected(ValueError):
    """검증에서 버린 본문 대신 비민감 오류 코드와 이미 발생한 호출 영수증만 유지한다."""

    def __init__(self, code, receipt):
        super().__init__(code)
        self.receipt = receipt


def ask(provider, system: str, body: dict, schema: dict):
    """모델을 한 번 부르고 스키마를 검사한다. (출력, 영수증)을 돌려준다. 오류 문장은 입력을 반사할 수 있어 코드만 남긴다."""
    started = perf_counter()
    # [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 공급자가 다음 조건의 본문·스키마를 바꾸지 못하도록 사본만 전달한다.
    result = provider(system, deepcopy(body), schema=deepcopy(schema), timeout=45)
    output = result["output"]
    receipt = {"usage": result.get("usage"), "request_id": result.get("request_id"), "raw_sha256": result.get("raw_sha256"),
               "provider": result.get("provider"), "model": result.get("model"), "mock": result.get("mock", False), "elapsed_ms": round((perf_counter() - started) * 1000, 2)}
    # [수정: 0 이영 · Codex] 2026-10-01 03:14 KST — 유료 호출 뒤 응답을 버려도 호출·토큰 사용량은 실제 부작용이다. 원문 없는 영수증을 실패 칸에 유지한다.
    try:
        jsonschema.Draft202012Validator(schema).validate(output)
    except jsonschema.ValidationError:
        raise ModelOutputRejected("MODEL_OUTPUT_SCHEMA_INVALID", receipt) from None
    # [수정: 0 이영 · Codex] 2026-10-01 03:10 KST — 모델이 생성한 연락처·인증 값도 원문 결과 파일에 남기지 않고 비민감 오류 코드로 기록한다.
    if sensitive_content_kinds(output):
        raise ModelOutputRejected("PERSONAL_DATA_IN_MODEL_OUTPUT", receipt)
    return output, receipt


def error_code(exc: Exception) -> str:
    code = str(exc)
    return code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", code) else type(exc).__name__


# ── 실행 ────────────────────────────────────────────────────────────────────────
def run_sealed(packets: dict, expected: dict, provider, *, evidence_dir: Path = EVIDENCE, conditions=AI_CONDITIONS,
               max_calls: int = 16, stop_after_errors: int = 2) -> dict:
    # [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 모든 결정적 계산은 같은 바이트 사본을 사용한다. 원본의 도중 변경은 비교 전체 무효 사유다.
    if not packets or any(cid not in CASE_IDS for cid in packets) or len(set(conditions)) != len(conditions) or any(c not in AI_CONDITIONS for c in conditions):
        raise ValueError("INVALID_REGISTERED_CASE_SELECTION")
    if type(max_calls) is not int or max_calls < 0 or type(stop_after_errors) is not int or stop_after_errors < 1:
        raise ValueError("INVALID_LOCAL_CALL_BUDGET")
    packets, expected = deepcopy(packets), deepcopy(expected)
    evidence_dir = Path(evidence_dir)
    results, calls, consecutive, aborted, invalid = [], 0, 0, None, False
    fingerprints = {}
    with TemporaryDirectory() as directory:
        snapshot = Path(directory)
        try:
            fingerprints = _snapshot_inputs(packets, expected, evidence_dir, snapshot)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
            aborted, invalid = error_code(exc), True
        for case_id, packet in packets.items():
            gold, registration = expected[case_id], packet["registration"]
            body = model_input(packet)
            input_sha = sha(canonical(body))
            if not invalid:
                try:
                    _assert_stable(evidence_dir, fingerprints)
                except InputChanged as exc:
                    aborted, invalid = error_code(exc), True
            if invalid:
                results.extend(not_run(case_id, condition, aborted) for condition in ("without_llm", *conditions))
                continue
            local_started = perf_counter()
            local = audit_with(registration, snapshot)
            try:
                _assert_stable(evidence_dir, fingerprints)
            except InputChanged as exc:
                aborted, invalid = error_code(exc), True
            results.append(cell(case_id, "without_llm", "EXECUTED", decision=local["decision"], value=local["value"], reason=local["reason"],
                                semantic_validation=semantic_review(None, registration),
                                evidence_present=bool(registration.get("source_location") and registration.get("source_quote")),
                                elapsed_ms=round((perf_counter() - local_started) * 1000, 2),
                                input_sha256=input_sha, new_model_calls=0, **score(local["decision"], local["value"], gold)))
            blocked_by_privacy = bool(sensitive_kinds(body))
            for condition in conditions:
                if aborted or calls >= max_calls:
                    results.append(not_run(case_id, condition, aborted or "CALL_BUDGET_EXHAUSTED"))
                    continue
                if blocked_by_privacy:
                    results.append(not_run(case_id, condition, "PERSONAL_DATA_IN_OUTBOUND_PAYLOAD"))
                    continue
                started, output, receipt, called = perf_counter(), None, None, False
                try:
                    _assert_stable(evidence_dir, fingerprints)
                    calls += 1
                    called = True
                    if condition == "general_ai":
                        output, receipt = ask(provider, GENERAL_SYSTEM, body, DECISION_SCHEMA)
                        _assert_stable(evidence_dir, fingerprints)
                        decision, value = output["decision"], output["calculated_value"]
                        extra = {"model_output": output, "evidence_present": bool((output["evidence_location"] or "").strip()),
                                 "semantic_validation": semantic_review(None, registration)}
                    else:
                        output, receipt = ask(provider, CONDITIONS_SYSTEM, body, CONDITIONS_SCHEMA)
                        _assert_stable(evidence_dir, fingerprints)
                        proposed = conditions_from(output, source_excerpt=body["source_excerpt"])
                        semantics = semantic_review(output, registration)
                        if proposed is None or semantics["blocking_issues"]:
                            audited = {"decision": "BLOCK", "value": None, "reason": "MODEL_PROPOSAL_UNRESOLVED"}
                        else:
                            audited = audit_with(registration, snapshot, proposed)
                        decision, value = audited["decision"], audited["value"]
                        extra = {"model_output": output, "proposed_conditions": proposed, "audit_reason": audited["reason"],
                                 "human_approval": False, "evaluation_scope": "ARITHMETIC_PREVIEW_NOT_HUMAN_APPROVAL",
                                 "semantic_validation": semantics,
                                 "evidence_present": bool(registration.get("source_location") and registration.get("source_quote")),
                                 "fields_differing_from_registered": differing_fields(registration, proposed)}
                    _assert_stable(evidence_dir, fingerprints)
                    consecutive = 0
                    results.append(cell(case_id, condition, "EXECUTED", decision=decision, value=value, input_sha256=input_sha,
                                        elapsed_ms=round((perf_counter() - started) * 1000, 2),
                                        new_model_calls=1, receipt=receipt, **extra, **score(decision, value, gold)))
                except InputChanged as exc:
                    aborted, invalid = error_code(exc), True
                    results.append(cell(case_id, condition, "INVALIDATED", blocker=aborted, decision=None, passed=None,
                                        model_output=output, receipt=receipt, new_model_calls=int(called), input_sha256=input_sha))
                except Exception as exc:  # 공급자/스키마 오류와 입력 변화의 원인을 섞지 않는다.
                    consecutive += 1
                    rejected_receipt = {"receipt": exc.receipt} if isinstance(exc, ModelOutputRejected) else {}
                    results.append(cell(case_id, condition, "ERROR", error=error_code(exc), decision=None, passed=False, new_model_calls=int(called),
                                        input_sha256=input_sha, **rejected_receipt))
                    if consecutive >= stop_after_errors:
                        aborted = "ABORTED_AFTER_CONSECUTIVE_ERRORS:" + error_code(exc)
        if not invalid:
            try:
                _assert_stable(evidence_dir, fingerprints)
            except InputChanged as exc:
                aborted, invalid = error_code(exc), True
    for row in results:
        row["comparison_valid"] = not invalid
    return {"results": results, "provider_calls": calls, "aborted": aborted, "comparison_valid": not invalid,
            "input_snapshot_sha256": sha(canonical(fingerprints)), "input_fingerprints": fingerprints,
            "expected_sha256": sha(canonical(expected)), "evaluation_rules_sha256": sha(canonical(EVALUATION_RULES)),
            "score_scope": EVALUATION_RULES["score"]["scope"], "summary": summarize(results),
            "condition_adapter": {"version": CONDITION_ADAPTER_VERSION, "post_seal_extension": True,
                "schema_sha256": sha(canonical(CONDITIONS_SCHEMA)),
                "evidence_scope": "EXACT_QUOTES_IN_SHARED_SOURCE_EXCERPT_NOT_SEMANTIC_OR_HUMAN_APPROVAL",
                "required_conditions": list(SIX_CONDITIONS), "human_approval": False}}


def summarize(results: list[dict]) -> dict:
    summary = {}
    for condition in ("without_llm", *AI_CONDITIONS):
        rows = [row for row in results if row["condition"] == condition]
        executed = [row for row in rows if row["execution_status"] == "EXECUTED"]
        done = [row for row in executed if row.get("comparison_valid", True)]
        # [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 무효 관측은 승패 총계에서 제외하지만 이미 발생한 호출량은 보존한다.
        tokens = [(row.get("receipt") or {}).get("usage") or {} for row in rows]
        times = [row["elapsed_ms"] for row in done if row.get("elapsed_ms") is not None]
        summary[condition] = {
            "cells": len(rows), "executed": len(executed), "valid_executed": len(done),
            "passed": sum(1 for row in done if row["passed"]), "failed": sum(1 for row in done if not row["passed"]),
            "invalidated": sum(1 for row in rows if row["execution_status"] == "INVALIDATED" or row["execution_status"] == "EXECUTED" and not row.get("comparison_valid", True)),
            "errors": sum(1 for row in rows if row["execution_status"] == "ERROR"), "not_run": sum(1 for row in rows if row["execution_status"] == "NOT_RUN"),
            "claimed_number_on_blocked_case": sum(1 for row in done if row.get("claimed_number_on_blocked_case")),
            "evidence_present": sum(1 for row in done if row.get("evidence_present")),
            "semantics_not_verified": sum(1 for row in done if not (row.get("semantic_validation") or {}).get("verified", False)),
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
    if row["execution_status"] == "INVALIDATED":
        return f"비교 무효: {row['blocker']}"
    mark = "통과" if row["passed"] else "**불일치**"
    if not row.get("comparison_valid", True):
        mark = "비교 무효 · 관측 " + mark
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
    lines += ["", "| 조건 | 실행 | 유효 실행 | 산술·멈춤 통과 | 불일치 | 무효 | 오류 | 미실행 | 숫자 주장 오류 | 근거 위치 제시 | 의미 미검증 | 입력 토큰 | 출력 토큰 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for condition, name in (("without_llm", "LLM 없는 경로"), ("general_ai", "일반 AI"), ("with_llm", "LLM 있는 경로")):
        c = s[condition]
        lines.append(f"| {name} | {c['executed']} | {c['valid_executed']} | {c['passed']} | {c['failed']} | {c['invalidated']} | {c['errors']} | {c['not_run']} | {c['claimed_number_on_blocked_case']} | {c['evidence_present']} | {c['semantics_not_verified']} | {c['input_tokens']} | {c['output_tokens']} |")
    lines += ["", "이 표는 사전 봉인한 8개 등록 사례의 결과이며 일반적 우위나 모델 성능을 입증하지 않는다. 불일치·오류·미실행 칸을 지우거나 고치지 않았다.",
              "통과는 산술·멈춤 기준이며 원문과 분모·단위의 의미 검증을 뜻하지 않는다. 근거 위치 제시도 내용의 정확성 검증과 구분한다.",
              f"비교 유효성: {'유효' if report.get('comparison_valid', True) else '무효 — 자료 변경 관측을 승패 총계에서 제외'}. 평가 규칙 지문: {report.get('evaluation_rules_sha256', '미기록')}",
              f"비용은 코드에 고정된 단가 가정으로 추정 약 {estimate_cost(s)}달러이며 영수증이 아니다."]
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
    conditions = tuple(item for item in args.conditions.split(",") if item)
    if not conditions or len(set(conditions)) != len(conditions) or any(item not in AI_CONDITIONS for item in conditions):
        parser.error("등록된 모델 조건만 중복 없이 지정하세요.")
    verify_seal(args.evidence_dir)                                   # 봉인 입력이 바뀌었거나 비공개 입력이 복원되지 않았으면 여기서 멈춘다
    packets = load_packets(args.evidence_dir, ids)
    expected = json.loads((args.evidence_dir / "expected.json").read_text(encoding="utf-8"))
    if args.dry_run:
        print(json.dumps(dry_run(packets), ensure_ascii=False, indent=2))
        return 0
    injected_provider = provider is not None
    if provider is None:
        if not args.confirm_spend:
            print(json.dumps({"status": "BLOCKED", "code": "CONFIRM_SPEND_REQUIRED"}, ensure_ascii=False))
            return 2
        from finals_provider import complete_json
        provider = complete_json
    started = now()
    runner_sha256 = sha(Path(__file__).read_bytes())
    report = run_sealed(packets, expected, provider, evidence_dir=args.evidence_dir, conditions=conditions, max_calls=args.max_calls)
    run_id = uuid.uuid4().hex
    folder = args.results_dir / run_id
    # [수정: 3 조지현 · 2026-10-01T03:16:35+09:00] 이번 실행기 수정 담당 번호와 모의/외부 공급자 주입 여부를 구분한다.
    report.update(run_id=run_id, started_at_kst=started, finished_at_kst=now(), contributor_version=3,
                  seal_sha256=report["input_fingerprints"].get("seal.json"), runner_sha256=runner_sha256,
                  sealed_protocol_sha256=report["input_fingerprints"].get("protocol.json"),
                  model={"provider": "openai", "id": "gpt-4.1-mini"} if not injected_provider else {"provider": "INJECTED_PROVIDER", "id": "SEE_RECEIPTS"},
                  execution_source="INJECTED_PROVIDER_NOT_LIVE_MODEL_PROOF" if injected_provider else "LIVE_PROVIDER",
                  excerpt_radius=EXCERPT_RADIUS, conditions=list(conditions),
                  estimated_cost_usd=estimate_cost(report["summary"]), cost_status="ESTIMATED_FROM_USAGE_NOT_A_RECEIPT")
    write(folder / "results.json", report)
    (folder / "presentation-table.md").write_text(render_table(report, expected), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "folder": str(folder), "summary": report["summary"], "aborted": report["aborted"]}, ensure_ascii=False, indent=2))
    return 1 if report["aborted"] or not report["comparison_valid"] else 0


if __name__ == "__main__":
    sys.exit(main())
