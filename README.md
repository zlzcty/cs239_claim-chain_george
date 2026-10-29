# Claim Chain Auditor

Give the auditor a claim and its course or subject context. The Research Lead assigns source checks to two Investigators; a Reviewer checks the evidence and report. Each agent uses the configured OpenAI-compatible model.

## Run

Requires Python 3.14 and `uv` to manage dependencies and environments. On windows, set environment variables using `$env:KEY="value"`

```sh
uv sync --python 3.14 --dev
source .venv/bin/activate
export API_KEY=...
export OPENAI_BASE_URL=https://your-provider.example/v1
export OPENAI_MODEL=your-model
python -m claim_chain.tui --base-url "$OPENAI_BASE_URL" \
  --api-key-env API_KEY --model "$OPENAI_MODEL" \
  --claim 'For my local history course, I am checking the claim that Northbridge’s north bridge opened in 1920. I found it in the Northbridge anniversary leaflet (1924 print), page 2: “The north bridge opened in 1920, as recorded in the Town Register.” Trace that citation backward and identify the earliest source in the supplied material that states when the bridge opened. Keep construction completion distinct from opening to traffic. Check whether later sources rely on one another or provide independent evidence. Report what the sources support, conflicts, and what remains unknown; do not treat the earliest source as proof that the event happened.'
```

Set `OPENAI_BASE_URL` and `OPENAI_MODEL`, or pass `--base-url` and `--model`, to choose any compatible endpoint and model. `--api-key-env` names the environment variable holding that service's key; the default is `API_KEY`. The default endpoint is `https://api.openai.com/v1`.

Each run writes `report.md`, `review.json`, and `ledger.sqlite` under a new `runs/` directory. Verify a report with:

```sh
python -m claim_chain --verify runs/<run-id>
```

## Evidence input

`--claim` is free-form: include the course context, what the claim means, relevant distinctions, investigation scope, and the question you want answered. The agents can trace only sources already in the corpus; they do not search the web or download documents. Use `--corpus path/to/corpus.json` to provide those sources. The JSON fields are `claim`, `seeds` (source IDs to start from), `sources` (records with `id`, `title`, `edition`, `year`, and `passages`), and optional `unavailable` IDs. Each passage has an `id`, `locator`, `text`, and optional `cites` containing source IDs. `--claim` replaces the corpus claim while keeping its sources.

The bundled corpus is fictional and demonstrates conflicting editions and citation chains. Runs are bounded by `--max-calls`, `--max-sources`, `--timeout`, and `--deadline`; defaults are 64 calls, eight sources, 120 seconds per request, and 600 seconds total. Without `--documents`, `--max-calls` must be at least 14: ten calls are reserved for preliminary review and up to two draft/review rounds, including one correction per response. With `--documents`, ten more calls are reserved for review and each source check budgets ten calls. Research admits work only when planning and at least one source check fit with their correction attempts. Reasoning models spend most of a run's time on hidden thinking tokens; `--no-thinking ROLE` (repeatable) sends `thinking: disabled` for that role on providers that accept it. In one test it cut a run from about 9 to under 3 minutes, but the Reviewer without thinking approved less reliably, so try it on the Lead first.

## Full-document mode

`--documents DIR --claim '...'` makes the agents work from complete PDF, text, Markdown or HTML files instead of a prepared corpus. Investigators and the Reviewer get three tools, served by a local MCP subprocess: `list_sources`, `search_source` (SQLite FTS5 keywords, quoted phrases, `OR`, prefix `*`) and `read_source`. An optional `metadata.json` in the documents directory maps relative file paths to `{"edition": "...", "year": 1923}`; without it every year is 0 (unknown), so the agents cannot order sources by date. Reading is limited to the assigned document, and a passage can be quoted only after it has been opened. Tool requests and results appear in the TUI "Document tools" tab. This mode has been tested with mocked models and a real MCP subprocess, not yet with a live provider.

## Development

```sh
python -m pytest
mypy src tests
```

## Demo and terminal interface

Launch the Textual interface with the real-source Great Wall corpus:

```sh
python -m claim_chain.tui --corpus src/claim_chain/data/great-wall.json \
  --max-calls 28 --max-sources 5
```

It uses the same provider environment variables and run options as the CLI. The interface shows delegated jobs, active model calls, inspected passages, and the report. Select a job to see its question and prerequisite scope. Press `q` to quit; quitting a live run stops its process.

To inspect a saved run, use `python -m claim_chain.tui --watch runs/<run-id>`. To replay its recorded events for filming, use `python -m claim_chain.tui --replay runs/<run-id> --pace 0.25`; press Space to pause. Replay is labeled and makes no model calls.

See [the five-minute demo and recording script](demo.md) and [the Great Wall source notes](episodes/great-wall-sources.md). These excerpts are prepared inputs; the agents do not download sources or search the web.

## Check provider configuration

Run `python -m claim_chain.check_connection` in the same shell as the app. It prints provider environment settings with API keys masked, then sends one small chat request. It accepts `--model`, `--base-url`, `--api-key-env`, `--header`, and `--timeout`. It reads `API_KEY` by default:

```sh
python -m claim_chain.check_connection
```

Exit code 0 means a text completion succeeded; 1 means the request failed; 2 means configuration is missing or invalid. The script does not load `.env` files. The request may incur a small provider charge.

Model calls stream by default. The TUI shows a short progress description for each active job, based on the response field being generated, with received character counts. These labels describe provisional output, not hidden reasoning or verified findings. Before text arrives, it shows a waiting status and elapsed request time. Saved-run viewers show recorded progress without treating playback time as model latency. Use `--no-stream` if your provider does not support Chat Completions streaming with usage reporting. The connection checker uses a non-streaming request.

## Models by role

Use `--model` or `OPENAI_MODEL` as the fallback, then override individual roles:

```sh
python -m claim_chain.tui --model your-default-model \
  --lead-model your-planning-model \
  --investigator-model your-fast-model \
  --reviewer-model your-review-model \
  --corpus src/claim_chain/data/great-wall.json
```

The corresponding environment variables are `OPENAI_LEAD_MODEL`, `OPENAI_INVESTIGATOR_MODEL`, and `OPENAI_REVIEWER_MODEL`. Command-line overrides take priority. The Lead uses its model for planning and drafting; both Investigators use the Investigator model; the Reviewer uses its model for preliminary and final review. Corrections keep the same model. All roles share the configured endpoint and API key. The TUI shows the configured models, and model events record the selection for each call.
