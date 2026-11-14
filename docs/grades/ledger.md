# Grade ledger (numbers + the toys' dialog, synthetic scenarios only; append-only records in ledger.jsonl, rendered per run in ledger/<run>.md (every scene's lines with per-line and scene scores, same scenario vs baseline side by side); all with real Gemma on the Jetson via tools/grade_remote.sh, brain stopped then restarted and muted)

Composite /20 after chunk merging. Baseline = no toy-talk block (`SENTIENT_TOY_TALK=0`, the code on main).

<!-- TABLE -->
| run | set | level | composite | probes | words/scene | guards (long/run-on/repeat) | decision | dialog |
|---|---|---|---|---|---|---|---|---|
| baseline-tune | tune | 0 | 13.21 | 4/6 | 75.5 | 0/0/4 | reference | [dialog](ledger/baseline-tune.md) |
| baseline-held | held | 0 | 14.91 | 12/12 | 84.8 | 0/0/1 | reference | [dialog](ledger/baseline-held.md) |
| v2-level1-tune | tune | 1 | 14.63 | 4/6 | 125.8 | 8/0/3 | revert: guard 'long_lines' rose 0 -> 8 (gain +1.43) | [dialog](ledger/v2-level1-tune.md) |
| v2-level2-tune | tune | 2 | 17.38 | 6/6 | 165.2 | 81/6/6 | revert: guard 'run_on' rose 0 -> 6 (gain +4.18) | [dialog](ledger/v2-level2-tune.md) |
| v2-level3-tune | tune | 3 | 18.05 | 6/6 | 170.7 | 69/2/1 | revert: guard 'long_lines' rose 0 -> 69 (gain +4.85) | [dialog](ledger/v2-level3-tune.md) |
| v3-level3-tune | tune | 3 | 18.58 | 6/6 | 100.2 | 10/9/0 | revert: guard 'run_on' rose 0 -> 9 (gain +5.38) | [dialog](ledger/v3-level3-tune.md) |
| v4-level3-tune | tune | 3 | 18.66 | 6/6 | 109.2 | 12/5/5 | revert: guard 'run_on' rose 0 -> 5 (gain +5.45) | [dialog](ledger/v4-level3-tune.md) |
| v5-level3-tune | tune | 3 | 18.56 | 6/6 | 115.5 | 6/0/7 | revert: guard 'repeats' rose 4 -> 7 (gain +5.36) | [dialog](ledger/v5-level3-tune.md) |
| v6-level3-tune | tune | 3 | 18.64 | 6/6 | 123.9 | 8/1/0 | revert: guard 'long_lines' rose 0 -> 8 (gain +5.44) | [dialog](ledger/v6-level3-tune.md) |
| v7-level3-tune | tune | 3 | 14.73 | 6/6 | 97.8 | 0/0/0 | revert: padding, words/scene 75.5 -> 97.8 | [dialog](ledger/v7-level3-tune.md) |
<!-- /TABLE -->

Per-category columns: see docs/grades/runs/*.json (`agg.toys.<toy>.scores`). Headline category moves, baseline tune -> v2 level 3: relevance ~2.1 -> 3.9,
follow-up ~1.4 -> 3.9, banter depth 2.1 -> 3.8, variety 3.7 -> 3.9, **length 4.0 -> 2.5** (toys wrote 3+ sentence lines), speaker distinctness 0.72 -> 0.66.

## Notes
- v3 level 3 (tune, run finished before the user's stop; result valid): composite 18.58 (1.41x tune baseline), length back to ~3.5, repeats 0, probes 6/6, but run-on guard 0 -> 9, long lines 0 -> 10, words/scene 100 (1.33x, over the 1.2x padding limit), and almost every line is a question (q/line ~0.9). Reverted. Levels 1 and 2 of v3 not run.
- Round 2 (Nov 14, four variants in a row, none kept, stop rule hit; every run ended `muted-ok`):
  v4 level 3 (one sentence, 4-10 words): 18.66, reverted, run-on 0 -> 5 (Gemma collapsed several toys onto one line, format break).
  v5 level 3 (each toy on its own NAME: line): 18.56, reverted, long lines 6 and repeats 4 -> 7 (the 'ask the next toy' rule added a second/third sentence; replies repeated across turns).
  v6 level 3 (1-2 sentences, <= 16 words, question as second sentence): 18.64, reverted, long lines 8 (Gemma ignores the word cap when it also adds a question).
  v7 level 3 (hand-off questions as their own short lines): 14.73 (1.12x), ALL content guards clean (long 0, run-on 0, repeats 0), probes 6/6, reverted ONLY on padding, words/scene 75.5 -> 97.8 (limit 1.2x = 90.6).
  Closest to a keep: v7. Its padding is the cost of extra question lines; the rule was not loosened. Held set not run (nothing passed tune).
- No variant is kept. Level 3 would be 1.37x the tune baseline, but it buys it with longer multi-sentence lines (padding, long-line and run-on guards), against the 1-2 sentence requirement.
- v3 (committed untested): the length instruction now says ONE sentence of at most 10 words per line. Needs a real-Gemma tune run when the Jetson is free.
- Held-set target: 1.30x of 14.91 = 19.4/20, within ~0.6 of the ceiling. Reaching it is unlikely; report the held ratio, do not change the target.
- Safety: baseline tune run failed 2 of 6 hurt/scared probes (both Dyno; held 12/12). Cause not yet read (probe text is now saved in scratch runs). Variants with the block passed 6/6 in 2 of 3 runs; with n=6 this is noisy, not evidence either way.
- Superseded earlier runs (first composite = timing + rubric categories, single-turn scenes; discarded when scope became text-only): baseline 10.17/20 tune; v1 level 3 reverted for repeats 9 -> 27.
- Defect found after the first real text runs: chunks of one toy line counted as separate lines (broke alternation, inflated line counts). Fixed in `merge_chunks`; every run above re-scored from its saved text, so all rows are comparable. Done before any keep decision (all were reverts).
- Mute: the first grade_remote left the brain unmuted for a short window after restart (fixed: now retries until muted is confirmed). The three later chains ended `muted-ok`.
