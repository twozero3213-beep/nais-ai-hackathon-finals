"""Read-only publication updates and PubMed identity metadata, without a verdict."""
# [작성: 0 이영 · Codex] 2026-10-01 00:32 KST — 기존 watch의 역방향 정정·철회 누락을 보완한다.
# 공식 상태·출처·발행일과 실제 조회 시각을 구분하며 원문·저자·이메일·댓글은 반환하지 않는다.
import re
from urllib.parse import quote
import xml.etree.ElementTree as ET

from core.integration_http import get_json, get_xml

MAX_ITEMS = 30
MAX_NOTICE_LOOKUPS = 3
_DOI = re.compile(r"10\.\d{4,9}/[A-Za-z0-9][A-Za-z0-9._;()/:+\-]*\Z")
_PMID = re.compile(r"[1-9]\d{0,9}\Z")
_SENSITIVE = re.compile(r"(?:sk-(?:proj-)?[\w-]{20,}|gh[pousr]_[\w]{20,}|AIza[\w-]{25,}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})")
_PROVENANCE = ("http_status", "source_url", "retrieved_at_kst", "response_sha256", "cached")
_REF_TYPES = {
    "ErratumIn": "correction", "ErratumFor": "correction",
    "RetractionIn": "retraction", "RetractionOf": "retraction",
    "ExpressionOfConcernIn": "expression-of-concern", "ExpressionOfConcernFor": "expression-of-concern",
    "CorrectedandRepublishedIn": "corrected-and-republished", "CorrectedandRepublishedFrom": "corrected-and-republished",
    "RetractedandRepublishedIn": "retracted-and-republished", "RetractedandRepublishedFrom": "retracted-and-republished",
    "UpdateIn": "update", "UpdateOf": "update",
    "PartialRetractionIn": "partial-retraction", "PartialRetractionOf": "partial-retraction",
}
OFFICIAL_SOURCES = {
    "crossref_updates": "https://www.crossref.org/documentation/register-maintain-records/maintaining-your-metadata/registering-updates/",
    "retraction_watch": "https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/",
    "crossref_production": "https://www.crossref.org/labs/retraction-watch/",
    "pubmed_efetch": "https://www.ncbi.nlm.nih.gov/books/NBK25499/",
    "pubmed_relations": "https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/230101/el-CommentsCorrections.html",
}


def _doi(value):
    if not isinstance(value, str) or len(value) > 200 or not _DOI.fullmatch(value) or _SENSITIVE.search(value):
        raise ValueError("INVALID_DOI")
    return value.lower()


def _pmid(value):
    if not isinstance(value, str) or not _PMID.fullmatch(value):
        raise ValueError("INVALID_PMID")
    return value


def _text(value, limit=120):
    if not isinstance(value, str) or len(value) > limit or _SENSITIVE.search(value) or any(ord(c) < 32 for c in value):
        return None
    return value


def _result(identifier, envelope=None):
    result = {"ok": False, "error": None, "semantic_status": "LOOKUP_FAILED", **identifier,
              "verification_pass": False, "retraction_absence_proven": False,
              "limitations": ["갱신 메타데이터 미검출은 철회 없음이나 수치 검산 PASS를 증명하지 않습니다."],
              "warnings": []}
    # Preserve transport provenance, never copy its raw data into the public result.
    result.update({key: None for key in _PROVENANCE})
    if envelope is not None:
        result.update({key: envelope.get(key) for key in _PROVENANCE})
    return result


def _date(value):
    if not isinstance(value, dict):
        return None
    selected = {}
    parts = value.get("date-parts")
    if isinstance(parts, list) and len(parts) <= 3 and all(isinstance(row, list) and 1 <= len(row) <= 3 and all(type(x) is int for x in row) for row in parts):
        selected["date-parts"] = parts
    text = _text(value.get("date-time"), 50)
    if text is not None:
        selected["date-time"] = text
    if type(value.get("timestamp")) is int:
        selected["timestamp"] = value["timestamp"]
    return selected or None


