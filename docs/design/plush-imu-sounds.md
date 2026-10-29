# Plush toys: IMU-triggered fixed sounds

Status: DESIGN ONLY — not flashed to the Atoms, not pushed to Git.
Update Oct 29: a v1 patch implementing this design exists in
`imu-patch/` (see its README). In v1, local clip names are generic
(`imu_snore`, `imu_toss`, …) with per-toy audio, and friends'
reactions go through Gemma like other events — not pre-rendered
friend clips. That README, not this file's clip-name note, is the
current implementation reference.
It is written to fit the system as it actually is today, so it can be
implemented without redesigning the brain.

## What is already true (checked in the repo, Oct 29)

- The Atoms are M5Stack AtomS3R-CAMs. They DO have an IMU: a BMI270
  6-axis IMU (accel + gyro, I2C 0x68) plus a BMM150 magnetometer.
  Source: M5Stack AtomS3R-CAM spec.
- The current firmware (`firmware/toy-client/toy-client.ino`) uses
  NO IMU code at all — grep for imu/accel/gyro/mpu returns nothing.
  So this is new firmware work, not a setting flip.
- "Fixed sounds" on an Atom today = clips in LittleFS (`/clips/*.ul`,
  8-bit mu-law, 16 kHz, ~1.5 MB partition), played with
  `POST /playclip?name=N`, listed with `GET /clips`.
  The "hello" clip is the existing example: it plays from flash with
  no brain reachable.
- The brain already has an event path this can reuse: the Atom sends
  `BTN click` / `BTN hold` over UDP, and `brain/director.py`
  `on_button()` turns those into queued events / canned scenes.
  An IMU event should be a third message of the same shape, e.g.
  `IMU on_back`, `IMU tossed`, so the director can queue a
  friends-react turn the same way it queues a tap.
- While any toy speaks, all mics are muted. So a friend's reaction
  must go through the director's event queue (like a tap), never
  straight over a child speaking.

## Two layers — do not mix them up

1. **Local, on the moved toy itself (works with no brain).**
   Short clips stored in that toy's flash. Instant, no Wi-Fi, no TTS.
   This is the snore, the toss yell, the "oof!", the giggle.
2. **Brain-mediated, from the other two toys (needs the brain).**
   The moved toy sends one `IMU <event>` UDP message. The director
   queues one short reaction turn from the other toys, in character.
   If the brain is offline, layer 1 still works and layer 2 simply
   does not happen. No friend should comment more than once per
   episode.

## Calibration first — "on its back" is not a fixed number

The Atom's orientation inside each plush is not known, so "upright"
cannot be hard-coded. On first boot (and on a dashboard "calibrate"
button, if added), each toy records its own upright gravity vector
for 2 seconds while sitting normally. Every later reading is compared
to THAT toy's reference:

- on_back = gravity vector roughly opposite the upright reference
  (dot product < -0.7), held continuously.
- upright = dot product > 0.7 with the upright reference.
- tossed = freefall (total accel < 0.3 g for > 80 ms) followed by a
  landing spike (> 2.0 g) within 500 ms.
- shaken = 4+ direction reversals in 1 second, peak accel > 1.5 g.
- spun = gyro magnitude > 300 deg/s sustained > 0.5 s.
- rocked = gentle, periodic sway, peak accel 1.1–1.4 g, period
  0.8–2.0 s, for > 4 s.
- dropped / tipped = single spike > 2.0 g with no preceding freefall.

All thresholds below are starting values to tune by ear and by
log, not measured values. Nothing here should fire on a single
sample — every event needs its hold time, or normal carrying will
set it off constantly.

## Event table

Cooldowns are per toy, per event. A snore loop stops the moment the
toy is upright again; it does not wait for a timer.

### 1. On its back — held > 3 s

Local (the sleeping toy, looped softly until upright):
- Dyno: deep, slow dino snore — "Zzz… rawr-zzz… Zzz…"
- Sage: soft, even unicorn snore — "mmm-zzz… mmm-zzz…"
- Penny: squeaky penguin snore — "honk-zzz… honk-zzz…"

Friends react, once per sleep episode, in character:
- Dyno, about Sage or Penny asleep: "Shhh! Somebody's dreaming.
  I will be extra quiet. Rawr… quietly."
- Sage, about Dyno or Penny asleep: "Oh, they're asleep. Let's keep
  our voices soft, like a library."
- Penny, about Dyno or Sage asleep: "Hee hee! Listen to that snore!
  Shhh — don't wake them up!"

### 2. Tossed in the air

Local (the tossed toy, played on landing):
- Dyno: "WHEEE! Again! Again! Rawr!"
- Sage: "Whoa! That was higher than my bookshelf!"
- Penny: "WHEEE-HONK! I can fly! …almost!"

Friends react (cooldown 10 s):
- Dyno: "I saw that! Ten out of ten for airtime!"
- Sage: "Wow! And please land on something soft!"
- Penny: "Did you see that? I was basically a penguin rocket!"

Note, in character rather than as a lecture: Sage's "land soft"
line is the gentle-play cue. Do not add a separate safety lecture.

### 3. Shaken

