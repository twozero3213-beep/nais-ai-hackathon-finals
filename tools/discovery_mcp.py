"""Read-only, public-network discovery MCP. Separate from offline verification MCP."""
from pathlib import Path
import sys
from typing import Annotated, Literal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pydantic import Field
from mcp.server import MCPServer

server=MCPServer('NAIS Public Research Discovery',version='95',
    instructions='Read-only public metadata. Sends search queries to fixed scholarly APIs. No private text, secrets, paid models, downloads of full text, or approval.')


# [작성: MCP 연결 담당] 2026-09-29 case95 / UI와 같은 출처·결과 재사용, 오프라인 기존 MCP 계약 보존.
@server.tool()
def source_catalog() -> dict[str, object]:
    """List scholarly APIs, official university feeds and available field starting points."""
    from core.research_fields import FIELDS
    from core.research_news import SOURCES
    return {'version':'95','apis':['Crossref','OpenAlex','Europe PMC'],
        'feeds':{key:{'label':value['label'],'url':value['url']} for key,value in SOURCES.items()},
        'fields':FIELDS,'network':'public metadata GET only; queries leave this process',
        'boundaries':['no arbitrary URLs','no write tools','no paid models','metadata is not evidence approval']}


@server.tool()
def discover_papers(query:Annotated[str,Field(min_length=1,max_length=300)],
        mode:Literal['latest','cited']='latest',years:Literal[1,3]=1,
        limit:Annotated[int,Field(ge=1,le=8)]=8) -> dict[str, object]:
    """Search public metadata with bounded provider fallback; citation scopes stay separate."""
    from core.paper_sources import search_resilient
    return search_resilient(query,mode=mode,years=years,limit=limit)


@server.tool()
def university_news(source:Literal['mit','kaist','harvard']='mit') -> dict[str, object]:
    """Fetch up to eight metadata records from one official university RSS/API."""
    from core.research_news import fetch_research_news
    return fetch_research_news(source)


@server.tool()
def scheduled_research() -> dict[str, object]:
    """Read last saved snapshot, including timestamps and failures. Does not trigger collection."""
    from core.research_digest_remote import load_digest
    digest,source,error=load_digest()
    return {'snapshot':digest,'source':source,'error':error,'approved':False}


if __name__=='__main__':server.run(transport='stdio')
