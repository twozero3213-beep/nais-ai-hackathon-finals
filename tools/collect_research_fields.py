"""Public Europe PMC design references; rule-based relevance, not expert validation."""
import argparse
import concurrent.futures
import csv
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

API = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'
OLD = {'10.32614/rj-2022-020','10.1371/journal.pone.0090081','10.1016/j.dss.2009.05.016','10.1145/3025453.3025912','10.1371/journal.pone.0286045','10.1073/pnas.2001283117','10.1371/journal.pone.0149458','10.1371/journal.pone.0259711'}
TECHNICAL = {
 'claim_evidence': [['information extraction','claim extraction','evidence extraction','relation extraction','text mining','natural language processing'], ['scientific','evidence','literature','research articles']],
 'statistics': [['missing data','multiple testing','statistical test','statistical analysis','statistical inference'], ['reproducibility','assumption','bias','imputation','false discovery','replicability']],
 'provenance': [['data provenance','data quality','fair principles','fair data','audit trail'], ['research','scientific','reproducibility','metadata','workflow']],
 'ai_evaluation': [['benchmark','evaluation','hallucination','error detection'], ['large language model','artificial intelligence','language models','generative ai']],
 'research_workflow': [['open science','research workflow','research collaboration','collaborative research','scientific workflow'], ['reproducibility','collaboration','reproducible','research','transparency']],
}
APPLIED = {
 'clinical_treatment': [['randomized trial','randomised trial','clinical trial'], ['treatment','therapy','intervention']],
 'epidemiology': [['epidemiology','population-based','cohort study'], ['public health','incidence','risk factors','mortality']],
 'psychology_behavior': [['psychology','psychological','behavioral','behavioural'], ['experiment','participants','cognitive','mental health']],
 'education_learning': [['education','teaching','learning outcomes'], ['students','classroom','academic achievement','educational intervention']],
 'economics_policy': [['economic','economics','public policy'], ['cost-effectiveness','causal','policy evaluation','difference-in-differences']],
 'ecology_biodiversity': [['biodiversity','ecology','species diversity'], ['ecosystem','conservation','habitat','species richness']],
 'climate_pollution': [['climate change','air pollution','environmental pollution'], ['exposure','temperature','emissions','pollutants']],
 'agriculture_crops': [['agriculture','crop','crops'], ['yield','cultivar','irrigation','fertilizer']],
 'energy_engineering': [['renewable energy','energy efficiency','solar energy','bioenergy'], ['engineering','optimization','efficiency','performance']],
 'exercise_sport': [['exercise','sport','sports'], ['training','physical activity','athletes','performance']],
}
TITLE_GATES = {
 'claim_evidence':['text','language','claim','evidence extraction','entity recognition','coreference','literature','scientific publication','curation'],
 'statistics':['missing','imputation','statistic','multiple test','multiple compar','p-value','false discovery','reproducib','replicab'],
 'provenance':['provenance','data quality','fair','metadata','audit','data management','reproducib'],
 'ai_evaluation':['language model','artificial intelligence','chatgpt','hallucinat','benchmark','generative ai'],
 'research_workflow':['open science','workflow','collaborat','reproducib','research software','research data'],
 'clinical_treatment':['trial','treatment','therapy','therapeutic','intervention'],
 'epidemiology':['cohort','epidemiolog','population','risk','incidence','mortality','prevalence'],
 'psychology_behavior':['psycholog','behavior','behaviour','cognit','mental','depress','anxiety','emotion','personality','attention'],
 'education_learning':['educat','student','learn','teach','classroom','school','academic'],
 'economics_policy':['econom','cost','policy','policies','financial','financing'],
 'ecology_biodiversity':['ecolog','biodivers','species','habitat','ecosystem','conservation'],
 'climate_pollution':['climate','pollution','pollutant','temperature','emission','warming'],
 'agriculture_crops':['agricultur','crop','yield','wheat','maize','rice','cultivar','irrigation','fertiliz'],
 'energy_engineering':['energy','solar','bioenergy','biofuel','photovoltaic','renewable','battery','batteries'],
 'exercise_sport':['exercise','sport','athlet','physical activity','training','fitness'],
}
LOCK = threading.Lock()

