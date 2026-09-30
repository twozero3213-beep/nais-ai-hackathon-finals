"""Third-party replay using only Python's standard library and bundled CSVs."""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import statistics
import io
import math
import zipfile

ROOT=Path(__file__).resolve().parents[1]


# [작성: 전문가4/8] 2026-09-26 case62: 자체일관성과 산술검사 범위를 인증과 구별.
LIMITATIONS = ('ZIP 내부 해시는 자체일관성·산술검사이며 원장 또는 서명 인증이 아닙니다. '
               '모든 파일과 해시의 동시 재작성은 탐지하지 못하며 원문 진위·범위는 검증하지 않습니다.')
MAX_PACKET_BYTES = 64 * 1024 * 1024


# [작성: 전문가4/8] 2026-09-26 case62: JSON NaN·중복 키를 거부하여 모호한 명세 차단.
def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('중복 JSON 키')
        result[key] = value
    return result


# [작성: 전문가4/8] 2026-09-26 case62: 유한 실제 수치만 기대값과 관측값으로 사용.
def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('유효한 수치가 필요합니다.')
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError('유효한 수치가 필요합니다.') from exc
    if not math.isfinite(number):
        raise ValueError('비유한 수치')
    return number


# [작성: 전문가4/8] 2026-09-26 case62: 명세를 독립 해석해 행수·결측·평균을 손계산 가능한 정책으로 재계산.
def _calculate(data, spec):
    keys = {'method', 'column', 'filters', 'missing_policy', 'delimiter', 'filter_policy', 'missing_values'}
    if not isinstance(spec, dict) or set(spec) != keys:
        raise ValueError('분석 명세 필드 불일치')
    method, column, filters = spec['method'], spec['column'], spec['filters']
    if method not in ('row_count', 'missing_cells', 'mean'):
        raise ValueError('독립 재실행 미지원 방법')
    if spec['missing_policy'] not in ('drop', 'error'):
        raise ValueError('미지원 결측 정책')
    if spec['filter_policy'] != 'exact_string_and' or spec['missing_values'] != ['']:
        raise ValueError('미지원 필터·결측 해석')
    delimiter = spec['delimiter']
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n"':
        raise ValueError('잘못된 CSV 구분자')
    if not isinstance(filters, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k,v in filters.items()):
        raise ValueError('필터는 열명과 정확한 문자열 값의 사전이어야 합니다.')
    if method != 'mean' and column not in (None, '__dataset__'):
        raise ValueError('행·결측 수는 전체 열 범위만 지원합니다.')
    try:
        reader = csv.reader(io.StringIO(data.decode('utf-8-sig'), newline=''), delimiter=delimiter, strict=True)
        header = next(reader, [])
        if not header or any(not h for h in header) or len(set(header)) != len(header):
            raise ValueError('CSV 헤더가 없거나 중복됩니다.')
        rows = []
        for cells in reader:
            if not cells:  # CSV의 완전한 빈 줄은 관측행이 아님.
                continue
            if len(cells) != len(header):
                raise ValueError('CSV 행의 열 수 불일치')
            rows.append(dict(zip(header, cells)))
    except (UnicodeError, csv.Error) as exc:
        raise ValueError('UTF-8 CSV 해석 실패') from exc
    if set(filters) - set(header):
        raise ValueError('필터 열 없음: ' + ', '.join(sorted(set(filters) - set(header))))
    if method == 'mean' and (not isinstance(column, str) or column not in header):
        raise ValueError('평균의 대상 열 없음')
    selected = [r for r in rows if all(r[k] == v for k,v in filters.items())]
    observations = len(selected)
    if method == 'row_count':
        value = len(selected)
    elif method == 'missing_cells':
        value = sum(v == '' for row in selected for v in row.values())
    else:
        cells = [r[column] for r in selected]
        if spec['missing_policy'] == 'error' and '' in cells:
            raise ValueError('평균 대상에 결측 관측값이 있습니다.')
        numbers = [_finite(v) for v in cells if v != '']
        if not numbers:
            raise ValueError('수치 관측값 없음')
        try:
            value = statistics.fmean(numbers)
        except OverflowError as exc:
            raise ValueError('평균 산술 범위 초과') from exc
        _finite(value)
        observations = len(numbers)
    return value, len(selected), observations


