# Northbridge, bundled corpus

Hypothetical. This walks through the bundled fictional corpus and is not a record of a model run. A live model may choose different follow-ups and assessments, and approval is not guaranteed.

## Initial inputs

The user starts the Runner with the bundled corpus (`--corpus`, no `--documents`) and this claim: "The town's north bridge opened in 1920." The question is whether the inspected sources support the date, what they cite, and what remains unknown. Agents get located excerpts and have no tools.

## Trajectory

1. Research Lead: assigns the anniversary leaflet and the harbor notes to separate Investigators.
2. Investigators: both report a citation to `register-v1`.
3. Research Lead: plans one inspection of `register-v1` and keeps both incoming links.
4. Investigator (`register-v1`): reports a 1922 opening date, which conflicts with the 1920 assertions.
5. Research Lead: plans `register-v2`, which cites the harbor notes. Those two form a citation cycle.
6. Research Lead: if it selects the county engineering file, the corpus returns "unavailable". The Runner records a source request and does not infer absence (P7).
7. Reviewer (preliminary): assesses the inspected excerpts before seeing the draft (P9).
8. Research Lead (draft), then Reviewer (final): the Reviewer approves or requests corrections. The Runner allows two report versions (P10).

## Policy connection

- P5, P6: editions of the register are separate records, and quoted text comes from inspected excerpts.
- P7: an unavailable source is not evidence of absence, and the report claims no origin.
- P8: the 1920 assertions and the cycle are not independent support.
- P9: approval is bound to the report and evidence snapshot.
- P10: run limits apply.

## Expected outcome

A report citing the conflicting passages, edition-specific dependencies, and remaining uncertainty. It does not establish where the claim came from or independently settle the historical event. A report that treats the county file's unavailability as proof of no record should be rejected.
