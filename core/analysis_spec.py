# [작성: 전문가4] 2026-09-23 case36
# 무엇을: 추론통계 분석명세의 canonical API를 제공한다.
# 왜: 버전명 모듈 의존을 제거하고 신규 코드가 하나의 안정 경로를 사용하게 한다.
# 입력·출력: 기존 case35 호환 API와 동일.
# 검증: tests/test_case36.py 및 전체 회귀 테스트.
"""Analysis-specification gate for Evidence Gate case25.

case25 SAFETY CHANGE
FAILURE: case24 could confirm a missing-data policy and then execute an inferential model even
when population/estimand/variance/multiplicity details were still unknown.
RISK: a numerically correct calculation under the wrong analysis specification can be
mislabelled as a reproduction failure.
WHY: reproduction requires the *reported analysis specification*, not merely the same test name.
CHANGE: inferential contracts receive an explicit specification object. Unknown material fields
are surfaced to the reviewer and execution is fail-closed until the reviewer confirms the
minimum supported specification.
REGRESSION: tests/test_case25.py covers blocked/unblocked paths.
"""
from dataclasses import dataclass, asdict, field

@dataclass
class AnalysisSpecification:
    population:str='unspecified'
    estimand:str='unspecified'
    missing_policy:str='unspecified'
    variance_estimator:str='unspecified'
    multiplicity_policy:str='unspecified'
    multiplicity_count:int=0
    # [작성/수정: 전문가5·6] 2026-09-26 case62
    # 무엇을: 전체 원 p 가족·대상·정의를 명세에 보존 / 왜: 부분 가족 보정 차단 및 재현.
    multiplicity_p_values:list[float]=field(default_factory=list)
    multiplicity_target_index:int|None=None
    multiplicity_family_definition:str=''
    reference_levels:dict=field(default_factory=dict)
    interactions:list[str]=field(default_factory=list)
    transforms:dict=field(default_factory=dict)
    human_confirmed:bool=False
    def to_dict(self): return asdict(self)

SUPPORTED_MISSING={'complete_case'}

def build_analysis_spec(claim):
    return AnalysisSpecification(
        population=getattr(claim,'analysis_population','unspecified'),
        estimand=getattr(claim,'estimand','unspecified'),
        missing_policy=getattr(claim,'missing_policy','unspecified'),
        variance_estimator=getattr(claim,'variance_estimator','unspecified'),
        multiplicity_policy=getattr(claim,'multiplicity_policy','unspecified'),
        multiplicity_count=getattr(claim,'multiplicity_count',0),
        multiplicity_p_values=list(getattr(claim,'multiplicity_p_values',[]) or []),
        multiplicity_target_index=getattr(claim,'multiplicity_target_index',None),
        multiplicity_family_definition=getattr(claim,'multiplicity_family_definition',''),
        reference_levels=dict(getattr(claim,'reference_levels',{}) or {}),
        interactions=list(getattr(claim,'interaction_terms',[]) or []),
        transforms=dict(getattr(claim,'transform_spec',{}) or {}),
        human_confirmed=bool(getattr(claim,'analysis_spec_confirmed',False)),
    )

