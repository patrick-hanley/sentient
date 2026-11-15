"""Fact guard (brain/factcheck.py): wrong checkable facts are fixed or dropped before a toy says them; true lines pass untouched.
The BAD lines include real ones Gemma produced in the graded runs (docs/grades/ledger)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain import config, factcheck as F
from brain.director import ReplyLines

FIXED = {  # wrong line -> what the toy says instead
    "If we have 100 and take away 10, we have zero! Silly subtraction!": "If we have 100 and take away 10, we have ninety! Silly subtraction!",
    "Factor and product are like counting! Five times five is twenty!": "Factor and product are like counting! Five times five is twenty-five!",
    "For example, three groups of five is twenty-five.": "For example, three groups of five is fifteen.",
    "A dollar is ten cents.": "A dollar is one hundred cents.",
    "Parallelograms have four equal sides.": "Parallelograms have four sides.",
    "Adventure has seven letters!": "Adventure has nine letters!",
    "Seven times eight is fifty-four.": "Seven times eight is fifty-six.",
    "2 plus 3 makes 6!": "2 plus 3 makes 5!",
    "A spider has six legs!": "A spider has eight legs!",
    "There are nine planets in our solar system.": "There are eight planets in our solar system.",
    "Venus is the biggest planet!": "Jupiter is the biggest planet!",
    "The capital of California is Los Angeles.": "The capital of California is Sacramento.",
    "Sacramento is the capital of Texas.": "Austin is the capital of Texas.",
    "Cat starts with K.": "Cat starts with C.",
    "Dog begins with D and ends with X!": "Dog begins with D and ends with G!",
    "Dog is spelled D-O-H.": "Dog is spelled D-O-G.",
    "A hexagon has five sides.": "A hexagon has six sides.",
    "There are 10 days in a week.": "There are 7 days in a week.",
    "Seven is an even number.": "Seven is an odd number.",
    "Let's count by fives: five, ten, sixteen!": "Let's count by fives: five, ten, fifteen!",
    "The sun is a planet.": "The sun is a star.",
    "Earth is the fourth planet from the sun.": "Mars is the fourth planet from the sun.",
    "Double 4 is 9!": "Double 4 is 8!",
    "Half of ten is four.": "Half of ten is five.",
    "An hour has 100 minutes.": "An hour has 60 minutes.",
    "A week has ten days, and a year has twelve months.": "A week has seven days, and a year has twelve months.",
    "Ship has two letters. Sage, what is a digraph?": "Ship has four letters. Sage, what is a digraph?",
}
DROPPED = {  # no safe fix: the wrong sentence is not said, the rest of the line is
    "Nine is bigger than twelve. Numbers are fun!": "Numbers are fun!",
    "The moon is a planet.": "",
}
TRUE = [
    "If we have 100 and take away 10, we have 90!", "Adventure has nine letters!", "Five, ten, fifteen!", "Parallelograms have four sides.",
    "A square has four equal sides.", "Seven times eight is fifty-six.", "Two and three make five.", "A spider has eight legs!",
    "There are eight planets.", "Jupiter is the biggest planet!", "The capital of California is Sacramento.", "Cat starts with C.",
    "Dog is spelled D-O-G.", "In two weeks there are fourteen days.", "Two spiders have sixteen legs.",
    "Mars is the red planet, and Jupiter is the biggest planet.", "Twelve is bigger than nine.", "One, two, three, go!",
    "I have three cats and two dogs.", "Often I count to ten.", "There are 50 states in the United States.", "The sun is a star.",
    "Earth is the third planet from the sun.", "Penny, what about division?", "Rivers are like long, wiggly ribbons!",
    "A week has seven days, and a year has twelve months.", "Sally Ride flew to space in 1983!", "Twenty-five is five times five.",
    "Mercury is closer to the sun than Venus.", "A sentence starts with a capital letter and ends with a period.",
    "Thin words have two letters.", "The capital of the United States is Washington, D.C.", "Ants have six legs and spiders have eight legs.",
    "Six times seven equals forty-two!", "Fractions are like pizza slices, one out of four!", "{dino_growl} Wow, the ocean is so big and blue!",
]


class GuardTests(unittest.TestCase):
    def test_wrong_facts_are_fixed(self):
        bad = {t: F.FactGuard().check(t) for t in FIXED}
        self.assertEqual({t: v for t, v in bad.items() if v != FIXED[t]}, {})

    def test_unfixable_wrong_sentences_are_dropped(self):
        for t, want in DROPPED.items():
            self.assertEqual(F.FactGuard().check(t), want, t)

    def test_true_lines_pass_untouched(self):
        self.assertEqual([t for t in TRUE if F.find(t) or F.FactGuard().check(t) != t], [])

    def test_a_question_answered_in_the_next_line_is_checked(self):
        for q, a, want in (("What is six times seven?", "Forty-one!", "Forty-two!"),
                           ("How many letters are in dog?", "Four letters!", "Three letters!"),
                           ("How many legs does a spider have?", "Six legs!", "Eight legs!"),
                           ("How many sides does a triangle have?", "Four!", "Three!"),
                           ("What is the capital of Texas?", "It is Dallas!", "It is Austin!"),
                           ("What is six times seven?", "Forty-two!", "Forty-two!"),
                           ("What's six times six?", "Six times seven equals forty-two!", "Six times seven equals forty-two!")):
            g = F.FactGuard()
            g.check(q)
            self.assertEqual(g.check(a), want, (q, a))

    def test_the_question_can_come_from_the_previous_turn_or_the_child(self):
        g = F.FactGuard(context=["what is nine plus nine"])
        self.assertEqual(g.check("Seventeen!"), "Seventeen!")       # the child's words have no '?': not a question to check against
        g = F.FactGuard(context=["Dyno: What is nine plus nine?"])
        self.assertEqual(g.check("Seventeen!"), "Eighteen!")

    def test_a_claim_cut_across_two_pieces_is_still_checked(self):
        g = F.FactGuard()
        first = "If we have 100 and take away 10,"
        self.assertEqual(g.check(first), first)
        self.assertEqual(g.check("we have zero!", first), "we have ninety!")
        self.assertEqual((g.fixed, g.dropped), (1, 0))

    def test_numbers_words_round_trip(self):
        for n in (0, 7, 13, 20, 42, 99, 100, 305, 1000, 2026):
            self.assertEqual(F.numbers(F.words(n))[0].value, n)

    def test_the_grader_count(self):
        self.assertEqual(F.errors(["What is six times seven?", "Forty-one!", "A spider has six legs."]), 2)
        self.assertEqual(F.errors(TRUE), 0)


class ReplyLinesTests(unittest.TestCase):
    def run_reply(self, text, chunks=8):
        said = []
        p = ReplyLines(["dyno", "sage", "penny"], lambda who, t: said.append((who, t)), lambda t: None)
        for i in range(0, len(text), chunks):     # streamed in small pieces, like the model
            p.feed(text[i:i + chunks])
        p.finish()
        return said

    def test_the_stream_is_fixed_before_it_is_spoken(self):
        said = self.run_reply("DYNO: What is six times seven?\nSAGE: Forty-one! That is a lot.\nPENNY: Three groups of five is twenty-five.\nHEARD: -\n")
        text = " ".join(t for _w, t in said)
        self.assertIn("Forty-two!", text)
        self.assertNotIn("Forty-one", text)
        self.assertIn("fifteen", text)
        self.assertNotIn("twenty-five", text)

    def test_a_line_with_numbers_is_not_cut_at_a_comma(self):
        said = self.run_reply("PENNY: If we have 100 and take away 10, we have zero! Silly!\nHEARD: -\n")
        self.assertEqual([t for _w, t in said if "ninety" in t or "zero" in t], ["If we have 100 and take away 10, we have ninety!"])

    def test_the_guard_can_be_switched_off(self):
        with patch.object(config, "FACT_GUARD", False):
            said = self.run_reply("SAGE: A spider has six legs.\nHEARD: -\n")
        self.assertEqual(said, [("sage", "A spider has six legs.")])


if __name__ == "__main__":
    unittest.main()
