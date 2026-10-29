# Tools

## Storage and document handling

Use SQLite for evidence, task state, and budget accounting, plus a file-backed artifact directory. A graph database is not required. Every operation records run/task/attempt IDs, inputs, tool version, timestamps, status, usage, and output references. Retrieval records include the requested and final URL, access status, and artifact hash. Logs must not contain session credentials.

Retrieve once, store the original, extract located text, then OCR if needed. Preserve PDF page index separately from printed page label. OCR text retains image coordinates and warnings; decisive scan quotations must be checked against the page image. Cache extraction by artifact hash and extractor version. Corrections, translations, and summaries are derived artifacts with parent references, never replacements for the original.

Agents read excerpts with surrounding context through the tools below. Full documents remain in storage. Search results and citation extractions are candidates, not verified evidence.

## Research tools

| Tool | Input | Output |
|---|---|---|
| `web_search` | Query, result limit, date/domain filters | Candidate URLs, snippets, retrieval status, search record |
| `fetch_url` | URL, allowed types, size limit, timeout | Stored artifact and response metadata, or access error |
| `browser_open` | URL, configured read session, permitted interaction | Rendered artifact, snapshot/downloads, or access error |
| `extract_text` | HTML/PDF/text artifact | Located spans, extraction warnings, method/version |
| `ocr_image` | Image or scanned PDF, optional region | Located OCR spans, confidence where available, page-image references |
| `find_quote` | Passage/query, corpus, matching options | Exact/fuzzy matches with locations and search coverage |
| `extract_citations` | Located spans and metadata | Candidate references with originating passage IDs |
| `search_catalogs` | Title, creator, date, edition, language | Candidate works/editions and catalog identifiers |
| `fetch_book_page` | Edition ID and locator | Stored page/preview with verified identity, or access status |
| `compare_editions` | Two edition IDs and target passages | Located textual differences, alignment uncertainty, artifact references |
| `search_records` | Entity, date, place, permitted collection | Candidate records, located extracts, provenance, coverage |
| `lookup_entity` | Name, type, time/place | Candidate identities and evidence references |
| `create_source_request` | Work/edition, pages, reason, facts needed | Local structured request with a stable ID |

`compare_editions` aligns and diffs passages; the Investigator explains the significance. Record search does not certify a factual assertion. Investigators assess returned records and explain supporting, conflicting, or inconclusive findings. The former `verify_record` tool is therefore omitted.

## Evidence tools

Records follow [evidence.md](evidence.md). All references identify an ID and revision; snapshot reads never silently substitute the latest revision.

| Tool | Input | Output |
|---|---|---|
| `write_evidence` | Record, expected prior revision, idempotency key | Validated new revision or conflict |
| `read_evidence` | Record ID/revision or snapshot ID | Stored record and provenance |
| `search_evidence` | Run, query, record types/filters | Matching records with revisions |
| `get_passage` | Passage ID or artifact locator, context window | Original/derived text with locations and context |
| `get_page_image` | Artifact ID, page index, optional region | Page image with mapping to printed label |
| `query_graph` | Claim/snapshot, node/edge filters | Citation paths, cycles, and dependence records |
| `hash_artifact` | Stored artifact | Cryptographic hash and byte size |
| `create_snapshot` | Run ID and selected record revisions | Immutable manifest and content hash |

## Execution and orchestration

`execute_python` accepts code or a configured skill ID, declared artifact inputs, and a resource allocation. It returns output artifacts, exit status, errors, and usage. Apply policy P3. Configured Python extraction skills do not need per-task approval. Agent-written code is optional and disabled unless the restricted execution environment exists.

Scheduler operations are application code, not Investigator tools: validate/enqueue tasks selected by the Lead, atomically claim ready work, reserve/reconcile budget, renew leases, checkpoint progress, retry, and cancel. Workers can submit proposals and results but cannot enqueue agent tasks or raise allocations. The scheduler validates dependency graphs and rejects cycles. See [protocol.md](protocol.md).

Tool wrappers check run/task allocations before calls and enforce timeouts, byte limits, and allowed actions. Shared limits apply to reviewer tools as well as Investigator tools.

## Suggested implementation order

1. SQLite/artifact storage, evidence read/write, HTTP retrieval, and located extraction. PyMuPDF and an HTML extractor are suitable starting points.
2. OCR and page-image inspection for scans; Tesseract/OCRmyPDF are options.
3. Search/catalog adapters, exact and fuzzy quote search, and a two-worker queue.
4. Browser fallback with Playwright where rendering is needed; edition alignment and graph views after basic evidence handling works.

Treat external providers as adapters: record provider-specific access failures without requiring one catalog or archive to be available for every run.
