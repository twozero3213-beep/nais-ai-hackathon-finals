"""Public repository metadata snapshots; no file download or scientific verdict."""
# [작성: 0 이영 · Codex] 2026-10-01 00:30 KST — 원자료 후보의 DOI·버전·라이선스·공급자 체크섬을 공개 조회로 연결한다. 버전 0. 파일 수신·지문 검증·사람 승인과 분리하며 모의 계약 시험으로 검증한다.
from __future__ import annotations

import html
import re
from urllib.parse import urlencode, urlsplit

from core.integration_http import get_json


HOSTS = {"zenodo": "zenodo.org", "figshare": "api.figshare.com", "dataverse": "dataverse.harvard.edu"}
DOI_RE = re.compile(r"10\.\d{4,9}/[A-Za-z0-9][A-Za-z0-9._;()/-]{1,180}", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HASH_LENGTHS = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}
NOTICE = "PUBLIC_METADATA_ONLY: repository checksums are advertised metadata, not verified downloaded bytes or reproduced scientific results."


def _text(value, maximum=1000, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("INVALID_RESPONSE")
    value = html.unescape(re.sub(r"<[^>]*>", "", value))
    value = "".join(c for c in value if ord(c) >= 32 and ord(c) != 127).strip()
    value = EMAIL_RE.sub("[redacted]", value)
    if required and not value:
        raise ValueError("INVALID_RESPONSE")
    return value or None


def _number(value, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("INVALID_RESPONSE")
    return value


def _doi(value, *, required=False):
    if value in (None, "") and not required:
        return None
    if not isinstance(value, str):
        raise ValueError("INVALID_RESPONSE")
    if value.startswith("https://doi.org/"):
        value = value[len("https://doi.org/"):]
    if value.startswith("doi:"):
        value = value[4:]
    if not DOI_RE.fullmatch(value):
        raise ValueError("INVALID_RESPONSE")
    return value.lower()


def _url(value):
    if value is None:
        return None
    value = _text(value, 2000)
    parts = urlsplit(value or "")
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password or EMAIL_RE.search(value or ""):
        raise ValueError("INVALID_RESPONSE")
    return value


def _license(value):
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("INVALID_RESPONSE")
    license_id = value.get("id", value.get("rightsIdentifier"))
    if license_id is None and value.get("value") is not None:
        license_id = str(_number(value["value"]))
    return {"id": _text(license_id, 100), "name": _text(value.get("name", value.get("title")), 300),
            "url": _url(value.get("url", value.get("uri"))), "reuse_authorization": "NOT_CONFIRMED"}


def _checksum(value, algorithm=None, *, origin):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("INVALID_RESPONSE")
    if algorithm is None:
        if ":" not in value:
            raise ValueError("INVALID_RESPONSE")
        algorithm, value = value.split(":", 1)
    if not isinstance(algorithm, str):
        raise ValueError("INVALID_RESPONSE")
    publisher_algorithm = algorithm
    normalized = algorithm.lower().replace("-", "")
    if normalized not in HASH_LENGTHS or not re.fullmatch(r"[0-9a-fA-F]{" + str(HASH_LENGTHS[normalized]) + "}", value):
        raise ValueError("INVALID_RESPONSE")
    return {"algorithm": normalized, "publisher_algorithm": publisher_algorithm, "value": value.lower(),
            "origin": origin, "verified_against_download": False}


def _failure(provider, operation, code, response=None):
    response = response if isinstance(response, dict) else {}
    return {"success": False, "provider": provider, "operation": operation, "items": [], "total": None,
            "http_status": response.get("http_status"), "source_url": response.get("source_url"),
            "retrieved_at_kst": response.get("retrieved_at_kst"), "response_sha256": response.get("response_sha256"),
            "error": code, "scope": "PUBLIC_METADATA_ONLY", "verified": False, "approved": False, "notice": NOTICE}


def _provenance(response):
    return {name: response.get(name) for name in ("source_url", "retrieved_at_kst", "response_sha256", "http_status")}


def _success(provider, operation, records, response, total=None):
    result = _failure(provider, operation, None, response)
    result.update(success=True, items=records, total=total)
    for record in records:
        record["provenance"] = _provenance(response)
    return result


def _request(provider, path, params=None):
    try:
        result = get_json(HOSTS[provider], path, params=params)
    except Exception:
        return {"ok": False, "error": "TRANSPORT_ERROR"}
    if not isinstance(result, dict):
        return {"ok": False, "error": "INVALID_TRANSPORT_RESPONSE"}
    return result


def _error(response):
    value = response.get("error")
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", value) else "TRANSPORT_ERROR"


def _input(provider, identifier):
    if not isinstance(provider, str) or provider not in HOSTS:
        raise ValueError("INVALID_PROVIDER")
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 220 or identifier != identifier.strip():
        raise ValueError("INVALID_IDENTIFIER")
    if provider == "zenodo":
        match = re.fullmatch(r"(?:10\.5281/zenodo\.)?([1-9][0-9]{0,14})", identifier, re.I)
        if not match:
            raise ValueError("INVALID_IDENTIFIER")
        return match.group(1), None
    if provider == "figshare":
        match = re.fullmatch(r"(?:10\.6084/m9\.figshare\.)?([1-9][0-9]{0,14})(?:\.v([1-9][0-9]{0,5}))?", identifier, re.I)
        if not match:
            raise ValueError("INVALID_IDENTIFIER")
        return match.group(1), match.group(2)
    parts = identifier.split("@")
    if len(parts) > 2 or (len(parts) == 2 and not re.fullmatch(r"[1-9][0-9]{0,5}\.[0-9]{1,5}", parts[1])):
        raise ValueError("INVALID_IDENTIFIER")
    try:
        return _doi(parts[0], required=True), parts[1] if len(parts) == 2 else None
    except ValueError:
        raise ValueError("INVALID_IDENTIFIER") from None


def _related(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError("INVALID_RESPONSE")
    result = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("INVALID_RESPONSE")
        identifier = row.get("identifier")
        if isinstance(identifier, str) and DOI_RE.fullmatch(identifier):
            result.append({"identifier": identifier.lower(), "relation": _text(row.get("relation"), 100), "type": "doi"})
    return result


def _base(record_id, title, doi, version, license_value, access, files, official_url):
    return {"id": record_id, "title": _text(title, 2000, required=True), "doi": _doi(doi), "concept_doi": None,
            "version": _text(version, 200), "license": _license(license_value), "access": access, "files": files,
            "official_url": official_url, "related_identifiers": [], "detail_status": "RETRIEVED",
            "scientific_verdict": "NOT_ASSESSED", "approved": False}


def _zenodo(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("metadata"), dict):
        raise ValueError("INVALID_RESPONSE")
    record_id = _number(raw.get("id"), minimum=1)
    metadata = raw["metadata"]
    access = metadata.get("access_right")
    if access not in {"open", "embargoed", "restricted", "closed"}:
        raise ValueError("INVALID_RESPONSE")
    raw_files = raw.get("files", [])
    if not isinstance(raw_files, list) or len(raw_files) > 1000:
        raise ValueError("INVALID_RESPONSE")
    files = []
    for file in raw_files:
        if not isinstance(file, dict):
            raise ValueError("INVALID_RESPONSE")
        files.append({"id": _text(str(file["id"]), 200, required=True), "name": _text(file.get("key"), 1000, required=True),
                      "size": _number(file.get("size")), "checksum": _checksum(file.get("checksum"), origin="repository_computed"),
                      "supplied_checksum": None, "restricted": access != "open"})
    record = _base(str(record_id), metadata.get("title"), raw.get("doi", metadata.get("doi")), metadata.get("version"),
                   metadata.get("license"), {"metadata": "public", "files": access}, files, f"https://zenodo.org/records/{record_id}")
    record["concept_doi"] = _doi(raw.get("conceptdoi"))
    record["related_identifiers"] = _related(metadata.get("related_identifiers"))
    record["updated_at"] = _text(raw.get("updated"), 100)
    return record


def _figshare(raw):
    if not isinstance(raw, dict):
        raise ValueError("INVALID_RESPONSE")
    record_id = _number(raw.get("id"), minimum=1)
    version = _number(raw.get("version"), minimum=1)
    # [수정: 0 이영 · Codex] 2026-10-01 00:45 KST — 접근 플래그 누락을 공개 파일로 추론하지 않는다. 버전 0, 누락 응답 계약 시험으로 검증.
    flags = [raw.get("is_embargoed"), raw.get("is_confidential"), raw.get("download_disabled")]
    if any(flag is not None and type(flag) is not bool for flag in flags):
        raise ValueError("INVALID_RESPONSE")
    restricted = True if any(flags) else None if None in flags else False
    access = "restricted" if restricted is True else "NOT_CHECKED" if restricted is None else "public"
    raw_files = raw.get("files")
    if not isinstance(raw_files, list) or len(raw_files) > 1000:
        raise ValueError("INVALID_RESPONSE")
    files = []
    for file in raw_files:
        if not isinstance(file, dict) or type(file.get("is_link_only", False)) is not bool:
            raise ValueError("INVALID_RESPONSE")
        link_only = file.get("is_link_only", False)
        files.append({"id": str(_number(file.get("id"), minimum=1)), "name": _text(file.get("name"), 1000, required=True),
                      "size": _number(file.get("size")),
                      "checksum": _checksum(file.get("computed_md5"), "md5", origin="repository_computed"),
                      "supplied_checksum": _checksum(file.get("supplied_md5"), "md5", origin="uploader_supplied"),
                      "restricted": restricted, "link_only": link_only})
    record = _base(str(record_id), raw.get("title"), raw.get("doi"), str(version), raw.get("license"),
                   {"metadata": "public", "files": access}, files, f"https://figshare.com/articles/{record_id}/{version}")
    record["related_identifiers"] = _related(raw.get("related_materials"))
    legacy_doi = _doi(raw.get("resource_doi"))
    if legacy_doi:
        record["related_identifiers"].append({"identifier": legacy_doi, "relation": "legacy_resource_doi", "type": "doi"})
    record["updated_at"] = _text(raw.get("modified_date"), 100)
    return record


def _dataverse(raw, requested_doi):
    if not isinstance(raw, dict) or raw.get("status") != "OK" or not isinstance(raw.get("data"), dict):
        raise ValueError("INVALID_RESPONSE")
    dataset = raw["data"]
    version = dataset.get("latestVersion", dataset)
    if not isinstance(version, dict) or version.get("versionState") != "RELEASED":
        raise ValueError("UNPUBLISHED_VERSION")
    major = _number(version.get("versionNumber"), minimum=1)
    minor = _number(version.get("versionMinorNumber"))
    blocks = version.get("metadataBlocks")
    if not isinstance(blocks, dict) or not isinstance(blocks.get("citation"), dict):
        raise ValueError("INVALID_RESPONSE")
    fields = blocks["citation"].get("fields")
    if not isinstance(fields, list):
        raise ValueError("INVALID_RESPONSE")
    titles = [field.get("value") for field in fields if isinstance(field, dict) and field.get("typeName") == "title"]
    if len(titles) != 1:
        raise ValueError("INVALID_RESPONSE")
    doi = _doi(dataset.get("persistentUrl", version.get("datasetPersistentId", requested_doi)), required=True)
    if doi != requested_doi:
        raise ValueError("IDENTIFIER_MISMATCH")
    raw_files = version.get("files")
    if not isinstance(raw_files, list) or len(raw_files) > 1000:
        raise ValueError("INVALID_RESPONSE")
    files = []
    for item in raw_files:
        if not isinstance(item, dict) or type(item.get("restricted")) is not bool or not isinstance(item.get("dataFile"), dict):
            raise ValueError("INVALID_RESPONSE")
        file = item["dataFile"]
        checksum = file.get("checksum")
        if checksum is not None and not isinstance(checksum, dict):
            raise ValueError("INVALID_RESPONSE")
        checksum = _checksum(checksum.get("value"), checksum.get("type"), origin="repository_computed") if checksum else None
        files.append({"id": str(_number(file.get("id"), minimum=1)), "name": _text(file.get("filename"), 1000, required=True),
                      "size": _number(file.get("filesize")), "checksum": checksum, "supplied_checksum": None,
                      "restricted": item["restricted"], "content_type": _text(file.get("contentType"), 200)})
    internal_id = dataset.get("id", version.get("datasetId"))
    record_id = str(_number(internal_id, minimum=1)) if internal_id is not None else requested_doi
    record = _base(record_id, titles[0], doi, f"{major}.{minor}",
                   version.get("license"), {"metadata": "public", "files": "some_restricted" if any(x["restricted"] for x in files) else "public"},
                   files, "https://dataverse.harvard.edu/dataset.xhtml?" + urlencode({"persistentId": "doi:" + doi, "version": f"{major}.{minor}"}))
    record["custom_terms_present"] = bool(version.get("termsOfUse") or version.get("customTerms"))
    record["updated_at"] = _text(version.get("lastUpdateTime"), 100)
    return record


def repository_record(provider: str, identifier: str) -> dict:
    """ID/DOI lookup. Figshare .vN and Harvard DOI@N.M pin specific published versions."""
    try:
        record_id, requested_version = _input(provider, identifier)
    except ValueError as error:
        return _failure(provider if isinstance(provider, str) and provider in HOSTS else None, "record", str(error))
    if provider == "zenodo":
        path, params = "/api/records/" + record_id, None
    elif provider == "figshare":
        path = "/v2/articles/" + record_id + ("/versions/" + requested_version if requested_version else "")
        params = None
    else:
        path = "/api/datasets/:persistentId/" + ("versions/" + requested_version if requested_version else "")
        params = {"persistentId": "doi:" + record_id}
    response = _request(provider, path, params)
    if response.get("ok") is not True:
        return _failure(provider, "record", _error(response), response)
    try:
        data = response.get("data")
        record = _zenodo(data) if provider == "zenodo" else _figshare(data) if provider == "figshare" else _dataverse(data, record_id)
        if provider != "dataverse" and record["id"] != record_id:
            raise ValueError("IDENTIFIER_MISMATCH")
        if requested_version and record["version"] != requested_version:
            raise ValueError("VERSION_MISMATCH")
        # [수정: 0 이영 · Codex] 2026-10-01 00:45 KST — DOI로 조회한 경우 숫자 ID만 같고 DOI가 다른 응답을 배제한다. 버전 0, 충돌 응답 시험으로 검증.
        if identifier.lower().startswith("10.") and provider != "dataverse":
            expected_doi = identifier.lower()
            allowed_dois = {expected_doi}
            if provider == "figshare" and not requested_version:
                allowed_dois.add(expected_doi + ".v" + record["version"])
            if record["doi"] not in allowed_dois:
                raise ValueError("IDENTIFIER_MISMATCH")
        return _success(provider, "record", [record], response, 1)
    except (ValueError, KeyError, TypeError, IndexError):
        return _failure(provider, "record", "INVALID_RESPONSE", response)


def search_repository(provider: str, query: str, limit=5) -> dict:
    """Bounded candidate metadata. Figshare GET supports exact DOI search only."""
    if not isinstance(provider, str) or provider not in HOSTS:
        return _failure(None, "search", "INVALID_PROVIDER")
    if type(limit) is not int or not 1 <= limit <= 10 or not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        return _failure(provider, "search", "INVALID_QUERY_OR_LIMIT")
    if any(ord(c) < 32 or ord(c) == 127 for c in query) or EMAIL_RE.search(query) or re.search(r"https?://|file:|localhost|(?:api.?key|token|secret|password)\s*[=:]", query, re.I):
        return _failure(provider, "search", "INVALID_QUERY_OR_LIMIT")
    query = query.strip()
    if provider == "figshare":
        try:
            doi = _doi(query, required=True)
        except ValueError:
            return _failure(provider, "search", "SEARCH_REQUIRES_DOI")
        path, params = "/v2/articles", {"doi": doi, "page_size": limit}
    else:
        phrase = '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"'
        path, params = ("/api/records", {"q": phrase, "size": limit, "all_versions": "false"}) if provider == "zenodo" else ("/api/search", {"q": phrase, "type": "dataset", "per_page": limit})
    response = _request(provider, path, params)
    if response.get("ok") is not True:
        return _failure(provider, "search", _error(response), response)
    try:
        data = response.get("data")
        if provider == "zenodo":
            hits = data["hits"]
            total = hits["total"].get("value") if isinstance(hits.get("total"), dict) else hits["total"]
            rows = hits["hits"]
            records = [_zenodo(row) for row in rows] if isinstance(rows, list) and len(rows) <= limit else None
        elif provider == "figshare":
            if not isinstance(data, list) or len(data) > limit:
                raise ValueError("INVALID_RESPONSE")
            records = []
            for row in data:
                record = {"id": str(_number(row["id"], minimum=1)), "title": _text(row.get("title"), 2000, required=True), "doi": _doi(row.get("doi"), required=True),
                          "concept_doi": None, "version": None, "license": None, "access": {"metadata": "public", "files": "NOT_CHECKED"}, "files": [],
                          "official_url": "https://figshare.com/articles/" + str(row["id"]), "related_identifiers": [], "detail_status": "NOT_FETCHED", "scientific_verdict": "NOT_ASSESSED", "approved": False}
                if record["doi"] != doi:
                    raise ValueError("IDENTIFIER_MISMATCH")
                records.append(record)
            total = None
        else:
            if data.get("status") != "OK" or not isinstance(data.get("data"), dict):
                raise ValueError("INVALID_RESPONSE")
            result = data["data"]
            rows, total = result["items"], result["total_count"]
            if not isinstance(rows, list) or len(rows) > limit:
                raise ValueError("INVALID_RESPONSE")
            records = []
            for row in rows:
                doi = _doi(row.get("global_id"), required=True)
                major, minor = row.get("majorVersion"), row.get("minorVersion")
                version = f"{_number(major, minimum=1)}.{_number(minor)}" if major is not None and minor is not None else None
                records.append({"id": doi, "title": _text(row.get("name"), 2000, required=True), "doi": doi, "concept_doi": None, "version": version,
                                "license": None, "access": {"metadata": "public", "files": "NOT_CHECKED"}, "files": [],
                                "official_url": "https://dataverse.harvard.edu/dataset.xhtml?" + urlencode({"persistentId": "doi:" + doi}),
                                "related_identifiers": [], "detail_status": "NOT_FETCHED", "scientific_verdict": "NOT_ASSESSED", "approved": False})
        if records is None or (total is not None and _number(total) < len(records)):
            raise ValueError("INVALID_RESPONSE")
        return _success(provider, "search", records, response, total)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        return _failure(provider, "search", "INVALID_RESPONSE", response)
