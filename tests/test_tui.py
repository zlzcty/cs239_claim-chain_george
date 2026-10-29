"""The viewer follows ledger state without making provider calls."""

from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from claim_chain.storage import Ledger
from claim_chain.tui import AuditApp, read_events, source_markdown


def test_read_events_only_reads_new_records(tmp_path: Path) -> None:
    assert read_events(tmp_path, 0) == []
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record("run_started", {"claim": "Example"})
    ledger.record("job_running", {"job_id": "inspect:a"})
    ledger.close()
    assert read_events(tmp_path, 1) == [(2, "job_running", {"job_id": "inspect:a"})]


@pytest.mark.asyncio
async def test_watch_shows_actual_concurrency_and_failure(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record("run_started", {"claim": "A claim", "max_calls": 24})
    for source in ("a", "b"):
        job: dict[str, object] = {
            "job_id": f"inspect:{source}",
            "source_id": source,
            "question": "Check date",
            "depends_on": [],
        }
        ledger.record("job_running", job)
        ledger.record("model_request", {**job, "role": "investigator"})
    app = AuditApp(tmp_path, "WATCH", (), 0.1)
    async with app.run_test(size=(120, 36)) as pilot:
        await app.poll()
        await pilot.pause()
        assert len(app.active) == 2
        assert app.query_one("#jobs", DataTable).row_count == 2
        card = str(app.query_one("#investigator", Static).render())
        assert "2 active: a, b" in card
        ledger.record("model_error", {"job_id": "inspect:a", "role": "investigator"})
        ledger.record("job_failed", {"job_id": "inspect:a", "error_type": "TimeoutError"})
        ledger.record("model_response", {"job_id": "inspect:b", "role": "investigator"})
        ledger.record(
            "job_completed",
            {"job_id": "inspect:b", "source_id": "b", "result": {"assessment": "supported"}},
        )
        await app.poll()
        assert not app.active
        assert app.jobs["inspect:a"]["status"] == "failed"
        assert app.jobs["inspect:b"]["status"] == "completed"
        assert app.jobs["inspect:a"]["question"] == "Check date"
    ledger.close()


@pytest.mark.asyncio
async def test_replay_is_labeled_and_can_pause(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record("run_started", {"claim": "Recorded claim"})
    ledger.record("review", {"approved": False})
    ledger.close()
    app = AuditApp(tmp_path, "REPLAY", (), 60)
    async with app.run_test(size=(120, 36)) as pilot:
        await app.poll()
        assert app.sequence == 1
        await pilot.press("space")
        await app.poll()
        assert app.sequence == 1
        assert "REPLAY" in str(app.query_one("#banner", Static).render())
        assert "PAUSED" in str(app.query_one("#banner", Static).render())
        await pilot.press("space")
        await app.poll()
        await app.poll()
        assert app.ended
        assert app.sequence == 2


def test_source_view_retains_locator_and_citation() -> None:
    text = source_markdown(
        {
            "title": "Original",
            "year": 1900,
            "passages": [
                {
                    "id": "p1",
                    "locator": "https://example.org/source#section",
                    "text": "Quoted words",
                    "cites": ["earlier"],
                }
            ],
        }
    )
    assert "https://example.org/source#section" in text
    assert "Quoted words" in text
    assert "earlier" in text


@pytest.mark.asyncio
async def test_quitting_stops_the_owned_runner(tmp_path: Path) -> None:
    import sys

    app = AuditApp(tmp_path, "LIVE", (sys.executable, "-c", "import time; time.sleep(60)"), 0.1)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.1)
        assert app.process is not None
        assert app.process.returncode is None
    assert app.process.returncode is not None


@pytest.mark.asyncio
async def test_runner_configuration_error_is_visible(tmp_path: Path) -> None:
    import sys

    from textual.widgets import RichLog

    app = AuditApp(
        tmp_path, "LIVE", (sys.executable, "-c", "raise SystemExit('Set --model')"), 0.1
    )
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.2)
        assert app.ended
        lines = app.query_one("#feed", RichLog).lines
        assert any("Set --model" in line.text for line in lines)


@pytest.mark.asyncio
async def test_live_progress_is_scoped_to_job_and_cleared_on_failure(tmp_path: Path) -> None:
    from textual.widgets import RichLog

    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record("model_request", {"job_id": "plan:1", "role": "research-lead", "stage": "plan"})
    app = AuditApp(tmp_path, "WATCH", (), 60)
    async with app.run_test(size=(120, 36)):
        await app.poll()
        assert "waiting for first text" in str(app.query_one("#progress", Static).render())
        ledger.record(
            "model_progress",
            {"job_id": "plan:1", "summary": "Defining source question", "characters": 90},
        )
        await app.poll()
        text = str(app.query_one("#progress", Static).render())
        assert "plan:1" in text
        assert "Defining source question" in text
        assert "90 characters" in text
        assert "provisional" in text
        assert not any(
            "model progress" in line.text for line in app.query_one("#feed", RichLog).lines
        )
        ledger.record("run_failed", {"error_type": "TimeoutError"})
        await app.poll()
        assert not app.active
        assert "No active model requests" in str(app.query_one("#progress", Static).render())
    ledger.close()
