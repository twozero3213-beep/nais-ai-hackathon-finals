"""Typed deterministic executor for case21.

WHY: execution is separated from semantic proposal/UI so no model or presentation component can
silently change the statistical calculation. The executor accepts only a sufficient typed contract.
"""
from __future__ import annotations
import pandas as pd
from .typed_contracts import (DescriptiveContract,ComparativeContract,AssociationContract,RegressionContract,ScopeContract,check_evidence_sufficiency)
from .statistics import descriptive,inferential


def _filtered(df,filters):
    out=df
    for f in filters:
        col,val=f.get("column"),f.get("value")
        if col in out.columns: out=out[out[col].astype(str)==str(val)]
    return out


def execute_contract(contract,df):
    check=check_evidence_sufficiency(contract,df)
    if not check.executable:
        return {"state":"BLOCKED","reason":check.reason,"missing":check.missing,"result":None}
    fdf=_filtered(df,contract.filters)
    if isinstance(contract,DescriptiveContract):
        val,meta=descriptive(fdf,contract.variable,contract.aggregation)
        return {"state":"EXECUTED","reason":"기술통계 재계산 완료","result":{"value":val,**meta},"rows_used":len(fdf)}
    if isinstance(contract,ComparativeContract):
        res=inferential(fdf,contract.method,contract.outcome,contract.group_column,contract.group_a,contract.group_b,"")
        return {"state":"EXECUTED","reason":"두 집단 비교 재분석 완료","result":res,"rows_used":len(fdf)}
    if isinstance(contract,AssociationContract):
        res=inferential(fdf,contract.method,contract.y,"","","",contract.x)
        return {"state":"EXECUTED","reason":"연관성 재분석 완료","result":res,"rows_used":len(fdf)}
    if isinstance(contract,RegressionContract):
        res=inferential(fdf,contract.method,contract.outcome,"","","",contract.predictors[0])
        return {"state":"EXECUTED","reason":"회귀 재분석 완료","result":res,"rows_used":len(fdf)}
    if isinstance(contract,ScopeContract):
        # Defensive invariant: ScopeContract should normally be blocked until explicit coverage exists.
        return {"state":"BLOCKED","reason":"범위 Claim은 조건별 coverage 검증계획이 필요합니다.","missing":["coverage plan"],"result":None}
    return {"state":"BLOCKED","reason":"알 수 없는 계약 유형","missing":["contract type"],"result":None}
