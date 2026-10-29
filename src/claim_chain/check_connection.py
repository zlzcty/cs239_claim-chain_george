"""Print provider configuration safely and test one chat completion."""

import argparse
import os
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from openai import APIConnectionError, APIStatusError, OpenAI, OpenAIError


def display_environment(environment: Mapping[str, str], key_name: str) -> None:
    for name in dict.fromkeys(
        ("OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY", "API_KEY", key_name)
    ):
        value = environment.get(name, "")
        if name in {"OPENAI_BASE_URL", "OPENAI_MODEL"} and name != key_name:
            shown = safe_url(value) if name == "OPENAI_BASE_URL" and value else value
            print(f"{name}={shown or '(unset)'}")
        else:
            print(f"{name}={'(set, masked)' if value else '(unset or empty)'}")
    print("Only the selected key variable is used. .env files are not loaded automatically.")


def safe_url(value: str) -> str:
    parts = urlsplit(value)
    host = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def check_connection(client: OpenAI, model: str) -> bool:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with OK only."}],
            max_tokens=16,
        )
    except APIStatusError as error:
        print(f"FAILED: {type(error).__name__}, HTTP {error.status_code}.")
        if error.status_code in {401, 403}:
            print("Check that the selected key belongs to this provider and has model access.")
        elif error.status_code == 429:
            print("Check provider quota, billing, and rate limits.")
        else:
            print("Check the base URL, model ID, and provider chat-completions support.")
        return False
    except APIConnectionError as error:
        print(f"FAILED: {type(error).__name__}. Check network access, URL, and timeout.")
        return False
    except OpenAIError as error:
        print(f"FAILED: {type(error).__name__}.")
        return False
    if not response.choices or not response.choices[0].message.content:
        print("FAILED: provider returned no text completion.")
        return False
    print("SUCCESS: provider returned a text completion. Authentication and model access work.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL"))
    parser.add_argument(
        "--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    parser.add_argument("--api-key-env", default="API_KEY")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--header", action="append", default=[], metavar="NAME=VALUE")
    args = parser.parse_args()
    display_environment(os.environ, args.api_key_env)
    print(f"Effective base URL: {safe_url(args.base_url)}")
    print(f"Effective model: {args.model or '(unset)'}")
    print(f"Selected key variable: {args.api_key_env}")
    print(f"Additional headers: {len(args.header)} (values masked)")
    if not args.model or args.timeout <= 0:
        parser.error("Set --model or OPENAI_MODEL and use a positive timeout.")
    if any("=" not in item or not item.split("=", 1)[0].strip() for item in args.header):
        parser.error("Headers must use NAME=VALUE.")
    key = os.getenv(args.api_key_env, "")
    if not key and urlsplit(args.base_url).hostname == "api.openai.com":
        parser.error(f"Set {args.api_key_env} in this shell.")
    if not key:
        print("Selected key is missing; using the runner's local-no-key placeholder.")
    headers = dict(item.split("=", 1) for item in args.header)
    if urlsplit(args.base_url).hostname == "opencode.ai":
        headers.setdefault("x-opencode-session", uuid4().hex)
    print("Sending one small chat request (provider charges may apply; no retries).")
    with OpenAI(
        base_url=args.base_url,
        api_key=key or "local-no-key",
        timeout=args.timeout,
        max_retries=0,
        default_headers=headers,
    ) as client:
        success = check_connection(client, args.model)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
