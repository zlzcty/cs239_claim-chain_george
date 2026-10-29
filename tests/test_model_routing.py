import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, SecretStr

from claim_chain.cli import parser
from claim_chain.provider import ClientConfig, ModelClient


class Answer(BaseModel):
    result: str


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_role_models_route_requests_and_corrections_and_events(stream: bool) -> None:
    requested: list[str] = []
    events: list[tuple[str, dict[str, object]]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requested.append(body["model"])
        content = "invalid" if len(requested) == 1 else '{"result":"ok"}'
        if stream:
            chunk = {
                "id": "test",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": body["model"],
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": "stop"}],
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    config = ClientConfig(
        base_url="https://example.org/v1",
        api_key=SecretStr("test"),
        model="fallback",
        role_models={"research-lead": "planner", "investigator": "fast"},
        stream=stream,
    )
    sdk = AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    async with ModelClient(
        config,
        sdk_client=sdk,
        event_callback=lambda kind, body: events.append((kind, body)),
    ) as client:
        for role in ("research-lead", "investigator", "reviewer"):
            await client.chat(role, "test", {}, Answer, job_id=role)
    assert requested == ["planner", "planner", "fast", "fallback"]
    for _, body in events:
        assert body["model"] == config.role_models.get(str(body["role"]), "fallback")


def test_role_model_flags_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "default")
    monkeypatch.setenv("OPENAI_LEAD_MODEL", "planner")
    monkeypatch.setenv("OPENAI_INVESTIGATOR_MODEL", "fast")
    monkeypatch.setenv("OPENAI_REVIEWER_MODEL", "careful")
    args = parser().parse_args(["--reviewer-model", "override"])
    assert (args.model, args.lead_model, args.investigator_model, args.reviewer_model) == (
        "default",
        "planner",
        "fast",
        "override",
    )
