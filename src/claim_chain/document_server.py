"""MCP stdio server for local document evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .documents import DocumentStore


def create_server(store: DocumentStore) -> FastMCP:
    server = FastMCP("claim-chain-documents")

    @server.tool()
    def list_sources() -> dict[str, Any]:
        """List available document sources."""
        return store.list_sources()

    @server.tool()
    def search_source(source_id: str, query: str, limit: int = 5) -> dict[str, Any]:
        """Find matching chunk snippets without opening full evidence."""
        return store.search_source(source_id, query, limit)

    @server.tool()
    def read_source(source_id: str, start: int = 1, count: int = 1) -> dict[str, Any]:
        """Read numbered source chunks as full evidence passages."""
        return store.read_source(source_id, start, count)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a local document archive over MCP stdio.")
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    create_server(DocumentStore(args.documents, args.archive)).run(transport="stdio")


if __name__ == "__main__":
    main()
