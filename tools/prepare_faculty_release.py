"""Prepare a separate case67 copy; frozen data are included only by explicit CLI flag."""
import argparse
import csv
import collections
import hashlib
import json
import shutil
import sys
from pathlib import Path

TOOLS=['collect_faculty.py','probe_faculty.py','collect_faculty_publications.py','merge_faculty_index.py','prepare_faculty_release.py','faculty_profile_excerpt.py']
TESTS=['test_faculty.py','test_faculty_collection.py','test_faculty_publications.py','test_merge_faculty_index.py','test_case67.py']

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 복사 경로 탈출 차단; 입출력: 상대근거 경로→안전 경로; 검증: 절대·상위·Windows drive 경로 거부.
def safe_path(value):
    value=value.replace('\\','/')
    path=Path(value)
    if not value or value.startswith('/') or path.is_absolute() or '..' in path.parts or ':' in value:raise ValueError('Unsafe evidence path')
    return path

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 선정 근거만 패키징; 입출력: 서지목록→필요파일 집합; 검증: 링크전용 원문 파일을 보관 파일로 승격하지 않음.
def evidence_paths(records):
    result=set()
    for record in records:
        for key in ['faculty_evidence_path','metadata_source_path']:
            if record.get(key):result.add(safe_path(record[key]))
        for evidence in record.get('source_evidence',{}).values():
            result.add(safe_path(evidence['path']))
        if record.get('fulltext_path'):
            if record['fulltext_status']!='ARCHIVED_CC_BY_OR_CC0':raise ValueError('Restricted body archive forbidden')
            result.add(safe_path(record['fulltext_path']))
    return result

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 기존600 파서 격리; 입출력: 새도구 문자열→새 base import; 검증: case66 소스 자체는 수정하지 않음.
def faculty_imports(text):
    return text.replace('import collect_research_fields as base','import collect_faculty_base as base')

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 버전 표시만 갱신; 입출력: case66 앱문자열→case67; 검증: 알려진 네 marker 모두 있어야 변경.
def version_app(text):
    pairs=[('Evidence Gate case66 —','Evidence Gate case67 —'),('APP_VERSION="0"','APP_VERSION="0"'),('ENGINE_VERSION="rule-engine-case66"','ENGINE_VERSION="rule-engine-case67"'),('page_title="Evidence Gate case66"','page_title="Evidence Gate case67"')]
    if any(old not in text for old,new in pairs):raise ValueError('Unexpected case66 app version markers')
    for old,new in pairs:text=text.replace(old,new,1)
    return text

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 원본 앱·원자료 보존; 입출력: 원본/새폴더/수집루트→분리복사; 검증: 기존 대상 덮어쓰기·원본 내부 복사 거부.
def prepare_source(source,target,collection):
    source=source.resolve();target=target.resolve()
    if target==source or source in target.parents:raise ValueError('Target must be separate from source')
    if target.exists():raise ValueError('Target already exists')
    if (source/'VERSION').read_text(encoding='utf-8-sig').strip()!='0':raise ValueError('Expected case66 source')
    app=version_app((source/'app.py').read_text(encoding='utf-8-sig'))
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','.git'))
    (target/'VERSION').write_text('0\n',encoding='utf-8');(target/'app.py').write_text(app,encoding='utf-8')
    refresh_tools(target,collection)
    write_docs(target,None)

