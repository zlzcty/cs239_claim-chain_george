from claim_chain.provider import ToolSession
import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, RateLimitError
from pydantic import BaseModel

from claim_chain.corpus import citation_cycles, digest, validate_finding, verified_citations
from claim_chain.models import (
    Corpus,
    Draft,
    Citation,
    Investigation,
    Job,
    Passage,
    Plan,
    Preliminary,
    Quote,
    Review,
    Source,
)
from claim_chain.storage import Ledger, verify_review
from claim_chain.workflow import FINISH_CALL_RESERVE, MIN_CALLS, Audit


def source(source_id: str, edition: str, cites: tuple[str, ...] = ()) -> Source:
    return Source(
        id=source_id,
        title="Town Register",
        edition=edition,
        year=1920,
        passages=(
            Passage(
                id=f"{source_id}-p1",
                locator="p. 1",
                text="The bridge opened in 1920.",
                cites=cites,
            ),
        ),
    )


def test_finding_quotes_must_match_passage_verbatim() -> None:
    document = source("register-v1", "first edition")
    known = {document.id}
    valid = Investigation(
        assessment="supported",
        reasoning="The passage states the claim.",
        quotes=(Quote(passage_id="register-v1-p1", text="The bridge opened in 1920."),),
        followups=(),
    )
    validate_finding(document, valid, known)
    invalid = valid.model_copy(
        update={"quotes": (Quote(passage_id="register-v1-p1", text="It opened in 1920."),)}
    )
    with pytest.raises(ValueError, match="Unverified quotation"):
        validate_finding(document, invalid, known)


def test_edition_specific_cycle_excludes_apparent_cross_edition_loop() -> None:
    first_edition = source("register-v1", "first edition", ("harbor-notes",))
    revised_edition = source("register-v2", "revised edition", ("harbor-notes",))
    harbor = source("harbor-notes", "1925 notebook", ("register-v2",))

    cycles = citation_cycles((first_edition, revised_edition, harbor))

    assert cycles == (("harbor-notes", "register-v2"),)
    assert "register-v1" not in cycles[0]


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.payloads: dict[str, dict[str, object]] = {}

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
        self.calls += 1
        assert role == "investigator"
        assert stage == "inspect"
        assert isinstance(payload, dict)
        source_payload = payload["source"]
        source_model = Source.model_validate(source_payload)
        self.payloads[source_model.id] = payload
        assert job_id == f"inspect:{source_model.id}"
        passage = source_model.passages[0]
        finding = Investigation(
            assessment="supported",
            reasoning=f"Inspected {source_model.id}.",
            quotes=(Quote(passage_id=passage.id, text=passage.text),),
            followups=(),
        )
        result = response_type.model_validate(finding.model_dump())
        if validator:
            validator(result)
        return result


class FakeWorkflowClient:
    def __init__(self) -> None:
        self.calls = 0
        self.plans = 0
        self.preliminary_payload: object = None

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
        self.calls += 1
        if stage == "plan":
            self.plans += 1
            value: BaseModel = Plan(
                jobs=(Job(source_id="alpha", question="inspect alpha"),)
                if self.plans == 1
                else (),
                rationale="Inspect the supplied seed.",
            )
        elif stage == "inspect":
            assert isinstance(payload, dict)
            document = Source.model_validate(payload["source"])
            passage = document.passages[0]
            value = Investigation(
                assessment="supported",
                reasoning="The located passage states the claim.",
                quotes=(Quote(passage_id=passage.id, text=passage.text),),
                followups=(),
            )
        elif stage == "preliminary":
            self.preliminary_payload = payload
            value = Preliminary(
                assessment="supported",
                reasoning="Evidence contains an explicit statement.",
                alternatives=(),
            )
        elif stage == "draft":
            value = Draft(
                assessment="supported",
                reasoning="The inspected passage directly states the claim.",
                decisive_passages=("alpha-p1",),
                earliest_source_id="alpha",
                limitations=(),
            )
        else:
            assert stage == "review"
            value = Review(approved=True, issues=(), required_changes=())
        result = response_type.model_validate(value.model_dump())
        if validator:
            validator(result)
        return result


