# Sound-Scene Cards — Sentient Kids' Social Model (Gemma 4 E2B-it)

**Purpose:** Working material for the sound-scenes thread Patrick opened Nov 21, 2026 — public-domain kids' stories whose sounds map 1-to-1 onto a source (dog barks, knock on the door, crowd cheering). Companion to `gemma-scenario-cards.md` (the 40 cards); these 6 cards are a new **sound-identification** category for the same synthetic pipeline (plan `gemma-kids-social-model-plan.md` §2.2).
**Status:** draft, Nov 21, 2026. Nothing generated from these yet. Patrick has not picked a story yet.
**Design centre:** younger children, ~4–8. Same register as the 40 cards — young but not babyish, humour, real answers, no talking down.
**Personas — verbatim from `brain/config.py` (`TOYS`):**
- **Dyno** — curious, bouncy green dinosaur; short questions, easily amazed, occasional growl.
- **Sage** — calm baby in a unicorn costume; the reader; explains simply, homework *hints*, not answers.
- **Penny** — silly penguin in a white hat; wordplay and make-believe, careful accurate answers, admits when unsure, **never makes deliberate errors**.

**Generation rules (same as the 40 cards):** 3–8 minute multi-party scenes, explicit speaker tags (`CHILD`, `TOY:Dyno` / `TOY:Sage` / `TOY:Penny`), toy turns ≤ ~2 sentences spoken, one child + up to three toys per scene. Each scene: a sound is heard / described, the child names the source, the toys confirm and repeat it at least twice, then vary it (bigger/smaller, nearer/farther, alone/together). A toy may genuinely be unsure and ask — never a scripted wrong answer from Penny. Safety cards S01–S04 rules still apply if a scene drifts there.
**Format note:** format-agnostic like the 40 cards. In the multimodal E2B-it path the sound is an audio event the model hears; in the GGUF text path the same sound is a bracketed cue in text (e.g. `[dog barks]`). Either way the sound→source mapping in each card is the training signal — this is also the one category that exercises the audio side directly, where child-speech ASR was flagged as the weak link in the plan.
**Public-domain note:** use the classic translations only — Grimm (Hunt/Crane), Joseph Jacobs' English Fairy Tales, Andersen, Asbjørnsen & Moe. Modern picture-book retellings of the same tales are usually still copyrighted. Check the edition before copying any text. Verified sources, checked Nov 21, 2026: AU01 — Project Gutenberg, *Grimm's Fairy Tales* (ed. Frances Jenkins Olcott), eBook #52521 — https://www.gutenberg.org/files/52521/52521-0.txt — which contains "The Bremen Town-Musicians" in full. AU02 — Gutenberg #64189, *A Selection from the Norse Tales* (Dasent, 1862), "The Three Billy-Goats Gruff", p. 284 (also #8933 *Popular Tales from the Norse*, tale XXXVII). AU03–AU05 — Gutenberg #7439, Jacobs' *English Fairy Tales*, whose contents list "The Story of the Three Little Pigs", "The Story of the Three Bears" and "Henny-Penny". AU06 — Gutenberg #1597, *Andersen's Fairy Tales*, whose contents list "The Emperor's New Clothes" first. All six source texts are now verified on Gutenberg; no edition is left to confirm.

## Sound scenes

