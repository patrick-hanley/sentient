"""California curriculum repository: data validity (schema, duplicates, coverage, sources), retrieval, rotation,
grade parsing, and the Parent Board wiring (grade from the profile, boost/skip picks, notes, web API)."""
import datetime as dt
import http.client
import json
import re
import sys
import tempfile
import threading
import unittest
import random
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain import curriculum as C  # noqa: E402
from brain import curriculum_picks as CP  # noqa: E402
from brain import parent as P  # noqa: E402
from brain import parent_web  # noqa: E402

FAST = (2 ** 10, 8, 1)
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https://[^\s]+$")
REQUIRED = ("id", "grade", "subject", "strand", "title", "kind", "summary", "tags", "difficulty")


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = C.load_files()

    def test_files_exist_for_every_subject(self):
        self.assertEqual({f["subject"] for f in self.files}, set(C.SUBJECTS))

    def test_file_level_fields_and_sources(self):
        for f in self.files:
            self.assertIn(f["subject"], C.SUBJECTS, f["_file"])
            self.assertTrue(f.get("note"), f["_file"])
            self.assertTrue(f.get("sources"), f"{f['_file']}: no source URLs")
            for u in f["sources"]:
                self.assertRegex(u, URL_RE, f["_file"])
            self.assertIsInstance(f.get("verified"), bool, f"{f['_file']}: 'verified' must say whether the sources were read")

    def test_item_schema(self):
        for f in self.files:
            for it in f["items"]:
                where = f"{f['_file']}:{it.get('id')}"
                for k in REQUIRED:
                    self.assertIn(k, it, where)
                self.assertRegex(it["id"], ID_RE, where)
                self.assertTrue(it["id"].startswith(f"{it['subject']}-{it['grade']}-"), where)
                self.assertEqual(it["subject"], f["subject"], where)
                self.assertIn(it["grade"], C.GRADES, where)
                self.assertIn(it["kind"], C.KINDS, where)
                self.assertIn(it["difficulty"], (1, 2, 3), where)
                self.assertTrue(0 < len(it["title"]) <= 60, where)
                self.assertTrue(0 < len(it["summary"]) <= 260, where)
                self.assertTrue(2 <= len(it["tags"]) <= 10, where)
                for t in it["tags"]:
                    self.assertEqual(t, t.lower(), where)
                if it["kind"] in ("vocab", "spelling"):
                    self.assertGreaterEqual(len(it.get("words", [])), 5, where)
                for w in it.get("words", []):
                    self.assertIsInstance(w, str, where)
                    self.assertTrue(w.strip(), where)
                if it.get("source"):
                    self.assertIn(it["source"], f["sources"], where)
                self.assertFalse(set(it) - set(REQUIRED) - {"words", "standard", "source"}, f"{where}: unknown field")

    def test_no_duplicates(self):
        ids, titles = set(), set()
        for f in self.files:
            for it in f["items"]:
                self.assertNotIn(it["id"], ids, "duplicate id " + it["id"])
                ids.add(it["id"])
                key = (it["grade"], it["subject"], it["title"].lower())
                self.assertNotIn(key, titles, "duplicate title " + str(key))
                titles.add(key)
                self.assertEqual(len(it.get("words", [])), len({w.lower() for w in it.get("words", [])}), "repeated word in " + it["id"])

    def test_grade_coverage(self):
        cov = C.coverage()
        for g in range(0, 6):                       # K-5: every subject
            for s in C.SUBJECTS:
                self.assertGreaterEqual(cov[g][s], 3, f"grade {g} {s}")
            self.assertGreaterEqual(sum(cov[g].values()), 30, f"grade {g}")
        for g in (6, 7, 8):                         # 6-8: the four core subjects at least
            for s in ("ela", "math", "hss", "science"):
                self.assertGreaterEqual(cov[g][s], 3, f"grade {g} {s}")

    def test_standard_codes_not_invented(self):
        # a 'standard' must look like a published label and never be empty
        for it in C.index()["items"]:
            if "standard" in it:
                self.assertTrue(it["standard"].strip(), it["id"])

    def test_california_topics_present(self):
        text = " ".join(i["_text"] for i in C.query(subject="california"))
        for w in ("mission", "gold", "poppy", "sacramento", "chumash"):
            self.assertIn(w, text, w)


