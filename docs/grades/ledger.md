# Grade ledger (numbers only; run JSONs in docs/grades/runs; all with real Gemma on the Jetson via tools/grade_remote.sh, brain stopped then restarted and muted)

Composite /20 after chunk merging. Baseline = no toy-talk block (`SENTIENT_TOY_TALK=0`, the code on main).

| run | set | composite | rel | follow | variety | length | banter | safety | probes | words/scene | guards (long/run-on/repeat) | decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | tune | 13.21 | | | | | | | 4/6 | 75.5 | 0/0/4 | reference |
| baseline | held | 14.91 | | | | | | | 12/12 | 84.8 | 0/0/1 | reference |
| v2 level 1 | tune | 14.63 | | | | | | | 4/6 | 125.8 | 8/0/3 | revert: long_lines 0 -> 8 (+1.43) |
| v2 level 2 | tune | 17.38 | | | | | | | 6/6 | 165.2 | 81/6/6 | revert: run_on 0 -> 6 (+4.18) |
| v2 level 3 | tune | 18.05 | | | | | | | 6/6 | 170.7 | 69/2/1 | revert: long_lines 0 -> 69 (+4.85) |

Per-category columns: see docs/grades/runs/*.json (`agg.toys.<toy>.scores`). Headline category moves, baseline tune -> v2 level 3: relevance ~2.1 -> 3.9,
follow-up ~1.4 -> 3.9, banter depth 2.1 -> 3.8, variety 3.7 -> 3.9, **length 4.0 -> 2.5** (toys wrote 3+ sentence lines), speaker distinctness 0.72 -> 0.66.

## Notes
- No variant is kept. Level 3 would be 1.37x the tune baseline, but it buys it with longer multi-sentence lines (padding, long-line and run-on guards), against the 1-2 sentence requirement.
- v3 (committed untested): the length instruction now says ONE sentence of at most 10 words per line. Needs a real-Gemma tune run when the Jetson is free.
- Held-set target: 1.30x of 14.91 = 19.4/20, within ~0.6 of the ceiling. Reaching it is unlikely; report the held ratio, do not change the target.
- Safety: baseline tune run failed 2 of 6 hurt/scared probes (both Dyno; held 12/12). Cause not yet read (probe text is now saved in scratch runs). Variants with the block passed 6/6 in 2 of 3 runs; with n=6 this is noisy, not evidence either way.
- Superseded earlier runs (first composite = timing + rubric categories, single-turn scenes; discarded when scope became text-only): baseline 10.17/20 tune; v1 level 3 reverted for repeats 9 -> 27.
- Defect found after the first real text runs: chunks of one toy line counted as separate lines (broke alternation, inflated line counts). Fixed in `merge_chunks`; every run above re-scored from its saved text, so all rows are comparable. Done before any keep decision (all were reverts).
- Mute: the first grade_remote left the brain unmuted for a short window after restart (fixed: now retries until muted is confirmed). The three later chains ended `muted-ok`.
