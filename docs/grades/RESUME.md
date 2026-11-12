# Resume notes (grade goal, paused by the user)

State: branch goal/grade, main merged in, all committed. Nothing running; the Jetson is NOT in use (another goal has it until the user says).
Toys stay muted; no audio; do not deploy tuned settings.

Done: text-only composite (tools/textgrade.py, fixed in a2dad6b), harness with 3-turn banter scenes, keep/revert rule, ledger (docs/grades/ledger.md).
Baselines (real Gemma): tune 13.21/20, held 14.91/20. toytalk v2 levels 1-3 all reverted on guards (long lines / run-ons / padding).

Next, when released:
1. `tools/grade_remote.sh v3l3-tune tune 1 3` (then levels 1, 2): toytalk v3 = one sentence, <= 10 words per line. Needs the user's OK for the Jetson.
2. Score vs baseline: `tools/grade_toys.py compare /tmp/grade-runs/grade-base-tune.json <new>`. Raw baseline runs live in /tmp/grade-runs (scratch; if gone, rerun baseline tune+held).
3. Only a variant that passes decide() on tune goes to held: `tools/grade_remote.sh <label> held 1 <level>`; report the ratio to held baseline 14.91 (1.30x = 19.4, near the cap).
4. Read why Dyno failed 2/6 safety probes in the baseline tune run (probe text is saved in new runs only; rerun baseline to see it).
5. Add each run to docs/grades/runs via `tools/grade_toys.py agg` and to the ledger. Numbers only.
Run the grade_remote chain with run_in_background and wait on the *.agg.json file named grade-<label>.agg.json.
