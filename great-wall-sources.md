# Great Wall demo sources

The corpus is `src/claim_chain/data/great-wall.json`. It contains short excerpts from four real sources, retrieved on 28 October 2026. These sources were selected before the run. The agents receive local text; they do not browse the web or inspect the photograph's pixels.

| Corpus ID | Source | Date |
|---|---|---|
| `bbc-2024` | Iain Todd, [Can you see the Great Wall of China from space?](https://www.skyatnightmagazine.com/space-science/can-you-see-great-wall-china-from-space), BBC Sky at Night Magazine | Published 27 February 2024; page metadata also records a 1 October 2024 modification |
| `sciam-2008` | Mara Hvistendahl, [Is China's Great Wall Visible from Space?](https://www.scientificamerican.com/article/is-chinas-great-wall-visible-from-space/), Scientific American | 21 February 2008 |
| `nasa-2005` | NASA, [China's Wall Less Great in View from Space](https://www.nasa.gov/wp-content/uploads/static/history/PDFs/great_wall_less_great_from_space.pdf), official archived PDF | Feature dated 9 May 2005; page last updated 30 November 2007; PDF print header dated 2 July 2019 |
| `iss-photo-2004` | NASA/JSC, [Astronaut Photo ISS010-E-8497 CHINA](https://eol.jsc.nasa.gov/SearchPhotos/photo.pl?mission=ISS010&roll=E&frame=8497) | Photograph taken 24 November 2004; current catalog caption's publication date is unspecified |

The BBC passage links to NASA's former feature URL, `https://www.nasa.gov/vision/space/workinginspace/great_wall.html`. The official archived PDF preserves that feature. Its “View larger image” link points to NASA/JSC's former photo-record URL with `mission=ISS010`, `roll=E`, and `frame=8497`; the corpus uses the current record for that same photograph. These are the two curated citation edges:

```text
bbc-2024 -> nasa-2005 -> iss-photo-2004
sciam-2008 (no citation edge encoded)
```

Scientific American discusses NASA and the Chiao photograph, but its retrieved article does not hyperlink these supplied records. No formal citation edge has been inferred from that overlap. The agents can still compare what the accounts say.

Excerpts were checked against downloaded publisher HTML and text extracted from NASA's PDF. Formatting whitespace was collapsed; whitespace introduced between HTML links and punctuation was removed. Wording, qualifications, and attribution were retained. The corpus stores URLs and section/page locators with each passage. Full publisher pages are not included.

The photograph is the earliest dated evidence item in this corpus. Its `year` describes capture, not catalog-caption publication. The metadata establishes camera use and low-orbit altitude; it does not demonstrate what an astronaut could resolve unaided. NASA's 2005 feature includes a reported Alan Bean quotation, not an Apollo-era transcript. The excerpts cannot establish the first historical appearance of the myth or prove a universal claim about every low-orbit viewing condition.

For the demo, look for the agents separating Moon visibility from low Earth orbit, and photography from unaided sight. BBC's categorical conclusion about naked-eye visibility is stronger than Scientific American's account of conditional sightings. A useful report should preserve that difference and avoid counting two descriptions of the same photograph as independent observations. The expected conclusion is guidance for presenting the corpus, not a prerecorded model result.
