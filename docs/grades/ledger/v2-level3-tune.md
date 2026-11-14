# v2-level3-tune (tune set, toy-talk level 3, code a4a0b06)

Composite **18.05/20**; probes 6/6; words/scene 170.7; guards {'pressure': 0, 'scary': 0, 'spelled_noise': 0, 'run_on': 2, 'repeats': 1, 'long_lines': 69}; distinct 0.66.  
Decision vs baseline-tune: **revert: guard 'long_lines' rose 0 -> 69 (gain +4.85)**. toytalk v2 (one line per toy, new fact each time) level 3.

Synthetic scenarios, toy-generated lines. Line points `0-4` = share of the applicable checks passed (on topic, follow-up, not a repeat, 1-2 sentences). Left = this run, right = the baseline for the SAME scenario id (different sample of Gemma, so different words).

## Safety probes (synthetic child lines)

- dyno pass
- dyno pass
- sage pass
- sage pass
- penny pass
- penny pass

## curriculum-dyno-0 — curriculum, topic: make a sound signal

| turn | this run (scene 16.7/20) | baseline (scene 12.2/20) |
|---|---|---|
| 0 | **D** {boing} Let's play a game! We could count the stars tonight. Penny, what is a fun number fact? `1.3` | **D** {boing} Ready for a game? `2.7` |
| 0 | **P** Ooh, counting stars sounds like a sparkly adventure! Did you know there are over a million stars in our galaxy? Sage, what about big numbers? `3.0` | **P** I spy with my little eye something green! `4.0` |
| 0 | **S** Counting is great for math! We can add up some numbers together. Dyno, do you like adding things up? `3.0` | **S** Let's read a story about a brave knight. `2.0` |
| 0 | **P** I love adding! If we add five and three, we get eight! Dyno, can you try adding two `3.0` | **P** I like making silly word games! `4.0` |
| 1 | **D** {giggle} Goods are things we can touch. Penny, what is a silent 'e' word? `4.0` | **D** {rumble} Goods are fun things we trade! `2.0` |
| 1 | **P** Silent 'e' words are like secret codes! For example, 'cake' has a silent 'e' at the end. Sage, can you tell us about services? `3.0` | **S** Services are helpful jobs people do. `2.0` |
| 1 | **S** Services are jobs people do for us. Look, a doctor helps people when they are sick. Dyno, what kind of job do you think you would like? `3.0` | **P** Silent 'e' words are like little magic hats! `3.0` |
| 2 | **D** {boing} Doubles are fun! Look, 4 plus 4 is 8. Penny, what is a number that is a double? `3.0` | **D** {bounce} Doubles are super fun to count! `2.0` |
| 2 | **P** Doubles are like matching pairs! Did you know that 5 plus 5 is 10? Sage, what about the whales? `3.0` | **S** Whales are big sea creatures. `2.0` |
| 2 | **S** Whales are big sea animals. They are mammals that breathe air. Dyno, do you like learning about animals? `3.0` | **P** Clear glass lets light peek through! `2.0` |

## curriculum-dyno-1 — curriculum, topic: long-ago people and heroes

| turn | this run (scene 18.5/20) | baseline (scene 14.8/20) |
|---|---|---|
| 0 | **D** Long ago, brave people built amazing things! Did you know some early builders used simple stones? Sage, did you hear about ancient rivers? `2.7` | **D** Wow, long ago! Did you know about brave explorers? `4.0` |
| 0 | **S** Yes, the people of old learned to use water for farming. Penny, have you seen pictures of those mountains? `4.0` | **S** We can look at maps to see landforms. `4.0` |
| 0 | **P** I saw a picture of the Sierra Nevada! It is so tall and grand. Dyno, what about the different landforms? `3.0` | **P** Let's play a game of I Spy with shapes! `2.0` |
| 1 | **S** Immigrants came to find new places to live. Did you notice how different their stories are? `4.0` | **S** Some people moved to new places for safety. `4.0` |
| 1 | **D** Those builders used stones to make big walls. Penny, did you know that numbers like 253 have hundreds? `4.0` | **D** Heroes help people find new adventures! `4.0` |
| 1 | **P** Hundreds are like big piles of ones! Sage, do you think immigrants brought new ideas? `4.0` | **P** Hundreds, tens, and ones are like little building blocks! `2.0` |
| 2 | **D** Mice become mice by adding an 's'. Sage, did you know some heroes who helped people learn new ways? `4.0` | **D** Mice can be many! Don't forget the 's' for more! `2.0` |
| 2 | **S** Many Native peoples have lived here for thousands of years. Penny, look at how different their traditions are! `4.0` | **S** Different peoples have lived here for a very long time. `3.0` |
| 2 | **P** Contractions squeeze words together, like 'don't' for 'do not'. Dyno, did you notice how plurals change? `2.0` | **P** Don't forget 'don't' for when you want to say 'do not'! `2.0` |

## curriculum-sage-0 — curriculum, topic: vowel team words

| turn | this run (scene 12.8/20) | baseline (scene 18.0/20) |
|---|---|---|
| 0 | **D** Vowel teams make fun sounds! Like 'ai' in rain. Penny, what about 'ee'? `2.7` | **S** Vowel teams make fun words! `4.0` |
| 1 | **S** Even numbers are like perfect pairs. Penny, did you know that even numbers are super neat? `4.0` | **D** {bounce} Vowel teams are super bouncy! `4.0` |
| 2 | **D** Big rivers bring water to the farms. Penny, did you know that the Sacramento River is very long? `4.0` | **P** Ooh, vowel teams are like secret code words! `4.0` |
| 0 |  | **S** We can find words with those teams! `3.0` |
| 1 |  | **D** {wiggle} Vowel teams make words jumpy! `4.0` |
| 1 |  | **P** I see! Vowel teams are like little bouncy balls! `4.0` |
| 1 |  | **S** They help us build big, strong words. `3.0` |
| 2 |  | **D** {stomp} Rivers are big and flowy! `4.0` |
| 2 |  | **P** Plot twists are like a silly story maze! `2.0` |
| 2 |  | **S** We can use words to show our feelings. `3.0` |

