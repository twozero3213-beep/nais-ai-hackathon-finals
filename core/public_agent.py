"""case105 public, release-time discovery files. Never export a user task or runtime DB."""
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

from core.paths import PROJECT_ROOT

# [수정: 0 이영 · Codex] 2026-10-01T03:19:13+09:00 — 실제 배포의 네 공개 파일은 finals /~/+/app/static/에서 HTTP200이며 기존 team 주소·/app/static 경로는 제공 주소와 다르다. 카탈로그·OpenAPI·AI 요청문·화면 링크를 한 경로로 맞춘다.
BASE_URL = 'https://nais-evidence-gate-finals.streamlit.app'
STATIC_PATH = '/~/+/app/static/'
PUBLIC_FILES = {'agent.json', 'examples.json', 'openapi.json', 'llms.txt'}
MAX_FILE_BYTES = 96 * 1024


# case105: explicit projections of fixed public examples prevent accidental runtime/secret export.
def public_examples():
    from core.research_cases import run_case, _public_cases
    from core.portfolio_workspace import claim_workflow_review
    baseline = run_case('public_penguins')
    flow = claim_workflow_review()
    registered = _public_cases('public_penguins')[0]
    conditions = {k: registered[k] for k in ('method', 'column', 'filters', 'missing_policy',
                  'source_location', 'license', 'license_url', 'data_original_url', 'data_sha256', 'source_sha256')}
    rows = [{k: row[k] for k in ('claim_id', 'reported_value', 'calculated_value', 'tolerance', 'unit', 'status')}
            for row in baseline['rows']]
    changes = []
    for scenario in flow['change_scenarios']:
        changes.append({
            'change': scenario['kind'], 'origin': 'SYNTHETIC_CHANGE',
            'reuse_previous_result': False,
            'claims': [{k: row[k] for k in ('claim_id', 'action', 'changed_inputs')}
                       for row in scenario['impact']['results']],
            'recalculated_value': scenario['result'].get('value'),
            'calculation_status': scenario['result']['action'],
        })
    return {
        'schema_version': 1, 'version': (PROJECT_ROOT/'VERSION').read_text().strip(),
        'approved': False, 'origin': 'RELEASE_TIME_EXECUTION_OF_FIXED_PUBLIC_CASE',
        'arithmetic': {'case_id': 'public_penguins', 'doi': baseline['doi'], 'rows': rows,
                       'source_url': 'https://journal.r-project.org/articles/RJ-2022-020/', 'conditions': conditions,
                       'known': ['등록 원자료의 행 수만 대조했습니다. 결측·다른 주장은 포함하지 않습니다.'],
                       'unknown': baseline['unknown'], 'next_actions': baseline['next_actions']},
        'change_impact': changes,
        'scope': 'One registered row-count claim and three synthetic changes, with an unaffected control claim. Not whole-paper approval, a live query endpoint, a model-quality test or comparative superiority.',
    }


# case105: known local launch commands describe stdio transport; they are not remote MCP URLs.
def public_catalog(examples, built_at):
    from core.research_cases import list_cases
    cases = [{k: item[k] for k in ('id', 'label', 'doi', 'scope')} for item in list_cases()]
    raw = encode_json(examples)
    return {
        'schema_version': 1, 'version': (PROJECT_ROOT/'VERSION').read_text().strip(),
        'name': 'NAIS Evidence Gate', 'built_at': built_at,
        'purpose': 'Read located evidence, understand unresolved conditions, and re-run supported research calculations.',
        'approved': False, 'transport': 'PUBLIC_STATIC_HTTPS_GET',
        'endpoints': {name: BASE_URL+STATIC_PATH+name for name in sorted(PUBLIC_FILES)},
        'examples_sha256': hashlib.sha256(raw).hexdigest(),
        'cases': cases,
        'mcp': [
            {'module': 'tools.research_mcp', 'transport': 'stdio', 'purpose': 'Located local evidence search and fixed registered arithmetic'},
            {'module': 'tools.discovery_mcp', 'transport': 'stdio', 'purpose': 'Bounded public paper metadata discovery'},
            {'module': 'tools.aihub_mcp', 'transport': 'stdio', 'purpose': 'AI Hub metadata, own approved credential required'},
            {'module': 'tools.data_sources_mcp', 'transport': 'stdio', 'purpose': 'Bounded public and satellite metadata/observations, some providers require own credentials'},
        ],
        'limitations': [
            'These GET files are release snapshots; they do not execute a question or search.',
            'Run stdio modules from an installed project in an MCP-capable local host. No public remote MCP endpoint is provided.',
            'Descriptions and arithmetic agreement are not scientific approval. Unknown conditions remain unresolved.',
            'Private tasks, member identities, credentials, raw participant responses and team workspaces are excluded.',
            'No paid language model call or generic-AI superiority is established by these examples.',
        ],
    }


