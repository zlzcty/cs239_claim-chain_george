"""Live and recorded views of the runner's actual ledger events."""

import argparse
import asyncio
import json
import signal
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import ClassVar, cast
from uuid import uuid4

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Markdown,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

Event = tuple[int, str, dict[str, object]]


def read_events(directory: Path, after: int) -> list[Event]:
    path = directory / "ledger.sqlite"
    if not path.is_file():
        return []
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT sequence, kind, body FROM events WHERE sequence > ? ORDER BY sequence",
            (after,),
        ).fetchall()
    return [
        (number, kind, cast(dict[str, object], json.loads(body))) for number, kind, body in rows
    ]


def event_summary(kind: str, body: dict[str, object]) -> str:
    if kind == "trajectory":
        return f"{body.get('role')}: {body.get('text')}"
    if kind == "plan":
        return f"Lead plan: {body.get('rationale')}"
    if kind == "tool_call":
        return f"{body.get('job_id')}: {body.get('name')} {body.get('arguments')}"
    if kind == "tool_result":
        return f"{body.get("job_id")}: {body.get("name")} returned document data"
    if kind == "review":
        return "Reviewer: " + ("APPROVED" if body.get("approved") else "CHANGES REQUESTED")
    return f"{kind.replace('_', ' ')} · {body.get('job_id', body.get('id', ''))}"


def source_markdown(source: dict[str, object]) -> str:
    lines = [f"### {source.get('title')} ({source.get('year') or 'year unknown'})", str(source.get("edition", ""))]
    passages = source.get("passages", [])
    if isinstance(passages, list):
        for passage in passages:
            if isinstance(passage, dict):
                lines.extend(
                    [
                        f"\n**{passage.get('id')}** · {passage.get('locator')}",
                        f"\n> {passage.get('text')}",
                        f"\nCites: {', '.join(str(item) for item in passage.get('cites', [])) or 'none recorded'}",
                    ]
                )
    return "\n\n".join(lines)


