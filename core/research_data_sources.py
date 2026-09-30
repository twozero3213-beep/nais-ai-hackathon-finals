"""Bounded public metadata: fixed HTTPS GETs and Korea read-only search POST."""
from datetime import datetime, timedelta, timezone
import http.client
import ipaddress
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote, urlencode, urlsplit

from core.paper_discovery import _plain, validate_query
from core.research_corpus import strict_json
from core.research_tasks import SECRET_PATTERN

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
COLLECTIONS = ('sentinel-2-l2a', 'sentinel-2-c1-l2a', 'landsat-c2-l2')
INDICATORS = ('SP.POP.TOTL', 'NY.GDP.MKTP.CD', 'SP.DYN.LE00.IN')
INDICATOR_UNITS = {'SP.POP.TOTL': 'persons', 'NY.GDP.MKTP.CD': 'current US$', 'SP.DYN.LE00.IN': 'years'}
REGIONS = {'global': None, 'korea': (124, 33, 132, 39)}
# [수정: 0 이영 · Codex] 2026-10-01 00:05 KST — 외부 Data.gov API 주소·허용 prefix·표시명을 함께 복구한다.
SOURCES = {
    'kci': ('KCI 국내 학술논문', 'datasets', 'open.kci.go.kr', '/po/openapi/openApiSearch.kci', 'https://www.kci.go.kr/kciportal/po/openapi/openApiConnSamp.kci'),
    'aida': ('KISTI AIDA 연구 데이터', 'datasets', 'aida.kisti.re.kr', '/openapi/data', 'https://aida.kisti.re.kr/about/openapi'),
    'nasa_cmr': ('NASA CMR', 'satellite', 'cmr.earthdata.nasa.gov', '/search/collections.json', 'https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html'),
    'earth_search': ('Earth Search · Sentinel/Landsat', 'satellite', 'earth-search.aws.element84.com', '/v1', 'https://element84.com/earth-search/examples'),
    'world_bank': ('World Bank', 'statistics', 'api.worldbank.org', '/v2', 'https://datahelpdesk.worldbank.org/knowledgebase/articles/889392'),
    'usgs': ('USGS 지진 관측', 'satellite', 'earthquake.usgs.gov', '/fdsnws/event/1/query', 'https://earthquake.usgs.gov/fdsnws/event/1/1'),
    'datacite': ('DataCite 연구 데이터 DOI', 'datasets', 'api.datacite.org', '/dois', 'https://support.datacite.org/docs/api'),
    'data_gov': ('미국 Data.gov v4', 'public', 'api.gsa.gov', '/technology/datagov/v4/search', 'https://resources.data.gov/catalog-api/'),
    'korea_data': ('한국 공공데이터포털 검색 서비스', 'public', 'api.odcloud.kr', '/api/GetSearchDataList/v1/searchData', 'https://www.data.go.kr/data/15112888/openapi.do'),
}
FILTERS = {s: {'catalog': ['query', 'limit']} for s in SOURCES}
FILTERS['earth_search']['items'] = ['collection', 'region', 'days', 'limit']
FILTERS['world_bank']['observations'] = ['indicator', 'limit']
FILTERS['usgs'] = {'catalog': ['region', 'days', 'limit']}
NOTICE = '일부 공개 메타데이터/관측값 표본입니다. 검색어는 해당 출처로 전송됩니다. 전체 데이터·원영상·이용 승인·연구 결론 검증이 아닙니다.'


