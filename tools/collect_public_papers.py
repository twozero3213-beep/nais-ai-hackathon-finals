"""Public Europe PMC collection; no credentials, paid APIs, or raw-data downloads."""
import argparse
import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = 'https://www.ebi.ac.uk/europepmc/webservices/rest'
EXCLUDED = {'10.32614/rj-2022-020', '10.1371/journal.pone.0090081', '10.1016/j.dss.2009.05.016', '10.1145/3025453.3025912', '10.1371/journal.pone.0286045', '10.1073/pnas.2001283117', '10.1371/journal.pone.0149458', '10.1371/journal.pone.0259711'}
CATEGORIES = {'ecology': '(ecology OR biodiversity)', 'neuroscience': '(neuroscience OR brain)', 'psychology': '(psychology OR behavior)', 'genomics': '(genomics OR genetics)', 'public_health': '(epidemiology OR public health)', 'computational': '(machine learning OR computational)', 'environment': '(climate OR environmental)', 'evolution': '(evolution OR phylogenetic)'}
BASE_QUERY = 'OPEN_ACCESS:Y AND FIRST_PDATE:[2015-01-01 TO 2025-12-31] AND (Dryad OR Figshare OR Zenodo OR "osf.io")'
REPOSITORIES = ('datadryad.org', 'figshare.com', 'zenodo.org', 'osf.io')
BLOCKED = re.compile(r'\b(?:on|upon|by) (?:reasonable )?request\b|not (?:publicly )?available|controlled.access|cannot be (?:publicly )?(?:shared|made available)|restricted access', re.I)


# [작성:전문가4] 2026-09-27 case66 무엇:UTC시각 왜:추적 입력:없음 출력:ISO 검증:timezone.
def utc():
    """작성전문가4 2026-09-27 case66: UTC 시각; 입력 없음→ISO 문자열; timezone 검증."""
    return datetime.now(timezone.utc).isoformat()


# [작성:전문가4] 2026-09-27 case66 무엇:감사로그 왜:실패보존 입력:dict 출력:JSONL 검증:append.
def log(event):
    """작성전문가4 2026-09-27 case66: 실패 포함 감사로그 보존; dict→JSONL; append만 사용."""
    with (ROOT / 'request_log.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'time': utc(), **event}, ensure_ascii=False) + '\n')


# [작성:전문가4] 2026-09-27 case66 무엇:공개GET 왜:원문검증 입력:URL 출력:bytes 검증:200/timeout/retry.
def fetch(url):
    """작성전문가4 2026-09-27 case66: 공개 HTTP GET; URL→bytes; 200·45초·2재시도 검증."""
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'NAIS-PublicResearchCollector/1.0 (metadata verification)'})
            with urllib.request.urlopen(request, timeout=45) as response:
                status = response.status
                payload = response.read()
            if status != 200:
                raise ValueError(f'HTTP {status}')
            log({'url': url, 'status': status, 'attempt': attempt, 'bytes': len(payload)})
            return payload
        except (OSError, ValueError) as error:
            log({'url': url, 'attempt': attempt, 'error': str(error)})
            if attempt == 2:
                return None
            time.sleep(2 ** (attempt + 1))


# [작성:전문가4] 2026-09-27 case66 무엇:텍스트정규화 왜:XML혼합내용 입력:element 출력:str 검증:결측.
def text(node):
    """작성전문가4 2026-09-27 case66: XML 텍스트 정규화; element→str; 결측 안전 처리."""
    return ' '.join(' '.join(node.itertext()).split()) if node is not None else ''


# [작성:전문가4] 2026-09-27 case66 무엇:저장소URL식별 왜:위장호스트제외 입력:URL 출력:bool 검증:정확호스트/DOI경로.
def repository_url(url):
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http', 'https'):
        return False
    return any(host == domain or host.endswith('.' + domain) for domain in REPOSITORIES) or (host in ('doi.org', 'dx.doi.org') and parts.path.lower().startswith(('/10.5061/', '/10.6084/', '/10.5281/', '/10.17605/')))


# [작성:전문가4] 2026-09-27 case66 무엇:선언주소구문검사 왜:출판사잘못된주소격리 입력:URL 출력:오류이유 검증:host/중복scheme.
def declared_url_error(url):
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            return 'MISSING_HTTP_SCHEME_OR_HOSTNAME'
        if len(re.findall(r'https?://', url, re.I)) != 1:
            return 'MULTIPLE_HTTP_SCHEMES_IN_DECLARED_VALUE'
        if re.search(r'\s', url):
            return 'WHITESPACE_IN_DECLARED_VALUE'
    except ValueError:
        return 'URL_PARSE_ERROR'
    return ''


