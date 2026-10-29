# Claim Chain Auditor

## Current MVP

The application audits a claim against a supplied local corpus. It runs a Research Lead, up to two concurrent Investigators, and a Reviewer through configurable OpenAI-compatible chat completions. A reachable model endpoint and model ID are required, along with an API key when the provider requires one. The roles receive separate prompts and fresh contexts. The model cannot call tools: the runner loads sources, schedules jobs, validates quoted text, stores events, and creates reports.

The corpus contains source identities and located passages, with optional citation target IDs. The agents can inspect only those supplied passages. There is no web search, URL retrieval, PDF extraction, OCR, catalog lookup, record search, arbitrary code execution, or remote worker support. The included corpora are examples; the Great Wall source notes describe the curated excerpts and their limits.

## Run behavior

The Lead proposes at most four source checks per planning wave. The runner admits only known, unattempted source IDs, dispatches at most two at once, and allows up to three planning waves. A check handles one source; dependencies must refer to completed findings. Unavailable sources create local source-request ledger entries. Failed jobs do not block unrelated work. The runner records uninspected citation targets and local-corpus limitations.

Every model response is validated against a Pydantic schema. An invalid response gets at most one correction call. Calls, including corrections, count against the run limit. The runner reserves ten calls for preliminary review and up to two draft/review rounds, including one correction attempt per response; research capacity also reserves calls for planning and investigations. The default limits are 24 attempted calls, eight sources, 120 seconds per request, and 600 seconds for the run. The minimum call budget is 14. The runner permits at most two report versions; the Reviewer cannot request more research during final review.

The reviewer first assesses the evidence snapshot without Investigator findings or a draft, then receives the draft in a later fresh context. The runner verifies that decisive passage IDs and quotations refer to supplied, inspected text. Approval is stored against report and snapshot hashes. `python -m claim_chain --verify RUN_DIRECTORY` checks those exact bytes. Interrupted runs receive no approval and preserve partial artifacts.

## Report contents

The Markdown report records the claim, assessment, evidence passages, citation graph, earliest attestation found in the inspected corpus when established, and limitations. Earliest attestation is not a claim of origin or proof of truth. `review.json` records approval and hashes; `snapshot.json` records the evidence view; `ledger.sqlite` stores run events. The application also saves the input corpus.

See [README.md](README.md) for setup and command examples, [agent-execution.md](agent-execution.md) for implementation details, and the [bridge episode](episodes/bridge.md) and [Great Wall walkthrough](episodes/great-wall-hypothetical.md) for bounded examples.