class DataSourceError(ValueError):
    def __init__(self, code):
        self.code = code if code in {'HTTP_ERROR', 'TIMEOUT', 'UNAVAILABLE', 'INVALID_RESPONSE', 'RESPONSE_TOO_LARGE', 'INVALID_KEY', 'AUTH_REQUIRED', 'PERMISSION_DENIED', 'RATE_LIMITED'} else 'UNAVAILABLE'
        super().__init__('RESEARCH_DATA_' + self.code)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _key(source='data_gov'):
    # case105: reuse the existing env/Streamlit-only credential boundary for Korea.
    variable, setting = {'korea_data': ('KOREA_DATA_API_KEY', 'korea_data_api_key'), 'kci': ('KCI_API_KEY', 'kci_api_key'), 'aida': ('AIDA_API_KEY', 'aida_api_key')}.get(source, ('DATA_GOV_API_KEY', 'data_gov_api_key'))
    value = os.environ.get(variable)
    if value is None:
        st = sys.modules.get('streamlit')
        if st is not None:
            try: value = st.secrets['public_data'][setting]
            except Exception: value = None
    if not value: return None
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in value) or value.upper() == 'DEMO_KEY':
        raise DataSourceError('INVALID_KEY')
    value = unquote(value) if source == 'korea_data' else value
    if any(ord(c) < 33 or ord(c) > 126 for c in value): raise DataSourceError('INVALID_KEY')
    return value


def source_catalog():
    """Configuration status only; PUBLIC does not assert a live lookup succeeded."""
    configured = {}
    for source in ('data_gov', 'korea_data', 'kci', 'aida'):
        try: configured[source] = bool(_key(source))
        except DataSourceError: configured[source] = False
    return [dict(id=s, name=v[0], label=v[0], category=v[1],
                 status=('CONFIGURED' if configured[s] else 'NEEDS_KEY') if s in configured else 'PUBLIC',
                 url=v[4] if s == 'korea_data' else 'https://' + v[2] + v[3], docs_url=v[4], modes=list(FILTERS[s]),
                 supported_filters={k: list(x) for k, x in FILTERS[s].items()},
                 notice=('공공데이터포털 목록 검색입니다. 설정된 키의 서비스 권한은 조회 시 확인합니다. 원자료 다운로드·기관별 API 이용승인과 별개입니다.' if s == 'korea_data' else NOTICE))
            for s, v in SOURCES.items()]


