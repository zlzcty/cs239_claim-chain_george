# Future work

Design material removed from [protocol.md](protocol.md) and [evidence.md](evidence.md) because the current application does not implement it. The full text is kept below unchanged apart from heading levels. The same files, untrimmed, are on branch `full-design-docs`. Nothing here describes current behavior; see [app.md](app.md) and [agent-execution.md](agent-execution.md) for that.

Not implemented: A2A transport and remote workers, leases, a persistent dependency queue with states and priorities, deduplication and identity merges, per-task allocations, spending caps, request/decision exchanges, the domain action set, versioned evidence records with revisions, locators for PDF images and OCR, evidence snapshots as record manifests, and transmission findings.

## Agent protocol and scheduling

### Execution and transport boundary

The first deployment runs in one process with a SQLite-backed queue and up to two concurrent Investigator tasks. Agents have distinct role instructions, contexts, and tool permissions. A local runner invokes the roles through a common interface. The scheduler is application code; it enforces the queue and budget and does not make research decisions. The Lead alone selects and creates agent jobs; workers propose follow-ups. See [agent-execution.md](agent-execution.md) for role inputs, tool permissions, and the model loop.

The local runner uses a stable `runId`, a client-generated `jobId` per job, and a distinct `attemptId` for each attempt. Store their mapping with checkpoints and results. Evidence references contain record IDs and revisions from [evidence.md](evidence.md). Pass full documents through artifact storage, not task histories. Bind review approval to the configured reviewer role in application code.

If the course requires A2A, implement a transport adapter against a pinned A2A 1.0.0 JSON-RPC schema and validate it with that SDK. The domain payloads below are not complete wire envelopes and do not establish conformance. A distributed adapter can use Agent Cards, `SendMessage`, `GetTask`, and `CancelTask`; it maps local run/job/attempt identities to transport context/task IDs. Keep the domain schema and scheduler independent of transport. Shared context is neither shared model memory nor access authorization. Use authenticated configured endpoints before trusting a remote reviewer's identity.

### Domain actions

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

For a remote adapter, persist returned transport identifiers and handle both asynchronous task responses and complete synchronous results. Do not assume every successful response created a task. Validate the adapter against the pinned schema.

### Dependency queue

Store jobs with `jobId`, action/input versions, research question, acceptance criteria, `dependsOn`, priority, deterministic duplicate key, depth, state, allocation, attempts, owner, checkpoint, and result reference. A distributed adapter also tracks leases.

Queue states are `queued`, `ready`, `running`, `waiting_input`, `completed`, `failed`, `canceled`, and `dependency_blocked`. They are application states, separate from A2A task states.

1. The Lead admits a proposed job after scope, duplicate, dependency-cycle, and budget checks. A proposal is not itself an agent task.
2. A job becomes ready when every dependency has completed and its stated prerequisite evidence exists. Completion with an unavailable source does not satisfy a prerequisite requiring an inspected passage.
3. Atomically claim the highest-priority ready job and reserve its allocation. Run at most two Investigator attempts at once by default. Reviewer work has a separate worker slot but consumes the same run budget.
4. A worker checkpoints evidence, searches, open questions, and usage. It reads the checkpoint and evidence on resume, not an unbounded conversation transcript.
5. On completion, store a validated result and reconcile usage. Evaluate proposals and release newly ready jobs. Existing unrelated ready work continues while another task waits for input.
6. Failed/canceled dependencies mark dependents `dependency_blocked`. The Lead can replace a dependency or drop the question with a recorded reason; no silent success. Unknown dependency IDs and cycles are rejected at admission.

Priority favors questions decisive to the claim and work that could disprove the current interpretation. It is not restricted to sources supporting it. Citation cycles are evidence findings; queue cycles are scheduling errors.

### Deduplication and identity merges

Check an atomic deterministic key composed of claim/interpretation revision, action, confirmed target identity, input revisions, and canonical structured scope and parameters. Equal keys identify duplicate candidates, not proof that free-text questions or acceptance criteria are equivalent. The Lead checks whether an existing result meets the requested question, criteria, and coverage before reusing it. For differently worded or uncertain matches, the Lead may assess equivalence and record the rationale; otherwise keep jobs separate. Different questions about the same book can share artifacts and extraction.

