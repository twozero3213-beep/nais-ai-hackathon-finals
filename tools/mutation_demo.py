"""Deterministic synthetic example of approval invalidation after one input change.

The four-row CSV and approval are generated in memory. This proves behavior of the
current gate; it is neither a paper reproduction nor a generic-AI benchmark.
"""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json

import pandas as pd

from core.models import Claim, Status
from core.verifier import auto_verify
from core.workflow import approve_reverified, revise_and_reverify
from tools.procedural_review import capture_approval, review_approval


BASE_CSV = b"group,score\nA,10\nA,20\nB,30\nB,40\n"
CHANGED_CSV = b"group,score\nA,12\nA,20\nB,30\nB,40\n"


# [작성: 전문가4] 2026-09-25 case60
# 무엇을: 합성 CSV를 동일한 pandas 입력으로 읽음 / 왜: 승인·재검증 경로가 실제 데이터 객체를 사용하게 함 / 입력·출력: CSV bytes -> DataFrame / 검증: tests/test_case60_mutation.py.
def _frame(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(BytesIO(raw))


# [작성: 전문가4] 2026-09-25 case60
# 무엇을: 실제 workflow API로 합성 Claim의 정정값을 승인 / 왜: 시연 결과를 임의 상수 판정으로 만들지 않음 / 입력·출력: 없음 -> Claim / 검증: tests/test_case60_mutation.py.
def _synthetic_approval() -> Claim:
    claim = Claim("SYNTHETIC-MEAN-A", "A군 평균 18.4", 18.4, column="score",
                  aggregation="mean", semantic_confirmed=True,
                  filters=[{"column": "group", "value": "A"}])
    frame = _frame(BASE_CSV)
    revised = revise_and_reverify(claim, frame, 15.0, "합성 자료의 정정값")
    if revised["status"] != Status.SUPPORTED:
        raise RuntimeError("합성 정정 검증 실패")
    if not approve_reverified(claim, frame, "합성 승인", csv_bytes=BASE_CSV)[3]:
        raise RuntimeError("합성 승인 실패")
    return claim


# [작성: 전문가4] 2026-09-25 case60
# 무엇을: 승인 뒤 원자료·필터·방법을 각각 하나만 바꿔 재검증 / 왜: 승인 무효화와 원문·정정 분리를 30초 안에 재실행 가능하게 함 / 입력·출력: 없음 -> 결정적 JSON 호환 dict / 검증: tests/test_case60_mutation.py, python -m tools.mutation_demo.
def run_demo() -> dict:
    claim = _synthetic_approval()
    approved = capture_approval(claim, BASE_CSV)
    baseline_review = review_approval(approved, claim, BASE_CSV)
    baseline_status = auto_verify(claim, _frame(BASE_CSV), csv_bytes=BASE_CSV)[0]
    baseline = {
        "action": baseline_review["action"],
        "engine_status": baseline_status.value,
        "calculated_value": baseline_review["observed"]["calculated_value"],
        "original_reported_status": baseline_review["observed"]["reported_status"],
    }

    mutations = {}
    for name in ("csv_bytes", "filter", "method"):
        variant = deepcopy(claim)
        raw = BASE_CSV
        if name == "csv_bytes":
            raw = CHANGED_CSV
        elif name == "filter":
            variant.filters = [{"column": "group", "value": "B"}]
        else:
            variant.analysis_method = "sum"
        review = review_approval(approved, variant, raw)
        status, reason, _, _ = auto_verify(variant, _frame(raw), csv_bytes=raw)
        mutations[name] = {
            "action": review["action"],
            "engine_status": status.value,
            "changed_inputs": review["changed_inputs"],
            "calculated_value": review["observed"]["calculated_value"],
            "original_reported_status": review["observed"]["reported_status"],
            "reason": reason,
        }
    return {
        "schema": 1,
        "sample": "synthetic_four_row_csv_and_simulated_human_approval",
        "baseline": baseline,
        "mutations": mutations,
        "limitations": {
            "human_identity_verified": False,
            "independent_mean_replay_packet": False,
            "paper_claim_reproduced": False,
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
