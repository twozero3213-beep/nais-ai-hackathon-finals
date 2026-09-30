"""Fixed HTTPS search adapters; search results are untrusted evidence candidates."""
# [작성: 0 이영 · Codex] 2026-10-01 02:40 KST — Cloud에서 로컬 stdio 등록 대신 공식 검색 HTTPS를 사용한다.
# 검증 범위: 모의 계약·비밀/redirect/크기/시간 제한. 검색은 검산·사람 승인이 아니다.
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import unescape
import hashlib
import http.client
import ipaddress
import json
import os
import re
import sys
from threading import RLock
import time
import uuid
from urllib.parse import parse_qsl, urlsplit

from core.research_corpus import strict_json as _parse_json

PROVIDERS = {
    "exa": ("api.exa.ai", "/search", "EXA_API_KEY", "x-api-key", "https://exa.ai/docs/reference/search"),
    "parallel": ("api.parallel.ai", "/v1/search", "PARALLEL_API_KEY", "x-api-key", "https://docs.parallel.ai/search/search-quickstart"),
    "you": ("ydc-index.io", "/v1/search", "YOU_API_KEY", "X-API-Key", "https://you.com/docs/api-reference/search/v1-search"),
    "tavily": ("api.tavily.com", "/search", "TAVILY_API_KEY", "Authorization", "https://docs.tavily.com/documentation/api-reference/endpoint/search"),
    "firecrawl": ("api.firecrawl.dev", "/v2/search", "FIRECRAWL_API_KEY", "Authorization", "https://docs.firecrawl.dev/api-reference/endpoint/search"),
}
# [수정: 0 이영 · Codex] 2026-10-01 03:04 KST — 공식 무료 원격 MCP를 Cloud에서 직접 사용하고 유료 API fallback은 명시 옵션에서만 실행한다.
REMOTE_MCP = {
    "exa": ("mcp.exa.ai", "/mcp", ("web_search_exa",), "https://exa.ai/docs/get-started/exa-mcp"),
    "parallel": ("search.parallel.ai", "/mcp", ("web_search",), "https://docs.parallel.ai/integrations/mcp/search-mcp"),
    "you": ("api.you.com", "/mcp?profile=free", ("you-search",), "https://you.com/docs/build-with-agents/mcp-server"),
    "tavily": ("mcp.tavily.com", "/mcp/", ("tavily-search", "tavily_search"), "https://docs.tavily.com/documentation/keyless"),
    "firecrawl": ("mcp.firecrawl.dev", "/v2/mcp", ("firecrawl_search",), "https://docs.firecrawl.dev/mcp-server/keyless"),
}
_MCP_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
_MCP_FREE_SESSION = uuid.uuid4().hex  # Stable process session; never rotate to bypass rate limits.
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 20
CACHE_TTL = 300
_CACHE, _HEALTH = {}, {}
_LOCK = RLock()
SENSITIVE = re.compile(r"sk-(?:proj-|ant-)?[\w-]{6,}|gh[pousr]_[\w]{20,}|github_pat_[\w]{8,}|AIza[\w-]{25,}|Bearer\s+\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:api[_ -]?key|password|secret|token)\s*[=:]", re.I)
NOTICE = "검색 결과는 원출처 후보입니다. 원문·파일 확보, 논문 재현, 검산 및 사람 승인은 별도입니다."


def now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def strict_json(raw):
    parsed = _parse_json(raw)
    json.dumps(parsed, allow_nan=False)  # Reject nonfinite values even in unselected fields.
    return parsed


def validate_query(query, limit):
    if (not isinstance(query, str) or not 2 <= len(query.strip()) <= 200 or
            any(ord(c) < 32 or ord(c) == 127 for c in query) or SENSITIVE.search(query)):
        raise ValueError("INVALID_QUERY")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("INVALID_LIMIT")
    return query.strip()


def credential(provider, field="api_key", variable=None):
    """Read only process env or the existing Cloud secrets object; never a file."""
    variable = variable or PROVIDERS[provider][2]
    value = os.environ.get(variable)
    if value is None and provider == "you" and field == "api_key":
        value = os.environ.get("YDC_API_KEY")
    if value is None:
        st = sys.modules.get("streamlit")
        if st is not None:
            try:
                value = st.secrets[provider][field]
            except Exception:
                try:
                    value = st.secrets["research_web"][provider + "_" + field]
                except Exception:
                    value = None
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("INVALID_CONFIGURATION")
    return value


