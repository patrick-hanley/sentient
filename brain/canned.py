"""Scripted ~2-minute scene. Works with no LLM at all (pre-rendered voices)."""

SCENE = [
    ("dyno", "Rawr! Hi! I'm Dyno the dinosaur! Ooh, are you a new friend?"),
    ("penny", "And I'm Penny the penguin! I know everything! Three times four is... seven!"),
    ("sage", "Hmm. Penny, I don't think that's right. Can our friend help?"),
    ("dyno", "What is three times four? Can you tell Penny?"),
    ("penny", "Twelve? Oh! Twelve! Thank you! You're so smart!"),
    ("sage", "I'm Sage. I love stories. Do you know the story of the Three Little Pigs?"),
    ("dyno", "Ooh! Which house did the big bad wolf blow down first?"),
    ("penny", "I know! The brick house! Huff and puff!"),
    ("sage", "Silly Penny. It was the straw house. The brick house stayed strong."),
    ("dyno", "If you were a little pig, what would you build your house out of?"),
    ("penny", "Jelly beans! A jelly bean house! Is that strong?"),
    ("sage", "Not very strong, Penny. Bricks are best. Thank you for playing with us, friend!"),
]

FILLERS = {
    "dyno": ["Ooh!", "Hmm!", "Rawr!"],
    "sage": ["Hmm, let me think.", "Mm-hmm."],
    "penny": ["Hee hee!", "Ooh ooh!"],
}
