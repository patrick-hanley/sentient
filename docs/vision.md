# Vision

## Choosing the vision model

Question: which model should turn a tiny, dim toy-camera JPEG into "that is a cup"? Gemma 4 E2B already
runs on the Jetson GPU and can take the image directly in its prompt (no extra model). Is a separate
vision-to-text model worth its extra RAM and latency? Only about 2-3 GB of the Jetson's 7.4 GB shared
memory is left beside Gemma.

### Candidates

Licenses were checked against the Hugging Face model cards. "Jetson" = can plausibly run on the Orin Nano
(aarch64, CUDA) with llama.cpp or PyTorch; the memory column is the weights plus runtime we measured or
expect, not a Jetson measurement.

| Model | Params | License | Disk | Runtime | Jetson | Extra RAM next to Gemma |
|---|---|---|---|---|---|---|
| Gemma 4 E2B (own vision, tested) | 5.1B (2.3B eff.) | Apache-2.0 | 0 extra (already loaded) | LiteRT-LM (llama.cpp GGUF in the bench) | yes, live today | none |
| SmolVLM-256M (tested) | 0.26B | Apache-2.0 | 0.27 GB Q8 | llama.cpp, transformers | yes | ~0.6 GB |
| SmolVLM-500M (tested) | 0.5B | Apache-2.0 | 0.5 GB Q8 | llama.cpp, transformers | yes | ~1.0 GB |
| SmolVLM2-2.2B | 2.2B | Apache-2.0 | ~2.3 GB Q8 | llama.cpp, transformers | yes | ~3 GB (too big) |
| Florence-2-base (tested) | 0.23B | MIT | 0.5 GB | transformers (ONNX export exists) | yes (PyTorch CUDA, fp16) | ~0.5-1 GB fp16, 1.8 GB fp32 on CPU |
| Florence-2-large | 0.77B | MIT | 1.5 GB | transformers | yes | ~1.5-2 GB |
| Moondream2 (tested) | 1.9B | Apache-2.0 | 3.7 GB fp16 | transformers (remote code, needs pyvips) | possible, heavy | ~4 GB fp16 (measured 7.9 GB fp32 on Mac) |
| Moondream3 preview | 9B MoE (2B active) | BSL (restricted) | 18 GB | transformers | no | no |
| Qwen3-VL-2B (tested) | 2.1B | Apache-2.0 | 2.2 GB Q8 (1.75 + 0.42 mmproj) | llama.cpp (ggml-org GGUF), transformers | yes | ~2.2 GB weights + ~1 GB runtime at Q8; Q4 would be roughly half the weights (not tested) |
| Qwen2.5-VL-3B | 3.8B | Qwen Research (non-commercial) | 2.6 GB Q4_K_M | llama.cpp | yes | ~3 GB (too big, license) |
| PaliGemma 2 3B | 3.0B | Gemma terms | 6 GB bf16 | transformers | heavy | ~3-6 GB (too big; needs per-task fine-tune prompts) |
| InternVL3-1B / 3.5-2B | 0.9B / 2.3B | Apache-2.0 | 1.9 / 4.7 GB bf16 | transformers (llama.cpp support partial) | possible | ~1-2.5 GB; not run |
| LFM2-VL 450M / 1.6B | 0.45B / 1.6B | LFM Open License (free for small orgs) | 0.9 / 3.2 GB | transformers, llama.cpp | yes | not run |
| FastVLM-0.5B | 0.5B | Apple research license | 1.5 GB | transformers | n/a | excluded by license |
| nanoVLM-222M | 0.22B | Apache-2.0 | 0.9 GB | custom PyTorch | possible | not run (research code, no GGUF) |

Not run on the Mac: Qwen2.5-VL-3B (license is research-only for the 3B, and ~3 GB is over budget),
PaliGemma 2, SmolVLM2-2.2B, Florence-2-large, InternVL, LFM2-VL, nanoVLM (over budget, no
ready GGUF, or not worth the setup time; each can be added to `MODELS` in `tools/vision_bench.py`).

### Method

