# Gemma conversation settings: what the ledger shows and what to change

**Status (Nov 14, night):** #1 (one topic per chat) and #2 (line jobs, fixed by persona) are graded keeps and ON by default
(`SENTIENT_SCENE_TOPIC=1`, `SENTIENT_BEATS=1`). Tune 13.21 -> 16.59/20, follow-up 1.38 -> 2.48, round 3 / round 1 0.73 -> 0.88;
held 13.82 -> 15.58 against a baseline on the same code. #3 (quote the last lines) gave no gain and stays off. Details: docs/grades/ledger.md.
The grading rules were changed with the user: padding limit 1.3x, plus a rule that the last round must hold up against the first.

Source: every run in `docs/grades/ledger/` (baseline-tune, baseline-held, v2 to v7; synthetic scenarios only, real Gemma 4 E2B
on the Jetson). Goal: toy-to-toy talk that stays on one subject, answers what was just asked, and makes sense. Nothing here
is applied yet; each item names the place in the code to change.

## What goes wrong

**1. The conversation resets its subject every round.** A scene is three rounds (three Gemma turns). Round 1 is usually
fine; rounds 2 and 3 jump to unrelated lesson topics.

| run | line score round 1 / 2 / 3 (0-4) | full-marks lines round 1 / 2 / 3 |
|---|---|---|
| baseline-tune | 3.42 / 2.81 / 2.49 | 66% / 32% / 18% |
| baseline-held | 3.37 / 3.03 / 2.58 | 62% / 44% / 24% |
| v7 (best clean variant) | 3.44 / 2.86 / 2.67 | 64% / 39% / 28% |
| v3 (every line a question) | 3.75 / 3.78 / 3.67 | 82% / 83% / 73% |

Example (baseline-held, topic "ocean and beaches"), round 2:
> **S** The golden poppy is a beautiful thing in California. **P** Washing machines are like magic!

Example ("slow and fast changes"), round 2: **P** "R-controlled vowels are like silly, bouncy balls!"
Even v3, the most on-topic run, drifts by round 3: a rhyming scene ends on settlers, division and redwoods.

**2. Toys don't answer each other.** Questions are asked and dropped. "What is the capital city?" (Dyno) gets "I like the
letter C, it sounds like a cat!" and is never answered. Most lines are side-by-side statements, not replies.

**3. The variants that fixed the flow did it by making every line a question.** In v3, 170 of 187 lines end in "?"
("Penny, what about division?"). Scores went up, but that's quizzing, not conversation, and the lines got long.

**4. Persona tics replace content.**
- Dyno starts 56 of 74 lines (baseline-tune) with a sound tag, nearly always `{dino_growl}`, and says "bouncy" about
  anything ("Sally ride is super bouncy!").
- Penny makes a "like a ..." comparison in about half her lines.
- About a quarter of Sage's lines are a generic "X helps us ... nicely".

**5. Wrong or nonsense facts.**
- "Parallelograms have four equal sides."
- "If we have 100 and take away 10, we have zero!"
- "Six, eleven, twelve!" (counting by fives)
- "Sally ride is a fun shape! Does it have a special number?"
- "Tongva sounds like a big, bouncy word!"

**6. Heavy subjects show up as idle chatter.** "slavery in the colonies" got "Slavery sounds like a long story!" from Dyno.

## Why (in the code)

| cause | where |
|---|---|
| Every turn prepends a NEW rotating `[GRADE TOPICS]` block (3 different curriculum items, rotation never repeats). Each continuation round therefore offers three fresh unrelated topics, and the system prompt says EVERY line must be about the topics. This is the main cause of item 1. | `brain/director.py` `_turn` (`topics = self._grade_topics()`), `brain/curriculum.py` `topics_block`, `BLOCK_ITEMS = 3` |
| The system prompt asks for "One to four toy lines; usually let all three join in" with "Toys react to the line before" as one clause among ~20 rules. A 2B model writes three or four parallel statements. | `brain/director.py` `system_prompt()` |
| Banter seeds are lowercased curriculum titles with no content ("sally ride", "tongva of the los angeles area"), so the model doesn't know what they are and guesses from the words. | `brain/curriculum.py` `banter_seed` (`.lower()`), `_idle_event_base` |
| Personas name the tics directly: Dyno is "bouncy" and "sometimes growls with the {dino_growl} sound"; the sound-effect rule offers a tag per line. | `brain/config.py` `TOYS[...]["persona"]`, sound-tag rule in `system_prompt()` |
| No sampler is set. The model file carries no defaults (temperature 0.0, top_p 0.0, top_k unset) and `create_conversation` gets no `sampler_config`, so the toys run on the LiteRT runtime's built-in sampler, whatever that is. The llama.cpp path uses temperature 0.8. No repetition penalty anywhere. | `brain/llm.py` `new_conversation` / `_stream` |
| The conversation is reset after 8 turns (`RESET_AFTER_TURNS`), and on a notes change, with nothing carried over, so a live conversation can lose its subject mid-chat. | `brain/config.py`, `brain/llm.py` |

## Suggested settings

Ranked by expected effect. The first three are the ones that matter for "doesn't flow / doesn't make sense".

