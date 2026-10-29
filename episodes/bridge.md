# Hypothetical bridge walkthrough

This is a hypothetical walkthrough of the bundled fictional corpus, not a record of a particular model run. Given the same input, a live model may choose different follow-ups and assessments.

Initial input: “The town's north bridge opened in 1920.” Use the bundled corpus and ask whether the inspected sources support the date, what they cite, and what remains unknown.

1. The Research Lead assigns the anniversary leaflet and Harbor notes to separate Investigators.
2. Both cite `register-v1`. Inspect that edition once and retain both incoming links.
3. Compare its 1922 opening date with the 1920 assertions. Inspect `register-v2`, which cites Harbor notes; those two edition identities form a citation cycle.
4. If selected, the county engineering file returns the corpus's unavailable status. The runner records a source request without inferring absence.
5. The Reviewer assesses the inspected excerpts before seeing the draft. The Lead drafts, and the Reviewer approves or requests corrections. The runner allows two report versions.

Expected outcome: a report citing the conflicting passages, edition-specific dependencies, and remaining uncertainty. The evidence does not establish the claim's origin or independently settle the historical event. Approval is not guaranteed.

Policies: P4 treats source instructions as untrusted data; P5 and P6 preserve source identity and grounded evidence; P7 bounds origin claims; P8 distinguishes repeated assertions from independent support; P9 binds review to the report and evidence snapshot; P10 limits run resources.
