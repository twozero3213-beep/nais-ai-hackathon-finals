"""Audit coefficients in an author-supplied analysis dataset, never raw selection."""
from __future__ import annotations
import argparse
import csv
import io
import json
import math
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from core.statistics import multivariable_regression
from tools.case_registry import _verified_bytes
from tools.independent_replay import _load_json, _finite
from tools.registry_benchmark import benchmark_provenance

# [작성: 통계 계약 담당] 2026-09-29 case90
# 무엇: b/SE/t의 같은 근거·오차계약 / 왜: 일부수치만 일치해도전체일치하는오류방지 / 입력·출력: 수치쌍·등록참조→대조 / 검증: test_case90 손계산·불일치.
def _compare_statistic(left,right,reference,source):
    if not isinstance(reference,dict) or set(reference)!={'value','tolerance','source_quote'}:raise ValueError('보고값·허용오차·원문인용 필요')
    quote=reference['source_quote']
    if not isinstance(quote,str) or not quote or quote not in source:raise ValueError('계수 근거 인용이 원문에 없습니다.')
    expected=_finite(reference['value']);tolerance=_finite(reference['tolerance'])
    if tolerance<0:raise ValueError('음수 허용오차')
    left=_finite(left);right=_finite(right)
    agrees=math.isclose(left,right,rel_tol=1e-9,abs_tol=1e-12)
    return {'product':left,'independent':right,'reported':expected,'tolerance':tolerance,'engines_agree':agrees,'matches_reported':agrees and abs(left-expected)<=tolerance and abs(right-expected)<=tolerance}

# [작성: 전처리계보 담당] 2026-09-29 case90
# 무엇: 근거인용이있는 정수역코딩/완전문항평균 / 왜: 파생수치를매번재생성 / 입력·출력: frame·명세→파생frame / 검증: test_case90 손계산·결측·범위·덮어쓰기.
def _derive_columns(frame,rules,source):
    if not isinstance(rules,list) or len(rules)>10:raise ValueError('파생열 명세 한도')
    frame=frame.copy()
    for rule in rules:
        if not isinstance(rule,dict):raise ValueError('파생열 명세 형식')
        kind=rule.get('kind');target=rule.get('target');quote=rule.get('source_quote')
        if not isinstance(target,str) or not target or target in frame or not isinstance(quote,str) or not quote or quote not in source:raise ValueError('파생열 덮어쓰기 또는 근거 부재')
        if kind=='reverse_integer' and set(rule)=={'kind','target','source','min','max','source_quote'}:
            lo=_finite(rule['min']);hi=_finite(rule['max'])
            if lo>=hi or not lo.is_integer() or not hi.is_integer() or not isinstance(rule['source'],str) or rule['source'] not in frame:raise ValueError('역코딩 범위/열')
            values=pd.to_numeric(frame[rule['source']].replace('',np.nan),errors='raise')
            present=values.dropna()
            if not (np.isfinite(present).all() and present.between(lo,hi).all() and (present==np.floor(present)).all()):raise ValueError('역코딩은 명시된 정수 범위만 지원')
            frame[target]=lo+hi-values
        elif kind=='mean_complete' and set(rule)=={'kind','target','sources','source_quote'}:
            names=rule['sources']
            if not isinstance(names,list) or not 1<=len(names)<=100 or any(not isinstance(x,str) or x not in frame for x in names) or len(set(names))!=len(names):raise ValueError('평균 문항 열')
            values=frame[names].replace('',np.nan).apply(pd.to_numeric,errors='raise')
            if np.isinf(values.to_numpy()).any():raise ValueError('문항 비유한값')
            frame[target]=values.sum(axis=1,min_count=len(names))/len(names)
        else:raise ValueError('미지원 파생열 명세')
    return frame

