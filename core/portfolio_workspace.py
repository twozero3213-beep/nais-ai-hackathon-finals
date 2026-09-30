"""case63 fixed-registry review workspace; snapshots cannot select local inputs."""
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import streamlit as st

from core.paths import PROJECT_ROOT
from tools.case_registry import audit_registry, pack_registration_template, expand_registration_template, registration_readiness
from tools.change_impact import snapshot_registry, compare_snapshots
from tools.independent_replay import _load_json, replay_packet
from tools.registry_benchmark import benchmark_provenance, _fingerprint

MANIFEST = PROJECT_ROOT / 'data/evaluation/scalability_cases.json'
MEASUREMENT = PROJECT_ROOT / 'docs/scalability_measurement.json'
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
COMPARISON_MANIFEST_SHA256 = '078b771c1a99f228e280cdfb53fa16e930997d4c1563b2a5ededf10b325b38b9'
AUTHOR_MODEL_MANIFESTS = tuple(f'data/evaluation/n3_11814/rep{i}_models.json' for i in range(1, 5))
LABELS = {'ADDED': '추가', 'REMOVED': '삭제', 'UNCHANGED': '입력 동일',
          'REEXECUTION_REQUIRED': '재실행 필요', 'BLOCKED_INPUT': '입력 확인 필요'}
NEXT_ACTION = {'ADDED': '새 주장 검산과 범위 확인', 'REMOVED': '삭제 사유와 참조 확인',
               'UNCHANGED': '변경 없음은 현재 유효성 인증이나 사람 승인이 아님',
               'REEXECUTION_REQUIRED': '변경된 근거·자료·명세로 다시 검산',
               'BLOCKED_INPUT': '자료 경로·해시·의존성 확인 후 다시 실행'}


# [작성: 재현성 제품·실행증빙 담당] 2026-09-28 case88
# 무엇을: 보관 AI제안→합성누락차단→기존등록복원→두검산→변경영향 / 왜: 선언과 실제 실행 연결 / 입력·출력: 고정 보관·등록→지문 연결 보고 / 검증: test_case88_workflow; AI호출·승인 없음.
def claim_workflow_review():
    from copy import deepcopy
    from tools.case_registry import _verified_bytes
    from tools.compare_exploratory import compare
    from tools.change_impact import snapshot_registry_with_preprocessing

    manifest = PROJECT_ROOT/'data/evaluation/public_reproduction_cases.json'
    folder = PROJECT_ROOT/'data/evaluation/comparison'
    provenance = benchmark_provenance()
    original = snapshot_registry_with_preprocessing(manifest, root=PROJECT_ROOT)
    comparison = compare(folder/'manifest.json', folder/'case85_observations.json', COMPARISON_MANIFEST_SHA256)
    archived = next(r for r in comparison['cases'] if r['claim_id'] == 'RAW-ROWS')
    registered = {r['claim_id']: r['metadata'] for r in original['claims']}
    primary = registered['PENG-RAW-ROWS']
    control = registered['BAT-POSITIVE-N']
    if (primary['data_sha256'] != archived['input_hashes']['csv_sha256']
            or primary['method'] != 'count_rows' or primary['filters'] != {}
            or primary['source_quote'] not in (folder/'paper_excerpt.txt').read_text(encoding='utf-8-sig')):
        raise ValueError('보관 제안과 기존 등록의 자료·조건·원문 연결이 변경되었습니다.')
    proposal = {'origin': 'ARCHIVED_MODEL_OUTPUT', 'claim_id': 'RAW-ROWS',
        'prediction': archived['model_prediction'], 'execution': archived['model_execution'],
        'raw_output': archived['model_raw_output'], 'raw_output_sha256': archived['model_raw_output_sha256'],
        'provenance': archived['model_provenance'], 'input_hashes': archived['input_hashes'],
        'protocol_sha256': comparison['manifest_sha256'], 'observations_sha256': comparison['observations_sha256'],
        'trial_prompt_sha256': comparison['trial_prompt_sha256'],
        'protocol_binding': comparison['protocol_binding']}
    mapping = {'origin': 'DEVELOPER_REGISTERED_MAPPING', 'metadata': primary,
        'note': '동일 CSV 지문과 인용 부분문자열로 개발자가 연결한 기존 등록. AI가 원문위치·해시·분모를 생성했다는 증거가 아니며 의미 정답 승인 없음.'}
    stages, changes = [], []
    # ponytail: 고정 주장 1개와 미영향 대조1개; 대규모 시연은 등록 ID 선택과 같은 검증기를 재사용.
    with TemporaryDirectory(prefix='nais-workflow-') as directory:
        root = Path(directory)
        originals = {}
        for case in (primary, control):
            for kind in ('source', 'data'):
                relative = case[kind+'_file']
                raw = _verified_bytes(relative, case[kind+'_sha256'], PROJECT_ROOT)
                target = root/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                originals[relative] = raw
        selected = root/'workflow.json'
        missing = deepcopy(primary)
        missing['source_location'] = ''
        previous = _fingerprint(proposal)
        for name, case, origin in [('MISSING_EVIDENCE', missing, 'SYNTHETIC_FAULT'),
                                    ('RESTORED_MAPPING', primary, 'DEVELOPER_REGISTERED_MAPPING'),
                                    ('RECHECKED', primary, 'EXISTING_TWO_ENGINE_EXECUTION')]:
            selected.write_bytes(_json_bytes({'schema': 1, 'cases': [case, control]}))
            snapshot = snapshot_registry(selected, root=root)
            result = audit_registry(selected, root=root)['results'][0]
            stage = {'stage': name, 'origin': origin, 'metadata': case, 'result': result,
                'snapshot': snapshot, 'previous_sha256': previous,
                'verifier_provenance_sha256': _fingerprint(provenance),
                'repair': {'field': 'source_location', 'source_file': primary['source_file'],
                    'source_quote': primary['source_quote'], 'restore_from': 'existing registered mapping',
                    'next_action': '빈 원문위치를 기존 등록값으로 복원 후 재검산; 새로운 의미 승인을 만들지 않음'}}
            stage['stage_sha256'] = _fingerprint(stage)
            previous = stage['stage_sha256']
            stages.append(stage)
        baseline = stages[-1]['snapshot']
        data_path = root/primary['data_file']
        source_path = root/primary['source_file']
        for kind in ('data_bytes_without_hash_update', 'source_bytes_with_hash_update', 'filter'):
            data_path.write_bytes(originals[primary['data_file']])
            source_path.write_bytes(originals[primary['source_file']])
            changed = deepcopy(primary)
            if kind == 'data_bytes_without_hash_update':
                data_path.write_bytes(data_path.read_bytes()+b'\n')
            elif kind == 'source_bytes_with_hash_update':
                source_path.write_bytes(source_path.read_bytes()+b'\n<!-- NAIS synthetic change-impact test -->\n')
                changed['source_sha256'] = hashlib.sha256(source_path.read_bytes()).hexdigest()
            else:
                changed['filters'] = {'Species': 'Adelie Penguin (Pygoscelis adeliae)'}
            selected.write_bytes(_json_bytes({'schema': 1, 'cases': [changed, control]}))
            current = snapshot_registry(selected, root=root)
            result = audit_registry(selected, root=root)['results'][0]
            impact = compare_snapshots(baseline, current)
            changes.append({'kind': kind, 'origin': 'SYNTHETIC_CHANGE', 'metadata': changed,
                'snapshot': current, 'result': result, 'impact': impact, 'reuse_previous_result': False,
                'baseline_stage_sha256': stages[-1]['stage_sha256']})
        scenario = changes[0]
        stage = {'stage': 'INPUT_CHANGED', 'origin': 'SYNTHETIC_CHANGE',
            'metadata': scenario['metadata'], 'result': scenario['result'], 'snapshot': scenario['snapshot'],
            'impact': scenario['impact'], 'previous_sha256': previous,
            'verifier_provenance_sha256': _fingerprint(provenance),
            'reuse_previous_result': False}
        stage['stage_sha256'] = _fingerprint(stage)
        stages.append(stage)
    if (original != snapshot_registry_with_preprocessing(manifest, root=PROJECT_ROOT)
            or provenance != benchmark_provenance()
            or comparison != compare(folder/'manifest.json', folder/'case85_observations.json', COMPARISON_MANIFEST_SHA256)):
        raise ValueError('연속 검증 중 입력·보관 출력·코드·환경이 변경되었습니다. 다시 실행하세요.')
    return {'schema': 1, 'proposal': proposal, 'mapping': mapping, 'stages': stages,
        'change_scenarios': changes, 'input_snapshot_sha256': original['content_sha256'],
        'provenance': provenance, 'comparison_counts': comparison['counts'],
        'new_model_calls': 0, 'human_approval': False, 'new_source_pairs': 0,
        'scope': 'Archived AI suggestion, developer mapping and explicitly synthetic faults. No semantic gold, full-paper reproduction or superiority.',
        'limitations': '원출력은 2026-09-25 보관값이며 실행 로그 미확인. 합성 누락을 실제 AI 오류로 세지 않음. 명세 복원은 개발자 등록값 재사용. 지문은 자체결속이며 작성자 진실성 인증 아님.'}


