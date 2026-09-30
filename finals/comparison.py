"""[0 이영] 등록된 C01~C08 입력과 정답을 봉인한 뒤 로컬 경로를 실행한다."""
# 수정 이유: 성능을 보기 전에 입력·정답을 고정하고, 모델 미실행을 로컬 검산 성공과 구분한다.
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
import uuid

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.case_registry import audit_registry

EVIDENCE=ROOT/'finals/evidence'
KST=timezone(timedelta(hours=9))

def now():return datetime.now(KST).isoformat(timespec='seconds')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical(value))


def seal():
    seal_path=EVIDENCE/'seal.json'
    if seal_path.exists():
        verify_seal()
        return json.loads(seal_path.read_text(encoding='utf-8'))
    plan=json.loads((ROOT/'docs/finals-strategy/comparison-protocol.json').read_text(encoding='utf-8-sig'))
    registry=json.loads((ROOT/'data/evaluation/public_reproduction_cases.json').read_text(encoding='utf-8-sig'))
    registered={c['claim_id']:c for c in registry['cases']}
    fixture=json.loads((ROOT/'data/evaluation/fixed_demo_expectations.json').read_text(encoding='utf-8-sig'))
    synthetic={c['id']:c for c in fixture['cases']}
    expected={c['id']:{'action':c['expected_kind'],'value':c['expected_value']} for c in plan['cases']}
    if list(expected)!=[f'C{n:02}' for n in range(1,9)]:raise ValueError('REGISTERED_CASE_ORDER_CHANGED')
    inputs=[]
    for cid in expected:
        if cid in {'C01','C02','C05','C07','C08'}:
            item=deepcopy(registered['BAT-POSITIVE-N' if cid=='C02' else 'PENG-RAW-ROWS'])
            source=(ROOT/item['source_file']).read_bytes()
            data=(ROOT/item['data_file']).read_bytes()
            if sha(source)!=item['source_sha256'] or sha(data)!=item['data_sha256']:raise ValueError('REGISTERED_SOURCE_CHANGED')
        else:
            gid={'C03':'G03','C04':'G08','C06':'G07'}[cid]
            item={**fixture['baseline_registration'],**synthetic[gid]['overrides']}
            source=fixture['inputs']['source_text'].encode('utf-8')
            data=fixture['inputs']['csv_text'].encode('utf-8')
            item.update(source_sha256=sha(source),data_sha256=sha(data),synthetic=True)
        item['claim_id']=cid
        prior_hash=item['data_sha256']
        if cid=='C05':item['source_location']=''
        if cid=='C07':
            rows=data.splitlines(keepends=True)
            data=b''.join(rows[:1]+rows[2:])
        if cid=='C08':
            data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n') if b'\r\n' not in data else data.replace(b'\r\n',b'\n')
        item['source_file']=f'inputs/{cid}-source.txt'
        item['data_file']=f'inputs/{cid}-data.csv'
        for key,raw in [('source_file',source),('data_file',data)]:
            p=EVIDENCE/item[key];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        packet={
            'case_id':cid,'question':plan['shared_prompt'],'source_text':source.decode('utf-8-sig'),
            'current_csv':data.decode('utf-8-sig'),'registration':item,
            'registered_data_sha256':prior_hash,'current_data_sha256':sha(data),
            'prior_result_reuse_requested':cid in {'C07','C08'},
            'prior_human_approval':False,
        }
        write(EVIDENCE/f'packets/{cid}.json',packet)
        inputs.append(item)
    write(EVIDENCE/'registry.json',{'schema':1,'cases':inputs})
    write(EVIDENCE/'expected.json',expected)
    shared=deepcopy(plan['shared_conditions'])
    shared.update(actual_model_id='gpt-4.1-mini',provider='openai',currency_budget_cap=0,
                  model_execution_status='NOT_RUN_CREDIT_BALANCE_EXHAUSTED',external_transfer_permission_status='USER_AUTHORIZED',
                  same_readonly_tools=False,allowed_tools=[],tool_rule='로컬 경로는 결정적 엔진, 두 모델 조건에는 같은 전체 입력·질문·최대 호출/시간/출력 예산 제공. 도구 사용 비교는 별도 과제.')
    protocol={'contributor_version':0,'contributor_name':'이영','created_at_kst':now(),
              'source_plan_sha256':sha((ROOT/'docs/finals-strategy/comparison-protocol.json').read_bytes()),
              'cases':deepcopy(plan['cases']),'conditions':['general_ai','without_llm','with_llm'],
              'shared_conditions':shared,'mapping_effort_status':'NOT_MEASURED_REGISTERED_MAPPINGS_REUSED',
              'limits':'8개 등록 사례의 범위이며 일반적 우위·사람 정답률·모델 기여도는 입증하지 않는다.',
              'expected_values_are_not_in_model_packets':True}
    write(EVIDENCE/'protocol.json',protocol)
    files={p.relative_to(EVIDENCE).as_posix():sha(p.read_bytes()) for p in EVIDENCE.rglob('*') if p.is_file() and p.name!='seal.json'}
    result={'sealed_at_kst':now(),'contributor_version':0,'files':files,'status':'SEALED_BEFORE_COMPARISON_RUN'}
    write(seal_path,result)
    return result


