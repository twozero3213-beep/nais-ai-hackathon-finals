"""Explicit, free Europe PMC OA lookup. Read-only bounded excerpts; no cache or code execution.

API contract: https://europepmc.org/RestfulWebService (DOI search, OA fullTextXML).
Only explicit Creative Commons licences are accepted; availability is not permission.
"""
import hashlib
from datetime import datetime, timezone
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
import xml.etree.ElementTree as ET

from core.research_corpus import strict_json
from core.research_agent import prepare_evidence

BASE = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 10


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('FULLTEXT_REDIRECT_BLOCKED')


def _read(url):
    """case100: fixed HTTPS host/path, no redirects, bounded transport; no arbitrary URLs."""
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != 'www.ebi.ac.uk'
            or not re.fullmatch(r'/europepmc/webservices/rest/(?:search|PMC\d+/fullTextXML)', parts.path)):
        raise ValueError('FULLTEXT_URL_BLOCKED')
    request = Request(url, headers={'User-Agent': 'NAIS-public-fulltext/100', 'Accept-Encoding': 'identity'})
    with build_opener(_NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
        if response.geturl() != url:
            raise ValueError('FULLTEXT_REDIRECT_BLOCKED')
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError('FULLTEXT_RESPONSE_TOO_LARGE')
    return body


def _doi(value):
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError('INVALID_DOI')
    value = value.strip().lower()
    # Reject search syntax injection as well as URLs. Ordinary DOI punctuation is retained.
    if not re.fullmatch(r'10\.\d{4,9}/[^\s"\\\x00-\x1f]+', value):
        raise ValueError('INVALID_DOI')
    return value


def fetch_selected_fulltext(doi, query=''):
    """Return fresh selected-DOI excerpts or explicit missing status; never previous evidence.

case100: metadata DOI + OA flag + PMCID and XML article IDs + licence must all agree.
Body paragraphs are ranked by query overlap, not interpreted or approved by a model.
"""
    doi = _doi(doi)
    if not isinstance(query, str) or len(query) > 1000:
        raise ValueError('INVALID_SEARCH_INPUT')
    result = dict(status='NOT_AVAILABLE', doi=doi, source='Europe PMC', pmcid=None,
                  source_url=None, license=None, evidence=[], approved=False,
                  limitations=['Europe PMC 생명과학 OA 일부만 조회합니다. 미수집은 논문 부재의 증거가 아닙니다.',
                               '읽기 전용 원문 조각이며 논문 전체 검토·재현·최종 승인이 아닙니다. 재사용은 표시된 라이선스를 확인하세요.'])
    url = BASE + 'search?' + urlencode({'query': f'DOI:"{doi}" AND OPEN_ACCESS:Y',
                                        'format': 'json', 'resultType': 'core', 'pageSize': 10})
    response = strict_json(_read(url))
    rows = response.get('resultList', {}).get('result', [])
    if not isinstance(rows, list) or len(rows) > 10:
        raise ValueError('FULLTEXT_INVALID_METADATA')
    matches = [row for row in rows if isinstance(row, dict)
               and str(row.get('doi', '')).strip().lower() == doi and row.get('isOpenAccess') == 'Y'
               and isinstance(row.get('pmcid'), str) and re.fullmatch(r'PMC\d+', row['pmcid'])]
    if not matches:
        return result
    pmcids = {row['pmcid'] for row in matches}
    if len(pmcids) != 1:
        raise ValueError('FULLTEXT_AMBIGUOUS_DOI')
    pmcid = matches[0]['pmcid']
    xml_url = BASE + pmcid + '/fullTextXML'
    raw = _read(xml_url)
    # ET never resolves external entities; reject internal entities/subsets and exotic encodings.
    xml = raw.decode('utf-8-sig')
    if '<!ENTITY' in xml.upper() or re.search(r'<!DOCTYPE[^>]*\[', xml, re.I):
        raise ValueError('FULLTEXT_UNSAFE_XML')
    try:
        article = ET.fromstring(xml)
    except ET.ParseError:
        raise ValueError('FULLTEXT_INVALID_XML') from None
    if article.tag != 'article':
        raise ValueError('FULLTEXT_INVALID_XML')
    ids = article.findall('./front/article-meta/article-id')
    dois = {str(node.text or '').strip().lower() for node in ids if node.get('pub-id-type') == 'doi'}
    pmcs = {str(node.text or '').strip().removeprefix('PMC') for node in ids
            if node.get('pub-id-type') in {'pmc', 'pmcid'}}
    if dois != {doi} or pmcs != {pmcid[3:]}:
        raise ValueError('FULLTEXT_ID_MISMATCH')
    licence = None
    for node in article.findall('./front/article-meta/permissions/license'):
        # JATS permits the licence URI on <license> or its nested <ext-link>.
        for element in node.iter():
            for value in element.attrib.values():
                if re.fullmatch(r'https?://creativecommons\.org/(?:licenses/(?:by|by-sa|by-nc|by-nd|by-nc-sa|by-nc-nd)/[1-4]\.0|publicdomain/zero/1\.0)/?', value):
                    licence = value
                    break
    result.update(pmcid=pmcid, source_url=xml_url, license=licence,
                  checked_at=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest())
    if not licence:
        result['status'] = 'LICENSE_UNCONFIRMED'
        return result
    tokens = set(re.findall(r'\w+', query.lower()))
    paragraphs = []
    for index, node in enumerate(article.findall('./body//p'), 1):
        text = ''.join(node.itertext()).strip()
        if not text:
            continue
        locator = f'{pmcid} body paragraph {index}'
        paragraphs.append((len(tokens & set(re.findall(r'\w+', text.lower()))), index,
                           dict(id='oa-' + hashlib.sha256((doi+'\n'+locator).encode()).hexdigest()[:20],
                                text=text, doi=doi, locator=locator)))
    # ponytail: deterministic word overlap over <=4MiB; richer ranking only after measured need.
    paragraphs.sort(key=lambda item: (-item[0], item[1]))
    if paragraphs:
        evidence, truncated = prepare_evidence([item[2] for item in paragraphs[:5]])
        result.update(status='EXCERPTS_RETRIEVED', evidence=evidence, truncated=truncated)
    else:
        result['status'] = 'NO_BODY_EXCERPTS'
    return result
