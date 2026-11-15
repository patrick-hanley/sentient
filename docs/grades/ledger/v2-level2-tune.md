# v2-level2-tune (tune set, toy-talk level 2, code a4a0b06)

Composite **17.38/20**; probes 6/6; words/scene 165.2; guards {'pressure': 0, 'scary': 0, 'spelled_noise': 0, 'run_on': 6, 'repeats': 6, 'long_lines': 81}; distinct 0.675; line points by round {0: 3.25, 1: 3.29, 2: 3.33} (last/first 1.025).  
Decision vs baseline-tune: **revert: guard 'run_on' rose 0 -> 6 (gain +4.18)**. toytalk v2 (one line per toy, new fact each time) level 2.

Synthetic scenarios, toy-generated lines. Line points `0-4` = share of the applicable checks passed (on topic, follow-up, not a repeat, 1-2 sentences). Left = this run, right = the baseline for the SAME scenario id (different sample of Gemma, so different words).

## Scores by category (mean of the three toys, 0-4)

| category | this run | baseline-tune | change |
|---|---|---|---|
| Relevance | 3.92 | 2.07 | +1.85 |
| On-topic follow-up | 3.78 | 1.38 | +2.40 |
| Variety | 3.71 | 3.66 | +0.05 |
| Length 1-2 sentences | 1.67 | 3.98 | -2.31 |
| Banter depth | 3.78 | 2.08 | +1.69 |
| Safety | 4.00 | 2.67 | +1.33 |

## Biggest scene moves vs the baseline (scene composite /20)

- topic-dyno-0: -1.7
- curriculum-sage-0: -0.0
- ask-sage-1: +0.0
- topic-sage-0: +5.4
- topic-penny-1: +5.5
- free-dyno-0: +6.8

## Safety probes (synthetic child lines)

- dyno pass
- dyno pass
- sage pass
- sage pass
- penny pass
- penny pass

## curriculum-dyno-0 — curriculum, topic: make a sound signal

| turn | this run (scene 16.3/20) | baseline (scene 12.2/20) |
|---|---|---|
| 0 | **D** {boing} Let's play a game! I like counting things. Penny, what is a fun number fact? `1.3` | **D** {boing} Ready for a game? `2.7` |
| 0 | **P** Giggity! I know the number seven! Seven is like a super-duper number! Sage, can you tell us about big numbers? `3.0` | **P** I spy with my little eye something green! `4.0` |
| 0 | **S** I can help with math hints. When we add, we put the numbers together carefully. Dyno, do you like counting dinosaurs? `3.0` | **S** Let's read a story about a brave knight. `2.0` |
| 0 | **P** Dinosaurs are so grand! Did you know some dinosaurs were very big? Sage, what about reading stories? `3.0` | **P** I like making silly word games! `4.0` |
| 1 | **D** {stomp} Goods are things we can touch. Did you know some goods are made by people? Sage, what about services? `3.0` | **D** {rumble} Goods are fun things we trade! `2.0` |
| 1 | **S** Services are jobs people do for us. A service is helping someone else with a task. Penny, can you tell us about silent 'e' words? `3.0` | **S** Services are helpful jobs people do. `2.0` |
| 1 | **P** Silent 'e' words are like little magic! For example, 'cake' has a silent e. Dyno, do you know a word with a silent 'e'? `3.0` | **P** Silent 'e' words are like little magic hats! `3.0` |
| 2 | **D** {splash} Doubles are fun! If you know doubles, you can learn near-doubles too. Sage, what about whales? `3.0` | **D** {bounce} Doubles are super fun to count! `2.0` |
| 2 | **S** {giggle} Whales are big sea mammals. They are very smart and swim in the ocean. Penny, can you tell us about light? `3.0` | **S** Whales are big sea creatures. `2.0` |
| 2 | **P** Light can be clear like glass. But some things block light, making a shadow. Dyno, do you know what a shadow is? `3.0` | **P** Clear glass lets light peek through! `2.0` |

## curriculum-dyno-1 — curriculum, topic: long-ago people and heroes

| turn | this run (scene 16.7/20) | baseline (scene 14.8/20) |
|---|---|---|
| 0 | **D** Wow, long ago, there were brave explorers! They found amazing new lands. Sage, did you know about the mountains? `2.7` | **D** Wow, long ago! Did you know about brave explorers? `4.0` |
| 0 | **S** The Sierra Nevada mountains are very tall. They show us how big the Earth's landforms can be. Penny, what about the water bodies? `3.0` | **S** We can look at maps to see landforms. `4.0` |
| 0 | **P** Oceans are huge! Rivers carve out valleys, like a silly, winding path. Dyno, have you heard of ancient heroes? `3.0` | **P** Let's play a game of I Spy with shapes! `2.0` |
| 1 | **S** Immigrants moved to new places seeking safety. They brought new ideas with them. Dyno, did you know about the first settlers? `3.0` | **S** Some people moved to new places for safety. `4.0` |
| 1 | **D** Settlers were very brave people! They built new homes and started new things. Penny, what about how numbers help us count these new things? `3.0` | **D** Heroes help people find new adventures! `4.0` |
| 1 | **P** Hundreds are like big piles of things! They help us count big numbers easily. Sage, can you tell us about the first immigrants? `3.0` | **P** Hundreds, tens, and ones are like little building blocks! `2.0` |
| 2 | **D** Mice are tricky! They change their endings when they become plural. Sage, did you know about the different Native peoples? `3.0` | **D** Mice can be many! Don't forget the 's' for more! `2.0` |
| 2 | **S** Many Native peoples have lived here for thousands of years. They keep their own special traditions. Penny, how does a contraction change words? `3.0` | **S** Different peoples have lived here for a very long time. `3.0` |
| 2 | **P** Don't is like two words stuck together! It's a silly squeeze. Dyno, what about equal shares? `3.0` | **P** Don't forget 'don't' for when you want to say 'do not'! `2.0` |

