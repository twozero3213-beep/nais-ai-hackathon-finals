"""행 대응 검사: 자료 식별자와 기준 식별자(예: 계통수 종 목록)의 구성·순서 진단.

표기 정규화(공백↔밑줄, 대소문자, 앞뒤 공백)는 후보로만 제시한다. 적용은 사람 승인 후 gate에서 한다.
"""

from __future__ import annotations

RULES = (
    ("trim", str.strip),
    ("space_to_underscore", lambda v: v.strip().replace(" ", "_")),
    ("casefold", lambda v: v.strip().casefold()),
    ("space_to_underscore+casefold", lambda v: v.strip().replace(" ", "_").casefold()),
)


def _duplicates(values):
    seen, dup = set(), []
    for v in values:
        if v in seen and v not in dup:
            dup.append(v)
        seen.add(v)
    return dup


def normalization_candidates(missing_in_data, missing_in_reference):
    """자료에만 있는 식별자 → 기준에만 있는 식별자로, 규칙 하나로 유일하게 이어질 때만 후보."""
    candidates, used = [], set()
    for source in missing_in_reference:
        for rule, norm in RULES:
            targets = [t for t in missing_in_data if t not in used and norm(t) == norm(source)]
            if len(targets) == 1:
                candidates.append({"from": source, "to": targets[0], "rule": rule})
                used.add(targets[0])
                break
    return candidates


def diagnose(data_ids, reference_ids, limit=20):
    """구성·중복·순서·표기 차이를 식별자 단위로 보고한다. 판정은 gate가 한다."""
    data, reference = list(data_ids), list(reference_ids)
    data_set, reference_set = set(data), set(reference)
    missing_in_data = [v for v in dict.fromkeys(reference) if v not in data_set]
    missing_in_reference = [v for v in dict.fromkeys(data) if v not in reference_set]
    report = {
        "data_count": len(data),
        "reference_count": len(reference),
        "empty_data_positions": [i + 1 for i, v in enumerate(data) if not v.strip()][:limit],
        "duplicates_data": _duplicates(data)[:limit],
        "duplicates_reference": _duplicates(reference)[:limit],
        "missing_in_data": missing_in_data[:limit],
        "missing_in_reference": missing_in_reference[:limit],
        "normalization_candidates": normalization_candidates(missing_in_data, missing_in_reference)[:limit],
        "order_differs": False,
        "order_differences_count": 0,
        "order_differences": [],
    }
    membership_ok = not (report["empty_data_positions"] or report["duplicates_data"]
                         or report["duplicates_reference"] or missing_in_data or missing_in_reference)
    if membership_ok:
        diffs = [{"position": i + 1, "data_id": d, "reference_id": r}
                 for i, (d, r) in enumerate(zip(data, reference)) if d != r]
        report.update(order_differs=bool(diffs), order_differences_count=len(diffs), order_differences=diffs[:limit])
    report["status"] = ("MEMBERSHIP_MISMATCH" if not membership_ok
                        else "ORDER_DIFFERS" if report["order_differs"] else "ALIGNED")
    return report


def reorder_indices(data_ids, reference_ids):
    """구성이 같을 때만: 기준 순서대로 자료 행을 놓는 0 기반 위치."""
    position = {v: i for i, v in enumerate(data_ids)}
    return [position[v] for v in reference_ids]
