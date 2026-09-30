"""case95 live, free Crossref metadata discovery; no keys, LLM, or full-text claim.

Official API: https://www.crossref.org/documentation/retrieve-metadata/rest-api/
Sorting/filter details: https://github.com/CrossRef/rest-api-doc
All provider text is untrusted plain display data. This is not systematic
literature coverage, a relevance guarantee, or a paper quality verdict.
"""
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import http.client
import re
import unicodedata
from urllib.parse import quote, urlencode

from core.research_corpus import strict_json
from core.research_tasks import SECRET_PATTERN

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_INSTITUTION_ROWS = 50
SORTS = {'latest':'published', 'registered':'created', 'cited':'is-referenced-by-count'}
KST = timezone(timedelta(hours=9))
INSTITUTIONS = {
    'snu': {'label':'서울대학교','query':'Seoul National University','aliases':('Seoul National University','서울대학교','SNU')},
    'kaist': {'label':'KAIST','query':'Korea Advanced Institute of Science and Technology','aliases':('Korea Advanced Institute of Science and Technology','KAIST','한국과학기술원')},
    'yonsei': {'label':'연세대학교','query':'Yonsei University','aliases':('Yonsei University','연세대학교')},
    'korea': {'label':'고려대학교','query':'Korea University','aliases':('Korea University','고려대학교')},
    'postech': {'label':'POSTECH','query':'Pohang University of Science and Technology','aliases':('Pohang University of Science and Technology','POSTECH','포항공과대학교')},
    'skku': {'label':'성균관대학교','query':'Sungkyunkwan University','aliases':('Sungkyunkwan University','SKKU','성균관대학교')},
    'unist': {'label':'UNIST','query':'Ulsan National Institute of Science and Technology','aliases':('Ulsan National Institute of Science and Technology','UNIST','울산과학기술원')},
    'hanyang': {'label':'한양대학교','query':'Hanyang University','aliases':('Hanyang University','한양대학교')},
    'pusan': {'label':'부산대학교','query':'Pusan National University','aliases':('Pusan National University','부산대학교')},
    'kyunghee': {'label':'경희대학교','query':'Kyung Hee University','aliases':('Kyung Hee University','Kyunghee University','경희대학교')},
    'mit': {'label':'MIT','query':'Massachusetts Institute of Technology','aliases':('Massachusetts Institute of Technology','MIT')},
    'harvard': {'label':'Harvard','query':'Harvard University','aliases':('Harvard University',)},
    'stanford': {'label':'Stanford','query':'Stanford University','aliases':('Stanford University',)},
    'oxford': {'label':'Oxford','query':'University of Oxford','aliases':('University of Oxford','Oxford University')},
    'cambridge': {'label':'Cambridge','query':'University of Cambridge','aliases':('University of Cambridge','Cambridge University')},
    'eth': {'label':'ETH Zurich','query':'ETH Zurich','aliases':('ETH Zurich','ETH Zürich','Swiss Federal Institute of Technology Zurich','Eidgenössische Technische Hochschule Zürich')},
    'caltech': {'label':'Caltech','query':'California Institute of Technology','aliases':('California Institute of Technology','Caltech')},
    'berkeley': {'label':'UC Berkeley','query':'University of California Berkeley','aliases':('University of California Berkeley','UC Berkeley')},
    'tokyo': {'label':'도쿄대학교','query':'University of Tokyo','aliases':('University of Tokyo','東京大学')},
    'tsinghua': {'label':'칭화대학교','query':'Tsinghua University','aliases':('Tsinghua University','清华大学')},
}


# [작성: 문헌검색 백엔드] 2026-09-29 case95 / KST오늘→미래발행제외 / 검증: 주입날짜·윤년경계.
def _today():
    return datetime.now(KST).date()


# [작성: 문헌검색 백엔드] 2026-09-29 case95 / query→공유외부전송검사 / 검증: 빈입력·키·제어·300자·네트워크0.
def validate_query(query):
    if (not isinstance(query,str) or not query.strip() or len(query)>300
            or any(ord(c)<32 or ord(c)==127 for c in query) or SECRET_PATTERN.search(query)):
        raise ValueError('DISCOVERY_INVALID_QUERY')
    return query.strip()


