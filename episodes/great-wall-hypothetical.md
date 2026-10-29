# Great Wall visibility, curated excerpts

Hypothetical. This illustrates a possible run against the curated excerpts in `src/claim_chain/data/great-wall.json`. It is not a transcript or a prediction of a live model's choices. Agents get local excerpts with no tools. They do not browse, download documents, or inspect the photograph's pixels. See [the source notes](../great-wall-sources.md) for source selection and excerpt limits.

## Initial inputs

The user starts the Runner with the bundled corpus (`--corpus`), which supplies four excerpted sources: `bbc-2024`, `sciam-2008`, `nasa-2005` and `iss-photo-2004`. The claim is the corpus default:

> Trace the claim that the Great Wall of China is visible to the unaided eye from the Moon, and the related claim that an ISS photograph proves naked-eye visibility from space. Start with the BBC and Scientific American accounts, follow their supplied evidence, and distinguish the Moon from low Earth orbit and photography from unaided vision. Find the earliest relevant evidence in this corpus; do not call it the historical origin of the myth. Compare the accounts' certainty about low-orbit visibility, explain which citations repeat the same photograph, and state what these excerpts cannot establish.

## Trajectory

1. Research Lead: starts with `bbc-2024` and `sciam-2008`, as separate source checks. The BBC excerpt links onward to NASA. The Scientific American excerpt has no formal citation edge to NASA or the photo record.
2. Investigator (BBC): reports that `bbc-photo` says the image used a digital camera and a 180mm lens, and that `bbc-nasa-link` points to `nasa-2005`.
3. Investigator (NASA): finds in `nasa-visibility` that the wall is generally not visible to the unaided eye in low Earth orbit and not visible from the Moon.
4. Investigator (`iss-photo-2004`): identifies the 24 November 2004 image NASA discusses. Its metadata gives 348 km altitude and a 180mm lens. This shows a camera photograph, not naked-eye observation (P6).
5. Investigator (Scientific American): separates conditional low-orbit sightings from the Moon claim. NASA's `nasa-chiao` passage and `sciam-photo` both say Chiao was unsure what he saw. These describe overlapping evidence, not independent observations (P8).
6. Reviewer (preliminary): assesses the evidence snapshot before seeing a draft (P9).
7. Research Lead (draft), then Reviewer (final): the Reviewer may request corrections. The Runner allows two report versions and the final review cannot dispatch more research (P10).

## Policy connection

- P5: the photograph's `year` is the capture date, not the catalog caption date.
- P6: decisive passages are cited by ID and were inspected.
- P7: the photograph is the earliest dated item in this corpus, not the myth's origin.
- P8: two descriptions of the same photograph are not counted as two observations.
- P9: approval is bound to the report and snapshot hashes.
- P10: call, source and report-version limits apply.

## Expected outcome

A careful report separates three questions: visibility from the Moon, unaided visibility in low Earth orbit, and whether a camera image depicts the wall. The excerpts reject Moon visibility. NASA says unaided low-orbit visibility generally does not occur, while Scientific American preserves reports of occasional sightings under certain lighting. The 2004 photograph shows a camera captured an image interpreted as part of the wall, but not that Chiao saw it unaided. The excerpts cannot establish the myth's first appearance or every low-orbit viewing condition. Model assessments vary and approval is not guaranteed. A report that counts the photograph as proof of naked-eye visibility should be rejected.