# [작성: 연구자 UX 담당] 2026-09-28 case88
# 무엇을: 한 주장 연속검증 화면 / 왜: 차단 뒤 수정위치·재검산·변경영향 연결 / 입력·출력: 클릭→기존검증 보고·JSON / 검증: test_case88_workflow UI 재실행·다운로드.
def render_claim_workflow():
    st.subheader('한 주장 연속 시연 · 보관 AI 제안에서 변경 재검토까지')
    st.caption('보관 AI 제안 · 개발자 등록 매핑 · 합성 오류를 구분합니다. 실제 AI가 source_location을 누락했다는 주장이 아닙니다. 새 모델 호출 0회·사람 승인 없음.')
    if st.button('한 주장 제안·차단·수정·검산·변경 시연', key='claim_workflow_run'):
        st.session_state['claim_workflow_open'] = True
    if not st.checkbox('주장 연속 시연 열기', key='claim_workflow_open'):
        return
    try:
        report = claim_workflow_review()
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        st.error('보관 출력·등록 조건·파일·코드의 연결이 바뀌었습니다. 입력을 점검하고 다시 실행하세요.')
        return
    proposal = report['proposal']
    st.write('보관 AI 제안 RAW-ROWS: ' + json.dumps(proposal['prediction'], ensure_ascii=False))
    st.caption('보관 출력 SHA-256: '+proposal['raw_output_sha256']+' · 모델 실행 로그: '+proposal['execution']['execution_state'])
    st.dataframe(pd.DataFrame([{'단계': r['stage'], '작성 주체': r['origin'],
        '상태': r['result']['action'], '계산값': r['result'].get('value'),
        '독립값': r['result'].get('independent_value'), '차단·검산 이유': r['result']['reason'],
        '기록 SHA-256': r['stage_sha256']} for r in report['stages']]), hide_index=True)
    repair = report['stages'][0]['repair']
    st.info('합성 오류 복구: '+repair['field']+' · '+repair['next_action'])
    st.write({'원문 파일': repair['source_file'], '찾을 원문 인용': repair['source_quote'],
              '복원 위치': report['mapping']['metadata']['source_location']})
    with st.expander('원문·자료·필터 변경의 영향과 미영향 대조'):
        st.dataframe(pd.DataFrame([{'합성 변경': scenario['kind'], '주장': row['claim_id'],
            '상태': row['action'], '변경 입력': ', '.join(row['changed_inputs']),
            '이전결과 재사용': scenario['reuse_previous_result']}
            for scenario in report['change_scenarios'] for row in scenario['impact']['results']]), hide_index=True)
    st.warning(report['limitations'])
    st.download_button('주장 연속 추적 JSON 내려받기', _json_bytes(report),
                       file_name='claim_workflow_review.json', mime='application/json')


