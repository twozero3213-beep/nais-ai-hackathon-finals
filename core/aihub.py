"""case95 AI Hub metadata adapter; stdlib HTTPS, no downloads or document fetches.

Official protocol reference: https://github.com/aihub-git/AIHub-MCP
Written independently; no official server implementation copied.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import http.client
import os
import re
import sys
from urllib.parse import parse_qs, urlencode, urlsplit

from core.research_corpus import strict_json
from core.research_tasks import SECRET_PATTERN

MAX_RESPONSE_BYTES=2*1024*1024
HOST='aihub.or.kr'
CODES={'NOT_CONFIGURED','INVALID_KEY','INVALID_QUERY','INVALID_OPTIONS','INVALID_ID','INVALID_REQUEST','HTTP_ERROR','RESPONSE_TOO_LARGE','INVALID_RESPONSE','SOURCE_UNAVAILABLE','TIMEOUT','SERVER_REJECTED'}
LIMITATIONS=[
    'AI Hub 데이터셋 메타데이터입니다. 원문·설명서·데이터 파일을 가져오거나 내려받지 않습니다.',
    '조회수·다운로드 수는 데이터셋의 현재 누적 이용 지표이며 개별 논문 인용 수·인기 순위가 아닙니다.',
    '접근·이용 신청·라이선스·재배포 허가는 미확인(approval_unknown)입니다. 메타데이터 조회 성공으로 승인하지 않습니다.',
    '검색은 제목·설명 등의 조건 조회이며 정확한 이름 일치·관련성·전체 문헌 범위를 보장하지 않습니다.',
]


class AIHubError(ValueError):
    # case95 2026-09-29 / 오류→비밀없는코드 / 검증: FAIL본문·네트워크오류원문출력0.
    def __init__(self,code):
        self.code='AIHUB_'+(code if code in CODES else 'SOURCE_UNAVAILABLE')
        super().__init__(self.code)


# case95 2026-09-29 / env·이미로드된Streamlit→비공개키 / 검증: 미설정·제어문자·키네트워크전차단.
def _api_key():
    key=os.environ.get('AIHUB_API_KEY')
    if key is None:
        streamlit=sys.modules.get('streamlit')
        if streamlit is not None:
            try:key=streamlit.secrets['aiHub']['api_key']
            except Exception:key=None
    if key is None or key=='':raise AIHubError('NOT_CONFIGURED')
    if not isinstance(key,str) or not 1<=len(key)<=512 or any(ord(c)<33 or ord(c)>126 for c in key):
        raise AIHubError('INVALID_KEY')
    return key


def _keyword(value):
    if not isinstance(value,str) or not value.strip() or len(value)>300 or any(ord(c)<32 or ord(c)==127 for c in value) or SECRET_PATTERN.search(value):
        raise AIHubError('INVALID_QUERY')
    return value.strip()


def _id(value):
    if type(value) is not int or not 1<=value<10**10:raise AIHubError('INVALID_ID')
    return value


# case95 2026-09-29 / 고정공식GET→30초·2MiB엄격JSON / 검증: 감사headers·redirect0·errorbody0·재시도0.
def _request(path,tool):
    expected={'getDataSet':'/mcp/dataSetDetail.do?','searchDataSets':'/mcp/dataSetList.do?'}
    if tool not in expected or not isinstance(path,str) or not path.startswith(expected[tool]) or len(path)>4000 or any(ord(c)<32 or ord(c)==127 for c in path):
        raise AIHubError('INVALID_REQUEST')
    key=_api_key();connection=None
    try:
        connection=http.client.HTTPSConnection(HOST,timeout=30)
        connection.request('GET',path,headers={'Accept':'application/json','User-Agent':'NAIS-AIHub/95','X-API-KEY':key,'X-MCP-Client':'NAIS','X-MCP-Tool':tool})
        response=connection.getresponse()
        if response.status!=200:raise AIHubError('HTTP_ERROR')
        raw=response.read(MAX_RESPONSE_BYTES+1)
        if len(raw)>MAX_RESPONSE_BYTES:raise AIHubError('RESPONSE_TOO_LARGE')
        # Even a UUID-like key not caught by generic secret patterns cannot reach UI.
        if key.encode('ascii') in raw:raise AIHubError('INVALID_RESPONSE')
        try:
            parsed=strict_json(raw)
            pending=[parsed];nodes=0
            while pending:
                value=pending.pop();nodes+=1
                if nodes>100000:raise ValueError()
                if isinstance(value,str) and key in value:raise ValueError()
                if isinstance(value,dict):pending.extend(value.keys());pending.extend(value.values())
                elif isinstance(value,list):pending.extend(value)
            return parsed
        except Exception:raise AIHubError('INVALID_RESPONSE') from None
    except AIHubError:raise
    except TimeoutError:raise AIHubError('TIMEOUT') from None
    except Exception:raise AIHubError('SOURCE_UNAVAILABLE') from None
    finally:
        if connection is not None:
            try:connection.close()
            except Exception:pass


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]

    def handle_data(self,value):
        self.parts.append(value)


def _plain(value,limit):
    if not isinstance(value,str) or len(value)>8000:raise AIHubError('INVALID_RESPONSE')
    parser=_Text();parser.feed(value);parser.close()
    value=' '.join(''.join(parser.parts).split())
    if not value or SECRET_PATTERN.search(value) or any(ord(c)<32 or ord(c)==127 for c in value):raise AIHubError('INVALID_RESPONSE')
    return value[:limit]


def _value(row,name,required=False):
    wrapped=row.get(name)
    if wrapped is None and not required:return None
    if not isinstance(wrapped,dict) or 'value' not in wrapped:raise AIHubError('INVALID_RESPONSE')
    return wrapped['value']


def _number(value):
    if value is None:return None
    if isinstance(value,str) and value.isascii() and value.isdigit() and len(value)<=13:value=int(value)
    if type(value) is not int or not 0<=value<=10**12:raise AIHubError('INVALID_RESPONSE')
    return value


# case95 2026-09-29 / 공개값allowlist→plain카드 / 검증: 원문·이메일·파일목록반환0·None유지·DOI오인0.
def _metadata(row):
    if not isinstance(row,dict):raise AIHubError('INVALID_RESPONSE')
    identifier=_number(_value(row,'dataSetSn',True))
    try:_id(identifier)
    except AIHubError:raise AIHubError('INVALID_RESPONSE') from None
    title=_plain(_value(row,'dataNm',True),600)
    domain=_value(row,'dataRealmNm');domain=_plain(domain,200) if domain is not None else None
    year=_number(_value(row,'dataCnstcYear'))
    if year is not None and not 1900<=year<=datetime.now(timezone.utc).year:raise AIHubError('INVALID_RESPONSE')
    url=_value(row,'url',True)
    if not isinstance(url,str) or len(url)>1500 or SECRET_PATTERN.search(url) or any(ord(c)<33 or ord(c)==127 for c in url):raise AIHubError('INVALID_RESPONSE')
    try:
        parsed=urlsplit(url)
        params=parse_qs(parsed.query,strict_parsing=True,max_num_fields=10)
        if parsed.scheme!='https' or parsed.netloc not in {'aihub.or.kr','www.aihub.or.kr'} or parsed.path!='/aihubdata/data/view.do' or parsed.fragment:
            raise ValueError()
        if set(params)-{'currMenu','topMenu','aihubDataSe','dataSetSn'} or len(params.get('dataSetSn',[]))!=1 or params['dataSetSn'][0]!=str(identifier):raise ValueError()
        if any(len(values)!=1 or SECRET_PATTERN.search(values[0]) or any(ord(c)<32 or ord(c)==127 for c in values[0]) for values in params.values()):raise ValueError()
    except Exception:raise AIHubError('INVALID_RESPONSE') from None
    return dict(id=identifier,title=title,url=url,domain=domain,year=year,views=_number(_value(row,'rdcnt')),download_count=_number(_value(row,'dwldCnt')),access='approval_unknown')


def _data(response):
    if not isinstance(response,dict) or not isinstance(response.get('result'),str):raise AIHubError('INVALID_RESPONSE')
    result=response['result'].strip().upper()
    if result=='FAIL':raise AIHubError('SERVER_REJECTED')
    if result!='SUCCESS' or not isinstance(response.get('data'),dict):raise AIHubError('INVALID_RESPONSE')
    return response['data']


def _base(path):
    return dict(source='https://'+HOST+path,checked_at=datetime.now(timezone.utc).isoformat(),access='approval_unknown',limitations=list(LIMITATIONS))


# case95 2026-09-29 / 정수ID→단일메타 / 검증: 실제공개261409bytes응답의오프라인투영·ID결속.
def get_dataset(identifier):
    identifier=_id(identifier)
    path='/mcp/dataSetDetail.do?'+urlencode({'dataSetSn':identifier})
    data=_data(_request(path,'getDataSet'))
    try:item=_metadata(data['주요 정보'])
    except AIHubError:raise
    except Exception:raise AIHubError('INVALID_RESPONSE') from None
    if item['id']!=identifier:raise AIHubError('INVALID_RESPONSE')
    return dict(_base(path),item=item)


# case95 2026-09-29 / 질문·상한→최대10공개메타 / 검증: 원시search프로브·과대/중복·비밀질문.
def search_datasets(keyword,limit=5):
    keyword=_keyword(keyword)
    if type(limit) is not int or not 1<=limit<=10:raise AIHubError('INVALID_OPTIONS')
    path='/mcp/dataSetList.do?'+urlencode({'searchKeyword':keyword,'recordCountPerPage':limit,'firstIndex':0})
    response=_request(path,'searchDataSets');data=_data(response)
    try:
        rows=data['list']['value']
        if not isinstance(rows,list) or len(rows)>limit:raise ValueError()
        items=[_metadata(row) for row in rows]
        if len({item['id'] for item in items})!=len(items):raise ValueError()
        total_count=response.get('totalCount')
        total_count=_number(total_count['총 개수']) if total_count is not None else None
        if total_count is not None and total_count<len(items):raise ValueError()
    except AIHubError:raise
    except Exception:raise AIHubError('INVALID_RESPONSE') from None
    return dict(_base(path),query=keyword,total_count=total_count,items=items)