# [작성: 문헌검색 백엔드] 2026-09-29 case95 / 고정GET→상한서지응답 / 검증: timeout·redirect안읽음·2MiB·중복JSON.
def _request(path):
    if not isinstance(path,str) or not path.startswith('/works?') or len(path)>4000 or any(ord(c)<32 for c in path):
        raise ValueError('DISCOVERY_INVALID_REQUEST')
    connection=None
    try:
        connection=http.client.HTTPSConnection('api.crossref.org',timeout=15)
        connection.request('GET',path,headers={'User-Agent':'NAIS-PaperDiscovery/95','Accept':'application/json'})
        response=connection.getresponse()
        if response.status!=200:raise ValueError('DISCOVERY_HTTP_ERROR')
        raw=response.read(MAX_RESPONSE_BYTES+1)
        if len(raw)>MAX_RESPONSE_BYTES:raise ValueError('DISCOVERY_RESPONSE_TOO_LARGE')
        return strict_json(raw)
    except Exception:
        raise ValueError('DISCOVERY_UNAVAILABLE_OR_INVALID_RESPONSE') from None
    finally:
        if connection is not None:connection.close()


class _PlainText(HTMLParser):
    # [작성: 문헌검색 백엔드] 2026-09-29 case95 / HTML태그→실행없는plain문자 / 검증: &amp;·태그제거.
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]

    # [작성: 문헌검색 백엔드] 2026-09-29 case95 / 본문조각→텍스트 / 검증: UI에서HTML비실행.
    def handle_data(self,data):
        self.parts.append(data)


# [작성: 문헌검색 백엔드] 2026-09-29 case95 / bounded제목·학술지→plain출력 / 검증: 과대·비밀메타삭제.
def _plain(value,limit):
    if not isinstance(value,str) or len(value)>8000:raise ValueError()
    parser=_PlainText();parser.feed(value);parser.close()
    text=' '.join(''.join(parser.parts).split())
    if not text or SECRET_PATTERN.search(text) or any(ord(c)<32 or ord(c)==127 for c in text):raise ValueError()
    return text[:limit]


# [작성: 문헌검색 백엔드] 2026-09-29 case95 / 정확발행일→기간검사 / 검증: 일부날짜·bool·존재하지않는날짜제외.
def _published(item):
    parts=item['published']['date-parts']
    if not isinstance(parts,list) or len(parts)!=1 or not isinstance(parts[0],list) or len(parts[0])!=3 or any(type(x) is not int for x in parts[0]):
        raise ValueError()
    return date(*parts[0])


# [작성: 소속검색 백엔드] 2026-09-29 case95 / 저자소속→plain고유목록(최대50) / 검증: 누락·키·HTML·과대목록.
def _affiliations(item):
    authors=item.get('author',[])
    if not isinstance(authors,list) or len(authors)>200:raise ValueError()
    result=[]
    for author in authors:
        if not isinstance(author,dict):raise ValueError()
        entries=author.get('affiliation',[])
        if not isinstance(entries,list) or len(entries)>20:raise ValueError()
        for entry in entries:
            if not isinstance(entry,dict):raise ValueError()
            name=_plain(entry.get('name'),8000)
            # Do not match a truncated name: it could cut off "of Science and Technology" after SNU.
            if len(name)>500:raise ValueError()
            if name not in result:result.append(name)
            if len(result)>50:raise ValueError()
    return result


