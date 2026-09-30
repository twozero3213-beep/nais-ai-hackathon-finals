"""Canonical deterministic typed-contract executor (case28).

case28 ARCHITECTURE CHANGE — WHY:
case22 exposed three production risks in review: raw-string filtering, single-predictor-only
regression, and Scope contracts that could only block forever. This executor centralizes
normalized filtering, supports numeric multi-predictor models, and can audit Scope *coverage*
when a human has explicitly completed the contract. Scope execution never claims efficacy;
it only reports whether the required evidence cells exist.
"""
from __future__ import annotations
from .analysis_spec import AnalysisSpecification, check_analysis_spec, validate_multiplicity_family
import itertools
import math
import pandas as pd
from .typed_contracts import DescriptiveContract,ComparativeContract,AssociationContract,RegressionContract,ScopeContract,check_evidence_sufficiency
from .statistics import descriptive,inferential,multivariable_regression
from .normalization import filter_mask,normalize_missing
from .diagnostics import comparative_diagnostics,association_diagnostics,regression_diagnostics

# [작성: 전문가6] 2026-09-25 case43
# 무엇을: apply_multiplicity / 왜: 확인된 검정 가족 크기의 Bonferroni p 보정 / 입력·출력: 원래 결과·분석 명세 -> 원 p와 보정 p / 검증: tests/test_case43.py의 .01×3=.03.
def apply_multiplicity(result,spec):
    out=dict(result)
    if spec.multiplicity_policy=='bonferroni' and out.get('p_value') is not None:
        raw=float(out['p_value'])
        out.update(raw_p_value=raw,p_value=min(1.0,raw*spec.multiplicity_count),multiplicity_policy='bonferroni',multiplicity_count=spec.multiplicity_count)
    # [작성/수정: 전문가5·6] 2026-09-26 case62
    # 무엇을: 명시 전체 가족의 Holm/BH 대상 p 보정 / 왜: 단일 p만으로 순위보정은 불가능.
    # 입력·출력: 전체 원 p·대상 재계산 p -> 원/보정 p·가족 기록 / 검증: test_complete_family_applies_and_exposes_interpretation.
    if spec.multiplicity_policy in {'holm','bh','fdr_bh'}:
        adjusted=validate_multiplicity_family(spec)
        index=spec.multiplicity_target_index
        raw=float(out['p_value'])
        # 반올림 p는 허용하지 않고 부동소수점 재계산 오차만 허용한다.
        if not math.isfinite(raw) or not math.isclose(raw,float(spec.multiplicity_p_values[index]),rel_tol=1e-12,abs_tol=1e-15):
            raise ValueError('대상 원 p값이 재계산 p와 일치하지 않습니다.')
        control='FWER' if spec.multiplicity_policy=='holm' else 'FDR'
        note='원 p 가족은 사용자 입력이며 다른 검정의 재계산·사람 인증을 뜻하지 않습니다. CI는 보정하지 않은 개별 구간이며 동시 신뢰구간이 아닙니다.'
        if control=='FDR': note+=' BH의 FDR 통제는 독립 또는 적절한 양의 의존 조건에서 해석하며 FWER 통제가 아닙니다.'
        out.update(raw_p_value=raw,p_value=adjusted[index],multiplicity_policy=spec.multiplicity_policy,
                   multiplicity_count=spec.multiplicity_count,multiplicity_p_values=list(spec.multiplicity_p_values),
                   multiplicity_adjusted_p_values=adjusted,multiplicity_target_index=index,
                   multiplicity_family_definition=spec.multiplicity_family_definition,
                   multiplicity_error_control=control,multiplicity_note=note)
    return out

def _filtered(df,filters):
    out=normalize_missing(df)
    for f in filters:
        col,val=f.get("column"),f.get("value")
        if col in out.columns:out=out[filter_mask(out[col],val)]
    return out