def encode_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')


# Fixed output shapes reject new fields at every nesting level; changes require a deliberate review.
_ROW = dict(claim_id=str, reported_value=(int,float), calculated_value=(int,float,type(None)), tolerance=(int,float), unit=(str,type(None)), status=str)
_CONDITIONS = dict(method=str, column=str, filters={}, missing_policy=str, source_location=str, license=str,
                   license_url=str, data_original_url=str, data_sha256=str, source_sha256=str)
_EXAMPLES = dict(schema_version=int, version=str, approved=bool, origin=str, scope=str,
    arithmetic=dict(case_id=str, doi=str, rows=[_ROW], source_url=str, conditions=_CONDITIONS,
                    known=[str], unknown=[str], next_actions=[str]),
    change_impact=[dict(change=str, origin=str, reuse_previous_result=bool,
        claims=[dict(claim_id=str, action=str, changed_inputs=[str])],
        recalculated_value=(int,float,type(None)), calculation_status=str)])
_CATALOG = dict(schema_version=int, version=str, name=str, built_at=str, purpose=str, approved=bool, transport=str,
    endpoints={name:str for name in PUBLIC_FILES}, examples_sha256=str,
    cases=[dict(id=str,label=str,doi=str,scope=str)], mcp=[dict(module=str,transport=str,purpose=str)], limitations=[str])


def _shape(value, schema):
    if isinstance(schema, dict):
        if not isinstance(value, dict) or set(value) != set(schema): raise ValueError('PUBLIC_SCHEMA_FIELDS')
        for key, child in schema.items(): _shape(value[key], child)
    elif isinstance(schema, list):
        if not isinstance(value, list) or len(value) > 32: raise ValueError('PUBLIC_SCHEMA_LIST')
        for child in value: _shape(child, schema[0])
    elif type(value) not in (schema if isinstance(schema, tuple) else (schema,)):
        raise ValueError('PUBLIC_SCHEMA_TYPE')


def _openapi(version):
    api = {'openapi':'3.1.0','info':{'title':'NAIS public release snapshots','version':version},
           'servers':[{'url':BASE_URL}], 'paths':{}}
    for name in sorted(PUBLIC_FILES - {'openapi.json'}):
        mime = 'application/json' if name.endswith('.json') else 'text/plain'
        api['paths'][STATIC_PATH+name] = {'get': {
            'summary': 'Read the public release snapshot '+name,
            'responses': {'200': {'description': 'Static public snapshot; no calculation or user-task access',
                                  'content': {mime: {'schema': {'type': 'object' if name.endswith('.json') else 'string'}}}}}}}
    return api


# case105: check the entire static directory, not only intended outputs; extra files become public too.
def validate_public_directory(directory, *, require_complete=True, check_schema=True):
    from tools.make_recovery_bundle import SECRET
    directory = Path(directory)
    if directory.is_symlink() or (hasattr(directory, 'is_junction') and directory.is_junction()):
        raise ValueError('PUBLIC_DIRECTORY_LINK')
    entries = list(directory.iterdir()) if directory.exists() else []
    if {p.name for p in entries} - PUBLIC_FILES:
        raise ValueError('UNEXPECTED_PUBLIC_FILE')
    if require_complete and {p.name for p in entries} != PUBLIC_FILES:
        raise ValueError('PUBLIC_FILE_MISSING')
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('UNSAFE_PUBLIC_FILE')
        raw = path.read_bytes()
        if SECRET.search(raw) or re.search(rb'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?:home|Users|tmp|private)/|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', raw):
            raise ValueError('PRIVATE_CONTENT_IN_PUBLIC_FILE')
        if path.suffix == '.json':
            def invalid_number(value): raise ValueError('PUBLIC_NONFINITE_NUMBER')
            obj = json.loads(raw, parse_constant=invalid_number)
            if check_schema and path.name in {'agent.json','examples.json'}:
                _shape(obj, _CATALOG if path.name == 'agent.json' else _EXAMPLES)
                # [수정: 0 이영] 2026-09-30 22:01 KST — 본선 VERSION=0(정수)도 공개 스냅샷 버전으로 허용.
                if obj['approved'] is not False or obj['schema_version'] != 1 or not re.fullmatch(r'\d+(?:\.\d+\.\d+)?', obj['version']):
                    raise ValueError('PUBLIC_SCOPE_INVALID')
            elif check_schema and path.name == 'openapi.json' and obj != _openapi(obj.get('info',{}).get('version')):
                raise ValueError('PUBLIC_API_CONTRACT_INVALID')
            # The public docs contain only constructed fields; no credential field is accepted.
            def inspect(value):
                if isinstance(value, dict):
                    if any(k.lower() in {'password','token','api_key','secret','actor','email','raw_output','runs'} for k in value):
                        raise ValueError('PRIVATE_PUBLIC_FIELD')
                    for child in value.values(): inspect(child)
                elif isinstance(value, list):
                    for child in value: inspect(child)
                elif isinstance(value, str) and value.startswith(('http://','https://')):
                    url = urlsplit(value)
                    # [수정: 0 이영 · Codex] 2026-10-01T03:24:13+09:00 — 검증한 현재 배포 호스트만 허용한다. 임의 호스트·인증 URL·쿼리·조각 차단은 유지한다.
                    if url.scheme != 'https' or url.hostname not in {'nais-evidence-gate-finals.streamlit.app','journal.r-project.org','creativecommons.org','raw.githubusercontent.com'} or url.username or url.password or url.query or url.fragment:
                        raise ValueError('UNSAFE_PUBLIC_URL')
            inspect(obj)
    if require_complete:
        catalog = json.loads((directory/'agent.json').read_bytes())
        examples = json.loads((directory/'examples.json').read_bytes())
        if catalog['examples_sha256'] != hashlib.sha256((directory/'examples.json').read_bytes()).hexdigest() or catalog['version'] != examples['version']:
            raise ValueError('PUBLIC_RELEASE_BINDING_MISMATCH')
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in entries}


