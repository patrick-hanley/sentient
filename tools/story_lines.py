"""The six read-aloud stories of "Sentient sound-scene cards.md", as a child would read them: a sentence, the pause after it
(seconds, for the live check) and the sounds the toys should add at that pause, in order. The wording follows the public-domain
texts (Grimm; Dasent's Norse tales; Jacobs' English Fairy Tales; Andersen), shortened. Used by tools/test_harness.py (the word
table alone) and tools/mac_story_check.py (live, judged by the Mac's microphone)."""

STORIES = {
    "bremen": [   # AU01, Grimm
        ("A man had a donkey who had carried sacks to the mill for many years.", 5, ["donkey"]),
        ("On the road he found a hound, lying and panting.", 5, ["dog"]),
        ("Then they came to a cat, sitting on the path, with a face like three rainy days.", 5, ["cat"]),
        ("A rooster sat on the gate, crowing with all his might.", 6, ["rooster"]),
        ("They saw a light far away and walked toward it.", 4, []),
        ("Inside the house, robbers were sitting at a table full of good food.", 4, []),
        ("The donkey brayed, the hound barked, the cat mewed, and the rooster crowed.", 10, ["donkey", "dog", "cat", "rooster"]),
        ("Then they burst through the window, so that the glass clattered.", 5, ["glass"]),
        ("And the four musicians lived happily in the house.", 4, []),
    ],
    "billy_goats": [   # AU02, Asbjornsen and Moe (Dasent)
        ("Once upon a time there were three billy goats, and the name of all three was Gruff.", 5, ["goat"]),
        ("On the way up was a bridge over a stream they had to cross.", 4, []),
        ("Under the bridge lived a great ugly troll, with eyes as big as saucers.", 5, ["dino_roar"]),
        ("First of all came the youngest billy goat Gruff to cross the bridge.", 5, ["goat"]),
        ("Trip, trap, trip, trap, went the bridge.", 5, ["hooves"]),
        ("Who's that tripping over my bridge, roared the troll.", 5, ["dino_roar"]),
        ("Oh, it is only I, the tiniest billy goat Gruff, said the goat in a small voice.", 5, ["goat"]),
        ("Then came the big billy goat Gruff, trip, trap, trip, trap, and the bridge creaked and groaned under him.", 8,
         ["goat", "hooves", "door_creak"]),
        ("He flew at the troll and tossed him out into the river.", 6, ["dino_roar", "splash"]),
        ("Snip, snap, snout, this tale's told out.", 4, []),
    ],
    "three_pigs": [   # AU03, Jacobs
        ("There was an old sow with three little pigs.", 5, ["pig"]),
        ("The first little pig built his house of straw.", 5, ["pig"]),
        ("Presently along came a wolf, and knocked at the door.", 6, ["wolf", "knock"]),
        ("Little pig, little pig, let me come in.", 5, ["pig"]),
        ("No, no, by the hair of my chinny chin chin.", 4, []),
        ("Then I'll huff, and I'll puff, and I'll blow your house in.", 5, ["puff"]),
        ("So he huffed, and he puffed, and he blew the house in.", 5, ["puff"]),
        ("The third little pig built his house of bricks.", 5, ["pig"]),
        ("The wolf huffed and puffed, but he could not get the house down.", 6, ["wolf", "puff"]),
        ("The little pig hung a pot full of water over a blazing fire.", 5, ["pig"]),
        ("The wolf came down the chimney and fell into the pot with a great splash.", 6, ["wolf", "splash"]),
        ("And the little pig lived happily ever afterwards.", 5, ["pig"]),
    ],
    "three_bears": [   # AU04, Southey / Jacobs
        ("Once upon a time there were three bears who lived together in a house in a wood.", 5, ["dino_growl"]),
        ("They made porridge for their breakfast and poured it into their bowls.", 5, ["slurp"]),
        ("A little girl named Goldilocks came to the house and knocked at the door.", 5, ["knock"]),
        ("She tasted the porridge of the little wee bear, and ate it all up.", 6, ["slurp", "dino_growl"]),
        ("Then she sat in the little chair, and it broke all to pieces.", 5, ["crack"]),
        ("Then Goldilocks went upstairs and fell fast asleep in the little bed.", 6, ["footsteps", "snore_big"]),
        ("Somebody has been eating my porridge, said the great big bear in his great, rough, gruff voice.", 6, ["slurp", "dino_growl"]),
        ("Somebody has been sitting in my chair, and has broken it all to pieces, cried the little wee bear.", 6, ["crack", "dino_growl"]),
        ("Goldilocks woke up, jumped out of the window, and ran away.", 4, []),
    ],
    "henny_penny": [   # AU05, Jacobs
        ("One day Henny Penny was picking up corn in the yard when, whack, an acorn hit her upon the head.", 6, ["hen", "pumpkin_thump"]),
        ("Goodness gracious me, said Henny Penny, the sky is falling, I must go and tell the king.", 5, ["hen"]),
        ("She went along until she met Cocky Locky.", 5, ["rooster"]),
        ("Then they met Ducky Daddles.", 5, ["duck"]),
        ("Then they met Goosey Poosey.", 5, ["goose"]),
        ("Then they met Turkey Lurkey.", 5, ["turkey"]),
        ("So they all went along until they met Foxy Woxy.", 4, []),
        ("Foxy Woxy said, I know the proper way, shall I show it to you?", 4, []),
        ("They went into a dark, narrow hole, the door of Foxy Woxy's cave.", 4, []),
        ("Henny Penny turned tail and ran back home, so she never told the king the sky was falling.", 5, ["hen"]),
    ],
    "emperor": [   # AU06, Andersen
        ("Many years ago there was an emperor who was so fond of new clothes that he spent all his money on them.", 4, []),
        ("One day two swindlers came, and said they could weave the finest cloth anyone could imagine.", 4, []),
        ("So the emperor walked in the procession under the beautiful canopy.", 6, ["trumpet"]),
        ("All the people in the street said, how beautiful the emperor's new clothes are!", 6, ["crowd"]),
        ("But he has nothing on at all, said a little child.", 4, []),
        ("And one whispered to another what the child had said.", 6, ["crowd"]),
        ("But he has nothing on at all, cried all the people at last.", 6, ["crowd"]),
        ("And the chamberlains walked on, holding the train that was not there.", 4, []),
    ],
}

# recordings these stories need that tools/fetch_sfx.py had not fetched before Nov 22
NEW_SOUNDS = ("goat", "hooves", "puff", "slurp", "crack", "hen", "goose", "turkey", "trumpet", "crowd")