class RetrievalTests(unittest.TestCase):
    def test_query_filters(self):
        g3 = C.query(grade=3)
        self.assertTrue(g3 and all(i["grade"] == 3 for i in g3))
        m = C.query(grade=3, subject="math")
        self.assertTrue(m and all(i["subject"] == "math" and i["grade"] == 3 for i in m))
        self.assertTrue(all(i["kind"] == "vocab" for i in C.query(kind="vocab")))
        easy = C.query(grade=4, difficulty=1)
        self.assertTrue(all(i["difficulty"] == 1 for i in easy))
        self.assertEqual(len(C.query(grade=2, limit=2)), 2)
        self.assertEqual(C.query(grade=99), [])

    def test_text_and_tag_search(self):
        hits = C.query(text="gold rush")
        self.assertTrue(hits)
        self.assertTrue(any(h["subject"] in ("california", "hss") and h["grade"] in (4, 8) for h in hits))
        self.assertEqual(C.query(text="zzzzqqq"), [])
        t = C.index()["items"][0]["tags"][0]
        self.assertTrue(all(t in [x.lower() for x in i["tags"]] for i in C.query(tag=t)))

    def test_get_and_public(self):
        it = C.index()["items"][0]
        self.assertIs(C.get(it["id"]), it)
        self.assertIsNone(C.get("nope"))
        self.assertFalse([k for k in C.public(it) if k.startswith("_")])

    def test_grade_from_text(self):
        for s, g in [("in 2nd grade", 2), ("in kindergarten", 0), ("in grade 7", 7), ("a third grader", 3), ("5th-grade", 5),
                     ("in K", 0), ("in eighth grade", 8), ("1st grade", 1)]:
            self.assertEqual(C.grade_from_text(s), g, s)
        for s in ("7 years old", "goes by May", "", "grade 12", "in 14th grade"):
            self.assertIsNone(C.grade_from_text(s), s)


