from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib, json
class Status(str,Enum):
 SUPPORTED='SUPPORTED'; CONFLICT='CONFLICT'; MISSING='MISSING'; OVERCLAIM='OVERCLAIM'; REVIEW='REVIEW'; VALIDATED='VALIDATED'
@dataclass
class Claim:
 claim_id:str; text:str; original_value:float|None=None; column:str=''; aggregation:str='mean'; tolerance:float=0.15; qualifier:str=''; current_value:float|None=None; status:Status=Status.REVIEW; reason:str=''; revision_count:int=0; validated_signature:str=''; last_auto_signature:str=''; history:list[dict]=field(default_factory=list); decomposition:dict=field(default_factory=dict); evidence_candidates:list[dict]=field(default_factory=list); filters:list[dict]=field(default_factory=list); semantic_confirmed:bool=False; source_page:int|None=None; source_quote:str=''; claim_type:str='percentage'; analysis_method:str=''; weight_column:str=''; success_value:str='1'; group_column:str=''; group_a:str=''; group_b:str=''; x_column:str=''; mu0:float=0.0; alpha:float=0.05; reported_p_value:float|None=None; reported_p_operator:str=''; reported_effect:float|None=None; effect_kind:str=''; reported_ci95:tuple|None=None; missing_policy:str='unspecified'; missing_policy_confirmed:bool=False; analysis_population:str='unspecified'; estimand:str='unspecified'; variance_estimator:str='unspecified'; multiplicity_policy:str='unspecified'; reference_levels:dict=field(default_factory=dict); interaction_terms:list[str]=field(default_factory=list); transform_spec:dict=field(default_factory=dict); analysis_spec_confirmed:bool=False; scope_endpoint:str=''; scope_subgroup_dimensions:list[str]=field(default_factory=list); scope_timepoints:list[str]=field(default_factory=list); scope_confirmed:bool=False; method_candidate:str=''; method_candidate_source:str=''; method_confirmed:bool=False; evidence_source:str='system_candidate'; evidence_provenance:dict=field(default_factory=dict); method_provenance:dict=field(default_factory=dict); validated_data_hash:str=''
 # [수정: 전문가4] 2026-09-25 case43
 # 종류: 오류수정 / 재현 방법: 정정 뒤 Claim.status만 저장돼 원문 판정 추적 불가 / 변경 전: 단일 상태 / 변경 후: 원문·정정 상태와 사유 별도 보존 / 왜: 공유 스냅샷의 과학적 의미 분리 / 영향: 기존 status는 호환용 현재값 판정으로 유지.
 reported_status:Status=Status.REVIEW; reported_reason:str=''; amendment_status:Status=Status.REVIEW; amendment_reason:str=''; multiplicity_count:int=0
 # [작성/수정: 전문가5·6] 2026-09-26 case62
 # 무엇을: 가족 명세 저장·승인서명 결속 / 왜: 가족 변경 시 재검증 필수 / 검증: test_target_mismatch_and_changed_signature.
 multiplicity_p_values:list[float]=field(default_factory=list); multiplicity_target_index:int|None=None; multiplicity_family_definition:str=''
 def __post_init__(self):
  if self.current_value is None:self.current_value=self.original_value
 @property
 def report_value(self):return self.current_value
 @report_value.setter
 def report_value(self,v):self.current_value=v
 def verification_signature(self):
  # [수정: 전문가7] 2026-09-25 case58
  # 무엇을: 실제 계산에 쓰는 방법·인자를 승인 서명에 포함 / 왜: 방법 변경 뒤 기존 승인 재사용 방지 / 검증: tests/test_case58_approval.py.
  from .typed_contracts import ContractType, route_contract_type
  contract_type=route_contract_type(self)
  # [작성: 전문가7] 2026-09-25 case58
  # 무엇을: 확정 근거 필드만 승인 서명에 담음 / 왜: 후보 점수 변경과 확정 근거 변경을 구분 / 입력·출력: provenance dict -> 확정 필드 dict / 검증: tests/test_case58_approval.py.
  def confirmed_record(record):
   return {k:record.get(k) for k in ('value','source','source_location','selected_by','selected_at','confirmed_by','confirmed_at')} if record else {}
  # [수정: 전문가7] 2026-09-25 case58
  # 무엇을: 확정 근거·계약 유형별 분석 명세만 승인 서명에 결속 / 왜: 후보 점수 같은 UI 변화는 무시하고 계약 변경은 재승인 요구 / 검증: tests/test_case58_approval.py.
  p={'current_value':self.current_value,'column':self.column,'aggregation':self.aggregation,'analysis_method':self.analysis_method,'tolerance':self.tolerance,'filters':self.filters,'semantic_confirmed':self.semantic_confirmed,'weight_column':self.weight_column,'success_value':self.success_value,'group_column':self.group_column,'group_a':self.group_a,'group_b':self.group_b,'x_column':self.x_column,'mu0':self.mu0,'alpha':self.alpha,'decomposition':self.decomposition,'source_quote':self.source_quote or self.text,'source_page':self.source_page,'contract_type':contract_type.value,'evidence_provenance':confirmed_record(self.evidence_provenance)}
  # [수정: 0 이영] 2026-09-30 22:57 KST — C03: 1표본 t의 분석 정책 변경도 기존 검증 서명을 무효화하도록 명세를 결속한다.
  if contract_type in {ContractType.COMPARATIVE,ContractType.ASSOCIATION,ContractType.REGRESSION} or (self.analysis_method or self.method_candidate or self.aggregation)=="one_sample_t":
   p.update({'method_confirmed':self.method_confirmed,'method_provenance':confirmed_record(self.method_provenance),'analysis_spec_confirmed':self.analysis_spec_confirmed,'missing_policy':self.missing_policy,'missing_policy_confirmed':self.missing_policy_confirmed,'analysis_population':self.analysis_population,'estimand':self.estimand,'variance_estimator':self.variance_estimator,'multiplicity_policy':self.multiplicity_policy,'multiplicity_count':self.multiplicity_count,'multiplicity_p_values':self.multiplicity_p_values,'multiplicity_target_index':self.multiplicity_target_index,'multiplicity_family_definition':self.multiplicity_family_definition,'reference_levels':self.reference_levels,'interaction_terms':self.interaction_terms,'transform_spec':self.transform_spec})
  if contract_type==ContractType.SCOPE:
   p.update({'scope_confirmed':self.scope_confirmed,'scope_endpoint':self.scope_endpoint,'scope_subgroup_dimensions':self.scope_subgroup_dimensions,'scope_timepoints':self.scope_timepoints})
  return hashlib.sha256(json.dumps(p,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 def transition(self,status,reason,actor='SYSTEM',action='TRANSITION'):
  before=self.status; self.history.append({'at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'actor':actor,'action':action,'from':before.value,'to':status.value,'reason':reason}); self.status=status; self.reason=reason
 def revise(self,new_value,reason):
  before=self.current_value; self.current_value=float(new_value); self.revision_count+=1; self.validated_signature=''; self.amendment_status=Status.REVIEW; self.amendment_reason='정정값 재검증 전'; self.history.append({'at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'actor':'HUMAN','action':'REVISE_VALUE','from_value':before,'to_value':self.current_value,'reason':reason}); return before
 def validate(self,reason):
  self.transition(Status.VALIDATED,reason,'HUMAN','APPROVE'); self.validated_signature=self.verification_signature()
  if self.revision_count:self.amendment_status=Status.VALIDATED;self.amendment_reason=reason
