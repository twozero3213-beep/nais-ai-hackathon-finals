"""Research discovery routes to existing bounded clients, without scientific approval."""
# [작성: 0 이영 · Codex] 2026-10-01 02:44 KST — 기존 출처를 제공자별 계약으로 연결하고 Cloud 실행과 로컬 MCP 등록을 구분한다.
# 검증: 허용 입력·출처·실패/빈결과·승인 경계 회귀. 파일 수신 및 계산은 다른 기존 경로에서 수행한다.
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import http.client
import importlib.util
import json
import math
import re
from threading import RLock
from urllib.parse import quote, urlencode
import xml.etree.ElementTree as ET

from core import aihub, ntis, paper_discovery, paper_sources, publication_extensions
from core import repository_extensions, research_data_sources, scholar_discovery
from core.integration_http import get_json
from core.research_corpus import strict_json
from core import research_web_search as web

DEFAULT_PROVIDERS = ("crossref", "europepmc", "scholar")
SEARCH_PROVIDERS = ("crossref", "openalex", "europepmc", "scienceon", "aihub", "ntis", "scholar",
                    "zenodo", "figshare", "dataverse", *web.PROVIDERS, *research_data_sources.SOURCES)
_HEALTH = {}
_LOCK = RLock()
_SCIENCEON_HOST = "apigateway.kisti.re.kr"
_SCIENCEON_DOC = "https://github.com/ansua79/scienceon-mcp"
_SCIENCEON_FIELDS = {"api_key": "SCIENCEON_API_KEY", "client_id": "SCIENCEON_CLIENT_ID", "mac_address": "SCIENCEON_MAC_ADDRESS"}
_DOI = re.compile(r"10\.\d{4,9}/[A-Za-z0-9][A-Za-z0-9._;()/:+\-]{1,180}\Z", re.I)


def _base(provider, operation):
    return web.envelope(provider, operation)


def _failure(provider, operation, code, status="LOOKUP_FAILED"):
    result = _base(provider, operation)
    result.update(status=status, error=code)
    return result