Cache bytes by hash and extraction by hash/method version. Normalize catalog IDs and URLs as identity hints; URLs and matching titles alone do not prove edition identity. The Lead resolves ambiguous merges with recorded rationale. Evidence writes use expected revisions and idempotency keys. On conflict, reread and reconcile; do not overwrite another worker's findings.

### Budgets and stopping

The run record stores maximum distinct sources, deadline, research cutoff, model-call limit, optional spending cap, depth limit, and review reserve. By default the cutoff is at 80% of the initial run duration and 20% of the initial model calls are reserved for drafting, review, and export. The user may configure these before a run. At cutoff, stop admitting research and cancel or checkpoint active research; begin drafting and review. New research requested by review is deferred unless the user changes the cutoff and limits; preserve an unapproved report if necessary. The reserve does not guarantee that review will finish. A source is an edition/version admitted for inspection; provisional unknown-edition targets have stable source keys. Retries, pages, and multiple copies of the same edition do not add source slots. Reserve a provisional slot before retrieving an unknown target; reconcile confirmed duplicates without erasing usage history. Search snippets/catalog metadata are discovery, not inspected source evidence. Tools still enforce request, time, and byte limits for discovery calls.

Allocate sources, model calls, time, and any spending cap from the shared remaining budget atomically; task limits cannot exceed their allocation or the run remainder. Count all model calls, including retries and review, and record provider-reported input/output tokens and billed cost when available. A finite call count bounds usage even when token reporting is unavailable. If a spending cap is set, use conservative pre-call cost estimates and stop calls whose cost cannot be bounded; reconcile actual charges afterward. Charge actual external usage once by operation ID, including failures and retries. Canceled calls keep their incurred charges; uncertain charges stay reserved until reconciled. Review has a reserved allocation; spending it on more research requires the Lead to record that a fully reviewed result may no longer be possible. Only the user can increase run limits.

When a task answers its bounded question, it returns even if the overall claim remains unresolved. It proposes branches rather than following them without permission. An unambiguous extra link is allowed only when `maxAdditionalLinks` permits it and depth/allocation allow it. At limits, preserve partial evidence and record what stopped the task. On run deadline, stop dispatch, cancel active work, and preserve any partial report as unapproved unless its exact version was already approved.

### Lifecycle, requests, and results

Local jobs use the queue states above. A remote adapter maps transport states to them; input-required maps to `waiting_input`. An access request pauses only that task for an authorized access decision. The MVP never sends credentials in domain payloads. Missing access can instead end with a source request and an unresolved link. Task completion describes execution, not claim truth.

An agent requests a decision only if it cannot finish its current bounded question. Otherwise it completes with proposals so it does not hold a worker while waiting for unrelated research. A decision request contains `requestId`, question, options, evidence references, and the exact missing prerequisite. The Lead responds to the same nonterminal local job with the request ID; a remote adapter maps that response to its transport task. A response adding work schedules a separate job; it does not silently expand the current allocation. Pending questions have an expiry bounded by the run deadline.

Every completed research result contains:

- `schemaVersion`, `runId`, `jobId`, `attemptId`, and `outcome` (`answered`, `unresolved`, or `limit_reached`).
- Evidence and citation-link references, findings, search coverage, source requests, unresolved questions, and a checkpoint reference if work remains.
- `proposedTasks` and final usage. Empty collections are explicit.

Each proposal has a `proposalId`, action, question, acceptance criteria, input references, prerequisite jobs/evidence, depth, estimated new sources/time/spend, and rationale. Proposed dependency references may use proposal IDs from the same result; the Lead maps accepted proposals to job IDs and records deferred/rejected proposals. No agent-selected budget is authoritative.

Results are structured artifacts. The scheduler accepts completion only after validating references and persisting the result; transport completion without a valid result is an execution failure. An unavailable source is an `unresolved` research result, not a tool-failure task. Reaching a limit is a partial research result, not support for or against the claim.

### Review and publication

The Lead persists a draft report and immutable evidence snapshot before requesting review. Review inputs name their exact versions/hashes and related task IDs. Before receiving the draft or the Lead’s assessment, the reviewer reads the original claim and a restricted view of the snapshot containing source identities, artifacts, passages, and citation links, then records a preliminary assessment and possible alternate explanations. Hide finding, report, and review records until the assessment is persisted; remove agent-written link rationales from this initial view. Source selection and extraction metadata may still reveal investigator assumptions, so this is not blind independent research. The reviewer then receives the draft and checks it against that assessment. It can inspect originals and page images, and proposes additional Investigator work to the Lead. Any research before cutoff uses its allocated budget; after cutoff follow the stopping rule above.

