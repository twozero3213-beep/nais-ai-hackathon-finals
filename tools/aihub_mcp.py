"""NAIS read-only AI Hub metadata MCP adapter; not the official Java server."""
from pathlib import Path
import sys
from typing import Annotated
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pydantic import Field
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

server = MCPServer('NAIS AI Hub Dataset Discovery', version=(Path(__file__).resolve().parents[1]/'VERSION').read_text(encoding='utf-8').strip(),  # [수정: 0 이영] 2026-09-30 22:01 KST — 사전 '95' 하드코딩 대신 VERSION 단일 출처.
    instructions='Read-only metadata from official AI Hub endpoints. Public research queries only. No dataset download, model training, or approval. Dataset views are not paper views.')


# [작성: 연결 담당] case95 / 웹과 동일한 검증된 API 함수를 사용하고 키는 프로세스 환경에서만 읽는다.
@server.tool()
def find_research_datasets(query: Annotated[str, Field(min_length=1, max_length=200,strict=True)],
                           limit: Annotated[int, Field(ge=1, le=10,strict=True)] = 5) -> dict[str, object]:
    """Search AI Hub dataset metadata, with source links and unknown approval status."""
    from core.aihub import AIHubError, search_datasets
    try:return search_datasets(query, limit=limit)
    except AIHubError as error:raise ToolError(error.code) from None


@server.tool()
def research_dataset_details(dataset_id: Annotated[int, Field(ge=1, le=99999999,strict=True)]) -> dict[str, object]:
    """Read allowlisted dataset metadata; never fetch files or approve use."""
    from core.aihub import AIHubError, get_dataset
    try:return get_dataset(dataset_id)
    except AIHubError as error:raise ToolError(error.code) from None


# case95 2026-09-29 / pinned MCP2.2.0 generated Pydantic argument models:
# validation errors must not echo caller-provided secret strings. Keep integer
# schemas/strict validation and hide input values rather than relaxing bounds.
for tool in server._tool_manager._tools.values():
    tool.fn_metadata.arg_model.model_config['hide_input_in_errors']=True
    tool.fn_metadata.arg_model.model_rebuild(force=True)


if __name__ == '__main__':
    server.run(transport='stdio')
