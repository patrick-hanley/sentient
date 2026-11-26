"""Round 7 training mix: every attachment, "warm first" and round-7 scene, as corrected on Nov 26, plus a replay of the rest.

  python tools/finetune/make_train7.py        -> data/train7.jsonl, data/train7-val.jsonl, data/round7-heldout.jsonl

Meant to continue from the ROUND 3 adapter, not round 5 or 6: those learned the faults this round removes from the scenes (the
cold "I am a toy, so ..." opener was in 21 round-2 and round-4 replies; "your mom or dad" in 18% of round 6; a stop boundary the
scenes disagreed about). Plan, 3i.
- New: 176 of the 200 round-7 scenes (stop pairs, statements about the bond, hurts with no feeling word and I spy asked as a
  question, words that arrived clipped or wrong). Held out: 6 from each file (24, listed in round7-heldout.jsonl).
- Again, corrected: 176 round-6 scenes and 220 round-4 scenes (never their held-out 24 and 30).
- Replay: 100 round-3 scenes (cameras, I spy, always answer) and 100 from the pilot and round 2. 23% of the mix is new.
- Validation: round 3's 64 held-out scenes + the 30 attachment + the 24 round-6 + the 24 new ones.
- data/live-z.jsonl (48 scenes built from lines the models got wrong when spoken to) is in neither file: it is a test set only.
- Half the scenes get a brain-shaped spoken history, as in rounds 3 to 6. Same output every run.
"""
import json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
PER_FILE_HELD, N_ROUND3, N_EARLIER, HISTORY = 6, 100, 100, 0.5
NEW_FILES = ["round7-a.jsonl", "round7-b.jsonl", "round7-c.jsonl", "round7-d.jsonl"]


def ids(name):
    return {json.loads(l)["id"] for l in (DATA / name).read_text().splitlines() if l.strip()}


def main():
    snd = scenes.sounds()
    by_file = {}
    for p in sorted(DATA.glob("*-?.jsonl")):
        for _p, _n, sc in scenes.load([p]):
            assert not scenes.check_scene(sc, snd), sc["id"]
            by_file.setdefault(p.name, []).append(sc)
    group = lambda start: [sc for name, v in by_file.items() if name.startswith(start) for sc in v]
    held_before = ids("train3-val.jsonl") | ids("train2-val.jsonl") | ids("train-val.jsonl")
    held_attach = ids("round4-heldout.jsonl") | ids("round5-heldout.jsonl")
    held6 = ids("round6-heldout.jsonl")
    rnd = random.Random(7)
    held_new = []
    for name in NEW_FILES:                           # one of each kind first, then fill up
        pool = by_file[name][:]
        rnd.shuffle(pool)
        pick, kinds = [], set()
        for sc in pool:
            k = sc["scenario"].split(":")[0]
            if k not in kinds and len(pick) < PER_FILE_HELD:
                kinds.add(k)
                pick.append(sc)
        pick += [sc for sc in pool if sc not in pick][:PER_FILE_HELD - len(pick)]
        held_new += pick
    held_ids = {s["id"] for s in held_new}
    train_new = [sc for sc in group("round7") if sc["id"] not in held_ids]
    again = [sc for sc in group("round6") if sc["id"] not in held6] + [sc for sc in group("round4") if sc["id"] not in held_attach]
    r3 = [sc for sc in group("round3") if sc["id"] not in held_before]
    old = [sc for sc in group("pilot") + group("round2") if sc["id"] not in held_before]
    for pool in (r3, old):
        rnd.shuffle(pool)
    train = train_new + again + r3[:N_ROUND3] + old[:N_EARLIER]
    rnd.shuffle(train)
    all_scenes = {sc["id"]: sc for v in by_file.values() for sc in v}
    val_ids = sorted(ids("train3-val.jsonl")) + sorted(held_attach) + sorted(held6) + sorted(held_ids)
    val = [all_scenes[i] for i in val_ids]
    assert not {s["id"] for s in train} & (set(val_ids) | held_before)
    assert not any(s["id"].startswith("z-") for s in train + val)
    for name, part in (("train7.jsonl", train), ("train7-val.jsonl", val)):
        (DATA / name).write_text("".join(json.dumps(scenes.render(s, audio_history=HISTORY)) + "\n" for s in part))
        print(f"{name}: {len(part)} scenes, {sum(len(s['turns']) for s in part)} turns")
    (DATA / "round7-heldout.jsonl").write_text("".join(json.dumps({"id": i}) + "\n" for i in sorted(held_ids)))
    kinds = {}
    for s in held_new:
        kinds[s["scenario"].split(":")[0]] = kinds.get(s["scenario"].split(":")[0], 0) + 1
    print(f"new in training: {len(train_new)} | rounds 4 and 6 again: {len(again)} | round 3 replay: {N_ROUND3} | "
          f"earlier replay: {N_EARLIER} | held-out new: {len(held_new)} {kinds}")


if __name__ == "__main__":
    main()