# [작성: 통계·재현 담당] 2026-09-29 case89
# 무엇을: bounded 출처자료 읽기 / 왜: 경로탈출·변조·과대입력 차단 / 입력·출력: manifest→원본bytes / 검증: test_case89_author_models.
def _input_bytes(manifest,kind,root):
    relative=manifest[kind+'_file'];digest=manifest[kind+'_sha256']
    if not isinstance(relative,str) or not isinstance(digest,str) or len(digest)!=64:
        raise ValueError('출처·자료 경로와 SHA-256을 확인하세요.')
    path=(root/relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size>8*1024*1024:
        raise ValueError('출처·자료는 프로젝트 안의 8MiB 이하 파일이어야 합니다.')
    return _verified_bytes(relative,digest,root)

# [작성: 통계·재현 담당] 2026-09-29 case89
# 무엇을: 선언명세로 두계산기 계수대조 / 왜: 논문별 전용계산 방지 / 입력·출력: JSON·root→제한적산술보고 / 검증: b1.2손계산·근거/결측/공선성차단.
# [수정: 통계·재사용 담당] 2026-09-29 case90
# 종류: 검증방법추가 / 전후: b·결측거부만→명시 listwise/SE/t/df분리 / 왜: 저자4반복연구 같은계약사용 / 영향: case89명세 호환·가정/결론권한여전히없음; test_case90.
# [수정: 실행검증 담당] 2026-09-29 case91
# 종류: 실행증빙 결속 / 재현: 같은 입력의 검산보고에 코드·환경 식별 없음 / 변경전후: 수치보고만→안정 provenance·실행전후 재검사 / 왜: 변경 중 계산의 거짓 최신성 방지 / 입력·출력: 명세·root→지문 결속 보고 / 영향: 기존 산술·명세 호환 유지, 결속 변화시 수치 폐기·BLOCK / 검증: test_case91_execution.
def audit_models(manifest,root=None):
    root=Path(root or Path(__file__).resolve().parents[1]).resolve()
    provenance=benchmark_provenance()
    with Path(manifest).open('rb') as handle:raw=handle.read(65537)
    if len(raw)>65536:raise ValueError('모형 명세는 64KiB 이하입니다.')
    spec=_load_json(raw)
    required={'schema','scope','data_file','data_sha256','source_file','source_sha256','models'}
    # [수정: 계약검토 담당] 2026-09-29 case89 / 오류수정: JSON true==1 혼동 / 전후: bool 허용→정수만 / 검증: schema_boolean 반례.
    if not isinstance(spec,dict) or not required<=set(spec) or set(spec)-required-{'derivations'} or type(spec['schema']) is not int or spec['schema']!=1 or spec['scope']!='AUTHOR_ANALYSIS_DATASET_ONLY':
        raise ValueError('저자 분석자료 전용 명세가 필요합니다.')
    models=spec['models']
    if not isinstance(models,list) or not 1<=len(models)<=10:raise ValueError('모형은 1~10개입니다.')
    ids=[m.get('model_id') if isinstance(m,dict) else None for m in models]
    if any(not isinstance(x,str) or not x.strip() for x in ids) or len(set(ids))!=len(ids):raise ValueError('중복/빈 모형ID')
    try:
        source=_input_bytes(spec,'source',root).decode('utf-8-sig')
        data=_input_bytes(spec,'data',root)
        # [수정: 통계·입력검증 담당] 2026-09-29 case89
        # 종류: 오류수정 / 재현: header2열·body3열 / 변경 전: pandas가 첫열을 index로 묵시 전환 / 변경 후: 행폭 차단 / 왜: 열 이동으로 거짓일치 방지 / 영향: malformed CSV만 거부.
        reader=csv.reader(io.StringIO(data.decode('utf-8-sig')),strict=True)
        header=next(reader,[])
        if not header or any(not h for h in header) or len(set(header))!=len(header):raise ValueError('CSV 열 이름 오류')
        if any(len(row)!=len(header) for row in reader):raise ValueError('CSV 행별 열수 불일치')
        frame=pd.read_csv(io.BytesIO(data),dtype=str,keep_default_na=False)
        if not 1<=len(frame)<=100000:raise ValueError('분석자료 행수 한도')
        frame=_derive_columns(frame,spec.get('derivations',[]),source)
    except (ValueError,OSError,UnicodeError,csv.Error):
        return {'schema':1,'scope':spec['scope'],'provenance':provenance,'execution_identity_verified':False,'raw_selection_verified':False,'conclusion_allowed':False,'results':[{'model_id':m['model_id'],'action':'BLOCK','reason':'원문·자료 경로/크기/지문/CSV를 확인하세요.'} for m in models]}
    results=[]
    for model in models:
        result={'model_id':model['model_id'],'action':'BLOCK'}
        try:
            required_model={'model_id','method','outcome','predictors','missing_policy','reported_terms'}
            if not required_model<=set(model) or set(model)-required_model-{'reported_df'} or model['method']!='ols' or model['missing_policy'] not in {'error','listwise'}:raise ValueError('OLS·명시적 결측정책만 지원합니다.')
            predictors=model['predictors'];outcome=model['outcome'];reported=model['reported_terms']
            if not isinstance(predictors,list) or not 1<=len(predictors)<=20 or any(not isinstance(x,str) for x in predictors) or len(set(predictors))!=len(predictors) or 'const' in predictors or outcome in predictors:raise ValueError('독립적인 예측열 명세가 필요합니다.')
            if not isinstance(outcome,str) or any(x not in frame for x in [outcome,*predictors]):raise ValueError('원자료 열 이름을 확인하세요.')
            if not isinstance(reported,dict) or not reported or not set(reported)<=set(predictors):raise ValueError('보고 계수의 열 이름을 확인하세요.')
            for term,reference in reported.items():
                if not isinstance(reference,dict):raise ValueError('계수 참조 형식')
                base={k:v for k,v in reference.items() if k!='statistics'}
                _compare_statistic(0.,0.,base,source)
                stats=reference.get('statistics',{})
                if not isinstance(stats,dict) or not set(stats)<={'se','statistic'}:raise ValueError('지원 통계량: se,statistic')
                for ref in stats.values():_compare_statistic(0.,0.,ref,source)
            df_reference=model.get('reported_df')
            if df_reference is not None:
                if not isinstance(df_reference,dict) or set(df_reference)!={'value','source_quote'} or type(df_reference['value']) is not int or df_reference['value']<0:raise ValueError('보고 자유도 형식')
                _compare_statistic(0.,0.,{**df_reference,'tolerance':0},source)
            # 빈 셀만 결측. NaN/NA 문자열·숫자오염·무한값을 조용히 삭제하지 않는다.
            numeric=frame[[outcome,*predictors]].replace('',np.nan).apply(pd.to_numeric,errors='raise')
            if np.isinf(numeric.to_numpy()).any():raise ValueError('비유한 자료')
            if model['missing_policy']=='listwise':numeric=numeric.dropna()
            if not np.isfinite(numeric.to_numpy()).all():raise ValueError('비유한/결측 자료는 자동 삭제하지 않습니다.')
            X=np.column_stack([np.ones(len(numeric)),numeric[predictors].to_numpy(dtype=float)])
            if len(numeric)<=X.shape[1] or np.linalg.matrix_rank(X)!=X.shape[1]:raise ValueError('표본수 부족 또는 공선성')
            independent=np.linalg.lstsq(X,numeric[outcome].to_numpy(dtype=float),rcond=None)[0]
            df_resid=len(numeric)-X.shape[1]
            independent_se=None
            if any(ref.get('statistics') for ref in reported.values()):
                residual=numeric[outcome].to_numpy(dtype=float)-X@independent
                independent_se=np.sqrt((residual@residual/df_resid)*np.diag(np.linalg.inv(X.T@X)))
            product=multivariable_regression(numeric,outcome,predictors)
            if product['n']!=len(numeric):raise ValueError('계산기가 행을 누락했습니다.')
            terms={};matched=True
            for term,reference in reported.items():
                left=_finite(product['terms'][term]['estimate']);right=_finite(independent[predictors.index(term)+1].item())
                terms[term]=_compare_statistic(left,right,{k:v for k,v in reference.items() if k!='statistics'},source)
                matched=matched and terms[term]['matches_reported']
                if reference.get('statistics'):
                    j=predictors.index(term)+1;se=_finite(float(independent_se[j]));stats={}
                    for metric,ref in reference['statistics'].items():
                        if metric=='statistic' and se==0:raise ValueError('표준오차0 t값 정의불가')
                        independent_value=se if metric=='se' else right/se
                        stats[metric]=_compare_statistic(product['terms'][term][metric],independent_value,ref,source)
                        matched=matched and stats[metric]['matches_reported']
                    terms[term]['statistics']=stats
            result.update(action='COEFFICIENT_MATCH' if matched else 'COEFFICIENT_MISMATCH',n=len(numeric),n_input=len(frame),rows_dropped=len(frame)-len(numeric),missing_policy=model['missing_policy'],residual_df=df_resid,terms=terms)
            if df_reference is not None:result.update(reported_df=df_reference['value'],reported_df_matches=df_reference['value']==df_resid)
        except (ValueError,TypeError,KeyError,np.linalg.LinAlgError,OverflowError) as error:
            result['reason']=str(error)
        results.append(result)
    try:
        stable=(provenance==benchmark_provenance() and Path(manifest).read_bytes()==raw
                and _input_bytes(spec,'data',root)==data
                and _input_bytes(spec,'source',root).decode('utf-8-sig')==source)
    except (ValueError,OSError,UnicodeError):
        stable=False
    if not stable:
        results=[{'model_id':m['model_id'],'action':'BLOCK','reason':'EXECUTION_INPUT_OR_CODE_ENVIRONMENT_CHANGED'} for m in models]
    return {'schema':1,'scope':spec['scope'],'provenance':provenance,'execution_identity_verified':stable,'manifest_sha256':hashlib.sha256(raw).hexdigest(),'source_sha256':spec['source_sha256'],'data_sha256':spec['data_sha256'],'derivations':spec.get('derivations',[]),'raw_selection_verified':False,'conclusion_allowed':False,'semantic_verified':False,'assumptions_verified':False,'results':results,'limitation':'저자 분석자료의 계수·등록 통계량 산술대조만 수행. 원자료 제외절차·공변량 의미·통계가정·다중비교·논문 결론·AI우위는 검증하지 않음.'}

# [작성: 재현성 담당] 2026-09-29 case89 CLI / 무엇: UI없이 같은검산 / 왜: 제3자재실행 / 입력·출력: 명세→JSON / 검증: 실제공개사례·손계산시험.
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',required=True);parser.add_argument('--root',default='.');parser.add_argument('--output')
    args=parser.parse_args();text=json.dumps(audit_models(args.manifest,root=args.root),ensure_ascii=False,indent=2,allow_nan=False)
    if args.output:Path(args.output).write_text(text+'\n',encoding='utf-8')
    else:print(text)

if __name__=='__main__':main()
