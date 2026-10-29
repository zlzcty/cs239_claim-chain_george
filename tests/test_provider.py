import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, AsyncOpenAI
from pydantic import BaseModel, SecretStr

from claim_chain.provider import CallBudgetExceeded, ClientConfig, ModelClient


class Answer(BaseModel):
    result: str


class ReferenceAnswer(BaseModel):
    source_id: str


def response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2),
    )


def make_client(
    side_effect: Callable[..., Awaitable[SimpleNamespace]],
    events: list[tuple[str, dict[str, object]]],
    max_calls: int = 2,
) -> tuple[ModelClient, AsyncMock]:
    sdk = AsyncOpenAI(api_key="test-secret", base_url="https://mock.invalid/v1", max_retries=0)
    create = AsyncMock(side_effect=side_effect)
    cast(Any, sdk.chat.completions).create = create
    config = ClientConfig(
        base_url="https://mock.invalid/v1",
        api_key=SecretStr("test-secret"),
        model="test-model",
        max_calls=max_calls,
    )
    return ModelClient(
        config, event_callback=lambda name, event: events.append((name, event)), sdk_client=sdk
    ), create


@pytest.mark.asyncio
async def test_chat_parses_fenced_json_and_logs_usage_without_key() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    async def create(**kwargs: object) -> SimpleNamespace:
        messages = cast(list[Any], kwargs["messages"])
        assert messages[0]["role"] == "system"
        assert '"result"' in messages[0]["content"]
        assert messages[1]["content"] == '{"claim":"A"}'
        return response('```json\n{"result":"ok"}\n```')

    client, mocked_call = make_client(create, events)
    answer = await client.chat(
        "investigator", "inspect", {"claim": "A"}, Answer, job_id="inspect:alpha"
    )
    assert answer == Answer(result="ok")
    assert client.calls == 1
    assert mocked_call.await_count == 1
    assert not any("test-secret" in repr(event) for event in events)
    output = next(event for name, event in events if name == "model_response")
    assert output["usage"] == {"input_tokens": 7, "output_tokens": 2}


@pytest.mark.asyncio
async def test_invalid_json_gets_one_correction_attempt() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    responses = iter((response("not json"), response('{"result":"fixed"}')))

    async def create(**kwargs: object) -> SimpleNamespace:
        return next(responses)

    client, mocked_call = make_client(create, events)
    answer = await client.chat("reviewer", "review", {}, Answer, job_id="review:1")
    assert answer.result == "fixed"
    assert client.calls == 2
    corrected_messages = mocked_call.await_args_list[1].kwargs["messages"]
    assert [message["role"] for message in corrected_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert corrected_messages[-2]["content"] == "not json"


@pytest.mark.asyncio
async def test_semantic_validation_gets_one_correction_attempt() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    responses = iter(
        (response('{"source_id":"invented"}'), response('{"source_id":"register-v1"}'))
    )

    async def create(**_kwargs: object) -> SimpleNamespace:
        return next(responses)

    def validate_reference(answer: ReferenceAnswer) -> None:
        if answer.source_id != "register-v1":
            raise ValueError("source_id must reference the supplied catalog")

    client, mocked_call = make_client(create, events)
    answer = await client.chat(
        "research-lead", "plan", {}, ReferenceAnswer, validator=validate_reference, job_id="plan:1"
    )
    assert answer.source_id == "register-v1"
    assert client.calls == 2
    assert mocked_call.await_count == 2
    retry_messages = mocked_call.await_args_list[1].kwargs["messages"]
    assert retry_messages[-2]["content"] == '{"source_id":"invented"}'
    assert "supplied catalog" in retry_messages[-1]["content"]


@pytest.mark.asyncio
async def test_call_budget_prevents_extra_request() -> None:
    events: list[tuple[str, dict[str, object]]] = []

    async def create(**_kwargs: object) -> SimpleNamespace:
        return response("bad")

    client, mocked_call = make_client(create, events, max_calls=1)
    with pytest.raises(CallBudgetExceeded):
        await client.chat("research-lead", "draft", {}, Answer, job_id="draft:1")
    assert client.calls == 1
    assert mocked_call.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_call_events_keep_job_identity_through_correction_and_failure() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    beta_started = asyncio.Event()
    alpha_attempts = 0

    async def create(**kwargs: object) -> SimpleNamespace:
        nonlocal alpha_attempts
        messages = cast(list[Any], kwargs["messages"])
        payload = messages[1]["content"]
        if payload == '{"source_id":"alpha"}':
            alpha_attempts += 1
            await beta_started.wait()
            return response("invalid JSON" if alpha_attempts == 1 else '{"result":"alpha"}')
        beta_started.set()
        raise APIConnectionError(request=httpx.Request("POST", "https://mock.invalid/v1"))

    client, _ = make_client(create, events, max_calls=3)
    async with client:
        results = await asyncio.gather(
            client.chat(
                "investigator", "inspect", {"source_id": "alpha"}, Answer, job_id="inspect:alpha"
            ),
            client.chat(
                "investigator", "inspect", {"source_id": "beta"}, Answer, job_id="inspect:beta"
            ),
            return_exceptions=True,
        )
    assert results[0] == Answer(result="alpha")
    assert isinstance(results[1], APIConnectionError)
    requests = {event["call"]: event for kind, event in events if kind == "model_request"}
    assert len(requests) == 3
    assert [
        event["correction"] for event in requests.values() if event["job_id"] == "inspect:alpha"
    ] == [0, 1]
    for _, event in events:
        assert event["job_id"] == requests[event["call"]]["job_id"]
    assert {event["job_id"] for kind, event in events if kind == "model_validation_error"} == {
        "inspect:alpha"
    }
    assert {event["job_id"] for kind, event in events if kind == "model_error"} == {"inspect:beta"}
