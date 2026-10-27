# Plan: Validate, characterize and improve 3 Atom voice agents + Pi 5 brain + human

## Context
Three M5Stack AtomS3R-CAM + Voice Base units (ES8311 shared by mic and speaker, so half-duplex; 2.4 GHz Wi-Fi) are driven by one Pi 5 brain (8GB). Pipeline: Atom audio -> Pi -> Gemma 4 E2B (LiteRT-LM, thinking off) reads the audio directly -> TTS (Kokoro-82M int8 via kokoro-onnx, primary; Piper as fallback) -> PCM over Wi-Fi -> Atom playback. Dashboard on :8080. Audio is RAM-only and deleted after Gemma reads it; embeddings live in `brain/data/`. Human-stops-talking to first agent audio is about 6 s.

Goal: (1) find where the 6 s goes, (2) let the agents talk to each other without a human, (3) have the Mac listen and judge, (4) cut latency and improve turn-taking, without breaking the no-audio-stored rule.

## Model facts
- Gemma 4 E2B loaded file: `~/.litert-lm/models/gemma4-e2b/model.litertlm` (about 2.6 GB, INT4; overridable by `SENTIENT_MODEL`). Source: `litert-community/gemma-4-E2B-it-litert-lm`.
- Backend `auto`: LiteRT-LM if `litert_lm` imports, otherwise llama.cpp (only on ImportError).
- llama.cpp fallback: `offline/gguf/gemma-4-E2B-it-Q4_0.gguf` plus Q8_0 mmproj, served by llama-server on port 8081 (only if no healthy server is already there).
- TTS: Kokoro primary (on unless `SENTIENT_KOKORO=0`); Piper fallback.

## Likely latency suspects (to confirm by measurement, not assume)
No separate ASR stage exists, so the 6 s is probably spread over:
1. End-of-speech detection / hangover on the Atom or Pi
2. Wi-Fi upload of the utterance (2.4 GHz, contention with 3 Atoms)
3. Gemma audio prefill on Pi 5 CPU (audio tokens are the expensive part; scales with utterance length)
4. Gemma decode to a complete reply before TTS starts (if not streamed)
5. Kokoro synth of the full reply before sending (RTF on Pi 5 CPU, shared cores with Gemma)
6. PCM download over Wi-Fi plus Atom playout buffer
7. One Pi serving 3 agents: Gemma and Kokoro compete for the same 4 cores, so overlapping agent turns serialize or slow each other.

## Proposal 1: Instrument the brain (do this first)
Single monotonic clock on the Pi; Atoms report their own timestamps with a sync handshake (NTP-style ping at connect, since ESP32 clocks drift).
Events per turn (`turn_id`, `agent_id`, `t`): `atom_vad_end`, `upload_start/end`, `gemma_prefill_start/end`, `gemma_first_token`, `gemma_done`, `tts_start`, `tts_first_chunk`, `tts_done`, `pcm_send_start/end`, `atom_first_sample_played`.
Write as JSONL (timestamps and sizes only, no audio). Add a waterfall view to the existing :8080 dashboard with p50/p95. Also log Pi CPU %, temp/throttle flag, and Wi-Fi RSSI/retries per Atom.

## Proposal 2: Agent-to-agent harness (no human)
- **Tier A, software-only on the Pi:** a "virtual Atom" client that speaks the same protocol as the firmware, fed by TTS or a prefilled clip instead of a mic, and sinking PCM instead of a speaker. Run 3 virtual Atoms plus a scripted virtual human. Isolates compute latency from Wi-Fi.
- **Tier B, real hardware:** the 3 real Atoms in a room. Each one's speaker is audible to the others' mics, so agent-to-agent conversation can happen acoustically. The brain can also route agent A's TTS PCM straight to agent B's input (skips the air gap) for comparison.
- Scenario files: topic, personas, who starts, injected interruption/silence/overlap, seed. Existing prefilled Atom recordings can serve as the scripted human.
- Privacy: RAM-only by default; any WAV capture for the judge is behind `SENTIENT_DEBUG_RECORD=1`, written to a gitignored temp dir, auto-deleted.