def check_analysis_spec(spec, contract_type, method=""):
    """Return (executable, missing, unsupported).

    The prototype requires explicit human confirmation plus a supported missing-data policy.
    Population/estimand/multiplicity remain auditable fields; 'unspecified' is allowed only after
    the reviewer explicitly confirms that the source does not report them. This prevents the UI
    from silently inventing details while keeping the prototype usable on incomplete papers.
    """
    # [수정: 0 이영] 2026-09-30 22:44 KST — C03: 1표본 t는 DESCRIPTIVE 경로에서도 추론 명세·정책을 검사한다.
    if contract_type=='SCOPE' or (contract_type=='DESCRIPTIVE' and method!='one_sample_t'): return True,[],[]
    missing=[]; unsupported=[]
    if not spec.human_confirmed: missing.append('analysis specification confirmation')
    if spec.missing_policy=='unspecified': missing.append('missing-data policy')
    elif spec.missing_policy not in SUPPORTED_MISSING: unsupported.append('missing-data policy:'+spec.missing_policy)
    # [수정: 전문가6] 2026-09-25 case40
    # 종류: 오류수정
    # 재현 방법: robust 분산·Bonferroni·상호작용·변환을 기록해도 기본 검정이 실행됐다.
    # 변경 전: 결측 정책만 검사하고 실제 미구현 명세는 무시.
    # 변경 후: 실행 엔진에 연결되지 않은 명시적 정책은 차단한다.
    # 왜: 다른 분석을 같은 결과의 재현으로 오인하면 안 된다.
    # 영향: 미지원 고급 분석 명세는 사람 확인 후에도 BLOCKED로 남는다.
    # [수정: 전문가6] 2026-09-25 case43
    # 종류: 통계검정추가 / 재현 방법: Welch 검정의 welch 분산 정책이 차단됨 / 변경 전: classical만 허용 / 변경 후: 실행기가 검정 일치를 확인할 때 welch 허용 / 왜: 명시된 방법 재현 / 영향: 불일치는 계속 차단.
    if spec.variance_estimator not in {'unspecified','classical','welch'}:
        unsupported.append('variance estimator:'+spec.variance_estimator)
    # [수정: 전문가6] 2026-09-25 case43
    # 종류: 통계검정추가 / 재현 방법: Bonferroni 명세가 있어도 실행 차단 / 변경 전: 전부 미지원 / 변경 후: 가족 크기 확인 시 단일 p 보정 / 왜: 원문 보정 정책 재현 / 영향: Holm·BH는 전체 p 벡터 없으면 계속 차단.
    if spec.multiplicity_policy=='bonferroni':
        # [수정: 0 이영] 2026-09-30 22:44 KST — 보정 가족 크기에 bool·소수·비양수 입력을 허용하지 않는다.
        if type(spec.multiplicity_count) is not int or spec.multiplicity_count<2:unsupported.append('multiplicity family size:unconfirmed')
    elif spec.multiplicity_policy in {'holm','bh','fdr_bh'}:
        try: validate_multiplicity_family(spec)
        except (TypeError,ValueError): unsupported.append('multiplicity family:incomplete or invalid')
    elif spec.multiplicity_policy not in {'unspecified','none','none_reported','unadjusted'}:
        unsupported.append('multiplicity policy:'+spec.multiplicity_policy)
    if spec.reference_levels: unsupported.append('reference levels')
    if spec.interactions: unsupported.append('interactions')
    if spec.transforms: unsupported.append('transforms')
    return not missing and not unsupported,missing,unsupported


# [작성/수정: 전문가5·6] 2026-09-26 case62
# 무엇을: Holm/BH 전체 가족 공통 가드 / 왜: count·대상·가족 정의가 없으면 보정 재현 불가.
# 입력·출력: 명시 가족 -> 보정 벡터; 불완전 -> ValueError / 검증: test_incomplete_family_blocked.
def validate_multiplicity_family(spec):
    from .statistics import adjust_pvalues
    adjusted=adjust_pvalues(spec.multiplicity_p_values,spec.multiplicity_policy)
    count=spec.multiplicity_count
    index=spec.multiplicity_target_index
    if type(count) is not int or count<2 or count!=len(adjusted):
        raise ValueError('전체 검정 가족 크기와 p값 개수가 일치해야 합니다.')
    if type(index) is not int or not 0<=index<count:
        raise ValueError('대상 검정의 0부터 시작하는 인덱스가 필요합니다.')
    if not isinstance(spec.multiplicity_family_definition,str) or not spec.multiplicity_family_definition.strip():
        raise ValueError('전체 검정 가족 정의가 필요합니다.')
    return adjusted
