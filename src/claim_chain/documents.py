"""Local document ingestion and searchable, chunked source evidence."""

from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from shutil import copy2
from typing import Any

from .models import Source

_SUPPORTED = {".pdf", ".txt", ".html", ".htm", ".md"}
_CHUNK_SIZE = 3000
_PDF: Any = importlib.import_module("pymupdf")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        elif tag in {"p", "div", "li", "br", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1
        elif tag in {"p", "div", "li", "br", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _extract_text(path: Path) -> list[tuple[str, str]]:
    if path.suffix.lower() == ".pdf":
        with _PDF.open(path) as document:
            return [(f"page {number}", page.get_text()) for number, page in enumerate(document, 1)]
    content = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm"}:
        parser = _TextExtractor()
        parser.feed(content)
        content = "".join(parser.parts)
    return [("text", content)]


def _chunks(text: str) -> list[str]:
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        while len(paragraph) > _CHUNK_SIZE:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:_CHUNK_SIZE])
            paragraph = paragraph[_CHUNK_SIZE:]
        if current and len(current) + len(paragraph) + 1 > _CHUNK_SIZE:
            chunks.append(current)
            current = ""
        current = f"{current}\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def _read_metadata(directory: Path) -> dict[str, dict[str, Any]]:
    """Optional `metadata.json`: {"<relative path>": {"edition": str, "year": int}}."""
    path = directory / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_id(relative: str, content_hash: str) -> str:
    return "doc-" + _digest(f"{relative}\0{content_hash}".encode("utf-8"))[:20]