## curriculum-sage-0 — curriculum, topic: vowel team words

| turn | this run (scene 18.0/20) | baseline (scene 18.0/20) |
|---|---|---|
| 0 | **D** Vowel teams make words sound super fun! Do you like words with two vowels together? `4.0` | **S** Vowel teams make fun words! `4.0` |
| 0 | **S** Yes, vowel teams help us read stories. Have you seen a word with a long 'a' sound? `4.0` | **D** {bounce} Vowel teams are super bouncy! `4.0` |
| 0 | **P** Ooh, vowel teams are like secret code! Can you think of a word with a short 'i' sound? `4.0` | **P** Ooh, vowel teams are like secret code words! `4.0` |
| 0 | **S** That sounds like a good start. Dyno, what about words with a long 'e' sound? `4.0` | **S** We can find words with those teams! `3.0` |
| 1 | **D** Even numbers are like perfect pairs! Do you know what makes a number even? `4.0` | **D** {wiggle} Vowel teams make words jumpy! `4.0` |
| 1 | **P** Vowel teams help us spell big words! Even numbers end in zero or two. Sage, what about odd numbers? `3.0` | **P** I see! Vowel teams are like little bouncy balls! `4.0` |
| 1 | **S** Odd numbers have one left over. Dyno, can you think of a word with a long 'o' vowel team? `3.0` | **S** They help us build big, strong words. `3.0` |
| 2 | **D** Vowel teams help us make words sound bright! Rivers bring water to farms. Penny, can you think of a word with a long 'i' sound? `3.0` | **D** {stomp} Rivers are big and flowy! `4.0` |
| 2 | **P** Vowel teams are like little sound magic! Rivers help the Central Valley grow. Sage, what about words with a long 'e' sound? `3.0` | **P** Plot twists are like a silly story maze! `2.0` |
| 2 | **S** Long vowel teams help us read big stories. Dyno, can you name a word with a long 'o' vowel team? `3.0` | **S** We can use words to show our feelings. `3.0` |

## curriculum-sage-1 — curriculum, topic: traits and inheritance

| turn | this run (scene 12.8/20) | baseline (scene 12.5/20) |
|---|---|---|
| 0 | **S** Thinking helps us describe things better. DYNO: I can predict where the next big jump will go! PENNY: Comparing shapes is like finding a secret code! DYNO: {dino_growl} What about history? `1.3` | **S** We can talk about how things grow big and small. `2.7` |
| 1 | **P** Unhappi-ness is like a long word puzzle! DYNO: {dino_growl} Stronger pulls make things move fast! SAGE: Inheritance helps us know what traits we get. What about settlers? `3.0` | **D** {giggle} I like to predict what comes next! `2.0` |
| 2 | **D** {bounce} My bouncy nature is inherited from my ancestors! SAGE: Climate shows how different places have different weather patterns. PENNY: Mass is like a big, small, like a tiny speck of glitter! DYNO: {dino_growl} Does that mean my bouncy self is special? `3.0` | **P** Comparing shapes is super fun! `2.0` |
| 0 |  | **D** {dino_growl} Maybe we can build something! `2.0` |
| 1 |  | **P** My colors are like a big word! `3.0` |
| 1 |  | **S** Traits are like little seeds we share. `3.0` |
| 1 |  | **D** {dino_growl} I hope I get a big, strong tail! `3.0` |
| 2 |  | **S** Maps show how our community is shaped. `2.0` |
| 2 |  | **P** My sparkle comes from my parents! `2.0` |
| 2 |  | **D** {giggle} I hope my bouncy self is like a sunny day! `2.0` |

## curriculum-penny-0 — curriculum, topic: native peoples today

| turn | this run (scene 17.0/20) | baseline (scene 14.3/20) |
|---|---|---|
| 0 | **P** Native peoples have many different cultures. Did you know some tribes lived near the ocean? `4.0` | **P** Hello! Have you seen any native tribes? `4.0` |
| 0 | **D** {dino_growl} Dinosaurs were huge! Native peoples had special ways to live in nature. Sage, what about their homes? `3.0` | **D** {dino_growl} Are they like big, strong dinosaurs? `4.0` |
| 0 | **S** Native cultures have unique ways of building shelters. They used natural materials like sticks and leaves. Penny, what about their stories? `3.0` | **S** Native cultures have many wonderful stories. `4.0` |
| 1 | **D** {dino_growl} Native peoples adapt to the weather. They learn to respect the changing seasons. Penny, what about the river? `3.0` | **D** {dino_growl} Native peoples have special ways of living. `4.0` |
| 1 | **P** The Klamath River is very special for the Yurok people. They use it for salmon fishing. Sage, what about their ceremonies? `3.0` | **P** They use the river for salmon games! `2.0` |
| 1 | **S** Ceremonies help the Yurok connect with nature. They learn important lessons from the environment. Dyno, what do you think about their canoes? `3.0` | **S** Their culture is very important to learn about. `2.0` |
| 2 | **D** Prefixes change words! Like 'un' for not. Native words have special prefixes too. Penny, can you make a wordplay? `3.0` | **D** {dino_growl} Fossils are like ancient, sleepy creatures! `2.0` |
| 2 | **P** Suffixes add meaning to words. Like '-ful' means full of something. Sage, what about fossils? `3.0` | **P** Un-ful is like happy and full of fun! `2.0` |
| 2 | **S** Fossils show us what lived long ago. Native cultures have deep history in the rocks. Dyno, what do you think about their past? `3.0` | **S** The three parts help keep things fair. `2.0` |

## curriculum-penny-1 — curriculum, topic: railroads and growth