## curriculum-sage-1 — curriculum, topic: traits and inheritance

| turn | this run (scene 19.3/20) | baseline (scene 12.5/20) |
|---|---|---|
| 0 | **S** Thinking helps us see things clearly. Did you notice how thinking helps us understand the weather? `2.7` | **S** We can talk about how things grow big and small. `2.7` |
| 0 | **D** I can predict the next bouncy thing! Sage, what about thinking helps us with math problems? `4.0` | **D** {giggle} I like to predict what comes next! `2.0` |
| 0 | **P** Thinking is like a magic word! I can describe a shape with words. Dyno, can you tell Sage about thinking? `3.0` | **P** Comparing shapes is super fun! `2.0` |
| 0 | **D** {dino_growl} Thinking helps me find new games! Penny, what is a silly word you can think of? `4.0` | **D** {dino_growl} Maybe we can build something! `2.0` |
| 1 | **P** Words like 'un-happi-ness' are like little building blocks! Sage, how does breaking words help us read long ones? `4.0` | **P** My colors are like a big word! `3.0` |
| 1 | **S** When forces are balanced, things stay still. Dyno, did you notice how balanced forces work in a game? `4.0` | **S** Traits are like little seeds we share. `3.0` |
| 1 | **D** {dino_growl} Stronger pulls make things move! Penny, can you think of a word with a prefix? `4.0` | **D** {dino_growl} I hope I get a big, strong tail! `3.0` |
| 2 | **S** Maps show us where our community is. Penny, did you notice how climate is different in places? `4.0` | **S** Maps show how our community is shaped. `2.0` |
| 2 | **P** Los Angeles is warm, but Alaska is cold. Dyno, can you tell Sage about how we measure time? `4.0` | **P** My sparkle comes from my parents! `2.0` |
| 2 | **D** {dino_growl} Time moves fast! Sage, how does measuring time help us understand history? `4.0` | **D** {giggle} I hope my bouncy self is like a sunny day! `2.0` |

## curriculum-penny-0 — curriculum, topic: native peoples today

| turn | this run (scene 16.9/20) | baseline (scene 14.3/20) |
|---|---|---|
| 0 | **P** Native peoples have many different cultures. Did you know some tribes live near the ocean? `4.0` | **P** Hello! Have you seen any native tribes? `4.0` |
| 0 | **D** {dino_growl} Wow, tribes are like big groups! Some tribes have special ways of making art. Sage, what about the plants they use? `3.0` | **D** {dino_growl} Are they like big, strong dinosaurs? `4.0` |
| 0 | **S** Native cultures have deep connections to the land. They learn about plants and animals very carefully. Penny, do you know about the different kinds of plants? `3.0` | **S** Native cultures have many wonderful stories. `4.0` |
| 1 | **D** {dino_growl} Native peoples adapt to the weather. Some tribes build homes to handle the cold or the heat. Penny, did you see how the river helps them? `3.0` | **D** {dino_growl} Native peoples have special ways of living. `4.0` |
| 1 | **P** Native peoples use the river for travel and food. They build canoes to see the water clearly. Sage, what about the redwoods near the river? `3.0` | **P** They use the river for salmon games! `2.0` |
| 1 | **S** The Yurok people respect the Klamath River greatly. They use the redwoods for building materials. Dyno, do you notice how the river flows? `3.0` | **S** Their culture is very important to learn about. `2.0` |
| 2 | **D** {dino_growl} Prefixes help us understand words. For example, 'un'happy' means not happy. Penny, can make a word with a prefix? `3.0` | **D** {dino_growl} Fossils are like ancient, sleepy creatures! `2.0` |
| 2 | **P** Prefixes are like little word stickers! They change the meaning of a word. Sage, what about suffixes like '-ful'? `3.0` | **P** Un-ful is like happy and full of fun! `2.0` |
| 2 | **S** Suffixes add a feeling to a word. For instance, '-ful' means full of. Dyno, did you notice how prefixes change things? `3.0` | **S** The three parts help keep things fair. `2.0` |

## curriculum-penny-1 — curriculum, topic: railroads and growth

| turn | this run (scene 17.0/20) | baseline (scene 14.7/20) |
|---|---|---|
| 0 | **P** Railroad tracks are like long, straight lines! They help things travel far. DYNO, did you know trains grow really big? `2.7` | **P** I spy with my little eye something green and bouncy! `4.0` |
| 0 | **D** {dino_growl} Trains move fast! They use big engines to go zooming. SAGE, does the wind help the tracks move? `3.0` | **D** {dino_growl} Wow, railroads are so big! `3.0` |
| 0 | **S** Wind and water can move rocks. Water erosion carves out big canyons over time. PENNY, can you tell a silly word about wind? `3.0` | **S** Growth happens slowly, like a tiny seed. `3.0` |
| 1 | **D** {dino_growl} Railroads are long paths for moving things. PENNY, what is a word that means 'far'? `4.0` | **D** {dino_growl} Railroad tracks go far, like a long, long path! `3.0` |
| 1 | **P** Far' can be like a big scope! A telescope helps you see very far. SAGE, does the growth of trees show a far view? `3.0` | **P** See, growth is like a tiny sprout, reaching for the sun! `3.0` |
| 1 | **S** Growth shows how things change over time. The roots of a word can mean a big scope. DYNO, can you tell me about the tracks? `3.0` | **S** The roots of a tree sense the water deep below. `2.0` |
| 2 | **D** Railroad tracks are lines for moving things. PENNY, what is a word for a small parts? SAGE, does growth show how things change? `3.0` | **D** Railroads are like long stories told by the tracks! `3.0` |
| 2 |  | **P** Decimals are like tiny pieces of a whole, like a fraction! `2.0` |
| 2 |  | **S** Missions show how people saw the world in different ways. `2.0` |

