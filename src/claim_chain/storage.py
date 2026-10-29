"""Append-only run events and exact-byte review checks."""

import json
import sqlite3
from pathlib import Path
from typing import cast

from .corpus import digest


class Ledger:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE events (sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )

    def record(self, kind: str, payload: dict[str, object]) -> None:
        self.connection.execute(
            "INSERT INTO events(kind, body) VALUES (?, ?)",
            (kind, json.dumps(payload, ensure_ascii=False)),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def verify_review(directory: Path) -> bool:
    record = cast(dict[str, object], json.loads((directory / "review.json").read_text()))
    if not isinstance(record, dict) or not (directory / "ledger.sqlite").is_file():
        return False
    try:
        with sqlite3.connect(directory / "ledger.sqlite") as connection:
            row = connection.execute(
                "SELECT body FROM events WHERE kind='review' ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
    except sqlite3.DatabaseError:
        return False
    if row is None or json.loads(row[0]) != record:
        return False
    return (
        record.get("approved") is True
        and record.get("reviewer") == "reviewer"
        and record.get("report_hash") == digest((directory / "report.md").read_bytes())
        and record.get("snapshot_hash") == digest((directory / "snapshot.json").read_bytes())
    )
