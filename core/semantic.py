"""Auditable local semantic mapper used as a fallback when no external model is connected.

case20 CHANGE: population/timepoint extraction now handles Korean + English study language and
multi-condition filters. The matcher remains a *proposal engine*, never the final verifier.
Keeping this boundary is intentional: better LLMs can replace proposal generation later
without changing deterministic verification, provenance, or audit modules.
"""
import re
import logging
import pandas as pd
logger=logging.getLogger("evidence_gate_case24.semantic")

STOP={'평균','결과','보고','확인','대한','에서','으로','했다','였다','그리고','the','of','and','rate','value','pct','group','average','was','were'}
ALIASES={
 'change_score':['change score','mean change','변화량','변화 점수'],
 'responder':['responder','response status','반응자'],
 'age':['age','연령','나이'],
 'outcome_pct':['처리군','대조군','개선','개선율','효과','outcome','outcome pct','change','improvement'],
 'satisfaction_rate':['만족도','만족','satisfaction','satisfaction rate'],
 'employment_rate':['고용률','고용','employment'],
 'score':['점수','score'],
}

def tokens(s):
 return {x for x in re.findall(r'[가-힣A-Za-z0-9]+',str(s).lower()) if len(x)>1 and x not in STOP}

def decompose_claim(text,value=None):
 t=text.strip(); low=t.lower()
 population=''
 # case20 BUGFIX: English labels use word boundaries ('men' must not match 'treatment').
 has_treat=bool(re.search(r'\btreatment\s+group\b',low)); has_control=bool(re.search(r'\bcontrol\s+group\b',low))
 if has_treat and has_control: population='Treatment vs Control'
 elif has_treat: population='Treatment'
 elif has_control: population='Control'
 else:
  for needle,label in [('처리군','처리군'),('대조군','대조군'),('청년층','청년층'),('남성','남성'),('여성','여성')]:
   if needle in t: population=label; break
  if not population:
   for needle,label in [('female','Female'),('women','Female'),('male','Male'),('men','Male'),('overall','Overall')]:
    if re.search(rf'\b{needle}\b',low): population=label; break
 time=''
 m=re.search(r'(20\d{2}년|\d+주(?:차)?|week\s*\d+|month\s*\d+|baseline|follow[- ]?up|전년|기준시점)',low,re.I)
 if m: time=m.group(1)
 direction='increase' if any(x in low for x in ['증가','개선','상승','increase','improv']) else ('decrease' if any(x in low for x in ['감소','하락','decrease','decline']) else '')
 statistic='mean' if any(x in low for x in ['평균','average','mean']) else ('sum' if any(x in low for x in ['합계','sum']) else ('median' if any(x in low for x in ['중앙값','median']) else 'mean'))
 unit='%' if '%' in t else ''
 overclaim=any(x in low for x in ['모든 조건','항상','전부','모두','예외 없이','all conditions','every subgroup','all subgroups','always'])
 claim_kind='significance' if any(x in low for x in ['significant','유의']) else ('correlation' if any(x in low for x in ['correlation','correlated','상관']) else ('regression' if any(x in low for x in ['regression','회귀','odds ratio','or=','or =']) else 'numeric'))
 metric=''; x_hint=''; predictor_hints=[]
 # case20: association/regression claims have an outcome and an explanatory variable.
 if claim_kind=='correlation' and 'satisfaction' in low: metric='satisfaction_rate'; x_hint='age' if re.search(r'\bage\b',low) else ''
 elif claim_kind=='regression':
  if 'responder' in low: metric='responder'
  elif 'change score' in low or 'change_score' in low: metric='change_score'
  for name,patterns in [('age',[r'\bage\b','연령']),('baseline_score',[r'baseline[_ ]?score','기저.*점수']),('satisfaction_rate',[r'satisfaction[_ ]?rate','만족도'])]:
   if any(re.search(p,low) for p in patterns): predictor_hints.append(name)
  x_hint=predictor_hints[0] if predictor_hints else ''
 else:
  for col,words in ALIASES.items():
   if any(w.lower() in low for w in words): metric=col; break
 return {'population':population,'metric_hint':metric,'x_hint':x_hint,'predictor_hints':predictor_hints,'timepoint':time,'statistic':statistic,'unit':unit,'direction':direction,'overclaim_signal':overclaim,'value':value,'claim_kind':claim_kind}