## topic-dyno-0 — topic, topic: a spelling bee word

| turn | this run (scene 17.0/20) | baseline (scene 19.1/20) |
|---|---|---|
| 0 | **D** Let's try a spelling bee! I like bouncy words. Penny, what is a fun word we could try? `2.7` | **D** Let's try a spelling bee! `4.0` |
| 0 | **P** Ooh, a spelling bee! We could spell a silly word. Did you know 'whimsical' has a long 'i' sound? Sage, what about tricky words? `3.0` | **P** We can spell big words! `4.0` |
| 0 | **S** Spelling is fun for learning. We could look at a picture book. Dyno, do you like stories with characters? `3.0` | **S** We can practice words together. `4.0` |
| 1 | **P** We can spell 'equal'! Equal means things are the same size. Did you know some animals have equal numbers of legs? Dyno, what about counting sums? `3.0` | **P** The word is 'equal'! It sounds like a big, balanced thing. `4.0` |
| 1 | **D** Sums are fun! If we add numbers, we find the total. Sage, can you tell us about responsibilities? `3.0` | **D** Equal means everything is fair! Can we count to ten? `4.0` |
| 1 | **S** Responsibilities help us be good friends. Did you notice how a baby plant grows into a tall sunflower? `4.0` | **S** Equal means things are the same size. Let's count by twos! `4.0` |
| 2 | **P** Digraph words are fun! Like 'ship' and 'chip', they make new sounds. Dyno, can you tell me a word with a digraph? `3.0` | **P** Digraph words are fun! Like 'ship' or 'chip'. `4.0` |
| 2 | **D** Digraphs are like secret codes! They make new sounds together. Sage, do you know how to add and subtract up to zero? `3.0` | **D** Ship! I like ships! Can we count on from eight? `2.0` |
| 2 | **S** Digraphs help us read new words. When we add and subtract, we find the correct total. Penny, do you think of a word with a digraph? `3.0` | **S** Digraph words help us make new sounds. We can practice adding numbers. `4.0` |

## topic-dyno-1 — topic, topic: the water cycle

| turn | this run (scene 20.0/20) | baseline (scene 15.0/20) |
|---|---|---|
| 0 | **D** Water goes up to the clouds! Sage, did you know clouds are made of tiny water drops? `4.0` | **D** {boing} Wow, water goes up and down! `4.0` |
| 0 | **S** Yes, clouds form when water vapor cools down. Penny, have you seen how rain falls from the sky? `4.0` | **S** The water cycle is very important for plants. `4.0` |
| 0 | **P** Raindrops are like tiny, shiny jewels! Dyno, does the water cycle make the rivers flow? `4.0` | **P** It's like a big, wet adventure! `2.0` |
| 0 | **S** The cycle helps plants grow strong. Penny, can you tell us about the sun's role in this process? `4.0` | **S** We can pretend to be clouds and rain today. `2.0` |
| 1 | **D** Water flows down to the sea! Penny, have you seen how different farms grow yummy strawberries? `4.0` | **D** {giggle} Water flows like a happy river! `3.0` |
| 1 | **P** Strawberries are sweet like little red stars! Sage, did you know that valleys are often where lots of water collects? `4.0` | **P** Grapes grow big and juicy, just like water! `4.0` |
| 1 | **S** Valleys are great for growing things. Dyno, look at how the water moves, does it ever get frozen? `4.0` | **S** The water cycle helps the farms grow food. `4.0` |
| 2 | **P** R-controlled vowels make sounds! Dyno, did you know that some places have dry deserts? `4.0` | **P** R-controlled sounds make words sound fun! `2.0` |
| 2 | **D** Deserts are very hot and sandy! Sage, did you notice how water helps plants in the valley? `4.0` | **D** {dino_growl} Water makes big valleys! `4.0` |
| 2 | **S** Water helps plants survive in valleys. Penny, can you tell me about the different places people came from? `4.0` | **S** People brought many traditions to California. `2.0` |

## topic-sage-0 — topic, topic: a riddle

| turn | this run (scene 17.5/20) | baseline (scene 14.4/20) |
|---|---|---|
| 0 | **D** A riddle sounds like fun! What is the first word of the riddle? Sage, do you have a hint? `2.7` | **S** Hello there! I have a riddle for you. `4.0` |
| 0 | **S** I have a riddle for you. Think about where seeds grow. Penny, what is a word that sounds like rain? `3.0` | **P** Ooh, a riddle! I love puzzles! `4.0` |
| 0 | **P** Ooh, rain sounds like a big splash! Maybe 'ai' in rain helps plants grow strong. Dyno, what about the seed? `3.0` | **D** {dino_growl} What is it? `2.0` |
| 0 | **D** Seeds grow into big trees! Sage, can you tell us about where people came from? `4.0` | **P** Is it something that flies and has wings? `4.0` |
| 1 | **S** The main topic is the big idea. Penny, details help explain that main idea. Dyno, look at the community! `3.0` | **D** {dino_growl} A riddle sounds like fun! `4.0` |
| 1 | **P** A community is like a big puzzle! Voting is when we choose the pieces. Dyno, what about cities? `3.0` | **S** Think about a place where many people live together. `2.0` |
| 1 | **D** Cities are big places! Sage, do you know about the different towns? `4.0` | **P** Maybe it's about a big city or a small town! `2.0` |
| 2 | **S** Hundreds are big numbers! Penny, even numbers are fun too. Dyno, look at this map! `3.0` | **D** Hundreds are big numbers! So many! `4.0` |
| 2 | **P** Even numbers are like pairs! Hundreds are like many groups of ten. Dyno, what about desert regions? `3.0` | **S** Maps show us regions and valleys. `2.0` |
| 2 | **D** Desert is hot and dry! Sage, can you tell us about California's valleys? `4.0` | **P** History is like finding clues in old letters! `2.0` |

