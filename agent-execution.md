# Agent execution contract

This document separates the implemented bounded MVP from the larger target design.

## Implemented bounded MVP

The runtime uses the OpenAI Python SDK with configurable OpenAI-compatible chat completions, Jinja2 role templates, and Pydantic response models. Every request is a fresh role context with a JSON payload and schema; no messages are shared between agents. Invalid JSON gets at most one correction request. The run counts attempted calls and records model outputs and reported token usage without credentials. Every model event carries a runner-assigned job ID, including validation failures and correction calls. Investigation job records link that ID to the source and question.

The Research Lead receives a local source catalog and run results, then returns a bounded plan. Two Investigators run local source checks concurrently and return assessments with quotations; the runner validates quotes and dispatches at most three plan waves. Dependent Investigators receive only their named prerequisites’ original passages and accepted findings. An Investigator provider or validation failure is recorded against its job; independent jobs continue, while dependent jobs remain blocked. Whole-run cancellation still stops active workers.

The reviewer gets the evidence snapshot first and the report in a later fresh context. In excerpt mode there are no model-accessible tools. In document mode, Investigators and the Reviewer's preliminary assessment call `list_sources`, `search_source` and `read_source` through a native tool loop (at most 8 rounds per request, each round counted against the call limit); the Lead and final review have none. The runner alone loads the local corpus, stores events in SQLite, enforces dependencies and limits, writes artifacts, and verifies report/snapshot hashes.

## Target design

The sections below describe the larger intended agent loop. The browser, retrieval, OCR, arbitrary tool execution, remote workers, leases, and full protocol contracts described there are not part of the current MVP.

Role system prompts and tool lists are in [agents/research-lead.md](agents/research-lead.md), [agents/investigator.md](agents/investigator.md), and [agents/reviewer.md](agents/reviewer.md). Supply each prompt with policy.md, evidence.md, protocol.md, this execution contract, and the permitted tool definitions. The role lists are ceilings; task allowlists may narrow them.

## Role permissions

| Role | Inputs | Permitted operations |
|---|---|---|
| Research Lead | Original claim, scope, run limits, job results and proposals | Read/search evidence and task state; select/enqueue jobs through scheduler; create snapshots and draft reports. Research tools may be used only through scheduled Investigator or reviewer work. |
| Investigator | Claim interpretation, task question, criteria, input references, scope and allocation | Research and evidence read/write tools from [tools.md](tools.md), within the assigned task. Return results and propose follow-ups. Cannot create jobs or alter run limits. |
| Review Agent | Claim, scope, snapshot and decisive evidence references; draft only after preliminary assessment | Evidence read/search and passage/image tools; bounded research tools during research time; write a preliminary assessment and review artifact; propose follow-ups. Cannot approve its own report or create jobs. |

The application assigns identity and tool permissions independently of model output. The Lead is the only role that can revise the report; reviewer approval is checked by the application against its version and snapshot. Configured skills may implement these tools, subject to [policy.md](policy.md).

## Task loop

1. Validate the action payload and allocate resources. Initialize context with role instructions and their version, original claim and tested interpretation, task question and criteria, limits, input references, and relevant excerpts with locations. Add the checkpoint on retry. Do not include unrelated task histories or full documents by default.
2. Call the configured model through the provider adapter. The runner validates each requested tool and its arguments against the task's allowlist and remaining allocation. It executes authorized calls, records their results and usage, and returns bounded outputs with references to the model.
3. Continue until the agent returns a structured result, requests required input, reaches its step or budget limit, or encounters an unrecoverable error. Default limits per attempt are 12 model calls and 30 tool calls, both subordinate to the run allocation and deadline. A model call that requests several tools still counts once; each tool invocation counts separately.
4. Validate results, referenced records, and role authority. Persist evidence and a checkpoint after each successful tool operation. The checkpoint includes task/attempt IDs, role and prompt/skill versions, referenced evidence revisions, completed operations, open questions, and usage. It does not treat the agent's summary as source evidence.
5. Return the validated result or an explicit partial/error outcome. A task failure does not imply a claim outcome. A retry starts from the checkpoint with a new attempt ID and the remaining allocation.

The runner validates each action's required fields from [protocol.md](protocol.md). Research results require `schemaVersion`, `runId`, `jobId`, `attemptId`, `outcome`, evidence and link references, findings, searches, source requests, unresolved questions, proposed tasks, and usage; absent collections are empty arrays. Review results require the reviewed report and snapshot versions/hashes, reviewer identity, preliminary assessment, checks, `approved`, issues, and required changes. Requests for input include `requestId`, question, options, evidence references, and missing prerequisite. Before implementation, express these contracts as versioned machine-validated schemas and make those schemas the source of truth for enums and field names.

If a model response or tool request fails schema validation, return the validation errors to the model for one correction attempt within its existing budget. If the correction fails, record the invalid response and fail the attempt; do not fabricate a result. Unavailable evidence and reached limits are structured partial results, not malformed-response failures. Never retry indefinitely.

## Review sequence

The reviewer first sees the claim, scope, and an evidence-only snapshot view containing source identities, artifacts, passages, and citation links; it does not see finding, report, or review records or agent-written link rationales. It inspects originals with surrounding context and records an assessment of their relevance, provenance, and potential alternatives before seeing the draft or the Lead's conclusion. The Lead's selection of decisive evidence can still bias this step; the reviewer can inspect other source material in the snapshot. The reviewer then reads the exact draft, compares it with its assessment, and approves or requests specific corrections. Preserve both the preliminary assessment and final review. These steps reduce anchoring; they do not prove independent research or truth.

## Provider and usage records

The model adapter is separate from research tools. Record provider, exact model identifier, model settings, role/prompt/skill versions, schema version, call IDs, timestamps, outcomes, reported input/output tokens and costs, and tool-operation references. Count attempted calls against the run limit, including failed and correction calls. When cost or token use is unavailable, mark it unknown rather than zero. Avoid logging credentials. Store enough inputs and outputs to examine a failure, subject to the MVP's public/non-confidential input scope.
