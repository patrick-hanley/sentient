# Parents updating the toys about a child — design

Goal: a parent can tell the toys what matters about their child —
interests, hobbies, schedule, homework — in seconds, and that
information stays in the house. It must never become a cloud form,
a shared spreadsheet, or something a toy repeats back to the child.

## The core tension, stated plainly

Frictionless and secure pull in opposite directions. The usual
"frictionless" answer — text it to an app, fill a Google Form, email
it — is frictionless precisely because it copies the child's data
to someone else's server, where it lives forever, gets backed up,
and can be read back by the wrong person. The usual "secure" answer
— a long intake form behind a login — is secure precisely because
nobody ever fills it in, so the toys end up knowing nothing and
personalisation dies.

The design below resolves that by making the *house* the database,
the *parent* the only writer, and *confirmation* the only work.

## Principles (non-negotiable)

1. **Local only.** The profile lives on the brain in the home
   (Pi / Jetson today), in one file, on the home network only.
   It is never uploaded, synced, emailed, or sent to a cloud LLM.
   Gemma already runs locally, so the profile can be used without
   ever leaving the room — the same rule as the toys' audio.
2. **Parent is the only source of truth.** Toys never infer a
   profile from a child, never ask a child "is it true you like…?",
   and never store something a child said about themselves as a
   profile fact. Anything a child volunteers in play stays in that
   play session; it does not become a permanent fact.
3. **Use, don't quote.** The brain may use a parent note to choose
   a topic or a homework game. It must never say "your mum told me
   you struggle with spelling" or repeat a parent note verbatim.
   The child should experience a toy that happens to pick a good
   topic, not a toy that reports on them.
4. **Everything expires or gets re-confirmed.** A schedule is not
   a fact forever. Interests fade. Homework is due and then gone.
   Stale data is worse than no data — it makes the toys confidently
   wrong — so every item carries a date and either an expiry or a
   re-confirmation nudge.
5. **Delete is real and per-item.** A parent can delete one interest,
   one week, or everything, from the same screen they added it on.
   Deleting removes it from the profile file and from the prompt
   the brain builds. There is no trash, no backup copy, no "we keep
   it for quality purposes."

## What the parent actually does

There is one surface: a **Parent Board** — a website served by the
brain itself, on the brain's existing dashboard (port 8080 today),
reachable only on the home Wi-Fi, behind
a 4-digit family PIN, set once and shared by the household adults. It is
not a phone app and not a cloud portal: no install, no App Store,
no account, no hosted website elsewhere. You open it in any phone
browser on the home Wi-Fi, and "Add to Home Screen" makes it feel
like an app icon without it becoming one. No account, no app to install,
no password to remember, no cloud login. A QR code on the fridge
opens it on a phone. The child never needs to see it, and the toys
never read it aloud.

Three ways in, in order of effort:

### 1. Say it once, tap to confirm (the main path, ~10 seconds)

The parent types or speaks one freeform sentence, exactly as they
would text a partner:

> "Spelling test Friday, she loves space, and soccer is Tuesdays
> at four."

The brain, locally, parses that into suggested cards — one per fact
— and shows them back. The parent taps ✓ on each correct card and
✗ on any wrong one. Nothing is saved until the parent taps. This is
the whole trick: freeform input is frictionless, but *unconfirmed*
freeform input is how you end up with a toy confidently teaching
the wrong spelling words. Confirmation is the only mandatory work,
and it is three taps.

Cards look like this, not like a form:

- [Spelling test — Friday] [Space — loves it] [Soccer — Tue 4pm]
  ✓ all / tap one to fix / ✗ to drop it

### 2. Chips for the common stuff (~5 seconds)

For the things parents say every week, there are no sentences at
all. Tap chips:

- Interests: dinosaurs, space, drawing, music, animals, building,
  reading, sport… plus one "add your own" chip.
- School: spelling, reading, maths, times tables — with a due date
  picker that defaults to "this Friday."
