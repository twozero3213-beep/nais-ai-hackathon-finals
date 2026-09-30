"""[전문가4] 2026-09-27 case67: 기존600+국내교수 실제 n 서지를 검증·색인화한다. 원본은 수정하지 않는다."""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import collect_faculty
import collect_faculty_publications
from probe_faculty import FIELDS
import collect_faculty_base as base


# [전문가4] 2026-09-27 case67: 두 기존 인덱스 형태만 수용한다.
def papers(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    return value if isinstance(value, list) else value['papers']


# [전문가4] 2026-09-27 case67: 앞선 증거가 풍부한 PMC 서지를 우선하며 중복을 편수에 더하지 않는다.
def merge_unique(existing, faculty, publications):
    output = []; duplicates = []; doi_seen = set(); pmc_seen = set(); field_counts = collections.Counter()
    for group, records in [('existing600', existing), ('faculty_pmc', faculty), ('faculty_publications', publications)]:
        for record in records:
            ident = base.doi(record.get('doi')); pmc = record.get('pmcid') or ''
            if not ident or ident in base.OLD: raise ValueError('Missing DOI or old8 exclusion violation')
            if ident in doi_seen or (pmc and pmc in pmc_seen):
                duplicates.append({'source_group': group, 'doi': ident, 'pmcid': pmc, 'reason': 'DUPLICATE_DOI_OR_PMCID'})
                continue
            field = record.get('field', record.get('category', ''))
            # [전문가4] 2026-09-27 case67: 원본은 보존하고 합본만 분야별20편으로 제한한다.
            if group != 'existing600' and field_counts[field] >= 20:
                duplicates.append({'source_group': group, 'doi': ident, 'pmcid': pmc, 'field': field, 'reason': 'QUOTA_EXCLUDED', 'record': record})
                continue
            doi_seen.add(ident)
            if pmc: pmc_seen.add(pmc)
            item = dict(record, source_group=group, doi=ident)
            item['field'] = record.get('field', record.get('category', ''))
            output.append(item)
            if group != 'existing600': field_counts[field] += 1
    return output, duplicates


# [전문가4] 2026-09-27 case67: 0편 분야와 실제 부족분을 빠뜨리지 않는다.
def summary(records):
    domestic = [record for record in records if record['source_group'] != 'existing600']
    counts = collections.Counter(record['field'] for record in domestic)
    if any(field not in FIELDS for field in counts): raise ValueError('Unknown faculty field')
    if any(count > 20 for count in counts.values()): raise ValueError('Faculty field exceeds 20')
    states = collections.Counter(record['fulltext_status'] for record in domestic)
    return {'existing600': sum(record['source_group'] == 'existing600' for record in records), 'faculty_selected': len(domestic), 'total_selected': len(records), 'target_total': 900, 'target_faculty': 300, 'target_complete': len(domestic) == 300, 'field_counts': {field: counts[field] for field in FIELDS}, 'field_shortfalls': {field: 20 - counts[field] for field in FIELDS}, 'faculty_fulltext_status_counts': dict(states), 'faculty_archived_fulltext': states['ARCHIVED_CC_BY_OR_CC0'], 'faculty_publication_type_counts': dict(collections.Counter(record.get('publication_type_status', 'NOT_CONFIRMED') for record in domestic)), 'faculty_access_status_counts': dict(collections.Counter(record.get('fulltext_access_status', 'NOT_RECORDED') for record in domestic)), 'analysis_eligibility': 'NOT_ESTABLISHED', 'raw_data_download_status': 'NOT_TESTED', 'reproduction_status': 'NOT_TESTED'}


# [전문가4] 2026-09-27 case67: 실제 입력 루트와 최종 패키지 경로를 분리하여 기존600 복제를 피한다.
def index_record(record):
    group = record['source_group']
    prefix = {'existing600': '', 'faculty_pmc': 'data/korean_professors/pmc/', 'faculty_publications': 'data/korean_professors/publications/'}[group]
    path = record.get('relative_fulltext_path') if group == 'existing600' else record.get('fulltext_path')
    if path and (Path(path).is_absolute() or '..' in Path(path).parts or ':' in path): raise ValueError('Unsafe source path')
    result = {'source_group': group, 'group': record.get('group', 'korean_faculty'), 'field': record['field'], 'title': record['title'], 'doi': record['doi'], 'pmcid': record.get('pmcid') or None, 'publication_date': record.get('publication_date', record.get('date', '')), 'article_type': record.get('article_type', 'NOT_CONFIRMED'), 'publication_type_status': record.get('publication_type_status', 'NOT_CONFIRMED'), 'reference_role': record.get('reference_role', 'UNCLASSIFIED_REFERENCE'), 'fulltext_status': record.get('fulltext_status', 'ARCHIVED_CC_BY_OR_CC0' if group == 'existing600' else 'NOT_CONFIRMED'), 'fulltext_access_status': record.get('fulltext_access_status', 'ARCHIVED' if group == 'existing600' else 'NOT_RECORDED'), 'relative_fulltext_path': prefix + path if path else None, 'fulltext_sha256': record.get('fulltext_sha256'), 'license': record.get('license', 'NOT_CONFIRMED'), 'source_url': record.get('source_url') or 'https://doi.org/' + record['doi'], 'raw_data_download_status': record['raw_data_download_status'], 'reproduction_status': record['reproduction_status'], 'analysis_eligibility': record.get('analysis_eligibility', 'NOT_ESTABLISHED')}
    result.update({key: record.get('faculty_match', {}).get(key, '') for key in ['faculty_name', 'faculty_role', 'faculty_affiliation']})
    if group != 'existing600':
        result['faculty_match'] = record['faculty_match']
        result['source_record_list'] = prefix + 'papers.json'
        result['role_at_publication'] = record.get('role_at_publication', record['faculty_match'].get('role_at_publication', 'NOT_ESTABLISHED'))
    return result


# [전문가4] 2026-09-27 case67: 검증 완료된 case66 ZIP의 인덱스 바이트를 재사용하며600원문을 재검증하지 않는다.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--existing-root', type=Path, required=True)
    parser.add_argument('--existing-zip', type=Path, required=True)
    parser.add_argument('--existing-receipt', type=Path, required=True)
    parser.add_argument('--faculty', type=Path, required=True)
    parser.add_argument('--publications', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.existing_receipt.read_text(encoding='utf-8'))
    if receipt['source_corpus']['status'] != 'PASS' or receipt['archive_byte_comparison']['status'] != 'PASS': raise ValueError('Existing600 verification receipt not PASS')
    if hashlib.sha256(args.existing_zip.read_bytes()).hexdigest() != receipt['archive']['sha256']: raise ValueError('Existing archive does not match verified receipt')
    existing_path = args.existing_root / 'data/papers_index.json'
    with ZipFile(args.existing_zip) as archive:
        entry = next(name for name in archive.namelist() if name.endswith('/data/papers_index.json'))
        if archive.read(entry) != existing_path.read_bytes(): raise ValueError('Existing index changed since verified archive')
    input_paths = {'existing600': existing_path, 'faculty_pmc': args.faculty / 'papers.json', 'faculty_publications': args.publications / 'papers.json'}
    snapshot_bytes = {key: path.read_bytes() for key, path in input_paths.items()}
    snapshots = {key: json.loads(raw) for key, raw in snapshot_bytes.items()}
    snapshots = {key: value if isinstance(value, list) else value['papers'] for key, value in snapshots.items()}
    existing = snapshots['existing600']; faculty = snapshots['faculty_pmc']; publications = snapshots['faculty_publications']
    if len(existing) != 600: raise ValueError('Existing selected index must have 600 records')
    excluded = base.OLD | {base.doi(record['doi']) for record in existing}
    excluded_pmc = {record['pmcid'] for record in existing if record.get('pmcid')}
    source_checks = {'faculty_pmc': collect_faculty.verify(faculty, args.faculty, excluded, excluded_pmc, 20), 'faculty_publications': collect_faculty_publications.verify(publications, args.publications, excluded, excluded_pmc, 20)}
    merged, duplicates = merge_unique(existing, faculty, publications)
    report = summary(merged)
    if report['existing600'] != 600: raise ValueError('Existing600 identity count changed')
    report.update(duplicate_records_excluded=duplicates, source_checks=source_checks, existing600_verification='Reused verified case66 receipt and archive/index byte match; no repeated600 XML verification')
    report['generated_at'] = base.now()
    report['source_input_sha256'] = {key: hashlib.sha256(raw).hexdigest() for key, raw in snapshot_bytes.items()}
    if any(path.read_bytes() != snapshot_bytes[key] for key, path in input_paths.items()): raise ValueError('Input collection changed during verification; rerun on a stable snapshot')
    records = [index_record(record) for record in merged]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'papers_index.json').write_text(json.dumps({'summary': report, 'papers': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    columns = [key for key in records[0] if key != 'faculty_match']
    with (args.output / 'papers_index.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore'); writer.writeheader(); writer.writerows(records)
    lines = ['# 논문 통합 목록 — 실제 선정 ' + str(len(records)) + '편', '', '기존 600편과 국내 교수 참여 서지 ' + str(report['faculty_selected']) + '편입니다. 총 목표 900편이며 미달분은 아래에 표시합니다. 국내 교수 서지는 원문 보관 ' + str(report['faculty_archived_fulltext']) + '편과 구분합니다. 자료 다운로드·분석 재현은 NOT_TESTED입니다.', '', '| 국내 교수 분야 | 실제 | 목표 | 부족 |', '|---|---:|---:|---:|']
    for field in FIELDS: lines.append(f"| {field} | {report['field_counts'][field]} | 20 | {report['field_shortfalls'][field]} |")
    for record in records:
        lines.append('\n- [' + record['title'].replace('\n', ' ') + '](' + record['source_url'] + ') — ' + record['source_group'] + '/' + record['field'] + ' — ' + record['fulltext_status'] + ' — ' + record['reference_role'])
    (args.output / 'papers_index.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (args.output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ['total_selected', 'faculty_selected', 'faculty_archived_fulltext', 'field_counts', 'field_shortfalls', 'target_complete']}), flush=True)


if __name__ == '__main__': main()
