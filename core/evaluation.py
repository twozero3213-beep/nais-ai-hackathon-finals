"""Same-input evaluation. Gold is supplied only after human review."""
from __future__ import annotations
import statistics
import math

from .team_workspace import MEMBERS


def _finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


# [작성: 전문가7] 2026-09-25 case49
# 무엇을: _independent_label_ready / 왜: 선택형 팀원 이름만으로 독립 사람 정답을 가장한 점수를 만들지 않기 위해 / 입력·출력: 라벨·원자료 해시 -> 구조적 검수 가능 여부 / 검증: tests/test_case49.py.
def _independent_label_ready(label, source_hash):
    if not isinstance(label, dict) or not isinstance(source_hash, str) or not source_hash:
        return False
    if not isinstance(label.get('verified_by'), str):
        return False
    if label.get('review_status') != 'APPROVED' or label.get('verified_by') not in MEMBERS or label.get('identity_verified') is False:
        return False
    action = label.get('expected_action')
    if action not in ('BLOCK', 'EXECUTE'):
        return False
    value = label.get('expected_value')
    tolerance = label.get('tolerance', 0)
    if not _finite_number(tolerance) or tolerance < 0:
        return False
    if action == 'EXECUTE' and not _finite_number(value):
        return False
    if action == 'BLOCK' and value is not None:
        return False
    reviews = label.get('independent_reviews')
    if not isinstance(reviews, list) or len(reviews) < 2:
        return False
    reviewer_ids = []
    identity_refs = []
    for review in reviews:
        if not isinstance(review, dict):
            return False
        reviewer_id = review.get('reviewer_id')
        if not isinstance(reviewer_id, str) or not reviewer_id.strip() or reviewer_id.strip() in MEMBERS:
            return False
        reviewer_ids.append(reviewer_id.strip())
        if review.get('independent_of_development') is not True or review.get('blind_to_outputs') is not True:
            return False
        if not all(isinstance(review.get(key), str) and review[key].strip() for key in ('identity_check_ref', 'source_location', 'rationale')):
            return False
        identity_refs.append(review['identity_check_ref'].strip())
        if review.get('data_sha256') != source_hash or review.get('expected_action') != action:
            return False
        if action == 'EXECUTE':
            if not _finite_number(review.get('expected_value')) or review['expected_value'] != value:
                return False
        elif review.get('expected_value') is not None:
            return False
    return len(set(reviewer_ids)) == len(reviewer_ids) and len(set(identity_refs)) == len(identity_refs)


# [작성: 전문가7] 2026-09-25 case43
# 무엇을: score_comparison / 왜: 미승인 정답·다른 원자료·불완전 시간을 성능 수치로 발표하지 않기 위해 / 입력·출력: 시스템별 결과, 승인 라벨, SHA 목록 -> 지표 또는 차단 / 검증: tests/test_case43.py.
# [수정: 전문가7] 2026-09-25 case49
# 종류: 오류수정 / 재현 방법: APPROVED와 선택형 팀원 이름만 있는 라벨이 SCORED 반환 / 변경 전: 이름만 확인 / 변경 후: 외부 독립 판정 2건의 블라인드·근거·자료 해시 기록을 요구 / 왜: 가상 검토와 사람 정답 혼동 차단 / 영향: 과거 간략 라벨은 NOT_SCORED.
def score_comparison(runs,labels,source_hashes):
    if not isinstance(source_hashes, dict) or not isinstance(labels, list) or not labels or any(
            not isinstance(x, dict) or not isinstance(x.get('claim_id'), str)
            or not _independent_label_ready(x, source_hashes.get(x['claim_id'])) for x in labels):
        return {'status':'NOT_SCORED','reason':'서로 다른 외부 판정자 2명의 블라인드·근거·원자료 일치 기록이 모두 필요합니다.'}
    if not isinstance(runs, dict) or not runs:
        return {'status':'NOT_SCORED','reason':'실제 시스템 결과가 필요합니다.'}
    ids={x['claim_id'] for x in labels}
    if len(ids)!=len(labels):raise ValueError('정답 라벨 ID가 중복됩니다.')
    gold={x['claim_id']:x for x in labels}
    systems={}
    for name,rows in runs.items():
        if not isinstance(rows, list) or any(not isinstance(x, dict) or not isinstance(x.get('claim_id'), str) for x in rows):
            raise ValueError(f'{name}: 예측 결과는 객체 목록이어야 합니다.')
        # [수정: 전문가7] 2026-09-25 case47
        # 종류: 오류수정 / 재현 방법: A의 BLOCK·EXECUTE를 중복 제출하면 마지막 행에 따라 재현률 변경 / 변경 전: dict 변환으로 앞 행 소실 / 변경 후: 중복 ID 채점 거부 / 왜: 동일 입력 비교의 결정성·감사 가능성 / 영향: 중복 결과 파일은 수정 전까지 점수 없음.
        if len({x['claim_id'] for x in rows})!=len(rows):raise ValueError(f'{name}: 예측 Claim ID가 중복됩니다.')
        pred={x['claim_id']:x for x in rows}
        if set(pred)!=ids:raise ValueError(f'{name}: 동일한 모든 Claim 결과가 필요합니다.')
        if any(pred[c].get('source_hash')!=source_hashes[c] for c in ids):raise ValueError(f'{name}: 원자료 해시가 일치하지 않습니다.')
        for c in ids:
            action, value = pred[c].get('action'), pred[c].get('value')
            if action not in ('BLOCK', 'EXECUTE') or (action == 'EXECUTE' and not _finite_number(value)) or (action == 'BLOCK' and value is not None):
                raise ValueError(f'{name}: {c} 예측 행동 또는 값이 유효하지 않습니다.')
        blocked=[c for c in ids if gold[c]['expected_action']=='BLOCK']
        executable=[c for c in ids if gold[c]['expected_action']=='EXECUTE']
        false_executions=sum(pred[c].get('action')=='EXECUTE' for c in blocked)
        reproduced=sum(pred[c]['action']=='EXECUTE' and abs(pred[c]['value']-gold[c]['expected_value'])<=gold[c].get('tolerance',0) for c in executable)
        times=[pred[c].get('review_seconds') for c in ids]
        median=statistics.median(times) if all(_finite_number(x) and x>=0 for x in times) else None
        systems[name]={'false_execution_rate':false_executions/len(blocked) if blocked else None,
                       'false_execution_denominator':len(blocked),'reproduction_rate':reproduced/len(executable) if executable else None,
                       'reproduction_denominator':len(executable),'review_seconds_median':median,'review_time_n':len(times) if median is not None else 0}
    return {'status':'SCORED','label_assurance':'독립 판정 기록의 구조만 확인; 실제 신원과 독립성은 외부 확인 필요','comparison_scope':'시스템별 지표만 계산; 동일 조건·원출력 검증이나 우위 판정 아님','n_cases':len(ids),'systems':systems}
