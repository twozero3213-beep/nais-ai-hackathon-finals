"""Synthetic, provider-neutral intake benchmark. No AI/API/analysis execution."""
import copy
import hashlib
import json
import pandas as pd
from core.models import Claim
from core.proposal_intake import review_proposal_json

# [작성: 전문가4·8] 2026-09-28 case84
# 무엇을: 두 열 이름에 같은 검토기를 재사용 / 왜: 앱 밖 호출 및 차단의 재실행 / 입력·출력: 없음->합성10건결과 / 검증: test_case84 demo + 실제 CLI.
def run_demo():
    records=[]
    for column,unit in [('rain_mm','mm'),('response_seconds','seconds')]:
        df=pd.DataFrame({column:[10,20]})
        fingerprint=hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()
        claim=Claim('SYNTHETIC-'+column,'Mean 15 '+unit,15,source_page=1,source_quote='Mean 15 '+unit)
        base=dict(claim_id=claim.claim_id,data_fingerprint=fingerprint,
                  evidence=dict(source_page=1,source_quote=claim.text),column=column,method='mean',filters=[],
                  denominator='2 nonmissing observations',missing_policy='complete_case',unit=unit,reported_value=15,tolerance=0)
        for name,updates,expected in [('complete',{},'PROPOSED'),('missing_denominator',{'denominator':''},'BLOCKED'),
                                      ('unsupported_method',{'method':'arbitrary_code'},'BLOCKED'),
                                      ('wrong_dataset',{'data_fingerprint':'0'*64},'BLOCKED'),
                                      ('changed_original',{'reported_value':999},'BLOCKED')]:
            payload=copy.deepcopy(base);payload.update(updates)
            report=review_proposal_json(json.dumps(payload),claim,df,fingerprint)
            records.append({'case':column+'/'+name,'expected':expected,'actual':report['state'],
                            'pass':report['state']==expected and not report['executed'] and not report['approved'],
                            'report':report})
    return {'scope':'Synthetic intake checks, not paper reproduction, model comparison, semantic labels or accuracy.',
            'all_passed':all(row['pass'] for row in records),'cases':records,
            'new_papers_reproduced':0,'ai_calls':0,'human_labels':0}

if __name__=='__main__':
    report=run_demo()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['all_passed'] else 1)
