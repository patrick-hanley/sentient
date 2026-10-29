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

Heard by ear (Patrick): **Supertonic at low steps (2-4) sounds terrible**, and at its default 8 steps it is only 1.6x, so it is dropped. Kitten and Piper not yet judged. Pocket TTS needs PyTorch and a gated download: untried. The Pi's root disk is small: keep installs on `/data`.

## Kitten live on the Pi (Oct 26)
Kitten runs as a sidecar (`tools/kitten_server.py`, `deploy/sentient-kitten.service`, Python 3.12 venv `/data/bench-k312`, CPU core 3) because misaki needs Python <3.13. The brain calls it through `Voices._render_kitten`, with a 30 s fallback to Kokoro/Piper if it is down. Dashboard engine "Kitten (fast)". Trial setup: Dyno = Jasper, Penny = Bella at speed 1.3, Sage stays Kokoro bf_emma (no British Kitten voice). Revert on the dashboard (Dyno am_eric, Penny af_heart). First lines: 2.3 s speech in 0.9 s, 4.3 s in 1.3 s.

## Live A/B on the Atoms: Kitten/Piper mix vs all Kokoro (Oct 26-27)
Method: `tools/live_run.py --atom penny` plays a recorded child question through Penny's speaker (`tools/atom_ask.py` on the Pi); Dyno and Sage hear it on their mics. Atom-side timestamps, ms after the child stops. Raw turns: `data/live_ab_2026-10-27.json`, TTS numbers: `data/tts_bench_2026-10-26.csv`.

| | Kitten Jasper + Piper alba (g0.4) + Kitten Rosie (n=7) | All Kokoro (n=4) |
|---|---|---|
| Filler audible | 0.7 s | 0.7 s |
| **Real reply audible, p50 (max)** | **5.3 s (5.9)** | 6.4 s (7.2) |
| Silence between toys, per turn | ~1 ms (one 40 ms) | 1.7 s in 2 of 3 turns |
| Whole turn, p50 | 9.6 s | 11.6 s |

About 1.1 s sooner to the first real words and the dead air between toys is gone, with small n and one room. Caveats: a run that played the questions from the Mac speaker (not through an Atom) had a 13.4 s outlier and several misses, so it is not in the table. The Kokoro arm was cut short when the Mac left the Pi's network. Gotcha found on the way: after a brain restart all three Atoms read volume 0 (`POST /speaker?toy=X&vol=200`), and the questions then go unheard.

**State left on the Pi: it is still on the all-Kokoro voices from the A/B run.** Restore the approved mix: Dyno Kitten Jasper, Sage Piper en_GB-alba-medium speed 0.93 gain 0.4, Penny Kitten Rosie speed 1.0.

## Audio conversion: anti-alias filter + soft limiter (Oct 28, commit f3f6a9d)
Change (Patrick): `_resample()` low-passes at 90% of the target Nyquist (7.2 kHz for 16 kHz) before downsampling, for Piper, Kokoro and Kitten alike; Piper's final stage soft-limits instead of hard clipping. Judged by spectrogram only (`tools/audio_ab.py`, `tools/spectro.py`, `brain/spectrum.py`; images and metrics in `data/audio_ab/`).

- **Native Piper (22.05 kHz) has 2.4% of its energy at 8-11 kHz**, about 4x the 7.2-8 kHz band. The old plain downsample folded that into 5-8 kHz.
- **Tone test:** a 9, 10 or 11 kHz tone leaked back at -5 to -8 dB below a 1 kHz tone (old) vs -73 to -94 dB (new): 68-86 dB better.
- **Piper speech, same text, Mac:** the 7.2-8 kHz band falls 17-21 dB (-12 -> -31 dB), 6-7.2 kHz falls 1-5 dB, energy above 7 kHz falls 0.7% -> 0.05%, below 4 kHz unchanged (+-0.1 dB). In the old spectrograms "s"/"sh" streaks reach 8 kHz; in the new they stop at the filter edge.
- **Kokoro (24 kHz) through the same path:** 7.2-8 kHz down 19 dB, Kitten Bella down 12.5 dB. The filter helps all three engines.
- **Soft limiter** on a deliberately hot line: 3290 flat-topped samples -> 0, peak 32768 -> 31129, no change in spectrum shape or loudness (-9.3 vs -9.6 dBFS).
- **On the Atoms** (Penny's speaker -> Dyno's mic, 3 reps x 2 lines, alternating old/new): 7.2-8 kHz -8 to -10 dB, 6-7.2 kHz -2 to -3 dB, 4-6 kHz about -1 dB, below 4 kHz within +-1 dB. Penny's own mic is unreliable (signal under its noise floor) and is ignored.
- **Cost:** none measurable in render time (numpy FIR, ~2 M multiply-adds per second of speech).