def verify_seal(evidence=None):
    # [수정: 0 이영 · Claude] 2026-10-01 03:00 KST — 비공개 입력을 복원한 임시 사본(evidence 인자)도 같은 규칙으로 검증한다. 인자가 없으면 기존 동작과 같다.
    # 공개 저장소에는 연락처가 든 입력 10개가 없어 읽기에 실패하므로 원인을 알리는 오류로 바꾼다.
    evidence=Path(evidence) if evidence else EVIDENCE
    data=json.loads((evidence/'seal.json').read_text(encoding='utf-8'))
    for rel,digest in data['files'].items():
        path=(evidence/rel).resolve()
        if not path.is_relative_to(evidence.resolve()):raise ValueError('SEALED_INPUT_CHANGED')
        try:raw=path.read_bytes()
        except OSError:raise ValueError('SEALED_INPUT_MISSING_RESTORE_PRIVATE_BUNDLE') from None
        if sha(raw)!=digest:raise ValueError('SEALED_INPUT_CHANGED')
    return data


def run_local():
    frozen=verify_seal()
    registry=json.loads((EVIDENCE/'registry.json').read_text(encoding='utf-8'))
    expected=json.loads((EVIDENCE/'expected.json').read_text(encoding='utf-8'))
    run_id=uuid.uuid4().hex
    results=[]
    run_root=ROOT/'finals/results'/run_id
    run_root.mkdir(parents=True,exist_ok=False)
    started_at=now()
    for item in registry['cases']:
        one=run_root/(item['claim_id']+'-registry.json')
        write(one,{'schema':1,'cases':[item]})
        started=perf_counter()
        actual=audit_registry(one,root=EVIDENCE)['results'][0]
        elapsed=(perf_counter()-started)*1000
        current=(EVIDENCE/item['data_file']).read_bytes()
        stale=sha(current)!=item['data_sha256']
        action='STALE_BLOCK' if stale and actual['action']=='BLOCK' else actual['action']
        gold=expected[item['claim_id']]
        passed=action==gold['action'] and (gold['value'] is None or actual.get('value')==gold['value'])
        results.append({'case_id':item['claim_id'],'condition':'without_llm','execution_status':'EXECUTED','decision':action,
                        'evidence_present':bool(item.get('source_location') and item.get('source_quote')),
                        'stopped':actual['action']=='BLOCK','incorrect_numeric_output':gold['value'] is not None and actual.get('value')!=gold['value'],
                        'elapsed_ms':round(elapsed,3),'provider_cost_usd':0,'local_compute_cost':'NOT_MEASURED','new_model_calls':0,
                        'human_approval':False,'passed_registered_expectation':passed,'actual':actual})
    for condition in ('general_ai','with_llm'):
        for item in registry['cases']:
            results.append({'case_id':item['claim_id'],'condition':condition,'execution_status':'NOT_RUN',
                            'blocker':'MODEL_CREDIT_BALANCE_EXHAUSTED','decision':None,'evidence_present':None,'stopped':None,
                            'incorrect_numeric_output':None,'elapsed_ms':None,'provider_cost_usd':None,'new_model_calls':0})
    report={'run_id':run_id,'started_at_kst':started_at,'finished_at_kst':now(),'contributor_version':0,
            'seal_sha256':sha((EVIDENCE/'seal.json').read_bytes()),'runner_sha256':sha(Path(__file__).read_bytes()),
            'scope':'등록 C01~C08의 결정적 검산·차단 실행. 새로운 사람 매핑 시간·AI 기여도·일반 AI 우위는 미측정.',
            'results':results,'local_passed':sum(x.get('passed_registered_expectation',False) for x in results),
            'local_executed':8,'model_conditions_executed':0,'model_conditions_not_run':16}
    write(run_root/'results.json',report)
    # 비교표의 미실행 칸을 빈 성공으로 바꾸지 않는다.
    lines=['| 사례 | LLM 없는 경로 | 일반 AI | LLM 있는 경로 |','|---|---|---|---|']
    for row in results[:8]:lines.append(f"| {row['case_id']} | {row['decision']} · {row['elapsed_ms']} ms | 미실행: 생성 크레딧 차단 | 미실행: 생성 크레딧 차단 |")
    (run_root/'presentation-table.md').write_text('\n'.join(lines)+'\n\n등록된 8개 사례의 로컬 검산 결과이며, 일반 AI 대비 우위와 모델 기여도는 아직 측정하지 않았습니다.\n',encoding='utf-8')
    return {'path':str(run_root/'results.json'),'local_executed':8,'local_passed':report['local_passed'],'model_not_run':16}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['seal','verify','run-local']);args=parser.parse_args()
    result=seal() if args.action=='seal' else verify_seal() if args.action=='verify' else run_local()
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