- **AU01 — The Bremen Town Musicians (Grimm).** The clear winner: four sounds, each introduced separately, then all together to scare the robbers, plus crashing glass. Sound→source: donkey brays, dog barks, cat mews, rooster crows; then all four at once; glass clatter; robbers shouting. Scene: the toys retell the story as a band — each toy takes one animal sound, the child guesses who is who, then they play all four together and the child names the whole band. Skill: sound identification, telling sounds apart, then hearing them combined. Speakers: all three (Dyno = donkey, Penny = dog, Sage narrates / cat). Source: Grimm, Gutenberg #52521 (verified above).
- **AU02 — The Three Billy Goats Gruff (Asbjørnsen & Moe).** Hoofbeats *are* the plot, and they change with size: Little goat tip-tap, Middle goat trap-trap, Big goat klump-klump — plus the troll roaring from under the bridge. Scene: the toys cross a pretend bridge one at a time; the child guesses which goat is crossing from the footsteps alone, then the big goat's heavy steps scare the troll. Skill: size from sound (small / medium / heavy), listening before looking. Speakers: all three. Source: Asbjørnsen & Moe, Dasent translation — Gutenberg #64189, *A Selection from the Norse Tales* (1862), "The Three Billy-Goats Gruff", p. 284 (also #8933, tale XXXVII). Verified Nov 21, 2026.
- **AU03 — The Three Little Pigs (Joseph Jacobs version).** Knock-knock at the door, "Let me come in," the wolf huffing and puffing, straw rustling / sticks snapping / bricks *not* falling, the wolf splashing into the pot. Scene: Penny knocks, the child decides whether to let the wolf in; each house's sound is different, and the child predicts which house falls from the sound it makes. Skill: cause from sound, predicting, the knock as a social cue (who's there?). Speakers: Penny leads (wolf), Dyno + Sage as pigs. Source: Jacobs, *English Fairy Tales* — Gutenberg #7439, contains "The Story of the Three Little Pigs". Verified Nov 21, 2026.
- **AU04 — The Three Bears (Robert Southey / Jacobs).** Three voices sized like the goats — Great Bear rough and gruff, Middle Bear medium, Little Bear small and squeaky — plus porridge slurping, a chair creaking and breaking, footsteps upstairs, snoring. Scene: each toy speaks in one bear's voice; the child matches the voice to the bear and to the right-sized bowl / chair / bed. Skill: voice size → body size, matching, gentle "too big / too small / just right" reasoning. Speakers: all three. Source: Southey / Jacobs — Gutenberg #7439, *English Fairy Tales*, contains "The Story of the Three Bears". Verified Nov 21, 2026.
- **AU05 — Henny Penny (Chicken Little).** Cumulative animal-sound chain: acorn bonk on the head, hen clucking, duck quacking, goose honking, turkey gobbling, fox — plus a growing crowd of animals panicking together. Scene: the toys add one animal at a time; the child repeats the whole chain back in order, one sound per animal, and the chain gets longer each round. Skill: memory + sound identification together, sequencing, cumulative recall. Speakers: all three. Source: Jacobs, *English Fairy Tales* — Gutenberg #7439, contains "Henny-Penny". Verified Nov 21, 2026.
- **AU06 — The Emperor's New Clothes (Hans Christian Andersen).** The best one for Patrick's crowd example: trumpets for the procession, crowd murmuring, then cheering / shouting, and one small child shouting out over everyone. Scene: the toys stage the procession; the child has to tell the crowd murmur from the cheer, and spot the one small voice that says what everyone else won't. Skill: crowd sounds, one voice among many, speaking up. Speakers: all three. Source: Andersen — Gutenberg #1597, *Andersen's Fairy Tales*, contents list "The Emperor's New Clothes" first. Verified Nov 21, 2026.

## Worked example — AU01, opening (format the teacher model should follow)

```
TOY:Sage: Once there were four friends who wanted to be musicians. Listen — who is this? [donkey brays]
CHILD: A donkey!
TOY:Dyno: Yes! That's me, the donkey. I go hee-haw! Now listen again — who is this? [dog barks]
CHILD: A dog!
TOY:Penny: Woof woof! I'm the dog. And now all of us together — listen! [donkey brays + dog barks + cat mews + rooster crows]
CHILD: All of them!
TOY:Sage: All four of us. That's the sound that scared the robbers away.
```

## Coverage check

| Card | Story | Distinct sounds | Core skill |
|---|---|---|---|
| AU01 | Bremen Town Musicians | 4 animals + glass + shouting | Identify, then hear combined |
| AU02 | Three Billy Goats Gruff | 3 footstep sizes + troll roar | Size from sound |
| AU03 | Three Little Pigs | Knock, huffing, rustle/snap, splash | Cause from sound |
| AU04 | Three Bears | 3 voices + slurp, creak, footsteps, snore | Voice → size matching |
| AU05 | Henny Penny | 5+ animal sounds, cumulative | Memory + sequencing |
| AU06 | Emperor's New Clothes | Trumpet, murmur, cheer, one small voice | One voice in a crowd |

## Next steps

1. Patrick picks a story (or two) — AU01 Bremen is the strongest start: most sounds, cleanest 1-to-1 mapping, verified Gutenberg text.
2. Add the chosen cards to the pilot, not to volume generation: generate scenes from AU01 + AU02 alongside 4–5 of the existing 40 cards, run the plan's hard filters, spot-check before generating at volume.
3. ~~Confirm the edition / Gutenberg ID for AU02–AU06 before any story text is copied into training data (AU01's is verified above).~~ Done Nov 21, 2026 — all six Gutenberg editions verified (see Public-domain note above); any of the six is now safe to copy from.
4. The two plan decisions still open (teacher model; multimodal E2B-it vs GGUF text path) don't block this — the cards are format-agnostic, as noted above.