# [작성:전문가4] 2026-09-27 case66 무엇:증거파싱 왜:출처확보 입력:XML/DOI 출력:dict 검증:허가/식별/접근성.
def parse_article(payload, expected_doi):
    """작성전문가4 2026-09-27 case66: 출처·허가·데이터문 검증; XML/DOI→dict; 참조문헌 링크 제외."""
    root = ET.fromstring(payload)
    meta = root.find('./front/article-meta')
    if meta is None:
        raise ValueError('missing_article_meta')
    if not text(root.find('./body')):
        raise ValueError('missing_article_body')
    dois = {text(n).lower().removeprefix('https://doi.org/') for n in meta.findall('./article-id') if n.get('pub-id-type') == 'doi'}
    if expected_doi.lower() not in dois:
        raise ValueError('doi_mismatch')
    article_type = root.get('article-type', '').lower()
    if article_type not in ('research-article',):
        raise ValueError('not_research_article:' + article_type)
    license_nodes = meta.findall('./permissions/license')
    license_text = ' '.join(text(n) + ' ' + ' '.join(v for e in n.iter() for v in e.attrib.values()) for n in license_nodes)
    allowed = re.search(r'creativecommons.org/(?:licenses/by/|publicdomain/zero/)', license_text, re.I)
    if not allowed:
        raise ValueError('not_explicit_CC_BY_or_CC0')
    statements = []
    # Search only structural data statements, never the full references/body URL pool.
    for node in root.iter():
        if node.tag not in ('sec', 'fn', 'notes', 'custom-meta'):
            continue
        title = text(node.find('./title')) or text(node.find('./meta-name'))
        kind = ' '.join([node.get('sec-type', ''), node.get('fn-type', ''), title])
        content = text(node)
        explicit = re.search(r'data.?avail|availability.*data|data.?access|data.?sharing|data.?deposition|supporting data', kind, re.I)
        implicit = node.tag in ('fn', 'notes') and re.match(r'(?:data availability|availability of data|data access)', content, re.I)
        if explicit or implicit:
            statements.append(node)
    if not statements:
        raise ValueError('no_data_statement')
    statement = '\n'.join(dict.fromkeys(text(node) for node in statements))
    if BLOCKED.search(statement):
        raise ValueError('data_access_restriction:' + statement[:350])
    urls = set()
    evidence = set()
    for node in statements:
        for element in node.iter():
            if element.tag == 'ext-link':
                for key, value in element.attrib.items():
                    if key.endswith('href') and value.startswith(('http://', 'https://')):
                        cleaned = value.rstrip('.,;)')
                        urls.add(cleaned)
                        evidence.add((cleaned, 'XML_EXT_LINK_HREF'))
        for value in re.findall(r'https?://[^\s<>"\[\](){}]+', text(node)):
            cleaned = value.rstrip('.,;:')
            urls.add(cleaned)
            evidence.add((cleaned, 'STATEMENT_TEXT_URL'))
        for value in re.findall(r'\b10\.(?:5061|6084|5281|17605)/[A-Za-z0-9._/-]+', text(node)):
            cleaned = 'https://doi.org/' + value.rstrip('.,;:')
            urls.add(cleaned)
            evidence.add((cleaned, 'STATEMENT_DOI_NORMALIZED'))
    malformed = [{'url': url, 'source_type': kind, 'reason': declared_url_error(url)} for url, kind in sorted(evidence) if declared_url_error(url)]
    urls = {url for url in urls if not declared_url_error(url)}
    evidence = {(url, kind) for url, kind in evidence if url in urls}
    selected = sorted(url for url in urls if repository_url(url))
    if not selected:
        raise ValueError('no_repository_url_in_data_statement')
    return {'article_type': article_type, 'license': 'CC0' if 'publicdomain/zero/' in license_text.lower() else 'CC BY', 'license_evidence': license_text, 'data_statement': statement, 'data_urls': sorted(urls), 'repository_urls': selected, 'data_url_evidence': [{'url': url, 'source_type': kind} for url, kind in sorted(evidence)], 'malformed_declared_links': malformed, 'data_resource_note': 'Declared links only. Extraction is not exhaustive; non-whitelisted bare DOI resources may be omitted. Data format and access conditions were not independently checked; links may refer to processed data or conditional external resources.', 'data_link_status': 'DECLARED_LINK_ONLY', 'raw_data_download_status': 'NOT_TESTED', 'reproducibility_status': 'NOT_TESTED'}


