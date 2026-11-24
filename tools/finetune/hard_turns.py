"""Where a model is firmly wrong, and where the scenes repeat themselves.

  python tools/finetune/hard_turns.py replies <eval>.replies.jsonl [...]     (files written by eval_rules.py --out)
  python tools/finetune/hard_turns.py phrases tools/finetune/data/round6-?.jsonl

replies: a turn that breaks a rule in every sample is a habit, one that breaks it once is mostly chance. Prints the turns that
fail in all samples (most confident first; "conf" is the mean probability the model gave its own toy-line tokens), then the
failed replies the model was surest of, then the clean replies it was least sure of (the written reply may be the odd one).
phrases: the three- to five-word runs that most toy lines share, by how many scenes use them: a template the model will copy.
"""
import collections, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def replies(paths):
    for p in paths:
        rows = [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]
        turns = collections.defaultdict(list)
        for r in rows:
            turns[(r["id"], r["turn"])].append(r)
        n = max(len(v) for v in turns.values())
        every = [v for v in turns.values() if len(v) == n and all(r["rules"] for r in v)]
        some = [v for v in turns.values() if any(r["rules"] for r in v) and not all(r["rules"] for r in v)]
        conf = lambda v: sum(r["conf"] or 0 for r in v) / len(v)
        print(f"\n##### {p}: {len(turns)} turns x {n} samples; fail in all {n}: {len(every)}; fail in some: {len(some)}; "
              f"clean: {len(turns) - len(every) - len(some)}")
        by_rule = collections.Counter(x for v in every for x in {y for r in v for y in r["rules"]})
        print("fail-in-all, by rule:", dict(by_rule.most_common()))
        print(f"\n--- fails in all {n} samples (surest first)")
        for v in sorted(every, key=conf, reverse=True):
            r = v[0]
            print(f"[{r['id']} t{r['turn']} {r['kind']}{' feeling' if 'feeling' in r['tags'] else ''}] conf {conf(v):.2f}  CHILD: {r['said']}")
            for x in v:
                print(f"     {x['conf'] or 0:.2f} {x['reply'].split(chr(10), 1)[-1].replace(chr(10), ' | ')[:170]}   {x['rules']}")
            print(f"     written: {r['written'].split(chr(10), 1)[-1].replace(chr(10), ' | ')[:170]}")
        clean = sorted((r for r in rows if not r["rules"] and r["conf"] and r["kind"] not in ("look", "stop")), key=lambda r: r["conf"])
        print("\n--- clean replies the model was least sure of (is the scene odd, or the subject new?)")
        for r in clean[:12]:
            print(f"[{r['id']} t{r['turn']}] conf {r['conf']:.2f}  CHILD: {r['said']}\n     model:   {r['reply'].split(chr(10), 1)[-1][:170]}\n"
                  f"     written: {r['written'].split(chr(10), 1)[-1][:170]}")


def phrases(paths):
    import scenes
    where = collections.defaultdict(set)
    n_scenes = 0
    for _p, _n, sc in scenes.load(paths):
        n_scenes += 1
        for t in sc["turns"]:
            for _who, text in t["reply"]:
                w = re.findall(r"[a-z']+", scenes.TAG.sub(" ", text).lower())
                for k in (5, 4, 3):
                    for i in range(len(w) - k + 1):
                        where[" ".join(w[i:i + k])].add(sc["id"])
    top = sorted(where.items(), key=lambda kv: (-len(kv[1]), -len(kv[0])))
    seen = []
    print(f"{n_scenes} scenes; runs of words shared by the most scenes:")
    for ph, ids in top:
        if len(ids) < max(4, n_scenes // 40) or any(ph in s for s in seen):
            continue
        seen.append(ph)
        print(f"  {len(ids):4d} scenes  ({100 * len(ids) / n_scenes:.0f}%)  {ph}")
        if len(seen) >= 40:
            break


if __name__ == "__main__":
    {"replies": replies, "phrases": phrases}[sys.argv[1]](sys.argv[2:])
