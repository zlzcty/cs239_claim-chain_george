# Agent protocol and scheduling

## Transport boundary

Target: A2A 1.0.0, JSON-RPC 2.0 binding. Pin the implementation's SDK/schema to that version rather than relying on a changing `latest` specification. This document defines the application contract; JSON examples below are domain payloads, not complete A2A envelopes. Validate the transport adapter against the pinned A2A schema before claiming conformance.

The Research Lead is the client. Investigator workers and the Review Agent expose endpoints with Agent Cards at `/.well-known/agent-card.json`. Cards declare JSON input/output and these skills:

- Investigator: `resolve-citation`, `compare-editions`, `search-claim-evidence`, `check-historical-record`.
- Reviewer: `review-claim-report`.

Use `SendMessage`, `GetTask`, and `CancelTask`; streaming is optional. Domain payloads use `urn:claim-chain-auditor:extension:v1`, declared by the cards and carried according to the pinned transport schema. Unsupported domain versions/actions fail validation. Keep domain fields inside the data payload, not invented A2A envelope fields.

## Identity and authority

One run has a stable `runId` and one A2A `contextId`. The first task can establish the context; persist it before dispatching later tasks. Each scheduled job has a client-generated `jobId`; each execution attempt has an `attemptId` and a server-issued A2A `taskId`. Store the mapping. New tasks share the context and use `referenceTaskIds` for related tasks, but scheduler dependencies are explicit domain fields. A shared context is not shared model memory or an access-control mechanism.

Only the Lead selects and creates agent jobs. Investigators and the reviewer propose work. A scheduler implemented in application code enforces the queue, allocations, and worker ownership. It does not make research decisions. The application binds endpoints to configured worker/reviewer identities; a payload claiming to be a reviewer cannot grant approval. The MVP assumes trusted configured services, not arbitrary third-party agents.

Messages have unique A2A message IDs. Evidence references contain record IDs and revisions from [evidence.md](evidence.md); tools resolve them from shared storage. Pass full documents through artifact storage, not task histories.

## Domain actions

| Action | Sender | Required parameters |
|---|---|---|
| `resolve_citation` | Lead | Originating passage/link reference, bounded question, acceptance criteria |
| `compare_editions` | Lead | Two edition references, target passage/query, comparison question |
| `search_claim_evidence` | Lead | Question, query variants, scope, goal (`earlier_source`, `independent_support`, or `counterevidence`) |
| `check_historical_record` | Lead | Assertion, entity candidates, time/place/collection scope |
| `review_claim_report` | Lead | Report ID/revision/body hash, snapshot ID/hash, reviewed job references |
| `provide_decision` | Lead | Waiting task's `requestId`, selected decision and rationale |
| `provide_evidence` | Lead | Waiting task's `requestId`, new evidence references |

Each initial action also includes `schemaVersion`, `runId`, `jobId`, `attemptId`, `claimRef`, `inputRefs`, `question`, `acceptanceCriteria`, `dependsOn`, `allocationId`, `limits`, and `idempotencyKey`. Research actions include `depth` and `maxAdditionalLinks` (default zero, at most one). Edition comparison must identify two candidate editions; finding an unknown edition is a `resolve_citation` question instead.

Example initial domain payload:

```json
{
  "schemaVersion": 1,
  "action": "resolve_citation",
  "runId": "run-001",
  "jobId": "job-101",
  "attemptId": "attempt-101-1",
  "idempotencyKey": "run-001/job-101/attempt-1",
  "claimRef": {"id": "claim-001", "revision": 1},
  "inputRefs": [{"id": "passage-100", "revision": 1}],
  "originatingPassageRef": {"id": "passage-100", "revision": 1},
  "question": "Which work and edition does this footnote cite, and does its passage support the assertion?",
  "acceptanceCriteria": ["Record the target identity and located passage, or a documented unresolved link."],
  "dependsOn": [],
  "depth": 0,
  "maxAdditionalLinks": 0,
  "allocationId": "allocation-101",
  "limits": {"maxNewSources": 2, "deadline": "2026-10-28T15:00:00Z", "maxSpend": 0}
}
```

