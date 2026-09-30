"""Compare two prediction files only against independently approved labels."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from core.evaluation import score_comparison
from tools import independent_replay
from tools.compare_exploratory import read_json


# [작성: 전문가7] 2026-09-25 case43
# 무엇을: main / 왜: 제3자가 같은 사례·해시·승인 라벨로 지표 재계산 / 입력·출력: JSON 파일 경로 -> JSON 지표 / 검증: tests/test_case43.py.
# [수정: 전문가7] 2026-09-25 case50
# 종류: 오류수정 / 재현 방법: CSV를 바꾸거나 삭제해도 cases.json·예측의 선언 해시만 같으면 SCORED / 변경 전: 실제 원자료 바이트 미확인 / 변경 후: 기존 독립 재실행기의 경로·SHA-256 검사를 채점 전에 실행 / 왜: 현재 원자료와 평가 라벨 연결 보장 / 영향: 누락·변조 자료는 NOT_SCORED.
# [수정: 전문가4] 2026-09-26 case64
# 무엇/왜: 공통 JSON 판독기로 라벨·예측 중복 키 덮어쓰기 거부 / 입출력: 평가 파일 경로 -> 명확한 객체/ValueError / 검증: tests/test_case64_evaluation.py의 CLI 실패 3건.
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',default='data/evaluation/cases.json')
    parser.add_argument('--labels',default='data/evaluation/gold_proposals.json')
    parser.add_argument('--system',required=True)
    parser.add_argument('--baseline',required=True)
    args=parser.parse_args()
    cases=read_json(args.cases)['cases']
    try:independent_replay.replay_cases(Path(args.cases))
    except (OSError,ValueError):
        print(json.dumps({'status':'NOT_SCORED','reason':'현재 원자료 파일 누락 또는 선언 해시 불일치'},ensure_ascii=False,indent=2))
        return
    labels=read_json(args.labels)['labels']
    details={x['claim_id']:x for x in cases}
    for label in labels:label['tolerance']=details[label['claim_id']]['tolerance']
    runs={name:read_json(file)['results'] for name,file in [('evidence_gate',args.system),('general_ai',args.baseline)]}
    result=score_comparison(runs,labels,{c['claim_id']:c['data_sha256'] for c in cases})
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
