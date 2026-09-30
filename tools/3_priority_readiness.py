"""[3 조지현] 비교·제출 준비 상태를 호출 없이 확인한다. 원봉인/원자료는 수정하지 않는다."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/'finals'):
    if str(p) not in sys.path:sys.path.insert(0,str(p))


def sealed_input_status(evidence: Path) -> dict:
    seal=json.loads((evidence/'seal.json').read_text(encoding='utf-8-sig'))
    missing,changed,unsafe=[],[],[]
    for name,digest in seal['files'].items():
        target=(evidence/name).resolve()
        if not target.is_relative_to(evidence.resolve()):unsafe.append(name);continue
        if not target.is_file():missing.append(name);continue
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:changed.append(name)
    return {'ready':not(missing or changed or unsafe),'missing_files':missing,'changed_files':changed,'unsafe_paths':unsafe,
            'next_action':'복원 묶음 전체 지문 검사 후 비공개 입력 복원' if missing else '원봉인 지문과 입력 재대조' if changed or unsafe else '전송 본문 개인정보·사용량 사전점검'}


def readiness(evidence: Path) -> dict:
    result={'contributor_version':3,'checked_at_kst':datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
            'new_model_calls':0,'sealed_inputs':sealed_input_status(evidence),
            'claims_allowed':['등록된 제한 계산/보류/변경 동작의 검증 결과'],
            'claims_not_established':['범용 에이전트 대비 우위','연구자 업무 시간 절감','논문 전체 타당성 검증']}
    protocol=json.loads((evidence/'protocol.json').read_text(encoding='utf-8-sig'))
    shared=protocol.get('shared_conditions',{})
    result['comparison_contract']={'same_readonly_tools':shared.get('same_readonly_tools'),
        'scope':'MODEL_ONLY_VS_TOOL_ASSISTED_SYSTEM_NOT_EQUAL_TOOL_AGENT_COMPARISON',
        'next_action':'동일 계산·지문 도구를 제공하는 범용 에이전트 비교를 별도 프로토콜로 고정',
        'actual_model_comparison_executed_by_this_check':False}
    result['status']='INPUT_READY_FURTHER_CHECKS_REQUIRED' if result['sealed_inputs']['ready'] else 'BLOCKED_INPUTS'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence-dir',type=Path,default=ROOT/'finals/evidence');args=parser.parse_args()
    print(json.dumps(readiness(args.evidence_dir),ensure_ascii=False,indent=2))
