# Benchmarks: Jetson Orin Nano Super vs Pi 5, and speaker calibration

Measured 2026-11-03 unless stated. Raw output is in `docs/bench/`.

## Jetson vs Pi 5

The Pi 5 was powered off (since Oct 30) during this run, so the **Pi column is the earlier live measurements (Oct 25-26)**, not a same-day re-run.
Tools: `tools/llm_bench.py` (Gemma through the brain's own backends, brain system prompt, 10 prompts, first dropped), `tools/voice_bench.py`
(the brain's real voice path per toy), `tools/tts_bench/bench_all.py`.

| | Pi 5 (8 GB, CPU) | Jetson Orin Nano Super (MAXN_SUPER) |
|---|---|---|
| Gemma 4 E2B LiteRT-LM, first token | ~1.5 s (CPU) | **0.23 s (GPU)**, 1.13 s (CPU) |
| Gemma, first complete line | ~3.1-3.5 s (prefill 1.8 + decode 1.3-1.7) | **0.76 s (GPU)**, 2.50 s (CPU) |
| Gemma, whole reply | 9-10 s (pinned cores) | **2.4 s (GPU)**, 5.4 s (CPU) |
| GPU backend | ~15x slower than CPU (Vulkan) | works, no code change; 3.3x faster than CPU on first line |
| Kitten TTS (nano fp32) | x2.6-3.3 real time | x3.0-3.5 (CPU, core 3): same class of speed |
| Brain voice path, Piper (Sage) | x8-10 | x7.4-12 |
| Brain voice path, Kitten (Dyno, Penny) | 2.3 s of speech in 0.9 s | 2.4 s in 0.40 s, 5.7 s in 0.91 s (x6.0-6.3) |
| Kokoro int8 | x1.1 | not installed on the Jetson (approved mix does not use it) |
| Event turn to first audible sample (toy-side timestamps) | ~4 s | **1.06-1.09 s** |
| Spoken-question turn, child stops to filler / real reply | 0.7 s / ~6.8 s (p50) | not yet measured (needs live speech) |

Outcome: the win is the GPU. Gemma first line is 4x faster than the Pi and the whole reply 4x faster. Voice synthesis is only about 2x faster, so TTS is now the
largest hop. One cold-start outlier appears in both LiteRT runs (prompt 8: 11.6 s CPU, 1.2 s GPU) when the conversation resets; the brain's `warm()` hides it.
Not compared: vision (kept off, `SENTIENT_VISION=never`) and power draw.

## Speaker calibration against the Mac microphone

The Oct 28-29 speaker EQ used the other Atoms' mics, so the speaker and mic responses could not be separated. This run records each Atom with the Mac's own mic
(`tools/mac_sweep.py`, `tools/mac_sweep_solve.py`, `tools/play_wav_atom.py`): a 6 s log sweep at the low and high levels (11.5 dB apart), toy about 10 cm from the mic.

| Toy | Level step heard at the Mac mic for an 11.5 dB drive step | Verdict |
|---|---|---|
| Dyno | 11.8 dB | speaker is linear |
| Penny | 12.5 dB | speaker is linear |
| Sage | not measurable: sweep not found above room noise even at volume 100 | needs a repeat with Sage right next to the mic |

Findings:
- The compression seen earlier (11.5 dB more drive gave only 6-9 dB more heard) was in the **Atom microphones**, not the speakers. Mic-side compression made the old speaker EQ unreliable.
- Mac-mic response and Atom-mic response agree within ~3 dB between 500 Hz and 5 kHz. They disagree below 500 Hz (the Atom mics lose bass: Mac sees Dyno 30 dB higher at 160 Hz) and above 6 kHz.
- The speaker EQ stays **off** (`SENTIENT_DSP_EQ=0`). The old EQ curves were fitted to Atom-mic data, so they would boost lows the speakers cannot reproduce. A new EQ should be fitted to the Mac-mic curves in `docs/bench/speaker_mac_mic_2026-11-03.json` once Sage is measured.
- Volumes were set to 100 for the test and restored (Dyno 65, Sage 50, Penny 75).
