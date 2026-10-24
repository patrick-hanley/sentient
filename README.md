# Sentient Toys

Three plush toys — **Dyno** (a curious green dinosaur), **Sage** (a baby in a unicorn costume, the reader),
**Penny** (a silly penguin in a white hat, confidently wrong) — that
listen hands-free, see who they're looking at, and talk with a child. Built at the
[Google Gemma Hardware Hackathon](https://www.agihouse.org/events/the-google-gemma-hardware-hackathon),
AGI House, Oct 24 2026. Everything runs on-device; no cloud anywhere in the loop.

```
AtomS3R-CAM + Voice Base (x3, same firmware)        Brain (Jetson Orin Nano / Raspberry Pi 5 / Mac fallback)
 mic 16 kHz ──UDP──────────────────────────────────▶ voice activity detection → loudest mic = addressed toy
 GET /capture (QVGA JPEG) ◀── 1–2 fps ─────────────── perception: faces (YuNet+SFace, enrolled family),
                                                      toys (ArUco tags), pets/books (MediaPipe on LiteRT)
                                                      director → Gemma 4 E2B on LiteRT-LM (hears audio directly)
 POST /play (16 kHz PCM) ◀───────────────────────── Piper TTS, one voice per toy
```

## Layout
| Path | What |
|---|---|
| `firmware/toy-client/` | Arduino sketch for all three Atoms (M5AtomS3R, OPI PSRAM, USB CDC on boot). Copy `secrets.example.h` → `secrets.h`. |
| `brain/` | `python -m brain.main` — VAD, perception, director, LLM backends, Piper, dashboard on `:8080`. |
| `tools/fetch_offline.sh` | Downloads models, voices and aarch64 wheelhouses into `offline/` (not committed). |
| `tools/setup_brain.sh` | On the Pi/Jetson: offline install, model copy, `sentient-brain` hotspot. |
| `tools/atom_probe.py` | Mac-side Atom test: discovery, camera, mic level, playback. |
| `tools/make_aruco_sheet.py` | Printable toy tags (id 1 Dyno, 2 Sage, 3 Penny). |
| `today-plan-2026-10-24.md` | Hackathon-day plan and decision tree. |

## Run
```bash
bash tools/fetch_offline.sh                 # once, on a fast network
python -m brain.main --selftest             # voices, vision, LLM
python -m brain.main                        # add --cpu on a Pi 5; --backend llamacpp on an Intel Mac
```

## Hardware notes (learned the hard way)
- GC0308 camera has **no JPEG encoder** → capture RGB565, encode in `/capture`.
- esp32-camera takes I2C port 1 with its own pins, which is the ES8311 codec's bus → open port 0 on the
  camera pins (`Wire`) and pass `pin_sccb_sda = -1, sccb_i2c_port = 0`.
- The Echo/Voice Base ES8311 puts ADC data in the I2S slot M5Unified's mono mode doesn't read → set
  `Mic.config().stereo = true` (record() still returns mono).
- `cfg.external_speaker.atomic_echo = true` or the base's mic/speaker stay off.
- `WiFi.macAddress()` is junk before Wi-Fi starts → use `esp_read_mac()`.
- Gemma 4 thinks by default (+8 s/turn) → `ThinkingConfig(enable_thinking=False)`.

## Privacy
No audio is stored (utterances live in RAM/`/dev/shm` and are deleted after Gemma reads them).
Face/pet embeddings stay on the brain in `brain/data/` (git-ignored); wipe with `python -m brain.enroll --wipe`.
