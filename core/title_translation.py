"""case95 offline English→Korean title drafts, with verified public model bootstrap."""
from collections import Counter
from functools import lru_cache
import hashlib
import http.client
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import zipfile

from core.research_tasks import SECRET_PATTERN

MODEL_URL = 'https://data.argosopentech.com/argospm/v1/translate-en_ko-1_1.argosmodel'
MODEL_SHA256 = 'e03d8e65e6d44525ec5808c3409fcf8728c76c2c76925372b6d3dc3278de17fc'
MAX_BYTES = 180 * 1024 * 1024
FILES = ('model/model.bin', 'model/shared_vocabulary.txt', 'sentencepiece.model')
LOCK = threading.Lock()
BOOTSTRAP_LOCK = threading.Lock()
BOOTSTRAP = {}


# [수정: 0 이영 · Codex] 2026-10-01T02:53:50+09:00 — Claude의 공개 제목 293개 번역 실측에서 의미 오류·반복·한국어 훼손이 확인됐다. 기본은 원제목을 유지하고 명시 설정에서만 검증 전 번역 초안을 제공한다. 원제목·과학 약어는 번역 전에 변경하지 않는다.
ENABLE_ENV = 'NAIS_TITLE_TRANSLATION'
_ENGLISH_WORDS = frozenset('the of and in for on with to a an by from at is are as its their between using via into among under toward towards after during through than or not how what why when do does can be that this these those versus vs'.split())
_NON_LATIN = re.compile(r'[\u0370-\u03ff\u0400-\u04ff\u0590-\u06ff\u0900-\u0dff\u0e00-\u0eff\u3040-\u30ff\u3400-\u9fff]')
_ACRONYM = re.compile(r'(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,}(?:-[0-9A-Za-z]+)?(?![A-Za-z0-9])|(?<![A-Za-z0-9])[A-Z]{1,3}[0-9]+(?:\.[0-9]+)?(?![A-Za-z0-9])')


def enabled():
    """기계 번역 초안은 운영자가 명시적으로 켠 경우에만 제공한다."""
    return os.environ.get(ENABLE_ENV) == '1' or bool(os.environ.get('NAIS_TRANSLATION_MODEL'))


def _looks_english(title):
    """영어가 아닌 문자나 파일 식별자를 영어 번역기에 넣지 않는다."""
    if _NON_LATIN.search(title) or re.fullmatch(r'[A-Za-z0-9_.:/\\-]+', title):
        return False
    letters = [char for char in title if char.isalpha()]
    if not letters or sum(ord(char) > 127 for char in letters) / len(letters) > 0.04:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", title)
    return not (len(words) >= 5 and not (_ENGLISH_WORDS & {word.lower() for word in words}))


def _accept(title, korean):
    """반복·한국어 부재·과도한 영어 잔존을 걸러낸다. 의미 정확성은 보증하지 않는다."""
    if not isinstance(korean, str) or not re.search(r'[가-힣]', korean):
        return None
    korean = re.sub(r'인공\s+지능', '인공지능', korean.strip())
    tokens = korean.split()
    if len(tokens) >= 3:
        if any(tokens[i] == tokens[i + 1] == tokens[i + 2] for i in range(len(tokens) - 2)):
            return None
        count = Counter(tokens).most_common(1)[0][1]
        if (count >= 4 and count / len(tokens) >= 0.25) or Counter(zip(tokens, tokens[1:])).most_common(1)[0][1] >= 3:
            return None
    if len(korean) > max(80, 1.8 * len(title)):
        return None
    body = _ACRONYM.sub(' ', re.sub(r'\([^)]*\)', ' ', korean))
    letters = [char for char in body if char.isalpha()]
    if letters and sum(char.isascii() for char in letters) / len(letters) >= 0.35:
        return None
    return korean


def _valid_model(path):
    base = path.resolve()
    return all((base / name).is_file() and (base / name).stat().st_size > 0
               and (base / name).resolve().is_relative_to(base) for name in FILES)


def _verify_zip(path):
    digest = hashlib.sha256()
    count = 0
    with path.open('rb') as handle:
        while block := handle.read(1024 * 1024):
            count += len(block)
            if count > MAX_BYTES:
                raise ValueError('MODEL_SIZE_LIMIT')
            digest.update(block)
    if digest.hexdigest() != MODEL_SHA256:
        raise ValueError('MODEL_HASH_MISMATCH')