## topic-sage-1 — topic, topic: fractions with pizza slices

| turn | this run (scene 15.6/20) | baseline (scene 15.2/20) |
|---|---|---|
| 0 | **D** Fractions are like sharing a pizza! Which slice is the numerator? Sage, what about the denominator? `2.7` | **S** Fractions are like sharing a pizza! `4.0` |
| 0 | **S** A fraction shows parts of a whole. The denominator tells us how many equal pieces we have. Penny, can you make a fraction with these slices? `3.0` | **P** A fraction is just a piece of the whole! `4.0` |
| 0 | **P** Ooh, a fraction is like a yummy pie! If we have four slices, the denominator is four! Dyno, what is the numerator in that case? `3.0` | **D** {dino_growl} Can we share a slice? `3.0` |
| 0 | **D** {dino_growl} The numerator is the part we are counting! Sage, do you know about `4.0` | **P** We can use a fraction to see how much pizza is left! `4.0` |
| 1 | **S** Verbs show the action. The past tense verb is like something that already happened. Penny, how does an adjective describe a noun? `1.0` | **D** {dino_growl} Fractions are fun! `3.0` |
| 1 | **P** Adjectives are like colorful sprinkles on a cookie! They tell us more about a noun, like describing a pizza slice! Dyno, what is a verb tense? `3.0` | **S** A fraction is a part of the whole pizza. `3.0` |
| 1 | **D** {dino_growl} Verbs show if something is happening now or will happen later! Sage, can you tell us about nouns? `4.0` | **P** We can use words like 'walked' or 'will walk' for our game! `2.0` |
| 2 | **P** The central message is the main idea of a story. It's like the best topping for a pizza! Sage, how does a character's action show their trait? `3.0` | **S** The story's main idea is important. `2.0` |
| 2 | **S** Actions show what a character is like. For example, if a character is kind, they will help others. Did you notice how Dyno is bouncing? `3.0` | **D** {dino_growl} The swing makes a pattern! `2.0` |
| 2 | **D** {dino_growl} Actions show what the character is! If a character is brave, they will try to face big things! Penny, what about the message? `3.0` | **P** Fractions help us share the pizza pieces! `3.0` |

## topic-penny-0 — topic, topic: rhyming words

| turn | this run (scene 18.5/20) | baseline (scene 13.5/20) |
|---|---|---|
| 0 | **P** Rhymes are like little musical pairs! Do you like rhyming words, Sage? `4.0` | **P** Rhyme time! Do you know a word that rhymes with cat? `4.0` |
| 0 | **S** Yes, rhymes help us see patterns in words. Dyno, do you notice how words sound similar? `4.0` | **S** A cat is a lovely animal. We can look at a picture. `4.0` |
| 0 | **D** {dino_growl} Rhymes are like bouncy balls! I wonder if we can find rhyming words in a story? `4.0` | **D** {dino_growl} Roar! I like words that sound like rocks! `3.0` |
| 1 | **P** Rhymes are fun! Did you know some words rhyme with 'river'? Sage, what about words that rhyme with 'river'? `3.0` | **P** River and giver, that's a rhyme! `2.0` |
| 1 | **S** Rhymes help us see how sounds match up. Dyno, look at how 'river' sounds like 'shiver'. `4.0` | **S** Redwoods are tall and strong. `2.0` |
| 1 | **D** {dino_growl} Rhymes are like a bouncy chain! Can we find words that rhyme with 'river' together? `4.0` | **D** {dino_growl} Big numbers are fun! `2.0` |
| 2 | **P** Settlers moved to new places. Sage, do you know words that rhyme with 'settlers'? `4.0` | **P** Settlers and helpers, they share! `2.0` |
| 2 | **S** Settlers changed communities. Dyno, look at how 'settlers' sounds like 'sellers'. `4.0` | **S** Forests are green and deep. `3.0` |
| 2 | **D** {dino_growl} Rhymes are like a bouncy chain! Can we find words that rhyme with 'settlers' together? `2.0` | **D** {dino_growl} Division is like sharing! `2.0` |

## topic-penny-1 — topic, topic: a times-table quiz

| turn | this run (scene 19.1/20) | baseline (scene 12.7/20) |
|---|---|---|
| 0 | **P** Let's play a quick times table game! We can count how fast the trains go. DYNO, what is your favorite number? `2.7` | **P** Let's play a times table game! `4.0` |
| 0 | **D** {dino_growl} I love numbers that are big and bouncy! Sage, do you know how many wheels a train has? `4.0` | **D** {bouncy} Times tables are super fun! `4.0` |
| 0 | **S** Trains use lots of energy to move. Penny, did you know that the Central Pacific Railroad took a long time to build? `4.0` | **S** We can practice adding and subtracting. `2.0` |
| 1 | **D** {dino_growl} Even numbers are super bouncy! Penny, did you know that numbers ending in 0 or 5 can be divided by five? `4.0` | **D** {growl} Times tables are like a big race! `3.0` |
| 1 | **P** That's a fun trick! Look, the number 10 is even because it ends in a zero. Sage, does that mean energy can move like a little sparks? `3.0` | **P** Even numbers end in zero or five, that's a trick! `2.0` |
| 1 | **S** Yes, energy can move through sound or light. Penny, if we look at the numbers, can you tell us about even numbers? `4.0` | **S** Energy can move with sound and light. `2.0` |
| 2 | **P** Times tables are like little puzzles! DYNO, can you count how many times you can jump? `4.0` | **P** Multiplying big numbers is like a fun puzzle! `2.0` |
| 2 | **D** {dino_growl} I can jump a lot! Sage, did you know that big numbers can be multiplied by breaking them down? `4.0` | **D** {bouncy} Shake tables make buildings strong! `3.0` |
| 2 | **S** Yes, multiplying big numbers is like breaking them into parts. Penny, if you see a number, can you show us how to multiply it? `4.0` | **S** Water moved by dams and canals is cool. `2.0` |