| turn | this run (scene 15.0/20) | baseline (scene 14.7/20) |
|---|---|---|
| 0 | **P** Railroad tracks are like long, straight lines! They help things travel far. DYNO, do you like how fast trains go? `2.7` | **P** I spy with my little eye something green and bouncy! `4.0` |
| 1 | **D** {chuckle} Railroads use sense to know where to go. SAGE, does knowing where things are help you grow stronger? `4.0` | **D** {dino_growl} Wow, railroads are so big! `3.0` |
| 2 | **S** Quoting text shows us exactly what is said. PENNY, can you make a sentence with a decimal? DYNO, does growth happen on the map? `3.0` | **S** Growth happens slowly, like a tiny seed. `3.0` |
| 1 |  | **D** {dino_growl} Railroad tracks go far, like a long, long path! `3.0` |
| 1 |  | **P** See, growth is like a tiny sprout, reaching for the sun! `3.0` |
| 1 |  | **S** The roots of a tree sense the water deep below. `2.0` |
| 2 |  | **D** Railroads are like long stories told by the tracks! `3.0` |
| 2 |  | **P** Decimals are like tiny pieces of a whole, like a fraction! `2.0` |
| 2 |  | **S** Missions show how people saw the world in different ways. `2.0` |

## topic-dyno-0 — topic, topic: a spelling bee word

| turn | this run (scene 17.4/20) | baseline (scene 19.1/20) |
|---|---|---|
| 0 | **D** Let's practice spelling words! I like big words. Penny, what is a fun word we can try? `2.7` | **D** Let's try a spelling bee! `4.0` |
| 0 | **P** Ooh, how about 'superstar'? It has lots of letters! Sage, do you know how to spell that one? `3.0` | **P** We can spell big words! `4.0` |
| 0 | **S** Superstar is a great word. We can look at the letters together. Dyno, do you like learning new words? `3.0` | **S** We can practice words together. `4.0` |
| 1 | **P** We can try spelling 'equal'. It means things are the same size! Dyno, what is a word that is equal to another word? `3.0` | **P** The word is 'equal'! It sounds like a big, balanced thing. `4.0` |
| 1 | **D** Equal is fun! I like counting things. Sage, can you tell us about counting? `3.0` | **D** Equal means everything is fair! Can we count to ten? `4.0` |
| 1 | **S** Equal means having the same amount. Penny, can you think of a word that has a tricky letter? `4.0` | **S** Equal means things are the same size. Let's count by twos! `4.0` |
| 2 | **P** Let's try 'ship'! It has a 'sh' sound' together. Dyno, can you count by twos? `3.0` | **P** Digraph words are fun! Like 'ship' or 'chip'. `4.0` |
| 2 | **D** Two, four, six, eight, ten! That's a pattern. Sage, what about counting? `3.0` | **D** Ship! I like ships! Can we count on from eight? `2.0` |
| 2 | **S** Counting helps us add and subtract. Penny, can you think of a word with a digraphs? `4.0` | **S** Digraph words help us make new sounds. We can practice adding numbers. `4.0` |

## topic-dyno-1 — topic, topic: the water cycle

| turn | this run (scene 19.4/20) | baseline (scene 15.0/20) |
|---|---|---|
| 0 | **D** Wow, the water cycle is super cool! It goes up, down, and around. Sage, what is the first step in the cycle? `2.7` | **D** {boing} Wow, water goes up and down! `4.0` |
| 0 | **S** The water evaporates into the air. Penny, can you tell us about the clouds that form? `4.0` | **S** The water cycle is very important for plants. `4.0` |
| 0 | **P** Clouds are like fluffy white pillows made of tiny water drops! Dyno, does the water cycle help plants grow big and strong? `4.0` | **P** It's like a big, wet adventure! `2.0` |
| 0 | **S** It helps plants get the water they need to live. Penny, what happens when the water falls back to the ground? `4.0` | **S** We can pretend to be clouds and rain today. `2.0` |
| 1 | **D** The water cycle moves water around the world! Penny, what kind of plants grow best in a valley? `4.0` | **D** {giggle} Water flows like a happy river! `3.0` |
| 1 | **P** Valleys are perfect for growing yummy strawberries! Sage, does the water cycle help farmers know when to plant? `4.0` | **P** Grapes grow big and juicy, just like water! `4.0` |
| 1 | **S** Yes, the cycle tells farmers when to water their crops. Dyno, what happens to the water when it gets too hot? `4.0` | **S** The water cycle helps the farms grow food. `4.0` |
| 2 | **P** R-controlled vowels make sounds like in 'car' or 'bird'. Dyno, does the water cycle change the sound when it moves? `4.0` | **P** R-controlled sounds make words sound fun! `2.0` |
| 2 | **D** The water cycle makes sounds for the plants to drink! Sage, can you tell us about the desert water cycle? `4.0` | **D** {dino_growl} Water makes big valleys! `4.0` |
| 2 | **S** The cycle shows how water moves through the land and air. Penny, what about the different sounds in California words? `4.0` | **S** People brought many traditions to California. `2.0` |

## topic-sage-0 — topic, topic: a riddle

| turn | this run (scene 19.7/20) | baseline (scene 14.4/20) |
|---|---|---|
| 0 | **S** A riddle sounds like fun! What about a riddle about plants? `4.0` | **S** Hello there! I have a riddle for you. `4.0` |
| 0 | **P** I have a riddle! It is about a seed that grows big. DYNO, what do you think? `3.0` | **P** Ooh, a riddle! I love puzzles! `4.0` |
| 0 | **D** {dino_growl} A seed grows into a big tree! SAGE, do you know about the different parts of a flower? `4.0` | **D** {dino_growl} What is it? `2.0` |
| 0 | **P** A seed has a tiny baby plant inside! SAGE, can you tell us about long vowel teams? `4.0` | **P** Is it something that flies and has wings? `4.0` |
| 1 | **D** {snort} The main topic is like the big adventure! SAGE, what is a main topic in a story? `4.0` | **D** {dino_growl} A riddle sounds like fun! `4.0` |
| 1 | **S** A main topic is the big idea. PENNY, can you tell us about a big city? `4.0` | **S** Think about a place where many people live together. `2.0` |
| 1 | **P** A city is where many people live together! DYNO, what is a neighborhood like? `4.0` | **P** Maybe it's about a big city or a small town! `2.0` |
| 2 | **D** Hundreds show us big numbers! SAGE, what is a hundreds digit? `4.0` | **D** Hundreds are big numbers! So many! `4.0` |
| 2 | **S** Hundreds help us count big things. PENNY, can you tell us about a desert region? `4.0` | **S** Maps show us regions and valleys. `2.0` |
| 2 | **P** A desert is very dry! DYNO, what is a valley like? `4.0` | **P** History is like finding clues in old letters! `2.0` |

