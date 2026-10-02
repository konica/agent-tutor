"""RAG MCP server: streamable HTTP at :8000/mcp.

Tools ``search`` and ``get_chunk`` call knowledge.application (M1). JWTs are validated in code (PRD §9.3).
"""

from mcp.server import MCPServer

mcp = MCPServer("rag-mcp")


def main() -> None:
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
