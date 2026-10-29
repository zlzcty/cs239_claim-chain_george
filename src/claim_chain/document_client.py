"""MCP document connection and evidence scoped to one agent conversation."""

import json
import sys
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai.types.chat import ChatCompletionToolUnionParam

from .models import Passage, Source


@asynccontextmanager
async def connect_documents(directory: Path, archive: Path) -> AsyncIterator[ClientSession]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "claim_chain.document_server", "--documents", str(directory.resolve()),
              "--archive", str(archive.resolve())],
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


async def call_document_tool(
    session: ClientSession, name: str, arguments: dict[str, object]
) -> dict[str, object]:
    result = await session.call_tool(name, arguments)
    if result.isError:
        raise ValueError(str(result.content))
    if result.structuredContent is not None:
        return result.structuredContent
    text = "".join(block.text for block in result.content if block.type == "text")
    value: object = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Document tool must return an object.")
    return cast(dict[str, object], value)


class DocumentTools:
    def __init__(
        self, session: ClientSession, definitions: list[ChatCompletionToolUnionParam],
        allowed: Collection[str],
    ) -> None:
        self.session = session
        self.definitions = definitions
        self.allowed = frozenset(allowed)
        self.opened: dict[str, dict[str, Passage]] = {}

    async def execute(self, name: str, arguments: str) -> str:
        value: object = json.loads(arguments)
        if not isinstance(value, dict):
            raise ValueError("Tool arguments must be an object.")
        args = cast(dict[str, object], value)
        if name not in {"list_sources", "search_source", "read_source"}:
            raise ValueError("Unknown document tool.")
        if name != "list_sources" and args.get("source_id") not in self.allowed:
            raise ValueError("Read only sources assigned to this task.")
        result = await call_document_tool(self.session, name, args)
        if name == "read_source":
            passages = result.get("passages", [])
            if not isinstance(passages, list):
                raise ValueError("Invalid passage response.")
            for item in passages:
                if not isinstance(item, dict):
                    raise ValueError("Invalid passage record.")
                passage = Passage(
                    id=str(item["id"]), locator=str(item["locator"]), text=str(item["text"]),
                )
                source_id = str(result["source_id"])
                self.opened.setdefault(source_id, {})[passage.id] = passage
        return json.dumps(result, ensure_ascii=False)

    def source(self, metadata: Source) -> Source:
        return metadata.model_copy(update={"passages": tuple(self.opened.get(metadata.id, {}).values())})


async def document_definitions(session: ClientSession) -> list[ChatCompletionToolUnionParam]:
    available = await session.list_tools()
    return [
        {"type": "function", "function": {
            "name": tool.name, "description": tool.description or "",
            "parameters": tool.inputSchema,
        }}
        for tool in available.tools
    ]
