"""정규 분석 명세 v2: 형식 검사·지문·v1 추출 계약 변환.

명세는 AI 후보나 사람 입력을 담는 그릇이다. 검사 통과는 실행 가능한 형식이라는 뜻이며
원문 해석이 맞다는 승인이 아니다.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

SPEC_VERSION = 2
METHODS = ("row_count", "mean", "ols_regression", "row_alignment")
MISSING_POLICIES = ("error", "complete_case", "not_applicable")
FIELDS = (
    "spec_version", "claim_id", "method", "reported_value", "variable", "filters",
    "missing_policy", "missing_tokens", "denominator", "unit", "data_fingerprint", "tolerance",
    "source_location", "field_evidence", "unresolved",
    "outcome", "predictors", "reported", "reported_df",
    "data_id_column", "reference_ids_source",
)
EVIDENCE_FIELDS = tuple(f for f in FIELDS if f not in ("spec_version", "claim_id", "source_location", "field_evidence", "unresolved"))
SHA256 = re.compile(r"[0-9a-f]{64}")


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        # [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — 10**400 같은 큰 정수는 float로 바꿀 수 없어 validate가 예외로 죽었다. 숫자로 인정하지 않는다.
        return False


def _text(value, limit=4000):
    return isinstance(value, str) and value.strip() != "" and len(value) <= limit


def spec_sha256(spec):
    """키 순서와 무관한 명세 지문."""
    raw = json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def empty_spec(claim_id):
    """모든 필드를 null로 둔 v2 명세. 모르는 값은 채우지 않는다."""
    spec = {name: None for name in FIELDS}
    spec.update(spec_version=SPEC_VERSION, claim_id=claim_id, field_evidence={}, unresolved=[])
    return spec


def validate(spec):
    """형식 오류(errors)와 실행에 모자란 필드(missing)를 모두 모아 돌려준다.

    ready는 errors·missing·unresolved가 모두 비었을 때만 True다.
    """
    errors, missing = [], []
    if not isinstance(spec, dict):
        return {"ready": False, "errors": ["명세는 JSON 객체여야 함"], "missing": [], "unresolved": []}
    for key in sorted(set(FIELDS) - spec.keys()):
        errors.append(f"필드 누락: {key}")
    for key in sorted(spec.keys() - set(FIELDS)):
        errors.append(f"알 수 없는 필드: {key}")
    get = spec.get

    if get("spec_version") != SPEC_VERSION:
        errors.append("spec_version은 2여야 함")
    if not _text(get("claim_id"), 128):
        errors.append("claim_id: 1~128자 문자열 필요")

    method = get("method")
    if method is None:
        missing.append("method")
    elif method not in METHODS:
        errors.append(f"method: 허용되지 않은 방법 {method!r}")

    for key in ("reported_value", "tolerance"):
        value = get(key)
        if value is not None and not _number(value):
            errors.append(f"{key}: 유한 숫자 또는 null")
    if _number(get("tolerance")) and get("tolerance") < 0:
        errors.append("tolerance: 0 이상")
    if get("tolerance") is None:
        missing.append("tolerance")

    fingerprint = get("data_fingerprint")
    if fingerprint is None:
        missing.append("data_fingerprint")
    elif not (isinstance(fingerprint, str) and SHA256.fullmatch(fingerprint)):
        errors.append("data_fingerprint: 소문자 SHA-256 64자")

    filters = get("filters")
    if filters is None:
        missing.append("filters")
    elif not isinstance(filters, list) or len(filters) > 8:
        errors.append("filters: 8개 이하 배열")
    else:
        for i, item in enumerate(filters):
            if not isinstance(item, dict) or set(item) != {"column", "operator", "value"}:
                errors.append(f"filters[{i}]: column·operator·value만 허용")
            elif not _text(item["column"], 128) or item["operator"] != "eq":
                errors.append(f"filters[{i}]: 열 이름과 operator 'eq' 필요")
            elif not (isinstance(item["value"], str) or _number(item["value"])):
                errors.append(f"filters[{i}].value: 문자열 또는 유한 숫자")

    policy = get("missing_policy")
    if policy is not None and policy not in MISSING_POLICIES:
        errors.append(f"missing_policy: 허용되지 않은 정책 {policy!r}")
    tokens = get("missing_tokens")
    if tokens is not None and (not isinstance(tokens, list) or len(tokens) > 16
                               or any(not isinstance(t, str) or len(t) > 32 for t in tokens)
                               or len(set(tokens)) != len(tokens)):
        errors.append("missing_tokens: 32자 이하 문자열의 중복 없는 배열(16개 이하)")

    for key in ("variable", "outcome", "data_id_column"):
        if get(key) is not None and not _text(get(key), 128):
            errors.append(f"{key}: 1~128자 문자열 또는 null")
    for key in ("denominator", "unit", "reference_ids_source"):
        if get(key) is not None and not _text(get(key)):
            errors.append(f"{key}: 비어 있지 않은 문자열 또는 null")

    location = get("source_location")
    if location is None:
        missing.append("source_location")
    elif (not isinstance(location, dict) or set(location) != {"source_id", "locator", "quote"}
          or not _text(location.get("source_id"), 128) or not _text(location.get("locator"), 512)
          or not _text(location.get("quote"))):
        errors.append("source_location: source_id·locator·quote 비어 있지 않은 문자열")

    evidence = get("field_evidence")
    if not isinstance(evidence, dict):
        errors.append("field_evidence: 객체 필요")
    else:
        for key, value in evidence.items():
            if key not in EVIDENCE_FIELDS:
                errors.append(f"field_evidence: 알 수 없는 필드 {key}")
            elif value is not None and (not isinstance(value, list) or len(value) > 8
                                        or any(not _text(v, 512) for v in value)):
                errors.append(f"field_evidence.{key}: 문자열 배열 또는 null")

    unresolved = get("unresolved")
    if not isinstance(unresolved, list) or any(not _text(u, 512) for u in unresolved):
        errors.append("unresolved: 문자열 배열")
        unresolved = []

    predictors = get("predictors")
    if predictors is not None and (not isinstance(predictors, list) or not predictors or len(predictors) > 16
                                   or any(not _text(p, 128) for p in predictors) or len(set(predictors)) != len(predictors)):
        errors.append("predictors: 중복 없는 열 이름 배열(1~16개)")
    reported = get("reported")
    if reported is not None:
        if not isinstance(reported, dict) or not reported:
            errors.append("reported: 항 이름별 {b, se, t} 객체")
        else:
            for term, stats in reported.items():
                if not isinstance(stats, dict) or set(stats) != {"b", "se", "t"}:
                    errors.append(f"reported.{term}: b·se·t 키만 허용")
                elif any(v is not None and not _number(v) for v in stats.values()):
                    errors.append(f"reported.{term}: 유한 숫자 또는 null")
                elif stats["b"] is None:
                    missing.append(f"reported.{term}.b")
    reported_df = get("reported_df")
    if reported_df is not None and (type(reported_df) is not int or reported_df < 1):
        errors.append("reported_df: 1 이상 정수 또는 null")

    # 방법별로 계산에 꼭 필요한 필드
    # [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — method가 배열·객체이면 dict 조회가 TypeError로 죽었다(1_이채우_경계검증 method_array). 문자열일 때만 조회한다.
    needs = {
        "row_count": ("reported_value",),
        "mean": ("reported_value", "variable", "missing_policy", "missing_tokens"),
        "ols_regression": ("outcome", "predictors", "reported", "missing_policy", "missing_tokens"),
        "row_alignment": ("data_id_column", "reference_ids_source"),
    }.get(method, ()) if isinstance(method, str) else ()
    missing.extend(key for key in needs if get(key) is None)
    if method in ("mean", "ols_regression") and policy == "not_applicable":
        errors.append(f"missing_policy: {method}에는 error 또는 complete_case")
    if method == "row_count" and get("variable") is not None:
        errors.append("variable: row_count는 전체 행 범위만 지원(null)")
    if method == "ols_regression" and isinstance(reported, dict) and isinstance(predictors, list):
        expected_terms = {"(Intercept)", *predictors}
        unknown = sorted(set(reported) - expected_terms)
        if unknown:
            errors.append(f"reported: 모형에 없는 항 {unknown}")

    return {"ready": not errors and not missing and not unresolved,
            "errors": errors, "missing": list(dict.fromkeys(missing)), "unresolved": list(unresolved)}


def from_extraction_v1(candidate):
    """docs/finals-strategy/extraction.schema.json(v1) 후보를 v2 명세로 옮긴다.

    v1에 없는 data_fingerprint·tolerance는 null로 두어 사람이나 앱이 채우게 한다.
    """
    spec = empty_spec(candidate["claim_id"])
    for key in ("reported_value", "variable", "filters", "missing_policy", "missing_tokens",
                "denominator", "unit", "source_location"):
        spec[key] = candidate.get(key)
    method = candidate.get("method")
    spec["method"] = "row_count" if method == "count_rows" else method
    spec["field_evidence"] = dict(candidate.get("field_evidence") or {})
    spec["unresolved"] = list(candidate.get("unresolved") or [])
    return spec
