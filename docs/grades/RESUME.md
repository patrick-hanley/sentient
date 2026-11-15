# Resume notes (grade goal, paused by the user)

State: branch goal/grade, main merged in again on resume (sfx brackets), all committed. Nothing running; the Jetson is NOT in use (another goal has it until the user says).
Toys stay muted; no audio; do not deploy tuned settings.

Done: text-only composite (tools/textgrade.py, fixed in a2dad6b), harness with 3-turn banter scenes, keep/revert rule, ledger (docs/grades/ledger.md).
Baselines (real Gemma): tune 13.21/20, held 14.91/20. toytalk v2 levels 1-3 all reverted on guards (long lines / run-ons / padding).

Next, when released:
1. v3 level 3 on tune is DONE and in the ledger (18.58, reverted on run-on 9 / long lines 10 / padding 100 words per scene; the user asked for a rerun later). Next: a v4 wording that holds ONE sentence strictly and does not make every line a question (q/line ~0.9), then v3/v4 level 1 and 2. Needs the user's OK for the Jetson (they are fixing hardware; do not use it until told).
2. Score vs baseline: `tools/grade_toys.py compare /tmp/grade-runs/grade-base-tune.json <new>`. Raw baseline runs live in /tmp/grade-runs (scratch; if gone, rerun baseline tune+held).
3. Only a variant that passes decide() on tune goes to held: `tools/grade_remote.sh <label> held 1 <level>`; report the ratio to held baseline 14.91 (1.30x = 19.4, near the cap).
4. Read why Dyno failed 2/6 safety probes in the baseline tune run (probe text is saved in new runs only; rerun baseline to see it).
5. Add each run to docs/grades/runs via `tools/grade_toys.py agg` and to the ledger. Numbers only.
Run the grade_remote chain with run_in_background and wait on the *.agg.json file named grade-<label>.agg.json.

## Round 2 result (Nov 14): stop rule hit, 4 variants (v4-v7) in a row without a keep
Best: v7 level 3 (code in brain/toytalk.py at HEAD), tune 14.73 vs 13.21 baseline (1.12x), guards all clean, reverted only on padding (97.8 vs 75.5 words/scene, limit 1.2x).
Ideas not tried: level 2 only with v7 wording (fewer question lines, less padding); asking for 'under 7 words per statement'; the user deciding whether the 1.2x padding limit is right
(a conversation with questions and facts needs more words than 6-word statements). Do not loosen the rule without the user.
Held baseline 14.91: 1.30x = 19.4/20, so the held target is probably out of reach whatever the tune result.
Run a step: `NOTE=... tools/grade_step.sh <label> <tune|held> <level> baseline-<set>` (ends muted, verified; appends ledger + /tmp/grade-progress.log).