# case105: release build only, with bounded whitelist and no environment/secret/runtime reads.
def build_public_files(directory=None, *, built_at=None):
    directory = Path(directory) if directory is not None else PROJECT_ROOT/'static'
    # Existing old-version files may have an older schema; they still must pass physical/privacy checks.
    validate_public_directory(directory, require_complete=False, check_schema=False)
    examples = public_examples()
    stamp = built_at or datetime.now(timezone.utc).isoformat()
    catalog = public_catalog(examples, stamp)
    api = _openapi(catalog['version'])
    text = f'''# NAIS Evidence Gate {catalog['version']}

Public research verification discovery files. No sign-in or key needed for these files.
- Catalog: {BASE_URL}{STATIC_PATH}agent.json
- Reproducible example results: {BASE_URL}{STATIC_PATH}examples.json
- GET contract: {BASE_URL}{STATIC_PATH}openapi.json

Read examples_sha256 in agent.json to verify examples.json bytes. Check version and built_at.
The example re-runs a fixed public penguin row-count and synthetic changes with an unaffected control.
SYNTHETIC_CHANGE is a deliberate test, not an observed error in a paper or another AI.
approved=false remains false. Arithmetic agreement is not full-paper approval.
These static files cannot accept questions or execute tools. For execution, install the project and
configure an MCP-capable local host to run python -m tools.research_mcp in the project directory.
Other modules and boundaries are in agent.json. They use stdio, not this website as a remote MCP URL.
Private tasks, team records, secrets and participant-level research responses are not published.
'''
    payloads = {'agent.json': encode_json(catalog), 'examples.json': encode_json(examples),
                'openapi.json': encode_json(api), 'llms.txt': text.encode('utf-8')}
    if any(len(value) > MAX_FILE_BYTES for value in payloads.values()):
        raise ValueError('PUBLIC_OUTPUT_TOO_LARGE')
    directory.parent.mkdir(parents=True, exist_ok=True)
    # Validate every byte before publication. A failed build leaves existing public files untouched.
    with TemporaryDirectory(dir=directory.parent, prefix='.public-build-') as temporary:
        staging = Path(temporary)
        for name, raw in payloads.items(): (staging/name).write_bytes(raw)
        validate_public_directory(staging)
        directory.mkdir(exist_ok=True)
        for name in sorted(PUBLIC_FILES): (staging/name).replace(directory/name)
    return validate_public_directory(directory)


def _validated_public_payloads(directory=None):
    """Read only release snapshots through the same whitelist, SHA and version boundary."""
    directory = Path(directory) if directory is not None else PROJECT_ROOT/'static'
    hashes = validate_public_directory(directory)
    payloads = {name: (directory/name).read_bytes() for name in sorted(PUBLIC_FILES)}
    if any(hashlib.sha256(raw).hexdigest() != hashes[name] for name, raw in payloads.items()):
        raise ValueError('PUBLIC_SNAPSHOT_CHANGED')
    version = (PROJECT_ROOT/'VERSION').read_text().strip()
    if json.loads(payloads['agent.json'])['version'] != version:
        raise ValueError('PUBLIC_RELEASE_VERSION_MISMATCH')
    return payloads


def public_download_zip(directory=None):
    """Package only validated release snapshots; never walk the project or read private state."""
    payloads = _validated_public_payloads(directory)
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, raw in payloads.items(): archive.writestr(name, raw)
    return output.getvalue()