# [수정: 전문가5/6] 2026-09-26 case64
# 원인: 빈 필터 결과가 0/0 완성, 시간열 부재가 중복 셀 / 무엇·왜: 실제 관측 구조만 coverage 계산.
# 입력·출력: 빈 자료/미관측 시점 -> 불완전 / 검증: case64 scope 회귀시험.
def _scope_coverage(contract,df):
    dims=list(contract.subgroup_dimensions)
    if not dims or df.empty or any(col not in df.columns for col in dims):return {"coverage_complete":False,"missing_cells":[],"observed_cells":0,"required_cells":0}
    levels=[]
    for col in dims:
        vals=[x for x in df[col].dropna().unique().tolist()]
        levels.append(vals)
    time_col=""
    for candidate in ("week","timepoint","visit","month"):
        if candidate in df.columns:time_col=candidate;break
    if not time_col:return {"coverage_complete":False,"missing_cells":[],"observed_cells":0,"required_cells":0}
    required=[]
    for combo in itertools.product(*levels):
        base=dict(zip(dims,combo))
        for tp in contract.timepoints:
            cell={**base,**({time_col:tp} if time_col else {})};required.append(cell)
    missing=[]
    for cell in required:
        cur=df
        for col,val in cell.items():cur=cur[filter_mask(cur[col],val)]
        values=pd.to_numeric(cur[contract.endpoint],errors="coerce").dropna() if contract.endpoint in cur.columns else []
        if not any(math.isfinite(float(value)) for value in values):missing.append(cell)
    return {"coverage_complete":bool(required) and not missing,"missing_cells":missing,"observed_cells":len(required)-len(missing),"required_cells":len(required),"endpoint":contract.endpoint,"note":"coverage only; efficacy is not inferred"}

# [수정: 전문가5/6] 2026-09-26 case65
# 원인: 비교·상관 rows_used가 선택밖 집단·결측 탈락행까지 포함 / 무엇·왜: 실제 계산 결과의 n으로 감사 행수 일치.
# 입력·출력: A/B 유효 6행 또는 완전 관측쌍 4행 + 사용하지 않은 행 -> rows_used 6 또는 4.
# 검증: tests/test_case65_statistics.py의 행 추가 메타모픽 시험 11건, 수정 전 모두 FAIL.
def _execute_deterministic(contract,df):
    check=check_evidence_sufficiency(contract,df)
    if not check.executable:return {"state":"BLOCKED","reason":check.reason,"missing":check.missing,"result":None}
    fdf=_filtered(df,contract.filters)
    if isinstance(contract,DescriptiveContract):
        # [수정: 재현성/계약 라우팅] 2026-09-28 case72
        # one_sample_t는 집단 계약이 아니라 단일 결과열+기준값(mu0) 계약이다. 평균으로 폴백하지 않고
        # 확인된 기준값을 그대로 inferential()에 전달해야 같은 명세가 같은 통계검정으로 재현된다.
        if contract.method == "one_sample_t":
            res=inferential(fdf,"one_sample_t",contract.variable,mu0=contract.reference_value)
            return {"state":"EXECUTED","reason":"1표본 t 검정 재분석 완료","result":res,"rows_used":res["n"]}
        # [수정: 전문가5] 2026-09-25 case40
        # 종류: 오류수정
        # 재현 방법: typed 실행에서 가중치·성공값이 무시되어 verifier와 값이 달랐다.
        # 변경 전: descriptive() 기본 인수만 전달.
        # 변경 후: 사람이 확인한 계약 필드를 그대로 전달.
        # 왜: 동일 Claim은 모든 실행 경로에서 같은 수치를 내야 한다.
        # 영향: proportion/weighted_mean 실행값과 감사 계약이 일치한다.
        val,meta=descriptive(fdf,contract.variable,contract.aggregation,contract.weight_column,contract.success_value)
        return {"state":"EXECUTED","reason":"기술통계 재계산 완료","result":{"value":val,**meta},"rows_used":len(fdf)}
    if isinstance(contract,ComparativeContract):
        res=inferential(fdf,contract.method,contract.outcome,contract.group_column,contract.group_a,contract.group_b,"")
        res["diagnostics"]=comparative_diagnostics(fdf,contract.outcome,contract.group_column,contract.group_a,contract.group_b)
        alerts=list(res['diagnostics']['review_flags'])
        if contract.method=='independent_t' and res['diagnostics'].get('levene_p',1)<.05:alerts.append('등분산 진단 경고: Welch 민감도 검토 필요')
        res['assumption_alerts']=alerts
        # [작성/수정: 전문가5·6] 2026-09-26 case61
        # 무엇을: 비교 출력의 실제 선택 n 표시 / 왜: 범위 밖 C 20행을 사용했다고 보고하지 않음.
        # 입력·출력: A/B/C 60행 중 A/B 40행 -> rows_used=40 / 검증: test_categorical_comparison_excludes_unselected_groups.
        rows_used=res["n"] if "n" in res else res["n_a"]+res["n_b"]
        return {"state":"EXECUTED","reason":"두 집단 비교 재분석 완료","result":res,"rows_used":rows_used}
    if isinstance(contract,AssociationContract):
        res=inferential(fdf,contract.method,contract.y,"","","",contract.x)
        # paired 검정도 두 열의 대응 관계를 보존하는 AssociationContract를 재사용한다.
        # 진단은 현재 쌍의 완전관측 수를 제공하며 검정 자체의 fail-closed 조건은 statistics.py가 담당한다.
        res["diagnostics"]=association_diagnostics(fdf,contract.x,contract.y)
        return {"state":"EXECUTED","reason":"연관성 재분석 완료","result":res,"rows_used":res["n"]}
    if isinstance(contract,RegressionContract):
        if len(contract.predictors)>1:
            res=multivariable_regression(fdf,contract.outcome,contract.predictors,contract.method)
            # [수정: 0 이영] 2026-09-30 22:44 KST — C09: 첫 설명변수 대신 계약에 결속된 검산 대상 항을 대표 수치로 전달한다.
            target=contract.target_predictor
            res['estimate']=res['terms'][target]['estimate'];res['p_value']=res['terms'][target]['p_value'];res['ci95']=res['terms'][target]['ci95_beta']
            if 'odds_ratio' in res['terms'][target]:res['odds_ratio']=res['terms'][target]['odds_ratio']
        else:
            res=inferential(fdf,contract.method,contract.outcome,"","","",contract.predictors[0])
        res["target_predictor"]=contract.target_predictor or contract.predictors[0]
        res["diagnostics"]=regression_diagnostics(fdf,contract.outcome,contract.predictors,contract.method)
        res['assumption_alerts']=[res['diagnostics']['diagnostic_error']] if 'diagnostic_error' in res['diagnostics'] else []
        return {"state":"EXECUTED","reason":"회귀 재분석 완료","result":res,"rows_used":res.get("n",len(fdf))}
    if isinstance(contract,ScopeContract):
        res=_scope_coverage(contract,fdf)
        return {"state":"EXECUTED","reason":"범위 근거 coverage 점검 완료 — 효과 결론은 생성하지 않음","result":res,"rows_used":len(fdf)}
    return {"state":"BLOCKED","reason":"알 수 없는 계약 유형","missing":["contract type"],"result":None}