def _safe_tree(value, depth=0):
    """Retain metadata/checksums, suppress private values and any approval flags."""
    if depth > 15:
        raise ValueError("INVALID_RESPONSE")
    if value is None or type(value) in (int, bool):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("INVALID_RESPONSE")
        return value
    if isinstance(value, str):
        if len(value) > 20000 or web.SENSITIVE.search(value) or any(ord(c) < 32 and c not in "\n\t\r" for c in value):
            return None
        return value
    if isinstance(value, list):
        if len(value) > 1000:
            raise ValueError("INVALID_RESPONSE")
        return [_safe_tree(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError("INVALID_RESPONSE")
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 100:
                raise ValueError("INVALID_RESPONSE")
            if key in {"verified", "verification_pass", "approved"}:
                result[key] = False
            elif not re.search(r"^(?:api_?key|password|secret|access_token|authorization|email)$", key, re.I):
                result[key] = _safe_tree(item, depth + 1)
        return result
    raise ValueError("INVALID_RESPONSE")


def _remember(result):
    if result.get("provider"):
        with _LOCK:
            _HEALTH[result["provider"]] = {key: deepcopy(result.get(key)) for key in
                ("status", "error", "retrieved_at_kst", "response_sha256", "http_status")}
    return result


def _wrap(provider, operation, raw, *, success=True, limit=10):
    if not isinstance(raw, dict):
        return _failure(provider, operation, "INVALID_RESPONSE")
    result = _base(provider, operation)
    for field in ("source_url", "retrieved_at_kst", "response_sha256", "http_status", "cached"):
        if field in raw:
            result[field] = raw[field]
    result["source_url"] = web.safe_url(raw.get("source_url", raw.get("source")))
    observed = raw.get("retrieved_at_kst") or raw.get("checked_at")
    if isinstance(observed, str):
        try:
            timestamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if timestamp.tzinfo is not None:
                result["retrieved_at_kst"] = timestamp.astimezone(timezone(timedelta(hours=9))).isoformat()
        except ValueError:
            pass
    sha = raw.get("response_sha256", raw.get("source_response_sha256"))
    result["response_sha256"] = sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha) else None
    try:
        rows = raw.get("items", [])
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("INVALID_RESPONSE")
        for row in rows[:limit]:
            if not isinstance(row, dict):
                raise ValueError("INVALID_RESPONSE")
            item = _safe_tree(row)
            item.update(provider=provider, verified=False, verification_pass=False, approved=False)
            item["scientific_verdict"] = "NOT_ASSESSED"
            item["provenance"] = {key: result[key] for key in ("provider", "source_url", "retrieved_at_kst", "response_sha256", "http_status")}
            result["items"].append(item)
        limitations = raw.get("limitations")
        if isinstance(limitations, list):
            result["limitations"].extend(text for x in limitations[:20] if (text := web.safe_text(x, 1200)))
        if result["response_sha256"] is None:
            result["limitations"].append("기존 어댑터는 응답 바이트 지문을 반환하지 않습니다. 조회된 값의 원응답 지문은 미확인입니다.")
        result.update(ok=success, status=("SUCCESS" if result["items"] else "EMPTY") if success else "LOOKUP_FAILED")
    except (ValueError, TypeError):
        result.update(ok=False, status="INVALID_RESPONSE", error="INVALID_RESPONSE", items=[])
    return result


def _scienceon_config():
    values = {field: web.credential("scienceon", field, variable) for field, variable in _SCIENCEON_FIELDS.items()}
    if any(value is None for value in values.values()):
        raise ValueError("NOT_CONFIGURED")
    if len(values["api_key"].encode()) not in (16, 24, 32) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", values["client_id"]):
        raise ValueError("INVALID_CONFIGURATION")
    if not re.fullmatch(r"(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}", values["mac_address"], re.I):
        raise ValueError("INVALID_CONFIGURATION")
    return values


def _aes_available():
    try:
        return importlib.util.find_spec("Crypto.Cipher.AES") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _scienceon_get(path, secrets):
    """Private auth query remains only inside this fixed HTTPS request, never provenance."""
    if not path.startswith(("/tokenrequest.do?", "/openapicall.do?")) or len(path) > 4000 or any(ord(c) < 32 for c in path):
        raise ValueError("INVALID_REQUEST")
    connection = None
    try:
        connection = http.client.HTTPSConnection(_SCIENCEON_HOST, timeout=20)
        connection.request("GET", path, headers={"Accept": "application/json,application/xml", "Accept-Encoding": "identity", "User-Agent": "NAIS-EvidenceGate-ScienceON/0"})
        response = connection.getresponse()
        if response.status != 200:
            code = {401: "AUTH_REQUIRED", 403: "PERMISSION_DENIED", 429: "RATE_LIMITED"}.get(response.status, "PROVIDER_UNAVAILABLE")
            raise ValueError(code)
        raw = response.read(web.MAX_BYTES + 1)
        if len(raw) > web.MAX_BYTES:
            raise ValueError("RESPONSE_TOO_LARGE")
        # Do not surface auth echoes, including credentials escaped in JSON/XML.
        text = raw.decode("utf-8")
        if any(value and (value in text or value in __import__("html").unescape(text)) for value in secrets):
            raise ValueError("PRIVATE_RESPONSE")
        return raw
    finally:
        if connection is not None:
            connection.close()


def _scienceon_search(query, limit):
    result = _base("scienceon", "search")
    result["source_url"] = "https://" + _SCIENCEON_HOST + "/openapicall.do"
    result["limitations"].append("ScienceON 등록 IP·MAC의 현재 배포 환경 일치는 미확인입니다. 인증 실패는 빈 검색 결과와 구분합니다.")
    try:
        config = _scienceon_config()
        if any(value in query for value in config.values()):
            raise ValueError("PRIVATE_INPUT")
        if not _aes_available():
            raise ValueError("DEPENDENCY_MISSING")
        from Crypto.Cipher import AES
        # Official gateway accounts contract; no official .env loader or local MCP imported.
        plain = json.dumps({"datetime": datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d%H%M%S"),
                            "mac_address": config["mac_address"]}, separators=(",", ":")).encode()
        padding = 16 - len(plain) % 16
        encrypted = AES.new(config["api_key"].encode(), AES.MODE_CBC, b"jvHJ1EFA0IXBrxxz").encrypt(plain + bytes([padding]) * padding)
        accounts = base64.urlsafe_b64encode(encrypted).decode()
        private = list(config.values()) + [accounts]
        raw = _scienceon_get("/tokenrequest.do?" + urlencode({"client_id": config["client_id"], "accounts": accounts}), private)
        payload = strict_json(raw)
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not 1 <= len(token) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("AUTH_REQUIRED")
        params = {"client_id": config["client_id"], "token": token, "version": "1.0", "action": "search",
                  "target": "ARTI", "searchQuery": json.dumps({"BI": query}, ensure_ascii=False), "curPage": 1, "rowCount": limit}
        raw = _scienceon_get("/openapicall.do?" + urlencode(params), private + [token])
        if b"<!ENTITY" in raw.upper() or b"<!DOCTYPE" in raw.upper():
            raise ValueError("INVALID_RESPONSE")
        root = ET.fromstring(raw)
        status = root.findtext(".//statusCode")
        if status not in (None, "200"):
            raise ValueError("PROVIDER_REJECTED")
        total = root.findtext(".//TotalCount")
        if total is None or not total.isascii() or not total.isdigit():
            raise ValueError("INVALID_RESPONSE")
        records = root.findall(".//record")
        if len(records) > limit or int(total) < len(records) or (int(total) > 0 and not records):
            raise ValueError("INVALID_RESPONSE")
        for record in records:
            fields = {}
            for field in record.findall("item"):
                name = field.get("metaCode")
                if name in {"CN", "Title", "DOI", "Pubyear", "JournalName"}:
                    if name in fields:
                        raise ValueError("INVALID_RESPONSE")
                    fields[name] = web.safe_text(field.text, 600)
            cn, title = fields.get("CN"), fields.get("Title")
            if not cn or not title or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", cn):
                continue
            doi = fields.get("DOI")
            if doi and not _DOI.fullmatch(doi):
                doi = None
            result["items"].append({"provider": "scienceon", "id": cn, "title": title, "doi": doi,
                "published_at": fields.get("Pubyear"), "journal": fields.get("JournalName"),
                "url": "https://scienceon.kisti.re.kr/srch/selectPORSrchArticle.do?cn=" + quote(cn),
                "publication_form": "UNCONFIRMED", "license": None, "access": "NOT_CHECKED", "verified": False, "approved": False})
        result.update(ok=True, status="SUCCESS" if result["items"] else "EMPTY", http_status=200,
                      total=int(total), retrieved_at_kst=web.now(), response_sha256=hashlib.sha256(raw).hexdigest())
        for item in result["items"]:
            item["provenance"] = {key: result[key] for key in ("provider", "source_url", "retrieved_at_kst", "response_sha256", "http_status")}
    except TimeoutError:
        result.update(status="TIMEOUT", error="TIMEOUT")
    except ValueError as error:
        code = str(error)
        allowed = {"NOT_CONFIGURED", "INVALID_CONFIGURATION", "DEPENDENCY_MISSING", "PRIVATE_INPUT", "AUTH_REQUIRED", "PERMISSION_DENIED", "RATE_LIMITED", "PROVIDER_UNAVAILABLE", "PROVIDER_REJECTED", "RESPONSE_TOO_LARGE", "PRIVATE_RESPONSE", "INVALID_RESPONSE"}
        code = code if code in allowed else "INVALID_RESPONSE"
        result.update(status=code, error=code, items=[])
    except Exception:
        result.update(status="PROVIDER_UNAVAILABLE", error="CONNECTION_OR_RESPONSE_ERROR", items=[])
    return result


def _search_one(provider, query, limit):
    if provider in web.PROVIDERS:
        return web.search(provider, query, limit)
    if provider == "scienceon":
        return _scienceon_search(query, limit)
    if provider == "scholar":
        raw = scholar_discovery.scholar_discovery(query)
        result = _base(provider, "search")
        result.update(ok=raw.get("ok") is True, status="NAVIGATION_ONLY", source_url=raw.get("search_url"),
                      search_url=raw.get("search_url"), retrieved=False, evidence_steps=raw.get("evidence_steps", []))
        return result
    if provider in ("zenodo", "figshare", "dataverse"):
        raw = repository_extensions.search_repository(provider, query, limit)
        result = _wrap(provider, "search", raw, success=raw.get("success") is True, limit=limit)
        if not raw.get("success"):
            result.update(status="LOOKUP_FAILED", error=raw.get("error"))
        return result
    if provider in research_data_sources.SOURCES:
        raw = research_data_sources.search_research_data(provider, query, limit)
        result = _wrap(provider, "search", raw, success=raw.get("status") in ("OK", "EMPTY"), limit=limit)
        if not result["ok"]:
            result.update(status=raw.get("status", "LOOKUP_FAILED"), error=raw.get("error") or "LOOKUP_FAILED")
        return result
    if provider == "crossref":
        raw = paper_discovery.search_papers(query, years=3, limit=limit)
    elif provider == "openalex":
        raw = paper_sources.search_openalex(query, years=3, limit=limit)
    elif provider == "europepmc":
        raw = paper_sources.search_europepmc(query, years=3, limit=limit)
    elif provider == "aihub":
        raw = aihub.search_datasets(query, limit)
    else:
        raw = ntis.search_projects(query, limit)
    return _wrap(provider, "search", raw, limit=limit)


def search(query, providers=None, limit=5):
    """Explicit selected providers only. Failure remains in each provider envelope."""
    result = _base(None, "integrated_search")
    result["results"] = []
    try:
        query = web.validate_query(query, limit)
        selected = DEFAULT_PROVIDERS if providers is None else providers
        if not isinstance(selected, (list, tuple)) or not 1 <= len(selected) <= 8 or any(not isinstance(p, str) or p not in SEARCH_PROVIDERS for p in selected) or len(set(selected)) != len(selected):
            raise ValueError("INVALID_PROVIDERS")
    except ValueError as error:
        result.update(status="INVALID_INPUT", error=str(error))
        return result
    for provider in selected:
        try:
            current = _search_one(provider, query, limit)
        except Exception as error:
            code = getattr(error, "code", None)
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z_0-9]{1,70}", code):
                code = "PROVIDER_UNAVAILABLE"
            status = "NOT_CONFIGURED" if code.endswith("NOT_CONFIGURED") else "LOOKUP_FAILED"
            current = _failure(provider, "search", code, status)
        result["results"].append(_remember(current))
        result["items"].extend(current.get("items", []))
    good = sum(x.get("ok") is True for x in result["results"])
    result.update(ok=good > 0, status="SUCCESS" if good == len(selected) else "PARTIAL" if good else "LOOKUP_FAILED",
                  query=query, providers=list(selected))
    if not good:
        result["error"] = "ALL_PROVIDERS_FAILED"
    result["limitations"].append("검색 범위·정렬·인용망은 제공자마다 다릅니다. 제공자별 결과를 유지하며 한 통합 순위로 평가하지 않습니다.")
    return result