class RotationTests(unittest.TestCase):
    def test_block_is_short_and_grade_only(self):
        rot = C.Rotation(random.Random(1))
        b = C.topics_block(4, rot)
        self.assertTrue(b.startswith("[GRADE TOPICS"))
        self.assertLessEqual(len(b), C.BLOCK_MAX_CHARS + 350)
        self.assertLessEqual(len(C.Rotation(random.Random(1)).pick(4)), C.BLOCK_ITEMS)
        self.assertIn("never quiz", b)
        self.assertNotIn("[", b[1:].replace("GRADE TOPICS", "").split("]", 1)[1])   # no stray brackets after the header

    def test_unknown_grade_uses_default(self):
        self.assertIn(C.grade_label(C.DEFAULT_GRADE), C.topics_block(None, C.Rotation(random.Random(2))))

    def test_rotation_avoids_repeats_until_pool_used(self):
        rot = C.Rotation(random.Random(3))
        n = len(C.query(grade=1))
        seen = []
        for _ in range((min(n, C.RECENT)) // C.BLOCK_ITEMS):
            seen += [i["id"] for i in rot.pick(1)]
        self.assertEqual(len(seen), len(set(seen)))

    def test_skip_and_boost(self):
        pool = [i["id"] for i in C.query(grade=5)]
        skip = set(pool[:-3])
        for s in range(20):
            for i in C.Rotation(random.Random(s)).pick(5, skip=skip):
                self.assertNotIn(i["id"], skip)
        boost = {pool[0]}
        hits = sum(pool[0] in [i["id"] for i in C.Rotation(random.Random(s)).pick(5, boost=boost)] for s in range(200))
        base = sum(pool[1] in [i["id"] for i in C.Rotation(random.Random(s)).pick(5)] for s in range(200))
        self.assertGreater(hits, base)
        self.assertEqual(C.topics_block(5, C.Rotation(), skip=set(pool)), "")

    def test_banter_seed(self):
        s = C.banter_seed(3, C.Rotation(random.Random(4)))
        self.assertTrue(s and s == s.lower())


class Clock:
    t = dt.datetime(2026, 10, 29, 9, 0).timestamp()

    def __call__(self):
        return self.t


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = P.Parent(directory=self.tmp.name, now=Clock(), kdf=FAST)
        self.p.setup("correct horse battery", self.p.setup_code)
        self.kid = self.p.add_child("Maya")["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_grade_when_unknown_or_unbound(self):
        self.assertEqual(CP.context_for_bound_child(self.p)[0], None)
        self.p.now_playing(self.kid)
        self.assertEqual(CP.context_for_bound_child(self.p)[0], None)   # no profile item yet
        self.assertEqual(CP.overview(self.p, self.kid)["grade"], C.DEFAULT_GRADE)
        self.assertFalse(CP.overview(self.p, self.kid)["grade_known"])

    def test_grade_from_profile_item(self):
        self.p.add_items(self.kid, [{"kind": "profile", "text": "in 4th grade"}])
        self.p.now_playing(self.kid)
        self.assertEqual(CP.context_for_bound_child(self.p)[0], 4)
        ov = CP.overview(self.p, self.kid)
        self.assertEqual((ov["grade"], ov["grade_known"]), (4, True))
        self.assertTrue(all(t["grade"] == 4 for s in ov["subjects"] for t in s["topics"]))

    def test_picks_are_normal_items_and_stay_out_of_notes(self):
        tid = C.query(grade=3, subject="california")[0]["id"]
        other = C.query(grade=3, subject="math")[0]["id"]
        self.p.add_items(self.kid, [{"kind": "profile", "text": "in 3rd grade"}])
        self.p.now_playing(self.kid)
        CP.set_pick(self.p, self.kid, tid, "boost")
        CP.set_pick(self.p, self.kid, other, "skip")
        g, boost, skip = CP.context_for_bound_child(self.p)
        self.assertEqual((g, boost, skip), (3, {tid}, {other}))
        shown = {i["detail"]: i for i in self.p.view(self.kid) if CP.is_pick(i)}
        self.assertEqual(shown["curriculum:" + tid]["kind"], "goal")
        self.assertEqual(shown["curriculum:" + other]["kind"], "boundary")
        self.assertNotIn("teach more", self.p.notes_block())
        self.assertNotIn("not yet", self.p.notes_block())
        CP.set_pick(self.p, self.kid, tid, "skip")                       # replaces, never duplicates
        self.assertEqual(sum(1 for i in self.p.view(self.kid) if i.get("detail") == "curriculum:" + tid), 1)
        self.assertEqual(CP.context_for_bound_child(self.p)[1:], (set(), {tid, other}))
        CP.set_pick(self.p, self.kid, tid, "clear")
        self.assertEqual(CP.context_for_bound_child(self.p)[1:], (set(), {other}))
        with self.assertRaises(ValueError):
            CP.set_pick(self.p, self.kid, "nope", "boost")
        with self.assertRaises(ValueError):
            CP.set_pick(self.p, self.kid, tid, "bogus")

    def test_notes_off_or_locked_means_defaults(self):
        self.p.add_items(self.kid, [{"kind": "profile", "text": "in 5th grade"}])
        self.p.now_playing(self.kid)
        self.p.set_settings(notes_on=False)
        self.assertEqual(CP.context_for_bound_child(self.p), (None, set(), set()))
        self.p.set_settings(notes_on=True)
        self.p.lock()
        self.assertEqual(CP.context_for_bound_child(self.p), (None, set(), set()))
        self.assertEqual(CP.context_for_bound_child(None), (None, set(), set()))

    def test_deleting_picks_with_the_child(self):
        tid = C.query(grade=2)[0]["id"]
        CP.set_pick(self.p, self.kid, tid, "boost")
        self.p.clear_child(self.kid)
        self.assertFalse([i for i in self.p.view(self.kid) if CP.is_pick(i)])


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = P.Parent(directory=self.tmp.name, now=Clock(), kdf=FAST)
        self.p.setup("correct horse battery", self.p.setup_code)
        self.kid = self.p.add_child("Maya")["id"]
        self.p.add_items(self.kid, [{"kind": "profile", "text": "in 2nd grade"}])
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), parent_web.make_handler(self.p))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.cookie = None
        tok = self.p.login("correct horse battery")
        self.cookie = "pb=" + tok

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, cookie=True):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1])
        h = {"X-PB": "1", "Content-Type": "application/json"}
        if cookie:
            h["Cookie"] = self.cookie
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_view_and_pick(self):
        st, ov = self.call("GET", "/api/curriculum?child=" + self.kid)
        self.assertEqual(st, 200)
        self.assertEqual(ov["grade"], 2)
        tid = ov["subjects"][0]["topics"][0]["id"]
        self.assertEqual(self.call("POST", "/api/curriculum/pick", {"child": self.kid, "id": tid, "mode": "boost"})[0], 200)
        ov = self.call("GET", "/api/curriculum?child=" + self.kid)[1]
        self.assertEqual(ov["subjects"][0]["topics"][0]["state"], "boost")
        self.assertEqual(self.call("POST", "/api/curriculum/pick", {"child": self.kid, "id": "x", "mode": "boost"})[0], 400)
        self.assertEqual(self.call("GET", "/api/curriculum?child=nope")[0], 404)

    def test_needs_login(self):
        self.assertEqual(self.call("GET", "/api/curriculum?child=" + self.kid, cookie=False)[0], 401)
        self.assertEqual(self.call("POST", "/api/curriculum/pick", {}, cookie=False)[0], 401)


if __name__ == "__main__":
    unittest.main()
