# Conversation metrics and the self-improvement loop

The toys measure how the **child** communicates during play (a sample of roughly 5-10 minutes), score it against a
published-style speech-interaction rubric, and adapt the **toys** a little after each session. The rubric itself is a private
reference (`docs/private/`, git-ignored because this repo is public); this page describes the measures in our own words.

Code: `brain/metrics.py` (tracker + scoring), `brain/coaching.py` (adaptation), `brain/progress.py` (encrypted storage),
`brain/metrics_live.py` (glue to the Director), `brain/report.py` (session-log export). Tests: `tools/test_metrics.py`.

## What is measured

Per session (a run of activity; see "Sessions"):

| Name | Meaning | Target |
| --- | --- | --- |
| N_T | toy **cues**: a toy-started turn (greeting, idle banter, a noticed face/tap), or a reply that asks a question or invites | |
| N_R | child **responses**: the first child utterance that starts within 10 s of the end of a cue | |
| N_I | child **initiations**: every other utterance (including a second one after a response, or one after 10 s) | |
| T_R | turn-taking ratio, (N_R + N_I) / N_T | about 1.0 |
| I:R | initiation-to-response ratio, N_I / N_R | about 1.0 |
| C_R | longest reciprocity loop: consecutive alternating toy/child turns on one thread. **Both speakers count**, so cue + answer = 2 | 5 or more |
| L_R | response latency: end of the toy's sound to the child's speech onset, per response; we keep median, 25th/75th/90th percentile | 1-2 s |

Five 0-4 scores (total out of 20) follow the rubric's level descriptions:

* **Response latency** from the median: under 1 s = 4, up to 2.5 s = 3, up to 5 s = 2, slower = 1, a cue with no answer inside 10 s = 0.
  (The rubric leaves 2-3 s open; the cut at 2.5 s is ours.) No cue at all: not measurable.
* **Reciprocal turn-taking** from C_R: under 2 = 0, 2 = 1, 3-4 = 2, 5-6 = 3, 7 or more = 4.
* **Verbal initiation** from comments/questions per 5 minutes: none = 0; only requests ("more", "open") = 1; under 1 = 1; 1 to under 3 = 2;
  3 to under 5 = 3; 5 or more = 4.
