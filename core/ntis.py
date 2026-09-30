"""Read-only NTIS public national R&D project metadata search."""
import http.client
import os
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

from core.research_tasks import SECRET_PATTERN

HOST = 'www.ntis.go.kr'
PATH = '/rndopen/openApi/public_project'
MAX_BYTES = 1024 * 1024


class NTISError(ValueError):
    def __init__(self, code):
        self.code = 'NTIS_' + code
        super().__init__(self.code)


def _api_key():
    key = os.environ.get('NTIS_API_KEY')
    if key is None:
        streamlit = sys.modules.get('streamlit')
        if streamlit is not None:
            try:
                key = streamlit.secrets['ntis']['api_key']
            except Exception:
                key = None
    if not key:
        raise NTISError('NOT_CONFIGURED')
    if not isinstance(key, str) or not 1 <= len(key) <= 512 or not key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise NTISError('INVALID_KEY')
    return key


def _plain(value, max_length):
    value = ' '.join((value or '').split())
    if len(value) > max_length or SECRET_PATTERN.search(value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise NTISError('INVALID_RESPONSE')
    return value


def _parse(raw, key, limit):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper() or key.encode('ascii') in raw:
        raise NTISError('INVALID_RESPONSE')
    try:
        root = ET.fromstring(raw)
        if root.tag != 'RESULT':
            raise ValueError()
        count = int(root.findtext('TOTALHITS', ''))
        if count < 0:
            raise ValueError()
        resultset = root.find('RESULTSET')
        if resultset is None:
            raise ValueError()
        items = []
        for hit in resultset.findall('HIT')[:limit]:
            title = _plain(hit.findtext('ProjectTitle/Korean'), 400)
            if not title:
                continue
            items.append({
                'title': title,
                'project_number': _plain(hit.findtext('ProjectNumber'), 100),
                'project_year': _plain(hit.findtext('ProjectYear'), 20),
                'period_start': _plain(hit.findtext('ProjectPeriod/Start'), 30),
                'period_end': _plain(hit.findtext('ProjectPeriod/End'), 30),
                'institution': _plain(hit.findtext('ResearchAgency/Name'), 200),
                'ministry': _plain(hit.findtext('Ministry/Name'), 200),
            })
        return {'total_count': count, 'items': items, 'source': 'https://www.ntis.go.kr/rndopen/api/mng/apiMain.do'}
    except NTISError:
        raise
    except (ET.ParseError, TypeError, ValueError):
        raise NTISError('INVALID_RESPONSE') from None


def search_projects(keyword, limit=3):
    if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 200 or SECRET_PATTERN.search(keyword) or any(ord(c) < 32 or ord(c) == 127 for c in keyword):
        raise NTISError('INVALID_QUERY')
    if type(limit) is not int or not 1 <= limit <= 10:
        raise NTISError('INVALID_LIMIT')
    key = _api_key()
    if key in keyword:
        raise NTISError('INVALID_QUERY')
    path = PATH + '?' + urlencode({
        'apprvKey': key, 'collection': 'project', 'SRWR': keyword.strip(),
        'startPosition': 1, 'displayCnt': limit,
    })
    connection = None
    try:
        connection = http.client.HTTPSConnection(HOST, timeout=20)
        connection.request('GET', path, headers={'Accept': 'application/xml', 'User-Agent': 'NAIS-NTIS/105'})
        response = connection.getresponse()
        if response.status != 200:
            raise NTISError('HTTP_ERROR')
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise NTISError('RESPONSE_TOO_LARGE')
        return _parse(raw, key, limit)
    except NTISError:
        raise
    except TimeoutError:
        raise NTISError('TIMEOUT') from None
    except Exception:
        raise NTISError('SOURCE_UNAVAILABLE') from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
