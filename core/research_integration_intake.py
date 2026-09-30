"""Public fixed-version CSV intake and explicit arithmetic review; never executes code."""
# [작성: 0 이영 · Codex] 2026-10-01 02:51 KST — 공개 원자료 영수증과 기존 결정적 계산을 연결하고, 변경된 입력의 승인을 차단한다. 신규 모의 회귀와 무키 대표 GET으로 검증한다.
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from core.integration_http import _reserve_slot
from core.rbac import can
from core.source_revision import source_revision
from evidence_gate import gate
from evidence_gate.compute import GateError, read_csv
from evidence_gate.spec import METHODS, empty_spec, spec_sha256, validate
from finals.finals_privacy import sensitive_kinds

MAX_BYTES = 5 * 1024 * 1024
SUPPORTED_METHODS = METHODS
ROOT = Path(__file__).resolve().parents[1]
REGISTERED_CLAIM_ID = 'PENG-RAW-ROWS'
PIN = '8957207b78d6ccd1b4654a9dd9c9041b657478ab'
REGISTERED_PATH = f'/allisonhorst/palmerpenguins/{PIN}/inst/extdata/penguins_raw.csv'
LICENSE_PATH = f'/allisonhorst/palmerpenguins/{PIN}/DESCRIPTION'
DOWNLOAD_HOSTS = frozenset({'zenodo.org', 'ndownloader.figshare.com', 'dataverse.harvard.edu', 'raw.githubusercontent.com'})
SCHEMA = 'research-integration-intake/1'
LIMITATIONS = ['Arithmetic verification only; no author code execution or full paper reproduction.',
               'Repository metadata and checksums do not prove that a dataset belongs to a paper.',
               'Imported approval records require fresh review; integrity hashes are not digital signatures.']


class IntakeError(ValueError):
    pass


def _now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(_canonical(value).encode('utf-8'))


def _public(value):
    if sensitive_kinds(value):
        raise IntakeError('SENSITIVE_INPUT')
    _canonical(value)


def _seal(value):
    item = deepcopy(value)
    item.pop('integrity_sha256', None)
    item['integrity_sha256'] = _digest(item)
    return item


def _intact(value):
    if not isinstance(value, dict):
        return False
    item = deepcopy(value)
    supplied = item.pop('integrity_sha256', None)
    try:
        return isinstance(supplied, str) and supplied == _digest(item)
    except (TypeError, ValueError):
        return False


def _blocked(code):
    return {'success': False, 'state': 'BLOCKED', 'action': 'BLOCK', 'error': code,
            'can_approve': False, 'approved': False, 'verified': False,
            'raw_bytes': None, 'limitations': list(LIMITATIONS)}


