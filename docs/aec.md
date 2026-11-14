# Cross-toy echo cancellation and barge-in

**Status (Nov 12): works in simulation, does NOT yet work on the real toys; off by default (`SENTIENT_AEC=1` enables it). See "Hardware findings".** Implemented and tested in simulation (`tools/test_aec.py`, 20 tests). **Not yet measured on the real toys**; see "Hardware measurement" below. Code: `brain/aec.py` (new), small hooks in `brain/atoms.py`, `brain/director.py`, `brain/tts.py`, constants in `brain/config.py` (`AEC_*`), simulator `tools/aec_sim.py`.

## What it does

A toy cannot hear while its own speaker plays (shared codec), but the other toys' mics keep streaming 20 ms UDP frames, and they hear the talker through the room. The brain knows exactly what it sent to the talker, so for every (talker -> listener) pair it subtracts that sound from the listener's stream. What is left is the child plus room noise. That residual is watched for speech while the toy talks:

1. a child starts talking over a toy -> the residual gets loud and speech-like for 120 ms;
2. the brain sends STOP to the toys (`director.barge_in` -> `interrupt`: `_gen` is bumped so the rest of the reply is dropped, `hub.stop_all`);
3. the residual frames from before the first loud one (15 frames, 300 ms, pre-roll) up to now are handed to the normal `Segmenter` at once, and the child's mic stays live from then on (the hub does not wait for the toy's `/play` to return);
4. the segmenter emits the utterance from its true start and the director answers it as a normal turn. `Director._flush()` (run when the cancelled turn winds down) used to drop everything captured while busy; it now keeps utterances that ended after a barge-in and does not reset a segmenter that is mid-sentence.

If the canceller is not ready for a pair (first ~0.65 s of the pair's first clip, no clock offset, the pair lost its lock) the old loudness-ratio `BargeDetector` keeps listening for that mic, so nothing regresses. `SENTIENT_AEC=0` turns the canceller off entirely.

## Signal path, per (talker -> listener) pair

| Stage | What | Why |
|---|---|---|
| Reference | The exact bytes sent to the talker, decoded back (mu-law, 8 kHz transport undone): `wire_to_ref`. Fixed lines that play from the Atom's flash use the cached PCM through the same mu-law round trip (`TTS.cached`). | The speaker plays the decoded wire audio, quantisation noise included. |
| Time | Listener frames carry only a 16-bit `seq` (frame n = `seq` x 320 samples, wraps handled, gaps = lost packets, jumps > 50 = resync). Brain arrival time minus n/16000, lower envelope over 8 s (the least delayed packets), is the brain time of sample 0. The talker's `PLAYING <us>` (already converted to brain time by `atoms.py` through `sync_clocks`' `clock_off`) puts the clip on that timeline. | No timestamps in the mic packets (see firmware proposal). |
| Lag | What remains is the capture frame (20 ms), codec/DMA latency, WiFi jitter and the sync error: tens of ms, constant per pair. GCC-PHAT (300-3800 Hz band, beta 0.85) over the first 0.55 s of the clip finds it, range -150..+600 ms; a confident peak (score over 6) is required. Later clips of the same pair re-align with a narrow search (+-62 ms, 0.3 s of audio) around the last lag. | Timestamps alone are not accurate enough for a 160 ms filter; the filter is placed 10 ms early so the main tap has slack. |
| Filter | Partitioned-block frequency-domain NLMS (multi-delay filter): 8 x 20 ms partitions = 160 ms of room echo, overlap-save with a 640-point FFT, per-bin power-normalised step (mu 0.5), constrained gradient. Trained retrospectively (6 passes) over the frames already heard when the lag is found, so it converges at once; the filter then persists across the pair's clips (warm start; the room does not change between lines). | A block size equal to the packet size; ~0.75 ms per frame on a Mac core. |
| Double talk | `q` = running residual-to-echo power ratio measured while nobody else talks. Expected leftover = 1.5 x q x (recent echo power) + noise floor. A residual more than 2x that in amplitude and over 250 RMS is a second voice: adaptation freezes (and also when it is merely 1.4x over, so the child is never learned as echo), no matter what. `q` is pessimistic after the retrospective pass (it saw the data), and a worse filter is trusted less at once. | Standard Geigel/ERLE-based protection, with the leftover referenced to the *recent* loudness because the residual lingers after a syllable ends. |
| Barge trigger | Loud residual for >= 120 ms, at least half of the frames speech to webrtcvad, then (veto) a candidate shift of the filter from GCC-PHAT between mic and reference is replayed over the last blocks; if that removes more than half of the residual it was the echo path moving (the toy slid), the filter is shifted and nobody is cut. | A residual that webrtcvad hears as speech is not enough: the toy's own leftover is speech too. |
| STOP | `hub.stop()` tells the canceller, which cuts the reference 40 ms after (`AEC_STOP_LATENCY_S`), and `PLAYED` refines it. Without the cut the rest of the clip would be subtracted from a speaker that is already silent, adding a phantom echo to the child's audio (tested). | |
| Drift | While converged, the filter's frequency response is sampled every second; the phase change between samples (300-3500 Hz, sub-sample) divided by the time is the speaker-versus-mic clock mismatch. The reference is then read at a slowly changing fractional delay (cubic interpolation), closed loop. Estimated -46 ppm for a simulated 40 ppm; ESP32 crystals are typically within +-20 ppm each. | A one-sample misalignment is already -13 dB at 3 kHz. |

