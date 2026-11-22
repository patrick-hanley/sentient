# Plan: A Kid-Social Interaction Model on Gemma

**Project:** sentient — plush toys (camera + mic) that talk with a child and with each other; the brain runs locally on a Jetson Orin Nano.
**Base model:** Gemma 4 E2B instruct (`gemma-4-E2B-it`, Apache 2.0). Fine-tune it with a LoRA; do not train from scratch.
**Target:** one younger child (design centre about 4–8) plus up to three toys, spoken, multi-party, short turns. An older child (11) should find the toys young but not babyish.
**Status:** revised Nov 19, 2026 after review. Step zero (§3) is done except the ledger baseline; pilot round 1 (§3b) and round 2 (§3c) are trained and scored. Round 2, merged into the model, passes the rule check; not yet tried live.

## 0. What changed in this revision

1. **Step zero comes first** (§3): prove on the Jetson that a tuned model can be loaded and still hears, before any data is generated.
2. **The deployment runtime changes to llama.cpp** (§2). The `.litertlm` file the toys run today cannot take a LoRA.
3. **Training data is rendered through the brain's real prompt builder** (§4.3), not a separate `CHILD` / `TOY:` JSON chat format.
4. **There is no speech-to-text step.** Gemma hears the child's audio directly. The old "ASR is the weak link" section is replaced by a hearing regression check (§6).
5. **Volume cut from 60–120K scenes to 2–5K**, grown only while scores still climb.
6. **Evaluation reuses the repo's grading ledger** (`docs/grades/`, `tools/grade_toys.py`) instead of a new suite.
7. **A pass/fail target** the prompt-only system cannot reach (§5).
8. **Every score is taken on the 4-bit file that ships**, not the full-precision model.
9. **Distillation stage dropped** (no smaller Gemma 4 exists). DPO is deferred until SFT leaves a named gap.
10. Facts corrected: no audio recordings exist (audio is RAM-only; the source is text conversation logs); toy voices are Kitten TTS; Sage is a jack-o'-lantern; memory wording matches the Parent Board.

## 1. Design principles

1. **Fine-tune behaviour, not knowledge.** The gap is the social register for kids: short turns, playfulness, turn-taking, emotion reading, pretend play, safe redirection.
2. **Multi-party from day one.** The model writes several toys' lines in one reply and must keep the child's words apart from the toys'.
3. **Safety is trained and also guarded.** Redirection is in the training data, and the runtime guards stay (§7).
4. **On-device stays on-device.** No child audio, transcript or profile leaves the house for training. Only synthetic scenes go to a rented GPU.
5. **Train on what the brain sends.** An example the brain would never produce teaches nothing useful.
6. **Age fit.** Design centre 4–8. The repo's `AUDIENCE` line and `docs/curriculum.md` still say 2nd–5th grade; aligning them is an open decision (§10).

## 2. Runtime and deployment path

Measured on the Jetson, Nov 19 (`tools/finetune/step0_runtime.py`; ten synthetic spoken clips, the real system prompt):

| Runtime | Takes a fine-tune? | Heard the clips | First token | Full reply |
|---|---|---|---|---|
| LiteRT-LM `.litertlm` (today) | No: the shipped decoder has no LoRA inputs, and the public converter cannot yet export the audio encoder | 10/10 | 2.2 s cold (0.24 s warm, measured Oct 30) | 4.9 s cold (2.3 s warm) |
| llama.cpp, GGUF Q4_0 + `mmproj` with the audio encoder, GPU | Yes: merged GGUF or a LoRA adapter, stock tools | 10/10 | 0.22 s | 2.35 s |

So the tuned model ships as GGUF on llama.cpp. LiteRT-LM stays the live runtime until a tuned model beats it on the gates in §5.

Work this adds: the brain's `LlamaCppBackend` currently transcribes with Whisper and sends text; it needs an audio-in mode (send the clip as `input_audio`), early-stop handling, and a run through the full test suite. llama.cpp marks audio input as experimental, so the hearing check in §6 covers it too.