def safe_text(value, limit=700):
    if not isinstance(value, str) or len(value) > 20000 or SENSITIVE.search(value):
        return None
    value = unescape(re.sub(r"<[^>]*>", " ", value))
    value = " ".join(value.split())
    if SENSITIVE.search(value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return value[:limit] or None


def safe_url(value):
    """Display-only public HTTPS links. No link is fetched or executed here."""
    if not isinstance(value, str) or len(value) > 2000 or SENSITIVE.search(value) or any(ord(c) < 33 or ord(c) == 127 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment:
            return None
        if host == "localhost" or "." not in host or host.endswith((".local", ".internal", ".localhost")):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        if any(re.search(r"key|token|secret|password|authorization", name, re.I) for name, _ in parse_qsl(parsed.query, max_num_fields=30)):
            return None
        return value
    except (ValueError, TypeError):
        return None


def envelope(provider, operation="search"):
    return {"ok": False, "status": "NOT_EXECUTED", "error": None, "provider": provider,
            "operation": operation, "items": [], "source_url": None, "http_status": None,
            "retrieved_at_kst": now(), "response_sha256": None, "cached": False,
            "verified": False, "verification_pass": False, "approved": False,
            "scientific_verdict": "NOT_ASSESSED", "limitations": [NOTICE]}


def _finish(result):
    with _LOCK:
        _HEALTH[result["provider"]] = {key: deepcopy(result.get(key)) for key in
            ("status", "error", "http_status", "retrieved_at_kst", "response_sha256", "cached", "transport", "initialized", "tools_listed", "tool_called")}
    return result


def status_catalog():
    rows = []
    for provider, (host, path, variable, _, docs) in PROVIDERS.items():
        try:
            configured = credential(provider) is not None
            configuration = "CONFIGURED" if configured else "NOT_CONFIGURED"
        except ValueError:
            configuration = "INVALID_CONFIGURATION"
        with _LOCK:
            health = deepcopy(_HEALTH.get(provider))
        rows.append({"id": provider, "name": provider.title(), "code_exists": True,
                     "transport": "HTTPS_REMOTE_MCP", "source_url": "https://" + REMOTE_MCP[provider][0] + REMOTE_MCP[provider][1],
                     "docs_url": REMOTE_MCP[provider][3], "configuration": "KEYLESS_REMOTE",
                     "api_configuration": configuration, "api_docs_url": docs,
                     "required_environment": [variable], "runtime_health": health or {"status": "NOT_EXECUTED"},
                     "client_registration": "NOT_INSPECTED", "web_applied": "ROUTER_AVAILABLE_UI_UNCONFIRMED",
                     "deployment_verified": False, "verified": False, "approved": False})
    return rows


def _payload(provider, query, limit):
    if provider == "exa":
        return {"query": query, "type": "auto", "numResults": limit}
    if provider == "parallel":
        return {"objective": query, "search_queries": [query], "advanced_settings":
                {"max_results": limit, "excerpt_settings": {"max_chars_per_result": 700}}}
    if provider == "you":
        return {"query": query, "count": limit}
    if provider == "tavily":
        return {"query": query, "max_results": limit, "search_depth": "basic",
                "include_answer": False, "include_raw_content": False, "include_images": False}
    return {"query": query, "limit": limit, "sources": ["web"], "timeout": 15000}


def _rows(provider, payload):
    if not isinstance(payload, dict):
        raise ValueError("INVALID_RESPONSE")
    if provider == "firecrawl":
        if payload.get("success") is not True or not isinstance(payload.get("data"), dict):
            raise ValueError("PROVIDER_REJECTED")
        rows = payload["data"].get("web")
    elif provider == "you":
        if not isinstance(payload.get("results"), dict):
            raise ValueError("INVALID_RESPONSE")
        rows = payload["results"].get("web")
    else:
        rows = payload.get("results")
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("INVALID_RESPONSE")
    return rows


def _items(provider, payload, limit):
    items, seen = [], set()
    for row in _rows(provider, payload):
        if not isinstance(row, dict):
            raise ValueError("INVALID_RESPONSE")
        url, title = safe_url(row.get("url")), safe_text(row.get("title"), 600)
        if not url or not title or url in seen:
            continue
        seen.add(url)
        description = row.get("description", row.get("content"))
        if description is None:
            fragments = row.get("snippets", row.get("excerpts", row.get("highlights")))
            if isinstance(fragments, list) and all(isinstance(x, str) for x in fragments[:10]):
                description = " ".join(fragments[:3])
        date = row.get("publishedDate", row.get("published_at", row.get("published_date")))
        items.append({"provider": provider, "title": title, "url": url, "source_url": url,
                      "description": safe_text(description), "published_at": safe_text(date, 100),
                      "publication_form": "UNCONFIRMED", "license": None, "access": "NOT_CHECKED",
                      "verified": False, "approved": False, "scientific_verdict": "NOT_ASSESSED"})
        if len(items) == limit:
            break
    return items


def search_api(provider, query, limit=5):
    """One bounded official request, or explicit missing configuration; no retry."""
    result = envelope(provider if isinstance(provider, str) and provider in PROVIDERS else None)
    if result["provider"] is None:
        result.update(status="INVALID_INPUT", error="INVALID_PROVIDER")
        return result
    host, path, _, header, _ = PROVIDERS[provider]
    result["source_url"] = "https://" + host + path  # Auth never appears in a provenance URL.
    try:
        query = validate_query(query, limit)
        key = credential(provider)
        if key is None:
            result.update(status="NOT_CONFIGURED", error="MISSING_API_KEY")
            return _finish(result)
        if key in query:
            raise ValueError("PRIVATE_INPUT")
    except ValueError as exc:
        result.update(status="INVALID_INPUT", error=str(exc))
        return _finish(result)
    cache_key = (provider, hashlib.sha256(key.encode()).hexdigest(), query, limit)
    with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL:
            output = deepcopy(cached[1])
            output["cached"] = True
            return _finish(output)
    connection = None
    try:
        connection = http.client.HTTPSConnection(host, timeout=TIMEOUT)
        body = json.dumps(_payload(provider, query, limit), ensure_ascii=False, allow_nan=False).encode("utf-8")
        connection.request("POST", path, body=body, headers={"Content-Type": "application/json",
            "Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "NAIS-EvidenceGate-Search/0",
            header: ("Bearer " + key) if header == "Authorization" else key})
        response = connection.getresponse()
        result.update(http_status=response.status, retrieved_at_kst=now())
        if response.status != 200:
            status = {401: "AUTH_REQUIRED", 403: "PERMISSION_DENIED", 402: "QUOTA_EXCEEDED", 429: "RATE_LIMITED"}.get(response.status, "PROVIDER_UNAVAILABLE")
            if 300 <= response.status < 400:
                status = "REDIRECT_BLOCKED"
            result.update(status=status, error="HTTP_" + str(response.status))
            return _finish(result)  # Never display or retain error response bodies.
        raw = response.read(MAX_BYTES + 1)
        result["retrieved_at_kst"] = now()
        if len(raw) > MAX_BYTES:
            raise ValueError("RESPONSE_TOO_LARGE")
        if key.encode() in raw:
            raise ValueError("PRIVATE_RESPONSE")
        payload = strict_json(raw)
        # JSON escaping must not allow an exact configured secret to reach any selected field.
        if key in json.dumps(payload, ensure_ascii=False):
            raise ValueError("PRIVATE_RESPONSE")
        result["response_sha256"] = hashlib.sha256(raw).hexdigest()
        result["items"] = _items(provider, payload, limit)
        for item in result["items"]:
            item["provenance"] = {name: result[name] for name in ("provider", "source_url", "retrieved_at_kst", "response_sha256", "http_status")}
        result.update(ok=True, status="SUCCESS" if result["items"] else "EMPTY")
        with _LOCK:
            if len(_CACHE) >= 128:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[cache_key] = (time.monotonic(), deepcopy(result))
    except TimeoutError:
        result.update(status="TIMEOUT", error="TIMEOUT")
    except (ValueError, TypeError, RecursionError, UnicodeError, json.JSONDecodeError):
        result.update(status="INVALID_RESPONSE", error="INVALID_OR_PRIVATE_RESPONSE", items=[])
    except (OSError, http.client.HTTPException):
        result.update(status="PROVIDER_UNAVAILABLE", error="CONNECTION_ERROR", items=[])
    except Exception:
        result.update(status="PROVIDER_UNAVAILABLE", error="PROVIDER_ERROR", items=[])
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return _finish(result)


class _MCPFailure(ValueError):
    def __init__(self, code, http_status=None):
        self.code, self.http_status = code, http_status
        super().__init__(code)


def _mcp_response(response, request_id, deadline=None):
    content_type = response.getheader("Content-Type", "").lower()
    if "text/event-stream" not in content_type:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise _MCPFailure("RESPONSE_TOO_LARGE")
        data = strict_json(raw)
        return data, hashlib.sha256(raw).hexdigest(), "HTTP_BODY"
    # A streaming response can stay open: stop after the matching message, no GET loop.
    received, data_lines = bytearray(), []
    while len(received) <= MAX_BYTES:
        if deadline is not None and time.monotonic() >= deadline:
            raise _MCPFailure("TIMEOUT")
        # [수정: 0 이영 · Codex] 2026-10-01 KST — tools/list의 긴 SSE data 줄을 분할 누락하지 않으며 전체 2MiB 상한은 유지한다.
        line = response.readline(MAX_BYTES + 1 - len(received))
        if not line:
            break
        received.extend(line)
        if len(received) > MAX_BYTES:
            raise _MCPFailure("RESPONSE_TOO_LARGE")
        if line.startswith(b"data:"):
            data_lines.append(line[5:].strip())
        elif line.strip() == b"" and data_lines:
            data = strict_json(b"\n".join(data_lines))
            data_lines = []
            if isinstance(data, dict) and data.get("id") == request_id:
                return data, hashlib.sha256(received).hexdigest(), "RECEIVED_SSE_PREFIX"
    raise _MCPFailure("INVALID_MCP_RESPONSE")


def _mcp_rpc(provider, method, params, request_id, session=None, protocol="2025-06-18", deadline=None):
    host, path, _, _ = REMOTE_MCP[provider]
    connection = None
    remaining = min(TIMEOUT, deadline - time.monotonic()) if deadline is not None else TIMEOUT
    if remaining <= 0:
        raise _MCPFailure("TIMEOUT")
    message = {"jsonrpc": "2.0", "method": method, "params": params}
    if request_id is not None:
        message["id"] = request_id
    headers = {"Content-Type": "application/json", "Accept": "application/json,text/event-stream",
               "Accept-Encoding": "identity", "User-Agent": "NAIS-EvidenceGate-RemoteMCP/0"}
    if provider == "tavily":
        headers["X-Tavily-Access-Mode"] = "keyless"
    if method != "initialize":
        headers["MCP-Protocol-Version"] = protocol
    if session is not None:
        headers["Mcp-Session-Id"] = session
    try:
        connection = http.client.HTTPSConnection(host, timeout=max(.1, remaining))
        connection.request("POST", path, body=json.dumps(message, ensure_ascii=False, allow_nan=False).encode(), headers=headers)
        response = connection.getresponse()
        if response.status not in (200, 202):
            code = {401: "AUTH_REQUIRED", 403: "PERMISSION_DENIED", 402: "QUOTA_EXCEEDED", 429: "RATE_LIMITED"}.get(response.status, "PROVIDER_UNAVAILABLE")
            if 300 <= response.status < 400:
                code = "REDIRECT_BLOCKED"
            raise _MCPFailure(code, response.status)
        if request_id is None:
            return {}, session, None, "NO_BODY"
        if response.status != 200:
            raise _MCPFailure("INVALID_MCP_RESPONSE", response.status)
        data, digest, scope = _mcp_response(response, request_id, deadline)
        if not isinstance(data, dict) or data.get("jsonrpc") != "2.0" or type(data.get("id")) is not int or data.get("id") != request_id:
            raise _MCPFailure("MCP_RESPONSE_ID_MISMATCH")
        if "error" in data:
            raise _MCPFailure("REMOTE_RPC_ERROR")
        if not isinstance(data.get("result"), dict):
            raise _MCPFailure("INVALID_MCP_RESPONSE")
        remote_session = response.getheader("Mcp-Session-Id")
        if remote_session is not None:
            if not 1 <= len(remote_session) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in remote_session):
                raise _MCPFailure("INVALID_MCP_SESSION")
            session = remote_session
        return data["result"], session, digest, scope
    finally:
        if connection is not None:
            connection.close()


def _mcp_arguments(provider, query, limit):
    if provider == "exa":
        return {"query": query, "objective": query, "numResults": limit}
    if provider == "parallel":
        return {"objective": query, "search_queries": [query], "session_id": _MCP_FREE_SESSION}
    if provider == "you":
        return {"query": query, "count": limit, "extraction": "none"}
    if provider == "tavily":
        return {"query": query, "max_results": limit, "search_depth": "basic", "include_raw_content": False, "include_images": False}
    return {"query": query, "limit": limit, "sources": ["web"], "domainTools": False}


def _mcp_items(provider, result, limit):
    content = result.get("content", [])
    if not isinstance(content, list) or len(content) > 30:
        raise _MCPFailure("INVALID_MCP_RESPONSE")
    texts = [item.get("text") for item in content if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)]
    combined = "\n".join(texts)
    if len(combined.encode()) > MAX_BYTES:
        raise _MCPFailure("RESPONSE_TOO_LARGE")
    # Provider error instructions remain data; do not follow signup/payment/auth instructions.
    if result.get("isError") is True:
        code = "PUBLIC_QUOTA_LIMIT" if re.search(r"rate.limit|quota|monthly.cap|credits.exhausted|free.allowance", combined, re.I) else "REMOTE_TOOL_ERROR"
        raise _MCPFailure(code)
    candidates = []
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        candidates.append(structured)
    for text in texts:
        try:
            parsed = strict_json(text)
        except (ValueError, TypeError, RecursionError):
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    for candidate in candidates:
        if candidate.get("error") or candidate.get("code") or candidate.get("success") is False:
            diagnostic = json.dumps(candidate, ensure_ascii=False)
            code = "PUBLIC_QUOTA_LIMIT" if re.search(r"rate.limit|quota|monthly.cap|credits.exhausted|free.allowance", diagnostic, re.I) else "REMOTE_TOOL_ERROR"
            raise _MCPFailure(code)
        try:
            return _items(provider, candidate, limit)
        except ValueError:
            pass
        # Some MCPs wrap the same official API result inside a data field.
        if isinstance(candidate.get("data"), dict):
            try:
                return _items(provider, candidate["data"], limit)
            except ValueError:
                pass
    items, seen = [], set()
    # Exa/Parallel may return a text document; only explicit URL/title pairs are projected.
    blocks = re.split(r"(?=^Title:)|(?=^<search_result)|(?=^\s*\d+\. )", combined, flags=re.M)
    for block in blocks:
        title_match = re.search(r"^Title:\s*(.+)$", block, re.M)
        url_match = re.search(r"^(?:URL|Url|url):\s*(https://\S+)", block, re.M)
        markdown = re.search(r"\[([^\]\n]{1,600})\]\((https://[^\s)]+)\)", block)
        if not url_match and not markdown:
            continue
        url = safe_url(url_match.group(1) if url_match else markdown.group(2))
        title = safe_text(title_match.group(1) if title_match else markdown.group(1) if markdown else None, 600)
        if not url or not title or url in seen:
            continue
        seen.add(url)
        items.append({"provider": provider, "title": title, "url": url, "source_url": url,
            "description": None, "published_at": None, "publication_form": "UNCONFIRMED", "license": None,
            "access": "NOT_CHECKED", "verified": False, "approved": False, "scientific_verdict": "NOT_ASSESSED"})
        if len(items) >= limit:
            break
    if not items:
        raise _MCPFailure("UNSUPPORTED_MCP_RESULT_FORMAT")
    return items


