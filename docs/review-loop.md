# Review loop: conversation logs -> a stronger model's grade -> fixes (Nov 15)

User: "There should be a simple way to upload the conversation logs, get graded by a better model and improvements made. It constantly needs to improve."

## What is logged
`brain/convlog.py`: one entry per turn — what the child said (words only), each toy's lines, and flags (stop, I spy, look, fact-guard
fixes), status and reply latency. **RAM only** on the brain (last 2000 turns, gone on restart; `SENTIENT_CONVLOG=0` turns it off).
Readable only on the brain itself (`GET /convlog` from 127.0.0.1, i.e. over ssh) and on the PIN-protected Parent Board (Settings:
Conversation log -> Download / Clear).

## The loop (ask Claude Code: "review the logs")
1. `python tools/review_convlog.py pull [--clear]` — brain -> `docs/private/convlogs/<stamp>.json` (git-ignored; holds the child's words, never committed).
2. `python tools/review_convlog.py score <file>` — `<file>.review.md`: transcript + automatic checks per child turn
   (answered, one answer, no deflection to school, no toy chat right after the child, stop kept) and a summary.
3. The reviewing model (Claude) reads the transcript, grades each failed turn, names the cause (prompt, code, model limit) and the fix.
4. `python tools/review_convlog.py regress <file>` — the child's turns become regression cases (`docs/private/convlogs/regression.json`).
5. Fix, then measure on the Jetson with the real Gemma: `tools/child_check.py` (synthetic notes + questions + the regression cases,
   `--audio` for Gemma hearing speech like the live toys), `tools/grade_toys.py` (toy-to-toy chats), `tools/ispy_check.py`; keep only
   what improves without breaking a guard; deploy.

Privacy: reviewing sends the child's words to the reviewing model (Claude) in that session. The Parent Board can clear the log at any time.

## Child leads (first round, Nov 15)
Cause of "the toys do not respond, they keep talking about their random facts": the Parent Board was locked (Lock forgot the key: no
notes at all), the prompt told the toys to answer anything off-curriculum "in at most five words, then ask a school question", every
child turn carried rotating curriculum items, all three toys answered every question, and toy chats restarted 45 s after the child.
Changes: `SENTIENT_CHILD_LEADS=1` (child's subject first, notes questions answered, no deflection, no curriculum block on child turns),
`CHILD_MAX_LINES=2`, toy chats wait `IDLE_AFTER_CHILD_S=180` after the child, "stop" -> one "I'm listening" + no toy chat for
`STOP_QUIET_S=600` (transcript shortcut; for the audio model, the HEARD words cut the queued reply), one-child families use that
child's notes without "Playing now", the board's **Close** no longer forgets the key (Settings has "Lock the notes").

`tools/child_check.py` (real Gemma on the Jetson): text 2/26 (old rules) -> 11/13; audio 7/13 (notes 4/5, child's subject 3/3; Gemma
itself never answers STOP, the code stop works; a toy named by the child answered first 1/1 in text, 0/1 in audio).
