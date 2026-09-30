"""Canonical human-facing presentation helpers for Evidence Gate case28.

case28 ARCHITECTURE CHANGE — WHY:
case21 correctly introduced typed contracts but exposed internal terms directly to judges/users.
This module keeps the machine contract unchanged while translating it into a review-friendly
layer: conclusion first, evidence second, implementation detail last.  It is deliberately
pure (no Streamlit dependency) so the same labels can be reused by future web/API clients.
"""
from __future__ import annotations
from core.typed_contracts import (
    ContractType, DescriptiveContract, ComparativeContract,
    AssociationContract, RegressionContract, ScopeContract,
)

TYPE_LABELS={
    ContractType.DESCRIPTIVE:"기술통계 검증",
    ContractType.COMPARATIVE:"집단 비교 검증",
    ContractType.ASSOCIATION:"연관성 검증",
    ContractType.REGRESSION:"회귀모형 검증",
    ContractType.SCOPE:"표현 범위 검증",
}

MISSING_LABELS={
    "human semantic confirmation":"사람의 근거 연결 확인",
    "method confirmation":"분석방법 확인",
    "subgroup dimensions":"하위집단 기준",
    "timepoints":"평가 시점",
    "scope endpoint":"검증 지표",
    "X variable":"X 변수",
    "Y variable":"Y 변수",
    "outcome":"결과변수",
    "predictor":"설명변수",
    "group column":"집단 변수",
    "group A":"비교집단 A",
    "group B":"비교집단 B",
    "descriptive variable":"검증 변수",
}

def human_missing(missing:list[str])->list[str]:
    out=[]
    for item in missing:
        if item.startswith("filter column:"): out.append("필터 변수: "+item.split(":",1)[1])
        elif item.startswith("predictor:"): out.append("설명변수: "+item.split(":",1)[1])
        else: out.append(MISSING_LABELS.get(item,item))
    return out

def contract_view(contract)->dict:
    """Return a compact, human-readable contract without weakening the machine contract."""
    if isinstance(contract,DescriptiveContract):
        fields=[("검증 변수",contract.variable or "미연결"),("계산 방법",contract.aggregation)]
    elif isinstance(contract,ComparativeContract):
        fields=[("결과 지표",contract.outcome or "미연결"),("비교 집단",f"{contract.group_a or '?'} ↔ {contract.group_b or '?'}"),("분석 방법",contract.method)]
    elif isinstance(contract,AssociationContract):
        fields=[("X 변수",contract.x or "미연결"),("Y 변수",contract.y or "미연결"),("분석 방법",contract.method)]
    elif isinstance(contract,RegressionContract):
        fields=[("결과변수",contract.outcome or "미연결"),("설명변수",", ".join(contract.predictors) or "미연결"),("모형",contract.method)]
    elif isinstance(contract,ScopeContract):
        # case24 SAFETY CONTINUITY — WHY: endpoint_candidate is a proposal, not confirmed evidence.
        fields=[("지표 후보",contract.endpoint_candidate or contract.endpoint or "미연결"),("필요 범위",contract.required_coverage),("하위집단 기준",", ".join(contract.subgroup_dimensions) or "미확정"),("평가 시점",", ".join(contract.timepoints) or "미확정")]
    else: fields=[]
    return {"type":TYPE_LABELS[contract.contract_type],"fields":fields}

def queue_detail(label:str,claim,run:dict|None=None)->str:
    """Second-line queue summary so large papers can be scanned without opening every claim."""
    if label=="수치 불일치" and run and run.get("result"):
        val=run["result"].get("value")
        # [수정: 전문가1] 2026-09-25 case40
        # 종류: 오류수정
        # 재현 방법: 사람 정정 후 원문 충돌 대기열이 14.8→14.8로 표시됐다.
        # 변경 전: 사후 수정값 current_value를 원문 수치처럼 표시.
        # 변경 후: 원문 original_value를 사용.
        # 왜: 대기열의 충돌 상태와 수치가 서로 맞아야 한다.
        # 영향: 정정 후에도 원문 18.4→14.8로 보인다.
        if claim.original_value is not None and val is not None:return f"{claim.original_value:g} → {val:.4g}"
    if label=="범위 검토":return "조건별 근거 필요"
    if label=="근거 확인":return "검증 계약 확인 대기"
    if label=="재현 성공":return "원자료 재계산 일치"
    return "검토 필요"


# case28 canonical display helpers; historical presentation_case27 remains compatibility-only.
# [수정: 전문가4] 2026-09-23 case37
# 종류: 오류수정
# 재현 방법: 수치 재현 결과 화면에서 fmt_number() 호출 시 display_zero 미정의 NameError 발생.
# 변경 전: display_zero는 presentation_case27에만 있고 canonical presentation에는 정의되지 않음.
# 변경 후: canonical presentation에 display-only near-zero 정규화 함수를 직접 정의.
# 왜: app.py가 canonical presentation만 import하므로 호환 모듈에 숨어 있는 함수를 호출하면 런타임이 중단됨.
# 영향: 표시값만 1e-12 미만을 0으로 정리하며 검증 원값·허용오차·감사 데이터는 변경하지 않음.
DISPLAY_EPSILON=1e-12

def display_zero(value:float|None, epsilon:float=DISPLAY_EPSILON):
    """입력: 숫자 또는 None. 출력: 표시 전용 float 또는 None. 검증 계산 원값은 변경하지 않는다."""
    if value is None:return None
    return 0.0 if abs(float(value)) < epsilon else float(value)

def fmt_number(value, digits=4):
    if value is None:return "—"
    v=display_zero(value)
    return f"{v:.{digits}g}"

def provenance_label(source:str, confirmed:bool=False):
    if confirmed:return "사람 확인 완료"
    return {"pdf_reported":"논문에서 직접 확인","system_candidate":"시스템 후보","heuristic":"시스템 후보"}.get(source or "","출처 미확정")