Why not LiteRT: community exports of tuned E2B show quality regressions and crashes (google-ai-edge/litert-torch issues #998 and #1013), and the audio encoder cannot be exported with public tools yet. Re-check that route later; it is not needed now.

## 3. Step zero: prove the path (before any data work)

- [x] llama.cpp on the Jetson hears audio and matches today's speed (table above).
- [x] The `.litertlm` route ruled out for now (no LoRA inputs in the file).
- [x] An untrained, random LoRA on the language layers (`tools/finetune/make_random_lora.py`) converts with `convert_lora_to_gguf.py` (25 MB) and loads with `llama-server --lora`. Hearing stays 10/10. First token 0.29 s against 0.22 s without the adapter: a runtime adapter costs roughly 30% per token, so the shipped model should be merged into the GGUF.
- [x] Training rule found on the way: layers 15–34 of E2B share the key/value cache, so the GGUF has no `attn_k` / `attn_v` there. A LoRA must not target `k_proj` / `v_proj` in those layers or llama.cpp refuses the adapter.
- [x] Audio-in mode for the brain's `LlamaCppBackend` (`SENTIENT_LLAMA_AUDIO=1`, `SENTIENT_LLAMA_LORA`, `SENTIENT_LLAMA_SERVER`); `tools/finetune/backend_check.py` passes on the Jetson (hears, survives an early stop, answers next).
- [ ] Baseline ledger run (tune and held) with the brain on llama.cpp; it must match the LiteRT baseline within noise.
- [ ] Merge route checked once a real adapter exists (merge in PEFT, `convert_hf_to_gguf.py`, quantize to Q4_0).

Exit: a deliberately changed model runs in the brain on the Jetson, hears, sees, and is as fast as today. If this fails, stop and rethink.

## 3b. Pilot round 1 (Nov 19): 200 scenes, one LoRA

200 hand-checked synthetic scenes (`tools/finetune/data/pilot-[a-d].jsonl`, 1,044 turns), 180 trained, 20 held out. LoRA r=16 on
all language-layer projections, lr 2e-4, 3 epochs, 36 minutes on a Colab T4; held-out loss 2.77 -> 1.15. Scored on the Jetson
through llama.cpp (Q4_0 GGUF + adapter) with `tools/finetune/eval_rules.py`: 104 held-out turns, one sample each at
temperature 0.8, so differences of a few points are noise.

| Model | Turns with every rule kept | HEARD line exact | Words per line | Long lines | Over two sentences | Over two toys | Bad sound tag | Wrong facts |
|---|---|---|---|---|---|---|---|---|
| Untuned | 48.1% | 86.5% | 14.3 | 19 | 36 | 20 | 4 | 0 |
| Adapter at full strength | 50.0% | 78.8% | 10.9 | 7 | 6 | 25 | 14 | 3 |
| Adapter at half strength | **61.5%** | **91.3%** | 12.4 | 12 | 13 | 13 | 5 | 1 |

Reading: at full strength the adapter learned the short style but over-fitted: some garbled sentences, braces and brackets
mixed up on sound tags, and hearing fell (spoken clips 91% word match against 100%, one clip answered instead of
transcribed). At half strength it is coherent and beats the untuned model. So the training was too strong for 180 scenes,
not wrong in kind. This adapter does not ship.

Round 2: train more gently (r=8, lr 1e-4, 2 epochs, early stop on held-out loss), 5x the scenes, more named-toy and
sound-tag turns, three samples per turn in the eval to cut noise, and a larger held-out set. Gate: section 5.

## 3c. Round 2 (Nov 20): 1,000 scenes, merged into the model

Training: 900 scenes train / 100 held out, rank 8, learning rate 1e-4, 2 epochs, 121 minutes on a Colab T4; held-out loss 2.70 -> 1.05.
Scored on the Jetson: 40 held-out scenes, 3 replies per turn, 594 replies, same seeds for every model.

| Model on the Jetson | Replies with no rule broken | Child's words exact | Words per line | Median reply |
|---|---|---|---|---|
| Untuned Q4_0 | 41.1% | 94.8% | 14.7 | |
| Round-1 adapter at half strength, loaded at runtime | 55.7% | 95.5% | 11.7 | |
| Round-2 adapter, loaded at runtime | 48.3% | 67.0% | | |
| **Round 2 merged, then quantized** (`/data/ft/toys-round2-Q4_0.gguf`, 3.36 GB) | **81.6%** | 90.4% | 10.6 | 1.03 s |

Spoken-clip check on the merged model (10 Kokoro clips, audio in): 9 of 10 heard, 88% word match (untuned llama.cpp: 10 of 10), first
token 0.22 s, full reply 1.11 s. The one miss wrote `HEARD BY:` instead of `HEARD:`.

**Lesson: never load the adapter at runtime on the 4-bit file.** The adapter is trained against Google's original weights; the
Jetson's Q4_0 file is those weights rounded, and the adapter does not fit the rounded ones (dropped HEARD lines, garbled words). The
same adapter is coherent on the full-precision model. The route that works: merge the adapter into the full-precision weights
(`tools/finetune/merge_lora.py`, tensor by tensor, on the Jetson), convert to GGUF f16, quantize to Q4_0, ship that one file with the
unchanged mmproj. It also removes the ~30% per-token cost of a runtime adapter. Round 1's "works only at half strength" was the same flaw.

Still wrong in the merged model (per 594 replies): more than two sentences 34, wrong toy first 20, line too long 17, other toys
answering a named toy 17, talking after stop 9, feelings without a grown-up 7, wrong fact 5. Seen in the clips: "Dyno" heard as
"Dino" and Penny answering for him; a wrong spelling answer. The child's-words-exact score dropped 4 points and needs a real-mic check.

Not done yet: the ledger baseline on llama.cpp, a re-scored round 1 merged the same way.

## 3d. Live trial of round 2 (Nov 20, about 25 minutes, all three toys) and what round 3 must fix

The merged round-2 model ran in the brain on llama.cpp with audio in. It talked, kept lines short and heard well, but the trial was
ended and the brain put back on LiteRT-LM. Found, in order of weight:

1. **Silent turns.** After plain remarks ("We are both eleven.", "You are a penguin.") the model wrote the HEARD line and no toy
   line; once one empty reply was in the history the next turns were empty too (3 of 17 turns in one stretch). The stop scenes
   taught "say nothing" and it spread. The scoring missed it: 2 of 594 replies.
2. **No LOOK.** Camera and I spy turns were left out of rounds 1-2, so the model stopped answering the one word LOOK and made up
   what it "saw" ("something orange" with no picture taken).
3. **History shape.** In the brain an earlier spoken turn is stored without the child's words (they are only in the reply's HEARD
   line); the training scenes always had the words in the user text.
