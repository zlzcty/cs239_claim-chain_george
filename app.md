# Claim Chain Auditor

## Purpose and scope

Audit one explicit claim by tracing citations, checking the passages they point to, and making bounded searches for earlier wording or independent evidence. Report the earliest source found within the search scope, how the claim changed, and whether the inspected evidence supports it. Finding an early source does not establish the claim's origin or truth.

The MVP accepts public sources and non-confidential user-supplied URLs, passages, PDFs, and text files. It does not provide confidentiality controls. It does not contact people, buy sources, or scan an archive without a question.

## Run input

Record the original claim, seed sources, and the interpretation being tested. Preserve close variants separately. Ask the user when ambiguity would change the investigation.

Before starting, record date/domain/language limits, maximum citation depth, maximum distinct sources, deadline, model-call limit, optional spending cap, and enabled tools. Depth counts followed citation edges from a seed at depth zero; alternate searches start at depth zero and consume the same source budget. Require a finite source limit and deadline. The user can change limits during a run; record the change. Default to two Investigator workers and 80 model calls per run. Reserve 20% of the initial time and model-call allowance for drafting, review, and export; the user can set different reserves before the run. See [protocol.md](protocol.md) for cutoff and accounting rules.

## Agents and task boundaries

- **Research Lead:** selects questions, creates all agent tasks, decides proposed follow-ups, and drafts the report.
- **Investigator:** resolves one citation link or bounded source question: identify a reference, inspect a passage, compare specified editions, search for earlier/independent evidence, or check a material factual assertion. It stores evidence and proposes follow-up tasks; it does not spawn agents.
- **Review Agent:** inspects decisive original passages and their context, checks editions and evidence dependencies, and tests an alternate explanation or trail. It can use research tools and propose Investigator tasks. It approves a specific report version or lists required corrections.

A task has a question, evidence inputs, acceptance criteria, dependencies, and an allocation from the run budget. By default it resolves one link. The Lead may permit one further unambiguous link within that allocation. Ambiguity, branching, or a substantial new question produces a task proposal.

## Execution

1. Store seed artifacts; extract located text and citation candidates. Use OCR for scans and retain page images.
2. The Lead selects tasks for promising citation trails and searches that could challenge them.
3. A persistent dependency queue dispatches ready tasks to available workers. Tasks share stored sources, not conversation histories. Merge duplicate work; do not automatically merge ambiguous source identities.
4. Investigators retrieve relevant passages, inspect context, save findings, and propose bounded follow-ups. Independent tasks run in parallel; dependent tasks wait for their stated prerequisites.
5. Stop a branch at its answered question, depth limit, repeated citation, unavailable source, or exhausted allocation. A primary source can end provenance tracing but does not by itself settle truth. Other branches continue within the run limits.
6. The Lead drafts a report against an immutable evidence snapshot. Before reading the draft, the reviewer independently records an assessment of decisive passages and potential alternate explanations. It then checks the draft and approves that exact version or requests corrections. Changed reports or snapshots require another review.
7. Return the approved report locally. If review cannot finish, return an explicitly unapproved partial report with the reason. External publication follows the action permissions in policy.md.

## Evidence and output

Use the records and graph rules in [evidence.md](evidence.md). Keep full documents outside agent context; retrieve passages and nearby pages on demand. Preserve original text separately from OCR corrections, translations, and summaries.

Each citation link has a resolution status: `resolved`, `edition_unknown`, `source_unavailable`, `passage_not_found`, `reference_missing`, or `blocked`. `Resolved` means the target and cited passage were located, not that they support the claim. Negative searches record their coverage; inaccessible sources are not evidence of absence.

The report contains the original and interpreted claim, an answer with evidence references, decisive quotations with locations, the citation graph, the earliest source found, and unresolved links with next steps. It records search scope, budget use, and review status. Separate:

- **Evidence assessment:** `supported`, `contradicted`, `mixed`, or `insufficient`, with reasons distinguishing assertions from evidence of truth.
- **Transmission findings:** zero or more of `citation_cycle`, `quotation_altered`, `context_changed`, or `attribution_changed`, each tied to graph edges or passages.
- **Coverage:** `within_scope_complete`, `budget_exhausted`, `access_blocked`, or `interrupted`; list all applicable limitations. Complete means selected in-scope questions were addressed, not that every possible source was searched.

## Acceptance cases

Use the replayable cases and comparison plan in [evaluation.md](evaluation.md). Check citation locations and uncertainty, including a real cycle, an apparent work-level cycle across editions, an inaccessible source, a misleading quotation, and converging branches. Verify that changing the report invalidates approval.
