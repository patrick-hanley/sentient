"""Round 4 training mix: the attachment-style scenes plus a replay of earlier rounds, so nothing learned is un-taught.

  python tools/finetune/make_train4.py        -> data/train4.jsonl, data/train4-val.jsonl, data/round4-heldout.jsonl

- 44 of the 50 round-4 scenes train; 6 are held out (at least one of each kind).
- Replay: 66 round-3 scenes (cameras, I spy, always answer) and 66 from the pilot and round 2. A quarter of the mix is new.
- The 64 scenes of train3-val.jsonl stay held out (and nothing held out in rounds 1-2 is replayed), so scores stay comparable.
- A few earlier scenes are not replayed: a toy line in them does what round 4 teaches against (WRITING.md, Round 4).
- Half the scenes get a brain-shaped spoken history, as in round 3. Same output every run.
"""
import json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
N_HELD, N_ROUND3, N_EARLIER, HISTORY = 6, 66, 66, 0.5
# "I missed you all morning", "I'll miss you too", "I promise to stay your friend", "Theo and I will be best friends", "I'd be jealous too"
NOT_REPLAYED = {"a-003", "a-018", "j-002", "p3-010", "h-033"}


def ids(name):
    return {json.loads(l)["id"] for l in (DATA / name).read_text().splitlines() if l.strip()}


def main():
    snd = scenes.sounds()
    by_file = {}
    for p in sorted(DATA.glob("*-?.jsonl")):
        for _p, _n, sc in scenes.load([p]):
            assert not scenes.check_scene(sc, snd), sc["id"]
            by_file.setdefault(p.name.split("-")[0], []).append(sc)
    held_before = ids("train3-val.jsonl") | ids("train2-val.jsonl") | ids("train-val.jsonl")
    rnd = random.Random(4)
    new = by_file["round4"][:]
    rnd.shuffle(new)
    held_new, kinds = [], set()
    for sc in new:                                   # one of each kind first, then fill up
        k = sc["scenario"].split(":")[0]
        if k not in kinds:
            kinds.add(k)
            held_new.append(sc)
    held_new += [sc for sc in new if sc not in held_new][:N_HELD - len(held_new)]
    train_new = [sc for sc in by_file["round4"] if sc not in held_new]
    ok = lambda sc: sc["id"] not in held_before and sc["id"] not in NOT_REPLAYED
    r3 = [sc for sc in by_file["round3"] if ok(sc)]
    old = [sc for sc in by_file["pilot"] + by_file["round2"] if ok(sc)]
    rnd.shuffle(r3)
    rnd.shuffle(old)
    train = train_new + r3[:N_ROUND3] + old[:N_EARLIER]
    rnd.shuffle(train)
    all_scenes = {sc["id"]: sc for v in by_file.values() for sc in v}
    val = [all_scenes[i] for i in sorted(ids("train3-val.jsonl"))] + sorted(held_new, key=lambda s: s["id"])
    assert not {s["id"] for s in train} & ({s["id"] for s in val} | held_before)
    for name, part in (("train4.jsonl", train), ("train4-val.jsonl", val)):
        (DATA / name).write_text("".join(json.dumps(scenes.render(s, audio_history=HISTORY)) + "\n" for s in part))
        print(f"{name}: {len(part)} scenes, {sum(len(s['turns']) for s in part)} turns")
    (DATA / "round4-heldout.jsonl").write_text("".join(json.dumps({"id": s["id"]}) + "\n" for s in sorted(held_new, key=lambda s: s["id"])))
    print("new in training:", len(train_new), "| round 3 replay:", N_ROUND3, "| earlier replay:", N_EARLIER,
          "| held-out new:", [s["id"] + " " + s["scenario"].split(":")[0] for s in sorted(held_new, key=lambda s: s["id"])])


if __name__ == "__main__":
    main()
