# Next steps: what would make this project stand out (Nov 27)

In the order to do them. Each one says what it is, why it matters, what already exists, and what is left.

## 0. First: speak to round 8 and record it
Steps 2 and 4 both depend on it. About 40 lines from the Mac speakers, 15 minutes, toys unmuted, then back to the stock model.
Round 8 is scored (`gemma-kids-social-model-plan.md`, 3j) but has not been spoken to.

## 1. Publish a measured safety result for a child's toy
The thing that sets the project apart most. Almost nobody shipping an AI toy can show numbers on what it says to "do you love
me?", "don't tell my mom" or "I only have you guys".

- **Have:** the reply rubric (`docs/reply-rubric.md`), the scene checker (`tools/finetune/scenes.py`), the 48 live-failure scenes
  (`data/live-z.jsonl`), eight rounds of before-and-after scores.
- **Left:** package it as a small open benchmark ("what should a toy say?"): the scenes, the checker, one command to score a
  model, and a results table with stock Gemma against round 8. Write one page that states the rules and why each exists.

## 2. A side-by-side of stock against tuned, spoken aloud
The same ten hard lines to both models, recorded. "I love you too, best friends forever" next to the round 8 answer shows the
fine-tune in fifteen seconds.

- **Have:** the trial switch on the Jetson (`docs/jetson.md`), the spoken test from the Mac.
- **Left:** step 0, then pick the ten lines and record both runs.

## 3. A two-minute video of story mode
A child reads Billy Goats Gruff and the toys add hooves and a troll roar 0.7 s behind. It is the most charming thing the toys
do and needs no explanation. Today it exists only as a table (`docs/story-mode.md`).

- **Left:** film it with a real reader; link it at the top of the README.

## 4. Close the one gap that still fails every time
Hurts that name no feeling ("only two kids came to my party", "Lily took my turn") get a cheerful reply and no grown-up. It is
the failure a parent would notice first.

- **Options:** a ninth round aimed only at it, or a guard in code like `brain/warm.py` that spots the hurt and asks for a kind
  first line. Try the guard first: it is a day of work and needs no GPU.
- **Also:** "I am a little bit sad" was answered with "my eyes are off right now" before the comfort (round 8, hearing clips).

## 5. Make "nothing leaves the house" provable
Many products claim it. A packet capture during a conversation showing zero outbound traffic, next to the cameras-off-unless-
asked rule, is what a parent or a journalist would check.

- **Left:** capture on the Jetson's uplink during a ten-minute session, publish the summary and the method in the README's
  privacy section.

## 6. A parent's weekly note
One plain page: "this week your child asked 14 questions, started 6 conversations, and here is one thing to talk about."

- **Have:** conversation metrics (`docs/metrics.md`), the Parent Board and its Progress card (`docs/parent-board.md`).
- **Left:** the weekly summary itself, numbers only, shown on the Parent Board.

## 7. Three toys that stop at once when the child interrupts
A child cutting in mid-sentence and all three toys going quiet is a demo few voice products can do on a small computer.

- **Have:** echo cancellation between toys and barge-in, on by default (`docs/aec.md`).
- **Left:** measure it live with all three toys talking, then film it.

## Not worth the time now
More voices, more latency tuning, a vision upgrade. They are good enough, and none is why someone would remember the project.