def _updates(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("INVALID_UPDATE_METADATA")
    selected = []
    for item in value[:MAX_ITEMS]:
        event = {}
        for field in ("DOI", "type", "source", "label"):
            text = _text(item.get(field), 200 if field in ("DOI", "label") else 80)
            if text is not None:
                event[field] = text
        if "DOI" in event:
            try:
                _doi(event["DOI"])
            except ValueError:
                event.pop("DOI")
        date = _date(item.get("updated"))
        if date is not None:
            event["updated"] = date
        if type(item.get("record-id")) is int or _text(item.get("record-id"), 30) is not None:
            event["record-id"] = item["record-id"]
        if event:
            selected.append(event)
    return selected


def _relations(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("INVALID_RELATION_METADATA")
    result = {}
    for name, records in list(value.items())[:MAX_ITEMS]:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z-]{1,60}", name) or not isinstance(records, list):
            raise ValueError("INVALID_RELATION_METADATA")
        selected = []
        for item in records[:MAX_ITEMS]:
            if not isinstance(item, dict):
                raise ValueError("INVALID_RELATION_METADATA")
            if item.get("id-type") != "doi":
                continue
            try:
                _doi(item.get("id"))
            except ValueError:
                continue
            record = {"id-type": "doi", "id": item["id"]}
            if _text(item.get("asserted-by"), 50) is not None:
                record["asserted-by"] = item["asserted-by"]
            selected.append(record)
        if selected:
            result[name] = selected
    return result


def _work(envelope, requested_doi):
    if not envelope.get("ok"):
        raise ValueError(envelope.get("error") or "LOOKUP_FAILED")
    payload = envelope.get("data")
    if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("message"), dict):
        raise ValueError("INVALID_CROSSREF_RESPONSE")
    item = payload["message"]
    if _doi(item.get("DOI")) != requested_doi:
        raise ValueError("DOI_IDENTITY_MISMATCH")
    return item


def publication_updates(doi: str) -> dict:
    """Keep update-to (notice -> work) and updated-by (work -> notice) distinct."""
    result = _result({})
    try:
        canonical = _doi(doi)
    except ValueError as exc:
        result["error"] = str(exc)
        return result
    envelope = get_json("api.crossref.org", "/works/" + quote(canonical, safe=""))
    result = _result({"doi": canonical}, envelope)
    try:
        item = _work(envelope, canonical)
        update_to = _updates(item.get("update-to"))
        updated_by = _updates(item.get("updated-by"))
        relations = _relations(item.get("relation"))
        result.update(ok=True, update_to=update_to, updated_by=updated_by, relations=relations, notices=[])
        result["metadata_update_dates"] = {field: _date(item[field]) for field in ("indexed", "deposited", "created") if isinstance(item.get(field), dict)}
        candidates = list(dict.fromkeys(_doi(event["DOI"]) for event in updated_by if "DOI" in event and _doi(event["DOI"]) != canonical))
        for notice_doi in candidates[:MAX_NOTICE_LOOKUPS]:
            notice_envelope = get_json("api.crossref.org", "/works/" + quote(notice_doi, safe=""))
            notice = {"doi": notice_doi, "identity_verified": False, "links_to_requested_doi": False,
                      "error": None, **{key: notice_envelope.get(key) for key in _PROVENANCE}}
            try:
                notice_item = _work(notice_envelope, notice_doi)
                notice_updates = _updates(notice_item.get("update-to"))
                notice.update(identity_verified=True, update_to=notice_updates,
                              links_to_requested_doi=any("DOI" in event and _doi(event["DOI"]) == canonical for event in notice_updates))
            except ValueError as exc:
                notice["error"] = str(exc)
            result["notices"].append(notice)
        result["notice_lookup_truncated"] = len(candidates) > MAX_NOTICE_LOOKUPS
        result["update_metadata_truncated"] = any(isinstance(item.get(field), list) and len(item[field]) > MAX_ITEMS for field in ("update-to", "updated-by"))
        result["semantic_status"] = "UPDATE_METADATA_FOUND" if update_to or updated_by else "NO_UPDATE_METADATA_FOUND"
        result["limitations"] = ["갱신 메타데이터 미검출은 철회 없음이나 수치 검산 PASS를 증명하지 않습니다.",
                                 "update-to는 이 DOI에서 갱신 대상 논문으로, updated-by는 이 DOI에서 갱신 공지로 향합니다.",
                                 "indexed·deposited·created는 서지 레코드 날짜이며 철회 발행일이 아닙니다.",
                                 "Retraction Watch의 정정·우려 표명은 철회만큼 포괄적이지 않습니다."]
    except ValueError as exc:
        result.update(ok=False, error=str(exc), semantic_status="LOOKUP_FAILED")
    return result


def _tag(element):
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def _children(element, name):
    return [child for child in element if _tag(child) == name] if element is not None else []


def _find(element, *names):
    for name in names:
        matches = _children(element, name)
        element = matches[0] if matches else None
    return element


def _element_text(element, limit=600):
    return _text("".join(element.itertext()), limit) if element is not None else None


def _xml_date(element):
    return {field: value for field in ("Year", "Month", "Day", "Season", "MedlineDate")
            if (value := _element_text(_find(element, field), 60)) is not None}


