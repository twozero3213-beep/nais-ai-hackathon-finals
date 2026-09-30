"""[전문가4] 2026-09-27 case66: 검증된 50+250+300 수집본의 상대경로 통합 색인 생성."""
import argparse
from collections import Counter
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

FIELDS = ['group', 'field', 'title', 'doi', 'pmcid', 'year', 'date', 'article_type', 'reference_role', 'license', 'source_url', 'relative_fulltext_path', 'fulltext_sha256', 'raw_data_download_status', 'reproduction_status']


# [전문가4] 2026-09-27 case66: 외부 링크는 HTTP(S)와 호스트를 확인하고 마크다운 제어문자를 인코딩.
def link(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or '://' in value.split('://', 1)[1] or any(c.isspace() for c in value):
        raise ValueError('Invalid source URL')
    return quote(value, safe=':/?#=&%+@,;~_-')


# [전문가4] 2026-09-27 case66: 제목·라이선스의 표 구분자와 개행을 이스케이프해 논문 한 편당 한 행 유지.
def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ').replace('[', '\\[').replace(']', '\\]')


# [전문가4] 2026-09-27 case66: 상대 원문 경로만 허용하고 실제 파일·SHA256·미실행 상태를 검증.
def record(row, group, base, data):
    source_path = row.get('source_file') if group == 'candidate50' else row.get('fulltext_path')
    relative = Path(str(source_path or '').replace('\\', '/'))
    if not source_path or relative.is_absolute() or '..' in relative.parts or ':' in str(relative):
        raise ValueError('Invalid relative fulltext path')
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError('Missing or escaped fulltext path')
    digest = row.get('source_sha256') if group == 'candidate50' else row.get('fulltext_sha256')
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Fulltext hash mismatch')
    doi = str(row['doi']).strip().lower().removeprefix('https://doi.org/')
    if not re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        raise ValueError('Invalid DOI')
    pmcid = str(row['pmcid']).upper()
    if not re.fullmatch(r'PMC\d+', pmcid):
        raise ValueError('Invalid PMCID')
    status = row.get('reproducibility_status', row.get('reproduction_status'))
    if row['raw_data_download_status'] != 'NOT_TESTED' or status != 'NOT_TESTED':
        raise ValueError('Unexpected tested status')
    if group == 'applied' and row.get('article_type') != 'research-article':
        raise ValueError('Applied corpus requires research articles')
    url = row.get('fulltext_url') or row.get('source_url') or row.get('url')
    link(url)
    date = row.get('date', row.get('publication_date', row.get('first_publication_date', '')))
    # [전문가4] 2026-09-27 case66: 제목·원문 유형의 단순 파생 안내로 의미 인증이나 신규성 판단을 대체하지 않음.
    if group == 'candidate50':
        role = '공개자료 연결 후보'
    elif group == 'applied':
        role = '응용 연구 후보'
    elif re.search(r'\b(?:CONSORT|SPIRIT|guidelines?|checklists?|reporting standards?)\b', row['title'], re.I):
        role = '평가·보고 지침(제목 기준)'
    elif row.get('article_type') == 'review-article':
        role = '문헌 검토·설계 배경'
    else:
        role = '기술 연구 참고'
    return dict(zip(FIELDS, [group, 'candidate50' if group == 'candidate50' else row['category'], row['title'], doi, pmcid, row.get('year') or date[:4], date, row.get('article_type', ''), role, row['license'], url, path.relative_to(data.resolve()).as_posix(), digest, 'NOT_TESTED', 'NOT_TESTED']))


# [전문가4] 2026-09-27 case66: 모두 완료된 자료만 색인화하고 600 DOI/PMCID 고유성과 분야별 분모를 강제.
def build(project):
    data = project / 'data'
    spec = importlib.util.spec_from_file_location('collector', project / 'tools/collect_public_papers.py')
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    records = []
    for group, folder, filename, expected in [('candidate50', 'public_papers', 'papers50.json', 50), ('technical', 'research_fields/technical', 'papers.json', 250), ('applied', 'research_fields/applied', 'papers.json', 300)]:
        base = data / folder
        obj = json.loads((base / filename).read_text(encoding='utf-8-sig'))
        rows = obj if group == 'candidate50' else obj['papers']
        if len(rows) != expected:
            raise ValueError(f'{group}: expected {expected}, got {len(rows)}; index remains pending')
        if group != 'candidate50' and obj['profile'] != group:
            raise ValueError('Profile mismatch')
        merged = [record(row, group, base, data) for row in rows]
        counts = Counter(row['field'] for row in merged)
        if group != 'candidate50' and (len(counts) != (5 if group == 'technical' else 10) or set(counts.values()) != {50 if group == 'technical' else 30}):
            raise ValueError('Field quota mismatch')
        records.extend(merged)
    if len({row['doi'] for row in records}) != 600 or len({row['pmcid'] for row in records}) != 600:
        raise ValueError('Duplicate DOI or PMCID across the 600 papers')
    if {row['doi'] for row in records} & {doi.lower() for doi in collector.EXCLUDED}:
        raise ValueError('Excluded historical DOI found')
    serialized = json.dumps(records, ensure_ascii=False, indent=2)
    if re.search(r'(?i)[A-Z]:[\\/]{1,2}Users[\\/]|/Users/|/home/', serialized):
        raise ValueError('Private absolute path in index')
    lines = ['# 공개 논문 통합 색인 — case66', '', '실제 확인: 600편 = 원자료 후보50 + 기술5분야×50 + 응용10분야×30. DOI와 PMCID 각각600개 고유·기존8편 제외·로컬 원문 해시를 검증했습니다.', '', '원자료 다운로드·수치 재현은 전부 NOT_TESTED입니다. 이 목록은 논문 재현 성공이나 전문가의 의미 적합성 인증을 뜻하지 않습니다. 원자료 후보50의 search_category는 검색 범주이므로 실제 연구 분야로 표시하지 않습니다. 기술·응용 분야는 제목과 초록의 자동 규칙 분류입니다. 응용 논문은 research-article만 포함합니다.', '', '## 분야별 누적 수량', '', '|묶음|분야|편수|누적|', '|---|---|---:|---:|']
    cumulative = 0
    lines[4] += ' 기술 참고문헌은 구현 방법과 평가·보고·공유 설계의 배경 문헌을 포함합니다. 문헌 역할은 제목 규칙과 원문 article_type의 파생 표시이며 전문가 확정 유형·방법론 신규성·품질 판정이 아닙니다. 분야는 본질적으로 배타적이지 않으며 수량 계산을 위해 한 논문을 한 그룹에 우선 배정했습니다. Europe PMC 수집은 모든 검색엔진이나 전체 연구를 대표하지 않습니다.'
    lines[4] += ' 탈락 후보 XML도 감사용으로 보존하므로 저장 XML 수는 선정600보다 많을 수 있습니다. 후속 분석·자료 처리는 전체 폴더를 glob하지 말고 papers_index.json의 선정600편만 사용합니다. 탈락 원문은 선정 논문 수나 재현 시험 대상으로 세지 않습니다.'
    groups = [('candidate50', '원자료 후보50'), ('technical', '제품 기술'), ('applied', '응용')]
    for group, label in groups:
        for field, count in sorted(Counter(row['field'] for row in records if row['group'] == group).items()):
            cumulative += count
            lines.append(f'|{label}|{cell(field)}|{count}|{cumulative}|')
    for group, label in groups:
        for field in sorted({row['field'] for row in records if row['group'] == group}):
            lines += ['', f'## {label} · {cell(field)}', '', '|제목|연도/날짜|DOI|PMCID|유형|문헌 역할|이용조건|원문|로컬 XML|', '|---|---|---|---|---|---|---|---|---|']
            for row in records:
                if row['group'] == group and row['field'] == field:
                    lines.append(f"|{cell(row['title'])}|{cell(row['date'] or row['year'])}|[{cell(row['doi'])}]({link('https://doi.org/' + row['doi'])})|{row['pmcid']}|{cell(row['article_type'])}|{cell(row['reference_role'])}|{cell(row['license'])}|[원문]({link(row['source_url'])})|[XML]({quote(row['relative_fulltext_path'], safe='/._-')})|")
    markdown = '\n'.join(lines) + '\n'
    (data / 'papers_index.json').write_text(serialized + '\n', encoding='utf-8')
    with (data / 'papers_index.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    (data / 'PAPER_INDEX.md').write_text(markdown, encoding='utf-8')
    (data / 'papers_index.md').write_text(markdown, encoding='utf-8')
    readme = project / 'README.md'
    text = readme.read_text(encoding='utf-8')
    if '(data/PAPER_INDEX.md)' not in text:
        heading, rest = text.split('\n', 1)
        readme.write_text(heading + '\n\n[공개 논문600편 통합 색인](data/PAPER_INDEX.md) · [CSV](data/papers_index.csv) · [JSON](data/papers_index.json)\n' + rest, encoding='utf-8')
    return {'papers': len(records), 'unique_doi': 600, 'unique_pmcid': 600, 'field_groups': 15, 'index': 'data/PAPER_INDEX.md'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.project.resolve()), ensure_ascii=False))
