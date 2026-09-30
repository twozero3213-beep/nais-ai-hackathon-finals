# [작성: 0 이영 · Codex · 버전 0] 실제 봉인/실행 KST는 전용 protocol/results JSON에 기록한다.
# 이유: 큰 정수의 거짓 차이0와 선언오차 초과를 실제 양 계산경로에서 재현하고 정상 회귀를 인계한다.
# 이 파일은 제품 수정/monkeypatch 없이 현재 코드에서 실패해야 하는 교정 기대를 테스트한다.
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

OUT=Path(__file__).resolve().parent
PROTO=OUT/'0_이영_수치회귀_protocol.json'
RESULT=OUT/'0_이영_수치회귀_results.json'
COMMIT='a6729178963392249b14c9dfbd93bf28704262a4'

def now():return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

class NumericRegression(unittest.TestCase):
    def fixture(self,values,reported,tolerance):
        frame=pd.DataFrame({'group':['A']*len(values),'age':values})
        proposal={'claim_text':'Synthetic numeric boundary','reported_value':reported,
                  'source_quote':'Synthetic descriptive claim with explicit numeric contract.',
                  'source_location':'synthetic:table1','method':'mean','column':'age',
                  'filters':[{'column':'group','value':'A'}],
                  'denominator':{'rule':'filtered_rows','expected_n':len(values)},
                  'missing_policy':'error','unit':'years','tolerance':tolerance}
        case={'id':'numeric-regression','dataframe':frame,'source_gate':True,
              'source':{'data_file':'synthetic.csv'},'input_sha256':'synthetic',
              'expected_proposal':deepcopy(proposal)}
        return frame,case,proposal

    def assert_core_not_supported(self,values,reported,tolerance):
        frame,case,proposal=self.fixture(values,reported,tolerance)
        status,reason,value=verify(_claim(case,proposal,confirmed=True),frame)
        self.assertNotEqual(status.value,'SUPPORTED',f'actual status={status.value}, value={value}; {reason}')

    def assert_finals_not_within(self,values,reported,tolerance):
        _,case,proposal=self.fixture(values,reported,tolerance)
        try:result=_calculate(case,proposal)
        except ValueError:return  # 명시 정밀도 미지원 차단도 안전한 교정 기대다.
        self.assertFalse(result['within_tolerance'],f'actual calculation={result}')

    def test_large_odd_reported_int_core(self):
        self.assert_core_not_supported([9007199254740992,9007199254740994],9007199254740993,0)
    def test_large_odd_reported_int_finals(self):
        self.assert_finals_not_within([9007199254740992,9007199254740994],9007199254740993,0)
    def test_zero_tolerance_core(self):self.assert_core_not_supported([5e-13],0,0)
    def test_zero_tolerance_finals(self):self.assert_finals_not_within([5e-13],0,0)
    def test_sub_floor_tolerance_core(self):self.assert_core_not_supported([5e-13],0,1e-13)
    def test_sub_floor_tolerance_finals(self):self.assert_finals_not_within([5e-13],0,1e-13)
    def test_normal_exact_mean_core(self):
        frame,case,proposal=self.fixture([10,20],15,0)
        self.assertEqual(verify(_claim(case,proposal,confirmed=True),frame)[0].value,'SUPPORTED')
    def test_normal_exact_mean_finals(self):
        _,case,proposal=self.fixture([10,20],15,0)
        self.assertTrue(_calculate(case,proposal)['within_tolerance'])
    def test_normal_decimal_boundary_core(self):
        frame,case,proposal=self.fixture([0.8],0.7,0.1)
        self.assertEqual(verify(_claim(case,proposal,confirmed=True),frame)[0].value,'SUPPORTED')
    def test_normal_decimal_boundary_finals(self):
        _,case,proposal=self.fixture([0.8],0.7,0.1)
        self.assertTrue(_calculate(case,proposal)['within_tolerance'])
    def test_large_integer_numeric_filter_is_distinct(self):
        # 두 수의 차이는1이며 atol1e-12보다 크다. 문자열 코드 해석을 추가로 가정하지 않아도 다르다.
        actual=filter_mask(pd.Series(['9007199254740992','9007199254740993'],dtype=object),'9007199254740992').tolist()
        self.assertEqual(actual,[True,False])
    def test_normal_numeric_representation_filter(self):
        self.assertEqual(filter_mask(pd.Series(['12.0',12],dtype=object),12).tolist(),[True,True])

def main():
    parser=argparse.ArgumentParser(description='Expected-failing real-function regression tests; seal before run.')
    parser.add_argument('phase',choices=['seal','run'])
    parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args()
    repo=args.repo.resolve()
    sources=['core/normalization.py','core/verifier.py','core/statistics.py','core/typed_contracts.py','finals/finals_pipeline.py']
    hashes={name:sha(repo/name) for name in sources}
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    if args.phase=='seal':
        if PROTO.exists():raise SystemExit('refusing protocol overwrite')
        if head!=COMMIT:raise SystemExit('source commit mismatch')
        save(PROTO,{'_change_note':'[0 이영] 버전0: 수정 전 실패해야 하는 정밀도 교정 기대를 실행 전 봉인한다.',
                    'sealed_at_kst':now(),'commit':head,'source_sha256':hashes,'script_sha256':sha(Path(__file__)),
                    'expected_current_source':{'large_odd_mean_tests':2,'zero_tolerance_tests':2,'sub_floor_tolerance_tests':2,
                                               'distinct_large_integer_filter_test':1,'normal_controls':5,
                                               'expected_current_failures':7,'expected_current_passes':5},
                    'limits':'synthetic source_gate/human-confirmed inputs only; no loader/UI/approval/model/network/key execution'})
        print(json.dumps({'phase':'sealed','at_kst':now(),'protocol_sha256':sha(PROTO)},ensure_ascii=False))
        return
    if RESULT.exists():raise SystemExit('refusing results overwrite')
    protocol=json.loads(PROTO.read_text(encoding='utf-8'))
    assert hashes==protocol['source_sha256'] and head==protocol['commit']
    assert sha(Path(__file__))==protocol['script_sha256']
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(repo));sys.path.insert(0,str(repo/'finals'))
    global pd,verify,_claim,_calculate,filter_mask
    import pandas as pd
    from core.verifier import verify
    from core.normalization import filter_mask
    from finals_pipeline import _claim,_calculate
    started=now()
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(NumericRegression)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(RESULT,{'_change_note':'[0 이영] 버전0: 현재 소스의 교정 기대 실패와 정상 통제 성공을 분리 기록한다. 제품 수정 없음.',
                 'started_at_kst':started,'ended_at_kst':now(),'commit':head,'protocol_sha256':sha(PROTO),
                 'source_sha256':hashes,'script_sha256':sha(Path(__file__)),'tests_run':result.testsRun,
                 'failures':[{'test':str(test),'traceback':trace} for test,trace in result.failures],
                 'errors':[{'test':str(test),'traceback':trace} for test,trace in result.errors],
                 'passes':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
                 'expected_failures_are_reproduced_defects':True,'output':stream.getvalue()})
    assert {name:sha(repo/name) for name in sources}==hashes
    print(json.dumps({'phase':'executed','tests_run':result.testsRun,'passes':result.testsRun-len(result.failures)-len(result.errors),
                      'failures':len(result.failures),'errors':len(result.errors),'at_kst':now()},ensure_ascii=False))
    sys.exit(0 if result.wasSuccessful() else 1)

if __name__=='__main__':main()