def repository(provider, identifier):
    raw = repository_extensions.repository_record(provider, identifier)
    result = _wrap(raw.get("provider"), "repository_record", raw, success=raw.get("success") is True)
    if not raw.get("success"):
        result.update(status="LOOKUP_FAILED", error=raw.get("error"))
    return _remember(result)


def publication(doi, pmid=None):
    """Exact DOI metadata, version links and direction-preserving corrections."""
    result = _base("crossref", "publication")
    if not isinstance(doi, str) or len(doi) > 200 or not _DOI.fullmatch(doi) or web.SENSITIVE.search(doi):
        result.update(status="INVALID_INPUT", error="INVALID_DOI")
        return result
    if pmid is not None and (not isinstance(pmid, str) or not re.fullmatch(r"[1-9]\d{0,9}", pmid)):
        result.update(status="INVALID_INPUT", error="INVALID_PMID")
        return result
    doi = doi.lower()
    raw = get_json("api.crossref.org", "/works/" + quote(doi, safe=""))
    for key in ("source_url", "retrieved_at_kst", "response_sha256", "http_status", "cached"):
        result[key] = raw.get(key)
    try:
        item = raw.get("data", {}).get("message") if raw.get("ok") else None
        if not isinstance(item, dict) or str(item.get("DOI", "")).lower() != doi:
            raise ValueError("DOI_IDENTITY_OR_LOOKUP_FAILED")
        title = item.get("title")
        if not isinstance(title, list) or not title or not (text := web.safe_text(title[0], 600)):
            raise ValueError("INVALID_RESPONSE")
        version_links = []
        links = item.get("link", [])
        if not isinstance(links, list) or len(links) > 100:
            raise ValueError("INVALID_RESPONSE")
        for link in links:
            if isinstance(link, dict) and (url := web.safe_url(link.get("URL"))):
                version_links.append({"url": url, "content_type": web.safe_text(link.get("content-type"), 100),
                                      "version": web.safe_text(link.get("content-version"), 100), "access": "NOT_CHECKED"})
        updates = publication_extensions.publication_updates(doi)
        result.update(ok=True, status="SUCCESS" if updates.get("ok") else "PARTIAL", doi=doi,
            items=[{"provider": "crossref", "doi": doi, "id": doi, "title": text, "url": "https://doi.org/" + doi,
                    "type": web.safe_text(item.get("type"), 80), "publication_form": "UNCONFIRMED",
                    "published": _safe_tree(item.get("published")), "license": _safe_tree(item.get("license")),
                    "version_links": version_links, "access": "NOT_CHECKED", "verified": False, "approved": False}],
            updates=_safe_tree(updates))
        if pmid is not None:
            pubmed = publication_extensions.pubmed_record(pmid)
            # Never attach a different DOI's PubMed record to this publication.
            if pubmed.get("ok") and doi not in pubmed.get("dois", []):
                result["pubmed"] = {"ok": False, "error": "DOI_IDENTITY_MISMATCH", "pmid": pmid}
                result["status"] = "PARTIAL"
            else:
                result["pubmed"] = _safe_tree(pubmed)
                if not pubmed.get("ok"):
                    result["status"] = "PARTIAL"
        result["items"][0]["provenance"] = {key: result[key] for key in ("provider", "source_url", "retrieved_at_kst", "response_sha256", "http_status")}
    except (ValueError, TypeError, AttributeError) as error:
        code = str(error) if str(error) in {"DOI_IDENTITY_OR_LOOKUP_FAILED", "INVALID_RESPONSE"} else "INVALID_RESPONSE"
        result.update(ok=False, status="LOOKUP_FAILED", error=code, items=[])
    return _remember(result)


