"""Read-only data catalogue MCP; run with the project's pinned mcp==2.2.0."""
from pathlib import Path
import sys
from typing import Annotated, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp.server import MCPServer
from pydantic import Field

# case105: reuse the same adapter; Korea's fixed POST is metadata search only.
server = MCPServer('NAIS Public Research Data', version='105', instructions='Read-only fixed public HTTPS APIs, including the Korea portal POST-only metadata search. Queries leave this process. No user URLs, paid models, asset downloads, private coordinates or approvals.')


@server.tool()
def source_catalog() -> dict[str, object]:
    """List sources and configuration state; this does not trigger a network call."""
    from core.research_data_sources import source_catalog as catalog
    return {'version': '105', 'sources': catalog(), 'approved': False}


@server.tool()
def search_research_data(
        source: Literal['nasa_cmr', 'earth_search', 'world_bank', 'usgs', 'datacite', 'data_gov', 'korea_data', 'kci', 'aida'],
        query: Annotated[str, Field(max_length=300)] = '',
        limit: Annotated[int, Field(strict=True, ge=1, le=10)] = 5,
        mode: Literal['catalog', 'items', 'observations'] = 'catalog',
        collection: Literal['sentinel-2-l2a', 'sentinel-2-c1-l2a', 'landsat-c2-l2'] = 'sentinel-2-l2a',
        region: Literal['global', 'korea'] = 'global',
        indicator: Literal['SP.POP.TOTL', 'NY.GDP.MKTP.CD', 'SP.DYN.LE00.IN'] = 'SP.POP.TOTL',
        days: Annotated[int, Field(strict=True, ge=1, le=30)] = 7) -> dict[str, object]:
    """Bounded metadata or USGS/World Bank observations. No imagery download."""
    from core.research_data_sources import search_research_data as search
    return search(source, query, limit, mode=mode, collection=collection, region=region, indicator=indicator, days=days)


if __name__ == '__main__':
    server.run(transport='stdio')
