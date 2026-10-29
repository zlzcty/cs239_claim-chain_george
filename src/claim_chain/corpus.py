"""Local source loading and edition-specific graph checks."""

import hashlib
from collections.abc import Sequence
from pathlib import Path

from .models import Corpus, Investigation, Source


def load_corpus(path: Path) -> Corpus:
    corpus = Corpus.model_validate_json(path.read_text(encoding="utf-8"))
    ids = [source.id for source in corpus.sources]
    if len(set(ids)) != len(ids) or set(ids) & set(corpus.unavailable):
        raise ValueError("Source IDs must be unique edition identities.")
    passages = [p.id for s in corpus.sources for p in s.passages]
    if len(set(passages)) != len(passages):
        raise ValueError("Passage IDs must be unique.")
    known = set(ids) | set(corpus.unavailable)
    references = set(corpus.seeds) | {
        ref for s in corpus.sources for p in s.passages for ref in p.cites
    }
    if not references <= known:
        raise ValueError(f"Unknown source references: {references - known}")
    if any(len(s.model_dump_json()) > 16000 for s in corpus.sources):
        raise ValueError("Demo sources must fit the 16,000-character excerpt limit.")
    return corpus


def validate_finding(source: Source, finding: Investigation, known: set[str]) -> None:
    passages = {p.id: p.text for p in source.passages}
    for quote in finding.quotes:
        if quote.passage_id not in passages or quote.text not in passages[quote.passage_id]:
            raise ValueError(f"Unverified quotation: {quote.passage_id}")
    if finding.assessment != "insufficient" and not finding.quotes:
        raise ValueError("An evidence assessment requires a verified quotation.")
    for citation in finding.citations:
        if citation.passage_id not in passages or citation.reference not in passages[citation.passage_id]:
            raise ValueError("Citation requires an opened passage containing the reference text.")
    if not set(finding.followups) <= known:
        raise ValueError("Investigator proposed an unknown source.")


def digest(text: str | bytes) -> str:
    return hashlib.sha256(text.encode("utf-8") if isinstance(text, str) else text).hexdigest()


def citation_cycles(sources: Sequence[Source]) -> tuple[tuple[str, ...], ...]:
    graph = {s.id: {ref for p in s.passages for ref in p.cites} for s in sources}
    found: set[tuple[str, ...]] = set()

    def walk(node: str, path: tuple[str, ...]) -> None:
        if node in path:
            cycle = path[path.index(node) :]
            found.add(min(cycle[i:] + cycle[:i] for i in range(len(cycle))))
            return
        for target in graph.get(node, set()):
            walk(target, (*path, node))

    for source_id in graph:
        walk(source_id, ())
    return tuple(sorted(found))
