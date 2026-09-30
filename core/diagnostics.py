# [작성: 전문가4] 2026-09-23 case36
# 무엇을: 통계 가정 진단의 canonical API를 제공한다.
# 왜: 버전명 모듈에 신규 production 코드가 의존하지 않도록 한다.
# 입력·출력: 기존 case35 호환 API와 동일.
# 검증: tests/test_case36.py 및 전체 회귀 테스트.
"""case24 statistical assumption diagnostics.

WHY: case23 could rerun a test/model but did not surface enough diagnostics to distinguish
"the code ran" from "the method is scientifically defensible". Diagnostics never
auto-validate a paper; they expose assumption-sensitive signals for human review.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy import stats
from .normalization import filter_mask

def comparative_diagnostics(df,outcome,group_col,group_a,group_b):
    # [수정: 재현성] 2026-09-28 case72
    # 본 계산과 진단이 동일한 표본을 사용해야 가정 진단도 재현 가능하다.
    a=pd.to_numeric(df.loc[filter_mask(df[group_col],group_a),outcome],errors='coerce').dropna()
    b=pd.to_numeric(df.loc[filter_mask(df[group_col],group_b),outcome],errors='coerce').dropna()
    out={'n_a':len(a),'n_b':len(b)}
    out['review_flags']=['각 집단 유효 표본 3 미만'] if min(len(a),len(b))<3 else []
    if len(a)>=3 and len(b)>=3:
        lev=stats.levene(a,b,center='median'); out['levene_p']=float(lev.pvalue)
        va,vb=float(a.var(ddof=1)),float(b.var(ddof=1));out['variance_ratio']=float(max(va,vb)/max(min(va,vb),1e-12))
        if len(a)<=5000:out['shapiro_a_p']=float(stats.shapiro(a).pvalue)
        if len(b)<=5000:out['shapiro_b_p']=float(stats.shapiro(b).pvalue)
    return out

def association_diagnostics(df,x,y):
    z=pd.DataFrame({'x':pd.to_numeric(df[x],errors='coerce'),'y':pd.to_numeric(df[y],errors='coerce')}).dropna();out={'n':len(z)}
    if len(z)>=4:
        for c in ('x','y'):
            q1,q3=z[c].quantile([.25,.75]);iqr=q3-q1;out[f'{c}_iqr_outliers']=int(((z[c]<q1-1.5*iqr)|(z[c]>q3+1.5*iqr)).sum()) if iqr>0 else 0
    return out

def regression_diagnostics(df,outcome,predictors,method):
    import statsmodels.api as sm
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    from statsmodels.stats.diagnostic import het_breuschpagan
    z=df[[outcome,*predictors]].apply(pd.to_numeric,errors='coerce').dropna()
    out={'n_input':len(df),'n_complete_case':len(z),'dropped_for_missing':len(df)-len(z),'predictors':list(predictors)}
    if z.empty:return out
    X=sm.add_constant(z[predictors],has_constant='add');y=z[outcome]
    if len(predictors)>1:out['vif']={p:float(variance_inflation_factor(X.values,i)) for i,p in enumerate(X.columns) if p!='const'}
    try:
        if method=='linear_regression':
            fit=sm.OLS(y,X).fit();bp=het_breuschpagan(fit.resid,fit.model.exog);out['breusch_pagan_p']=float(bp[1]);out['max_cooks_distance']=float(np.max(fit.get_influence().cooks_distance[0]))
        elif method=='logistic_regression':
            vals=sorted(y.unique().tolist());yy=y if vals==[0,1] else (y==vals[-1]).astype(int);fit=sm.Logit(yy,X).fit(disp=False);out['converged']=bool(fit.mle_retvals.get('converged',True))
    except Exception as exc:out['diagnostic_error']=f'{type(exc).__name__}: {exc}'
    return out