# [수정: 전문가5/6] 2026-09-26 case64
# 원인: 계산 실패 예외가 실행 경계 밖으로 유출 / 무엇·왜: 유한 계산 불가를 BLOCKED로 반환.
# 입력·출력: 기술통계 overflow/표본 부족 -> 결과 없는 BLOCKED / 검증: case64 기술통계 양 경로 시험.
def execute_contract(contract, df, analysis_spec=None):
    """Canonical fail-closed execution boundary.

    case28 ARCHITECTURE CHANGE
    FAILURE: the stable API still delegated executor -> case25 -> case24.
    RISK: fixes could land in one historical module and not another.
    WHY: one canonical implementation is easier to audit and reuse.
    CHANGE: analysis-spec gating and deterministic execution now live here.
    REGRESSION: tests/test_case28.py::test_canonical_executor_has_no_version_delegate
    """
    # [수정: 0 이영] 2026-09-30 22:44 KST — C02/C03: 명세 생략 우회를 막고 별도 명세는 계약 snapshot과 대조한다.
    inferential=isinstance(contract,(ComparativeContract,AssociationContract,RegressionContract)) or (isinstance(contract,DescriptiveContract) and contract.method=="one_sample_t")
    if inferential:
        try:
            embedded=AnalysisSpecification(**contract.analysis_spec)
            if analysis_spec is None:
                analysis_spec=embedded
            elif not isinstance(analysis_spec,AnalysisSpecification):
                analysis_spec=AnalysisSpecification(**analysis_spec.to_dict())
            if contract.analysis_spec and analysis_spec.to_dict()!=embedded.to_dict():
                return {"state":"BLOCKED","reason":"분석 명세와 계약 snapshot 불일치","missing":["matching analysis specification"],"result":None}
            if analysis_spec.missing_policy!=contract.missing_policy:
                return {"state":"BLOCKED","reason":"결측 정책과 계약 불일치","missing":["matching missing-data policy"],"result":None}
        except (TypeError,ValueError,AttributeError):
            return {"state":"BLOCKED","reason":"분석 명세 형식 오류","missing":["valid analysis specification"],"result":None}
    if analysis_spec is not None:
        # [수정: 0 이영] 2026-09-30 22:50 KST — C02: 잘못된 명세 필드형도 예외 유출 없이 계산 전에 차단한다.
        try:
            ok, missing, unsupported = check_analysis_spec(analysis_spec, contract.contract_type.value, contract.method)
        except (TypeError,ValueError,AttributeError,OverflowError):
            return {"state":"BLOCKED","reason":"분석 명세 필드 오류","missing":["valid analysis specification"],"result":None}
        if not ok:
            return {"state":"BLOCKED","reason":"분석 명세 미완성","missing":missing,"unsupported":unsupported,"result":None}
        # [수정: 전문가6] 2026-09-25 case43
        # 종류: 오류수정 / 재현 방법: 분산 정책과 실제 검정이 달라도 실행 / 변경 전: 별도 일치 검사 없음 / 변경 후: Welch 정책과 검정의 불일치 차단 / 왜: 서로 다른 통계방법을 재현으로 표시하지 않기 위함 / 영향: 명시적 불일치만 차단.
        variance=analysis_spec.variance_estimator
        if (variance=='welch' and not (isinstance(contract,ComparativeContract) and contract.method=='welch_t')) or (variance=='classical' and isinstance(contract,ComparativeContract) and contract.method=='welch_t'):
            return {"state":"BLOCKED","reason":"분산 정책과 검정 방법 불일치","unsupported":["variance estimator:"+variance],"result":None}
    # [작성/수정: 전문가5·6] 2026-09-26 case61
    # 무엇을: 비수렴 회귀의 실행 완료 승격 차단 / 왜: 유한 계수·p만으로 fit 유효성을 보장하지 못함.
    # 입력·출력: 단일/다중 회귀의 converged=False -> BLOCKED, result=None.
    # 검증: tests/test_case61_statistics.py 실제 완전분리 데이터의 수정 전 2 FAIL -> 수정 후 PASS.
    try: run=_execute_deterministic(contract, df)
    except (ValueError,TypeError,ArithmeticError) as exc:
        return {'state':'BLOCKED','reason':f'통계 재계산 실패: {exc}','missing':['valid statistical computation'],'result':None}
    if run['state']=='EXECUTED' and isinstance(contract,RegressionContract) and run['result'].get('converged') is False:
        return {'state':'BLOCKED','reason':'회귀 모형이 수렴하지 않아 추론 결과를 사용할 수 없습니다.','missing':['model convergence'],'result':None}
    # [수정: 전문가6] 2026-09-25 case47
    # 종류: 오류수정 / 재현 방법: 상수열 Pearson이 NaN r/p와 함께 EXECUTED / 변경 전: 비유한 결과도 실행 완료 / 변경 후: 추론의 주요 계산값이 유한하지 않으면 BLOCKED / 왜: 계산 불능을 감사상 성공 실행으로 남기지 않음 / 영향: 정상 유한 계산값 불변.
    if run['state']=='EXECUTED' and (isinstance(contract,(ComparativeContract,AssociationContract,RegressionContract)) or (isinstance(contract,DescriptiveContract) and contract.method=='one_sample_t')):
        # [작성/수정: 전문가5·6] 2026-09-26 case61
        # 무엇을: 카이제곱은 p·통계량 검증, 정의하지 않은 estimate=None 허용 / 왜: 정상 검정의 거짓 차단 방지.
        # 입력·출력: chi-square 유효 p/통계량 -> EXECUTED / 검증: test_chi_square_no_effect_estimate_is_valid.
        fields=('p_value','statistic') if contract.method=='chi_square' else ('p_value','estimate','odds_ratio')
        for field in fields:
            if field in run['result']:
                try:finite=math.isfinite(float(run['result'][field]))
                except (TypeError,ValueError,OverflowError):finite=False
                if not finite:return {'state':'BLOCKED','reason':f'추론 통계량 {field}을(를) 유한하게 계산할 수 없습니다.','missing':[field],'result':None}
    # [수정: 0 이영] 2026-09-30 22:44 KST — C03: 1표본 t를 포함한 모든 추론 결과에 확인된 다중비교 정책을 적용한다.
    if analysis_spec is not None and run['state']=='EXECUTED' and inferential:
        # [작성/수정: 전문가5·6] 2026-09-26 case62
        # 무엇을: 대상 p 불일치도 fail-closed / 검증: test_executor_family_target_mismatch_blocks.
        try: run['result']=apply_multiplicity(run['result'],analysis_spec)
        except (TypeError,ValueError,KeyError) as exc:
            return {'state':'BLOCKED','reason':str(exc),'missing':['multiplicity family target'],'result':None}
    return run
