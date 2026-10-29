# Northbridge, four documents

Real episode of a fictional corpus. This records one live run (`deepseek-v4.1-flash` through an OpenAI-compatible endpoint). A different run may choose different searches.

## Initial inputs

The user starts the Runner with `--documents` pointing at four Markdown files plus a `metadata.json` giving each file's edition and year:

| Year | File |
|---|---|
| 1923 | Town Register, first edition (`register-v1`) |
| 1924 | Anniversary leaflet |
| 1925 | Harbor notes |
| 1926 | Town Register, revised edition (`register-v2`) |

Claim: the north bridge opened in 1920, per the leaflet, which cites the Town Register. Trace the citation, find the earliest source stating the opening date, separate completion from opening to traffic, and check independence.

## Trajectory

1. Research Lead: plans wave 1 with one source check per file, two running at a time (P10).
2. Investigators: each calls `search_source`, then `read_source` on its assigned file only, and quotes verbatim from opened passages (P5, P6). They record references such as "see: register-v1" with the matching catalog ID.
3. Findings: the leaflet and harbor notes repeat 1920. `register-v1` says construction ended in 1921 and the bridge opened to traffic on 3 May 1922. `register-v2` repeats 1920 and cites the harbor notes.
4. Runner: builds the citation graph and flags the cycle between the harbor notes and `register-v2` (P8).
5. Reviewer (preliminary): assesses the evidence snapshot before seeing any draft, with read access to the documents (P9).
6. Research Lead (draft): the Runner rejects an earliest source with unknown year (P7), then renders the report.
7. Reviewer (final): approves report version 1 against the report and snapshot hashes.

## Policy connection

- P5: the two register editions are separate sources, not one.
- P6: quotes come only from passages an Investigator opened.
- P7: the report names the earliest source within the supplied material, not the origin of the date.
- P8: the 1920 repetitions are not counted as independent; the cycle is flagged.
- P9: the approval is tied to hashes.
- P10: waves, jobs and calls are capped.

## Expected outcome

Assessment "contradicted". `register-v1` (1923) is the earliest source in the supplied material. Construction (1921) is kept distinct from opening (1922). The limitations say the material is local documents only, has no eyewitness evidence, and does not prove origin.

Observed difference without `metadata.json`: all years are 0, so the earliest source cannot be named. In one run the Reviewer rejected a draft that called `register-v1` earliest in prose but left the field null, which is the P7 check working.
