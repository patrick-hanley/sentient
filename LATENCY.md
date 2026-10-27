# Sentient latency upgrade

The brain can speak its first complete toy line while the model continues generating. It can synthesize the next line while the first plays. The default `responsive` profile also shortens the wait after speech and skips new camera capture requests during a response.

## What changed

Previously, the brain waited for the whole model reply, then synthesized and played each line in sequence. Now the model streams into a strict line parser and a bounded speech pipeline:

```mermaid
flowchart LR
  A[Microphone frames] --> B[Speech endpoint and mic arbitration]
  B --> C[Local ASR or direct audio model]
  C --> D[Streaming model reply]
  D --> E[Complete labelled toy line]
  E --> F[One synthesis worker]
  F --> G[One ordered playback worker]
  H[Cached camera scene] --> D
```

- LiteRT-LM uses its streaming iterator; llama.cpp and GenieX use Server-Sent Events.
- Only complete labelled lines for online toys are queued. Explicit thought blocks and reasoning channels are excluded. A stream failure cannot cause an automatic resend after visible output starts. A token-limit stop discards the incomplete tail on the HTTP backends.
- One synthesis worker keeps Piper calls serial; a separate playback worker preserves speaker order. There are at most two reply lines. Playback errors mark the turn failed and release the response lock.
- Camera requests use cached views during a turn. An existing capture/recognition operation may finish; new capture requests resume after playback. Images older than three seconds are not attached to the model. The small scene description still comes from the perception cache.
- Piper still produces mono 16 kHz signed 16-bit PCM. The existing `PLAY_CODEC` / `PLAY_RATE` settings control the wire format: default 16 kHz mu-law, with PCM and 8 kHz options retained. Each line is encoded and uploaded in full. This is line streaming, not sample-by-sample streaming or interruption support.
- The school-focused characters are preserved. Penny is whimsical and silly while giving careful, accurate answers. Her spelling is never deliberately altered, and other toys can take the next turn normally. The scripted scene follows the same characterization and invites the child to respond at the end.

## Profiles

| Setting | Previous behavior | `responsive` (default) | `patient` |
|---|---:|---:|---:|
| Silence to end an utterance | 700 ms | 500 ms | 700 ms |
| Maximum wait for other microphones | 350 ms | 120 ms | 350 ms |
| Filler before model reply | On | Off | On |
| Stream model and overlap speech work | No | Yes | Yes |

With one online toy, arbitration now returns immediately. With several, it stops once all online microphones report an overlapping utterance, choosing the loudest. The two configured maximum waits shrink by a combined 430 ms in responsive mode; real timing also depends on microphone arrival and voice activity detection. If a child pauses between words and is cut off, use `--latency-profile patient`.

## Run with existing models

From the project folder, using the Python environment containing the project's dependencies and models:

```bash
python -m brain.main --latency-profile responsive
python -m brain.main --latency-profile patient
```

Existing LiteRT and llama.cpp backends keep working. An older LiteRT runtime without streaming still works synchronously and receives only the downstream synthesis/playback overlap benefit. `--cpu` applies to LiteRT; GenieX chooses its processor in the server command.

## VENTUNO Q deployment

Run the brain on the board's Ubuntu processor. The board is not yet running this project, so this upgrade does not claim a measured hardware speedup or an enabled NPU.