# [작성: 소속검색 백엔드] 2026-09-29 case95 / 명시별칭+기관구간경계→오인없는소속일치 / 검증: SNUofScience·MITPress反例.
def _matches_affiliation(affiliations,institution):
    for name in affiliations:
        name=unicodedata.normalize('NFKC',name).casefold()
        for alias in INSTITUTIONS[institution]['aliases']:
            alias=unicodedata.normalize('NFKC',alias).casefold()
            # Acronyms (MIT/SNU/KAIST) must be an entire delimiter-separated affiliation component;
            # substring presence such as "MIT Press" or "SNU Corporation" is not university evidence.
            if alias.isascii() and alias.isalpha() and len(alias)<=7:
                # An explicit different institution expanded beside an acronym must not win:
                # Somali National University (SNU), or Madanapalle Institute of Technology (MIT).
                # A full selected alias is checked independently; conservative rejection can miss
                # abbreviated school-only records, which is disclosed as incomplete affiliation.
                if re.search(r'\b(?:university|institute|college|corporation|press)\b|대학교|대학',name):continue
                if any(part.strip()==alias for part in re.split(r'[,;()|]',name)):return True
                continue
            # Full names may follow department text but must end at a delimiter or end of field.
            # In particular "Seoul National University of Science and Technology" is a distinct
            # institution, never SNU: trailing words after "University" cannot pass this boundary.
            # Commas inside "University of California, Berkeley" are allowed between alias words.
            pattern=r'(?<!\w)'+r'[^\w]+'.join(re.escape(word) for word in alias.split())+r'(?!\w)'
            for match in re.finditer(pattern,name):
                tail=name[match.end():]
                if re.match(r'^[\s,;()|]*(?:of|and)\b',tail):continue
                if not tail.strip() or re.match(r'^\s*[,;()|]',tail):return True
    return False


# [작성: 문헌검색 백엔드] 2026-09-29 case95 / validated서지1건→허용출력만 / 검증: DOI·누적인용None·등록미래.
def _item(item,start,today,mode):
    if not isinstance(item,dict):raise ValueError()
    doi=item.get('DOI')
    if not isinstance(doi,str) or len(doi)>200 or not re.fullmatch(r'10\.\d{4,9}/[^\s\x00-\x1f\x7f]+',doi) or SECRET_PATTERN.search(doi):raise ValueError()
    doi=doi.lower()
    published=_published(item)
    if not start<=published<=today:raise ValueError()
    registered_at=None
    if item.get('created') is not None:
        created=item['created']['date-time']
        if not isinstance(created,str) or len(created)>40:raise ValueError()
        created=datetime.fromisoformat(created.replace('Z','+00:00'))
        if created.tzinfo is None or created.astimezone(KST).date()>today:raise ValueError()
        registered_at=created.astimezone(timezone.utc).isoformat()
    if mode=='registered' and registered_at is None:raise ValueError()
    titles=item.get('title')
    if not isinstance(titles,list) or not 1<=len(titles)<=20:raise ValueError()
    title=_plain(titles[0],600)
    citations=item.get('is-referenced-by-count')
    if citations is not None and (type(citations) is not int or not 0<=citations<=10**12):raise ValueError()
    journals=item.get('container-title')
    if journals is None or journals==[]:journal=None
    else:
        if not isinstance(journals,list) or len(journals)>20:raise ValueError()
        journal=_plain(journals[0],200)
    return dict(doi=doi,title=title,published=published.isoformat(),registered_at=registered_at,citations=citations,journal=journal,
                url='https://doi.org/'+quote(doi,safe='/'),affiliations=_affiliations(item))