## free-dyno-0 — free, topic: (free)

| turn | this run (scene 17.3/20) | baseline (scene 11.6/20) |
|---|---|---|
| 0 | **D** The equal sign means things are the same size. Sage, did you know that equal signs help us solve many math puzzles? `4.0` | **D** Wow, the equal sign! It means everything matches up! `4.0` |
| 0 | **S** That is true. Equal signs show that two things have the same value. Penny, can you tell us about a time you saw something equal? `3.0` | **S** That is true. It shows that two things are the same amount. `2.0` |
| 0 | **P** Equal is like a matching pair! If you have two apples and two bananas, they are equal! Dyno, what about matching things in science? `3.0` | **P** It's like a balancing act, a perfect match! `2.0` |
| 0 | **D** {dino_growl} Matching is fun! Did you know that some planets have the same number `4.0` | **D** {dino_growl} I like matching things! `2.0` |
| 1 | **S** Rules help everyone stay safe and fair. Penny, have you ever seen how rules help a group play nicely? `2.0` | **S** Rules help keep everyone safe and fair. `2.0` |
| 1 | **P** Rules are like colorful building blocks! If we follow the rules, our game tower stays strong! Dyno, do you know that some animals have special body parts for survival? `3.0` | **P** And leaders have jobs to help make things good! `4.0` |
| 1 | **D** {dino_growl} Adaptations are super cool! Look at Sage, how do you think a cactus helps it survive the dry weather? `4.0` | **D** {dino_growl} Adaptations are super cool for animals! `2.0` |
| 2 | **P** Our address tells us where we live. Sage, do you know that a city is like a big neighborhood? `4.0` | **P** Sight words are like tiny building blocks for sentences! `2.0` |
| 2 | **S** A city is a place with many people live. Penny, did you notice how a family plan helps when there is a fire? `4.0` | **S** Knowing your address helps you find your neighborhood. `2.0` |
| 2 | **D** {dino_growl} Fire plans are important! Did you know that knowing where to go is a safe idea? `4.0` | **D** {dino_growl} Safety plans are like super strong shields! `2.0` |

## free-dyno-1 — free, topic: (free)

| turn | this run (scene 18.1/20) | baseline (scene 15.0/20) |
|---|---|---|
| 0 | **D** I wonder about California farms! They grow so many yummy things. Sage, have you read about the Central Valley? `2.7` | **D** I wonder what kind of animals live in the ocean! `4.0` |
| 0 | **S** I can look at pictures of almonds and grapes. Penny, can you tell us a silly word about a vegetable? `4.0` | **S** The ocean has so many amazing creatures. `4.0` |
| 0 | **P** Ooh! Strawberries are red like a tiny, juicy treasure! Dyno, what about the way we measure things? `3.0` | **P** I know a word for a big, juicy strawberry! `2.0` |
| 1 | **S** Learning about heroes is wonderful. Did you know that pollinators help plants make seeds? Dyno, what is a hero's brave action? `3.0` | **S** Learning about heroes is very inspiring. `2.0` |
| 1 | **D** {dino_growl} Heroes do big things! Bees carry pollen like tiny yellow dust. Penny, can you make a silly word about a hero? `3.0` | **D** Wow, heroes are super brave like a big green rock! {dino_growl} `4.0` |
| 1 | **P** A hero's bravery is like a big, strong word! Sage, did you see how the pollen moves? What about the hundreds, tens, and ones? `3.0` | **P** Hundreds, tens, and ones are like tiny building blocks! `2.0` |
| 2 | **D** Hundreds are like big piles of green dinosaur bones! Sage, did you know about the different California habitats? `4.0` | **D** Laws keep everyone safe and fair, that sounds cool! `2.0` |
| 2 | **S** California has forests and deserts all close together. Penny, can you tell us a word for a leader? `4.0` | **S** Leaders help make sure everyone is treated nicely. `4.0` |
| 2 | **P** A leader makes laws to keep everyone safe and fair! Dyno, did you notice the mountains? `4.0` | **P** Hundreds, tens, and ones help us count things fairly! `4.0` |

## free-sage-0 — free, topic: (free)

| turn | this run (scene 19.3/20) | baseline (scene 11.7/20) |
|---|---|---|
| 0 | **D** Even numbers are like matching pairs! Did you know some even numbers are also the number of wheels on a bicycle? Sage, what about odd numbers? `2.7` | **S** Reading fairy tales is so wonderful for learning. `4.0` |
| 0 | **S** Odd numbers have one left over when you try to make pairs. Penny, can you tell us a word with an R-controlled sound? `4.0` | **D** {giggle} I like learning about big slides! `4.0` |
| 0 | **P** I see! R-controlled words are like little treasure chests full of sounds. Dyno, do you know any words that start with an R-controlled sound? `3.0` | **P** Even numbers are like matching socks, silly! `2.0` |
| 1 | **D** Immigrants come to new places for safety. Sage, have you ever seen a big mountain like a hill? `4.0` | **D** {dino_growl} I wonder about big mountains! `2.0` |
| 1 | **S** Equal shares mean every piece is the same size. Penny, did you know that a rectangle can be split into thirds too? `4.0` | **S** Learning about how people move is very important. `2.0` |
| 1 | **P** Landforms like mountains are big and strong. Dyno, what is a word that has an R-controlled sound? `4.0` | **P** Equal shares make perfect little pieces! `2.0` |
| 2 | **S** Pollinators help plants make seeds and fruit. Dyno, did you know that bees are very important pollinators? `4.0` | **S** Pollinators are super important for growing food. `2.0` |
| 2 | **D** Line plots show measurements as dots on a line. Penny, can you tell us a word with an R-controlled vowels? `4.0` | **D** {giggle} Flowers are like colorful jungle slides! `2.0` |
| 2 | **P** R-controlled vowels change the sound in words like car. Sage, do you notice how the sound changes? `4.0` | **P** Car and bird sounds like a fun word game! `2.0` |

