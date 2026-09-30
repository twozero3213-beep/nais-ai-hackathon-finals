"""case18 deterministic verification engine.

Semantic mapping must be confirmed by a human before verification. AI/heuristics never
produce the final numeric verdict; pandas/scipy recompute it from the connected dataset.
"""
import math,pandas as pd
from hashlib import sha256
from dataclasses import replace
from .models import Status
from .provenance import dataframe_hash
from .statistics import descriptive, inferential, DESCRIPTIVE_METHODS, INFERENTIAL_METHODS
from .normalization import filter_mask
from .semantic import dataset_scope_mismatch
# [수정: 0 이영 · Codex] 2026-10-01T06:07:34+09:00 — 기술통계 수치 비교를 선언 오차·표현 정책을 보존하는 공통 함수로 결속한다.
from .numeric_comparison import compare_numeric, require_integer_mean_precision

# [수정: 전문가5] 2026-09-23 case36
# 종류: 오류수정
# 재현 방법: Claim filter week=12, CSV week='12.0'에서 기존 raw 문자열 비교는 0행을 선택했다.
# 변경 전: astype(str)==str(value)로 경로별 필터 의미가 달랐다.
# 변경 후: canonical normalization의 filter_mask를 공통 사용한다.
# 왜: 같은 Claim/데이터가 verifier와 typed executor에서 다른 행을 선택하면 재현성이 깨진다.
# 영향: 숫자 표기·공통 범주 alias의 동치 비교가 일관된다.
def _filtered(df,c):
 out=df
 for f in c.filters:
  col=f.get('column');val=f.get('value')
  out=out[filter_mask(out[col],val)]
 return out

# [수정: 전문가5/6] 2026-09-26 case64
# 원인: 비유한 기술통계의 직접 검증 경로 / 무엇·왜: 공통 descriptive 유한성 검증과 기존 예외 경계를 재사용.
# 입력·출력: overflow·표본 1개 std·무한대 -> REVIEW, 결과 없음 / 검증: case64 두 경로 회귀시험.
def verify(c,df):
 if c.decomposition.get('overclaim_signal'):return Status.OVERCLAIM,'범위가 넓은 일반화 표현은 단일 집계값만으로 입증할 수 없습니다.',None
 if not c.semantic_confirmed:return Status.REVIEW,'근거 연결 확인 전입니다. 후보 변수·필터·분석방법을 사람이 확인해야 합니다.',None
 # [수정: 전문가5] 2026-09-25 case58
 # 종류: 오류수정 / 재현 방법: 없는 집단 필터 열로 평균을 승인 / 변경 전: 필터를 조용히 무시 / 변경 후: MISSING 차단 / 왜: 전체 표를 대상 집단으로 오인한 승인을 방지 / 영향: 유효 필터의 계산은 유지.
 missing_filters=[f.get('column') for f in c.filters if f.get('column') not in df.columns]
 if missing_filters:return Status.MISSING,f"CSV에 필터 열이 없습니다: {', '.join(map(str,missing_filters))}",None
 fdf=_filtered(df,c)
 method=c.analysis_method or c.aggregation
 # [수정: Fail-closed/재현성] 2026-09-28 case72
 # NaN/Inf/음수 tolerance와 범위 밖 alpha는 계산 결과가 아니라 잘못된 분석 명세다.
 try:
  tol=float(c.tolerance); alpha=float(c.alpha)
 except (TypeError,ValueError,OverflowError):
  return Status.REVIEW,'허용오차 또는 유의수준이 유효한 실수가 아닙니다.',None
 if not math.isfinite(tol) or tol < 0:return Status.REVIEW,'허용오차는 0 이상의 유한한 값이어야 합니다.',None
 if method in INFERENTIAL_METHODS and (not math.isfinite(alpha) or not 0 < alpha < 1):return Status.REVIEW,'유의수준 α는 0과 1 사이의 유한한 값이어야 합니다.',None
 # [수정: 전문가5] 2026-09-25 case45
 # 종류: 오류수정 / 재현 방법: 행 수·결측 셀 수는 특정 열이 없어도 계산해야 함 / 변경 전: 열 선검사로 MISSING / 변경 후: __dataset__만 전체 데이터 방법에 허용 / 왜: 분모 정확성 / 영향: 나머지 방법의 열 검사 유지.
 if method in {"row_count","missing_cells"}:
  if c.column!="__dataset__":return Status.MISSING,"전체 데이터 범위 확인이 필요합니다.",None
  # [수정: 전문가5] 2026-09-25 case46
  # 종류: 오류수정 / 재현 방법: 직접 검증 경로가 17변수 원문·8열 CSV의 동일 행 수를 성공으로 판정 / 변경 전: 값만 비교 / 변경 후: 원문 명시 차원과 자료 불일치 시 REVIEW / 왜: 계약 밖 호출도 안전하게 유지 / 영향: 범위 재확인 필요.
  mismatch=dataset_scope_mismatch(c.source_quote or c.text,fdf)
  if mismatch:return Status.REVIEW,mismatch,None
 elif not c.column or c.column not in fdf.columns:return Status.MISSING,f"CSV 열 '{c.column}'에서 근거를 찾지 못했습니다.",None
 try:
  if method in DESCRIPTIVE_METHODS:
   calc,meta=descriptive(fdf,c.column,method,c.weight_column,c.success_value)
   # [수정: 0 이영 · Codex] 2026-10-01T06:07:34+09:00 — 큰 정수 mean의 반올림값을 보고값과 우연히 일치시키기 전에 정밀도 미지원으로 보류한다.
   if method=="mean":
    require_integer_mean_precision(pd.to_numeric(fdf[c.column],errors="coerce").dropna(),calc,c.tolerance)
   if c.current_value is None:return Status.REVIEW,f"{meta['expression']}={calc:.6g}; 보고 수치가 없어 비교 대신 검토가 필요합니다.",calc
   comparison=compare_numeric(calc,c.current_value,c.tolerance)
   delta=comparison.delta;ftxt=', '.join(f"{x['column']}={x['value']}" for x in c.filters) or '없음';base=f"필터[{ftxt}] · {meta['expression']} · n={meta['n']} · 보고 {c.current_value:g} ↔ 재계산 {calc:.6g}; 차이 {delta:.6g}"
   # [수정: 전문가5] 2026-09-23 case36
   # 종류: 오류수정
   # 재현 방법: 보고 0.7, 재계산 0.8, tolerance 0.1은 이진 부동소수점에서 delta가 0.100000...이 되어 충돌했다.
   # 변경 전: delta <= tolerance의 엄격한 이진 비교.
   # 변경 후: 경계값에서만 매우 작은 절대오차를 허용하는 isclose를 병행한다.
   # 왜: 표시 정밀도 차이가 아닌 부동소수점 표현 잔차로 수치충돌을 만들지 않기 위해.
   # 영향: tolerance보다 실질적으로 큰 차이는 기존처럼 CONFLICT다.
   # [수정: 0 이영 · Codex] 2026-10-01T06:07:34+09:00 — 위 과거 이진 경계 보완을 decimal 표시 정책으로 대체한다. 0.8/0.7 오차0.1을 유지하며 오차0/1e-13을 1e-12로 넓히지 않는다.
   within=comparison.within_tolerance
   return (Status.SUPPORTED,base+f' ≤ 허용오차 {c.tolerance:g}',calc) if within else (Status.CONFLICT,base+f' > 허용오차 {c.tolerance:g}',calc)
  if method in INFERENTIAL_METHODS:
   res=inferential(fdf,method,c.column,c.group_column,c.group_a,c.group_b,c.x_column,getattr(c,"mu0",0.0))
   p=res.get('p_value');alpha=c.alpha
   if p is None or not math.isfinite(float(p)): return Status.REVIEW,'추론 통계량을 유한하게 계산할 수 없습니다.',None
   sig=(p<alpha)
   # Inferential claims are not auto-approved from significance alone; the engine exposes the result and assumptions.
   return Status.REVIEW,f"{method}: estimate={res.get('estimate')} · p={p:.6g} · α={alpha:g} · {'통계적 유의' if sig else '유의하지 않음'}; 가정/해석을 사람이 확인해야 합니다.",res
  return Status.REVIEW,f'지원하지 않는 분석방법: {method}',None
 except Exception as exc:return Status.REVIEW,f'통계 재계산 실패: {exc}',None