def public_handoff_text(directory=None):
    """Copyable envelope preserves exact UTF-8 contents and per-file integrity evidence."""
    payloads = _validated_public_payloads(directory)
    return encode_json({
        'format': 'NAIS_PUBLIC_HANDOFF_V1',
        'delivery': 'MANUAL_COPY_OR_ATTACHMENT',
        'public_get_verified': False, 'remote_mcp_available': False,
        'version': json.loads(payloads['agent.json'])['version'],
        'instruction': 'Read only these four release snapshots. Verify each UTF-8 file against sha256. '
                       'Explain scope, unknown conditions and changed versus unaffected claims. '
                       'approved=false is not whole-paper approval. Listed URLs are not verified GET delivery.',
        'sha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()},
        'files': {name: raw.decode('utf-8') for name, raw in payloads.items()},
    }).decode('utf-8')


def render_public_delivery(*, key_prefix='public_delivery'):
    import streamlit as st
    st.warning('공개 웹 파일 주소는 배포 환경에서 실패가 확인됐으며, 현재 외부 AI가 읽을 수 있다고 보장하지 않습니다.')
    st.write('대신 공개 설명·예제 4개를 ZIP으로 내려받아, 파일 첨부를 지원하는 AI에 전달할 수 있습니다. 이 다운로드는 공개 GET 복구나 원격 MCP 연결을 뜻하지 않습니다.')
    try:
        payload = public_download_zip()
        handoff = public_handoff_text()
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        st.error('공개 파일 검증에 실패해 다운로드를 중단했습니다. 담당자가 릴리스 파일을 확인해야 합니다.')
    else:
        st.download_button('공개 설명·예제 4개 ZIP 내려받기', payload,
                           file_name='nais_public_snapshots.zip', mime='application/zip',
                           on_click='ignore', key=key_prefix+'_zip')
        with st.expander('다운로드가 막히면 · AI에 전달할 공개 텍스트 복사'):
            st.write('아래 코드의 복사 버튼으로 전체 내용을 복사해 다른 AI의 입력창에 붙여 넣으세요. 공개 4파일의 원문과 확인용 해시만 포함합니다.')
            st.caption('붙여 넣기 전달은 웹 주소 조회 성공이나 원격 MCP 실행이 아닙니다. AI가 지원 범위와 미확인 조건부터 설명하도록 요청하세요.')
            st.code(handoff, language='json', wrap_lines=True)
    with st.expander('공개 웹 주소 · 성공 여부 별도 확인 필요'):
        st.code(BASE_URL+STATIC_PATH+'agent.json', language=None)
        st.link_button('공개 설명 주소 확인', BASE_URL+STATIC_PATH+'llms.txt')
        st.link_button('공개 예제 주소 확인', BASE_URL+STATIC_PATH+'examples.json')
    with st.expander('공개 파일 제공 진단 · 비공개 설정 제외'):
        st.json({'enableStaticServing': st.get_option('server.enableStaticServing'),
                 'version': (PROJECT_ROOT/'VERSION').read_text().strip(),
                 'public_files': {name: (PROJECT_ROOT/'static'/name).is_file() for name in sorted(PUBLIC_FILES)}})


def render_public_agent():
    import streamlit as st
    st.header('다른 AI와 함께 근거를 확인하세요')
    render_public_delivery()
    st.info('예제는 공개 펭귄 자료의 행 수와 의도적으로 바꾼 입력을 검사합니다. 개인 과제는 공유되지 않습니다. 웹 파일 조회만으로 새 질문의 계산이 실행되지는 않습니다.')
    with st.expander('AI에 붙여 넣을 요청 예시'):
        # [수정: 0 이영 · Codex] 2026-10-01T03:22:27+09:00 — 외부 AI 요청문구의 번역투·띄어쓰기·어조를 바로잡는다. 하나의 외부 AI 요청문구 안에서 존댓말을 통일한다. 외부 AI 요청문구의 존댓말을 통일하고 기존 제한 의미를 보존한다.
        st.code('내려받은 ZIP의 공개 설명·예제 파일을 첨부합니다. 지원 범위와 미확인 조건을 먼저 설명해 주세요. 예제에서 입력이 바뀌면 어떤 주장을 다시 검산해야 하는지, 영향을 받지 않은 주장도 함께 알려 주세요. 논문 전체 승인으로 해석하지 마세요.', language=None)
    with st.expander('MCP로 직접 실행하려면'):
        st.write('프로젝트를 설치한 PC에서 MCP를 지원하는 AI 도구에 stdio 서버를 등록합니다. 작업 폴더는 압축을 푼 프로젝트입니다.')
        st.code('python -m tools.research_mcp', language='shell')
        st.caption('고정 등록 사례 재검산과 근거 검색용입니다. 공개 웹 주소는 원격 MCP 실행 서버가 아닙니다.')