def profile_dataframe(df):
 rows=[]
 for c in df.columns:
  s=df[c]
  # case24 BUGFIX — WHY: categorical columns are expected, not exceptional. ``errors=coerce``
  # distinguishes them without noisy tracebacks while genuine unexpected errors still surface.
  numeric=pd.to_numeric(s.astype(str).str.replace(',','',regex=False),errors='coerce').notna().mean()>.7
  sample=', '.join(map(str,s.dropna().astype(str).unique()[:4]))
  rows.append({'column':c,'dtype':str(s.dtype),'numeric':numeric,'sample':sample})
 return rows

# [작성: 전문가5] 2026-09-25 case46
# 무엇을: 원문에 명시된 변수·전체 셀 수와 CSV 크기 비교 / 왜: 다른 데이터 객체의 동일 행 수를 재현 성공으로 오인 / 입력·출력: 원문 문장·자료표 -> 불일치 이유 또는 빈 문자열 / 검증: tests/test_case46.py의 17 대 8, 344×8=2752.
def dataset_scope_mismatch(source_quote,df):
 """Return explicit source/CSV shape conflicts for whole-dataset claims."""
 text=str(source_quote or '').lower()
 counts=[int(n.replace(',','')) for n in re.findall(r'\b(\d[\d,]*)\s+(?:variables?|columns?|features?)\b',text)]
 counts += [int(n.replace(',','')) for n in re.findall(r'\bdimensions?\s*(?:\([^)]*\)\s*)?(\d[\d,]*)\s*[×x]\s*\d[\d,]*',text)]
 if any(n!=df.shape[1] for n in counts):
  return f'원문 열 수 {counts}개와 CSV 열 수 {df.shape[1]}개가 다릅니다. 데이터셋 범위를 다시 확인해야 합니다.'
 totals=[int(n.replace(',','')) for n in re.findall(r'\b(?:out of\s+)?(\d[\d,]*)\s+total values?\b',text)]
 if any(n!=df.size for n in totals):
  return f'원문 전체 셀 수 {totals}개와 CSV 전체 셀 수 {df.size}개가 다릅니다. 데이터셋 범위를 다시 확인해야 합니다.'
 return ''

def candidate_columns(text,decomp,df,top_k=3):
 # [수정: 전문가7] 2026-09-25 case45
 # 종류: 오류수정 / 재현 방법: 논문 전체 행·결측 수에서 관련 없는 숫자열이 1순위 후보 / 변경 전: 숫자열만 제안 / 변경 후: 문장에 명시된 전체 데이터 지표는 범위 후보 제안 / 왜: 열-분모 혼동 차단 / 영향: 사람 확인 전 자동 실행 없음.
 if suggest_analysis_method(text,decomp) in {'row_count','missing_cells'}:
  return [{'column':'__dataset__','score':0.9,'reason':'원문이 전체 데이터 행/결측 셀 수를 지정함; 데이터셋 범위 사람 확인 필요'}]
 ct=tokens(text); prof=profile_dataframe(df); out=[]
 for p in prof:
  if not p['numeric']:continue
  col=p['column'];score=0.0;reasons=[]
  if decomp.get('metric_hint')==col:score+=0.65;reasons.append('주장 지표와 사전 매핑 일치')
  al=set(tokens(col.replace('_',' ')))
  for w in ALIASES.get(col,[]):al|=tokens(w)
  overlap=len(ct&al)
  if overlap:score+=min(.25,.1*overlap);reasons.append('주장-열 의미 토큰 일치')
  if any(x in col.lower() for x in ['pct','rate','percent']) and decomp.get('unit')=='%':score+=.10;reasons.append('% 단위와 열 이름 일치')
  if score==0:score=.02
  out.append({'column':col,'score':round(min(score,.99),3),'reason':' · '.join(reasons) or '수치형 열 후보'})
 return sorted(out,key=lambda x:(-x['score'],x['column']))[:top_k]