# [작성: 전문가5] 2026-09-25 case40
# 무엇을: 논문 원문 보고값을 사람의 사후 수정값과 독립적으로 재검증한다.
# 왜: 수정값 14.8이 통과해도 원문 18.4의 충돌을 성공으로 표시해서는 안 된다.
# 입력·출력: Claim, DataFrame -> (Status, 사유, 계산값); 원본 Claim은 변경하지 않는다.
# 검증: tests/test_case40.py::test_reported_paper_verdict_remains_conflict_after_human_amendment.
def verify_reported_claim(claim, df):
 if claim.original_value is None:
  return Status.REVIEW,'논문에 비교할 원래 보고 수치가 없습니다.',None
 return verify(replace(claim,current_value=claim.original_value),df)

# [작성: 전문가4] 2026-09-25 case43
# 무엇을: refresh_reported_status / 왜: 원문 판정을 정정 판정과 별도 보존 / 입력·출력: Claim, DataFrame -> 원문 검증 결과 / 검증: tests/test_case43.py.
def refresh_reported_status(claim,df):
 status,reason,calc=verify_reported_claim(claim,df)
 claim.reported_status,claim.reported_reason=status,reason
 return status,reason,calc

def tool_reason(c):
 f=', '.join(f"{x['column']}={x['value']}" for x in c.filters) or '없음';m=c.analysis_method or c.aggregation
 return f"근거 연결 확인 후 필터[{f}]를 적용하고 {m} 방법으로 재계산합니다. 의미 연결은 후보 제안일 뿐이며 최종 수치/통계 계산에는 생성형 AI를 사용하지 않습니다."

def auto_verify(c,df,*,csv_bytes:bytes|None=None):
 refresh_reported_status(c,df)
 sig=c.verification_signature()
 # [수정: 전문가7] 2026-09-25 case58
 # 무엇을: 승인 당시 데이터 지문을 현재 표와 대조 / 왜: 행 수가 같은 CSV 교체에서 승인 재사용 방지 / 검증: tests/test_case58_approval.py.
 current_data_hash=sha256(csv_bytes).hexdigest() if csv_bytes is not None else dataframe_hash(df)
 data_changed=c.validated_data_hash!=current_data_hash
 if c.status==Status.VALIDATED and c.validated_signature==sig and not data_changed:return Status.VALIDATED,c.reason or '사람 승인 완료',None,False
 status,reason,calc=verify(c,df);changed=(c.status!=status or c.reason!=reason) and c.last_auto_signature!=sig
 if c.status==Status.VALIDATED and (c.validated_signature!=sig or data_changed):reason='승인 후 검증 입력이 변경되어 승인이 해제되었습니다. '+reason
 c.status,c.reason,c.last_auto_signature=status,reason,sig
 if c.revision_count:c.amendment_status,c.amendment_reason=status,reason
 return status,reason,calc,changed