def _request(source, path, key=None, body=None):
    prefixes = {'nasa_cmr': ('/search/collections.json?',), 'earth_search': ('/v1/collections', '/v1/search?'),
                'world_bank': ('/v2/indicator?', '/v2/country/KOR/indicator/'),
                'usgs': ('/fdsnws/event/1/query?',), 'datacite': ('/dois?',),
                'data_gov': ('/technology/datagov/v4/search?',), 'korea_data': ('/api/GetSearchDataList/v1/searchData',),
                'kci': ('/po/openapi/openApiSearch.kci?',), 'aida': ('/openapi/data?',)}
    if source not in prefixes or not isinstance(path, str) or not path.startswith(prefixes[source]) or len(path) > 4000 or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise ValueError('RESEARCH_DATA_INVALID_REQUEST')
    # case105: official Swagger supports POST-only read-only search; fixed path/body.
    if source == 'korea_data':
        if path != SOURCES[source][3] or not key or not isinstance(body, dict) or set(body) - {'page', 'size', 'dataType', 'keyword'} or type(body.get('page')) is not int or body['page'] != 1 or type(body.get('size')) is not int or not 1 <= body['size'] <= 10 or body.get('dataType') != ['FILE', 'API', 'STD']:
            raise ValueError('RESEARCH_DATA_INVALID_REQUEST')
        if 'keyword' in body:
            validate_query(body['keyword'])
            if re.search(r'(?:https?://|file:|localhost|service.?key\s*[=:]|Infuser\s+)', body['keyword'], re.I): raise ValueError('RESEARCH_DATA_INVALID_QUERY')
    elif body is not None: raise ValueError('RESEARCH_DATA_INVALID_REQUEST')
    connection = None
    try:
        connection = http.client.HTTPSConnection(SOURCES[source][2], timeout=15)
        headers = {'Accept': 'application/json', 'User-Agent': 'NAIS-ResearchData/100'}
        if source == 'korea_data':
            headers.update({'Authorization': 'Infuser ' + key, 'Content-Type': 'application/json'})
            connection.request('POST', path, body=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=headers)
        else:
            if key and source not in ('kci', 'aida'): headers['X-Api-Key'] = key
            if source == 'kci': headers['Accept'] = 'application/xml'
            connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            code = {401: 'AUTH_REQUIRED', 403: 'PERMISSION_DENIED', 429: 'RATE_LIMITED'}.get(response.status, 'HTTP_ERROR')
            raise DataSourceError(code)
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES: raise DataSourceError('RESPONSE_TOO_LARGE')
        if source == 'kci':
            # KCI echoes the credential in inputData; discard it before any output.
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper() or b'\x00' in raw:
                raise DataSourceError('INVALID_RESPONSE')
            try:
                root = ET.fromstring(raw)
                output = root.find('outputData')
                if root.tag != 'MetaData' or output is None or output.find('result/total') is None:
                    raise ValueError()
                clean = ET.tostring(output, encoding='utf-8')
                if key and (key.encode('ascii') in clean or key in unquote(clean.decode('utf-8'))): raise ValueError()
                return output
            except Exception: raise DataSourceError('INVALID_RESPONSE') from None
        if key and key.encode('ascii') in raw: raise DataSourceError('INVALID_RESPONSE')
        try:
            data = strict_json(raw)
            pending = [data]; nodes = 0
            while pending:
                item = pending.pop(); nodes += 1
                if nodes > 100000: raise ValueError()
                if isinstance(item, float) and not math.isfinite(item): raise ValueError()
                # case105: reuse reflection guard, including URL-encoded credentials.
                if isinstance(item, str) and key and (key in item or key in unquote(item)): raise ValueError()
                if isinstance(item, dict): pending.extend(item); pending.extend(item.values())
                elif isinstance(item, list): pending.extend(item)
            return data
        except Exception: raise DataSourceError('INVALID_RESPONSE') from None
    except DataSourceError: raise
    except TimeoutError: raise DataSourceError('TIMEOUT') from None
    except Exception: raise DataSourceError('UNAVAILABLE') from None
    finally:
        if connection is not None:
            try: connection.close()
            except Exception: pass


def _text(value, limit=1200):
    if value in (None, ''): return 'unknown'
    if type(value) in (int, float): value = str(value)
    # case105: complement the reused plain guard with the portal credential names.
    if isinstance(value, str) and re.search(r'(?:service.?key\s*[=:]|Infuser\s+)\S+', value, re.I): raise DataSourceError('INVALID_RESPONSE')
    return _plain(value, limit)


def _url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) <= 32 or ord(c) == 127 for c in value) or SECRET_PATTERN.search(value): return ''
    try:
        decoded = unquote(value)
        if any(ord(c) < 32 or ord(c) == 127 for c in decoded) or SECRET_PATTERN.search(decoded): return ''
        parts = urlsplit(value)
        host = parts.hostname or ''
        if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None, 443) or '.' not in host or host.lower().endswith(('.local', '.localhost')): return ''
        try:
            if not ipaddress.ip_address(host).is_global: return ''
        except ValueError:
            if re.fullmatch(r'[0-9.]+', host): return ''
        if re.search(r'(?:key|token|api.?key|service.?key|authorization|secret|password|signature)=', unquote(parts.query), re.I): return ''
        return value
    except ValueError: return ''


def _link(row, relation):
    return next((_url(x.get('href')) for x in row.get('links', []) if isinstance(x, dict) and x.get('rel') == relation and _url(x.get('href'))), '')


def _card(source, checked, id, title, url='', description=None, license=None, access=None, temporal=None, spatial=None, data_kind='metadata', **extra):
    return dict(id=_text(id, 300), title=_text(title, 500), source=source, url=_url(url),
                description=_text(description), license=_text(license, 500), access=_text(access, 300),
                temporal=_text(temporal, 500), spatial=_text(spatial, 500), checked_at=checked, data_kind=data_kind, **extra)


