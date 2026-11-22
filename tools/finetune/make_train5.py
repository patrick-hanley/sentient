"""Round 5 training mix: all the attachment-style scenes (round4-q and round4-r..u) plus a replay of earlier rounds.

  python tools/finetune/make_train5.py        -> data/train5.jsonl, data/train5-val.jsonl, data/round5-heldout.jsonl

Meant to continue from the ROUND 3 adapter, not round 4: round 4 was round 3 plus 44 of these scenes and only nudged the
behaviour (plan, 3f), so starting from it would train those 44 twice.
- New: 220 of the 250 attachment scenes train. Held out: the 6 of round 4 (round4-heldout.jsonl) and 6 from each new file,
  one of each kind first (24, listed in round5-heldout.jsonl).
- Replay: 110 round-3 scenes (cameras, I spy, always answer) and 170 from the pilot and round 2. 44% of the mix is new.
- The 64 scenes of train3-val.jsonl stay held out and nothing held out in rounds 1-2 is replayed: scores stay comparable.
- Half the scenes get a brain-shaped spoken history, as in rounds 3 and 4. Same output every run.
"""
import json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
PER_FILE_HELD, N_ROUND3, N_EARLIER, HISTORY = 6, 110, 170, 0.5
NEW_FILES = ["round4-r.jsonl", "round4-s.jsonl", "round4-t.jsonl", "round4-u.jsonl"]


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
    held4 = ids("round4-heldout.jsonl")
    rnd = random.Random(5)
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
    held_ids = {s["id"] for s in held_new} | held4
    train_new = [sc for sc in group("round4") if sc["id"] not in held_ids]
    r3 = [sc for sc in group("round3") if sc["id"] not in held_before]
    old = [sc for sc in group("pilot") + group("round2") if sc["id"] not in held_before]
    rnd.shuffle(r3)
    rnd.shuffle(old)
    train = train_new + r3[:N_ROUND3] + old[:N_EARLIER]
    rnd.shuffle(train)
    all_scenes = {sc["id"]: sc for v in by_file.values() for sc in v}
    val = [all_scenes[i] for i in sorted(ids("train3-val.jsonl"))] + [all_scenes[i] for i in sorted(held_ids)]
    assert not {s["id"] for s in train} & ({s["id"] for s in val} | held_before)
    for name, part in (("train5.jsonl", train), ("train5-val.jsonl", val)):
        (DATA / name).write_text("".join(json.dumps(scenes.render(s, audio_history=HISTORY)) + "\n" for s in part))
        print(f"{name}: {len(part)} scenes, {sum(len(s['turns']) for s in part)} turns")
    (DATA / "round5-heldout.jsonl").write_text("".join(json.dumps({"id": s["id"]}) + "\n" for s in sorted(held_new, key=lambda s: s["id"])))
    kinds = {}
    for s in held_new:
        kinds[s["scenario"].split(":")[0]] = kinds.get(s["scenario"].split(":")[0], 0) + 1
    print(f"new in training: {len(train_new)} | round 3 replay: {N_ROUND3} | earlier replay: {N_EARLIER} | "
          f"held-out new: {len(held_new)} {kinds} + {len(held4)} from round 4")


if __name__ == "__main__":
    main()
