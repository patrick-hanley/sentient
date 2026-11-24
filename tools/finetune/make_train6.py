"""Round 6 training mix: the 200 "warm first" scenes (round6-v..y) plus a replay of everything before.

  python tools/finetune/make_train6.py        -> data/train6.jsonl, data/train6-val.jsonl, data/round6-heldout.jsonl

Meant to continue from the ROUND 5 end-of-run adapter (`adapter-last` of adapter-round5.zip): round 5 keeps the attachment rules,
round 6 adds warmth on top (plan, 3h).
- New: 176 of the 200 round-6 scenes train. Held out: 6 from each file, one of each kind first (24, listed in round6-heldout.jsonl).
- Replay: 120 attachment scenes (round 4 files, never the 30 held out in round 5), 90 round-3 scenes (cameras, I spy, always
  answer) and 110 from the pilot and round 2. 35% of the mix is new.
- Validation: round 3's 64 held-out scenes + the 30 attachment scenes + the 24 new ones. Nothing held out before is replayed.
- Half the scenes get a brain-shaped spoken history, as in rounds 3 to 5. Same output every run.
"""
import json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
PER_FILE_HELD, N_ATTACH, N_ROUND3, N_EARLIER, HISTORY = 6, 120, 90, 110, 0.5
NEW_FILES = ["round6-v.jsonl", "round6-w.jsonl", "round6-x.jsonl", "round6-y.jsonl"]


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
    rnd = random.Random(6)
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
    train_new = [sc for sc in group("round6") if sc["id"] not in held_ids]
    attach = [sc for sc in group("round4") if sc["id"] not in held_attach]
    r3 = [sc for sc in group("round3") if sc["id"] not in held_before]
    old = [sc for sc in group("pilot") + group("round2") if sc["id"] not in held_before]
    for pool in (attach, r3, old):
        rnd.shuffle(pool)
    train = train_new + attach[:N_ATTACH] + r3[:N_ROUND3] + old[:N_EARLIER]
    rnd.shuffle(train)
    all_scenes = {sc["id"]: sc for v in by_file.values() for sc in v}
    val_ids = sorted(ids("train3-val.jsonl")) + sorted(held_attach) + sorted(held_ids)
    val = [all_scenes[i] for i in val_ids]
    assert not {s["id"] for s in train} & (set(val_ids) | held_before)
    for name, part in (("train6.jsonl", train), ("train6-val.jsonl", val)):
        (DATA / name).write_text("".join(json.dumps(scenes.render(s, audio_history=HISTORY)) + "\n" for s in part))
        print(f"{name}: {len(part)} scenes, {sum(len(s['turns']) for s in part)} turns")
    (DATA / "round6-heldout.jsonl").write_text("".join(json.dumps({"id": i}) + "\n" for i in sorted(held_ids)))
    kinds = {}
    for s in held_new:
        kinds[s["scenario"].split(":")[0]] = kinds.get(s["scenario"].split(":")[0], 0) + 1
    print(f"new in training: {len(train_new)} | attachment replay: {min(N_ATTACH, len(attach))} | round 3 replay: {N_ROUND3} | "
          f"earlier replay: {N_EARLIER} | held-out new: {len(held_new)} {kinds}")


if __name__ == "__main__":
    main()