# [수정: 전문가4/8] 2026-09-26 case62: 기존 9개 인자 유지, keyword 명세와 기대결과 바이트를 추가 결속.
def make_packet(source_name,source_bytes,csv_name,csv_bytes,claim_id,method,reported_value,executed_value,source_location,
                *, column=None, filters=None, missing_policy='drop', delimiter=','):
    spec = {'method':method, 'column':column, 'filters':{} if filters is None else filters,
            'missing_policy':missing_policy, 'delimiter':delimiter,
            'filter_policy':'exact_string_and', 'missing_values':['']}
    _calculate(csv_bytes, spec)
    _finite(executed_value)
    if reported_value is not None:
        _finite(reported_value)
    expected = {'claim_id':claim_id, 'executed_value':executed_value,
                'reported_value':reported_value, 'source_location':source_location}
    files = {'source_input':source_bytes, 'raw_data.csv':csv_bytes,
             'specification.json':json.dumps(spec, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8'),
             'expected_result.json':json.dumps(expected, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')}
    if sum(len(v) for v in files.values()) > MAX_PACKET_BYTES:
        raise ValueError('재실행 묶음 크기 제한 초과')
    metadata = {'schema':2, 'source_name':Path(source_name).name, 'csv_name':Path(csv_name).name,
                'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(metadata, ensure_ascii=False, indent=2))
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('README.md', 'Run: python -m tools.independent_replay --packet PATH\n'
                         'Requires this trusted replay tool, Python standard library only.\n'
                         'Methods: row_count, missing_cells, mean. Filters: exact string equality AND.\n'
                         'Missing: empty CSV cells only; mean drop/error; count methods retain cells.\n'
                         'UTF-8 CSV, explicit delimiter, finite numeric observations only.\n' + LIMITATIONS + '\n')
    return output.getvalue()


# [작성: 전문가4/8] 2026-09-26 case62: 명세 JSON의 중복키·비유한 상수 거부.
def _load_json(data):
    def reject_constant(value):
        # [작성: 전문가4/8] 2026-09-26 case62: 비표준 JSON 상수 차단.
        raise ValueError('비유한 JSON 상수: ' + value)
    try:
        return json.loads(data, object_pairs_hook=_json_object, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('JSON 해석 실패') from exc


# [수정: 전문가4/8] 2026-09-26 case62: ZIP은 추출 없이 허용 목록·중복·크기·해시 검사 후 독립 재계산.
def replay_packet(packet):
    try:
        with zipfile.ZipFile(io.BytesIO(packet) if isinstance(packet, bytes) else packet) as archive:
            names = archive.namelist()
            allowed = {'manifest.json', 'source_input', 'raw_data.csv', 'README.md',
                       'specification.json', 'expected_result.json'}
            if len(names) != len(set(names)) or set(names) - allowed:
                raise ValueError('허용되지 않은 ZIP 경로 또는 중복 엔트리')
            if sum(item.file_size for item in archive.infolist()) > MAX_PACKET_BYTES:
                raise ValueError('재실행 묶음 크기 제한 초과')
            if 'manifest.json' not in names:
                raise ValueError('ZIP 명세 누락')
            meta = _load_json(archive.read('manifest.json'))
            if not isinstance(meta, dict) or type(meta.get('schema')) is not int or meta['schema'] not in (1,2):
                raise ValueError('미지원 묶음 스키마')
            required = {'manifest.json','source_input','raw_data.csv','README.md'}
            if meta['schema'] == 2:
                required |= {'specification.json','expected_result.json'}
            if set(names) != required:
                raise ValueError('ZIP 필수 파일 누락 또는 스키마 파일 불일치')
            files = {name:archive.read(name) for name in names}
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError('유효하지 않은 ZIP 묶음') from exc
    if meta['schema'] == 2:
        bound = {'source_input','raw_data.csv','specification.json','expected_result.json'}
        hashes = meta.get('files')
        if not isinstance(hashes, dict) or set(hashes) != bound:
            raise ValueError('결속 파일 해시 누락')
        spec = _load_json(files['specification.json'])
        expected = _load_json(files['expected_result.json'])
    else:
        hashes = {'source_input':meta.get('source_sha256'), 'raw_data.csv':meta.get('csv_sha256')}
        if meta.get('method') not in ('row_count','missing_cells'):
            raise ValueError('레거시 독립 재실행 미지원 방법')
        spec = {'method':meta['method'], 'column':None, 'filters':{}, 'missing_policy':'drop',
                'delimiter':',', 'filter_policy':'exact_string_and', 'missing_values':['']}
        expected = {k:meta.get(k) for k in ('claim_id','executed_value','reported_value','source_location')}
    for name, digest in hashes.items():
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise ValueError('입력 해시 불일치: ' + name)
    if not isinstance(expected, dict) or set(expected) != {'claim_id','executed_value','reported_value','source_location'}:
        raise ValueError('기대 결과 필드 누락 또는 불일치')
    executed = _finite(expected['executed_value'])
    if expected['reported_value'] is not None:
        _finite(expected['reported_value'])
    value, rows, observations = _calculate(files['raw_data.csv'], spec)
    matched = abs(value - executed) <= 1e-9
    return {**expected, 'action':'ARITHMETIC_MATCH' if matched else 'MISMATCH',
            'source_scope_verified':False, 'authenticity_verified':False,
            'independent_value':value, 'rows_used':rows, 'observations_used':observations,
            'specification':spec, 'packet_schema':meta['schema'],
            'binding_scope':'source_csv_specification_expected' if meta['schema']==2 else 'legacy_source_csv_only',
            'limitations':LIMITATIONS}


# [수정: 전문가4/8] 2026-09-26 case62: legacy 사례도 ZIP과 같은 CSV/산술 검증을 공유.
# 중복 헤더·짧거나 긴 행·평균 overflow를 구조화 BLOCK으로 반환; 정상 공개 수치/해시 오류 동작 유지.
def replay_cases(manifest=ROOT/'data/evaluation/cases.json', root=None):
    # [수정: 전문가4·7] 2026-09-26 case63: 복사 프로젝트의 명시 root와 기존 ROOT monkeypatch 모두 지원.
    root = Path(ROOT if root is None else root).resolve()
    if not root.is_dir():
        raise ValueError('root 디렉터리가 없습니다.')
    path = Path(manifest)
    cases = _load_json(path.read_bytes())['cases']
    results = []
    for case in cases:
        source = (root/case['data_file']).resolve()
        if not source.is_relative_to(root):
            raise ValueError('원자료 경로가 프로젝트 밖입니다.')
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != case['data_sha256']:
            raise ValueError(f"원자료 해시 불일치: {case['claim_id']}")
        base = {'claim_id':case['claim_id'], 'source_hash':digest}
        method = case['method']
        if method not in {'count_rows','mean','missing_cells'}:
            results.append({**base, 'action':'BLOCK', 'reason':'독립 재실행 미지원 분석방법'})
            continue
        try:
            filters = case.get('filters', {})
            if not isinstance(filters, dict) or any(not isinstance(v, (str, int, float, bool)) for v in filters.values()):
                raise ValueError('필터는 열명과 단일 값의 사전이어야 합니다.')
            # [수정: 전문가4/8] 2026-09-26 case62: legacy의 str(value) 필터 해석은 보존.
            spec = {'method':'row_count' if method == 'count_rows' else method,
                    'column':case.get('column') if method == 'mean' else None,
                    'filters':{k:str(v) for k,v in filters.items()},
                    'missing_policy':case.get('missing_policy', 'drop'),
                    'delimiter':case.get('delimiter', ','),
                    'filter_policy':'exact_string_and', 'missing_values':['']}
            value, rows, observations = _calculate(data, spec)
        except ValueError as exc:
            results.append({**base, 'action':'BLOCK', 'reason':str(exc)})
            continue
        results.append({**base, 'action':'EXECUTE', 'value':value, 'rows_used':rows, 'observations_used':observations})
    return {'schema':1, 'results':results}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output');parser.add_argument('--packet');args=parser.parse_args()
    text=json.dumps(replay_packet(args.packet) if args.packet else replay_cases(),ensure_ascii=False,indent=2)+'\n'
    if args.output:Path(args.output).write_text(text,encoding='utf-8')
    else:
        # [수정: 전문가4/8] 2026-09-26 case62: Windows 파이프에서도 JSON CLI 출력 UTF-8 고정.
        import sys
        sys.stdout.reconfigure(encoding='utf-8')
        print(text)