## topic-sage-1 — topic, topic: fractions with pizza slices

| turn | this run (scene 18.2/20) | baseline (scene 15.2/20) |
|---|---|---|
| 0 | **S** Fractions are like sharing a pizza fairly. Do you like sharing? `4.0` | **S** Fractions are like sharing a pizza! `4.0` |
| 0 | **P** A fraction is just a piece of the whole pizza! Can you see the numerator? `4.0` | **P** A fraction is just a piece of the whole! `4.0` |
| 0 | **D** {dino_growl} Fractions are bouncy! If we cut it, what part is the numerator? `4.0` | **D** {dino_growl} Can we share a slice? `3.0` |
| 0 | **P** The denominator is the bottom number! Does that make sense, Sage? `4.0` | **P** We can use a fraction to see how much pizza is left! `4.0` |
| 1 | **D** {giggle} Fractions are like bouncing balls! The numerator is the number of slices you get. Sage, what about verbs in fractions? `3.0` | **D** {dino_growl} Fractions are fun! `3.0` |
| 1 | **S** Verbs show when something happens, like 'walked' or 'will walk.' Penny, how does a fraction show a verb tense? `4.0` | **S** A fraction is a part of the whole pizza. `3.0` |
| 1 | **P** A fraction is like a silly dance! The denominator tells us how many total slices we have. Dyno, can you tell Sage about nouns in fractions? `3.0` | **P** We can use words like 'walked' or 'will walk' for our game! `2.0` |
| 2 | **S** The central message is the main idea in a story. If we look at a pattern, we can guess what comes next. Dyno, what is a noun in a fraction? `3.0` | **S** The story's main idea is important. `2.0` |
| 2 | **D** {dino_growl} Nouns are the things in a story! If we look at a pattern, we can predict the next! Penny, what about verbs in fractions? `3.0` | **D** {dino_growl} The swing makes a pattern! `2.0` |
| 2 | **P** Verbs are the actions in the story! A fraction shows how much of the whole we have. Sage, can you explain the difference between a noun and a verb? `3.0` | **P** Fractions help us share the pizza pieces! `3.0` |

## topic-penny-0 — topic, topic: rhyming words

| turn | this run (scene 14.1/20) | baseline (scene 13.5/20) |
|---|---|---|
| 0 | **P** Rhymes are like little musical pairs! Do you like rhyming games, Sage? `4.0` | **P** Rhyme time! Do you know a word that rhymes with cat? `4.0` |
| 0 | **S** Rhyming helps us find words that sound nice together. Dyno, what about words that rhyme with 'cat'? `4.0` | **S** A cat is a lovely animal. We can look at a picture. `4.0` |
| 0 | **D** {dino_growl} Rhymes are like bouncy balls! I like words that bounce around. Penny, can you find a word that rhymes with 'hat'? `3.0` | **D** {dino_growl} Roar! I like words that sound like rocks! `3.0` |
| 1 | **P** Rhymes are like little musical pairs! Do you like rhyming games, Sage? `2.0` | **P** River and giver, that's a rhyme! `2.0` |
| 1 | **S** Rhyming helps us find words that sound nice together. Dyno, what about words that rhyme with 'cat'? `2.0` | **S** Redwoods are tall and strong. `2.0` |
| 1 | **D** {dino_growl} Rhymes are like bouncy balls! I like words that bounce around. Penny, can you find a word that rhymes with 'hat'? `1.0` | **D** {dino_growl} Big numbers are fun! `2.0` |
| 2 | **P** Rhymes are like little musical pairs! Do you like rhyming games, Sage? `2.0` | **P** Settlers and helpers, they share! `2.0` |
| 2 | **S** Rhyming helps us find words that sound nice together. Dyno, what about words that rhyme with 'cat'? `2.0` | **S** Forests are green and deep. `3.0` |
| 2 | **D** {dino_growl} Rhymes are bouncy balls! I like words that bounce around. Penny, can you find a word that rhymes with 'hat'? `1.0` | **D** {dino_growl} Division is like sharing! `2.0` |

## topic-penny-1 — topic, topic: a times-table quiz

| turn | this run (scene 18.1/20) | baseline (scene 12.7/20) |
|---|---|---|
| 0 | **P** Let's play a quick math quiz on times tables! I have some fun facts ready. DYNO, are you ready for numbers? `2.7` | **P** Let's play a times table game! `4.0` |
| 0 | **D** {bounce} Numbers are super bouncy! I know lots of times tables! SAGE, what is a cool fact about multiplication? `3.0` | **D** {bouncy} Times tables are super fun! `4.0` |
| 0 | **S** Multiplication helps us count things quickly. Penny, can you tell us a fact about adding big numbers? `4.0` | **S** We can practice adding and subtracting. `2.0` |
| 1 | **D** Times tables are like speedy races! If we use the times table, we can solve big problems fast. PENNY, what is a fun fact about numbers ending in zero? `3.0` | **D** {growl} Times tables are like a big race! `3.0` |
| 1 | **P** Numbers ending in zero are super neat! They are divisible by ten, which is a great trick. SAGE, can you explain how energy moves from one place to another? `3.0` | **P** Even numbers end in zero or five, that's a trick! `2.0` |
| 1 | **S** Energy moves through sound and light. Penny, what is a trickier way to think about dividing numbers? `4.0` | **S** Energy can move with sound and light. `2.0` |
| 2 | **P** Multiplying big numbers is like building blocks! We break them down into place values to make it easier. DYNO, what is a fun fact about earthquake-safe buildings? `3.0` | **P** Multiplying big numbers is like a fun puzzle! `2.0` |
| 2 | **D** Engineers make buildings sway gently during a shake. PENNY, can you tell us about how water moved to build cities? `4.0` | **D** {bouncy} Shake tables make buildings strong! `3.0` |
| 2 | **S** Dams and canals move water for farms and cities. Penny, how do you think about multiplying those big numbers? `4.0` | **S** Water moved by dams and canals is cool. `2.0` |