- Mood / boundaries: "quieter voices today", "no scary stories",
  "tired today, keep it gentle."

A chip is a complete fact. No typing required.

### 3. Photo a worksheet or schedule (~20 seconds, optional)

The parent photographs a homework sheet or a school schedule. The
brain reads it locally, summarises it — "practice these 5 spelling
words: …" — and shows that summary as a card for confirmation.
The photo itself is deleted after parsing. Only the confirmed
summary is kept, and only until its due date. The toys never see
the photo, and the parent never has to transcribe a worksheet.

## What gets stored — and for how long

One profile per child, one file, fields grouped by how the toys use
them. Nothing else is stored. In particular: no health information
unless the parent explicitly adds a boundary ("keep volume low",
"avoid flashing topics") — and even then it is stored as the
boundary, not the reason.

| Field | Example | Why the toys need it | Retention |
|---|---|---|---|
| Interests | space, dinosaurs | Choose topics, stories, games | Re-confirm every 4 weeks, else fades out |
| Hobbies / activities | soccer Tue 4pm, piano | Talk about their week, know when they are busy | Schedule items expire on their date; recurring items expire at term end |
| School / homework | spelling test Fri, 5 words | Practice games, reading help | Expires on the due date, then deleted |
| Reading level / language | reads short chapter books | Pitch vocabulary right | Re-confirm each term |
| Boundaries | quieter today, no scary | Tone, volume, topic choice | "Today" items expire overnight; standing items until the parent removes them |
| Routines | bedtime 7:30, quiet time after lunch | Know when to wind down, not start a long game | Until changed |
| Goals the parent set | "practise times tables" | A toy can suggest that game, once, gently | Until the parent marks it done |

What is NOT stored: full names of schools or teachers, addresses,
medical details, anything a child said in play, audio recordings,
photos, or a history of what the child did with the toys. The
profile is a forward-looking note ("what would help this week"),
not a record of the child.

## How the toys use it (and how they must not)

At the start of a turn, the brain builds a short, private section
for Gemma — never spoken, never shown to the child:

> Parent notes (use to choose topics, never quote, never name the
> source): loves space; spelling test Friday (words: …); soccer
> Tuesdays; keep voices gentle today.

Rules enforced in that prompt, not left to vibes:

- Pick a topic from the notes when choosing a game or story.
- Never reveal the notes, the parent, or that a note exists.
- Never use a note as a test ("Your mum said you have a spelling
  test, spell this") — offer the game, let the child accept.
- A boundary beats an interest: "quieter today" overrides
  "loves dinosaurs" for tone, not for topic.
- If there are no notes, the toys play normally. No notes is a
  valid state, not an error to be fixed by interrogating the child.

## Security, concretely

Threats, and what stops each one:

- **A visitor or another child on the home Wi-Fi finds the board.**
  The PIN stops casual browsing. The board is not linked from the
  toys' dashboard homepage; it is a separate path, and it locks
  after 5 minutes idle.
- **A phone is lost or a screenshot leaks.** There is no cloud
  copy to leak from, and the board shows only the current week by
  default — no history to screenshot in bulk.
- **The brain is stolen or the SD card is read.** The profile file
  is encrypted at rest with a key derived from the family PIN
  (not stored in plaintext next to it). Losing the PIN means losing
  the profile, which is the right trade: the profile is rebuildable
  in minutes from the parent's head, and it must not be recoverable
  by anyone else.
- **A cloud service or model provider sees it.** It never leaves
  the house. The parse step uses the local Gemma, not an API. If
  the local model cannot parse a sentence, it shows the sentence
  back and asks the parent to pick chips instead — it does not
  send the sentence out for help.
- **The child asks the toy what the parent wrote.** The toys have
  no read-back path. They cannot answer that question because the
  profile is not in their conversational memory, only in the
  private prompt section, and the prompt rule is "never quote,
  never name the source." If pressed, the toy deflects to play:
  "Let's pick a game instead!"
- **Two children, one house.** Profiles are separate files, and a
  toy in a session with one child only loads that child's notes.
  A toy never mixes notes across children, and a parent board
  shows one child at a time.

## Friction over time: the weekly 60 seconds

The system that survives is the one that asks at the right moment,
not the one with the best form. Once a week — Sunday evening is the
obvious slot, and the parent picks the time — the board shows a
single screen, three questions, all pre-filled from last week:

1. Anything new this week? (chips + one freeform box)
2. Still true? [space] [soccer Tue] [spelling] — tap to keep, tap
   again to drop.
3. Anything to stop? (one tap to clear homework, boundaries, or all
   of this week's items)

Sixty seconds, once a week, and the toys stay current. If the
parent ignores it, nothing breaks: old schedules expire on their
own, interests fade after 4 weeks, and the toys fall back to
generic play. Silence is a safe default, not a failure state.

## Why not the obvious alternatives

- **Texting Muse / a chat app.** Lowest friction, but it copies
  child data to a cloud agent's memory, mixes it with everything
  else the parent chats about, has no expiry, no per-child
  separation, and no delete button the parent controls. Good for
  the parent's own notes; wrong for a child's profile.
- **A shared spreadsheet or form.** Same cloud problem, plus a
  form is work nobody does twice. It also invites over-sharing:
  a blank form asks for everything, so parents fill in everything.
- **Telling the toys by voice.** The child is usually in the room,
  the toys would repeat it, and voice input has no confirmation
  step — a misheard spelling word becomes a confident wrong fact.
- **The toys learning it from the child.** Tempting, and wrong:
  it turns play into surveillance, it has no parent consent per
  fact, and children are unreliable reporters of their own
  schedules. Parent-confirmed notes only.

## Decisions (set Oct 29)

- **Multiple children, from v1.** Not a later add-on: the board
  is built around a child switcher from the start.
- **One shared family PIN.** Everyone in the household who has the
  PIN can view and edit every child's profile. No per-parent
  accounts, no per-parent PINs, no read-only tier in v1.

## Multiple children + one family PIN — how it works

### Children are separate, always

- Adding a child takes a first name only, plus a colour dot to
  tell them apart on screen. No full name, no date of birth, no
  photo — the board does not need any of that to personalise play,
  and every extra field is a leak waiting to happen.
- Each child gets their own profile file, their own expiry dates,
  their own weekly check-in section. Nothing is shared between
  children by default, and nothing is copied from one child to
  another. A toy in a session with one child only loads that
  child's notes.
- The board shows one child at a time, with a switcher at the top
  (name + colour). Editing the wrong child's profile is the main
  failure mode here, so the switcher is always visible, and every
  card and every save button carries the child's name and colour.

### Which child is playing? The session binds once

The toys need to know whose notes to load, and they must not guess
from a voice or a face and then mix two children's notes. So:

- Before play, the parent picks "Now playing" on the board (one
  tap, same switcher). That child stays bound for the whole
  session. If play stops and a different child picks up a toy, the
  parent taps again — or the session times out after 30 minutes
  idle and the next session starts unbound, with generic play
  until a parent picks a child.
- The toys never switch child mid-turn, never ask "are you Maya
  or Leo?", and never load a second child's notes to compare.
  If no child is bound, the toys play generically. That is safe,
  and it is also the correct behaviour for a visitor's child.

### One family PIN — what it means, honestly

A shared PIN is simpler than per-parent accounts — one PIN to
remember, one PIN to tell a grandparent or a babysitter — but it
also means the trust boundary is the household, not the
individual. Anyone with the PIN can see and edit every child's
profile. That is the trade, and it should be stated, not hidden:

- The PIN is for household adults. It is not for children, and
  not for anyone outside the household, even temporarily — there
  is no "guest PIN" in v1, so handing the PIN to a visitor hands
  them the whole board.
- Because the PIN is shared, edits cannot be attributed to a
  person. The board shows "last changed" (time only) per child,
  so a second parent can see something changed, but not who
  changed it. If attribution ever matters, that is a reason to
  move to per-adult PINs later — it is not a v1 problem.
- The profile encryption key is derived from the family PIN, so
  changing the PIN re-encrypts the profiles, and losing the PIN
  still means losing the profiles. Rotating the PIN is a
  one-screen job: old PIN, new PIN, done — no accounts to reset.
- The board still locks after 5 minutes idle, and it still shows
  only the current week by default, so a phone left unlocked on
  the kitchen table exposes less than a full history would.

### Weekly check-in, for a family

The Sunday check-in is one screen, but stacked by child: each
child gets a collapsible section with the same three questions
(anything new, still true, anything to stop), and the parent works
down the list. Roughly 60 seconds per child, not 60 seconds total
— pretending a family check-in is 60 seconds total is how
younger siblings' notes go stale. Skipping a child's section is
fine: that child's old items expire on their own, as before.

## Immediate parent statements — "Say it now" (live cues)

This is different from everything above. A profile update is a
fact for later ("spelling test Friday"). A live cue is a statement
for *right now* that the toys must interpret and react to, in the
moment, in character — not read back verbatim, and not stored.

Example, exactly as you put it: the parent taps or types "time for
dinner." The toys do not all say "time for dinner." They interpret
it:

- Dyno: "I smell dinner! Rawr, my tummy is rumbling!"
- Sage: "Dinner time! Let us wash our paws first."
- Penny: "I am hungry! Let us eat!"

That is the rule for every cue: **the parent supplies the meaning,
the toys supply the reaction.** No toy repeats the parent's
sentence, and no toy attributes it ("Mum says…") unless the parent
explicitly taps "say Mum/Dad says" — the default is that the toys
just react, as if they noticed, so the magic is not broken by a
citation.

### Two tiers, because not every cue can be pre-scripted

**Tier 1 — common cues, fixed lines, instant.** Dinner, bedtime,
bath, homework, leaving, quiet time, snack, story, clean-up,
visitor coming. These are chips on the board, one tap, no typing.
Each chip has a fixed line per toy, pre-rendered onto that toy's
flash exactly like the IMU reactions, so it plays instantly with
no Gemma turn and no waiting for a model. This is the tier to use
for the cues a parent sends every day.

**Tier 2 — freeform cue, Gemma interprets.** Anything else the
parent types — "the park is closed today", "grandma is coming in
an hour", "it is raining, no bikes today." There is no fixed line
for that, so it goes to Gemma with a tight instruction: interpret
the cue, do not repeat it verbatim, do not name the parent as the
source, one short line per toy, in character, age-appropriate, and
do not invent details beyond the cue. It takes a few seconds,
which is fine for an announcement — it is not a sound effect, and
it does not need to be instant to be useful.

A freeform cue that matches a Tier 1 chip ("time for dinner",
"dinner time", "dinner!") fires the fixed Tier 1 lines instead of
going to Gemma. Keywords are matched, not guessed: if it does not
clearly match, it goes to Gemma rather than firing the wrong fixed
line.

### Fixed lines for the common cues

Written so they work for any child, any day — no names, no details
that could be wrong:

- **Dinner:** Dyno "I smell dinner! Rawr, my tummy is rumbling!"
  / Sage "Dinner time! Let us wash our paws first."
  / Penny "I am hungry! Let us eat!"
- **Bedtime:** Dyno "Yawn… rawr. Sleepy time already?"
  / Sage "Time for one last story, then sleep."
  / Penny "Pajamas on! Hee hee, I am ready!"
- **Bath:** Dyno "Splash time! Rawr!"
  / Sage "Bath time. Let us be nice and clean."
  / Penny "Bubbles! I love bubbles!"
- **Homework:** Dyno "Homework time! Rawr, let us do it together!"
  / Sage "Let us start with the easy ones."
  / Penny "I will cheer you on! Hee hee!"
- **Leaving / out the door:** Dyno "Shoes on! Adventure time!"
  / Sage "Do we have everything? Let us check."
  / Penny "Wait for me! I am coming!"
- **Quiet time:** Dyno "Shhh… quiet time. Rawr, softly."
  / Sage "Quiet voices, like a library."
  / Penny "Shhh! I can whisper too!"
- **Snack:** Dyno "Snack time! My favourite time!"
  / Sage "A little snack, then back to play."
  / Penny "Yum! What are we having?"
- **Story time:** Dyno "Story time! Rawr, I love stories!"
  / Sage "Let us pick a good book."
  / Penny "Ooh! A story! Tell me, tell me!"
- **Clean up:** Dyno "Clean up! Let us tidy like a parade!"
  / Sage "Everything has a home. Let us put it back."
  / Penny "Race you! Hee hee, last one to tidy is a sleepy penguin!"
- **Visitor coming:** Dyno "A visitor! Rawr, hello!"
  / Sage "Let us be on our best behaviour."
  / Penny "Yay! Company! Hee hee!"

### Timing: immediate, but not mid-word

"Immediate" means the parent's cue wins, not that it cuts a toy
off mid-syllable. The default is: play at the next line boundary
(the current toy line finishes, the cue lines play, then play
resumes). That is seconds, not minutes, and it does not corrupt a
turn in progress. For a truly urgent cue — leaving now, bedtime
now — the board has a "Stop everything now" toggle: it stops the
current toy speech, plays the cue, and the interrupted turn is
dropped, not resumed. The parent chooses urgency; the system does
not guess it, because dropping a child's game is a real cost and
should be the parent's call.

If no toy is online, the cue is not queued for later. It is
ephemeral: it either plays now or it does not happen. A dinner
call delivered an hour later is worse than no dinner call.

### What a cue is not

- Not a profile fact. A cue is not saved, does not appear in the
  weekly check-in, and does not change what the toys know about
  the child next week. "Time for dinner" today says nothing about
  dinner tomorrow.
- Not a message to a specific child. A cue goes to all toys that
  are online, in the currently bound child's session if there is
  one, or generically if there is not. Dinner is dinner for
  whoever is playing.
- Not a way to spy or to test. The toys must not use a cue to
  quiz the child ("Mum said dinner, what are we eating?") — they
  react, then the child takes it from there.
- Not stored history. There is no log of cues a parent sent, to
  read back later. Ephemeral means ephemeral.

### Board UI for it

A separate section from the profile cards, at the top of the
board, because it is used differently: "Say it now" — a row of
cue chips (dinner, bedtime, bath, homework, leaving, quiet,
snack, story, clean up, visitor), a freeform box underneath, and
a Send button, plus the "Stop everything now" toggle. One tap
for a chip, type + Send for anything else. No confirmation card
is needed here — unlike a profile fact, a cue is not stored, so
there is nothing to get wrong permanently — but the board does
show "Sent: dinner" for a few seconds, so the parent knows it
fired.

## Build order (updated)

1. **Parent Board v1 (manual):** family PIN, child switcher
   (first name + colour only), chips + freeform text with manual
   card confirmation, expiry dates, delete-all, "Now playing"
   session binding, plus "Say it now" Tier 1 chips (fixed lines,
   instant). No parsing magic yet.
2. **Local parse + freeform cues:** freeform sentence → suggested
   profile cards, parent taps to confirm; freeform cue → Gemma
   interpretation (Tier 2). Same screen, less typing.
3. **Photo homework:** local read → summary card → confirm →
   photo deleted. Only after 1 and 2 work.
4. **Weekly check-in screen** (stacked by child) and stale-data
   fading. This is what keeps it alive past week two.

## Open questions for the parent (not blockers)

- Sunday evening check-in, or a different day/time? Parent picks
  it; the system should not pick for them.
