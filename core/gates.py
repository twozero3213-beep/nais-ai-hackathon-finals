"""case20 verification gates.

WHY case20 changed this module:
- A descriptive calculation being executable is not the same as proving a statistical method valid.
- Interpretation is N/A for claims with no inferential interpretation, not PENDING.
- Gate labels deliberately describe *verification scope* so reviewers cannot mistake a green card
  for a claim that the whole paper is scientifically valid.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import re
from decimal import Decimal, InvalidOperation
import numpy as np
import pandas as pd
from scipy import stats
from .methodology import method_contract

@dataclass
class GateResult:
    gate:str;status:str;title:str;detail:str;metrics:dict
    def to_dict(self):return asdict(self)

def semantic_gate(claim):
    if not getattr(claim,'semantic_confirmed',False):return GateResult('SEMANTIC','PENDING','근거 연결 확인 필요','대상·지표·시점·단위·필터가 같은 의미인지 사람이 확인해야 합니다.',{})
    return GateResult('SEMANTIC','PASS','의미 연결 확인','선택한 데이터·필터·분석방법의 의미 연결을 사람이 확인했습니다.',{})

def statistical_gate(df,claim):
    method=getattr(claim,'analysis_method','') or getattr(claim,'aggregation','mean'); contract=method_contract(method);col=getattr(claim,'column','')
    if contract['family']=='descriptive':
        return GateResult('METHOD','APPLICABLE','기술통계 재계산 가능',f'{method}는 연결된 변수·필터에서 결정론적으로 재계산합니다. 이 판정은 연구설계 전체의 타당성을 의미하지 않습니다.',{'method':method,'contract':contract})
    if col not in df.columns:return GateResult('METHOD','PENDING','분석 열 미연결','방법 검토 전에 결과변수 연결이 필요합니다.',{'method':method})
    if method in {'independent_t','welch_t'}:
        gc=getattr(claim,'group_column','');ga=str(getattr(claim,'group_a',''));gb=str(getattr(claim,'group_b',''))
        if not gc or gc not in df.columns or not ga or not gb:return GateResult('METHOD','PENDING','집단 정의 필요','그룹 열과 두 집단을 확인해야 합니다.',{'method':method})
        a=pd.to_numeric(df.loc[df[gc].astype(str)==ga,col],errors='coerce').dropna();b=pd.to_numeric(df.loc[df[gc].astype(str)==gb,col],errors='coerce').dropna()
        if len(a)<2 or len(b)<2:return GateResult('METHOD','PENDING','표본 부족','각 집단에 최소 2개 이상의 유효 관측이 필요합니다.',{'n_a':len(a),'n_b':len(b)})
        lev=stats.levene(a,b,center='median'); ratio=max(float(a.var(ddof=1)),float(b.var(ddof=1)))/max(min(float(a.var(ddof=1)),float(b.var(ddof=1))),1e-12)
        # Normality tests are diagnostics, not binary permission slips. Record only when n permits.
        sh_a=float(stats.shapiro(a).pvalue) if 3<=len(a)<=5000 else None;sh_b=float(stats.shapiro(b).pvalue) if 3<=len(b)<=5000 else None
        metrics={'method':method,'levene_p':float(lev.pvalue),'variance_ratio':ratio,'n_a':len(a),'n_b':len(b),'shapiro_a_p':sh_a,'shapiro_b_p':sh_b}
        if method=='independent_t' and float(lev.pvalue)<.05:return GateResult('METHOD','WARN','등분산 민감도 확인',"Student t-test의 등분산 가정을 점검했습니다. Welch 결과를 민감도 분석으로 함께 비교하세요.",metrics)
        return GateResult('METHOD','REVIEW','추론방법 진단 완료','표본수·분산·분포 진단을 기록했습니다. 진단 하나만으로 방법 타당성을 자동 확정하지 않습니다.',metrics)
    if method in {'linear_regression','logistic_regression'}:
        x=getattr(claim,'x_column','')
        if not x or x not in df.columns:return GateResult('METHOD','PENDING','설명변수 필요','회귀 검증을 위해 설명변수 열을 연결해야 합니다.',{'method':method})
        return GateResult('METHOD','REVIEW','회귀 진단 필요','계수 재현과 함께 잔차/선형성 또는 이진결과·수렴·분리 여부를 사람이 검토해야 합니다.',{'method':method,'contract':contract})
    return GateResult('METHOD','REVIEW','추론방법 검토','효과크기·신뢰구간·가정·다중비교·사전계획 여부를 함께 검토해야 합니다.',{'method':method,'contract':contract})

def reproduction_gate(verification_status,reason,calc):
    s=getattr(verification_status,'value',str(verification_status))
    if s=='SUPPORTED':return GateResult('REPRODUCTION','PASS','재현 성공','동일 분석조건의 재계산값이 허용오차 안에서 보고값과 일치합니다.',{'calculated':calc,'reason':reason})
    if s=='CONFLICT':return GateResult('REPRODUCTION','FAIL','수치 재현 실패','동일 분석조건의 재계산 결과가 보고값과 일치하지 않습니다.',{'calculated':calc,'reason':reason})
    if s=='OVERCLAIM':return GateResult('REPRODUCTION','WARN','표현 범위 검토','단일 근거로 넓은 일반화 표현을 재현할 수 없습니다.',{'reason':reason})
    return GateResult('REPRODUCTION','PENDING','재현 검토 대기',reason,{'calculated':calc})

# [수정: 전문가5/6] 2026-09-26 case64
# 원인: not significant 안의 significant 중복 검출 / 무엇·왜: 부정 표현 먼저 판별.
# 입력·출력: 부정/긍정 문장과 p -> FAIL 또는 REVIEW / 검증: test_interpretation_negation_first.
# 불리언 p·비확률·잘못된 α는 REVIEW: test_interpretation_invalid_probability_is_review.
# 원인: no significant·insignificant의 긍정 부분매칭 / 무엇·왜: 부정 제거 후 단어 경계로 긍정 탐지.
# 입력·출력: 추가 영어 부정×p -> REVIEW/FAIL / 검증: test_additional_negative_significance_phrases.
def interpretation_gate(claim,inferential_result):
    text=(getattr(claim,'text','') or '').lower();has_language=any(k in text for k in ['유의','significant','p=','p =','correlation','상관','odds ratio','회귀','regression'])
    if not has_language:return GateResult('INTERPRETATION','NA','별도 추론 해석 없음','이 Claim은 기술통계/수치 재현 Claim이므로 별도 유의성 해석 판정 대상이 아닙니다.',{})
    if not inferential_result or inferential_result.get('p_value') is None:return GateResult('INTERPRETATION','PENDING','추론 결과 필요','문장의 통계 해석을 비교하려면 해당 분석을 재실행해야 합니다.',{})
    try:
        raw_p=inferential_result['p_value'];raw_alpha=getattr(claim,'alpha',.05)
        p=float(raw_p);alpha=float(raw_alpha)
        if isinstance(raw_p,(bool,np.bool_)) or isinstance(raw_alpha,(bool,np.bool_)) or not 0<=p<=1 or not 0<alpha<1: raise ValueError("invalid probability")
    except (ValueError,TypeError,OverflowError):
        return GateResult('INTERPRETATION','REVIEW','추론 수치 확인 필요','p는 0~1 확률, α는 0과 1 사이의 수여야 합니다.',{})
    negative_phrases=['not statistically significant','no statistically significant','not significant','no significant','non-significant','nonsignificant','insignificant','유의하지']
    claims_nonsig=any(k in text for k in negative_phrases)
    positive_text=text
    for phrase in negative_phrases: positive_text=positive_text.replace(phrase,'')
    claims_sig=any(k in positive_text for k in ['유의한','유의하게']) or bool(re.search(r'\bsignificant(?:ly)?\b',positive_text))
    if claims_sig and claims_nonsig:return GateResult('INTERPRETATION','REVIEW','혼합 해석 확인 필요','긍정과 부정 결론이 함께 있어 단일 p값으로 문장 전체를 판정하지 않습니다.',{'p_value':p,'alpha':alpha})
    if claims_sig and p>=alpha:return GateResult('INTERPRETATION','FAIL','통계 해석 불일치',f'문장은 유의를 주장하지만 재분석 p={p:.4g}는 α={alpha:g} 이상입니다.',{'p_value':p,'alpha':alpha})
    if claims_nonsig and p<alpha:return GateResult('INTERPRETATION','FAIL','통계 해석 불일치',f'문장은 비유의를 주장하지만 재분석 p={p:.4g}는 α={alpha:g} 미만입니다.',{'p_value':p,'alpha':alpha})
    return GateResult('INTERPRETATION','REVIEW','과학적 해석 확인',f'p={p:.4g}, α={alpha:g}. p-value만으로 중요성·인과성·전체 결론을 자동 확정하지 않습니다.',{'p_value':p,'alpha':alpha,'estimate':inferential_result.get('estimate'),'ci95':inferential_result.get('ci95')})


# [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C06/C07: 검산 허용오차는 원문 숫자의 마지막 자릿수에만 연결한다.
_REPORTED_NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
_REPORTED_END=r'(?![\w%]|\.\d)'
_REPORTED_P=re.compile(r'\bp\s*(<=|>=|[=<>≤≥])\s*('+_REPORTED_NUMBER+r')'+_REPORTED_END,re.I)
_REPORTED_CI=re.compile(r'(?:(?P<level>\d+(?:\.\d+)?)\s*%\s*)?(?:\bCI\b|confidence interval|신뢰구간)\s*(?:[:=]|from)?\s*[\[(]?\s*(?P<low>'+_REPORTED_NUMBER+r')\s*(?:[,~–-]|to)\s*(?P<high>'+_REPORTED_NUMBER+r')'+_REPORTED_END,re.I)


def _printed_tolerance(token, value):
    try:
        printed=Decimal(token)
        if float(printed)!=float(value):return None
        # p=0 또는 p=1처럼 소수/지수가 없는 경계 표기는 넓은 반올림 구간으로 확장하지 않는다.
        if '.' not in token and 'e' not in token.lower():return None
        tolerance=float(Decimal('0.5').scaleb(printed.as_tuple().exponent))
        return tolerance if math.isfinite(tolerance) else None
    except (InvalidOperation,ValueError,OverflowError):return None


def _valid_interval(values):
    try:
        if isinstance(values,(str,bytes)) or len(values)!=2:return None
        if any(isinstance(v,(bool,np.bool_)) or not math.isfinite(float(v)) for v in values):return None
        lo,hi=map(float,values)
        return (lo,hi) if lo<=hi else None
    except (TypeError,ValueError,OverflowError):return None


# [수정: 전문가5/6] 2026-09-26 case64
# 원인: > 등 연산자 누락이 PASS / 무엇·왜: 5개 비교 및 확률 범위·미지원 연산자 검사.
# 입력·출력: 보고 p/연산자/재계산 p -> PASS·FAIL·REVIEW / 검증: test_p_operators, test_invalid_probabilities_rejected.
def inferential_reproduction_gate(claim,result):
    """Compare reported inferential quantities with deterministic reanalysis.

    case20: p-values/effect sizes are first-class reproducibility targets. We do not convert
    a matching p-value into scientific validity; this gate only asks whether the reported
    number can be reproduced under the confirmed method/conditions.
    """
    if not result:return GateResult('REPRODUCTION','PENDING','추론 재현 대기','재분석 결과가 필요합니다.',{})
    diffs=[];metrics={'reanalysis':result}
    rp=getattr(claim,'reported_p_value',None);op=getattr(claim,'reported_p_operator','')
    reff=getattr(claim,'reported_effect',None);kind=getattr(claim,'effect_kind','')
    # [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C06/C08: 보고된 CI를 무시하지 않고 미지원 신뢰수준은 사람 검토로 남긴다.
    rci=getattr(claim,'reported_ci95',None)
    source=getattr(claim,'source_quote','') or getattr(claim,'text','') or ''
    source_ci=_REPORTED_CI.search(source)
    source_level=float(source_ci.group('level')) if source_ci and source_ci.group('level') else None
    if source_ci and (source_level!=95 or rci is None):
        metrics.update(reported_confidence_level=source_level)
        return GateResult('REPRODUCTION','REVIEW','신뢰구간 확인 필요','원문의 구간은 명시된 95% CI와 연결된 두 경계값을 확인한 후 비교해야 합니다.',metrics)
    if rci is not None:
        computed_ci=result.get('ci95_or') if kind=='odds_ratio' else result.get('ci95')
        if computed_ci is None and kind!='odds_ratio':computed_ci=result.get('ci95_beta')
        reported_bounds=_valid_interval(rci);computed_bounds=_valid_interval(computed_ci)
        if reported_bounds is None or computed_bounds is None:
            return GateResult('REPRODUCTION','REVIEW','신뢰구간 계산 확인 필요','보고·재계산 CI에는 유한하고 순서가 맞는 두 경계값이 필요합니다.',metrics)
        tolerances=[None,None]
        if source_ci:
            tolerances=[_printed_tolerance(source_ci.group(key),v) for key,v in zip(('low','high'),reported_bounds)]
        metrics.update(reported_ci95=reported_bounds,recomputed_ci95=computed_bounds,ci_tolerances=tolerances)
        for index,(reported,actual,tolerance) in enumerate(zip(reported_bounds,computed_bounds,tolerances)):
            matches=math.isclose(actual,reported,rel_tol=1e-12,abs_tol=1e-12)
            # [수정: 0 이영 · Codex] 2026-09-30T22:59:03+09:00 — 반올림 구간 경계의 이진 부동소수점 차이만 허용한다.
            if tolerance is not None:
                difference=abs(actual-reported)
                matches=matches or difference<=tolerance or math.isclose(difference,tolerance,rel_tol=1e-12,abs_tol=0.0)
            if not matches:diffs.append(f'95% CI {index+1}번째 경계 보고 {reported:g} vs 재분석 {actual:.6g}')
    # [수정: 전문가6] 2026-09-25 case47
    # 종류: 오류수정 / 재현 방법: 상수열 Pearson의 NaN p·효과에서 차이 비교가 False가 되어 PASS / 변경 전: 비유한 값도 수치 비교 통과 / 변경 후: 비교 대상이 없거나 비유한 값이면 REVIEW / 왜: 계산 불능을 재현 성공으로 승격 금지 / 영향: 기존 정상 유한 수치 판정 불변.
    try:
        if rp is not None and not all(not isinstance(v,(bool,np.bool_)) and math.isfinite(float(v)) and 0<=float(v)<=1 for v in (rp,result.get('p_value'))):
            return GateResult('REPRODUCTION','REVIEW','추론 수치 계산 불가','보고 p값 또는 재계산 p값이 유한한 0~1 확률이 아닙니다.',metrics)
        if reff is not None:
            effect=result.get('odds_ratio') if kind=='odds_ratio' else result.get('estimate')
            if not all(math.isfinite(float(v)) for v in (reff,effect)):
                return GateResult('REPRODUCTION','REVIEW','추론 수치 계산 불가','보고 효과크기 또는 재계산 효과크기가 유한하지 않습니다.',metrics)
    except (TypeError,ValueError,OverflowError):
        return GateResult('REPRODUCTION','REVIEW','추론 수치 계산 불가','비교할 추론 수치가 없습니다.',metrics)
    if rp is not None and result.get('p_value') is not None:
        if op not in {'=','<','>','<=','>='}:
            return GateResult('REPRODUCTION','REVIEW','p 비교 연산자 확인 필요','지원하는 명시적 연산자는 =, <, >, <=, >= 입니다.',metrics)
        rp=float(rp)
        actual=float(result['p_value']);metrics.update(reported_p=rp,recomputed_p=actual,p_operator=op)
        # [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C07: 작은 p에도 0.001을 허용하던 오차 대신 명시된 출력 정밀도만 허용한다.
        if op=='=':
            printed_p=next((m for m in _REPORTED_P.finditer(source) if m.group(1)=='=' and float(m.group(2))==rp),None)
            tolerance=_printed_tolerance(printed_p.group(2),rp) if printed_p else None
            metrics.update(p_tolerance=tolerance,p_tolerance_basis='source_rounding' if tolerance is not None else 'numeric_equality')
            matches=math.isclose(actual,rp,rel_tol=1e-12,abs_tol=0.0)
            # [수정: 0 이영 · Codex] 2026-09-30T22:59:03+09:00 — 반올림 구간 경계의 이진 부동소수점 차이만 허용한다.
            if tolerance is not None:
                difference=abs(actual-rp)
                matches=matches or difference<=tolerance or math.isclose(difference,tolerance,rel_tol=1e-12,abs_tol=0.0)
            if not matches:diffs.append(f'p-value 보고 {rp:g} vs 재분석 {actual:.4g}')
        if op=='<' and not actual<rp:diffs.append(f'p-value 보고 p<{rp:g}이나 재분석 {actual:.4g}')
        if op=='>' and not actual>rp:diffs.append(f'p-value 보고 p>{rp:g}이나 재분석 {actual:.4g}')
        if op=='<=' and not actual<=rp:diffs.append(f'p-value 보고 p<={rp:g}이나 재분석 {actual:.4g}')
        if op=='>=' and not actual>=rp:diffs.append(f'p-value 보고 p>={rp:g}이나 재분석 {actual:.4g}')
    if reff is not None:
        actual=result.get('odds_ratio') if kind=='odds_ratio' else result.get('estimate')
        metrics.update(reported_effect=reff,recomputed_effect=actual,effect_kind=kind)
        tol=.05 if kind=='odds_ratio' else .02
        if actual is None or abs(float(actual)-reff)>tol:diffs.append(f'{kind} 보고 {reff:g} vs 재분석 {actual}')
    if diffs:return GateResult('REPRODUCTION','FAIL','추론 통계량 재현 실패','; '.join(diffs),metrics)
    if rp is None and reff is None and rci is None:return GateResult('REPRODUCTION','REVIEW','추론 결과 기록','재분석 결과는 생성했지만 비교할 보고 p-value/효과크기/95% CI가 명시되지 않았습니다.',metrics)
    # [수정: 전문가6] 2026-09-25 case43
    # 종류: 오류수정 / 재현 방법: 표본 부족 경고가 있어도 p 일치만으로 PASS / 변경 전: 숫자 일치 즉시 PASS / 변경 후: 가정 경고 시 사람 검토 / 왜: 실행 성공과 방법 적합성 분리 / 영향: 수치 일치는 기록하되 결론 자동 확정 안 함.
    if result.get('assumption_alerts'):
        return GateResult('REPRODUCTION','REVIEW','수치는 일치, 가정 검토 필요','; '.join(result['assumption_alerts']),metrics)
    return GateResult('REPRODUCTION','PASS','추론 통계량 재현','보고된 추론 통계량이 설정된 수치 허용기준 안에서 재현됩니다.',metrics)