* Test set: 36 photos of everyday household objects (cup, mug, scissors, remote, teddy bear, book, shoe,
  keys, banana, apple, lamp, backpack, water bottle, pencils, LEGO, chair, clock, kettle, stapler, ...).
  People-free. From Wikimedia Commons under CC0 / public domain / CC BY / CC BY-SA; source URL, license and
  author per image are in `tools/vision_set/manifest.json` together with the ground-truth label and 1-4
  acceptable synonyms. Some are deliberately hard (LEGO pile, folded umbrella, 3 toothbrushes).
* Degraded to toy-camera quality: centre-cropped to 4:3, 320x240, Gaussian blur (radius 0.9), gamma 1.6-2.3
  with brightness x0.45-0.7 (dim room), warm colour cast, Gaussian noise, JPEG q50. Only the degraded images
  are in the repo (316 KB).
* Prompt: "Name the main object in one short sentence a child would understand." (Florence-2 cannot take a
  free prompt, so it uses its `<CAPTION>` task.)
* Score: hit if the ground-truth label or any synonym appears in the normalised answer (substring match, a
  trailing plural "s" is ignored). Latency: per image wall time, median and p90, after one warm-up call on a
  synthetic image. Memory: peak RSS of the process (llama-server tree for GGUF models) sampled every 100 ms.
* All GGUF models run through llama.cpp `llama-server` (b11856, one slot, CPU, mmproj on CPU) so they are
  measured the same way. Gemma is the same Q4_0 + Q8 mmproj the toys use, but through llama.cpp rather than
  LiteRT-LM, so its accuracy is a proxy for the Jetson path. Qwen3-VL ran with `--image-min-tokens 256`.
* Caveats: 36 images, so one image is ~3 points and a 6-point gap is within noise; substring scoring favours
  wordy answers (Moondream2 describes the whole scene); Florence-2 captioned the shoe by brand name and missed.

### Results (Intel Mac, CPU only)

Mac latency is NOT Jetson latency: use it only to compare models with each other.

| Model | Hit rate | Median s | p90 s | Peak RSS MB | Missed |
|---|---|---|---|---|---|
| SmolVLM-256M Q8 | 32/36 (89%) | 2.79 | 3.02 | 578 | kettle, lego, stapler, umbrella |
| SmolVLM-500M Q8 | 30/36 (83%) | 3.26 | 3.56 | 1002 | book, cake, kettle, lego, stapler, umbrella |
| Florence-2-base fp32 | 32/36 (89%) | 4.15 | 4.35 | 1766 | lego, shoe (brand name), umbrella, water bottle |
| Moondream2 (2024-08-26) fp32 | 35/36 (97%) | 24.74 | 49.41 | 7863 | lego |
| Gemma 4 E2B Q4_0 + mmproj | 30/36 (83%) | 3.25 | 3.63 | 4564 (the whole Gemma, already resident on the toys) | backpack ("ladder"), lego, pencils, stapler, umbrella, vase ("wreath") |
| Qwen3-VL-2B Q8 | 35/36 (97%) | 8.90 | 9.79 | 3551 | lego |

Raw per-image answers: `tools/vision_results_mac.json`, table: `tools/vision_results_mac.md`.

What the numbers say:

* Accuracy tiers: Qwen3-VL-2B and Moondream2 (97%) > SmolVLM-256M and Florence-2-base (89%) > Gemma and
  SmolVLM-500M (83%). The 500M model is not better than the 256M one on this set.
* Moondream2 is out: 25 s per image and ~8 GB fp32 (about 4 GB even in fp16) for no gain over Qwen3-VL-2B.
* Qwen3-VL-2B is the accuracy winner and its answers are the most child-friendly ("A big, fancy clock
  with a round face"), at about 2.7x Gemma's Mac latency and ~2.2 GB of weights at Q8.
* SmolVLM-256M is the cheap option: 0.6 GB, fastest, 89%. Its answers are terse and it fails on odd
  objects (stapler -> "binder", folded umbrella -> "lace").
* Gemma's own vision is the weakest of the useful models here (83%, with a few confident wrong answers and
  markdown in the reply) but costs no extra memory and no extra model load.

### Jetson numbers

Jetson numbers: pending. Run when the main session says the hardware is free (do not run while the toys
are in use; Gemma is already holding the GPU, so stop or accept contention, and note which):

