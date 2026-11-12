# California academics repository

What the toys can teach, by grade and subject, grounded in the California Department of Education (CDE) frameworks and
standards. Data: `brain/curriculum/*.json`. Lookup: `brain/curriculum.py`. Parent Board glue: `brain/curriculum_picks.py`.
Tests: `tools/test_curriculum.py`.

## Verification status (read this first)

`cde.ca.gov` sits behind a web firewall that redirects automated clients (WebFetch, curl) to a "wafalert" page, so the content
could **not** be checked against the live CDE pages by the build agents. Each file therefore carries `"verified": false` (or `true`
once a human has compared it with the sources) and a `verification_note`. Topic structure follows the published California course
sequence (e.g. grade 4 = *California: A Changing State*), but a person should compare each file with its `sources` in a browser
and flip `verified` to `true`. No standard codes are invented: `standard` is omitted unless it was seen on a source page.
Spelling and vocabulary lists are representative grade-appropriate examples; CDE publishes skills, not official word lists.

## Files

| file | subject id | content |
|---|---|---|
| `ela.json` | `ela` | reading / writing / language skills, spelling lists by pattern, grade vocabulary |
| `math.json` | `math` | CA Common Core math domains per grade, math vocabulary, number facts |
| `hss.json` | `hss` | History-Social Science framework units and vocabulary, K-8 |
| `science.json` | `science` | California NGSS topics, science vocabulary |
| `california.json` | `california` | symbols, regions and geography, Native peoples, missions and ranchos, Gold Rush, government, famous Californians |

Grade `0` is kindergarten; grades 0-8 are supported.

## Schema

A file is `{subject, sources[], verified, verification_note?, note, items[]}`. `sources` must have at least one https URL.
An item is:

| field | meaning |
|---|---|
| `id` | unique across all files, `<subject>-<grade>-<slug>` (lowercase a-z, 0-9, hyphens) |
| `grade`, `subject`, `strand` | where it is taught; strand is a short area name |
| `title` | child-friendly name, at most 60 characters |
| `kind` | `topic`, `vocab`, `spelling` or `fact` |
| `summary` | one or two plain sentences a toy could say, own words, at most 260 characters |
| `words` | vocab / spelling lists (at least 5 for those kinds) |
| `tags` | 2-10 lowercase search keywords |
| `difficulty` | 1 start of grade, 2 middle, 3 end of grade or stretch |
| `standard`, `source` | optional; only what was seen on a page; `source` must be one of the file's `sources` |

`brain/curriculum/SPEC.md` is the brief the data was written to.

## Lookup

```python
from brain import curriculum as C
C.query(grade=4, subject="california", text="gold rush")   # all filters optional, ANDed
C.query(kind="spelling", grade=2, difficulty=2)            # difficulty = hardest level to include
C.grade_from_text("in 2nd grade")                          # -> 2
C.coverage()                                               # {grade: {subject: count}}
```

The index (by id, grade, grade+subject, tag) is built once on first use; `C.reload()` rebuilds it.

## How the toys use it

* **Grade**: the child's Parent Board `profile` item ("in 2nd grade", "in kindergarten", "grade 7"). Unknown, nobody playing,
  notes paused or board locked: `DEFAULT_GRADE` (2nd), with no child data used.
* **[GRADE TOPICS] block**: each turn the director adds up to 3 topics (about 500 characters) after the private notes. They rotate
  (no repeats until the grade is used up), mix subjects, and say "never quiz unless the child asks". It is added after the log line
  and is never logged. Any failure returns an empty block; a turn never fails because of the curriculum.
* **Idle banter** picks its topic from the same rotation (falling back to `config.BANTER_SEEDS` if the data is missing).
* **Parent Board**: "What the toys can teach at this grade" lists every topic for the grade (read-only). "More" and "Skip" save a
  normal item: boost = `goal` "teach more: ...", skip = `boundary` "not yet: ...", both with `detail: "curriculum:<id>"`. They are
  encrypted, visible and deletable under "What the toys know", and `notes_block` leaves them out (the topics block uses them instead:
  boosted topics are 5x as likely, skipped ones never appear). API: `GET /api/curriculum?child=ID`, `POST /api/curriculum/pick`
  `{child, id, mode: boost|skip|clear}`.

## Extending it

1. Read the CDE source page; summarise in your own words (no pasted standards text); do not invent standard codes.
2. Add items to the right file (or a new `<name>.json` whose `subject` is one of the five), keep ids unique, add the page URL to `sources`.
3. Set `verified` to `true` only if you compared the whole file with its sources.
4. Run `.venv/bin/python tools/test_curriculum.py`; it checks schema, duplicates, coverage (K-5 every subject, 6-8 the four core subjects) and sources.
5. Deploy like any brain change (rsync `brain/`, restart, POST `/mute`).

## Privacy

The curriculum is public content and holds nothing about a child. Only the grade number and the parent's boost/skip ids (already
encrypted Parent Board items) feed the block; neither is logged.
