"""Command-line configuration and run lifecycle."""

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from openai import OpenAIError
from pydantic import SecretStr

from .corpus import load_corpus
from .document_client import call_document_tool, connect_documents
from .models import Corpus, Draft, Source
from .provider import ClientConfig, ModelClient
from .storage import Ledger, verify_review
from .workflow import (
    DOCUMENT_JOB_CALLS, DOCUMENT_REVIEW_RESERVE, FINISH_CALL_RESERVE,
    MIN_CALLS, Audit, render_report,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Audit a claim using live OpenAI-compatible models and local evidence."
    )
    result.add_argument(
        "--model", default=os.getenv("OPENAI_MODEL"), help="Provider model ID, or OPENAI_MODEL"
    )
    for name in ("lead", "investigator", "reviewer"):
        result.add_argument(
            f"--{name}-model",
            default=os.getenv(f"OPENAI_{name.upper()}_MODEL"),
            help=f"Model for {name}; defaults to --model",
        )
    result.add_argument(
        "--base-url", default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    result.add_argument(
        "--api-key-env", default="API_KEY", help="Environment variable holding the API key"
    )
    result.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Additional provider header; repeatable",
    )
    result.add_argument(
        "--no-thinking",
        action="append",
        default=[],
        choices=["research-lead", "investigator", "reviewer"],
        help="Disable provider thinking for a role (sends thinking=disabled); repeatable",
    )
    result.add_argument(
        "--corpus", type=Path, default=Path(__file__).with_name("data") / "bridge.json"
    )
    result.add_argument("--documents", type=Path, help="Directory of complete PDF, text, Markdown or HTML sources")
    result.add_argument("--claim", help="Claim and research context; required with --documents")
    result.add_argument("--output", type=Path)
    result.add_argument("--max-calls", type=int, default=64)
    result.add_argument("--max-sources", type=int, default=8)
    result.add_argument(
        "--timeout", type=float, default=120, help="Per-request seconds (default: 120)"
    )
    result.add_argument(
        "--deadline", type=float, default=600, help="Whole-run seconds (default: 600)"
    )
    result.add_argument(
        "--stream",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stream model responses for live progress; use --no-stream for incompatible providers",
    )
    result.add_argument("--verify", type=Path, metavar="RUN_DIRECTORY")
    return result


async def execute(args: argparse.Namespace) -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = args.output or Path("runs") / run_id
    output.mkdir(parents=True, exist_ok=False)
    async with AsyncExitStack() as resources:
        return await execute_run(args, output, run_id, resources)


