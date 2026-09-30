"""Read-only comparison of a human approval with the inputs now being reviewed.

This is a procedural fixture, not a model benchmark or a new approval API.
"""

from hashlib import sha256
from io import BytesIO

import pandas as pd

from core.models import Status
from core.provenance import dataframe_hash
from core.verifier import verify, verify_reported_claim


# [작성: 전문가4] 2026-09-25 case57
# 무엇을: 승인 비교용 CSV 바이트를 표로 읽음 / 왜: 파일을 수정하지 않고 현재 입력을 재검산 / 입력·출력: CSV bytes -> DataFrame / 검증: tests/test_case57_procedural.py.
def _frame(csv_bytes):
    return pd.read_csv(BytesIO(csv_bytes))


# [작성: 전문가4] 2026-09-25 case57
# 무엇을: 원문·정정 수치를 각각 재검증 / 왜: 정정 성공이 원문 실패를 가리지 않도록 함 / 입력·출력: Claim·CSV bytes -> 두 판정·계산값 / 검증: tests/test_case57_procedural.py.
def _verdicts(claim, csv_bytes):
    data = _frame(csv_bytes)
    reported, _, _ = verify_reported_claim(claim, data)
    amendment, _, calculated = verify(claim, data)
    return reported.value, amendment.value, calculated


# [작성: 전문가4] 2026-09-25 case57
# 무엇을: 사람 승인 당시의 자료 해시·방법·판정을 보존 / 왜: 사후 입력 교체를 판별 / 입력·출력: 승인 Claim·CSV bytes -> 승인 스냅샷 / 검증: tests/test_case57_procedural.py.
def capture_approval(claim, csv_bytes):
    """Freeze the exact CSV bytes and method behind an existing human approval."""
    if claim.status != Status.VALIDATED or not claim.validated_signature:
        raise ValueError("사람 승인 상태가 아닙니다.")
    # [수정: 전문가4] 2026-09-25 case60
    # 종류: 오류수정 | 재현 방법: 승인 CSV 대신 같은 평균의 다른 CSV로 스냅샷 작성 또는 승인 후 방법 변경 | 변경 전: 승인 상태만 검사 | 변경 후: 승인 서명·원자료 지문 대조 | 왜: 사후 스냅샷이 다른 입력을 승인 근거로 위장하지 않도록 함 | 영향: 과거 DataFrame 기반 승인도 같은 표에 한해 허용.
    if claim.validated_signature != claim.verification_signature():
        raise ValueError("승인 당시 분석조건이 현재 Claim과 다릅니다.")
    frame = _frame(csv_bytes)
    if claim.validated_data_hash not in {sha256(csv_bytes).hexdigest(), dataframe_hash(frame)}:
        raise ValueError("승인 당시 원자료와 현재 CSV가 다릅니다.")
    reported, amendment, calculated = _verdicts(claim, csv_bytes)
    if amendment != Status.SUPPORTED.value:
        raise ValueError("승인 당시 CSV에서 정정값을 재현할 수 없습니다.")
    return {
        "claim_id": claim.claim_id,
        "dataset_sha256": sha256(csv_bytes).hexdigest(),
        "method": claim.analysis_method or claim.aggregation,
        "claim_signature": claim.verification_signature(),
        "reported_status": reported,
        "amendment_status": claim.amendment_status.value,
        "calculated_value": calculated,
    }


# [작성: 전문가4] 2026-09-25 case57
# 무엇을: 승인 스냅샷과 현재 입력·판정을 비교 / 왜: CSV나 방법 변경 뒤 재승인을 요구 / 입력·출력: 스냅샷·Claim·CSV bytes -> 전후 근거·조치 / 검증: tests/test_case57_procedural.py.
def review_approval(approved, claim, current_csv_bytes):
    """Show pre/post evidence; changed inputs always require a fresh approval."""
    if claim.claim_id != approved["claim_id"]:
        raise ValueError("승인 대상 Claim이 다릅니다.")
    reported, amendment, calculated = _verdicts(claim, current_csv_bytes)
    observed = {
        "claim_id": claim.claim_id,
        "dataset_sha256": sha256(current_csv_bytes).hexdigest(),
        "method": claim.analysis_method or claim.aggregation,
        "claim_signature": claim.verification_signature(),
        "reported_status": reported,
        "amendment_status": amendment,
        "calculated_value": calculated,
    }
    # [수정: 전문가7] 2026-09-25 case58
    # 무엇을: 방법 변경을 명시 항목 하나로 표시 / 왜: 방법이 승인 서명에도 포함돼 같은 변경을 중복 보고함 / 검증: tests/test_case57_procedural.py.
    changed = [key for key in ("dataset_sha256", "method", "claim_signature")
               if approved[key] != observed[key] and (key != "claim_signature" or approved["method"] == observed["method"])]
    current = not changed and claim.status == Status.VALIDATED and amendment == Status.SUPPORTED.value
    return {
        "action": "APPROVAL_CURRENT" if current else "REAPPROVAL_REQUIRED",
        "changed_inputs": changed,
        "approved": dict(approved),
        "observed": observed,
    }