Design differences from the brief's suggestion, and why: GCC-PHAT is also used per clip (warm start + narrow search) rather than only once; the filter is trained retrospectively on the search window; double-talk uses a pessimistic `q` and a freeze threshold below the trigger threshold; drift is tracked with a frequency-domain phase-slope estimator and a fractional-delay reference rather than integer tap shifting (that failed to follow even 40 ppm in the simulation); and the barge decision goes through a verify-by-replay step for echo-path moves.

## Simulation results (`.venv/bin/python tools/aec_sim.py`)

The rig (`tools/aec_sim.py`) models synthetic source-filter speech, mu-law, a decaying-noise room response with early reflections and a speaker/mic band-pass, listener clock offset and drift, WiFi jitter, stalls and 1% loss, a 45 ms PLAYING-before-first-sample lead and a 3 ms sync error, ambient noise, a child with a different voice and room path, and STOP cutting the speaker at the trigger (closed loop, two passes). The brain side is the real `AecManager` and `Segmenter`.

ERLE in dB while the toy talks and nobody else does (mean of 4 voice/room combinations; time since the toy started):

| case | 1-2 s | 2-3 s | 3-4 s |
|---|---|---|---|
| clean room | 10.1 | 15.6 | 19.7 |
| long reverb (rt60 0.5 s) | 8.2 | 12.5 | 14.8 |
| clock drift 40 ppm | 8.5 | 9.8 | 12.9 |
| noisy room (RMS 200) | 6.0 | 9.5 | 12.5 |
| clipping speaker | 4.7 | 6.4 | 8.0 |
| timestamp 40 ms off, 120 ms pipeline | 11.9 | 15.5 | 19.7 |

