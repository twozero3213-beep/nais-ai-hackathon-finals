"""Professor-linked bibliography; only CC BY/CC0 full text is archived."""
import argparse
import collections
import csv
import hashlib
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
import collect_faculty_base as base
from probe_faculty import FIELDS, author_links, match_faculty, match_paper_faculty, api_author_links
from collect_faculty_publications import extraction_component_terms, statistical_method_terms

START_DATE='2000-01-01'
END_DATE='2026-09-27'

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 승인된 과거 서지 범위 확장; 입출력: 발행일→허용여부; 검증: 2000년 경계와 미래 자료 제외.
def eligible_date(value):
    return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',value or '')) and START_DATE<=value<=END_DATE

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 승인된 추출 구성요소 범위 공통화; 입출력: 메타/분야→키워드근거; 검증: 제목의 네 명시적 추출 방법만 확장 허용.
def faculty_relevance(record,category):
    hits=base.relevance(record,FIELDS[category])
    if hits:return hits
    if category=='psychology_behavior':
        title=record.get('title','').lower();text=title+' '+record.get('abstractText','').lower()
        anchors=[w for w in ['craving','impulsiv','decision making','decision-making','gambling task','addictive behavior','substance use disorder','psychiatric','suicid'] if w in title]
        context=[w for w in ['participants','patients','individuals','children','youth','human','subjects'] if w in text]
        outcomes=[w for w in ['behavior','behaviour','cognit','emotion','symptom','suicid','craving','impulsiv','psychological'] if w in text]
        return [anchors,context+outcomes] if anchors and context and outcomes else None
    terms=extraction_component_terms(record.get('title','')) if category=='claim_evidence' else []
    if category=='statistics':
        terms=statistical_method_terms(record.get('title',''),record.get('abstractText',''))
        return [terms,['STATISTICAL_METHOD_REFERENCE']] if terms else None
    return [terms,['EXTRACTION_COMPONENT_METHOD']] if terms else None

# [작성:전문가4] 2026-09-27 case67 무엇/왜: API 이니셜 색인 누락 보완; 입출력: 공식 교수 이름→검색OR식; 검증: 검색에만 사용하고 XML 실명 판정은 확장하지 않음.
def author_query(profile):
    pieces=profile['faculty_name'].split()
    given=' '.join(pieces[:-1]);parts=re.findall(r'[A-Z][a-z]*|[a-z]+',given)
    initials=''.join(x[0] for x in parts)
    query=profile['author_query']
    if len(pieces)>1 and initials:
        variants=[pieces[-1]+' '+initials,pieces[-1]+' '+initials[0],re.sub(r'[-\s]','',given)+' '+pieces[-1],profile['faculty_name'].replace('-',' ')]
        for variant in variants:
            alias='AUTH:"'+variant+'"'
            if alias not in query:query+=' OR '+alias
    return query

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 정정된 원연구와 정정공고 분리; 입출력: API메타/분야→제외여부; 검증: correctionList 존재만으로 정상원연구 거부 금지, 철회/프로토콜은 제외.
def excluded_metadata(record,category):
    title=re.sub('<[^>]+>',' ',record.get('title','')).lower().strip();types=json.dumps(record.get('pubTypeList',{})).lower()
    links=json.dumps(record.get('commentCorrectionList',{})).lower()
    if 'retract' in links or 'expression of concern' in links:return True
    if any(x in types for x in ['retract','correction','erratum','protocol','editorial','meeting abstract','conference abstract','abstract-only']):return True
    return bool(re.search(r'^(?:correction|erratum|retraction|withdrawn|editorial)\b|\b(?:study protocol|trial protocol|protocol for|protocol of)\b',title))

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 서지선정과 분석적격성 분리; 입출력: XML/API유형→출처별표시; 검증: review 충돌을 research로 표시하지 않음.
def publication_type_facts(xml_type,metadata,category=None):
    types=metadata.get('pubTypeList',{}).get('pubType',[])
    api_review=any('review' in value.lower() for value in types)
    conflict=xml_type=='research-article' and api_review
    review=xml_type=='review-article' or api_review
    status='CONFLICTING_SOURCE_TYPES' if conflict else ('REVIEW_CONFIRMED' if review else ('RESEARCH_ARTICLE_LABEL' if xml_type else 'NOT_CONFIRMED'))
    role='REVIEW_BACKGROUND' if review else ('RESEARCH_CANDIDATE' if xml_type else 'UNCLASSIFIED_REFERENCE')
    if category=='claim_evidence' and not base.relevance(metadata,FIELDS[category]) and extraction_component_terms(metadata.get('title','')):role='EXTRACTION_COMPONENT_METHOD'
    if category=='statistics' and not base.relevance(metadata,FIELDS[category]) and statistical_method_terms(metadata.get('title',''),metadata.get('abstractText','')):role='STATISTICAL_METHOD_REFERENCE'
    return {'article_type':'CONFLICTING_SOURCE_TYPES' if conflict else (xml_type or ('review-article' if review else 'NOT_CONFIRMED')),'xml_article_type':xml_type,'api_publication_types':types,'publication_type_status':status,'reference_role':role,'analysis_eligibility':'NOT_ESTABLISHED'}

