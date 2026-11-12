# Curriculum data file format (see docs/curriculum.md)

Each file brain/curriculum/<name>.json is one JSON object:

{
  "subject": "ela" | "math" | "hss" | "science" | "california",
  "sources": ["https://www.cde.ca.gov/...", ...],   // >=1 real CDE (or other official) URLs you actually fetched; required
  "note": "one or two sentences: what this file covers and how it was derived (own words)",
  "items": [ ... ]
}

Each item:
{
  "id": "<subject>-<grade>-<slug>",     // unique across ALL files; grade 0 = kindergarten; lowercase a-z0-9-
  "grade": 0..8,
  "subject": same as the file's subject,
  "strand": "short area name, e.g. 'phonics', 'fractions', 'Gold Rush', 'Earth science'",
  "title": "short child-friendly topic name (<= 60 chars)",
  "kind": "topic" | "vocab" | "spelling" | "fact",
  "summary": "1-2 plain sentences, written for a toy to say to a child of that grade, in your own words (<= 220 chars)",
  "words": ["optional", "list", "of", "vocabulary or spelling words"],   // vocab/spelling items: 6-12 words; others may omit
  "tags": ["lowercase", "keywords", "a child might say"],               // 3-8 tags, used for search
  "difficulty": 1 | 2 | 3,            // 1 = start of grade, 3 = end of grade / stretch
  "standard": "optional label of the standard/framework section ONLY if you saw it on the page, e.g. 'HSS-4.2' style codes exactly as published; omit if unsure",
  "source": "optional URL of the exact page this item came from (must be one of the file's sources)"
}

Rules: summarize in your own words (no long copied text); never invent standard codes; be accurate (these are said to children);
child-safe content (describe hard history such as the mission era, Gold Rush, and Native peoples' treatment honestly but gently, from
the perspective the CA framework takes: multiple perspectives, respect for California Native peoples, present tense where they are living communities).
Coverage target: EVERY grade 0-8 gets items (K-5 at least 10 each, 6-8 at least 6 each) unless the file's note says the subject does not apply.
Output valid JSON only (no comments in the file). Validate with: python3 -c "import json;json.load(open('FILE'))"
