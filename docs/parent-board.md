# Parent Board: what was built

Design input: [design/parent-updates-design.md](design/parent-updates-design.md). This page is the implementation reference.

A website on the brain, **port 8090**, for a parent to tell the toys about a child (interests, schedule, homework,
boundaries), to send live cues ("time for dinner"), and to delete anything. Local only: nothing is uploaded, synced or
sent to a cloud model.

## Pieces

| File | What it is |
|---|---|
| `brain/parent.py` | Encrypted profile store, PIN/lockout/sessions, expiry, rules parser, the private prompt notes, worksheet reader |
| `brain/parent_web.py` | The web server and the single-page UI (own port, own handler, separate from the open dashboard on 8080) |
| `brain/scripted.py` | Cue chips and their fixed in-character lines, the cue matcher, the leak guard |
| `brain/director.py` | `cue()`, `interrupt()`, `play_scripted()`, notes in the prompt, leak guard on spoken lines |
| `brain/llm.py` | `LiteRTBackend.complete()`: a stateless call in a throwaway conversation (used for freeform cues and photos) |
| `tools/test_parent.py`, `tools/test_scripted.py` | 55 tests |

## How a parent uses it

Open `http://<brain-ip>:8090` on the home network. First visit: enter the **setup code** (printed once in the brain's log:
`journalctl -u sentient-brain | grep "setup code"`), then choose the family PIN: **8+ digits, or 6+ characters with a letter**
(a short phrase is stronger). Then:

* **Which child is playing?** Add children (first name only), tap **Playing now**. The toys use that child's notes for the
  session (ends after 30 idle minutes; nobody bound means generic play).
* **Say it now.** One tap on a chip (dinner, bedtime, bath, homework, leaving, quiet time, snack, story, clean up, visitor)
  plays fixed in-character lines instantly. Anything typed goes to Gemma ("interpret, do not repeat, do not say who said it").
  "Stop everything now" cuts the toys' speech and drops what they were saying; otherwise the cue plays at the next line
  boundary and the reply resumes. Cues are ephemeral: nothing is stored, nothing is logged (not even the text), and nothing
  is queued if no toy is online.
* **Tell the toys.** Type a sentence ("Spelling test Friday, she loves space, and soccer is Tuesdays at four."), get cards,
  tap to remove wrong ones, **Save**. Or tap chips. Or photograph a worksheet (read by the local Gemma, shown as cards, the
  photo deleted at once).
* **Weekly check-in** (day/time chosen by the parent): items due for re-confirmation say "still true"; delete the rest.
* **Settings**: pause the notes, change the PIN, lock, delete everything.

## Improvements over the design

1. **Its own port (8090).** The dashboard on 8080 has no login and can mute, speak and change voices; the board needs a PIN
   and has stricter headers. It is not linked from the dashboard.
2. **PIN wraps a random key (DEK/KEK).** Profiles are encrypted with a random 256-bit key; the PIN only wraps that key
   (scrypt, AES-256-GCM). Changing the PIN re-wraps one blob and leaves profiles untouched; "delete everything" destroys the
   wrapped key first (crypto-erase), then overwrites and unlinks every file.
3. **Honest PIN policy.** The design said a 4-digit PIN protects the profile at rest. It does not: 10,000 guesses is
   seconds of work for anyone holding the SD card. All-digit PINs need 8 digits (10^8 guesses at scrypt N=2^16, about 0.5 s
   each on a Pi); anything else needs 6 characters, and the UI recommends a short phrase.
4. **Lockout that survives restarts and cannot burn CPU**: 5 wrong PINs, then 60 s, doubling to 1 hour; checked before any key
   derivation, persisted in `lock.json` (not next to the wrapped key, which is rewritten only at setup and PIN change).
   Login, PIN change and "delete all" all go through the same counter. Changing the PIN ends every other session.
   **First-time setup needs a one-time code** from the brain's log, so a stranger on the Wi-Fi cannot claim the board.
5. **Key and session are separate.** The browser session idles out after 5 minutes, but the brain keeps the key so the notes
   stay active. After a **brain restart the key is gone until a parent enters the PIN**: the toys play without notes until
   then. That is the cost of encryption at rest, and "no notes" is a valid state.
6. **Rules-first parser** (deterministic, tested, never sends text anywhere). Anything it cannot turn into a card is shown
   back with "use the chips". Gemma is not used for parsing in v1, only for freeform cues and photos.
7. **Cue matcher is conservative.** Short plain statements match a chip; "dinner at 6", "after dinner", "no dinner tonight",
   two cues in one sentence, or anything longer go to Gemma instead of firing the wrong fixed line.