| # | setting | now | suggested | why |
|---|---|---|---|---|
| 1 | Topic during banter | new `[GRADE TOPICS]` (3 items) every turn | **one topic per scene**: pick it once when banter starts; continuation turns send `[TOPIC] <same topic>` and **no** `[GRADE TOPICS]` block. Rotate only when a new scene starts or the child changes the subject. | Removes the round-2/3 jumps (item 1). |
| 2 | Turn shape | 1-4 lines, all three toys, "react to the line before" | **Explicit beats per line** in `[ORDER]`, e.g. `DYNO asks one question about the topic. SAGE answers that exact question with one true fact. PENNY adds a playful twist on Sage's fact.` Next round: rotate the beats (ask, answer, react) so the hand-off is built in, without making every line a question. | Makes lines answer each other (item 2) and keeps questions to about 1 in 3 lines (item 3). |
| 3 | What the model sees of the last round | only its own conversation memory | Add `[JUST SAID] Penny: "<last line>"` (the last one or two lines) to each continuation event, and "the first line must answer or build on it". | A 2B model follows a quoted line far better than a memory 3 turns back. |
| 4 | Lines per banter turn | up to `MAX_LINES = 4` | **2 or 3** for banter (two toys trading, the third joins every other round); keep 4 for answering the child. | Fewer parallel lines, more back-and-forth. |
| 5 | Banter seed text | lowercased title only | Original case **plus the curriculum item's one-line description or one key fact**, e.g. `Sally Ride (the first American woman in space)`. | Stops "Sally ride is a fun shape" (item 5). |
| 6 | Idle banter topic list | every curriculum item | Skip heavy history/social items for **idle** banter (slavery, wars, disasters, mistreatment); they stay available when the child or a parent note brings them up. | Item 6. |
| 7 | Sampler (LiteRT) | none set (runtime default) | `SamplerConfig(temperature=0.7, top_p=0.9, top_k=40)` for banter; **0.3** for turns answering the child's school question (facts, math, spelling). Make it a config knob (`SENTIENT_LLM_TEMP`). | Lower temperature for facts reduces errors; moderate for banter keeps variety. |
| 8 | Repetition (LiteRT) | none | `RepetitionPenaltyConfig(presence_penalty=0.3, window_size=256)` per message; leave `NoRepeatNgramConfig` off (it would ban the toys' names and the topic word). | Fewer repeated openings ("Five, ten, fifteen!" twice; repeats guard 4-7 in v5). Verify it doesn't hurt topic words. |
| 9 | Personas | "curious and bouncy ... sometimes growls with {dino_growl}"; Penny "playful comparisons" | Dyno: "curious, easily amazed, asks short questions" (drop "bouncy"). Sound tags: "**at most one sound tag in a whole reply**, only when it fits a story or an animal". Penny: "wordplay and jokes; a comparison at most once a scene". Sage: "gives one specific fact, a number or a name; never 'X helps us'". | Item 4: the tics come straight from the persona wording. |
| 10 | System-prompt topic rule | "EVERY line must be about those topics" + broad TOPICS list | "Stay on the **[TOPIC]** of this scene. Only change it if the child does." | The broad rule plus 3 fresh items per turn invites jumps. |
| 11 | Fact check line | "If unsure, say so" (one clause) | Add to Sage's beat: "If a number or fact is not certain, Sage says 'Let's check that together' instead of guessing." Keep math to small numbers in banter. | Item 5; a 2B model guesses confidently. |
| 12 | Memory across resets | `RESET_AFTER_TURNS = 8`, nothing carried over | Keep 8 (latency), but prefill the fresh conversation with `[TOPIC]` and the last two lines. | Live chat keeps its subject across a reset. |
| 13 | Model size (optional) | Gemma 4 E2B | Try **Gemma 4 E4B** for banter only if the Jetson has the memory and latency allows; measure first. | More coherent multi-speaker turns. Costs time to first audio. |

## Prompt text to try (for #1-#3)

Continuation event, replacing the one in `tools/grade_toys.py` and the live idle path:

```
[TOPIC] Sally Ride (the first American woman in space)
[JUST SAID] Penny: "Sally Ride flew on the space shuttle!"
[ORDER] SAGE answers or builds on Penny's line with one true fact. DYNO asks one short question about it. PENNY answers Dyno's question playfully.
One or two short sentences each, under 16 words. Stay on the topic. No new topics.
```

## How to test

1. Use the existing harness: `tools/grade_remote.sh` with the tune set; compare to `baseline-tune` with the same guards
   (long lines, run-on, repeats, padding at most 1.2x words/scene).
2. Add two numbers to `tools/textgrade.py`:
   - **Round 3 / round 1 score ratio.** Target ≥ 0.9; baseline is 0.73.
   - **Answered-question rate.** Share of toy questions whose next line contains a content word from the question, or a
     number/name answering it.
3. Keep the questions-per-line rate under about 0.4, so a v3-style "everything is a question" result doesn't score as a win.
4. Change one row at a time, in the order above (#1 alone first: it should move round 2/3 the most), and record each in the
   ledger as before.
