"""Validate declarative case registration and cross-check existing engines.

This developer evaluation path is not a human approval or a paper verdict.
No paper ID selects code. Unsupported methods and pending scope stay blocked.
"""
from __future__ import annotations
import argparse
import csv
import io
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.independent_replay import replay_cases, _load_json, _finite
from tools.run_corpus_system import run_system
from tools.change_impact import _unknown_dependencies, _relative

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_STRINGS = ('paper_url', 'source_file', 'source_sha256', 'source_quote', 'source_location',
                    'source_kind', 'claim_text', 'data_file', 'data_sha256', 'method', 'scope_status')


# [작성: 확장설계·보안 담당] 2026-09-28 case87
# 무엇을: 재사용 명세의 구조검사 / 왜: 누락·중복을 기본값으로 채우지 않음 / 입력·출력: cases -> JSON 사본 / 검증: test_case87 왕복·경계.
def _template_cases(cases):
    if not isinstance(cases,list) or not 1 <= len(cases) <= 1000: raise ValueError('1~1000개 사례가 필요합니다.')
    raw=json.dumps(cases,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(raw)>2*1024*1024: raise ValueError('등록 명세는 2MB 이하만 지원합니다.')
    result=_load_json(raw)
    ids=[]
    for case in result:
        if not isinstance(case,dict) or not isinstance(case.get('claim_id'),str) or not case['claim_id'].strip(): raise ValueError('Claim ID가 필요합니다.')
        _validate_case({k:v for k,v in case.items() if k!='preprocessing_contract'})
        ids.append(case['claim_id'])
    if len(set(ids))!=len(ids): raise ValueError('중복 Claim ID')
    return result


# [작성: 확장설계 담당] 2026-09-28 case87
# 무엇을: 논문별 동일 필드만 공유 / 왜: 반복입력 절약과 명세 재사용 / 입력·출력: cases -> 템플릿 / 검증: 값·타입·순서·검산불변.
def pack_registration_template(cases, metadata=None):
    cases=_template_cases(cases)
    grouped={}
    for case in cases: grouped.setdefault(case['paper_url'],[]).append(case)
    papers=[]
    for group in grouped.values():
        keys=set.intersection(*(set(c) for c in group)) - {'claim_id'}
        shared={key:group[0][key] for key in sorted(keys) if all(json.dumps(c[key],sort_keys=True,ensure_ascii=False,allow_nan=False)==json.dumps(group[0][key],sort_keys=True,ensure_ascii=False,allow_nan=False) for c in group)}
        papers.append({'shared':shared,'claims':[{k:v for k,v in c.items() if k not in shared} for c in group]})
    template={'schema':'NAIS_REGISTRATION_TEMPLATE_1','metadata':{} if metadata is None else metadata,'case_order':[c['claim_id'] for c in cases],'papers':papers}
    expand_registration_template(template)
    return template


# [작성: 확장설계·보안 담당] 2026-09-28 case87
# 무엇을: 공통조건을 기존 명세로 복원 / 왜: 별도 계산기·승인 우회 금지 / 입력·출력: 템플릿 -> schema1 / 검증: 충돌·중복·경로·순서 검사. 파일읽기·코드실행 없음.
def expand_registration_template(template):
    if not isinstance(template,dict) or set(template)!={'schema','metadata','case_order','papers'} or template['schema']!='NAIS_REGISTRATION_TEMPLATE_1': raise ValueError('잘못된 템플릿 스키마')
    metadata=template['metadata']
    if not isinstance(metadata,dict) or {'schema','cases'}&set(metadata): raise ValueError('잘못된 등록 메타데이터')
    encoded=json.dumps(template,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(encoded)>2*1024*1024: raise ValueError('등록 템플릿은 2MB 이하만 지원합니다.')
    order=template['case_order'];papers=template['papers']
    if not isinstance(order,list) or not order or any(not isinstance(x,str) for x in order) or len(set(order))!=len(order): raise ValueError('잘못된 Claim 순서')
    if not isinstance(papers,list) or not 1<=len(papers)<=1000: raise ValueError('잘못된 논문 목록')
    cases=[]
    for paper in papers:
        if not isinstance(paper,dict) or set(paper)!={'shared','claims'} or not isinstance(paper['shared'],dict) or not isinstance(paper['claims'],list) or not paper['claims']: raise ValueError('공통조건과 주장 목록이 필요합니다.')
        shared=paper['shared']
        if 'claim_id' in shared: raise ValueError('Claim ID는 공유할 수 없습니다.')
        for claim in paper['claims']:
            if not isinstance(claim,dict) or set(shared)&set(claim): raise ValueError('공통조건과 개별조건 충돌')
            cases.append({**shared,**claim})
            if len(cases)>1000: raise ValueError('1000개 사례 한도 초과')
    cases=_template_cases(cases)
    indexed={c['claim_id']:c for c in cases}
    if set(order)!=set(indexed): raise ValueError('Claim 순서 목록 누락 또는 추가')
    return {**metadata,'schema':1,'cases':[indexed[cid] for cid in order]}


# [작성: 전문가4·7] 2026-09-25 case60
# 무엇을: 등록 파일의 경로·해시 검증 / 왜: 다른 파일·프로젝트 밖 입력으로 승인 대체 방지 / 입력·출력: 상대 경로·해시 -> bytes / 검증: test_case60_registry 무결성·경로 차단.
def _verified_bytes(relative_path, expected_hash, root=None):
    root = Path(ROOT if root is None else root).resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("프로젝트 밖 파일 경로")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("등록 파일 해시 불일치")
    return raw


# [작성: 전문가4·7] 2026-09-25 case60
# 무엇을: 선언형 사례 검증·기존 두 계산 경로 교차 대조 / 왜: 새 논문마다 전용 실행기를 쓰지 않고 범위 한계를 유지 / 입력·출력: JSON -> 산술 일치 또는 차단 / 검증: 임의 ID 평균3·누락근거·미확정·미지원·변조 시험.
# [작성: 전문가4·7] 2026-09-26 case63: 중복 JSON·스키마·ID는 실행 전 거부, 사례 오류는 개별 차단.
def load_registry(manifest):
    raw = Path(manifest).read_bytes()
    entries = _load_json(raw)
    if not isinstance(entries, dict) or type(entries.get("schema")) is not int or entries['schema'] != 1:
        raise ValueError("미지원 등록 스키마")
    cases = entries.get('cases')
    if not isinstance(cases, list):
        raise ValueError("cases 배열이 필요합니다.")
    if any(not isinstance(c, dict) or not isinstance(c.get('claim_id'), str) or not c['claim_id'].strip() for c in cases):
        raise ValueError("사례 객체와 비어 있지 않은 Claim ID가 필요합니다.")
    ids = [case['claim_id'] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("중복 Claim ID")
    return raw, cases


# [작성: 전문가4·7] 2026-09-26 case63: 유효 등록의 최소 필드·정책 검사; 알 수 없는 방법은 기존 BLOCK 유지.
# [수정: 등록준비 담당] 2026-09-29 case89
# 종류: 효율화 / 변경 전: 필수문자열 필드 지역정의 / 변경 후: 준비도와 REQUIRED_STRINGS 공유 / 왜: 진단과 실행 계약 불일치 방지 / 영향: 기존 필드·결과 불변, registry 회귀 확인.
def _validate_case(case):
    # [수정: 전문가4·7] 2026-09-26 case63: 영향추적과 같은 의존성/상대경로 규칙 사용.
    if _unknown_dependencies(case):
        raise ValueError('미지원 추가 입력 의존성')
    if any(not _relative(case.get(field)) for field in ('source_file', 'data_file')):
        raise ValueError('유효한 프로젝트 상대경로가 필요합니다.')
    for field in REQUIRED_STRINGS:
        if not isinstance(case.get(field), str) or not case[field].strip():
            raise ValueError('필수 문자열 필드: ' + field)
    for field in ('source_sha256', 'data_sha256'):
        if len(case[field]) != 64 or any(c not in '0123456789abcdef' for c in case[field]):
            raise ValueError('잘못된 SHA256: ' + field)
    _finite(case['reported_value'])
    if _finite(case['tolerance']) < 0:
        raise ValueError('음수 허용오차')
    filters = case.get('filters')
    if not isinstance(filters, dict) or any(not isinstance(k, str) or not isinstance(v, (str, int, float, bool)) for k,v in filters.items()):
        raise ValueError('필터 사전이 필요합니다.')
    for value in filters.values():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _finite(value)
    delimiter = case.get('delimiter', ',')
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n"':
        raise ValueError('잘못된 CSV 구분자')
    if case.get('missing_policy', 'drop') not in ('drop', 'error'):
        raise ValueError('미지원 결측 정책')
    if case['method'] == 'mean' and (not isinstance(case.get('column'), str) or not case['column'].strip()):
        raise ValueError('평균 대상 열이 필요합니다.')


# [작성: 등록준비·보안 담당] 2026-09-29 case89
# 무엇·왜: 첫 오류 대신 주장별 수정필드 표시 / 입출력: 엄격 JSON bytes·명시 root→읽기 전용 보고 / 검증: test_case89_registration; 실행·경로추정·해시수정·승인 없음.
def registration_readiness(raw, *, root):
    if len(raw) > 2*1024*1024: raise ValueError('등록 명세는 2MB 이하만 지원합니다.')
    entries = _load_json(raw)
    if isinstance(entries, dict) and entries.get('schema') == 'NAIS_REGISTRATION_TEMPLATE_1':
        entries = expand_registration_template(entries)
    if not isinstance(entries, dict) or type(entries.get('schema')) is not int or entries['schema'] != 1:
        raise ValueError('미지원 등록 스키마')
    cases = entries.get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 1000: raise ValueError('1~1000개 사례가 필요합니다.')
    if any(not isinstance(c, dict) or not isinstance(c.get('claim_id'), str) or not c['claim_id'].strip() for c in cases):
        raise ValueError('사례 객체와 비어 있지 않은 Claim ID가 필요합니다.')
    if len({c['claim_id'] for c in cases}) != len(cases): raise ValueError('중복 Claim ID')
    root = Path(root).resolve()
    if not root.is_dir(): raise ValueError('명시한 root 디렉터리가 없습니다.')
    results = []
    for case in cases:
        issues = []
        # [작성: 등록준비·보안 담당] 2026-09-29 case89: 중복 안내 없이 필드별 수동수정 위치 보존.
        def issue(field, reason, action):
            if not any(x['field'] == field for x in issues):
                issues.append({'field': field, 'reason': reason, 'repair_action': action})
        row = {'claim_id': case['claim_id'], 'action': 'BLOCK', 'issues': issues,
               'source_quote_found': False, 'source_scope_verified': False, 'human_approval': False}
        checked = {k:v for k,v in case.items() if k != 'preprocessing_contract'}
        if _unknown_dependencies(checked):
            for key in checked:
                if _unknown_dependencies({key: checked[key]}):
                    issue(key, '미지원 추가 입력 의존성', '지원된 명세로 직접 재등록; 추가 파일·코드를 실행하지 마세요.')
            results.append(row)
            continue
        for field in REQUIRED_STRINGS:
            if not isinstance(case.get(field), str) or not case[field].strip():
                issue(field, '필수 문자열 누락', '원문·자료 기록에서 이 필드를 직접 확인하여 입력하세요.')
        for field in ('reported_value', 'tolerance', 'filters'):
            if field not in case: issue(field, '필수 필드 누락', '보고값·허용오차·필터를 원문 조건대로 명시하세요.')
        for field in ('reported_value', 'tolerance'):
            try:
                value = _finite(case.get(field))
                if field == 'tolerance' and value < 0: raise ValueError('음수 허용오차')
            except (ValueError, TypeError, OverflowError) as error:
                issue(field, str(error), '유한 숫자를 명시하세요; tolerance는 0 이상이어야 합니다.')
        try:
            _validate_case(checked)
        except (ValueError, KeyError, TypeError, OverflowError) as error:
            message = str(error)
            field = next((f for f in (*REQUIRED_STRINGS, 'reported_value', 'tolerance', 'filters') if f in message),
                         'filters' if '필터' in message else 'column' if '대상 열' in message else
                         'delimiter' if '구분자' in message else 'missing_policy' if '결측 정책' in message else 'case')
            if field != 'case' or not issues:
                issue(field, message, '기존 등록 스키마의 타입·경로·정책을 수정하세요; 기본값으로 채우지 않습니다.')
        blobs = {}
        for kind in ('source', 'data'):
            path, digest = case.get(kind+'_file'), case.get(kind+'_sha256')
            if not _relative(path):
                issue(kind+'_file', '유효한 프로젝트 상대경로 필요', '선택한 프로젝트 root 안의 실제 상대경로를 직접 입력하세요.')
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                issue(kind+'_sha256', 'SHA256 누락 또는 형식 오류', '의도한 원본을 확인하고 SHA256을 직접 기록하세요; 자동 재작성하지 않습니다.')
                continue
            if not _relative(path): continue
            try:
                blobs[kind] = _verified_bytes(path, digest, root)
            except ValueError as error:
                issue(kind+'_sha256' if '해시' in str(error) else kind+'_file', str(error),
                      '선택한 root·원본 경로·등록 지문을 확인하세요; 다른 파일 탐색이나 해시 갱신은 하지 않습니다.')
            except (OSError, RuntimeError):
                issue(kind+'_file', '선택한 root에서 파일을 읽을 수 없음', '프로젝트 root와 상대경로를 직접 확인하세요; 업로드 위치를 root로 추정하지 않습니다.')
        if 'source' in blobs:
            try: row['source_quote_found'] = bool(case.get('source_quote')) and case['source_quote'] in blobs['source'].decode('utf-8-sig')
            except (UnicodeError, TypeError): pass
            if not row['source_quote_found']: issue('source_quote', '등록 원문에서 인용 미발견', '원문 인용·인코딩·위치를 직접 대조하세요; 인용 발견도 의미 승인이 아닙니다.')
        if 'preprocessing_contract' in case:
            try:
                if 'data' not in blobs: raise ValueError('파생자료 결속 먼저 확인 필요')
                _verify_preprocessing(case['preprocessing_contract'], blobs['data'], root)
            except (ValueError, KeyError, TypeError, OSError, UnicodeError, OverflowError, RuntimeError) as error:
                issue('preprocessing_contract', str(error), '지원된 전처리 계약의 raw·author_code·경로·지문·투영을 직접 확인하세요; 코드는 실행하지 않습니다.')
        for field, valid, action in (
            ('source_kind', case.get('source_kind') == 'article_extract', '출판 원문을 별도 확보·대조하세요; 코드·큐레이터 자료를 원문으로 승격하지 않습니다.'),
            ('scope_status', case.get('scope_status') == 'EVALUATION_MAPPING', '모집단·조건을 직접 확인하여 개발자 매핑 범위를 기록하세요; 사람 승인 아님.'),
            ('method', case.get('method') in ('count_rows', 'missing_cells', 'mean'), '지원 방법은 count_rows·missing_cells·mean입니다; 다른 방법은 별도 구현·검증이 필요합니다.')):
            if not valid: issue(field, '등록 검산 조건 미충족', action)
        if not issues: row['action'] = 'REGISTRATION_READY'
        elif case.get('source_kind') == 'package_source_doc' and [x['field'] for x in issues] == ['source_kind']:
            row['action'] = 'DATASET_ONLY'
        results.append(row)
    return {'schema': 1, 'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'results': results,
            'executed': False, 'human_approval': False,
            'scope': '등록 준비도만 검사; 산술·원문 의미·진위·논문 전체 재현 검증 아님. DATASET_ONLY도 article gate는 차단.'}


# [작성:전문가4] 2026-09-27 case69 목적: 저자 명시 필터와 실제 투영행 결속; 입력: 엄격계약/파생CSV/root; 출력: 부분재계산범위; 검증: raw·code SHA, 경로, 숫자/결측, 순서/중복/투영 일치.
def _verify_preprocessing(contract, derived, root):
    keys={'kind','raw','author_code','column','excluded_value','missing_policy','projection','source_rows','selected_rows'}
    if not isinstance(contract,dict) or set(contract)!=keys or contract['kind']!='numeric_not_equal_projection':raise ValueError('미지원 전처리 계약')
    if contract['missing_policy']!='drop' or not isinstance(contract['column'],str) or not contract['column']:raise ValueError('잘못된 전처리 정책')
    projection=contract['projection']
    if not isinstance(projection,list) or not projection or any(not isinstance(v,str) or not v for v in projection) or len(set(projection))!=len(projection):raise ValueError('잘못된 투영 열')
    for key in ['source_rows','selected_rows']:
        if type(contract[key]) is not int or contract[key]<0:raise ValueError('잘못된 전처리 분모')
    threshold=_finite(contract['excluded_value']);blobs={}
    for key,expected in [('raw',{'path','sha256'}),('author_code',{'path','sha256','quote','executed'})]:
        ref=contract[key]
        if not isinstance(ref,dict) or set(ref)!=expected or not _relative(ref.get('path')):raise ValueError('잘못된 전처리 근거 경로')
        digest=ref.get('sha256')
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('잘못된 전처리 SHA')
        blobs[key]=_verified_bytes(ref['path'],digest,root)
    author=contract['author_code']
    expected_quote=f"filter({contract['column']} != {threshold:g})"
    if not contract['column'].isidentifier() or author['quote']!=expected_quote:raise ValueError('코드 인용과 명시 필터 불일치')
    if author['executed'] is not False or not isinstance(author['quote'],str) or not author['quote'] or author['quote'] not in blobs['author_code'].decode('utf-8-sig'):raise ValueError('저자 코드 인용 불일치 또는 실행 주장')
    # [수정: 전처리 추적 담당] 2026-09-28 case83 / 무엇·왜: shared CSV파싱 오류 정규화로 두진입 UI크래시 방지 / 입출력: raw·derived bytes→행목록 또는 ValueError / 검증: 실제큰셀 SHA audit·snapshot 4건 차단, 전역CSV한도 불변.
    try:
        reader=csv.DictReader(io.StringIO(blobs['raw'].decode('utf-8-sig')))
        raw_rows=list(reader)
        parsed=csv.DictReader(io.StringIO(derived.decode('utf-8-sig')))
        derived_rows=list(parsed)
    except csv.Error as error:
        raise ValueError('잘못된 전처리 CSV') from error
    if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames) or any(c not in reader.fieldnames for c in projection+[contract['column']]):raise ValueError('원자료 열 불일치')
    selected=[];missing=0
    for row in raw_rows:
        if None in row or any(value is None for value in row.values()):raise ValueError('불완전 CSV 행')
        value=row[contract['column']].strip()
        if value in {'','NA'}:missing+=1;continue
        if _finite(value)!=threshold:selected.append({key:row[key] for key in projection})
    if parsed.fieldnames!=projection or derived_rows!=selected:raise ValueError('파생 CSV가 명시 전처리 투영과 다름')
    if len(raw_rows)!=contract['source_rows'] or len(selected)!=contract['selected_rows']:raise ValueError('전처리 분모 불일치')
    return {'preprocessing_verified':True,'raw_data_rows':len(raw_rows),'analysis_rows':len(selected),'preprocessing_missing_rows':missing,'author_code_executed':False,'reproduction_scope':'DECLARED_PARTIAL_ARITHMETIC_REIMPLEMENTATION'}


# [수정: 전문가4·7] 2026-09-26 case63: 명시 root·실제 선택행/관측 분모 대조로 같은 평균의 다른 모집단 차단.
# [수정:전문가4] 2026-09-27 case69 종류: 전처리계약 검증 추가 / 재현: 파생행 변조·추가의존성 / 전후: 근거 없는 투영→raw/code/SHA/행순서 검증 / 왜: 부분산술 범위 결속 / 영향: 확장명세만, 기본4건 불변.
def audit_registry(manifest=ROOT / "data/evaluation/registered_cases.json", root=None):
    root = Path(ROOT if root is None else root).resolve()
    if not root.is_dir():
        raise ValueError('root 디렉터리가 없습니다.')
    raw_manifest, cases = load_registry(manifest)
    results = []
    for case in cases:
        result = {"claim_id": case["claim_id"], "action": "BLOCK",
                  "source_scope_verified": False, "full_paper_reproduced": False}
        try:
            # 전처리를 먼저 엄격 검증한 경우에만 그 키 하나를 기존 unknown 검사에서 제외한다.
            checked_case=case
            if 'preprocessing_contract' in case:
                derived=_verified_bytes(case['data_file'],case['data_sha256'],root)
                result.update(_verify_preprocessing(case['preprocessing_contract'],derived,root))
                checked_case={key:value for key,value in case.items() if key!='preprocessing_contract'}
            _validate_case(checked_case)
            if not case.get("paper_url") or not case.get("source_location"):
                raise ValueError("논문 출처·근거 위치 없음")
            source = _verified_bytes(case["source_file"], case["source_sha256"], root)
            if not case.get("source_quote") or case["source_quote"] not in source.decode("utf-8-sig"):
                raise ValueError("근거 인용이 등록 원문에 없음")
            _verified_bytes(case["data_file"], case["data_sha256"], root)
            if case.get("source_kind") != "article_extract":
                raise ValueError("출판 원문이 아닌 코드·큐레이터 기록: 원문 대조 필요")
            if case.get("scope_status") != "EVALUATION_MAPPING":
                raise ValueError("모집단·조건 확인 대기: " + case.get("scope_note", "범위 미확정"))
            if case["method"] not in {"count_rows", "missing_cells", "mean"}:
                raise ValueError("범용 등록 실행에서 미지원 분석방법")
            # Existing evaluation mapping entry point; never synthesize a human signature.
            mapped = dict(case, oracle_mapping_supplied=True)
            with TemporaryDirectory() as directory:
                selected = Path(directory) / "case.json"
                selected.write_text(json.dumps({"cases": [mapped]}, ensure_ascii=False), encoding="utf-8")
                engine = run_system(selected, root=root)["results"][0]
                independent = replay_cases(selected, root=root)["results"][0]
            if engine["action"] != "EXECUTE" or independent["action"] != "EXECUTE":
                raise ValueError(engine.get("reason") or independent.get("reason") or "엔진 실행 차단")
            if any(engine[k] != independent[k] for k in ("rows_used", "observations_used")):
                raise ValueError("제품·독립 재계산 분모 불일치")
            values = [_finite(engine["value"]), _finite(independent["value"]), _finite(case["reported_value"])]
            tolerance = float(case["tolerance"])
            if not all(map(math.isfinite, values)) or not math.isfinite(tolerance) or tolerance < 0:
                raise ValueError("비유한 값 또는 잘못된 허용오차")
            agreed = math.isclose(values[0], values[1], rel_tol=1e-12, abs_tol=1e-12)
            if not agreed:
                raise ValueError("제품·독립 재계산 불일치")
            result.update(action="ARITHMETIC_MATCH" if abs(values[0] - values[2]) <= tolerance else "ARITHMETIC_MISMATCH",
                          value=values[0], independent_value=values[1], reported_value=values[2],
                          rows_used=engine["rows_used"], observations_used=engine["observations_used"],
                          confirmation_source="evaluation_mapping_not_human",
                          reason="산술 대조만 완료; 원문과 모집단의 의미 연결은 사람 확인 필요")
        except (KeyError, ValueError, TypeError, OSError, UnicodeError, OverflowError) as error:
            result["reason"] = str(error)
        results.append(result)
    return {"schema": 1, "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
            "registration_bytes": len(raw_manifest), "registration_lines": len(raw_manifest.splitlines()), "results": results,
            "scope": "개발자 등록 시험; 사람 정답·범용 AI 우위·논문 전체 재현 아님"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/evaluation/registered_cases.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument('--expand-template',type=Path,help='공통조건 템플릿을 표준 명세로 복원만 합니다. 실행하지 않습니다.')
    args = parser.parse_args()
    # [수정: 확장설계 담당] 2026-09-28 case87 / 종류: 효율화 / 재현: 템플릿 수동복사 / 전후: 중복입력→검증복원 / 왜: 도구밖 재사용 / 영향: expand 경로는 검산도 실행하지 않음.
    if args.expand_template:
        raw=args.expand_template.read_bytes()
        if len(raw)>2*1024*1024: raise ValueError('등록 템플릿은 2MB 이하만 지원합니다.')
        result=expand_registration_template(_load_json(raw))
    else:
        result=audit_registry(args.manifest,root=args.root)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
        print(output)