class DocumentStore:
    """Indexes supported local documents in an archive-local SQLite database."""

    def __init__(self, directory: Path, archive: Path) -> None:
        self.directory = directory.resolve()
        self.archive = archive.resolve()
        if self.archive == self.directory or self.directory in self.archive.parents:
            raise ValueError("Archive must be outside the documents directory.")
        self.archive.mkdir(parents=True, exist_ok=True)
        self.database = self.archive / "documents.sqlite3"
        self._initialize()
        self._ingest()
        self.sources = self._sources()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sources ("
                "id TEXT PRIMARY KEY, title TEXT NOT NULL, path TEXT NOT NULL, "
                "content_hash TEXT NOT NULL, chunk_count INTEGER NOT NULL, "
                "page_count INTEGER NOT NULL, blank_pages INTEGER NOT NULL, "
                "error TEXT NOT NULL, warning TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS chunks ("
                "id TEXT PRIMARY KEY, source_id TEXT NOT NULL, number INTEGER NOT NULL, "
                "locator TEXT NOT NULL, text TEXT NOT NULL, UNIQUE(source_id, number))"
            )
            connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(chunk_id UNINDEXED, source_id UNINDEXED, text)")

    def _ingest(self) -> None:
        if not self.directory.is_dir():
            raise NotADirectoryError(self.directory)
        with self._connect() as connection:
            paths = sorted(p for p in self.directory.rglob("*") if p.is_file() and p.suffix.lower() in _SUPPORTED)
            active_ids = {_source_id(path.relative_to(self.directory).as_posix(), _digest(path.read_bytes())) for path in paths}
            for path in paths:
                self._ingest_file(connection, path)
            existing_ids = {row[0] for row in connection.execute("SELECT id FROM sources")}
            stale_ids = existing_ids - active_ids
            for source_id in stale_ids:
                connection.execute("DELETE FROM chunk_search WHERE source_id = ?", (source_id,))
                connection.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
                connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def _ingest_file(self, connection: sqlite3.Connection, path: Path) -> None:
        relative = path.relative_to(self.directory).as_posix()
        content_hash = _digest(path.read_bytes())
        source_id = _source_id(relative, content_hash)
        destination = self.archive / source_id / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(path, destination)
        try:
            pages = _extract_text(destination)
            passages = self._make_passages(pages)
            blank_pages = sum(not text.strip() for _, text in pages) if path.suffix.lower() == ".pdf" else 0
            error = "No extractable text; file may be scanned or blank." if path.suffix.lower() == ".pdf" and not passages else ""
            warning = f"{blank_pages} PDF page(s) had no extractable text." if blank_pages else ""
        except Exception as exception:
            pages, passages = [], []
            blank_pages = 0
            error = f"{type(exception).__name__}: {exception}"
            warning = ""
        self._store_source(
            connection,
            source_id,
            path.name,
            relative,
            content_hash,
            len(passages),
            len(pages),
            blank_pages,
            error,
            warning,
        )
        self._store_passages(connection, source_id, passages)

    @staticmethod
    def _make_passages(pages: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return [
            (f"{page_locator}, chunk {number}", text)
            for page_locator, page_text in pages
            for number, text in enumerate(_chunks(page_text), 1)
        ]

    @staticmethod
    def _store_source(
        connection: sqlite3.Connection,
        source_id: str,
        title: str,
        path: str,
        content_hash: str,
        chunk_count: int,
        page_count: int,
        blank_pages: int,
        error: str,
        warning: str,
    ) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source_id, title, path, content_hash, chunk_count, page_count, blank_pages, error, warning),
        )

    @staticmethod
    def _store_passages(
        connection: sqlite3.Connection,
        source_id: str,
        passages: list[tuple[str, str]],
    ) -> None:
        connection.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
        connection.execute("DELETE FROM chunk_search WHERE source_id = ?", (source_id,))
        for number, (locator, text) in enumerate(passages, 1):
            passage_id = "passage-" + _digest(f"{source_id}\0{number}\0{locator}\0{text}".encode("utf-8"))[:24]
            connection.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)", (passage_id, source_id, number, locator, text))
            connection.execute("INSERT INTO chunk_search VALUES (?, ?, ?)", (passage_id, source_id, text))

    def _sources(self) -> tuple[Source, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id, title, path FROM sources ORDER BY path").fetchall()
        metadata = _read_metadata(self.directory)
        return tuple(
            Source(
                id=row["id"],
                title=row["title"],
                edition=str(metadata.get(row["path"], {}).get("edition", row["title"])),
                year=int(metadata.get(row["path"], {}).get("year", 0)),
                passages=(),
            )
            for row in rows
        )

    def list_sources(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, path, content_hash, chunk_count, page_count, blank_pages, error, warning "
                "FROM sources ORDER BY path"
            ).fetchall()
        metadata = {
            row["id"]: {
                "path": row["path"],
                "content_hash": row["content_hash"],
                "chunk_count": row["chunk_count"],
                "page_count": row["page_count"],
                "blank_pages": row["blank_pages"],
                "error": row["error"],
                "warning": row["warning"],
            }
            for row in rows
        }
        return {"sources": [{**source.model_dump(mode="json"), "manifest": metadata[source.id]} for source in self.sources]}

    def search_source(self, source_id: str, query: str, limit: int = 5) -> dict[str, Any]:
        self._require_source(source_id)
        if not query.strip():
            raise ValueError("Search query must not be empty.")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT c.id, c.number, c.locator, snippet(chunk_search, 2, '', '', ' … ', 18) AS snippet "
                "FROM chunk_search JOIN chunks c ON c.id = chunk_search.chunk_id "
                "WHERE chunk_search MATCH ? AND c.source_id = ? ORDER BY rank LIMIT ?",
                (query, source_id, max(1, min(limit, 10))),
            ).fetchall()
        matches = [
            {"id": row["id"], "chunk": row["number"], "locator": row["locator"], "snippet": row["snippet"]}
            for row in rows
        ]
        return {"source_id": source_id, "matches": matches}

    def read_source(self, source_id: str, start: int = 1, count: int = 1) -> dict[str, Any]:
        self._require_source(source_id)
        if start < 1 or count < 1:
            raise ValueError("start and count must be positive.")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, number, locator, text FROM chunks WHERE source_id = ? AND number >= ? ORDER BY number LIMIT ?",
                (source_id, start, min(count, 3)),
            ).fetchall()
        passages = [
            {"id": row["id"], "chunk": row["number"], "locator": row["locator"], "text": row["text"]}
            for row in rows
        ]
        return {"source_id": source_id, "passages": passages}

    def _require_source(self, source_id: str) -> None:
        if source_id not in {source.id for source in self.sources}:
            raise KeyError(f"Unknown source: {source_id}")

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "list_sources":
            return self.list_sources()
        if name == "search_source":
            return self.search_source(str(args["source_id"]), str(args["query"]), int(args.get("limit", 5)))
        if name == "read_source":
            return self.read_source(str(args["source_id"]), int(args.get("start", 1)), int(args.get("count", 1)))
        raise ValueError(f"Unknown document tool: {name}")