Local:
- Dyno: dizzy giggle + wobbly "Whoa-oh-oh!"
- Sage: "Whoa, whoa — my pages are all mixed up!"
- Penny: squeaky giggle + "Hee hee hee, I'm all wiggly!"

Friends react:
- Dyno: "Shake, shake! Are you a maraca now?"
- Sage: "Gently, gently — let's un-shake and sit down."
- Penny: "Again! Again! No wait… I'm dizzy. Hee hee."

### 4. Rocked / cradled — gentle sway > 4 s

Local (soft, low volume):
- Dyno: low sleepy hum, "hmm-hmm, rawr…"
- Sage: soft lullaby hum, "la-la, la-la…"
- Penny: sleepy squeak-hum, "honk… la-la…"

Friends react (only if another toy is also awake and the child
is not speaking):
- Dyno: "Rock-a-bye, friend. Shhh."
- Sage: "That's a nice, slow rock. Like a story boat."
- Penny: "Sway, sway… I'm getting sleepy just watching!"

### 5. Dropped / tipped over

Local (single, short):
- Dyno: "Oof! Rawr… I'm okay!"
- Sage: "Oh! I tumbled! My pages are fine."
- Penny: "Whoa-honk! I fell over!"

Friends react:
- Dyno: "You okay, friend? That was a big tumble!"
- Sage: "Are you hurt? Let's check — paws, ears, tail, all there?"
- Penny: "Oops! Up you get! Hee hee, that was a funny fall!"

### 6. Spun around

Local:
- Dyno: "Whoa! The room is spinning! Rawr!"
- Sage: "Everything is going round and round…"
- Penny: "Wheee! I'm a spinning top! Honk!"

Friends react:
- Dyno: "Spin, spin! Don't fall over!"
- Sage: "Stop when the world stops spinning, okay?"
- Penny: "I want a turn! Spin me next!"

### 7. Upside down (briefly, < 3 s — so it is not the sleep event)

Local:
- Dyno: "Whoa! The world is upside down!"
- Sage: "Hmm, everything looks different from here."
- Penny: "Hee hee! The ceiling is the floor!"

Friends react:
- Dyno: "You're upside down! That's a funny view!"
- Sage: "Careful — upside-down toys sometimes bonk."
- Penny: "Flip! Flip! Do it again!"

### 8. Woken up — upright again after a sleep episode

Local (once, not looped):
- Dyno: big stretch + "Mmm… rawr! Did I nap?"
- Sage: sleepy yawn + "Oh… was I dreaming about books?"
- Penny: "Honk-yawn! I'm awake! What did I miss?"

Friends react:
- Dyno: "Welcome back! You snored like a champion!"
- Sage: "Good morning, sleepyhead. Dream anything good?"
- Penny: "You're awake! Hee hee, you missed nothing. Except my joke."

## Clip budget (mu-law, 16 kHz = 1 byte/sample)

- A 2-second clip = ~32 KB. A 4-second snore loop = ~64 KB.
- Local clips per toy: snore loop + toss yell + shake + rock hum
  + drop + spin + upside-down + wake = 8 clips, roughly
  2–4 s each, ~300–400 KB per toy.
- That fits inside the ~1.5 MB LittleFS partition alongside the
  existing "hello" clip, with room left — but the exact headroom
  depends on what clips are already on each Atom, so check
  `GET /clips` on each toy before uploading, and do not assume
  the full 1.5 MB is free.
- Friends' reaction lines are NOT stored on the moved toy. They
  are either normal brain TTS lines (the usual path) or, if
  pre-rendered for speed, clips stored on the reacting toy under
  names like `imu_friend_sleep`, `imu_friend_toss`, etc.

## Implementation order (not yet done)

1. Firmware: BMI270 driver (I2C 0x68), 20 ms sampling, upright
   calibration, event detector with the hold times and cooldowns
   above, local `/playclip` for layer 1, one `IMU <event>` UDP
   message for layer 2. No IMU data is stored, and no audio is
   stored — same no-audio-stored rule as the rest of the brain.
2. Brain: `brain/atoms.py` parses `IMU …` like `BTN …`;
   `brain/director.py` gets an `on_imu(toy, event)` that queues
   one friends-react turn, with one-reaction-per-episode guarding.
3. Clips: render the local lines in each toy's own voice
   (Dyno Kitten Jasper / Sage Piper alba / Penny Kitten Rosie is
   the approved mix to restore — see the live A/B notes), upload
   via `PUT /clip`, verify with `GET /clips` and a live test:
   lay a toy on its back, toss it gently, shake it, and check
   that (a) the local sound plays, (b) friends comment once,
   (c) nothing fires while the toy is just being carried.
4. Only then: flash the Atoms, pull the brain change to the Pi,
   restart the brain service.

## What this deliberately does NOT do

- No continuous IMU streaming to the brain. One short event
  message per episode, or Wi-Fi and battery both suffer.
- No IMU-based speaker separation or child tracking. This is
  toy-state only (on back, tossed, shaken…), not person tracking.
- No new privacy surface: IMU events say what the toy did, not
  where the child is or what the child said.
