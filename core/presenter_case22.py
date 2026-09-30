"""Human-facing presentation helpers for Evidence Gate case22.

case22 UX CHANGE — WHY:
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
        # case22 SAFETY CHANGE — WHY: endpoint_candidate is a proposal, not confirmed evidence.
        fields=[("지표 후보",contract.endpoint_candidate or contract.endpoint or "미연결"),("필요 범위",contract.required_coverage),("하위집단 기준",", ".join(contract.subgroup_dimensions) or "미확정"),("평가 시점",", ".join(contract.timepoints) or "미확정")]
    else: fields=[]
    return {"type":TYPE_LABELS[contract.contract_type],"fields":fields}

def queue_detail(label:str,claim,run:dict|None=None)->str:
    """Second-line queue summary so large papers can be scanned without opening every claim."""
    if label=="수치 불일치" and run and run.get("result"):
        val=run["result"].get("value")
        if claim.current_value is not None and val is not None:return f"{claim.current_value:g} → {val:.4g}"
    if label=="범위 검토":return "조건별 근거 필요"
    if label=="근거 확인":return "검증 계약 확인 대기"
    if label=="재현 성공":return "원자료 재계산 일치"
    return "검토 필요"
