"""Read-only DOI relations and JATS availability locations; all outputs are candidates.

Contracts: https://support.datacite.org/docs/queries
https://datacite-metadata-schema.readthedocs.io/en/4.6/properties/relatedidentifier/
https://europepmc.org/RestfulWebService
"""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 등록 관계의 방향과 원문 위치를 보존하고 사용 원자료·검산·승인을 자동 확정하지 않는다.
import hashlib
import json
import re
from urllib.parse import urlencode, unquote, urlsplit
import xml.etree.ElementTree as ET

from core import public_fulltext, research_data_sources
from core.research_web_search import SENSITIVE, envelope, now, safe_text, safe_url, strict_json

_CITATIONS = {"Cites", "IsCitedBy", "References", "IsReferencedBy"}
_VERSIONS = {"HasVersion", "IsVersionOf", "IsNewVersionOf", "IsPreviousVersionOf", "IsIdenticalTo"}
_RELATIONS = set("IsCitedBy Cites IsSupplementTo IsSupplementedBy IsContinuedBy Continues IsDescribedBy Describes HasMetadata IsMetadataFor HasVersion IsVersionOf IsNewVersionOf IsPreviousVersionOf IsPartOf HasPart IsPublishedIn IsReferencedBy References IsDocumentedBy Documents IsCompiledBy Compiles IsVariantFormOf IsOriginalFormOf IsIdenticalTo IsReviewedBy Reviews IsDerivedFrom IsSourceOf IsRequiredBy Requires IsObsoletedBy Obsoletes IsCollectedBy Collects IsTranslationOf HasTranslation".split())
_CC = re.compile(r"https?://creativecommons\.org/(?:licenses/(?:by|by-sa|by-nc|by-nd|by-nc-sa|by-nc-nd)/[1-4]\.0|publicdomain/zero/1\.0)/?")
_AVAILABILITY = re.compile(r"^(?:data (?:availability|accessibility|access)(?: statement)?|availability of (?:data|supporting data|data and materials)|data and materials availability|availability of data and materials)$", re.I)
_DOI_TEXT = re.compile(r"\b10\.\d{4,9}/[^\s<>\"\\]+", re.I)


def _validate(doi, limit):
    doi = public_fulltext._doi(doi)
    if SENSITIVE.search(doi) or any(c in doi for c in "?#<>") or len(doi) > 200:
        raise ValueError("INVALID_DOI")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("INVALID_LIMIT")
    return doi


def _canonical_doi(value):
    try:
        return _validate(value, 1)
    except (ValueError, TypeError):
        return None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _candidate(**values):
    return dict(values, candidate=True, used_as_raw_data=False, downloaded=False,
                verified=False, verification_pass=False, approved=False)


def _result(provider, operation, doi):
    result = envelope(provider, operation)
    result.update(doi=doi, candidate=True, received_metadata_sha256=None, source_identity_checked=False)
    result["limitations"].append("관계 등록·Data availability는 원자료 사용의 검증이나 계산 조건의 정답이 아닙니다. 사람의 원문·파일 확인이 필요합니다.")
    return result


def _error(result, code):
    result.update(status=code, error=code)
    return result


