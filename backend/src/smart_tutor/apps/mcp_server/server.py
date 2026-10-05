"""RAG MCP server: streamable HTTP at :8000/mcp (SMART_TUTOR_MCP_PORT; 10452 on the host).

Tools ``search`` and ``get_chunk`` call knowledge.application (M1). JWTs are validated in code (PRD §9.3).
"""

from mcp.server import MCPServer

from smart_tutor.shared.config import Settings

mcp = MCPServer("rag-mcp")


def main() -> None:
    mcp.run(transport="streamable-http", host="0.0.0.0", port=Settings().mcp_port)


if __name__ == "__main__":
    main()