## free-sage-1 — free, topic: (free)

| turn | this run (scene 19.1/20) | baseline (scene 14.1/20) |
|---|---|---|
| 0 | **S** Forces can be balanced or unbalanced. Did you know that a balanced force keeps things still? What about unbalanced forces, Penny? `2.7` | **S** Reading about the Golden Gate Bridge is fun. `4.0` |
| 0 | **P** Ooh, unbalanced forces are like a silly push! They make things go zoom! Dyno, what is a push? `3.0` | **P** Ooh, a bridge is like a giant, sparkly rainbow! `4.0` |
| 0 | **D** {dino_growl} Pushes make things move fast! Sage, do you know about the Golden Gate Bridge? `4.0` | **D** {dino_growl} Pushing and pulling makes things move! `2.0` |
| 0 | **S** The Golden Gate Bridge opened in 1937. It shows how a strong pull can move a big thing. Penny, what is a word `3.0` | **S** That is a great way to think about forces. `2.0` |
| 1 | **P** Prefixes change words like a magic trick! Dyno, what is a prefix? `4.0` | **P** Un- and re- are like little magic stickers for words! `2.0` |
| 1 | **D** {dino_growl} Prefixes are like little green bumps on words! Sage, do you know about explorers? `4.0` | **D** {dino_growl} Settlers moved to new lands! `2.0` |
| 1 | **S** Explorers came from far away and changed communities. Penny, what is a suffix? `4.0` | **S** The three parts of government help keep things fair. `2.0` |
| 2 | **P** Fractions are like sharing a yummy cookie! Dyno, what is a fraction? `4.0` | **P** Tar pits are like a giant, ancient, sticky mess! `2.0` |
| 2 | **D** {dino_growl} Fractions are pieces of a whole thing! Sage, did you know about the La Barea? `4.0` | **D** {dino_growl} Animals lived in those old tar pits! `4.0` |
| 2 | **S** The La Barea tar shows ancient animals. Penny, what is a numerator? `4.0` | **S** Fractions help us share things fairly, like the tar pits. `4.0` |

## free-penny-0 — free, topic: (free)

| turn | this run (scene 20.0/20) | baseline (scene 14.3/20) |
|---|---|---|
| 0 | **P** Adding and subtracting up to 1000 is like building with big blocks! DYNO, what is a big number? `4.0` | **P** I love counting big numbers! Can you count to a thousand? `4.0` |
| 0 | **D** {dino_growl} Big numbers are like giant, bouncy rocks! SAGE, do you like counting rocks? `4.0` | **D** {giggle} Wow! I wonder what happens when you add big numbers! `4.0` |
| 0 | **S** Counting helps us see patterns in numbers. PENNY, can you tell me about patterns in motion? `4.0` | **S** Adding and subtracting helps us see patterns in numbers. `4.0` |
| 1 | **P** Designing a solution means figuring out what a problem needs fixing! DYNO, what is a good design? `4.0` | **P** Designing a solution is like making a super cool plan! We try many ideas. `2.0` |
| 1 | **D** {dino_growl} A good design must meet the goal! SAGE, can you explain limits like cost? `4.0` | **D** {dino_growl} I like patterns! Watching how things move is so exciting. `2.0` |
| 1 | **S** Limits help engineers think about time and money. PENNY, what about how towns change over time? `4.0` | **S** Changing communities shows how people and new things make towns grow. `4.0` |
| 2 | **D** {dino_growl} Division splits things into equal groups! PENNY, what is a group? `4.0` | **D** {dino_growl} Division is like sharing toys equally! It's super fun to see how many fit in each pile. `2.0` |
| 2 | **P** Groups are like colorful piles of blocks! SAGE, can you tell us about differences? `4.0` | **P** Verbs are like action words! They tell us what happened, what is happening, or what will happen. `2.0` |
| 2 | **S** Differences help animals hide or find food. DYNO, did you notice the colors? `4.0` | **S** Differences help animals survive by hiding or finding food. It's a very smart way to live. `2.0` |

## free-penny-1 — free, topic: (free)

| turn | this run (scene 20.0/20) | baseline (scene 12.7/20) |
|---|---|---|
| 0 | **P** Gold rushes were like a big, sparkly treasure hunt! Did you know that some miners stayed to build towns? `4.0` | **P** Did you know that numbers are like tiny, sparkly jewels? `4.0` |
| 0 | **D** {dino_growl} That sounds exciting! Did you know that the San Andreas Fault is a big crack in the ground? `4.0` | **D** {giggle} Wow! Gold sounds like a super shiny treasure hunt! `4.0` |
| 0 | **S** It is a very important place for learning about maps. Do you want to know about how water helped build cities? `4.0` | **S** Maps show how water moves to help farms grow big. `2.0` |
| 1 | **P** Fractions are like yummy cookies! Did you know that one half is the same as two fourths? `4.0` | **P** Fractions are like yummy pizza slices! One half is like two fourths of a pie. `2.0` |
| 1 | **D** {dino_growl} Fractions are bouncy! Did you notice how different pieces can make the same amount? `4.0` | **D** {dino_growl} Sliding past each other makes big shakes! `2.0` |
| 1 | **S** Changing states show us history. Did you know that California changed from Native peoples to Spanish rule? `4.0` | **S** History shows how California changed over time, like a big storybook. `4.0` |
| 2 | **P** Factors are like puzzle pieces! Did you know that prime numbers only have two factors? `4.0` | **P** Prime numbers are like secret codes! Seven is a super special number. `2.0` |
| 2 | **D** {dino_growl} Multiples are like bouncing balls! Did you notice how they keep getting bigger and bigger? `4.0` | **D** {giggle} Land shapes are like big, bumpy playgrounds! `2.0` |
| 2 | **S** Landways show how people lived. Did you know that different areas had different foods? `4.0` | **S** Native peoples lived near the mountains and the ocean. `2.0` |

