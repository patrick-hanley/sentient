"""Fixed, in-character lines the toys say without waiting for Gemma: IMU reactions and parent cues.

Lines are rendered once into the TTS disk cache (voices.prerender) and played from there, so a reaction starts
about 0.1 s after the event instead of ~6 s. {name} in a friend line is the toy that was moved.
Tone rules (same as the system prompt): warm, short, nothing scary, no lectures, no quoting a parent.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# IMU: what the moved toy says itself. Stored on that toy's own flash as clip "imu_<event>" (works with no brain).
# {sfx} tags use the existing sound library.
# ---------------------------------------------------------------------------
IMU_EVENTS = ("sleep", "woken", "tossed", "shaken", "rocked", "dropped", "spun", "upside_down")

IMU_LOCAL = {
    "sleep": {"dyno": "{snore_big}", "sage": "{snore_cat}", "penny": "{snore_dog}"},   # recorded snores (CC0), never spoken "zzz"
    "woken": {"dyno": "Mmm... rawr! Did I nap?", "sage": "Oh... was I dreaming about books?",
              "penny": "Honk! I'm awake! What did I miss?"},
    "tossed": {"dyno": "Wheee! Again! Again! Rawr!", "sage": "Whoa! That was higher than my bookshelf!",
               "penny": "Wheee, honk! I can fly! Almost!"},
    "shaken": {"dyno": "Whoa, oh, oh! I'm all wobbly!", "sage": "Whoa, whoa! My pages are all mixed up!",
               "penny": "Hee hee hee, I'm all wiggly!"},
    "rocked": {"dyno": "Hmm, hmm, rawr...", "sage": "La la, la la...", "penny": "Honk... la la..."},
    "dropped": {"dyno": "Oof! Rawr... I'm okay!", "sage": "Oh! I tumbled! My pages are fine.",
                "penny": "Whoa, honk! I fell over!"},
    "spun": {"dyno": "Whoa! The room is spinning! Rawr!", "sage": "Everything is going round and round...",
             "penny": "Wheee! I'm a spinning top! Honk!"},
    "upside_down": {"dyno": "Whoa! The world is upside down!", "sage": "Hmm, everything looks different from here.",
                    "penny": "Hee hee! The ceiling is the floor!"},
}

# ---------------------------------------------------------------------------
# IMU: what the OTHER toys say, once per episode. Two variants each so a repeat does not sound canned.
# ---------------------------------------------------------------------------
IMU_FRIENDS = {
    "sleep": {
        "dyno": ["Shhh! Somebody's dreaming. I will be extra quiet. Rawr... quietly.",
                 "Shhh... {name} is fast asleep. Tiptoe, tiptoe."],
        "sage": ["Oh, they're asleep. Let's keep our voices soft, like a library.",
                 "Sweet dreams, {name}. We will whisper."],
        "penny": ["Hee hee! Listen to that snore! Shhh, don't wake them up!",
                  "Shh, shh! {name} is snoozing. I will whisper my jokes."]},
    "woken": {
        "dyno": ["Welcome back! You snored like a champion!", "Rawr! You're awake! Did you have a good nap?"],
        "sage": ["Good morning, sleepyhead. Dream anything good?", "Welcome back, {name}. Did you dream of stories?"],
        "penny": ["You're awake! Hee hee, you missed nothing. Except my joke.",
                  "Yay, {name} is up! I kept your spot warm!"]},
    "tossed": {
        "dyno": ["I saw that! Ten out of ten for airtime!", "Whoa! {name} was flying! Rawr!"],
        "sage": ["Wow! And please land on something soft!", "That was a big jump! Soft landings, please."],
        "penny": ["Did you see that? I was basically a penguin rocket!", "Whee! {name} flew like a bird! Honk!"]},
    "shaken": {
        "dyno": ["Shake, shake! Are you a maraca now?", "Wiggle wiggle! Rawr!"],
        "sage": ["Gently, gently. Let's un-shake and sit down.", "Easy now. Let's keep our pages in order."],
        "penny": ["Again! Again! No wait... I'm dizzy. Hee hee.", "Hee hee! {name} is a wiggle worm!"]},
    "rocked": {
        "dyno": ["Rock-a-bye, friend. Shhh.", "Sway, sway. Nice and slow. Rawr."],
        "sage": ["That's a nice, slow rock. Like a story boat.", "Slow and gentle. That is lovely."],
        "penny": ["Sway, sway... I'm getting sleepy just watching!", "Ooh, rock-a-bye! Hee hee."]},
    "dropped": {
        "dyno": ["You okay, friend? That was a big tumble!", "Oh no! Are you okay, {name}?"],
        "sage": ["Are you hurt? Let's check. Paws, ears, tail, all there?", "Oh dear. Let's check that everything is okay."],
        "penny": ["Oops! Up you get! Hee hee, that was a funny fall!", "Whoopsie! Up we go, {name}!"]},
    "spun": {
        "dyno": ["Spin, spin! Don't fall over!", "Whoa! {name} is a spinning top!"],
        "sage": ["Stop when the world stops spinning, okay?", "Round and round! Let's stop before we get dizzy."],
        "penny": ["I want a turn! Spin me next!", "Wheee! Spin spin spin! Honk!"]},
    "upside_down": {
        "dyno": ["You're upside down! That's a funny view!", "Rawr! {name} is upside down!"],
        "sage": ["Careful. Upside-down toys sometimes bonk.", "Hmm, a new way to look at things."],
        "penny": ["Flip! Flip! Do it again!", "Hee hee! {name} is topsy turvy!"]},
}

# How many friends comment, per event (the rest stay quiet so it never turns into a chorus).
IMU_FRIEND_COUNT = {"sleep": 2, "woken": 2, "tossed": 2, "dropped": 2, "shaken": 1, "rocked": 1, "spun": 1, "upside_down": 1}

# ---------------------------------------------------------------------------
# Parent cues, tier 1: one tap, fixed lines per toy. The parent supplies the meaning, the toys supply the reaction:
# they never repeat the parent's sentence and never say who asked.
# ---------------------------------------------------------------------------
CUES = {
    "dinner": {"label": "Dinner", "lines": {
        "dyno": ["I smell dinner! Rawr, my tummy is rumbling!", "Dinner! Rawr, I could eat a whole mountain!"],
        "sage": ["Dinner time! Let us wash our paws first.", "Something smells good. Let us wash up for dinner."],
        "penny": ["I am hungry! Let us eat!", "Yum yum! Dinner! Hee hee!"]}},
    "bedtime": {"label": "Bedtime", "lines": {
        "dyno": ["Yawn... rawr. Sleepy time already?", "Rawr... my eyes are getting heavy."],
        "sage": ["Time for one last story, then sleep.", "Sleepy time. A cozy story, then goodnight."],
        "penny": ["Pajamas on! Hee hee, I am ready!", "Brrr, cozy blankets! I am ready for bed!"]}},
    "bath": {"label": "Bath", "lines": {
        "dyno": ["Splash time! Rawr!", "Rawr! Time to splash!"],
        "sage": ["Bath time. Let us be nice and clean.", "A warm bath sounds lovely."],
        "penny": ["Bubbles! I love bubbles!", "Splish splash! Hee hee!"]}},
    "homework": {"label": "Homework", "lines": {
        "dyno": ["Homework time! Rawr, let us do it together!", "Rawr! Brain power time!"],
        "sage": ["Let us start with the easy ones.", "Homework time. One step at a time."],
        "penny": ["I will cheer you on! Hee hee!", "You can do it! I will be your cheerleader!"]}},
    "leaving": {"label": "Leaving", "lines": {
        "dyno": ["Shoes on! Adventure time!", "Rawr! Time for an adventure!"],
        "sage": ["Do we have everything? Let us check.", "Let us check we have everything we need."],
        "penny": ["Wait for me! I am coming!", "Off we go! Hee hee!"]}},
    "quiet": {"label": "Quiet time", "lines": {
        "dyno": ["Shhh... quiet time. Rawr, softly.", "Shhh. Quiet voices. Rawr, very softly."],
        "sage": ["Quiet voices, like a library.", "Let us use our whispering voices."],
        "penny": ["Shhh! I can whisper too!", "Shhh, shhh. Tiny quiet voice."]}},
    "snack": {"label": "Snack", "lines": {
        "dyno": ["Snack time! My favourite time!", "Rawr! Snack attack!"],
        "sage": ["A little snack, then back to play.", "A snack sounds nice. Then we can play again."],
        "penny": ["Yum! What are we having?", "Snack time! Hee hee!"]}},
    "story": {"label": "Story time", "lines": {
        "dyno": ["Story time! Rawr, I love stories!", "A story! Rawr, yes please!"],
        "sage": ["Let us pick a good book.", "Story time. I love a good book."],
        "penny": ["Ooh! A story! Tell me, tell me!", "Story time! Hee hee, I am so excited!"]}},
    "cleanup": {"label": "Clean up", "lines": {
        "dyno": ["Clean up! Let us tidy like a parade!", "Tidy time! Rawr, march and tidy!"],
        "sage": ["Everything has a home. Let us put it back.", "Let us tidy up, one thing at a time."],
        "penny": ["Race you! Hee hee, last one to tidy is a sleepy penguin!", "Tidy tidy! Honk!"]}},
    "visitor": {"label": "Visitor", "lines": {
        "dyno": ["A visitor! Rawr, hello!", "Someone is coming! Rawr!"],
        "sage": ["Let us be on our best behaviour.", "We have company. Let us be polite."],
        "penny": ["Yay! Company! Hee hee!", "A visitor! I will wave my flippers!"]}},
}

_CUE_PATTERNS = {
    "dinner": r"\b(dinner|supper)\b|\btime to eat\b|\bfood is ready\b",
    "bedtime": r"\bbed ?time\b|\btime for bed\b|\btime to sleep\b|\bgo to bed\b|\blights out\b",
    "bath": r"\bbath\b|\bbath ?time\b|\bshower\b",
    "homework": r"\bhome ?work\b",
    "leaving": r"\bshoes on\b|\btime to go\b|\bleaving\b|\bout the door\b|\bget your shoes\b",
    "quiet": r"\bquiet time\b|\bquiet please\b|\bquiet down\b",
    "snack": r"\bsnack\b",
    "story": r"\bstory ?time\b|\bbook ?time\b|\btime for a story\b",
    "cleanup": r"\bclean ?up\b|\btidy\b|\bput (your )?toys away\b",
    "visitor": r"\bvisitors?\b|\bguests?\b|\bcompany\b",
}
# A cue that is about a different moment ("dinner at 6", "after dinner", "no dinner today") is not the fixed cue.
_SHIFT = re.compile(r"\b(after|before|tomorrow|tonight|later|soon|no|not|don'?t|won'?t|never|yesterday|at \d|in \d+|in an? |"
                    r"minutes?|hours?|if|when|until|instead|without|cancel(led)?)\b")


def match_cue(text: str) -> str | None:
    """Tier-1 cue id for a short, plain statement; None sends it to Gemma. Keywords are matched, never guessed."""
    t = " ".join(re.sub(r"[^a-z0-9' ]", " ", text.lower()).split())
    if not t or len(t.split()) > 8 or _SHIFT.search(t):
        return None
    hits = [cid for cid, pat in _CUE_PATTERNS.items() if re.search(pat, t)]
    return hits[0] if len(hits) == 1 else None   # two different cues in one sentence: let Gemma sort it out


# Phrases a toy must never say to a child: they would reveal that a parent wrote a note or sent a cue.
LEAK_PATTERNS = [
    r"\byour (mum|mom|mommy|mummy|dad|daddy|mother|father|parents?|grown[- ]?ups?|teacher)\b.{0,30}\b(said|says|told|wrote|asked|want|wants|texted|sent)\b",
    r"\b(mum|mom|dad|mother|father|parents?)\b (said|says|told|wrote|texted|asked|sent)\b",
    r"\b(parent|parents'?|family) notes?\b", r"\bthe notes?\b", r"\bnotes? (said|says|mention)",
    r"\bi (was|were|have been) told\b", r"\bsomeone told me\b", r"\bi read (about )?you\b",
    r"\b(spelling|math|maths|reading|school) test (on|is|this|next)\b.*\b(your|you have|you've)\b",
]
_LEAK = [re.compile(p, re.I) for p in LEAK_PATTERNS]
SAFE_DEFLECT = {"dyno": "Let's pick a game instead! Rawr!", "sage": "Let us pick a game instead.",
                "penny": "Ooh, let's play a game instead! Hee hee!"}


def leaks_note(text: str) -> bool:
    return any(p.search(text) for p in _LEAK)


def all_lines():
    """Every (toy, text) the toys may say from this module: for pre-rendering into the TTS cache."""
    out = []
    for ev in IMU_EVENTS:
        for toy, text in IMU_LOCAL[ev].items():
            out.append((toy, text))
    for ev in IMU_EVENTS:
        for friend, variants in IMU_FRIENDS[ev].items():
            for v in variants:
                if "{name}" in v:
                    out += [(friend, v.format(name=n)) for n in ("Dyno", "Sage", "Penny") if n.lower() != friend]
                else:
                    out.append((friend, v))
    for cue in CUES.values():
        for toy, variants in cue["lines"].items():
            out += [(toy, v) for v in variants]
    out += [(toy, text) for toy, text in SAFE_DEFLECT.items()]
    return out