On success the adapter stores the returned A2A task/context IDs. Poll persisted task IDs; do not resend an initial instruction merely because a response is slow. A request may return a message instead of a task: validate and accept a complete synchronous domain result, or report an adapter error if it lacks a usable result. Never assume every successful response created a task.

## Dependency queue

Store jobs with `jobId`, action/input versions, research question, acceptance criteria, `dependsOn`, priority, semantic deduplication key, depth, state, allocation, attempts, owner, lease expiry, checkpoint, and result reference.

Queue states are `queued`, `ready`, `running`, `waiting_input`, `completed`, `failed`, `canceled`, and `dependency_blocked`. They are application states, separate from A2A task states.

1. The Lead admits a proposed job after scope, duplicate, dependency-cycle, and budget checks. A proposal is not itself an agent task.
2. A job becomes ready when every dependency has completed and its stated prerequisite evidence exists. Completion with an unavailable source does not satisfy a prerequisite requiring an inspected passage.
3. Atomically claim the highest-priority ready job and reserve its allocation. Run at most two Investigator attempts at once by default. Reviewer work has a separate worker slot but consumes the same run budget.
4. A worker renews its lease and checkpoints evidence, searches, open questions, and usage. It reads the checkpoint and evidence on resume, not an unbounded conversation transcript.
5. On completion, store a validated result and reconcile usage. Evaluate proposals and release newly ready jobs. Existing unrelated ready work continues while another task waits for input.
6. Failed/canceled dependencies mark dependents `dependency_blocked`. The Lead can replace a dependency or drop the question with a recorded reason; no silent success. Unknown dependency IDs and cycles are rejected at admission.

Priority favors questions decisive to the claim and work that could disprove the current interpretation. It is not restricted to sources supporting it. Citation cycles are evidence findings; queue cycles are scheduling errors.

## Deduplication and identity merges

Use a semantic key based on claim interpretation, action, normalized target identity, input revisions, question, and relevant scope. Check it atomically when admitting jobs. Share an existing job/result only if its acceptance criteria and coverage suffice. Different questions about the same book can remain separate jobs while sharing artifacts and extraction.

Cache bytes by hash and extraction by hash/method version. Normalize catalog IDs and URLs as identity hints; URLs and matching titles alone do not prove edition identity. The Lead resolves ambiguous merges with recorded rationale. Evidence writes use expected revisions and idempotency keys. On conflict, reread and reconcile; do not overwrite another worker's findings.

## Budgets and stopping

The run record stores maximum distinct sources, deadline, optional spending cap, depth limit, and review reserve. A source is an edition/version admitted for inspection; provisional unknown-edition targets have stable source keys. Retries, pages, and multiple copies of the same edition do not add source slots. Reserve a provisional slot before retrieving an unknown target; reconcile confirmed duplicates without erasing usage history. Search snippets/catalog metadata are discovery, not inspected source evidence. Tools still enforce request, time, and byte limits for discovery calls.

Allocate from the shared remaining budget atomically; task limits cannot exceed their allocation or the run remainder. Charge actual external usage once by operation ID, including failures and retries. Canceled calls keep their incurred charges; uncertain charges stay reserved until reconciled. Review has a reserved allocation; spending it on more research requires the Lead to record that a fully reviewed result may no longer be possible. Only the user can increase run limits.

When a task answers its bounded question, it returns even if the overall claim remains unresolved. It proposes branches rather than following them without permission. An unambiguous extra link is allowed only when `maxAdditionalLinks` permits it and depth/allocation allow it. At limits, preserve partial evidence and record what stopped the task. On run deadline, stop dispatch, cancel active work, and preserve any partial report as unapproved unless its exact version was already approved.

## Lifecycle, requests, and results

A2A submitted/working states map to active jobs; input-required maps to `waiting_input`. Auth-required pauses only that task for an authorized access decision. The MVP never sends credentials in domain payloads. Missing access can instead end with a source request and an unresolved link. Task completion describes execution, not claim truth.

An agent requests a decision only if it cannot finish its current bounded question. Otherwise it completes with proposals so it does not hold a worker while waiting for unrelated research. A decision request contains `requestId`, question, options, evidence references, and the exact missing prerequisite. The Lead responds on the same nonterminal A2A task/context with the request ID. A response adding work schedules a separate job; it does not silently expand the current allocation. Pending questions have an expiry bounded by the run deadline.

