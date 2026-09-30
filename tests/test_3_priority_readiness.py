"""사전점검에서 누락/변조/경로 이탈을 준비 완료로 처리하지 않는다."""
import importlib.util
import hashlib
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('priority_readiness',Path(__file__).resolve().parents[1]/'tools/3_priority_readiness.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_missing_changed_and_outside_inputs_never_ready(tmp_path):
    (tmp_path/'input.csv').write_bytes(b'x\n1\n')
    seal={'files':{'input.csv':hashlib.sha256(b'x\n2\n').hexdigest(),'missing.csv':'0'*64,'../outside.csv':'0'*64}}
    (tmp_path/'seal.json').write_text(json.dumps(seal))
    result=module.sealed_input_status(tmp_path)
    assert result['ready'] is False
    assert result['changed_files']==['input.csv'] and result['missing_files']==['missing.csv']
    assert result['unsafe_paths']==['../outside.csv']


def test_intact_inputs_still_do_not_claim_model_comparison_or_equal_tools(tmp_path):
    (tmp_path/'input.csv').write_bytes(b'x\n1\n')
    (tmp_path/'seal.json').write_text(json.dumps({'files':{'input.csv':hashlib.sha256(b'x\n1\n').hexdigest()}}))
    (tmp_path/'protocol.json').write_text(json.dumps({'shared_conditions':{'same_readonly_tools':False}}))
    result=module.readiness(tmp_path)
    assert result['status']=='INPUT_READY_FURTHER_CHECKS_REQUIRED'
    assert result['new_model_calls']==0
    assert result['comparison_contract']['actual_model_comparison_executed_by_this_check'] is False
    assert result['comparison_contract']['same_readonly_tools'] is False