The review artifact records the report reference/body hash, snapshot ID/hash, reviewer identity, checks performed, `approved`, issues, and required changes. Approval is allowed for an honestly limited or unresolved report. Report revision requests use `approved: false`; task rejection is reserved for refusing an invalid or prohibited assignment.

If approval needs new evidence, the reviewer completes with `approved: false` and proposals. Before the research cutoff, the Lead may schedule checks, revise the snapshot/report, and create a new review job. After cutoff, new research follows the stopping rule above. A clarification not changing the reviewed inputs can use input-required on the existing task. Any change to report bytes or snapshot invalidates approval for the new version. Record a finite review-round limit in run configuration (default two); unresolved corrections at that limit produce an unapproved partial report.

Before marking a report approved, application code verifies reviewer identity, exact report version/hash, snapshot hash, and approval flag. It returns those same report bytes locally. External publication additionally requires authorization under policy P2. Reviewer approval is a report-quality gate, not permission to take external actions.

### Failure, retry, and cancellation

- Invalid domain fields fail before execution with a structured code and field details. Transport errors follow the pinned A2A binding. Research limitations belong in results, not JSON-RPC errors.
- Persist an initial request's idempotency key before dispatch. The runner deduplicates repeat submissions to the same attempt and returns its task/result; a remote endpoint must provide equivalent behavior. Reusing a key with a different payload fails. Ledger/tool writes have operation keys too; do not assume exactly-once network delivery.
- Retry transient tool failures within the existing allocation, at most two retries with bounded backoff. Permanent access errors become research limitations. A new execution attempt receives a new `attemptId`/key and references the previous task and checkpoint.
- For remote workers, reconcile an expired lease through the transport before reassignment. Cancel the old worker or fence its writes before starting another; reject stale lease tokens. Retain late artifacts only as unaccepted provenance. The single-process runner does not need distributed leases.
- Cancellation stops dispatch and cancels local active attempts. Remote adapters request transport cancellation; until confirmed or writes are fenced, retain ownership and allocation. Preserve incurred costs and partial evidence. Canceling a prerequisite blocks its dependents.
- Terminal jobs are not resumed with new instructions. Reopening a completed or blocked question creates a new job referencing the old result. On restart, restore the persisted queue, allocations, and checkpoints before dispatching work.

### Worked flow

1. The Lead stores seeds, establishes the run context, and schedules two independent citation questions.
2. Investigator A resolves its link and proposes an edition comparison; Investigator B finds that its source is unavailable and creates a local source request.
3. The Lead admits the comparison after its edition prerequisites exist. A second proposal matching A's completed question reuses its result.
4. Within the remaining budget, the Lead schedules a counterevidence search. It records deferred questions rather than spawning unrestricted descendants.
5. Before the research cutoff, the reviewer independently inspects decisive sources, identifies a wrong-edition quotation, and proposes a check.
6. If time and allocation allow, the Lead schedules that check, revises the report/snapshot, and requests a new review. After the cutoff, the check is deferred unless the user changes the limits; the result remains unapproved if the issue cannot be resolved. Only the exact approved version is returned as approved.

## Evidence records

This is the shared storage contract, not an A2A wire schema. Persist records in SQLite and bytes in an artifact directory. Validate required fields, enum values, and referenced revisions before committing writes. Timestamps use UTC; hashes use SHA-256.

### Common fields

Every record has `id`, `revision` (positive integer), `recordType`, `runId`, `createdAt`, `createdBy` (agent/tool identity), `taskId` (nullable for initial input), and `provenanceIds`. Unknown values are explicit nulls, not invented metadata. Cross-record references contain `{ "id": "...", "revision": 1 }`.

Writes append revisions. An update names the expected prior revision; concurrent updates return a conflict rather than overwriting. An idempotency key repeated with the same payload returns the original result; reuse with different content fails. Referenced records are retained for the run. Identity merges preserve aliases and the merge rationale; uncertain matches remain separate.

### Record types