4. Brain-side faults of the llama.cpp backend, fixed in `brain/llm.py`: the 4096-token window filled after about 15 turns and every
   request failed with HTTP 400 (now 8192, and the older half of the history is dropped on a 400); empty replies are no longer kept
   in the history.
5. **Picture lists are unreliable on llama.cpp with either model** (I spy list prompt on ten labelled photos: tuned 3 of 10, untuned
   2 of 10, both inventing objects). Open: check the test against the brain's real list call, and LiteRT-LM on the same photos.
6. Memory: brain + llama-server left about 0.3 to 1.1 GB free on the 8 GB Jetson. Too tight to ship as is.
7. A brain restart locks the Parent Board, so taught faces are unknown until the PIN is entered again.

**Round 3** (`tools/finetune/WRITING.md`, "Round 3"): 200 new scenes (`data/round3-[m-p].jsonl`) with look turns (reply HEARD + LOOK),
camera-failed turns, I spy turns held to the brain's own referee, the three camera modes, and plain remarks that always get an
answer; `scenes.py render --audio-history 0.5` writes half the scenes with a brain-shaped history; `eval_rules.py` scores the new
turn kinds and has `--live-history`.

## 3e. Round 3 (Nov 21): 200 camera / I spy scenes added, continued from round 2

Trained on Colab (T4, 72.6 min, 2 epochs, `--init` round-2 adapter, 496 scenes); held-out loss 1.037 -> 1.008. Merged, converted and
quantized on the Jetson (`/data/ft/toys-round3-Q4_0.gguf`, 3.36 GB). Rule-clean replies, 3 samples per turn:

