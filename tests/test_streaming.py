"""Streaming uses the same final validation and job attribution as complete responses."""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, SecretStr

from claim_chain.provider import ClientConfig, ModelClient, progress_summary


class Answer(BaseModel):
    reasoning: str


def sse_chunk(content: str | None, finished: bool = False) -> bytes:
    delta: dict[str, object] = {"content": content} if content is not None else {}
    return (
        "data: "
        + json.dumps(
            {
                "id": "test",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "test",
                "choices": [
                    {"index": 0, "delta": delta, "finish_reason": "stop" if finished else None}
                ],
            }
        )
        + "\n\n"
    ).encode()


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, chunks: Sequence[bytes], block: bool = False) -> None:
        self.chunks = chunks
        self.block = block
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk
        self.started.set()
        if self.block:
            await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


def client_for(
    streams: Sequence[ResponseStream], events: list[tuple[str, dict[str, object]]]
) -> ModelClient:
    responses = iter(streams)

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=next(responses)
        )

    sdk = AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    config = ClientConfig(
        base_url="https://mock.invalid/v1", api_key=SecretStr("test"), model="test", stream=True
    )
    return ModelClient(
        config, sdk_client=sdk, event_callback=lambda name, body: events.append((name, body))
    )


@pytest.mark.parametrize(
    ("partial", "summary"),
    [
        ('{"rea', "Receiving response"),
        ('{"reasoning": "Checking the Moon', "Writing the evidence assessment"),
        ('{"reasoning": "A quoted key: \\"issues\\": ', "Writing the evidence assessment"),
        ('{"reasoning": "done", "quotes": [', "Selecting quotations"),
    ],
)
def test_progress_describes_fields_without_reading_quoted_keys(partial: str, summary: str) -> None:
    assert progress_summary(partial) == summary


@pytest.mark.asyncio
async def test_stream_fragments_validate_and_record_usage_and_job() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    usage = b'data: {"id":"test","object":"chat.completion.chunk","created":0,"model":"test","choices":[],"usage":{"prompt_tokens":8,"completion_tokens":6,"total_tokens":14}}\n\n'
    reasoning_only = b'data: {"id":"test","object":"chat.completion.chunk","created":0,"model":"test","choices":[{"index":0,"delta":{"reasoning_content":"private reasoning content"},"finish_reason":null}]}\n\n'
    stream = ResponseStream(
        [
            reasoning_only,
            sse_chunk('{"rea'),
            sse_chunk('soning":"The Moon'),
            sse_chunk(' differs from orbit."}'),
            sse_chunk(None, finished=True),
            usage,
            b"data: [DONE]\n\n",
        ]
    )
    async with client_for([stream], events) as client:
        answer = await client.chat("investigator", "inspect", {}, Answer, job_id="inspect:moon")
        assert client.calls == 1
    assert answer.reasoning == "The Moon differs from orbit."
    assert stream.closed
    assert "private reasoning content" not in repr(events)
    progress = [body for kind, body in events if kind == "model_progress"]
    assert [body["summary"] for body in progress] == [
        "Receiving response",
        "Writing the evidence assessment",
    ]
    assert all(body["job_id"] == "inspect:moon" and body["call"] == 1 for body in progress)
    assert all("Moon" not in repr(body) for body in progress)
    response = next(body for kind, body in events if kind == "model_response")
    assert response["usage"] == {"input_tokens": 8, "output_tokens": 6}


@pytest.mark.asyncio
async def test_stream_invalid_json_uses_existing_correction_budget() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    streams = [
        ResponseStream([sse_chunk(text), sse_chunk(None, finished=True)])
        for text in ("invalid", '{"reasoning":"corrected"}')
    ]
    async with client_for(streams, events) as client:
        answer = await client.chat("reviewer", "review", {}, Answer, job_id="review:1")
        assert client.calls == 2
    assert answer.reasoning == "corrected"
    assert {body["call"] for kind, body in events if kind == "model_progress"} == {1, 2}
    assert sum(kind == "model_validation_error" for kind, _ in events) == 1


@pytest.mark.asyncio
async def test_unfinished_stream_is_failure_not_partial_answer() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    stream = ResponseStream([sse_chunk('{"reasoning":"valid-looking"}')])
    async with client_for([stream], events) as client:
        with pytest.raises(ValueError, match="finish reason"):
            await client.chat("reviewer", "review", {}, Answer, job_id="review:1")
    assert stream.closed
    assert any(kind == "model_error" for kind, _ in events)
    assert not any(kind == "model_response" for kind, _ in events)


@pytest.mark.asyncio
async def test_cancelling_stream_closes_response() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    stream = ResponseStream([sse_chunk('{"reasoning":"partial')], block=True)
    async with client_for([stream], events) as client:
        task = asyncio.create_task(
            client.chat("reviewer", "review", {}, Answer, job_id="review:1")
        )
        await asyncio.wait_for(stream.started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stream.closed
    assert not any(kind == "model_response" for kind, _ in events)
