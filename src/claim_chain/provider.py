"""OpenAI-compatible chat client with bounded structured-output correction."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, Self, cast

from jinja2 import Environment, StrictUndefined
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolUnionParam,
    ChatCompletionUserMessageParam,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr

MAX_CALL_ATTEMPTS = 2

EventCallback = Callable[[str, dict[str, object]], None]
MAX_TOOL_ROUNDS = 8


class ToolSession(Protocol):
    definitions: list[ChatCompletionToolUnionParam]

    async def execute(self, name: str, arguments: str) -> str: ...


PROGRESS_FIELDS = {
    "jobs": "Planning source checks",
    "source_id": "Choosing a source",
    "question": "Defining a source question",
    "depends_on": "Setting investigation prerequisites",
    "rationale": "Explaining the research plan",
    "assessment": "Assessing the claim",
    "reasoning": "Writing the evidence assessment",
    "quotes": "Selecting quotations",
    "passage_id": "Selecting a passage",
    "text": "Writing a quotation",
    "followups": "Choosing follow-up sources",
    "alternatives": "Considering alternative interpretations",
    "decisive_passages": "Selecting decisive evidence",
    "earliest_source_id": "Identifying the earliest supplied source",
    "limitations": "Describing evidence limits",
    "approved": "Checking the report",
    "issues": "Identifying report issues",
    "required_changes": "Describing required corrections",
}


def progress_summary(text: str) -> str:
    """Describe JSON fields being written; this is not a model reasoning summary."""
    previous = ""
    summary = "Receiving response"
    for match in re.finditer(r'"(?:\\.|[^"\\])*(?:"|\\?$)|[^\s]', text):
        token = match.group()
        if token == ":" and previous.startswith('"'):
            summary = PROGRESS_FIELDS.get(previous[1:-1], summary)
        previous = token
    return summary


class ClientConfig(BaseModel):
    """Connection settings. The API key is never included in event records."""

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(min_length=1)
    api_key: SecretStr
    model: str = Field(min_length=1)
    timeout: float = Field(default=120.0, gt=0)
    max_calls: int = Field(default=24, gt=0)
    headers: dict[str, str] = Field(default_factory=dict)
    stream: bool = False
    role_models: dict[str, str] = Field(default_factory=dict)
    no_thinking_roles: frozenset[str] = frozenset()


class CallBudgetExceeded(RuntimeError):
    """Raised when the configured attempted-call budget is exhausted."""


class ModelClient:
    def __init__(
        self,
        config: ClientConfig,
        prompt_dir: Path | None = None,
        event_callback: EventCallback | None = None,
        sdk_client: AsyncOpenAI | None = None,
    ) -> None:
        self._config = config
        self._prompt_dir = prompt_dir or Path(__file__).with_name("prompts")
        self._events = event_callback or (lambda _name, _event: None)
        self._sdk = sdk_client or AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key.get_secret_value(),
            timeout=config.timeout,
            max_retries=0,
            default_headers=config.headers,
        )
        self._calls = 0
        self._call_lock = asyncio.Lock()
        self._templates = Environment(undefined=StrictUndefined, autoescape=False)

    @property
    def calls(self) -> int:
        return self._calls

    async def chat[T: BaseModel](
        self,
        role: str,
        stage: str,
        payload: object,
        response_type: type[T],
        validator: Callable[[T], None] | None = None,
        *,
        job_id: str,
        tools: ToolSession | None = None,
        call_limit: int | None = None,
    ) -> T:
        """Call one isolated role context and validate its JSON against a Pydantic model."""
        system = self._system_prompt(role, stage, response_type)
        user = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        context: dict[str, object] = {
            "job_id": job_id,
            "role": role,
            "stage": stage,
            "model": self._config.role_models.get(role, self._config.model),
        }
        previous_response = ""
        correction_message = ""
        tool_messages = self._messages(system, user, "", "") if tools is not None else None
        tool_operations = 0
        for correction in range(MAX_CALL_ATTEMPTS):
            call_id = await self._reserve_call(context, correction, call_limit)
            if tools is None:
                messages = self._messages(system, user, previous_response, correction_message)
            else:
                assert tool_messages is not None
                messages = tool_messages
                if correction_message:
                    messages.append(ChatCompletionUserMessageParam(
                        role="user", content=correction_message
                    ))
            try:
                if tools is None:
                    text, usage = await self._complete(messages, {**context, "call": call_id})
                else:
                    text, usage, operations, call_id = await self._complete_with_tools(
                        messages, context, call_id, tools, call_limit, correction,
                        tool_operations,
                    )
                    tool_operations += operations
            except Exception as error:
                self._events(
                    "model_error",
                    {
                        **context,
                        "call": call_id,
                        "error_type": type(error).__name__,
                    },
                )
                raise
            if tools is None:
                self._events(
                    "model_response",
                    {**context, "call": call_id, "usage": usage, "output": text},
                )
            try:
                result = response_type.model_validate_json(self._strip_fence(text))
                if validator is not None:
                    validator(result)
                return result
            except ValueError as error:
                self._events(
                    "model_validation_error",
                    {**context, "call": call_id, "error_type": type(error).__name__, "error": str(error)[:300]},
                )
                if correction == MAX_CALL_ATTEMPTS - 1:
                    raise ValueError(
                        f"Model response failed validation after correction: {error}"
                    ) from error
                previous_response = text
                correction_message = (
                    "Correct the previous response. Return JSON only. Validation errors: "
                    + str(error)
                )
        raise AssertionError("unreachable")

    def _extra_body(self, context: dict[str, object]) -> dict[str, object] | None:
        if context["role"] in self._config.no_thinking_roles:
            return {"thinking": {"type": "disabled"}}
        return None

    async def _complete(
        self, messages: list[ChatCompletionMessageParam], context: dict[str, object]
    ) -> tuple[str, dict[str, int | None]]:
        if self._config.stream:
            return await self._stream(messages, context)
        response = await self._sdk.chat.completions.create(
            model=str(context["model"]), messages=messages, extra_body=self._extra_body(context)
        )
        if not response.choices:
            raise ValueError("Provider returned no completion choices.")
        return response.choices[0].message.content or "", self._usage(response)

    async def _stream(
        self, messages: list[ChatCompletionMessageParam], context: dict[str, object]
    ) -> tuple[str, dict[str, int | None]]:
        stream = await self._sdk.chat.completions.create(
            model=str(context["model"]),
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            extra_body=self._extra_body(context),
        )
        text = ""
        usage: dict[str, int | None] = {"input_tokens": None, "output_tokens": None}
        summary = ""
        last_update = 0.0
        finished = False
        async with stream:
            async for chunk in stream:
                if chunk.usage is not None:
                    usage = self._usage(chunk)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason is not None:
                    finished = True
                content = choice.delta.content
                if not content:
                    continue
                text += content
                current_summary = progress_summary(text)
                now = time.monotonic()
                if current_summary != summary or now - last_update >= 1:
                    self._events(
                        "model_progress",
                        {**context, "summary": current_summary, "characters": len(text)},
                    )
                    summary = current_summary
                    last_update = now
        if not finished:
            raise ValueError("Provider stream ended without a completion finish reason.")
        return text, usage

    def _system_prompt(self, role: str, stage: str, response_type: type[BaseModel]) -> str:
        allowed = {"research-lead", "investigator", "reviewer"}
        if role not in allowed:
            raise ValueError(f"Unknown role: {role}")
        template_path = self._prompt_dir / f"{role}.j2"
        template = self._templates.from_string(template_path.read_text(encoding="utf-8"))
        return template.render(stage=stage, output_schema=response_type.model_json_schema())

    async def _complete_with_tools(
        self,
        messages: list[ChatCompletionMessageParam],
        context: dict[str, object],
        call_id: int,
        tools: ToolSession,
        call_limit: int | None,
        correction: int,
        previous_operations: int,
    ) -> tuple[str, dict[str, int | None], int, int]:
        """Run native tool calls; non-streaming keeps each complete tool call atomic."""
        usage: dict[str, int | None] = {"input_tokens": None, "output_tokens": None}
        operations = 0
        call_ceiling = min(
            self._config.max_calls,
            call_limit if call_limit is not None else self._config.max_calls,
        )
        for round_number in range(MAX_TOOL_ROUNDS + 1):
            final_only = (
                round_number == MAX_TOOL_ROUNDS
                or previous_operations + operations >= 24
                or call_id >= call_ceiling
            )
            response = await self._sdk.chat.completions.create(
                model=str(context["model"]),
                messages=messages,
                tools=tools.definitions,
                tool_choice="none" if final_only else "auto",
                extra_body=self._extra_body(context),
            )
            if not response.choices:
                raise ValueError("Provider returned no completion choices.")
            message = response.choices[0].message
            usage = self._usage(response)
            self._events("model_response", {
                **context, "call": call_id, "usage": usage, "output": message.content or ""
            })
            if not message.tool_calls:
                text = message.content or ""
                messages.append(ChatCompletionAssistantMessageParam(role="assistant", content=text))
                return text, usage, operations, call_id
            if final_only:
                text = message.content or ""
                messages.append(ChatCompletionAssistantMessageParam(role="assistant", content=text))
                return text, usage, operations, call_id
            messages.append(cast(ChatCompletionMessageParam, {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [call.model_dump(exclude_none=True) for call in message.tool_calls],
            }))
            for index, tool_call in enumerate(message.tool_calls):
                if tool_call.type == "function":
                    name = tool_call.function.name
                    arguments = tool_call.function.arguments
                else:
                    name = "custom"
                    arguments = json.dumps(tool_call.model_dump(exclude_none=True))
                event_context = {**context, "call": call_id, "name": name, "arguments": arguments}
                self._events("tool_call", event_context)
                if tool_call.type != "function":
                    result = json.dumps({"error": "UnsupportedTool", "message": "Only function tools are supported."})
                elif index >= 8 or previous_operations + operations >= 24:
                    result = json.dumps({"error": "ToolLimitExceeded", "message": "Tool call limit reached."})
                else:
                    operations += 1
                    try:
                        result = await tools.execute(name, arguments)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        result = json.dumps({"error": type(error).__name__, "message": str(error)})
                self._events("tool_result", {**event_context, "result": result})
                messages.append(ChatCompletionToolMessageParam(
                    role="tool", tool_call_id=tool_call.id, content=result
                ))
            call_id = await self._reserve_call(context, correction, call_limit)
        raise AssertionError("unreachable")

    async def _reserve_call(
        self, context: Mapping[str, object], correction: int, call_limit: int | None = None
    ) -> int:
        async with self._call_lock:
            if call_limit is not None and self._calls >= call_limit:
                raise CallBudgetExceeded("reserved model call budget exhausted")
            if self._calls >= self._config.max_calls:
                raise CallBudgetExceeded("model call budget exhausted")
            self._calls += 1
            call_id = self._calls
            self._events(
                "model_request",
                {
                    **context,
                    "call": call_id,
                    "correction": correction,
                },
            )
            return call_id

    @staticmethod
    def _messages(
        system: str,
        user: str,
        previous_response: str,
        correction_message: str,
    ) -> list[ChatCompletionMessageParam]:
        messages: list[ChatCompletionMessageParam] = [
            ChatCompletionSystemMessageParam(role="system", content=system),
            ChatCompletionUserMessageParam(role="user", content=user),
        ]
        if previous_response:
            messages.append(
                ChatCompletionAssistantMessageParam(role="assistant", content=previous_response)
            )
            messages.append(
                ChatCompletionUserMessageParam(role="user", content=correction_message)
            )
        return messages

    async def close(self) -> None:
        """Close the SDK client's underlying HTTP resources."""
        await self._sdk.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    @staticmethod
    def _usage(response: object) -> dict[str, int | None]:
        usage = getattr(response, "usage", None)
        return {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
        }

    @staticmethod
    def _strip_fence(text: str) -> str:
        match = re.fullmatch(
            r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", text, re.DOTALL | re.IGNORECASE
        )
        return match.group(1) if match else text


__all__ = ["CallBudgetExceeded", "ClientConfig", "ModelClient", "ToolSession"]