def datacite_relations(doi, limit=5):
    """Reverse-search registered DOI metadata pointing at the selected DOI.

    limit bounds records (one page); multiple exact edges per record are retained.
    Relation types always mean registered resource A -> related identifier B.
    The existing DataCite client discards raw bytes, so its canonical metadata
    digest is separate from response_sha256, which remains None.
    """
    doi = _validate(doi, limit)
    result = _result("datacite", "doi_relations", doi)
    path = "/dois?" + urlencode({"query": f'relatedIdentifiers.relatedIdentifier:"{doi}"', "page[size]": limit})
    result.update(source_url="https://api.datacite.org" + path, record_limit=limit,
                  metadata_sha256_scope="CANONICAL_PARSED_JSON", received_metadata_sha256_scope="CANONICAL_PARSED_JSON",
                  response_sha256_scope="UNAVAILABLE_IN_EXISTING_CLIENT")
    try:
        raw = research_data_sources._request("datacite", path)
        result["received_metadata_sha256"] = _digest(raw)
        rows = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(rows, list) or len(rows) > limit:
            return _error(result, "INVALID_RESPONSE")
        result.update(http_status=200, received_record_count=len(rows))
        seen, rejected = set(), 0
        for row_index, row in enumerate(rows):
            attrs = row.get("attributes") if isinstance(row, dict) else None
            if not isinstance(attrs, dict):
                rejected += 1
                continue
            source = _canonical_doi(attrs.get("doi"))
            related = attrs.get("relatedIdentifiers", [])
            if (not source or source != _canonical_doi(row.get("id")) or
                    not isinstance(related, list) or len(related) > 500):
                rejected += 1
                continue
            title_rows = attrs.get("titles", [])
            title = next((safe_text(r.get("title")) for r in title_rows if isinstance(r, dict) and safe_text(r.get("title"))), None) if isinstance(title_rows, list) and len(title_rows) <= 100 else None
            types = attrs.get("types") if isinstance(attrs.get("types"), dict) else {}
            version_edges = []
            for item_index, item in enumerate(related):
                if isinstance(item, dict) and item.get("relatedIdentifierType") == "DOI" and item.get("relationType") in _VERSIONS:
                    target = _canonical_doi(item.get("relatedIdentifier"))
                    if target:
                        version_edges.append(_candidate(source_doi=source, target_doi=target, relation_type=item["relationType"], direction="REGISTERED_RESOURCE_TO_RELATED_IDENTIFIER"))
            for item_index, item in enumerate(related):
                if (not isinstance(item, dict) or item.get("relatedIdentifierType") != "DOI" or
                        _canonical_doi(item.get("relatedIdentifier")) != doi):
                    continue
                relation = item.get("relationType")
                if relation not in _RELATIONS:
                    rejected += 1
                    continue
                identity = (source, doi, relation)
                if identity in seen:
                    continue
                seen.add(identity)
                classification = ("CITATION_ONLY" if relation in _CITATIONS else "VERSION_RELATION" if relation in _VERSIONS else
                                  "SUPPLEMENT_CANDIDATE" if relation in {"IsSupplementTo", "IsSupplementedBy"} else "REGISTERED_RELATION_CANDIDATE")
                result["items"].append(_candidate(
                    source_doi=source, target_doi=doi, relation_type=relation,
                    direction="REGISTERED_RESOURCE_TO_REQUESTED_DOI", classification=classification,
                    title=title, resource_type=safe_text(types.get("resourceTypeGeneral"), 100),
                    related_resource_type=safe_text(item.get("resourceTypeGeneral"), 100),
                    version=safe_text(attrs.get("version"), 100), version_relations=version_edges,
                    landing_url=safe_url(attrs.get("url")),
                    provenance={"provider": "datacite", "record_id": source,
                                "metadata_pointer": f"/data/{row_index}/attributes/relatedIdentifiers/{item_index}",
                                "source_url": result["source_url"],
                                "received_metadata_sha256": result["received_metadata_sha256"]}))
        result.update(ok=True, status="RELATION_CANDIDATES" if result["items"] else "NO_MATCH_IN_RETURNED_PAGE",
                      rejected_record_or_edge_count=rejected, source_identity_checked=bool(result["items"]), truncated=len(rows) == limit)
        result["limitations"].append("한 페이지에서 DOI가 정확히 일치하는 등록 관계만 반환합니다. 미조회·미등록 관계와 다른 페이지는 부재로 판정하지 않습니다.")
        return result
    except research_data_sources.DataSourceError as exc:
        return _error(result, exc.code)
    except (ValueError, TypeError, KeyError, OverflowError):
        return _error(result, "INVALID_RESPONSE")
    except Exception:
        return _error(result, "UNAVAILABLE")


