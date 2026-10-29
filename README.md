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
python -m claim_chain --base-url "$OPENAI_BASE_URL" \
  --api-key-env API_KEY --model "$OPENAI_MODEL" \
  --claim 'For my local history course, I am checking the claim that Northbridge’s north bridge opened in 1920. I found it in the Northbridge anniversary leaflet (1924 print), page 2: “The north bridge opened in 1920, as recorded in the Town Register.” Trace that citation backward and identify the earliest source in the supplied material that states when the bridge opened. Keep construction completion distinct from opening to traffic. Check whether later sources rely on one another or provide independent evidence. Report what the sources support, conflicts, and what remains unknown; do not treat the earliest source as proof that the event happened.'
```

Set `OPENAI_BASE_URL` and `OPENAI_MODEL`, or pass `--base-url` and `--model`, to choose any compatible endpoint and model. `--api-key-env` names the environment variable holding that service's key; this example uses `API_KEY`. The default endpoint is `https://api.openai.com/v1`.

Each run writes `report.md`, `review.json`, and `ledger.sqlite` under a new `runs/` directory. Verify a report with:

```sh
python -m claim_chain --verify runs/<run-id>
```

## Evidence input

`--claim` is free-form: include the course context, what the claim means, relevant distinctions, investigation scope, and the question you want answered. The agents can trace only sources already in the corpus; they do not search the web or fetch documents. Use `--corpus path/to/corpus.json` to provide those sources. The JSON fields are `claim`, `seeds` (source IDs to start from), `sources` (records with `id`, `title`, `edition`, `year`, and `passages`), and optional `unavailable` IDs. Each passage has an `id`, `locator`, `text`, and optional `cites` containing source IDs. `--claim` replaces the corpus claim while keeping its sources.

The bundled corpus is fictional and demonstrates conflicting editions and citation chains. Runs are bounded by `--max-calls`, `--max-sources`, `--timeout`, and `--deadline`; defaults are 24 calls, eight sources, 60 seconds per request, and 240 seconds total. `--max-calls` must be at least 14: ten calls are reserved for preliminary review and up to two draft/review rounds, including one correction per response. Research admits work only when planning and at least one source check fit with their correction attempts.

## Development

```sh
python -m pytest
mypy src tests
```
