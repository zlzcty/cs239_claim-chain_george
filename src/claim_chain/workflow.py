"""Bounded local agent scheduling, evidence snapshots, and review."""

import asyncio
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from mcp import ClientSession
from openai import OpenAIError
from pydantic import BaseModel

from .corpus import citation_cycles, digest, validate_finding
from .document_client import DocumentTools, document_definitions
from .models import Corpus, Draft, Investigation, Job, Plan, Preliminary, Review, Source
from .provider import MAX_CALL_ATTEMPTS, ToolSession
from .storage import Ledger

REPORT_ROUNDS = 2
FINISH_CALL_RESERVE = MAX_CALL_ATTEMPTS * (1 + 2 * REPORT_ROUNDS)
MIN_CALLS = FINISH_CALL_RESERVE + 2 * MAX_CALL_ATTEMPTS
DOCUMENT_REVIEW_RESERVE = 10
DOCUMENT_JOB_CALLS = 10


class AgentClient(Protocol):
    @property
    def calls(self) -> int: ...

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
    ) -> T: ...


def catalog(corpus: Corpus) -> list[dict[str, object]]:
    return [
        {"id": s.id, "title": s.title, "edition": s.edition, "year": s.year, "manifest": s.manifest}
        for s in corpus.sources
    ] + [{"id": source_id, "availability": "unavailable"} for source_id in corpus.unavailable]