# [작성: 문헌검색 백엔드] 2026-09-29 case95 / query+mode+calendar기간→1회무료실시간조회 / 검증: 모든mock+무료climate1회.
def search_papers(query,mode='latest',years=1,limit=8,institution=''):
    query=validate_query(query)
    if not isinstance(mode,str) or mode not in SORTS or type(years) is not int or years not in {1,3} or type(limit) is not int or not 1<=limit<=10:
        raise ValueError('DISCOVERY_INVALID_OPTIONS')
    if not isinstance(institution,str) or (institution and (SECRET_PATTERN.search(institution) or institution not in INSTITUTIONS)):
        raise ValueError('DISCOVERY_INVALID_INSTITUTION')
    today=_today()
    try:start=today.replace(year=today.year-years)
    except ValueError:start=today.replace(year=today.year-years,day=28) # Feb29 calendar boundary.
    params={'query.bibliographic':query,
            'filter':f'type:journal-article,from-pub-date:{start.isoformat()},until-pub-date:{today.isoformat()}',
            'sort':SORTS[mode],'order':'desc','rows':MAX_INSTITUTION_ROWS if institution else limit,
            'select':'DOI,title,published,created,is-referenced-by-count,container-title,author'}
    if institution:params['query.affiliation']=INSTITUTIONS[institution]['query']
    path='/works?'+urlencode(params)
    try:response=_request(path)
    except Exception:raise ValueError('DISCOVERY_UNAVAILABLE_OR_INVALID_RESPONSE') from None
    if (not isinstance(response,dict) or response.get('status')!='ok' or not isinstance(response.get('message'),dict)
            or not isinstance(response['message'].get('items'),list) or len(response['message']['items'])>100):
        raise ValueError('DISCOVERY_INVALID_RESPONSE')
    items=[];seen=set();skipped=0;affiliation_skipped=0
    for raw in response['message']['items']:
        try:
            item=_item(raw,start,today,mode)
            if institution and not _matches_affiliation(item['affiliations'],institution):
                affiliation_skipped+=1
                continue
            if item['doi'] in seen or len(items)>=limit:raise ValueError()
            seen.add(item['doi']);items.append(item)
        except Exception:skipped+=1
    label={'latest':'발행일 최신순','registered':'Crossref 최초 등록 최신순','cited':'현재 누적 인용순'}[mode]
    limitations=['Crossref 등록 서지 검색 결과입니다. 원문 확보·관련성·논문 품질·전체 문헌 범위를 확증하지 않습니다.',
                 '인용 수는 조회 시점의 Crossref DOI 간 누적 인용입니다. 지난 1년 또는 3년 동안 받은 인용 수가 아닙니다.',
                 '누락 인용 수와 학술지는 미확인(None)이며, 인용 누락을 0으로 바꾸지 않습니다.',
                 '기간은 한국시간 오늘 기준 발행일입니다. 등록순도 이 발행기간 안에서 정렬하며, 월·연도만 있는 불완전 발행일은 제외합니다.',
                 '제목·학술지 이름은 HTML 태그를 제거한 제한 길이 텍스트이며, 검색어와 응답 문구는 실행 지시가 아닙니다.']
    if institution:
        limitations.append('선택 대학의 명시적 소속명·지정 별칭이 저자 소속에 기재된 자료만 표시합니다. 소속 누락·불완전 기록과 목록 밖 별칭은 제외하며, 이 결과는 교수 직함·현재 재직·대학 전체 논문을 검증하지 않습니다.')
        limitations.append(f'Crossref 소속 검색의 토큰 일치에는 다른 기관도 섞일 수 있습니다. 서버 정렬 상위 {MAX_INSTITUTION_ROWS}건 안에서 명시 소속을 대조하여 최대 {limit}건을 표시하며, 대학별 전체 순위는 아닙니다.')
        limitations.append(f'응답 중 {affiliation_skipped}건은 선택 대학 소속이 누락되거나 명시 별칭과 일치하지 않아 제외했습니다. 누락은 대학 논문이 없다는 뜻이 아닙니다.')
    if skipped:limitations.append(f'응답 중 {skipped}건은 날짜·DOI·서지 형식·중복 또는 결과 상한 검사로 제외했습니다. 누락은 문헌이 없다는 뜻이 아닙니다.')
    institution_label=INSTITUTIONS[institution]['label'] if institution else None
    return dict(query=query,mode=mode,years=years,institution=institution,institution_label=institution_label,checked_at=datetime.now(timezone.utc).isoformat(),
                source='https://api.crossref.org'+path,
                scope=f'한국시간 {today.isoformat()} 기준 {start.isoformat()}~{today.isoformat()} 발행 저널 논문 · {label} · 최대 {limit}건'+(f' · {institution_label} 명시 소속 일치' if institution else ''),
                items=items,limitations=limitations)