def _get_bytes(host, path, *, max_bytes=MAX_BYTES):
    """One bounded GET; no keys, cookies, redirect following, retry or generic URL input."""
    if host not in DOWNLOAD_HOSTS or not path.startswith('/') or path.startswith('//'):
        raise IntakeError('DOWNLOAD_HOST_NOT_ALLOWED')
    if len(path) > 600 or any(c in path for c in ('\r', '\n', '\\', '#', '\x00')):
        raise IntakeError('DOWNLOAD_PATH_INVALID')
    if re.search(r'(?:key|token|secret|password|authorization)=', path, re.I):
        raise IntakeError('AUTH_URL_NOT_ALLOWED')
    if host == 'raw.githubusercontent.com' and path not in (REGISTERED_PATH, LICENSE_PATH):
        raise IntakeError('REGISTERED_PATH_NOT_ALLOWED')
    paths = {
        'zenodo.org': r'/api/records/[1-9]\d{0,14}/files/[^/]+\.csv/content',
        'ndownloader.figshare.com': r'/files/[1-9]\d{0,14}',
        'dataverse.harvard.edu': r'/api/access/datafile/[1-9]\d{0,14}\?format=original',
    }
    if host in paths and not re.fullmatch(paths[host], path, re.I):
        raise IntakeError('DOWNLOAD_PATH_NOT_ALLOWED')
    _reserve_slot(host)
    connection = http.client.HTTPSConnection(host, timeout=20)
    try:
        connection.request('GET', path, headers={'User-Agent': 'EvidenceGate-PublicIntake/0', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status != 200:
            raise IntakeError('HTTP_' + str(response.status))
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdigit() or int(length) > max_bytes):
            raise IntakeError('DOWNLOAD_TOO_LARGE')
        if response.getheader('Content-Encoding', 'identity').lower() not in ('', 'identity'):
            raise IntakeError('ENCODED_BODY_NOT_ALLOWED')
        body = response.read(max_bytes + 1)
        if not body or len(body) > max_bytes:
            raise IntakeError('DOWNLOAD_TOO_LARGE_OR_EMPTY')
        if length is not None and len(body) != int(length):
            raise IntakeError('CONTENT_LENGTH_MISMATCH')
        return body, {'http_status': 200, 'source_url': 'https://' + host + path,
                      'retrieved_at_kst': _now(), 'content_type': response.getheader('Content-Type', '').split(';')[0]}
    except IntakeError:
        raise
    except (OSError, http.client.HTTPException, ValueError):
        raise IntakeError('PUBLIC_DOWNLOAD_FAILED') from None
    finally:
        connection.close()


def _csv(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise IntakeError('CSV_BYTES_REQUIRED')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError:
        raise IntakeError('CSV_UTF8_REQUIRED') from None
    if '\x00' in text or raw.startswith((b'PK', b'MZ', b'\x1f\x8b')) or text.lstrip().lower().startswith(('<!doctype', '<html', '<script', '{', '[')):
        raise IntakeError('NON_CSV_BODY')
    _public(text)
    try:
        return read_csv(raw)
    except GateError:
        raise IntakeError('CSV_INVALID') from None


def _license(record):
    value = record.get('license')
    if not isinstance(value, dict) or record.get('custom_terms_present') is True:
        raise IntakeError('LICENSE_NOT_AUTHORIZED')
    candidate = str(value.get('id') or '').lower().replace('_', '-')
    url = str(value.get('url') or '').rstrip('/').lower()
    if candidate in ('cc0', 'cc0-1.0') or url in ('https://creativecommons.org/publicdomain/zero/1.0', 'http://creativecommons.org/publicdomain/zero/1.0'):
        return 'CC0-1.0'
    # [수정: 0 이영 · Codex] 2026-10-01 03:07 KST — 버전 없는 cc-by를 4.0으로 추론하지 않고 정확한 법적 식별자 또는 공식 4.0 URL만 허용한다.
    if candidate == 'cc-by-4.0' or url in ('https://creativecommons.org/licenses/by/4.0', 'http://creativecommons.org/licenses/by/4.0'):
        return 'CC-BY-4.0'
    raise IntakeError('LICENSE_NOT_AUTHORIZED')


def _record_context(provider, record, selected):
    return {'provider': provider, 'record_id': record.get('id'), 'doi': record.get('doi'),
            'concept_doi': record.get('concept_doi'), 'version': record.get('version'),
            'official_url': record.get('official_url'), 'license': record.get('license'),
            'custom_terms_present': record.get('custom_terms_present'), 'access': record.get('access'),
            'selected_file': selected}


def _selection(provider, record, selected_file):
    if provider not in ('zenodo', 'figshare', 'dataverse') or not isinstance(record, dict):
        raise IntakeError('PROVIDER_OR_RECORD_INVALID')
    _public(record)
    if record.get('detail_status') != 'RETRIEVED':
        raise IntakeError('FIXED_RECORD_DETAIL_REQUIRED')
    files = record.get('files')
    if not isinstance(files, list):
        raise IntakeError('FILE_LIST_REQUIRED')
    identifier = selected_file.get('id') if isinstance(selected_file, dict) else selected_file
    matches = [item for item in files if isinstance(item, dict) and str(item.get('id')) == str(identifier)]
    if len(matches) != 1 or (isinstance(selected_file, dict) and selected_file != matches[0]):
        raise IntakeError('SELECTED_FILE_NOT_IN_RECORD')
    selected = deepcopy(matches[0])
    name = selected.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[^/\\\x00\r\n]{1,240}\.csv', name, re.I) or name in ('.csv', '..csv'):
        raise IntakeError('CSV_FILE_REQUIRED')
    if selected.get('restricted') is not False or selected.get('link_only', False) is not False:
        raise IntakeError('FILE_NOT_PUBLIC')
    if record.get('access', {}).get('files') not in ('open', 'public'):
        raise IntakeError('FILES_ACCESS_NOT_PUBLIC')
    size = selected.get('size')
    if type(size) is not int or not 0 < size <= MAX_BYTES:
        raise IntakeError('ADVERTISED_SIZE_INVALID')
    license_id = _license(record)
    rid, fid = str(record.get('id')), str(selected.get('id'))
    if not re.fullmatch(r'[1-9]\d{0,14}', rid):
        raise IntakeError('RECORD_ID_INVALID')
    provenance = record.get('provenance')
    if not isinstance(provenance, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(provenance.get('response_sha256', ''))):
        raise IntakeError('METADATA_RECEIPT_REQUIRED')
    if provider == 'zenodo':
        if record.get('doi') != '10.5281/zenodo.' + rid or record.get('doi') == record.get('concept_doi'):
            raise IntakeError('FIXED_RECORD_VERSION_REQUIRED')
        host, path = 'zenodo.org', '/api/records/' + rid + '/files/' + quote(name, safe='') + '/content'
    elif provider == 'figshare':
        if not re.fullmatch(r'[1-9]\d{0,8}', str(record.get('version'))) or not re.fullmatch(r'[1-9]\d{0,14}', fid):
            raise IntakeError('FIXED_RECORD_VERSION_REQUIRED')
        host, path = 'ndownloader.figshare.com', '/files/' + fid
    else:
        if not re.fullmatch(r'\d+\.\d+', str(record.get('version'))) or not re.fullmatch(r'[1-9]\d{0,14}', fid) or record.get('version_state') not in (None, 'RELEASED'):
            raise IntakeError('FIXED_RECORD_VERSION_REQUIRED')
        host, path = 'dataverse.harvard.edu', '/api/access/datafile/' + fid + '?format=original'
    official = urlsplit(str(record.get('official_url') or ''))
    expected = {'zenodo': 'zenodo.org', 'figshare': 'figshare.com', 'dataverse': 'dataverse.harvard.edu'}[provider]
    if official.scheme != 'https' or official.hostname != expected or official.username or official.password or official.fragment or re.search(r'(?:key|token|secret|password|authorization)=', official.query, re.I):
        raise IntakeError('OFFICIAL_RECORD_URL_INVALID')
    return selected, license_id, host, path


def _checksum_comparison(raw, advertised):
    if advertised is None:
        return {'status': 'NOT_ADVERTISED', 'verified_against_download': False}
    if not isinstance(advertised, dict) or advertised.get('algorithm') not in ('md5', 'sha1', 'sha256', 'sha512'):
        raise IntakeError('CHECKSUM_ALGORITHM_UNSUPPORTED')
    algorithm = advertised['algorithm']
    value = advertised.get('value')
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{' + str(hashlib.new(algorithm).digest_size * 2) + r'}', value):
        raise IntakeError('ADVERTISED_CHECKSUM_INVALID')
    actual = hashlib.new(algorithm, raw).hexdigest()
    return {'algorithm': algorithm, 'origin': advertised.get('origin'), 'status': 'MATCH' if actual == value.lower() else 'MISMATCH',
            'verified_against_download': actual == value.lower(), 'actual_value': actual}


def acquisition(provider, record, selected_file):
    """Return raw_bytes internally plus a JSON-safe receipt; never auto-approve."""
    try:
        selected, license_id, host, path = _selection(provider, record, selected_file)
        raw, http = _get_bytes(host, path)
        _csv(raw)
        if len(raw) != selected['size']:
            raise IntakeError('ADVERTISED_SIZE_MISMATCH')
        checksums = [_checksum_comparison(raw, selected.get(k)) for k in ('checksum', 'supplied_checksum')]
        if any(item['status'] == 'MISMATCH' for item in checksums):
            raise IntakeError('ADVERTISED_CHECKSUM_MISMATCH')
        context = _record_context(provider, record, selected)
        receipt = _seal({'schema': SCHEMA, 'provider': provider, 'record_context': context,
                         'record_context_sha256': _digest(context), 'metadata_provenance': record['provenance'],
                         'download': http, 'advertised_size': selected['size'], 'actual_size': len(raw),
                         'actual_sha256': _sha(raw), 'license_policy': license_id,
                         'advertised_checksum': selected.get('checksum'), 'uploader_checksum': selected.get('supplied_checksum'),
                         'checksum_comparisons': checksums, 'verified': False, 'approved': False,
                         'limitations': list(LIMITATIONS)})
        return {'success': True, 'state': 'ACQUIRED', 'raw_bytes': raw, 'receipt': receipt, 'error': None,
                'approved': False, 'verified': False}
    except (IntakeError, TypeError, ValueError, KeyError) as exc:
        return _blocked(str(exc) if isinstance(exc, IntakeError) else 'INTAKE_INPUT_INVALID')


def _registered_case(claim_id):
    if claim_id != REGISTERED_CLAIM_ID:
        raise IntakeError('REGISTERED_SOURCE_NOT_ALLOWED')
    from finals.finals_cases import load_case
    case = load_case(claim_id)
    if not case.get('source_gate') or case['source'].get('data_original_url') != 'https://raw.githubusercontent.com' + REGISTERED_PATH:
        raise IntakeError('REGISTERED_SOURCE_INVALID')
    return case


def acquisition_registered(claim_id=REGISTERED_CLAIM_ID):
    """Only the already registered, exact 40-hex upstream source pair is supported."""
    try:
        case = _registered_case(claim_id)
        license_bytes, license_http = _get_bytes('raw.githubusercontent.com', LICENSE_PATH, max_bytes=64 * 1024)
        if not re.search(r'^License:\s*CC0\s*$', license_bytes.decode('utf-8'), re.M):
            raise IntakeError('PINNED_DATA_LICENSE_NOT_CONFIRMED')
        raw, http = _get_bytes('raw.githubusercontent.com', REGISTERED_PATH)
        _csv(raw)
        actual = _sha(raw)
        if actual != case['registered_data_sha256']:
            raise IntakeError('REGISTERED_DATA_SHA256_MISMATCH')
        item = case['source']
        context = {'provider': 'registered', 'claim_id': claim_id, 'upstream_commit': PIN,
                   'original_data_url': item['data_original_url'], 'registered_data_sha256': case['registered_data_sha256'],
                   'paper_url': item['paper_url'], 'source_public_derivative_sha256': case['source_sha256'],
                   'source_quote': case['source_quote'], 'source_location': case['source_location'],
                   'source_capture_method': item.get('source_capture_method')}
        receipt = _seal({'schema': SCHEMA, 'provider': 'registered', 'record_context': context,
                         'record_context_sha256': _digest(context), 'download': http,
                         'actual_size': len(raw), 'actual_sha256': actual, 'license_policy': 'CC0-1.0',
                         'license_proof': {**license_http, 'sha256': _sha(license_bytes), 'statement': 'License: CC0'},
                         'advertised_checksum': None, 'checksum_comparisons': [{'status': 'NOT_ADVERTISED', 'verified_against_download': False}],
                         'registered_checksum_comparison': {'status': 'MATCH', 'origin': 'existing_public_registry', 'sha256': actual},
                         'source_capture': {'kind': 'CONTACTS_REMOVED_PUBLIC_DERIVATIVE', 'sha256': case['source_sha256'],
                                            'original_publisher_bytes_sha256': None},
                         'verified': False, 'approved': False, 'limitations': list(LIMITATIONS)})
        location = {'source_id': 'RJ-2022-020', 'locator': case['source_location'], 'quote': case['source_quote']}
        spec = empty_spec(claim_id)
        spec.update(method='row_count', reported_value=item['reported_value'], filters=[], missing_policy='not_applicable',
                    missing_tokens=[], denominator='all CSV data rows, without filtering', unit='individual penguins',
                    data_fingerprint=actual, tolerance=item['tolerance'], source_location=location)
        paper = {'paper_doi': '10.32614/RJ-2022-020', 'source_id': 'RJ-2022-020', 'paper_version': 'published article; registered public derivative',
                 'source_url': case['paper_url'], 'source_sha256': case['source_sha256'],
                 'source_kind': 'CONTACTS_REMOVED_PUBLIC_DERIVATIVE'}
        return {'success': True, 'state': 'ACQUIRED', 'raw_bytes': raw, 'receipt': receipt,
                'suggested_spec': spec, 'paper_context': paper, 'source_location': location,
                'approved': False, 'verified': False, 'error': None}
    except (IntakeError, ValueError, TypeError, KeyError, OSError):
        return _blocked('REGISTERED_ACQUISITION_BLOCKED')


def _paper_context(paper):
    if not isinstance(paper, dict) or not isinstance(paper.get('paper_version'), str) or not paper['paper_version'].strip():
        raise IntakeError('PAPER_VERSION_REQUIRED')
    _public(paper)
    url = urlsplit(str(paper.get('source_url') or ''))
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment or re.search(r'(?:key|token|secret|password)=', url.query, re.I):
        raise IntakeError('PAPER_SOURCE_REQUIRED')
    digest = paper.get('source_sha256')
    if digest is not None and not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
        raise IntakeError('PAPER_HASH_INVALID')
    return deepcopy(paper)


def _current_receipt(raw, receipt, current_record):
    if not _intact(receipt) or receipt.get('schema') != SCHEMA:
        raise IntakeError('RECEIPT_INTEGRITY_INVALID')
    _csv(raw)
    if receipt.get('actual_sha256') != _sha(raw) or receipt.get('actual_size') != len(raw):
        raise IntakeError('STALE_DATA')
    context = receipt.get('record_context')
    if receipt.get('record_context_sha256') != _digest(context):
        raise IntakeError('STALE_RECORD')
    if receipt.get('provider') == 'registered':
        case = _registered_case(context.get('claim_id'))
        if case['source_sha256'] != context.get('source_public_derivative_sha256') or case['registered_data_sha256'] != _sha(raw) or case['source_quote'] != context.get('source_quote') or case['source_location'] != context.get('source_location'):
            raise IntakeError('STALE_REGISTERED_SOURCE')
    elif current_record is not None:
        selected, _, _, _ = _selection(receipt['provider'], current_record, context['selected_file']['id'])
        if _digest(_record_context(receipt['provider'], current_record, selected)) != receipt['record_context_sha256']:
            raise IntakeError('STALE_RECORD')


def verify_download(raw_bytes, receipt, spec, *, paper_context, conditions_confirmed=False,
                    current_record=None, reference_ids=None, prior_approval=None):
    """Use the existing gate; return a bound report without granting human approval."""
    try:
        _current_receipt(raw_bytes, receipt, current_record)
        paper = _paper_context(paper_context)
        # [수정: 0 이영 · Codex] 2026-10-01 03:14 KST — 사용자가 선언한 원문 지문을 실제 취득 증거로 간주하지 않는다. 등록 사례는 확인된 공개 사본 URL·지문과 반드시 결속한다.
        source_status = {'status': 'NOT_ACQUIRED', 'declared_sha256': paper.get('source_sha256'), 'actual_sha256': None}
        if receipt.get('provider') == 'registered':
            context = receipt['record_context']
            if paper.get('source_url') != context['paper_url'] or paper.get('source_sha256') != context['source_public_derivative_sha256']:
                raise IntakeError('PAPER_SOURCE_NOT_BOUND')
            if paper.get('paper_doi') != '10.32614/RJ-2022-020' or paper.get('paper_version') != 'published article; registered public derivative':
                raise IntakeError('PAPER_VERSION_NOT_BOUND')
            source_status = {'status': 'REGISTERED_PUBLIC_DERIVATIVE_CONFIRMED',
                             'actual_sha256': context['source_public_derivative_sha256'],
                             'original_publisher_response_sha256': None}
            # [수정: 0 이영] 2026-10-01 04:33 KST — 고정 등록 사례의 새 승인도 같은 숫자의 다른 집단·단위·원문 위치로 우회하지 못하게 등록 계약을 대조한다.
            registered = _registered_case(context['claim_id'])
            required = {'method': 'row_count', 'variable': None, 'filters': [],
                        'missing_policy': 'not_applicable', 'missing_tokens': [],
                        'denominator': 'all CSV data rows, without filtering', 'unit': 'individual penguins',
                        'reported_value': registered['source']['reported_value'],
                        'tolerance': registered['source']['tolerance'],
                        'source_location': {'source_id': 'RJ-2022-020', 'locator': registered['source_location'],
                                            'quote': registered['source_quote']}}
            if any(spec.get(key) != value for key, value in required.items()):
                raise IntakeError('REGISTERED_CONDITIONS_DIFFER')
        _public(spec)
        if conditions_confirmed is not True:
            raise IntakeError('CONDITIONS_NOT_CONFIRMED')
        if not validate(spec)['ready'] or not spec.get('denominator') or not spec.get('unit') or spec.get('missing_policy') is None or spec.get('missing_tokens') is None:
            raise IntakeError('SPEC_NOT_READY')
        if spec['data_fingerprint'] != receipt['actual_sha256']:
            raise IntakeError('STALE_SPEC_DATA')
        _public(reference_ids)
        revision = source_revision()
        bindings = {'data_sha256': _sha(raw_bytes), 'record_sha256': receipt['record_context_sha256'],
                    'paper_context_sha256': _digest(paper), 'spec_sha256': spec_sha256(spec),
                    'reference_sha256': _digest(reference_ids), 'engine_source_revision': revision}
        if prior_approval is not None and (not isinstance(prior_approval, dict) or prior_approval.get('bindings') != bindings):
            raise IntakeError('STALE_APPROVAL')
        result = gate.evaluate(spec, raw_bytes, reference_ids=reference_ids)
        if source_revision() != revision:
            raise IntakeError('SOURCE_CHANGED_DURING_CALCULATION')
        # Existing error details can contain source cells. Keep only scalar/aggregate results and codes.
        calculation = {key: deepcopy(result[key]) for key in ('claim_id', 'method', 'verdict', 'reason_code', 'computed', 'reported', 'tolerance', 'spec_sha256', 'data_sha256', 'comparisons') if key in result}
        _public(calculation)
        matched = result.get('verdict') == 'MATCH'
        blocked = result.get('verdict') == 'BLOCK'
        report = {'schema': SCHEMA, 'success': not blocked, 'state': 'BLOCKED' if blocked else 'NEEDS_HUMAN_REVIEW',
                  'action': 'BLOCK' if blocked else 'NEEDS_HUMAN_REVIEW', 'can_approve': matched,
                  'approved': False, 'verified': False, 'receipt': deepcopy(receipt), 'spec': deepcopy(spec),
                  'paper_context': paper, 'paper_source_status': source_status, 'bindings': bindings, 'calculation': calculation,
                  'human_approval': None, 'calculated_at_kst': _now(), 'conditions_confirmed': True,
                  'limitations': list(LIMITATIONS) + ([] if receipt.get('provider') == 'registered' else ['PAPER_BYTES_NOT_ACQUIRED', 'USER_DECLARED_PAPER_HASH_IS_NOT_ACQUISITION_PROOF'])}
        return _seal(report)
    except (IntakeError, ValueError, TypeError, KeyError, OSError) as exc:
        return _blocked(str(exc) if isinstance(exc, IntakeError) else 'VERIFICATION_INPUT_INVALID')


def approve_download(report, *, raw_bytes, receipt, spec, paper_context, actor, actor_role,
                     confirmed, reason, current_record=None, reference_ids=None):
    """Explicit authorized review re-calculates current inputs before binding approval."""
    try:
        if confirmed is not True or not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
            raise IntakeError('EXPLICIT_REVIEW_REQUIRED')
        _public({'actor': actor, 'reason': reason})
        if not can(actor_role, 'approve'):
            raise IntakeError('APPROVAL_ROLE_REQUIRED')
        if not _intact(report) or report.get('schema') != SCHEMA or report.get('can_approve') is not True:
            raise IntakeError('REVIEW_REPORT_NOT_READY')
        fresh = verify_download(raw_bytes, receipt, spec, paper_context=paper_context, conditions_confirmed=True,
                                current_record=current_record, reference_ids=reference_ids)
        if fresh.get('can_approve') is not True or fresh.get('bindings') != report.get('bindings'):
            raise IntakeError('STALE_APPROVAL')
        fresh.update(state='APPROVED_ARITHMETIC_SCOPE', action='HUMAN_REVIEWED', approved=True, verified=False,
                     human_approval={'actor': actor, 'role': str(actor_role), 'reason': reason.strip(),
                                     'confirmed': True, 'approved_at_kst': _now(), 'active': True,
                                     'bindings': deepcopy(fresh['bindings'])})
        return _seal(fresh)
    except (IntakeError, TypeError, ValueError) as exc:
        return _blocked(str(exc) if isinstance(exc, IntakeError) else 'APPROVAL_INPUT_INVALID')


def export_report(report):
    if not _intact(report) or report.get('schema') != SCHEMA or 'raw_bytes' in report:
        raise IntakeError('REPORT_INTEGRITY_INVALID')
    _public(report)
    return _canonical(report)


def reopen_report(text):
    try:
        if not isinstance(text, str) or len(text.encode('utf-8')) > 256 * 1024:
            raise IntakeError('IMPORT_SIZE_INVALID')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise IntakeError('DUPLICATE_JSON_KEY')
                result[key] = value
            return result
        item = json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(IntakeError('NONFINITE_JSON')))
        _public(item)
        if not _intact(item) or item.get('schema') != SCHEMA or 'raw_bytes' in item:
            raise IntakeError('REPORT_INTEGRITY_INVALID')
        item['approved'] = False
        item['verified'] = False
        item['can_approve'] = False
        item['state'] = 'IMPORTED_REVALIDATION_REQUIRED'
        item['action'] = 'REVALIDATE_CURRENT_INPUTS'
        if isinstance(item.get('human_approval'), dict):
            item['human_approval']['active'] = False
        return _seal(item)
    except (IntakeError, ValueError, TypeError) as exc:
        return _blocked(str(exc) if isinstance(exc, IntakeError) else 'IMPORT_INVALID')


import_report = reopen_report


def register_download(repository, receipt, dataset_id, name):
    """Reuse EvidenceRepository's metadata transaction; CSV bytes stay outside the DB/report."""
    if not _intact(receipt) or receipt.get('schema') != SCHEMA:
        raise IntakeError('RECEIPT_INTEGRITY_INVALID')
    _public({'dataset_id': dataset_id, 'name': name})
    repository.add_dataset(dataset_id, receipt['actual_sha256'], name)
    return {'success': True, 'dataset_id': dataset_id, 'sha256': receipt['actual_sha256'], 'approved': False}