def test_dispatch_waits_for_prerequisite_and_admission_deduplicates_source(tmp_path: Path) -> None:
    async def run() -> tuple[list[tuple[str, str]], int]:
        alpha = source("alpha", "edition A")
        beta = source("beta", "edition B")
        gamma = source("gamma", "edition C")
        ledger = Ledger(tmp_path / "ledger.sqlite")
        client = FakeClient()
        audit = Audit(
            Corpus(claim="Bridge opened", seeds=("alpha",), sources=(alpha, beta, gamma)),
            client,
            ledger,
        )
        admitted = audit.admit(
            (
                Job(source_id="alpha", question="inspect A"),
                Job(source_id="alpha", question="duplicate A"),
                Job(source_id="beta", question="inspect B"),
            ),
            allowance=3,
        )
        await audit.dispatch(
            (
                Job(source_id="alpha", question="inspect A"),
                Job(source_id="beta", question="inspect B", depends_on=("alpha",)),
                Job(source_id="gamma", question="inspect C"),
            )
        )
        assert client.payloads["alpha"]["dependencies"] == {}
        assert client.payloads["gamma"]["dependencies"] == {}
        assert client.payloads["beta"]["dependencies"] == {
            "alpha": {
                "source": alpha.model_dump(),
                "finding": audit.findings["alpha"].model_dump(),
            }
        }
        records = ledger.connection.execute(
            "SELECT kind, body FROM events WHERE kind = 'trajectory' ORDER BY sequence"
        ).fetchall()
        ledger.close()
        return [(kind, json.loads(body)["text"]) for kind, body in records], len(admitted)

    trajectory, admitted_count = asyncio.run(run())
    queue_events = [text for _, text in trajectory if text.startswith("Dispatch")]
    assert queue_events == [
        "Dispatch alpha: inspect A",
        "Dispatch gamma: inspect C",
        "Dispatch beta: inspect B",
    ]
    assert admitted_count == 2


def test_review_sequence_uses_evidence_first_and_binds_approved_bytes(tmp_path: Path) -> None:
    async def run() -> tuple[FakeWorkflowClient, list[str]]:
        document = source("alpha", "edition A")
        corpus = Corpus(claim="The bridge opened in 1920.", seeds=("alpha",), sources=(document,))
        ledger = Ledger(tmp_path / "ledger.sqlite")
        client = FakeWorkflowClient()
        audit = Audit(corpus, client, ledger)
        await audit.research(max_sources=2, research_calls=16)
        await audit.finish(tmp_path)
        order = [
            row[0]
            for row in ledger.connection.execute(
                "SELECT kind FROM events WHERE kind IN ('preliminary_review', 'report') ORDER BY sequence"
            ).fetchall()
        ]
        ledger.close()
        return client, order

    client, order = asyncio.run(run())
    assert isinstance(client.preliminary_payload, dict)
    assert "sources" in client.preliminary_payload
    assert "findings" not in client.preliminary_payload
    assert order == ["preliminary_review", "report"]
    assert verify_review(tmp_path)

    report_path = tmp_path / "report.md"
    report_path.write_bytes(report_path.read_bytes() + b"changed after approval")
    assert not verify_review(tmp_path)


@pytest.mark.parametrize("tampered_file", ["report.md", "snapshot.json"])
@pytest.mark.parametrize("line_ending", ["append", "crlf"])
def test_review_verification_rejects_tampered_bytes(
    tmp_path: Path, tampered_file: str, line_ending: str
) -> None:
    report = "# Report\n"
    snapshot = '{"claim":"example"}\n'
    (tmp_path / "report.md").write_bytes(report.encode())
    (tmp_path / "snapshot.json").write_bytes(snapshot.encode())
    record: dict[str, object] = {
        "approved": True,
        "reviewer": "reviewer",
        "report_hash": digest(report),
        "snapshot_hash": digest(snapshot),
    }
    (tmp_path / "review.json").write_text(json.dumps(record), encoding="utf-8")
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record("review", record)
    ledger.close()
    assert verify_review(tmp_path)

    path = tmp_path / tampered_file
    if line_ending == "crlf":
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    else:
        path.write_bytes(path.read_bytes() + b"tampered\n")
    assert not verify_review(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["connection", "timeout", "rate_limit"])