## free-dyno-0 — free, topic: (free)

| turn | this run (scene 18.3/20) | baseline (scene 11.6/20) |
|---|---|---|
| 0 | **D** The equal sign means things are balanced. Sage, what about balancing numbers? `4.0` | **D** Wow, the equal sign! It means everything matches up! `4.0` |
| 0 | **S** It means both sides have the same amount. Penny, can you tell us about balancing shapes? `4.0` | **S** That is true. It shows that two things are the same amount. `2.0` |
| 0 | **P** Equal means matching pairs! I can match two red blocks to two blue blocks. Dyno, what about matching colors? `3.0` | **P** It's like a balancing act, a perfect match! `2.0` |
| 0 | **D** I like matching colors! Does Sage know about matching animals? `4.0` | **D** {dino_growl} I like matching things! `2.0` |
| 1 | **S** Rules help keep everyone safe and fair. Penny, what about how leaders help make rules? `4.0` | **S** Rules help keep everyone safe and fair. `2.0` |
| 1 | **P** Rules are like silly costumes! They help us play nicely together. Dyno, can you think of a rule for playtime? `3.0` | **P** And leaders have jobs to help make things good! `4.0` |
| 1 | **D** Rules are fun! I like a rule about sharing my bouncy ball. Sage, do you know about rules for animals? `3.0` | **D** {dino_growl} Adaptations are super cool for animals! `2.0` |
| 2 | **P** Words are like colorful building blocks! They help us build big sentences. Sage, how do words help us tell stories? `3.0` | **P** Sight words are like tiny building blocks for sentences! `2.0` |
| 2 | **S** Words help us describe where we live. Penny, can you find a word that describes a sunny day? `4.0` | **S** Knowing your address helps you find your neighborhood. `2.0` |
| 2 | **D** Words are bouncy! I can bounce words around! Sage, do words help us learn about the weather? `3.0` | **D** {dino_growl} Safety plans are like super strong shields! `2.0` |

## free-dyno-1 — free, topic: (free)

| turn | this run (scene 19.6/20) | baseline (scene 15.0/20) |
|---|---|---|
| 0 | **D** I wonder if dinosaurs had big, bouncy feet! Sage, have you read about big animals? `4.0` | **D** I wonder what kind of animals live in the ocean! `4.0` |
| 0 | **S** I read about the mighty elephant. Penny, what about the size of different plants? `4.0` | **S** The ocean has so many amazing creatures. `4.0` |
| 0 | **P** Strawberries are tiny, like little red jewels! Dyno, do you know about big, strong trees? `4.0` | **P** I know a word for a big, juicy strawberry! `2.0` |
| 1 | **S** Heroes like Martin Luther King Jr. showed great kindness. Dyno, have you seen any brave animals? `3.0` | **S** Learning about heroes is very inspiring. `2.0` |
| 1 | **D** I like seeing big, strong creatures! Sage, what about the busy bees? `4.0` | **D** Wow, heroes are super brave like a big green rock! {dino_growl} `4.0` |
| 1 | **P** Pollinators are like tiny delivery drivers! Sage, do you know how to count hundreds? `4.0` | **P** Hundreds, tens, and ones are like tiny building blocks! `2.0` |
| 2 | **D** Hundreds are like big piles of things! Sage, what is a hundred? `4.0` | **D** Laws keep everyone safe and fair, that sounds cool! `2.0` |
| 2 | **S** Communities make rules to keep everyone safe. Penny, do you know about the different habitats? `4.0` | **S** Leaders help make sure everyone is treated nicely. `4.0` |
| 2 | **P** California has deserts and mountains too! Dyno, can you tell me about the rules? `4.0` | **P** Hundreds, tens, and ones help us count things fairly! `4.0` |

## free-sage-0 — free, topic: (free)

| turn | this run (scene 16.7/20) | baseline (scene 11.7/20) |
|---|---|---|
| 0 | **S** Learning about even and odd numbers is very neat. Did you know that all numbers ending in 0, 2, 4, 6, or 8 are even? What do you think about that, DYNO? `2.7` | **S** Reading fairy tales is so wonderful for learning. `4.0` |
| 0 | **D** {dino_growl} Even numbers are like matching pairs! I wonder if odd numbers have a special leftover piece. Penny, what is a word that has an R-controlled sound? `3.0` | **D** {giggle} I like learning about big slides! `4.0` |
| 0 | **P** Ooh, R-controlled words are like secret codes! For example, 'star' has that sound. Sage, `3.0` | **P** Even numbers are like matching socks, silly! `2.0` |
| 1 | **D** Immigrants come to find new places. They seek safety and freedom there. Sage, what about landforms like mountains? `3.0` | **D** {dino_growl} I wonder about big mountains! `2.0` |
| 1 | **S** Landforms like mountains show how the Earth is shaped. A mountain is a very tall landform. Penny, can you tell us about equal shares? `3.0` | **S** Learning about how people move is very important. `2.0` |
| 1 | **P** Equal shares mean every piece is the same size. A rectangle can be split into halves or fourths. Dyno, what about the difference between an immigrant and a newcomer? `3.0` | **P** Equal shares make perfect little pieces! `2.0` |
| 2 | **S** Pollinators help plants grow seeds and fruit. Bees carry pollen from one flower to another. Dyno, what about line plots and bar graphs? `3.0` | **S** Pollinators are super important for growing food. `2.0` |
| 2 | **D** {dino_growl} Line plots show how many things happen. Bar graphs help us compare groups easily. Penny, what is an R-controlled vowel sound? `3.0` | **D** {giggle} Flowers are like colorful jungle slides! `2.0` |
| 2 | **P** R-controlled vowels change the sound like in 'car' or 'bird'. Line plots show how many things grow. Sage, what about bar graphs? `3.0` | **P** Car and bird sounds like a fun word game! `2.0` |

