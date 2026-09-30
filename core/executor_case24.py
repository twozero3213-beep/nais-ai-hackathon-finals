"""case24 deterministic typed-contract executor.

case24 CHANGE — WHY:
case22 exposed three production risks in review: raw-string filtering, single-predictor-only
regression, and Scope contracts that could only block forever. This executor centralizes
normalized filtering, supports numeric multi-predictor models, and can audit Scope *coverage*
when a human has explicitly completed the contract. Scope execution never claims efficacy;
it only reports whether the required evidence cells exist.
"""
from __future__ import annotations
import itertools
import pandas as pd
from .typed_contracts import DescriptiveContract,ComparativeContract,AssociationContract,RegressionContract,ScopeContract,check_evidence_sufficiency
from .statistics import descriptive,inferential,multivariable_regression
from .normalization_case24 import filter_mask,normalize_missing
from .diagnostics_case24 import comparative_diagnostics,association_diagnostics,regression_diagnostics

def _filtered(df,filters):
    out=normalize_missing(df)
    for f in filters:
        col,val=f.get("column"),f.get("value")
        if col in out.columns:out=out[filter_mask(out[col],val)]
    return out

def _scope_coverage(contract,df):
    dims=list(contract.subgroup_dimensions)
    if not dims:return {"coverage_complete":False,"missing_cells":[],"observed_cells":0,"required_cells":0}
    levels=[]
    for col in dims:
        vals=[x for x in df[col].dropna().unique().tolist()]
        levels.append(vals)
    time_col=""
    for candidate in ("week","timepoint","visit","month"):
        if candidate in df.columns:time_col=candidate;break
    required=[]
    for combo in itertools.product(*levels):
        base=dict(zip(dims,combo))
        for tp in contract.timepoints:
            cell={**base,**({time_col:tp} if time_col else {})};required.append(cell)
    missing=[]
    for cell in required:
        cur=df
        for col,val in cell.items():cur=cur[filter_mask(cur[col],val)]
        if contract.endpoint not in cur.columns or pd.to_numeric(cur[contract.endpoint],errors="coerce").dropna().empty:missing.append(cell)
    return {"coverage_complete":not missing,"missing_cells":missing,"observed_cells":len(required)-len(missing),"required_cells":len(required),"endpoint":contract.endpoint,"note":"coverage only; efficacy is not inferred"}

def execute_contract(contract,df):
    check=check_evidence_sufficiency(contract,df)
    if not check.executable:return {"state":"BLOCKED","reason":check.reason,"missing":check.missing,"result":None}
    fdf=_filtered(df,contract.filters)
    if isinstance(contract,DescriptiveContract):
        val,meta=descriptive(fdf,contract.variable,contract.aggregation)
        return {"state":"EXECUTED","reason":"기술통계 재계산 완료","result":{"value":val,**meta},"rows_used":len(fdf)}
    if isinstance(contract,ComparativeContract):
        res=inferential(fdf,contract.method,contract.outcome,contract.group_column,contract.group_a,contract.group_b,"")
        res["diagnostics"]=comparative_diagnostics(fdf,contract.outcome,contract.group_column,contract.group_a,contract.group_b)
        return {"state":"EXECUTED","reason":"두 집단 비교 재분석 완료","result":res,"rows_used":len(fdf)}
    if isinstance(contract,AssociationContract):
        res=inferential(fdf,contract.method,contract.y,"","","",contract.x)
        res["diagnostics"]=association_diagnostics(fdf,contract.x,contract.y)
        return {"state":"EXECUTED","reason":"연관성 재분석 완료","result":res,"rows_used":len(fdf)}
    if isinstance(contract,RegressionContract):
        if len(contract.predictors)>1:
            res=multivariable_regression(fdf,contract.outcome,contract.predictors,contract.method)
            first=contract.predictors[0];res['estimate']=res['terms'][first]['estimate'];res['p_value']=res['terms'][first]['p_value'];res['ci95']=res['terms'][first]['ci95_beta']
            if 'odds_ratio' in res['terms'][first]:res['odds_ratio']=res['terms'][first]['odds_ratio']
        else:
            res=inferential(fdf,contract.method,contract.outcome,"","","",contract.predictors[0])
        res["diagnostics"]=regression_diagnostics(fdf,contract.outcome,contract.predictors,contract.method)
        return {"state":"EXECUTED","reason":"회귀 재분석 완료","result":res,"rows_used":res.get("n",len(fdf))}
    if isinstance(contract,ScopeContract):
        res=_scope_coverage(contract,fdf)
        return {"state":"EXECUTED","reason":"범위 근거 coverage 점검 완료 — 효과 결론은 생성하지 않음","result":res,"rows_used":len(fdf)}
    return {"state":"BLOCKED","reason":"알 수 없는 계약 유형","missing":["contract type"],"result":None}
