"""[03 조지현] 수정 이유: 최신 비교 실행기의 미확정·채점·입력 고정 경계를 독립 재현한다.
원래 입력/정답을 수정하지 않으며, 모든 모델 응답은 모의이고 실제 AI 성능 증거가 아니다.
"""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
ROOT=args.repo.resolve()
sys.path[:0]=[str(ROOT/'finals'),str(ROOT)]
import sealed_runner as runner
expected=json.loads((runner.EVIDENCE/'expected.json').read_text())
packets=runner.load_packets(runner.EVIDENCE, ('C03','C04','C06'))
def digests():
    return {p.relative_to(runner.EVIDENCE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in runner.EVIDENCE.rglob('*') if p.is_file()}
before=digests()
class Mock:
    def __init__(self, changes=None, general=None, error=False):
        self.changes=changes or {};self.general=general or {};self.error=error
    def __call__(self, system, body, **kw):
        if self.error:raise ValueError('MOCK_UPSTREAM_FAILURE')
        reg=body['registration'];cid=reg['claim_id']
        if system==runner.GENERAL_SYSTEM:
            out={'decision':expected[cid]['action'],'calculated_value':expected[cid]['value'],
                 'evidence_location':None,'reason':'모의 응답: 실제 모델 결과 아님'}
            out.update(self.general)
        else:
            out={'method':reg['method'],'column':reg['column'],
                 'filters':[{'column':k,'value':str(v)} for k,v in reg['filters'].items()],
                 'missing_policy':reg['missing_policy'],'denominator':None,'unit':None,'unresolved':[],
                 'field_evidence':{name:None for name in runner.SIX_CONDITIONS}}
            out.update(self.changes)
        return {'output':out,'provider':'mock','model':'MOCK_TEST_ONLY','mock':True,
                'request_id':'mock-audit','usage':{'input_tokens':1,'output_tokens':1},'raw_sha256':'0'*64}
def one(cid, provider, condition):
    rep=runner.run_sealed({cid:deepcopy(packets[cid])},expected,provider)
    return next(row for row in rep['results'] if row['condition']==condition)
probes=[]
row=one('C03',Mock(changes={'unresolved':['분모를 확인하지 못함']}),'with_llm')
probes.append({'id':'UNRESOLVED_NOT_BLOCKED','expected':'BLOCK; value null','actual':row,
               'issue_reproduced':row['decision']!='BLOCK' and row['value']==15})
row=one('C06',Mock(general={'calculated_value':7}),'general_ai')
probes.append({'id':'NUMBER_ON_BLOCKED_CASE_PASSES','expected':'passed false when blocked gold has value null but model claims a number','actual':row,
               'issue_reproduced':row['passed'] and row['claimed_number_on_blocked_case']})
row=one('C03',Mock(changes={'filters':[{'column':'group','value':'A'},{'column':'group','value':'B'}]}),'with_llm')
probes.append({'id':'DUPLICATE_FILTER_OVERWRITE','expected':'reject duplicate filter columns; do not silently select last value','actual':row,
               'issue_reproduced':(row.get('proposed_conditions') or {}).get('filters')=={'group':'B'} and row['value']==35})
row=one('C03',Mock(changes={'denominator':'unknown population','unit':'unverified unit'}),'with_llm')
probes.append({'id':'DENOMINATOR_UNIT_IGNORED','expected':'record and validate proposed denominator and unit; do not claim semantic extraction verified','actual':row,
               'issue_reproduced':not (row['semantic_validation']['fields']['denominator']['status']=='NOT_VERIFIED' and row['semantic_validation']['fields']['unit']['status']=='NOT_VERIFIED' and row['semantic_validation']['fields']['unit']['proposed']=='unverified unit')})
# 수정 이유: 실행 중 자료 변경은 임시 사본에서만 재현하고 원래 봉인 입력과 정답을 보존한다.
with TemporaryDirectory() as temp:
    evidence=Path(temp)/'evidence';(evidence/'inputs').mkdir(parents=True)
    for name in ('C03-data.csv','C03-source.txt'):
        shutil.copyfile(runner.EVIDENCE/'inputs'/name,evidence/'inputs'/name)
    class ChangingMock(Mock):
        def __call__(self, system, body, **kw):
            if system==runner.GENERAL_SYSTEM:
                (evidence/'inputs/C03-data.csv').write_text('group,score\nA,10\nA,20\nB,30\n')
            return super().__call__(system,body,**kw)
    report=runner.run_sealed({'C03':deepcopy(packets['C03'])},expected,ChangingMock(),evidence_dir=evidence)
    rows={r['condition']:r for r in report['results']}
    probes.append({'id':'INPUT_CHANGED_DURING_RUN','expected':'abort comparison on any mid-run sealed data change; keep initial immutable input for all paths',
                   'actual':report,'issue_reproduced':not (report['aborted']=='SEALED_INPUT_CHANGED_DURING_RUN' and not report['comparison_valid'] and rows['with_llm']['execution_status']=='NOT_RUN' and all(c['passed']==0 for c in report['summary'].values()))})
try:
    runner.verify_seal()
    seal={'status':'PASS'}
except Exception as exc:
    seal={'status':'BLOCKED','code':runner.error_code(exc)}
result={'reviewer':'03 조지현','checked_at_kst':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds'),
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'scope':'공개 합성 C03·C04·C06 및 일시 사본; 모든 공급자 모의',
        'actual_paid_model_calls':0,'source_files_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('finals/sealed_runner.py','finals/sealed_evaluation_rules.json')},'original_evidence_hashes_unchanged':before==digests(),
        'original_evidence_sha256':before,'full_default_seal_check':seal,'probes':probes,
        'original_input_and_gold_modified':False,'general_ai_advantage_measured':False}
assert all(not p['issue_reproduced'] for p in probes), '교차 재현 검사가 실패함'
assert result['original_evidence_hashes_unchanged'], '원래 입력 지문 변화'
result['all_five_fixes_verified']=True
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'issues_reproduced':[p['id'] for p in probes if p['issue_reproduced']],
                  'original_evidence_hashes_unchanged':result['original_evidence_hashes_unchanged'],'seal':seal},ensure_ascii=False,indent=2))
