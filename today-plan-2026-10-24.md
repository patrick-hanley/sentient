# Today: Gemma Hardware Hackathon — Saturday, Oct 24, 2026 (rev. 9:10 AM)

**Event:** 10:00 AM–5:00 PM PT, doors 9:30 AM. AGI House, 1868 Floribunda Ave, Hillsborough.
Parking on the golf-course side of Eucalyptus Street. Track: Physical AI, IoT & Robotics.
Science-fair judging; top 6 demo on stage. Prizes: $60,000 total (Best in Show $15,000,
Track $15,000, Best Use of LiteRT $15,000, plus hardware awards incl. Best Use of Raspberry Pi).

**Architecture: the brain is OUT of the toys.** Three identical AtomS3R-CAM clients
(mic + speaker + **camera on all three**) stream to one table-side brain.
- **Ears:** hands-free. Voice detection runs on the brain (webrtcvad); the same speech reaches all
  three mics, and the loudest mic counts as the toy being addressed.
- **Eyes:** every toy knows what it is looking at: the child, a familiar family member, a pet,
  another toy (ArUco tag on its chest), or a book.
- **Mind:** Gemma 4 E2B on **LiteRT-LM** hears the child's audio directly (no separate
  speech-to-text) and gets a text summary of what each toy sees. Sage also gets her camera frame.
- **Voice:** Piper, a distinct voice per toy.
- **Perception models:** MediaPipe pet and book models (LiteRT) plus OpenCV YuNet/SFace for faces.
  Together with LiteRT-LM, this is the "Best Use of LiteRT" story.

## Code (all in `~/Downloads/sentient/`)
| Path | What |
|---|---|
| `firmware/toy-client/toy-client.ino` | One firmware for all 3 Atoms. Compiled OK. UDP mic stream, `/capture`, `/play`, `/status`. **Turns on the Voice Base audio (`atomic_echo`), which the old v1 sketch never did.** |
| `brain/` | `python -m brain.main` — voice detection, perception, director, Piper, LiteRT-LM or llama.cpp. Dashboard on `:8080` (live annotated cameras, mic meters, canned-scene button, enroll-from-camera). |
| `tools/atom_probe.py` | Mac-side Atom test: HELLO, camera JPEG, mic meter, test chirp. |
| `tools/setup_brain.sh` | Run on the Pi/Jetson: offline pip install, model copy, `sentient-brain` hotspot. |
| `tools/copy_to_usb.sh` | Copies everything plus the .litertlm model to your USB drive. |
| `aruco_sheet.pdf` | Toy tags: id 1 Pip, 2 Sage, 3 Noodle (two of each). **Print at 100%.** |
| `offline/` | Wheel sets for the Pi (py3.13) and Jetson (py3.10), Piper voices, vision models, the Mac-fallback Gemma GGUF + llama.cpp + faster-whisper. |

## Verified at home (9:10 AM)
- ✅ Gemma 4 E2B .litertlm on the Mac, 2,588,147,712 bytes.
- ✅ Firmware compiles for M5AtomS3R (OPI PSRAM, USB CDC on boot).
- ✅ Brain selftest on the Mac:
  - 3 Piper voices render in about 0.2 s per line.
  - The ArUco sheet detects PIP, SAGE and NOODLE.
  - The Mac-fallback Gemma answers in the right `HEARD:/PIP:` format.
- ⚠️ **Gemma 4 "thinks" by default** (+8 s per turn). It's disabled in both backends
  (`ThinkingConfig(enable_thinking=False)` / `enable_thinking: false`).
- ❌ **Correction:** LiteRT-LM has no Intel-Mac build, so the Mac emergency brain is llama.cpp +
  faster-whisper (about 5 s per turn). Still Gemma, still on-device.
- ✅ **Kit 1 flashed, hardware self-test passes** (serial):
  `Camera init OK (SCCB port 0)` · `Camera frame OK 320x240` · `Mic self-test: rms=95 peak=460` · chirp played.
  Three firmware fixes were needed:
  1. **GC0308 has no JPEG encoder:** capture RGB565 and encode in `/capture`.
  2. **Camera on I2C bus 0 via `Wire`:** the default bus 1 belongs to the codec.
  3. **Mic in stereo mode:** the ES8311 data sits in the other I2S slot, so mono read all zeros.
  Also, the real MAC is read from eFuse; before Wi-Fi starts every Atom reported `A5:A5:…`.