async def execute_run(
    args: argparse.Namespace, output: Path, run_id: str, resources: AsyncExitStack
) -> Path:
    documents = None
    if args.documents:
        if not args.claim:
            raise ValueError("--documents requires --claim.")
        documents = await resources.enter_async_context(
            connect_documents(args.documents, output / "documents")
        )
        catalog = await call_document_tool(documents, "list_sources", {})
        entries = catalog.get("sources")
        if not isinstance(entries, list) or not entries:
            raise ValueError("No supported documents found.")
        sources = tuple(Source.model_validate(item) for item in entries)
        corpus = Corpus(claim=args.claim, seeds=(), sources=sources)
        (output / "documents.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    else:
        corpus = load_corpus(args.corpus)
        if args.claim:
            corpus = corpus.model_copy(update={"claim": args.claim})
    ledger = Ledger(output / "ledger.sqlite")
    headers = dict(value.split("=", 1) for value in args.header)
    if urlparse(args.base_url).hostname == "opencode.ai":
        headers.setdefault("x-opencode-session", run_id)
    config = ClientConfig(
        base_url=args.base_url,
        api_key=SecretStr(os.getenv(args.api_key_env, "local-no-key")),
        model=args.model,
        timeout=args.timeout,
        max_calls=args.max_calls,
        headers=headers,
        stream=args.stream,
        no_thinking_roles=frozenset(args.no_thinking),
        role_models={
            role: model
            for role, model in (
                ("research-lead", args.lead_model),
                ("investigator", args.investigator_model),
                ("reviewer", args.reviewer_model),
            )
            if model is not None
        },
    )
    ledger.record(
        "run_started",
        {
            "model": config.model,
            "role_models": config.role_models,
            "claim": corpus.claim,
            "max_calls": args.max_calls,
            "max_sources": args.max_sources,
            "request_timeout_seconds": args.timeout,
            "deadline_seconds": args.deadline,
            "stream": args.stream,
        },
    )
    (output / "corpus.json").write_text(corpus.model_dump_json(indent=2), encoding="utf-8")
    print(f"Run directory: {output}\nDefault model: {config.model}", flush=True)
    client = ModelClient(config, event_callback=ledger.record)
    audit = Audit(corpus, client, ledger, documents)
    time_limit = asyncio.timeout(args.deadline)
    try:
        async with time_limit:
            await audit.research(args.max_sources, args.max_calls - FINISH_CALL_RESERVE - (DOCUMENT_REVIEW_RESERVE if documents else 0))
            await audit.finish(output)
    except BaseException as error:
        failure = {
            "error_type": type(error).__name__,
            "calls": client.calls,
            "deadline_exceeded": time_limit.expired(),
        }
        ledger.record("run_failed", failure)
        (output / "status.json").write_text(
            json.dumps({"approved": False, "error_type": type(error).__name__})
        )
        if not (output / "report.md").exists():
            partial = Draft(
                assessment="insufficient",
                reasoning="Run interrupted before a reviewed conclusion was available.",
                decisive_passages=(),
                earliest_source_id=None,
                limitations=(type(error).__name__,),
            )
            report = render_report(
                corpus.claim, partial, tuple(audit.inspected.values()), audit.limitations
            )
            (output / "report.md").write_bytes(
                ("UNAPPROVED PARTIAL REPORT\n\n" + report).encode("utf-8")
            )
        print(
            f"Run incomplete; preserved artifacts at {output}. No approval granted.",
            file=sys.stderr,
        )
        if time_limit.expired():
            print(
                f"Whole-run deadline of {args.deadline:g}s exceeded. "
                "Increase --deadline for slower models; --timeout controls individual requests.",
                file=sys.stderr,
            )
        raise
    finally:
        await client.close()
        ledger.close()
    print(f"Report: {output / 'report.md'}\nReview: {output / 'review.json'}", flush=True)
    return output


def main() -> None:
    argument_parser = parser()
    args = argument_parser.parse_args()
    if args.verify:
        try:
            valid = verify_review(args.verify)
        except OSError, ValueError, TypeError:
            valid = False
        print(
            "APPROVED: report and snapshot match review."
            if valid
            else "UNAPPROVED: missing review, rejected report, or changed bytes."
        )
        raise SystemExit(0 if valid else 1)
    if any(
        value is not None and not value.strip()
        for value in (
            args.lead_model,
            args.investigator_model,
            args.reviewer_model,
        )
    ):
        argument_parser.error("Role model overrides cannot be empty.")
    if args.documents and args.max_calls < FINISH_CALL_RESERVE + DOCUMENT_REVIEW_RESERVE + 2 + DOCUMENT_JOB_CALLS:
        argument_parser.error(f"Document research requires --max-calls >= {FINISH_CALL_RESERVE + DOCUMENT_REVIEW_RESERVE + 2 + DOCUMENT_JOB_CALLS}.")
    if args.documents and not args.claim:
        argument_parser.error("--documents requires --claim.")
    if not args.model:
        argument_parser.error("Set --model or OPENAI_MODEL.")
    if (
        args.max_calls < MIN_CALLS
        or args.max_sources < 1
        or args.timeout <= 0
        or args.deadline <= 0
    ):
        argument_parser.error(
            f"Require max-calls >= {MIN_CALLS}, max-sources >= 1, and positive timeouts."
        )
    if any("=" not in value or not value.split("=", 1)[0].strip() for value in args.header):
        argument_parser.error("Headers must use NAME=VALUE.")
    if args.base_url == "https://api.openai.com/v1" and not os.getenv(args.api_key_env):
        argument_parser.error(f"Set the API key environment variable {args.api_key_env}.")
    try:
        asyncio.run(execute(args))
    except (OpenAIError, OSError, ValueError, RuntimeError, TimeoutError) as error:
        print(
            f"Audit failed ({type(error).__name__}). Check configuration and the run ledger.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
