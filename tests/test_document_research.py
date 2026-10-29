"""Exercise model tool calls through the real MCP subprocess and report pipeline."""

import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from claim_chain.corpus import validate_finding
from claim_chain.document_client import (
    DocumentTools, call_document_tool, connect_documents, document_definitions,
)
from claim_chain.models import Corpus, Investigation, Quote, Source
from claim_chain.provider import ClientConfig, ModelClient
from claim_chain.storage import Ledger, verify_review
from claim_chain.workflow import Audit


@pytest.mark.asyncio
async def test_mcp_search_requires_opening_before_quotation(tmp_path: Path) -> None:
    directory = tmp_path / "input"
    directory.mkdir()
    (directory / "register.txt").write_text("The bridge opened in 1920.", encoding="utf-8")
    async with connect_documents(directory, tmp_path / "archive") as session:
        catalog = await call_document_tool(session, "list_sources", {})
        entries = catalog["sources"]
        assert isinstance(entries, list)
        source = Source.model_validate(entries[0])
        tools = DocumentTools(session, await document_definitions(session), (source.id,))
        result = json.loads(await tools.execute(
            "search_source", json.dumps({"source_id": source.id, "query": "bridge"})
        ))
        match = result["matches"][0]
        finding = Investigation(
            assessment="supported", reasoning="Explicit statement.",
            quotes=(Quote(passage_id=match["id"], text="The bridge opened in 1920."),),
            followups=(),
        )
        with pytest.raises(ValueError, match="Unverified quotation"):
            validate_finding(tools.source(source), finding, {source.id})
        await tools.execute("read_source", json.dumps({"source_id": source.id, "start": match["chunk"]}))
        validate_finding(tools.source(source), finding, {source.id})
        with pytest.raises(ValueError, match="assigned"):
            await tools.execute("read_source", '{"source_id":"unassigned"}')


@pytest.mark.asyncio
async def test_research_uses_mcp_evidence_and_preserves_reviewed_report(tmp_path: Path) -> None:
    directory = tmp_path / "input"
    directory.mkdir()
    (directory / "register.txt").write_text("The bridge opened in 1920.", encoding="utf-8")
    output = tmp_path / "run"
    output.mkdir()
    async with connect_documents(directory, output / "documents") as session:
        listing = await call_document_tool(session, "list_sources", {})
        entries = listing["sources"]
        assert isinstance(entries, list)
        source = Source.model_validate(entries[0])
        requests: list[dict[str, object]] = []

        def complete(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            requests.append(body)
            system = body["messages"][0]["content"]
            stage = system.split("This is stage: ")[1].split(".")[0]
            message: dict[str, object]
            if stage == "plan":
                value: object = {"jobs": [{"source_id": source.id, "question": "When did it open?"}], "rationale": "Check record."}
            elif stage == "inspect" and body["messages"][-1]["role"] != "tool":
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "read1", "type": "function", "function": {
                        "name": "read_source", "arguments": json.dumps({"source_id": source.id}),
                    },
                }]}
                return response(message)
            elif stage == "inspect":
                passage = json.loads(body["messages"][-1]["content"])["passages"][0]
                value = {"assessment": "supported", "reasoning": "The record states the date.", "quotes": [{"passage_id": passage["id"], "text": passage["text"]}], "followups": []}
            elif stage == "preliminary":
                value = {"assessment": "supported", "reasoning": "Explicit statement; date of source unknown.", "alternatives": []}
            elif stage == "draft":
                evidence = json.loads(body["messages"][1]["content"])["evidence"]
                passage_id = evidence["sources"][0]["passages"][0]["id"]
                value = {"assessment": "supported", "reasoning": "The supplied register states 1920.", "decisive_passages": [passage_id], "earliest_source_id": None, "limitations": []}
            else:
                value = {"approved": True, "issues": [], "required_changes": []}
            return response({"role": "assistant", "content": json.dumps(value)})

        def response(message: dict[str, object]) -> httpx.Response:
            return httpx.Response(200, json={
                "id": "test", "object": "chat.completion", "created": 0, "model": "test",
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            })

        sdk = AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(complete)))
        config = ClientConfig(base_url="https://mock.invalid/v1", api_key=SecretStr("test"), model="test", max_calls=50)
        ledger = Ledger(output / "ledger.sqlite")
        try:
            async with ModelClient(config, sdk_client=sdk, event_callback=ledger.record) as client:
                audit = Audit(Corpus(claim="Bridge opened in 1920", seeds=(source.id,), sources=(source,)), client, ledger, session)
                await audit.research(1, 30)
                await audit.finish(output)
                assert audit.findings[source.id].assessment == "supported"
            assert verify_review(output)
            assert "The bridge opened in 1920." in (output / "report.md").read_text()
            assert any("tools" in request for request in requests)
            assert ledger.connection.execute("SELECT count(*) FROM events WHERE kind='tool_result'").fetchone()[0] == 1
        finally:
            ledger.close()
