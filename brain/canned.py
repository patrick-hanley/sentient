"""Scripted toy conversation. Works with no LLM at all (pre-rendered voices)."""

SCENE = [
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

FILLERS = {
    "dyno": ["Ooh!", "Hmm!", "Rawr!"],
    "sage": ["Hmm, let me think.", "Mm-hmm."],
    "penny": ["Hee hee!", "Ooh ooh!"],
}