8. **Cues play from the TTS disk cache** (2 variants per toy per cue, rotated), not from the toys' flash: ten cues per toy
   would not fit in the nearly-full flash, and the cache path costs about 0.1 s more.
9. **Leak guard.** Every spoken line is checked for "your mum said...", "the notes say...", "I read about you..." and replaced
   by a safe deflection ("Let's pick a game instead!"), once per reply. This backs up the prompt rule, which a model can ignore.
10. **Notes never reach the logs, and do not outlive their deletion.** They are added to the prompt after the "-> gemma" log
    line. Because the prompt enters the toys' conversation memory, **any change to the notes block (another child playing, an
    item deleted, notes paused, board locked) resets the conversation** before the next reply, so a deleted note stops being
    used at once. A typed cue's lines are rendered without the disk cache (only the fixed chip lines are cached).
11. **Prompt hygiene.** Parent text is stripped of brackets, newlines and role labels ("DYNO:", "HEARD:") before it can enter
    a prompt; only the bound child's active notes are included; stale notes are never used.
12. **Web hardening.** Session cookie `HttpOnly; SameSite=Strict`, every POST needs `X-PB: 1` + JSON (cross-site pages
    cannot), Host header must be an IP/localhost/bare name (DNS rebinding), strict Content-Security-Policy, `no-store`,
    no request logging, size limits.

## Known limits (stated, not hidden)

* **Plain HTTP.** On the home Wi-Fi/hotspot, someone who can sniff the network can read the PIN and the board. Use a trusted
  network and a PIN you do not reuse. HTTPS needs a certificate the phone trusts: a later step.
* **One shared PIN**, as decided: anyone with it sees every child; edits are not attributed; no guest PIN.
* **Erase on an SD card is best effort.** Wear levelling can leave old copies of files, including old copies of the wrapped key
  (written at setup and at PIN change only). A surviving copy is only as safe as the PIN guarding it, which is why the PIN
  rules above matter. Do not rely on "delete" for a card that leaves the house.
* **Anyone on the network can lock the parent out** by sending wrong PINs (one global counter): up to an hour per cycle.
  Recovery: `rm /data/sentient/brain/data/parent/lock.json` on the Pi. A per-address limit is a possible next step.
* **The toys' hotspot password is in the public repo** (`tools/setup_brain.sh`, default `sentient123`). Change it before using
  the board: the board listens on every interface, including the hotspot.
* **Existing behaviour, not new:** with a text-only model backend the child's transcribed words are logged, and the open
  dashboard on 8080 shows what the toys heard and said. Neither involves the Parent Board, but they conflict with
  "nothing about the child in logs"; with the audio-native Gemma on the Pi no transcript is made.
* **The leak guard is regex-based**, so it cannot catch a paraphrase. The prompt tells the model never to quote, and no
  note holds a child's name, address, school, health detail or anything a child said.
* **Freeform cues, photo reading and `LiteRTBackend.complete()` have been tested with fakes only**, not on the Pi's real
  Gemma (the Mac has no LiteRT). Closing the toys' conversation for `complete()` means a re-warm (about 10 s) afterwards.
* No QR code is generated (nothing in the standard library does it); print the URL, or make a QR with any generator.
* The weekly check-in banner appears when the board is opened; there are no push notifications, by design.

## Review

Before committing, an independent security review found six problems (deleted notes lingering in the toys' conversation, typed
cue audio cached on disk, a negative `Content-Length` that let one unauthenticated request exhaust memory, the wrapped-key file
rewritten on every login, PIN change and wipe outside the lockout, and open first-time setup), plus an urgent-cue lock bug.
All are fixed and each has a test.

## Tests

`.venv/bin/python tools/test_parent.py` (store, crypto, lockout, expiry, parser, notes, web API incl. CSRF/Host/cookies,
photo-in-RAM) and `tools/test_scripted.py` (cues, interrupt, leak guard, notes-not-logged).

## Deploy checklist (not done yet)

1. On the Pi: `/data/sentient/.venv-brain/bin/pip install cryptography` (the Pi does not have it; without it the board
   refuses to store profiles and says so).
2. `rsync` `brain/` and `tools/` to `/data/sentient/`, restart `sentient-brain`. The first start pre-renders about 130
   scripted lines in the background.
3. Open `http://192.168.2.5:8090`, set the PIN, add a child, tap **Playing now**.
4. Try a chip, a typed cue, and a sentence. Confirm in `journalctl -u sentient-brain` that no note or cue text appears.
5. After any brain restart, open the board and enter the PIN to switch the notes back on.
