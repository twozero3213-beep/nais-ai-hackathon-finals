"""실제 공개 파일 경로와 카탈로그·OpenAPI·ZIP의 연결이 일치하는지 검사한다."""
# [작성: 0 이영 · Codex] 2026-10-01T03:24:13+09:00 — finals /~/+/app/static/의 HTTP200을 확인한 경로를 재생성·검증한다. 네트워크·모델 호출 없이 고정 예제만 사용한다.
from io import BytesIO
import json
from zipfile import ZipFile

from core import public_agent as public


def test_public_files_zip_and_contract_agree_on_current_verified_urls(tmp_path):
    directory = tmp_path / "public"
    hashes = public.build_public_files(directory, built_at="2026-10-01T03:24:13+09:00")
    assert set(hashes) == public.PUBLIC_FILES
    catalog = json.loads((directory / "agent.json").read_bytes())
    expected = "https://nais-evidence-gate-finals.streamlit.app/~/+/app/static/"
    assert catalog["endpoints"] == {name: expected + name for name in public.PUBLIC_FILES}
    contract = json.loads((directory / "openapi.json").read_bytes())
    assert {contract["servers"][0]["url"] + path for path in contract["paths"]} == {expected + name for name in public.PUBLIC_FILES - {"openapi.json"}}
    assert "nais-evidence-gate-team" not in (directory / "llms.txt").read_text(encoding="utf-8")
    with ZipFile(BytesIO(public.public_download_zip(directory))) as package:
        assert set(package.namelist()) == public.PUBLIC_FILES
        assert json.loads(package.read("agent.json"))["endpoints"] == catalog["endpoints"]