- ⏳ **Not yet done:** Wi-Fi probe (needs SSID/password), kits 2–3, tags printed, USB copy.

## Timeline
| Time | Action |
|---|---|
| Before leaving | Flash kit 1 → `atom_probe.py` (mic level, chirp, JPEG). Flash kits 2–3. Print tags. `bash tools/copy_to_usb.sh /Volumes/<USB>`. |
| 9:30–10:00 | Hardware check-in FIRST: **Jetson Orin Nano** (24 tok/s, 0.9 s to first token on GPU) > Pi 5 (7.6 tok/s, use `--cpu`) > Pixel. Take Pi + Jetson if allowed. |
| 10:00–11:00 | Brain: copy `sentient/` → `bash tools/setup_brain.sh` → `python -m brain.main --selftest` → `python -m brain.main`. Atoms join `sentient-brain`; the dashboard shows 3 toys online. One full voice loop. Canned scene armed (long-press any Atom or the dashboard button). |
| 11:00–12:30 | Mount cameras on all three toys (eye-socket or Velcro harness, lens flush, no stuffing in front). Tags on chests. Enroll yourself live (dashboard → Enroll). Enroll family and pets from phone photos (`enroll/people/<Name>/`, `enroll/pets/<Name>/`, then `python -m brain.enroll --from-dir enroll/`). |
| 12:30–3:30 | Tune: voice-detection thresholds for the room (`brain/config.py`), personas, greetings, idle banter, Sage reading the picture book (`SENTIENT_VISION=sage`). |
| 3:30–4:00 | Code freeze. Rehearse: canned scene → free chat → phone-photo "Is that Grandma?" → toys noticing each other. |
| ~4:00–5:00 | Judging. Point judges at the dashboard: it shows exactly what each toy sees. |
| 5:00 | Return ALL loaners. `python -m brain.enroll --wipe` (delete face/pet embeddings). |

## Decision tree
- **No Jetson** → Pi 5 loaner (`--cpu`). Turns take about 8–10 s; the instant filler ("Ooh!") masks the wait.
- **No Pi either** → Mac brain: `.venv/bin/python -m brain.main --backend llamacpp`
  (no pet detector on the Mac; faces and tags work).
- **Voice detection triggers on room noise** → `VAD_AGGRESSIVENESS=3`, raise `ENERGY_FLOOR`
  (watch the dashboard meters). Last resort: mute mics on the dashboard and run the canned scene.
- **Camera fails on an Atom** → the firmware retries with the other SCCB port, then a
  camera-first boot, then runs audio-only. That toy's scene line reads "eyes are closed." The demo survives.
- **Wi-Fi hotspot trouble** → phone hotspot (iPhone: Maximize Compatibility ON = 2.4 GHz). Put its
  SSID/password in the firmware's `WIFI_LIST` slot 2. Brain and Atoms join it; still no cloud.
- **Model missing on the brain** → `offline/model/` on your USB, or the venue drives. Never download on venue Wi-Fi.
- **Power banks missing** → Atoms tethered to USB at the table; untethered is a nicety.
- **Plush missing** → bare Atoms with the printed tags plus the table sign; the dashboard carries the "eyes" story.

## Rules that still bind
- A Gemma model, fully on-device, no cloud anywhere in the loop (Atom ↔ brain is LAN only).
- **No audio stored:** utterances live in RAM or `/dev/shm` and are deleted right after Gemma reads them.
  The dashboard shows only the last heard line, in memory.
- Face and pet embeddings stay on the brain and get wiped at the end. No real kids at the event.
  No educational-efficacy claims.

## Pack checklist
- [ ] Laptop + charger
- [ ] USB drive with `sentient/` + `offline/model/model.litertlm` (run `tools/copy_to_usb.sh`)
- [ ] 3× Atoms (kit 1 probed; kits 2–3 flashed)
- [ ] Printed ArUco tags (+ tape/safety pins)
- [ ] 3× Anker Nano banks, charged
- [ ] 3 plush
- [ ] 4× USB-C **data** cables, power strip
- [ ] Picture book + letter cards (Sage reads; the canned scene uses the letter B)
- [ ] Table sign / persona cards
- [ ] Phone with family and pet photos (for enrollment + the "Is that Grandma?" moment)