```
ssh sentient@sentient-jetson.local
cd ~/sentient   # the repo checkout
# one-time: llama.cpp built with CUDA (llama-server on PATH or LLAMA_SERVER=...), GGUFs from ggml-org in ./models
.venv/bin/python tools/vision_bench.py --jetson --models-dir models \
    --models smolvlm-256m,smolvlm-500m,qwen3vl-2b,gemma,florence2-base
```

`--jetson` runs llama-server with `-ngl 99` (full GPU offload including the mmproj) and Torch on CUDA in
fp16, and writes `tools/vision_results_jetson.md/.json`. Gemma comes from `offline/gguf` (set
`SENTIENT_OFFLINE` if it lives elsewhere). Needs `pip install requests psutil pillow` (plus torch,
transformers, einops, timm for Florence-2). To fit next to the brain's Gemma, also record `tegrastats`
RAM during the run.

### Recommendation

1. Keep `SENTIENT_VISION_MODEL=gemma` (the default) for now: zero extra memory, one model, and the
   toys already work this way. Its main weakness is odd or dim objects.
2. If object naming matters (enrolling "teach the camera" items, parent-visible labels), add Qwen3-VL-2B
   as a second backend: +14 points on this set (97% vs 83%). It must fit the 2-3 GB budget, which is
   tight at Q8 (2.2 GB weights plus runtime); use a Q4 GGUF if the Jetson run shows it does not fit, or
   load it on demand for the one-shot "what is this?" call rather than keeping it resident.
3. If memory will not allow that, SmolVLM-256M (0.6 GB, 89%) is the low-cost alternative, and it already
   beats Gemma's own vision on this set.
4. Decide after the Jetson run: GPU latency and the real free RAM are what settle 2 vs 3.

Both options are served through one OpenAI-compatible `llama-server` (any GGUF + mmproj), selected with
`SENTIENT_VISION_MODEL=llamacpp` and `SENTIENT_VISION_URL`. See `brain/vision_model.py`. Example:

```
llama-server -m Qwen3-VL-2B-Instruct-Q8_0.gguf --mmproj mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf \
    --port 8082 -ngl 99 -np 1 --image-min-tokens 256
SENTIENT_VISION_MODEL=llamacpp SENTIENT_VISION_URL=http://127.0.0.1:8082 ...
```

Florence-2 (`SENTIENT_VISION_MODEL=florence`) is also available in-process; it is small but has no free
prompt and tied SmolVLM-256M on accuracy.

## Camera policy: off unless the child asks

The toys' cameras are **off by default**. The brain never polls them. A toy takes one picture only when the child asks it to look, from the toy that heard the child, and the camera is off again as soon as the frame is captured.

| | before | now |
|---|---|---|
| `Perceiver.start()` | polled every toy at `CAPTURE_FPS` | starts nothing (opt-in: `SENTIENT_CAMERA_CONTINUOUS=1`) |
| greeting familiar faces/pets (`on_seen`) | on every poll | only in continuous mode |
| `[SCENE]` in the prompt | what each toy saw 0–2 s ago | "All cameras are off; a toy looks only when the child asks." |
| dashboard | live frame per toy | "Camera off" tile, chip `cameras: off (on request)` |

("Off" means the brain never requests a frame. The Atom firmware keeps its camera initialised and only exposes `/capture`; nothing reads it.)

### Detecting the request (`brain/camera.py`)

Two paths, both in the same turn:

1. **Transcript rules** (`camera.wants_look`): used whenever there is a transcript (llama.cpp / GenieX backends, which transcribe first). About 25 patterns: "what do you see", "look at this/that/what I made", "what is this/that/these", "can/do you see …", "what am I holding", "who's this", "what colour is this", "let me show you …", "take a look", "check this out". Refusals ("don't look", "stop looking", "turn the camera off", "no peeking") and idioms ("look up", "look for my shoes", "see you later", "let's see how many") never match. The picture is taken before the first model call, so a look turn costs one model call.
2. **The LOOK handshake** (LiteRT Gemma hears the child's audio directly, so there is no transcript up front): the system prompt tells Gemma that the cameras are off and that when the child asks it to look it must reply with the single word `LOOK`. `camera.LookPeeler` sits between the model stream and the reply parser, recognises a first word `LOOK` however it is chunked, and swallows it. Any other reply passes through byte for byte with no added delay (a toy line starts `DYNO:`/`SAGE:`/`PENNY:`/`HEARD:`, which cannot be a prefix of LOOK after its first letter). The director then calls `Perceiver.snap(toy)` (a forced capture, allowed mid-turn, plus the usual face/tag analysis), writes the JPEG to a `/dev/shm` temp file, calls `Perceiver.close(toy)` (camera off, frame forgotten) and sends a second message in the same conversation: a `[CAMERA]` block plus the image. The question is already in the conversation as audio. The "Hmm!" filler that already plays at turn start covers the extra round trip. A second `LOOK` in one turn is ignored; a dead camera produces an honest "my eyes are not working" prompt.

The extra latency of a look turn is one short model round trip (audio prefill plus ~2 tokens) + one capture (~0.1–0.3 s over the hotspot) + the second call with the image. It is recorded in the turn trace as `look_ms` (stage work) and `look_done_ms` (milestone); ordinary turns are unchanged. Jetson numbers: see "Jetson measurements" below.

Privacy: the frame exists in RAM and in one temp file that the end of the turn deletes (`tmp_files`), the `View` is dropped by `close()`, nothing is logged about what was seen.

## Teach the camera (Parent Board)

Parent Board → **Teach the camera**. A parent can teach, by name:

| teach | stored | recognised as |
|---|---|---|
| a parent / family member | SFace face vectors | `person` named by the parent (an unknown face stays **"a person"**) |
| the child | SFace face vectors | **"the child"** (only a face enrolled as the child gets that label) |
| a toy's look (Dyno, Sage, Penny) | appearance vectors from *another* toy's camera | the toy, **with no ArUco tag** (tags still work) |
| a household item ("red cup") | appearance vectors | `object` with the parent's name |

Photos come from a toy's own camera (the camera is on only while the button runs: 6 frames, forced capture) or are uploaded from the parent's phone (up to 10, one request each). Every enrollment needs the consent box; the server refuses without it and touches no camera first.

Rules it keeps (all covered by `tools/test_vision.py`):

- **embeddings only**: photos are decoded in RAM, turned into vectors and dropped; nothing but `teach.enc` is written;
- **encrypted like the profiles**: AES-GCM under the Parent Board key (`SPB1` format, scrypt-wrapped by the family PIN), file `brain/data/parent/teach.enc`. While the board is locked (after a restart, until a parent enters the PIN) **nothing is recognised**: unknown faces are "a person";
- **deletable**: per entry from the board, with the child's profile (`forget_child`), and with "Delete all profiles" (`wipe_all` overwrites every file in the directory);
- **never logged**: the log says only `teach: person enrolled from 6 photo(s)`; the old startup line that listed enrolled names now logs counts; the web server logs no requests;
- the board never receives vectors (`/api/teach/list` returns kind, name, photo count).

How recognition works (`Recognizer.analyze`): faces use SFace cosine ≥ `FACE_MATCH` against the encrypted gallery (the legacy `enroll.npz` CLI path still works and is checked first). Toys and items are compared on up to four regions of the frame (the detector's two largest boxes, the centre 60 %, the whole frame) with the MediaPipe image embedder where installed and otherwise an OpenCV colour-histogram embedder (brightness-stretched so the dim toy cameras match, so it also works on the Mac). A thing is claimed only if its score clears the embedder's threshold (`SENTIENT_THING_MATCH_MP`=0.80, `_HIST`=0.90) and beats the runner-up by 0.03; a toy never recognises itself and a toy already found by its tag is not reported twice. Entries remember which embedder made them, so a brain moved between machines never mixes scales.

Limits: thresholds were set on synthetic and Mac-only data (the MediaPipe embedder is not installable on the Intel Mac), so **calibrate on the Jetson with the real toys** before trusting them: enroll each toy and two items from a neighbouring toy's camera, then run `tools/test_vision.py`-style checks live (see "Jetson to-do").

## Jetson to-do (when the hardware is free)
1. Deploy, restart, `POST /mute`; say "what do you see?" to each toy and read `look_ms` / `look_done_ms` in the turn log (the LOOK round trip is untested on hardware).
2. Run the vision benchmark command above for Gemma (LiteRT is the real runtime) and Qwen3-VL-2B Q4 / SmolVLM-256M; fill in "Jetson numbers".
3. Teach each toy and two items from a neighbouring toy's camera, check recognition, and tune `SENTIENT_THING_MATCH_MP` / `_HIST`.