# [작성: 통합·검증 인프라 담당] 2026-09-28 case85
# 무엇을: 공개 사례와 보관 원출력의 기계 검증 / 왜: 사람 라벨 없이 가능한 범위 제공 / 입력·출력: 고정 등록 -> 현재 검산·과거 비교 / 검증: test_case85_integration.
# [수정: 전문가4·7·확장설계] 2026-09-28 case86
# 종류: 오류수정 / 재현 방법: 최종 검사 뒤 다른 메타데이터를 읽으면3쌍이1쌍으로오집계 / 변경 전: 파일 재읽기 / 변경 후: 검사한snapshot재사용·추적표/등록량 산출 / 왜: 결과와설명을같은입력에결속 / 영향: 산술·승인불변; test_case86.
def machine_evidence_review():
    from tools.change_impact import snapshot_registry_with_preprocessing
    from tools.compare_exploratory import compare
    manifest = PROJECT_ROOT/'data/evaluation/public_reproduction_cases.json'
    before = snapshot_registry_with_preprocessing(manifest, root=PROJECT_ROOT)
    provenance = benchmark_provenance()
    public = audit_registry(manifest, root=PROJECT_ROOT)
    folder = PROJECT_ROOT/'data/evaluation/comparison'
    comparison = compare(folder/'manifest.json', folder/'case85_observations.json', COMPARISON_MANIFEST_SHA256)
    after = snapshot_registry_with_preprocessing(manifest, root=PROJECT_ROOT)
    if before != after or provenance != benchmark_provenance():
        raise ValueError('검증 중 입력·코드·환경이 변경되었습니다. 다시 실행하세요.')
    cases = {c['claim_id']: c['metadata'] for c in before['claims']}
    metadata_hashes = {c['claim_id']: c['metadata_sha256'] for c in before['claims']}
    chain, inventory = [], {}
    for result in public['results']:
        cid = result['claim_id']
        case = cases[cid]
        chain.append({**{key: case.get(key) for key in (
            'claim_id', 'claim_text', 'paper_url', 'source_quote', 'source_location',
            'source_kind', 'source_file', 'source_sha256', 'data_file', 'data_sha256',
            'method', 'column', 'filters', 'missing_policy', 'reported_value', 'tolerance')},
            'metadata_sha256': metadata_hashes[cid],
            'preprocessing_kind': case.get('preprocessing_contract', {}).get('kind'),
            **{key: result.get(key) for key in ('action', 'value', 'independent_value', 'rows_used', 'observations_used', 'reason')},
            'human_approval': False})
        paper = case['paper_url']
        row = inventory.setdefault(paper, {'paper_url': paper, 'claims': 0, 'arithmetic_matches': 0,
            'blocked': 0, 'methods': set(), 'metadata_fields': 0, 'metadata_bytes': 0,
            'registration_seconds': None})
        row['claims'] += 1
        row['arithmetic_matches'] += result['action'] == 'ARITHMETIC_MATCH'
        row['blocked'] += result['action'] == 'BLOCK'
        row['methods'].add(case['method'])
        row['metadata_fields'] += len(case)
        row['metadata_bytes'] += len(json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'))
    inventory = [dict(inventory[key], methods=sorted(inventory[key]['methods'])) for key in sorted(inventory)]
    matched = [r for r in public['results'] if r['action'] == 'ARITHMETIC_MATCH']
    # [수정: 확장설계 담당] 2026-09-28 case87 / 종류: 효율화 / 재현: 논문별 반복설정 / 전후: 개별명세만→공통조건 템플릿·복원검사 / 왜: 입력부담 절약 / 영향: 산술·승인불변.
    standard={'schema':1,'cases':list(cases.values())}
    template=pack_registration_template(standard['cases'])
    if expand_registration_template(template)!=standard: raise ValueError('템플릿 복원 불일치')
    canonical=lambda obj:json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    template_metrics={'standard_bytes':len(canonical(standard)),'template_bytes':len(canonical(template)),
        'standard_fields':sum(len(c) for c in standard['cases']),
        'template_fields':sum(len(p['shared'])+sum(len(c) for c in p['claims']) for p in template['papers']),
        'roundtrip_identical':canonical(expand_registration_template(template))==canonical(standard),
        'registration_seconds':None,'new_reproductions':0}
    return {'schema': 1, 'human_approval': False, 'new_model_calls': 0,
            'registration_template':template,'template_metrics':template_metrics,
            'public': public, 'input_snapshot': before, 'provenance': provenance,
            'evidence_chain': chain, 'registration_inventory': inventory,
            'public_counts': {'pairs_with_arithmetic': len({cases[r['claim_id']]['paper_url'] for r in matched}),
                              'arithmetic_matches': len(matched),
                              'blocked': sum(r['action'] == 'BLOCK' for r in public['results']),
                              'claims': len(public['results'])},
            'comparison': comparison,
            'scope': 'Current registered arithmetic; archived model/product records rechecked, no human gold or superiority measurement.'}


# [작성: UX·통합 담당] 2026-09-28 case85
# 무엇을: 실제 검산과 한계 표시 / 왜: 평가 준비실의 사람 판정 필수 동선 해소 / 입력·출력: 클릭 -> 검증 결과·다운로드 / 검증: test_case85_integration 및 case61 회귀.
# [수정: 전문가1·2] 2026-09-28 case86
# 종류: 효율화 / 재현 방법: 요약표만으로원문/명세/등록범위 확인불가 / 변경 전: 결과숫자·이유 / 변경 후: 같은검산의근거·조건·등록량표 / 왜: 추적/재사용성가시화 / 영향: 새계산·AI호출없음; test_case86.
# [수정: 변경UX 담당] 2026-09-29 case91 / 종류: 변경재검토 동선 추가 / 재현: 검산 뒤 입력변경 확인동선 없음 / 변경전후: 고정대조만→별도 영향화면 연결 / 왜: 계획과 실제재실행 연결 / 영향: 기존 비교표·버튼 보존 / 검증: test_case91_change_ui 및 case90/case91 UI.
def render_machine_evaluation():
    from core.team_materials_ui import render_team_materials
    render_team_materials()
    render_registration_readiness()
    render_author_models()
    render_registered_model_comparison()
    render_reproduction_alignment()
    render_author_change_review()
    render_claim_workflow()
    st.subheader('사람 판정 없이 실행하는 근거 검산')
    st.caption('공개 논문·원자료의 등록된 산술을 두 계산 경로로 대조합니다. 원문 의미 승인·추출 정확도·논문 전체 재현을 자동 판정하지 않습니다.')
    if st.button('공개 사례·보관 원출력 검증', key='machine_evidence_run'):
        st.session_state['machine_evidence_open'] = True
    # ponytail: 7개 고정 사례는 매번 재검증; 대규모 등록은 입력·코드 지문 결속 캐시 도입.
    if not st.checkbox('자동 검산 결과 열기', key='machine_evidence_open'):
        return
    try:
        report = machine_evidence_review()
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        st.error('원문·자료·전처리·보관 출력의 결속을 확인할 수 없습니다. 변경된 파일을 점검한 뒤 다시 실행하세요.')
        return
    counts = report['public_counts']
    st.write(f"기존 자료 쌍 {counts['pairs_with_arithmetic']}세트 · 산술 일치 {counts['arithmetic_matches']}/{counts['claims']} · 차단 {counts['blocked']}건 · 신규 원자료 쌍 0세트")
    st.dataframe(pd.DataFrame([{'주장': r['claim_id'], '상태': r['action'],
                               '계산값': r.get('value'), '행수': r.get('rows_used'), '이유': r['reason']}
                              for r in report['public']['results']]), hide_index=True)
    with st.expander('주장별 원문·실행 경로'):
        st.caption('개발자 등록 조건입니다. 원문 인용·분모·결측·필터·독립 계산값을 함께 확인하며, 산술 일치를 의미 승인으로 바꾸지 않습니다. 원자료·원문·설정 지문은 내려받는 JSON에 포함됩니다.')
        st.dataframe(pd.DataFrame([{'주장': r['claim_id'], '논문': r['paper_url'],
            '원문 인용': r['source_quote'], '위치': r['source_location'], '근거 종류': r['source_kind'],
            '방법': r['method'], '대상 열': r['column'], '필터': json.dumps(r['filters'], ensure_ascii=False, sort_keys=True),
            '결측 처리': r['missing_policy'], '전처리': r['preprocessing_kind'] or '등록 전처리 없음',
            '보고값': r['reported_value'], '허용오차': r['tolerance'], '계산 관측수': r['observations_used'],
            '독립 계산값': r['independent_value'], '상태': r['action']}
            for r in report['evidence_chain']]), hide_index=True)
    with st.expander('논문별 등록 부담과 지원 범위'):
        st.caption('출판 원문 미확보 Wine도 등록 참조에 포함됩니다. 참조 논문 수를 검증 성공 수로 세지 않습니다. 설정량은 자료확보·의미매핑에 든 사람 시간이나 확장 자동화율이 아닙니다.')
        st.dataframe(pd.DataFrame([{'논문': r['paper_url'], '등록 주장': r['claims'],
            '산술 일치': r['arithmetic_matches'], '차단': r['blocked'], '등록 방법': ', '.join(r['methods']),
            '설정 필드': r['metadata_fields'], '설정 바이트': r['metadata_bytes'],
            '등록 시간': '미측정'} for r in report['registration_inventory']]), hide_index=True)
        st.caption('설정 바이트는 각 주장 메타데이터를 키 정렬·공백 없이 UTF-8로 직렬화한 합계입니다. 파일 전체 크기와 다릅니다. 공통 등록 검산은 행수·결측수·평균, 전처리는 명시된 숫자 제외·열 투영 계약만 지원합니다. 가중·군집·혼합모형 등으로 자동 확장하지 않습니다.')
    # [작성: UX·확장설계 담당] 2026-09-28 case87
    # 무엇을: 공통조건 명세 다운로드·검증복원 / 왜: 코드를 고치지 않고 명세 재사용 / 입력·출력: 템플릿 -> 표준JSON / 검증: test_case87 화면·동일결과. 실행·승인 없음.
    with st.expander('공통조건 템플릿 · 등록 재사용'):
        st.json(report['template_metrics'])
        st.caption('동일한 값을 가진 필드만 논문별 공통조건으로 묶습니다. 복원 명세의 값·순서는 그대로이며 근거·필터·분모·승인을 새로 추정하지 않습니다. 바이트·필드 감소는 사람 작업시간 절감이나 자동화율이 아닙니다.')
        st.download_button('공통조건 템플릿 내려받기',_json_bytes(report['registration_template']),file_name='registration_template.json',mime='application/json')
        upload=st.file_uploader('수정한 공통조건 템플릿 · 2MB 이하',type=['json'],key='registration_template_upload')
        if upload is not None:
            try:
                raw=upload.getvalue()
                if len(raw)>MAX_UPLOAD_BYTES: raise ValueError('2MB 초과')
                expanded=expand_registration_template(_load_json(raw))
                st.download_button('복원한 표준 명세 내려받기',_json_bytes(expanded),file_name='registered_cases.json',mime='application/json')
                st.info('명세만 복원했습니다. 파일·원문·조건 검증과 검산은 기존 등록 검산기로 별도 수행해야 합니다. 실행·승인하지 않았습니다.')
            except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
                st.error('템플릿의 중복 ID·조건 충돌·필수 필드·상대경로·크기를 확인하세요.')
    comparison = report['comparison']
    c, d, e = comparison['counts'], comparison['metric_denominators'], comparison['execution_summary']
    st.write(f"보관 비교: 행동 일치 {c['action_agreements']}/{d['action_agreements']} · 산술 참조 일치 제품 {c['product_arithmetic_matches']}/{d['product_arithmetic_matches']}, 모델 {c['model_arithmetic_matches']}/{d['model_arithmetic_matches']}")
    st.caption(f"2026-09-25의 모델 호출 {c['model_calls']}회·{c['cases']}사례 재사용 · 새 모델 호출 0회. 제품 기록은 case85 재계산 기록입니다. 양쪽의 같은 답이 정답률이나 우위 증거는 아닙니다.")
    st.warning(f"실행 선언 중 로그 미확인 {e['unsupported_claims']}건 · 거짓 실행률 미산출. 로그가 없다는 이유로 미실행 또는 거짓이라고 판정하지 않습니다. 실제 사람 정답·검토시간은 미측정입니다.")
    st.download_button('자동 검산 근거 JSON 내려받기', _json_bytes(report),
                       file_name='machine_evidence_review.json', mime='application/json')


# [작성: 등록준비·UX 담당] 2026-09-29 case89
# 무엇·왜: 업로드 명세의 주장별 수동 수정 동선 / 입출력: 2MB JSON→읽기 전용 보고 / 검증: test_case89_registration; root는 고정 PROJECT_ROOT, 압축해제·네트워크·실행 없음.
def render_registration_readiness():
    with st.expander('등록 준비도 · 실행 전 수정필드 확인'):
        st.caption('등록 JSON 또는 공통조건 템플릿만 받습니다. 파일은 현재 프로젝트 root에서 읽습니다. 경로 추정·원문 승격·해시 자동 갱신·검산 실행·사람 승인은 하지 않습니다.')
        st.download_button('기존 등록 표준명세 템플릿 내려받기',
            (PROJECT_ROOT/'data/evaluation/public_reproduction_cases.json').read_bytes(),
            file_name='registration_manifest.json', mime='application/json')
        upload = st.file_uploader('등록 준비도 JSON · 최대 2MB', type=['json'], key='registration_readiness_upload', max_upload_size=2)
        if upload is None: return
        try:
            report = registration_readiness(upload.getvalue(), root=PROJECT_ROOT)
            st.dataframe(pd.DataFrame([{'주장': r['claim_id'], '준비 상태': r['action'],
                '인용 발견': r['source_quote_found'], '의미 검증': r['source_scope_verified'],
                '수정필드': ', '.join(x['field'] for x in r['issues']) or '없음'} for r in report['results']]), hide_index=True)
            for row in report['results']:
                for item in row['issues']:
                    st.write(row['claim_id']+' · '+item['field']+' · '+item['reason']+' · '+item['repair_action'])
            st.caption(report['scope'])
            st.download_button('등록 준비도 보고 JSON 내려받기', _json_bytes(report), file_name='registration_readiness.json', mime='application/json')
        except (ValueError, OSError, TypeError, KeyError, UnicodeError, RecursionError):
            st.error('명세 전체 차단: JSON 구문·중복 키/ID·스키마·크기·공통조건 충돌을 확인하세요. 자동 수정하지 않았습니다.')


# [작성: 통계·연구자UX 담당] 2026-09-29 case89
# 무엇을: 저자 분석자료 회귀계수의 두 계산경로 비교 / 왜: 표본수 일치와 실제 모형 재계산 구별 / 입력·출력: 고정명세→표·JSON / 검증: test_case89_author_models 실제사례·화면.
def render_author_models():
    with st.expander('저자 분석자료 · 회귀계수 대조'):
        st.caption('공개 정정자료 264행 · 2개 모형의 3개 보고계수. 저자 분석자료의 계수 산술만 대조하며 통계가정·원문 의미·논문 결론을 승인하지 않습니다.')
        st.warning('원자료 제외 규칙 미재현: 후보 규칙과 저자 분석자료는 모두 264명이지만 포함 대상이 서로 2명씩 다릅니다. 공변량 재코딩도 확인되지 않았습니다.')
        if not st.button('저자 분석자료 계수 재계산',key='author_models_run'): return
        try:
            from tools.author_model_audit import audit_models
            report=audit_models(PROJECT_ROOT/'data/evaluation/author_model_cases.json',root=PROJECT_ROOT)
            st.dataframe(pd.DataFrame([{'모형':r['model_id'],'상태':r['action'],'관측수':r.get('n'),'잔차 자유도':r.get('residual_df'),'차단 이유':r.get('reason','')} for r in report['results']]),hide_index=True)
            st.json(report)
            st.download_button('저자 분석자료 계수 대조 JSON 내려받기',_json_bytes(report),file_name='author_model_review.json',mime='application/json')
        except (ValueError,OSError,KeyError,TypeError,UnicodeError):
            st.error('저자 자료·원문 지문·모형 명세를 확인하세요. 근거 확인 실패로 재계산을 중단했습니다.')


# [작성: 재현·통합 담당] 2026-09-29 case90
# 무엇: 원래/정정명세 4자료8쌍 대조 / 왜: 새통계엔진 중복구현없이 재사용 / 입력·출력: 고정상대명세→보고 / 검증: test_case90 N·df·각b/SE/t.
# [수정: 전문가4 교차검토] 2026-09-29 case91
# 종류: 오류수정 / 재현 방법: 첫 감사 직후 명세 조건 변경 / 변경 전: 서로 다른 시점 결과 혼합
# 변경 후: 전체 입력·코드·환경의 시작/종료 기록 비교 후 반환 / 왜: 묶음 보고의 동일 조건 보장 / 영향: 변경 중 보고 폐기; test_case91_crosscheck.
def registered_model_comparison():
    from tools.author_model_audit import audit_models
    from tools.change_impact import snapshot_author_models
    before = snapshot_author_models(AUTHOR_MODEL_MANIFESTS, root=PROJECT_ROOT)
    reports=[audit_models(PROJECT_ROOT/name,root=PROJECT_ROOT) for name in AUTHOR_MODEL_MANIFESTS]
    if before != snapshot_author_models(AUTHOR_MODEL_MANIFESTS, root=PROJECT_ROOT):
        raise ValueError('묶음 검산 중 입력·명세·코드·환경이 변경되어 보고를 폐기했습니다.')
    corrected=[x for run in reports for x in run['results'] if x['model_id'].endswith('/corrected')]
    original=[x for run in reports for x in run['results'] if x['model_id'].endswith('/original')]
    return {'reports':reports,'summary':{'model_pairs':len(corrected),'corrected_matches':sum(x['action']=='COEFFICIENT_MATCH' for x in corrected),'original_matches':sum(x['action']=='COEFFICIENT_MATCH' for x in original),'corrected_df_mismatches':sum(x.get('reported_df_matches') is False for x in corrected)},'scope':'동일 논문 4반복자료의 8개 모형 쌍. b·SE·t 산술일치만 검사. 독립 논문16편·원자료선별완결·결론승인·AI우위가 아님.'}


# [작성: 연구자 업무 담당] 2026-09-29 case91
# 무엇: 입력에 결속한 미완료 업무 / 왜: 수치일치가 검토종료로 오해되지 않게 / 입력·출력: 검산보고→역할·완료증거·영향모형 / 검증: test_case91_workflow.
def model_followup_tasks(report):
    # 작성: case105 통계·계보 담당 | 집계 증거는 입력 지문에 결속, 기존 16개 업무 완료 상태는 유지
    from core.research_cases import n3_followup_context
    is_n3 = len(report['reports']) == 4 and all(
        run['results'] and all(row['model_id'].startswith('N3-11814-') for row in run['results'])
        for run in report['reports'])
    evidence = n3_followup_context(report) if is_n3 else None
    definitions={
        'INPUT_BLOCKED':('P0','자료·명세 담당','원문·자료 지문과 필수 분석조건을 복구','현재 파일 지문/명세가 일치하고 같은 모형 재실행이 차단 없이 완료된 기록'),
        'STATISTIC_DISAGREEMENT':('P0','통계 재현 담당','보고값·단위·반올림·대상 열·전처리 조건을 대조','원문 인용과 조건별 재계산 기록; 값을 맞추려고 근거 없는 조건을 변경하지 않음'),
        'DF_DISAGREEMENT':('P1','통계 방법 담당','보고 자유도와 잔차 자유도의 정의를 확인','공개 저자 코드/방법 문구에 근거한 자유도 정의와 모형별 N·설계행렬 열수의 대응'),
        'RAW_SELECTION_UNVERIFIED':('P1','데이터 계보 담당','원자료 포함·제외와 공변량 재코딩 근거를 확보','공개 선택 규칙으로 재생성한 대상 행 집합과 분석자료의 일치 기록; 같은 N만으로 완료하지 않음'),
        'SEMANTIC_UNVERIFIED':('P1','연구자료 연결 담당','인용의 변수·대상·단위가 분석열과 대응하는지 문서화','공개 변수사전·방법·근거 위치의 대응표; 의미 정답이나 사람 승인으로 자동 승격하지 않음'),
        'ASSUMPTIONS_UNVERIFIED':('P2','통계 방법 담당','독립성·오차구조·표준오차 방식의 지원 범위를 확인','연구 설계/저자 조건에 근거한 가정과 검정 범위; 미지원 가정은 미확인 유지')}
    grouped={}
    for index,run in enumerate(report['reports']):
        references={key:run.get(key) for key in ('data_sha256','source_sha256','manifest_sha256')}
        for row in run['results']:
            if row['action'] not in {'BLOCK','COEFFICIENT_MATCH','COEFFICIENT_MISMATCH'}:raise ValueError('미지원 검산 상태')
            codes=[]
            if row['action']=='BLOCK':codes.append('INPUT_BLOCKED')
            if row['action']=='COEFFICIENT_MISMATCH':codes.append('STATISTIC_DISAGREEMENT')
            if row.get('reported_df_matches') is False:codes.append('DF_DISAGREEMENT')
            for flag,code in [('raw_selection_verified','RAW_SELECTION_UNVERIFIED'),('semantic_verified','SEMANTIC_UNVERIFIED'),('assumptions_verified','ASSUMPTIONS_UNVERIFIED')]:
                if run.get(flag) is not True:codes.append(code)
            for code in codes:
                # ponytail: 같은 명세/입력 안에서만 묶음. 다른 연구 간 임무 병합은 별도 근거가 필요.
                key=_fingerprint({'references':references,'report_index':index,'reason_code':code})
                if key not in grouped:
                    priority,owner,title,completion=definitions[code]
                    grouped[key]={'task_id':key,'reason_code':code,'priority':priority,'owner_role':owner,'task':title,'completion_evidence':completion,'input_hashes':references,'model_ids':[],'completed':False,'resolution_mode':'공개 근거·명세 보완 후 재검토; 미확인은 자동 승인하지 않음'}
                    if evidence is not None and code in {'RAW_SELECTION_UNVERIFIED', 'DF_DISAGREEMENT'}:
                        grouped[key]['partial_evidence'] = evidence[index]
                if row['model_id'] not in grouped[key]['model_ids']:grouped[key]['model_ids'].append(row['model_id'])
    return sorted(grouped.values(),key=lambda t:(t['priority'],t['task_id']))


# [작성: 연구자UX 담당] 2026-09-29 case90
# 무엇: 한버튼 실제계산·부호/누락행/df동시표시 / 왜: 별도코드만있는자료를시연가능하게 / 입력·출력: 클릭→16행·JSON / 검증: test_case90 AppTest.
# [수정: 연구자 업무 담당] 2026-09-29 case91
# 종류: 효율화 / 전후: 미확인 경고만→입력별 역할·완료증거를 묶은 인계 / 왜: 팀의 다음 일을 명확하게 / 영향: 수치/승인 불변; test_case91_workflow.
def render_registered_model_comparison():
    with st.expander('원래 구문·정정 구문 · 8개 회귀 주장 비교'):
        st.caption('같은 저자 분석자료에서 두 명세를 실행합니다. 숫자 재현과 올바른 분석조건의 확인은 별개입니다. 정정 공지·저자 구문의 개발자 매핑이며 자동 의미 승인이 아닙니다.')
        if not st.button('원래·정정 8개 주장 재계산',key='registered_models_run'): return
        try:
            report=registered_model_comparison();s=report['summary']
            st.write(f"정정 구문 수치 일치 {s['corrected_matches']}/{s['model_pairs']} · 원래 구문 수치 재현 {s['original_matches']}/{s['model_pairs']}")
            rows=[]
            for run in report['reports']:
                for result in run['results']:
                    term=next(iter(result.get('terms',{}).values()),{});stats=term.get('statistics',{})
                    rows.append({'명세':result['model_id'],'상태':result['action'],'입력행':result.get('n_input'),'결측제외':result.get('rows_dropped'),'계산행':result.get('n'),'계수':term.get('product'),'표준오차':stats.get('se',{}).get('product'),'t값':stats.get('statistic',{}).get('product'),'보고df':result.get('reported_df'),'잔차df':result.get('residual_df'),'차단이유':result.get('reason','')})
            st.dataframe(pd.DataFrame(rows),hide_index=True)
            st.warning(f"정정 공지 자유도와 잔차 자유도 불일치 {s['corrected_df_mismatches']}건. 원자료 제외 사유·공변량 재코딩은 미확인입니다. 원래 오류값의 재현은 올바른 분석이라는 뜻이 아닙니다.")
            st.json(report)
            st.download_button('원래·정정 비교 근거 JSON 내려받기',_json_bytes(report),file_name='registered_model_comparison.json',mime='application/json')
            tasks=model_followup_tasks(report)
            st.markdown('**다음 검토 작업** — 같은 입력·명세의 공통 문제를 묶었습니다. 숫자 일치와 업무 완료는 별개입니다.')
            for task in tasks:
                st.markdown(f"- **{task['priority']} · {task['owner_role']}**: {task['task']} · 영향 모형 {len(task['model_ids'])}개")
                if task.get('partial_evidence'):
                    st.caption(f"추가 증거: 반복 {task['partial_evidence']['replication']} · 입력 연결 {task['partial_evidence']['input_binding']} · 응답열 대응·df 관찰만 확보, 완료 미확인")
            st.download_button('역할·완료증거가 포함된 작업 목록 내려받기',_json_bytes({'tasks':tasks,'human_approval':False}),file_name='followup_tasks.json',mime='application/json')
        except (ValueError,OSError,KeyError,TypeError,UnicodeError):
            st.error('원문·자료·명세를 확인할 수 없어 대조를 중단했습니다. 지문과 필수 필드를 확인하세요.')


# 작성: case105 통계·계보 담당 | 입력 짝짓기 실오류를 재사용 가능한 식별자 검사로 연결; 승인 없음
def render_reproduction_alignment():
    from core.research_cases import supplemental_reproduction_evidence
    from core.row_alignment import row_alignment_indices
    with st.expander('추가 재현 증거 · 자료 행과 기준 목록 대응'):
        st.caption('영장류 사례 N3-49665는 계통 통계방법 미지원으로 차단합니다. 외부 Python 검증 기록은 제품 계산·승인이 아닙니다.')
        try:
            evidence = supplemental_reproduction_evidence()
            st.write('외부 재실행: 원래 행 순서 55/57 · 기준 순서 57/57. λ는 저자값이며 저자 R 코드는 실행하지 않았습니다.')
            st.caption('저자 저장소 이용허락은 미확인입니다. 원자료와 저자코드는 배포 묶음에 포함하지 않습니다. 사람 확인은 팀원의 진술만 보관합니다.')
            st.json(evidence)
        except (ValueError, OSError, KeyError, UnicodeError):
            st.error('추가 증거 지문이 맞지 않아 기록 표시를 차단했습니다.')
        st.caption('식별자를 한 줄에 하나씩 입력하세요. 같은 개수라도 중복·누락·순서 차이는 계산 전에 차단합니다. 식별자가 같은 실제 대상을 뜻하는지는 별도 확인해야 합니다.')
        data = st.text_area('자료 행 식별자', key='alignment_data_ids')
        reference = st.text_area('기준 목록 식별자', key='alignment_reference_ids')
        reorder = st.checkbox('일치하는 식별자로 명시적 재정렬 허용', key='alignment_allow_reorder')
        if st.button('행 대응 검사', key='alignment_run'):
            try:
                if len(data.encode('utf8')) + len(reference.encode('utf8')) > MAX_UPLOAD_BYTES:
                    raise ValueError('입력은 합계 2 MB 이하로 제한됩니다.')
                indices = row_alignment_indices(data.splitlines(), reference.splitlines(), allow_reorder=reorder)
                st.success(f'식별자 대응 {len(indices)}행 확인. 의미·방법·결론 승인은 아닙니다.')
                st.json({'status':'IDENTIFIERS_ALIGNED','source_row_indices':indices,'approved':False})
            except ValueError as error:
                st.error(f'행 대응 차단: {error}')


# [작성: 변경UX 담당] 2026-09-29 case91
# 무엇: 고정4명세의 영향계획과 실제 선택 재검산 / 왜: 업로드기록의 경로실행·옛수치승격 방지 / 입력·출력: 이전snapshot bytes·실행선택→현재snapshot·영향·새보고 / 검증: test_case91_change_ui.
# [수정: 전문가4] 2026-09-29 case92
# 종류: 효율화 / 재현 방법: 고정 UI 안에 실행로직 중복 / 변경 전: UI 전용 구현 / 변경 후: 공통 실행기 재사용 / 왜: 로컬 도구와 같은 변경 차단 / 영향: 웹 입력 경계 고정 유지; case91/case92 동일 결과 시험.
def author_model_change_review(previous_raw=None, rerun=False):
    from tools.change_impact import snapshot_author_models, execute_author_model_changes
    if previous_raw is None:
        return {'current_snapshot':snapshot_author_models(AUTHOR_MODEL_MANIFESTS, root=PROJECT_ROOT),
                'impact':None, 'reports':[], 'fresh_execution':False, 'human_approval':False}
    if len(previous_raw) > MAX_UPLOAD_BYTES:
        raise ValueError('이전 기록은 2 MB 이하만 비교할 수 있습니다.')
    return execute_author_model_changes(_load_json(previous_raw), AUTHOR_MODEL_MANIFESTS,
                                        root=PROJECT_ROOT, execute=rerun)



# [작성: 변경UX 담당] 2026-09-29 case91
# 무엇: 현재snapshot 다운로드·이전기록 영향표·영향명세만 새검산 / 왜: 연구자의 변경재검토를 실제실행에 연결 / 입력·출력: 화면선택→보고·다운로드 / 검증: test_case91_change_ui 및 기존 case90/case91 UI.
def render_author_change_review():
    with st.expander('저자모형 · 입력 변경과 재검산 계획'):
        if not st.checkbox('저자모형 변경 추적 열기', key='author_change_open'):
            return
        st.warning('이전 snapshot은 변경영향 계획용입니다. 입력 동일은 현재 산술검산 성공이나 사람 승인이 아니며, 이전 수치를 새 실행 결과로 사용하지 않습니다.')
        st.caption('같은 논문의 고정된 4개 분석명세만 비교합니다. 기준 기록의 작성자 진위는 자체 해시로 인증할 수 없습니다.')
        upload = st.file_uploader('이전 저자모형 snapshot JSON · 최대 2MB', type=['json'],
                                  key='author_change_previous', max_upload_size=2)
        try:
            if upload is not None and upload.size > MAX_UPLOAD_BYTES:
                raise ValueError('이전 기록은 2 MB 이하만 비교할 수 있습니다.')
            raw = upload.getvalue() if upload is not None else None
            review = author_model_change_review(raw)
            st.download_button('현재 저자모형 입력 snapshot 내려받기', _json_bytes(review['current_snapshot']),
                               file_name='author_model_snapshot.json', mime='application/json')
            plan = review['impact']
            if plan is None:
                st.info('현재 기록을 보관한 뒤 이전 기록을 올리면 변경영향을 비교합니다. 아직 산술검산하지 않았습니다.')
                return
            st.dataframe(pd.DataFrame([{'명세': r['manifest'], '모형': r['model_id'],
                '상태': LABELS[r['action']], '변경 입력': ', '.join(r['changed_inputs']),
                '재검산 필요': r['rerun_required'], '차단 이유': ', '.join(r['blocking_reasons'])}
                for r in plan['results']]), hide_index=True)
            st.download_button('저자모형 변경영향 계획 내려받기', _json_bytes(plan),
                               file_name='author_model_impact.json', mime='application/json')
            st.caption(f"재검산 가능한 영향 명세 {len(plan['rerun_manifests'])}개. 차단된 입력은 원문·자료·명세를 복구한 뒤 새 기준으로 점검하세요.")
            if st.button('영향 명세만 실제 재검산', key='author_change_rerun', disabled=not plan['rerun_manifests']):
                with st.spinner('영향 명세를 재검산하고 입력·코드·환경을 다시 확인합니다…'):
                    fresh = author_model_change_review(raw, rerun=True)
                if not fresh['fresh_execution']:
                    st.info('현재 입력을 다시 비교한 결과 실행할 영향 명세가 없습니다. 새 수치 검산 결과를 만들지 않았습니다.')
                    return
                st.success(f"영향 명세 {len(fresh['reports'])}개를 실제 재검산했습니다. 산술 상태는 아래 보고에서 확인하세요.")
                st.json(fresh)
                st.download_button('실제 재검산 근거 내려받기', _json_bytes(fresh),
                                   file_name='author_model_fresh_rerun.json', mime='application/json')
        except (ValueError, OSError, KeyError, TypeError, UnicodeError, RecursionError, OverflowError):
            st.error('기록 크기·고정 명세·지문·의존성을 확인하세요. 비교 또는 재검산 중 결속이 깨져 결과를 제공하지 않습니다.')


# [작성: 전문가4·18] 2026-09-28 case82
# 무엇을: 현재 독립 검산기를 그대로 배포 / 왜: 프로젝트 설치 없는 재실행 / 입력·출력: 없음 -> Python bytes / 검증: test_case82의 -I -S 실행.
def replay_tool_bytes():
    return (PROJECT_ROOT / 'tools/independent_replay.py').read_bytes()


# [작성: 전문가4·8] 2026-09-28 case82
# 무엇을: 데이터 묶음만 받아 기존 검산기에 전달 / 왜: 외부 코드 실행 없는 재검산 / 입력·출력: ZIP bytes -> 지문 결속 결과 / 검증: test_case82 변조·한도·평균.
def audit_uploaded_packet(raw):
    base = {'packet_sha256': hashlib.sha256(raw).hexdigest(),
            'replay_tool_sha256': hashlib.sha256(replay_tool_bytes()).hexdigest(),
            'human_approval': False}
    try:
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError('화면 재실행 묶음은 2 MB 이하만 허용합니다.')
        return {**replay_packet(raw), **base}
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        return {**base, 'action': 'BLOCK', 'reason': str(exc) or '묶음 형식 확인 실패',
                'source_scope_verified': False, 'authenticity_verified': False}


# [작성: 전문가1·18] 2026-09-28 case82
# 무엇을: 외부 묶음 검산과 독립 도구 제공 / 왜: 앱 밖 연구 흐름에 연결 / 입력·출력: 업로드 -> JSON / 검증: test_case82 UI·독립 실행.
def _replay_intake():
    st.subheader('3. 외부 재실행 묶음 검산')
    st.caption('NAIS 재실행 형식의 데이터 ZIP만 받습니다. 업로드한 프로그램은 실행하지 않습니다. 지원: 행수·결측수·평균. 임의 AI 답변이나 미지원 통계는 이 형식 없이 검산할 수 없습니다.')
    runner = replay_tool_bytes()
    st.download_button('독립 검증 도구 내려받기', runner,
                       file_name='nais_replay.py', mime='text/x-python')
    st.code('python -I -S nais_replay.py --packet case.zip', language='shell')
    st.caption('다운로드한 도구와 묶음만으로 실행합니다. Python 표준 라이브러리를 사용하며 pandas·Streamlit 설치는 필요 없습니다. 도구 SHA-256: ' + hashlib.sha256(runner).hexdigest())
    uploaded = st.file_uploader('재실행 묶음 ZIP (최대 2 MB)', type=['zip'],
                                key='replay_packet_upload', max_upload_size=2)
    if uploaded is not None:
        if uploaded.size > MAX_UPLOAD_BYTES:
            st.error('화면 재실행 묶음은 2 MB 이하만 허용합니다.')
            return
        report = audit_uploaded_packet(uploaded.getvalue())
        labels = {'ARITHMETIC_MATCH': '저장된 실행값과 독립 재계산 일치',
                  'MISMATCH': '저장된 실행값과 독립 재계산 불일치', 'BLOCK': '검산 차단'}
        st.write(labels[report['action']])
        st.json(report)
        st.download_button('외부 묶음 검산 결과 JSON 내려받기', _json_bytes(report),
                           file_name='external_replay_result.json', mime='application/json')
    st.warning('산술 일치는 논문 주장·원문 진위·사람 승인이 아닙니다. 파일과 해시를 함께 바꾸는 공격은 외부 서명 기준점 없이 탐지하지 못합니다. 민감한 자료는 로컬 검증 도구로 실행하세요.')


# [작성: 전처리 UX·통합 담당] 2026-09-28 case83
# 무엇을: 실제 부분재계산 계약의 의존성 추적 / 왜: 원자료 변화의 영향 표시 / 입력·출력: 등록명세·이전snapshot -> 비교 / 검증: test_case83_integration 및 lineage시험.
def _preprocessing_review():
    from tools.change_impact import snapshot_registry_with_preprocessing, compare_snapshots_with_preprocessing
    st.subheader('4. 전처리 원자료·저자 코드 변경 추적')
    st.caption('기존 공개 FAIR 자료의 명시된 필터·투영 계약만 지원합니다. 팀원이 제안한 임의 의존성 목록은 검증 계약을 대신하지 않습니다. 저자 코드를 실행하거나 논문 전체를 재현하지 않습니다.')
    if st.button('현재 전처리 입력 검증', key='preprocessing_inspect'):
        st.session_state['preprocessing_open'] = True
    # [수정: 통합시험 담당] 2026-09-28 case83 / 종류: 오류수정 / 재현: 버튼 뒤 재실행 시 업로드 사라짐 / 전후: 일회 변수→명시 체크 상태 / 왜: 이전기록 업로드 유지 / 영향: 화면 열림만, 검증은 매번 새로 수행.
    active = st.checkbox('전처리 변경 추적 열기', key='preprocessing_open')
    if not active:
        return
    try:
        current = snapshot_registry_with_preprocessing(PROJECT_ROOT/'data/evaluation/registered_reproduction_cases.json', root=PROJECT_ROOT)
        st.json([{'claim_id': row['claim_id'], 'preprocessing': row['preprocessing']} for row in current['claims']])
        st.download_button('전처리 입력 기록 JSON 내려받기', _json_bytes(current),
                           file_name='preprocessing_snapshot.json', mime='application/json')
        previous = st.file_uploader('이전 전처리 기록 JSON (schema 2)', type=['json'],
                                    key='preprocessing_previous', max_upload_size=2)
        if previous is not None:
            if previous.size > MAX_UPLOAD_BYTES:
                raise ValueError('이전 기록은 2 MB 이하만 비교할 수 있습니다.')
            report = compare_snapshots_with_preprocessing(_load_json(previous.getvalue()), current)
            st.json(report)
            st.download_button('전처리 변경 영향 JSON', _json_bytes(report),
                               file_name='preprocessing_impact.json', mime='application/json')
        st.caption('CONSISTENT는 명시된 투영과 파일 결속의 일치이며 진위 인증·사람 승인 아님. schema 1 기록은 섞지 않고 새 기준 기록을 만드세요.')
    except (ValueError, OSError, TypeError, KeyError, RecursionError):
        st.error('전처리 기록을 확인할 수 없습니다. 지원 계약·파일 지문·기록 스키마를 확인하세요.')


# [작성: 전문가1/4] 2026-09-26 case63: 업로드 크기·엄격 JSON·snapshot 구조 검사, 파일 경로 실행 없음.
def compare_uploaded_snapshot(raw, current):
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError('이전 기록은 2 MB 이하만 비교할 수 있습니다.')
    try:
        return compare_snapshots(_load_json(raw), current)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ValueError('이전 기록의 JSON 구조·해시 결속을 확인할 수 없습니다.') from exc


# [작성: 전문가1/4] 2026-09-26 case63: JSON 결과 다운로드 직렬화.
def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


# [작성: 전문가1/4] 2026-09-26 case63: 고정 명세와 실제 파일 snapshot에 계산 결과를 결속.
# [수정: 전문가4] 2026-09-26 case65: 무엇/왜: 소스·환경 변경도 세션 결과 무효화 / 입출력: 현재 입력 -> 3요소 binding / 검증: case65 batch binding 시험.
def _current():
    snapshot = snapshot_registry(MANIFEST, root=PROJECT_ROOT)
    binding = (hashlib.sha256(MANIFEST.read_bytes()).hexdigest(), snapshot['content_sha256'], _fingerprint(benchmark_provenance()))
    return snapshot, binding


# [작성: 전문가1/4] 2026-09-26 case63: 기계 실행시간과 등록 설정량만 표시, 사람시간 미측정 명시.
# [수정: 전문가4] 2026-09-26 case65: 무엇/왜: 입력 동일해도 소스·환경 미결속은 역사적 기록 / 입출력: 측정 -> 현재 일치/과거 표시 / 검증: case65 UI 4상태.
def _measurement(binding):
    st.subheader('확장 비용 측정')
    st.caption('등록·검토에 든 사람 시간은 측정하지 않았습니다. 아래 시간은 미리 등록된 설정의 기계 실행시간입니다.')
    if not MEASUREMENT.exists():
        st.info('기계 실행시간 미측정: 측정 기록이 아직 없습니다.')
        return
    try:
        report = _load_json(MEASUREMENT.read_bytes())
        if (report['manifest_sha256'] != binding[0]
                or report.get('snapshotcontent_sha256') != binding[1]
                or report.get('results_identical') is not True):
            st.warning('측정 기록의 등록 명세·실제 입력 또는 반복 결과 확인이 현재와 다릅니다. 기존 측정값은 표시하지 않습니다.')
            return
        counts = [report[key] for key in ('case_count', 'unique_dataset_contents', 'unique_dataset_references',
                  'unique_source_data_pairs', 'manifest_lines', 'manifest_bytes', 'case_top_level_field_count')]
        counts.append(report['warm']['repeats'])
        times = [report['cold']['fresh_process_wall_seconds'], report['warm']['median_seconds']]
        if (not all(type(value) is int and value >= 0 and math.isfinite(value) for value in counts)
                or report['warm']['repeats'] < 1
                or not all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in times)):
            raise ValueError('invalid measurement numbers')
        if report.get('provenance') is not None and report['provenance'].get('environment') != report['environment']:
            raise ValueError('displayed environment is not bound')
        env = report['environment']
        if (not isinstance(env, dict) or not all(isinstance(env.get(key), str) for key in ('python', 'platform', 'processor'))
                or not isinstance(env.get('packages'), dict) or not isinstance(report.get('measured_at_utc', '기록 없음'), str)):
            raise ValueError('invalid recorded environment')
        if report.get('provenance') != benchmark_provenance():
            st.warning('과거 측정: 코드·환경이 현재와 다르거나 결속 기록이 없습니다. 아래 시간은 기록된 측정환경의 역사적 값이며 현재 성능을 뜻하지 않습니다.')
        else:
            st.caption('현재 코드·환경과 일치하는 측정 기록입니다. 현재 부하에서의 실행시간 보장이나 사람 승인은 아닙니다.')
        st.write(f"등록 {report['case_count']}개 · 서로 다른 자료 내용 {report['unique_dataset_contents']}종 · 자료 참조 {report['unique_dataset_references']}개 · 근거·자료 조합 {report['unique_source_data_pairs']}개 · 설정 {report['manifest_lines']}줄 / {report['manifest_bytes']} bytes · 사례 필드 {report['case_top_level_field_count']}개")
        st.write(f"새 프로세스 1회 {report['cold']['fresh_process_wall_seconds']:.3f}초 · 준비 실행 제외 반복 {report['warm']['repeats']}회 중앙값 {report['warm']['median_seconds']:.3f}초")
        st.caption('새 프로세스 시간에는 시작·출력 비용이 포함됩니다. 운영체제 파일 캐시는 비우지 않았습니다. 반복 시간에는 파일 읽기·해시·두 계산 경로가 포함됩니다.')
        st.write({'Python': env['python'], '운영체제': env['platform'], '프로세서': env['processor'], '패키지': env['packages']})
        st.caption('지원된 방법의 등록 확장 측정입니다. 공통 기능 개발·자료 확보·미지원 분석 구현 비용을 포함하지 않습니다.')
    except (ValueError, KeyError, TypeError, OSError, OverflowError, AttributeError):
        st.warning('측정 기록의 형식을 확인할 수 없어 측정값을 표시하지 않습니다.')