def search_mcp(provider, query, limit=5):
    result = envelope(provider if isinstance(provider, str) and provider in REMOTE_MCP else None)
    result.update(transport="HTTPS_REMOTE_MCP", initialized=False, tools_listed=False, tool_called=False,
                  auth_mode="KEYLESS", protocol_version=None, response_hash_scope=None)
    if result["provider"] is None:
        result.update(status="INVALID_INPUT", error="INVALID_PROVIDER")
        return result
    result["source_url"] = "https://" + REMOTE_MCP[provider][0] + REMOTE_MCP[provider][1]
    try:
        query = validate_query(query, limit)
    except ValueError as error:
        result.update(status="INVALID_INPUT", error=str(error))
        return _finish(result)
    cache_key = ("remote_mcp", provider, query, limit)
    with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL:
            output = deepcopy(cached[1]); output["cached"] = True
            return _finish(output)
    deadline = time.monotonic() + 50  # Total operation budget, no unlimited stream/reconnect.
    try:
        initial, session, _, _ = _mcp_rpc(provider, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "nais-evidence-gate-web", "version": "0"}}, 1, deadline=deadline)
        protocol = initial.get("protocolVersion")
        if protocol not in _MCP_PROTOCOLS:
            raise _MCPFailure("UNSUPPORTED_MCP_PROTOCOL")
        result.update(initialized=True, protocol_version=protocol)
        _mcp_rpc(provider, "notifications/initialized", {}, None, session, protocol, deadline)
        listing, session, _, _ = _mcp_rpc(provider, "tools/list", {}, 2, session, protocol, deadline)
        tools = listing.get("tools")
        if not isinstance(tools, list) or len(tools) > 100:
            raise _MCPFailure("INVALID_MCP_TOOLS")
        result["tools_listed"] = True
        selected = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") in REMOTE_MCP[provider][2]]
        if len(selected) != 1:
            raise _MCPFailure("SEARCH_TOOL_UNAVAILABLE")
        tool = selected[0]
        arguments = _mcp_arguments(provider, query, limit)
        # Verify the live schema before call, without allowing dynamic tool names or arguments.
        from jsonschema import Draft202012Validator
        try:
            Draft202012Validator.check_schema(tool.get("inputSchema"))
            Draft202012Validator(tool["inputSchema"]).validate(arguments)
        except Exception:
            raise _MCPFailure("MCP_SCHEMA_CHANGED") from None
        result.update(tools_listed=True, tool_name=tool["name"])
        reply, _, digest, scope = _mcp_rpc(provider, "tools/call", {"name": tool["name"], "arguments": arguments}, 3, session, protocol, deadline)
        result.update(tool_called=True, response_sha256=digest, response_hash_scope=scope,
                      retrieved_at_kst=now(), http_status=200)
        result["items"] = _mcp_items(provider, reply, limit)
        for item in result["items"]:
            item["provenance"] = {key: result[key] for key in ("provider", "source_url", "retrieved_at_kst", "response_sha256", "http_status", "response_hash_scope")}
        result.update(ok=True, status="SUCCESS" if result["items"] else "EMPTY")
        with _LOCK:
            if len(_CACHE) >= 128:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[cache_key] = (time.monotonic(), deepcopy(result))
    except _MCPFailure as error:
        result.update(status=error.code, error=error.code, items=[])
        if error.http_status is not None:
            result["http_status"] = error.http_status
    except TimeoutError:
        result.update(status="TIMEOUT", error="TIMEOUT", items=[])
    except Exception:
        result.update(status="PROVIDER_UNAVAILABLE", error="CONNECTION_OR_MCP_RESPONSE_ERROR", items=[])
    return _finish(result)


def search(provider, query, limit=5, *, transport="mcp", allow_api_fallback=False):
    """Free remote MCP first. A configured paid API fallback must be explicit."""
    if transport == "api":
        return search_api(provider, query, limit)
    if transport != "mcp" or type(allow_api_fallback) is not bool:
        result = envelope(None); result.update(status="INVALID_INPUT", error="INVALID_TRANSPORT")
        return result
    result = search_mcp(provider, query, limit)
    if not result["ok"] and allow_api_fallback and result["status"] != "INVALID_INPUT":
        fallback = search_api(provider, query, limit)
        fallback["attempts"] = [{key: result.get(key) for key in ("transport", "status", "error", "initialized", "tools_listed", "tool_called", "retrieved_at_kst")}]
        return fallback
    return result