def status_catalog():
    """Code/config/current-process health are separate from host registration/deployment."""
    rows = web.status_catalog()
    data_rows = {row["id"]: row for row in research_data_sources.source_catalog()}
    for provider in SEARCH_PROVIDERS:
        if provider in web.PROVIDERS:
            continue
        configuration, required, docs = "PUBLIC_NO_KEY", [], None
        if provider == "scienceon":
            required, docs = list(_SCIENCEON_FIELDS.values()), _SCIENCEON_DOC
            try:
                _scienceon_config()
                configuration = "CONFIGURED" if _aes_available() else "DEPENDENCY_MISSING"
            except ValueError as error:
                configuration = str(error)
        elif provider in ("aihub", "ntis"):
            required = ["AIHUB_API_KEY" if provider == "aihub" else "NTIS_API_KEY"]
            docs = "https://github.com/aihub-git/AIHub-MCP" if provider == "aihub" else "https://www.ntis.go.kr/rndopen/api/mng/apiMain.do"
            try:
                (aihub._api_key if provider == "aihub" else ntis._api_key)()
                configuration = "CONFIGURED"
            except (aihub.AIHubError, ntis.NTISError) as error:
                configuration = "NOT_CONFIGURED" if error.code.endswith("NOT_CONFIGURED") else "INVALID_CONFIGURATION"
        elif provider in data_rows:
            configuration = data_rows[provider]["status"]
            docs = data_rows[provider]["docs_url"]
        with _LOCK:
            health = deepcopy(_HEALTH.get(provider, {"status": "NOT_EXECUTED"}))
        rows.append({"id": provider, "name": provider.title(), "code_exists": True, "transport": "BROWSER_LINK" if provider == "scholar" else "HTTPS",
            "configuration": configuration, "required_environment": required, "docs_url": docs,
            "runtime_health": health, "client_registration": "NOT_INSPECTED", "web_applied": "ROUTER_AVAILABLE_UI_UNCONFIRMED",
            "deployment_verified": False, "verified": False, "approved": False,
            "deployment_authentication": "REGISTERED_IP_MAC_UNCONFIRMED" if provider == "scienceon" else "NOT_TESTED"})
    rows.append({"id": "dataon", "name": "DataON", "code_exists": False, "configuration": "CONTRACT_UNCONFIRMED",
        "runtime_health": {"status": "NOT_EXECUTED"}, "client_registration": "NOT_INSPECTED", "web_applied": "NOT_APPLIED",
        "deployment_verified": False, "verified": False, "approved": False,
        "reason": "현재 제품의 고정 API 계약·인증·응답 형식이 확인되지 않아 임의 URL을 만들지 않습니다."})
    return rows
