# Flat-Earth claim, eight real documents

Real episode. This records one live run (`deepseek-v4.1-flash`, thinking on, 61 model calls, about 8 minutes). A different run may plan differently, fail a different job, or need a second draft.

## Initial inputs

The user starts the Runner with `--documents` pointing at eight downloaded files plus a `metadata.json` giving each file's edition and year, and this claim:

> Claim from a school textbook: In 1492 most educated Europeans, and the medieval Church, believed the Earth was flat, and Columbus's voyage proved them wrong. Trace where this story comes from using the supplied documents. Find the earliest supplied source that shows Columbus facing flat-Earth opposition, check whether supplied sources written before 1492 treat the Earth as round, and check how the later retellings depend on one another. Keep what people believed separate from what later writers said they believed.

| Year | Document |
|---|---|
| c.1268 | Aquinas, Summa Theologiae I q.1 |
| c.1357 | Mandeville, Travels |
| 1839 | Irving, Life and Voyages of Columbus (abridged edition of the 1828 work) |
| 1874 | Draper, Conflict Between Religion and Science |
| 1891 | Hale, Life of Columbus |
| 1896 | White, Warfare of Science with Theology |
| 1997 | Russell, The Myth of the Flat Earth (paper) |
| unknown | Wikipedia, Myth of the flat Earth |

The Research Lead receives the claim and a catalog of the eight documents (id, title, edition, year). It cannot read the documents.

## Trajectory

1. Runner: indexes the files into chunks and a search index, reads `metadata.json`, and starts the Lead.
2. Research Lead (wave 1): plans four jobs, each with one source and one question (P10 caps jobs per wave).
   - Irving: "What flat-Earth opposition does this account attribute to Columbus, and which earlier sources, if any, does it cite?"
   - Aquinas: "Does this pre-1492 text treat the Earth as round, and what belief does it attribute to its contemporaries?"
   - White, waiting for Irving: "How does this later retelling describe medieval flat-Earth belief and Columbus, and which earlier accounts does it credit?"
   - Russell, waiting for White: "What does this critique identify as the origin of the flat-Earth Columbus story, and what evidence does it cite?"
3. Runner: starts the Irving and Aquinas jobs, two at a time. A job with a prerequisite waits for that job's finding.
4. Investigator (Irving): `search_source`, then `read_source` on its own document only. It quotes the Salamanca passage where "casuists" argue from scripture that the earth is flat, and records references to other works (P5, P6).
5. Investigator (Aquinas): finds "the earth is round" used as a stock example of a proven conclusion.
6. Runner: checks every quote is a verbatim substring (whitespace aside) of a passage the Investigator opened. A citation whose reference text is not in an opened passage is dropped and listed under limitations (P6). Twelve were dropped in this run.
7. Investigators (White, then Russell): each receives the earlier job's finding labeled as an interpretation to check, not as evidence (P8). White dates acceptance of a round earth to the eighth century. Russell names Irving and Letronne as the myth's 19th-century source.
8. Research Lead (wave 2): sees that Irving names no medieval source and that Aquinas and White cut against the claim. It plans Draper, Mandeville, Hale (after Draper) and Wikipedia (after Draper and Hale), each asking what the source says and what it cites.
9. Investigators (wave 2): Mandeville affirms a round earth with antipodes and gives flatness only to "simple men unlearned". Draper and White repeat the Church-versus-science story. Hale names Irving as his model, giving two citation edges.
10. Runner: stops scheduling when the source and call allowance is reached, and records that as a limitation (P10).
11. Reviewer (preliminary): receives only the evidence snapshot, not the Investigators' reasoning or any draft, and may open passages itself with the same tools (P9).
12. Research Lead (draft): returns an assessment, reasoning, decisive passage IDs, an earliest source and limitations. The Runner rejects an earliest source whose year is 0 (P7), then renders the report with quoted evidence and a citation graph.
13. Reviewer (final): receives the rendered report and approves version 1. The Runner stores the approval with the SHA-256 of the report and the evidence snapshot.
14. User: runs `python -m claim_chain --verify runs/<run-id>`, which recomputes both hashes.

## Policy connection

- P1: all eight files are user-supplied; nothing is fetched at run time. The Wikipedia page was saved before the run.
- P5: the Irving file is the 1839 abridged edition, and the report says it is not the 1828 first edition.
- P6: every quote in the report was opened by an Investigator; unmatched citations were dropped rather than kept.
- P7: Wikipedia has no year, so it cannot be named earliest. Letronne, Augustine, Lactantius, Cosmas and Boorstin are named but not supplied, so they stay unresolved.
- P8: Draper and White are treated as repeating one story, not as independent support.
- P9: only the Reviewer approves, and the approval is bound to the report and snapshot hashes.
- P10: waves, jobs, concurrency and calls are capped; the cap stopped further research.

## Expected outcome

Assessment "contradicted". The report says pre-1492 texts (Aquinas, Mandeville) treat the earth as round; the earliest supplied Columbus opposition is Irving; Draper and White repeat the story; Russell and Wikipedia point to Irving as the source. The citation graph is thin (two edges, both from Hale), so dependence among the retellers rests mostly on what Russell and Wikipedia say. The report does not prove the myth's origin or settle what people believed in 1492. A run that approves a report naming an undated source as earliest, or quoting text no Investigator opened, would be a failure.
