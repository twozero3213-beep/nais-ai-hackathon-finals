# 작성: case95 등록사례·MCP 담당 | 2026-09-29 | 역할: 검색과 고정 등록사례 재검산만 stdio 노출
# 왜: 제품의 재사용 기능 연결 | 입력: query/limit, case_id Literal | 검증: case93 회귀 및 test_case95_cases_mcp 공식 Client
"""case95 read-only MCP stdio facade over bounded local research operations."""
from pathlib import Path
import sys
from typing import Annotated, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import Field
from mcp.server import MCPServer

server = MCPServer(
    "NAIS Evidence Gate",
    version=(Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip(),
    instructions="Read-only evidence search and fixed registered arithmetic cases.",
)


@server.tool()
def capabilities() -> dict[str, object]:
    """Describe available tools and their fixed local-only boundaries."""
    from core.research_cases import list_cases

    return {
        "version": (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip(),
        "transport": "stdio",
        "read_only_data": True,
        "calculations_allowed": True,
        "approvals": False,
        "tools": ["search_evidence", "registered_arithmetic", "capabilities"],
        "cases": list_cases(include_extensions=True),
        "search_evidence": {
            "input": {"query": "non-empty text (max 300 chars)", "limit": "integer 1–5"},
            "output": "results with id, text, doi, locator",
            "source": "validated local corpus",
        },
        "boundaries": ["fixed registered case only", "no arbitrary paths", "no network", "no SQL or shell", "no data writes or approvals"],
    }


@server.tool()
def search_evidence(
    query: Annotated[str, Field(min_length=1, max_length=300)],
    limit: Annotated[int, Field(ge=1, le=5)] = 5,
) -> dict[str, object]:
    """Search validated local evidence; returns at most five located records."""
    from core.research_agent import search_evidence as search_local

    records = search_local(query=query, limit=limit)
    return {"results": records}


# case95: run one fixed catalog ID via its existing guarded engine; return only bounded common result fields.
@server.tool()
def registered_arithmetic(case_id: Literal["n3_11814", "public_penguins", "public_bat", "public_covid_fair", "public_forest"]) -> dict[str, object]:
    """Re-run one fixed registered case; arithmetic agreement never means approval."""
    from core.research_cases import run_case

    return run_case(case_id)


if __name__ == "__main__":
    server.run(transport="stdio")