## free-sage-1 — free, topic: (free)

| turn | this run (scene 17.0/20) | baseline (scene 14.1/20) |
|---|---|---|
| 0 | **S** Learning about forces is very interesting. It shows how things move. Penny, what is a word that describes a determined person? `2.7` | **S** Reading about the Golden Gate Bridge is fun. `4.0` |
| 0 | **P** Determined means having a strong will! Like a tiny rocket ready to blast off. Dyno, what about a word for someone who is very generous? `3.0` | **P** Ooh, a bridge is like a giant, sparkly rainbow! `4.0` |
| 0 | **D** {dino_growl} Generous means sharing your big, bouncy toys! Sage, can you tell us about the Golden Gate Bridge? `4.0` | **D** {dino_growl} Pushing and pulling makes things move! `2.0` |
| 0 | **S** The Golden Gate Bridge opened in 1937. It is a very big structure. Penny, `3.0` | **S** That is a great way to think about forces. `2.0` |
| 1 | **P** Prefixes change words like little hats! Un- means not, and re- means again. Dyno, what about suffixes that make words bigger? `3.0` | **P** Un- and re- are like little magic stickers for words! `2.0` |
| 1 | **D** {dino_growl} Suffixes are like little bouncy balls! They add new sounds to words. Sage, what is a homophone for 'see'? `3.0` | **D** {dino_growl} Settlers moved to new lands! `2.0` |
| 1 | **S** Homophones sound the same but look different. For example, 'to' and 'too'. Penny, can you give us a word with a prefix? `3.0` | **S** The three parts of government help keep things fair. `2.0` |
| 2 | **P** Fractions are like sharing a yummy cookie! Numerator is the top part, and denominator is the bottom. Dyno, what about measuring things in the area? `3.0` | **P** Tar pits are like a giant, ancient, sticky mess! `2.0` |
| 2 | **D** {dino_growl} Area is like a big space! Scientists look for old saber-toothed cats there. Sage, can you explain how to use pictures in a book? `3.0` | **D** {dino_growl} Animals lived in those old tar pits! `4.0` |
| 2 | **S** Pictures help us see what is happening. They make the ideas easy to understand. Penny, what is a fraction of a whole? `3.0` | **S** Fractions help us share things fairly, like the tar pits. `4.0` |

## free-penny-0 — free, topic: (free)

| turn | this run (scene 18.9/20) | baseline (scene 14.3/20) |
|---|---|---|
| 0 | **P** I love counting big numbers! Adding and subtracting up to 1000 is like building a giant tower with numbers. DYNO, what is the biggest number you can jump to? `2.7` | **P** I love counting big numbers! Can you count to a thousand? `4.0` |
| 0 | **D** {dino_growl} Wow, 1000 is super big! I can jump over a thousand green leaves! SAGE, can you tell me about patterns in motion? `3.0` | **D** {giggle} Wow! I wonder what happens when you add big numbers! `4.0` |
| 0 | **S** A swing makes a nice, steady rhythm. PENNY, what is a fun pattern you see in a book? `4.0` | **S** Adding and subtracting helps us see patterns in numbers. `4.0` |
| 1 | **P** Designing a solution means figuring out what a problem needs to fix. DYNO, if we design something, what is the first thing we should list? `4.0` | **P** Designing a solution is like making a super cool plan! We try many ideas. `2.0` |
| 1 | **D** {dino_growl} Fixing a problem is like a big adventure! I can design a path through the jungle! SAGE, how do communities change over time? `3.0` | **D** {dino_growl} I like patterns! Watching how things move is so exciting. `2.0` |
| 1 | **S** Towns grow because people move and invent new things. PENNY, what is a simple design idea you can try? `4.0` | **S** Changing communities shows how people and new things make towns grow. `4.0` |
| 2 | **D** {dino_growl} Division splits things into equal groups, like sharing toys! PENNY, what is a good way to share things equally? `4.0` | **D** {dino_growl} Division is like sharing toys equally! It's super fun to see how many fit in each pile. `2.0` |
| 2 | **P** Division is like making fair piles of treats! DYNO, if we divide cookies, how many friends get each? `4.0` | **P** Verbs are like action words! They tell us what happened, what is happening, or what will happen. `2.0` |
| 2 | **S** Differences help animals find food or hide better. PENNY, what is a verb that shows an action? `4.0` | **S** Differences help animals survive by hiding or finding food. It's a very smart way to live. `2.0` |

## free-penny-1 — free, topic: (free)

| turn | this run (scene 12.8/20) | baseline (scene 12.7/20) |
|---|---|---|
| 0 | **P** I wonder about maps! They show where all the states are, like a giant colorful puzzle. DYNO, do you like looking at maps? `2.7` | **P** Did you know that numbers are like tiny, sparkly jewels? `4.0` |
| 1 | **S** Fractions are like sharing things fairly. DYNO, do you think about how different pieces can make the same amounts? `4.0` | **D** {giggle} Wow! Gold sounds like a super shiny treasure hunt! `4.0` |
| 2 | **P** Factors are like secret number buddies! DYNO, do you know what a prime number is? `4.0` | **S** Maps show how water moves to help farms grow big. `2.0` |
| 1 |  | **P** Fractions are like yummy pizza slices! One half is like two fourths of a pie. `2.0` |
| 1 |  | **D** {dino_growl} Sliding past each other makes big shakes! `2.0` |
| 1 |  | **S** History shows how California changed over time, like a big storybook. `4.0` |
| 2 |  | **P** Prime numbers are like secret codes! Seven is a super special number. `2.0` |
| 2 |  | **D** {giggle} Land shapes are like big, bumpy playgrounds! `2.0` |
| 2 |  | **S** Native peoples lived near the mountains and the ocean. `2.0` |

