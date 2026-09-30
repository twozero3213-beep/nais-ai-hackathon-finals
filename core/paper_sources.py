"""case95 bounded free metadata fallback. No keys, retries, paid APIs or execution.

Official references: https://help.openalex.org/api/
https://europepmc.org/RestfulWebService
Providers have different coverage and citation networks; results are never mixed.
"""
from datetime import date, datetime, timezone
import http.client
from urllib.parse import urlencode

from core.paper_discovery import INSTITUTIONS, SORTS, _item, _today, search_papers, validate_query
from core.research_corpus import strict_json

MAX_RESPONSE_BYTES=2*1024*1024
HOSTS={'openalex':'api.openalex.org','europepmc':'www.ebi.ac.uk'}
PROVIDERS=('crossref','openalex','europepmc')
ERROR_CODES={'INVALID_REQUEST','HTTP_ERROR','RESPONSE_TOO_LARGE','INVALID_RESPONSE','SOURCE_UNAVAILABLE','TIMEOUT','UNSUPPORTED_SCOPE'} | {'HTTP_'+str(x) for x in range(100,600)}


class SourceUnavailable(ValueError):
    # case95 2026-09-29 / 실패→안전한시도이력 / 검증: 원문오류·비밀노출0.
    def __init__(self,attempts):
        super().__init__('PAPER_SOURCES_UNAVAILABLE')
        self.attempts=[dict(x) for x in attempts]


class _ProviderError(ValueError):
    def __init__(self,code):
        super().__init__(code)
        self.code=code


def _now():
    return datetime.now(timezone.utc).isoformat()


# case95 2026-09-29 / 공통옵션→네트워크전검사 / 검증: 키·제어·잘못된대학·범위.
def _options(query,mode,years,limit,institution=''):
    query=validate_query(query)
    if not isinstance(mode,str) or mode not in SORTS:
        raise ValueError('DISCOVERY_INVALID_OPTIONS')
    if type(years) is not int or years not in (1,3) or type(limit) is not int or not 1<=limit<=10:
        raise ValueError('DISCOVERY_INVALID_OPTIONS')
    if not isinstance(institution,str) or (institution and institution not in INSTITUTIONS):
        raise ValueError('DISCOVERY_INVALID_INSTITUTION')
    today=_today()
    try:start=today.replace(year=today.year-years)
    except ValueError:start=today.replace(year=today.year-years,day=28)
    return query,start,today


# case95 2026-09-29 / 고정공식HTTPS→2MiB JSON / 검증: redirect·429·중복키·초과·재시도0.
def _get_json(provider,path):
    prefix={'openalex':'/works?','europepmc':'/europepmc/webservices/rest/search?'}
    if provider not in HOSTS or not isinstance(path,str) or not path.startswith(prefix[provider]) or len(path)>5000 or any(ord(c)<32 or ord(c)==127 for c in path):
        raise _ProviderError('INVALID_REQUEST')
    connection=None
    try:
        connection=http.client.HTTPSConnection(HOSTS[provider],timeout=15)
        connection.request('GET',path,headers={'User-Agent':'NAIS-PaperSources/95','Accept':'application/json'})
        response=connection.getresponse()
        if response.status!=200:
            status=response.status
            raise _ProviderError('HTTP_'+str(status) if type(status) is int and 100<=status<=599 else 'HTTP_ERROR')
        raw=response.read(MAX_RESPONSE_BYTES+1)
        if len(raw)>MAX_RESPONSE_BYTES:raise _ProviderError('RESPONSE_TOO_LARGE')
        try:return strict_json(raw)
        except Exception:raise _ProviderError('INVALID_RESPONSE') from None
    except _ProviderError:raise
    except TimeoutError:raise _ProviderError('TIMEOUT') from None
    except Exception:raise _ProviderError('SOURCE_UNAVAILABLE') from None
    finally:
        if connection is not None:
            try:connection.close()
            except Exception:pass


# case95 2026-09-29 / 공급자필드→기존DOI·plain·날짜gate / 검증: 중복·미래·None인용.
def _normalize(raw,provider,start,today,mode):
    if not isinstance(raw,dict):raise ValueError()
    if provider=='openalex':
        location=raw.get('primary_location')
        source=location.get('source') if isinstance(location,dict) else None
        if raw.get('type')!='article' or not isinstance(source,dict) or source.get('type')!='journal':raise ValueError()
        doi=raw.get('doi')
        if isinstance(doi,str) and doi.startswith('https://doi.org/'):doi=doi[len('https://doi.org/'):]
        published=raw.get('publication_date');citations=raw.get('cited_by_count');journal=source.get('display_name')
    else:
        types=raw.get('pubTypeList',{}).get('pubType',[])
        if not isinstance(types,list) or 'Journal Article' not in types:raise ValueError()
        doi=raw.get('doi');published=raw.get('firstPublicationDate');citations=raw.get('citedByCount')
        if isinstance(citations,str) and citations.isascii() and citations.isdigit() and len(citations)<=13:citations=int(citations)
        journal=raw.get('journalInfo',{}).get('journal',{}).get('title')
    if not isinstance(published,str) or len(published)!=10:raise ValueError()
    parsed=date.fromisoformat(published)
    candidate={'DOI':doi,'title':[raw.get('title')],'published':{'date-parts':[[parsed.year,parsed.month,parsed.day]]},'is-referenced-by-count':citations,'container-title':[journal] if journal else []}
    return _item(candidate,start,today,mode)