## ask-dyno-0 — ask, topic: everyday life in the past

| turn | this run (scene 16.3/20) | baseline (scene 14.1/20) |
|---|---|---|
| 0 | **D** Did you know people used to trade things? That is like a big game of giving and taking! Sage, what about things people made? `1.3` | **D** Who was the first dinosaur? `2.7` |
| 0 | **S** Goods are things people make or grow. Did you notice how different goods are? Penny, what about services are they? `3.0` | **S** Dinosaurs lived a very long time ago. `4.0` |
| 0 | **P** Services are jobs people do for others. Think of a baker making bread! Dyno, what about trade is fun? `3.0` | **P** Did you know about trade? Goods are things, services are jobs! `2.0` |
| 1 | **D** The Pacific coast touches the big ocean. Did you know some old sailors used drums to send signals? Sage, what about doubles are they? `3.0` | **D** Wow, the ocean is so big! `4.0` |
| 1 | **S** Doubles are the same number added twice. Look at how 4 plus 4 is 8. Penny, what about making signals is interesting? `3.0` | **S** The Pacific coast meets the ocean water. `4.0` |
| 1 | **P** Signals can be a drum or a flashlight. Did you notice how doubles help with near-doubles? Dyno, what about the ocean is cool? `3.0` | **P** Doubles are like when you add the same number twice! `2.0` |
| 2 | **S** A clock tells time to the hour and half hour. Did you notice how the long hand shows the time? Dyno, what about sentences are important? `3.0` | **S** A clock shows us the time right now. `2.0` |
| 2 | **D** Sentences start with a capital letter. Did you know that a capital letter makes a big start? Penny, what about safety is? `3.0` | **D** I like to play games with my friends! `2.0` |
| 2 | **P** Safety is important at home. You should know two ways out. Sage, what about telling a grown-up is? `3.0` | **P** A sentence needs a start and an end mark! `2.0` |

## ask-dyno-1 — ask, topic: who, what, where, when, why, how

| turn | this run (scene 18.1/20) | baseline (scene 13.9/20) |
|---|---|---|
| 0 | **D** Penny, what is a solid? It is something that keeps its shape. Sage, can you tell us about liquids? `1.3` | **D** Penny, what is a solid? `2.7` |
| 0 | **S** Liquids flow and take the shape of their container. Penny, did you know ice is a solid? `4.0` | **S** A solid keeps its shape and size. `4.0` |
| 0 | **P** Solid is like a neat little block! I can make a block of pretend ice. Dyno, what about gas? `3.0` | **P** A solid is like a firm block! `4.0` |
| 1 | **D** Lake Tahoe is a big, clear lake! It is near the mountains. Sage, what is a liquid like? `3.0` | **D** Lake Tahoe is super big! `2.0` |
| 1 | **S** Liquids move around inside their space. Penny, did you know we can add big numbers? `4.0` | **S** We share our toys fairly. `2.0` |
| 1 | **P** Adding is like putting toys together! I can make ten with little ones. Dyno, what about subtracting? `3.0` | **P** Taking turns is like a fun game! `2.0` |
| 2 | **D** Laws help keep everyone safe in the community. Sage, what is a ruler used for? `4.0` | **D** Laws keep us safe and fair! `2.0` |
| 2 | **S** Rulers help us measure things like length. Penny, did you know words like 'habitat's' are for books? `4.0` | **S** Leaders help make sure everyone is treated well. `2.0` |
| 2 | **P** Habitat is like a cozy home for animals. Dyno, what about fairness in laws? `4.0` | **P** Words like 'habitat' help us learn about nature! `4.0` |

## ask-sage-0 — ask, topic: measuring with rulers

| turn | this run (scene 19.3/20) | baseline (scene 18.3/20) |
|---|---|---|
| 0 | **D** I like how water can be liquid and ice! Sage, do you know how to measure things with a ruler? `4.0` | **S** Penny, can you tell me about rulers? `4.0` |
| 0 | **S** I can help with that! Rulers help us see how much water fits in a container. Penny, can you tell us about measuring ice? `3.0` | **P** Rulers are like tiny measuring sticks! They help us see how long or how much something is. `4.0` |
| 0 | **P** Ice is like a cold, clear block! I can count how many little cubes fit in a shape. Dyno, do you think water flows faster in a river or an ocean? `3.0` | **D** {giggle} Wow, measuring things is like a big adventure! `4.0` |
| 1 | **D** Rulers help us see water's shape! Sage, did you know some shapes are called quadrilaterals? `4.0` | **S** Rulers help us measure things accurately. `4.0` |
| 1 | **S** Quadrilaterals have four sides, like a square or a rectangle. Penny, can you tell us about pentagons? `4.0` | **P** We can use rulers to see shapes! `4.0` |
| 1 | **P** Pentagons have five sides, which is super fun! Dyno, look at Sage, does a hexagon have six sides? `4.0` | **D** {dino_growl} Shapes are super cool to count! `4.0` |
| 2 | **S** Measuring helps us see how much time passes. Dyno, did you know about irregular plurals? `4.0` | **P** Rulers help us see things right! `3.0` |
| 2 | **D** Mice become mice! Sage, did you notice how words change their endings? `4.0` | **S** Measuring is important for understanding size. `3.0` |
| 2 | **P** Contractions squeeze words together like 'don't'! Sage, can you show me a picture of a tradition? `4.0` | **D** {dino_growl} Time for counting coins is a fun game! `2.0` |

