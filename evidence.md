# Evidence records

This is the shared storage contract, not an A2A wire schema. Persist records in SQLite and bytes in an artifact directory. Validate required fields, enum values, and referenced revisions before committing writes. Timestamps use UTC; hashes use SHA-256.

## Common fields

Every record has `id`, `revision` (positive integer), `recordType`, `runId`, `createdAt`, `createdBy` (agent/tool identity), `taskId` (nullable for initial input), and `provenanceIds`. Unknown values are explicit nulls, not invented metadata. Cross-record references contain `{ "id": "...", "revision": 1 }`.

Writes append revisions. An update names the expected prior revision; concurrent updates return a conflict rather than overwriting. An idempotency key repeated with the same payload returns the original result; reuse with different content fails. Referenced records are retained for the run. Identity merges preserve aliases and the merge rationale; uncertain matches remain separate.

## Record types

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

## Locations and transformations

A PDF locator contains `pageIndex` (zero-based) and `printedPageLabel` (nullable string), plus optional bounding box. HTML uses a captured artifact plus a selector or text offsets; plain text uses offsets. Locations refer to the stored artifact, not a mutable live page. Page ranges and search ranges are inclusive and specify which locator system they use.

A passage retains nearby context through a locator into the same artifact. Corrections and translations reference their input passages/artifacts. OCR verification records that the quotation was checked against its page image; extraction confidence alone is not verification.

## Graph and resolution

Edges point from the citing passage to the source it references; this direction does not establish chronology. Edge types are `explicit_citation`, `quotation`, and `inferred_borrowing`; inferred borrowing requires a stated basis and uncertain direction where applicable. Contradiction is a finding about passages, not automatically a citation edge.

Detect citation cycles on edition-specific passage and link identities. Do not collapse editions into works when confirming a cycle. A work-level loop is a candidate requiring inspection, since one edition may cite a source that cites a different edition. Where a target passage or edition is unresolved, report a possible cycle with its uncertainty, not a confirmed cycle. A citation cycle alone does not prove that all support is circular: assess the evidence dependence separately. Record dates and conflicts without assuming that every citation points backward in time.

Resolution statuses are `resolved`, `edition_unknown`, `source_unavailable`, `passage_not_found`, `reference_missing`, and `blocked`. Use `resolved` only when the cited target passage is located in an identified edition. Support or contradiction is a separate finding. If several limitations apply, use the earliest unresolved step (reference, edition, access, passage) as the status and retain the others in the rationale.

`passage_not_found` requires a search record stating the inspected edition/artifact, page range, query variants, extraction/OCR limitations, and outcome. It means not found within that coverage. `source_unavailable` and `blocked` require a reason and next step; `blocked` is a policy or scope restriction, not an ordinary retrieval failure.

## Snapshots and evidence assessment

A snapshot is an immutable manifest of exact record revisions and artifact hashes, including graph edges and search coverage used by the report. Its ID/hash is distinct from the report body's hash to avoid circular hashing. Snapshot creation validates all references. Later records do not alter it.

Report evidence assessment uses `supported`, `contradicted`, `mixed`, or `insufficient`. Support requires evidence bearing on the tested assertion, not merely an assertion repeated by a source. Contradicted requires evidence against the assertion. Mixed means material evidence conflicts or supports only part of the tested assertion; explain which. Insufficient means the inspected evidence cannot settle it and does not imply falsehood.

Transmission findings use `citation_cycle`, `quotation_altered`, `context_changed`, and `attribution_changed`. Coverage reasons use `within_scope_complete`, `budget_exhausted`, `access_blocked`, and `interrupted`. They are separate from evidence assessment. Each finding references the passages/edges that justify it.
