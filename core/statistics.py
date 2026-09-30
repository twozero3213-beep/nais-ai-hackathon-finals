"""case19 statistical verification library.

Deterministic only: language models/heuristics may propose a plan, but every number
returned here is recomputed from the connected dataframe. Methods deliberately use
well-known estimators/tests and return assumptions/limitations for human review.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy import stats
from .normalization import equivalent, canonical_category, filter_mask

DESCRIPTIVE_METHODS=("mean","weighted_mean","sum","median","min","max","count","proportion","std","q25","q75","row_count","missing_cells")
INFERENTIAL_METHODS=("one_sample_t","independent_t","welch_t","paired_t","mannwhitney_u","wilcoxon_signed","pearson_r","spearman_r","chi_square","fisher_exact","linear_regression","logistic_regression")


# [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C05: 순위검정도 무한대를 순위로 바꾸기 전에 입력 경계에서 거부한다.
def _require_finite_numeric_input(df, columns):
    for col in dict.fromkeys(columns):
        if col and col in df.columns:
            values=pd.to_numeric(df[col],errors="coerce").dropna()
            if not np.isfinite(values).all():
                raise ValueError(f"수치형 입력 {col}에 무한대가 포함되어 있습니다.")


def numeric(df,col):
    if not col or col not in df.columns:return pd.Series(dtype=float)
    return pd.to_numeric(df[col],errors="coerce").dropna()


# [수정: 전문가5/6] 2026-09-26 case64
# 원인: 입력 무한대·표본 부족·합계 overflow의 성공 반환 / 무엇·왜: 공통 기술통계에서 유한성 검증.
# 입력·출력: 잘못된 입력/결과 -> ValueError / 검증: test_descriptive_invalid_computation_fails_closed_in_both_paths.
# 원인: 가중치 합 overflow의 유한한 오답 / 무엇·왜: 최대 가중치로 나눈 뒤 합 1 정규화.
# 입력·출력: x=[0.1,0.1], w=[1e308,1e308] -> 0.1 / 검증: test_weighted_mean_overflow_is_stable_in_both_paths.
def descriptive(df,col,method,weight_col="",success_value=None):
    # [수정: 전문가5] 2026-09-25 case45
    # 종류: 통계검정추가 / 재현 방법: 전체 344행·19결측 주장은 임의의 숫자열 count로 대체돼 분모가 틀릴 수 있음 / 변경 전: 열 단위 count만 지원 / 변경 후: 행 수·전체 결측 셀 수를 명시적 데이터셋 방법으로 계산 / 왜: 원문 분모와 실행 방법 일치 / 영향: 두 방법만 열 없는 계약 허용.
    if method=="row_count":
        return float(len(df)),{"n":len(df),"expression":"row_count(all rows)","method":method}
    if method=="missing_cells":
        return float(df.isna().sum().sum()),{"n":len(df),"cells":int(df.size),"expression":"missing_cells(all columns)","method":method}
    if method=="proportion":
        # [수정: 전문가5] 2026-09-25 case40
        # 종류: 오류수정
        # 재현 방법: [1.0, 0.0, NaN]의 성공값 "1"을 기존 문자열 비교하면 0%가 된다.
        # 변경 전: "1.0"과 "1"을 다른 값으로 보고, 정규화 결측 토큰은 분모에 남겼다.
        # 변경 후: 공통 범주/수치 동치 규칙을 쓰고 비결측 관측만 분모에 넣는다.
        # 왜: 같은 숫자 표기의 성공비율과 결측 분모가 정확해야 한다.
        # 영향: proportion의 숫자 표기·공통 alias 결과만 교정한다.
        raw=df[col].dropna(); raw=raw[raw.map(lambda x: canonical_category(x) is not None)]
        target=success_value if success_value is not None else 1
        if len(raw)==0: raise ValueError("비율 계산에 사용할 관측값이 없습니다.")
        val=float(raw.map(lambda x: equivalent(x,target)).mean()*100)
        return val,{"n":len(raw),"expression":f"proportion({col}=={target})","method":method}
    s=numeric(df,col)
    if not np.isfinite(s).all(): raise ValueError("수치형 입력에 무한대가 포함되어 있습니다.")
    if method=="count": return float(len(s)),{"n":len(s),"expression":f"count({col})"}
    if len(s)==0: raise ValueError("수치형 관측값이 없습니다.")
    if method=="mean": val=float(s.mean())
    elif method=="sum": val=float(s.sum())
    elif method=="median": val=float(s.median())
    elif method=="min": val=float(s.min())
    elif method=="max": val=float(s.max())
    elif method=="std": val=float(s.std(ddof=1))
    elif method=="q25": val=float(s.quantile(.25))
    elif method=="q75": val=float(s.quantile(.75))
    elif method=="weighted_mean":
        if not weight_col or weight_col not in df.columns: raise ValueError("가중평균에는 가중치 열이 필요합니다.")
        x=pd.to_numeric(df[col],errors="coerce");w=pd.to_numeric(df[weight_col],errors="coerce")
        if not np.isfinite(w.dropna()).all(): raise ValueError("가중치에 무한대가 포함되어 있습니다.")
        ok=x.notna()&w.notna()&(w>=0);x=x[ok];w=w[ok]
        if len(x)==0 or float(w.max())<=0: raise ValueError("유효한 값/가중치가 없습니다.")
        w=w/w.max();w=w/w.sum()
        val=float(np.dot(x,w)); s=x
    else: raise ValueError(f"지원하지 않는 기술통계 방법: {method}")
    if not math.isfinite(val): raise ValueError("기술통계 결과를 유한하게 계산할 수 없습니다.")
    return val,{"n":len(s),"expression":f"{method}({col})","method":method}


# [수정: 전문가5/6] 2026-09-26 case64
# 원인: OLS CI의 정규 1.96 사용 / 무엇·왜: 잔차 자유도 n-2의 t 임계값 적용.
# 입력·출력: 네 관측 -> df=2 CI / 검증: test_ols_small_sample_t_interval 고정 기대값.
def inferential(df,method,outcome,group_col="",group_a="",group_b="",x_col="",mu0=0.0):
    """Return estimate/test statistic/p-value/CI plus explicit assumptions."""
    # [작성/수정: 전문가5·6] 2026-09-26 case61
    # 무엇을: 범주검정에서 명시된 두 집단만 선택 / 왜: 선택 밖 집단을 넣어 검정 모집단과 p가 바뀌는 오류 차단.
    # 입력·출력: A/B 계약과 A/B/C 자료 -> A/B 빈도표 / 검증: test_categorical_comparison_excludes_unselected_groups.
    # [수정: 통계·재현성] 2026-09-28 case71
    # 무엇을: 모든 두 집단 추론검정의 집단 선택을 공통 filter_mask() 정규화 규칙으로 통일한다.
    # 왜: CSV가 같은 집단을 1.0으로 저장하고 분석 명세가 1로 기록하는 등 표현형만 달라도
    #     문자열 직접 비교는 관측치를 누락시켜 재계산 결과를 바꾼다. 같은 원자료·같은 분석 의미라면
    #     파일 직렬화/표기 차이와 무관하게 같은 표본이 선택되어야 재현성(Reproducibility)이 보장된다.
    # 영향: 숫자 1↔1.0, 대소문자/공백, 공통 범주 alias(treatment↔처리군 등)를 기존
    #       normalization.equivalent 규칙과 동일하게 처리한다. 도메인별 임의 재코딩은 추가하지 않는다.
    # 검증: tests/test_case71_reproducible_group_selection.py에서 t/Welch/Mann-Whitney/chi-square/Fisher 회귀 고정.
    if method in ("independent_t", "welch_t", "mannwhitney_u"):
        if not group_col or group_col not in df.columns or group_a=="" or group_b=="" or equivalent(group_a, group_b):
            raise ValueError("두 집단 비교에는 서로 다른 두 집단과 유효한 그룹 열이 필요합니다.")
        mask_a=filter_mask(df[group_col], group_a)
        mask_b=filter_mask(df[group_col], group_b)
    elif method in ("chi_square", "fisher_exact") and (group_a!="" or group_b!=""):
        # 과거 API는 group_a/group_b 생략 시 데이터 전체 분할표를 허용한다.
        # 명시 선택이 있을 때만 재현성 정규화를 적용해 기존 계약과 하위 호환성을 함께 보존한다.
        if not group_col or group_col not in df.columns or group_a=="" or group_b=="" or equivalent(group_a, group_b):
            raise ValueError("범주 비교에는 서로 다른 두 집단과 유효한 그룹 열이 필요합니다.")
        mask_a=filter_mask(df[group_col], group_a)
        mask_b=filter_mask(df[group_col], group_b)
        # [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C04: 선택 마스크와 같은 두 집단 표기로 분할표를 만들고 원자료는 보존한다.
        selected=mask_a | mask_b
        df=df[selected].copy()
        df[group_col]=np.where(mask_a[selected].to_numpy(),group_a,group_b)
    # [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C05: 두 집단 검정은 선택 표본, 나머지 수치 검정은 연결 열의 유한성을 확인한다.
    if method not in ("chi_square", "fisher_exact"):
        numeric_frame=df[mask_a | mask_b] if method in ("independent_t", "welch_t", "mannwhitney_u") else df
        _require_finite_numeric_input(numeric_frame,[outcome,x_col])
    assumptions=[]; result={"method":method}
    # [수정: 통계 안전성/재현성] 2026-09-28 case72
    # scipy가 NaN을 반환하거나 빈/퇴화 표본을 경고만 하고 계속하는 경우가 있다.
    # 실행 불가능한 검정을 성공 객체로 남기면 환경/버전에 따라 판정이 달라질 수 있으므로 fail-closed 한다.
    def require_n(series, minimum, label):
        if len(series) < minimum: raise ValueError(f"{label}에는 유효 관측값이 최소 {minimum}개 필요합니다.")
    def require_finite_result(obj):
        for key in ("statistic","p_value"):
            if key in obj and not math.isfinite(float(obj[key])): raise ValueError(f"{key}을(를) 유한하게 계산할 수 없습니다.")

    if method=="one_sample_t":
        y=numeric(df,outcome); require_n(y,2,"1표본 t 검정"); r=stats.ttest_1samp(y,mu0,nan_policy="omit"); est=float(y.mean()-mu0); se=float(y.sem()); ci=stats.t.interval(.95,len(y)-1,loc=est,scale=se) if len(y)>1 else (math.nan,math.nan)
        result.update(n=len(y),estimate=est,statistic=float(r.statistic),p_value=float(r.pvalue),ci95=tuple(map(float,ci)));assumptions=["독립 관측","평균 추론에 적절한 표본/분포"]
    elif method in ("independent_t","welch_t"):
        if not group_col: raise ValueError("두 집단 t 검정에는 그룹 열이 필요합니다.")
        a=numeric(df[mask_a],outcome);b=numeric(df[mask_b],outcome); require_n(a,2,"집단 A"); require_n(b,2,"집단 B")
        equal=method=="independent_t";r=stats.ttest_ind(a,b,equal_var=equal,nan_policy="omit");est=float(a.mean()-b.mean())
        va=float(a.var(ddof=1)); vb=float(b.var(ddof=1)); na=len(a); nb=len(b)
        if equal:
            sp2=((na-1)*va+(nb-1)*vb)/(na+nb-2); se=math.sqrt(sp2*(1/na+1/nb)); dfree=na+nb-2; pooled=math.sqrt(sp2)
        else:
            se=math.sqrt(va/na+vb/nb); dfree=(va/na+vb/nb)**2/((va/na)**2/(na-1)+(vb/nb)**2/(nb-1)); pooled=math.sqrt(((na-1)*va+(nb-1)*vb)/(na+nb-2))
        crit=float(stats.t.ppf(.975,dfree)); ci=(est-crit*se,est+crit*se); d=est/pooled if pooled>0 else math.nan; correction=1-3/(4*(na+nb)-9); g=d*correction if not math.isnan(d) else math.nan
        result.update(n_a=na,n_b=nb,estimate=est,statistic=float(r.statistic),p_value=float(r.pvalue),df=float(dfree),ci95=tuple(map(float,ci)),cohen_d=float(d),hedges_g=float(g));assumptions=["집단 간 독립", "연속형 결과", "등분산" if equal else "Welch 방식으로 등분산을 가정하지 않음"]
    elif method=="paired_t":
        if not x_col: raise ValueError("대응 t 검정에는 비교 열이 필요합니다.")
        z=pd.DataFrame({"a":pd.to_numeric(df[outcome],errors="coerce"),"b":pd.to_numeric(df[x_col],errors="coerce")}).dropna(); require_n(z,2,"대응 t 검정"); r=stats.ttest_rel(z.a,z.b);d=z.a-z.b;est=float(d.mean());se=float(d.sem());ci=stats.t.interval(.95,len(d)-1,loc=est,scale=se) if len(d)>1 else (math.nan,math.nan)
        result.update(n=len(d),estimate=est,statistic=float(r.statistic),p_value=float(r.pvalue),ci95=tuple(map(float,ci)));assumptions=["동일 개체/쌍의 대응 관측","차이값의 평균 추론"]
    elif method=="mannwhitney_u":
        if not group_col: raise ValueError("Mann–Whitney U 검정에는 그룹 열이 필요합니다.")
        a=numeric(df[mask_a],outcome);b=numeric(df[mask_b],outcome); require_n(a,1,"집단 A"); require_n(b,1,"집단 B");r=stats.mannwhitneyu(a,b,alternative="two-sided")
        result.update(n_a=len(a),n_b=len(b),estimate=float(a.median()-b.median()),statistic=float(r.statistic),p_value=float(r.pvalue),ci95=None);assumptions=["집단 간 독립","순서형/연속형 결과","분포 위치 비교의 해석은 분포 형태를 함께 검토"]
    elif method=="wilcoxon_signed":
        if not x_col: raise ValueError("Wilcoxon signed-rank 검정에는 비교 열이 필요합니다.")
        z=pd.DataFrame({"a":pd.to_numeric(df[outcome],errors="coerce"),"b":pd.to_numeric(df[x_col],errors="coerce")}).dropna(); require_n(z,1,"Wilcoxon signed-rank 검정");d=z.a-z.b
        if not (d != 0).any(): raise ValueError("Wilcoxon signed-rank 검정에는 0이 아닌 차이가 필요합니다.")
        r=stats.wilcoxon(d)
        result.update(n=len(d),estimate=float(d.median()),statistic=float(r.statistic),p_value=float(r.pvalue),ci95=None);assumptions=["대응 관측","차이의 순위 기반 검정"]
    elif method in ("pearson_r","spearman_r"):
        if not x_col: raise ValueError("상관분석에는 두 번째 수치 열이 필요합니다.")
        z=pd.DataFrame({"x":pd.to_numeric(df[x_col],errors="coerce"),"y":pd.to_numeric(df[outcome],errors="coerce")}).dropna(); require_n(z,2,"상관분석")
        if z.x.nunique()<2 or z.y.nunique()<2: raise ValueError("상관분석에는 두 변수 모두 최소 두 개의 서로 다른 값이 필요합니다.")
        r=stats.pearsonr(z.x,z.y) if method=="pearson_r" else stats.spearmanr(z.x,z.y)
        result.update(n=len(z),estimate=float(r.statistic),statistic=float(r.statistic),p_value=float(r.pvalue),ci95=None);assumptions=["관측쌍 독립","Pearson은 선형 관계" if method=="pearson_r" else "Spearman은 단조 관계"]
    elif method=="chi_square":
        if not group_col: raise ValueError("카이제곱 검정에는 두 범주형 열이 필요합니다.")
        tab=pd.crosstab(df[group_col],df[outcome])
        if tab.shape[0] < 2 or tab.shape[1] < 2: raise ValueError("카이제곱 검정에는 각 범주형 변수에 최소 두 수준이 필요합니다.")
        chi,p,dof,expected=stats.chi2_contingency(tab);result.update(n=int(tab.values.sum()),estimate=None,statistic=float(chi),p_value=float(p),df=int(dof),ci95=None,min_expected=float(expected.min()));assumptions=["관측 독립","기대도수가 지나치게 작지 않음"]
    elif method=="fisher_exact":
        if not group_col: raise ValueError("Fisher exact 검정에는 두 범주형 열이 필요합니다.")
        tab=pd.crosstab(df[group_col],df[outcome])
        if tab.shape!=(2,2): raise ValueError("Fisher exact 검정은 현재 2x2 표만 지원합니다.")
        r=stats.fisher_exact(tab.values);result.update(n=int(tab.values.sum()),estimate=float(r.statistic),statistic=float(r.statistic),p_value=float(r.pvalue),ci95=None);assumptions=["관측 독립","2x2 분할표"]
    elif method=="logistic_regression":
        if not x_col: raise ValueError("로지스틱 회귀에는 설명변수 열이 필요합니다.")
        return logistic_regression(df,outcome,x_col)
    elif method=="linear_regression":
        if not x_col: raise ValueError("단순선형회귀에는 설명변수 열이 필요합니다.")
        z=pd.DataFrame({"x":pd.to_numeric(df[x_col],errors="coerce"),"y":pd.to_numeric(df[outcome],errors="coerce")}).dropna()
        if len(z)<=2: raise ValueError("OLS 추론에는 잔차 자유도가 양수인 최소 3개 관측이 필요합니다.")
        r=stats.linregress(z.x,z.y);dfree=len(z)-2;crit=float(stats.t.ppf(.975,dfree))
        result.update(n=len(z),df=dfree,estimate=float(r.slope),intercept=float(r.intercept),statistic=float(r.rvalue),p_value=float(r.pvalue),ci95=(float(r.slope-crit*r.stderr),float(r.slope+crit*r.stderr)));assumptions=["선형성","오차 독립","등분산성/잔차 조건은 별도 진단 필요"]
    else: raise ValueError(f"지원하지 않는 추론 방법: {method}")
    require_finite_result(result)
    result["assumptions"]=assumptions
    return result

# case20 CHANGE: add a deterministic logistic-regression verifier. We use statsmodels here
# because it exposes coefficient/SE/CI/convergence diagnostics needed for auditability.
def logistic_regression(df,outcome,x_col):
    # [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C05: 직접 호출도 fit 전에 비유한 입력을 명시적으로 차단한다.
    _require_finite_numeric_input(df,[outcome,x_col])
    import statsmodels.api as sm
    z=pd.DataFrame({'x':pd.to_numeric(df[x_col],errors='coerce'),'y':pd.to_numeric(df[outcome],errors='coerce')}).dropna()
    vals=sorted(z.y.unique().tolist())
    if len(vals)!=2: raise ValueError('로지스틱 회귀 결과변수는 두 값의 이진 변수여야 합니다.')
    if vals!=[0,1]: z['y']=(z.y==vals[-1]).astype(int)
    X=sm.add_constant(z[['x']],has_constant='add')
    fit=sm.Logit(z.y,X).fit(disp=False)
    beta=float(fit.params['x']); se=float(fit.bse['x']); ci=fit.conf_int().loc['x'].tolist()
    return {'method':'logistic_regression','n':len(z),'estimate':beta,'odds_ratio':float(np.exp(beta)),'se':se,'statistic':float(fit.tvalues['x']),'p_value':float(fit.pvalues['x']),'ci95_beta':tuple(map(float,ci)),'ci95_or':tuple(map(float,np.exp(ci))),'converged':bool(fit.mle_retvals.get('converged',True)),'assumptions':['이진 결과','독립 관측','logit 선형성/분리 여부 검토']}


def adjust_pvalues(p_values,method='holm'):
    """Multiplicity correction kept local/deterministic for reproducible batch verification."""
    # [작성/수정: 전문가5·6] 2026-09-26 case62
    # 무엇을: 보정 경계에서 전체 1차원 유한 확률 검증 / 왜: NaN·범위 밖 값을 성공 반환하지 않음.
    # 입력·출력: 비어 있거나 잘못된 가족 -> ValueError / 검증: test_invalid_family_rejected.
    # [작성/수정: 전문가5·6] 2026-09-26 case62
    # 무엇을: 거대 정수 변환 오류도 ValueError로 통일 / 왜: 명세·UI가 안전하게 차단하도록 함.
    # 검증: test_oversized_integer_family_rejected_as_value_error 실패 선행 후 통과.
    try: ps=np.asarray(p_values,dtype=float)
    except OverflowError as exc:
        raise ValueError('p값이 유한 실수 표현 범위를 초과합니다.') from exc
    if ps.ndim!=1 or ps.size==0 or not np.isfinite(ps).all() or ((ps<0)|(ps>1)).any():
        raise ValueError('다중비교 가족은 비어 있지 않은 1차원 유한 p값(0~1)이어야 합니다.')
    m=len(ps)
    if method=='bonferroni':return np.minimum(ps*m,1.0).tolist()
    order=np.argsort(ps);ranked=ps[order]
    if method=='holm':
        adj=np.maximum.accumulate((m-np.arange(m))*ranked);adj=np.minimum(adj,1.0)
    elif method in ('fdr_bh','bh'):
        raw=ranked*m/(np.arange(m)+1);adj=np.minimum.accumulate(raw[::-1])[::-1];adj=np.minimum(adj,1.0)
    else:raise ValueError('지원하지 않는 다중비교 보정 방법입니다.')
    out=np.empty(m);out[order]=adj;return out.tolist()

# case24 CHANGE — WHY: case22 stored predictors as a list but executed only predictors[0].
# This deterministic statsmodels path makes the contract and execution semantics agree.
def multivariable_regression(df,outcome,predictors,method='linear_regression'):
    # [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C05: 모든 연결 설명변수와 결과변수를 직접 호출 경계에서도 검사한다.
    _require_finite_numeric_input(df,[outcome,*predictors])
    import statsmodels.api as sm
    cols=[outcome,*predictors]
    z=df[cols].apply(pd.to_numeric,errors='coerce').dropna()
    if z.empty:raise ValueError('회귀분석에 사용할 complete-case 관측값이 없습니다.')
    X=sm.add_constant(z[predictors],has_constant='add'); y=z[outcome]
    if method=='logistic_regression':
        vals=sorted(y.unique().tolist())
        if len(vals)!=2:raise ValueError('로지스틱 회귀 결과변수는 두 값의 이진 변수여야 합니다.')
        if vals!=[0,1]:y=(y==vals[-1]).astype(int)
        fit=sm.Logit(y,X).fit(disp=False);model='logistic_regression'
    elif method=='linear_regression':
        fit=sm.OLS(y,X).fit();model='linear_regression'
    else:raise ValueError('다중회귀는 linear_regression 또는 logistic_regression만 지원합니다.')
    terms={}
    ci=fit.conf_int()
    for p in predictors:
        beta=float(fit.params[p]);lo,hi=map(float,ci.loc[p].tolist())
        item={'estimate':beta,'se':float(fit.bse[p]),'statistic':float(fit.tvalues[p]),'p_value':float(fit.pvalues[p]),'ci95_beta':(lo,hi)}
        if model=='logistic_regression':item.update(odds_ratio=float(np.exp(beta)),ci95_or=(float(np.exp(lo)),float(np.exp(hi))))
        terms[p]=item
    return {'method':model,'n':len(z),'predictors':predictors,'terms':terms,'intercept':float(fit.params.get('const',math.nan)),'r_squared':float(getattr(fit,'rsquared',math.nan)) if model=='linear_regression' else None,'converged':bool(getattr(fit,'mle_retvals',{}).get('converged',True)) if model=='logistic_regression' else True,'assumptions':['complete-case analysis','모형 specification/잔차·선형성·공선성은 별도 검토 필요']}
