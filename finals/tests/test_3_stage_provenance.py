"""실행 지문과 두 모델 응답의 원호출·역할·모의 구분을 검증한다."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT/'finals'):
    if str(path) not in sys.path:sys.path.insert(0,str(path))
import finals_pipeline as p
import finals_cases as c
import finals_provenance as provenance


def test_snapshot_detects_code_change_even_when_commit_is_the_same(monkeypatch, tmp_path):
    for name in provenance.CODE_FILES:
        target=tmp_path/name;target.parent.mkdir(parents=True, exist_ok=True);target.write_text('original')
    monkeypatch.setattr(provenance,'ROOT',tmp_path)
    first=provenance.execution_snapshot()
    (tmp_path/'core/statistics.py').write_text('changed')
    second=provenance.execution_snapshot()
    assert first['execution_fingerprint'] != second['execution_fingerprint']
    assert first['code_files_sha256']['core/statistics.py'] != second['code_files_sha256']['core/statistics.py']
    assert not any(str(tmp_path) in key for key in second['code_files_sha256'])


@pytest.mark.parametrize('ready',[True,False])
def test_two_stage_outputs_and_receipts_survive_export_without_becoming_real_calls(ready):
    outputs=[c.load_case('NORMAL-PENG-ROWS')['manual_proposal'],{'evidence_ready':ready,'issues':[] if ready else ['check source']}]
    calls=[]
    def provider(*args,**kwargs):
        result=deepcopy(outputs[len(calls)]);calls.append(1)
        return {'output':result,'provider':'mock','model':'MOCK_TEST_ONLY','mock':True,
                'usage':{'input_tokens':2,'output_tokens':1},'request_id':'mock-'+str(len(calls)),
                'raw_sha256':'0'*64}
    report=p.run_case_ai('NORMAL-PENG-ROWS',provider=provider)
    records=report['model_stage_records']
    assert [x['role'] for x in records]==['proposal','critique']
    assert [x['output'] for x in records]==outputs
    assert all(x['mock'] for x in records) and not report['actual_model_output']
    assert all(x['received_at_kst'] and x['input_payload_sha256'] and x['output_sha256'] for x in records)
    assert records[1]['input_bindings']['proposal_sha256']==report['proposal_sha256']
    saved=p.reopen_report(p.export_report(report))
    assert saved['model_stage_records']==records
    assert not saved['human_approval']['active']
    assert saved['execution_provenance']==report['execution_provenance']


def test_manual_execution_has_no_model_records_and_separate_approval_state():
    report=p.run_case_manual('NORMAL-BAT-MEAN')
    assert report['model_stage_records']==[]
    assert report['execution_provenance']['execution_fingerprint']
    assert not report['human_approval']['approved']