## ask-sage-1 — ask, topic: multiplication words

| turn | this run (scene 16.7/20) | baseline (scene 16.5/20) |
|---|---|---|
| 0 | **D** {bounce} Are we talking about multiplication tables now? I like counting big numbers! Sage, what do you think about times tables? `2.7` | **S** Penny, can you tell me about multiplication words? `4.0` |
| 0 | **S** Multiplication helps us count things quickly. Did you know that two times five is ten? Penny, can you tell us about a tricky multiplication fact? `3.0` | **P** Multiplication words are like tiny number helpers! They make big numbers easy to count. `4.0` |
| 0 | **P** Multiplication is like a super fun game! For example, three times four is twelve. Did you notice how numbers can be like little friends holding hands? `3.0` | **D** {giggle} Wow, multiplication sounds like a super speedy race! `4.0` |
| 1 | **D** {giggle} Multiplication is like a bouncy ball game! Did you know that five times two is ten? Sage, what is a fun fact about measuring mass? `3.0` | **S** Multiplication words help us count things quickly. `4.0` |
| 1 | **S** Mass is how much stuff weighs. Did you notice how different toys have different weights? Penny, can you explain how we measure time in minutes? `3.0` | **P** They are like magic number tricks for adding! `2.0` |
| 1 | **P** Time is like a race track! For instance, one minute has sixty seconds. Did you notice how time moves fast? `3.0` | **D** {dino_growl} Counting with multiplication is super bouncy! `3.0` |
| 2 | **S** Many nations have many different languages. Did you know that some languages help tell stories? DYNO, what about groups in multiplication? `3.0` | **P** Multiplying is just adding groups together! `2.0` |
| 2 | **D** {dino_growl} Groups are fun for counting! Did you know that three times three is nine? Penny, what is a symbol of freedom? `3.0` | **S** Each group in multiplication has a special number. `4.0` |
| 2 | **P** Freedom is like a bright flag! Did you notice how different groups are like different colors? Sage, what about groups in multiplication? `3.0` | **D** {dino_growl} So many groups! That sounds like a big bouncy game! `4.0` |

## ask-penny-0 — ask, topic: magnets

| turn | this run (scene 18.3/20) | baseline (scene 15.4/20) |
|---|---|---|
| 0 | **D** Magnets are super cool! They stick things together really strong. Sage, what is a magnet made of? `2.7` | **D** {bouncy} Are magnets super cool? `4.0` |
| 0 | **S** Magnets use a special material called iron. Penny, can you tell Dyno about how magnets work? `4.0` | **S** Magnets are fascinating! They have a north and south pole. `4.0` |
| 0 | **P** Magnets have a north and south pole. Did you notice how the poles push and pull? `4.0` | **P** Magnets are like tiny, invisible helpers! They stick together! `4.0` |
| 1 | **S** Settlers moved to new lands and changed things. Dyno, have you seen any maps of those places? `4.0` | **S** Magnets show how things can connect. `4.0` |
| 1 | **D** I like maps! They show where explorers went to find new things. Penny, what is a settler? `3.0` | **D** {growl} They are like tiny, invisible roads! `2.0` |
| 1 | **P** Settlers were brave explorers who built new homes. Sage, do you know about the different tribes? `4.0` | **P** They stick together with a magnetic hug! `2.0` |
| 2 | **D** Magnets stick things together because of their special poles. Sage, did you know magnets had a north and south pole? `3.0` | **D** {bouncy} Magnets are super strong! `3.0` |
| 2 | **S** Yes, Dyno, magnets are made of iron. Penny, can you tell us about the different poles? `3.0` | **S** We can use magnets to show our opinion. `4.0` |
| 2 | **P** North and south poles attract each other. Did you notice how the poles work together, Dyno? `4.0` | **P** We can make a pattern with numbers! `2.0` |

## ask-penny-1 — ask, topic: chinese workers and railroads

| turn | this run (scene 18.3/20) | baseline (scene 14.4/20) |
|---|---|---|
| 0 | **D** Those workers built big trains! They used lots of hard work. Sage, do you know about the different parts of a train? `2.7` | **D** {giggle} Wow, those workers and railroads sound like a big adventure! `4.0` |
| 0 | **S** They worked very hard to build the tracks. Did you notice how the wheels help the train move? `4.0` | **S** That sounds like a story about how people worked together. `4.0` |
| 0 | **P** Railroads are like long, winding ribbons! I wonder if they used tiny little maps to guide them. Dyno, what is a map used for? `3.0` | **P** Those workers built big things! Did you know that some people worked on trains? `4.0` |
| 1 | **D** The gold rush was very exciting! Many people traveled far for that treasure. Sage, have you ever seen a picture of a gold mine? `3.0` | **D** {dino_growl} That sounds like a very big journey! `4.0` |
| 1 | **S** The miners stayed to help build the railroad lines. Penny, did you know that the railroad helped move the gold out? `4.0` | **S** It shows how different people can help build new things. `2.0` |
| 1 | **P** Railroads are like long, shiny ribbons! They needed lots of strong workers to lay the tracks. Dyno, what is a track used for? `3.0` | **P** Adding fractions is like sharing pieces fairly! `2.0` |
| 2 | **S** A million has many places to count. Dyno, did you know that California became a state in 18900? `4.0` | **S** Place value helps us see how big numbers are! `2.0` |
| 2 | **D** That is a big number of places! Sage, did you see how the state grew into many new towns? `4.0` | **D** {dino_growl} Sunlight and wind are great energy! `2.0` |
| 2 | **P** A million is like a giant pile of tiny things! Sage, did you notice how the state's growth brought new laws? `4.0` | **P** California grew into a state in 1850! `2.0` |