class AuditApp(App[None]):
    TITLE = "CLAIM CHAIN"
    SUB_TITLE = "Delegation · evidence · independent review"
    CSS = """
    Screen { background: #0b1120; }
    Header { background: #16243c; }
    #banner { height: 3; padding: 1 2; background: #183448; color: #74e0d4; }
    #claim-pane { height: 5; }
    #claim { height: auto; padding: 0 2; color: #e4edf8; }
    #roles { height: 5; margin: 0 1; }
    .role { width: 1fr; margin: 0 1; padding: 0 1; border: round #35546e; }
    #progress { height: auto; max-height: 4; padding: 0 2; color: #74e0d4; }
    TabbedContent { height: 1fr; margin: 0 2; }
    #jobs { height: 6; }
    #detail-pane { height: 5; background: #152238; }
    #detail { height: auto; padding: 1; }
    #feed { height: 1fr; }
    Markdown { padding: 1 2; }
    Footer { background: #16243c; }
    """
    BINDINGS: ClassVar = [("q", "quit", "Quit"), ("space", "pause", "Pause replay")]

    def __init__(self, directory: Path, mode: str, command: Sequence[str], pace: float) -> None:
        super().__init__()
        self.directory = directory
        self.mode = mode
        self.command = tuple(command)
        self.pace = pace
        self.sequence = 0
        self.paused = False
        self.jobs: dict[str, dict[str, object]] = {}
        self.active: dict[str, str] = {}
        self.completed: dict[str, int] = {}
        self.role_models: dict[str, str] = {}
        self.progress: dict[str, str] = {}
        self.started: dict[str, float] = {}
        self.sources: dict[str, str] = {}
        self.calls = 0
        self.max_calls = "?"
        self.process: asyncio.subprocess.Process | None = None
        self.report_seen = False
        self.ended = False
        self.verdict = "Awaiting review"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="banner", markup=False)
        with VerticalScroll(id="claim-pane"):
            yield Static("Waiting for the claim…", id="claim", markup=False)
        with Horizontal(id="roles"):
            for name, title in (
                ("research-lead", "RESEARCH LEAD"),
                ("investigator", "INVESTIGATORS"),
                ("reviewer", "REVIEWER"),
            ):
                yield Static(f"{title}\nWaiting", id=name, classes="role", markup=False)
        yield Static("No active model requests", id="progress", markup=False)
        with TabbedContent():
            with TabPane("Delegation", id="activity"), Vertical():
                yield DataTable(id="jobs", cursor_type="row")
                with VerticalScroll(id="detail-pane"):
                    yield Static(
                        "Select a job to inspect its question and evidence boundary.",
                        id="detail",
                        markup=False,
                    )
                yield RichLog(id="feed", wrap=True, markup=False, highlight=False)
            with TabPane("Document tools", id="tools-tab"):
                yield RichLog(id="tools", wrap=True, markup=False, highlight=False)
            with TabPane("Source passages", id="evidence-tab"), VerticalScroll():
                yield Markdown("Inspected source passages will appear here.", id="evidence")
            with TabPane("Report", id="report-tab"), VerticalScroll():
                yield Markdown(
                    "The report appears after drafting (at the end of a replay). Approval is a separate reviewer decision.",
                    id="report",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#jobs", DataTable).add_columns("Source / job", "Status", "Prerequisites")
        self.update_banner()
        if self.command:
            self.run_worker(self.launch(), exclusive=True)
        self.set_interval(self.pace if self.mode == "REPLAY" else 0.2, self.poll)

    async def launch(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            *self.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        output, _ = await self.process.communicate()
        self.ended = True
        if self.process.returncode:
            self.query_one("#feed", RichLog).write(output.decode(errors="replace")[-3000:])
        self.update_banner()

    async def on_unmount(self) -> None:
        if self.process is not None and self.process.returncode is None:
            self.process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()

    def action_pause(self) -> None:
        if self.mode == "REPLAY":
            self.paused = not self.paused
            self.update_banner()

    async def poll(self) -> None:
        if self.paused:
            return
        try:
            events = read_events(self.directory, self.sequence)
        except sqlite3.OperationalError:
            return
        if self.mode == "REPLAY":
            events = events[:1]
        for number, kind, body in events:
            self.sequence = number
            self.apply_event(kind, body)
        if self.mode == "REPLAY" and not events:
            self.ended = True
        if self.report_seen and (self.mode != "REPLAY" or self.ended):
            report = self.directory / "report.md"
            if report.is_file():
                await self.query_one("#report", Markdown).update(
                    report.read_text(encoding="utf-8")
                )
                self.report_seen = False
        self.update_banner()

    def apply_event(self, kind: str, body: dict[str, object]) -> None:
        job_id = str(body.get("job_id", ""))
        if kind == "run_started":
            self.query_one("#claim", Static).update(str(body.get("claim", "")))
            self.max_calls = str(body.get("max_calls", "?"))
            overrides = body.get("role_models", {})
            if isinstance(overrides, dict):
                self.role_models = {
                    role: str(overrides.get(role, body.get("model", "Model unspecified")))
                    for role in ("research-lead", "investigator", "reviewer")
                }
        elif kind == "model_request":
            self.calls += 1
            self.active[job_id] = str(body.get("role"))
            self.started[job_id] = monotonic()
            stage = {
                "plan": "Planning source checks",
                "inspect": "Examining source evidence",
                "preliminary": "Assessing evidence before draft",
                "draft": "Drafting report",
                "review": "Reviewing report",
            }.get(str(body.get("stage")), "Requesting model response")
            self.progress[job_id] = f"{stage} · waiting for first text"
        elif kind == "model_progress":
            self.progress[job_id] = (
                f"{body.get('summary', 'Receiving response')} · "
                f"{body.get('characters', 0)} characters received · provisional"
            )
        elif kind in {"model_response", "model_error"}:
            role = self.active.pop(job_id, str(body.get("role", "")))
            self.completed[role] = self.completed.get(role, 0) + 1
            self.progress.pop(job_id, None)
            self.started.pop(job_id, None)
        elif kind.startswith("job_"):
            previous = self.jobs.get(job_id, {})
            self.jobs[job_id] = {**previous, **body, "status": kind.removeprefix("job_")}
            self.update_jobs()
        elif kind == "source_request":
            self.jobs[job_id] = {**self.jobs.get(job_id, {}), **body, "status": "unavailable"}
            self.update_jobs()
        elif kind in {"tool_call", "tool_result"}:
            text = event_summary(kind, body)
            if kind == "tool_result":
                text += "\n" + str(body.get("result", ""))
            self.query_one("#tools", RichLog).write(text)
        elif kind == "source_inspected":
            self.sources[str(body.get("id"))] = source_markdown(body)
            self.run_worker(
                self.query_one("#evidence", Markdown).update("\n\n---\n\n".join(self.sources.values()))
            )
        elif kind == "report":
            self.report_seen = True
        elif kind == "review":
            self.verdict = (
                "Reviewer approved" if body.get("approved") else "Reviewer requested changes"
            )
        elif kind == "run_failed":
            self.verdict = "Run failed"
            self.active.clear()
            self.progress.clear()
            self.started.clear()
            self.ended = True
        if kind not in {"model_response", "model_progress", "source_inspected", "snapshot"}:
            self.query_one("#feed", RichLog).write(
                f"{self.sequence:03}  {event_summary(kind, body)}"
            )
        self.update_roles()

    def update_jobs(self) -> None:
        table = self.query_one("#jobs", DataTable)
        table.clear()
        for job_id, body in self.jobs.items():
            dependencies = body.get("depends_on", [])
            table.add_row(
                str(body.get("source_id", job_id)),
                str(body.get("status")),
                ", ".join(str(item) for item in dependencies)
                if isinstance(dependencies, list)
                else "",
                key=job_id,
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        body = self.jobs.get(str(event.row_key.value), {})
        dependencies = body.get("depends_on") or "none"
        lines = [
            f"{body.get('job_id', '')}: {body.get('question', '')}",
            f"Context: assigned source + catalog + named prerequisites: {dependencies}",
            f"Status: {body.get('status', '')}",
        ]
        result = body.get("result")
        if isinstance(result, dict):
            lines.extend([str(result.get("assessment", "")), str(result.get("reasoning", ""))])
            for quote in result.get("quotes", []):
                if isinstance(quote, dict):
                    lines.append(f"{quote.get('passage_id')}: {quote.get('text')}")
        if body.get("error_type"):
            lines.append(str(body["error_type"]))
        self.query_one("#detail", Static).update("\n".join(lines))

    def update_roles(self) -> None:
        for role, title in (
            ("research-lead", "RESEARCH LEAD"),
            ("investigator", "INVESTIGATORS"),
            ("reviewer", "REVIEWER"),
        ):
            active = [job for job, assigned in self.active.items() if assigned == role]
            text = (
                f"{len(active)} active: "
                + ", ".join(job.removeprefix("inspect:") for job in active)
                if active
                else "Idle"
            )
            self.query_one(f"#{role}", Static).update(
                f"{title}\n{self.role_models.get(role, 'Model unspecified')}\n{text}"
            )

    def update_progress(self) -> None:
        lines = []
        for job_id in self.active:
            elapsed = (
                "recorded progress"
                if self.mode in {"WATCH", "REPLAY"}
                else f"{monotonic() - self.started[job_id]:.0f}s elapsed"
            )
            lines.append(f"{job_id}: {self.progress.get(job_id, 'Waiting')} · {elapsed}")
        self.query_one("#progress", Static).update("\n".join(lines) or "No active model requests")

    def update_banner(self) -> None:
        self.update_progress()
        state = (
            "PAUSED"
            if self.paused
            else "END OF RECORDING"
            if self.ended and self.mode == "REPLAY"
            else "FINISHED"
            if self.ended
            else "WATCHING"
            if self.mode == "WATCH"
            else "RUNNING"
        )
        self.query_one("#banner", Static).update(
            f"{self.mode} · {state}  |  Calls {self.calls}/{self.max_calls}  |  "
            f"{len(self.sources)} sources  |  {self.verdict}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View live claim delegation or replay a recorded run."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, metavar="RUN_DIRECTORY")
    mode.add_argument("--watch", type=Path, metavar="RUN_DIRECTORY")
    parser.add_argument("--pace", type=float, default=0.25, help="Seconds per recorded event")
    args, remaining = parser.parse_known_args()
    if args.pace <= 0:
        parser.error("--pace must be positive.")
    if args.replay or args.watch:
        directory = args.replay or args.watch
        if not (directory / "ledger.sqlite").is_file():
            parser.error("The selected run must contain ledger.sqlite.")
        if remaining:
            parser.error("Runner arguments are only accepted when launching a live run.")
        app = AuditApp(directory, "REPLAY" if args.replay else "WATCH", (), args.pace)
    else:
        from .cli import parser as runner_parser

        runner_args = runner_parser().parse_args(remaining)
        directory = runner_args.output or Path("runs") / (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        )
        command = [sys.executable, "-m", "claim_chain", *remaining]
        if runner_args.output is None:
            command.extend(["--output", str(directory)])
        app = AuditApp(directory, "LIVE", command, args.pace)
    app.run()


if __name__ == "__main__":
    main()
