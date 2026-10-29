"""OpenAI-compatible chat client with bounded structured-output correction."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Self

from jinja2 import Environment, StrictUndefined
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr

MAX_CALL_ATTEMPTS = 2

EventCallback = Callable[[str, dict[str, object]], None]


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
        for correction in range(MAX_CALL_ATTEMPTS):
            call_id = await self._reserve_call(context, correction)
            messages = self._messages(system, user, previous_response, correction_message)
            try:
                text, usage = await self._complete(messages, {**context, "call": call_id})
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
            self._events(
                "model_response",
                {
                    **context,
                    "call": call_id,
                    "usage": usage,
                    "output": text,
                },
            )
            try:
                result = response_type.model_validate_json(self._strip_fence(text))
                if validator is not None:
                    validator(result)
                return result
            except ValueError as error:
                self._events(
                    "model_validation_error",
                    {**context, "call": call_id, "error_type": type(error).__name__},
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

    async def _complete(
        self, messages: list[ChatCompletionMessageParam], context: dict[str, object]
    ) -> tuple[str, dict[str, int | None]]:
        if self._config.stream:
            return await self._stream(messages, context)
        response = await self._sdk.chat.completions.create(
            model=str(context["model"]), messages=messages
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

    async def _reserve_call(self, context: Mapping[str, object], correction: int) -> int:
        async with self._call_lock:
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


__all__ = ["CallBudgetExceeded", "ClientConfig", "ModelClient"]
