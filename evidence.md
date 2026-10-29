# Evidence records

Evidence is stored as Pydantic models in `models.py`, in a SQLite event ledger, and in run files. Versioned records, an artifact store, and edition and work identities are in [future-todo.md](future-todo.md).

## Models

- `Source`: `id`, `title`, `edition`, `year` (0 means unknown), `passages`, and a `manifest` (document mode: path, content hash, chunk and page counts, extraction errors).
- `Passage`: `id`, `locator`, `text`, and `cites`, the catalog source IDs it references.
- `Quote`: `passage_id` and verbatim `text`. `Citation`: `passage_id`, reference text, `target_id`.
- `Investigation`, `Preliminary`, `Draft` and `Review` are the agent outputs described in [protocol.md](protocol.md).

## Document mode

Each file is copied into the run's `documents/` archive and identified by a content-hash ID, so changed bytes get a new identity. Text is split into 3000-character chunks (PDFs per page, locator `page N, chunk M`) and indexed with SQLite FTS5. `metadata.json` in the documents directory may give each file's `edition` and `year`. A passage exists as evidence only after `read_source` opens it; search snippets are discovery only. Failed or blank extraction is recorded in the manifest and reported as a limitation.

## Run files

- `ledger.sqlite`: an append-only `events` table (sequence, kind, JSON body, time) holding plans, tool calls and results, source inspections, findings, snapshot, reviews. The terminal interface replays it.
- `snapshot.json`: the evidence view given to the Reviewer. Its SHA-256 is recorded.
- `report.md` and `review.json`: the report, and approval with the report and snapshot hashes.
- `corpus.json` or `documents.json` plus `documents/`: the input as used.

## Citation graph

Edges run from a citing passage to its target source (`cites`). Cycles are found between inspected sources and reported as candidates, not proof of dependence; a cycle among editions of one work needs inspection. Resolution gaps are listed as uninspected citation targets. Assessments are `supported`, `contradicted`, `mixed` or `insufficient`, and "earliest source" means the earliest attestation in the supplied material, not the origin of the claim.