* **Conversational maintenance**: each utterance gets a level (repeat of the toy 0, one or two words 1, an answer without detail 2, an answer with
  detail 3, detail plus handing the turn back with a question or the toy's name 4); the session score is the rounded mean over the
  answers, and 0 if at least half of the utterances repeat the toy.
* **Joint attention (verbal)**: 0 speech unconnected to the toys; 1 on topic but never naming a toy/feature, or naming one only within 8 s of a tap or
  motion; 2 names a toy/feature, but only when answering a cue; 3 does so spontaneously; 4 spontaneously directs attention ("look at...", "this...").

If a category cannot be measured (for example no words were available), it is shown as unmeasurable and the total is out of fewer points
(for example 12/16) instead of being counted as zero.

## Sessions

A session ends after `METRICS_IDLE_GAP_S` (180 s) without activity, at `METRICS_MAX_SESSION_S` (600 s) so each is a 5-10 minute sample, or when the
child marked "Playing now" changes. A session is scored and kept only with at least 3 child utterances, 60 s and one cue; shorter ones are counted
and dropped. Settings are in `brain/config.py`.

## How events get in

`Director` calls small hooks (all in `brain/metrics_live.py`, all exception-proof):

* child utterance: speech onset/end from the VAD (`Utterance.start_mono` is the first voiced frame, not the pre-roll) and its words from the STT result or the model's HEARD line;
* toy sound: the Atom's PLAYING/PLAYED timestamps (already on the brain clock) give each toy turn its audio span; the turn's end is the last sound, not when text finished;
* toy turn open/close, whether it was toy-initiated, and the question/invite flags of each line as it is dispatched;
* barge-in, and taps/motion ("activation").

## Proxies, honestly: what each can and cannot see

* **Text features are shallow.** Echolalia is "at least 80% of the child's content words came from the toy's last line"; it misses delayed echo and
  flags a child who legitimately repeats a key word. Expansion is words like "because / and then" or 8+ words. Wants vs. comments is a short word list plus length.
  Questions are `?`/wh-/auxiliary form. Joint attention uses the toys' names, a list of body/feature words and attention verbs; it cannot tell that "it" means the horn.
* **Topic continuity** is word overlap with the previous turn. A spontaneous utterance with no overlap starts a new loop; paraphrase can break a
  loop that a person would call one. Answers to a cue are always linked.
* **Latency is biased.** Mics are muted while a toy talks plus `MIC_TAIL_S`, so speech that starts during a toy line is only heard through barge-in; those count as latency 0 and
  an overlap. The VAD needs a few voiced frames, so onset can be late by tens of milliseconds. Wi-Fi jitter between PLAYED and our clock adds to it.
* **Cues are counted per toy turn, not per line**, and a reply that happens to end in a question counts as a cue. IMU reactions, parent cues and canned scenes are not cues.
* **Who spoke** is not known: the system hears "a voice". A sibling or parent speaking is counted as the child. Speaker identity is not used.
* **No words (audio-mode model that does not report HEARD)**: timing and counts still work; the text-based categories are unmeasurable.
* **Early sessions are noisy.** Few utterances, one noisy minute or a hard topic move a score by a point. The loop is built for that (see below).
* It measures **speech**, not understanding, nonverbal communication or whether the child enjoyed it. It is a coaching signal, not a clinical assessment.

An optional local-model judge (`SENTIENT_METRICS_JUDGE`, `config.METRICS_JUDGE`) is reserved for a second opinion on maintenance and joint attention when the
brain is idle; it is **not implemented yet** and the flag does nothing. Any future version must hold text only in RAM and discard it with the session.

## Privacy

* Text is turned into numbers/tags at the moment it is understood and dropped. The tracker holds only the content words of the toys' last line and the child's last
  utterance, in RAM, replaced by the next one and cleared when a session closes. Nothing is logged: no transcripts, no audio.
* A finished session is numbers and tags: counts, ratios, scores, tag counts, time-of-day bucket, median noise level, number of toys online, the coaching settings in force.
* **Per child**, only while the Parent Board is unlocked *and* a child is marked "Playing now": sealed with the board's data key as `progress-<child>.enc`
  (same envelope as the profiles, `Parent._seal`). It is deleted with the child or "wipe everything", and a parent can delete one session or all history.
  Otherwise the summary is kept **anonymously in RAM** (last 12) and lost at restart.
* The open dashboard (:8080) shows live anonymous counters only: no names, no child identity, no text.
* The markdown "session log" export is generated on demand from the stored numbers; nothing is stored.

## The self-improvement loop

After every scored session (`coaching.after_session`), for the child who was playing:

1. Compare the five scores with the target (3, proficient); the weakest category picks a lever. One change per step, one at a time:

   | Weak category | Knob moved one level |
   | --- | --- |
   | Response latency | patience (toys wait longer before filling silence: idle-banter wait x (1 + 0.35/level)); then shorter lines; then simpler pace |
   | Reciprocal turn-taking | follow-up bias (stay on the child's topic, ask about their detail); then more open questions |
   | Verbal initiation | invitation frequency (pause and invite the child to tell or ask) |
   | Maintenance | question style: easier either/or questions while answers are minimal, mixed when middling; once everything is at least proficient, a stretch toward open questions |
   | Joint attention | "point out a feature" prompts |

2. Knobs are integers with hard bounds (`coaching.KNOBS`). All neutral = today's prompt, byte for byte. Non-neutral knobs become a short `[COACHING ...]` block prepended through the
   same slot as the parent notes, plus a longer idle wait. "Pace" is a prompt instruction (shorter, simpler sentences); the TTS speed is deliberately not touched.
3. Lightly after each interaction: three unanswered cues in a row make the toys wait one level longer for the rest of the session, five two levels. In RAM only.
4. Guardrails: at most 2 changes per rolling day; none while the previous change is being judged; a change is judged on the next 2 scored sessions against the average just before it. If the
   normalised total falls by more than 0.08 (about 1.6 of 20) it is **rolled back automatically** and that knob is frozen for 5 sessions. Parents can switch coaching **off** per child
   (frozen: no changes, no rollbacks, neutral prompt), **undo** a change, or **reset** to defaults, all from the Progress card. Every change, keep, rollback and undo is logged as numbers (knob, from, to, weak
   category, score, total) and shown there.
5. **Review queue.** If a category stays weak (score under 2) for three sessions with every relevant knob exhausted or frozen, or a change was rolled back twice, the loop adds a *proposal* (canned, generic text)
   about the spoken lines or the base prompt. It is shown on the Parent Board; "Approve" only records that a person agreed to do it.

**Why this boundary.** A knob is a bounded, reversible nudge to *how* the toys behave in this child's session, checkable from numbers alone, small enough that a bad step costs one session and the rollback undoes it.
Spoken lines (greetings, fillers, scripted reactions) and the base system prompt carry the toys' safety rules, persona, topic limits and accuracy requirements for a young child. Rewriting them automatically from noisy,
shallow proxies could quietly erode those guarantees, is hard to roll back by metric, and the signal cannot tell a better line from one that merely scores better. So the coach has no code path to them (`coaching.py` imports neither the
director, scripted lines nor config; a test enforces it) and can only ask a human.

Known limits: one child per session; knobs act on the toys' prompt, so the effect depends on Gemma following it; a parent talking nearby can move scores; a change is judged on two sessions, which is quick and noisy.

## Using it

* Operator: the "Conversation" panel on the dashboard, and `GET /metrics` (JSON).
* Parent Board: select a child, "Progress". Mark the child "Playing now" so sessions are kept for them.
* Offline: `python tools/score_run.py run.jsonl --rubric` feeds a `tools/virtual_atoms.py` run to the same scoring (timing only; every real reply is assumed to end with an invitation).
* Tests: `.venv/bin/python tools/test_metrics.py` (rubric boundaries, classification, loops, echo, barge, sessions, privacy, storage, coaching, rollback, review queue).
