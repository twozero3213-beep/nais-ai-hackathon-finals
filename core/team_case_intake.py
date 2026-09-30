"""Fixed team candidate: existing registry arithmetic only, no human approval."""
import hashlib
from pathlib import Path
from tools.case_registry import audit_registry, registration_readiness
from tools.change_impact import snapshot_registry

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'data/evaluation/team_chaewoo_20260929/forest_count_rows.json'
MANIFEST_SHA256 = 'c1368e499d09ea9cece66a3df434ff106d239766d44f105be8a0e583edff3f0f'


# [작성: 이채우 자료검증 담당] 2026-09-29 case105
# 입력 없음→고정 후보/차단 요약; 원자료행/개인값 출력·승인·정식카탈로그 변경 없음.
def intake_summary():
    return {
        'approved': False, 'arithmetic_only': True, 'full_paper_reproduced': False,
        'source_scope_verified': False,
        'forest': {
            'claim_id': 'FOREST-2015-N', 'status': 'ARITHMETIC_CANDIDATE',
            'paper_doi': '10.4996/fireecology.1101106', 'dataset_doi': '10.24432/C5D88D',
            'rows': 517, 'columns': 13, 'method': 'count_rows', 'reported_value': 517,
            'manifest': MANIFEST, 'unresolved': ['CODE_MISSING', 'UNIT_CONFLICT'],
            'note': '표본수 부분 산술 후보. 강우 mm 대 mm/m2 충돌·저자 실험코드 미확보 유지; 모형성능 재현 아님.'},
        'retail': {
            'action': 'BLOCK', 'status': 'VERSION_OR_COHORT_MISMATCH',
            'paper_doi': '10.1057/dbm.2012.17', 'dataset_doi': '10.24432/C5BW33',
            'rows': 541909, 'columns': 8, 'raw_period': '2010-12-01~2011-12-09',
            'reported_period': '2011년 전체', 'reported_rows': 406830,
            'reported_postcodes': 4381, 'independent_paper_value': None,
            'missing_required_columns': ['PostCode'],
            'source_basis': '제출 논문검토 기록; 유통 PDF는 이번 ZIP에 없어 재검토 미실행',
            'reason': '논문은 영국·유효 PostCode 집단, UCI는 기간이 다르고 PostCode가 없음. CustomerID 대체 금지.'}}


# [작성: 이채우 자료검증 담당] 2026-09-29 case105
# 고정명세 SHA→기존 준비도/두 계산기. 경로·raw/source SHA는 기존 등록기가 확인한다.
# 검증: 실제517·변조/누락BLOCK. 해시는 내용결속이며 작성자 인증/사람 승인 아님.
def run_forest_intake():
    result = intake_summary()
    result.update(action='BLOCK', executed=False)
    try:
        manifest = ROOT / MANIFEST
        if not manifest.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('고정 팀 명세 경로가 프로젝트 밖입니다.')
        raw = manifest.read_bytes()
        if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
            raise ValueError('고정 팀 명세 SHA256 불일치')
        ready = registration_readiness(raw, root=ROOT)
        result['readiness'] = ready
        if ready['results'][0]['action'] != 'REGISTRATION_READY':
            result['reason'] = '팀 원문·자료·조건의 등록 준비도 검사 차단'
            return result
        before = snapshot_registry(manifest, root=ROOT)
        audit = audit_registry(manifest, root=ROOT)
        # 실행 도중 파일 교체도 기존 입력 스냅샷으로 차단한다.
        if (audit['manifest_sha256'] != MANIFEST_SHA256 or
                before != snapshot_registry(manifest, root=ROOT)):
            raise ValueError('검산 중 팀 자료가 변경되었습니다.')
        result.update(audit=audit, action=audit['results'][0]['action'],
                      executed=audit['results'][0]['action'] in ('ARITHMETIC_MATCH', 'ARITHMETIC_MISMATCH'),
                      reason=audit['results'][0]['reason'])
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as error:
        result['reason'] = str(error) if not isinstance(error, OSError) else '고정 팀 자료를 읽을 수 없습니다.'
    return result
