# IMU motion sounds: what was built

Design input: [design/plush-imu-sounds.md](design/plush-imu-sounds.md). This page is the implementation reference.

## How it works

1. **Firmware 3.5** (`firmware/toy-client/`): `imu_events.h` is a dependency-free C++ detector fed 50 Hz accel/gyro samples
   from the BMI270 (via `M5.Imu`). On an event the toy (a) sends one UDP `IMU <event>` to the brain and (b) plays its own
   flash clip `imu_<event>` at once, so the sound works with no brain and no Wi-Fi. A snore loops softly (55% volume,
   a breath between snores) while the toy lies still, and stops the moment it is upright.
2. **Brain** (`brain/atoms.py`, `brain/director.py`, `brain/scripted.py`): `Director.on_imu` makes the *other* toys react
   once, in character, from cached lines (about 0.1 s instead of a 6 s Gemma turn). The moved toy never comments on itself.
3. **Clips**: `sync_imu_clips` (brain/main.py) renders each toy's 8 motion sounds in its own voice and stores them under
   fixed names `imu_<event>` *before* the sound effects. Which text/voice each was made from is kept in
   `brain/data/imu_clips.json`, so changing a voice or a line re-sends just that clip. If the flash is too full the toy's
   clips are cleared once and refilled in priority order (sound effects that no longer fit stream from the Pi, as before).

Events: `sleep`, `woken`, `tossed`, `shaken`, `rocked`, `dropped` (also "tipped over"), `spun`, `upside_down`.

## Improvements over the design

| Design | Built | Why |
|---|---|---|
| Sleep = gravity opposite "upright" for 3 s | Sleep = **lying down in any direction and still** for 3 s (more than ~70 degrees from upright, accel within 1 g +-0.08 and gyro < 20 dps) | A real sleeping toy lies on its side or back; a toy being carried sideways is not still, so it never snores |
| Toss needs a >2 g landing | Also counts a **long flight (>= 180 ms) caught softly** (>= 1.5 g) | A child catching a toy gently is still a toss |
| Dropped = single spike | Also **tipped over** (upright to lying within 1.5 s with a >= 1.4 g bump) | Toppling is the most common "drop" |
| Calibrate on first boot | **Learns only from 2 s of real stillness**; a provisional pose is learned automatically, flagged `imu=1` in HELLO, and a parent confirms it with the dashboard **Calibrate** button (`imu=2`); stored in NVS | A toy that was moving at boot would otherwise calibrate wrongly |
| Friends react through Gemma | **Fixed cached lines**, two variants each, `{name}` of the moved toy, once per episode (nobody comments twice in a sleep), a flurry limiter (max 4 reactions a minute, 5 s apart), dropped (not queued) if a child is speaking or a turn is running | Instant, no model variance, no chorus |
| (not specified) | Mics stay off while a toy plays its own clip (`PLAYING`/`PLAYED` without a brain-initiated play) | Otherwise the other toys hear the snore as the child |
| (not specified) | The IMU is also polled **during playback** | A toss while a toy is talking would be missed |

## Tests

* `tools/test_imu.py` compiles the real detector header with the host C++ compiler and replays 21 synthetic traces
  (carried upright, carried sideways, sleep then wake, brief upside-down, toss, soft catch, tiny hop, drop, tip, shake, spin,
  rock, short sway, cooldown, uncalibrated, and four regressions found in review: a wake-up colliding with another event,
  the 49-day millis() wrap, a wobble around the upside-down threshold, and re-calibration). Run: `.venv/bin/python tools/test_imu.py`.
* `tools/test_scripted.py` covers the brain side: episode rules, flurry limit, nobody-speaks-over-a-child, hub IMU and
  mute messages, clip sync (upload, stale re-upload, make-room clear, firmware gate).
* The firmware compiles (`arduino-cli`, 39% of flash) but **has not been flashed**.

## Review

An independent review found, and these are fixed: a SLEEP/WOKEN that collided with another event on the same sample could be
swallowed (the toy then snored forever; now deferred one sample); a data race on `play_buf` between the toy's own clips and
an HTTP upload (now a seq_cst claim protocol, `take_buf()`/`local_claim`); WOKEN cutting off the brain's speech (only a snore
is stopped now); a toss while asleep making no yell (the yell now preempts the snore); a brain play ending elsewhere unmuting
the mics during a toy's own clip (per-toy `local_until`); a lost wake-up silencing later sleep reactions (cleared first,
expires after 30 minutes); `millis()` wrap hazards; state left over across re-calibration; upside-down re-firing; the
snore delaying `/play`; and a toy's own clip polluting the running turn's latency marks.

## What is NOT verified (needs the toys)

* That the BMI270 answers on the AtomS3R-CAM + Echo Base I2C bus through `M5.Imu` (the serial log prints `IMU: enabled` or `NOT FOUND`).
* All thresholds in `imu_events.h` `Config` are starting values, tuned only against synthetic traces. Tune by watching
  the serial log (`IMU event: tossed`) and adjusting. A speaker vibrating the unit at high volume may add noise.
* The sound of the clips (TTS of "Zzz..." and similar): listen and adjust the text in `brain/scripted.py`.

## Deploy checklist (not done yet)

1. Flash firmware 3.5 over Wi-Fi: `python tools/ota.py --ssh sentient@192.168.2.5` after building: `arduino-cli compile --fqbn m5stack:esp32:m5stack_atoms3r:CDCOnBoot=cdc,PSRAM=opi --build-path /private/tmp/claude-501/fwbuild firmware/toy-client` (the Arduino IDE bundles arduino-cli; `tools/ota.py` reads `toy-client.ino.bin` from that build path).
2. Deploy the brain (`rsync brain/ tools/`), restart `sentient-brain`; the clip sync stores the motion clips on each toy (clears the flash once if needed).
3. Stand each toy upright and press **Calibrate** on the dashboard (Motion sounds panel).
4. Use the **Test** buttons, then lay a toy down, toss it gently over a bed, shake it, and carry it around to confirm nothing fires while carrying.
5. Speakers read volume 0 after a flash or restart: set them back (`POST /speaker?toy=X&vol=200`).
