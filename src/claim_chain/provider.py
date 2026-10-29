"""OpenAI-compatible chat client with bounded structured-output correction."""

from __future__ import annotations

import asyncio
import json
import re
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


class ClientConfig(BaseModel):
    """Connection settings. The API key is never included in event records."""

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(min_length=1)
    api_key: SecretStr
    model: str = Field(min_length=1)
    timeout: float = Field(default=60.0, gt=0)
    max_calls: int = Field(default=24, gt=0)
    headers: dict[str, str] = Field(default_factory=dict)


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
            "model": self._config.model,
        }
        previous_response = ""
        correction_message = ""
        for correction in range(MAX_CALL_ATTEMPTS):
            call_id = await self._reserve_call(context, correction)
            messages = self._messages(system, user, previous_response, correction_message)
            try:
                response = await self._sdk.chat.completions.create(
                    model=self._config.model,
                    messages=messages,
                )
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
            if not response.choices:
                self._events(
                    "model_error", {**context, "call": call_id, "error_type": "EmptyChoices"}
                )
                raise ValueError("Provider returned no completion choices.")
            text = response.choices[0].message.content or ""
            usage = self._usage(response)
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
