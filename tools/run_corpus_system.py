"""Run the current Evidence Gate numeric path on pre-confirmed public mappings."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import pandas as pd
from core.models import Claim
from core.verifier import verify_reported_claim
from core.typed_contracts import build_typed_contract
from core.executor import execute_contract

ROOT=Path(__file__).resolve().parents[1]


# [작성: 전문가7] 2026-09-25 case43
# 무엇을: run_system / 왜: 공개 사례에서 지원 분석만 실제 엔진으로 실행하고 미지원 방법은 차단 / 입력·출력: 사례 manifest -> 결정·값·해시 / 검증: tests/test_case43.py.
def run_system(manifest=ROOT/'data/evaluation/cases.json', root=None):
    # [수정: 전문가4·7] 2026-09-26 case63: 전역 변경 없는 복사 프로젝트 실행.
    root=Path(ROOT if root is None else root).resolve()
    if not root.is_dir():raise ValueError('root 디렉터리가 없습니다.')
    cases=json.loads(Path(manifest).read_text(encoding='utf-8'))['cases']
    output=[]
    for case in cases:
        path=(root/case['data_file']).resolve()
        if not path.is_relative_to(root):raise ValueError('프로젝트 밖의 원자료 경로입니다.')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=case['data_sha256']:raise ValueError('원자료 해시 불일치: '+case['claim_id'])
        # [수정: 전문가7] 2026-09-25 case45
        # 종류: 오류수정 / 재현 방법: WINE-RED 등 세 ID만 실행, 같은 사례의 ID를 바꾸면 차단 / 변경 전: ID별 사전 매핑 코드 / 변경 후: manifest의 지원 방법·평가용 사전 매핑 공급 여부로 처리 / 왜: 사례 이름 과적합 제거 / 영향: 이 평가는 여전히 사람 정답·자율 추출 점수가 아님.
        method=case['method']
        if not case.get('oracle_mapping_supplied',False) or method not in {'count_rows','missing_cells','mean'}:
            output.append({'claim_id':case['claim_id'],'action':'BLOCK','reason':'평가용 사전 매핑 없음 또는 현재 엔진 미지원 분석방법','source_hash':digest})
            continue
        # [수정: 전문가4·7] 2026-09-26 case63: 명시 결측 정책은 제품 경로에도 적용.
        missing_policy=case.get('missing_policy','drop')
        if missing_policy not in ('drop','error'):
            output.append({'claim_id':case['claim_id'],'action':'BLOCK','reason':'미지원 결측 정책','source_hash':digest})
            continue
        aggregation={'count_rows':'row_count','missing_cells':'missing_cells','mean':'mean'}[method]
        column='__dataset__' if aggregation in {'row_count','missing_cells'} else case['column']
        filters=[{'column':k,'value':v} for k,v in case['filters'].items()]
        data=pd.read_csv(path,sep=case.get('delimiter',','))
        claim=Claim(case['claim_id'],case['claim_text'],case['reported_value'],column=column,aggregation=aggregation,tolerance=case['tolerance'],filters=filters,semantic_confirmed=True,missing_policy=missing_policy,missing_policy_confirmed=True)
        contract=build_typed_contract(claim,path.name,digest)
        run=execute_contract(contract,data)
        if run['state']!='EXECUTED':
            output.append({'claim_id':case['claim_id'],'action':'BLOCK','reason':run['reason'],'source_hash':digest})
            continue
        if method=='mean' and missing_policy=='error' and run['result']['n'] != run['rows_used']:
            output.append({'claim_id':case['claim_id'],'action':'BLOCK','reason':'평균 대상에 결측 또는 비수치 관측값이 있습니다.','source_hash':digest})
            continue
        status,reason,value=verify_reported_claim(claim,data)
        # [수정: 전문가4·7] 2026-09-26 case63: typed 실행과 verifier 값 일치, 선택행·수치분모 노출.
        if not math.isclose(float(run['result']['value']),float(value),rel_tol=1e-12,abs_tol=1e-12):
            output.append({'claim_id':case['claim_id'],'action':'BLOCK','reason':'typed·verifier 값 불일치','source_hash':digest})
            continue
        output.append({'rows_used':run['rows_used'],'observations_used':run['result']['n'],'claim_id':case['claim_id'],'action':'EXECUTE','value':value,'verdict':status.value,'reason':reason,'source_hash':digest,'contract':contract.to_dict(),'confirmation_source':'evaluation_oracle_fixture_not_human'})
    return {'schema':1,'mapping_scope':'evaluation oracle: supplied mappings enter typed contract; not autonomous extraction or human-approved gold','results':output}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    text=json.dumps(run_system(),ensure_ascii=False,indent=2)+'\n'
    if args.output:Path(args.output).write_text(text,encoding='utf-8')
    else:print(text)