# [작성:전문가4] 2026-09-27 case66 무엇/왜: UTC 감사시각; 입출력: 없음→ISO; 검증: timezone 명시.
def now():
    return datetime.now(timezone.utc).isoformat()

# [작성:전문가4] 2026-09-27 case66 무엇/왜: append 감사로그; 입출력: 경로/객체→JSONL; 검증: lock 동시쓰기 보호.
def append(path, obj):
    with LOCK, path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 공개 API bounded 재시도; 입출력: URL→bytes; 검증: HTTP 상태와 오류 기록.
def fetch(url, out):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'NAIS-PublicResearch/1.0'}), timeout=45) as r:
                data = r.read()
                append(out/'requests.jsonl', {'time':now(),'url':url,'status':r.status,'attempt':attempt+1,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
                if r.status != 200:
                    raise ValueError('HTTP status is not 200')
                return data
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            append(out/'errors.jsonl', {'time':now(),'url':url,'attempt':attempt+1,'error':str(e)})
            if isinstance(e, urllib.error.HTTPError) and e.code in (400,401,403,404):
                break
            if attempt < 2:
                time.sleep(attempt+1)
    return None

# [작성:전문가4] 2026-09-27 case66 무엇/왜: DOI 정규화; 입출력: 문자열→소문자 DOI; 검증: URL 접두 제거.
def doi(value):
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', str(value or '').strip(), flags=re.I).lower()

# [작성:전문가4] 2026-09-27 case66 무엇/왜: XML 분리 텍스트; 입출력: 노드→문자열; 검증: xref 인용번호 제외.
def clean(node):
    if node is None:
        return ''
    parts = [node.text or '']
    for child in node:
        if child.tag.split('}')[-1] != 'xref':
            parts.append(clean(child))
        parts.append(child.tail or '')
    return re.sub(r'\s+', ' ', ' '.join(parts)).strip()

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 주제 근거 2그룹 검증; 입출력: 메타데이터/키워드→히트; 검증: title+abstract 한정.
def relevance(record, groups):
    text = re.sub('<[^>]+>', ' ', record.get('title','')+' '+record.get('abstractText','')).lower()
    title = record.get('title','').lower()
    if groups in APPLIED.values() and re.search(r'\b(?:study protocol|trial protocol|protocol for|protocol of)\b',title):
        return None
    for category,terms in {**TECHNICAL,**APPLIED}.items():
        if groups == terms and not any(word in title for word in TITLE_GATES[category]):
            return None
    if groups == TECHNICAL['claim_evidence'] and not any(word in text for word in ['text','language','literature','publication','entity recognition','claim extraction']):
        return None
    if groups == TECHNICAL['claim_evidence']:
        if any(word in title for word in ['bibliometric','research trends','optical chemical','chemical structure identification']):
            return None
        if any(word in title for word in ['computer vision','optical']) and not any(word in title for word in ['scientific','biomedical literature','bar chart','meta-analysis','figure']):
            return None
        if any(word in title for word in ['social media','twitter']) and not any(word in title for word in ['extract','entity','claim','evidence','retrieval']):
            return None
        focused=any(word in title for word in ['extract','entity','coreference','relation','text mining','claim','evidence','retrieval','semantic','curation'])
        if not focused and not ('natural language processing' in title and any(word in text for word in ['information extraction','evidence extraction','claim extraction'])):
            return None
    if groups == TECHNICAL['ai_evaluation']:
        if not any(word in title for word in ['evaluat','benchmark','validat','reliab','accura','error','hallucinat','performance','assess','quality','safety','consort-ai','spirit-ai']):
            return None
    if groups == APPLIED['psychology_behavior'] and any(word in title for word in ['genome','genetic','genomic','methylation']):
        return None
    hits = [[word for word in group if word in text] for group in groups]
    return hits if all(hits) and len(set(sum(hits, []))) >= 2 else None

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 라이선스/DOI/자료선언 검증; 입출력: XML/DOI→근거; 검증: front article-meta와 DAS만.
def parse_xml(data, expected):
    root = ET.fromstring(data)
    if not clean(root.find('body')):
        raise ValueError('Missing or empty article body')
    meta = root.find('./front/article-meta')
    if meta is None:
        raise ValueError('Missing article-meta')
    ids = [doi(n.text) for n in meta.findall('article-id') if n.get('pub-id-type') == 'doi']
    if expected not in ids:
        raise ValueError('Article DOI mismatch')
    atype = root.get('article-type','')
    if atype in {'correction','editorial','retraction','expression-of-concern','protocol'}:
        raise ValueError('Excluded publication type: '+atype)
    if atype not in {'research-article','review-article'}:
        raise ValueError('Not a research/review article: '+atype)
    licenses = []
    for n in meta.findall('./permissions/license'):
        content = ET.tostring(n, encoding='unicode')
        if re.search(r'creativecommons\.org/(?:licenses/by/|publicdomain/zero/)', content, re.I):
            licenses.append({'text':clean(n),'xml':content,'label':'CC0' if 'publicdomain/zero/' in content.lower() else 'CC BY'})
    if not licenses:
        raise ValueError('No explicit CC BY/CC0 article license URL')
    statements = []
    for n in root.iter():
        tag = n.tag.split('}')[-1]
        if tag not in {'sec','custom-meta','notes'}:
            continue
        heading = clean(n.find('title'))+' '+clean(n.find('meta-name'))+' '+n.get('sec-type','')
        if re.search(r'data.?availab|availability of data|data sharing|data-access', heading, re.I):
            statements.append(n)
    links = set()
    statement_text = []
    for n in statements:
        text = clean(n)
        statement_text.append(text)
        for el in n.iter('ext-link'):
            href = el.get('{http://www.w3.org/1999/xlink}href')
            if href:
                links.add(href.strip())
        links.update(x.rstrip('.,;') for x in re.findall(r'''https?://[^\s<>\]\)"']+''', text))
        links.update('https://doi.org/'+x.rstrip('.,;') for x in re.findall(r'''(?<![\w/])10\.\d{4,9}/[^\s<>\]\)"']+''',text))
    valid=set(); malformed=set()
    for link in links:
        try:
            parsed=urllib.parse.urlsplit(link)
            ok=parsed.scheme in {'http','https'} and bool(parsed.hostname) and not any(ch.isspace() for ch in link) and len(re.findall(r'https?://',link))==1
        except ValueError:
            ok=False
        (valid if ok else malformed).add(link)
    return {'article_type':atype,'license':licenses[0]['label'],'license_evidence':licenses[0], 'data_availability_statements':list(dict.fromkeys(statement_text)), 'declared_data_links':sorted(valid), 'malformed_declared_links':sorted(malformed), 'data_link_status':'DECLARED' if valid else 'NOT_IDENTIFIED', 'data_link_extraction':'DAS-only; ext-link href preferred; bare DOI normalized to https://doi.org/; resource_type UNVERIFIED (may link to articles rather than datasets); no repository HTTP verification'}

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 외부 목록 DOI 제외; 입출력: JSON 경로들→집합; 검증: 중첩 객체 재귀.
def exclusions(paths, field='doi'):
    found = set(OLD) if field=='doi' else set()
    stack = []
    for path in paths:
        stack.append(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if field in item:
                found.add(doi(item[field]) if field=='doi' else item[field])
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 본문 검증/저장; 입출력: 후보→검증레코드; 검증: hash·DOI·license 실패 제외.
def accept(candidate, field, hits, query, out):
    ident = candidate.get('pmcid')
    if not ident or not re.fullmatch(r'PMC\d+', ident):
        return None
    url = API+ident+'/fullTextXML'
    data = fetch(url, out)
    if data is None:
        return None
    try:
        evidence = parse_xml(data, doi(candidate.get('doi')))
        if field in APPLIED and evidence['article_type'] != 'research-article':
            raise ValueError('Applied profile requires research-article XML type')
    except (ValueError, ET.ParseError) as e:
        append(out/'rejected.jsonl', {'doi':candidate.get('doi'),'pmcid':ident,'reason':str(e)})
        return None
    path = Path('fulltext')/(ident+'.xml')
    (out/path).write_bytes(data)
    return dict(evidence, doi=doi(candidate['doi']), title=candidate['title'], abstract=candidate.get('abstractText',''), pmcid=ident, category=field, publication_date=candidate.get('firstPublicationDate',''), authors=candidate.get('authorString',''), journal=candidate.get('journalInfo',{}).get('journal',{}).get('title',''), fulltext_url=url, fulltext_http_status=200, fulltext_path=path.as_posix(), fulltext_sha256=hashlib.sha256(data).hexdigest(), collected_at=now(), query=query, topic_keyword_hits=hits, topic_title_hits=[w for w in TITLE_GATES.get(field,[]) if w in candidate['title'].lower()], design_reference_role='설계배경/보고지침' if any(w in candidate['title'].lower() for w in ['consort-ai','spirit-ai']) else ('간접 설계참고/리뷰' if evidence['article_type']=='review-article' else '연구 설계참고'), topic_relevance='규칙 자동분류: 제목·초록에서 두 키워드 그룹을 모두 충족; 분야 제목 앵커 추가 검사. 연구자 확인은 미실시.', raw_data_download_status='NOT_TESTED', reproduction_status='NOT_TESTED', repository_http_status='NOT_TESTED')

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 추적가능한 분야 쿼리 3개; 입출력: 키워드→검색문; 검증: 날짜/공개본문 필터.
def queries(groups):
    left, right = groups
    for subset,begin,sort in ((left,'2024-01-01','sort_date:y'),(left[:2],'2015-01-01','sort_cited:y'),(left,'2015-01-01','sort_cited:y')):
        a = ' OR '.join('TITLE_ABS:"'+w+'"' for w in subset)
        b = ' OR '.join('TITLE_ABS:"'+w+'"' for w in right)
        yield f'({a}) AND ({b}) AND OPEN_ACCESS:Y AND IN_PMC:Y AND FIRST_PDATE:[{begin} TO 2026-09-27] {sort}'

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 최종 3형식 목록; 입출력: 레코드→JSON/CSV/MD; 검증: JSON과 동일 레코드 사용.
def save(records, out, profile):
    (out/'papers.json').write_text(json.dumps({'profile':profile,'generated_at':now(),'classification':'RULE_BASED_NOT_RESEARCHER_VERIFIED','papers':records}, ensure_ascii=False, indent=2), encoding='utf-8')
    columns=['category','title','doi','pmcid','publication_date','article_type','license','data_link_status','raw_data_download_status','reproduction_status','fulltext_path','fulltext_sha256']
    with (out/'papers.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore'); writer.writeheader(); writer.writerows(records)
    lines=['# NAIS 공개 연구 참고문헌','', '규칙 자동분류이며 연구자 확인을 뜻하지 않습니다. 공개 본문 HTTP 200·DOI·CC BY/CC0를 검증했습니다. 자료 링크는 DAS에 선언된 문자열이며 저장소 접속·원자료 다운로드·분석 재현은 NOT_TESTED입니다.','', '| 분야 | 논문 | DOI | 라이선스 | 자료 링크 |','|---|---|---|---|---|']
    lines.extend('| '+r['category']+' | '+r['title'].replace('|','/')+' | https://doi.org/'+r['doi']+' | '+r['license']+' | '+r['data_link_status']+' |' for r in records)
    (out/'papers.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 오프라인 재검증; 입출력: 목록→검사결과; 검증: 요청 분야별 개수·제외 DOI/PMCID·hash·license·미시험상태.
def verify(records, out, fields, per_field, excluded, excluded_pmc=()):
    errors=[]
    if Counter(r['category'] for r in records) != Counter({k:per_field for k in fields}):
        errors.append('category counts do not match target')
    identifiers=[r['doi'] for r in records]
    if len(identifiers)!=len(set(identifiers)) or set(identifiers)&excluded:
        errors.append('duplicate or excluded DOI')
    pmcs=[r['pmcid'] for r in records]
    if len(pmcs)!=len(set(pmcs)) or set(pmcs)&set(excluded_pmc):
        errors.append('duplicate or excluded PMCID')
    for r in records:
        try:
            if Path(r['fulltext_path']).is_absolute() or '..' in Path(r['fulltext_path']).parts:
                raise ValueError('Fulltext path must stay relative to output directory')
            raw=(out/r['fulltext_path']).read_bytes()
            ev=parse_xml(raw,r['doi'])
            checks=[hashlib.sha256(raw).hexdigest()==r['fulltext_sha256'],ev['license']==r['license'],r['fulltext_http_status']==200, bool(relevance({'title':r['title'],'abstractText':r['abstract']},fields[r['category']])),all(r[k]=='NOT_TESTED' for k in ['raw_data_download_status','reproduction_status','repository_http_status']),'2015-01-01' <= r['publication_date'] <= '2026-09-27',ev['declared_data_links']==r['declared_data_links'],ev['data_link_status']==r['data_link_status']]
            if r['category'] in APPLIED:
                checks.append(ev['article_type']=='research-article')
            checks.append(ev['article_type']==r['article_type'])
            if not all(checks):
                raise ValueError('Metadata/hash/date/relevance/data-link/status verification failed')
        except (AssertionError, ValueError, OSError, ET.ParseError) as e:
            errors.append(r['doi']+': '+str(e))
    result={'verified_at':now(),'count':len(records),'category_counts':dict(Counter(r['category'] for r in records)),'errors':errors,'passed':not errors}
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return not errors

# [작성:전문가4] 2026-09-27 case66 무엇/왜: 재개가능 CLI 수집; 입출력: 프로필/출력/제외 목록→검증된 목록; 검증: 공식 fields 확인·최대2 workers.
def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True); p.add_argument('--profile',choices=['technical','applied'],default='technical'); p.add_argument('--per-field',type=int); p.add_argument('--exclude-json',action='append',default=[]); p.add_argument('--verify-only',action='store_true'); a=p.parse_args()
    out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    fields=TECHNICAL if a.profile=='technical' else APPLIED
    target=a.per_field or (50 if a.profile=='technical' else 30)
    if a.per_field is not None and a.per_field <= 0:
        p.error('--per-field must be positive')
    excluded=exclusions(a.exclude_json)
    excluded_pmc=exclusions(a.exclude_json,'pmcid')
    if a.verify_only:
        records=json.loads((out/'papers.json').read_text(encoding='utf-8'))['papers']
        return 0 if verify(records,out,fields,target,excluded,excluded_pmc) else 1
    for folder in ['fulltext','raw_search']:
        (out/folder).mkdir(exist_ok=True)
    checkpoint=out/'checkpoint.jsonl'
    records=[]; seen=set(excluded); seen_pmc=set(excluded_pmc)
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            if r['doi'] not in seen and r['pmcid'] not in seen_pmc and r['category'] in fields and sum(x['category']==r['category'] for x in records)<target:
                try:
                    r.update(parse_xml((out/r['fulltext_path']).read_bytes(),r['doi']))
                    if not relevance({'title':r['title'],'abstractText':r['abstract']},fields[r['category']]):
                        raise ValueError('Current topic relevance gate failed')
                    if a.profile=='applied' and r['article_type']!='research-article':
                        raise ValueError('Applied profile requires research-article')
                    r['topic_title_hits']=[w for w in TITLE_GATES.get(r['category'],[]) if w in r['title'].lower()]
                    r['design_reference_role']='설계배경/보고지침' if any(w in r['title'].lower() for w in ['consort-ai','spirit-ai']) else ('간접 설계참고/리뷰' if r['article_type']=='review-article' else '연구 설계참고')
                    r['topic_relevance']='규칙 자동분류: 제목·초록 두 그룹 AND; technical 제목 방법론 키워드 추가 검사. 연구자 확인 미실시.'
                except (ValueError,OSError,ET.ParseError) as e:
                    append(out/'rejected.jsonl',{'doi':r['doi'],'reason':'Resume validation: '+str(e)})
                    continue
                records.append(r); seen.add(r['doi']); seen_pmc.add(r['pmcid'])
    field_doc=fetch(API+'fields?format=json',out)
    if field_doc is None or b'TITLE_ABS' not in field_doc:
        raise RuntimeError('Official fields API did not confirm TITLE_ABS')
    (out/'raw_search'/'official_fields.json').write_bytes(field_doc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for field,groups in fields.items():
            count=sum(r['category']==field for r in records)
            attempted=set()
            for qi,query in enumerate(queries(groups)):
                if count>=target: break
                cursor='*'
                for page in range(4):
                    if count>=target: break
                    url=API+'search?'+urllib.parse.urlencode({'query':query,'format':'json','resultType':'core','pageSize':100,'cursorMark':cursor})
                    raw=fetch(url,out)
                    if raw is None: break
                    (out/'raw_search'/f'{field}_{qi}_{page}_{run_id}.json').write_bytes(raw)
                    payload=json.loads(raw); candidates=[]
                    for c in payload.get('resultList',{}).get('result',[]):
                        d=doi(c.get('doi')); hits=relevance(c,groups)
                        types=' '.join(c.get('pubTypeList',{}).get('pubType',[])).lower()
                        if a.profile=='applied' and 'review' in types:
                            continue
                        correction=json.dumps(c.get('commentCorrectionList',{})).lower()
                        if re.search(r'\bretract(?:ed|ion|ionof|ionin)?\b',c.get('title','').lower()+' '+correction):
                            append(out/'rejected.jsonl',{'doi':d,'reason':'retraction metadata/title signal','signal':correction,'title':c.get('title','')})
                            continue
                        if not d or d in seen or d in attempted or c.get('pmcid') in seen_pmc or not hits or any(x in types for x in ['editorial','correction','retracted','protocol']): continue
                        if not ('2015-01-01'<=c.get('firstPublicationDate','')<='2026-09-27'): continue
                        candidates.append((c,hits)); attempted.add(d)
                    for start in range(0,len(candidates),2):
                        if count>=target: break
                        futures=[pool.submit(accept,c,field,hits,query,out) for c,hits in candidates[start:start+2]]
                        for future in futures:
                            r=future.result()
                            if r and count<target:
                                if r['pmcid'] in seen_pmc: continue
                                records.append(r); seen.add(r['doi']); seen_pmc.add(r['pmcid']); append(checkpoint,r); count+=1
                                print(f'{field}: {count}/{target} {r["doi"]}',flush=True)
                    nxt=payload.get('nextCursorMark')
                    if not nxt or nxt==cursor: break
                    cursor=nxt
            print(f'FIELD_COMPLETE {field} {count}/{target}',flush=True)
    excluded=exclusions(a.exclude_json)
    excluded_pmc=exclusions(a.exclude_json,'pmcid')
    records=[r for r in records if r['doi'] not in excluded and r['pmcid'] not in excluded_pmc]
    save(records,out,a.profile)
    return 0 if verify(records,out,fields,target,excluded,excluded_pmc) else 1

if __name__=='__main__':
    raise SystemExit(main())