# [작성:전문가4] 2026-09-27 case66 무엇:결과저장 왜:검토가능 입력:records 출력:JSON/CSV/MD 검증:BOM/배열.
def outputs(records):
    """작성전문가4 2026-09-27 case66: 결과3형식 저장; records→JSON/CSV/MD; Unicode·CSV배열 보존."""
    (ROOT / 'papers50.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    if not records:
        return
    with (ROOT / 'papers50.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows({key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value for key, value in row.items()} for row in records)
    lines = ['# 공개 논문 수집 검증 목록', '', '수집·라이선스·명시 링크 확인만 수행. 원자료 다운로드·분석·재현성 검증은 NOT_TESTED. 검색 범주는 전문가 분야 분류가 아님.', '링크 추출은 완전목록이 아니며 허용 저장소 외의 bare DOI는 누락될 수 있음. 자료 형태·접근 조건은 미확인: 전처리 자료나 조건부 외부 자료를 포함할 수 있으며 원자료 공개를 확정하지 않음. 잘못된 선언 주소는 malformed_declared_links에 보존하며 추측 교정하지 않음.', '', '|번호|검색범주|연도|논문|DOI|PMCID|허가|원자료|', '|---|---|---|---|---|---|---|---|']
    for i, row in enumerate(records, 1):
        title = row['title'].replace('|', '/')
        lines.append(f"|{i}|{row['search_category']}|{row['year']}|{title}|[DOI](https://doi.org/{row['doi']})|{row['pmcid']}|{row['license']}|NOT_TESTED|")
    (ROOT / 'papers50.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


# [작성:전문가4] 2026-09-27 case66 무엇:오프라인감사 왜:배포검증 입력:records/target 출력:dict 검증:고유성/SHA/XML/상태.
def verify(records, target):
    if len(records) != target:
        raise ValueError(f'Expected {target} records, got {len(records)}')
    dois = [row['doi'].lower() for row in records]
    pmcs = [row['pmcid'] for row in records]
    if len(set(dois)) != target or len(set(pmcs)) != target or set(dois) & EXCLUDED:
        raise ValueError('duplicate_or_preexisting_identifier')
    search_metadata = {}
    for search_file in (ROOT / 'raw_search').glob('*.json'):
        result = json.loads(search_file.read_text(encoding='utf-8'))
        for candidate in result.get('resultList', {}).get('result', []):
            search_metadata[candidate.get('doi', '').lower()] = candidate
    for row in records:
        metadata = search_metadata.get(row['doi'].lower())
        if metadata is None:
            raise ValueError('missing_search_metadata:' + row['doi'])
        retraction_fields = {'title': metadata.get('title'), 'pubTypeList': metadata.get('pubTypeList'), 'commentCorrectionList': metadata.get('commentCorrectionList')}
        if re.search(r'retract', json.dumps(retraction_fields), re.I):
            raise ValueError('retraction_signal_in_metadata:' + row['doi'])
        path = (ROOT / row['source_file'].replace('\\', '/')).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('source_file_outside_collection')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['source_sha256']:
            raise ValueError('source_hash_mismatch:' + row['doi'])
        parsed = parse_article(raw, row['doi'])
        for key in ('license', 'data_statement', 'repository_urls', 'data_urls', 'data_url_evidence', 'malformed_declared_links', 'data_resource_note'):
            if parsed[key] != row[key]:
                raise ValueError('parsed_field_mismatch:' + key + ':' + row['doi'])
        for key in ('raw_data_download_status', 'reproducibility_status'):
            if row[key] != 'NOT_TESTED':
                raise ValueError('unexpected_data_validation_claim:' + key)
    return {'verified_count': target, 'unique_doi': target, 'unique_pmcid': target, 'hash_xml_doi_license_data_statement': 'PASS', 'retraction_signal_check': 'NONE_IN_CAPTURED_EUROPE_PMC_TITLE_PUBTYPE_COMMENTCORRECTION', 'retraction_check_limit': 'Captured Europe PMC metadata only; not a complete independent retraction registry audit.', 'raw_data_download_status': 'NOT_TESTED', 'reproducibility_status': 'NOT_TESTED', 'verified_utc': utc()}


# [작성:전문가4] 2026-09-27 case66 무엇:수집실행 왜:검증50편 입력:CLI 출력:파일 검증:중복/부적격제외.
def main():
    """작성전문가4 2026-09-27 case66: 분야분산 실제수집; target→검증목록; DOI/PMCID중복·실패기록 보존."""
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=int, default=50)
    parser.add_argument('--output', type=Path, default=ROOT)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--revalidate', action='store_true', help='Reparse captured XML, preserve rejected rows, and replenish the collection.')
    args = parser.parse_args()
    if args.target < 1:
        parser.error('--target must be positive')
    ROOT = args.output.resolve()
    (ROOT / 'raw_search').mkdir(parents=True, exist_ok=True)
    (ROOT / 'fulltext_xml').mkdir(exist_ok=True)
    records = json.loads((ROOT / 'papers50.json').read_text(encoding='utf-8')) if (ROOT / 'papers50.json').exists() else []
    for row in records:
        row['source_file'] = row['source_file'].replace('\\', '/')
        if 'category' in row:
            row['search_category'] = row.pop('category')
    if args.revalidate:
        valid = []
        for row in records:
            try:
                parsed = parse_article((ROOT / row['source_file']).read_bytes(), row['doi'])
                valid.append({**row, **parsed})
            except (ValueError, ET.ParseError) as error:
                log({'event': 'revalidation_rejected', 'doi': row['doi'], 'reason': str(error)})
                with (ROOT / 'rejected_records.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'reason': str(error), 'record': row}, ensure_ascii=False) + '\n')
        records = valid
        outputs(records)
        print('REVALIDATED', len(records), flush=True)
    if args.verify_only:
        report = verify(records, args.target)
        (ROOT / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
        return
    seen_doi = EXCLUDED | {r['doi'].lower() for r in records}
    seen_pmc = {r['pmcid'] for r in records}
    candidates = {}
    for category, terms in CATEGORIES.items():
        query = BASE_QUERY + ' AND ' + terms
        url = API + '/search?' + urllib.parse.urlencode({'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': 200})
        filename = ROOT / 'raw_search' / (category + '.json')
        cached = filename.exists()
        raw = filename.read_bytes() if cached else fetch(url)
        if raw is None:
            continue
        filename.write_bytes(raw)
        result = json.loads(raw)
        candidates[category] = iter(result.get('resultList', {}).get('result', []))
        log({'event': 'search', 'category': category, 'query': query, 'hit_count': result.get('hitCount'), 'sha256': hashlib.sha256(raw).hexdigest(), 'file': filename.relative_to(ROOT).as_posix(), 'retrieval': 'CACHED_CAPTURE' if cached else 'HTTP_GET'})
        print('SEARCH', category, result.get('hitCount'), flush=True)
    while candidates and len(records) < args.target:
        for category in list(candidates):
            accepted = False
            while not accepted:
                candidate = next(candidates[category], None)
                if candidate is None:
                    del candidates[category]
                    break
                doi = candidate.get('doi', '').lower()
                pmcid = candidate.get('pmcid', '')
                types = ' '.join(candidate.get('pubTypeList', {}).get('pubType', [])).lower()
                title = candidate.get('title', '')
                if not doi or not pmcid or doi in seen_doi or pmcid in seen_pmc:
                    continue
                seen_doi.add(doi)
                seen_pmc.add(pmcid)
                if re.search(r'review|editorial|correction|protocol|retract', types + ' ' + title.lower()):
                    log({'event': 'rejected', 'doi': doi, 'reason': 'publication_type_or_title'})
                    continue
                if re.search(r'retract', json.dumps(candidate.get('commentCorrectionList', {})), re.I):
                    log({'event': 'rejected', 'doi': doi, 'reason': 'retraction_signal_in_commentCorrectionList'})
                    continue
                url = API + '/' + pmcid + '/fullTextXML'
                raw = fetch(url)
                if raw is None:
                    continue
                try:
                    parsed = parse_article(raw, doi)
                except (ValueError, ET.ParseError) as error:
                    log({'event': 'rejected', 'doi': doi, 'pmcid': pmcid, 'reason': str(error)})
                    continue
                destination = ROOT / 'fulltext_xml' / (pmcid + '.xml')
                destination.write_bytes(raw)
                journal = candidate.get('journalInfo', {}).get('journal', {}).get('title', '')
                row = {'title': title, 'year': candidate.get('pubYear', ''), 'journal': journal, 'doi': doi, 'pmcid': pmcid, 'search_category': category, 'fulltext_url': url, 'fulltext_status': 'HTTP_200_XML_PARSED_DOI_MATCHED', **parsed, 'source_sha256': hashlib.sha256(raw).hexdigest(), 'source_file': destination.relative_to(ROOT).as_posix(), 'retrieved_utc': utc()}
                records.append(row)
                outputs(records)
                print('ACCEPT', len(records), category, doi, flush=True)
                accepted = True
                if len(records) >= args.target:
                    break
            if len(records) >= args.target:
                break
    outputs(records)
    print('DONE', len(records), flush=True)
    if len(records) < args.target:
        raise SystemExit('Insufficient verified papers; retained partial results and complete request log.')


if __name__ == '__main__':
    main()