## Proposal 3: Mac as listener and judge
- **Capture:** Mac mic hears the real speakers (realistic, noisy), or the Mac taps the PCM stream from the Pi over the network (clean; recommended for scoring).
- **Objective metrics (no model):** response gap, overlap/double-talk, preempt time on barge-in, talk-time share per agent, half-duplex violations (sending audio while state is `listening`), dead-air rate.
- **Subjective judge:** transcribe on the Mac; a stronger model scores a rubric (coherence, on-topic, distinct personas, repetition, turn-taking naturalness, interruption recovery). Judge sees transcript plus timing summary. Calibrate against about 20 human-rated runs.

## Proposal 4: Latency improvements to A/B (ranked by expected payoff)
1. Stream Gemma tokens into TTS by sentence/clause; start PCM transfer on the first chunk. Likely the biggest win.
2. Stream PCM with a small jitter buffer on the Atom; start playback after about 100-200 ms of audio.
3. Short first utterance / filler: a prefilled acknowledgement clip ("mm", "let me think") plays while the real reply is generated.
4. Shrink prefill: trim silence, cap utterance length, downsample, keep the system prompt short, cache the prefix.
5. CPU budgeting: pin Gemma and Kokoro to separate cores, test thread counts, verify cooling (`vcgencmd get_throttled`).
6. Single-responder arbitration: per human turn, one agent responds; the others only listen.
7. Endpointing: tune VAD hangover; speculative start, cancelled if speech resumes.
8. Wi-Fi: fixed 2.4 GHz channel, Atoms close to the AP, ESP32 power-save off (`WIFI_PS_NONE`), compare TCP vs UDP/WebSocket framing for PCM.
9. Model/quant sweeps: Kokoro int8 vs fp16 (and Piper for comparison), Gemma thinking stays off; measure quality vs RTF.

## Proposal 5: Floor control for 3 half-duplex agents
State machine owned by the brain: `idle`, `human_talking`, `agent_X_talking`, `handoff`. One talker at a time; human barge-in always preempts and stops Atom playback quickly (target under 300 ms, measured as last played sample after a stop command); agents addressed by name or chosen by relevance; non-talking agents stay in listen mode for context. Tests: no deadlock (all listening forever), no pile-up (two talking), correct addressee routing.

## Validation matrix
| Question | Experiment | Metric |
|---|---|---|
| Where is the 6 s? | Proposal 1 over 50+ turns, short vs long utterances | stage p50/p95, correlation with utterance length |
| Compute vs RF? | Tier A vs Tier B, same scenarios | latency delta |
| Does a 2nd/3rd agent slow things? | 1, 2, 3 concurrent virtual agents | time-to-first-audio vs agent count |
| Did a change help? | A/B arms, same seeds | time-to-first-audio, judge score |
| Is the judge trustworthy? | vs human labels | agreement rate |

## Build order
1. Event log, clock sync, dashboard waterfall, CPU/thermal/RSSI logging.
2. Tier A virtual-Atom harness and scripted human.
3. Objective metrics, then Mac PCM-tap capture.
4. Latency arms 1-3 (streaming Gemma -> TTS -> Atom, jitter buffer, filler clip).
5. CPU pinning, Wi-Fi tuning, arbitration.
6. Judge model plus calibration.
7. Floor-control state machine tests, then Tier B acoustic runs.

## Verification
- Waterfall stage times sum to within about 100 ms of end-to-end (sync-corrected) latency.
- Same seeds re-run after each change: time-to-first-audio drops without a judge-score drop.
- Zero half-duplex violations; no audio files left on disk after a default (non-debug) run.
- Goal: first agent audio under about 2-3 s after the human stops, to refine once the waterfall exists.

## Open items
- **Brain code location:** not yet provided. Needed for Proposal 1. Either a path on this Mac, or SSH access to the Pi (the brain runs there, so its code and model file are probably on the Pi, not this Mac).
