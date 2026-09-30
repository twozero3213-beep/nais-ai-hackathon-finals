"""정규 명세 v2 ↔ 검토 대상 자료의 두 형식(AI 제안 검사기·등록 사례).

변환할 수 없는 의미는 버리지 않고 unresolved에 적는다. unresolved가 있으면 target은 None이다.
not_carried는 대상 형식에 자리가 없어 호출 측 문맥이 따로 보관해야 하는 값이다.
형식 기준: 자료 core/proposal_intake.py, tools/case_registry.py (지문은 docs 구현 기록 참고).
"""

from __future__ import annotations

import re

from .spec import empty_spec

PAGE = re.compile(r"(?:p\.|page)\s*(\d+)", re.IGNORECASE)
REGISTRY_CONTEXT = ("paper_url", "source_file", "source_sha256", "source_kind", "claim_text", "data_file", "scope_status")


def _outcome(target, unresolved, not_carried):
    return {"convertible": not unresolved, "target": None if unresolved else target,
            "unresolved": unresolved, "not_carried": not_carried}


def _common_unresolved(spec, unresolved):
    if spec.get("unresolved"):
        unresolved.extend(f"원 명세 미해결: {u}" for u in spec["unresolved"])
    for key in ("method", "data_fingerprint", "tolerance", "reported_value", "filters", "source_location"):
        if spec.get(key) is None:
            unresolved.append(f"{key}: 값 없음")


def to_proposal_intake(spec):
    """v2 → 자료 AI 제안 검사기 JSON(column·row_count·evidence{source_page, source_quote})."""
    unresolved, not_carried = [], []
    _common_unresolved(spec, unresolved)
    method = spec.get("method")
    if method not in (None, "row_count", "mean"):
        unresolved.append(f"method {method}: 자료 제안 형식에 같은 의미의 방법이 없음")
    column = "__dataset__" if method == "row_count" else spec.get("variable")
    if method == "mean" and column is None:
        unresolved.append("variable: 값 없음")
    if spec.get("missing_policy") != "complete_case":
        unresolved.append(f"missing_policy {spec.get('missing_policy')}: 자료 제안 형식은 complete_case만 받음")
    if method == "mean" and spec.get("missing_tokens") not in (None, [""]):
        unresolved.append("missing_tokens: 자료 제안 형식에 결측 표기 필드가 없음")
    for key in ("denominator", "unit"):
        if spec.get(key) is None:
            unresolved.append(f"{key}: 자료 제안 형식 필수인데 값 없음")
    page, quote = None, None
    location = spec.get("source_location")
    if isinstance(location, dict):
        match = PAGE.fullmatch(location["locator"].strip())
        if match:
            page = int(match.group(1))
        else:
            unresolved.append("source_location.locator: 자료 제안 형식은 정수 쪽 번호만 받음")
        quote = location["quote"]
        not_carried.append("source_location.source_id")
    if spec.get("field_evidence"):
        not_carried.append("field_evidence")
    target = {
        "claim_id": spec.get("claim_id"), "data_fingerprint": spec.get("data_fingerprint"),
        "evidence": {"source_page": page, "source_quote": quote}, "column": column, "method": method,
        "filters": [{"column": f["column"], "value": f["value"]} for f in spec.get("filters") or []],
        "denominator": spec.get("denominator"), "missing_policy": spec.get("missing_policy"),
        "unit": spec.get("unit"), "reported_value": spec.get("reported_value"), "tolerance": spec.get("tolerance"),
    }
    return _outcome(target, unresolved, not_carried)


def from_proposal_intake(proposal, *, source_id, missing_tokens=None):
    """자료 제안 → v2. 제안 형식에 없는 source_id·missing_tokens는 호출 측이 준다."""
    spec = empty_spec(proposal["claim_id"])
    method = proposal["method"]
    spec.update(method=method, reported_value=proposal["reported_value"], tolerance=proposal["tolerance"],
                data_fingerprint=proposal["data_fingerprint"], denominator=proposal["denominator"],
                unit=proposal["unit"], missing_policy=proposal["missing_policy"],
                variable=None if proposal["column"] == "__dataset__" else proposal["column"],
                filters=[{"column": f["column"], "operator": "eq", "value": f["value"]} for f in proposal["filters"]],
                missing_tokens=missing_tokens if method != "row_count" else None,
                source_location={"source_id": source_id, "locator": f"p. {proposal['evidence']['source_page']}",
                                 "quote": proposal["evidence"]["source_quote"]})
    return spec


def to_case_registry(spec, context):
    """v2 → 자료 등록 사례(count_rows·필터 사전·drop/error). context는 논문·파일 경로 등."""
    unresolved, not_carried = [], []
    _common_unresolved(spec, unresolved)
    for key in REGISTRY_CONTEXT:
        if not isinstance(context.get(key), str) or not context[key].strip():
            unresolved.append(f"context.{key}: 등록 형식 필수인데 값 없음")
    method = spec.get("method")
    registry_method = {"row_count": "count_rows", "mean": "mean"}.get(method)
    if method is not None and registry_method is None:
        unresolved.append(f"method {method}: 자료 등록 형식에 같은 의미의 방법이 없음")
    filters = {}
    for f in spec.get("filters") or []:
        if not isinstance(f["value"], str):
            unresolved.append(f"filters.{f['column']}: 등록 형식은 문자열 정확 일치만 지원")
        elif f["column"] in filters:
            unresolved.append(f"filters.{f['column']}: 같은 열 조건이 둘 이상")
        filters[f["column"]] = f["value"]
    policy = spec.get("missing_policy")
    if method == "row_count":
        registry_policy = "error"  # 등록 형식에서 행 수는 결측 정책을 쓰지 않음
    elif policy in ("error", "complete_case") and spec.get("missing_tokens") == [""]:
        registry_policy = {"error": "error", "complete_case": "drop"}[policy]
    else:
        registry_policy = None
        unresolved.append(f"missing_policy {policy} / missing_tokens {spec.get('missing_tokens')}: "
                          "등록 형식은 빈 칸만 결측으로 봄")
    location = spec.get("source_location") or {}
    if location:
        not_carried.append("source_location.source_id")
    for key in ("denominator", "unit", "field_evidence"):
        if spec.get(key):
            not_carried.append(key)
    target = {
        "claim_id": spec.get("claim_id"), **{k: context.get(k) for k in REGISTRY_CONTEXT},
        "source_quote": location.get("quote"), "source_location": location.get("locator"),
        "data_sha256": spec.get("data_fingerprint"), "method": registry_method,
        "column": "" if method == "row_count" else spec.get("variable"), "filters": filters,
        "missing_policy": registry_policy, "delimiter": ",",
        "reported_value": spec.get("reported_value"), "tolerance": spec.get("tolerance"),
    }
    return _outcome(target, unresolved, not_carried)


def from_case_registry(case, *, source_id):
    """자료 등록 사례 → v2."""
    spec = empty_spec(case["claim_id"])
    method = {"count_rows": "row_count", "mean": "mean"}[case["method"]]
    spec.update(method=method, reported_value=case["reported_value"], tolerance=case["tolerance"],
                data_fingerprint=case["data_sha256"],
                variable=None if method == "row_count" else case["column"],
                filters=[{"column": k, "operator": "eq", "value": v} for k, v in case["filters"].items()],
                missing_policy="not_applicable" if method == "row_count"
                else {"drop": "complete_case", "error": "error"}[case["missing_policy"]],
                missing_tokens=None if method == "row_count" else [""],
                source_location={"source_id": source_id, "locator": case["source_location"],
                                 "quote": case["source_quote"]})
    return spec