def _rows(value):
    if not isinstance(value, list) or len(value) > 1000 or any(not isinstance(x, dict) for x in value): raise DataSourceError('INVALID_RESPONSE')
    return value


def search_research_data(source, query='', limit=5, *, mode='catalog', collection='sentinel-2-l2a', region='global', indicator='SP.POP.TOTL', days=7):
    """No user URLs, arbitrary countries, precise coordinates, downloads or paid calls."""
    if not isinstance(source, str) or source not in SOURCES: raise ValueError('RESEARCH_DATA_INVALID_SOURCE')
    if not isinstance(query, str): raise ValueError('RESEARCH_DATA_INVALID_QUERY')
    if query: query = validate_query(query)
    if query and re.search(r'(?:https?://|file:|localhost|service.?key\s*[=:]|Infuser\s+)', query, re.I): raise ValueError('RESEARCH_DATA_INVALID_QUERY')
    if type(limit) is not int or not 1 <= limit <= 10 or type(days) is not int or not 1 <= days <= 30: raise ValueError('RESEARCH_DATA_INVALID_OPTIONS')
    if not isinstance(mode, str) or mode not in FILTERS[source] or not isinstance(region, str) or region not in REGIONS or not isinstance(collection, str) or collection not in COLLECTIONS or not isinstance(indicator, str) or indicator not in INDICATORS: raise ValueError('RESEARCH_DATA_INVALID_OPTIONS')
    if query and 'query' not in FILTERS[source][mode]: raise ValueError('RESEARCH_DATA_UNSUPPORTED_QUERY')
    checked = _now()
    result = dict(source=source, status='OK', checked_at=checked, items=[], error='', notice=NOTICE)
    try:
        key = _key(source) if source in ('data_gov', 'korea_data', 'kci', 'aida') else None
        if source in ('data_gov', 'korea_data', 'kci', 'aida') and key is None:
            result.update(status='NEEDS_KEY', error='NOT_CONFIGURED', notice='공식 안내에서 무료 키/이용신청을 준비하세요. 현재 API 미연결입니다. DEMO_KEY 자동 호출은 하지 않습니다.')
            return result
        params = {}; path = SOURCES[source][3]
        if source == 'nasa_cmr':
            params = {'page_size': limit, 'keyword': query or 'earth science'}
        elif source == 'earth_search':
            path += '/collections' if mode == 'catalog' else '/search'
            if mode == 'items':
                params = {'collections': collection, 'limit': limit, 'datetime': (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() + '/' + checked}
                if REGIONS[region]: params['bbox'] = ','.join(map(str, REGIONS[region]))
        elif source == 'world_bank':
            path += '/indicator' if mode == 'catalog' else '/country/KOR/indicator/' + indicator
            params = {'format': 'json', 'per_page': min(100, limit * 10) if mode == 'catalog' else limit}
            if mode == 'observations': params['mrv'] = limit
        elif source == 'usgs':
            params = {'format': 'geojson', 'limit': limit, 'orderby': 'time', 'starttime': (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()}
            if REGIONS[region]:
                west, south, east, north = REGIONS[region]
                params.update(minlongitude=west, minlatitude=south, maxlongitude=east, maxlatitude=north)
        elif source == 'datacite': params = {'query': query or '*', 'resource-type-id': 'dataset', 'page[size]': limit}
        elif source == 'data_gov': params = {'q': query, 'per_page': limit}
        elif source == 'kci': params = {'key': key, 'apiCode': 'articleSearch', 'title': query or '인공지능', 'page': 1, 'displayCount': 10}
        elif source == 'aida': params = {'key': key, 'page': 0, 'size': limit, 'q': query or '논문'}
        if source == 'korea_data':
            body = {'page': 1, 'size': limit, 'dataType': ['FILE', 'API', 'STD']}
            if query: body['keyword'] = query
            raw = _request(source, path, key, body)
        else: raw = _request(source, path + ('?' + urlencode(params) if params else ''), key)
        cards = []
        if source == 'kci':
            total = raw.findtext('result/total', '')
            if not total.isdigit(): raise DataSourceError('INVALID_RESPONSE')
            rows = raw.findall('record')
            if len(rows) > 100 or (int(total) > 0 and not rows): raise DataSourceError('INVALID_RESPONSE')
            for row in rows[:limit]:
                x = row.find('articleInfo')
                if x is None: raise DataSourceError('INVALID_RESPONSE')
                title = x.findtext("title-group/article-title[@lang='original']")
                if not title or not x.get('article-id'): raise DataSourceError('INVALID_RESPONSE')
                cards.append(_card(source, checked, x.get('article-id'), title, x.findtext('url'),
                    'KCI 논문 제목 검색 결과. 논문 내용의 검증·원문 재배포 승인이 아닙니다.',
                    access='metadata public; data access unknown', temporal=row.findtext('journalInfo/pub-year'),
                    provider=_text(row.findtext('journalInfo/journal-name'), 300)))
            result['notice'] += ' KCI 제목 검색 첫 페이지 최대10건 중 요청 수만 표시합니다. 전체 검색 결과나 인기 순위가 아닙니다.'
        elif source == 'aida':
            for x in _rows(raw['response']['content'])[:limit]:
                cards.append(_card(source, checked, x['id'], x['title'], SOURCES[source][4],
                    x.get('notes'), x.get('license'), 'metadata public; data access unknown',
                    updated_at=_text(x.get('lastModified'), 100)))
            result['notice'] += ' AIDA 데이터셋 목록이며 논문 검색·데이터 다운로드가 아닙니다. 이용조건은 자료별로 확인하세요.'
        elif source == 'nasa_cmr':
            for x in _rows(raw['feed']['entry'])[:limit]:
                cards.append(_card(source, checked, x['id'], x['title'], 'https://search.earthdata.nasa.gov/search?q=' + quote(x['id'], safe=''), x.get('summary'), access='metadata public; data access unknown', temporal=f"{x.get('time_start', 'unknown')} / {x.get('time_end', 'unknown')}", spatial='; '.join(x.get('boxes', []))))
        elif source == 'earth_search':
            rows = _rows(raw['collections' if mode == 'catalog' else 'features'])
            for x in rows:
                if mode == 'catalog' and query and query.casefold() not in (str(x.get('title', '')) + str(x.get('description', ''))).casefold(): continue
                p = x.get('properties', {}); extent = x.get('extent', {})
                cards.append(_card(source, checked, x['id'], x.get('title', x['id']), _link(x, 'self'), x.get('description') or '위성 장면 메타데이터; 원영상 미다운로드', x.get('license') or _link(x, 'license') or None, 'metadata public; asset terms require review', temporal=p.get('datetime') or str(extent.get('temporal', {}).get('interval', 'unknown')), spatial=str(x.get('bbox') or extent.get('spatial', {}).get('bbox', 'unknown'))))
        elif source == 'world_bank':
            if not isinstance(raw, list) or len(raw) != 2: raise DataSourceError('INVALID_RESPONSE')
            rows = [] if raw[1] is None else _rows(raw[1])
            if mode == 'catalog':
                result['notice'] += ' 지표 카탈로그 첫 페이지 최대100건 안의 키워드 대조이며 전체 검색이 아닙니다.'
                for x in rows:
                    if query and query.casefold() not in (str(x.get('name', '')) + str(x.get('sourceNote', ''))).casefold(): continue
                    cards.append(_card(source, checked, x['id'], x['name'], 'https://data.worldbank.org/indicator/' + quote(x['id'], safe=''), x.get('sourceNote'), access='public API metadata'))
            else:
                for x in rows[:limit]:
                    value = x.get('value')
                    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)): raise DataSourceError('INVALID_RESPONSE')
                    cards.append(_card(source, checked, indicator + ':' + x['date'], x['indicator']['value'], 'https://data.worldbank.org/indicator/' + indicator + '?locations=KR', '최신 조회 연도별 한국 관측값. 연도별 누락은 null, 현재 실시간 값이 아닙니다.', access='public API observation', temporal=x['date'], spatial='KOR · 대한민국', data_kind='observation', value=value, unit=_text(x.get('unit') or INDICATOR_UNITS[indicator], 100), unit_source='provider' if x.get('unit') else 'indicator_definition'))
        elif source == 'usgs':
            for x in _rows(raw['features'])[:limit]:
                p = x['properties']; mag = p.get('mag')
                if mag is not None and (type(mag) not in (int, float) or not math.isfinite(mag)): raise DataSourceError('INVALID_RESPONSE')
                cards.append(_card(source, checked, x['id'], p.get('title', x['id']), p.get('url'), 'USGS 지진 이벤트 기록; 자동값은 이후 수정될 수 있습니다.', access='public event observations', temporal=datetime.fromtimestamp(p['time'] / 1000, timezone.utc).isoformat(), spatial=str(x.get('geometry', {}).get('coordinates', 'unknown')), data_kind='observation', value=mag, unit=_text(p.get('magType'), 100)))
        elif source == 'datacite':
            for row in _rows(raw['data'])[:limit]:
                x = row['attributes']
                if x.get('types', {}).get('resourceTypeGeneral') != 'Dataset': raise DataSourceError('INVALID_RESPONSE')
                rights = x.get('rightsList', [])
                cards.append(_card(source, checked, row['id'], x['titles'][0]['title'], 'https://doi.org/' + quote(x['doi'], safe='/'), x.get('descriptions', [{}])[0].get('description') if x.get('descriptions') else None, rights[0].get('rights') or rights[0].get('rightsUri') if rights else None, 'DOI metadata public; dataset access unknown', temporal=x.get('publicationYear')))
        elif source == 'data_gov':
            for x in _rows(raw['results'])[:limit]:
                d = x.get('dcat') or {}
                cards.append(_card(source, checked, x.get('identifier') or d.get('identifier'), x.get('title'), x.get('landingPage') or d.get('landingPage') or ('https://catalog.data.gov/dataset/' + quote(x['slug'], safe='') if x.get('slug') else ''), x.get('description') or d.get('description'), d.get('license'), x.get('accessLevel') or d.get('accessLevel'), d.get('temporal'), d.get('spatial')))
        elif source == 'korea_data':
            code = raw.get('statusCode')
            if code != 200:
                raise DataSourceError({401: 'AUTH_REQUIRED', 403: 'PERMISSION_DENIED', 429: 'RATE_LIMITED'}.get(code, 'INVALID_RESPONSE'))
            # case105: reuse bounded rows/cards; live service returns result object.
            group = raw['result']
            if isinstance(group, list) and len(group) == 1: group = group[0]
            if not isinstance(group, dict): raise DataSourceError('INVALID_RESPONSE')
            for x in _rows(group['data'])[:limit]:
                link = x.get('detailPageUrl')
                if isinstance(link, str) and link.startswith('http://www.data.go.kr/'): link = 'https://' + link[7:]
                cards.append(_card(source, checked, link or x['dataName'], x['dataName'], link,
                    x.get('dataDescription'), access='metadata public; data access unknown',
                    provider=_text(x.get('organization'), 300), updated_at=_text(x.get('updateDate'), 100),
                    provider_license_code=_text(x.get('useScopeCode'), 100)))
            result['notice'] += ' 한국 목록 검색 권한으로 조회했습니다. 이용허락 코드와 수정일은 원제공 목록 정보이며 자료 기간·라이선스 전문은 원제공 페이지에서 확인하세요.'
        result['items'] = cards[:limit]
        if not result['items']: result['status'] = 'EMPTY'
    except DataSourceError as error: result.update(status='ERROR', error=error.code, items=[])
    except Exception: result.update(status='ERROR', error='INVALID_RESPONSE', items=[])
    return result
