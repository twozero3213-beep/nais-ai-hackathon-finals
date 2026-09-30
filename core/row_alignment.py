# 작성: case105 통계·계보 담당 | 2026-09-29 | 목적: 같은 개수라도 잘못 짝지은 행을 계산 전에 차단
# 입력: 자료 식별자·기준 식별자 | 출력: 명시적 재정렬 인덱스 | 검증: test_case105_reproduction.py
from __future__ import annotations


def row_alignment_indices(data_ids, reference_ids, *, allow_reorder=False):
    """Require unique, nonempty string IDs and exact membership before pairing rows."""
    data, reference = list(data_ids), list(reference_ids)
    for label, values in (("data", data), ("reference", reference)):
        if not values or any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"{label}: nonempty string identifiers required")
        if len(values) != len(set(values)):
            raise ValueError(f"{label}: duplicate identifiers are ambiguous")
    if set(data) != set(reference):
        raise ValueError("Row identifier membership mismatch")
    if data != reference and not allow_reorder:
        raise ValueError("Row identifier order mismatch; explicit reorder required")
    positions = {value: index for index, value in enumerate(data)}
    return [positions[value] for value in reference]