def pubmed_record(pmid: str) -> dict:
    """Return only exact-identity EFetch metadata and explicit corrections relations."""
    result = _result({})
    try:
        canonical = _pmid(pmid)
    except ValueError as exc:
        result["error"] = str(exc)
        return result
    envelope = get_xml("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/efetch.fcgi",
                       {"db": "pubmed", "id": canonical, "retmode": "xml", "tool": "NAIS_EvidenceGate"})
    result = _result({"pmid": canonical}, envelope)
    if not envelope.get("ok"):
        result["error"] = envelope.get("error") or "LOOKUP_FAILED"
        return result
    root = envelope.get("data")
    if not isinstance(root, ET.Element) or _tag(root) != "PubmedArticleSet" or any(_tag(e).lower() == "error" for e in root.iter()):
        result["error"] = "INVALID_PUBMED_RESPONSE"
        return result
    articles = [e for e in root if _tag(e) in ("PubmedArticle", "PubmedBookArticle")]
    if len(articles) != 1:
        result["error"] = "PUBMED_RECORD_COUNT_MISMATCH"
        return result
    article = articles[0]
    book = _tag(article) == "PubmedBookArticle"
    citation = _find(article, "BookDocument" if book else "MedlineCitation")
    if _element_text(_find(citation, "PMID"), 10) != canonical:
        result["error"] = "PMID_IDENTITY_MISMATCH"
        return result
    data = _find(article, "PubmedBookData" if book else "PubmedData")
    all_ids = _children(_find(data, "ArticleIdList"), "ArticleId")
    ids = all_ids[:MAX_ITEMS]
    if any(e.get("IdType") == "pubmed" and _element_text(e, 10) != canonical for e in ids):
        result["error"] = "PMID_IDENTITY_MISMATCH"
        return result
    dois, pmc_ids = [], []
    for identifier in ids:
        value = _element_text(identifier, 200)
        if identifier.get("IdType") == "doi":
            try:
                dois.append(_doi(value))
            except ValueError:
                result["warnings"].append("INVALID_DOI_IDENTIFIER_OMITTED")
        elif identifier.get("IdType") == "pmc" and isinstance(value, str) and re.fullmatch(r"PMC[1-9]\d{0,11}", value):
            pmc_ids.append(value)
    content = citation if book else _find(citation, "Article")
    for identifier in _children(content, "ELocationID"):
        if identifier.get("EIdType") == "doi" and identifier.get("ValidYN", "Y") == "Y":
            try:
                dois.append(_doi(_element_text(identifier, 200)))
            except ValueError:
                result["warnings"].append("INVALID_DOI_IDENTIFIER_OMITTED")
    relations = []
    all_relations = _children(_find(citation, "CommentsCorrectionsList"), "CommentsCorrections")
    for relation in all_relations[:MAX_ITEMS]:
        kind = relation.get("RefType")
        if kind not in _REF_TYPES:
            continue
        target = _element_text(_find(relation, "PMID"), 10)
        selected = {"ref_type": kind, "category": _REF_TYPES[kind]}
        if target is not None and _PMID.fullmatch(target):
            selected.update(pmid=target, source_url="https://pubmed.ncbi.nlm.nih.gov/" + target + "/")
        relations.append(selected)
    types = [_element_text(e, 100) for e in _children(_find(content, "PublicationTypeList"), "PublicationType")[:MAX_ITEMS]]
    types = [value for value in types if value is not None]
    signals = {"Retracted Publication", "Retraction of Publication", "Published Erratum", "Expression of Concern", "Corrected and Republished Article"}
    result.update(ok=True, title=_element_text(_find(content, "ArticleTitle")),
                  dois=list(dict.fromkeys(dois)), pmc_ids=list(dict.fromkeys(pmc_ids)),
                  publication_types=types, comments_corrections=relations,
                  record_fields_truncated=len(all_ids) > MAX_ITEMS or len(all_relations) > MAX_ITEMS,
                  publication_date=_xml_date(_find(content, "Journal", "JournalIssue", "PubDate")),
                  index_revision_date=_xml_date(_find(citation, "DateRevised")),
                  semantic_status="UPDATE_METADATA_FOUND" if relations or signals.intersection(types) else "NO_UPDATE_METADATA_FOUND")
    result["limitations"] = ["갱신 메타데이터 미검출은 철회 없음이나 수치 검산 PASS를 증명하지 않습니다.",
                             "CommentsCorrections의 RefType 방향을 유지합니다. 발행일·서지 개정일만으로 철회를 판정하지 않습니다.",
                             "PubMed 수록 범위의 메타데이터입니다. 원문·전문 조회, 수치 재계산, 승인은 실행하지 않습니다."]
    return result
