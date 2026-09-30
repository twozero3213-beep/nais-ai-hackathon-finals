"""Bounded feasibility probe. Korean affiliation is NOT professor verification."""
import argparse
import hashlib
import html as html_lib
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
import collect_faculty_base as base

FIELDS = {**base.TECHNICAL, **base.APPLIED}
PROBE_FIELDS = ['claim_evidence','provenance','research_workflow','clinical_treatment','economics_policy','energy_engineering']

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 이름 표기 비교; 입출력: 문자열→정규형; 검증: 공백/하이픈만 무시하고 이니셜 확장은 하지 않음.
def compact(value):
    return ''.join(ch for ch in value.casefold() if ch.isalnum())

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 같은 저자의 XML 소속 연결; 입출력: XML→저자/소속 목록; 검증: 저자 xref rid 또는 직접 자식 aff만 허용.
def author_links(raw):
    meta=ET.fromstring(raw).find('./front/article-meta')
    if meta is None:
        raise ValueError('Missing article-meta')
    affiliations={n.get('id'):base.clean(n) for n in meta.findall('.//aff') if n.get('id')}
    authors=[]
    for n in meta.findall('.//contrib'):
        if n.get('contrib-type','author') != 'author':
            continue
        name=n.find('name')
        if name is None:
            continue
        given=base.clean(name.find('given-names')); family=base.clean(name.find('surname'))
        rids=[rid for x in n.findall('xref') if x.get('ref-type')=='aff' for rid in x.get('rid','').split()]
        linked=[{'rid':rid,'text':affiliations[rid],'linkage':'AUTHOR_XREF'} for rid in rids if rid in affiliations]
        linked.extend({'rid':a.get('id',''),'text':base.clean(a),'linkage':'INLINE_AUTHOR_AFF'} for a in n.findall('aff'))
        orcids=[base.clean(x).removeprefix('https://orcid.org/').removeprefix('http://orcid.org/') for x in n.findall('contrib-id') if x.get('contrib-id-type','').lower()=='orcid']
        authors.append({'given_names':given,'surname':family,'name':(given+' '+family).strip(),'affiliations':linked,'orcid':orcids})
    return authors

