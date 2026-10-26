"""Scripted toy conversation. Works with no LLM at all (pre-rendered voices)."""

_MEET = [
    ("dyno", "Rawr! Hi! I'm Dyno the dinosaur! Welcome to our little learning party!"),
    ("penny", "I'm Penny the penguin! Imagine numbers wearing party hats. Even multiplication can have a giggle!"),
    ("sage", "I'm Sage. Let's try three groups of four. Four, eight, twelve!"),
    ("dyno", "So three times four is twelve. Rawr! A whole parade of numbers!"),
    ("penny", "Twelve! In my imagination, each number gets a tiny dancing hat."),
    ("sage", "Now a story puzzle for Dyno: which house stayed standing in the Three Little Pigs?"),
    ("dyno", "The brick house! The wolf couldn't blow it down."),
    ("penny", "I'd imagine a tiny library inside, with books small enough for piglet paws!"),
    ("sage", "What a lovely make-believe library. Let's spell the word book: B-O-O-K."),
    ("dyno", "B-O-O-K! Four letters, and two of them are O."),
    ("penny", "Those two O letters look like round little glasses. What a well-dressed word!"),
    ("sage", "Your turn, friend! Would you like a spelling game, a math puzzle, or a story?"),
]

_SPELLING = [
    ("sage", "Let's have a spelling bee! Penny, can you spell cat?"),
    ("penny", "C, A, T. Cat! Like a fluffy cloud with whiskers!"),
    ("dyno", "Rawr! My turn! Dog is spelled D, O, G!"),
    ("sage", "Wonderful! Now it's your turn, friend. Can you spell sun?"),
    ("penny", "I'll cheer for you! What letter does sun start with?"),
    ("dyno", "You're a super speller! Rawr!"),
]

_PLANETS = [
    ("dyno", "Rawr! Did you know Jupiter is the biggest planet?"),
    ("penny", "Jupiter is so big that more than a thousand Earths could fit inside!"),
    ("sage", "And Mercury is the planet closest to the Sun."),
    ("dyno", "Neptune is very far from the Sun, so it is super cold!"),
    ("penny", "Like a giant, faraway snow globe!"),
    ("sage", "Which planet would you like to visit, friend?"),
]

# Scripted scenes (dashboard buttons; long-press a toy plays the first). Each toy's lines are
# stored on that toy as clips, so a scene plays without speech synthesis or audio over Wi-Fi.
SCENES = {"Meet the toys": _MEET, "Spelling bee": _SPELLING, "Planets": _PLANETS}
SCENE = _MEET   # default scene

FILLERS = {
    "dyno": ["Ooh!", "Hmm!", "Rawr!"],
    "sage": ["Hmm, let me think.", "Mm-hmm."],
    "penny": ["Hee hee!", "Ooh ooh!"],
}


# Stored on each Atom as the "hello" clip: its button plays it when no brain is reachable.
GREETINGS = {
    "dyno": "Rawr! Hi, I'm Dyno! My brain is still waking up. Try again in a moment!",
    "sage": "Hello, I'm Sage. My brain is having a little rest. Let's talk again soon.",
    "penny": "Hi! I'm Penny the penguin! My brain is taking a quick nap.",
}
