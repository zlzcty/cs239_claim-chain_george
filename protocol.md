# Agent protocol and scheduling

The application runs in one process. A local runner calls the roles through the OpenAI-compatible provider adapter; scheduling is application code and makes no research decisions. Larger design ideas (A2A transport, leases, a persistent queue, deduplication, spending caps) are in [future-todo.md](future-todo.md). See [agent-execution.md](agent-execution.md) for the model loop and role permissions.

## Run flow

1. **Plan.** The Lead receives the claim and a source catalog and returns a `Plan`: up to four jobs, each with `source_id`, `question` and optional `depends_on`. There are at most three planning waves.
2. **Admit.** The runner admits only known, unattempted source IDs within the source and call limits. Unknown source IDs are dropped with a recorded limitation. Unavailable sources become local source-request records, not evidence of absence.
3. **Investigate.** At most two Investigators run at once, one per source, each in a fresh context. A dependent job receives only its prerequisites' original passages and accepted findings. The result is an `Investigation`: assessment, reasoning, verbatim quotes with passage IDs, citation links (passage, reference text, catalog target) and follow-up source IDs. In document mode the Investigator first searches and reads its assigned file with the tools in [tools.md](tools.md).
4. **Validate.** The runner checks that every quote is a verbatim substring of a passage the agent was given or opened, and that referenced IDs exist. A failed job is recorded and independent jobs continue. Jobs whose dependencies never complete, including cyclic ones, are marked blocked at dispatch.
5. **Preliminary review.** The Reviewer sees the claim and an evidence-only snapshot (sources, passages, citation links, cycles, limitations) with no findings or draft, and returns a `Preliminary` assessment with alternative explanations. In document mode it may open decisive passages itself.
6. **Draft and review.** The Lead drafts from the snapshot (`Draft`: assessment, reasoning, decisive passage IDs, `earliest_source_id`, limitations). The runner rejects unknown passages and an earliest source that is uninspected or has year 0. The Reviewer then checks the exact draft against its preliminary assessment (`Review`: approved, issues, required changes). There are at most two report versions, and review cannot request more research.
7. **Publish.** `report.md`, `review.json` (approval with report and snapshot hashes), `snapshot.json`, `preliminary.json` and `ledger.sqlite` are written. `python -m claim_chain --verify RUN_DIRECTORY` rechecks the hashes. Only the Reviewer role can approve, and approval binds to those exact bytes.

## Budgets and failures

- One shared model-call limit covers planning, investigation, tool rounds, corrections and review. Ten calls are reserved for review in document mode, and each document source check budgets ten. Source count, per-request timeout and run deadline are also enforced.
- A response that fails schema validation gets one correction call. Provider errors and validation failures are recorded against the job.
- On deadline or interruption the run stops dispatching and keeps partial artifacts without approval.
- An unapproved report after two rounds is labeled as such.