New brain features from this: `GET /spectrum` (band levels per mic, numbers only), a "Sound spectrum" dashboard panel, and `GET /tap.wav?toy=&sec=` (RAM only, only with `SENTIENT_DEBUG_RECORD=1`). `tools/clip_spectrum.py` is Patrick's standalone clip analyser from `piper-filter.zip`.

## More sound-quality work (Oct 28-29): `brain/dsp.py`
Measured by spectrogram, Mac first and then through the Atoms (`tools/chain_ab.py`, `atom_ab_pi.py`, `atom_sweep.py`; data in `data/audio_ab2/`).

| Idea | Result | Shipped |
|---|---|---|
| Better resampler (Kaiser-sinc low-pass + cubic interpolation, `dsp.resample`) | Flat to -0.2 dB at 4 kHz (linear interpolation lost -0.9) and <-90 dB aliasing; 13 ms per 5 s of speech. A full sinc interpolator is flatter at 6 kHz but 30x slower on the Pi. On the Atoms 4-7.2 kHz is +0.7 to +1.9 dB. | yes |
| Trim the neural voices' silent head/tail | Kitten Jasper lead-in 450 -> 30 ms, tail 230 -> 120 ms; Bella 650/470 -> 30/120 ms. 0.5-1.0 s shorter per Kitten line, also less dead air between toys. | yes |
| Single soft limiter at the end (Piper's own limiter removed to avoid stacking) | Piper peaks 32.6k -> 27.5k, no near-full-scale samples. | yes |
| Speaker EQ from a measured sweep (each Atom's speaker played a log sweep, the other mics recorded, speaker and mic terms separated by least squares) | The speakers lose 25-35 dB below 500 Hz. With boosts of +5/+10/+6 dB the heard response improved only +1-2 dB at 500-800 Hz (Dyno, Penny) and nothing on Sage, for hundreds of near-full-scale samples. Doubling the drive level raised the heard level only 6-9 dB instead of 11.5 dB, so the Atom chain compresses (speaker amp or mic path) and boosts mostly do not reach the room. | **off** (`SENTIENT_DSP_EQ=1` enables; curves in `brain/speaker_eq.json`, raw in `data/audio_ab2/speaker_response_measured.json`) |
| Loudness match across voices | Approved mix is already within ~3 dB, and normalising would have changed the levels Patrick approved (Sage Piper gain 0.4). | no (`SENTIENT_DSP_LEVEL=-22` enables) |
| 16-bit PCM instead of mu-law | mu-law SNR 37 dB (noise -53 dBFS, below the mics' own floor). PCM doubles the upload (131 vs 65 KB): overhead 0.22-0.66 s vs 0.17-0.50 s. Not worth it. | no |
| Pitch trick (resampling) | Not in use: all three live voices run pitch 1.0. | n/a |
| Firmware playback audit | `M5.Speaker.playRaw` mono at 16 kHz, volume from NVS. Nothing wrong found; M5Unified upsamples internally. Untested: the codec's own ALC/limiter, a suspect for the compression above. | n/a |

Sage's speaker was silent for a while (no sound on the other mics) until the user reseated it; measured properly afterwards. Its response is weaker at 4-5 kHz than Dyno's and Penny's.

**Clip refresh:** clip ids now include `dsp.fingerprint()` (processing version), so any change to this chain makes the brain clear and re-store every Atom's clips on the next start. Done Oct 29 for all three toys (dyno 37, sage 36, penny 38 clips). Also fixed a bug found on the way: after clearing an Atom's flash the brain still believed it was nearly full and stopped after the first clip (`clear_clips` now resets the used-space figure).

## Handoff dead air between toys
About 1.2 s average, up to ~2.3 s: Gemma writing line N+1 and Kokoro rendering it while line N plays. Needs faster TTS.

## Not done yet
- Judge Kitten by ear; if it passes, wire it as a per-toy option (Supertonic is out).
- Tier B acoustic scoring with the judge; judge calibration on ~20 human-rated runs.
- Barge-in policy (`hub.stop()`).
- Jetson Orin Nano for Gemma (published 0.9 s TTFT).