def suggest_filters(text,df):
 """Literal categorical/timepoint matcher with boundary checks.

 case20 BUGFIX: case19/case20 blind tests exposed false filters (Male inside Female, responder=1
 from a numeric claim). Numeric categories are therefore matched only when their column/time
 context is explicitly present; string categories use token boundaries.
 """
 suggestions=[];low=text.lower()
 for col in df.columns:
  vals=[x for x in df[col].dropna().unique()[:200]]
  if len(vals)>50:continue
  is_numeric=getattr(df[col].dtype,'kind','') in 'biufc'
  for raw in vals:
   v=str(raw);matched=False
   if is_numeric:
    if col.lower() in {'week','timepoint','visit'}:
     # case24 BUGFIX — WHY: CSV may parse 12 as 12.0 while the paper says week 12.
     try: vv=str(int(float(v))) if float(v).is_integer() else v
     except (TypeError,ValueError): vv=v
     matched=bool(re.search(rf'\bweek\s*{re.escape(vv)}\b|\b{re.escape(vv)}\s*주(?:차)?\b',low,re.I))
   else:
    matched=bool(re.search(rf'(?<![A-Za-z0-9가-힣]){re.escape(v.lower())}(?![A-Za-z0-9가-힣])',low))
   if matched:suggestions.append({'column':col,'value':v,'confidence':0.9,'reason':'주장 문장에 데이터 값/시점이 직접 등장'})
 seen=set();out=[]
 for x in suggestions:
  k=(x['column'],x['value'])
  if k not in seen:seen.add(k);out.append(x)
 return out

def suggest_analysis_method(text,decomp):
 low=text.lower()
 # [수정: 전문가7] 2026-09-25 case45
 # 종류: 오류수정 / 재현 방법: HTML 수식의 n missing = 19를 method 후보가 놓침 / 변경 전: 붙은 수식만 허용 / 변경 후: 공백·밑줄 수식 허용 / 왜: 추출·방법 제안 일치 / 영향: 근거·범위의 사람 확정은 유지.
 if ('missing values' in low or '결측값' in text or '결측 셀' in text) and re.search(r'\bn(?:[\s_]*\{?missing\}?)?\s*=\s*\d+|\d+\s+missing',low):
  return 'missing_cells'
 if re.search(r'\b\d[\d,]*\s+(?:individuals?|observations?|samples?|rows?)\b',low) or re.search(r'\b\d[\d,]*\s+individual\s+\w+',low) or ('행 수' in text):
  return 'row_count'
 if '가중평균' in text:return 'weighted_mean'
 if any(x in low for x in ['odds ratio','logistic regression','로지스틱']):return 'logistic_regression'
 # [수정: 전문가6] 2026-09-25 case58
 # 종류: 오류수정 / 재현 방법: "Spearman correlation"에 Pearson 추천 / 변경 전: 일반 correlation 조건 선평가 / 변경 후: 명시된 Spearman 우선 / 왜: 검정 종류 오제안 방지 / 영향: 일반 correlation의 Pearson 제안은 유지.
 if any(x in low for x in ['spearman']):return 'spearman_r'
 if any(x in low for x in ['pearson','correlation','correlated','상관']):return 'pearson_r'
 if any(x in low for x in ['regression coefficient','linear regression','회귀계수','선형회귀']):return 'linear_regression'
 if any(x in low for x in ['between groups','two groups','두 집단','집단 간 차이','significant difference','유의한 차이']):return 'welch_t'
 if '중앙값' in text or 'median' in low:return 'median'
 if '표준편차' in text or 'standard deviation' in low:return 'std'
 if '합계' in text or 'sum' in low:return 'sum'
 return decomp.get('statistic') or 'mean'

def build_plan(text,decomp,df):
 cands=candidate_columns(text,decomp,df);filters=suggest_filters(text,df);method=suggest_analysis_method(text,decomp)
 plan={'candidates':cands,'recommended_column':cands[0]['column'] if cands else '', 'aggregation':method,'filters':filters,'semantic_gate':'REVIEW_REQUIRED','note':'후보는 로컬 의미 매칭이 제안합니다. 사람 확인 후 규칙 엔진이 계산합니다.','x_column':decomp.get('x_hint',''),'group_column':'','group_a':'','group_b':''}
 # case20: a two-group comparison must not filter to A AND B simultaneously. Store groups as method parameters.
 if method in {'welch_t','independent_t','mannwhitney_u'}:
  groups=[f for f in filters if f['column'].lower() in {'group','arm','treatment_group'}]
  if len(groups)>=2 and groups[0]['column']==groups[1]['column']:
   plan['group_column']=groups[0]['column'];plan['group_a']=groups[0]['value'];plan['group_b']=groups[1]['value'];plan['filters']=[f for f in filters if f not in groups]
 return plan