# [작성:전문가4] 2026-09-27 case67 무엇/왜: XML 미확보 서지와 원문 상태 분리; 입출력: 공식 core 메타→미확인 상태; 검증: OA 선언은 실제 본문확보/라이선스확인으로 승격하지 않음.
def metadata_only_checks(metadata,category=None):
    return {**publication_type_facts(None,metadata,category),'license':'NOT_CONFIRMED','fulltext_status':'CITATION_METADATA_ONLY','fulltext_access_status':'DECLARED_OPEN_NOT_FETCHED' if metadata.get('isOpenAccess')=='Y' else 'NON_OPEN_OR_UNKNOWN','data_link_status':'NOT_IDENTIFIED','data_link_status_basis':'BODY_NOT_FETCHED','raw_data_download_status':'NOT_TESTED','reproduction_status':'NOT_TESTED'}

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 보관·링크 정책 독립 검증; 입출력: 최종목록/출력루트→검증통계; 검증: 해시·고유성·교수근거·금지 원문필드 검사.
def verify(records,out,excluded,excluded_pmc,per_field):
    seen=set();pmcs=set();counts=collections.Counter();states=collections.Counter()
    for r in records:
        if r['doi'] in seen|excluded or (r.get('pmcid') and r['pmcid'] in pmcs|excluded_pmc):raise ValueError('Duplicate or excluded identity')
        seen.add(r['doi'])
        if r.get('pmcid'):pmcs.add(r['pmcid'])
        counts[r['category']]+=1
        if r['category'] not in FIELDS or counts[r['category']]>per_field:raise ValueError('Invalid category count')
        match=r['faculty_match']
        if not r.get('faculty_profile'):raise ValueError('Original faculty profile definition missing')
        if match['status']!='MATCHED' or len(match['paper_author_match'])!=1:raise ValueError('Faculty match missing')
        evidence=(out/r['faculty_evidence_path']).read_bytes()
        if hashlib.sha256(evidence).hexdigest()!=match['faculty_evidence_sha256']:raise ValueError('Faculty profile hash mismatch')
        facthash=hashlib.sha256(json.dumps(match['paper_author_match'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if facthash!=r['author_link_evidence_sha256']:raise ValueError('Author evidence hash mismatch')
        rawmeta=(out/r['metadata_source_path']).read_bytes()
        if hashlib.sha256(rawmeta).hexdigest()!=r['metadata_source_sha256']:raise ValueError('Metadata hash mismatch')
        candidates=json.loads(rawmeta).get('resultList',{}).get('result',[])
        matched_meta=next((m for m in candidates if base.doi(m.get('doi'))==r['doi'] and (m.get('pmcid') or None)==r.get('pmcid') and m.get('title')==r['title']),None)
        if matched_meta is None:raise ValueError('Metadata identity/title mismatch')
        if not faculty_relevance(matched_meta,r['category']):raise ValueError('Topic relevance no longer matches')
        if excluded_metadata(matched_meta,r['category']):raise ValueError('Excluded publication metadata')
        if r['fulltext_status']!='CITATION_METADATA_ONLY' and r.get('xml_article_type') not in {'research-article','review-article'}:raise ValueError('Original XML publication type missing')
        if any(r.get(k)!=v for k,v in publication_type_facts(r['xml_article_type'],matched_meta,r['category']).items()):raise ValueError('Publication type evidence mismatch')
        state=r['fulltext_status'];states[state]+=1
        if state=='ARCHIVED_CC_BY_OR_CC0':
            xml=(out/r['fulltext_path']).read_bytes()
            if hashlib.sha256(xml).hexdigest()!=r['fulltext_sha256']:raise ValueError('Fulltext hash mismatch')
            if inspect_paper(xml,r['doi'],r['category'])['fulltext_status']!=state:raise ValueError('Archive license mismatch')
            checked=match_paper_faculty(r['faculty_profile'],evidence,xml,matched_meta)
            if checked['status']!='MATCHED' or checked['paper_author_match']!=match['paper_author_match']:raise ValueError('Archived XML author evidence mismatch')
        elif state in {'LINK_ONLY_REUSE_RESTRICTED','CITATION_METADATA_ONLY'}:
            if 'fulltext_path' in r or 'fulltext_sha256' in r:raise ValueError('Restricted fulltext must not be archived')
            if state=='CITATION_METADATA_ONLY':
                if any(r.get(k)!=v for k,v in metadata_only_checks(matched_meta,r['category']).items()):raise ValueError('Metadata-only evidence/status mismatch')
            if match['paper_author_match'][0]['match_basis']=='FULL_NAME_AND_API_LINKED_INSTITUTION':
                checked=match_faculty(r['faculty_profile'],evidence,api_author_links(matched_meta))
                if checked['status']!='MATCHED' or checked['paper_author_match']!=match['paper_author_match']:raise ValueError('API author evidence mismatch')
        else:raise ValueError('Unknown fulltext status')
        if r['raw_data_download_status']!='NOT_TESTED' or r['reproduction_status']!='NOT_TESTED':raise ValueError('Invalid execution status')
    return {'verified_selected':len(records),'counts':dict(counts),'fulltext_status_counts':dict(states),'target_complete':all(counts[k]==per_field for k in FIELDS),'verification_scope':'Saved evidence integrity; link-only XML not retained for offline reanalysis'}

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 검토 가능한 서지 목록 저장; 입출력: 선정목록/폴더→JSON·CSV·MD; 검증: 원문보관 상태와 교수 확인을 별도 표시.
def save(records,out):
    (out/'papers.json').write_text(json.dumps({'generated_at':base.now(),'papers':records},ensure_ascii=False,indent=2),encoding='utf-8')
    columns=['category','doi','pmcid','title','publication_date','fulltext_status','fulltext_url','faculty_name','faculty_evidence_url']
    with (out/'papers.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for r in records:writer.writerow({k:r.get(k,r['faculty_match'].get(k,'')) for k in columns})
    lines=['# 국내 대학 교수 참여 논문','', '분야는 자동 규칙 분류. 원자료 다운로드·분석 재현은 NOT_TESTED. 링크 전용 논문은 원문 보관 편수에 포함하지 않음.','']
    for r in records:lines.append('- ['+r['category']+'] '+r['title']+' — DOI '+r['doi']+' — '+r['faculty_match']['faculty_name']+' — '+r['fulltext_status'])
    (out/'papers.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 제한 이용 원문을 서지와 분리; 입출력: XML/DOI/분야→저장 정책; 검증: 원래 파서 통과만 보관, 라이선스 외 오류는 거부.
def inspect_paper(raw, ident, category):
    root=ET.fromstring(raw)
    meta=root.find('./front/article-meta')
    if meta is None or not base.clean(root.find('body')):
        raise ValueError('Missing article body or metadata')
    ids={base.doi(base.clean(n)) for n in meta.findall('article-id') if n.get('pub-id-type')=='doi'}
    if ident not in ids:
        raise ValueError('Article DOI mismatch')
    kind=root.get('article-type','')
    if kind not in {'research-article','review-article'}:
        raise ValueError('Disallowed article type')
    try:
        parsed=base.parse_xml(raw,ident)
        return {**parsed,'fulltext_status':'ARCHIVED_CC_BY_OR_CC0'}
    except ValueError as error:
        if str(error)!='No explicit CC BY/CC0 article license URL':
            raise
    licenses=[base.clean(n) for n in meta.findall('./permissions/license')]
    urls=[v for n in meta.findall('./permissions/license') for el in n.iter() for k,v in el.attrib.items() if k.endswith('href')]
    return {'article_type':kind,'license':'REUSE_RESTRICTED_OR_UNCONFIRMED','license_evidence':licenses,'license_urls':urls,'fulltext_status':'LINK_ONLY_REUSE_RESTRICTED','raw_data_download_status':'NOT_TESTED','reproduction_status':'NOT_TESTED','data_link_status':'NOT_IDENTIFIED','data_link_status_basis':'NOT_EXTRACTED_FOR_LINK_ONLY_RECORD'}

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 교수별 기존 검색 재사용; 입출력: 프로필/제외목록→선정 서지; 검증: DOI/PMCID 전역고유, 교수 본인 소속, 분야별20 상한.
def main():
    p=argparse.ArgumentParser();p.add_argument('--profiles');p.add_argument('--output',required=True);p.add_argument('--exclude-json',action='append',required=True);p.add_argument('--per-field',type=int,default=20);p.add_argument('--verify-only',action='store_true');p.add_argument('--category',action='append',choices=list(FIELDS));p.add_argument('--focused',action='store_true',help='One core query/page per profile/category with full author name only')
    a=p.parse_args()
    if a.per_field<1:raise ValueError('per-field must be positive')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    excluded=base.exclusions(a.exclude_json);excluded_pmc=base.exclusions(a.exclude_json,'pmcid')
    target=out/'papers.json';records=json.loads(target.read_text(encoding='utf-8'))['papers'] if target.exists() else []
    if records:verify(records,out,excluded,excluded_pmc,a.per_field)
    if a.verify_only:
        print(json.dumps(verify(records,out,excluded,excluded_pmc,a.per_field),ensure_ascii=False),flush=True);return
    if not a.profiles:raise ValueError('profiles required for collection')
    profiles=json.loads(Path(a.profiles).read_text(encoding='utf-8'))
    if isinstance(profiles,dict):profiles=[profiles]
    if a.category:profiles=[p for p in profiles if set(p['candidate_categories'])&set(a.category)]
    seen=excluded|{r['doi'] for r in records};seen_pmc=excluded_pmc|{r['pmcid'] for r in records if r.get('pmcid')};counts=collections.Counter(r['category'] for r in records)
    report=json.loads((out/'collection_report.json').read_text(encoding='utf-8')) if (out/'collection_report.json').exists() else []
    for profile in profiles:
        evidence=base.fetch(profile['faculty_evidence_url'],out)
        if evidence is None:
            report.append({'faculty':profile['faculty_name'],'error':'PROFILE_FETCH_FAILED'});continue
        profile['faculty_evidence_collected_at']=base.now()
        digest=hashlib.sha256(evidence).hexdigest();rel='profiles/'+digest+'.html';(out/'profiles').mkdir(exist_ok=True);(out/rel).write_bytes(evidence)
        profile_check=match_faculty(profile,evidence,[])
        if profile_check['status']!='NOT_MATCHED':
            report.append({'faculty':profile['faculty_name'],'error':profile_check['status'],'faculty_evidence_url':profile['faculty_evidence_url'],'faculty_evidence_path':rel})
            (out/'collection_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            continue
        for category in profile['candidate_categories']:
            if a.category and category not in a.category:continue
            if counts[category]>=a.per_field:continue
            failures=collections.Counter();hits=0;attempted=set()
            topic_queries=[(q,False) for q in base.queries(FIELDS[category])]
            topic_queries.append((topic_queries[-1][0].replace(' AND OPEN_ACCESS:Y','').replace(' AND IN_PMC:Y',''),True))
            if category=='claim_evidence':
                component=' OR '.join('TITLE_ABS:"'+term+'"' for term in ['entity recognition','relation extraction','coreference','document extraction'])
                topic_queries.append(('('+component+') AND FIRST_PDATE:['+START_DATE+' TO '+END_DATE+']',True))
            if category=='statistics':
                method=' OR '.join('TITLE_ABS:"'+term+'"' for term in ['statistical','inference','regression','resampling','bootstrap','permutation','contingency','parametric','large-sample test'])
                topic_queries.append(('('+method+') AND FIRST_PDATE:['+START_DATE+' TO '+END_DATE+']',True))
            if a.focused:topic_queries=topic_queries[-1:]
            else:topic_queries.append(('FIRST_PDATE:['+START_DATE+' TO '+END_DATE+']',True))
            for topic,allow_metadata in topic_queries:
                topic=topic.replace('2015-01-01',START_DATE)
                affiliation_query=' OR '.join('AFF:"'+alias+'"' for alias in profile['institution_aliases'])
                authors='AUTH:"'+profile['faculty_name']+'"' if a.focused else author_query(profile)
                query='('+authors+') AND ('+affiliation_query+') AND ('+topic.replace(' sort_cited:y','').replace(' sort_date:y','')+') sort_date:y'
                cursor='*'
                for page in range(1 if a.focused else 10):
                    url=base.API+'search?'+urllib.parse.urlencode({'query':query,'format':'json','resultType':'core','pageSize':100,'cursorMark':cursor})
                    raw=base.fetch(url,out)
                    if not raw:failures['SEARCH_FAILED']+=1;break
                    data=json.loads(raw);hits=max(hits,data.get('hitCount',0));searchpath='search_'+hashlib.sha256(raw).hexdigest()+'.json';(out/searchpath).write_bytes(raw)
                    for r in data.get('resultList',{}).get('result',[]):
                        ident=base.doi(r.get('doi'));pmc=r.get('pmcid')
                        if not ident or (not pmc and not allow_metadata):failures['MISSING_IDENTIFIERS']+=1;continue
                        if not eligible_date(r.get('firstPublicationDate','')):failures['DATE_RANGE']+=1;continue
                        if ident in seen or (pmc and pmc in seen_pmc):failures['DUPLICATE']+=1;continue
                        if ident in attempted:failures['REPEATED_QUERY_CANDIDATE']+=1;continue
                        attempted.add(ident)
                        relevance=faculty_relevance(r,category)
                        if not relevance:failures['TOPIC_RULE']+=1;continue
                        if excluded_metadata(r,category):failures['ARTICLE_SIGNAL']+=1;continue
                        xml=base.fetch(base.API+pmc+'/fullTextXML',out) if pmc else None
                        if xml:
                            try:checks=inspect_paper(xml,ident,category)
                            except (ValueError,ET.ParseError) as error:failures[str(error)]+=1;continue
                            checks.update(publication_type_facts(checks['article_type'],r,category));checks['fulltext_access_status']='FETCHED_PUBLIC_XML'
                            matched=match_paper_faculty(profile,evidence,xml,r)
                        else:
                            checks=metadata_only_checks(r,category);matched=match_faculty(profile,evidence,api_author_links(r))
                        if matched['status']!='MATCHED':
                            failures[matched['status']]+=1
                            with (out/'unmatched_candidates.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'doi':ident,'pmcid':pmc,'title':r.get('title'),'category':category,'faculty_status':'NOT_VERIFIED','attempted_faculty':profile['faculty_name'],'match_result':matched['status'],'xml_author_affiliation_facts':author_links(xml) if xml else [],'api_author_affiliation_facts':api_author_links(r),'metadata_source_path':searchpath},ensure_ascii=False)+'\n')
                            continue
                        rec={'doi':ident,'pmcid':pmc or None,'title':r.get('title'),'publication_date':r.get('firstPublicationDate'),'category':category,'topic_keyword_hits':relevance,'classification':'AUTOMATIC_RULES_NOT_EXPERT_REVIEW','landing_url':'https://doi.org/'+ident,'metadata_source_path':searchpath,'faculty_evidence_path':rel,'faculty_match':matched,'collected_at':base.now(),**checks}
                        if xml:rec['fulltext_url']=base.API+pmc+'/fullTextXML'
                        rec['faculty_profile']=dict(profile);rec['metadata_source_sha256']=hashlib.sha256(raw).hexdigest()
                        if checks['fulltext_status']=='ARCHIVED_CC_BY_OR_CC0':
                            (out/'fulltext').mkdir(exist_ok=True);rec['fulltext_path']='fulltext/'+pmc+'.xml';rec['fulltext_sha256']=hashlib.sha256(xml).hexdigest();(out/rec['fulltext_path']).write_bytes(xml)
                        rec['author_link_evidence_sha256']=hashlib.sha256(json.dumps(matched['paper_author_match'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                        rec['author_link_evidence_hash_scope']='Extracted author-affiliation facts only; not full text'
                        rec['raw_data_download_status']='NOT_TESTED';rec['reproduction_status']='NOT_TESTED'
                        records.append(rec);seen.add(ident)
                        if pmc:seen_pmc.add(pmc)
                        counts[category]+=1
                        with (out/'checkpoint.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')
                        print(json.dumps({'category':category,'selected':counts[category],'total':len(records),'faculty':profile['faculty_name']},ensure_ascii=False),flush=True)
                        if counts[category]>=a.per_field:break
                    nxt=data.get('nextCursorMark')
                    if counts[category]>=a.per_field or not nxt or nxt==cursor:break
                    cursor=nxt
                if counts[category]>=a.per_field:break
            report.append({'faculty':profile['faculty_name'],'category':category,'raw_hit_max':hits,'rejection_events':dict(failures),'selected_so_far':counts[category]})
            save(records,out)
            (out/'collection_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save(records,out)
    print(json.dumps({'selected':len(records),'counts':{k:counts[k] for k in FIELDS},'target':a.per_field*len(FIELDS)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
