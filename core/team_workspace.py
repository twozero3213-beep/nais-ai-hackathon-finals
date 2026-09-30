"""Four-person workspace. Immutable updates; GitHub branch for cloud persistence."""
from __future__ import annotations
import base64
from collections import Counter
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from .models import Status
from .input_security import safe_csv_export_bytes, sensitive_content_kinds
from .rbac import Role, can
from tools.independent_replay import _load_json

MEMBERS=('이영','조지현','이채우','임도윤')
MAX_BYTES=5*1024*1024
MAX_RESPONSE_BYTES=10*1024*1024
ALLOWED={'.pdf','.csv','.txt','.log','.md','.json','.py','.toml','.yaml','.yml','.png','.jpg','.jpeg'}


# [작성: 전문가4] 2026-09-25 case39
# 무엇을: validate_upload / 왜: 팀 공유·접근 및 회귀 검증.
# 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
def validate_upload(name, data):
    if not name or Path(name).name!=name or '/' in name or '\\' in name:
        raise ValueError('파일명에 경로를 사용할 수 없습니다.')
    if Path(name).suffix.lower() not in ALLOWED or name.startswith('.') or 'secret' in name.lower():
        raise ValueError('이 파일 형식 또는 비밀 설정 파일은 올릴 수 없습니다.')
    if len(data)>MAX_BYTES:
        raise ValueError('파일당 최대 5 MiB입니다.')
    # [수정: 0 이영] 2026-10-01 03:11 KST — 파일명도 저장되는 메타데이터이므로 공유 전에 민감 형태를 검사한다. 바이너리 본문 DLP를 수행한다고 주장하지 않는다.
    if sensitive_content_kinds(name):
        raise ValueError('개인정보 또는 인증 값 형태가 포함되어 업로드를 차단했습니다.')
    if Path(name).suffix.lower() not in {'.pdf','.png','.jpg','.jpeg'}:
        # [수정: 0 이영] 2026-10-01 03:11 KST — BOM이 있는 UTF-16/32 텍스트도 실제 문자로 검사한다. 해독 불가 입력을 replacement로 숨겨 민감 검사에서 빠지게 하지 않는다.
        encoding = ('utf-32' if data.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff'))
                    else 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        try:
            text = data.decode(encoding, errors='strict')
        except UnicodeError:
            raise ValueError('텍스트 첨부는 UTF-8 또는 BOM이 있는 UTF-16/32 형식이어야 합니다.') from None
        if sensitive_content_kinds(text):
            raise ValueError('개인정보 또는 인증 값 형태가 포함되어 업로드를 차단했습니다.')
    return name


# [작성: 전문가4] 2026-09-25 case39
# 무엇을: password_hash / 왜: 팀 공유·접근 및 회귀 검증.
# 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
def password_hash(password, salt=None):
    salt=salt or os.urandom(16).hex()
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
    return f'pbkdf2_sha256${salt}${digest}'


# [작성: 전문가4] 2026-09-25 case39
# 무엇을: verify_password / 왜: 팀 공유·접근 및 회귀 검증.
# 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
def verify_password(password, stored):
    try:
        scheme,salt,_=stored.split('$')
        return scheme=='pbkdf2_sha256' and hmac.compare_digest(password_hash(password,salt),stored)
    except (ValueError,TypeError):
        return False


# [작성: 전문가4] 2026-09-25 case46
# 무엇을: identity_assurance_label / 왜: 과거·현재 공유 기록의 선택 이름을 검증된 신원으로 오인하지 않게 함 / 입력·출력: 공유 record -> 표시 문구 / 검증: tests/test_case46.py의 새·과거 레코드.
def identity_assurance_label(record):
    name=record.get('claimed_by') or record.get('verified_by') or '이름 없음'
    return name+' · '+('신원 확인됨' if record.get('identity_verified') is True else '본인 확인 안 됨')


# [작성/수정: 전문가4] 2026-09-26 case65
# 무엇을·왜: 저장매체의 손상 기록을 다운로드·수정본 상속 전에 공통 검사한다.
# 재사용: _load_json·validate_upload와 표준 base64/SHA-256. 입력·출력: payload·요청 ID -> 원기록/ValueError.
# 검증: tests/test_case65_workspace.py의 로컬·원격 무결성 및 과거기록 호환 시험.
def _read_workspace_record(payload, item_id):
    try:
        if isinstance(payload, bytes): payload = payload.decode('utf-8-sig')
        if not isinstance(payload, str) or len(payload.encode('utf-8')) > 7*1024*1024:
            raise ValueError('기록 크기 또는 형식 오류')
        record = _load_json(payload)
        # save와 동일한 직렬화 조건으로 1e309 등의 overflow·잘못된 Unicode도 거부한다.
        json.dumps(record, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if not isinstance(record, dict) or record.get('id') != item_id:
            raise ValueError('기록 ID 불일치')
        if any(not isinstance(record.get(key), str) for key in ('at', 'title', 'status', 'note', 'verified_by')):
            raise ValueError('필수 기록 필드 오류')
        if record['status'] not in ('예정', '진행 중', '검토 요청', '완료', '차단'):
            raise ValueError('진행 상태 오류')
        if 'claimed_by' in record and not isinstance(record['claimed_by'], str):
            raise ValueError('표시 이름 형식 오류')
        if type(record.get('version', 1)) is not int or record.get('version', 1) < 1:
            raise ValueError('판 번호 오류')
        previous = record.get('supersedes')
        if previous is not None and previous != '' and (not isinstance(previous, str) or not re.fullmatch(r'[a-f0-9]{32}', previous)):
            raise ValueError('이전 기록 ID 오류')
        files = record.get('files')
        if not isinstance(files, list) or len(files) > 5:
            raise ValueError('첨부 목록 오류')
        for attachment in files:
            if not isinstance(attachment, dict) or any(not isinstance(attachment.get(key), str) for key in ('name', 'data', 'sha256')):
                raise ValueError('첨부 필드 오류')
            data = base64.b64decode(attachment['data'], validate=True)
            validate_upload(attachment['name'], data)
            if type(attachment.get('size')) is not int or attachment['size'] != len(data):
                raise ValueError('첨부 크기 불일치')
            if attachment['sha256'].lower() != hashlib.sha256(data).hexdigest():
                raise ValueError('첨부 해시 불일치')
        return record
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError('저장 기록 또는 첨부파일의 형식·무결성이 올바르지 않습니다.') from None


# [작성: 운영·UX 담당] 2026-09-29 case89
# 무엇을: 동일 폼 재시도 키 유지 / 왜: 응답유실 뒤 중복기록 방지 / 입력·출력: 세션·폼→임의요청ID / 검증: test_case89_operations, 내용변경새키.
def submission_key(state, payload):
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()
    attempt=state.get('team_pending_request',{})
    if attempt.get('fingerprint')!=fingerprint:
        attempt={'fingerprint':fingerprint,'id':uuid.uuid4().hex}
        state['team_pending_request']=attempt
    return attempt['id']


# [작성: 운영·보안 담당] 2026-09-29 case89
# 무엇을: 재시도 원문 대조 / 왜: 다른 내용/사람을 같은 요청으로 합치지 않음 / 입력·출력: 기존·새기록→동일ID 또는 거부 / 검증: key충돌·권한시험.
def _confirmed_submission(existing, proposed):
    left={k:v for k,v in existing.items() if k not in {'at','id'}}
    right={k:v for k,v in proposed.items() if k not in {'at','id'}}
    if json.dumps(left,sort_keys=True,ensure_ascii=False,allow_nan=False)!=json.dumps(right,sort_keys=True,ensure_ascii=False,allow_nan=False):
        raise ValueError('같은 요청 ID에 다른 내용이 있습니다. 기존 기록을 확인하고 새 요청으로 저장하세요.')
    return existing['id']


class Workspace:
    # [작성: 전문가4] 2026-09-25 case39
    # 무엇을: __init__ / 왜: 팀 공유·접근 및 회귀 검증.
    # 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
    def __init__(self, directory=None, *, repo='', token='', branch='team-data'):
        self.repo=repo;self.token=token;self.branch=branch
        self.directory=Path(directory or os.environ.get('EVIDENCE_GATE_TEAM_DIR',Path(__file__).resolve().parents[1]/'team_data'))
        if bool(repo)!=bool(token):raise ValueError('공용 저장소와 토큰을 함께 설정해야 합니다.')
        if repo and (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo) or branch=='main'):
            raise ValueError('유효한 비공개 저장소와 코드 배포와 분리된 데이터 브랜치가 필요합니다.')
        self.remote=bool(repo)
        if not self.remote:
            with self._local_connection() as con:
                con.execute('CREATE TABLE IF NOT EXISTS updates(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    # [작성: 보안·협업운영] 2026-09-28 case88 무엇: 로컬 연결·트랜잭션 공통 경계/왜: 오류복구·개인경로 노출 방지/입출력: 저장설정→연결 또는 RuntimeError/검증: test_case88_operations.
    @contextmanager
    def _local_connection(self):
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(self.directory/'workspace.db')) as con:
                with con: yield con
        except (sqlite3.Error, OSError):
            raise RuntimeError('로컬 저장소를 읽거나 저장하지 못했습니다. 초안을 유지하고 최신 목록을 확인하세요. 운영자는 저장 위치의 쓰기 권한·여유 공간·DB 잠금/손상을 확인하고 원본을 보존하세요.') from None

    # [작성: 전문가4] 2026-09-25 case39
    # 무엇을: _request / 왜: 팀 공유·접근 및 회귀 검증.
    # 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
    def _request(self, method, path='', payload=None):
        url=f'https://api.github.com/repos/{self.repo}/contents/team_updates'
        if path:url+='/'+urllib.parse.quote(path,safe='')
        if method=='GET':url+='?ref='+urllib.parse.quote(self.branch,safe='')
        req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,method=method,
            headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'})
        try:
            # [수정: 운영·보안 담당] 2026-09-29 case89 / 종류: 오류수정 / 재현: 과대·중복키응답 / 전후: 무제한json.load→크기제한·기존엄격파서 / 영향: 손상응답차단.
            with urllib.request.urlopen(req,timeout=30) as response: raw=response.read(MAX_RESPONSE_BYTES+1)
            if len(raw)>MAX_RESPONSE_BYTES: raise ValueError('응답 크기 초과')
            return _load_json(raw)
        except urllib.error.HTTPError as exc:
            # [수정: 보안·협업운영] 2026-09-28 case88 실제 설정의 브랜치명을 단정하지 않고 HTTP 오류 복구 위치 안내; 키·저장소 원문은 표시하지 않음.
            raise RuntimeError(f'공용 저장소 요청 실패 HTTP {exc.code}. 초안을 유지하고 운영자에게 저장소·설정한 데이터 브랜치·토큰 읽기/쓰기 권한을 확인하도록 요청하세요.') from None
        # [수정: 보안·협업운영] 2026-09-28 case88 응답 손상·전송 오류·HTTP 읽기 중단도 UI 안내로 처리; PUT 응답 유실은 서버 저장 여부 미확정이므로 재시도 전 최신 목록 확인.
        # [수정: 보안 교차검토] 2026-09-29 case89 / 오류수정: 10KB 깊은JSON 예외누출→응답실패 / 왜: 화면 복구 경계 / 검증: deep_json 반례.
        except (OSError, ValueError, HTTPException, RecursionError):
            raise RuntimeError('공용 저장소 연결 또는 응답 확인에 실패했습니다. 저장 완료로 처리하지 않았습니다. 서버 저장 여부는 미확정입니다. 초안을 유지하고 최신 목록에서 같은 내용이 저장됐는지 확인한 뒤 재시도하세요.') from None

    # [작성: 전문가4] 2026-09-25 case39
    # 무엇을: save / 왜: 팀 공유·접근 및 회귀 검증.
    # 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
    # [수정: 전문가4] 2026-09-25 case42
    # 종류: 검증방법추가 / 재현 방법: 기존 기록 수정 불가 / 변경 전: 새 기록만 가능 / 변경 후: 이전 기록을 보존한 수정본 연결 / 왜: 팀원 공동 수정과 감사 추적 / 영향: 새 레코드에 supersedes·version 추가.
    # [수정: 운영·보안 담당] 2026-09-29 case89 / 종류: 오류수정 / 재현: PUT성공뒤응답유실재시도 / 전후: 매번새ID→명시요청ID확인 / 영향: 기존호출유지·같은내용만중복방지.
    def save(self, actor, title, status, note='', files=(), snapshot=None, supersedes=None, *, request_id=None):
        if actor not in MEMBERS:raise ValueError('등록된 팀원만 저장할 수 있습니다.')
        # [수정: 협업 시험 엔지니어] 2026-09-28 case85: UI 우회 직접 호출도 VIEWER/정의되지 않은 역할 저장 차단; 기존 제안/검토 권한 재사용.
        role=member_role(actor)
        if role not in Role.__members__ or not (can(role,'propose') or can(role,'review')):
            raise ValueError('현재 팀원 역할은 저장 권한이 없습니다.')
        if not title.strip() or len(title)>120:raise ValueError('제목은 1~120자여야 합니다.')
        if status not in {'예정','진행 중','검토 요청','완료','차단'}:raise ValueError('지원하지 않는 진행 상태입니다.')
        if len(note)>10000:raise ValueError('진행 메모는 10,000자까지 저장할 수 있습니다.')
        # [수정: 0 이영] 2026-10-01 03:11 KST — 확인 체크박스/UI를 우회해도 title/note/snapshot을 로컬 DB·GitHub에 저장하기 전에 공통 민감 검사를 강제한다. 원입력·기존 기록은 바꾸지 않는다.
        if sensitive_content_kinds({'title': title, 'note': note, 'snapshot': snapshot}):
            raise ValueError('개인정보 또는 인증 값 형태가 포함되어 팀 기록 저장을 차단했습니다.')
        if request_id is not None and (not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id)):
            raise ValueError('유효한 요청 ID가 필요합니다.')
        previous=None
        if supersedes:
            try:previous=self.get(supersedes)
            except (ValueError,RuntimeError) as exc:raise ValueError('수정할 기록을 찾지 못했습니다.') from exc
        uploads=list(previous['files']) if previous else []
        if len(uploads)+len(files)>5:raise ValueError('기존 첨부를 포함해 파일 5개까지 올릴 수 있습니다.')
        for name,data in files:
            validate_upload(name,data)
            uploads.append({'name':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(data).decode()})
        # [수정: 전문가4] 2026-09-25 case46
        # 종류: 오류수정 / 재현 방법: 공용 암호로 다른 이름을 선택해 저장해도 verified_by만 있어 인증된 신원처럼 보임 / 변경 전: 이름만 저장 / 변경 후: legacy 이름을 보존하며 claimed_by·identity_verified=false·인증방식 명시 / 왜: 감사 증거의 강도를 정직하게 표시 / 영향: 실제 신원 증명은 향후 별도 인증 필요.
        record={'id':request_id or uuid.uuid4().hex,'at':datetime.now(timezone.utc).isoformat(),'verified_by':actor,'claimed_by':actor,'identity_verified':False,'auth_method':'selected_name_password',
                'title':title.strip(),'status':status,'note':note,'files':uploads,
                # [수정: 전문가4] 2026-09-25 case49
                # 종류: 오류수정 / 재현 방법: 수정본 저장 시 검증 기록 체크 해제해도 이전 snapshot이 계승 / 변경 전: None이면 이전 판 복사 / 변경 후: 명시한 snapshot만 새 판에 저장 / 왜: 최신 메모와 오래된 증거의 혼동 방지 / 영향: 이전 판 원본은 계속 열람 가능.
                'snapshot':snapshot,
                'supersedes':supersedes,'version':(previous or {}).get('version',1)+1 if previous else 1}
        encoded=json.dumps(record,ensure_ascii=False,allow_nan=False)
        if len(encoded.encode())>7*1024*1024:raise ValueError('한 번에 저장하는 전체 자료는 7 MiB 이하로 줄여 주세요.')
        if self.remote:
            try:
                # No sha: conditional creation; an existing record must never be overwritten.
                self._request('PUT',record['id']+'.json',{'message':f'team: {actor} {status}',
                    'branch':self.branch,'content':base64.b64encode(encoded.encode()).decode()})
            except RuntimeError as error:
                if request_id is None: raise
                try: existing=self.get(record['id'])
                except (ValueError,RuntimeError): raise error from None
                return _confirmed_submission(existing,record)
        else:
            with self._local_connection() as con:
                if request_id is None:
                    con.execute('INSERT INTO updates VALUES(?,?)',(record['id'],encoded))
                else:
                    con.execute('INSERT OR IGNORE INTO updates VALUES(?,?)',(record['id'],encoded))
                    stored=con.execute('SELECT payload FROM updates WHERE id=?',(record['id'],)).fetchone()[0]
                    return _confirmed_submission(_read_workspace_record(stored,record['id']),record)
        return record['id']

    # [작성: 전문가4] 2026-09-25 case39
    # 무엇을: list / 왜: 팀 공유·접근 및 회귀 검증.
    # 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
    # [작성/수정: 전문가4] 2026-09-26 case65
    # 무엇을·왜: 손상된 원격 목록 항목을 UI 처리 가능한 오류로 반환한다.
    # 재사용: 기존 목록 필터 / 입력·출력: 저장소 -> ID 목록/RuntimeError / 검증: malformed_remote_listing AppTest.
    def list(self):
        if self.remote:
            items=self._request('GET')
            if not isinstance(items,list) or any(not isinstance(item,dict) or not isinstance(item.get('name'),str) for item in items):
                raise RuntimeError('공용 저장소 목록 형식이 올바르지 않습니다.')
            if len(items)>=1000:raise RuntimeError('저장 기록이 1,000개에 도달했습니다. 별도 보관이 필요합니다.')
            return [x['name'][:-5] for x in items if re.fullmatch(r'[a-f0-9]{32}\.json',x['name'])]
        with self._local_connection() as con:
            return [r[0] for r in con.execute('SELECT id FROM updates ORDER BY rowid DESC')]

    # [작성: 전문가4] 2026-09-25 case39
    # 무엇을: get / 왜: 팀 공유·접근 및 회귀 검증.
    # 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
    # [작성/수정: 전문가4] 2026-09-26 case65
    # 무엇을·왜: 로컬·원격 반환을 공통 무결성 검사로 모아 손상 자료 상속을 차단한다.
    # 재사용: _read_workspace_record / 입력·출력: ID -> 검증한 기록 / 검증: test_case65_workspace의 세 읽기 경로.
    def get(self, item_id):
        if not isinstance(item_id, str) or not re.fullmatch(r'[a-f0-9]{32}', item_id):
            raise ValueError('유효하지 않은 기록 ID입니다.')
        if self.remote:
            item = self._request('GET', item_id+'.json')
            if not isinstance(item, dict): raise ValueError('공용 기록 응답 형식이 올바르지 않습니다.')
            if item.get('encoding') == 'base64':
                content = item.get('content')
                if not isinstance(content, str): raise ValueError('공용 기록 인코딩이 올바르지 않습니다.')
                try:
                    payload = base64.b64decode(re.sub(r'[\r\n\t ]', '', content), validate=True)
                except ValueError:
                    raise ValueError('공용 기록 인코딩이 올바르지 않습니다.') from None
            else:
                # GitHub Contents returns no base64 above 1 MB. Read via authenticated raw API.
                url=f'https://api.github.com/repos/{self.repo}/contents/team_updates/{item_id}.json?ref={urllib.parse.quote(self.branch,safe="")}'
                req=urllib.request.Request(url,headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github.raw+json'})
                try:
                    with urllib.request.urlopen(req,timeout=30) as response: payload=response.read(7*1024*1024+1)
                # [수정: 보안·협업운영] 2026-09-28 case88 raw 응답 읽기 중 IO·HTTP 중단 오류도 조회 복구 안내로 처리.
                except (OSError,HTTPException):raise RuntimeError('공용 첨부파일을 읽지 못했습니다. 원본을 바꾸지 말고 연결·접근권한을 확인한 뒤 다시 조회하세요.') from None
        else:
            with self._local_connection() as con:
                row=con.execute('SELECT payload FROM updates WHERE id=?',(item_id,)).fetchone()
            if not row:raise ValueError('기록을 찾지 못했습니다.')
            payload = row[0]
        return _read_workspace_record(payload, item_id)



# [작성: 전문가4] 2026-09-25 case39
# 무엇을: make_snapshot / 왜: 팀 공유·접근 및 회귀 검증.
# 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
# [작성/수정: 전문가4] 2026-09-26 case64
# 무엇을·왜: 원자료 부재로 승인을 취소할 때 정정안의 승인 표시도 함께 해제한다.
# 입력·출력: 세션 상태 -> 공유 스냅샷 / 검증: tests/test_case64_audit.py, 원문 판정은 보존.
# [수정: 전문가8·10·16] 2026-09-28 case81: 팀 화면 조기 종료로 화면 갱신을 건너뛰어도 공유 직전 실제 원장의 승인/취소 효력 확인; 순수 Ledger stub 호환.
def make_snapshot(state):
    claims=state.get('claims',[])
    if not claims:return None
    from .verifier import auto_verify, refresh_reported_status
    ledger=state['audit_store'];dataset=state['dataset_hash']
    if state.get('df') is not None:
        # [수정: 전문가4] 2026-09-25 case43
        # 종류: 오류수정 / 재현 방법: 추론 원문 판정 후 공유 저장 시 REVIEW로 덮임 / 변경 전: 모든 Claim에 기술통계 검증 함수 호출 / 변경 후: 기술통계만 갱신 / 왜: 추론 판정 보존 / 영향: 추론 결과는 앱 판정을 저장.
        for claim in claims:
            # [수정: 전문가8] 2026-09-25 case59
            # 종류: 오류수정 | 재현 방법: 승인 뒤 같은 표로 읽히는 다른 CSV를 팀에 저장 / 변경 전: VALIDATED 직렬화 유지 / 변경 후: 원자료 바이트·승인 서명을 공유 직전 재검사 / 왜: 낡은 승인을 팀 증거로 남기지 않기 위해 / 영향: 불일치·원자료 부재 시 재승인 필요.
            if claim.status == Status.VALIDATED:
                if callable(getattr(ledger,'approval_state',None)):
                    from .workflow import refresh_audited_approval
                    refresh_audited_approval(claim,state['df'],audit_store=ledger,dataset_hash=dataset,csv_bytes=state.get('csv_bytes'))
                else:
                    auto_verify(claim,state['df'],csv_bytes=state.get('csv_bytes'))
                continue
            method=claim.analysis_method or claim.aggregation
            if method in {'count','mean','median','sum','min','max','proportion','weighted_mean','std','variance','row_count','missing_cells'}:
                refresh_reported_status(claim,state['df'])
    else:
        for claim in claims:
            if claim.status == Status.VALIDATED:
                claim.status=Status.REVIEW
                claim.reason='원자료가 없어 공유 시 승인을 재확인할 수 없습니다.'
                if claim.revision_count:
                    claim.amendment_status=Status.REVIEW
                    claim.amendment_reason=claim.reason
    return {'schema':1,'dataset_name':state['dataset_name'],'dataset_hash':dataset,
            'claims':[asdict(c) for c in claims],
            'audit':[r for c in claims for r in ledger.for_claim(c.claim_id,dataset_hash=dataset)],
            'executions':[r for c in claims for r in ledger.attempts_for_claim(c.claim_id,dataset_hash=dataset)]}


# [작성: 전문가4] 2026-09-25 case39
# 무엇을: settings / 왜: 팀 공유·접근 및 회귀 검증.
# 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
def settings():
    import streamlit as st
    config={}
    try:config=dict(st.secrets.get('team',{}))
    except FileNotFoundError:pass
    config['repo']=os.environ.get('EVIDENCE_GATE_GITHUB_REPO',config.get('repo',''))
    config['token']=os.environ.get('EVIDENCE_GATE_GITHUB_TOKEN',config.get('token',''))
    return config


# [작성: 전문가4] 2026-09-25 case39
# 무엇을: require_member / 왜: 팀 공유·접근 및 회귀 검증.
# 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
def member_role(member):
    """Return configured RBAC role; production defaults to REVIEWER (no final approval)."""
    if os.environ.get('EVIDENCE_GATE_LOCAL_MODE')=='1':
        return os.environ.get('EVIDENCE_GATE_LOCAL_ROLE','ADMIN').upper()
    config=settings(); roles=config.get('roles',{})
    return str(roles.get(member,'REVIEWER')).upper()


def require_member():
    import streamlit as st
    if os.environ.get('EVIDENCE_GATE_LOCAL_MODE')=='1':
        st.sidebar.caption('로컬 시험 모드 · 외부 공유 금지')
        return st.sidebar.selectbox('검토자',MEMBERS,key='local_member')
    config=settings();hashes=config.get('password_hashes',{})
    if set(hashes)!=set(MEMBERS):
        st.error('팀원 4명의 접근 설정이 필요합니다. README의 팀 배포 설정을 완료해 주세요.')
        st.stop()
    if st.session_state.get('authenticated_member') not in MEMBERS:
        # [수정: 0 이영] 2026-09-30 22:52 KST — 팀 접속 화면의 제목 오기를 로그인으로 바로잡습니다. 인증·권한 로직은 유지합니다.
        st.title('근거관문 · 팀 로그인')
        with st.form('team_login'):
            who=st.selectbox('팀원',MEMBERS)
            password=st.text_input('개인 접속 비밀번호',type='password')
            if st.form_submit_button('로그인'):
                if verify_password(password,hashes[who]):
                    st.session_state.authenticated_member=who;st.rerun()
                else:st.error('이름 또는 비밀번호를 확인하세요.')
        st.stop()
    who=st.session_state.authenticated_member
    # [수정: 전문가2] 2026-09-25 case46
    # 종류: 오류수정 / 재현 방법: 동일 암호가 네 이름에 모두 로그인되는데 화면은 개인 검토자로 표시 / 변경 전: 검토자 이름만 노출 / 변경 후: 선택 이름과 본인 확인 미완료를 함께 표시 / 왜: 서명·승인 증거 과장 방지 / 영향: 기존 접근은 유지.
    st.sidebar.caption('선택한 검토자: '+who+' · 본인 확인 안 됨')
    if st.sidebar.button('로그아웃'):
        st.session_state.clear();st.rerun()
    return who


# [작성: 전문가4] 2026-09-25 case39
# 무엇을: render_workspace / 왜: 팀 공유·접근 및 회귀 검증.
# 입력·출력: 함수 인자와 반환값 / 검증: tests/test_case39.py.
# [작성/수정: 전문가4] 2026-09-26 case65
# 무엇을·왜: 과거 snapshot 누락값은 미기록으로 표시하고 손상된 표만 생략해 작업실 조회를 유지한다.
# 재사용: 기존 저장기록·Streamlit 표시 / 입력·출력: actor -> 화면 / 검증: test_case65_workspace AppTest.
# [수정: 전문가9·15·16] 2026-09-28 case81: 원본 첨부는 유지하고 별도 CSV 안전 보기만 제공; 변환 오류는 해당 파일 안내로 격리.
def render_workspace(actor):
    import streamlit as st
    config=settings()
    st.title('팀 공동 작업실')
    st.caption('이영 · 조지현 · 이채우 · 임도윤 | 저장한 진행상황·자료·검증 기록을 함께 확인합니다.')
    # [수정: 보안·협업운영] 2026-09-28 case88 무엇: 조회 역할과 설정별 운영범위/왜: 미검증 비공개·영구보존 단정 방지/입출력: actor·실제 설정→안내/검증: test_case88_operations AppTest.
    role=member_role(actor) if actor in MEMBERS else ''
    if role not in Role.__members__ or not can(role,'read'):
        st.error('현재 팀원 역할은 조회 권한이 없습니다. 운영자에게 팀원·역할 설정 확인을 요청하세요.');return
    try:store=Workspace(repo=config.get('repo',''),token=config.get('token',''),branch=config.get('branch','team-data'))
    except (ValueError,RuntimeError) as exc:st.error(str(exc));return
    if store.remote:
        st.caption('현재 설정: 원격 GitHub API 저장 · 코드 배포와 분리된 데이터 브랜치. 비공개 여부·실제 접근권한·배포 적용은 이 화면에서 검증하지 않았습니다.')
    else:
        st.warning('현재 설정: 이 앱 서버의 로컬 SQLite 저장(workspace.db). 팀 저장 기능에서 외부 API로 전송하지 않습니다. 클라우드 서버에서는 재시작·재배포 때 유지되지 않을 수 있습니다.')
    st.info('저장 범위: 선택 이름·시간·제목·상태·메모, 첨부 원본 전체(인코딩은 암호화가 아님), 선택 시 Claim·자료명/지문·감사·실행 기록. 원자료는 직접 첨부한 경우 포함됩니다. 브라우저에서 앱 서버로 제출되며, 원격 설정이면 위 내용이 GitHub로 추가 전송됩니다.')
    st.caption('보존/삭제: 자동 만료·삭제 기능이 없습니다. 수정 전 기록과 첨부는 계속 남습니다. 스냅샷 체크 해제는 새 판만 제외하며 과거 판을 삭제하지 않습니다. 운영자 삭제도 다운로드 사본·Git 이력·백업까지 삭제함을 보장하지 않습니다.')
    writable=can(role,'propose') or can(role,'review')
    st.caption(f"현재 역할: {role} · 조회/다운로드 가능 · 저장 {'가능' if writable else '불가'}. 이름+비밀번호 접근은 실제 사람 신원 증명이 아닙니다. 서버 파일/저장소 접근권한은 운영자가 별도로 관리해야 합니다.")
    st.info('코드·로그는 첨부파일로 공유합니다. 업로드한 코드는 자동 실행되지 않습니다. 실행 앱 갱신은 검토 후 GitHub main 브랜치에 반영하세요.')
    edit_id=st.session_state.get('team_edit_id')
    try:editing=store.get(edit_id) if edit_id else None
    except (ValueError,RuntimeError) as exc:st.error(str(exc));st.session_state.pop('team_edit_id',None);editing=None
    if editing:
        st.info(f"{editing['title']} · {editing.get('version',1)}판을 수정 중입니다. 원본은 남고 새 판이 저장됩니다.")
        if st.button('수정 취소'):
            st.session_state.pop('team_edit_id',None);st.rerun()
    saved_notice=st.session_state.pop('team_saved_notice',None)
    if saved_notice:st.success(saved_notice)
    form_key=f"team_{edit_id or 'new'}_{st.session_state.get('team_form_generation',0)}"
    # [수정: 전문가2] 2026-09-25 case47
    # 종류: 오류수정 / 재현 방법: 확인 누락·저장 실패에도 제출 직후 제목·메모·첨부가 초기화 / 변경 전: 모든 제출에서 폼 초기화 / 변경 후: 거부된 초안 유지, 성공 때만 새 폼 키로 초기화 / 왜: 팀 자료 손실·중복 제출 방지 / 영향: 성공 후 새 빈 기록.
    with st.form('team_update',clear_on_submit=False):
        title=st.text_input('작업 제목',value=editing['title'] if editing else '',max_chars=120,key=form_key+'_title')
        statuses=['예정','진행 중','검토 요청','완료','차단']
        status=st.selectbox('진행 상태',statuses,index=statuses.index(editing['status']) if editing else 0,key=form_key+'_status')
        note=st.text_area('진행 내용 · 검토 요청',value=editing['note'] if editing else '',max_chars=10000,key=form_key+'_note')
        files=st.file_uploader('공유할 코드·로그·자료',type=[x[1:] for x in sorted(ALLOWED)],accept_multiple_files=True,key=form_key+'_files')
        if editing:st.caption(f"기존 첨부 {len(editing['files'])}개는 유지됩니다. 새 첨부를 추가할 수 있습니다.")
        # [수정: 전문가2] 2026-09-25 case49
        # 종류: 오류수정 / 재현 방법: 기존 snapshot이 있는 기록을 새 세션에서 수정하면 보관 체크가 꺼져 있음 / 변경 전: 현재 세션 Claim만 확인 / 변경 후: 수정 중인 판의 snapshot도 기본 보관 대상으로 표시 / 왜: 메모 수정만 해도 기록이 뜻밖에 빠지는 일 방지 / 영향: 체크를 직접 끄면 새 판에서는 제외.
        include=st.checkbox('현재 Claim과 감사·실행 기록을 함께 보관',value=bool(st.session_state.get('claims')) or bool(editing and editing.get('snapshot')),key=form_key+'_include')
        safe=st.checkbox('첨부파일·메모에 API 키나 비밀번호가 없음을 확인했습니다',key=form_key+'_safe')
        if st.form_submit_button('수정본 저장' if editing else '팀에 저장'):
            if not safe:st.error('비밀정보 포함 여부를 확인해 주세요.')
            else:
                try:
                    snapshot=(make_snapshot(st.session_state) or (editing or {}).get('snapshot')) if include else None
                    # [수정: 운영·UX 담당] 2026-09-29 case89 / 종류: 오류수정 / 재현: 실패재시도중복 / 전후: 무조건새저장→폼내용결속요청키 / 영향: 실패초안보존·성공뒤새요청.
                    uploads=[(f.name,f.getvalue()) for f in files]
                    request_id=submission_key(st.session_state,{'actor':actor,'title':title,'status':status,'note':note,'files':[(name,hashlib.sha256(raw).hexdigest()) for name,raw in uploads],'snapshot':snapshot,'supersedes':edit_id if editing else None,'form':form_key})
                    store.save(actor,title,status,note,uploads,snapshot,supersedes=edit_id if editing else None,request_id=request_id)
                    st.session_state.pop('team_pending_request',None)
                    st.session_state.pop('team_edit_id',None)
                    st.session_state.team_form_generation=st.session_state.get('team_form_generation',0)+1
                    st.session_state.team_saved_notice='수정본을 팀에 저장했습니다.' if editing else '팀에 저장했습니다. 다른 팀원은 새로고침하면 확인할 수 있습니다.'
                    st.rerun()
                except (ValueError,RuntimeError) as exc:st.error(str(exc))
    st.button('최신 진행상황 새로고침')
    try:
        ids=store.list()
        # Small-team pilot: load once per page render; no cache hides newer writes.
        records=sorted((store.get(i) for i in ids),key=lambda r:r['at'],reverse=True)
    except (RuntimeError,ValueError) as exc:st.error(str(exc));return
    if not records:st.info('아직 공유한 기록이 없습니다.')
    superseded={r.get('supersedes') for r in records if r.get('supersedes')}
    # [수정: 협업 시험 엔지니어] 2026-09-28 case85: 불변 원본의 복수 수정본은 모두 보존하고 분기 충돌을 안내한다.
    branches=Counter(r['supersedes'] for r in records if r.get('supersedes'))
    titles={r['id']:r['title'] for r in records}
    for parent,count in branches.items():
        if count>1:
            st.warning(f"동시 수정: {titles.get(parent,parent)}의 수정본 {count}개가 같은 원본에서 갈라졌습니다. 각 수정본을 비교하고 합의한 기록을 새로 저장하세요. 모든 원본·첨부는 보존됩니다.")
    for record in records:
        label=f"{record['status']} · {record['title']} · {identity_assurance_label(record)} · {record.get('version',1)}판"
        if record['id'] in superseded:label+=' · 수정 전 기록'
        with st.expander(label):
            st.text(record['note'])
            if st.button('이 기록 수정',key='edit_'+record['id']):
                st.session_state.team_edit_id=record['id'];st.rerun()
            # [수정: 전문가4] 2026-09-25 case47
            # 종류: 오류수정 / 재현 방법: 같은 이름·내용 첨부 두 개에서 위젯 키 충돌로 작업실 전체 중단 / 변경 전: 파일 해시·이름만 키에 사용 / 변경 후: 레코드 안 순번 사용 / 왜: 과거 중복 기록도 열람·다운로드 / 영향: 첨부 내용과 저장 데이터는 불변.
            for index,f in enumerate(record['files']):
                original=base64.b64decode(f['data'])
                st.download_button(f['name'],original,file_name=f['name'],key=f"file_{record['id']}_{index}")
                if Path(f['name']).suffix.lower()=='.csv':
                    try:
                        safe=safe_csv_export_bytes(original)
                        st.download_button(f"{f['name']} · 스프레드시트 안전 보기",safe,file_name=Path(f['name']).stem+'_spreadsheet_view.csv',mime='text/csv',key=f"safe_file_{record['id']}_{index}")
                        st.caption('안전 보기는 수식 접두 셀에 작은따옴표를 붙인 사본입니다. 재현에는 원본 첨부를 사용하세요. 원본 CSV를 스프레드시트로 열면 수식이 실행될 수 있습니다.')
                    except ValueError as exc:
                        st.warning(f"{f['name']}: 스프레드시트 안전 보기 생성 불가: {exc}")
            snap=record.get('snapshot')
            if snap:
                valid = isinstance(snap, dict) and all(isinstance(snap.get(key, []), list) and all(isinstance(row, dict) for row in snap.get(key, [])) for key in ('claims', 'audit', 'executions'))
                if valid:
                    valid = all(c.get('evidence_provenance') is None or isinstance(c['evidence_provenance'], dict) for c in snap.get('claims', []))
                if not valid:
                    st.warning('검증 기록 형식이 올바르지 않아 이 기록의 표를 표시하지 않았습니다.')
                else:
                    st.dataframe([{'claim':c.get('claim_id','미기록'),'주장':c.get('text','미기록'),'원문 판정':c.get('reported_status','미기록'),'정정안 판정':c.get('amendment_status','미기록'),'원문 보고값':c.get('original_value','미기록'),'정정값':c.get('current_value','미기록') if c.get('revision_count') else None,'확인자':(c.get('evidence_provenance') or {}).get('confirmed_by','미기록')} for c in snap.get('claims',[])],hide_index=True)
                    audit_count = len(snap['audit']) if 'audit' in snap else '미기록'
                    execution_count = len(snap['executions']) if 'executions' in snap else '미기록'
                    st.caption(f"감사 사건 {audit_count}건 · 실행 시도 {execution_count}건 · 원자료 {snap.get('dataset_name','미기록')}")
                from core.activity_privacy import activity_view
                st.download_button('검증 기록 JSON 받기',json.dumps({'view':'activity_times_removed_not_original_ledger','snapshot':activity_view(snap)},ensure_ascii=False,indent=2),file_name=record['id']+'_verification.json',key='snapshot_'+record['id'])
