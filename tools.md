# Agent-facing tools

Tools are available only in document mode (`--documents DIR`), served by a local MCP stdio server (`claim_chain.document_server`) over an indexed copy of the supplied files. Excerpt mode (`--corpus`) has no agent tools. Investigators and the Reviewer's preliminary assessment can call them; the Research Lead and final report review cannot.

list_sources: Takes no input. Returns every document with `id`, `title`, `edition`, `year` (0 means unknown) and a manifest (path, content hash, chunk and page counts, blank pages, extraction error or warning).
search_source: Takes `source_id`, `query` (SQLite FTS5: keywords, quoted phrases, OR, prefix `*`) and optional `limit` (1-10, default 5). Returns matching chunk IDs, chunk numbers, locators and short snippets. Snippets are discovery only and are not citable evidence.
read_source: Takes `source_id`, optional `start` chunk number (default 1) and `count` (1-3, default 1). Returns full passages with `id`, chunk number, locator and text. Only passages opened this way can be quoted or cited.

An Investigator may read only its assigned source. The runner rejects other source IDs. The configured OpenAI-compatible model endpoint is an external service, not an agent tool. The runner's ordinary operations are described in [app.md](app.md).
