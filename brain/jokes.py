"""Jokes come from a list, not from the model (config.JOKE_BANK).

The tuned and the stock model both write the shape of a joke with no joke in it ("What is a pancake's favorite letter? The L.",
"What dinosaur is a big red apple? The Tyrannosaurus!", live and in scoring, Nov 24-26), or ask the question and never give the
answer. When the child asks for a joke, the toy that was asked tells one of these, whole, and the model is not asked."""
from __future__ import annotations

import random
import re

JOKES = [
    "What do you call a sleeping dinosaur? A dino-snore!",
    "Why did the cookie go to the nurse? It felt crumbly!",
    "What do you call a bear with no teeth? A gummy bear!",
    "Why did the banana go to the doctor? It was not peeling well!",
    "What do you call a fake noodle? An impasta!",
    "Why can't a bicycle stand up by itself? It is two tired!",
    "What do you call cheese that is not yours? Nacho cheese!",
    "Why did the teddy bear say no to dessert? It was already stuffed!",
    "What did the ocean say to the beach? Nothing, it just waved!",
    "What is a cat's favorite color? Purr-ple!",
    "Why are fish so smart? They live in schools!",
    "What do you call a dinosaur that knows lots of words? A thesaurus!",
    "Why did the math book look sad? It had too many problems!",
    "What does a cloud wear under its raincoat? Thunderwear!",
    "What time is it when an elephant sits on your fence? Time to get a new fence!",
    "Why do bees have sticky hair? They use honeycombs!",
    "What do you call a cow with no legs? Ground beef!",
    "Why did the student eat the homework? The teacher said it was a piece of cake!",
    "What is brown and sticky? A stick!",
    "What do you call a train that sneezes? Achoo-choo train!",
    "Why did the chicken join a band? It had the drumsticks!",
    "What do elves learn in school? The elf-abet!",
    "What kind of tree fits in your hand? A palm tree!",
    "Why did the golfer bring two pairs of pants? In case he got a hole in one!",
    "What do you call a pig that does karate? A pork chop!",
    "Where do cows go on Friday night? To the moo-vies!",
    "What has four wheels and flies? A garbage truck!",
    "Why did the scarecrow win a prize? He was outstanding in his field!",
    "What do you get when you cross a snowman and a dog? Frostbite!",
    "What is a ghost's favorite fruit? Boo-berries!",
    "Why don't eggs tell jokes? They would crack each other up!",
    "What do you call a boomerang that does not come back? A stick!",
    "How does the moon cut its hair? Eclipse it!",
    "What is a pirate's favorite letter? You would think R, but it is the C!",
    "Why was six afraid of seven? Because seven ate nine!",
    "What do you call an alligator in a vest? An investigator!",
    "What did one wall say to the other wall? Meet you at the corner!",
    "Why did the tomato turn red? It saw the salad dressing!",
    "What do you call a dog magician? A labracadabrador!",
    "How do you make an octopus laugh? With ten-tickles!",
    "What is a penguin's favorite relative? Aunt Arctica!",
    "Why do pumpkins sit on porches? They have no hands to knock on the door!",
]
BY_TOY = {"penny": ("penguin", "snowman", "ocean", "fish"), "dyno": ("dinosaur", "dino", "alligator"), "sage": ("pumpkin", "math", "homework", "ghost")}

_ASK = re.compile(r"\b(?:tell|say|know|give|got|have|hear|want|do|make)\b.{0,30}\bjokes?\b|^(?:\w+ )?(?:a |another |one more |more |funny )?jokes?\b"
                  r"|\bjokes? (?:please|time|about)\b|\b(?:another|one more|a different|a new|a funny|a good|a silly) jokes?\b|\bmake me laugh\b")
_NOT = re.compile(r"\b(?:was|is|its|that s|thats|not|no|just|only) (?:a |my |the )?jokes?\b|\bjoking\b|\bi (?:know|have|got|made) (?:a|one)\b.{0,12}\bjoke\b"
                  r"|\b(?:my|i ll tell|let me tell|can i tell|i want to tell) (?:you )?(?:a |my )?joke\b|\bno (?:more )?jokes?\b")
_AGAIN = re.compile(r"^(?:\w+ )?(?:another|another one|one more|again|more|do another|tell another)(?: one| please)?$")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower().replace("'", " ")).split())


def wants(text: str, just_told: bool = False) -> bool:
    """The child asks a toy for a joke (not: tells one, or says something was a joke). "Another one!" counts right after a joke."""
    t = _norm(text)
    if not t or len(t.split()) > 12 or _NOT.search(t):
        return False
    return bool(_ASK.search(t)) or (just_told and bool(_AGAIN.search(t)))


class Teller:
    """Hands out jokes without repeating one until all were told; a toy's own kind first now and then."""

    def __init__(self, seed=None):
        self.rnd, self.left = random.Random(seed), []

    def next(self, toy: str | None = None) -> str:
        if not self.left:
            self.left = JOKES[:]
            self.rnd.shuffle(self.left)
        own = [j for j in self.left if any(w in j.lower() for w in BY_TOY.get(toy or "", ()))]
        j = own[0] if own and self.rnd.random() < 0.4 else self.left[0]
        self.left.remove(j)
        return j