def _tag(node):
    return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else ""


def _children(node, name):
    return [child for child in node if _tag(child) == name]


def _path_nodes(root, names):
    nodes = [root]
    for name in names:
        nodes = [child for node in nodes for child in _children(node, name)]
    return nodes


def _text(node):
    return " ".join("".join(node.itertext()).split())


def _xml_index(article):
    """Namespace-independent occurrence XPath, parent map and body paragraph index."""
    paths, parents, body_indices = {article: "/article[1]"}, {}, {}
    stack, count = [(article, 0, False)], 0
    while stack:
        node, depth, in_body = stack.pop()
        count += 1
        if depth > 100 or count > 100000:
            raise ValueError("FULLTEXT_STRUCTURE_TOO_LARGE")
        in_body = in_body or _tag(node) == "body"
        if in_body and _tag(node) == "p":
            body_indices[node] = len(body_indices) + 1
        occurrences, pending = {}, []
        for child in node:
            tag = _tag(child)
            occurrences[tag] = occurrences.get(tag, 0) + 1
            paths[child] = paths[node] + f"/{tag}[{occurrences[tag]}]"
            parents[child] = node
            pending.append((child, depth + 1, in_body))
        stack.extend(reversed(pending))
    return paths, parents, body_indices


def _availability(node):
    for key in ("sec-type", "content-type", "fn-type"):
        marker = node.get(key, "").replace("-", " ").replace("_", " ")
        if _AVAILABILITY.fullmatch(marker.strip()):
            return True
    for title in _children(node, "title") + _children(node, "meta-name"):
        if _AVAILABILITY.fullmatch(_text(title).rstrip(".: ")):
            return True
    if _tag(node) == "p":
        leading = _children(node, "bold") + _children(node, "label")
        return bool(leading and _AVAILABILITY.fullmatch(_text(leading[0]).rstrip(".: ")))
    return False


def _doi_link(url):
    parsed = urlsplit(url)
    return _canonical_doi(unquote(parsed.path.lstrip("/"))) if parsed.hostname in {"doi.org", "dx.doi.org"} else None


def _links(node, paths, references):
    links, seen = [], set()
    for element in node.iter():
        candidates = []
        if _tag(element) == "ext-link":
            href = next((value for key, value in element.attrib.items() if key.rsplit("}", 1)[-1] == "href"), None)
            url = safe_url(href)
            if url:
                candidates.append((url, _doi_link(url), "EXPLICIT_EXT_LINK", paths[element]))
        if _tag(element) == "pub-id" and element.get("pub-id-type") == "doi":
            doi = _canonical_doi(_text(element))
            if doi:
                candidates.append(("https://doi.org/" + doi, doi, "EXPLICIT_DOI_IDENTIFIER", paths[element]))
        if _tag(element) == "xref" and element.get("ref-type") == "bibr":
            for rid in element.get("rid", "").split()[:10]:
                ref = references.get(rid)
                if ref is not None:
                    for identifier in ref.iter():
                        if _tag(identifier) == "pub-id" and identifier.get("pub-id-type") == "doi":
                            doi = _canonical_doi(_text(identifier))
                            if doi:
                                candidates.append(("https://doi.org/" + doi, doi, "AVAILABILITY_REFERENCE_DOI", paths[identifier]))
        for url, doi, kind, path in candidates:
            if url in seen:
                continue
            seen.add(url)
            links.append(_candidate(url=url, doi=doi, extraction=kind, source_xpath=path))
    # Text DOI occurrences are labelled separately; punctuation trimming is only a candidate heuristic.
    for match in _DOI_TEXT.finditer(_text(node)[:20000]):
        doi = _canonical_doi(match.group().rstrip(".,;:)]}"))
        url = "https://doi.org/" + doi if doi else None
        if url and url not in seen:
            seen.add(url)
            links.append(_candidate(url=url, doi=doi, extraction="TEXT_DOI_CANDIDATE", source_xpath=paths[node]))
    return links[:20]