def research_capacity(source_slots: int, call_slots: int) -> int:
    """Reserve correction attempts for planning and each admitted investigation."""
    investigation_calls = max(0, call_slots - MAX_CALL_ATTEMPTS)
    return min(source_slots, 4, investigation_calls // MAX_CALL_ATTEMPTS)


class Audit:
    def __init__(
        self, corpus: Corpus, client: AgentClient, ledger: Ledger,
        documents: ClientSession | None = None,
    ) -> None:
        self.documents = documents
        self.research_limit: int | None = None
        self.corpus = corpus
        self.client = client
        self.ledger = ledger
        self.inspected: dict[str, Source] = {}
        self.findings: dict[str, Investigation] = {}
        self.attempted: set[str] = set()
        self.limitations: list[str] = []

    def event(self, role: str, text: str) -> None:
        print(f"[{role}] {text}", flush=True)
        self.ledger.record("trajectory", {"role": role, "text": text})

    async def research(self, max_sources: int, research_calls: int) -> None:
        self.research_limit = research_calls
        for wave in range(3):
            remaining = max_sources - len(self.attempted)
            max_jobs = research_capacity(remaining, research_calls - self.client.calls)
            if self.documents is not None:
                available = research_calls - self.client.calls - MAX_CALL_ATTEMPTS
                max_jobs = min(remaining, 4, max(0, available // DOCUMENT_JOB_CALLS))
            if max_jobs <= 0:
                self.limitations.append("Research source or call allowance reached.")
                break
            self.event("Lead", f"Planning research wave {wave + 1}.")
            plan = await self.client.chat(
                "research-lead",
                "plan",
                {
                    "claim": self.corpus.claim,
                    "catalog": catalog(self.corpus),
                    "seeds": self.corpus.seeds,
                    "attempted": sorted(self.attempted),
                    "findings": {key: value.model_dump() for key, value in self.findings.items()},
                    "max_jobs": max_jobs,
                    "instruction": "Initially prioritize seeds within max_jobs. Later choose proposed citations and counterevidence. Each job inspects ONE source_id from catalog. depends_on lists source IDs of prerequisite jobs, or is empty. Do not repeat attempted sources. Empty jobs ends research.",
                },
                Plan,
                job_id=f"plan:{wave + 1}",
            )
            self.ledger.record("plan", plan.model_dump())
            if not plan.jobs:
                break
            jobs = self.admit(plan.jobs, max_jobs)
            await self.dispatch(jobs)
        uninspected = {
            target
            for source in self.inspected.values()
            for passage in source.passages
            for target in passage.cites
            if target not in self.inspected
        }
        if uninspected:
            self.limitations.append(
                "Uninspected citation targets: " + ", ".join(sorted(uninspected))
            )
        self.limitations.append(
            "Local documents only; no web discovery. Search coverage is partial; failed searches do not establish absence."
            if self.documents else
            "Local supplied excerpts only; no document search or extraction."
        )

    def admit(self, proposed: Sequence[Job], allowance: int) -> list[Job]:
        known = {s.id for s in self.corpus.sources} | set(self.corpus.unavailable)
        jobs: list[Job] = []
        selected: set[str] = set()
        for job in proposed:
            if job.source_id not in known:
                self.limitations.append(f"Lead proposed unknown source: {job.source_id}.")
            elif job.source_id not in self.attempted | selected and len(jobs) < allowance:
                jobs.append(job)
                selected.add(job.source_id)
                self.ledger.record("job_admitted", {**job.model_dump(), "job_id": job.job_id})
        return jobs

    async def dispatch(self, jobs: Sequence[Job]) -> None:
        pending = list(jobs)
        while pending:
            ready = [job for job in pending if set(job.depends_on) <= self.findings.keys()]
            if not ready:
                for job in pending:
                    self.ledger.record("job_blocked", {**job.model_dump(), "job_id": job.job_id})
                self.limitations.append(
                    "Jobs blocked by unsatisfied or cyclic dependencies: "
                    + ", ".join(j.source_id for j in pending)
                )
                return
            batch = ready[:2]
            for job in batch:
                self.event("Queue", f"Dispatch {job.source_id}: {job.question}")
            attempts = [asyncio.create_task(self.investigate(job)) for job in batch]
            try:
                await asyncio.gather(*attempts)
            except BaseException:
                for attempt in attempts:
                    attempt.cancel()
                await asyncio.gather(*attempts, return_exceptions=True)
                raise
            for job in batch:
                pending.remove(job)

    async def investigate(self, job: Job) -> None:
        self.attempted.add(job.source_id)
        self.ledger.record("job_running", {**job.model_dump(), "job_id": job.job_id})
        source = next((s for s in self.corpus.sources if s.id == job.source_id), None)
        if source is None:
            self.limitations.append(
                f"Source unavailable: {job.source_id}; no inference of absence."
            )
            self.ledger.record(
                "source_request",
                {"job_id": job.job_id, "source_id": job.source_id, "reason": job.question},
            )
            self.event("Investigator", f"{job.source_id}: unavailable; source request recorded.")
            return
        tools = None
        if self.documents is not None:
            tools = DocumentTools(
                self.documents, await document_definitions(self.documents), (source.id,)
            )
        if tools is None:
            self.inspected[source.id] = source
            self.ledger.record("source_inspected", source.model_dump())
        assigned_source = source
        try:
            finding = await self.client.chat(
                "investigator",
                "inspect",
                {
                    "claim": self.corpus.claim,
                    "question": job.question,
                    "source": source.model_dump(),
                    "dependencies": {
                        source_id: {
                            "source": self.inspected[source_id].model_dump(),
                            "finding": self.findings[source_id].model_dump(),
                        }
                        for source_id in job.depends_on
                    },
                    "catalog": catalog(self.corpus),
                    "instruction": "If tools are available, search and read the assigned full document before answering. Search snippets are not opened evidence. Use read_source to obtain passage IDs and inspect surrounding chunks. Identify references in the text and propose matching catalog IDs; say when a reference cannot be matched. Source year 0 means unknown, never an earliest date. Assess this source with the supplied prerequisite evidence. Quote only the assigned source, using verbatim substrings as quotes. Propose source IDs to inspect next. A citation/claim repeated by a source is not itself independent evidence of truth.",
                },
                Investigation,
                validator=lambda result: validate_finding(
                    tools.source(assigned_source) if tools is not None else assigned_source,
                    result,
                    {s.id for s in self.corpus.sources} | set(self.corpus.unavailable),
                ),
                job_id=job.job_id,
                tools=tools,
                call_limit=self.research_limit,
            )
        except (OpenAIError, ValueError, RuntimeError) as error:
            self.limitations.append(
                f"Investigation rejected for {source.id}: {type(error).__name__}."
            )
            self.ledger.record(
                "job_failed",
                {"job_id": job.job_id, "source_id": source.id, "error_type": type(error).__name__},
            )
            self.event(
                "Investigator",
                f"{source.id}: investigation failed; preserved source, no accepted finding.",
            )
            return
        if tools is not None:
            source = tools.source(source)
            self.inspected[source.id] = source
            self.ledger.record("source_inspected", source.model_dump())
        links = {
            passage.id: tuple(dict.fromkeys((*passage.cites, *(
                link.target_id for link in finding.citations if link.passage_id == passage.id
            )))) for passage in source.passages
        }
        source = source.model_copy(update={"passages": tuple(
            passage.model_copy(update={"cites": links[passage.id]})
            for passage in source.passages
        )})
        self.inspected[source.id] = source
        self.findings[source.id] = finding
        self.ledger.record(
            "job_completed",
            {"job_id": job.job_id, "source_id": source.id, "result": finding.model_dump()},
        )
        self.event(
            "Investigator",
            f"{source.id}: {finding.assessment}; {len(finding.quotes)} verified quotation(s).",
        )

    async def finish(self, output: Path) -> None:
        review_tools = None
        if self.documents is not None:
            review_tools = DocumentTools(
                self.documents, await document_definitions(self.documents),
                tuple(source.id for source in self.corpus.sources),
            )
        evidence = {
            "claim": self.corpus.claim,
            "sources": [s.model_dump() for s in self.inspected.values()],
            "catalog": catalog(self.corpus),
            "citation_cycles": citation_cycles(tuple(self.inspected.values())),
            "limitations": self.limitations,
        }
        self.event(
            "Reviewer", "Assessing evidence before receiving any draft or Investigator findings."
        )
        preliminary = await self.client.chat(
            "reviewer", "preliminary", evidence, Preliminary, job_id="review:preliminary",
            tools=review_tools,
            call_limit=(self.research_limit + DOCUMENT_REVIEW_RESERVE) if review_tools and self.research_limit else None,
        )
        if review_tools is not None:
            for metadata in self.corpus.sources:
                extra = review_tools.source(metadata)
                if not extra.passages:
                    continue
                previous = self.inspected.get(metadata.id, metadata)
                combined = {passage.id: passage for passage in (*previous.passages, *extra.passages)}
                self.inspected[metadata.id] = previous.model_copy(
                    update={"passages": tuple(combined.values())}
                )
                self.ledger.record("source_inspected", self.inspected[metadata.id].model_dump())
            evidence["sources"] = [source.model_dump() for source in self.inspected.values()]
        snapshot = json.dumps(evidence, ensure_ascii=False, indent=2)
        snapshot_hash = digest(snapshot)
        (output / "snapshot.json").write_bytes(snapshot.encode("utf-8"))
        self.ledger.record("snapshot", {"hash": snapshot_hash, "body": evidence})
        self.ledger.record("preliminary_review", preliminary.model_dump())
        (output / "preliminary.json").write_text(
            preliminary.model_dump_json(indent=2), encoding="utf-8"
        )
        draft_input: dict[str, object] = {
            "evidence": evidence,
            "findings": {key: value.model_dump() for key, value in self.findings.items()},
            "instruction": "Year 0 means unknown; earliest_source_id must be null for undated documents. Draft a bounded evidence assessment, cite only inspected passage IDs, choose earliest_source_id only if it actually attests the claim. It means earliest attestation found within this corpus, not origin. Include unresolved links and distinguish conflicting assertions from evidence of truth.",
        }
        for round_number in range(REPORT_ROUNDS):
            self.event("Lead", f"Drafting report version {round_number + 1}.")
            draft = await self.client.chat(
                "research-lead",
                "draft",
                draft_input,
                Draft,
                validator=self.validate_draft,
                job_id=f"draft:{round_number + 1}",
            )
            report = render_report(
                self.corpus.claim, draft, tuple(self.inspected.values()), self.limitations
            )
            report_hash = digest(report)
            (output / "report.md").write_bytes(report.encode("utf-8"))
            self.ledger.record(
                "report",
                {"version": round_number + 1, "hash": report_hash, "draft": draft.model_dump()},
            )
            self.event("Reviewer", f"Checking exact report version {round_number + 1}.")
            review = await self.client.chat(
                "reviewer",
                "review",
                {
                    "evidence": evidence,
                    "preliminary": preliminary.model_dump(),
                    "report": report,
                    "report_hash": report_hash,
                    "snapshot_hash": snapshot_hash,
                    "instruction": "Approve only if report represents evidence fairly. Unsupported certainty, misidentified earliest attestations, or missing decisive evidence require corrections. Do not request new research in this final reserved stage.",
                },
                Review,
                job_id=f"review:{round_number + 1}",
            )
            approved = review.approved and not review.required_changes and not review.issues
            review_record: dict[str, object] = {
                **review.model_dump(),
                "approved": approved,
                "reviewer": "reviewer",
                "report_hash": report_hash,
                "snapshot_hash": snapshot_hash,
                "report_version": round_number + 1,
                "calls": self.client.calls,
            }
            self.ledger.record("review", review_record)
            (output / "review.json").write_text(
                json.dumps(review_record, indent=2), encoding="utf-8"
            )
            if approved:
                self.event("Reviewer", "APPROVED: exact report and snapshot hashes recorded.")
                return
            self.event(
                "Reviewer", "UNAPPROVED: " + "; ".join((*review.issues, *review.required_changes))
            )
            draft_input["previous_draft"] = draft.model_dump()
            draft_input["required_corrections"] = review.model_dump()

    def validate_draft(self, draft: Draft) -> None:
        passages = {p.id for s in self.inspected.values() for p in s.passages}
        if not set(draft.decisive_passages) <= passages:
            raise ValueError("Draft references an uninspected passage.")
        if draft.earliest_source_id is not None and (
            draft.earliest_source_id not in self.inspected
            or self.inspected[draft.earliest_source_id].year == 0
        ):
            raise ValueError("Earliest source must be inspected and have a verified year.")
        if draft.assessment != "insufficient" and not draft.decisive_passages:
            raise ValueError("Draft assessment requires inspected passage references.")


def render_report(
    claim: str, draft: Draft, sources: Sequence[Source], limitations: Sequence[str]
) -> str:
    lines = [
        "# Claim audit",
        "",
        f"Claim: {claim}",
        "",
        f"Assessment: **{draft.assessment}**",
        "",
        draft.reasoning,
        "",
        "Review status is stored separately in review.json; verify it against these exact bytes.",
        "",
        "## Evidence",
        "",
    ]
    decisive = set(draft.decisive_passages)
    for source in sources:
        for passage in source.passages:
            marker = " (decisive)" if passage.id in decisive else ""
            lines.append(
                f"- `{passage.id}`{marker}: {source.title}, {source.edition} ({source.year or "year unknown"}), {passage.locator}."
            )
            lines.extend(f"  > {line}" for line in passage.text.splitlines())
    lines.extend(["", "## Citation graph", ""])
    for source in sources:
        for passage in source.passages:
            for target in passage.cites:
                status = "inspected" if target in {s.id for s in sources} else "uninspected"
                lines.append(f"- `{source.id}` / `{passage.id}` → `{target}` ({status})")
    for cycle in citation_cycles(sources):
        lines.append("- Edition-specific cycle: " + " → ".join((*cycle, cycle[0])))
    lines.extend(
        [
            "",
            f"Earliest attestation found within scope: {draft.earliest_source_id or 'not established'}.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(
        f"- {limitation}" for limitation in dict.fromkeys((*limitations, *draft.limitations))
    )
    return "\n".join(lines) + "\n"
