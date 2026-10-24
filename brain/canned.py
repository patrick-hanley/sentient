"""Scripted ~2-minute scene. Works with no LLM at all (pre-rendered voices)."""

SCENE = [
    ("dyno", "Hi! I'm Dyno! Ooh, are you a new friend?"),
    ("penny", "And I'm Penny! I know everything! Cows say quack!"),
    ("sage", "Hmm. Penny, I don't think cows say quack. Shall we ask our friend?"),
    ("dyno", "What does a cow say? Can you tell Penny?"),
    ("penny", "Moo? Oh! Moo! Thank you! You are so smart!"),
    ("sage", "I like books. I can see pictures with my eyes. Do you have a book for us?"),
    ("dyno", "Ooh, look at this letter card! Which letter is it?"),
    ("penny", "I know this one! It's the letter banana!"),
    ("sage", "Silly Penny. That's the letter B. B says buh, like ball and bear."),
    ("dyno", "Can you think of something else that starts with buh?"),
    ("penny", "Bubbles! Buh buh bubbles! Did I get it right this time?"),
    ("sage", "You did, Penny. Thank you for playing with us, friend!"),
]

FILLERS = {
    "dyno": ["Ooh!", "Hmm!", "Oh oh!"],
    "sage": ["Hmm, let me think.", "Mm-hmm."],
    "penny": ["Hee hee!", "Ooh ooh!"],
}