# [작성: 전문가1/4] 2026-09-26 case63: 고정 5사례 검산·이전 입력 비교·오래된 결과 차단 화면.
# [수정: 전문가4] 2026-09-26 case65: 무엇/왜: 코드·환경 변경의 세션 무효화 설명 / 입출력: binding 불일치 -> 재실행 안내 / 검증: case63 기존 UI 및 case65 binding.
def render_portfolio_workspace():
    st.title('변경·확장 검증실')
    st.warning('개발자 등록 매핑 시험 · 원문 진위 확인과 사람 승인 아님')
    st.caption('등록 명세의 산술 대조와 입력 변경을 확인합니다. 논문 전체 재현이나 범용 AI 우위를 뜻하지 않으며 자동 최종 승인을 만들지 않습니다.')
    try:
        current, binding = _current()
    except (ValueError, OSError):
        st.error('현재 등록 자료를 읽거나 검증할 수 없습니다. 배포 자료를 확인하세요.')
        return
    st.subheader('1. 현재 입력 기록과 변경 영향')
    st.write(f"현재 등록 주장 {len(current['claims'])}개")
    st.download_button('현재 입력 기록 JSON 내려받기', data=_json_bytes(current),
                       file_name='current_input_snapshot.json', mime='application/json')
    st.caption('기록의 해시는 내부 자체일관성만 확인합니다. 작성자 인증이 아니며 내용과 모든 해시를 함께 다시 쓰는 공격은 탐지하지 못합니다.')
    # [수정: 전문가1/4] 2026-09-26 case63: 위젯 표시·전송 제한도 서버 JSON 검사와 동일한 2 MB 적용.
    uploaded = st.file_uploader('이전 입력 기록 JSON (최대 2 MB)', type=['json'], key='case63_previous_snapshot', max_upload_size=2)
    if uploaded is not None:
        try:
            if uploaded.size > MAX_UPLOAD_BYTES:
                raise ValueError('이전 기록은 2 MB 이하만 비교할 수 있습니다.')
            report = compare_uploaded_snapshot(uploaded.getvalue(), current)
            st.write(' · '.join(f'{LABELS[key]} {value}건' for key, value in report['counts'].items()))
            rows = [{'주장': row['claim_id'], '상태': LABELS[row['action']],
                     '변경 입력': ', '.join(row['changed_inputs']) or '없음',
                     '다음 작업': NEXT_ACTION[row['action']]} for row in report['results']]
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            st.download_button('변경 영향 JSON 내려받기', data=_json_bytes(report),
                               file_name='change_impact.json', mime='application/json')
        except ValueError as exc:
            st.error(str(exc))
    st.subheader('2. 등록된 주장 일괄 검산')
    if st.button('등록된 주장 일괄 검산', key='case63_batch_run'):
        try:
            result = audit_registry(MANIFEST, root=PROJECT_ROOT)
            _, after = _current()
            if after != binding or result['manifest_sha256'] != binding[0]:
                raise ValueError('검산 중 등록 입력이 변경되었습니다. 다시 실행하세요.')
            st.session_state['case63_batch_result'] = {'binding': binding, 'result': result}
        except (ValueError, OSError):
            st.session_state.pop('case63_batch_result', None)
            st.error('등록 자료 검산을 완료하지 못했습니다. 입력 자료 확인 후 다시 실행하세요.')
    saved = st.session_state.get('case63_batch_result')
    if saved and saved.get('binding') != binding:
        st.warning('입력·코드·환경이 바뀌어 낡은 검산 결과를 숨겼습니다. 일괄 검산을 다시 실행하세요.')
    elif saved:
        result = saved['result']
        cases = {row['claim_id']: row['metadata'] for row in current['claims']}
        actions = {'ARITHMETIC_MATCH': '산술 일치', 'ARITHMETIC_MISMATCH': '산술 불일치', 'BLOCK': '차단'}
        st.write(' · '.join(f'{label} {sum(r["action"] == action for r in result["results"])}건' for action, label in actions.items()))
        rows = [{'주장': row['claim_id'], '상태': actions[row['action']],
                 '보고값': cases[row['claim_id']].get('reported_value'), '계산값': row.get('value'),
                 '선택 행수': row.get('rows_used'), '계산 관측수': row.get('observations_used'),
                 '원문 위치': cases[row['claim_id']].get('source_location'), '설명': row['reason']}
                for row in result['results']]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption('차단 사례는 계산값·분모를 비워 둡니다. 산술 일치가 원문의 의미·모집단 승인으로 바뀌지 않습니다.')
        st.download_button('일괄 검산 결과 JSON 내려받기', data=_json_bytes(saved),
                           file_name='registered_batch_result.json', mime='application/json')
    _measurement(binding)
    # [수정: 전문가1·18] 2026-09-28 case82
    # 종류: 효율화 / 재현: 도구 별도 탐색 필요 / 변경 전: 앱 설치 필요 / 변경 후: 도구 다운로드·묶음 검산 / 왜: 다른 연구 흐름 연결 / 영향: 승인 상태 불변.
    _replay_intake()
    _preprocessing_review()