Barge-in (child speaks 2 s over the toy; level relative to the toy's echo at the listening mic): +6 dB cut in 8/8 runs, median 205 ms after the first word (worst 427 ms); 0 dB 8/8, median 426 ms (worst 1.5 s); -6 dB 6/8, median 956 ms. False barge-ins with no child: 0 of 40 clips (clean, reverb, clipping, drift, noisy). The child's utterance reaches the real `Segmenter` with its first word at the head (<= 0.14 s in) and whole.

Caveats: ERLE saturates at the speech's information content, not the filter's capability; the synthetic voice is more harmonic (hence slower to identify) than TTS speech, so real ERLE may be better or worse. The speaker nonlinearity is the real limit (8 dB in the clipping case). Not covered: a sudden *complete* change of the echo path (someone hugs the listening toy): the canceller recovers in ~1.5 s but the residual meanwhile looks like loud speech and can cut the toy once (the old loudness detector had the same weakness). A pure delay change is handled (shift-and-replay veto) about 60% of the time.

## Firmware: proposal, nothing flashed

The brain currently estimates where a mic frame sits in time from packet arrival (lower envelope). That works (the 40 ms / 15 ms-jitter simulation case is as good as the clean one, because GCC-PHAT absorbs it) but costs ~0.55 s of search on the pair's first clip. Two small firmware changes would make alignment direct:
1. `M` packet: append the capture time of the frame's first sample as `int64 esp_timer_get_time()` microseconds (8 bytes: 651 bytes per packet instead of 643, fine for the 2048-byte receive buffer). The brain would then convert with `clock_off` and skip the lower-envelope estimate. Old brains ignore trailing bytes only if they use `data[3:3+640]`; `atoms._handle` currently reads `data[3:]`, so the brain must be updated first or the Atom must use a new packet letter.
2. `PLAYING <us>`: stamp when the first sample is written to the I2S DMA instead of "right after playback is queued" (today it is early by the codec pipeline; the simulation assumed 45 ms).

Neither is needed for the current implementation. Ask before flashing.

## Hardware findings (Nov 12, Jetson + Dyno, Sage, Penny, volumes 255, quiet room, mics muted so nothing could cut)

ERLE per pair over one clip, from the brain's own log line (`aec dyno->sage: ... ERLE x dB`), ~35 clips of 1-2.4 s: **between -36 dB and +3.6 dB, i.e. no useful cancellation.** Mic level while the talker plays: Dyno -> Sage 450-570 RMS and Dyno/Penny -> others 80-240 (room noise 10-16, so the echo is audible), Sage as talker is almost inaudible at the others (RMS 10-15). The lag the search found for the same pair changed from clip to clip (Dyno -> Sage: 67, 148, 33, 21 ms), which a fixed room cannot do. False-trigger rate and barge-in latency were not measured: with ERLE ~0 there is nothing to measure (the old loudness detector would have been tested, not this), and I did not ask for the voice test.

Root cause, measured from RAM-only dumps of toy-vs-toy audio (deleted afterwards, no person was talking): **while a clip is being sent to the talker, the listening Atoms lose mic audio without any gap in `seq`.** The mic streams ran at 42-47 packets/s instead of 50 (sample time advanced 0.82-0.92 s per wall second) with zero sequence gaps, and the arrival times show the stall: a 330 ms silence followed by 4 packets at once. The firmware sends every captured frame and only then increments `mic_seq`; when `udp.endPacket()` blocks on a busy WiFi, `M5.Mic.record()` overruns and frames are dropped silently. So `seq x 320` is not a sample clock during exactly the period we need, and the packet count between the clip start and the echo is wrong by up to 250 ms, which is more than the filter can absorb. Brain-side mitigation added (`Listener.frame`, `STALL_S`): a packet later than 150 ms forgets the offset estimate and re-places the clip; it helps but did not rescue the pairs.

**Firmware change needed (not flashed, awaiting approval):** make `mic_seq` follow time: before sending a frame, `seq += max(1, round((now_us - last_send_us) / 20000))` style catch-up, or better append the capture `esp_timer_get_time()` of the frame to each `M` packet (see the proposal above; the brain reads `data[3:]`, so the brain side must accept 8 extra bytes first). Either makes the timeline exact, lost audio shows up as a known gap, and the existing canceller then only has the within-run alignment to do, which the simulation shows it can. A second improvement: stamp `PLAYING` when the first sample is written to I2S.

Also noted: a clip is only 1-2.4 s for typical lines, and the first lock needs ~0.65 s; warm starts need 0.45 s. Even when it works, the first part of each line falls back to the old detector.

## Firmware 3.7 (built and committed; flashing waits for the Jetson brain)

`firmware/toy-client` 3.7: every `M` packet is now 3 + 640 + 8 bytes, the last 8 being the `esp_timer` capture time of the frame's first sample (little-endian int64 us, same clock as `SYNCR`/`PLAYING`). The capture time chains slot to slot (20 ms apart) unless `record()` was called late, in which case the slot starts at the call time (the codec had nothing to fill). `mic_seq` advances by `round(dt / 20 ms)`, so dropped audio is a seq gap. `PLAYING <us>` is stamped queue time + one DMA buffer (`dma_buf_len / rate`, ~16 ms; an estimate, not measured). Brain: `atoms._handle` reads `data[3:643]` and the stamp if present (converted with `clock_off`); `Listener.frame(cap=...)` then places frames on capture time and skips the late-packet heuristic. Old 643-byte packets behave exactly as before. A brain without this change must not receive 3.7 packets (it reads 324 samples).

## Hardware measurement plan (re-run after the firmware change)

Plan once it is this session's turn, with the room quiet and nobody talking:
1. Deploy `brain/` and `tools/`, restart `sentient-brain`, `POST /mute` on localhost:8080 right after.
2. **ERLE:** run 5 canned scenes (`/canned?scene=...` on :8080, or `s <toy> <text>` lines of 4+ s) with all three toys on the hotspot, each toy as talker in turn. The brain logs one line per listener when a clip ends: `aec dyno->sage: ERLE 14.2 dB over the clip, lag 79 ms, residual/echo q=0.03, drift -11 ppm, barges 0, echo-path resets 0` (numbers only, nothing about audio). Grep the journal for `aec `.
3. **False-trigger rate:** the same run, nobody talking: count `barge-in:` lines (`through the echo canceller` = new detector, `loudness` = old fallback) against the number of clips.
4. **Latency and recall:** a person speaks over a toy at conversational loudness, ~20 trials, from 0.5 m and 2 m: time from first word to the toy falling silent (the dashboard turn log), and whether the utterance became a turn.
5. Report ERLE per pair (hardware sets how the real speaker's compression and nonlinearity behave), then tune `AEC_MU`, `AEC_DT_RATIO`, `AEC_MIN_RMS`, `AEC_STOP_LATENCY_S`.

Cost: retrospective training takes ~90 ms once per pair on a Mac core and blocks the UDP receive thread (the kernel buffers packets meanwhile); measure on the Jetson. If it is a problem, lower `PASSES` in `brain/aec.py`.

## Privacy

Everything is in RAM: ~4 s of frames per listener, the clip being played, filter state (a few hundred KB). Nothing is written to disk and the log lines carry only dB, ms and counts.

## Knobs (`brain/config.py`)

`SENTIENT_AEC=0` (off), `SENTIENT_AEC_MU`, `AEC_PARTS`, `AEC_SEARCH_S`, `AEC_PLACE_S`, `AEC_MIN_SCORE(_PLACE)`, `AEC_DT_RATIO`, `AEC_MIN_RMS`, `AEC_BARGE_MS`, `AEC_PREROLL_FRAMES`, `AEC_STOP_LATENCY_S`.

## How to resume the hardware measurement (paused Nov 12 by the user; hardware released)

State left behind: Jetson runs main's code (no `brain/aec.py` there), mics muted, toy speakers at volume 0, `SENTIENT_AEC_DUMP` unset, no dump files in `/dev/shm`. Nothing is half done on the toys.

To resume, only when the user says sound is allowed again and the firmware change (mic `seq` follows time, or a capture timestamp in `M` packets) is flashed and the brain reads it:
1. `rsync -a --exclude data --exclude __pycache__ brain/ sentient@sentient-jetson.local:/data/sentient/brain/` and `tools/`, then `sudo systemctl restart sentient-brain` and `POST localhost:8080/mute` at once. Set `SENTIENT_AEC=1` for the service (it is off by default); raise toy volumes to 255 (`/speaker?toy=X&vol=255`); set them back to 0 and re-deploy main when finished.
2. ERLE: `/say?toy=<t>&text=...` from each toy in turn (3 clips each, 12 s apart), mics muted; read `journalctl -u sentient-brain | grep "atoms      aec "` (one line per listener: mic rms, ERLE, lag, q). Success = ERLE over 10 dB with a stable lag per pair. Check mic frames/s in a dump (`SENTIENT_AEC_DUMP=/dev/shm`, toy-only audio, delete after): it must be 50 with the new firmware.
3. False triggers: unmute (`POST /mute`), no one talking, the same clips, count `barge-in:` log lines. Barge-in latency: ask the user to talk over a toy ~20 times at 0.5 m and 2 m.
Debug aid: `log.debug("aec search ...")` in `AecManager._acquire` shows each GCC-PHAT attempt (lag, score, mic/ref rms).

## Firmware 3.7 flashed; sound experiment PAUSED by the user (Nov 12, resume notes)

**State left behind:** all three toys run `toy-client-3.7` (flashed by OTA one at a time, each came back online), speaker volumes 0, mics muted (`/mute` state true), no dump files in `/dev/shm`. The Jetson runs this branch's `brain/` and `tools/` under `sentient-brain` (running, muted). The service has a drop-in `/etc/systemd/system/sentient-brain.service.d/aec.conf` with `SENTIENT_AEC=1` and `SENTIENT_AEC_DUMP=/dev/shm` (RAM dumps of toy-vs-toy audio while a clip plays): delete it and restart the service when finished. Idle banter is OFF (`POST /idle` toggled it); toggle again to restore. Note `POST /say`, `/speaker`, `/mute`, `/idle` need POST; `/mute` and `/idle` toggle; a service restart un-mutes the mics.

**What the 3.7 change fixed (measured):** the per-pair lag is now stable from clip to clip (dyno->sage 91, 91, 89, 89 ms; dyno->penny 56, 56, 55 ms; before: 67, 148, 33, 21 ms), and the listener timeline follows time (sample span equals wall span within 0.05 s). Lost mic audio is now a visible `seq` gap.

**What is still wrong (not solved):**
1. ERLE is still ~0 dB at volume 90-255 (`aec dyno->sage`: 0.0 to 0.6 dB; at 255 mic rms 4000-4400). At volume 40 one clip reached 9.3 dB / 4.7 dB, another -17 dB. Offline on the dumps, a 100 ms least-squares FIR per clip also only gets ~1 dB at 255, and magnitude coherence between the reference and the mic is 0.05-0.5 at all bands, so this is not a filter-tuning problem: the mic hears a speaker signal that is not a linear function of the clip (at volume 255 the mic has ~18 dB more energy above 1 kHz than the reference has, i.e. distortion or coupling; low frequencies are 25 dB under).
2. The listeners still lose audio: 2 bursts of 12-14 frames (~250-280 ms) per 7 s clip, at the same ~3 s spacing (1.67 s and 4.69 s into the clip), 26-53 missing frames per clip. Zero-filled holes inside the echo hurt coherence. Not yet known whether it is the listener's firmware stalling (periodic task or `endPacket` blocking) or WiFi/brain-side loss. The next check I was about to run: dump both listeners for one clip and compare the gap times in brain time (same time at both listeners = brain/WiFi side; different = per toy firmware).
3. The `PLAYING` stamp (queue time + one DMA buffer) is unmeasured.

**Next steps when resumed** (needs the user's go for sound): run the gap-time comparison; try the experiment at volume 40-90 where the echo is still linear (A talks, B listens and cancels, C speaks as the "child" at the same time, check B's residual carries C and not A); if the speaker is the nonlinear part, cap the toy volume for AEC use or model it. The experiment's literal goal (B fully hears C while A talks) has not been reached.

## Nov 14: root cause of the lost mic audio found and fixed (firmware 3.9); first WER trials

**Root cause:** the toys' `HELLO` (every 3 s) called `clip_count()`, which scanned the LittleFS `/clips` directory: ~250 ms with 36 clips (Sage), less with 19-20 (Penny, Dyno). The mic loop starved, `M5.Mic.record()` overran, and 12-14 frames (Sage) or 4-7 (Penny) vanished every 3.0 s. Different listeners had gaps at different times, which is how it was found. **3.9 caches the clip count** (invalidated on upload/delete). Firmware 3.8 (HELLO broadcast only until the brain is known) was a wrong first guess but is harmless and kept. After 3.9 two listeners over a whole clip showed **0 missing frames** (before: 26-53 per 7 s clip). All three toys run 3.9.

**ERLE after the fix** (vol 70/100, one trial per row, child text plays 2.5 s into A's 5-7 s line): dyno->penny 12.7 dB, dyno->sage 12.9 dB with lag stable (40 / 32 ms); sweep rows 13.7, 8.9, 7.2 dB (earlier, with the stalls: about 0 dB). Cancellation works whenever the echo is audible at the listener.

**Child intelligibility (WER vs the true text, faster-whisper base.en on the Mac, `tools/aec_wer.py`):** with the child at a normal level the child is already understood from the raw mic (WER 0.0-0.2), and the canceller output is equal or better (one row: raw 1.0, out 0.0). Rows still failing at modest volume are physical, not the canceller: **Sage is too quiet as a speaker** (Sage as talker is not heard by Dyno, no pair forms; Sage as child is not heard by Penny: WER 1.0 raw and out). Not tested because the user asked for modest volumes: Sage at 200.

**Tools added:** `/aec_trial` brain endpoint (`a`, `c`, `atext`, `ctext`, `delay`; needs `SENTIENT_AEC=1`; A speaks through the normal path, C plays straight to its speaker), the dump now also stores the canceller's output and the trial notes, `tools/aec_experiment.py A C` (one trial, scored), `tools/aec_sweep.py [vol_a vol_c]` (all six rotations), `tools/aec_wer.py` (scoring only; run on the Mac, the Jetson has no faster-whisper).

**End state:** volumes 0, mics muted, `aec.conf` drop-in REMOVED (AEC off, no dumps), brain running this branch, idle banter on (default). To resume: recreate the drop-in (`SENTIENT_AEC=1`, `SENTIENT_AEC_DUMP=/dev/shm`), restart, `POST /mute`, `POST /idle` (off), set modest volumes.

**Still open:** barge-in latency/false triggers (mics were muted so the segmenter never ran; `barges` counts in the log are the canceller's own detector and fired 0-6 times per trial, including with a child that plays on the same toy), multiple trials per row for statistics, Sage's speaker level, and the unmeasured `PLAYING` offset.

## Nov 14 (later): Sage fixed, all rotations, offline tuning

Sage was reseated by the user (audible at 120+). Every trial ran behind a hardware guard (`aec_experiment.guard()`: /status spk_fail/mic_fail of all three toys must equal the baseline Sage 6/4, Dyno 0/0, Penny 0/0, else stop). No counter ever rose. Volumes used: talker Dyno/Penny 70, Sage 120 (160 made Sage's echo nonlinear: ERLE ~6 dB and the child suppressed); child Dyno/Penny 100, Sage 120. Muting uses `POST /mute?on=1`.

Hardware results (2 reps per rotation, whisper WER of the canceller output against the child's text): 10 of 12 trials gave WER 0.0-0.2. The weak rows: sage talks, dyno listens, penny child (WER 1.0 in 1 of 2) and dyno talks, sage listens with a loud penny child (ERLE -2 dB; the same pair gives 17 dB with the child after the clip and 12-16 dB with the child at 70, so a child much louder than the echo derails the filter: double-talk handling). ERLE varies a lot between reps of one rotation (e.g. -2.3 then 13.8).

Offline tuning (`tools/aec_corpus.py` records real trials, `tools/aec_replay.py` replays them, `tools/aec_tune.py` runs one change per iteration, keep only if ERLE +0.5 dB with WER and leakage not worse; progress in `/tmp/aec-progress.log`). Replay baseline over 12 recorded trials: ERLE 8.46 dB, WER 0.067, leak 0.00. Iterations: AEC_PARTS 12 (6.44 dB, WER 0.14), PRE 320 (8.53, 0.075), AEC_MU 0.3 (8.72, WER 0.03), AEC_MU 0.8 (-4.14). **None kept; stopped after 4 rejected in a row.** MU 0.3 is the only one worth a second look (WER better, ERLE +0.27). Not tried (need code, not a knob): comfort-noise handling, a double-talk detector that tracks the child's level, the remaining candidates in `aec_tune.py`.

End state: volumes 0, mics muted (verified from /state), idle banter on, `aec.conf` drop-in removed (AEC off), no dumps in /dev/shm, brain runs this branch merged with main. To resume: recreate the drop-in, restart, `POST /mute?on=1`, `POST /idle` (toggle), set volumes.
