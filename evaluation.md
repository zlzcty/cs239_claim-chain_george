# Evaluation plan

The repository does not yet contain an implementation or fixtures. This plan defines what to build and compare; it does not claim results.

## Replayable source set

Create a small fictional corpus with dated, edition-labeled documents and explicit page or line locators. Store source files, a manifest of retrieval responses and access failures, and an answer key separately. The audit must read only the source files and manifest; do not expose the answer key to agents. Record each document's hash so runs use the same bytes. Replay failed retrievals as well as successful responses, and disable live network access during evaluation.

Include these cases:

| Case | Corpus construction | Expected observation |
|---|---|---|
| Converging branches | Two seeds cite the same edition and passage | Both paths reach the same evidence; the source extraction is reused. Repetition alone is not independent support. |
| Contradictory evidence | A seed asserts a fact; a separately sourced record contradicts it | The report cites the record and explains the contradiction rather than counting repetitions. |
| Wrong edition and misleading context | A seed cites a passage from edition 1; edition 2 changes the wording, and surrounding text limits the claim | The report identifies the edition and records the relevant context and alteration. |
| Confirmed citation cycle | Two identified passages in specified editions explicitly cite each other | The graph records the cycle with locations. The claim's truth is assessed separately. |
| Apparent work-level cycle | Edition A2 cites B; B cites A1, with no evidence A1 cites B | Work-level collapse is a candidate only; no confirmed edition-specific cycle. |
| Inaccessible source | A citation identifies a work whose configured retrieval response is unavailable | The link stays unresolved with a source request; absence and falsity are not inferred. |

Provide a published answer key with expected source and edition identities, citations, passage locations, evidence assessment, permitted uncertainty, and known unavailable material. Include unambiguous assertions and expected findings for deterministic checks; allow equivalent wording in reports.

## Comparison

Run the multi-agent design and a single-agent baseline against the same corpus, claim, model/provider, available tools, deadline, source cap, model-call limit, and spending cap. The baseline performs all research and drafts the report in one agent context; it does not receive the multi-agent review. Report that difference when comparing outcomes. If a separate evaluator is used, keep its cost and calls outside both systems' budgets and report them separately.

Run each configuration at least three times when model behavior is nondeterministic, with recorded seeds/settings where supported. Randomize run order. Preserve provider/model and prompt versions, tool outputs, final reports, evidence snapshots, task traces, elapsed time, call/token usage, and available cost. If a provider does not report usage or supports no seed, say so. Results from a small synthetic corpus do not establish real-world performance.

## Checks and measures

- **Citation accuracy:** count expected links and passage/edition locations correctly identified, missed, and invented. Review ambiguous cases against the answer key.
- **Conclusions:** record unsupported factual assertions, false cycle claims, missed contradictions, and whether unavailable sources are represented accurately. Distinguish a partial but honest answer from an incorrect one.
- **Workflow:** check source-extraction reuse, task dependency ordering, independent preliminary review, and invalidation of approval after report changes.
- **Cost and speed:** report wall-clock time, model calls, reported token usage, tool calls, and cost per run. Do not call a system better solely because it is faster if evidence quality differs.

Before scoring, define how partial-credit and uncertain findings count. Report each run and its failures, not only averages. Add separate tests for deterministic budget accounting, retries, and queue recovery as those features are implemented.
