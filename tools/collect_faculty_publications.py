"""[전문가4] 2026-09-27 case67: 공식 교수 출판목록과 Crossref의 서지만 연결한다."""
import argparse
import collections
import csv
import hashlib
import html
from html.parser import HTMLParser
import json
import re
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import collect_faculty_base as base
from probe_faculty import FIELDS, compact, match_faculty
NEXT_CROSSREF_REQUEST = 0.0


# [전문가4] 2026-09-27 case67: Crossref 429의 Retry-After와 최소 간격을 지키고404를 DOI부재로 단정하지 않는다.
def crossref_fetch(url, out):
    global NEXT_CROSSREF_REQUEST
    for attempt in range(3):
        time.sleep(max(0, NEXT_CROSSREF_REQUEST - time.monotonic()))
        NEXT_CROSSREF_REQUEST = time.monotonic() + 0.5
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'NAIS-Bibliography/1.0'}), timeout=45) as response:
                raw = response.read()
                base.append(out / 'requests.jsonl', {'time': base.now(), 'url': url, 'status': response.status, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
                return raw
        except urllib.error.HTTPError as error:
            retry = error.headers.get('Retry-After', '')
            base.append(out / 'errors.jsonl', {'time': base.now(), 'url': url, 'status': error.code, 'retry_after': retry, 'attempt': attempt + 1})
            if error.code == 404:
                failure = out / 'evidence' / (hashlib.sha256(url.encode()).hexdigest() + '.failure.json')
                failure.parent.mkdir(exist_ok=True)
                failure.write_text(json.dumps({'url': url, 'status': 404, 'checked_at': base.now(), 'meaning': 'Crossref metadata unavailable; DOI may belong to another registration agency'}), encoding='utf-8')
                raise ValueError('CROSSREF_METADATA_UNAVAILABLE_404_NOT_DOI_ABSENCE') from error
            if error.code == 429:
                try: delay = float(retry)
                except ValueError:
                    try: delay = max(0, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError): delay = 60 * (2 ** attempt)
                NEXT_CROSSREF_REQUEST = time.monotonic() + max(delay, 1)
                print(json.dumps({'status': 'CROSSREF_RATE_LIMIT_WAIT', 'seconds': max(delay, 1)}), flush=True)
                continue
            if error.code in {400, 401, 403}: break
            NEXT_CROSSREF_REQUEST = time.monotonic() + 2 ** attempt
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            base.append(out / 'errors.jsonl', {'time': base.now(), 'url': url, 'error': str(error), 'attempt': attempt + 1})
            NEXT_CROSSREF_REQUEST = time.monotonic() + 2 ** attempt
    raise ValueError('Crossref fetch deferred or failed')


# [전문가4] 2026-09-27 case67: DOI 공식 content negotiation으로 타 등록기관 CSL 서지를 원형 보존한다.
def doi_csl_evidence(ident, out):
    url = 'https://doi.org/' + ident
    key = hashlib.sha256((url + '\nAccept: application/vnd.citationstyles.csl+json').encode()).hexdigest()
    record = out / 'evidence' / (key + '.json')
    if record.exists():
        fact = json.loads(record.read_text(encoding='utf-8')); raw = (out / fact['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != fact['sha256']: raise ValueError('Cached CSL evidence changed')
        return raw, fact
    request = urllib.request.Request(url, headers={'User-Agent': 'NAIS-Bibliography/1.0', 'Accept': 'application/vnd.citationstyles.csl+json'})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if 'json' not in response.headers.get('Content-Type', '').lower(): raise ValueError('DOI resolver did not return CSL metadata; body not read')
            raw = response.read(); data = json.loads(raw)
            if base.doi(data.get('DOI')) != ident: raise ValueError('DOI CSL identifier mismatch')
            fact = {'url': url, 'final_url': response.url, 'format': 'CSL_JSON', 'path': 'evidence/' + key + '.txt', 'sha256': hashlib.sha256(raw).hexdigest(), 'collected_at': base.now()}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise ValueError('DOI CSL metadata unavailable: ' + str(error)) from error
    record.parent.mkdir(exist_ok=True); (out / fact['path']).write_bytes(raw)
    record.write_text(json.dumps(fact, ensure_ascii=False, indent=2), encoding='utf-8')
    base.append(out / 'requests.jsonl', dict(fact, status=200, bytes=len(raw)))
    return raw, fact


# [전문가4] 2026-09-27 case67: 원형 JSON은 그대로 두고 표준 CSL 필드만 기존 검증 입력으로 대응한다.
def metadata_works(raw):
    data = json.loads(raw)
    if 'message' in data:
        message = data['message']
        return message.get('items', []) if 'items' in message else [message]
    kind = {'article-journal': 'journal-article', 'paper-conference': 'proceedings-article'}.get(data.get('type'), data.get('type'))
    title = data.get('title', '')
    return [dict(data, title=[title] if isinstance(title, str) else title, type=kind)]


# [전문가4] 2026-09-27 case67: ACL 공식 HTML의 citation 메타와 초록만 읽고 PDF는 요청하지 않는다.
class ACLMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = collections.defaultdict(list); self.abstract = []; self.depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name', '').startswith('citation_'):
            self.meta[attrs['name']].append(attrs.get('content', ''))
        if tag == 'div' and (self.depth or 'acl-abstract' in attrs.get('class', '').split()):
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == 'div' and self.depth: self.depth -= 1

    def handle_data(self, data):
        if self.depth: self.abstract.append(data)


# [전문가4] 2026-09-27 case67: 초록 보완 전에 ACL DOI·정확 제목·교수 저자를 다시 확인한다.
def supplement_acl(work, raw, profile):
    parser = ACLMetadata(); parser.feed(raw.decode('utf-8', errors='replace'))
    if base.doi(work['DOI']) not in {base.doi(value) for value in parser.meta['citation_doi']}:
        raise ValueError('ACL DOI mismatch')
    if title_key((work.get('title') or [''])[0]) not in {title_key(value) for value in parser.meta['citation_title']}:
        raise ValueError('ACL title mismatch')
    if compact(profile['faculty_name']) not in {compact(value) for value in parser.meta['citation_author']}:
        raise ValueError('ACL full-name author mismatch')
    abstract = visible(' '.join(parser.abstract))
    if not abstract: raise ValueError('ACL abstract unavailable')
    return dict(work, abstract=abstract)


# [전문가4] 2026-09-27 case67: HTML 표기만 제거하며 이름 이니셜을 확장하지 않는다.
def visible(raw):
    value = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
    value = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', value, flags=re.I | re.S)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value))).strip()


# [전문가4] 2026-09-27 case67: 표기 차이만 정규화하여 공식 목록의 정확 제목 포함을 검사한다.
def title_key(value):
    # [전문가4] 2026-09-27 case67: 국문 서지의 띄어쓰기 차이만 정규화하며 글자는 보존한다.
    return re.sub(r'(?<=[가-힣]) (?=[가-힣])', '', ' '.join(re.findall(r'\w+', visible(value).casefold())))


# [전문가4] 2026-09-27 case67: PMC/서지 어댑터가 같은 추출 구성요소 범위를 재사용한다.
def extraction_component_terms(title):
    return [term for term in ['entity recognition', 'entity linking', 'relation extraction', 'coreference', 'document extraction', 'document information extraction', 'extractive question answering'] if term in title.lower()]


# [전문가4] 2026-09-27 case67: 모델 능력 측정·사실지식 probing을 평가 참고로 분리한다.
def ai_evaluation_terms(title, abstract=''):
    title = visible(title).lower(); context = title + ' ' + visible(abstract).lower()
    model = any(x in title for x in ['language model', 'llm', 'artificial intelligence'])
    terms = [x for x in ['measuring', 'measurement', 'evaluating', 'evaluation', 'benchmark', 'factual probing'] if x in title]
    if model and terms: return terms
    if model and 'knowledge bases' in title and any(x in context for x in ['probing', 'probe', 'evaluate']): return ['factual knowledge probing']
    return []


# [전문가4] 2026-09-27 case67: 문서 주장 근거 검증의 방법 참고; 하드웨어 검증 일반은 포함하지 않는다.
def claim_verification_terms(title, abstract=''):
    title = visible(title).lower()
    return [term for term in ['fact verification', 'fact checking', 'fact-checking', 'factual consistency', 'claim verification', 'claim-evidence', 'claim evidence', 'document evidence', 'comparing and contrasting claims'] if term in title]


# [전문가4] 2026-09-27 case67: 학교·대학 맥락의 교육정책·성과·훈련 직접 연구만 보완한다.
def education_research_terms(title, abstract=''):
    title = visible(title).lower(); context = title + ' ' + visible(abstract).lower()
    if any(term in title for term in ['machine learning', 'deep learning', 'reinforcement learning']): return []
    setting = re.search(r'\b(?:school|schools|teacher|teachers|student|students|university|universities|higher education|doctoral|postdoctoral|academic)\b|학교|대학|교사|학생|고등교육', title)
    if not setting: return []
    return [term for term in ['education', 'learning', 'achievement', 'curriculum', 'governance', 'autonomy', 'tuition', 'school resources', 'school boards', 'satisfaction', 'training', 'academic adjustment', '교육', '학습', '성취', '교육과정', '등록금'] if term in context]


# [전문가4] 2026-09-27 case67: 생물군집·서식지·종기록의 직접 생태 연구; 일반 화학/온라인 군집 제외.
def ecology_research_terms(title, abstract=''):
    title = visible(title).lower()
    if re.search(r'\b(?:online|social network|software|chemical synthesis|catalyst)\b', title): return []
    taxa = ['benthic', 'benthos', 'benthic diatom', 'macrofaun', 'polychaete', 'ascidian', 'microphytobenth', 'halophyte', 'microalgal', 'coral', 'marine bivalve', 'diatom assemblage']
    habitat = ['tidal', 'marine', 'estuary', 'estuar', 'fjord', 'habitat', 'saltmarsh', 'mangrove', 'marshes', 'seas', 'coral reef', 'saltern']
    if any(term in title for term in taxa) and any(term in title for term in ['community', 'communities', 'assemblage', 'diversity']): return [term for term in taxa if term in title]
    if any(term in title for term in taxa) and any(term in title for term in habitat): return [term for term in taxa if term in title]
    if 'taxa' in title and 'new records' in title: return ['taxonomic species records']
    return []


# [전문가4] 2026-09-27 case67: 노동시장·소득·인적자본 등의 직접 경제 제목을 보완한다.
def economics_research_terms(title, abstract=''):
    title = visible(title).lower()
    return [term for term in ['labor market', 'labour market', 'wage', 'income inequality', 'human capital', 'wealth', 'household inequality', 'employment substitution', 'risk sharing', 'health insurance', 'tax policy', 'economic', 'capital inflow', 'unemployment', 'government spending', 'inflation', 'monetary', 'fiscal policy', 'financial market', 'credit constraints', 'subsidy', '노동시장', '소득불평등', '인적자본'] if term in title]


# [전문가4] 2026-09-27 case67: 대기질·기후의 직접 관측/모형 용어를 보완하고 약물 에어로졸은 제외한다.
def climate_research_terms(title, abstract=''):
    title = visible(title).lower(); context = title + ' ' + visible(abstract).lower()
    direct = [term for term in ['air quality', 'climate model', 'greenhouse gas', 'pm2.5', 'particulate matter', 'wildfire', '대기질', '미세먼지', '기후변화'] if term in title]
    if direct: return direct
    physical = [term for term in ['aerosol', 'ozone', 'no2', 'hcho', 'oh reactivity', 'albedo', 'carbonyl', 'black carbon'] if term in title]
    setting = ['atmospher', 'precipitation', 'emission', 'meteorolog', 'air quality', 'climate', 'seoul metropolitan', 'korus-aq', 'gmap/sijaq', 'arctic']
    return physical if physical and any(term in context for term in setting) else []


# [전문가4] 2026-09-27 case67: 인간 인지·선호·중독 행동을 직접 다루는 서지의 범위 보완.
def psychology_research_terms(title, abstract=''):
    title = visible(title).lower(); context = title + ' ' + visible(abstract).lower()
    if any(term in title for term in ['mice', 'mouse', 'rat model', 'machine learning', 'robot', 'molecular']): return []
    anchors = [term for term in ['memory', 'preference', 'decision', 'cognit', 'behavior', 'behaviour', 'smoking cessation', 'addiction', 'impulsiv', 'psychological', 'gambling'] if term in title]
    human = ['human', 'participants', 'individuals', 'patients', 'smokers', 'moral', 'smoking', 'psychological', 'psychiatric', 'substance', 'addiction', 'gambling']
    return anchors if anchors and any(term in context for term in human) else []


# [전문가4] 2026-09-27 case67: 승인된 통계 방법 범위; software regression/test 및 종양 퇴행과 구분한다.
def statistical_method_terms(title, abstract=''):
    title = visible(title).lower(); context = title + ' ' + visible(abstract).lower()
    if re.search(r'\b(?:software|unit test|integration test|regression testing|test suite|continuous integration)\b', title):
        return []
    terms = re.findall(r'\b(?:statistics|statistical|inference|inferences|resampling|bootstrap|permutation|nonparametric|non-parametric|parametric)\b', title)
    if re.search(r'large[- ]sample tests?|tests? for contingency tables?|contingency[- ]table tests?', title):
        terms.append('statistical test method')
    if 'regression' in title and re.search(r'\b(?:inference|inferences|estimation|statistical|bootstrap|resampling|linear|logistic|quantile|compositional|penalized|least squares|reduced-rank)\b', context):
        terms.append('regression method')
    statistical_context = r'\b(?:probability|density|variance|covariance|gaussian|kurtosis|quantile|asymptotic|bootstrap|mixture|likelihood|hypothesis|contingency|homogeneity|modality|nonparametric|parametric|principal component|stratification)\b'
    if re.search(r'\b(?:test|tests|testing)\b', title) and re.search(statistical_context, title):
        terms.append('statistical test method')
    if re.search(r'\b(?:estimation|distribution|distributions)\b', title) and re.search(statistical_context, context):
        terms.append('statistical estimation/distribution method')
    return sorted(set(terms))


# [전문가4] 2026-09-27 case67: 연구자료 관리·메타데이터의 직접 앵커만 허용하고 일반 개인정보 연구는 구분한다.
def provenance_method_terms(title, abstract=''):
    title = visible(title).lower(); context = title + ' ' + visible(abstract).lower()
    korean = [term for term in ['메타데이터', '연구데이터', '연구 데이터', '데이터 관리 계획', '데이터 생애주기', '데이터 리포지터리', '데이터 저장소'] if term in title]
    english = [term for term in ['metadata', 'research data', 'data provenance', 'data quality', 'data management plan', 'data repository', 'data repositories', 'data life cycle', 'data curation', 'data citation', 'data sharing'] if term in title]
    if not re.search(r'\b(?:research|scientific|scholarly|academic|clinical|repository|repositories)\b', context): english = []
    if 'metadata elements' in title and 'linked data' in title: english.append('linked data metadata elements')
    return korean + english


# [전문가4] 2026-09-27 case67: 연구자료 공유·관리계획·재사용·소프트웨어 인용을 작업흐름으로 구분한다.
def workflow_method_terms(title, abstract=''):
    title = visible(title).lower()
    terms = [term for term in ['research data management', 'research data sharing', 'research data reuse', 'data management plan', 'machine-actionable dmp', 'madmp', 'research software citation', 'software citation', 'open peer review', 'research collaboration', 'scientific workflow', 'scholarly collaboration', '연구데이터 관리', '연구 데이터 관리', '연구데이터 공유', '연구 데이터 공유', '연구데이터의 공유', '연구 데이터의 공유', '데이터 관리 계획', '연구 소프트웨어', '연구데이터 재사용', '공개 동료심사'] if term in title]
    if 'research' in title: terms.extend(term for term in ['data sharing', 'data reuse'] if term in title)
    if 'research software' in title and any(term in title for term in ['sharing', 'reuse', 'citation']): terms.append('research software sharing/reuse/citation')
    # [전문가4] 2026-09-27 case67: 과학·연구데이터 보존/활용은 데이터 수명주기 방법 참고다.
    if any(term in title for term in ['scientific data', 'research data', '과학데이터', '과학 데이터', '연구데이터']) and any(term in title for term in ['preserv', '보존', '활용']): terms.append('research data preservation/use')
    return terms


# [전문가4] 2026-09-27 case67: 수량보다 주제 의미를 우선해 한 논문을 한 분야에 배정한다.
def ordered_categories(profile, work):
    categories = list(profile['candidate_categories'])
    title = visible((work.get('title') or [''])[0]).lower()
    quality = any(term in title for term in ['metadata quality', 'data integrity', 'data provenance', 'metadata schema', 'metadata element', 'metadata design', 'design of metadata', 'schema class', '메타데이터 품질', '메타데이터 요소', '메타데이터 설계', '스키마', '무결성'])
    if 'research_workflow' in categories and workflow_method_terms(title) and not quality:
        categories.remove('research_workflow'); categories.insert(0, 'research_workflow')
    return categories


# [전문가4] 2026-09-27 case67: 공식 출판목록의 실제 문단에서 후보를 생성한다; 정답 DOI 목록을 넣지 않는다.
def publication_units(raw):
    markup = raw.decode('utf-8', errors='replace')
    fragments = re.split(r'</(?:li|p|tr|div)>|<br\s*/?>', markup, flags=re.I)
    units = []
    for fragment in fragments:
        text = visible(fragment)
        if 40 <= len(text) <= 2500 and text not in units:
            units.append(text)
    return units


# [전문가4] 2026-09-27 case67: 공식 목록에 명시된 DOI를 제목검색보다 먼저 단건 대조한다.
def list_doi(value):
    value = urllib.parse.unquote(base.doi(value)).rstrip('.,;')
    while value.endswith(')') and value.count(')') > value.count('('):
        value = value[:-1]
    return value


# [전문가4] 2026-09-27 case67: 목록 끝 인용 괄호는 제거하되 정상 DOI 내부 괄호는 보존한다.
def publication_queries(raw, profile, max_queries):
    markup = html.unescape(raw.decode('utf-8', errors='replace'))
    identifiers = sorted({list_doi(value) for value in re.findall(r'\b10\.\d{4,9}/[^\s<>"\x27]+', markup)})
    # [전문가4] 2026-09-27 case67: 감사 후보 DOI는 검색 힌트뿐이며 공식 목록 정확 제목/저자 검증을 우회하지 않는다.
    identifiers = list(dict.fromkeys([list_doi(value) for value in profile.get('candidate_dois', [])])) or identifiers
    for ident in identifiers:
        yield 'https://api.crossref.org/works/' + urllib.parse.quote(ident, safe=''), visible(raw)
    if profile.get('candidate_dois'): return
    gates = [word for category in profile['candidate_categories'] for word in base.TITLE_GATES[category]]
    units = [unit for unit in publication_units(raw) if any(word in unit.lower() for word in gates) or ('statistics' in profile['candidate_categories'] and statistical_method_terms(unit)) or ('provenance' in profile['candidate_categories'] and provenance_method_terms(unit)) or ('research_workflow' in profile['candidate_categories'] and workflow_method_terms(unit))]
    for unit in (units[:max_queries] if max_queries else units):
        if re.search(r'\b10\.\d{4,9}/', unit) or unit.startswith(('abstract =', 'N2 -', 'AB -', '@article', '@inproceedings')): continue
        yield 'https://api.crossref.org/works?' + urllib.parse.urlencode({'query.bibliographic': unit[:700], 'query.author': profile['faculty_name'], 'rows': 5}), unit


# [전문가4] 2026-09-27 case67: 공식 기관의 단일 논문 페이지에서 명시 Abstract만 결측 보완한다.
def supplement_official_abstract(work, raw, url):
    if work.get('abstract') or not urllib.parse.urlsplit(url).hostname.endswith('.elsevierpure.com') or '/en/publications/' not in url:
        return work
    title = (work.get('title') or [''])[0]
    markup = raw.decode('utf-8', errors='replace')
    identifiers = {list_doi(v) for v in re.findall(r'\b10\.\d{4,9}/[^\s<>"\x27]+', html.unescape(markup))}
    if not title_key(title) or title_key(title) not in title_key(raw) or base.doi(work.get('DOI')) not in identifiers:
        return work
    match = re.search(r'<h2\b[^>]*>\s*Abstract\s*</h2>\s*<div\b[^>]*abstractportal[^>]*>\s*<div\b[^>]*class="textblock"[^>]*>(.*?)</div>', markup, re.I | re.S)
    abstract = visible(match.group(1)) if match else ''
    return dict(work, abstract=abstract, abstract_source_url=url) if abstract else work


# [전문가4] 2026-09-27 case67: 공식 학술색인/학회 citation 태그만 보관하며 논문 본문은 저장하지 않는다.
def citation_evidence(url, out):
    host = urllib.parse.urlsplit(url).hostname
    if host not in {'www.kci.go.kr', 'journal.kci.go.kr', 'www.accesson.kr', 'accesson.kr', 'ijkcdt.net', 'www.ijkcdt.net', 'oak.go.kr'}:
        raise ValueError('Unsupported official citation metadata host')
    key = hashlib.sha256(('citation:' + url).encode()).hexdigest()
    receipt = out / 'evidence' / (key + '.json')
    if receipt.exists():
        fact = json.loads(receipt.read_text(encoding='utf-8')); raw = (out / fact['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != fact['sha256']: raise ValueError('Citation fragment hash mismatch')
        return raw, fact
    request = urllib.request.Request(url, headers={'User-Agent': 'NAIS bibliography evidence collector'})
    with urllib.request.urlopen(request, timeout=30) as response: raw = response.read()
    markup = raw.decode('utf-8', errors='replace')
    tags = re.findall(r'<meta\b[^>]*>|<title\b[^>]*>.*?</title>', markup, re.I | re.S)
    # [전문가4] 2026-09-27 case67: OAK의 별도 한영 논문 제목 블록만 추가 보존한다.
    if host == 'oak.go.kr':
        heading = re.search(r'<div class="oadetailtit">([^<]+)', markup)
        if heading: tags.append('<div class="oadetailtit">' + heading.group(1) + '</div>')
    fragment = ('<head>\n' + '\n'.join(tags) + '\n</head>').encode('utf-8')
    relative = 'evidence/' + key + '.html'
    (out / relative).write_bytes(fragment)
    fact = {'url': url, 'path': relative, 'sha256': hashlib.sha256(fragment).hexdigest(), 'raw_response_sha256': hashlib.sha256(raw).hexdigest(), 'collected_at': base.now(), 'retained_scope': 'CITATION_META_TAGS_AND_TITLE_ONLY_NO_ARTICLE_BODY'}
    receipt.write_text(json.dumps(fact, ensure_ascii=False, indent=2), encoding='utf-8')
    return fragment, fact


# [전문가4] 2026-09-27 case67: 같은 DOI·영문제목의 메타태그에서 국문제목과 누락 실명만 보완한다.
def supplement_citation(work, raw, profile, publications_raw):
    parser = ACLMetadata(); parser.feed(raw.decode('utf-8'))
    if base.doi(work.get('DOI')) not in {base.doi(x) for x in parser.meta['citation_doi']}: raise ValueError('Citation DOI mismatch')
    primary = (work.get('title') or [''])[0]
    oak_heading = re.search(r'<div class="oadetailtit">([^<]+)', raw.decode('utf-8'))
    alternatives = parser.meta['citation_title'] + [visible(x) for x in re.findall(r'<title[^>]*>(.*?)</title>', raw.decode('utf-8'), re.I | re.S)]
    for title in list(alternatives):
        # [전문가4] 2026-09-27 case67: 번역 제목 안 DAF(...) 같은 정상 중첩 괄호를 보존한다.
        depth = 0
        if title.endswith(')'):
            for index in range(len(title) - 1, -1, -1):
                depth += (title[index] == ')') - (title[index] == '(')
                if depth == 0:
                    first, second = title[:index].strip(), title[index + 1:-1].strip()
                    if bool(re.search('[가-힣]', first)) != bool(re.search('[가-힣]', second)): alternatives.extend([first, second])
                    break
    if oak_heading:
        bilingual = visible(oak_heading.group(1))
        for english in parser.meta['citation_title']:
            if bilingual.startswith(english) and re.search('[가-힣]', bilingual[len(english):]): alternatives.append(bilingual[len(english):].strip())
    if title_key(primary) not in {title_key(x) for x in alternatives}: raise ValueError('Citation metadata title mismatch')
    matching = next((x for x in alternatives if title_key(x) and title_key(x) in title_key(publications_raw)), None)
    result = dict(work, publisher_titles=alternatives)
    result['publisher_keywords'] = parser.meta['citation_keywords']
    if not result.get('abstract') and parser.meta['citation_abstract']: result['abstract'] = parser.meta['citation_abstract'][0]
    if matching: result['title'] = [matching]
    if any(not (a.get('given') or a.get('family')) for a in work.get('author', [])):
        authors = []
        for name in parser.meta['citation_author']:
            name = re.sub(r'\([^()]*\)', '', name).strip()
            pieces = name.replace(',', ' ').split()
            if not pieces: continue
            if pieces[0].casefold() == profile['faculty_name'].split()[-1].casefold(): authors.append({'given': ' '.join(pieces[1:]), 'family': pieces[0]})
            else: authors.append({'given': ' '.join(pieces[:-1]), 'family': pieces[-1]})
        # [전문가4] 2026-09-27 case67: 확인된 교수 한영 이름의 중복 citation 태그는 한 번만 센다.
        aliases = {compact(profile['faculty_name']), compact(' '.join(profile['faculty_name'].split()[-1:] + profile['faculty_name'].split()[:-1]))}
        if profile.get('faculty_name_local'): aliases.add(compact(profile['faculty_name_local']))
        unique = []; faculty_seen = False
        for author in authors:
            is_faculty = bool(aliases & {compact(author['given'] + author['family']), compact(author['family'] + author['given'])})
            if is_faculty and faculty_seen: continue
            faculty_seen = faculty_seen or is_faculty
            unique.append(author)
        result['author'] = unique
    return result


# [전문가4] 2026-09-27 case67: 교수 공식 도메인에 있는 출판목록만 자동 수집한다.
def official_publications(profile, profile_raw=None, publications_raw=None):
    url = profile['publications_url']
    parsed = urllib.parse.urlsplit(url)
    domain = profile['official_domain'].lower()
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname: raise ValueError('Invalid publication URL')
    if not (parsed.hostname == domain or parsed.hostname.endswith('.' + domain)):
        if profile.get('publication_list_basis') == 'FACULTY_PERSONAL_LIST_CORROBORATED_BY_OFFICIAL_PROFILE':
            quote = profile.get('publication_identity_quote', '')
            if publications_raw is not None:
                name_quotes = [compact(quote), compact(re.sub(r'\([^)]*\)', '', quote))]
                if not quote or quote not in visible(publications_raw) or not any(compact(profile['faculty_name']) in form for form in name_quotes) or compact(profile['faculty_affiliation']) not in compact(quote):
                    raise ValueError('Personal list lacks exact full-name and institution corroboration')
                if profile.get('faculty_name_local') and compact(profile['faculty_name_local']) not in compact(quote):
                    raise ValueError('Personal list local-name alias not corroborated')
            return url
        # [전문가4] 2026-09-27 case67: 감사로 확인된 별도 대학 기관 저장소 호스트만 정확히 허용한다.
        if parsed.hostname == profile.get('official_publication_domain') and parsed.hostname.endswith('.elsevierpure.com'):
            return url
        links = [] if profile_raw is None else re.findall(r'<a\b[^>]*href=["\x27]([^"\x27]+)', profile_raw.decode('utf-8', errors='replace'), re.I)
        links = [urllib.parse.urljoin(profile['faculty_evidence_url'], html.unescape(link)).rstrip('/') for link in links]
        if url.rstrip('/') not in links:
            raise ValueError('Publication list is outside verified official domain and not linked by official profile')
    return url


# [전문가4] 2026-09-27 case67: 한국어 공식 이름·직함과 개인 저작목록 영문명을 분리해 보존한다.
def faculty_profile_check(profile, raw):
    original = raw
    # [전문가4] 2026-09-27 case67: 공식 교수 편람 PDF의 명시 페이지를 추출하고 원본 해시를 유지한다.
    pdf_pages = profile.get('faculty_evidence_pdf_pages')
    if pdf_pages:
        if not raw.startswith(b'%PDF-') or not all(isinstance(n, int) and n >= 1 for n in pdf_pages):
            raise ValueError('Invalid official PDF profile/pages')
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(raw))
        raw = '\n'.join(reader.pages[n - 1].extract_text() for n in pdf_pages).encode('utf-8')
    local_route = profile.get('faculty_identity_route') == 'LOCAL_NAME_OWN_PUBLICATION_LIST'
    check_profile = dict(profile)
    quoted_name = profile.get('faculty_quoted_name')
    if quoted_name:
        if compact(re.sub(r'\([^)]*\)', '', quoted_name)) != compact(profile['faculty_name']):
            raise ValueError('Quoted faculty name is not a parenthetical nickname variant')
        check_profile['faculty_name'] = quoted_name
    if local_route:
        if not profile.get('faculty_name_local') or profile.get('publication_list_scope') != 'OWN_PUBLICATIONS_ON_OFFICIAL_PERSONAL_PROFILE' or profile['publications_url'].rstrip('/') != profile['faculty_evidence_url'].rstrip('/'):
            raise ValueError('Local-name identity requires own bibliography on the same official personal profile')
        check_profile['faculty_name'] = profile['faculty_name_local']
    checked = match_faculty(check_profile, raw, [])
    if quoted_name: checked.update(faculty_name=profile['faculty_name'], faculty_quoted_name=quoted_name)
    if pdf_pages:
        checked.update(faculty_evidence_sha256=hashlib.sha256(original).hexdigest(), faculty_evidence_pdf_pages=pdf_pages, faculty_evidence_extracted_sha256=hashlib.sha256(raw).hexdigest(), faculty_evidence_extractor='pypdf')
    if local_route:
        checked.update(faculty_name=profile['faculty_name'], faculty_name_local=profile['faculty_name_local'], faculty_identity_route='LOCAL_NAME_OWN_PUBLICATION_LIST', identity_inference='Official current local-name profile plus own English-name bibliography and exact publisher authors; not a single English-name/role quote')
    return checked


# [전문가4] 2026-09-27 case67: 긴 제목의 앞 3단어 이내 생략은 전체 공저자·연도·권호·쪽까지 일치해야 허용한다.
def publication_title_match(work, raw):
    title = visible((work.get('title') or [''])[0]); text = visible(raw)
    if title_key(title) and title_key(title) in title_key(text): return {'basis': 'EXACT_NORMALIZED_TITLE', 'listed_title': title}
    words = title.split(); year_parts = (work.get('published', {}).get('date-parts') or work.get('issued', {}).get('date-parts') or [[]])[0]
    journal = (work.get('container-title') or [''])[0]; volume = work.get('volume'); issue = work.get('issue'); pages = work.get('page', '')
    if not year_parts or not all([journal, volume, issue, pages]) or len(words) < 12: return None
    authors = work.get('author', [])
    if not authors or any(not a.get('family') or not a.get('given') for a in authors): return None
    author_key = ''.join(compact(a['family']) + compact(''.join(part[0] for part in a['given'].replace('-', ' ').split())) for a in authors)
    for omit in range(1, 4):
        suffix = ' '.join(words[omit:])
        pattern = re.compile(re.escape(suffix), re.I)
        for match in pattern.finditer(text):
            before, after = text[max(0, match.start()-180):match.start()], text[match.end():match.end()+len(journal)+80]
            year_match = re.search(r'\(' + str(year_parts[0]) + r'\)\.\s*$', before)
            if not year_match or not compact(before[:year_match.start()]).endswith(author_key): continue
            expected = title_key(f'{journal} {volume} {issue} {pages}')
            if not title_key(after).startswith(expected): continue
            return {'basis': 'LEADING_WORDS_OMITTED_FULL_BIBLIOGRAPHY_MATCH', 'listed_title': match.group(), 'publisher_title': title, 'omitted_leading_words': omit, 'citation_quote': before + match.group() + after, 'year': year_parts[0], 'journal': journal, 'volume': volume, 'issue': issue, 'pages': pages, 'all_author_names': [a['given'] + ' ' + a['family'] for a in authors]}
    return None


# [전문가4] 2026-09-27 case67: 출판사 기탁 Crossref 제목·DOI·실명 저자와 공식 목록을 대조한다.
def match_work(profile, profile_raw, publications_raw, work, category, identity_raw=None, checked_override=None):
    checked = dict(checked_override) if checked_override is not None else faculty_profile_check(profile, profile_raw)
    if checked['status'] != 'NOT_MATCHED':
        raise ValueError('Official faculty profile not verified: ' + checked['status'])
    official_publications(profile, profile_raw, identity_raw if identity_raw is not None else publications_raw)
    if profile.get('publication_list_basis'):
        checked.update(publication_list_basis=profile['publication_list_basis'], publication_identity_quote=profile.get('publication_identity_quote'), identity_note=profile.get('identity_note'))
    if profile.get('faculty_identity_route') == 'LOCAL_NAME_OWN_PUBLICATION_LIST' and compact(profile['faculty_name']) not in compact(visible(publications_raw)):
        raise ValueError('English author name absent from own official bibliography')
    title = visible((work.get('title') or [''])[0])
    ident = base.doi(work.get('DOI'))
    if not re.fullmatch(r'10\.\d{4,9}/\S+', ident) or not title_key(title):
        raise ValueError('Missing DOI or substantive title')
    title_match = publication_title_match(work, publications_raw)
    if not title_match:
        raise ValueError('Exact title missing from official publication list')
    if title_match['basis'] != 'EXACT_NORMALIZED_TITLE': checked['publication_title_variation'] = title_match
    if work.get('type') not in {'journal-article', 'proceedings-article'}:
        raise ValueError('Unsupported publication type')
    subtype = work.get('subtype', '')
    if subtype and subtype not in {'research-article', 'review-article'}:
        raise ValueError('Explicit unsupported publication subtype')
    if re.search(r'^(?:editorial|retraction|erratum|correction)(?:\s*:|\s+(?:to|of|notice)\b|$)|\b(?:abstract.only|study protocol|trial protocol|protocol for|protocol of)\b|^(?:comments? on|response to|reply to|letter to|book review)\b', title, re.I) or work.get('update-to'):
        raise ValueError('Excluded editorial/correction/protocol/update record')
    authors = []
    linked_aliases = set()
    # [전문가4] 2026-09-27 case67: 기관 저작의 실제 교수 프로필 링크가 입증한 중간이름 표기만 수용한다.
    for href, label in re.findall(r'<a\b[^>]*href=["\x27]([^"\x27]+)["\x27][^>]*>(.*?)</a>', publications_raw.decode('utf-8', errors='replace'), re.I | re.S):
        alias = visible(label).strip(' ,;')
        words = profile['faculty_name'].split()
        if urllib.parse.urljoin(profile['publications_url'], html.unescape(href)).rstrip('/') == profile['faculty_evidence_url'].rstrip('/') and len(words) >= 2 and all(re.search(r'\b' + re.escape(word) + r'\b', alias, re.I) for word in [words[0], words[-1]]):
            linked_aliases.add(compact(alias))
    for author in work.get('author', []):
        name = (author.get('given', '') + ' ' + author.get('family', '')).strip()
        faculty_pieces = profile['faculty_name'].split()
        expected_names = {compact(profile['faculty_name']), compact(' '.join(faculty_pieces[-1:] + faculty_pieces[:-1]))}
        expected_names.update(linked_aliases)
        if profile.get('faculty_identity_route') == 'LOCAL_NAME_OWN_PUBLICATION_LIST' or profile.get('publication_list_basis') == 'FACULTY_PERSONAL_LIST_CORROBORATED_BY_OFFICIAL_PROFILE':
            if profile.get('faculty_name_local'): expected_names.add(compact(profile['faculty_name_local']))
        if expected_names & {compact(name), compact(author.get('family', '') + author.get('given', ''))}:
            authors.append({'paper_author_name': name, 'paper_author_orcid': author.get('ORCID', ''), 'publisher_metadata_affiliations': author.get('affiliation', []), 'match_basis': 'OFFICIAL_FACULTY_PUBLICATION_AND_PUBLISHER_METADATA'})
    if len(authors) != 1:
        raise ValueError('Publisher metadata lacks one exact full-name author')
    if profile.get('orcid') and authors[0]['paper_author_orcid'] and profile['orcid'].removeprefix('https://orcid.org/') != authors[0]['paper_author_orcid'].removeprefix('https://orcid.org/'):
        raise ValueError('ORCID conflict')
    relevance = base.relevance({'title': title, 'abstractText': visible(work.get('abstract', ''))}, FIELDS[category])
    # [전문가4] 2026-09-27 case67: 승인된 구성요소 범위; 일반 NLP 전반을 논문 검증으로 승격하지 않는다.
    components = extraction_component_terms(title) if category == 'claim_evidence' else []
    claim_terms = claim_verification_terms(title, work.get('abstract', '')) if category == 'claim_evidence' else []
    education_terms = education_research_terms(title, work.get('abstract', '')) if category == 'education_learning' else []
    ecology_terms = ecology_research_terms(title, work.get('abstract', '')) if category == 'ecology_biodiversity' else []
    economics_terms = economics_research_terms(title, work.get('abstract', '')) if category == 'economics_policy' else []
    climate_terms = climate_research_terms(title, work.get('abstract', '')) if category == 'climate_pollution' else []
    psychology_terms = psychology_research_terms(title, work.get('abstract', '')) if category == 'psychology_behavior' else []
    ai_terms = ai_evaluation_terms(title, work.get('abstract', '')) if category == 'ai_evaluation' else []
    statistics_terms = statistical_method_terms(title, work.get('abstract', '')) if category == 'statistics' else []
    provenance_terms = provenance_method_terms(title, work.get('abstract', '')) if category == 'provenance' else []
    workflow_terms = workflow_method_terms(title, work.get('abstract', '')) if category == 'research_workflow' else []
    # [전문가4] 2026-09-27 case67: 공식 색인의 연구데이터 플랫폼 키워드와 실제 평가 제목을 함께 요구한다.
    if category == 'research_workflow' and 'research data platform' in ' '.join(work.get('publisher_keywords', [])).lower() and any(term in title.lower() for term in ['evaluation', 'usability', 'workflow']):
        workflow_terms.append('research data platform evaluation (publisher keywords + title)')
    if not relevance and components:
        relevance = [components]
    if not relevance and statistics_terms:
        relevance = [statistics_terms]
    if not relevance and provenance_terms:
        relevance = [provenance_terms]
    if not relevance and workflow_terms:
        relevance = [workflow_terms]
    if not relevance and claim_terms: relevance = [claim_terms]
    if not relevance and education_terms: relevance = [education_terms]
    if not relevance and ecology_terms: relevance = [ecology_terms]
    if not relevance and economics_terms: relevance = [economics_terms]
    if not relevance and climate_terms: relevance = [climate_terms]
    if not relevance and psychology_terms: relevance = [psychology_terms]
    if not relevance and ai_terms: relevance = [ai_terms]
    if not relevance:
        raise ValueError('Topic rule failed' if work.get('abstract') else 'TOPIC_INFORMATION_INSUFFICIENT_ABSTRACT_MISSING')
    parts = (work.get('published', {}).get('date-parts') or work.get('issued', {}).get('date-parts') or [[]])[0]
    if not parts or not 2000 <= parts[0] <= 2026:
        raise ValueError('Publication year outside scope')
    date = '-'.join(str(number).zfill(4 if index == 0 else 2) for index, number in enumerate(parts))
    if date > '2026-09-27':
        raise ValueError('Future publication date')
    checked.update(status='MATCHED', paper_author_match=authors)
    type_status = 'REVIEW_CONFIRMED' if subtype == 'review-article' else ('RESEARCH_ARTICLE_LABEL' if subtype == 'research-article' else 'NOT_CONFIRMED')
    role = 'REVIEW_BACKGROUND' if subtype == 'review-article' else ('RESEARCH_CANDIDATE' if subtype == 'research-article' else 'UNCLASSIFIED_REFERENCE')
    if components: role = 'EXTRACTION_COMPONENT_METHOD'
    if statistics_terms: role = 'STATISTICAL_METHOD_REFERENCE'
    if provenance_terms: role = 'DATA_MANAGEMENT_METHOD_REFERENCE'
    if workflow_terms: role = 'RESEARCH_WORKFLOW_REFERENCE'
    if claim_terms: role = 'CLAIM_EVIDENCE_METHOD_REFERENCE'
    pmcids = {str(value).upper() for value in work.get('alternative-id', []) if re.fullmatch(r'PMC\d+', str(value), re.I)}
    if len(pmcids) > 1: raise ValueError('Conflicting PMCID metadata')
    return {'doi': ident, 'pmcid': next(iter(pmcids), ''), 'title': title, 'publication_date': date, 'category': category, 'article_type': 'conference-paper' if work['type'] == 'proceedings-article' else (subtype or 'journal-article'), 'article_subtype': subtype or 'NOT_CONFIRMED', 'publication_type_status': type_status, 'reference_role': role, 'analysis_eligibility': 'NOT_ESTABLISHED', 'article_type_basis': 'CROSSREF_TYPE_AND_SUBTYPE', 'faculty_match': checked, 'topic_keyword_hits': relevance, 'classification': 'AUTOMATIC_RULES_NOT_EXPERT_REVIEW', 'official_publication_title_quote': title_match['listed_title'], 'source_url': 'https://doi.org/' + ident, 'fulltext_status': 'CITATION_METADATA_ONLY', 'fulltext_access_status': 'NON_OPEN_OR_UNKNOWN', 'fulltext_access_status_basis': 'FULLTEXT_ACCESS_NOT_ASSESSED', 'license': 'FULLTEXT_REUSE_NOT_ASSESSED', 'raw_data_download_status': 'NOT_TESTED', 'reproduction_status': 'NOT_TESTED', 'data_link_status': 'NOT_IDENTIFIED', 'data_link_status_basis': 'FULLTEXT_NOT_ACCESSED', 'faculty_status_basis': 'CURRENT_OFFICIAL_PROFILE', 'role_at_publication': 'NOT_ESTABLISHED'}


# [전문가4] 2026-09-27 case67: 공식 증거 응답과 시각을 상대 경로·해시로 저장한다.
def evidence(url, out):
    key = hashlib.sha256(url.encode()).hexdigest()
    record = out / 'evidence' / (key + '.json')
    if record.exists():
        item = json.loads(record.read_text(encoding='utf-8'))
        raw = (out / item['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Cached evidence changed')
        return raw, item
    failure = record.with_name(key + '.failure.json')
    if failure.exists(): raise ValueError('CACHED_CROSSREF_METADATA_UNAVAILABLE_404_NOT_DOI_ABSENCE')
    raw = crossref_fetch(url, out) if url.startswith('https://api.crossref.org/') else base.fetch(url, out)
    if raw is None:
        raise ValueError('Evidence fetch failed')
    item = {'url': url, 'path': 'evidence/' + key + '.txt', 'sha256': hashlib.sha256(raw).hexdigest(), 'collected_at': base.now()}
    record.parent.mkdir(exist_ok=True)
    (out / item['path']).write_bytes(raw)
    record.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
    return raw, item


# [전문가4] 2026-09-27 case67: 저장 근거를 다시 읽어 해시뿐 아니라 저자·제목·분야를 오프라인 재판정한다.
def verify(records, out, excluded, excluded_pmc, per_field):
    seen = set(); seen_pmc = set(); counts = collections.Counter()
    for record in records:
        ident = record['doi']; pmc = record.get('pmcid', '')
        if ident in seen | excluded or (pmc and pmc in seen_pmc | excluded_pmc):
            raise ValueError('Duplicate or excluded identity')
        seen.add(ident)
        if pmc: seen_pmc.add(pmc)
        counts[record['category']] += 1
        if counts[record['category']] > per_field:
            raise ValueError('Category quota exceeded')
        raw = {}
        facts = record['source_evidence']
        if facts['faculty_profile']['url'] != record['faculty_profile']['faculty_evidence_url'] or facts['official_publications']['url'] != record['faculty_profile']['publications_url']:
            raise ValueError('Evidence URL mismatch')
        metadata_url = facts['publisher_metadata']['url']
        if not metadata_url.startswith('https://api.crossref.org/works') and not (metadata_url == 'https://doi.org/' + ident and facts['publisher_metadata'].get('format') == 'CSL_JSON'):
            raise ValueError('Publisher metadata source is not Crossref or DOI CSL')
        for kind, fact in record['source_evidence'].items():
            relative = Path(fact['path'])
            if relative.is_absolute() or '..' in relative.parts or ':' in fact['path']:
                raise ValueError('Unsafe evidence path')
            raw[kind] = (out / relative).read_bytes()
            if hashlib.sha256(raw[kind]).hexdigest() != fact['sha256']:
                raise ValueError('Evidence hash mismatch')
        works = metadata_works(raw['publisher_metadata'])
        work = next((item for item in works if base.doi(item.get('DOI')) == ident), None)
        if work is None:
            raise ValueError('DOI missing from publisher metadata evidence')
        if 'acl_metadata' in raw:
            if facts['acl_metadata']['url'] != 'https://aclanthology.org/' + ident.removeprefix('10.18653/v1/') + '/':
                raise ValueError('ACL evidence URL mismatch')
            work = supplement_acl(work, raw['acl_metadata'], record['faculty_profile'])
        if 'publisher_citation' in raw:
            expected = record['faculty_profile'].get('publisher_metadata_urls', {}).get(ident)
            if facts['publisher_citation']['url'] != expected: raise ValueError('Citation URL mismatch')
            work = supplement_citation(work, raw['publisher_citation'], record['faculty_profile'], raw['official_publications'])
        work = supplement_official_abstract(work, raw['official_publications'], record['faculty_profile']['publications_url'])
        if 'personal_identity' in facts and facts['personal_identity']['url'] != record['faculty_profile'].get('publication_identity_url'):
            raise ValueError('Personal identity source URL mismatch')
        checked_override = None
        if facts['faculty_profile'].get('distribution_status') == 'RAW_PROFILE_PDF_NOT_REDISTRIBUTED':
            from faculty_profile_excerpt import profile_excerpt_check
            checked_override = profile_excerpt_check(record['faculty_profile'], facts['faculty_profile'], out)
        rebuilt = match_work(record['faculty_profile'], raw['faculty_profile'], raw['official_publications'], work, record['category'], raw.get('personal_identity'), checked_override)
        for key in ['doi', 'pmcid', 'title', 'publication_date', 'article_type', 'article_subtype', 'publication_type_status', 'reference_role', 'analysis_eligibility', 'fulltext_status', 'fulltext_access_status', 'raw_data_download_status', 'reproduction_status', 'role_at_publication', 'official_publication_title_quote']:
            if record[key] != rebuilt[key]:
                raise ValueError('Record does not match source evidence: ' + key)
        if record['faculty_match']['paper_author_match'] != rebuilt['faculty_match']['paper_author_match']:
            raise ValueError('Author evidence mismatch')
        for key in ['status', 'faculty_evidence_url', 'faculty_name', 'faculty_role', 'faculty_affiliation', 'faculty_evidence_quote', 'faculty_evidence_sha256', 'faculty_status_basis', 'role_at_publication', 'faculty_name_local', 'faculty_identity_route', 'identity_inference', 'faculty_evidence_pdf_pages', 'faculty_evidence_extracted_sha256', 'faculty_evidence_extractor', 'publication_title_variation', 'faculty_quoted_name', 'publication_list_basis', 'publication_identity_quote', 'identity_note', 'faculty_profile_distribution_status', 'faculty_profile_verification_scope']:
            if record['faculty_match'].get(key) != rebuilt['faculty_match'].get(key):
                raise ValueError('Faculty evidence mismatch: ' + key)
        if any(key in record for key in ['fulltext_path', 'fulltext_sha256']):
            raise ValueError('Metadata-only record must not claim archived fulltext')
    return {'verified_selected': len(records), 'counts': dict(counts), 'unique_doi': len(seen), 'profile_pdf_quote_only_count': sum(r['source_evidence']['faculty_profile'].get('distribution_status') == 'RAW_PROFILE_PDF_NOT_REDISTRIBUTED' for r in records), 'profile_pdf_quote_scope': 'Excerpt hash/quote checked; original PDF not offline revalidated when not redistributed', 'fulltext_status': 'CITATION_METADATA_ONLY', 'verification_scope': 'Official profile/publication list plus Crossref or DOI CSL metadata, with optional ACL abstract; no article body retained', 'target_complete': all(counts[key] == per_field for key in FIELDS)}


# [전문가4] 2026-09-27 case67: 읽기 쉬운 서지와 접근 상태를 저장하고 원문 확보를 주장하지 않는다.
def save(records, out):
    (out / 'papers.json').write_text(json.dumps({'generated_at': base.now(), 'papers': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    columns = ['category', 'title', 'doi', 'pmcid', 'publication_date', 'article_type', 'publication_type_status', 'reference_role', 'fulltext_status', 'fulltext_access_status', 'analysis_eligibility']
    with (out / 'papers.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader()
        writer.writerows({key: record.get(key, '') for key in columns} for record in records)
    lines = ['# 국내 교수 참여 서지 — 공식 출판목록 경로', '', '본문 미접속 서지입니다. 현재 공식 교수 직함은 확인했으나 발표 당시 교수 재직은 NOT_ESTABLISHED입니다. 자료 다운로드·분석 재현은 NOT_TESTED이며 하위유형 미확정을 연구논문으로 단정하지 않습니다.', '']
    for record in records:
        lines.append('- [' + record['title'] + '](' + record['source_url'] + ') — ' + record['category'] + ' — ' + record['faculty_match']['faculty_name'] + ' — ' + record['reference_role'] + ' — CITATION_METADATA_ONLY')
    (out / 'papers.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


# [전문가4] 2026-09-27 case67: 교수 목록에서 유래한 검색만 수행하고 실패·미달을 실제 수치로 남긴다.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profiles'); parser.add_argument('--output', required=True)
    parser.add_argument('--exclude-json', action='append', required=True)
    parser.add_argument('--per-field', type=int, default=20)
    parser.add_argument('--max-queries', type=int, default=100)
    parser.add_argument('--quota-json', help='Other faculty collection only; old600 exclusion lists do not count toward quotas')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    excluded = base.exclusions(args.exclude_json); excluded_pmc = base.exclusions(args.exclude_json, 'pmcid')
    target = out / 'papers.json'
    records = json.loads(target.read_text(encoding='utf-8'))['papers'] if target.exists() else []
    verify(records, out, excluded, excluded_pmc, args.per_field)
    if not args.verify_only:
        profiles = json.loads(Path(args.profiles).read_text(encoding='utf-8'))
        if isinstance(profiles, dict): profiles = [profiles]
        seen = excluded | {record['doi'] for record in records}
        seen_pmc = excluded_pmc | {record['pmcid'] for record in records if record.get('pmcid')}
        counts = collections.Counter(record['category'] for record in records)
        if args.quota_json:
            other = json.loads(Path(args.quota_json).read_text(encoding='utf-8'))
            counts.update(record['category'] for record in other['papers'])
        for profile in profiles:
            try:
                profile_raw, profile_fact = evidence(profile['faculty_evidence_url'], out)
                official_publications(profile, profile_raw)
                profile['faculty_evidence_collected_at'] = profile_fact['collected_at']
                if faculty_profile_check(profile, profile_raw)['status'] != 'NOT_MATCHED':
                    raise ValueError('Official profile evidence invalid')
                pub_raw, pub_fact = evidence(profile['publications_url'], out)
                identity_raw = identity_fact = None
                if profile.get('publication_identity_url'):
                    identity_raw, identity_fact = evidence(profile['publication_identity_url'], out)
                attempted = set()
                print(json.dumps({'faculty': profile['faculty_name'], 'status': 'OFFICIAL_LIST_VERIFIED'}), flush=True)
                for url, unit in publication_queries(pub_raw, profile, args.max_queries):
                    if all(counts[c] >= args.per_field for c in profile['candidate_categories']): break
                    try: metadata_raw, metadata_fact = evidence(url, out)
                    except ValueError as error:
                        base.append(out / 'candidate_rejections.jsonl', {'url': url, 'error': str(error)})
                        if url.startswith('https://api.crossref.org/works/') and '404' in str(error):
                            try: metadata_raw, metadata_fact = doi_csl_evidence(base.doi(urllib.parse.unquote(url.split('/works/', 1)[1])), out)
                            except ValueError as fallback_error:
                                base.append(out / 'candidate_rejections.jsonl', {'url': url, 'fallback_error': str(fallback_error)})
                                continue
                        else: continue
                    for work in metadata_works(metadata_raw):
                        citation_fact = None
                        citation_url = profile.get('publisher_metadata_urls', {}).get(base.doi(work.get('DOI')))
                        if citation_url:
                            try:
                                citation_raw, citation_fact = citation_evidence(citation_url, out)
                                work = supplement_citation(work, citation_raw, profile, pub_raw)
                            except (ValueError, OSError) as error:
                                base.append(out / 'candidate_rejections.jsonl', {'doi': work.get('DOI'), 'citation_error': str(error)})
                                citation_fact = None
                        work = supplement_official_abstract(work, pub_raw, profile['publications_url'])
                        if base.doi(work.get('DOI')) in seen: continue
                        if not publication_title_match(work, unit): continue
                        if base.doi(work.get('DOI')) in attempted: continue
                        attempted.add(base.doi(work.get('DOI')))
                        acl_fact = None
                        if not work.get('abstract') and base.doi(work.get('DOI')).startswith('10.18653/v1/'):
                            try:
                                acl_raw, acl_fact = evidence('https://aclanthology.org/' + base.doi(work['DOI']).removeprefix('10.18653/v1/') + '/', out)
                                work = supplement_acl(work, acl_raw, profile)
                            except ValueError as error:
                                base.append(out / 'candidate_rejections.jsonl', {'doi': work.get('DOI'), 'error': str(error)})
                                acl_fact = None
                        for category in ordered_categories(profile, work):
                            if counts[category] >= args.per_field: continue
                            try: record = match_work(profile, profile_raw, pub_raw, work, category, identity_raw)
                            except ValueError as error:
                                base.append(out / 'candidate_rejections.jsonl', {'doi': work.get('DOI'), 'category': category, 'error': str(error)})
                                continue
                            record.update(faculty_profile=dict(profile), source_evidence={'faculty_profile': profile_fact, 'official_publications': pub_fact, 'publisher_metadata': metadata_fact}, collected_at=base.now())
                            if record['pmcid'] and record['pmcid'] in seen_pmc: continue
                            if acl_fact: record['source_evidence']['acl_metadata'] = acl_fact
                            if identity_fact: record['source_evidence']['personal_identity'] = identity_fact
                            if citation_fact: record['source_evidence']['publisher_citation'] = citation_fact
                            records.append(record); seen.add(record['doi']); counts[category] += 1
                            if record['pmcid']: seen_pmc.add(record['pmcid'])
                            target.write_text(json.dumps({'generated_at': base.now(), 'papers': records}, ensure_ascii=False, indent=2), encoding='utf-8')
                            print(json.dumps({'selected': len(records), 'category': category, 'doi': record['doi']}), flush=True)
                            break
            except (ValueError, KeyError) as error:
                base.append(out / 'profile_errors.jsonl', {'faculty': profile.get('faculty_name'), 'error': str(error)})
    result = verify(records, out, excluded, excluded_pmc, args.per_field)
    save(records, out)
    (out / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