| Scenes | Untuned | Round 2 | Round 3 |
|---|---|---|---|
| Old 40 held-out (594 replies) | 41.1% | 81.6% | 85.2% |
| New 24 held-out, camera / I spy (330 replies) | 45.2% | 80.9% | 88.5% |
| New 24, earlier turns as live audio history | 39.4% | 80.9% | 88.8% |
| Look requests answered with LOOK (30 replies) | 16.7% | 6.7% | 63.3% (56.7% live history) |

Hearing check: 10/10 clips, 100% word match (round 2: 88%), first token 0.22 s, full reply 1.18 s. HEARD exact 95.5% on the old 40.
Not shown by these numbers: stop turns still get a toy line every time on all three models (9/9 and 3/3; the brain's code handles stop);
I spy turns score 100% on every model including untuned (12 replies, the test does not discriminate); the silent turns of the live
trial do not appear in this test for round 2 either, so only a live trial can show whether they are gone.

## 4. Data plan

### 4.1 Sources

| Source | Use | Notes |
|---|---|---|
| **Synthetic scenes (teacher-generated)** | Bulk of SFT | §4.2. Synthetic only, so it may go to a rented GPU. |
| **Our own conversation logs** (text, git-ignored `docs/private/convlogs`) | Held-out eval first; later a small, de-identified training share | A child's words. Names stripped. Never uploaded for training. |
| **Graded runs from the ledger** | Good/bad reply pairs for a later DPO stage | Already scored by `tools/textgrade.py`. |
| **Kids Multilingual Benchmark** (Hugging Face, CC-BY-4.0, 2,312 items) | Evaluation only | English subset as the safety scorecard. |
| **ChildEval** (GitHub) | Maybe, for persona following | Licence unclear (paper is CC BY-NC-SA); data was translated from Chinese. Do not use until the licence is confirmed. |
| **CHILDES**, **TinyStories** | Reference for vocabulary level only | CHILDES is research-use; not used as training text. |

### 4.2 Synthetic pipeline

1. **Scenario cards (about 40):** greetings, pretend play, co-created stories, show-and-tell and I spy, feelings, toy-toy disagreement and making up, curiosity questions, jokes, games with rules, bedtime, goodbyes, "stop" and interruptions, "who am I?", and safety redirects (strangers, personal info, scary topics, secrets from parents).
2. **Teacher generation:** a large model plays the child and all toys from a scenario card plus the persona cards in `brain/config.py` (`TOYS`). Scenes of 6–15 turns.
3. **Filters, in order:** the brain's own guards (`brain/factcheck.py`, line caps, safe-deflect rules) → reading level → persona consistency → near-duplicate removal → a judge model → human spot check of 5%.
4. **Volume:** start with 2–5K scenes. Expect to discard 30–50%.

### 4.3 Format

Scenes are stored as plain JSONL (speaker, text, scenario, emotion). Training examples are **rendered** from them:
- the system prompt from `brain.director.system_prompt()`;
- each user turn built the way the director builds it: `[TOYS HERE]`, `[SCENE]`, `[SPEAKER]`, `[HEARD BY]`, then the child's words as text (at runtime they arrive as audio);
- each target reply in the brain's output format: a `HEARD:` line, then `DYNO:` / `SAGE:` / `PENNY:` lines with sound tags such as `{dino_growl}`.

A share of examples uses a shortened system prompt, so the tuned model can later run with fewer prompt tokens (§5).

## 5. Training stages and gates

**Stage 0 — Baseline.** The current ledger scores are the baseline (tune 16.59, held 15.58 after the prompt work). Re-run both sets on llama.cpp with the untuned GGUF.

**Stage 1 — SFT.** LoRA r=8–16 on the language layers only (`finetune_vision_layers=False`; audio tower untouched), 2–3 epochs. Needs one GPU with about 16 GB (a Colab T4 works per Unsloth's guide); the Intel Mac and the Jetson cannot train this.

**Gate to ship Stage 1** — all on the Q4 file, on the Jetson:
- held-set composite at least +0.5 over baseline with every ledger guard clean (`grade_toys.decide`), **or** equal score with a system prompt at least 40% shorter and a faster first line;
- hearing check 100% on the clip set (§6), vision check unchanged (`docs/vision.md` object set);
- safety slices no worse than baseline; zero wrong facts spoken.

If it beats the prompt-only system on neither score nor speed, stop.

**Stage 2 — DPO (only if needed).** Pairs from ledger-graded replies and Stage-1 outputs, for a named gap (for example repeated lines).

**Stage 3 — Safety hardening.** Adversarial scenes: secrets, personal info, scary content, "do you love me", self-harm signals, stranger role-play. Redirect to play or a trusted adult. Self-harm and abuse disclosure stay scripted, never generated.

## 6. Evaluation

| Layer | Instrument | What it proves |
|---|---|---|
| Social quality | The ledger: `tools/grade_toys.py` tune/held sets, keep/revert rule | Better company, measured the same way as every earlier change |
| Child-led turns | `tools/child_check.py`, review loop on conversation logs | Answers the child first, stops on "stop" |
| Hearing | `tools/finetune/step0_runtime.py`: same clips, old vs new model | Text-only tuning did not damage audio understanding |
| Vision | The 36-object set in `docs/vision.md` | Object naming unchanged |
| Safety | Kids Multilingual Benchmark (English) + Stage-3 set | Redirection, privacy, emotional support |
| On-device | First token, first line, full reply, memory on the Jetson | It runs in the toy brain at today's speed or better |

## 7. Runtime guardrails (already built, kept)

The fact guard, line caps, safe-deflect lines, "stop" handling and scripted responses stay in front of the tuned model. Memory: the toys know only what a parent entered on the Parent Board (encrypted, parent-deletable) plus the faces and voices a parent enrolled; nothing else about identity is kept.

## 8. Compliance checklist

- [x] Gemma 4 licence: Apache 2.0 (keep notices and attribution).
- [ ] Teacher-model terms: confirm generated scenes may be used to train a model.
- [ ] ChildEval licence, before any use.
- [ ] Conversation logs: household only; other children's words need their parents' consent before training use.
- [ ] COPPA story: on-device, no accounts; training uses synthetic data off-device.

## 9. Milestones

| Phase | Deliverable | Needs |
|---|---|---|
| 0 | Step zero finished (§3) | Jetson only; toys not needed |
| 1 | Scenario cards, renderer, filters, 200-scene pilot, baseline on llama.cpp | Teacher model |
| 2 | 2–5K filtered scenes | Teacher model |
| 3 | Stage-1 LoRA, converted, gated on the Jetson | Rented GPU |
| 4 | Live trial with the toys, then safety hardening | Toys online |

The toys are needed only in phase 4. Everything before it runs on the Jetson, the Mac and a rented GPU.

## 10. Open decisions for Patrick

1. **Where to train:** Colab or another rented GPU (a few dollars per run at this size).
2. **Teacher model** for the synthetic scenes.
3. **Age band in the repo:** move `AUDIENCE` and the curriculum from 2nd–5th grade to 4–8, or keep both.
4. **Share of conversation logs** used for training versus held-out eval (recommended: eval only at first).