# [작성:전문가4] 2026-09-27 case67 무엇/왜: XML xref 없는 출판형식의 공식 API 연결; 입출력: core 레코드→저자별 직접소속; 검증: 해당 author 객체의 affiliation만 사용, 공용소속 추정 금지.
def api_author_links(record):
    authors=[]
    for a in record.get('authorList',{}).get('author',[]):
        given=a.get('firstName','');family=a.get('lastName','')
        affiliations=[{'rid':str(i),'text':entry['affiliation'],'linkage':'EUROPE_PMC_API_AUTHOR_AFFILIATION'} for i,entry in enumerate(a.get('authorAffiliationDetailsList',{}).get('authorAffiliation',[])) if entry.get('affiliation')]
        authors.append({'given_names':given,'surname':family,'name':(given+' '+family).strip(),'affiliations':affiliations,'orcid':[]})
    return authors

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 교수 증거와 논문 저자 교차검사; 입출력: 공식프로필레코드/HTML/XML저자→판정; 검증: full-name+기관 일치 필수, 기관만으로 교수 판정 금지.
def match_faculty(profile, evidence, authors):
    required=['faculty_evidence_url','faculty_name','faculty_role','faculty_affiliation','faculty_evidence_quote','official_domain','institution_aliases']
    if any(not profile.get(k) for k in required):
        return {'status':'INSUFFICIENT_PROFILE_EVIDENCE'}
    parsed=urllib.parse.urlsplit(profile['faculty_evidence_url'])
    domain=profile['official_domain'].lower()
    if not parsed.hostname or not (parsed.hostname==domain or parsed.hostname.endswith('.'+domain)):
        return {'status':'PROFILE_DOMAIN_MISMATCH'}
    role=profile['faculty_role'].casefold()
    if role not in {'professor','associate professor','assistant professor','교수','부교수','조교수','정교수'}:
        return {'status':'ROLE_NEEDS_EXPLICIT_SCOPE'}
    html=evidence.decode('utf-8',errors='replace')
    html=re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ',html,flags=re.I|re.S)
    text=re.sub(r'\s+',' ',html_lib.unescape(re.sub('<[^>]*>',' ',html))).strip()
    quote=re.sub(r'\s+',' ',profile['faculty_evidence_quote']).strip()
    pieces=profile['faculty_name'].split()
    name_forms={compact(profile['faculty_name']),compact(' '.join(pieces[-1:]+pieces[:-1]))}
    abbreviated_professor=role=='professor' and bool(re.search(r'\bprof\.',quote,re.I))
    if quote not in text or not any(name in compact(quote) for name in name_forms) or not (compact(profile['faculty_role']) in compact(quote) or abbreviated_professor):
        return {'status':'QUOTE_NAME_ROLE_NOT_VERIFIED'}
    matches=[]
    for author in authors:
        forms={compact(author['given_names']+author['surname']),compact(author['surname']+author['given_names'])}
        if compact(profile['faculty_name']) not in forms:
            continue
        affiliations=[a for a in author['affiliations'] if any((bool(re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',a['text'],re.I)) if alias.isascii() and len(alias)<=4 else compact(alias) in compact(a['text'])) for alias in profile['institution_aliases'])]
        if not affiliations:
            continue
        if profile.get('orcid') and author['orcid'] and profile['orcid'] not in author['orcid']:
            continue
        basis='FULL_NAME_AND_API_LINKED_INSTITUTION' if all(a['linkage']=='EUROPE_PMC_API_AUTHOR_AFFILIATION' for a in affiliations) else 'FULL_NAME_AND_XML_LINKED_INSTITUTION'
        matches.append({'paper_author_name':author['name'],'paper_author_affiliations':affiliations,'paper_author_orcid':author['orcid'],'match_basis':basis})
    return {'status':'MATCHED' if len(matches)==1 else ('AMBIGUOUS' if len(matches)>1 else 'NOT_MATCHED'), 'faculty_evidence_url':profile['faculty_evidence_url'],'faculty_name':profile['faculty_name'],'faculty_role':profile['faculty_role'],'faculty_role_precision':'PROFESSOR_TITLE_RANK_UNSPECIFIED' if abbreviated_professor else 'AS_QUOTED','faculty_affiliation':profile['faculty_affiliation'],'faculty_evidence_quote':quote,'faculty_evidence_sha256':hashlib.sha256(evidence).hexdigest(),'faculty_evidence_collected_at':profile.get('faculty_evidence_collected_at'),'faculty_match_checked_at':base.now(),'faculty_status_basis':'CURRENT_OFFICIAL_PROFILE','role_at_publication':'NOT_ESTABLISHED','paper_author_match':matches}

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 직접 증거 우선순위 일관화; 입출력: XML/core/프로필→교수 판정; 검증: XML 직접연결 우선, 미연결 때만 저자별 API소속 대안.
def match_paper_faculty(profile,evidence,raw,metadata):
    matched=match_faculty(profile,evidence,author_links(raw))
    if matched['status']=='NOT_MATCHED':
        matched=match_faculty(profile,evidence,api_author_links(metadata))
    return matched

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 공식교수→실제논문 연결 1건만 검사; 입출력: 프로필JSON/제외목록→연결근거; 검증: 검색20개·본문최대3개, strict topic/license/DOI 유지.
def profile_probe(profile, out, excluded, excluded_pmc):
    evidence=base.fetch(profile['faculty_evidence_url'],out)
    if evidence is None:
        result={'status':'OFFICIAL_PROFILE_FETCH_FAILED','profile':profile}
    else:
        profile['faculty_evidence_collected_at']=base.now()
        (out/'faculty_profile.html').write_bytes(evidence)
        topic=' OR '.join('('+list(base.queries(FIELDS[field]))[-1].replace(' sort_cited:y','')+')' for field in profile['candidate_categories'])
        query='('+profile['author_query']+') AND AFF:"'+profile['faculty_affiliation']+'" AND ('+topic+') sort_cited:y'
        raw=base.fetch(base.API+'search?'+urllib.parse.urlencode({'query':query,'format':'json','resultType':'core','pageSize':20}),out)
        result={'status':'NO_VERIFIED_MATCH_IN_BOUNDED_SAMPLE','profile':profile,'query':query,'attempts':[]}
        if raw:
            (out/'faculty_search.json').write_bytes(raw); data=json.loads(raw);result['raw_hit_count']=data.get('hitCount')
            attempts=0
            for r in data.get('resultList',{}).get('result',[]):
                ident=base.doi(r.get('doi'));pmc=r.get('pmcid')
                categories=[field for field in profile['candidate_categories'] if base.relevance(r,FIELDS[field])]
                if not ident or not pmc or ident in excluded or pmc in excluded_pmc or not categories:
                    continue
                if attempts>=3:break
                attempts+=1;xml=base.fetch(base.API+pmc+'/fullTextXML',out)
                if not xml:continue
                try:
                    paper=base.parse_xml(xml,ident)
                    match=match_faculty(profile,evidence,author_links(xml))
                    item={'doi':ident,'pmcid':pmc,'title':r['title'],'matching_categories':categories,'paper_checks':paper,'faculty_match':match}
                    result['attempts'].append(item)
                    if match['status']=='MATCHED':
                        (out/(pmc+'.xml')).write_bytes(xml)
                        item['xml_path']=pmc+'.xml';item['xml_sha256']=hashlib.sha256(xml).hexdigest()
                        result['status']='ONE_FACULTY_PAPER_LINK_VERIFIED';break
                except (ValueError,ET.ParseError) as e:
                    result['attempts'].append({'doi':ident,'error':str(e)})
    (out/'faculty_link_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'raw_hit_count':result.get('raw_hit_count'),'attempt_count':len(result.get('attempts',[]))},ensure_ascii=False),flush=True)

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 제한 표본 가능성검사; 입출력: 출력/기존600목록→분야별표본·증거; 검증: 최대6쿼리×5후보/분야별XML1개, 교수확인편수는0으로 유지.
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--exclude-json',action='append',required=True);p.add_argument('--faculty-profile');a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    excluded=base.exclusions(a.exclude_json);excluded_pmc=base.exclusions(a.exclude_json,'pmcid')
    if a.faculty_profile:
        profile_probe(json.loads(Path(a.faculty_profile).read_text(encoding='utf-8')),out,excluded,excluded_pmc)
        return
    fields=base.fetch(base.API+'fields?format=json',out)
    if not fields:
        raise RuntimeError('Official field lookup failed')
    supported={x['term'] for x in json.loads(fields)['searchTermList']['searchTerms']}
    if not {'AFF','TITLE_ABS'} <= supported:
        raise RuntimeError('Required official search fields not confirmed')
    (out/'official_fields.json').write_bytes(fields)
    reports=[]
    for field in PROBE_FIELDS:
        query=list(base.queries(FIELDS[field]))[-1]+' AND (AFF:"Korea" OR AFF:"Republic of Korea")'
        url=base.API+'search?'+urllib.parse.urlencode({'query':query,'format':'json','resultType':'core','pageSize':5})
        raw=base.fetch(url,out)
        if not raw:
            reports.append({'category':field,'status':'SEARCH_FAILED'});continue
        (out/(field+'_search.json')).write_bytes(raw)
        data=json.loads(raw);samples=[];xml_attempted=False
        for r in data.get('resultList',{}).get('result',[]):
            ident=base.doi(r.get('doi'));pmc=r.get('pmcid')
            sample={'doi':ident,'pmcid':pmc,'title':r.get('title'),'excluded_existing600':ident in excluded or pmc in excluded_pmc,'topic_rule_pass':bool(base.relevance(r,FIELDS[field])),'faculty_status':'NOT_VERIFIED','api_author_list':r.get('authorList',{})}
            if not sample['excluded_existing600'] and sample['topic_rule_pass'] and pmc and not xml_attempted:
                xml_attempted=True;xml=base.fetch(base.API+pmc+'/fullTextXML',out)
                if xml:
                    try:
                        sample['paper_checks']=base.parse_xml(xml,ident)
                        sample['xml_authors']=author_links(xml)
                        sample['xml_path']=pmc+'.xml';sample['xml_sha256']=hashlib.sha256(xml).hexdigest()
                        (out/sample['xml_path']).write_bytes(xml)
                    except (ValueError,ET.ParseError) as e:
                        sample['paper_error']=str(e)
            samples.append(sample)
        report={'category':field,'query':query,'raw_hit_count':data.get('hitCount'),'sample_count':len(samples),'verified_faculty_paper_count':0,'samples':samples}
        reports.append(report);print(json.dumps({k:v for k,v in report.items() if k!='samples'},ensure_ascii=False),flush=True)
    (out/'feasibility.json').write_text(json.dumps({'mode':'BOUNDED_PROBE_NOT_FINAL_COLLECTION','fields_preserved':list(FIELDS),'reports':reports,'confirmed_professor_papers':0},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