Every completed research result contains:

- `schemaVersion`, `runId`, `jobId`, `attemptId`, and `outcome` (`answered`, `unresolved`, or `limit_reached`).
- Evidence and citation-link references, findings, search coverage, source requests, unresolved questions, and a checkpoint reference if work remains.
- `proposedTasks` and final usage. Empty collections are explicit.

Each proposal has a `proposalId`, action, question, acceptance criteria, input references, prerequisite jobs/evidence, depth, estimated new sources/time/spend, and rationale. Proposed dependency references may use proposal IDs from the same result; the Lead maps accepted proposals to job IDs and records deferred/rejected proposals. No agent-selected budget is authoritative.

Results are structured artifacts. The scheduler accepts completion only after validating references and persisting the result; transport completion without a valid result is an execution failure. An unavailable source is an `unresolved` research result, not a tool-failure task. Reaching a limit is a partial research result, not support for or against the claim.

## Review and publication

The Lead persists a draft report and immutable evidence snapshot before requesting review. Review inputs name their exact versions/hashes and related task IDs. The reviewer can read originals, inspect page images, and run bounded alternate searches within its allocation. Additional Investigator work is proposed to the Lead.

The review artifact records the report reference/body hash, snapshot ID/hash, reviewer identity, checks performed, `approved`, issues, and required changes. Approval is allowed for an honestly limited or unresolved report. Report revision requests use `approved: false`; A2A task rejection is reserved for refusing an invalid or prohibited assignment.

If approval needs new evidence, the reviewer completes with `approved: false` and proposals. The Lead schedules the checks, revises the snapshot/report, and creates a new review job. A clarification not changing the reviewed inputs can use input-required on the existing task. Any change to report bytes or snapshot invalidates approval for the new version. Record a finite review-round limit in run configuration (default two); unresolved corrections at that limit produce an unapproved partial report.

Before marking a report approved, application code verifies reviewer identity, exact report version/hash, snapshot hash, and approval flag. It returns those same report bytes locally. External publication additionally requires authorization under policy P2. Reviewer approval is a report-quality gate, not permission to take external actions.

## Failure, retry, and cancellation

- Invalid domain fields fail before execution with a structured code and field details. Transport errors follow the pinned A2A binding. Research limitations belong in results, not JSON-RPC errors.
- Persist an initial request's idempotency key before dispatch. The endpoint deduplicates repeat submissions to the same attempt and returns its task/result. Reusing a key with a different payload fails. Ledger/tool writes have operation keys too; do not assume exactly-once network delivery.
- Retry transient tool failures within the existing allocation, at most two retries with bounded backoff. Permanent access errors become research limitations. A new execution attempt receives a new `attemptId`/key and references the previous task and checkpoint.
- On lease expiry, reconcile the old attempt through `GetTask` before reassignment. If it may still run, cancel it or fence its writes before starting another. All mutable writes require the current lease token; stale workers cannot commit authoritative results. Late artifacts may be retained as unaccepted provenance.
- Cancellation stops dispatch and requests `CancelTask` for active attempts. Until cancellation is confirmed or writes are fenced, keep ownership and allocation reserved. Preserve incurred costs and partial evidence. Canceling a prerequisite blocks its dependents.
- Terminal A2A tasks are not resumed with new instructions. Reopening a completed or blocked research question creates a new job/task referencing the old result. A scheduler restart restores persisted queues, allocations, and task mappings before dispatching work.

## Worked flow

1. The Lead stores seeds, establishes the run context, and schedules two independent citation questions.
2. Investigator A resolves its link and proposes an edition comparison; Investigator B finds that its source is unavailable and creates a local source request.
3. The Lead admits the comparison after its edition prerequisites exist. A second proposal matching A's completed question reuses its result.
4. Within the remaining budget, the Lead schedules a counterevidence search. It records deferred questions rather than spawning unrestricted descendants.
5. The Lead snapshots evidence and submits a draft. The reviewer identifies a wrong-edition quotation, completes with `approved: false`, and proposes a check.
6. The Lead schedules that check, revises the report/snapshot, and requests a new review. Only the exact approved version is returned as approved.