| Type | Required content beyond common fields |
|---|---|
| `claim` | Original wording, tested interpretation, variants, scope, user clarification if any |
| `work` | Title or provisional reference text, creator candidates, external identifiers, identity confidence and rationale |
| `edition` | Work reference, publication/version metadata, language, identifiers, identity status (`confirmed`, `candidate`, `unknown`) |
| `artifact` | Byte hash, MIME type, size, storage key, source URL or upload ID, retrieval time/status, nullable edition reference, parent artifacts and transformation method/version |
| `passage` | Artifact reference, exact text, locator, context locator, nullable edition reference, representation (`original_text`, `ocr`, `correction`, `translation`), verification status and verifying actor |
| `citation_link` | Claim reference, originating passage reference, cited work reference, nullable edition and target passage references, edge type, resolution status, rationale, nullable search/request references |
| `finding` | Claim reference, observation or inference, supporting/conflicting evidence references, reasoning, uncertainty, optional transmission finding |
| `search` | Question, query/filters, provider or corpus, artifact/page coverage, method/version, time, results and limitations |
| `source_request` | Work reference, nullable edition reference, desired pages, reason, facts needed, acquisition status |
| `report` | Claim reference, body artifact, evidence snapshot ID/hash, evidence assessment, transmission findings, coverage, limitations |
| `review` | Report ID/revision/body hash, evidence snapshot ID/hash, reviewer identity, approval flag, checks performed, issues and required changes |

Artifacts from failed retrievals may have null byte/hash/storage fields, but must record the requested locator and failure. A retrieved artifact without confirmed edition identity may be stored and searched; conclusions must retain that uncertainty. An uninspected reference creates a work/link record, not a fabricated passage.

### Locations and transformations

A PDF locator contains `pageIndex` (zero-based) and `printedPageLabel` (nullable string), plus optional bounding box. HTML uses a captured artifact plus a selector or text offsets; plain text uses offsets. Locations refer to the stored artifact, not a mutable live page. Page ranges and search ranges are inclusive and specify which locator system they use.

A passage retains nearby context through a locator into the same artifact. Corrections and translations reference their input passages/artifacts. OCR verification records that the quotation was checked against its page image; extraction confidence alone is not verification.

### Graph and resolution

Edges point from the citing passage to the source it references; this direction does not establish chronology. Edge types are `explicit_citation`, `quotation`, and `inferred_borrowing`; inferred borrowing requires a stated basis and uncertain direction where applicable. Contradiction is a finding about passages, not automatically a citation edge.

Detect citation cycles on edition-specific passage and link identities. Do not collapse editions into works when confirming a cycle. A work-level loop is a candidate requiring inspection, since one edition may cite a source that cites a different edition. Where a target passage or edition is unresolved, report a possible cycle with its uncertainty, not a confirmed cycle. A citation cycle alone does not prove that all support is circular: assess the evidence dependence separately. Record dates and conflicts without assuming that every citation points backward in time.

Resolution statuses are `resolved`, `edition_unknown`, `source_unavailable`, `passage_not_found`, `reference_missing`, and `blocked`. Use `resolved` only when the cited target passage is located in an identified edition. Support or contradiction is a separate finding. If several limitations apply, use the earliest unresolved step (reference, edition, access, passage) as the status and retain the others in the rationale.

`passage_not_found` requires a search record stating the inspected edition/artifact, page range, query variants, extraction/OCR limitations, and outcome. It means not found within that coverage. `source_unavailable` and `blocked` require a reason and next step; `blocked` is a policy or scope restriction, not an ordinary retrieval failure.

### Snapshots and evidence assessment

A snapshot is an immutable manifest of exact record revisions and artifact hashes, including graph edges and search coverage used by the report. Its ID/hash is distinct from the report body's hash to avoid circular hashing. Snapshot creation validates all references. Later records do not alter it.

Report evidence assessment uses `supported`, `contradicted`, `mixed`, or `insufficient`. Support requires evidence bearing on the tested assertion, not merely an assertion repeated by a source. Contradicted requires evidence against the assertion. Mixed means material evidence conflicts or supports only part of the tested assertion; explain which. Insufficient means the inspected evidence cannot settle it and does not imply falsehood.

Transmission findings use `citation_cycle`, `quotation_altered`, `context_changed`, and `attribution_changed`. Coverage reasons use `within_scope_complete`, `budget_exhausted`, `access_blocked`, and `interrupted`. They are separate from evidence assessment. Each finding references the passages/edges that justify it.
