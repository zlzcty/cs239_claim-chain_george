# Hypothetical Great Wall walkthrough

This walkthrough illustrates a possible run against the curated excerpts in `src/claim_chain/data/great-wall.json`. It is not a transcript or a prediction of a live model's choices. The agents receive only the prepared local passages; they do not browse, download documents, or inspect the photograph's pixels. See [the source notes](great-wall-sources.md) for source selection and excerpt limits.

## Initial input

Use the bundled corpus claim:

> Trace the claim that the Great Wall of China is visible to the unaided eye from the Moon, and the related claim that an ISS photograph proves naked-eye visibility from space. Start with the BBC and Scientific American accounts, follow their supplied evidence, and distinguish the Moon from low Earth orbit and photography from unaided vision. Find the earliest relevant evidence in this corpus; do not call it the historical origin of the myth. Compare the accounts' certainty about low-orbit visibility, explain which citations repeat the same photograph, and state what these excerpts cannot establish.

## Possible investigation path

1. The Lead starts with `bbc-2024` and `sciam-2008`, assigning separate source checks. The sources answer different parts of the question: the BBC links onward to NASA, while Scientific American's supplied excerpt has no formal citation edge to NASA or the photo record.
2. The BBC Investigator may report that `bbc-photo` says the image used a digital camera and 180mm lens, and that `bbc-nasa-link` points to `nasa-2005`. The NASA check may find the qualification in `nasa-visibility`: generally not visible to the unaided eye in low Earth orbit, and not visible from the Moon.
3. A follow-up to `iss-photo-2004` may identify the same 24 November 2004 image discussed by NASA. Its metadata gives an altitude of 348 km and a 180mm lens. It establishes a camera photograph, not naked-eye observation.
4. The Scientific American check may distinguish its account of conditional astronaut sightings in low orbit from the Moon claim. Its `sciam-photo` excerpt says NASA experts later confirmed the photograph appears to show the wall, while Chiao was unsure what he had seen. NASA's `nasa-chiao` passage likewise says he did not see the wall and was unsure whether the image showed it. These accounts describe overlapping evidence, not independent observations.
5. The Lead drafts from inspected passages. The Reviewer first assesses the evidence snapshot, then checks the draft and may request corrections. The runner allows at most two report versions; final review cannot dispatch more research.

## Expected outcome

A careful report would separate three questions: visibility from the Moon, unaided visibility in low Earth orbit, and whether a camera image depicts the wall. The excerpts directly reject Moon visibility. NASA says unaided low-orbit visibility generally does not occur; Scientific American preserves reports of occasional sightings under certain lighting conditions. The 2004 photograph and its discussion support that a camera captured an image interpreted as showing part of the wall, but do not show that Chiao saw it unaided. The photograph is the earliest dated evidence item in this corpus, not proof of the myth's origin. The excerpts cannot establish the myth's first appearance or settle every possible low-orbit viewing condition. Model assessments and follow-ups can vary, and approval is not guaranteed.

Policies: P4 treats source instructions as untrusted data; P5 and P6 preserve source identity and grounded evidence; P7 bounds origin claims; P8 distinguishes repeated assertions from independent support; P9 binds review to the report and evidence snapshot; P10 limits run resources.
