# Experiments log

Everything tried so far on the toys' latency and speech, with the outcome, so nobody repeats it.
Numbers are from the Pi 5 (4 cores, 8 GB) unless noted. Measurement detail: `LATENCY.md`. Tools: `tools/`.

## Where the ~6.8 s goes (human stops talking -> reply audible on the Atom)

Filler audible ~0.7 s. Real reply, p50: Gemma first token ~2.7 s, first sentence ~1.3 s, Kokoro render ~2.7 s, upload ~0.1 s.

| Arm (live Pi, Mac `say` near the toys) | p50 | p95 |
|---|---|---|
| Baseline | 7.4 s | 18.0 s |
| + conversation warm-up | 6.9 s | 10.6 s |
| + LLM cores 0-2 / TTS core 3 | 7.0 s | 8.1 s |
| + 3-word first clause | 6.8 s | 8.7 s |

## What helped (kept)
- **Background warm-up of the next conversation** (`LiteRTBackend.warm()`): a reset every 8th turn and the first turn after restart cost ~10 s. p95 17.9 s -> ~8.7 s.
- **Core pinning** (systemd drop-in `pin.conf`, `SENTIENT_LLM_CORES=0,1,2`, `SENTIENT_TTS_CORES=3`): full reply 16 s -> 9-10 s. Does not change first audio.
- **SENTIENT_VISION=never** on the Pi: replies 24-34 s -> ~6 s (camera JPEG to Gemma costs 20+ s on CPU).
- **Adaptive VAD threshold** (ENERGY_FLOOR 100 x NOISE_MULT 4), **fillers**, **answer-first reply format**, **speak each sentence/clause as soon as it completes**.
- **Kokoro int8 + ORT_ENABLE_ALL** (x1.10 real time; fp32 x0.84).
- **Planned speaking order** (`brain/choreo.py`): 1,2,1,3 style, brain-planned for banter, free order for child turns. Gemma follows `[ORDER]` exactly.
- **Bridge clips** (`SpeechPipeline._bridge`): a canned reaction from the next speaker when its line is still rendering after 0.35 s (max 3 per turn; none right after the opening filler).
- **Firmware 3.4**: clock sync, first-sample timestamps, STOP, Wi-Fi OTA (`tools/ota.py`).

## What did not help (dead ends)
- **Pi GPU for Gemma** (LiteRT-LM via Vulkan): ~15x slower than CPU.
- **Gemma reasoning ON**: +7 s, no accuracy gain.
- **Trimming silence / 1.25x speeding the child's audio**: no reliable gain, dropped the toy's name.
- **Perception on GPU**: perception is ~0.1 s CPU per frame at 0.5 fps; not a bottleneck.
- **Streamed playout to the Atom**: upload to first sample is only ~0.1 s.
- **3-word first clause**: within noise (kept, harmless).
- **Deeper TTS queue** (2 -> 3): did not shrink handoff gaps.
- **Two Kokoro processes in parallel**: each ran at half speed, no throughput gain (a live brain may have shared core 2).
- **Kokoro quantization**: uint8 x1.0, q4 no gain, q8f16 broken; ConvInteger is already int8 and element-wise ops dominate.
- **Kokoro-LiteRT** (`litert-community/Kokoro-82M`): only runs through the C++ `omni_runner` (Bazel); `litert-lm` 0.18.1 has no TTS API. The headline 6-10x is a phone GPU number. Old fp32 `.tflite`: RTF 1.8 on a Pixel 8a. Not built.

## TTS benchmark (brain stopped, one core, 4.7 s line; `tools/tts_bench/`)

| Model | x real time |
|---|---|
| Kokoro int8 (in use) | 1.3 |
| Kitten TTS nano 0.8 int8 / fp32 | 4.1-4.6 / 4.8-5.1 |
| Supertonic 3 at 8 / 4 / 3 / 2 steps | 1.6 / 2.8 / 3.4 / 4.5 |
| Piper | 8-10 |

Quality not yet judged by ear. Pocket TTS needs PyTorch and a gated download: untried. The Pi's root disk is small: keep installs on `/data`.

## Handoff dead air between toys
About 1.2 s average, up to ~2.3 s: Gemma writing line N+1 and Kokoro rendering it while line N plays. Needs faster TTS.

## Not done yet
- Pick a faster voice (Kitten / Supertonic low steps) and wire it as a per-toy option.
- Tier B acoustic scoring with the judge; judge calibration on ~20 human-rated runs.
- Barge-in policy (`hub.stop()`).
- Jetson Orin Nano for Gemma (published 0.9 s TTFT).