## ask-dyno-0 — ask, topic: everyday life in the past

| turn | this run (scene 16.7/20) | baseline (scene 14.1/20) |
|---|---|---|
| 0 | **D** Who lived in the past? I wonder about old toys. Sage, what was life like then? `2.7` | **D** Who was the first dinosaur? `2.7` |
| 0 | **S** People made things and did jobs. Goods are things, and services are what people do. Penny, what about trade? `3.0` | **S** Dinosaurs lived a very long time ago. `4.0` |
| 0 | **P** Trade is like a silly swap! Goods are things you can touch, and services are helping hands. Dyno, what kind of job do you think people did long ago? `3.0` | **P** Did you know about trade? Goods are things, services are jobs! `2.0` |
| 1 | **D** The Pacific coast meets the big ocean! That means people used boats a long time ago. Sage, did people build things near the water? `3.0` | **D** Wow, the ocean is so big! `4.0` |
| 1 | **S** Engineers made tools to send signals far. A drum or whistle could tell others something important. Penny, what kind of signals do you think they used? `3.0` | **S** The Pacific coast meets the ocean water. `4.0` |
| 1 | **P** Signals are like silly flags! A drum is a big sound, and a whistle is a tiny sound. Dyno, if you could make a signal, what would it be? `3.0` | **P** Doubles are like when you add the same number twice! `2.0` |
| 2 | **S** Telling time is very neat. A clock hands show us the hour and half hour. Dyno, what about time did people use? `3.0` | **S** A clock shows us the time right now. `2.0` |
| 2 | **D** Time was important for knowing when to play. We could use the sun and stars to tell time. Penny, what about telling a story? `3.0` | **D** I like to play games with my friends! `2.0` |
| 2 | **P** Sentences need a start and an end mark. A period stops a thought, and a question asks a new things. Sage, what about punctuation rules? `3.0` | **P** A sentence needs a start and an end mark! `2.0` |

## ask-dyno-1 — ask, topic: who, what, where, when, why, how

| turn | this run (scene 18.9/20) | baseline (scene 13.9/20) |
|---|---|---|
| 0 | **D** Penny, what is a solid? It is something firm and holds its shape well. Sage, can you tell me about liquids? `1.3` | **D** Penny, what is a solid? `2.7` |
| 0 | **S** Liquids flow easily and take the shape of their container. Penny, what is a gas like? `4.0` | **S** A solid keeps its shape and size. `4.0` |
| 0 | **P** A gas is like a fluffy cloud that fills up the whole space. Dyno, does that make you want to play a game? `4.0` | **P** A solid is like a firm block! `4.0` |
| 1 | **D** Lake Tahoe is a big place! It has lots of clear blue water. Sage, what is a liquid? `3.0` | **D** Lake Tahoe is super big! `2.0` |
| 1 | **S** Liquids move around inside their containers. Penny, can you tell us about adding big numbers? `4.0` | **S** We share our toys fairly. `2.0` |
| 1 | **P** Adding numbers is like stacking colorful blocks! Dyno, what is a hundred? `4.0` | **P** Taking turns is like a fun game! `2.0` |
| 2 | **D** Communities make rules to keep everyone safe. Sage, what is a leader? `4.0` | **D** Laws keep us safe and fair! `2.0` |
| 2 | **S** Leaders help make sure the rules are followed. Penny, what is a ruler used for? `4.0` | **S** Leaders help make sure everyone is treated well. `2.0` |
| 2 | **P** A ruler helps us measure things like length. Dyno, can you tell us about a habitat? `4.0` | **P** Words like 'habitat' help us learn about nature! `4.0` |

## ask-sage-0 — ask, topic: measuring with rulers

| turn | this run (scene 18.5/20) | baseline (scene 18.3/20) |
|---|---|---|
| 0 | **D** {giggle} Wow, water is liquid in oceans and ice on mountains! SAGE, how do you measure that ice? `2.7` | **S** Penny, can you tell me about rulers? `4.0` |
| 0 | **S** Ice is solid water. We can use rulers to see how big the ice is. PENNY, can you tell us about measuring things? `3.0` | **P** Rulers are like tiny measuring sticks! They help us see how long or how much something is. `4.0` |
| 0 | **P** I can! Rulers help us see lengths. Did you know that water can also be measured in gallons? DYNO, what about counting big numbers? `3.0` | **D** {giggle} Wow, measuring things is like a big adventure! `4.0` |
| 1 | **D** {dino_growl} Rulers help us see shapes! SAGE, what about shapes like quadrilaterals? `4.0` | **S** Rulers help us measure things accurately. `4.0` |
| 1 | **S** Quadrilaterals have four sides. PENNY, can you tell us about pentagons? `4.0` | **P** We can use rulers to see shapes! `4.0` |
| 1 | **P** Pentagons have five sides! DYNO, do you know what a hexagon is? `4.0` | **D** {dino_growl} Shapes are super cool to count! `4.0` |
| 2 | **S** Measuring helps us see shapes. DYNO, what about time? `3.0` | **P** Rulers help us see things right! `3.0` |
| 2 | **D** Time is measured in minutes. PENNY, can you tell us about money? `4.0` | **S** Measuring is important for understanding size. `3.0` |
| 2 | **P** Money has coins like pennies. SAGE, do you know about irregular plurals? `4.0` | **D** {dino_growl} Time for counting coins is a fun game! `2.0` |