# [작성: 무료번역 담당] 2026-09-29 case95 / 제목전송0, 고정모델1회다운로드·SHA검증 / 검증: test_case95_translation.
def _download(path):
    connection = http.client.HTTPSConnection('data.argosopentech.com', timeout=60)
    started, count = time.monotonic(), 0
    try:
        connection.request('GET', '/argospm/v1/translate-en_ko-1_1.argosmodel',
                           headers={'User-Agent': 'NAIS-OfflineTranslation/95'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('MODEL_DOWNLOAD_UNAVAILABLE')
        with path.open('wb') as handle:
            while True:
                remaining = 180 - (time.monotonic() - started)
                if remaining <= 0:
                    raise ValueError('MODEL_DOWNLOAD_LIMIT')
                sock = connection.sock or response.fp.raw._sock
                sock.settimeout(min(60, remaining))
                block = response.read1(1024 * 1024)
                if not block:
                    break
                count += len(block)
                if count > MAX_BYTES or time.monotonic() - started > 180:
                    raise ValueError('MODEL_DOWNLOAD_LIMIT')
                handle.write(block)
    finally:
        connection.close()


def _extract(path, destination):
    _verify_zip(path)
    with zipfile.ZipFile(path) as archive:
        for name in FILES:
            matches = [info for info in archive.infolist() if info.filename.endswith('/' + name) or info.filename == name]
            if len(matches) != 1 or matches[0].file_size <= 0 or matches[0].file_size > MAX_BYTES:
                raise ValueError('MODEL_ARCHIVE_INVALID')
            target = destination / name
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('MODEL_PATH_INVALID')
            target.parent.mkdir(parents=True, exist_ok=True)
            # Fixed output paths only: archive names are never passed to extract().
            with archive.open(matches[0]) as source, target.open('wb') as output:
                count = 0
                while block := source.read(1024 * 1024):
                    count += len(block)
                    if count > MAX_BYTES:
                        raise ValueError('MODEL_SIZE_LIMIT')
                    output.write(block)


def _model_path():
    explicit = os.environ.get('NAIS_TRANSLATION_MODEL')
    if explicit:
        return Path(explicit)
    return Path(tempfile.gettempdir()) / 'nais_translation' / ('en_ko_' + MODEL_SHA256[:16])


def _ensure_model(path):
    if _valid_model(path):
        return path
    if os.environ.get('NAIS_TRANSLATION_MODEL') or path.exists():
        raise ValueError('MODEL_LOCAL_INVALID')
    path.parent.mkdir(parents=True, exist_ok=True)
    offline = Path(__file__).resolve().parents[1] / 'offline_assets' / 'translate-en_ko-1_1.argosmodel'
    # Windows can exit while the daemon still holds its private download file open.
    # Leave an interrupted temp directory for OS cleanup instead of an exit traceback.
    with tempfile.TemporaryDirectory(prefix='translation-', dir=path.parent, ignore_cleanup_errors=True) as temporary:
        stage = Path(temporary)
        archive = offline if offline.is_file() else stage / 'model.zip'
        if not offline.is_file():
            _download(archive)
        extracted = stage / 'verified'
        _extract(archive, extracted)
        if not _valid_model(extracted):
            raise ValueError('MODEL_LOCAL_INVALID')
        os.replace(extracted, path)
    return path


def _bootstrap(path_string):
    try:
        _ensure_model(Path(path_string))
        state = 'ready'
    except Exception:
        state = 'failed'
    with BOOTSTRAP_LOCK:
        BOOTSTRAP[path_string] = state


# [작성: 무료번역 담당] 2026-09-29 case95 / 모델준비만daemon, 홈대기0·준비중None캐시0 / 검증: stage 준비완료뒤재번역.
def _model_ready(path_string):
    path = Path(path_string)
    try:
        if _valid_model(path):
            return True
    except OSError:
        return False
    if os.environ.get('NAIS_TRANSLATION_MODEL'):
        return False
    with BOOTSTRAP_LOCK:
        if path_string not in BOOTSTRAP:
            BOOTSTRAP[path_string] = 'preparing'
            threading.Thread(target=_bootstrap, args=(path_string,), daemon=True,
                             name='nais-translation-model').start()
    return False


@lru_cache(maxsize=1)
def _load(path_string):
    try:
        import ctranslate2
        import sentencepiece
        path = _ensure_model(Path(path_string))
        tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(path / 'sentencepiece.model'))
        translator = ctranslate2.Translator(str(path / 'model'), device='cpu', compute_type='int8',
                                           inter_threads=1, intra_threads=2)
        return tokenizer, translator
    except Exception:
        # No title, paths, API credentials, or raw errors are logged.
        return None


@lru_cache(maxsize=1000)
def _translate(title, path_string):
    with LOCK:
        loaded = _load(path_string)
        if loaded is None:
            return None
        tokenizer, translator = loaded
        try:
            result = translator.translate_batch([tokenizer.encode(title, out_type=str)],
                                                beam_size=2, max_decoding_length=180)
            text = tokenizer.decode(result[0].hypotheses[0]).strip()
            return text or None
        except Exception:
            return None


# [작성: 무료번역 담당] 2026-09-29 case95 / 유효짧은공개제목→로컬번역초안 / 검증: 비밀·제어문자·초장문은 모델/네트워크0.
def korean_title(title, *, stored_draft=None):
    if (not isinstance(title, str) or not title.strip() or len(title) > 600
            or any(ord(char) < 32 or ord(char) == 127 for char in title)
            or SECRET_PATTERN.search(title)):
        return None
    title = title.strip()
    # [수정: 0 이영 · Codex] 2026-10-01T02:53:50+09:00 — 한국어 제목 안의 AI·DNA 약어는 영어 제목의 근거가 아니다. 이미 한국어인 원제목은 그대로 보존한다.
    if re.search(r'[가-힣]', title):
        return title
    if not re.search(r'[A-Za-z]', title) or not enabled() or not _looks_english(title):
        return None
    # [수정: 0 이영 · Codex] 2026-10-01T03:19:13+09:00 — 저장된 title_ko도 기본 꺼짐·출력 검사를 우회하지 않는다. 저장 번역의 품질을 사람이 확인했다고 가정하지 않는다.
    if stored_draft is not None:
        return _accept(title, stored_draft)
    path_string = str(_model_path())
    if not _model_ready(path_string):
        return None
    return _accept(title, _translate(title, path_string))
