"""Local, non-executing literature retrieval. No model training or paper verdicts."""
from __future__ import annotations
import collections
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import threading
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from tools.collect_public_papers import EXCLUDED, declared_url_error

SCHEMA = 1
MANIFEST = 'data/combined_papers_index.json'
TEAM_METADATA = 'data/team_intake/jihyun_20260929/metadata.json'
TEAM_METADATA_SHA256 = '6174bd3c1959a8363d19210909cd61d58bf9f13fe6800b653a5f8104365535b1'
# [수정: 0 이영] 공개 파생 manifest 지문을 결속해 팀 취합 메타데이터 결손의 차단 조건을 유지한다. 변경 근거: docs/intake/0_이영_공개자료.json.
# [수정: 0 이영 · Codex] 2026-10-01 00:05 KST — 원본/공개사본 지문을 분리하고 운영 manifest의 실제 바이트에 연결한다.
TEAM_BASE_SHA256 = 'd4d394b77eae65c0bed1af4852f1b945262fffa93b0ed2dd5370f725c465eb16'
ARCHIVED = 'ARCHIVED_CC_BY_OR_CC0'
STATUSES = {ARCHIVED, 'LINK_ONLY_REUSE_RESTRICTED', 'CITATION_METADATA_ONLY'}
MAX_PASSAGE_CHARS = 2000
EXTRACTOR_VERSION = 'case69.1'
_VALIDATED = collections.OrderedDict()
_CACHE_LOCK = threading.RLock()
_SEARCH_LOCK = threading.RLock()
SYNONYM_SOURCE = 'NAIS_MANUAL_TERMS_case69_1'
SYNONYMS = [('reproducibility', '재현성'), ('metadata', '메타데이터'), ('regression', '회귀'), ('correlation', '상관'), ('biodiversity', '생물다양성'), ('sample', '표본')]


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 중복 JSON 거부 / 입력·출력: bytes→객체 / 검증: test_case68.
def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 플랫폼 독립 상대경로 및 실제 symlink 경계 / 입력·출력: root,path→Path / 검증: 탈출 시험.
def safe_path(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Invalid relative source path')
    item = PurePosixPath(relative)
    if item.is_absolute() or any(p in {'.', '..'} for p in relative.split('/')): raise ValueError('Path traversal')
    root = Path(root).resolve(); path = (root / relative).resolve()
    if not path.is_relative_to(root): raise ValueError('Source escapes root')
    return path


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 동일 입력의 안정 지문 / 입력·출력: JSON값→SHA256 / 검증: 반복 빌드.
def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 국문 보존 제목 그룹과 검색 토큰 / 입력·출력: 문자열→토큰목록 / 검증: 제목 alias.
def tokens(text):
    return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', str(text)).casefold(), re.UNICODE)


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 기존600/교수자료 기준경로 차이 명시 / 입력·출력: record→상대경로 / 검증: 실제644.
def source_path(record):
    relative = record.get('relative_fulltext_path')
    if record['source_group'] == 'existing600': return 'data/' + relative
    if record['source_group'] == 'faculty_pmc': return relative
    raise ValueError('Metadata collection cannot supply fulltext')


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: XML 지문·논문 정체성·본문 검증 / 입력·출력: raw,record→문단목록/본문지문 / 검증: 변조·빈본문·다른DOI.
# [수정:전문가4·7] 2026-09-27 case69 / 종류:검증방법추가 / 재현방법: 비p 표 셀 검색 누락 / 변경전: 본문 p만 / 변경후: 표행을 별도 후보로 보존 / 왜: 출처 있는 표 탐색 보완 / 영향: 기본 단락·수치 분석은 불변.
# [작성: 전문가4·7] 2026-09-28 case86
# 무엇을: 단일 article 정규화 / 왜: PMC 묶음 호환 / 입력·출력: bytes -> XML 요소 / 검증: entity·다중 article 거부.
def article_xml(raw):
    if b'<!ENTITY' in raw.upper(): raise ValueError('XML entities not accepted')
    try: article = ET.fromstring(raw)
    except ET.ParseError as error: raise ValueError('Invalid article XML') from error
    for node in article.iter(): node.tag = node.tag.rsplit('}', 1)[-1]
    if article.tag == 'pmc-articleset':
        children = list(article)
        if len(children) != 1 or children[0].tag != 'article': raise ValueError('Exactly one article required')
        article = children[0]
    if article.tag != 'article': raise ValueError('Article XML required')
    return article


# [수정: 전문가4·7] 2026-09-28 case86
# 종류: 검증방법추가 / 재현 방법: PMC efetch 묶음 XML / 변경 전: DOI 불일치 / 변경 후: 단일 article만 해석 / 왜: 출처 형식 호환 / 영향: 기존 해시·본문 검사 유지, 다중 논문 차단.
def xml_passages(raw, record):
    if hashlib.sha256(raw).hexdigest() != record['fulltext_sha256']: raise ValueError('Fulltext hash mismatch')
    article = article_xml(raw)
    ids = article.findall('./front/article-meta/article-id')
    dois = {''.join(n.itertext()).strip().lower().removeprefix('https://doi.org/') for n in ids if n.get('pub-id-type') == 'doi'}
    if record['doi'] not in dois: raise ValueError('XML DOI mismatch')
    identities = {n.get('pub-id-type'): ''.join(n.itertext()).strip() for n in ids}
    xml_pmc = identities.get('pmcid') or identities.get('pmc') or identities.get('pmcaid')
    if xml_pmc and not xml_pmc.upper().startswith('PMC'): xml_pmc = 'PMC' + xml_pmc
    if record.get('pmcid') and xml_pmc and record['pmcid'].upper() != xml_pmc.upper(): raise ValueError('XML PMCID mismatch')
    if record.get('pmid') and identities.get('pmid') and str(record['pmid']) != identities['pmid']: raise ValueError('XML PMID mismatch')
    body = article.find('body')
    if body is None: raise ValueError('Missing article body')
    passages = []
    for number, node in enumerate(body.iter('p'), 1):
        text = ' '.join(''.join(node.itertext()).split())
        if not text: continue
        for start in range(0, len(text), MAX_PASSAGE_CHARS):
            passages.append({'locator': f'body-descendant-p#{number}@normalized-char:{start}', 'text': text[start:start+MAX_PASSAGE_CHARS]})
    if not passages: raise ValueError('Empty article body')
    body_hash = fingerprint(' '.join(''.join(body.itertext()).split()))
    # [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 표행은 별도 후보로만 보존 / 입력·출력: XML표→셀구분문자열 / 검증: opt-in, 수치해석 없음.
    tables = []
    for table_number, table in enumerate(body.iter('table-wrap'), 1):
        caption = ' '.join(' '.join(n.itertext()) for n in table.findall('caption')).strip()
        headers = [' '.join(''.join(n.itertext()).split()) for n in table.iter('th')]
        for row_number, row in enumerate(table.iter('tr'), 1):
            cells = [' '.join(''.join(cell.itertext()).split()) for cell in row if cell.tag in {'td', 'th'}]
            if not cells: continue
            text = 'Caption: ' + caption + '\nHeaders: ' + ' | '.join(headers) + '\nCells: ' + ' | '.join(cells)
            tables.append({'locator': f'body-descendant-table-wrap#{table_number}/descendant-tr#{row_number}', 'text': text, 'evidence_level': 'TABLE_CANDIDATE', 'table_interpretation': 'LEXICAL_CELLS_ONLY_NO_ROWSPAN_COLSPAN_OR_STATISTICAL_INTERPRETATION'})
    return passages, body_hash, identities.get('pmid'), tables


# [작성: 자료통합·검증 담당] 2026-09-28 case86
# 무엇을: 정정·철회 쌍 읽기 전용 검사 / 왜: 공지 존재를 정량 주장 오답으로 승격하지 않음 / 입력·출력: root,pair -> 검증한 단락·관계 / 검증: test_case86 전수·변조 검사.
def read_correction_pair(root, pair):
    if pair['documents'] and pair['doi'] == pair['notice_doi']: raise ValueError('Same DOI cannot form an original/notice pair')
    documents = {}
    notice_links = set()
    for role, record in pair['documents'].items():
        if role not in {'original', 'notice'}: raise ValueError('Unknown document role')
        expected_doi = pair['doi'] if role == 'original' else pair['notice_doi']
        if record['doi'] != expected_doi: raise ValueError('Pair DOI mismatch')
        raw = safe_path(root, record['path']).read_bytes()
        passages, _, _, tables = xml_passages(raw, record)
        article = article_xml(raw)
        permissions = article.findall('./front/article-meta/permissions/license')
        links = [value for node in permissions for child in node.iter() for key, value in child.attrib.items() if key.endswith('href')]
        links += [''.join(child.itertext()).strip() for node in permissions for child in node.iter('license_ref')]
        allowed = sorted({link for link in links if re.fullmatch(r'https?://creativecommons\.org/(?:licenses/by/[1-4]\.0|publicdomain/zero/1\.0)/?', link)})
        if not allowed: raise ValueError('Article permission is not verified CC BY/CC0')
        documents[role] = {'doi': record['doi'], 'path': record['path'], 'sha256': record['fulltext_sha256'], 'license_urls': allowed, 'passages': passages, 'tables': tables}
        if role == 'notice':
            for node in article.findall('./front/article-meta/related-article'):
                if node.get('related-article-type') in {'corrected-article', 'retracted-article'}:
                    notice_links.update(value.strip().lower().removeprefix('https://doi.org/').removeprefix('http://dx.doi.org/') for key, value in node.attrib.items() if key.endswith('href'))
    original = pair['documents'].get('original', {})
    identifiers = {str(original.get('doi', '')).lower(), str(original.get('pmcid', '')).lower()} - {''}
    relationship = 'NOTICE_LINKS_TO_ORIGINAL' if notice_links & identifiers else 'PAIRING_NOT_CONFIRMED_BY_XML'
    return {'pair_id': pair['pair_id'], 'documents': documents, 'relationship': relationship, 'analysis_status': 'NOT_EXECUTED', 'human_approval': False}


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 선정목록만 읽고 근거 승격 차단 / 입력·출력: root,manifest→raw,records / 검증: 잘못된상태/경로/중복.
def load_records(root, manifest):
    raw = safe_path(root, manifest).read_bytes(); value = strict_json(raw)
    records = value.get('papers') if isinstance(value, dict) else None
    if not isinstance(records, list) or not records: raise ValueError('Nonempty selected papers required')
    seen = set(); result = []
    for record in records:
        if not isinstance(record, dict): raise ValueError('Paper object required')
        ident = record.get('doi')
        if not isinstance(ident, str) or not re.fullmatch(r'10\.\d{4,9}/\S+', ident) or ident != ident.lower() or ident in seen or ident in EXCLUDED: raise ValueError('Invalid, duplicate or excluded DOI')
        seen.add(ident)
        if not isinstance(record.get('title'), str) or not tokens(record['title']): raise ValueError('Empty paper title')
        if record.get('source_group') not in {'existing600', 'faculty_pmc', 'faculty_publications'}: raise ValueError('Unknown source group')
        state = record.get('fulltext_status')
        if state not in STATUSES: raise ValueError('Unknown fulltext status')
        if record.get('raw_data_download_status') != 'NOT_TESTED' or record.get('reproduction_status') != 'NOT_TESTED': raise ValueError('Unsupported execution claim')
        if state == ARCHIVED:
            if record.get('license') not in {'CC BY', 'CC0'} or not re.fullmatch('[0-9a-f]{64}', record.get('fulltext_sha256') or ''): raise ValueError('Missing archived license/hash')
            if not record.get('relative_fulltext_path'): raise ValueError('Missing fulltext path')
            safe_path(root, source_path(record))
        elif record.get('relative_fulltext_path') or record.get('fulltext_sha256'):
            raise ValueError('Bibliography-only record cannot claim fulltext')
        result.append(dict(record))
    return raw, sorted(result, key=lambda r: r['doi'])


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 동일 논문 별칭의 분리 누수 차단 / 입력·출력: records→DOI별group/split / 검증: 연결그룹·순서독립.
def assign_splits(records):
    parent = {r['doi']: r['doi'] for r in records}; owners = {}
    def find(ident):
        while parent[ident] != ident:
            parent[ident] = parent[parent[ident]]; ident = parent[ident]
        return ident
    for record in records:
        keys = [('doi', record['doi']), ('title', ''.join(tokens(record['title'])))]
        keys += [(key, str(record[key]).strip().upper()) for key in ['pmcid', 'pmid', 'fulltext_sha256', 'body_sha256'] if record.get(key)]
        for key in keys:
            if key in owners:
                left, right = find(record['doi']), find(owners[key]); parent[max(left, right)] = min(left, right)
            else: owners[key] = record['doi']
    members = collections.defaultdict(list)
    for ident in parent: members[find(ident)].append(ident)
    result = {}
    for group in members.values():
        digest = fingerprint(sorted(group)); split = 'validation' if int(digest[:8], 16) % 5 == 0 else 'development'
        for ident in group: result[ident] = {'group_id': digest, 'split': split}
    return result


def load_team_metadata(root, existing):
    """case105: hash-bound bibliography only; submitted XML and claims are never read."""
    path = safe_path(root, TEAM_METADATA)
    if not path.exists():
        # Older fixture manifests stay valid; deleting the case105 addon fails closed.
        if hashlib.sha256(safe_path(root, MANIFEST).read_bytes()).hexdigest() == TEAM_BASE_SHA256:
            raise ValueError('Required team metadata missing')
        return []
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != TEAM_METADATA_SHA256:
        raise ValueError('Team metadata hash mismatch')
    value = strict_json(raw)
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise ValueError('Invalid team metadata schema')
    rows = value.get('papers')
    if not isinstance(rows, list): raise ValueError('Team papers list required')
    seen = {r['doi'].strip().lower().removeprefix('https://doi.org/').removeprefix('http://dx.doi.org/') for r in existing}
    selected = []; submitted = set()
    fields = {'doi', 'original_doi', 'title', 'title_ko_unverified', 'field', 'source_group', 'fulltext_status', 'source_url', 'public_urls', 'license', 'license_urls', 'license_text_locator', 'submission_paper_id', 'submission_fulltext_status', 'fulltext_block_reason', 'metadata_provenance', 'raw_data_download_status', 'reproduction_status', 'human_review', 'automatic_execution'}
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields: raise ValueError('Invalid team paper fields')
        strings = fields - {'public_urls', 'license_urls', 'metadata_provenance', 'automatic_execution'}
        if any(not isinstance(row[k], str) or len(row[k]) > 2000 for k in strings): raise ValueError('Invalid team paper types')
        doi = row['doi']
        if not re.fullmatch(r'10\.\d{4,9}/[^\s"\\\x00-\x1f]+', doi) or doi != doi.lower() or doi in submitted or doi in EXCLUDED:
            raise ValueError('Invalid team DOI')
        submitted.add(doi)
        if (not tokens(row['title']) or row['fulltext_status'] != 'CITATION_METADATA_ONLY'
                or row['source_group'] != 'team_jihyun_20260929' or row['automatic_execution'] is not False
                or row['human_review'] != 'UNREVIEWED' or row['license'] != 'UNVERIFIED_SUBMISSION_POINTER_ONLY'
                or row['raw_data_download_status'] != 'NOT_TESTED' or row['reproduction_status'] != 'NOT_TESTED'
                or row['fulltext_block_reason'] not in {'REDISTRIBUTION_NOT_VERIFIED', 'FULLTEXT_NOT_ACQUIRED'}):
            raise ValueError('Unsupported team evidence claim')
        for key in ['public_urls', 'license_urls', 'metadata_provenance']:
            if not isinstance(row[key], list) or any(not isinstance(s, str) or len(s) > 2000 for s in row[key]):
                raise ValueError('Invalid team provenance list')
        for url in [row['source_url']] + row['public_urls'] + row['license_urls']:
            if declared_url_error(url): raise ValueError('Invalid team public URL')
            parts = urlsplit(url)
            if (parts.username or parts.password or parts.port or parts.query
                    or parts.hostname not in {'doi.org', 'pmc.ncbi.nlm.nih.gov', 'creativecommons.org', 'ieeexplore.ieee.org', 'academic.oup.com', 'www.tandfonline.com', 'onlinelibrary.wiley.com'}):
                raise ValueError('Unsupported team public URL')
        for relative in row['metadata_provenance']: safe_path(root, relative)
        if doi not in seen: selected.append(dict(row))
    splits = assign_splits(list(existing) + selected)
    return [row | splits[row['doi']] for row in selected]


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 900서지와 보관본문만 결정적 검색자료 생성 / 입력·출력: root,manifest→corpus / 검증: 전체실측.
# [수정:전문가4·7] 2026-09-27 case69 / 종류:최적화 / 재현방법: 반복 검색마다 XML 재구성 / 변경전: 파일을 직접 읽어 구성 / 변경후: 같은 bytes snapshot으로 구성 / 왜: 안전한 검증 재사용 / 영향: 원문·분리·해시 계약 유지.
def build_corpus(root, manifest=MANIFEST):
    if manifest != MANIFEST: raise ValueError('Only the selected product manifest is supported')
    raw, records = load_records(root, manifest)
    sources = {source_path(r): safe_path(root, source_path(r)).read_bytes() for r in records if r['fulltext_status'] == ARCHIVED}
    return _assemble_corpus(raw, records, sources)


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 해시검사한 같은 bytes로 재구성해 이중읽기 경합 차단 / 입력·출력: snapshots→corpus / 검증: cache cold snapshot.
def _assemble_corpus(raw, records, sources):
    records = [dict(record) for record in records]; passages = []; table_passages = []
    for record in records:
        if record['fulltext_status'] == ARCHIVED:
            path = source_path(record); extracted, body_hash, pmid, tables = xml_passages(sources[path], record)
            record['body_sha256'] = body_hash
            if pmid: record['pmid'] = pmid
            passages.extend(dict(p, doi=record['doi'], source_path=path, source_sha256=record['fulltext_sha256']) for p in extracted)
            table_passages.extend(dict(p, doi=record['doi'], source_path=path, source_sha256=record['fulltext_sha256']) for p in tables)
    splits = assign_splits(records)
    # [수정: 0 이영] 공개 연락처 치환 파생 자료와 발행사 원문 지문을 검색 인용에 구분해 보존한다.
    papers = [{key: r.get(key) for key in ['doi', 'title', 'field', 'source_group', 'fulltext_status', 'source_url', 'license', 'pmcid', 'pmid', 'body_sha256', 'original_fulltext_sha256', 'public_derivative', 'public_transform']} | splits[r['doi']] for r in records]
    fulltext = sum(r['fulltext_status'] == ARCHIVED for r in records)
    summary = {'records': len(records), 'fulltext': fulltext, 'bibliography_only': len(records)-fulltext, 'passages': len(passages), 'splits': dict(collections.Counter(p['split'] for p in papers)), 'parsed_fulltext': fulltext, 'parse_failures': 0}
    summary['table_candidates'] = len(table_passages)
    corpus = {'schema': SCHEMA, 'extractor_version': EXTRACTOR_VERSION, 'manifest': MANIFEST, 'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'summary': summary, 'scope': 'Default: body descendant p elements, 2000 normalized-character chunks. Optional tables retain caption/header/cells as lexical candidates, not layout or numeric interpretation. Optional boundary context joins 160 characters on each side of consecutive chunks/paragraphs. Front/back excluded. Local retrieval, not training or blind evaluation.', 'papers': papers, 'passages': passages, 'table_passages': table_passages}
    corpus['content_sha256'] = fingerprint(corpus)
    return corpus


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 저장검색자료를 실제 원문에서 재구성 대조 / 입력·출력: corpus,root→report / 검증: JSON·원문 변조.
# [수정:전문가4·7] 2026-09-27 case69 / 종류:최적화 / 재현방법: warm 검색·동일mtime 변조 / 변경전: 매번 XML 재파싱 / 변경후: bytes·corpus 지문 확인 후 검증 보고서 재사용 / 왜: 지연 감소 / 영향: 매요청 원문 SHA 검사 유지.
def validate_corpus(corpus, root):
    # [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 외부 가변dict와 검증사용 경합 차단 / 입력·출력: corpus→독립snapshot / 검증: 결과오염/thread.
    snapshot = strict_json(json.dumps(corpus, ensure_ascii=False, separators=(',', ':')))
    return _validate_snapshot(snapshot, root)


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 실제bytes 검사 후만 검증보고서 재사용 / 입력·출력: 불변snapshot/root→report / 검증: 동일mtime변조·root격리.
def _validate_snapshot(corpus, root):
    if not isinstance(corpus, dict) or type(corpus.get('schema')) is not int or corpus['schema'] != SCHEMA: raise ValueError('Unsupported corpus schema')
    if corpus.get('manifest') != MANIFEST: raise ValueError('Unexpected selected manifest')
    content = {key: value for key, value in corpus.items() if key != 'content_sha256'}
    if fingerprint(content) != corpus.get('content_sha256'): raise ValueError('Corpus content fingerprint mismatch')
    root = Path(root).resolve()
    # ponytail: one lock bounds cold XML reconstruction; cache stores only small report JSON, never corpus/results.
    with _CACHE_LOCK:
        raw, records = load_records(root, MANIFEST); manifest_hash = hashlib.sha256(raw).hexdigest()
        if manifest_hash != corpus.get('manifest_sha256'): raise ValueError('Selected manifest hash mismatch')
        expected = tuple((source_path(r), r['fulltext_sha256']) for r in records if r['fulltext_status'] == ARCHIVED)
        key = (str(root), EXTRACTOR_VERSION, manifest_hash, corpus['content_sha256'], expected)
        cached = _VALIDATED.get(key); sources = {}; byte_count = 0
        for path, digest in expected:
            source = safe_path(root, path).read_bytes(); byte_count += len(source)
            if hashlib.sha256(source).hexdigest() != digest: raise ValueError('Fulltext hash mismatch')
            if cached is None: sources[path] = source
        if cached is not None:
            _VALIDATED.move_to_end(key)
            report = strict_json(cached)
        else:
            rebuilt = _assemble_corpus(raw, records, sources)
            if fingerprint(corpus) != fingerprint(rebuilt): raise ValueError('Corpus does not match selected manifest and sources')
            report = {'status': 'PASS', **rebuilt['summary'], 'content_sha256': rebuilt['content_sha256'], 'validation_scope': 'All selected source bytes hashed every request; reconstruction reused only for verified matching snapshots; not authentication or reproduction'}
            _VALIDATED[key] = json.dumps(report, ensure_ascii=False)
            while len(_VALIDATED) > 4: _VALIDATED.popitem(last=False)
        return dict(report, source_files_hashed=len(expected), source_bytes_hashed=byte_count, reconstruction_cache_hit=cached is not None)


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 조각/문단 경계를 명시 후보로 보완 / 입력·출력: passages→양쪽locator후보 / 검증: 경계토큰·분리.
def boundary_candidates(passages):
    for left, right in zip(passages, passages[1:]):
        if left['doi'] != right['doi']: continue
        same_paragraph = left['locator'].split('@')[0] == right['locator'].split('@')[0]
        separator = '' if same_paragraph else '\n'
        ranges = []
        for chunk, start, end in [(left, max(0,len(left['text'])-160),len(left['text'])),(right,0,min(160,len(right['text'])))]:
            offset = int(chunk['locator'].rsplit(':',1)[1])
            ranges.append({'paragraph':chunk['locator'].split('@')[0],'normalized_start':offset+start,'normalized_end_exclusive':offset+end})
        yield dict(left, text=left['text'][-160:] + separator + right['text'][:160], locator=left['locator']+'..'+right['locator'], source_locators=[left['locator'], right['locator']], source_ranges=ranges, evidence_level='BOUNDARY_CANDIDATE', context_scope='CONSECUTIVE_EXTRACTED_CHUNKS_NOT_CAUSAL_OR_TABLE_ASSOCIATION')


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 선택분리 검색과 출처 재대조 / 입력·출력: corpus/query/split/mode/root→후보 / 검증: 누수·변조·메타승격.
# [수정:전문가4·7] 2026-09-27 case69 / 종류:최적화 / 재현방법: 4요청 snapshot 메모리 증가 / 변경전: 동시 복사·검색 / 변경후: 전체 검색 직렬화와 명시 확장 옵션 / 왜: 메모리 중복 제한 / 영향: 대기 증가 가능·기본 결과 유지.
def search_corpus(corpus, query, split='development', mode='passages', limit=10, root=None, *, include_tables=False, boundary_context=False, expand_synonyms=False, doi=None):
    # [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 대형JSON snapshot 동시중복메모리 상한 / 입력·출력: 대기요청→후보 / 검증: 4thread peak·순서격리.
    with _SEARCH_LOCK:
        return _search_corpus(corpus, query, split, mode, limit, root, include_tables=include_tables, boundary_context=boundary_context, expand_synonyms=expand_synonyms, doi=doi)


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 직렬검색 안에서 독립snapshot검증 / 입력·출력: corpus/query→후보 / 검증: 기본호환·옵션경계.
def _search_corpus(corpus, query, split='development', mode='passages', limit=10, root=None, *, include_tables=False, boundary_context=False, expand_synonyms=False, doi=None):
    if root is None: raise ValueError('Source root required for search verification')
    if split not in {'development', 'validation'} or mode not in {'passages', 'bibliography'}: raise ValueError('Explicit supported split/mode required')
    if type(limit) is not int or not 1 <= limit <= 100: raise ValueError('Limit outside 1..100')
    if not isinstance(query, str) or len(query) > 1000: raise ValueError('Invalid query')
    if any(type(option) is not bool for option in [include_tables, boundary_context, expand_synonyms]): raise ValueError('Retrieval options must be bool')
    if doi is not None:
        if not isinstance(doi, str) or len(doi) > 200 or not re.fullmatch(r'10\.\d{4,9}/[^\s]+', doi.strip()):
            raise ValueError('Invalid selected DOI')
        doi = doi.strip().lower()
    terms = set(tokens(query))
    if not terms: return []
    # [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 검증한 독립snapshot만 검색 / 입력·출력: corpus→후보 / 검증: 가변입력경합.
    corpus = strict_json(json.dumps(corpus, ensure_ascii=False, separators=(',', ':')))
    _validate_snapshot(corpus, root)
    searchable = corpus['papers']
    if mode == 'bibliography': searchable = searchable + load_team_metadata(root, searchable)
    # Filter before ranking/limit: a selected paper must not disappear behind related hits.
    papers = {p['doi']: p for p in searchable if p['split'] == split
              and (doi is None or p['doi'].strip().lower() == doi)}
    candidates = corpus['passages'] if mode == 'passages' else [dict(p, text=p['title'], locator='bibliographic-title', source_path=None, source_sha256=None) for p in papers.values()]
    if mode == 'passages' and include_tables: candidates = candidates + corpus['table_passages']
    if mode == 'passages' and boundary_context: candidates = candidates + list(boundary_candidates(corpus['passages']))
    groups = [{term} for term in sorted(terms)]
    if expand_synonyms:
        for group in groups:
            for pair in SYNONYMS:
                if group.intersection(pair): group.update(pair)
    results = []
    for candidate in candidates:
        paper = papers.get(candidate['doi'])
        if paper is None: continue
        text_terms = set(tokens(candidate['text']))
        overlap = sum(bool(group & text_terms) for group in groups)
        if not overlap: continue
        result = {**paper, **candidate, 'rank_score': overlap / len(terms), 'evidence_level': candidate.get('evidence_level', 'PASSAGE_CANDIDATE') if mode == 'passages' else 'BIBLIOGRAPHY_ONLY', 'analysis_eligibility': 'NOT_ESTABLISHED', 'automatic_execution': False}
        if include_tables or boundary_context or expand_synonyms:
            result.update(retrieval_options={'include_tables':include_tables,'boundary_context':boundary_context,'expand_synonyms':expand_synonyms},query=query,expanded_terms=sorted(set().union(*groups)-terms),synonym_source=SYNONYM_SOURCE if expand_synonyms else None,match_basis='LEXICAL_QUERY_TERM_COVERAGE_NOT_PROBABILITY')
        results.append(result)
    return sorted(results, key=lambda r: (-r['rank_score'], r['doi'], r['locator']))[:limit]
