# Agent execution contract

What the runner does when it calls an agent. Larger designs (checkpointed task loop, retries with attempt IDs, remote workers) are in [future-todo.md](future-todo.md). Run order and budgets are in [protocol.md](protocol.md).

## Calls

The runtime uses the OpenAI Python SDK with a configurable OpenAI-compatible endpoint, Jinja2 role templates and Pydantic response models. Every request is a fresh context containing a role system prompt, the JSON schema and a JSON task payload. No messages are shared between agents. Roles can use different models (`--lead-model`, `--investigator-model`, `--reviewer-model`).

Each response is validated against its model. An invalid response gets at most one correction request. The run counts every attempted call, including corrections and tool rounds, against `--max-calls`. Every model event carries a runner-assigned job ID, including validation failures and corrections, and investigation records link that ID to the source and question. Events and reported token usage are stored without credentials.

Prompts are in [agents/research-lead.md](agents/research-lead.md), [agents/investigator.md](agents/investigator.md) and [agents/reviewer.md](agents/reviewer.md); each file holds the exact template the application renders.

## Roles

| Role | Inputs | Tools | Output |
|---|---|---|---|
| Research Lead | Claim, source catalog, prior results, limits; later the evidence snapshot | None | `Plan`, then `Draft` |
| Investigator | Claim, one assigned source, its question, prerequisites' original passages and accepted findings, catalog | Document mode: `list_sources`, `search_source`, `read_source` (assigned source only). Excerpt mode: none | `Investigation` |
| Reviewer | Claim and evidence-only snapshot; later the exact draft | Document mode, preliminary assessment only: the same three tools, all sources. Final review: none | `Preliminary`, then `Review` |

The runner, not the model, loads the corpus or documents, schedules jobs, enforces dependencies and limits, checks quotes, stores events, writes artifacts, and verifies report and snapshot hashes. Only the Lead role drafts, and only the Reviewer role can approve; the application checks approval against the report and snapshot hashes.

## Tool loop

In document mode a request with tools loops: the model returns tool calls, the runner executes them through the MCP server, appends the results to that request's own conversation, and calls again. A request allows at most 8 tool rounds, each counted against the call limit. The runner rejects tool calls for sources outside the agent's allowance. An invalid final answer is corrected with the tool transcript kept. Quotes and citations are accepted only for passages opened with `read_source`.

## Failures

An Investigator provider or validation failure is recorded against its job. Independent jobs continue and dependent jobs stay blocked. A failed correction fails the call; the runner does not fabricate a result. Cancelling the run stops active workers.

## Review

The Reviewer first sees the claim and an evidence-only snapshot with no findings, report or agent-written link rationales, and records an assessment and alternatives. It then reads the exact draft and approves or requests specific corrections. Both records are kept. The Lead's choice of decisive evidence can still bias the first step, so this reduces anchoring without proving independence or truth.
