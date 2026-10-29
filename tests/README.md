# Test cases

Run with `python -m pytest`. All tests use mocked model clients or a local MCP subprocess; none call a live provider.

- `test_workflow.py`: planning waves, job admission and dependencies, quote validation, preliminary review before drafting, report versions, approval hashes.
- `test_cli.py`: argument validation, call-budget minimums, run artifacts, `--verify`.
- `test_documents.py`: HTML and Markdown ingestion, PDF page locators, extraction failures, FTS5 search, bounded reads, content-hash identity, and `metadata.json` editions and years.
- `test_document_research.py`: an MCP subprocess where unopened text cannot be quoted, and a document-mode run that produces a reviewed report.
- `test_tools_provider.py`: the native tool-call loop, tool transcripts in isolated contexts, correction after invalid output.
- `test_provider.py`, `test_model_routing.py`, `test_streaming.py`, `test_check_connection.py`: schema-validated calls and corrections, per-role models, streaming, connection check.
- `test_tui.py`: terminal interface panes, Document tools tab, live progress, replay.