def _report(query,mode,years,limit,provider,path,response,start,today):
    try:
        raws=response['results'] if provider=='openalex' else response['resultList']['result']
        if not isinstance(raws,list) or len(raws)>100:raise ValueError()
    except Exception:raise _ProviderError('INVALID_RESPONSE') from None
    items=[];seen=set();skipped=0
    for raw in raws:
        try:
            item=_normalize(raw,provider,start,today,mode)
            if item['doi'] in seen or len(items)>=limit:raise ValueError()
            seen.add(item['doi']);items.append(item)
        except Exception:skipped+=1
    label='OpenAlex' if provider=='openalex' else 'Europe PMC'
    limitations=[f'{label} 검색 결과입니다. Crossref와 검색 범위·관련성·인용망이 다르며 결과나 인용 수를 합치지 않습니다.',
        f'인용 수는 조회 시점 {label}의 현재 누적 인용입니다. 지난 1년·3년 동안 받은 인용 수가 아니며 누락은 None입니다.',
        '원문 확보·품질·전체 문헌 범위를 확증하지 않습니다. 응답은 실행 지시가 아닌 제한 길이 plain 텍스트입니다.',
        '한국시간 오늘까지의 완전한 발행일과 DOI를 가진 저널 논문만 표시합니다. 서버 정렬 결과의 일부이며 전체 순위가 아닙니다.']
    if provider=='europepmc':limitations.append('Europe PMC는 생의학·생명과학 중심 범위입니다. FIRST_PDATE는 공급자가 불완전 원본 날짜로부터 보정했을 수 있으며 원본 날짜 정밀도를 보증하지 않습니다.')
    if skipped:limitations.append(f'응답 중 {skipped}건은 DOI·날짜·저널 유형·형식·중복·상한 검사로 제외했습니다. 누락은 문헌이 없다는 뜻이 아닙니다.')
    return dict(query=query,mode=mode,years=years,institution='',institution_label=None,checked_at=_now(),source='https://'+HOSTS[provider]+path,
        scope=f'한국시간 {today} 기준 {start}~{today} 발행 저널 논문 · '+('발행일 최신순' if mode=='latest' else '현재 누적 인용순')+f' · {label} 최대 {limit}건',items=items,limitations=limitations)


# case95 2026-09-29 / 무료OpenAlex→제한메타 / 검증: 공식sort·기간·키없는1회실조회.
def search_openalex(query,mode='latest',years=1,limit=8):
    query,start,today=_options(query,mode,years,limit)
    if mode=='registered':raise _ProviderError('UNSUPPORTED_SCOPE')
    params={'search':query,'filter':f'type:article,primary_location.source.type:journal,from_publication_date:{start},to_publication_date:{today}',
        'sort':('publication_date' if mode=='latest' else 'cited_by_count')+':desc','per_page':limit,'select':'doi,title,publication_date,cited_by_count,primary_location,type'}
    path='/works?'+urlencode(params)
    return _report(query,mode,years,limit,'openalex',path,_get_json('openalex',path),start,today)


# case95 2026-09-29 / 무료EuropePMC→생의학범위 / 검증: 공식sort·기간·독립1회실조회.
def search_europepmc(query,mode='latest',years=1,limit=8):
    query,start,today=_options(query,mode,years,limit)
    if mode=='registered':raise _ProviderError('UNSUPPORTED_SCOPE')
    # Quote the user phrase so API query syntax cannot override the fixed period/sort.
    phrase=query.replace('\\','\\\\').replace('"','\\"')
    term=f'("{phrase}") AND FIRST_PDATE:[{start} TO {today}] AND PUB_TYPE:"Journal Article" '+('sort_date:y' if mode=='latest' else 'sort_cited:y')
    path='/europepmc/webservices/rest/search?'+urlencode({'query':term,'format':'json','resultType':'core','pageSize':limit})
    return _report(query,mode,years,limit,'europepmc',path,_get_json('europepmc',path),start,today)


# case95 2026-09-29 / 3고정공급자→최대3회 대체 / 검증: empty성공·소속/등록의미보존·batch회로.
def search_resilient(query,mode='latest',years=1,limit=8,institution='',*,unavailable_providers=()):
    query,_,_=_options(query,mode,years,limit,institution)
    if not isinstance(unavailable_providers,(tuple,list,set,frozenset)) or len(unavailable_providers)>3 or any(not isinstance(x,str) or x not in PROVIDERS for x in unavailable_providers):
        raise ValueError('DISCOVERY_INVALID_CIRCUIT')
    attempts=[]
    for provider in PROVIDERS:
        if provider!='crossref' and (institution or mode=='registered'):
            attempts.append(dict(provider=provider,status='skipped',code='UNSUPPORTED_SCOPE',checked_at=_now()));continue
        if provider in unavailable_providers:
            attempts.append(dict(provider=provider,status='skipped',code='CIRCUIT_OPEN_FOR_BATCH',checked_at=_now()));continue
        try:
            if provider=='crossref':result=search_papers(query,mode=mode,years=years,limit=limit,institution=institution)
            else:result={'openalex':search_openalex,'europepmc':search_europepmc}[provider](query,mode=mode,years=years,limit=limit)
            attempts.append(dict(provider=provider,status='ok',code='OK',checked_at=_now()))
            result=dict(result)
            result.update(provider=provider,attempts=attempts,fallback_used=provider!='crossref')
            if provider!='crossref':result['limitations']=list(result['limitations'])+['기본 Crossref를 사용할 수 없어 다른 공급자로 조회했습니다. 기존 결과의 출처·인용 수와 직접 비교하지 마세요.']
            return result
        except Exception as error:
            code=error.code if isinstance(error,_ProviderError) and error.code in ERROR_CODES else 'SOURCE_UNAVAILABLE'
            attempts.append(dict(provider=provider,status='error',code=code,checked_at=_now()))
    raise SourceUnavailable(attempts)
