"""Round 8 training mix: the 120 round-8 scenes (what round 7 still got wrong when spoken to), the round 4, 6 and 7 scenes again,
and a replay of the rest, with the cameras OFF in a share of the scenes.

  python tools/finetune/make_train8.py        -> data/train8.jsonl, data/train8-val.jsonl, data/round8-heldout.jsonl
  python tools/finetune/make_train8.py 9      -> data/train9.jsonl, data/train9-val.jsonl: the same scenes after the Nov 27
                                                 correction ("a grown-up" unless the child named someone), for round 9

Meant to continue from the ROUND 7 adapter. Plan, 3j.
- New: 105 of the 120 round-8 scenes (a hurt that names no feeling inside cheerful talk, with its cheerful look-alike; promises
  and "only you"; "did you miss me" with no word about eyes; I spy by hints with the eyes off). Held out: 5 from each file (15).
- Again: the 176 round-7 scenes, 150 of round 6 and 150 of round 4 (never their held-out scenes).
- Replay: 90 round-3 scenes (cameras, I spy, always answer) and 90 from the pilot and round 2.
- Cameras off: the toys at home run with their cameras off, and rounds 4 to 7 were all written with "look when asked". 40% of the
  older training scenes that have no look, picture or I spy turn are rendered with the cameras-off prompt (same turns, same replies).
- Validation: round 3's 64 held-out scenes + the 30 attachment + the 24 round-6 + the 24 round-7 + the 15 new ones, as written.
- data/live-z.jsonl is in neither file: a test set only.
- Half the scenes get a brain-shaped spoken history, as in rounds 3 to 7. Same output every run.
"""
import json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
PER_FILE_HELD, N_ROUND7_6, N_ROUND4, N_ROUND3, N_EARLIER, HISTORY, OFF = 5, 150, 150, 90, 90, 0.5, 0.4
NEW_FILES = ["round8-a.jsonl", "round8-b.jsonl", "round8-c.jsonl"]


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
    held7 = ids("round7-heldout.jsonl")
    rnd = random.Random(8)
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
    train_new = [sc for sc in group("round8") if sc["id"] not in held_ids]
    r7 = [sc for sc in group("round7") if sc["id"] not in held7]
    r6 = [sc for sc in group("round6") if sc["id"] not in held6]
    r4 = [sc for sc in group("round4") if sc["id"] not in held_attach]
    r3 = [sc for sc in group("round3") if sc["id"] not in held_before]
    old = [sc for sc in group("pilot") + group("round2") if sc["id"] not in held_before]
    for pool in (r6, r4, r3, old):
        rnd.shuffle(pool)
    older = r7 + r6[:N_ROUND7_6] + r4[:N_ROUND4] + r3[:N_ROUND3] + old[:N_EARLIER]
    plain = lambda sc: sc.get("cameras", "request") == "request" and not any(
        t.get(k) for t in sc["turns"] for k in ("look", "seen", "scene", "toy", "guessed", "secret", "picture"))
    n_off = 0
    for k, sc in enumerate(older):                   # the same scene with the eyes off (a copy: the files stay as written)
        if plain(sc) and rnd.random() < OFF:
            older[k] = dict(sc, cameras="off")
            n_off += 1
    train = train_new + older
    rnd.shuffle(train)
    all_scenes = {sc["id"]: sc for v in by_file.values() for sc in v}
    val_ids = sorted(ids("train3-val.jsonl")) + sorted(held_attach) + sorted(held6) + sorted(held7) + sorted(held_ids)
    val = [all_scenes[i] for i in val_ids]
    assert not {s["id"] for s in train} & (set(val_ids) | held_before)
    assert not any(s["id"].startswith("z-") for s in train + val)
    tag = sys.argv[1] if len(sys.argv) > 1 else "8"     # "9": the same mix after the scenes were corrected (round 9)
    for name, part in ((f"train{tag}.jsonl", train), (f"train{tag}-val.jsonl", val)):
        (DATA / name).write_text("".join(json.dumps(scenes.render(s, audio_history=HISTORY)) + "\n" for s in part))
        print(f"{name}: {len(part)} scenes, {sum(len(s['turns']) for s in part)} turns")
    (DATA / "round8-heldout.jsonl").write_text("".join(json.dumps({"id": i}) + "\n" for i in sorted(held_ids)))
    kinds = {}
    for s in held_new:
        kinds[s["scenario"].split(":")[0]] = kinds.get(s["scenario"].split(":")[0], 0) + 1
    print(f"new in training: {len(train_new)} | rounds 7, 6, 4 again: {len(r7)} + {N_ROUND7_6} + {N_ROUND4} | round 3 replay: {N_ROUND3} | "
          f"earlier replay: {N_EARLIER} | older scenes rendered with cameras off: {n_off} | held-out new: {len(held_new)} {kinds}")


if __name__ == "__main__":
    main()