Arduino documents [GenieX on the VENTUNO Q](https://docs.arduino.cc/de/tutorials/ventuno-q/geniex/) for local NPU execution. Follow that guide to install the runtime, then use these commands **on the board**:

```bash
geniex pull google/gemma-4-E2B-it-qat-q4_0-gguf --model-hub hf
geniex infer google/gemma-4-E2B-it-qat-q4_0-gguf:Q4_0 --compute npu --max-tokens 32 --think=false --prompt "Reply with exactly: NPU OK"
geniex serve --compute npu
```

Keep the server running in its terminal. It uses loopback port 18181. In another board terminal, from the Sentient folder with the brain's Python environment activated:

```bash
SENTIENT_VISION=never python -m brain.main --backend geniex --latency-profile responsive --selftest
SENTIENT_VISION=never python -m brain.main --backend geniex --latency-profile responsive
```

The recommended initial setting `SENTIENT_VISION=never` omits the raw image from the model prompt while retaining cached face/toy/scene descriptions. Direct VLM image processing can dominate response time on this runtime; add `SENTIENT_VISION=sage` only when testing the reader's image features. Arduino's [GPU/llama.cpp guide](https://docs.arduino.cc/tutorials/ventuno-q/llama-cpp/) describes an alternative runtime.

The new adapter checks `/v1/models`, requires the selected model to be cached, uses native `enable_think=false`, and streams `/v1/chat/completions`. It does not launch another runtime if GenieX is missing. The dashboard reports `server-configured`; confirm NPU use from the server/runtime, rather than inferring it from the selected backend. Protocol details follow [Qualcomm's server guide](https://github.com/qualcomm/GenieX/blob/main/docs/cn/run/cli/local-server.mdx).

Optional settings, set before starting Python:

| Variable | Default | Meaning |
|---|---|---|
| `SENTIENT_GENIEX_URL` | `http://127.0.0.1:18181` | Server origin, without `/v1` |
| `SENTIENT_GENIEX_MODEL` | `google/gemma-4-E2B-it-qat-q4_0-gguf:Q4_0` | Exact id from `/v1/models` |
| `SENTIENT_VISION` | `sage` | `never`, `sage`, or `always` for raw image attachment |
| `SENTIENT_OFFLINE` | `offline/` under the project | Local voices, vision and ASR assets |

### Prerequisites still needed for a first board install

The downloaded project did not have an `offline/` model bundle or a brain environment when this upgrade was prepared. GenieX replaces the language-model runtime, not these other dependencies:

- Python packages: `numpy`, `opencv-python-headless`, `webrtcvad-wheels`, `piper-tts`. Optional MediaPipe adds pet/book detection.
- Piper assets under `offline/piper/`: `en_GB-alba-medium.onnx` and `en_US-libritts_r-medium.onnx`, each with its `.onnx.json` file.
- Face assets under `offline/vision/`: YuNet and SFace models, as listed in `brain/config.py`. Optional object detector/embedder assets enable more perception features.
- For the GenieX/llama.cpp audio path, either `whisper-cli` / `whisper-cpp` on PATH plus `offline/whisper/ggml-base.en.bin`, or `faster-whisper` plus a complete local CTranslate2 base.en directory at `offline/faster-whisper-base.en/`. ASR stays on CPU in this upgrade. LiteRT can continue receiving audio directly.

Use a board-native virtual environment, for example `python3 -m venv .venv-brain`, then activate it and install those Python packages. The existing `tools/fetch_offline.sh` lists asset URLs, but it also builds Mac/Pi/Jetson environments. The existing `tools/setup_brain.sh` changes Wi-Fi/hotspot settings; neither script has been run as part of this upgrade. Use the board's current Python version for wheels. Copy the prepared folder to the board and run `--selftest` before connecting toys.

## Read actual timings

The dashboard at `http://<brain-ip>:8080` includes a latency details panel. Its `/state` endpoint returns `latency_breakdown`, and the same content-free timing record is logged after a turn.

For microphone turns, milestones start at the host's receipt of the last voiced audio frame. This includes endpoint silence and arbitration, but excludes delay before that frame reached the host. Event turns start at turn entry.

| Milestone | What it measures |
|---|---|
| `utterance_ready_ms` | VAD emitted the utterance |
| `turn_started_ms` | Arbitration finished and response started |
| `stt_done_ms` | Separate ASR completed, when used |
| `first_model_text_ms` | First visible model text |
| `first_line_ready_ms` | First complete accepted toy line |
| `first_pcm_ready_ms` | First reply PCM synthesized |
| `first_audio_post_ms` | Brain began the reply's HTTP POST, after acquiring the playback lock |
| `last_playback_ack_ms` | Toy acknowledged the last successful playback request |
| `turn_done_ms` | Playback and cleanup finished |

`first_audio_post_ms` is **not acoustic first-audio latency**: the toy receives the full body before playing, and does not report its first speaker sample. `audio_onset_measured` is explicitly false. The patient profile's filler is excluded from the reply's first audio milestone. `stage_work_ms` separates ASR, model, synthesis, filler wait and upload/playback work; overlapping stages must not be added together.

After deployment, compare repeated identical prompts with the same model, image setting and network. Record at least ten turns, inspect median and slowest turns, and check speech cutoff and reply order with two toys. For actual end-of-speech to speaker onset, measure both sounds with an external recording.

## Local verification

```bash
python tools/test_latency.py
python tools/benchmark_latency.py --runs 5
```

The tests use fake models/voices and loopback-only mock model/toy HTTP servers. They check streaming order, overlap, endpoint timing, parsing, failures, temporary-file cleanup and both HTTP backend contracts. They do not run model inference or claim physical speaker output.

The five-run scheduling simulation used 80 ms to the first model line, another 420 ms to finish the reply, 80 ms synthesis per line, and 200 ms playback per line:

| Simulated median | Previous serial scheduling | New pipeline |
|---|---:|---:|
| Turn entry to first audio POST | 590 ms | 166 ms |
| Total turn | 1,082 ms | 793 ms |

First audio POST fell 71.9% in this controlled simulation. These values demonstrate scheduling overlap; they are not VENTUNO Q performance predictions. Firmware, microphone transport and camera calibration files are outside this change.

## Measuring it (turn log, virtual Atoms, scoring)

**Always on.** Every turn appends a content-free record to `brain/data/latency/turns.jsonl` (milestones, stage work,
`speech_ms`, Pi CPU %/temp/throttle flag, per-Atom RSSI and lost mic packets, floor-control violations). The dashboard
has a "Latency waterfall" panel and `GET /latency` returns the last 200 turns plus p50/p95 per stage.

**Virtual Atoms** (no hardware, no human):

    python tools/virtual_atoms.py tools/scenarios/one_toy.json --selfhost      # fake models: tests the rig only
    python tools/virtual_atoms.py tools/scenarios/three_toys_chain.json --brain 192.168.2.5   # real brain on the Pi
    python tools/score_run.py runs/<file>.jsonl [runs/<other>.jsonl]           # gaps, overlap, dead air, A/B delta

`--selfhost --set END_SILENCE_MS=700 --set PLAY_FILLERS=false` runs A/B arms with the same seed. Against the Pi, change
the knob in `brain/config.py` or the environment and restart `sentient-brain` between runs. Timings from `--selfhost`
use made-up model delays from the scenario's `model` block; only runs against the Pi measure Gemma/Kokoro.
Scenario `chain` feeds one toy's reply into another toy's mic (Tier A agent-to-agent, no air gap).

**Judge:** `--transcribe` makes a text transcript (local faster-whisper, audio stays in RAM); `tools/judge.py` scores it
with the Anthropic API (or prints the prompt without a key) and `--calibrate` compares it with human ratings.

**Debug audio:** `SENTIENT_DEBUG_RECORD=1` writes input/output WAVs to a private temp dir that is deleted at exit
(files older than an hour are pruned). Default off: nothing is written.

**CPU budgeting (experimental):** `SENTIENT_LLM_CORES=0,1,2 SENTIENT_TTS_CORES=3` pins the LLM and the TTS worker.

**Firmware 3.3 (compiled, not yet flashed):** the Atom answers `SYNC <n>` with `SYNCR <n> <us>` (the brain keeps the
lowest-RTT offset per Atom), sends `PLAYING <us>` as the first sample is queued and `PLAYED <us>` at the end, and stops
playback on `STOP` (`AtomHub.stop(toy)` sends it). The brain turns these into `atom_first_sample_ms`,
`atom_reply_sample_ms` and `atom_play_end_ms` milestones. Older firmware ignores SYNC/STOP, so the brain works with both.
Build: `arduino-cli compile -b m5stack:esp32:m5stack_atoms3r:CDCOnBoot=cdc,PSRAM=opi firmware/toy-client` (the CLI is inside
Arduino IDE.app).

Not built yet: streamed playout with a jitter buffer (a whole line is ~16-48 KB, so the transfer is tens of ms on a good
link; measure `first_audio_post_ms` to `atom_reply_sample_ms` on the Pi first), a barge-in policy that calls `stop()`,
and Tier B acoustic runs.

## Measured on the Pi 5 (Oct 26, real Gemma + Kokoro, Mac speaking near the toys, 3 Atoms on firmware 3.4)

Time after the child stops speaking (ms, p50 / p95, 9-11 turns per arm):

| Arm | filler heard | first token | first line ready | reply audio ready | reply audible on Atom |
|---|---|---|---|---|---|
| Baseline | 694 / 917 | 2542 / 12810 | 4301 / 14855 | 7210 / 17896 | 7440 / 18029 |
| + conversation warm-up | 716 / 5107 | 2559 / 3671 | 3841 / 5595 | 6788 / 10509 | 6895 / 10644 |
| + LLM cores 0-2, TTS core 3 | 694 / 926 | 2772 / 4229 | 4226 / 5284 | 6921 / 8011 | 7030 / 8125 |
| + 3-word first clause | 701 / 941 | 2776 / 4251 | 4042 / 5536 | 6724 / 8620 | 6846 / 8732 |

What it shows:
- The 6 s was never one thing. A canned filler is audible at 0.7 s; the real reply takes about 6.8 s.
- Every ~8th turn (and the first after a restart) paid ~10 s: Gemma prefilled the persona prompt cold when the
  conversation reset. `LiteRTBackend.warm()` now does that in the background. p95 first audio fell from 17.9 s to ~8-9 s.
- Pinning Gemma to cores 0-2 and TTS to core 3 cut the time for Gemma to finish the whole reply from ~16 s to ~9-10 s,
  but not time-to-first-audio.
- Time-to-first-audio is now: ~2.7 s to first token (audio prefill), ~1.3 s for the first sentence, ~2.7 s for Kokoro to
  render it, ~0.1 s to reach the Atom. Atom-side upload is not a bottleneck (0.1 s), so streamed playout is not worth building.
- Kokoro is single-threaded in effect: 1 core or 4 cores renders at about 1x real time plus ~0.6 s per call
  (2.1 s of speech in 2.1 s). Piper renders the same text in 0.2-0.4 s but is a different voice.
- No CPU throttling (0x0), 51-58 C, mic packet loss about 0.2%.

Not done: a different TTS or parallel Kokoro sessions (the next real lever for first audio), and acoustic Tier B scoring
with the judge. The 5-word minimum for later chunks leaves small gaps between chunks because Kokoro is ~1x real time.