def jats_data_availability(doi, limit=5, include_source_bytes=False):
    """Fetch exact DOI OA JATS and locate explicit availability statements.

    No arbitrary discovered link is fetched. XML identity and explicit CC licence
    are required before returning snippets. An xref is followed only from a
    selected availability statement, never from general bibliography alone.

    include_source_bytes is a strict bool, default False. When True, licensed
    identity-checked raw XML is returned only as internal source_bytes for
    evidence agreement checks. Callers must exclude bytes from UI/JSON/logs;
    public_source_receipt contains only fixed-origin metadata and the raw SHA.
    """
    # [수정: 0 이영 · Codex] 2026-10-01 KST — 명시 옵션과 ID·CC 검사 뒤에만 원문 바이트를 내부 증거 검사용으로 전달하며 자동 공개·승인은 하지 않는다.
    if type(include_source_bytes) is not bool:
        raise ValueError("INVALID_SOURCE_BYTES_OPTION")
    doi = _validate(doi, limit)
    result = _result("europepmc", "jats_data_availability", doi)
    # [수정: 0 이영 · Codex] 2026-10-01 KST — 기존 원문 client가 상태코드를 반환하지 않으므로 성공을 HTTP200으로 지어내지 않는다.
    result.update(pmcid=None, license=None, public_source_receipt=None, response_sha256_scope="HTTP_BODY",
                  http_status_scope="UNAVAILABLE_IN_EXISTING_CLIENT", received_metadata_sha256_scope="HTTP_BODY")
    search_url = public_fulltext.BASE + "search?" + urlencode({"query": f'DOI:"{doi}" AND OPEN_ACCESS:Y', "format": "json", "resultType": "core", "pageSize": 10})
    result["metadata_source_url"] = search_url
    try:
        metadata_bytes = public_fulltext._read(search_url)
        metadata = strict_json(metadata_bytes)
        result["received_metadata_sha256"] = hashlib.sha256(metadata_bytes).hexdigest()
        rows = metadata.get("resultList", {}).get("result", []) if isinstance(metadata, dict) else None
        if not isinstance(rows, list) or len(rows) > 10:
            return _error(result, "FULLTEXT_INVALID_METADATA")
        ids = {r["pmcid"] for r in rows if isinstance(r, dict) and _canonical_doi(r.get("doi")) == doi and
               r.get("isOpenAccess") == "Y" and isinstance(r.get("pmcid"), str) and re.fullmatch(r"PMC\d+", r["pmcid"])}
        if not ids:
            result.update(ok=True, status="NOT_AVAILABLE")
            return result
        if len(ids) != 1:
            return _error(result, "FULLTEXT_AMBIGUOUS_DOI")
        pmcid = next(iter(ids))
        url = public_fulltext.BASE + pmcid + "/fullTextXML"
        raw = public_fulltext._read(url)
        source_received_at = now()
        if len(raw) > public_fulltext.MAX_RESPONSE_BYTES:
            return _error(result, "FULLTEXT_RESPONSE_TOO_LARGE")
        result.update(source_url=url, pmcid=pmcid, response_sha256=hashlib.sha256(raw).hexdigest())
        xml = raw.decode("utf-8-sig")
        if "<!ENTITY" in xml.upper() or re.search(r"<!DOCTYPE[^>]*\[", xml, re.I):
            return _error(result, "FULLTEXT_UNSAFE_XML")
        article = ET.fromstring(xml)
        if _tag(article) != "article":
            return _error(result, "FULLTEXT_INVALID_XML")
        paths, parents, body_indices = _xml_index(article)
        article_ids = _path_nodes(article, ("front", "article-meta", "article-id"))
        dois = {_canonical_doi(_text(n)) for n in article_ids if n.get("pub-id-type") == "doi"}
        pmcs = {_text(n).removeprefix("PMC") for n in article_ids if n.get("pub-id-type") in {"pmc", "pmcid"}}
        if dois != {doi} or pmcs != {pmcid[3:]}:
            return _error(result, "FULLTEXT_ID_MISMATCH")
        result["source_identity_checked"] = True
        for licence in _path_nodes(article, ("front", "article-meta", "permissions", "license")):
            for node in licence.iter():
                for value in node.attrib.values():
                    if _CC.fullmatch(value):
                        result["license"] = value
        if not result["license"]:
            result["status"] = "LICENSE_UNCONFIRMED"
            return result
        references = {}
        for node in article.iter():
            if _tag(node) == "ref" and node.get("id"):
                rid = node.get("id")
                # Duplicate reference IDs are ambiguous and never resolved.
                references[rid] = node if rid not in references else None
        selected, blocked = [], 0
        for node in article.iter():
            if not _availability(node):
                continue
            cursor, nested, in_refs = parents.get(node), False, False
            while cursor is not None:
                nested = nested or cursor in selected
                in_refs = in_refs or _tag(cursor) == "ref-list"
                cursor = parents.get(cursor)
            if nested or in_refs:
                continue
            selected.append(node)
            snippet = safe_text(_text(node), 1500)
            if not snippet:
                blocked += 1
                continue
            paragraphs = [n for n in node.iter() if n in body_indices]
            title = next((safe_text(_text(n), 200) for n in _children(node, "title") if safe_text(_text(n), 200)), None)
            location = {"xpath": paths[node], "element_id": safe_text(node.get("id"), 100),
                        "section_title": title, "body_paragraph_indices": [body_indices[p] for p in paragraphs]}
            links = _links(node, paths, references)
            result["items"].append(_candidate(
                id="availability-" + hashlib.sha256((doi + "\n" + paths[node] + "\n" + result["response_sha256"]).encode()).hexdigest()[:20],
                doi=doi, pmcid=pmcid, location=location, text=snippet, text_truncated=len(_text(node)) > 1500,
                links=links, relation_type="DATA_AVAILABILITY_STATEMENT_CANDIDATE",
                provenance={"provider": "europepmc", "source_url": url, "response_sha256": result["response_sha256"], "license": result["license"]}))
            if len(result["items"]) >= limit:
                break
        result.update(ok=True, status="AVAILABILITY_CANDIDATES" if result["items"] else "SENSITIVE_STATEMENTS_SUPPRESSED" if blocked else "NO_EXPLICIT_AVAILABILITY_STATEMENT",
                      suppressed_sensitive_statement_count=blocked, truncated=len(result["items"]) == limit)
        result.update(source_kind="LICENSED_JATS_RECEIVED", public_source_receipt={
            "type": "JATS_XML", "schema": "research_public_source_receipt/1",
            "url": url, "doi": doi, "pmcid": pmcid, "license": result["license"],
            "sha256": result["response_sha256"], "received_at": source_received_at})
        if include_source_bytes:
            result["source_bytes"] = raw
        result["limitations"].append("명시된 Data availability 절과 그 링크만 추출합니다. 일반 참고문헌·다른 본문 위치·비 OA 원문 전체를 포괄하지 않습니다.")
        return result
    except (ET.ParseError, UnicodeError):
        return _error(result, "FULLTEXT_INVALID_XML")
    except ValueError as exc:
        code = str(exc)
        return _error(result, code if code in {"FULLTEXT_REDIRECT_BLOCKED", "FULLTEXT_URL_BLOCKED", "FULLTEXT_RESPONSE_TOO_LARGE", "FULLTEXT_STRUCTURE_TOO_LARGE"} else "INVALID_RESPONSE")
    except (TypeError, KeyError, AttributeError, OverflowError):
        return _error(result, "INVALID_RESPONSE")
    except TimeoutError:
        return _error(result, "TIMEOUT")
    except Exception:
        return _error(result, "UNAVAILABLE")
