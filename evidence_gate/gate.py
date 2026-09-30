"""명세 + 자료 → 판정. MATCH / MISMATCH / BLOCK / NEEDS_REVIEW.

- BLOCK: 명세 미완성·근거 위치 없음·자료 지문 불일치·자료 문제로 계산할 수 없음
- NEEDS_REVIEW: 회귀 계수는 맞지만 표준오차·t·자유도가 다름
사람 승인은 approvals로만 들어오며 자동으로 만들지 않는다.
"""

from __future__ import annotations

import hashlib

from . import align, compute
from .compute import GateError
from .spec import spec_sha256, validate


def _within(computed, reported, tolerance):
    return abs(computed - reported) <= tolerance


def _spec_digest(spec):
    # [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — 명세에 NaN 등이 있으면 지문 계산이 ValueError로 죽어 BLOCK 판정을 못 남겼다(1_이채우_경계검증 nonfinite_report).
    try:
        return spec_sha256(spec) if isinstance(spec, dict) else None
    except (TypeError, ValueError):
        return None


def _result(spec, data_sha, verdict, reason, **extra):
    return {"claim_id": spec.get("claim_id") if isinstance(spec, dict) else None,
            "method": spec.get("method") if isinstance(spec, dict) else None,
            "verdict": verdict, "reason_code": reason,
            "spec_sha256": _spec_digest(spec),
            "data_sha256": data_sha, **extra}


def evaluate(spec, data, *, reference_ids=None, approvals=None):
    """data는 원자료 바이트. reference_ids는 row_alignment 기준 식별자 목록."""
    approvals = approvals or {}
    data_sha = hashlib.sha256(data).hexdigest()
    check = validate(spec)
    if not check["ready"]:
        return _result(spec, data_sha, "BLOCK", "SPEC_NOT_READY", validation=check)
    if spec["data_fingerprint"] != data_sha:
        return _result(spec, data_sha, "BLOCK", "STALE_DATA",
                       message="명세에 등록된 자료 지문과 현재 자료 바이트가 다름. 이전 결과를 쓰지 말고 다시 확인해야 함",
                       registered_sha256=spec["data_fingerprint"])
    try:
        header, rows = compute.read_csv(data)
        selected = compute.select_rows(header, rows, spec["filters"])
        method = spec["method"]
        if method == "row_count":
            return _scalar(spec, data_sha, len(selected), {"rows_selected": len(selected)})
        if method == "mean":
            table, info = compute.numeric_table(header, selected, [spec["variable"]],
                                                spec["missing_tokens"], spec["missing_policy"])
            return _scalar(spec, data_sha, compute.mean([r[0] for r in table]), info)
        if method == "ols_regression":
            table, info = compute.numeric_table(header, selected, [spec["outcome"], *spec["predictors"]],
                                                spec["missing_tokens"], spec["missing_policy"])
            return _ols(spec, data_sha, compute.ols(table, spec["predictors"]), info)
        return _alignment(spec, data_sha, header, selected, reference_ids, approvals)
    except GateError as exc:
        return _result(spec, data_sha, "BLOCK", exc.code, message=str(exc), details=exc.details)
    except ArithmeticError as exc:
        # [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — 계산 중 수 범위 오류도 예외로 끝내지 않고 BLOCK 판정과 기록을 남긴다(fail-closed).
        return _result(spec, data_sha, "BLOCK", "NUMERIC_ERROR", message=f"계산 중 수 범위 오류: {type(exc).__name__}")


def _scalar(spec, data_sha, value, info):
    verdict = "MATCH" if _within(value, spec["reported_value"], spec["tolerance"]) else "MISMATCH"
    return _result(spec, data_sha, verdict, "COMPUTED", computed=value,
                   reported=spec["reported_value"], tolerance=spec["tolerance"], details=info)


def _ols(spec, data_sha, fit, info):
    tolerance, comparisons = spec["tolerance"], []
    coefficient_ok, other_ok = True, True
    for term, reported in spec["reported"].items():
        computed = fit["terms"][term]
        row = {"term": term}
        for stat in ("b", "se", "t"):
            if reported[stat] is None:
                continue
            ok = computed[stat] is not None and _within(computed[stat], reported[stat], tolerance)
            row[stat] = {"computed": computed[stat], "reported": reported[stat], "match": ok}
            if stat == "b":
                coefficient_ok &= ok
            else:
                other_ok &= ok
        comparisons.append(row)
    df_match = None if spec["reported_df"] is None else spec["reported_df"] == fit["df"]
    if not coefficient_ok:
        verdict, reason = "MISMATCH", "COEFFICIENT_MISMATCH"
    elif not other_ok or df_match is False:
        verdict, reason = "NEEDS_REVIEW", "COEFFICIENT_MATCH_OTHER_DIFFERS"
    else:
        verdict, reason = "MATCH", "COMPUTED"
    return _result(spec, data_sha, verdict, reason, computed={"terms": fit["terms"], "df": fit["df"], "n": fit["n"]},
                   comparisons=comparisons, df={"computed": fit["df"], "reported": spec["reported_df"], "match": df_match},
                   tolerance=tolerance, details=info)


