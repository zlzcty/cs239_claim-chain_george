import copy
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionToolUnionParam
from pydantic import BaseModel, SecretStr

from claim_chain.provider import CallBudgetExceeded, ClientConfig, ModelClient


class Answer(BaseModel):
    result: str


class Session:
    definitions: list[ChatCompletionToolUnionParam] = [
        {"type": "function", "function": {"name": "lookup", "parameters": {}}}
    ]

    async def execute(self, name: str, arguments: str) -> str:
        assert name == "lookup"
        assert arguments == '{"query":"x"}'
        return '{"matches":["source"]}'


def completion(content: str | None = None, tool_calls: list[object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
    )


def tool_call() -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name="lookup", arguments='{"query":"x"}'),
        model_dump=lambda **_kwargs: {
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"query":"x"}'},
        },
    )


def client_for(
    side_effect: Callable[..., Awaitable[SimpleNamespace]], events: list[tuple[str, dict[str, object]]],
    max_calls: int = 5,
) -> tuple[ModelClient, AsyncMock]:
    sdk = AsyncOpenAI(api_key="test", base_url="https://mock.invalid/v1", max_retries=0)
    create = AsyncMock(side_effect=side_effect)
    cast(Any, sdk.chat.completions).create = create
    config = ClientConfig(
        base_url="https://mock.invalid/v1", api_key=SecretStr("test"), model="model",
        max_calls=max_calls,
    )
    return ModelClient(config, event_callback=lambda name, event: events.append((name, event)),
                       sdk_client=sdk), create


@pytest.mark.asyncio
async def test_native_tool_loop_keeps_tool_messages_in_isolated_context() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    responses = iter((completion(tool_calls=[tool_call()]), completion('{"result":"done"}')))

    async def create(**_kwargs: object) -> SimpleNamespace:
        return next(responses)

    client, call = client_for(create, events)
    answer = await client.chat(
        "investigator", "inspect", {"claim": "x"}, Answer, job_id="inspect:x", tools=Session()
    )
    assert answer == Answer(result="done")
    assert client.calls == 2
    assert call.await_count == 2
    request = call.await_args_list[1].kwargs
    messages = request["messages"]
    assert messages[-3]["role"] == "assistant"
    assert messages[-2] == {"role": "tool", "tool_call_id": "call_1", "content": '{"matches":["source"]}'}
    assert [name for name, _ in events if name.startswith("tool_")] == ["tool_call", "tool_result"]
    assert all(event["job_id"] == "inspect:x" for name, event in events if name.startswith("tool_"))
    model_responses = [event for name, event in events if name == "model_response"]
    assert [event["call"] for event in model_responses] == [1, 2]


@pytest.mark.asyncio
async def test_invalid_final_keeps_tool_transcript_for_correction() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    responses = iter((completion(tool_calls=[tool_call()]), completion("invalid"), completion('{"result":"fixed"}')))
    request_messages: list[list[dict[str, object]]] = []

    async def create(**kwargs: object) -> SimpleNamespace:
        request_messages.append(copy.deepcopy(cast(list[dict[str, object]], kwargs["messages"])))
        return next(responses)

    client, _ = client_for(create, events)
    answer = await client.chat(
        "investigator", "inspect", {}, Answer, job_id="inspect:x", tools=Session()
    )
    assert answer == Answer(result="fixed")
    assert any(message["role"] == "tool" for message in request_messages[2])
    assert request_messages[2][-2]["content"] == "invalid"
    assert [event["call"] for name, event in events if name == "model_response"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_tool_requests_obey_absolute_call_ceiling() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    async def create(**_kwargs: object) -> SimpleNamespace:
        return completion(tool_calls=[tool_call()])

    client, call = client_for(create, events, max_calls=4)
    with pytest.raises(CallBudgetExceeded):
        await client.chat(
            "investigator", "inspect", {}, Answer, job_id="inspect:x", tools=Session(), call_limit=1
        )
    assert client.calls == 1
    assert call.await_count == 1
    last_request = call.await_args
    assert last_request is not None
    assert last_request.kwargs["tool_choice"] == "none"