async def test_provider_failure_leaves_independent_work_running(
    tmp_path: Path, failure_kind: str
) -> None:
    started = asyncio.Event()
    request = httpx.Request("POST", "https://mock.invalid/v1/chat/completions")
    failures = {
        "connection": APIConnectionError(request=request),
        "timeout": APITimeoutError(request=request),
        "rate_limit": RateLimitError(
            "rate limited", response=httpx.Response(429, request=request), body=None
        ),
    }

    class FailingClient(FakeClient):
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
            if job_id == "inspect:alpha":
                await started.wait()
                raise failures[failure_kind]
            started.set()
            await asyncio.sleep(0)
            return await super().chat(
                role, stage, payload, response_type, validator, job_id=job_id
            )

    documents = tuple(source(name, name) for name in ("alpha", "beta", "gamma", "delta"))
    ledger = Ledger(tmp_path / "ledger.sqlite")
    try:
        client = FailingClient()
        audit = Audit(
            Corpus(claim="Bridge opened", seeds=("alpha",), sources=documents), client, ledger
        )
        await audit.dispatch(
            (
                Job(source_id="alpha", question="inspect A"),
                Job(source_id="beta", question="inspect B"),
                Job(source_id="gamma", question="compare A", depends_on=("alpha",)),
                Job(source_id="delta", question="compare B", depends_on=("beta",)),
            )
        )
        assert set(audit.findings) == {"beta", "delta"}
        assert "gamma" not in audit.attempted
        records = {
            kind: json.loads(body)
            for kind, body in ledger.connection.execute(
                "SELECT kind, body FROM events WHERE kind IN ('job_failed', 'job_blocked')"
            )
        }
        assert records["job_failed"]["job_id"] == "inspect:alpha"
        assert records["job_blocked"]["job_id"] == "inspect:gamma"
        assert any(type(failures[failure_kind]).__name__ in item for item in audit.limitations)
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_dispatch_propagates_cancellation_to_all_workers(tmp_path: Path) -> None:
    both_started = asyncio.Event()
    running: set[str] = set()
    cancelled: set[str] = set()

    class WaitingClient(FakeClient):
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
            running.add(job_id)
            if len(running) == 2:
                both_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.add(job_id)
            raise AssertionError("Waiting worker unexpectedly resumed.")

    documents = (source("alpha", "A"), source("beta", "B"))
    ledger = Ledger(tmp_path / "ledger.sqlite")
    try:
        audit = Audit(
            Corpus(claim="Bridge opened", seeds=("alpha",), sources=documents),
            WaitingClient(),
            ledger,
        )
        task = asyncio.create_task(
            audit.dispatch(
                tuple(Job(source_id=document.id, question="inspect") for document in documents)
            )
        )
        await asyncio.wait_for(both_started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled == {"inspect:alpha", "inspect:beta"}
        assert not audit.findings
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_minimum_budget_covers_research_and_two_reviews_with_all_corrections(
    tmp_path: Path,
) -> None:
    from openai import AsyncOpenAI
    from pydantic import SecretStr

    from claim_chain.provider import ClientConfig, ModelClient

    document = source("alpha", "A")
    passage = document.passages[0]
    plan = Plan(jobs=(Job(source_id="alpha", question="inspect"),), rationale="Inspect seed.")
    finding = Investigation(
        assessment="supported",
        reasoning="Direct statement.",
        quotes=(Quote(passage_id=passage.id, text=passage.text),),
        followups=(),
    )
    preliminary = Preliminary(
        assessment="supported", reasoning="Direct statement.", alternatives=()
    )
    draft = Draft(
        assessment="supported",
        reasoning="The passage states the claim.",
        decisive_passages=(passage.id,),
        earliest_source_id=document.id,
        limitations=(),
    )
    rejection = Review(approved=False, issues=("Clarify uncertainty.",), required_changes=())
    approval = Review(approved=True, issues=(), required_changes=())
    outputs = iter(
        text
        for result in (plan, finding, preliminary, draft, rejection, draft, approval)
        for text in ("invalid JSON", result.model_dump_json())
    )

    def complete(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": next(outputs)},
                    }
                ],
            },
        )

    sdk = AsyncOpenAI(
        api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(complete))
    )
    config = ClientConfig(
        base_url="https://mock.invalid/v1",
        api_key=SecretStr("test"),
        model="test",
        max_calls=MIN_CALLS,
    )
    ledger = Ledger(tmp_path / "ledger.sqlite")
    try:
        async with ModelClient(config, sdk_client=sdk, event_callback=ledger.record) as client:
            audit = Audit(
                Corpus(claim="Bridge opened", seeds=(document.id,), sources=(document,)),
                client,
                ledger,
            )
            await audit.research(2, MIN_CALLS - FINISH_CALL_RESERVE)
            assert set(audit.findings) == {"alpha"}
            assert MIN_CALLS - client.calls == FINISH_CALL_RESERVE
            await audit.finish(tmp_path)
            assert client.calls == MIN_CALLS
        assert verify_review(tmp_path)
        review = json.loads((tmp_path / "review.json").read_text())
        assert review["report_version"] == 2
        assert list(outputs) == []
    finally:
        ledger.close()


def test_verified_citations_drop_references_missing_from_opened_text() -> None:
    source = Source(
        id="a", title="A", edition="1", year=1900,
        passages=(Passage(id="p1", locator="1", text="See the Register for details."),),
    )
    kept = Citation(passage_id="p1", reference="the Register", target_id="register")
    finding = Investigation(
        assessment="insufficient", reasoning="r", quotes=(), followups=(),
        citations=(
            kept,
            Citation(passage_id="p1", reference="Louis XVIII", target_id="unresolved"),
            Citation(passage_id="p2", reference="the Register", target_id="register"),
        ),
    )
    assert verified_citations(source, finding) == (kept,)


def test_quotes_match_ignoring_whitespace_differences() -> None:
    source = Source(
        id="a", title="A", edition="1", year=1900,
        passages=(Passage(id="p1", locator="1", text="Translated  from\nRousseau, p. 262."),),
    )
    finding = Investigation(
        assessment="supported", reasoning="r", followups=(),
        quotes=(Quote(passage_id="p1", text="Translated from Rousseau, p. 262."),),
    )
    validate_finding(source, finding, set())
    bad = finding.model_copy(update={"quotes": (Quote(passage_id="p1", text="Translated from Voltaire"),)})
    with pytest.raises(ValueError, match="Unverified quotation"):
        validate_finding(source, bad, set())
