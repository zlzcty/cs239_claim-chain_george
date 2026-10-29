# Northbridge document-mode run

This records one live run, not a guaranteed result. Model: `deepseek-v4.1-flash` through an OpenAI-compatible endpoint. A different run may choose different searches.

Initial input: `--documents` pointing at four Markdown files (anniversary leaflet 1924, harbor notes 1925, Town Register first edition 1923 and revised edition 1926) plus a `metadata.json` giving each file's edition and year. Claim: the north bridge opened in 1920 per the leaflet, which cites the Town Register. Trace the citation, find the earliest source stating the opening date, separate completion from opening to traffic, and check independence.

1. Lead plans wave 1: one source check per file, two at a time (P10).
2. Each Investigator calls `search_source`, then `read_source` on its assigned file only, and quotes verbatim from opened passages (P5, P6). It records references such as "see: register-v1" and proposes the matching catalog ID.
3. Findings: the leaflet and harbor notes repeat 1920; register-v1 says construction ended in 1921 and the bridge opened to traffic on 3 May 1922; register-v2 repeats 1920 and cites harbor notes.
4. The runner builds the citation graph and flags the harbor notes and register-v2 cycle (P8).
5. Reviewer assesses the evidence snapshot before seeing any draft, with read access to the documents (P9).
6. Lead drafts; the runner rejects any earliest source with unknown year, then Reviewer approves report version 1 against the report and snapshot hashes.

Expected outcome: assessment "contradicted"; register-v1 (1923) named as the earliest source in the supplied material; construction (1921) kept distinct from opening (1922); the 1920 repetitions treated as non-independent; limitations state local documents only, no eyewitness evidence, and that this is not proof of origin (P7).

Observed difference without `metadata.json`: all years are 0, so the earliest source cannot be named, and in one run the Reviewer rejected a draft that called register-v1 earliest in prose but left the field null.

Policies: P4, P5, P6, P7, P8, P9, P10.
