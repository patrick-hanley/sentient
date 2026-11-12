# What we have built so far

Three M5Stack AtomS3R-CAM plush toys (Dyno, Sage, Penny) talk with a child through a local "brain". Nothing leaves the house and audio stays in RAM.

## Architecture
mic UDP :5005 -> VAD (`vad.py`) -> Director -> Gemma 4 E2B (LiteRT-LM) -> `ReplyLines` -> `SpeechPipeline` (Piper / Kitten) + sound mixer (`sfx.py`) -> HTTP `/play` on the Atom.
The dashboard is on :8080 and the Parent Board on :8090. Toys find the brain by UDP broadcast HELLO and are identified by MAC (`brain/data/toys.json`).

## Timeline
- **Oct 24-26, Pi 5 brain.** Toys, camera/face/pet recognition, streaming Gemma, Piper + Kitten voices, filler sounds, latency tooling (`LATENCY.md`, turn log), OTA firmware updates (`tools/ota.py`).
- **Oct 26-29, sound quality.** Anti-alias resampler, silence trim, soft limiter, spectrum monitor, speaker-EQ experiments (EQ left off), see `EXPERIMENTS.md`.
- **Oct 29, firmware 3.5.** IMU motion sounds (`docs/imu-sounds.md`) and the Parent Board (`docs/parent-board.md`).
- **Oct 30, firmware 3.6 and quiet mode.** Recorded snores replaced a spoken "zzz". Toys go quiet after 3-10 min without child contact (`config.QUIET_AFTER_S`), snoring is capped at 6-15 loops.
- **Oct 30, Jetson Orin Nano Super becomes the brain.** SD image, NVMe at `/data`, MAXN_SUPER, Gemma on the GPU, hotspot `sentient-brain` for the toys (`docs/jetson.md`). The Pi is retired (powered off).
- **Oct 30-Nov 3, speech-only transcripts.** `brain/nonspeech.py` strips snoring/yawning/coughing/laughing annotations from transcripts. Spoken vocalizations and bracketed words ([yawn], [giggle], "Rawr!", "Hee hee", "Honk", "zzz") become recorded sounds on the atoms (`brain/sfx.py`, new recordings from `tools/fetch_sfx.py`). Gemma is told never to spell noises.
- **Nov 2-3, dashboard.** Redesigned operator dashboard (`brain/dashboard.html`: dark, dense, responsive, keyboard accessible, connection-loss banner). Recorded sounds show as bracketed chips like `dino growl` so they can be monitored. Fixed lines that spelled noises ("Mm-hmm", "Brrr") were rewritten as words.
- **Nov 3, benchmarks and speaker calibration:** `docs/benchmarks.md`.
- **Nov 10, conversation metrics and coaching (branch `goal/metrics`).** The brain scores the child's speech with a 5-10 minute rubric (turn-taking, latency, reciprocity loop, initiation, five 0-4 scores), keeps numbers-only summaries per child in the encrypted Parent Board store, shows a live anonymous panel on the dashboard and a Progress card on the Parent Board, and adapts the toys through bounded, logged, reversible knobs with automatic rollback; spoken lines and the base prompt only go to a human review queue. `docs/metrics.md`. Not yet deployed to the Jetson.

## Running it
Jetson: `sentient@sentient-jetson.local`, services `sentient-brain`, `sentient-kitten`, `jetson-perf`. Deploy: rsync `brain/` and `tools/` to `/data/sentient`, restart `sentient-brain`, then `POST /mute` (a fresh start has the mics live).
Firmware: `python3 tools/ota.py --ssh sentient@sentient-jetson.local`. Tests: `for t in tools/test_*.py; do .venv/bin/python $t; done`.

## Open items
- Real spoken-question latency on the Jetson; IMU calibration per toy (upright and still for 2 s); Parent Board PIN setup.
- Repeat the Sage speaker sweep next to the Mac mic, then re-decide the speaker EQ.
- Pi `brain/data` (profiles, faces, voice settings) was not carried over.
- An acoustic (segment-level) filter for non-speech sounds was deliberately not built: simple spectral features overlap with speech.