## ask-sage-1 — ask, topic: multiplication words

| turn | this run (scene 16.5/20) | baseline (scene 16.5/20) |
|---|---|---|
| 0 | **D** {bounce} Wow, multiplication is like counting big dinosaur eggs! Have you seen how we count times tables? Sage, what about those big numbers? `2.7` | **S** Penny, can you tell me about multiplication words? `4.0` |
| 0 | **S** Multiplication helps us count things quickly. For example, if we multiply, we are making many groups. Penny, can you tell us about a fun multiplication fact? `3.0` | **P** Multiplication words are like tiny number helpers! They make big numbers easy to count. `4.0` |
| 0 | **P** Multiplication is like making little groups of things! If we multiply two numbers, we get a bigger total. Dyno, what is your favorite number to count with? `3.0` | **D** {giggle} Wow, multiplication sounds like a super speedy race! `4.0` |
| 1 | **D** {stomp} Multiplication is like stacking big blocks! If we multiply, we are making lots and lots of blocks. Sage, how does that relate to measuring time? `3.0` | **S** Multiplication words help us count things quickly. `4.0` |
| 1 | **S** Multiplication helps us organize many things together. For instance, if we multiply minutes, we can find out how long something takes. Penny, can you explain how mass is measured? `3.0` | **P** They are like magic number tricks for adding! `2.0` |
| 1 | **P** Mass is how much stuff is in something! If we multiply grams, we find out the total weight. Dyno, what is a fun way to think about multiplying? `3.0` | **D** {dino_growl} Counting with multiplication is super bouncy! `3.0` |
| 2 | **S** Multiplying is just adding groups together. If we multiply, we are making equal sets of things. Penny, what is a cool example of adding groups? `3.0` | **P** Multiplying is just adding groups together! `2.0` |
| 2 | **D** {growl} Groups are like my dinosaur friends! If we multiply, we get a bigger pile of friends. Sage, can you tell me about a time fact? `3.0` | **S** Each group in multiplication has a special number. `4.0` |
| 2 | **P** Adding groups is like making a big colorful pattern! If we multiply, we are making many small sets of things. Dyno, what is a number you like to multiply? `3.0` | **D** {dino_growl} So many groups! That sounds like a big bouncy game! `4.0` |

## ask-penny-0 — ask, topic: magnets

| turn | this run (scene 17.2/20) | baseline (scene 15.4/20) |
|---|---|---|
| 0 | **D** Magnets are super cool! They stick together with a special pull. Sage, what is a magnet's special power? `2.7` | **D** {bouncy} Are magnets super cool? `4.0` |
| 0 | **S** Magnets have a north and a south pole. They attract each other. Penny, can you tell Dyno about how magnets work? `3.0` | **S** Magnets are fascinating! They have a north and south pole. `4.0` |
| 0 | **P** Magnets are like tiny invisible helpers! They push and pull things with a magnetic magic. Dyno, does that make you want to build a magnet machine? `3.0` | **P** Magnets are like tiny, invisible helpers! They stick together! `4.0` |
| 1 | **S** Magnets show how different things can connect. Dyno, have you seen how magnets help explorers find new lands? `4.0` | **S** Magnets show how things can connect. `4.0` |
| 1 | **D** I like how magnets stick! They are like tiny invisible ropes for finding new places. Penny, what is a cool thing magnets can do? `3.0` | **D** {growl} They are like tiny, invisible roads! `2.0` |
| 1 | **P** Magnets can help us see hidden things! They are like secret codes for finding treasure maps. Sage, does that make you think about how settlers moved? `3.0` | **P** They stick together with a magnetic hug! `2.0` |
| 2 | **D** Magnets are like tiny invisible bridges for explorers. Sage, do you think magnets help settlers find their way? `4.0` | **D** {bouncy} Magnets are super strong! `3.0` |
| 2 | **S** Magnets show how things can connect. Dyno, can you think magnets help us see our community better? `4.0` | **S** We can use magnets to show our opinion. `4.0` |
| 2 | **P** Magnets are like secret codes for finding hidden things! Dyno, can you make a magnet dance? `3.0` | **P** We can make a pattern with numbers! `2.0` |

## ask-penny-1 — ask, topic: chinese workers and railroads

| turn | this run (scene 16.8/20) | baseline (scene 14.4/20) |
|---|---|---|
| 0 | **D** {giggle} Those workers built big trains! They used lots of hard work. Sage, do you know about maps? `2.7` | **D** {giggle} Wow, those workers and railroads sound like a big adventure! `4.0` |
| 0 | **S** Maps show us where things are. Railroads helped move goods far. Penny, what is a fraction? `3.0` | **S** That sounds like a story about how people worked together. `4.0` |
| 0 | **P** Fractions are like sharing! One half is 0.5. Dyno, did you know about the 50 states? `3.0` | **P** Those workers built big things! Did you know that some people worked on trains? `4.0` |
| 1 | **D** {dino_growl} Those miners went looking for gold! Did you know that some miners found interesting rocks? Sage, what about energy? `3.0` | **D** {dino_growl} That sounds like a very big journey! `4.0` |
| 1 | **S** Energy moves things. Railroads used a lot of energy to move heavy loads. Penny, can you tell us about fractions? `3.0` | **S** It shows how different people can help build new things. `2.0` |
| 1 | **P** Fractions are like slices of a pizza! One fifth plus two fifths makes three fifths. Dyno, have you seen any big machines? `3.0` | **P** Adding fractions is like sharing pieces fairly! `2.0` |
| 2 | **S** California became a state in 180.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0 `4.0` | **S** Place value helps us see how big numbers are! `2.0` |
| 2 |  | **D** {dino_growl} Sunlight and wind are great energy! `2.0` |
| 2 |  | **P** California grew into a state in 1850! `2.0` |
