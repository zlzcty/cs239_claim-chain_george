"""Validated messages exchanged by the local agents."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Assessment = Literal["supported", "contradicted", "mixed", "insufficient"]


class Passage(Message):
    id: str
    locator: str
    text: str
    cites: tuple[str, ...] = ()


class Source(Message):
    id: str
    title: str
    edition: str
    year: int
    passages: tuple[Passage, ...]
    manifest: dict[str, object] = Field(default_factory=dict)


class Corpus(Message):
    claim: str
    seeds: tuple[str, ...]
    sources: tuple[Source, ...]
    unavailable: tuple[str, ...] = ()


class Job(Message):
    source_id: str
    question: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()

    @property
    def job_id(self) -> str:
        """The runner admits at most one investigation per source in a run."""
        return f"inspect:{self.source_id}"


class Plan(Message):
    jobs: tuple[Job, ...] = Field(max_length=4)
    rationale: str


class Quote(Message):
    passage_id: str
    text: str = Field(min_length=1)


class Citation(Message):
    passage_id: str
    reference: str = Field(min_length=1)
    target_id: str


class Investigation(Message):
    assessment: Assessment
    reasoning: str
    quotes: tuple[Quote, ...]
    citations: tuple[Citation, ...] = ()
    followups: tuple[str, ...] = Field(
        description="Bare source IDs copied exactly from catalog, such as register-v1. Never questions or sentences. Empty if no follow-up is needed."
    )


class Preliminary(Message):
    assessment: Assessment
    reasoning: str
    alternatives: tuple[str, ...]


class Draft(Message):
    assessment: Assessment
    reasoning: str
    decisive_passages: tuple[str, ...] = Field(
        description="Bare passage IDs copied exactly from inspected sources. No quotations, labels, or commentary in these strings."
    )
    earliest_source_id: str | None
    limitations: tuple[str, ...] = Field(
        description="Additional limitations not already in evidence.limitations. Do not repeat source scope or access failures."
    )


class Review(Message):
    approved: bool
    issues: tuple[str, ...]
    required_changes: tuple[str, ...]