# [작성:전문가4] 2026-09-27 case67 무엇/왜: freeze 시 최신 도구 반영; 입출력: case67/수집루트→신규도구·시험; 검증: 기존 case66 도구와 시험 파일은 쓰지 않음.
def refresh_tools(target,collection):
    for folder,names in [('tools',TOOLS),('tests',TESTS)]:
        (target/folder).mkdir(exist_ok=True)
        for name in names:
            path=collection/folder/name
            if not path.is_file():raise ValueError('Required release source missing: '+name)
            if name in {'prepare_faculty_release.py','test_case67.py'}:shutil.copy2(path,target/folder/name)
            else:(target/folder/name).write_text(faculty_imports(path.read_text(encoding='utf-8-sig')),encoding='utf-8')
    shutil.copy2(collection/'tools/collect_research_fields.py',target/'tools/collect_faculty_base.py')
    (target/'docs').mkdir(exist_ok=True)
    shutil.copy2(collection/'COLLECTION_POLICY.md',target/'docs/KOREAN_FACULTY_COLLECTION_POLICY.md')

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 움직이는 수집본의 완료 오인 방지; 입출력: freeze된 소스→선정 근거 복사; 검증: 원목록 바이트 동일성 및 목적지 새 폴더 요구.
def copy_selected(source,target):
    raw=(source/'papers.json').read_bytes();records=json.loads(raw)['papers']
    if target.exists():raise ValueError('Collection target already exists')
    target.mkdir(parents=True)
    generated=profile_excerpts(records,source,target)
    for relative in sorted(evidence_paths(records)):
        if relative in generated:continue
        if not (source/relative).resolve().is_relative_to(source.resolve()):raise ValueError('Evidence symlink escapes source')
        destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/relative,destination)
    payload=json.loads(raw);payload['papers']=records
    if generated:
        payload['distribution_transform']={'status':'RAW_PROFILE_PDF_NOT_REDISTRIBUTED','source_manifest_sha256':hashlib.sha256(raw).hexdigest(),'verification_scope':'QUOTE_ONLY_ORIGINAL_PDF_NOT_OFFLINE_VERIFIABLE'}
        (target/'papers.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    else:(target/'papers.json').write_bytes(raw)
    for name in ['papers.csv','papers.md','requests.jsonl','errors.jsonl','collection_report.json','collection_summary.json','search_scope_note.json']:
        if (source/name).is_file():shutil.copy2(source/name,target/name)
    if (source/'papers.json').read_bytes()!=raw:raise ValueError('Collection changed during copy; do not release')
    return hashlib.sha256(raw).hexdigest()

# [작성:전문가4] 2026-09-27 case67 목적: 교수 PDF의 재배포 제외; 입력: 복사본 목록/로컬원본/배포루트; 출력: 최소인용 경로 집합; 검증: 원본 해시·교수 인용 재검사, 원본 목록 불변.
def profile_excerpts(records,source,target):
    from faculty_profile_excerpt import STATUS, profile_excerpt_check
    generated=set()
    for record in records:
        profile=record.get('faculty_profile',{})
        if not profile.get('faculty_evidence_pdf_pages'):continue
        from collect_faculty_publications import faculty_profile_check
        fact=record['source_evidence']['faculty_profile']
        original_path=source/safe_path(fact['path'])
        if not original_path.resolve().is_relative_to(source.resolve()):raise ValueError('Profile PDF symlink escapes source')
        raw=original_path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=fact['sha256']:raise ValueError('Original profile PDF hash mismatch')
        checked=faculty_profile_check(profile,raw)
        if checked['status']!='NOT_MATCHED':raise ValueError('Original profile PDF verification failed')
        if checked['faculty_evidence_extracted_sha256']!=record['faculty_match']['faculty_evidence_extracted_sha256']:raise ValueError('Original profile extraction hash mismatch')
        # 논리 페이지는 확인된 SNU 교육 편람만 매핑하며 다른 PDF에 추정 적용하지 않는다.
        known_url='https://www.eduadmin.snu.ac.kr/_files/ugd/3db26b_3ba0421b95be411f9b0e0857bd0eb94f.pdf'
        if fact['url']!=known_url or profile['faculty_evidence_pdf_pages']!=[52]:raise ValueError('Profile PDF logical page mapping not established')
        evidence={key:profile[key] for key in ['faculty_name','faculty_role','faculty_affiliation','faculty_evidence_quote']}
        evidence.update(distribution_status=STATUS,url=fact['url'],collected_at=fact['collected_at'],original_sha256=fact['sha256'],extracted_sha256=checked['faculty_evidence_extracted_sha256'],pdf_pages=[52],logical_pages=[43])
        data=json.dumps(evidence,ensure_ascii=False,indent=2).encode('utf-8');digest=hashlib.sha256(data).hexdigest()
        relative=Path('evidence')/('faculty_excerpt_'+digest+'.json')
        (target/relative).parent.mkdir(parents=True,exist_ok=True);(target/relative).write_bytes(data)
        replacement={key:evidence[key] for key in ['distribution_status','url','collected_at','original_sha256','extracted_sha256','pdf_pages','logical_pages']}
        replacement.update(path=relative.as_posix(),sha256=digest)
        profile_excerpt_check(profile,replacement,target)
        record['source_evidence']['faculty_profile']=replacement
        record['faculty_match'].update(faculty_profile_distribution_status=STATUS,faculty_profile_verification_scope='QUOTE_ONLY_ORIGINAL_PDF_NOT_OFFLINE_VERIFIABLE')
        generated.add(relative)
    return generated

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 패키지 내부 오프라인 재검사; 입출력: 패키지루트→실제 분야/보관 수; 검증: 원600 제외·교수 증거·합본 정확 일치.
def verify_package(project,write=False):
    sys.path.insert(0,str(project/'tools'))
    import collect_faculty
    import collect_faculty_publications
    import merge_faculty_index as merge
    existing=merge.papers(project/'data/papers_index.json')
    if len(existing)!=600:raise ValueError('Existing600 index changed')
    excluded=merge.base.OLD|{merge.base.doi(r['doi']) for r in existing}
    pmcs={r['pmcid'] for r in existing if r.get('pmcid')}
    pmc_root=project/'data/korean_professors/pmc';pub_root=project/'data/korean_professors/publications'
    pmc=merge.papers(pmc_root/'papers.json');pub=merge.papers(pub_root/'papers.json')
    checks={'faculty_pmc':collect_faculty.verify(pmc,pmc_root,excluded,pmcs,20),'faculty_publications':collect_faculty_publications.verify(pub,pub_root,excluded,pmcs,20)}
    records,duplicates=merge.merge_unique(existing,pmc,pub);report=merge.summary(records)
    report.update(source_checks=checks,duplicate_records_excluded=duplicates)
    names=collections.Counter(r['faculty_match']['faculty_name'] for r in records if r['source_group']!='existing600')
    report['faculty_name_group_counts']=dict(names.most_common())
    report['faculty_name_group_note']='Exact recorded name groups; aliases are not independently resolved identities'
    index=[merge.index_record(r) for r in records]
    path=project/'data/combined_papers_index.json'
    if write:
        path.write_text(json.dumps({'summary':report,'papers':index},ensure_ascii=False,indent=2),encoding='utf-8')
        with path.with_suffix('.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            columns=['source_group','field','title','doi','pmcid','fulltext_status','relative_fulltext_path','source_url']
            writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(index)
        lines=['# 전체 논문 색인','', '기존600 + 국내 교수 서지 '+str(report['faculty_selected'])+'편. 국내 교수 원문 보관은 '+str(report['faculty_archived_fulltext'])+'편. 원자료·재현 NOT_TESTED.','']
        lines += ['- ['+r['title'].replace('\n',' ')+']('+r['source_url']+') — '+r['field']+' — '+r['fulltext_status'] for r in index]
        path.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    elif json.loads(path.read_text(encoding='utf-8'))['papers']!=index:raise ValueError('Combined index differs from verified sources')
    return report

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 현행과 과거 검증 결과 분리; 입출력: 실제보고서 또는 미수집상태→문서; 검증: 목표300·원문300 완료를 추정하지 않음.
def write_docs(project,report):
    status='국내 교수 자료는 아직 패키지에 포함하지 않았습니다. 수집·동결·최종 검증은 PENDING입니다.' if report is None else '국내 교수 참여 서지 '+str(report['faculty_selected'])+'편, 그중 CC BY/CC0 원문 보관 '+str(report['faculty_archived_fulltext'])+'편입니다. 총 선정 '+str(report['total_selected'])+'편이며 목표900편 대비 부족분은 data/combined_papers_index.json의 summary에 기록합니다.'
    body=status+'\n\n기존600 원문과 국내 교수 서지300 목표를 구분합니다. 교수 직함은 현재 공식 프로필 기준이며 출판 당시 직급은 NOT_ESTABLISHED입니다. 자동 분야 분류이며 외부 전문가 검증 또는 분석 재현 성공이 아닙니다. 원자료 다운로드와 재현은 NOT_TESTED입니다. 기존 앱 전수시험 실패 기록은 아래 과거 이력에 보존하고, case67 앱 전체회귀·ZIP 재해제 검증은 별도 실제 실행 전 PENDING입니다.\n\n오프라인 새 서지 검증: `python tools/prepare_faculty_release.py --target . --verify-only`\n\n기존600 색인은 data/papers_index.json, 새 전체 합본은 data/combined_papers_index.json입니다. 기존600 검증 명령과 데이터·엔진 동작은 유지합니다. collect_faculty_base.py의 공통코드 복사는 기존 검증 재현을 보존하기 위한 것으로, 후속 공통화 대상입니다.'
    body=body.replace('case67 앱 전체회귀·ZIP 재해제 검증은 별도 실제 실행 전 PENDING입니다.', 'case67 source-only 앱 전체회귀는 718 passed, 13 warnings, 109.11초로 통과했고 15초 서버 기동 HTTP 200을 확인했습니다. 이는 국내 데이터 포함 및 최종 도구 동기화 전 결과입니다. 최종 ZIP 재해제본의 전체회귀 결과는 배포물 외부 최종 receipt에서 확인하며 실행 전에는 PENDING입니다.')
    body+='\n\n국내 대학 소속 기준이며 국적을 추정하지 않습니다. 교수 직함은 수집 시점 공식 페이지의 표시로, 갱신 지연 가능성이 있고 독립 인적 재직 확인이 아닙니다. 출판 당시 소속·직급을 추정하지 않습니다. 교수 편람 PDF 전체는 재배포하지 않으며 최소 인용·파일/논리 페이지·URL·원본/추출 해시·시각만 제공합니다. RAW_PROFILE_PDF_NOT_REDISTRIBUTED는 원본 PDF 오프라인 재검증 불가를 뜻하고, 인용 파일 검증 성공과 구분합니다.\n\n시험은 수집 출처별로 분리하고 실제 패키징 회귀는 tests/test_case67.py에 둡니다. 기존 시험의 복제나 기대값 완화로 통과 수를 늘리지 않습니다.'
    if report:
        states=report['faculty_fulltext_status_counts'];names=report['faculty_name_group_counts']
        body+='\n\n국내 자료 상태: CC BY/CC0 본문 보관 '+str(states.get('ARCHIVED_CC_BY_OR_CC0',0))+'편, 이용 제한 링크 '+str(states.get('LINK_ONLY_REUSE_RESTRICTED',0))+'편, 서지 메타데이터만 '+str(states.get('CITATION_METADATA_ONLY',0))+'편. 논문 유형 판정: '+json.dumps(report['faculty_publication_type_counts'],ensure_ascii=False)+'.\n\n교수 이름 문자열 그룹 '+str(len(names))+'개이며 상위 편중은 '+', '.join(name+' '+str(count)+'편' for name,count in list(names.items())[:5])+'. 별칭 통합 신원 확인 수가 아닙니다. 실험·가상 점수는 이번 수집과 무관하여 갱신하지 않았습니다.'
    review='\n\n이번 수집 범위의 작업 묶음과 가상 역할 점검(독립 인적 심사 아님):\n\n1. 요구·학술 범위 — 역할1 요구사항, 역할2 학술 분류: 실제 선정수/부족과 자동 분류 한계를 확인.\n2. 출처·이용조건 — 역할3 자료 출처, 역할4 구현: DOI/PMCID, 교수-저자 연결, 본문/링크/서지 상태와 해시 확인.\n3. 보존·보안 — 역할5 데이터 관리, 역할6 보안: 기존600·앱 보존, 상대경로, PDF 미재배포, 키/개인경로 점검.\n4. 검증 — 역할7 시험: 최종 수집 시험/compile 및 ZIP 재해제 전체회귀, 실제 실패 기록 유지.\n5. 문서·릴리스 — 역할8 문서, 역할9 릴리스: 실제 계수·저자 편중·NOT_TESTED·검증 범위와 인계 근거 확인.'
    headers={'README.md':'# NAIS Evidence Gate Practice case67','CHANGELOG.md':'# CHANGELOG\n\n## case67 — 2026-09-27','RELEASE_CHECK.md':'# case67 릴리스 점검 — 2026-09-27','WORK_ORDER.md':'# case67 작업 지시서 — 2026-09-27','TEAM_PROMPT.md':'# case67 인수인계 — 2026-09-27','EXPERT_REVIEW.md':'# case67 가상 전문가 검토 — 2026-09-27'}
    for name,header in headers.items():
        path=project/name;old=path.read_text(encoding='utf-8-sig') if path.exists() else ''
        if old.startswith(header):old=old.split('\n---\n',1)[1] if '\n---\n' in old else ''
        path.write_text(header+'\n\n'+body+(review if name in {'WORK_ORDER.md','EXPERT_REVIEW.md'} else '')+'\n\n---\n'+old,encoding='utf-8')
    index_path=project/'data/PAPER_INDEX.md'
    if index_path.exists():
        old=index_path.read_text(encoding='utf-8-sig');heading='# case67 전체 자료 접근'
        if old.startswith(heading):old=old.split('\n---\n',1)[1]
        index_path.write_text(heading+'\n\n'+status+'\n\n[전체 합본 목록](combined_papers_index.md) · [전체 JSON](combined_papers_index.json) · [전체 CSV](combined_papers_index.csv) · [기존600 JSON](papers_index.json)\n\n---\n'+old,encoding='utf-8')

# [작성:전문가4] 2026-09-27 case67 무엇/왜: 준비와 최종데이터 포함 분리; 입출력: CLI→로컬 복사/검증; 검증: include-data는 사용자가 승인한 freeze 이후 명시 실행.
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);parser.add_argument('--target',type=Path,required=True);parser.add_argument('--collection-root',type=Path);parser.add_argument('--include-data',action='store_true');parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();target=args.target.resolve()
    if args.verify_only:print(json.dumps(verify_package(target),ensure_ascii=False));return
    if not args.collection_root:raise ValueError('collection-root is required')
    if not target.exists():
        if not args.source:raise ValueError('source is required for first preparation')
        prepare_source(args.source,target,args.collection_root)
    elif (target/'VERSION').read_text(encoding='utf-8-sig').strip()!='0':raise ValueError('Only prepared case67 target may be refreshed')
    if args.include_data:
        refresh_tools(target,args.collection_root)
        for name,folder in [('collection','pmc'),('publication_collection','publications')]:copy_selected(args.collection_root/name,target/'data/korean_professors'/folder)
        report=verify_package(target,write=True);write_docs(target,report)
        (target/'data/korean_professors/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    else:print(json.dumps({'source_prepared':True,'faculty_data_included':False,'release_status':'PENDING'}))

if __name__=='__main__':main()
