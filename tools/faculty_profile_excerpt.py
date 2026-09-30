"""Distribution-only faculty quotations; original PDF verification remains local."""
import hashlib
import json
import re
from pathlib import Path
from probe_faculty import match_faculty

STATUS = 'RAW_PROFILE_PDF_NOT_REDISTRIBUTED'
SCOPE = 'QUOTE_ONLY_ORIGINAL_PDF_NOT_OFFLINE_VERIFIABLE'

# [작성:전문가4] 2026-09-27 case67 목적: 배포 인용과 PDF 검증 구분; 입력: 프로필/배포근거/루트; 출력: 제한 명시 match facts; 검증: 해시·경로·출처·인용 일치.
def profile_excerpt_check(profile, fact, root):
    value = fact['path'].replace('\\', '/')
    relative = Path(value)
    if not value or value.startswith('/') or relative.is_absolute() or '..' in relative.parts or ':' in value:
        raise ValueError('Unsafe profile excerpt path')
    path = Path(root) / relative
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Profile excerpt escapes root')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != fact['sha256']:
        raise ValueError('Profile excerpt hash mismatch')
    evidence = json.loads(raw)
    if fact.get('distribution_status') != STATUS or evidence.get('distribution_status') != STATUS:
        raise ValueError('Missing PDF non-redistribution status')
    for key in ['url', 'collected_at', 'original_sha256', 'extracted_sha256', 'pdf_pages', 'logical_pages']:
        if evidence.get(key) != fact.get(key):
            raise ValueError('Profile excerpt provenance mismatch: ' + key)
    if fact['url'] != profile['faculty_evidence_url'] or fact['pdf_pages'] != profile['faculty_evidence_pdf_pages']:
        raise ValueError('Profile excerpt source mismatch')
    if not fact['logical_pages'] or not all(isinstance(n, int) and n > 0 for n in fact['logical_pages'] + fact['pdf_pages']):
        raise ValueError('Invalid profile excerpt pages')
    if not fact['collected_at'] or any(not re.fullmatch(r'[0-9a-f]{64}', fact[k]) for k in ['original_sha256', 'extracted_sha256']):
        raise ValueError('Invalid original evidence provenance')
    for key in ['faculty_name', 'faculty_role', 'faculty_affiliation', 'faculty_evidence_quote']:
        if evidence.get(key) != profile.get(key):
            raise ValueError('Profile excerpt fact mismatch: ' + key)
    checked = match_faculty(profile, evidence['faculty_evidence_quote'].encode('utf-8'), [])
    if checked['status'] != 'NOT_MATCHED':
        raise ValueError('Profile excerpt quote does not establish name and role')
    checked.update(faculty_evidence_sha256=fact['original_sha256'], faculty_evidence_pdf_pages=fact['pdf_pages'],
                   faculty_evidence_extracted_sha256=fact['extracted_sha256'], faculty_evidence_extractor='pypdf',
                   faculty_profile_distribution_status=STATUS, faculty_profile_verification_scope=SCOPE)
    return checked
