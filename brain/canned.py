"""Scripted ~2-minute scene. Works with no LLM at all (pre-rendered voices)."""

SCENE = [
    ("pip", "Hi! I'm Pip! Ooh, are you a new friend?"),
    ("noodle", "And I'm Noodle! I know everything! Cows say quack!"),
    ("sage", "Hmm. Noodle, I don't think cows say quack. Shall we ask our friend?"),
    ("pip", "What does a cow say? Can you tell Noodle?"),
    ("noodle", "Moo? Oh! Moo! Thank you! You are so smart!"),
    ("sage", "I like books. I can see pictures with my eyes. Do you have a book for us?"),
    ("pip", "Ooh, look at this letter card! Which letter is it?"),
    ("noodle", "I know this one! It's the letter banana!"),
    ("sage", "Silly Noodle. That's the letter B. B says buh, like ball and bear."),
    ("pip", "Can you think of something else that starts with buh?"),
    ("noodle", "Bubbles! Buh buh bubbles! Did I get it right this time?"),
    ("sage", "You did, Noodle. Thank you for playing with us, friend!"),
]

FILLERS = {
    "pip": ["Ooh!", "Hmm!", "Oh oh!"],
    "sage": ["Hmm, let me think.", "Mm-hmm."],
    "noodle": ["Hee hee!", "Ooh ooh!"],
}