def _approval(approvals, kind, data_sha, reference_sha, spec_sha):
    """명시적으로 받은 승인만 자료·기준 식별자·명세에 결속해 확인한다."""
    if kind not in approvals:
        return None
    approval = approvals[kind]
    if not (isinstance(approval, dict)
            and all(isinstance(approval.get(key), str) and approval[key].strip()
                    for key in ("approver", "basis"))):
        raise GateError("APPROVAL_INVALID", "승인자와 승인 근거가 모두 필요함", {"approval": kind})
    # [1 이채우] 2026-10-01T01:03:10+09:00 — 지문 없는 저장 승인을 새 입력에 다시 결속하지 않는다.
    # [수정: 3 조지현] 2026-10-01T01:21:00+09:00 — 지문 없는 저장 승인 재사용을 막는다. 현재 지문을 자동 채워 사람 승인을 생성하지 않는다.
    bindings = {"data_sha256": data_sha, "reference_sha256": reference_sha, "spec_sha256": spec_sha}
    missing = [key for key in bindings if not isinstance(approval.get(key), str) or not approval[key]]
    if missing:
        raise GateError("APPROVAL_UNBOUND", "자료·기준 식별자·명세 지문이 없는 승인은 사용할 수 없음",
                        {"approval": kind, "missing": missing, "missing_fields": missing})
    for key, current in bindings.items():
        if approval[key] != current:
            raise GateError("APPROVAL_STALE", "승인 뒤 입력이 바뀌어 이전 승인을 쓸 수 없음",
                            {"approval": kind, "field": key, "approved": approval[key], "current": current})
    # [1 이채우] 2026-10-01T01:21:52+09:00 — 통합 시 미결속 표시 필드는 유지하되, 미결속 승인은 위에서 차단한다.
    return {"type": kind, "approver": approval["approver"], "basis": approval["basis"],
            "approved_at_kst": approval.get("approved_at_kst"),
            **bindings, "bound_data_sha256": data_sha, "bound_reference_sha256": reference_sha,
            "bound_spec_sha256": spec_sha, "unbound_fields": []}


def _alignment(spec, data_sha, header, selected, reference_ids, approvals):
    if reference_ids is None:
        raise GateError("REFERENCE_MISSING", "기준 식별자 목록이 주어지지 않음")
    column = spec["data_id_column"]
    if column not in header:
        raise GateError("COLUMN_NOT_FOUND", "식별자 열이 자료에 없음", {"columns": [column]})
    reference_ids = list(reference_ids)
    reference_sha = align.reference_ids_sha256(reference_ids)
    data_ids = [row[column] for _, row in selected]
    report = align.diagnose(data_ids, reference_ids)
    applied = []

    spec_sha = spec_sha256(spec)
    # 이미 정렬된 입력에서도 제출된 저장 승인의 만료를 건너뛰지 않는다.
    normalize = _approval(approvals, "normalize", data_sha, reference_sha, spec_sha)
    reorder = _approval(approvals, "reorder", data_sha, reference_sha, spec_sha)
    if normalize:
        offered = {(c["from"], c["to"]): c for c in report["normalization_candidates"]}
        requested = approvals["normalize"].get("pairs") or []
        chosen = [offered.get((p.get("from"), p.get("to"))) for p in requested]
        if not requested or None in chosen:
            raise GateError("APPROVAL_NOT_APPLICABLE", "승인한 표기 변환이 제시된 후보에 없음",
                            {"requested": requested, "candidates": report["normalization_candidates"]})
        mapping = {c["from"]: c["to"] for c in chosen}
        data_ids = [mapping.get(v, v) for v in data_ids]
        normalize["pairs"] = chosen
        applied.append(normalize)
        report = dict(align.diagnose(data_ids, reference_ids), before_normalization=report)

    extra = {"details": report, "reference_ids_sha256": reference_sha}
    if applied:
        extra["approvals"] = applied
    if report["status"] == "MEMBERSHIP_MISMATCH":
        next_action = ("표기 차이 후보를 확인하고 변환을 승인할 수 있음" if report["normalization_candidates"]
                       else "빠진·남는·중복 식별자를 원자료와 계통수 파일에서 확인")
        return _result(spec, data_sha, "BLOCK", "ROW_MEMBERSHIP_MISMATCH", next_action=next_action, **extra)
    if report["status"] == "ALIGNED":
        return _result(spec, data_sha, "MATCH", "ROWS_ALIGNED", **extra)
    if not reorder:
        return _result(spec, data_sha, "BLOCK", "ROW_ORDER_REORDER_REQUIRED",
                       message="구성은 같지만 순서가 다름. 식별자 기준 재정렬을 사람이 승인해야 계산을 이어갈 수 있음",
                       next_action="식별자 기준 재정렬을 승인하시겠어요?", **extra)
    extra["approvals"] = applied + [reorder]
    indices = align.reorder_indices(data_ids, reference_ids)
    mapping = [{"reference_position": i + 1, "id": ref, "data_row": selected[j][0]}
               for i, (ref, j) in enumerate(zip(reference_ids, indices))]
    return _result(spec, data_sha, "MATCH", "ROWS_REORDERED_WITH_APPROVAL",
                   reorder_indices=indices, alignment_table=mapping, **extra)
